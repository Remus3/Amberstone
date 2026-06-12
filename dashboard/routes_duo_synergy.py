# arch: 101.qq duo-synergy backend | section=dashboard | frozen=no
"""GET /api/duo-synergy - bot+sup pairing recommendations from 101.qq seed.

Item 199 Slice CD (2026-05-25). Powers the champ-select view's new
duo-lane panel that replaces the EXPLANATION sub-panel of the item-168
Pick & Ban 3-panel stack. The panel is a 4 x 2 grid:

  Top row = bottom-role champions (ADCs).
  Bottom row = support champions.
  Highest-ranking = LEFTMOST.

Lock-vs-hover resolution priority (highest first):

  both_locked   bot AND sup locked.   single icon per row + laning tips.
  bot_locked    bot locked, sup not.  top=that one bot, bot=top 4 sups.
  sup_locked    sup locked, bot not.  bot=that one sup, top=top 4 bots.
  bot_hover     bot hover, no locks.  same as bot_locked but hover source.
  sup_hover     sup hover, no locks.  same as sup_locked but hover source.
  none          nothing locked/hover. default to my_role's top 4 solo picks.

The 'none' mode populates the row matching `my_role` with the operator's
top-4 solo picks for that role; the OTHER row shows top-4 solos for
the partner role. So 'my_role=bot' surfaces "best bots" up top + "best
sups" bottom by aggregated metric. Operator sees both lanes when nothing
locked yet so they can reason about pairings before committing.

Query params:
  my_role          : bot | sup. Default "bot". Drives 'none' mode.
  ally_bot_lock    : champion name | empty. Locked bot ally.
  ally_bot_hover   : champion name | empty. Hovered bot ally.
  ally_sup_lock    : champion name | empty. Locked sup ally.
  ally_sup_hover   : champion name | empty. Hovered sup ally.
  top_n            : int, default 4, max 4 (UI grid).

Response:
  {
    "ok":     true,
    "mode":   "none" | "bot_locked" | "bot_hover" |
              "sup_locked" | "sup_hover" | "both_locked",
    "top_row":    [{cell, ...}, ...],   bot-role cells
    "bottom_row": [{cell, ...}, ...],   sup-role cells
    "laning_tips": str | None,           populated only when both_locked
    "cached": bool,
    "elapsed_ms": int
  }

Cell shape:
  {
    "champ":            "Jinx",
    "champ_key":        222,           DDragon numeric key
    "icon_id":          222,            alias for JS img helper
    "rank":             1,              irank from seed (or aggregated median)
    "iwinrate":         0.5373,         solo WR for the role
    "itemp":            0.0478,         play-rate share
    "pair_with":        "Senna" | None, the partner champ this rec pairs against
    "pair_with_key":    235  | None,
    "doublewinrate":    0.5653 | None,  joint WR; None when no specific pair
    "smoothed_rate":    0.5644          Laplace-smoothed pair rate
  }

Cache: 5s TTL keyed on the full query tuple.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urlparse

from core import smoothed_rates_101qq as _ssq
from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

# Cache parameters.
_CACHE_TTL_S = 5.0
_DEFAULT_TOP_N = 4
_MAX_TOP_N = 4

# Cache: tuple key -> (cached_at, payload).
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
# Cycle-8 audit: keys embed free-form hover/lock name strings from the
# query, so the dict could grow without bound across a long uptime
# (entries were never evicted - TTL only gates serving). Cap+drop-oldest.
_CACHE_MAX = 256
_CACHE_EVICT = 64


def _cache_put(key: tuple, now: float, payload: dict) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (now, payload)
        if len(_CACHE) > _CACHE_MAX:
            victims = sorted(_CACHE.items(),
                             key=lambda kv: kv[1][0])[:_CACHE_EVICT]
            for k, _ in victims:
                _CACHE.pop(k, None)

# Laning tips file (operator-tunable).
_TIPS_PATH = Path(__file__).resolve().parent.parent / "data" / "laning_tips_duo.json"
_TIPS_CACHE: dict | None = None
_TIPS_LOCK = threading.RLock()


def _load_tips() -> dict:
    """Lazy-load + cache the laning tips JSON. Returns
    {default: str, pairs: {key: str}}. Empty defaults on missing/garbage."""
    global _TIPS_CACHE
    with _TIPS_LOCK:
        if _TIPS_CACHE is not None:
            return _TIPS_CACHE
        out = {"default": "", "pairs": {}}
        try:
            raw = json.loads(_TIPS_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                out["default"] = str(raw.get("default") or "")
                pairs = raw.get("pairs")
                if isinstance(pairs, dict):
                    out["pairs"] = {str(k): str(v) for k, v in pairs.items()
                                    if isinstance(v, str)}
        except (OSError, json.JSONDecodeError):
            pass
        _TIPS_CACHE = out
        return out


def _reset_caches() -> None:
    """Test-only: clear the response + tips caches."""
    global _TIPS_CACHE
    with _CACHE_LOCK:
        _CACHE.clear()
    with _TIPS_LOCK:
        _TIPS_CACHE = None


def _qs_str(qs: dict, key: str, default: str = "") -> str:
    raw = qs.get(key)
    if not raw:
        return default
    val = raw[0] if isinstance(raw, list) else raw
    return str(val or default).strip()


def _qs_int(qs: dict, key: str, default: int) -> int:
    raw = qs.get(key)
    if not raw:
        return default
    val = raw[0] if isinstance(raw, list) else raw
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _resolve_mode(bot_lock: str, bot_hover: str,
                  sup_lock: str, sup_hover: str) -> str:
    """Priority: both_locked > bot_locked > sup_locked > bot_hover > sup_hover > none.

    "both_locked" requires BOTH sides resolved. A lock on one side +
    hover on the other is treated as the lock side's mode (the locked
    pick is the firm signal; the hover may still swap)."""
    if bot_lock and sup_lock:
        return "both_locked"
    if bot_lock:
        return "bot_locked"
    if sup_lock:
        return "sup_locked"
    if bot_hover:
        return "bot_hover"
    if sup_hover:
        return "sup_hover"
    return "none"


def _solo_to_cell(rec) -> dict:
    """SoloRec -> JSON cell dict (no pair-context fields)."""
    return {
        "champ":         rec.champ,
        "champ_key":     rec.champ_id,
        "icon_id":       rec.champ_id,
        "rank":          int(round(rec.rank)),
        "iwinrate":      round(rec.iwinrate, 4),
        "itemp":         round(rec.itemp, 4),
        "pair_with":     None,
        "pair_with_key": None,
        "doublewinrate": None,
        "smoothed_rate": round(rec.smoothed_rate, 4),
    }


def _duo_to_cell(rec, *, partner_side: str) -> dict:
    """DuoRec -> JSON cell dict.

    partner_side='sup' means this cell IS the bot and 'pair_with' is the sup.
    partner_side='bot' means this cell IS the sup and 'pair_with' is the bot."""
    if partner_side == "sup":
        # This cell is the bot; partner is the sup.
        return {
            "champ":         rec.bot,
            "champ_key":     rec.bot_id,
            "icon_id":       rec.bot_id,
            "rank":          rec.irank,
            "iwinrate":      round(rec.iwinrate_bot, 4),
            "itemp":         round(rec.itemp_bot, 4),
            "pair_with":     rec.sup,
            "pair_with_key": rec.sup_id,
            "doublewinrate": round(rec.doublewinrate, 4),
            "smoothed_rate": round(rec.smoothed_rate, 4),
        }
    # partner_side == "bot": this cell is the sup; partner is the bot.
    return {
        "champ":         rec.sup,
        "champ_key":     rec.sup_id,
        "icon_id":       rec.sup_id,
        "rank":          rec.irank,
        "iwinrate":      round(rec.iwinrate_sup, 4),
        "itemp":         round(rec.itemp_bot, 4),
        "pair_with":     rec.bot,
        "pair_with_key": rec.bot_id,
        "doublewinrate": round(rec.doublewinrate, 4),
        "smoothed_rate": round(rec.smoothed_rate, 4),
    }


def _laning_tips_for(bot: str, sup: str) -> str | None:
    """Lookup hardcoded tips for a bot+sup pair. Falls through to the
    'default' field if the specific pair isn't mapped."""
    tips = _load_tips()
    key = f"{bot}:{sup}"
    specific = tips["pairs"].get(key)
    if specific:
        return specific
    return tips["default"] or None


def _build_payload(my_role: str, bot_lock: str, bot_hover: str,
                   sup_lock: str, sup_hover: str, top_n: int) -> dict:
    """Pure builder - no HTTP / no caching. Returns the response dict
    (without cached / elapsed_ms which are stamped by the route)."""
    mode = _resolve_mode(bot_lock, bot_hover, sup_lock, sup_hover)
    n = max(1, min(int(top_n), _MAX_TOP_N))
    top_row: list[dict] = []
    bottom_row: list[dict] = []
    laning_tips: str | None = None

    if mode == "both_locked":
        # 1-cell top + 1-cell bottom + tips for the specific pair.
        bot_id = _ssq._resolve_id(bot_lock)
        sup_id = _ssq._resolve_id(sup_lock)
        pair = _ssq.pair_synergy(bot_lock, sup_lock)
        if pair is not None:
            top_row.append(_duo_to_cell(pair, partner_side="sup"))
            bottom_row.append(_duo_to_cell(pair, partner_side="bot"))
        else:
            # Pair not in coverage - render generic solo cells so the
            # grid stays populated. iwinrate/itemp 0.0 as "unknown".
            top_row.append({
                "champ": bot_lock, "champ_key": bot_id, "icon_id": bot_id,
                "rank": 0, "iwinrate": 0.0, "itemp": 0.0,
                "pair_with": sup_lock, "pair_with_key": sup_id,
                "doublewinrate": None, "smoothed_rate": 0.5,
            })
            bottom_row.append({
                "champ": sup_lock, "champ_key": sup_id, "icon_id": sup_id,
                "rank": 0, "iwinrate": 0.0, "itemp": 0.0,
                "pair_with": bot_lock, "pair_with_key": bot_id,
                "doublewinrate": None, "smoothed_rate": 0.5,
            })
        laning_tips = _laning_tips_for(bot_lock, sup_lock)

    elif mode in ("bot_locked", "bot_hover"):
        # The bot champion is committed/hovered; top row shows just it,
        # bottom row shows the top-N supports paired with it.
        bot_champ = bot_lock or bot_hover
        bot_id = _ssq._resolve_id(bot_champ)
        # Top row: 1 cell = the bot itself.
        top_row.append({
            "champ": bot_champ, "champ_key": bot_id, "icon_id": bot_id,
            "rank": 0, "iwinrate": 0.0, "itemp": 0.0,
            "pair_with": None, "pair_with_key": None,
            "doublewinrate": None, "smoothed_rate": 0.5,
        })
        # Bottom row: top-N supports paired against this bot.
        duos = _ssq.top_duos_for_bot(bot_champ, top_n=n)
        for d in duos:
            bottom_row.append(_duo_to_cell(d, partner_side="bot"))

    elif mode in ("sup_locked", "sup_hover"):
        # The sup champion is committed/hovered; bottom row shows just
        # it, top row shows the top-N bots paired with it.
        sup_champ = sup_lock or sup_hover
        sup_id = _ssq._resolve_id(sup_champ)
        bottom_row.append({
            "champ": sup_champ, "champ_key": sup_id, "icon_id": sup_id,
            "rank": 0, "iwinrate": 0.0, "itemp": 0.0,
            "pair_with": None, "pair_with_key": None,
            "doublewinrate": None, "smoothed_rate": 0.5,
        })
        duos = _ssq.top_duos_for_sup(sup_champ, top_n=n)
        for d in duos:
            top_row.append(_duo_to_cell(d, partner_side="sup"))

    else:
        # mode == "none". Default to operator's role -> top-N solos in
        # that role; other row = top-N solos in the partner role.
        bot_solos = _ssq.top_solo_picks("bot", top_n=n)
        sup_solos = _ssq.top_solo_picks("sup", top_n=n)
        top_row = [_solo_to_cell(r) for r in bot_solos]
        bottom_row = [_solo_to_cell(r) for r in sup_solos]

    return {
        "ok":       True,
        "mode":     mode,
        "my_role":  my_role,
        "top_row":     top_row,
        "bottom_row":  bottom_row,
        "laning_tips": laning_tips,
    }


def _serve_duo_synergy(h) -> None:
    """GET /api/duo-synergy - route entry point."""
    t0 = time.time()
    try:
        qs = parse_qs(urlparse(h.path).query or "")
        my_role = _qs_str(qs, "my_role", "bot").lower()
        if my_role not in ("bot", "sup"):
            my_role = "bot"
        bot_lock = _qs_str(qs, "ally_bot_lock")
        bot_hover = _qs_str(qs, "ally_bot_hover")
        sup_lock = _qs_str(qs, "ally_sup_lock")
        sup_hover = _qs_str(qs, "ally_sup_hover")
        top_n = _qs_int(qs, "top_n", _DEFAULT_TOP_N)
        top_n = max(1, min(top_n, _MAX_TOP_N))

        cache_key = (my_role, bot_lock, bot_hover, sup_lock, sup_hover, top_n)
        now = time.time()
        with _CACHE_LOCK:
            cached = _CACHE.get(cache_key)
            if cached and (now - cached[0]) < _CACHE_TTL_S:
                payload = dict(cached[1])
                payload["cached"] = True
                payload["elapsed_ms"] = int((time.time() - t0) * 1000)
                h._send(200, json.dumps(payload).encode("utf-8"),
                        "application/json")
                return

        payload = _build_payload(my_role, bot_lock, bot_hover, sup_lock,
                                 sup_hover, top_n)
        payload["cached"] = False
        payload["elapsed_ms"] = int((time.time() - t0) * 1000)

        cacheable = dict(payload)
        cacheable.pop("cached", None)
        cacheable.pop("elapsed_ms", None)
        _cache_put(cache_key, now, cacheable)

        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:
        log.warning("api/duo-synergy: %s", exc)
        try:
            # Raw exception text stays in the log only.
            h._send(500, json.dumps(
                {"ok": False, "error": "internal error - see logs"})
                .encode("utf-8"), "application/json")
        except Exception:
            pass


GET_ROUTES = [
    (equals("/api/duo-synergy"), _serve_duo_synergy),
]
