"""One interface for Claude (online, primary), Gemini (online) and Ollama (offline).

Usage:
    from core.llm import generate
    reply = generate("Explain photosynthesis in one line.")
    data = generate("Return a JSON list of topics ...", json_mode=True)

If the configured model fails (overloaded, rate limit, timeout, no internet), the next
provider is tried automatically: Claude -> Gemini -> lighter Gemini -> Ollama.
Every provider has a short timeout and at most one retry, so one failing provider
can't hold up the others.
"""

import logging
import re
import time

from core import config

log = logging.getLogger(__name__)

# Seconds to wait for one request. Ollama runs locally and is much slower on CPU.
TIMEOUT_S = {"claude": 45, "gemini": 30, "ollama": 120}
CLAUDE_MAX_TOKENS = 16000
OLLAMA_NUM_CTX = 8192


class LLMError(RuntimeError):
    """Raised when no provider could produce a reply (or a provider can't be used)."""


_claude_client = None
_gemini_client = None


def _claude_generate(
    model: str, prompt: str, system: str | None, json_mode: bool, temperature: float,
    schema: dict | None = None,
) -> str:
    """`temperature` is deliberately not sent: the Messages API rejects it."""
    global _claude_client
    import anthropic

    if not config.ANTHROPIC_API_KEY:
        raise LLMError("ANTHROPIC_API_KEY is not set.")
    if _claude_client is None:
        # Retries are handled here (_with_retries), not by the SDK.
        _claude_client = anthropic.Anthropic(
            api_key=config.ANTHROPIC_API_KEY, timeout=TIMEOUT_S["claude"], max_retries=0
        )

    kwargs = {}
    if system:
        kwargs["system"] = system
    if schema:
        # The API guarantees the reply is valid JSON matching the schema.
        kwargs["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
    elif json_mode:
        prompt += "\n\nReply with the JSON object only, without code fences or other text."
    response = _claude_client.messages.create(
        model=model,
        max_tokens=CLAUDE_MAX_TOKENS,
        # No reasoning pass: these are single-shot extraction/writing tasks, and thinking
        # would add latency the short timeout can't afford.
        thinking={"type": "between_tools"},
        messages=[{"role": "user", "content": prompt}],
        **kwargs,
    )
    if response.stop_reason in ("refusal", "max_tokens"):
        raise LLMError(f"Claude stopped early ({response.stop_reason}).")
    text = "".join(block.text for block in response.content if block.type == "text").strip()
    if json_mode:
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    if not text:
        raise LLMError("Claude returned an empty reply.")
    return text


def _gemini_generate(
    model: str, prompt: str, system: str | None, json_mode: bool, temperature: float,
    schema: dict | None = None,
) -> str:
    global _gemini_client
    from google import genai
    from google.genai import types

    if not config.GEMINI_API_KEY:
        raise LLMError("GEMINI_API_KEY is not set.")
    if _gemini_client is None:
        _gemini_client = genai.Client(
            api_key=config.GEMINI_API_KEY,
            http_options=types.HttpOptions(timeout=TIMEOUT_S["gemini"] * 1000),
        )

    gen_config = types.GenerateContentConfig(
        system_instruction=system,
        temperature=temperature,
        response_mime_type="application/json" if json_mode else None,
    )
    response = _gemini_client.models.generate_content(
        model=model, contents=prompt, config=gen_config
    )
    if not response.text:
        raise LLMError("Gemini returned an empty reply.")
    return response.text


def _ollama_generate(
    model: str, prompt: str, system: str | None, json_mode: bool, temperature: float,
    schema: dict | None = None,
) -> str:
    import ollama

    client = ollama.Client(host=config.OLLAMA_HOST, timeout=TIMEOUT_S["ollama"])
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    response = client.chat(
        model=model,
        messages=messages,
        format="json" if json_mode else "",
        # Ollama's default context (2-4k tokens) silently truncates long prompts like
        # quiz generation with many excerpts.
        options={"temperature": temperature, "num_ctx": OLLAMA_NUM_CTX},
    )
    return response["message"]["content"]


_PROVIDERS = {"claude": _claude_generate, "gemini": _gemini_generate, "ollama": _ollama_generate}

# model -> time.time() until which it is skipped because its quota ran out.
# The Gemini free tier allows only ~20 requests/day for some models; without this,
# every call would first waste attempts on the exhausted model.
_cooldown_until: dict[str, float] = {}
# model -> time.time() until which it is skipped because it just timed out, so a hung
# provider costs one timeout, not one per request.
_slow_until: dict[str, float] = {}
SLOW_COOLDOWN_S = 60
# A 429 without a retry delay is treated as a long (daily) limit.
DEFAULT_COOLDOWN_S = 300
# A rate limit asking for a wait up to this long is waited out once on the same model.
MAX_RATE_LIMIT_WAIT_S = 10
MAX_RATE_LIMIT_WAITS = 1


def _status(exc: Exception) -> int | None:
    """HTTP status of a provider error (Anthropic/Ollama: status_code; Gemini: code)."""
    for attr in ("status_code", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    return None


def _describe(exc: Exception) -> str:
    """'RateLimitError HTTP 429: <message>' - the real status and message, for the log."""
    message = getattr(exc, "message", None) or getattr(exc, "error", None) or str(exc)
    status = _status(exc)
    head = f"{type(exc).__name__} HTTP {status}" if status else type(exc).__name__
    return f"{head}: {str(message)[:300]}"


def _is_timeout(exc: Exception) -> bool:
    return isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower()


def _quota_cooldown(exc: Exception) -> float | None:
    """Seconds to skip a model for, if exc is a quota/rate-limit error (HTTP 429)."""
    text = str(exc)
    if _status(exc) != 429 and "RESOURCE_EXHAUSTED" not in text:
        return None
    match = re.search(r"retryDelay'?:\s*'(\d+)s'", text)
    if match:
        return float(match.group(1))
    try:
        return float(exc.response.headers["retry-after"])  # Anthropic
    except (AttributeError, KeyError, TypeError, ValueError):
        return DEFAULT_COOLDOWN_S


def _candidates(primary: str, fallback: bool) -> list[tuple[str, str]]:
    """(provider, model) pairs to try in order.

    Gemini's free tier often returns 503 "high demand" for one model while a lighter
    model still answers, so the lighter Gemini model is tried before slow local Ollama.
    """
    claude = [("claude", config.ANTHROPIC_MODEL)]
    gemini = [("gemini", config.GEMINI_MODEL)]
    if config.GEMINI_FALLBACK_MODEL and config.GEMINI_FALLBACK_MODEL != config.GEMINI_MODEL:
        gemini.append(("gemini", config.GEMINI_FALLBACK_MODEL))
    ollama = [("ollama", config.OLLAMA_MODEL)]
    if not fallback:
        return {"claude": claude, "gemini": gemini, "ollama": ollama}[primary][:1]
    return {"claude": claude + gemini + ollama, "gemini": gemini + ollama,
            "ollama": ollama + gemini}[primary]


def _with_retries(label: str, fn, *args):
    """Call fn with at most one retry, logging every failure.

    - Timeouts are not retried (a second try would double the wait).
    - A short rate limit (a few seconds) is waited out once on the same model; a long
      one (daily quota) is raised so the caller can skip the model.
    - Other errors (overload, 5xx, network) are retried once after 1 s."""
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn(*args)
        except LLMError as exc:
            log.warning("%s failed (attempt %d): %s", label, attempt, exc)
            raise
        except Exception as exc:
            log.warning("%s failed (attempt %d): %s", label, attempt, _describe(exc))
            if attempt > 1 or _is_timeout(exc):
                raise
            cooldown = _quota_cooldown(exc)
            if cooldown is not None:
                if cooldown > MAX_RATE_LIMIT_WAIT_S or MAX_RATE_LIMIT_WAITS < 1:
                    raise
                log.info("Rate limited; waiting %.0fs and retrying", cooldown + 1)
                time.sleep(cooldown + 1)
            else:
                time.sleep(1)


def generate(
    prompt: str,
    system: str | None = None,
    json_mode: bool = False,
    temperature: float = 0.2,
    provider: str | None = None,
    fallback: bool | None = None,
    schema: dict | None = None,
) -> str:
    """Send a prompt to the configured LLM and return its text reply.

    With fallback (default: config.LLM_FALLBACK), if the chosen model fails the next one is
    tried (Claude -> Gemini -> lighter Gemini -> Ollama). `schema` is a JSON schema the reply
    must follow; Claude enforces it, the other providers just get JSON mode.
    """
    return generate_with_model(prompt, system, json_mode, temperature, provider, fallback, schema)[0]


def generate_with_model(
    prompt: str,
    system: str | None = None,
    json_mode: bool = False,
    temperature: float = 0.2,
    provider: str | None = None,
    fallback: bool | None = None,
    schema: dict | None = None,
) -> tuple[str, str]:
    """Like generate(), but also returns which model replied, e.g. "claude / claude-sonnet-5-5"."""
    primary = (provider or config.LLM_PROVIDER).lower()
    if primary not in _PROVIDERS:
        raise LLMError(f"Unknown LLM provider: {primary!r}. Use 'claude', 'gemini' or 'ollama'.")
    if schema:
        json_mode = True

    if fallback is None:
        fallback = config.LLM_FALLBACK
    candidates = _candidates(primary, fallback)
    errors = []
    for i, (name, model) in enumerate(candidates):
        wait = _cooldown_until.get(model, 0) - time.time()
        if wait > 0:
            errors.append(f"{name}/{model}: quota exhausted, retry in {wait / 60:.0f} min")
            continue
        # A recently timed-out model is skipped, unless it is the last one left to try.
        if _slow_until.get(model, 0) > time.time() and i < len(candidates) - 1:
            errors.append(f"{name}/{model}: timed out recently, skipped")
            continue
        started = time.time()
        label = f"{name} / {model}"
        try:
            text = _with_retries(
                label, _PROVIDERS[name], model, prompt, system, json_mode, temperature, schema
            )
            log.info("Answered by %s in %.1fs", label, time.time() - started)
            return text, label
        except Exception as exc:
            cooldown = _quota_cooldown(exc)
            if cooldown is not None:
                _cooldown_until[model] = time.time() + cooldown
                log.warning("%s quota exhausted; skipping it for %.0fs", label, cooldown)
            elif _is_timeout(exc):
                _slow_until[model] = time.time() + SLOW_COOLDOWN_S
                log.warning("%s timed out; skipping it for %ss", label, SLOW_COOLDOWN_S)
            errors.append(f"{name}/{model}: {_describe(exc)}")
    raise LLMError("All LLM providers failed. " + " | ".join(errors))


def active_model(provider: str | None = None) -> str:
    """Human-readable name of the model a provider uses, for display in the UI."""
    name = (provider or config.LLM_PROVIDER).lower()
    model = {"claude": config.ANTHROPIC_MODEL, "gemini": config.GEMINI_MODEL}.get(name, config.OLLAMA_MODEL)
    return f"{name} / {model}"
