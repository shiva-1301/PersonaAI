"""One interface for Gemini (online) and Ollama (offline).

Usage:
    from core.llm import generate
    reply = generate("Explain photosynthesis in one line.")
    data = generate("Return a JSON list of topics ...", json_mode=True)

If the configured Gemini model fails (overloaded, rate limit, no internet), it
falls back to a lighter Gemini model and then to Ollama automatically.
"""

import logging
import re
import time

from core import config

log = logging.getLogger(__name__)

# Seconds to wait for one Gemini request (Ollama gets 3x: local models are slower on CPU).
REQUEST_TIMEOUT_S = 60
OLLAMA_NUM_CTX = 8192


class LLMError(RuntimeError):
    """Raised when no provider could produce a reply."""


_gemini_client = None


def _gemini_generate(
    model: str, prompt: str, system: str | None, json_mode: bool, temperature: float
) -> str:
    global _gemini_client
    from google import genai
    from google.genai import types

    if not config.GEMINI_API_KEY:
        raise LLMError("GEMINI_API_KEY is not set.")
    if _gemini_client is None:
        _gemini_client = genai.Client(
            api_key=config.GEMINI_API_KEY,
            http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_S * 1000),
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
    model: str, prompt: str, system: str | None, json_mode: bool, temperature: float
) -> str:
    import ollama

    client = ollama.Client(host=config.OLLAMA_HOST, timeout=REQUEST_TIMEOUT_S * 3)
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


_PROVIDERS = {"gemini": _gemini_generate, "ollama": _ollama_generate}

# model -> time.time() until which it is skipped because its quota ran out.
# The Gemini free tier allows only ~20 requests/day for some models; without this,
# every call would first waste attempts on the exhausted model.
_cooldown_until: dict[str, float] = {}
# A 429 without a retry delay is treated as a long (daily) limit.
DEFAULT_COOLDOWN_S = 300
# Per-minute rate limits (Flash-Lite free tier: 15 requests/minute) ask for a few
# seconds' wait; anything up to this is waited out rather than skipping the model.
MAX_RATE_LIMIT_WAIT_S = 60
MAX_RATE_LIMIT_WAITS = 3


def _quota_cooldown(exc: Exception) -> float | None:
    """Seconds to skip a model for, if exc is a quota/rate-limit error (HTTP 429)."""
    text = str(exc)
    if getattr(exc, "code", None) != 429 and "RESOURCE_EXHAUSTED" not in text:
        return None
    match = re.search(r"retryDelay'?:\s*'(\d+)s'", text)
    return float(match.group(1)) if match else DEFAULT_COOLDOWN_S


def _candidates(primary: str, fallback: bool) -> list[tuple[str, str]]:
    """(provider, model) pairs to try in order.

    Gemini's free tier often returns 503 "high demand" for one model while a lighter
    model still answers, so the lighter Gemini model is tried before slow local Ollama.
    """
    gemini = [("gemini", config.GEMINI_MODEL)]
    if config.GEMINI_FALLBACK_MODEL and config.GEMINI_FALLBACK_MODEL != config.GEMINI_MODEL:
        gemini.append(("gemini", config.GEMINI_FALLBACK_MODEL))
    ollama = [("ollama", config.OLLAMA_MODEL)]
    if not fallback:
        return (gemini if primary == "gemini" else ollama)[:1]
    return gemini + ollama if primary == "gemini" else ollama + gemini


def _with_retries(fn, *args, attempts: int = 2):
    """Retry with exponential backoff (1s, 2s, ...) for transient errors like overload.

    Rate limits (HTTP 429) depend on how long Google says to wait: a per-minute limit
    (retry in ~6s) is waited out on the same model, which is far faster than falling
    back to a local model; a daily quota (retry in hours) is raised so the caller can
    skip the model."""
    failures = rate_waits = 0
    while True:
        try:
            return fn(*args)
        except LLMError:
            raise
        except Exception as exc:
            cooldown = _quota_cooldown(exc)
            if cooldown is not None:
                if cooldown > MAX_RATE_LIMIT_WAIT_S or rate_waits >= MAX_RATE_LIMIT_WAITS:
                    raise
                rate_waits += 1
                log.info("Rate limited; waiting %.0fs and retrying", cooldown + 1)
                time.sleep(cooldown + 1)
                continue
            failures += 1
            if failures >= attempts:
                raise
            wait = 2 ** (failures - 1)
            log.warning("LLM call failed (%s); retrying in %ss", exc, wait)
            time.sleep(wait)


def generate(
    prompt: str,
    system: str | None = None,
    json_mode: bool = False,
    temperature: float = 0.2,
    provider: str | None = None,
    fallback: bool | None = None,
) -> str:
    """Send a prompt to the configured LLM and return its text reply.

    With fallback (default: config.LLM_FALLBACK), if the chosen model fails the next one is tried
    (main Gemini model -> lighter Gemini model -> Ollama, or Ollama first in offline mode).
    """
    return generate_with_model(prompt, system, json_mode, temperature, provider, fallback)[0]


def generate_with_model(
    prompt: str,
    system: str | None = None,
    json_mode: bool = False,
    temperature: float = 0.2,
    provider: str | None = None,
    fallback: bool | None = None,
) -> tuple[str, str]:
    """Like generate(), but also returns which model replied, e.g. "gemini / gemini-3.5-flash-lite"."""
    primary = (provider or config.LLM_PROVIDER).lower()
    if primary not in _PROVIDERS:
        raise LLMError(f"Unknown LLM provider: {primary!r}. Use 'gemini' or 'ollama'.")

    if fallback is None:
        fallback = config.LLM_FALLBACK
    errors = []
    for name, model in _candidates(primary, fallback):
        wait = _cooldown_until.get(model, 0) - time.time()
        if wait > 0:
            errors.append(f"{name}/{model}: quota exhausted, retry in {wait / 60:.0f} min")
            continue
        started = time.time()
        try:
            text = _with_retries(_PROVIDERS[name], model, prompt, system, json_mode, temperature)
            log.info("Answered by %s / %s in %.1fs", name, model, time.time() - started)
            return text, f"{name} / {model}"
        except Exception as exc:
            cooldown = _quota_cooldown(exc)
            if cooldown is not None:
                _cooldown_until[model] = time.time() + cooldown
                log.warning("%s / %s quota exhausted; skipping it for %.0fs", name, model, cooldown)
            else:
                log.warning("%s / %s failed: %s", name, model, str(exc)[:300])
            errors.append(f"{name}/{model}: {str(exc)[:300]}")
    raise LLMError("All LLM providers failed. " + " | ".join(errors))


def active_model(provider: str | None = None) -> str:
    """Human-readable name of the model a provider uses, for display in the UI."""
    name = (provider or config.LLM_PROVIDER).lower()
    model = config.GEMINI_MODEL if name == "gemini" else config.OLLAMA_MODEL
    return f"{name} / {model}"
