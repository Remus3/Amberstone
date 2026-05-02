"""
core/tk_ai_bar_proxy.py
Phase 1 Step 5.4 — Thread-safe proxy for TftAiStatusBar.

TftLiveAnalysis calls set_scanning(), set_done(), and
notify_scan_scheduled() from its own background thread.
TftAiStatusBar (tft/tft_overlay.py) touches Tk widgets directly.
Direct cross-thread widget access is a Tk threading violation.

This proxy sits between TftLiveAnalysis and TftAiStatusBar:
  - Holds the real bar and the Tk root reference
  - Schedules all widget calls onto the Tk main thread via root.after(0, ...)
  - Fails silently if the root or bar has been destroyed

Invariant: no Tk widget method is ever called from a non-main thread
through this proxy.

Python 3.9 compatible: no X|Y unions, no walrus, no match.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

_log = logging.getLogger("rc.tk_ai_bar_proxy")


class TkAiBarProxy:
    """
    Thread-safe proxy for TftAiStatusBar.

    Wraps the real ai_bar widget and a Tk root reference.
    Exposes the same interface used by TftLiveAnalysis:
      set_scanning(pct)
      set_done()
      notify_scan_scheduled(at_mono)
      set_interval(seconds)         — forwarded immediately (Tk-thread call)

    All calls except set_interval() are marshaled onto the Tk main thread
    via root.after(0, fn).  If root or bar is destroyed/gone, calls are
    silently dropped.
    """

    __slots__ = ("_root", "_bar")

    def __init__(self, root: Any, bar: Any) -> None:
        """
        Parameters
        ----------
        root : tkinter.Tk or tkinter.Toplevel
            The Tk root window; used for root.after() marshaling.
        bar  : TftAiStatusBar
            The real AI status bar widget.
        """
        self._root = root
        self._bar  = bar

    # ── Internal safe dispatch ────────────────────────────────────────────────

    def _schedule(self, fn) -> None:
        """Schedule fn() on the Tk main thread. Silently no-op if root is gone."""
        try:
            self._root.after(0, fn)
        except Exception:
            pass  # root destroyed or Tk not running — silently ignore

    # ── TftLiveAnalysis interface ─────────────────────────────────────────────

    def set_scanning(self, pct: int = 0) -> None:
        """Marshal set_scanning onto Tk main thread."""
        bar = self._bar
        self._schedule(lambda: _safe_call(bar, "set_scanning", pct))

    def set_done(self) -> None:
        """Marshal set_done onto Tk main thread."""
        bar = self._bar
        self._schedule(lambda: _safe_call(bar, "set_done"))

    def notify_scan_scheduled(self, at_mono: float) -> None:
        """Marshal notify_scan_scheduled onto Tk main thread."""
        bar = self._bar
        self._schedule(lambda: _safe_call(bar, "notify_scan_scheduled", at_mono))

    def set_interval(self, seconds: float) -> None:
        """
        Forward set_interval directly.
        This is called once from the Tk thread (attach_overlay) so no
        marshaling is needed, but we guard defensively anyway.
        """
        try:
            if self._bar is not None:
                self._bar.set_interval(seconds)
        except Exception:
            pass


def _safe_call(obj: Any, method: str, *args) -> None:
    """Call obj.method(*args) safely — no-op if obj is None or method missing."""
    try:
        if obj is not None:
            fn = getattr(obj, method, None)
            if fn is not None:
                fn(*args)
    except Exception:
        pass
