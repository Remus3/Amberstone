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
  my_role          : bot | sup. Default "bot"; anything else reads "bot".
                     Drives 'none' mode.
  ally_bot_lock    : champion name | empty. Locked bot ally.
  ally_bot_hover   : champion name | empty. Hovered bot ally.
  ally_sup_lock    : champion name | empty. Locked sup ally.
  ally_sup_hover   : champion name | empty. Hovered sup ally.
  top_n            : ASCII digits (at most 6), default 4, clamped to 1..4.

Trust boundary (S144-T-601): this is a GET route on :8888, so a LAN peer
reaches it with any query. A champion value, once ASCII blanks are stripped,
is empty (absent) or 1-32 characters of ASCII letters, digits, space,
apostrophe, period and ampersand, starting with a letter or digit - every
DDragon name and display name ("Kai'Sa", "Dr. Mundo", "Nunu & Willump")
fits. A champion value outside that shape is a 400 "<param>_invalid", and a
top_n that is not ASCII digits a 400 "top_n_invalid"; a refusal never echoes
the value and is checked before the cache or the seed is touched. A
non-finite rate in a cell is served as null (rank 0), and every 200 body is
dumped with allow_nan=False, so the browser never meets a bare NaN token.

The 101.qq.com live feed no longer drives the lobby with locks: the live
client (web/js/panels/lobby_duo_synergy.js) sends only my_role and top_n.
The lock / hover parameters stay for any caller that wants a pairing.

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

Cache: 5s TTL keyed on the full query tuple, timed on the monotonic
clock (a wall clock stepped back must not extend it).
"""
from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from core import smoothed_rates_101qq as _ssq
from core.log_scrub import scrub_log
from dashboard._dispatch import equals
from dashboard._errors import send_error

log = logging.getLogger("rc.web_dashboard")

# S144-T-601: query shapes checked at the trust boundary.
_CHAMP_PARAMS = ("ally_bot_lock", "ally_bot_hover", "ally_sup_lock",
                 "ally_sup_hover")
# Explicit ASCII classes (no \w, no re.IGNORECASE folding); fullmatch, so a
# trailing newline is not absorbed by "$".
_CHAMP_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 '.&]{0,31}")
_TOP_N_RE = re.compile(r"[0-9]{1,6}")
# Only ASCII blanks are stripped: str.strip() would also eat U+3000 and the
# other Unicode spaces, letting a non-ASCII value through the shape check.
_ASCII_BLANKS = " \t\r\n\f\v"

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
    {default: str, pairs: {key: str}}. Empty defaults on missing/garbage.

    Read once per process: an edit to the file takes effect on the next
    RC restart. A non-string "default" reads as no default (it used to be
    rendered with str(), so a list showed as "['x', 1]"); a non-string
    pair value is dropped."""
    global _TIPS_CACHE
    with _TIPS_LOCK:
        if _TIPS_CACHE is not None:
            return _TIPS_CACHE
        out = {"default": "", "pairs": {}}
        try:
            raw = json.loads(_TIPS_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                default = raw.get("default")
                out["default"] = default if isinstance(default, str) else ""
                pairs = raw.get("pairs")
                if isinstance(pairs, dict):
                    out["pairs"] = {str(k): str(v) for k, v in pairs.items()
                                    if isinstance(v, str)}
        # RM-291A: UnicodeDecodeError is a ValueError, not an OSError.
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
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


class _BadQuery(ValueError):
    """A query value outside its shape. ``code`` is the fixed, server-authored
    400 error string; the offending value is never carried."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _first(qs: dict, key: str) -> str:
    raw = qs.get(key)
    if not raw:
        return ""
    val = raw[0] if isinstance(raw, list) else raw
    return val if isinstance(val, str) else ""


def _qs_champ(qs: dict, key: str) -> str:
    """A champion parameter: "" when absent or blank, else the stripped
    value when it fits ``_CHAMP_RE``; anything else raises ``_BadQuery``."""
    val = _first(qs, key).strip(_ASCII_BLANKS)
    if not val:
        return ""
    if not _CHAMP_RE.fullmatch(val):
        raise _BadQuery(f"{key}_invalid")
    return val


def _qs_top_n(qs: dict) -> int:
    """top_n: absent or blank reads the default; ASCII digits are clamped to
    1.._MAX_TOP_N; anything else (a sign, "1_1", non-ASCII digits) raises
    ``_BadQuery``. int() alone accepted all of those."""
    val = _first(qs, "top_n").strip(_ASCII_BLANKS)
    if not val:
        return _DEFAULT_TOP_N
    if not _TOP_N_RE.fullmatch(val):
        raise _BadQuery("top_n_invalid")
    return max(1, min(int(val), _MAX_TOP_N))


def _r4(value):
    """A cell rate: an int as it is, a finite float rounded to 4 places,
    anything else (NaN, an infinity, a non-number) None - the client renders
    None as "-", while a bare NaN token fails its JSON.parse."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return round(value, 4)
    return None


def _rank(value) -> int:
    """A solo cell rank: the rounded median, or 0 (the payload's "unknown"
    rank) when it is not a finite number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    if isinstance(value, float) and not math.isfinite(value):
        return 0
    return round(value)


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
        "rank":          _rank(rec.rank),
        "iwinrate":      _r4(rec.iwinrate),
        "itemp":         _r4(rec.itemp),
        "pair_with":     None,
        "pair_with_key": None,
        "doublewinrate": None,
        "smoothed_rate": _r4(rec.smoothed_rate),
    }


def _duo_to_cell(rec, *, partner_side: str) -> dict:
    """DuoRec -> JSON cell dict.

    partner_side='sup' means this cell IS the bot and 'pair_with' is the sup.
    partner_side='bot' means this cell IS the sup and 'pair_with' is the bot.

    itemp is the PAIR's play-rate share on both cells: the seed carries one
    (itemp1) per pairing, none per support."""
    if partner_side == "sup":
        # This cell is the bot; partner is the sup.
        return {
            "champ":         rec.bot,
            "champ_key":     rec.bot_id,
            "icon_id":       rec.bot_id,
            "rank":          rec.irank,
            "iwinrate":      _r4(rec.iwinrate_bot),
            "itemp":         _r4(rec.itemp_bot),
            "pair_with":     rec.sup,
            "pair_with_key": rec.sup_id,
            "doublewinrate": _r4(rec.doublewinrate),
            "smoothed_rate": _r4(rec.smoothed_rate),
        }
    # partner_side == "bot": this cell is the sup; partner is the bot.
    return {
        "champ":         rec.sup,
        "champ_key":     rec.sup_id,
        "icon_id":       rec.sup_id,
        "rank":          rec.irank,
        "iwinrate":      _r4(rec.iwinrate_sup),
        "itemp":         _r4(rec.itemp_bot),
        "pair_with":     rec.bot,
        "pair_with_key": rec.bot_id,
        "doublewinrate": _r4(rec.doublewinrate),
        "smoothed_rate": _r4(rec.smoothed_rate),
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


def _health_block() -> dict:
    """RM-416: freshness of the served snapshot, or a degraded marker.

    `_ssq.health()` is JSON-safe by contract (RM-295a) and is embedded
    verbatim plus `available: True`, so `last_refresh_ok` / `stale_for_s`
    and the adopted `coverage()` block reach a served route. A diagnostic
    must never take the grid down with it: any failure here yields a
    friendly marker, the raw error goes to the log only (CLAUDE.md Error
    Handling), and the rows are still served with a 200.
    """
    try:
        block = dict(_ssq.health())
        block["available"] = True
        # S144-T-601: the 200 body is dumped with allow_nan=False, so a
        # block that is not strict JSON degrades HERE instead of turning
        # the whole grid into a 500.
        json.dumps(block, allow_nan=False)
    except Exception as exc:  # noqa: BLE001
        log.warning("api/duo-synergy: health unavailable: %s: %s",
                    type(exc).__name__, scrub_log(str(exc)))
        return {"available": False,
                "message": "freshness unavailable - see logs"}
    return block


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
        # The tips file is keyed by the seed's DDragon names; the lookup
        # resolves case-insensitively, so key a resolved pair by ITS names,
        # not the caller's spelling ("jinx" used to miss "Jinx:Senna").
        tip_bot, tip_sup = bot_lock, sup_lock
        if pair is not None:
            tip_bot, tip_sup = pair.bot, pair.sup
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
        laning_tips = _laning_tips_for(tip_bot, tip_sup)

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
        # RM-416: also a response key - see _health_block() for its shape.
        "health":      _health_block(),
    }


def _serve_duo_synergy(h) -> None:
    """GET /api/duo-synergy - route entry point."""
    # Monotonic clocks: a wall clock stepped back used to keep a cached grid
    # alive for the whole step and could report a negative elapsed_ms.
    t0 = time.perf_counter()
    try:
        qs = parse_qs(urlparse(h.path).query or "")
        my_role = _qs_str(qs, "my_role", "bot").lower()
        if my_role not in ("bot", "sup"):
            my_role = "bot"
        try:
            bot_lock, bot_hover, sup_lock, sup_hover = (
                _qs_champ(qs, key) for key in _CHAMP_PARAMS)
            top_n = _qs_top_n(qs)
        except _BadQuery as bad:
            # A fixed code, never the value; nothing cached, seed untouched.
            h._send(400, json.dumps({"ok": False, "error": bad.code})
                    .encode("utf-8"), "application/json")
            return

        cache_key = (my_role, bot_lock, bot_hover, sup_lock, sup_hover, top_n)
        now = time.monotonic()
        with _CACHE_LOCK:
            cached = _CACHE.get(cache_key)
            if cached and 0.0 <= (now - cached[0]) < _CACHE_TTL_S:
                payload = dict(cached[1])
                payload["cached"] = True
                payload["elapsed_ms"] = _elapsed_ms(t0)
                h._send(200, json.dumps(payload, allow_nan=False)
                        .encode("utf-8"), "application/json")
                return

        payload = _build_payload(my_role, bot_lock, bot_hover, sup_lock,
                                 sup_hover, top_n)
        payload["cached"] = False
        payload["elapsed_ms"] = _elapsed_ms(t0)
        # allow_nan=False: a non-finite number the cell helpers did not see
        # raises here and becomes the fixed 500 below (and is not cached),
        # instead of a 200 whose bare NaN token the browser rejects.
        body = json.dumps(payload, allow_nan=False).encode("utf-8")

        cacheable = dict(payload)
        cacheable.pop("cached", None)
        cacheable.pop("elapsed_ms", None)
        _cache_put(cache_key, now, cacheable)

        h._send(200, body, "application/json")
    except Exception as exc:  # noqa: BLE001
        # RM-835: a fixed body; send_error logs the cause once, scrubbed,
        # with its type name and the traceback.
        try:
            send_error(h, exc, fields={"ok": False}, log_traceback=True)
        except Exception:  # noqa: BLE001
            pass


def _elapsed_ms(t0: float) -> int:
    return max(0, int((time.perf_counter() - t0) * 1000))


GET_ROUTES = [
    (equals("/api/duo-synergy"), _serve_duo_synergy),
]
