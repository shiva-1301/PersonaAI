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
