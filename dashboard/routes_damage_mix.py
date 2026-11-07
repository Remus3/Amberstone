"""GET /api/damage-mix - per-enemy damage-type donut data (UX-2, 2026-05-20).

Inputs (query string):

  - ``champ_id``  : Riot numeric champion key (e.g. 86 for Garen) OR
                    the snapshot string id (e.g. "Garen"). Required.
  - ``items``     : comma-separated item ids (e.g. "3074,3071,3047").
                    1..6 items. Required for a meaningful mix; empty
                    returns 400 ``items_required`` (kit-only baseline
                    is not exposed - the whole point of the surface is
                    "items have flipped damage").
  - ``level``     : optional, default 11. Outside [1, 18] is a 400.
  - ``mode``      : optional, default "SR". SR / ARAM / ARENA / BRAWL in any
                    case. Affects ARAM ``aramDamageDealt`` if "ARAM".

Output (JSON 200):

  {
    "ok": true,
    "champ_id": "Garen",
    "champ_key": 86,
    "items": ["3074", "3071", "3047"],
    "level": 11,
    "mode": "SR",
    "physical_dps": 18.5,
    "magical_dps": 0.3,
    "true_dps": 0.9,
    "on_hit_dps": 0.0,
    "total_dps": 19.7,
    "mix": {"physical": 0.939, "magical": 0.015, "true": 0.046, "on_hit": 0.0},
    "cache_key": "Garen:3074,3071,3047",
    "cached": false
  }

Errors (JSON 400). Every 400 body is a fixed line: the caller's value is
never echoed (RM-1255 class; S144-T-595).

  - missing or empty ``champ_id``, or one that is neither 1-4 ASCII digits
    (a numeric key) nor an ASCII letter followed by up to 31 ASCII letters /
    digits (a snapshot id) - refused before the snapshot is loaded
  - unknown champ key / id
  - missing or empty ``items``, more than 6 non-blank tokens, or a token
    that is not 1-8 ASCII digits - refused before the snapshot is loaded
  - unknown item id in the list
  - level not 1-9 ASCII digits (``level_invalid``), or outside [1, 18]
    (``level_out_of_range``); a blank ``level=`` reads the default, like a
    blank ``mode=``
  - mode outside the four above (ASCII only), with a fixed text and the
    supported list (RM-1330); the snapshot is not loaded and the engine is
    not called

Errors (JSON 500, fixed line ``damage-mix failed - see logs``): any failure
of the computation itself - a ``ValueError`` raised by the DS engine
included, which is a server fault, not the caller's - and a non-finite
number in the result (served as strict JSON or not at all).
"""
from __future__ import annotations

import json
import logging
import re
import threading
from urllib.parse import parse_qs, urlparse

from dashboard._dispatch import equals
from dashboard._errors import send_error

log = logging.getLogger("rc.web_dashboard")

# S144-T-595: the query shape is checked here, at the trust boundary, before
# the snapshot load and before any engine call. ``re.ASCII`` plus explicit
# ``[0-9]`` classes keep Unicode digits (fullwidth, Arabic-Indic) out: they
# pass ``str.isdigit`` / ``int()`` and used to resolve as numeric keys.
# Measured on the live snapshot: every champion id matches _CHAMP_ID_RE,
# every key is at most 3 digits and every item id at most 6 digits.
_CHAMP_KEY_RE = re.compile(r"[0-9]{1,4}", re.ASCII)
_CHAMP_ID_RE = re.compile(r"[A-Za-z][A-Za-z0-9]{0,31}", re.ASCII)
_ITEM_ID_RE = re.compile(r"[0-9]{1,8}", re.ASCII)
_LEVEL_RE = re.compile(r"[0-9]{1,9}", re.ASCII)
_DEFAULT_LEVEL = 11
# Same bound as core.damage_mix.MAX_ITEMS (six inventory slots), restated so
# the cap holds before the lazy import of the engine module.
_MAX_ITEMS = 6

# RM-1330: an unknown mode returned other numbers under the caller's label with
# ok=true (measured: ZZQ, CLASSIC, URF, KIWI, CHERRY and TFT each differed from SR
# in mix on 117 of 173 champions and in total_dps on 147). Same set as
# routes_ds_sweep (RM-1327).
_SUPPORTED_MODES: tuple[str, ...] = ("SR", "ARAM", "ARENA", "BRAWL")

# DataSnapshot is immutable per patch - load once + reuse across requests
# (mirrors routes_ds_knobs._get_snapshot). Pre-fix the route re-parsed the
# full multi-file snapshot from disk on EVERY request.
_SNAPSHOT = None
_SNAPSHOT_LOCK = threading.Lock()


def _get_snapshot():
    """Lazy-load + memoize the DS DataSnapshot (current.txt patch)."""
    global _SNAPSHOT
    with _SNAPSHOT_LOCK:
        if _SNAPSHOT is None:
            from agents.daemon_slayer.data_loader import DataSnapshot
            _SNAPSHOT = DataSnapshot.load()
        return _SNAPSHOT


def _reset_caches() -> None:
    """Test-only: clear the memoized snapshot."""
    global _SNAPSHOT
    with _SNAPSHOT_LOCK:
        _SNAPSHOT = None


def _bad(h, msg: str) -> None:
    """400 with a FIXED ``msg``; never pass caller-derived text here."""
    body = json.dumps({"ok": False, "error": msg}).encode("utf-8")
    h._send(400, body, "application/json")


def _parse_items(items_raw: str) -> tuple[list[str] | None, str | None]:
    """Split ``items`` into stripped ids; ``(None, error)`` on a bad list.

    Blank tokens are skipped; the walk stops at the seventh non-blank
    token, so a 5000-token list is refused without validating the rest and
    never reaches the snapshot.
    """
    items: list[str] = []
    for tok in items_raw.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if len(items) >= _MAX_ITEMS:
            return None, "too_many_items"
        if not _ITEM_ID_RE.fullmatch(tok):
            return None, "items_invalid"
        items.append(tok)
    if not items:
        return None, "items_required"
    return items, None


def _parse_level(qs: dict) -> tuple[int, str | None]:
    """``(level, None)`` with level in [1, 18], or ``(0, fixed_error)``.

    Blank or absent reads the default. Both error codes are fixed strings:
    the caller's value is never echoed (it used to be, unbounded).
    """
    level_raw = (qs.get("level") or [""])[0].strip()
    if not level_raw:
        return _DEFAULT_LEVEL, None
    if not _LEVEL_RE.fullmatch(level_raw):
        return 0, "level_invalid"
    level = int(level_raw)
    if level < 1 or level > 18:
        return 0, "level_out_of_range"
    return level, None


def _serve_damage_mix(h) -> None:
    """GET /api/damage-mix?champ_id=X&items=A,B,C[&level=N&mode=M]."""
    try:
        qs = parse_qs(urlparse(h.path).query, keep_blank_values=True)

        champ_raw = (qs.get("champ_id") or [""])[0].strip()
        if not champ_raw:
            _bad(h, "champ_id_required")
            return
        if not (_CHAMP_KEY_RE.fullmatch(champ_raw)
                or _CHAMP_ID_RE.fullmatch(champ_raw)):
            _bad(h, "champ_id_invalid")
            return

        items_raw = (qs.get("items") or [""])[0].strip()
        if not items_raw:
            _bad(h, "items_required")
            return
        items, items_err = _parse_items(items_raw)
        if items_err:
            _bad(h, items_err)
            return

        # Level - default 11 (mid-game); ASCII digits in [1, 18].
        level, level_err = _parse_level(qs)
        if level_err:
            _bad(h, level_err)
            return

        mode_raw = (qs.get("mode") or ["SR"])[0].strip()
        # ASCII first: Unicode upper-casing maps U+017F (long s) to "S", so
        # U+017F followed by "r" used to read as SR.
        mode = (mode_raw.upper() or "SR") if mode_raw.isascii() else ""
        if mode not in _SUPPORTED_MODES:
            h._send(400, json.dumps({
                "ok": False,
                # RM-1330: a fixed line, never the caller's value.
                "error": "unsupported mode",
                "supported": list(_SUPPORTED_MODES),
            }).encode("utf-8"), "application/json")
            return

        # Lazy import keeps a malformed snapshot from crashing the
        # whole dashboard at boot - same pattern as routes_lessons.
        from core import damage_mix as core_dm

        snapshot = _get_snapshot()
        # Only the two lookups that judge the CALLER's input map a
        # ValueError to 400. S144-T-595: the try used to wrap the whole
        # compute, so a ValueError from the DS engine itself read as a
        # client 400 "invalid_request"; it now reaches the 500 below.
        try:
            cid = core_dm.resolve_champ_id(snapshot, champ_raw)
            item_ids = core_dm.normalize_items(snapshot, items)
        except ValueError as exc:
            # RM-239 / RM-242: this used to be _bad(h, str(exc)), putting
            # core.damage_mix' raiser text on the wire - it carried the raw
            # champ/item input and the live snapshot patch. Raw cause now
            # goes to the log only.
            #
            # Two deliberate consequences of routing through send_error:
            #  - status=400 is passed explicitly; send_error defaults to 500.
            #  - the body is exactly {"error": msg}, so the "ok": False key
            #    that _bad emits is DROPPED here. Measured + accepted: the
            #    sole live consumer (web/js/panels/threat_donut.js) returns
            #    null on !resp.ok and never reads the body.
            send_error(h, exc, status=400, public_msg="invalid_request")
            return

        mix, was_cached = core_dm.compute_damage_mix(
            snapshot, cid, item_ids, level=level, mode=mode,
        )

        payload = mix.to_dict()
        payload.update({
            "ok": True,
            "cache_key": f"{mix.champ_id}:{','.join(mix.items)}",
            "cached": was_cached,
        })
        # allow_nan=False: a non-finite engine number raises here and
        # becomes the fixed 500 below, instead of a 200 whose bare NaN
        # token the browser's JSON.parse rejects (S144-T-595).
        body = json.dumps(payload, allow_nan=False).encode("utf-8")
        h._send(200, body, "application/json")
    except Exception as exc:  # noqa: BLE001
        # RM-835: a fixed line, never str(exc); send_error logs the cause
        # once, scrubbed, with its type name and the traceback.
        try:
            send_error(h, exc, public_msg="damage-mix failed - see logs",
                       fields={"ok": False}, log_traceback=True)
        except Exception:  # noqa: BLE001
            pass


GET_ROUTES = [
    (equals("/api/damage-mix"), _serve_damage_mix),
]

POST_ROUTES: list = []
