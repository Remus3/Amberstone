"""core/auto_accept_pref.py - LCU ready-check auto-accept on/off preference.

A tiny, NON-frozen preference flag so the dashboard can turn the frozen
``lcu/lcu_client.py`` auto-accept loop on or off without editing the loop's
logic. The frozen ``_auto_accept_tick`` consults ``is_enabled()`` right before
it calls ``accept_queue()``; everything else in the tick (rune application,
connect retry) is untouched.

TWO GATES, ONE SOURCE OF TRUTH (RM-1222, s145). Ready checks can be accepted
by two independent mechanisms: the LCU agent (``tools/lcu_agent.py``
``auto_features``, gated by its ``CONFIG["auto_accept"]``) and RC's in-process
loop (gated by this module). This file is the truth for BOTH: the agent seeds
its CONFIG from ``is_enabled()`` at boot and re-reads it every auto-features
tick (``_sync_auto_accept_from_pref``), because that CONFIG alone was process
memory and every agent restart showed Off while the saved choice said on. The
dashboard "Auto Accept" control DISPLAYS the agent's CONFIG
(``state.lcu.config.auto_accept``); on a click it posts the bool to
``/api/lcu/auto-accept`` (``dashboard/routes_auto_accept.py``), which writes
here, and only after that save lands sends the agent a ``set_config``. A
failed save puts the control back and says so (``web/js/main.js``
``_setAutoAccept``).

Default is DISABLED (False) - s144 true-audit cycle 83. It used to be True
("preserve the historical always-on behavior"), but the agent's boot default
is False, so with no stored choice here the UI said Off while this gate kept
accepting every ready check: the s171 "silently always on regardless of the UI
state" class. The default is now drift-guarded against the agent's
(``tests/test_auto_accept_pref_hardening_s144t083.py``). A stored choice
always wins over the default - in both gates, since RM-1222.

Read failures, by kind:
  * absent file -> the default (no choice was ever stored; not a warning).
  * a transient OS error (a sharing violation while the writer swaps the file
    in) -> the last value this process read or wrote, else the default, so a
    hiccup neither turns auto-accept on nor off behind the operator's back.
  * corrupt content (non-UTF-8, not JSON, not ``{"enabled": bool}``) -> the
    default: the stored choice is unknown, and accepting a queue nobody asked
    for is the worse error.
  Each problem is logged ONCE per distinct kind (the reader runs at about
  1 Hz while a ready check is pending) and a good read re-arms the warning.
  The log line never carries the file's content.

State lives in ``data/auto_accept_pref.json`` ({"enabled": bool}), written
atomically (``core.polled_json.atomic_write_text``: scratch file, fsync,
bounded-retry replace) so the reader never sees a half-written file.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Optional

from core.polled_json import atomic_write_text

_log = logging.getLogger("rc.lcu")

_PREF_PATH = Path(__file__).resolve().parent.parent / "data" / "auto_accept_pref.json"

# Serialize writes so a dashboard POST cannot interleave with another POST.
# Reads take no lock (a single read of a small JSON blob).
_WRITE_LOCK = threading.Lock()

# Default-OFF: no stored choice -> agree with the agent's boot default, which
# is what the dashboard control shows.
_DEFAULT_ENABLED = False

# Last value this process read from, or wrote to, the file (None = none yet).
# Returned on a transient read error only. A plain attribute store is atomic
# under the GIL; no lock is needed for a single bool. Known, accepted window:
# a read that started before a concurrent set_enabled() can store the older
# value after it; the next good read corrects it, and the memo is only ever
# consulted on a transient OSError.
_last_good: Optional[bool] = None

# Last read problem logged (dedupe key); None after a good read.
_last_problem: Optional[str] = None


def _note_problem(kind: str) -> None:
    """Log a read problem once per distinct kind until a good read re-arms it."""
    global _last_problem
    if kind != _last_problem:
        _last_problem = kind
        _log.warning("auto-accept preference unreadable (%s) - %s", kind,
                     "using the default (off)" if kind.startswith("corrupt")
                     else "using the last known value")


def _parse(raw: str) -> Optional[bool]:
    """The stored bool, or None when the content is not {"enabled": bool}."""
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError):
        # RecursionError: a deeply nested document ("[" * 200000) exhausts
        # the decoder's stack instead of failing as a ValueError.
        return None
    val = data.get("enabled") if isinstance(data, dict) else None
    return val if isinstance(val, bool) else None


def is_enabled() -> bool:
    """Return whether ready-check auto-accept is currently enabled.

    Never raises (the live tick calls it); see the module docstring for what
    each kind of read failure returns.
    """
    global _last_good, _last_problem
    try:
        raw = _PREF_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        _last_problem = None
        return _DEFAULT_ENABLED
    except UnicodeDecodeError:
        # RM-291A: UnicodeDecodeError is a ValueError, not an OSError.
        _note_problem("corrupt: not UTF-8")
        return _DEFAULT_ENABLED
    except OSError as exc:
        _note_problem(f"read failed: {type(exc).__name__}")
        return _DEFAULT_ENABLED if _last_good is None else _last_good
    val = _parse(raw)
    if val is None:
        _note_problem('corrupt: not {"enabled": bool}')
        return _DEFAULT_ENABLED
    _last_good = val
    _last_problem = None
    return val


def set_enabled(enabled: bool) -> bool:
    """Persist the auto-accept preference atomically. Returns the stored bool.

    ``enabled`` must be a real bool: ``bool("false")`` is True, so coercing a
    caller's value used to store the opposite of what a string meant.
    Raises TypeError for a non-bool (nothing is written) and lets the write's
    OSError propagate (the memo is left unchanged).
    """
    global _last_good
    if not isinstance(enabled, bool):
        raise TypeError("enabled must be a bool")
    with _WRITE_LOCK:
        atomic_write_text(_PREF_PATH, json.dumps({"enabled": enabled}))
        _last_good = enabled
    _log.info("auto-accept preference set: enabled=%s", enabled)
    return enabled
