"""One interface for Gemini (online) and Ollama (offline).

Usage:
    from core.llm import generate
    reply = generate("Explain photosynthesis in one line.")
    data = generate("Return a JSON list of topics ...", json_mode=True)

If the configured Gemini model fails (overloaded, rate limit, no internet), it
falls back to a lighter Gemini model and then to Ollama automatically.
"""

import logging
import time

from core import config

log = logging.getLogger(__name__)

# Seconds to wait for one Gemini request (Ollama gets 3x: local models are slower on CPU).
REQUEST_TIMEOUT_S = 60


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
        options={"temperature": temperature},
    )
    return response["message"]["content"]


_PROVIDERS = {"gemini": _gemini_generate, "ollama": _ollama_generate}


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
    """Retry with exponential backoff (1s, 2s, ...) for transient errors like rate limits."""
    for i in range(attempts):
        try:
            return fn(*args)
        except LLMError:
            raise
        except Exception as exc:
            if i == attempts - 1:
                raise
            wait = 2**i
            log.warning("LLM call failed (%s); retrying in %ss", exc, wait)
            time.sleep(wait)


def generate(
    prompt: str,
    system: str | None = None,
    json_mode: bool = False,
    temperature: float = 0.2,
    provider: str | None = None,
    fallback: bool = True,
) -> str:
    """Send a prompt to the configured LLM and return its text reply.

    With fallback=True, if the chosen model fails the next candidate is tried
    (main Gemini model -> lighter Gemini model -> Ollama, or Ollama first in offline mode).
    """
    primary = (provider or config.LLM_PROVIDER).lower()
    if primary not in _PROVIDERS:
        raise LLMError(f"Unknown LLM provider: {primary!r}. Use 'gemini' or 'ollama'.")

    errors = []
    for name, model in _candidates(primary, fallback):
        try:
            return _with_retries(_PROVIDERS[name], model, prompt, system, json_mode, temperature)
        except Exception as exc:
            log.warning("%s / %s failed: %s", name, model, exc)
            errors.append(f"{name}/{model}: {exc}")
    raise LLMError("All LLM providers failed. " + " | ".join(errors))


def active_model(provider: str | None = None) -> str:
    """Human-readable name of the model a provider uses, for display in the UI."""
    name = (provider or config.LLM_PROVIDER).lower()
    model = config.GEMINI_MODEL if name == "gemini" else config.OLLAMA_MODEL
    return f"{name} / {model}"
