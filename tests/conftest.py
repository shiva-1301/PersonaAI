import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import config  # noqa: E402  (sets up the app log file handler)

# Keep test runs (fake models, temp files) out of the real data/personaai.log.
_core_log = logging.getLogger("core")
for _h in list(_core_log.handlers):
    if getattr(_h, "_personaai", False):
        _core_log.removeHandler(_h)


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_ocr(monkeypatch):
    """Tests never send pages to the real OCR (Claude); tests that need it fake it."""
    monkeypatch.setattr(config, "OCR_ENABLED", False)
