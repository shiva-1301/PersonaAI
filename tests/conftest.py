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
