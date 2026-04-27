"""
coaches/sr_coach.py
Summoner's Rift coaching engine.

Wraps coach_integration.CoachIntegration with the standard Coach interface
so it can be swapped at runtime by the mode loader.
"""
import sys
from pathlib import Path

# Ensure parent is on path so core/ imports work
_APP_DIR = Path(__file__).parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

# Import the full SR coaching engine
from coach_integration import CoachIntegration   # noqa: E402


class Coach(CoachIntegration):
    """SR Coach — identical to CoachIntegration but registered under the
    standard Coach interface used by the mode loader."""

    GAME_MODES = ("CLASSIC", "PRACTICETOOL")

    def shutdown(self):
        """Clean exit: stop any pending threads, flush cache."""
        try:
            if hasattr(self, "_cache") and self._cache:
                self._cache.close()
        except Exception:
            pass
        try:
            if hasattr(self, "_lock"):
                # Ensure no thread is mid-flight
                acquired = self._lock.acquire(timeout=3.0)
                if acquired:
                    self._lock.release()
        except Exception:
            pass
