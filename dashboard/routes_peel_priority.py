# arch: peel-target verdict backend (item 304 Phase D) | section=dashboard | frozen=no
"""GET /api/peel-priority - ally-amplification peel-target verdict.

FIRST live consumer of the item-304 ally-amplification axis
(``agents.daemon_slayer.allyamp.compute_allyamp``, ENGINE 1.116.0). The
axis scores how much COMBAT VALUE a champion pumps OUTWARD into her allies
(shields / heals / steroids / hard-saves / haste); this route pairs a live
(or supplied) ALLY roster against it and answers the in-game question "who
do I peel for?".

Single-sided by construction (mirror of the SYMMETRIC cc-threat chips, but
ally amplification is a same-team property - there is no enemy side to
ratio against). For each ally champion it reports the ally-amp score, the
top buff kind + the ability that drives it, and whether the champion owns a
PROTECT mechanism (saves_ally - a hard save that can make a teammate
un-killable: Taric R / Zilean R / Kindred R / Tahm Kench R / Bard R / ...).

Auto-pairing: when the ``ally`` query param is ABSENT the route reads the
live ally roster from the in-game Live Client summary (``_live_ally_roster``,
which drops the operator's own champion - a peel verdict is about
teammates). When ``ally`` is supplied it is used verbatim (the champ-select
/ test path). An empty-but-present ``ally`` is a no_champions input, NOT a
live read - that distinction is load-bearing (keep_blank_values below).

Request shape:
  GET /api/peel-priority[?ally=<champ,champ,...>][&mode=SR]

  ally : comma-separated canonical DDragon ids. Blank entries are dropped
         before scoring (compute_allyamp fail-softs on unknown ids -> 0.0).
         ABSENT (no key) -> live auto-read. PRESENT-but-empty -> no_champions.
  mode : SR | ARAM | KIWI | ARENA | BRAWL. Default SR (this is an SR peel
         consumer). Ally amplification is map-independent so mode does not
         change the score today; it is carried for parity + cache keying.

Response shape (ok=true):
  {
    "ok":             true,
    "mode":           "SR",
    "source":         "param" | "live",
    "ranked":         [ {champion, allyamp_score, top_kind, top_source,
                         saves_ally}, ... ],   # desc by allyamp_score
    "protect_target": {champion, allyamp_score, top_kind, top_source,
                       saves_ally} | null,     # highest non-zero ally
    "hard_saves":     [ {champion, source, value}, ... ],  # PROTECT owners
    "verdict":        "<one-line ascii peel call>",
    "elapsed_ms":     <int>,
    "cached":         <bool>
  }

Failure / empty modes:
  - 200 ok=false reason="no_champions"   ally present but blank.
  - 200 ok=false reason="no_live_roster" ally absent + not in a game.
  - 200 ok=true protect_target=null      every ally scores 0.0 (a comp of
        selfish carries / assassins - the sparse-axis correct answer).
  - 503 allyamp import fails (DS engine unreachable).

5-min TTL in-process cache keyed on (sorted_ally_tuple, mode), mirroring the
cc-route discipline. The live roster is static within a game so the first
in-game call warms the slot for the rest of the game.

Don't-redo:
  * Single-sided is correct - ally amplification has no enemy mirror (do
    NOT add an enemy ratio; that would conflate it with the cc-threat chips).
  * ABSENT vs PRESENT-but-empty ``ally`` is the live-read fork. Keep
    keep_blank_values=True or the two collapse.
  * _live_ally_roster drops the operator's own champion. Peel-target is a
    teammate, not yourself; the full ally_team (incl self) lives in
    _liveclient.liveclient_summary().
  * Kind weights / scope mults are owned by allyamp.py (the Phase-D
    tunables) - this route only reads the computed score. Re-rank tuning
    happens there, not here.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from urllib.parse import parse_qs, urlparse

from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

# 5-min response TTL mirrors the cc-route chips exactly.
_CACHE_TTL_S = 300.0
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()

_DEFAULT_MODE = "SR"
_VALID_MODES = frozenset(("SR", "ARAM", "KIWI", "ARENA", "BRAWL"))


def _parse_champ_list(raw: str) -> list[str]:
    """Split a comma-separated DDragon-id list, drop blanks.

    Unknown ids are NOT filtered (compute_allyamp fail-softs to a 0.0
    result per its sparse-axis contract); only literal blanks are dropped
    so "Lulu,,Soraka" does not carry a phantom 0.0 row.
    """
    if not raw:
        return []
    return [s for s in (p.strip() for p in raw.split(",")) if s]


def _live_ally_roster() -> list[str]:
    """Best-effort live ALLY champion roster (teammates, self dropped).

    Reads ``dashboard._liveclient.liveclient_summary`` which surfaces
    ``ally_team`` (the full same-team champion list incl the operator) +
    ``champion`` (the operator's own pick). A peel-target is a teammate, so
    the operator's own champion is removed here (in Live Client display
    space, before canonicalizing). Live Client emits DISPLAY names
    ("Tahm Kench", "Nunu & Willump") while the ally-amp registry keys on
    canonical DDragon ids ("TahmKench", "Nunu"); each survivor is mapped
    through ``canonical_champion_id`` so multi-word registry champs
    (Tahm Kench is a PROTECT hard-save) are not silently missed. Returns []
    when not in a game (the summary is {} on a stale / missing snapshot).
    Monkeypatch point for tests - never raises.
    """
    try:
        from dashboard._liveclient import liveclient_summary

        from core.archetype_picks import canonical_champion_id

        lc = liveclient_summary() or {}
        roster = lc.get("ally_team") or []
        me = lc.get("champion") or ""
        return [canonical_champion_id(str(c)) for c in roster if c and c != me]
    except Exception as exc:
        log.debug("peel-priority: live roster read failed: %s", exc)
        return []


def _cache_key(ally: list[str], mode: str) -> tuple:
    return (tuple(sorted(ally)), mode)


def _score_ally(champ: str, mode: str) -> dict:
    """Score one ally via compute_allyamp -> a flat per-ally row.

    ``top_source`` is the ability driving the single highest-value
    mechanism (the champion's strongest ally-buff); ``protect_source`` /
    ``protect_value`` capture the strongest PROTECT mechanism (the
    hard-save), empty / 0.0 when the champion owns none.
    """
    from agents.daemon_slayer.allyamp import compute_allyamp

    r = compute_allyamp(champ, mode)
    top_source = ""
    best_v = -1.0
    protect_source = ""
    protect_value = 0.0
    for s in r.sources:
        if s.value > best_v:
            best_v = s.value
            top_source = s.source_key
        if s.kind == "PROTECT" and s.value > protect_value:
            protect_value = s.value
            protect_source = s.source_key
    has_amp = r.allyamp_score > 0.0
    return {
        "champion": champ,
        "allyamp_score": round(r.allyamp_score, 4),
        "top_kind": r.top_kind,
        "top_source": top_source if has_amp else "",
        "saves_ally": r.saves_ally,
        "protect_source": protect_source,
        "protect_value": round(protect_value, 4),
    }


def _build_verdict(protect_target: dict | None, hard_saves: list[dict]) -> str:
    """One-line ASCII peel call from the protect_target + hard_saves."""
    if not protect_target:
        return "No ally buff-throughput in this comp - play for picks / objectives"
    out = (
        f"Peel for {protect_target['champion']} "
        f"({protect_target['top_kind']} buff-throughput)"
    )
    if hard_saves:
        names = ", ".join(f"{h['champion']} {h['source']}" for h in hard_saves[:2])
        out += f"; hard-save: {names}"
    return out


def _compute(allies: list[str], mode: str, source: str) -> dict:
    """Build the peel-target payload from scratch (no cache)."""
    scored = [_score_ally(c, mode) for c in allies]
    scored.sort(key=lambda a: (-a["allyamp_score"], a["champion"]))

    ranked = [
        {
            "champion": a["champion"],
            "allyamp_score": a["allyamp_score"],
            "top_kind": a["top_kind"],
            "top_source": a["top_source"],
            "saves_ally": a["saves_ally"],
        }
        for a in scored
    ]

    nonzero = [a for a in scored if a["allyamp_score"] > 0.0]
    protect_target = None
    if nonzero:
        top = nonzero[0]
        protect_target = {
            "champion": top["champion"],
            "allyamp_score": top["allyamp_score"],
            "top_kind": top["top_kind"],
            "top_source": top["top_source"],
            "saves_ally": top["saves_ally"],
        }

    savers = [a for a in scored if a["saves_ally"]]
    savers.sort(key=lambda a: (-a["protect_value"], a["champion"]))
    hard_saves = [
        {"champion": a["champion"], "source": a["protect_source"],
         "value": a["protect_value"]}
        for a in savers
    ]

    return {
        "ok": True,
        "mode": mode,
        "source": source,
        "ranked": ranked,
        "protect_target": protect_target,
        "hard_saves": hard_saves,
        "verdict": _build_verdict(protect_target, hard_saves),
    }


def _serve_peel_priority(h) -> None:
    """GET /api/peel-priority handler."""
    t0 = time.time()
    try:
        qs = parse_qs(urlparse(h.path).query or "", keep_blank_values=True)
        mode_raw = (qs.get("mode") or [_DEFAULT_MODE])[0].strip()
        mode = mode_raw.upper() if mode_raw else _DEFAULT_MODE
        if mode not in _VALID_MODES:
            mode = _DEFAULT_MODE

        # ABSENT ally key -> live auto-read. PRESENT (even blank) -> param.
        if "ally" not in qs:
            allies = _live_ally_roster()
            source = "live"
            if not allies:
                h._send(200, json.dumps({
                    "ok": False,
                    "mode": mode,
                    "source": source,
                    "reason": "no_live_roster",
                    "elapsed_ms": int((time.time() - t0) * 1000),
                    "cached": False,
                }).encode("utf-8"), "application/json")
                return
        else:
            allies = _parse_champ_list((qs.get("ally") or [""])[0].strip())
            source = "param"
            if not allies:
                h._send(200, json.dumps({
                    "ok": False,
                    "mode": mode,
                    "source": source,
                    "reason": "no_champions",
                    "elapsed_ms": int((time.time() - t0) * 1000),
                    "cached": False,
                }).encode("utf-8"), "application/json")
                return

        key = _cache_key(allies, mode)
        now = time.time()
        with _CACHE_LOCK:
            cached = _CACHE.get(key)
            if cached and (now - cached[0]) < _CACHE_TTL_S:
                payload = dict(cached[1])
                payload["source"] = source
                payload["cached"] = True
                payload["elapsed_ms"] = int((time.time() - t0) * 1000)
                h._send(200, json.dumps(payload).encode("utf-8"),
                        "application/json")
                return

        try:
            payload = _compute(allies, mode, source)
        except ImportError as exc:
            log.warning("api/peel-priority import: %s", exc)
            h._send(503, json.dumps({
                "ok": False, "error": "DS engine unavailable",
            }).encode("utf-8"), "application/json")
            return
        except Exception as exc:
            log.warning("api/peel-priority compute: %s", exc)
            h._send(503, json.dumps({
                "ok": False, "error": "DS engine compute failed",
            }).encode("utf-8"), "application/json")
            return

        with _CACHE_LOCK:
            _CACHE[key] = (now, dict(payload))

        payload["cached"] = False
        payload["elapsed_ms"] = int((time.time() - t0) * 1000)
        h._send(200, json.dumps(payload).encode("utf-8"),
                "application/json")

    except Exception as exc:
        log.warning("api/peel-priority: %s", exc)
        try:
            h._send(500, json.dumps({
                "ok": False, "error": str(exc)[:200],
            }).encode("utf-8"), "application/json")
        except Exception:
            pass


def _reset_caches() -> None:
    """Test-only: clear response cache."""
    with _CACHE_LOCK:
        _CACHE.clear()


GET_ROUTES = [
    (equals("/api/peel-priority"), _serve_peel_priority),
]

POST_ROUTES: list = []
