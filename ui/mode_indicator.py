"""
ui/mode_indicator.py — Stub (mode indication absorbed into ClientPanel tabs).
"""

from ui.base import OverlayWindow


class ModeIndicator(OverlayWindow):
    """No-op stub. Mode is now shown by the active ClientPanel tab."""

    def __init__(self, root):
        super().__init__(root, {"x": 0, "y": 0, "w": 1, "h": 1},
                        tag="mode_indicator")

    def set_mode(self, mode, auto=False):
        pass
