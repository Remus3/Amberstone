"""
coaches/voice_coach.py - opt-in voice output for the Right Now headline.

Uses Windows' built-in System.Speech.Synthesis.SpeechSynthesizer via a
PowerShell subprocess so no pip dependencies are required. Throttled
+ deduped so the user doesn't get spammed by the same advice.

Public API:
    speak(text: str, *, dedup: bool = True) -> bool
        Returns True if the utterance was spoken (or queued), False if
        deduped or rate-limited.

Design rules:
    - Fire-and-forget: PowerShell process is spawned with no stdin,
      detached, output discarded. We never block the caller.
    - Dedup: same text within 60 seconds → silenced.
    - Rate limit: minimum 4 s between utterances regardless of dedup.
    - Length cap: 200 chars to keep utterances short.
    - Safe to call when voice is unavailable (e.g., headless Wine env).

Wired by the dashboard via /api/speak when the user enables the VOICE
toggle in the footer.
"""
from __future__ import annotations

import logging
import subprocess
import threading
import time
from typing import Optional

_log = logging.getLogger("rc.voice")

_LAST_TS: float = 0.0
_LAST_TEXT: str = ""
_DEDUP_WINDOW_S = 60.0
_MIN_INTERVAL_S = 4.0
_MAX_CHARS = 200
_lock = threading.Lock()


def _quote_for_ps(s: str) -> str:
    """Single-quote string for PowerShell. Replace ' with '' (PS escape)."""
    return "'" + s.replace("'", "''") + "'"


def speak(text: str, *, dedup: bool = True, rate: int = 0) -> bool:
    """Speak `text` via Windows SAPI. Non-blocking, throttled, deduped.

    rate: -10 (slowest) to +10 (fastest); 0 is default.
    """
    text = (text or "").strip()
    if not text:
        return False
    text = text[:_MAX_CHARS]
    now = time.time()
    global _LAST_TS, _LAST_TEXT
    with _lock:
        if dedup and text == _LAST_TEXT and (now - _LAST_TS) < _DEDUP_WINDOW_S:
            return False
        if (now - _LAST_TS) < _MIN_INTERVAL_S:
            return False
        _LAST_TS = now
        _LAST_TEXT = text

    quoted = _quote_for_ps(text)
    cmd = (
        "Add-Type -AssemblyName System.Speech;"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"$s.Rate = {int(rate)};"
        f"$s.Speak({quoted});"
    )
    try:
        # Detached, no window, ignore output. Process self-cleans on exit.
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive",
             "-WindowStyle", "Hidden", "-Command", cmd],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
        return True
    except Exception as exc:
        _log.debug("voice speak failed: %s", exc)
        return False


def is_available() -> bool:
    """Best-effort availability probe - checks PowerShell + SAPI."""
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "Add-Type -AssemblyName System.Speech;"
             "(New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices().Count"],
            capture_output=True, text=True, timeout=5,
            creationflags=0x08000000,
        )
        n = int((r.stdout or "0").strip() or "0")
        return n > 0
    except Exception:
        return False
