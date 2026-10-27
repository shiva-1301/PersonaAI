import pytest

from core import config, llm


@pytest.fixture
def models(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(config, "ANTHROPIC_MODEL", "c-main")
    monkeypatch.setattr(llm, "_cooldown_until", {})
    monkeypatch.setattr(llm, "_slow_until", {})
    monkeypatch.setattr(config, "GEMINI_MODEL", "g-main")
    monkeypatch.setattr(config, "GEMINI_FALLBACK_MODEL", "g-lite")
    monkeypatch.setattr(config, "OLLAMA_MODEL", "local")
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)


def fake_providers(monkeypatch, failing: set[str], calls: list):
    def make(provider):
        def fn(model, prompt, system, json_mode, temperature, schema=None):
            calls.append(model)
            if model in failing:
                raise RuntimeError(f"{model} unavailable")
            return f"reply from {provider}/{model}"
        return fn

    monkeypatch.setattr(llm, "_PROVIDERS", {p: make(p) for p in ("claude", "gemini", "ollama")})


def test_fallback_order_claude_first(models):
    assert llm._candidates("claude", True) == [
        ("claude", "c-main"), ("gemini", "g-main"), ("gemini", "g-lite"), ("ollama", "local"),
    ]


def test_failing_claude_falls_back_to_gemini(models, monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "claude")
    calls = []
    fake_providers(monkeypatch, {"c-main"}, calls)
    assert llm.generate("hi") == "reply from gemini/g-main"
    assert calls == ["c-main", "c-main", "g-main"]  # at most one retry per model


def test_fallback_order_gemini_first(models):
    assert llm._candidates("gemini", True) == [
        ("gemini", "g-main"), ("gemini", "g-lite"), ("ollama", "local"),
    ]


def test_no_fallback_uses_only_primary_model(models):
    assert llm._candidates("gemini", False) == [("gemini", "g-main")]
    assert llm._candidates("ollama", False) == [("ollama", "local")]


def test_overloaded_main_model_falls_back_to_lite(models, monkeypatch):
    calls = []
    fake_providers(monkeypatch, {"g-main"}, calls)
    assert llm.generate("hi") == "reply from gemini/g-lite"
    assert calls == ["g-main", "g-main", "g-lite"]  # one retry, then next model


def test_all_failing_raises_llm_error(models, monkeypatch):
    fake_providers(monkeypatch, {"g-main", "g-lite", "local"}, [])
    with pytest.raises(llm.LLMError, match="All LLM providers failed"):
        llm.generate("hi")


def test_unknown_provider_rejected(models):
    with pytest.raises(llm.LLMError, match="Unknown LLM provider"):
        llm.generate("hi", provider="gpt")


class QuotaError(Exception):
    code = 429


def test_quota_error_skips_model_for_retry_delay(models, monkeypatch):
    monkeypatch.setattr(llm, "_cooldown_until", {})
    calls = []

    def gemini(model, *a):
        calls.append(model)
        if model == "g-main":
            raise QuotaError("429 RESOURCE_EXHAUSTED {'retryDelay': '27190s'}")
        return "lite reply"

    monkeypatch.setattr(llm, "_PROVIDERS", {"gemini": gemini, "ollama": gemini})
    assert llm.generate("a") == "lite reply"
    assert llm.generate("b") == "lite reply"
    # Not retried, and skipped entirely on the second call.
    assert calls == ["g-main", "g-lite", "g-lite"]
    assert llm._cooldown_until["g-main"] - llm.time.time() > 27000


def test_overload_is_not_treated_as_quota():
    assert llm._quota_cooldown(RuntimeError("503 UNAVAILABLE high demand")) is None
    assert llm._quota_cooldown(QuotaError("429")) == llm.DEFAULT_COOLDOWN_S


def test_per_minute_rate_limit_is_waited_out_on_same_model(models, monkeypatch):
    monkeypatch.setattr(llm, "_cooldown_until", {})
    sleeps, calls = [], []
    monkeypatch.setattr(llm.time, "sleep", sleeps.append)

    def gemini(model, *a):
        calls.append(model)
        if len(calls) == 1:
            raise QuotaError("429 RESOURCE_EXHAUSTED PerMinute {'retryDelay': '6s'}")
        return f"reply from {model}"

    monkeypatch.setattr(llm, "_PROVIDERS", {"gemini": gemini, "ollama": gemini})
    assert llm.generate("a") == "reply from g-main"
    assert calls == ["g-main", "g-main"] and sleeps == [7]
    assert "g-main" not in llm._cooldown_until


def test_rate_limit_that_persists_falls_back(models, monkeypatch):
    monkeypatch.setattr(llm, "_cooldown_until", {})
    calls = []

    def gemini(model, *a):
        calls.append(model)
        if model == "g-main":
            raise QuotaError("429 {'retryDelay': '6s'}")
        return "lite"

    monkeypatch.setattr(llm, "_PROVIDERS", {"gemini": gemini, "ollama": gemini})
    assert llm.generate("a") == "lite"
    assert calls == ["g-main"] * (1 + llm.MAX_RATE_LIMIT_WAITS) + ["g-lite"]


class Timeout(Exception):
    pass


def test_timeout_is_not_retried_and_model_is_skipped_next_time(models, monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "claude")
    calls = []

    def provider(model, *a):
        calls.append(model)
        if model == "g-main":
            raise Timeout("Request timed out.")
        if model == "c-main":
            raise QuotaError("429 rate limited")  # no retry delay: treated as long
        return f"reply from {model}"

    monkeypatch.setattr(llm, "_PROVIDERS", {p: provider for p in ("claude", "gemini", "ollama")})
    assert llm.generate("a") == "reply from g-lite"
    assert llm.generate("b") == "reply from g-lite"
    # Each failing model was tried once; the timed-out one is skipped on the next call.
    assert calls == ["c-main", "g-main", "g-lite", "g-lite"]


def test_failure_log_has_status_code_and_message():
    class APIStatusError(Exception):
        status_code = 529
        message = "Overloaded"

    assert llm._describe(APIStatusError("x")) == "APIStatusError HTTP 529: Overloaded"


class _FakeAnthropic:
    """Stands in for anthropic.Anthropic(); records the request it receives."""

    def __init__(self, text):
        from types import SimpleNamespace as NS
        self.requests = []
        reply = NS(stop_reason="end_turn", content=[NS(type="text", text=text)])
        self.messages = NS(create=lambda **kw: self.requests.append(kw) or reply)


def test_claude_request_shape_with_fake_client(monkeypatch):
    fake = _FakeAnthropic('{"topics": ["Hive tables"]}')
    monkeypatch.setattr(llm, "_claude_client", fake)
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "test-key")
    schema = {"type": "object", "properties": {"topics": {"type": "array"}}}

    text = llm._claude_generate("claude-sonnet-5-5", "List topics", "Be brief", True, 0.7, schema)

    assert text == '{"topics": ["Hive tables"]}'
    [request] = fake.requests
    assert "temperature" not in request  # the API rejects it
    assert request["model"] == "claude-sonnet-5-5"
    assert request["system"] == "Be brief"
    assert request["output_config"] == {"format": {"type": "json_schema", "schema": schema}}
    assert request["messages"] == [{"role": "user", "content": "List topics"}]


def test_claude_without_key_fails_fast(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    with pytest.raises(llm.LLMError, match="ANTHROPIC_API_KEY"):
        llm._claude_generate("m", "p", None, False, 0.2)
