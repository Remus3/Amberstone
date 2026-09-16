# arch: shared boolean-flag parser for client-supplied JSON route bodies | section=dashboard | frozen=no
"""One rule for reading a boolean flag out of a client-supplied JSON body.

WHY THIS EXISTS (RM-296d, then RM-414). Route handlers read flags like
`payload.get("push_runes", True)` or `bool(payload.get("disabled"))` and
branched on BARE TRUTHINESS. A JSON body `{"disabled": "false"}` yields the
non-empty string "false", which is truthy, so the route took the ON path -
the exact opposite of what the body said. "0", "no" and "off" failed the
same way. RM-296d fixed that on `/api/loadout/apply`; RM-414 found five more
route sites with the same defect and moved the rule here so every site reads
flags identically. Two routes with one key name and two coercion rules is
worse than either bug alone.

THE CONTRACT (`coerce_json_flag`):
  key ABSENT      -> the caller's `default`. Omission keeps each route's
                     existing live default, so a client that never mentions
                     the key sees no behaviour change.
  real JSON bool  -> used as-is.
  string          -> stripped + lowercased, looked up in FALSE_TOKENS /
                     TRUE_TOKENS below; any other string is AMBIGUOUS.
  int / float     -> 0 is off, 1 is on; any other number is AMBIGUOUS.
  anything else   -> AMBIGUOUS (JSON null, list, dict).

AMBIGUOUS is returned as `None`, and it is the caller's cue to answer HTTP 400
naming the field. It is NOT "fall back to the default": a value the server
cannot read is not consent to act, and a silent default is wrong in whichever
direction it goes. Precedent, not invention: `dashboard/routes_diag.py`
rejects a non-bool `dismiss` the same way.

A JSON `null` is deliberately ambiguous rather than absent: a client that
computed `null` had an opinion and failed to express it, which is a different
statement from never mentioning the key. Hence the test is `key not in
payload`, not the value's own truthiness.
"""
from __future__ import annotations

import json

FALSE_TOKENS = frozenset({"false", "0", "no", "off", "n", ""})
TRUE_TOKENS = frozenset({"true", "1", "yes", "on", "y"})


def coerce_json_flag(payload, key: str, default: bool):
    """Read one flag. Returns True, False, or None for AMBIGUOUS.

    See the module docstring for the full contract. A non-dict `payload`
    carries no keys at all, so it reads as ABSENT and yields `default`.
    """
    if not isinstance(payload, dict) or key not in payload:
        return default
    raw = payload[key]
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        token = raw.strip().lower()
        if token in FALSE_TOKENS:
            return False
        if token in TRUE_TOKENS:
            return True
        return None
    if isinstance(raw, (int, float)):
        if raw == 0:
            return False
        if raw == 1:
            return True
    return None


def first_ambiguous_flag(payload, keys) -> "str | None":
    """Name the first key in `keys` whose value is AMBIGUOUS, else None.

    The default passed to `coerce_json_flag` cannot change whether a value is
    ambiguous (an absent key is never ambiguous), so none is taken here.
    """
    for key in keys:
        if coerce_json_flag(payload, key, False) is None:
            return key
    return None


def bad_flag_body(field: str, error: str = "bad_flag") -> bytes:
    """The HTTP 400 body naming the offending field."""
    return json.dumps({"error": error, "field": field}).encode()
