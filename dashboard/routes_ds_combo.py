# arch: action-queue combo simulator backend | section=dashboard | frozen=no
"""GET /api/ds-combo - per-hit timeline for an ordered cast/attack list.

Competitor lift #2 (DEPTH spec docs/COMPETITOR_LIFT_2026-05-30.md "Lift
2"). Thin dashboard wire over
``agents.daemon_slayer.combo.compute_combo`` - the action-queue duel-sim
that walks a clock over a SEQUENTIAL action list (``Q, AA, W, R``),
applying each hit through the existing burst-walker mitigation pipeline
and resolving cooldowns between actions. NO new scoring math (combo.py
composes ``compute_burst_damage`` + the patch-pinned cast/cooldown data);
NO ENGINE_VERSION bump; NO schema lift.

Sibling of ``routes_cooldown_watch.py`` - same cache + fail-soft + status
discipline. Where the cooldown-watch card surfaces enemy CC windows, this
route turns RC's single aggregate burst into a per-hit timeline for the
operator's OWN champion (calc.gg's Action Queue).

Request shape:
  GET /api/ds-combo?champion=<id>&level=11&items=<id,id,..>
      &seq=Q,AA,W,R&target_armor=80&target_mr=60
      &target_max_hp=&target_bonus_hp=&mode=SR&runes=8112,8005

  champion      : canonical DDragon id ("Lux", "Caitlyn"). REQUIRED.
  seq           : comma-separated action tokens (Q/W/E/R/AA + recast
                  variants the burst walker understands). REQUIRED.
                  Capped at 60 actions / 60s clock by the engine.
  level         : champion level 1-18 (default 11; clamped by the engine).
  items         : comma-separated item ids (default none).
  target_armor  : target armor (default 0).
  target_mr     : target magic resist (default 0).
  target_max_hp : target max HP (default 0; %-HP scaling blocks).
  target_bonus_hp: target bonus HP (default 0; LDR / giant-slayer amps).
  mode          : SR | ARAM | ... (default SR; only affects mode multiplier).
  runes         : comma-separated rune ids (default none); fed to the
                  rune_procs proc/amp layer. Omitted / blank / unknown-only
                  is byte-identical to the no-runes path.
  keystone      : single rune id; convenience alias merged into runes.

Response shape:
  {
    "ok":          true,
    "champion":    "Lux",
    "champion_name": "Lux",
    "level":       11,
    "mode":        "SR",
    "sequence":    ["Q","AA","W","E","R"],
    "hits": [
      {
        "index": 0, "action": "Q", "ability_key": "Q",
        "is_ability": true, "form_name": "Light Binding", "rank": 4,
        "t": 0.0, "cast_time": 0.25, "cooldown_s": 9.0,
        "damage_type": "MAGIC", "raw": 240.0, "mitigated": 150.0,
        "cumulative": 150.0, "status": "ok", "note": ""
      },
      ...
    ],
    "totals": {"total_raw": 751.09, "total_mitigated": 486.71,
               "duration_s": 2.0},
    "notes":     [...],
    "count":     <int>,
    "elapsed_ms": <int>,
    "cached":    <bool>
  }

Failure modes:
  - 400  champion OR seq param literally missing / blank.
  - 200  ok=false reason=empty_sequence when seq resolves to zero usable
         tokens (blanks only).
  - 503  combo import fails (DS engine module unreachable) or compute
         raises despite the engine's fail-soft contract.

5-min TTL in-process cache keyed on the full normalized request tuple.
Mirrors routes_cooldown_watch cache discipline.

Don't-redo:
  * v1 = FIXED cast times, NO animation-cancel; an on-cooldown re-cast is
    SKIPPED (not delayed) - see the engine module docstring. Don't pitch a
    delay model without a recast-window policy.
  * combo.py is a READ-ONLY COMPOSE over compute_burst_damage + the
    cast/cooldown JSON. Do NOT bump ENGINE_VERSION for this route (no
    scoring math moved) and do NOT restart DS :8893 (the engine server
    does not consume this module; the route imports combo in-process on
    the :8888 dashboard, same as routes_cooldown_watch imports
    cooldown_watch).
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from urllib.parse import parse_qs, urlparse

from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

# 5-min response TTL mirrors routes_cooldown_watch exactly.
_CACHE_TTL_S = 300.0
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()

_DEFAULT_LEVEL = 11
_MIN_LEVEL = 1
_MAX_LEVEL = 18


def _parse_seq(raw: str) -> list[str]:
    """Split a comma-separated action token list, strip blanks, uppercase."""
    if not raw:
        return []
    out: list[str] = []
    for part in raw.split(","):
        s = part.strip().upper()
        if s:
            out.append(s)
    return out


def _parse_items(raw: str) -> list[str]:
    """Split a comma-separated item-id list, strip blanks."""
    if not raw:
        return []
    out: list[str] = []
    for part in raw.split(","):
        s = part.strip()
        if s:
            out.append(s)
    return out


def _parse_runes(raw: str) -> list[int]:
    """Split a comma-separated rune-id list into ints; drop garbage.

    Defensive like _parse_items: a non-integer token is silently skipped
    so a malformed runes= never raises (engine treats unknown / empty ids
    as a zero contribution; an empty list is byte-identical to no runes).
    """
    if not raw:
        return []
    out: list[int] = []
    for part in raw.split(","):
        s = part.strip()
        if not s:
            continue
        try:
            out.append(int(s))
        except (TypeError, ValueError):
            continue
    return out


def _parse_level(raw: str) -> int:
    """Parse champion level; clamp to [1, 18]; fall to default on garbage.

    OverflowError covers int(float('inf')) - pre-fix it escaped to the
    outer 500 handler.
    """
    if not raw:
        return _DEFAULT_LEVEL
    try:
        n = int(float(raw))
    except (TypeError, ValueError, OverflowError):
        return _DEFAULT_LEVEL
    return max(_MIN_LEVEL, min(_MAX_LEVEL, n))


def _parse_float(raw: str, default: float = 0.0) -> float:
    """Parse a non-negative FINITE float; fall to default otherwise.

    inf is rejected too: it previously slipped the >= 0 gate and blew up
    math.ceil in _compute_ttk (OverflowError -> spurious 503); nan/inf
    also serialize to non-standard JSON browsers reject.
    """
    if not raw:
        return default
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(v):
        return default
    return v if v >= 0.0 else default


def _cache_key(
    champion: str,
    level: int,
    items: list[str],
    seq: list[str],
    target_armor: float,
    target_mr: float,
    target_max_hp: float,
    target_bonus_hp: float,
    mode: str,
    runes: list[int],
) -> tuple:
    return (
        champion,
        level,
        tuple(items),
        tuple(seq),
        round(target_armor, 2),
        round(target_mr, 2),
        round(target_max_hp, 2),
        round(target_bonus_hp, 2),
        mode,
        tuple(runes),
    )


def _compute_ttk(total_mitigated: float, duration_s: float, target_hp: float) -> dict:
    """T2-F3 headline time-to-kill block (docs/COMPETITOR_LIFT_2026-06-08.md
    lines 114-121).

    Derives a sustained DPS + time-to-kill / rotations-to-kill headline from
    the combo's mitigated total against the target's effective HP. PURELY
    DERIVED over values the route already computes - the ``totals`` block and
    every other field stay byte-identical; this is an ADDITIVE readout.

    ``target_hp`` is the target's effective HP (the ``target_max_hp`` request
    param; %-HP scaling already folded into the per-hit mitigated damage by
    compute_combo). ``total_mitigated`` is one full combo rotation's
    post-mitigation damage; ``duration_s`` is that rotation's clock length.

    Fields:
      * ``available``  - True only when target_hp > 0 AND the combo deals
        damage AND the rotation has a positive duration; otherwise the TTK
        is undefined and the numeric fields are null (stable shape, no math
        on a degenerate input).
      * ``target_hp``  - echo of the effective HP used (0.0 when absent).
      * ``combo_mitigated`` - one rotation's mitigated damage.
      * ``dps``        - sustained damage per second (mitigated / duration),
        the continuous-combat rate simulator tool R reports.
      * ``rotations_to_kill`` - ceil(target_hp / combo_mitigated): whole
        combo rotations needed to remove the target's effective HP.
      * ``ttk_s``      - target_hp / dps: continuous-DPS seconds-to-kill.
      * ``lethal``     - True when a single rotation removes >= target_hp.
    """
    available = (
        target_hp > 0.0 and total_mitigated > 0.0 and duration_s > 0.0
    )
    if not available:
        return {
            "available":         False,
            "target_hp":         round(float(max(0.0, target_hp)), 1),
            "combo_mitigated":   round(float(max(0.0, total_mitigated)), 1),
            "dps":               None,
            "rotations_to_kill": None,
            "ttk_s":             None,
            "lethal":            False,
        }
    dps = total_mitigated / duration_s
    rotations = int(math.ceil(target_hp / total_mitigated))
    ttk_s = target_hp / dps
    return {
        "available":         True,
        "target_hp":         round(float(target_hp), 1),
        "combo_mitigated":   round(float(total_mitigated), 1),
        "dps":               round(float(dps), 1),
        "rotations_to_kill": rotations,
        "ttk_s":             round(float(ttk_s), 2),
        "lethal":            total_mitigated >= target_hp,
    }


def _hit_to_dict(hit) -> dict:
    return {
        "index":       int(hit.index),
        "action":      hit.action,
        "ability_key": hit.ability_key,
        "is_ability":  bool(hit.is_ability),
        "form_name":   hit.form_name,
        "rank":        int(hit.rank),
        "t":           round(float(hit.t), 3),
        "cast_time":   round(float(hit.cast_time), 3),
        "cooldown_s":  round(float(hit.cooldown_s), 2),
        "damage_type": hit.damage_type,
        "raw":         round(float(hit.raw), 1),
        "mitigated":   round(float(hit.mitigated), 1),
        "cumulative":  round(float(hit.cumulative), 1),
        "status":      hit.status,
        "note":        hit.note,
    }


def _compute(
    champion: str,
    level: int,
    items: list[str],
    seq: list[str],
    target_armor: float,
    target_mr: float,
    target_max_hp: float,
    target_bonus_hp: float,
    mode: str,
    runes: list[int],
) -> dict:
    """Build the response payload from scratch (no cache)."""
    from agents.daemon_slayer.combo import compute_combo

    result = compute_combo(
        champion,
        level,
        item_ids=items,
        sequence=seq,
        target_armor=target_armor,
        target_mr=target_mr,
        target_max_hp=target_max_hp,
        target_bonus_hp=target_bonus_hp,
        mode=mode,
        runes=runes or None,
    )
    hits = [_hit_to_dict(h) for h in result.hits]
    return {
        "ok":            True,
        "champion":      result.champion,
        "champion_name": result.champion_name,
        "level":         result.level,
        "mode":          result.mode,
        "sequence":      list(result.sequence),
        "hits":          hits,
        "totals": {
            "total_raw":       round(float(result.total_raw), 1),
            "total_mitigated": round(float(result.total_mitigated), 1),
            "duration_s":      round(float(result.duration_s), 3),
        },
        # T2-F3: additive headline TTK block derived from totals vs the
        # target's effective HP (target_max_hp). totals above stay
        # byte-identical; ttk is purely derived.
        "ttk": _compute_ttk(
            float(result.total_mitigated),
            float(result.duration_s),
            float(target_max_hp),
        ),
        "notes":         list(result.notes),
        "count":         len(hits),
    }


def _serve_ds_combo(h) -> None:
    """GET /api/ds-combo handler."""
    t0 = time.time()
    try:
        qs = parse_qs(urlparse(h.path).query or "", keep_blank_values=True)

        champion = (qs.get("champion") or [""])[0].strip()
        seq_raw = (qs.get("seq") or [""])[0].strip()
        if not champion or "champion" not in qs:
            h._send(400, json.dumps({
                "ok":    False,
                "error": "champion param required",
            }).encode("utf-8"), "application/json")
            return
        if "seq" not in qs or not seq_raw:
            h._send(400, json.dumps({
                "ok":    False,
                "error": "seq param required",
            }).encode("utf-8"), "application/json")
            return

        # 2026-06-10: the active-match combo host passes the coach
        # payload's champion verbatim - a Live Client DISPLAY name
        # ("Tahm Kench"). The combo engine keys canonical DDragon ids;
        # bridge here so multi-word champs resolve. Canonical ids
        # (champ-select callers) pass through unchanged.
        try:
            from core.archetype_picks import canonical_champion_id
            champion = canonical_champion_id(champion) or champion
        except Exception:
            pass

        level = _parse_level((qs.get("level") or [""])[0].strip())
        items = _parse_items((qs.get("items") or [""])[0].strip())
        seq = _parse_seq(seq_raw)
        target_armor = _parse_float((qs.get("target_armor") or [""])[0].strip())
        target_mr = _parse_float((qs.get("target_mr") or [""])[0].strip())
        target_max_hp = _parse_float((qs.get("target_max_hp") or [""])[0].strip())
        target_bonus_hp = _parse_float(
            (qs.get("target_bonus_hp") or [""])[0].strip()
        )
        # Uppercase like every sibling route: the engine compares
        # mode == "ARAM" case-sensitively (burst.py / dps.py), so a
        # lowercase mode=aram silently skipped the ARAM multiplier.
        mode = (qs.get("mode") or ["SR"])[0].strip().upper() or "SR"
        # runes= is the canonical comma-separated id list; keystone= is a
        # convenience single-id alias. Both feed the same rune_procs path;
        # malformed tokens are dropped (never a 500) and an empty result is
        # byte-identical to the no-runes default.
        runes = _parse_runes((qs.get("runes") or [""])[0].strip())
        runes += _parse_runes((qs.get("keystone") or [""])[0].strip())

        if not seq:
            payload = {
                "ok":         False,
                "reason":     "empty_sequence",
                "champion":   champion,
                "hits":       [],
                "totals":     {
                    "total_raw": 0.0, "total_mitigated": 0.0,
                    "duration_s": 0.0,
                },
                # T2-F3: stable shape - an empty sequence deals no damage so
                # the headline TTK is unavailable.
                "ttk":        _compute_ttk(0.0, 0.0, target_max_hp),
                "count":      0,
                "elapsed_ms": int((time.time() - t0) * 1000),
                "cached":     False,
            }
            h._send(200, json.dumps(payload).encode("utf-8"),
                    "application/json")
            return

        key = _cache_key(
            champion, level, items, seq, target_armor, target_mr,
            target_max_hp, target_bonus_hp, mode, runes,
        )
        now = time.time()
        with _CACHE_LOCK:
            cached = _CACHE.get(key)
            if cached and (now - cached[0]) < _CACHE_TTL_S:
                payload = dict(cached[1])
                payload["cached"] = True
                payload["elapsed_ms"] = int((time.time() - t0) * 1000)
                h._send(200, json.dumps(payload).encode("utf-8"),
                        "application/json")
                return

        try:
            payload = _compute(
                champion, level, items, seq, target_armor, target_mr,
                target_max_hp, target_bonus_hp, mode, runes,
            )
        except ImportError as exc:
            log.warning("api/ds-combo import: %s", exc)
            h._send(503, json.dumps({
                "ok":    False,
                "error": "DS engine unavailable",
            }).encode("utf-8"), "application/json")
            return
        except Exception as exc:
            log.warning("api/ds-combo compute: %s", exc)
            h._send(503, json.dumps({
                "ok":    False,
                "error": "DS engine compute failed",
            }).encode("utf-8"), "application/json")
            return

        with _CACHE_LOCK:
            _CACHE[key] = (now, dict(payload))

        payload["cached"] = False
        payload["elapsed_ms"] = int((time.time() - t0) * 1000)
        h._send(200, json.dumps(payload).encode("utf-8"),
                "application/json")

    except Exception as exc:
        log.warning("api/ds-combo: %s", exc)
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
    (equals("/api/ds-combo"), _serve_ds_combo),
]

POST_ROUTES: list = []
