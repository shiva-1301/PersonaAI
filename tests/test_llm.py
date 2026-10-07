import pytest

from core import config, llm


@pytest.fixture
def models(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_MODEL", "g-main")
    monkeypatch.setattr(config, "GEMINI_FALLBACK_MODEL", "g-lite")
    monkeypatch.setattr(config, "OLLAMA_MODEL", "local")
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)


def fake_providers(monkeypatch, failing: set[str], calls: list):
    def make(provider):
        def fn(model, prompt, system, json_mode, temperature):
            calls.append(model)
            if model in failing:
                raise RuntimeError(f"{model} unavailable")
            return f"reply from {provider}/{model}"
        return fn

    monkeypatch.setattr(llm, "_PROVIDERS", {"gemini": make("gemini"), "ollama": make("ollama")})


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
