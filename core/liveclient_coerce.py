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
    minus) and all DISTINCT as numbers -> its values in NUMERIC key order,
    logging one WARNING the first time each ``field`` is coerced in this
    process; anything else -> ``[]``. It never raises. Two keys naming the
    same index (``"1"`` and ``"01"``, ``"0"`` and ``"-0"``) are refused, not
    merged: a real list never repeats an index and either order would be a
    guess. A key past the interpreter's int-string limit is not integer-like.
    None, an empty dict and an empty string are "absent" and stay silent;
    any other refused value (a scalar, a dict with a non-integer or repeated
    key) logs one WARNING per ``field`` naming only its type, never the
    value, so a renamed or re-nested upstream field does not go dark
    silently.

``as_bool(v, default=False)``
    a real bool -> itself; "True" / "False" in any case, surrounding
    whitespace ignored -> the matching bool; anything else -> ``default``,
    returned as given (``core/live_event_deriver.py`` passes ``None`` so a
    missing flag stays unknown). Ints are NOT accepted (1/0 are not a
    documented wire shape and a count must never read as a flag).
"""
from __future__ import annotations

import logging
import re
import threading
from typing import TypeVar

_log = logging.getLogger("core.liveclient_coerce")

_INT_KEY = re.compile(r"-?[0-9]+")

_D = TypeVar("_D")

# (field, kind) pairs already warned; kind is "coerced" or "refused". Field
# labels are caller literals, so the set is bounded by the call sites.
_warned: set[tuple[str, str]] = set()
_warned_lock = threading.Lock()


def _int_key(k: object):
    """``k`` as an int when it is integer-like, else None (bool is not)."""
    if isinstance(k, bool):
        return None
    if isinstance(k, int):
        return k
    if isinstance(k, str) and _INT_KEY.fullmatch(k):
        try:
            return int(k)
        except ValueError:
            # More digits than sys.get_int_max_str_digits() allows.
            return None
    return None


def _label(field: object) -> str:
    return field if isinstance(field, str) and field else "<unnamed>"


def _first(field: str, kind: str) -> bool:
    with _warned_lock:
        if (field, kind) in _warned:
            return False
        _warned.add((field, kind))
        return True


def _warn_coerced(field: str, n: int) -> None:
    if _first(field, "coerced"):
        _log.warning(
            "live-client list field %r arrived object-shaped (%d entries); "
            "read as a list in numeric key order (logged once per field)",
            field, n,
        )


def _refuse(field: str, v: object, why: str) -> list:
    if _first(field, "refused"):
        _log.warning(
            "live-client list field %r arrived in an unusable shape (%s, %s); "
            "read as an empty list (logged once per field)",
            field, type(v).__name__, why,
        )
    return []


def as_list(v: object, field: str | None = None) -> list:
    """Coerce a Live Client list field per the module rules."""
    if isinstance(v, list):
        return v
    if v is None or (isinstance(v, (dict, str)) and not v):
        return []
    label = _label(field)
    if not isinstance(v, dict):
        return _refuse(label, v, "not a list or dict")
    keyed = []
    seen: set[int] = set()
    for k, val in v.items():
        ik = _int_key(k)
        if ik is None:
            return _refuse(label, v, "non-integer key")
        if ik in seen:
            return _refuse(label, v, "repeated index")
        seen.add(ik)
        keyed.append((ik, val))
    keyed.sort(key=lambda kv: kv[0])
    _warn_coerced(label, len(keyed))
    return [val for _, val in keyed]


def as_bool(v: object, default: _D = False) -> bool | _D:
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
