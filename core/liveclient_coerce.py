"""Lenient Live Client list / bool coercion (RM-602, directive X-02).

Provenance: behaviour inspired by external reference E (re-implemented from
the behaviour description only; no code taken).

The Live Client ``:2999`` payload is foreign JSON. Two shape drifts are known:

* a LIST field can arrive OBJECT-SHAPED, ``{"0": a, "1": b}`` (seen on a
  Practice Tool game). The old per-module ``_as_list`` helpers returned ``[]``
  for it, which silently dropped real data.
* a BOOL field can arrive as the STRING ``"True"`` / ``"False"`` (the
  ``Stolen`` key on objective kill events).

Rules here, shared by ``dashboard/_liveclient.py`` and
``game_reader/snapshot_normalizer.py``:

``as_list(v, field)``
    list -> returned unchanged (same object); dict whose keys are ALL
    integer-like (int, or a string of ASCII digits with an optional leading
    minus) -> its values in NUMERIC key order, logging one WARNING the first
    time each ``field`` is coerced in this process; anything else (None,
    scalar, empty dict, a dict with any non-integer key) -> ``[]``.

``as_bool(v, default=False)``
    a real bool -> itself; "True" / "False" in any case, surrounding
    whitespace ignored -> the matching bool; anything else -> ``default``.
    Ints are NOT accepted (1/0 are not a documented wire shape and a count
    must never read as a flag).
"""
from __future__ import annotations

import logging
import re
import threading

_log = logging.getLogger("core.liveclient_coerce")

_INT_KEY = re.compile(r"-?[0-9]+")

_warned: set[str] = set()
_warned_lock = threading.Lock()


def _int_key(k: object):
    """``k`` as an int when it is integer-like, else None (bool is not)."""
    if isinstance(k, bool):
        return None
    if isinstance(k, int):
        return k
    if isinstance(k, str) and _INT_KEY.fullmatch(k):
        return int(k)
    return None


def _warn_once(field: str, n: int) -> None:
    with _warned_lock:
        if field in _warned:
            return
        _warned.add(field)
    _log.warning(
        "live-client list field %r arrived object-shaped (%d entries); "
        "read as a list in numeric key order (logged once per field)",
        field, n,
    )


def as_list(v: object, field: str | None = None) -> list:
    """Coerce a Live Client list field per the module rules."""
    if isinstance(v, list):
        return v
    if not isinstance(v, dict) or not v:
        return []
    keyed = []
    for k, val in v.items():
        ik = _int_key(k)
        if ik is None:
            return []
        keyed.append((ik, val))
    keyed.sort(key=lambda kv: kv[0])
    _warn_once(field or "<unnamed>", len(keyed))
    return [val for _, val in keyed]


def as_bool(v: object, default: bool = False) -> bool:
    """Coerce a Live Client bool field per the module rules."""
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s == "true":
            return True
        if s == "false":
            return False
    return default


def _reset_warned_for_tests() -> None:
    with _warned_lock:
        _warned.clear()
