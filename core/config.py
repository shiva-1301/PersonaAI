"""Loads settings from .env (locally) or Streamlit secrets (on Streamlit Cloud)."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
CHROMA_DIR = DATA_DIR / "chroma"
DB_PATH = DATA_DIR / "personaai.db"

load_dotenv(ROOT_DIR / ".env")

# Hugging Face's "xet" downloader ships a DLL that Windows Smart App Control blocks;
# plain HTTP downloads work everywhere. Set before sentence-transformers is imported.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


def _get(key: str, default: str = "") -> str:
    """Read a setting from the environment first, then Streamlit secrets."""
    value = os.getenv(key)
    if value:
        return value.strip()
    try:
        import streamlit as st

        if key in st.secrets:
            return str(st.secrets[key]).strip()
    except Exception:
        # No secrets.toml, or not running under Streamlit.
        pass
    return default


LLM_PROVIDER = _get("LLM_PROVIDER", "claude").lower()
# CLAUDE_API_KEY is accepted as an older name for the same key.
ANTHROPIC_API_KEY = _get("ANTHROPIC_API_KEY") or _get("CLAUDE_API_KEY")
ANTHROPIC_MODEL = _get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
GEMINI_API_KEY = _get("GEMINI_API_KEY")
GEMINI_MODEL = _get("GEMINI_MODEL", "gemini-3.8-flash")
# Lighter model tried when the main one is overloaded (503) before falling back to Ollama.
GEMINI_FALLBACK_MODEL = _get("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")
# When a model fails, try the next one (Claude -> main Gemini -> lighter Gemini -> Ollama).
# The evaluation turns this off so every answer comes from the same model.
LLM_FALLBACK = _get("LLM_FALLBACK", "true").lower() not in ("false", "0", "no")
OLLAMA_MODEL = _get("OLLAMA_MODEL", "llama3.1:8b")
# Password of the "admin" account (class lists, cohorts, course notes). Empty = admin off.
ADMIN_PASSWORD = _get("ADMIN_PASSWORD")
OLLAMA_HOST = _get("OLLAMA_HOST", "http://localhost:11434")

LOG_PATH = DATA_DIR / "personaai.log"

for _dir in (DATA_DIR, UPLOADS_DIR, CHROMA_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

# App log (which model answered, fallbacks, quota errors). Guarded so Streamlit's
# module reloads don't attach a second handler.
_app_log = logging.getLogger("core")
if not any(getattr(h, "_personaai", False) for h in _app_log.handlers):
    _handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    _handler._personaai = True
    _app_log.addHandler(_handler)
    _app_log.setLevel(logging.INFO)
