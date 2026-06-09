# arch: cc_conditional ally-pairing panel backend | section=dashboard | frozen=no
"""GET /api/cc-pairing - which ally conditional CC a teammate can set up.

CS1 (operator batch 2026-06-08). Thin dashboard wire over
``agents.daemon_slayer.cc_pairing.compute_cc_pairing`` - a read-only JOIN
of the existing ``cc_conditional`` registry that surfaces, for the
operator's OWN roster, each conditional CC entry whose condition an ALLY
can set up (dual_enemy / debuffed_target / terrain / traverse), the
plausible enabler teammates, and a human-readable setup hint. NO new
compute, NO ENGINE math change, NO schema lift; the join lives entirely
in the engine module.

Sibling of ``routes_cooldown_watch.py`` (same cache + fail-soft + status
discipline) and ``routes_cc_conditional_pressure.py``. Where the
cc-conditional-pressure chip ratios ally-vs-enemy CONDITIONAL CC seconds
into a single balance number, and cooldown-watch surfaces the single
highest-threat ENEMY ability, THIS route surfaces the per-entry PAIRING
data for the operator's OWN team - the gap neither existing surface fills.

Request shape:
  GET /api/cc-pairing?ally=<champ,champ,...>[&top_n=6]

  ally  : comma-separated canonical DDragon ids ("Sett", "Vex",
          "Taliyah"). Blank entries are silently skipped. Unknown ids and
          ids with no ally-enablable conditional CC contribute no card
          (compute_cc_pairing fail-softs per its contract).
  top_n : optional int cap on returned cards (default 6). Clamped to
          [0, 12]; out-of-range / non-numeric falls to 6.

Response shape:
  {
    "ok":         true,
    "cards": [
      {
        "champion":      "Vex",
        "spell":         "E",
        "spell_key":     "E",        # alias of spell for FE symmetry
        "cc_kind":       "fear",
        "cc_duration_s": 1.5,        # max-rank raw conditional CC seconds
        "condition":     "debuffed_target",
        "probability":   0.5,        # operator-tunable condition midpoint
        "setup_hint":    "fires on a debuffed target - land a teammate CC / mark first",
        "enablers":      ["Leona"]   # teammates with a hard-CC / displace tool
      },
      ...
    ],
    "count":      <int>,
    "elapsed_ms": <int>,
    "cached":     <bool>
  }

Failure modes:
  - 400  ally param literally missing (parse_qs returns no key).
  - 200  ok=false reason=no_champions when ally resolves to zero usable
         champions (blanks / empty input).
  - 503  cc_pairing import fails (DS engine module unreachable).

5-min TTL in-process cache keyed on (sorted_ally_tuple, top_n). Mirrors
routes_cooldown_watch cache discipline.

Don't-redo:
  * This route takes NO mode param: the pairing fact (which condition an
    ally can set up + who has the tools) is intrinsic to the abilities,
    not the map. ARAM tenacity scales how long the CC then locks down,
    which is a SEPARATE signal already on the cc-conditional-pressure
    chip; this route is the per-entry setup view.
  * The ally roster feeds BOTH the cards (whose conditional CC) AND the
    enabler resolution (which teammate can set it up) - they share the
    same roster by construction (a teammate is only an enabler if they
    are on the operator's team). Do NOT split the two inputs.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from urllib.parse import parse_qs, urlparse

from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

# 5-min response TTL mirrors routes_cooldown_watch exactly.
_CACHE_TTL_S = 300.0
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()

_DEFAULT_TOP_N = 6
_MAX_TOP_N = 12


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


def _cache_key(ally: list[str], top_n: int) -> tuple:
    return (tuple(sorted(ally)), top_n)


def _card_to_dict(card) -> dict:
    return {
        "champion":      card.champion,
        "spell":         card.spell,
        "spell_key":     card.spell,
        "cc_kind":       card.cc_kind,
        "cc_duration_s": round(float(card.cc_duration_s), 2),
        "condition":     card.condition,
        "probability":   round(float(card.probability), 2),
        "setup_hint":    card.setup_hint,
        "enablers":      list(card.enablers),
    }


def _compute(allies: list[str], top_n: int) -> dict:
    """Build the response payload from scratch (no cache)."""
    from agents.daemon_slayer.cc_pairing import compute_cc_pairing

    result = compute_cc_pairing(allies)
    cards = [_card_to_dict(c) for c in result.cards]
    if top_n is not None and top_n >= 0:
        cards = cards[:top_n]
    return {
        "ok":    True,
        "cards": cards,
        "count": len(cards),
    }


def _serve_cc_pairing(h) -> None:
    """GET /api/cc-pairing handler."""
    t0 = time.time()
    try:
        qs = parse_qs(urlparse(h.path).query or "", keep_blank_values=True)
        if "ally" not in qs:
            h._send(400, json.dumps({
                "ok":    False,
                "error": "ally param required",
            }).encode("utf-8"), "application/json")
            return

        ally_raw = (qs.get("ally") or [""])[0].strip()
        top_n = _parse_top_n((qs.get("top_n") or [""])[0].strip())
        ally_ids = _parse_champ_list(ally_raw)

        if not ally_ids:
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

        key = _cache_key(ally_ids, top_n)
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
            payload = _compute(ally_ids, top_n)
        except ImportError as exc:
            log.warning("api/cc-pairing import: %s", exc)
            h._send(503, json.dumps({
                "ok":    False,
                "error": "DS engine unavailable",
            }).encode("utf-8"), "application/json")
            return
        except Exception as exc:
            log.warning("api/cc-pairing compute: %s", exc)
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
        log.warning("api/cc-pairing: %s", exc)
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
    (equals("/api/cc-pairing"), _serve_cc_pairing),
]

POST_ROUTES: list = []
