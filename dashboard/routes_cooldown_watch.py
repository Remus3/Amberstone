# arch: cooldown-watch panel backend | section=dashboard | frozen=no
"""GET /api/cooldown-watch - enemy CC threat joined to ability cooldown.

Competitor lift #5 (DEPTH spec docs/COMPETITOR_LIFT_2026-05-30.md). Thin
dashboard wire over ``agents.daemon_slayer.cooldown_watch.compute_cooldown_watch``
- a read-only JOIN of the CC threat registries to per-rank ability
cooldowns from champion_abilities.json. NO new compute, NO ENGINE math
change, NO schema lift; the math seam already exists in the engine module.

Sibling of ``routes_cc_conditional_pressure.py`` - the cooldown-watch card
is the per-spell "watch their <spell> - <Ns>" surface that the aggregate
cc-conditional-pressure chip does not expose. Where that chip ratios ally
vs enemy CONDITIONAL CC seconds, this route surfaces, per enemy champion,
the single highest-threat hard-CC ability + its max-rank base cooldown.

Request shape:
  GET /api/cooldown-watch?enemy=<champ,champ,...>[&top_n=5]

  enemy : comma-separated canonical DDragon ids ("Blitzcrank", "Leona",
          "Aatrox"). Blank entries are silently skipped. Unknown ids and
          ids with no registered first-order CC contribute no card
          (compute_cooldown_watch fail-softs per its contract).
  top_n : optional int cap on returned cards (default 5 = one per enemy).
          Clamped to [0, 10]; out-of-range / non-numeric falls to 5.

Response shape:
  {
    "ok":         true,
    "cards": [
      {
        "champion":         "Blitzcrank",
        "spell_key":        "Q",
        "spell_name":       "Rocket Grab",
        "cc_kind":          "",          # "" for unconditional CC
        "cc_duration_s":    1.0,         # max-rank hard-CC seconds
        "cooldown_s":       16.0,        # max-rank base cooldown
        "cooldown_by_rank": [20,19,18,17,16],
        "conditional":      false,
        "probability":      1.0          # conditional midpoint; 1.0 if not
      },
      ...
    ],
    "count":      <int>,
    "elapsed_ms": <int>,
    "cached":     <bool>
  }

Failure modes:
  - 400  enemy param literally missing (parse_qs returns no key).
  - 200  ok=false reason=no_champions when enemy resolves to zero usable
         champions (blanks / empty input).
  - 503  cooldown_watch import fails (DS engine module unreachable).

5-min TTL in-process cache keyed on (sorted_enemy_tuple, top_n). Mirrors
routes_cc_conditional_pressure cache discipline.

Don't-redo:
  * Cooldown is BASE cd by rank, NOT haste-adjusted - RC has no live enemy
    ability haste in champ-select; base-cd-by-rank is the honest v1 (see
    the engine module docstring). summoner_cooldowns on /api/state is a
    separate summoner+ult layer; this route is the Q/W/E base layer.
  * This route takes NO mode param: the CC threat + cooldown are intrinsic
    to the ability; ARAM tenacity scales incoming CC on the modified champ,
    not the enemy's outgoing ability fact (engine module is mode-agnostic).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from urllib.parse import parse_qs, urlparse

from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

# 5-min response TTL mirrors routes_cc_conditional_pressure exactly.
_CACHE_TTL_S = 300.0
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()

_DEFAULT_TOP_N = 5
_MAX_TOP_N = 10


def _parse_champ_list(raw: str) -> list[str]:
    """Split a comma-separated DDragon-id list, strip blanks."""
    if not raw:
        return []
    out: list[str] = []
    for part in raw.split(","):
        s = part.strip()
        if s:
            out.append(s)
    return out


def _parse_top_n(raw: str) -> int:
    """Parse the top_n cap; clamp to [0, _MAX_TOP_N]; fall to default."""
    if not raw:
        return _DEFAULT_TOP_N
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_TOP_N
    if n < 0:
        return _DEFAULT_TOP_N
    return min(n, _MAX_TOP_N)


def _cache_key(enemy: list[str], top_n: int) -> tuple:
    return (tuple(sorted(enemy)), top_n)


def _card_to_dict(card) -> dict:
    return {
        "champion":         card.champion,
        "spell_key":        card.spell_key,
        "spell_name":       card.spell_name,
        "cc_kind":          card.cc_kind,
        "cc_duration_s":    round(float(card.cc_duration_s), 2),
        "cooldown_s":       round(float(card.cooldown_s), 1),
        "cooldown_by_rank": [round(float(x), 1) for x in card.cooldown_by_rank],
        "conditional":      bool(card.conditional),
        "probability":      round(float(card.probability), 2),
    }


def _compute(enemies: list[str], top_n: int) -> dict:
    """Build the response payload from scratch (no cache)."""
    from agents.daemon_slayer.cooldown_watch import compute_cooldown_watch

    result = compute_cooldown_watch(enemies, top_n=top_n)
    cards = [_card_to_dict(c) for c in result.cards]
    return {
        "ok":    True,
        "cards": cards,
        "count": len(cards),
    }


def _serve_cooldown_watch(h) -> None:
    """GET /api/cooldown-watch handler."""
    t0 = time.time()
    try:
        qs = parse_qs(urlparse(h.path).query or "", keep_blank_values=True)
        if "enemy" not in qs:
            h._send(400, json.dumps({
                "ok":    False,
                "error": "enemy param required",
            }).encode("utf-8"), "application/json")
            return

        enemy_raw = (qs.get("enemy") or [""])[0].strip()
        top_n = _parse_top_n((qs.get("top_n") or [""])[0].strip())
        enemy_ids = _parse_champ_list(enemy_raw)

        if not enemy_ids:
            payload = {
                "ok":         False,
                "reason":     "no_champions",
                "cards":      [],
                "count":      0,
                "elapsed_ms": int((time.time() - t0) * 1000),
                "cached":     False,
            }
            h._send(200, json.dumps(payload).encode("utf-8"),
                    "application/json")
            return

        key = _cache_key(enemy_ids, top_n)
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
            payload = _compute(enemy_ids, top_n)
        except ImportError as exc:
            log.warning("api/cooldown-watch import: %s", exc)
            h._send(503, json.dumps({
                "ok":    False,
                "error": "DS engine unavailable",
            }).encode("utf-8"), "application/json")
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("api/cooldown-watch compute: %s", exc)
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

    except Exception as exc:  # noqa: BLE001
        log.warning("api/cooldown-watch: %s", exc)
        try:
            h._send(500, json.dumps({
                "ok": False, "error": str(exc)[:200],
            }).encode("utf-8"), "application/json")
        except Exception:  # noqa: BLE001
            pass


def _reset_caches() -> None:
    """Test-only: clear response cache."""
    with _CACHE_LOCK:
        _CACHE.clear()


GET_ROUTES = [
    (equals("/api/cooldown-watch"), _serve_cooldown_watch),
]

POST_ROUTES: list = []
