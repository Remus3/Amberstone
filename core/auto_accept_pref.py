"""core/auto_accept_pref.py - LCU ready-check auto-accept on/off preference.

A tiny, NON-frozen preference flag so the dashboard can turn the frozen
``lcu/lcu_client.py`` auto-accept loop on or off without editing the loop's
logic. The frozen ``_auto_accept_tick`` consults ``is_enabled()`` right before
it calls ``accept_queue()``; everything else in the tick (rune application,
connect retry) is untouched.

Default is ENABLED (True) so a missing/corrupt flag file preserves the
historical always-on behavior - the auto-accept stays byte-identical until the
operator explicitly turns it off via the dashboard toggle (POST
/api/lcu/auto-accept).

State lives in ``data/auto_accept_pref.json`` ({"enabled": bool}), written
atomically (tmp + replace) per the project hard rule so the 1 Hz tick can never
read a half-written file.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

_log = logging.getLogger("rc.lcu")

_PREF_PATH = Path(__file__).resolve().parent.parent / "data" / "auto_accept_pref.json"

# Serialize writes so a dashboard POST cannot interleave with another POST.
# Reads are lock-free (a single os-level file read of a small JSON blob).
_WRITE_LOCK = threading.Lock()

# Default-ON: absent/unreadable/garbage file -> True (historical behavior).
_DEFAULT_ENABLED = True


def is_enabled() -> bool:
    """Return whether ready-check auto-accept is currently enabled.

    Fail-soft to the default (True) on any read/parse error so the live tick
    never throws and never silently disables itself on a transient FS hiccup.
    """
    try:
        raw = _PREF_PATH.read_text(encoding="utf-8")
    # RM-291A: UnicodeDecodeError is a ValueError, not an OSError.
    except (OSError, UnicodeDecodeError):
        return _DEFAULT_ENABLED
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return _DEFAULT_ENABLED
    val = data.get("enabled") if isinstance(data, dict) else None
    return bool(val) if isinstance(val, bool) else _DEFAULT_ENABLED


def set_enabled(enabled: bool) -> bool:
    """Persist the auto-accept preference atomically. Returns the stored bool.

    Atomic write (tmp + replace) so the concurrent 1 Hz reader in
    ``_auto_accept_tick`` never observes a partial file.
    """
    enabled = bool(enabled)
    with _WRITE_LOCK:
        _PREF_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _PREF_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"enabled": enabled}), encoding="utf-8")
        tmp.replace(_PREF_PATH)
    _log.info("auto-accept preference set: enabled=%s", enabled)
    return enabled
