# arch: first-purchase archetype mismatch nudge | section=core | frozen=no
"""First-purchase-mismatch soft-nudge (s184, 2026-05-13).

Closes the s176 Phase 3 deferral: when the operator picks an archetype at
champ-select (e.g. ``tank``) but their first completed item is way outside
the dispatcher's top-15 for that archetype (e.g. Infinity Edge), emit a
one-time soft nudge so the operator notices the mismatch.

Why server-side, not coach-side? The four mode coaches already dispatch
to the right scorer via ``coach_integration.archetype_dispatch`` (s182).
They get archetype-matched DS picks regardless of operator's actual buy.
The mismatch signal - "your buy doesn't match your archetype pick" - is
better surfaced as a passive UI hint than a coach prompt: the coach
operates on what the operator should buy NEXT given current state, not
what they bought a minute ago.

Design notes:

* **Per-game-session dedup.** The nudge fires at most once per
  (champion, game_session_token) pair. ``game_session_token`` comes from
  liveclient's ``gameData.gameId`` when present; falls back to a
  ``champion+start-floor`` synthetic token when liveclient doesn't expose
  one. Module-level dict cache - restart-wipes by design, matches
  ``rewind_history.db`` ephemerality for in-game state.

* **Dispatcher-driven, not hardcoded.** No item -> archetype affinity
  table. Mismatch = "first completed item not in top-15 of
  ``rank_for_primary_archetype(champion, primary, top=15)``". This means
  the bar adapts to per-champion meta - Veigar players bench AP items in
  top-15, so a non-AP item triggers; Yasuo crit IE-builds get IE in
  top-15, so IE is fine on Yasuo even though "carry" archetype generally
  prefers other items. The dispatcher already does the heavy lifting.

* **Engine-down = silent.** Dispatcher returning ``None`` (DS server
  unreachable) yields no nudge. Same fault-tolerance as the SR coach's
  DS-before-Haiku path.

* **Item filter.** Boots, Doran's, trinkets, consumables, jungle pets,
  and SR starter quest items are not signal-bearing - operator buying
  Berserker's first tells us nothing about their archetype intent.
  Hardcoded denylist of ~25 item IDs; new items added to the list as
  Riot adds them.

State shape (module-level ``_NUDGE_STATE``)::

    {
        "<champion>": {
            "session_token":   "<gameId or synthetic>",
            "phase":           "pending" | "fired" | "dismissed" | "no_mismatch",
            "first_item_id":   "<id>",        # only set after evaluation
            "first_item_name": "<name>",      # only set after evaluation
            "primary":         "<archetype>",
            "fired_at":        <epoch>,       # only set after evaluation
            "message":         "<text>",      # only set when phase=fired
            "expected_items":  ["<name>", ...] # top 3 from dispatcher, when fired
        }
    }

The state-builder calls ``compute_nudge_payload(coach, lc, lcu_snapshot,
cs_archetype_pick)`` once per /api/state and stamps the returned dict
(possibly empty) into ``state.archetype_nudge``. The dashboard reads
that field and renders a small chip near ``#ds-pill`` when present + not
dismissed.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Iterable, Optional

from core.game_snapshot import is_forbidden_game_mode

logger = logging.getLogger("rc.core.archetype_mismatch")


# Items that don't carry archetype signal. Operator buying these first
# tells us nothing about whether their archetype pick was wrong.
#
# - Boots (all variants incl. legacy ids)
# - Doran's items
# - Trinkets (yellow / red / blue)
# - Consumables (potions, elixirs, control wards)
# - Support starter quest items + completions
# - Jungle pets / Smite upgrades
_NON_SIGNAL_ITEM_IDS: frozenset[str] = frozenset({
    # Boots
    "1001",  # Boots
    "3006",  # Berserker's Greaves
    "3009",  # Boots of Swiftness
    "3020",  # Sorcerer's Shoes
    "3047",  # Plated Steelcaps
    "3111",  # Mercury's Treads
    "3117",  # Boots of Mobility
    "3158",  # Ionian Boots of Lucidity
    # Doran's
    "1054",  # Doran's Shield
    "1055",  # Doran's Blade
    "1056",  # Doran's Ring
    "1057",  # Doran's Mask (Cherry-only at some patches)
    # Trinkets
    "3340",  # Stealth Ward
    "3341",  # Scrying Orb (legacy / Arena variants)
    "3348",  # Arcane Sweeper (Arena trinket - covered by mode-strip in DS server)
    "3363",  # Farsight Alteration
    "3364",  # Oracle Lens
    # Consumables
    "2003",  # Health Potion
    "2031",  # Refillable Potion
    "2033",  # Corrupting Potion
    "2055",  # Control Ward
    "2138",  # Elixir of Iron
    "2139",  # Elixir of Sorcery
    "2140",  # Elixir of Wrath
    "2150",  # Elixir of Skill
    # Support starters + quest completions
    "3850",  # Spellthief's Edge
    "3851",  # Frostfang
    "3853",  # Shard of True Ice
    "3854",  # Steel Shoulderguards
    "3855",  # Runesteel Spaulders
    "3857",  # Pauldrons of Whiterock
    "3858",  # Relic Shield
    "3859",  # Targon's Buckler
    "3860",  # Bulwark of the Mountain
    "3862",  # Spectral Sickle
    "3863",  # Harrowing Crescent
    "3864",  # Black Mist Scythe
    # Jungle pets
    "1101",  # Scorchclaw Pup
    "1102",  # Mosstomper Smolder
    "1103",  # Gustwalker Hatchling
    "1104",  # Tracker (smite-tier upgrade)
})

# How wide to cast the dispatcher net before declaring a mismatch. 15 is
# generous: most archetypes have ~8 core items + ~7 situational; a real
# mismatch (Tank pick + Infinity Edge) sits far below this.
_TOP_N_THRESHOLD: int = 15

# s144 true-audit: the level handed to the dispatcher. League levels are
# 1..18 in every mode RC coaches; anything else is junk and reads as 1.
_MIN_LEVEL: int = 1
_MAX_LEVEL: int = 18

# s144 true-audit: an item id is 1..9 ASCII digits (liveclient ids are
# 4-6 digit ints). A wider check let "nan", "-5", True and Arabic-Indic
# digits through as a "first completed item".
_MAX_ITEM_ID_DIGITS: int = 9

# s144 true-audit: synthetic-session matching. Live Client's gameData
# carries no gameId, so the per-game dedup token is derived from the
# game's start estimate (wall clock minus game clock). That estimate
# jitters by the liveclient sample's age and drifts while a game is
# paused, so it is matched with a tolerance and FOLLOWED poll by poll,
# never compared as a minute bucket. A new game with the same champion
# moves the start by at least the previous game's length (a completed
# item means minutes in), far beyond the tolerance; a game clock that
# falls back is a new game too.
_SYNTH_START_TOLERANCE_S: float = 120.0
_GAME_CLOCK_BACKSTEP_S: float = 5.0

# s144 true-audit: the cache is keyed by champion name, which reaches it
# from a LAN-writable champ-select pick; bound it so no input stream can
# grow it without limit. Oldest entry is evicted first.
_MAX_CACHED_CHAMPIONS: int = 32

# Module-level dedup cache. Threadlock since the dashboard's HTTP server
# is multi-threaded.
_NUDGE_STATE: dict[str, dict] = {}
# Synthetic-session clock per champion: {"start": float, "game_time": float}.
# Kept beside the payload cache so the served payload shape is unchanged.
_SESSION_CLOCK: dict[str, dict] = {}
_NUDGE_LOCK: threading.Lock = threading.Lock()


def _text(value: object) -> str:
    """``value`` stripped when it is a str, else ``""``.

    The pick, the liveclient summary and the coach dict are all JSON
    shaped; a list / dict / number where a string belongs is junk and
    must never become its own ``repr`` (a dict champion used to)."""
    return value.strip() if isinstance(value, str) else ""


def _real(value: object) -> Optional[float]:
    """A finite int / float (never a bool), else ``None``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        out = float(value)
    except (OverflowError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _level(value: object) -> int:
    """Dispatcher level: a real number clamped to 1..18, junk reads 1."""
    num = _real(value)
    if num is None:
        return _MIN_LEVEL
    return max(_MIN_LEVEL, min(_MAX_LEVEL, int(num)))


def _item_id(raw: object) -> str:
    """Canonical item id string for ``raw``, or ``""`` when it is not one.

    A positive int (never a bool) or an ASCII-digit string; anything else
    is not an item id."""
    if isinstance(raw, bool):
        return ""
    if isinstance(raw, int):
        # Range check BEFORE str(): str() of an int past 4300 digits raises.
        sid = str(raw) if 0 < raw < 10 ** _MAX_ITEM_ID_DIGITS else ""
    elif isinstance(raw, str):
        sid = raw.strip()
    else:
        return ""
    if not (0 < len(sid) <= _MAX_ITEM_ID_DIGITS) or not sid.isascii() or not sid.isdigit():
        return ""
    return "" if int(sid) == 0 else sid


def _id_list(value: object) -> list:
    """``value`` when it is a list / tuple, else ``[]``.

    A string or bytes was iterated per character (``"3031"`` read as item
    "3"), a dict per key and an int raised."""
    return list(value) if isinstance(value, (list, tuple)) else []


def _game_clock(lc: dict) -> Optional[float]:
    """Positive finite ``game_time_s``, else ``None``.

    0 is the summary's missing default; with a completed item owned it
    cannot be a real clock, and a token from it changed every wall-clock
    minute."""
    gt = _real(lc.get("game_time_s"))
    return gt if gt is not None and gt > 0 else None


def _remember(store: dict, key: str, value: dict) -> None:
    """Insert ``value`` as the NEWEST entry and evict past the bound."""
    store.pop(key, None)
    store[key] = value
    while len(store) > _MAX_CACHED_CHAMPIONS:
        store.pop(next(iter(store)))


def _copy_entry(entry: dict) -> dict:
    """A copy of a cache entry that shares no mutable value with it."""
    out = dict(entry)
    items = out.get("expected_items")
    if isinstance(items, list):
        out["expected_items"] = list(items)
    return out


@dataclass
class NudgeResult:
    """Result of a single mismatch evaluation. Caller wraps into the
    ``state.archetype_nudge`` payload."""

    fired: bool
    phase: str = "pending"
    champion: str = ""
    primary: str = ""
    first_item_id: str = ""
    first_item_name: str = ""
    message: str = ""
    expected_items: list[str] = field(default_factory=list)
    session_token: str = ""

    def to_dict(self) -> dict:
        return {
            "fired":           self.fired,
            "phase":           self.phase,
            "champion":        self.champion,
            "primary":         self.primary,
            "first_item_id":   self.first_item_id,
            "first_item_name": self.first_item_name,
            "message":         self.message,
            "expected_items":  list(self.expected_items),
            "session_token":   self.session_token,
        }


def _first_completed_item_id(owned_item_ids: Iterable) -> str:
    """Return the first non-signal-empty item id, or ``""``.

    ``owned_item_ids`` is a sequence of either ints or strings as they
    appear in liveclient's ``allPlayers[me].items[].itemID``. We coerce
    to ``str`` and skip everything in ``_NON_SIGNAL_ITEM_IDS``.
    Empty / falsy entries are skipped too, and so is anything that is not
    an item id (s144: a bool, a float, "nan", a negative, non-ASCII
    digits); a non-list input is no items.
    """
    for raw in _id_list(owned_item_ids):
        sid = _item_id(raw)
        if not sid or sid in _NON_SIGNAL_ITEM_IDS:
            continue
        return sid
    return ""


def _resolve_item_name(
    owned_names: Iterable,
    owned_item_ids: Iterable,
    first_item_id: str,
    mode_engine: str,
) -> str:
    """Return the display name for ``first_item_id``, or ``""`` if unknown.

    Two lists, two different shapes: ``owned_names`` is liveclient's raw
    inventory dump while ``owned_item_ids`` has non-inventory ids
    (trinkets, consumables - ``NON_INVENTORY_IDS``) stripped by the state
    builder. They are positionally parallel ONLY when the operator holds
    neither, so a bare zip blanks the name the moment a ward trinket sits
    in the tray - which is always, past minute zero.

    Positional first because when the lengths do match the pairing is
    exact by construction and needs no DDragon read. Otherwise resolve
    each display name back to an id, which is both order- and
    length-independent.
    """
    names = _id_list(owned_names)
    ids = _id_list(owned_item_ids)

    if len(names) == len(ids):
        for raw_id, name in zip(ids, names):
            if _item_id(raw_id) == first_item_id and _text(name):
                return _text(name)

    try:
        from core.daemon_slayer_resolver import name_to_id

        for name in names:
            text = _text(name)
            if not text:
                continue
            if str(name_to_id(text, mode=mode_engine) or "") == first_item_id:
                return text
    except Exception as exc:  # noqa: BLE001
        logger.debug("resolve_item_name(%s) resolver failed: %s", first_item_id, exc)
        return ""

    # Name genuinely unknown (off-patch item, mode the index lacks). Say
    # so in the log rather than leaving an unexplained hole - the caller
    # substitutes the raw id into the operator-facing message.
    logger.debug("resolve_item_name: no display name for id %s (mode=%s, names=%d)",
                 first_item_id, mode_engine, len(names))
    return ""


def _session_token(lc: dict | None, champion: str) -> str:
    """Resolve a per-game dedup token.

    Priority:
      1. ``lc.game_id`` - liveclient's ``gameData.gameId`` field, populated
         by the s184 ``liveclient_summary`` extension when present.
      2. Synthetic ``{champion}@{game_start_floor_min}`` where the floor
         is ``int((now - game_time_s) / 60)`` - buckets each game to its
         minute-of-start. Crude but stable across the typical 25-minute
         game window, and survives clock drift better than absolute ts.

    Returns empty string if no liveclient data - caller can decide to
    skip eval entirely in that case.

    s144 true-audit: ``game_id`` must be a non-empty string (the summary
    emits a canonical decimal or ""), and the synthetic form needs a
    positive finite clock (``_game_clock``); 0, True, inf and NaN used to
    form a token or raise. The synthetic token NAMES a session; whether
    two polls are the same session is decided by ``_same_synthetic_session``
    with a tolerance, never by comparing these minute buckets.
    """
    return _session_key(lc, champion)[0]


def _session_key(lc: dict | None, champion: str) -> tuple[str, Optional[dict]]:
    """``(token, clock)`` for this poll.

    ``clock`` is ``None`` on the game_id path (exact token match) and
    ``{"start": float, "game_time": float}`` on the synthetic path, read
    by ``_same_synthetic_session``. ``("", None)`` = no usable session.
    """
    if not isinstance(lc, dict):
        return "", None
    gid = _text(lc.get("game_id"))
    if gid:
        return gid, None
    gt = _game_clock(lc)
    if gt is None:
        return "", None
    start = time.time() - gt
    return f"{champion}@{int(start / 60)}", {"start": start, "game_time": gt}


def _same_synthetic_session(clock: Optional[dict], start: float, game_time: float) -> bool:
    """True when a poll with derived ``start`` / ``game_time`` continues the
    synthetic session recorded in ``clock``.

    Same session = the start estimate moved by at most
    ``_SYNTH_START_TOLERANCE_S`` since the LAST poll (so a pause is
    followed step by step) and the game clock did not fall back by more
    than ``_GAME_CLOCK_BACKSTEP_S``.
    """
    if not isinstance(clock, dict):
        return False
    prev_start = clock.get("start")
    prev_gt = clock.get("game_time")
    if not isinstance(prev_start, float) or not isinstance(prev_gt, float):
        return False
    if abs(start - prev_start) > _SYNTH_START_TOLERANCE_S:
        return False
    return game_time >= prev_gt - _GAME_CLOCK_BACKSTEP_S


def _evaluate_dispatcher(
    champion: str,
    primary_archetype: str,
    first_item_id: str,
    level: int,
    mode_engine: str,
) -> Optional[tuple[bool, list[str]]]:
    """Call the dispatcher and return ``(is_mismatch, expected_items)`` or ``None``.

    ``is_mismatch`` is ``True`` when ``first_item_id`` is NOT in the
    dispatcher's top-N ids. ``expected_items`` is the list of top-3
    item names from the dispatcher (for the nudge message).

    Returns ``None`` when the dispatcher is unreachable, has no rows, or
    raises any import/runtime error - caller should treat as "no signal,
    skip nudge."
    """
    try:
        from core import daemon_slayer_client as _ds

        out = _ds.rank_for_primary_archetype(
            champion=str(champion),
            archetype=str(primary_archetype),
            level=int(level),
            item_ids=[],  # naked baseline so dispatcher recommends from scratch
            mode=str(mode_engine),
            top=_TOP_N_THRESHOLD,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("evaluate_dispatcher(%s, %s) failed: %s",
                     champion, primary_archetype, exc)
        return None

    if out is None or not isinstance(out, dict):
        return None
    # s144 true-audit: the DS reply is parsed JSON; a non-list ``ranked``
    # or a non-dict row raised AttributeError outside the try above. Junk
    # rows are skipped; no usable row at all is "no signal".
    ranked = out.get("ranked")
    rows = [r for r in ranked if isinstance(r, dict)] if isinstance(ranked, list) else []
    if not rows:
        return None

    top_ids = {_item_id(r.get("item_id")) for r in rows} - {""}
    if not top_ids:
        # Rows without a single item id cannot judge the buy; calling
        # every item a mismatch against an empty set fired a false nudge.
        return None
    top_names = [_text(r.get("item_name")) for r in rows[:3] if _text(r.get("item_name"))]
    is_mismatch = first_item_id not in top_ids
    return (is_mismatch, top_names)


def _build_message(primary: str, first_item_name: str, expected_items: list[str]) -> str:
    """One-line nudge text. Mirrors picks_str compactness - terse, no
    instructions. Operator decides whether to switch archetype."""
    expected = ", ".join(expected_items[:2]) if expected_items else "the archetype's core"
    return (
        f"Picked {primary.title()} but first item is {first_item_name} - "
        f"expected items like {expected}. Consider switching archetype."
    )


def _engine_mode(lc: dict | None) -> str:
    """Map liveclient.game_mode to the DS engine's mode token."""
    if not isinstance(lc, dict):
        return "SR"
    # s144 true-audit: a non-string game_mode raised AttributeError here;
    # it is an unknown mode and reads as the SR default like a missing one.
    gm = _text(lc.get("game_mode")).upper()
    if "ARAM" in gm:
        return "ARAM"
    if "ARENA" in gm or "CHERRY" in gm:
        return "ARENA"
    # Riot compliance 2026-08-11: this branch USED to read `if "BRAWL" in gm`,
    # which matched ONLY Riot's own Brawl mode - the one mode RC may not
    # aggregate. RC's rotating modes ship game_mode tokens like URF / ARURF /
    # NEXUSBLITZ, never "BRAWL", so the branch never did what its name implied.
    # Forbidden modes are now stopped upstream in
    # core.game_snapshot.mode_from_game_mode_string (MODE_UNSUPPORTED); this
    # assert-style guard is the second fence. See docs/OVERLAY_COMPLIANCE_PLAN.md.
    # s144 true-audit: "" is the fence's verdict, and compute_nudge_payload
    # now STOPS on it (before it only renamed the mode and still called the
    # DS dispatcher with mode "" and served the nudge).
    if is_forbidden_game_mode(gm):
        return ""
    return "SR"


def compute_nudge_payload(
    coach: dict | None,
    lc: dict | None,
    lcu_snapshot: dict | None,
    cs_archetype_pick: dict | None,
) -> dict:
    """Top-level entry called by the state-builder.

    Returns the ``state.archetype_nudge`` payload - a dict with at least
    ``fired`` + ``phase``. Empty when no signal (no champion / no
    archetype / no first item / engine down / already dismissed this
    game). The dashboard's chip renderer reads ``fired`` + ``phase`` to
    decide whether to display.

    Side effects: mutates the module-level ``_NUDGE_STATE`` to record
    decisions per (champion, session_token) - avoids re-evaluating the
    dispatcher on every /api/state poll.
    """
    if not isinstance(cs_archetype_pick, dict) or not cs_archetype_pick:
        return {}
    # s144 true-audit: every field read through _text, so a wrong-typed
    # value is "absent" instead of an AttributeError (primary / source)
    # or its own repr (a dict champion became "{'name': ...}").
    primary = _text(cs_archetype_pick.get("primary")).lower()
    if not primary:
        return {}
    # Default DDragon-tag picks aren't operator intent - only fire when
    # the operator explicitly picked or accepted a prior nudge.
    source = _text(cs_archetype_pick.get("source")).lower()
    if source == "default":
        return {}

    if not isinstance(lc, dict) or not lc:
        return {}
    # s144 true-audit: the compliance fence STOPS here, before the pending
    # payload, the cache and the DS dispatcher (it used to pass mode "").
    mode_engine = _engine_mode(lc)
    if not mode_engine:
        return {}
    champion = (_text(cs_archetype_pick.get("champion"))
                or _text(lc.get("champion"))
                or (_text(coach.get("champion")) if isinstance(coach, dict) else ""))
    if not champion:
        return {}

    owned_item_ids = _id_list(lc.get("owned_item_ids"))
    first_item_id = _first_completed_item_id(owned_item_ids)
    if not first_item_id:
        # No completed item yet (still on starter / boots only). Stamp a
        # pending entry so dashboard knows we're watching this game.
        return {
            "fired":   False,
            "phase":   "pending",
            "champion": champion,
            "primary":  primary,
        }

    session_token, clock = _session_key(lc, champion)
    if not session_token:
        return {}

    with _NUDGE_LOCK:
        existing = _NUDGE_STATE.get(champion)
        # If we already evaluated this game for this champion, return the
        # cached decision verbatim (a copy - the caller may mutate it).
        if existing:
            if clock is None:
                same = existing.get("session_token") == session_token
            else:
                same = _same_synthetic_session(
                    _SESSION_CLOCK.get(champion), clock["start"], clock["game_time"])
                if same:
                    # Follow the drift (sample age, pauses) poll by poll.
                    _SESSION_CLOCK[champion] = clock
            if same:
                return _copy_entry(existing)
        # Stale entry (different session) -> fall through to re-evaluate.

    level = _level(lc.get("level"))

    # Resolve item name for the message + payload. Blank is tolerated: the
    # message below falls back to the raw id so the nudge never renders a
    # hole where the item should be.
    first_item_name = _resolve_item_name(
        lc.get("owned_items"),
        owned_item_ids,
        first_item_id,
        mode_engine,
    )

    verdict = _evaluate_dispatcher(
        champion=champion,
        primary_archetype=primary,
        first_item_id=first_item_id,
        level=level,
        mode_engine=mode_engine,
    )
    if verdict is None:
        # Engine down or empty ranking - don't cache; we want to retry
        # on the next poll once the engine is healthy.
        return {}

    is_mismatch, expected_items = verdict

    result = NudgeResult(
        fired=False,
        phase="no_mismatch",
        champion=champion,
        primary=primary,
        first_item_id=first_item_id,
        first_item_name=first_item_name,
        expected_items=expected_items,
        session_token=session_token,
    )
    if is_mismatch:
        result.fired = True
        result.phase = "fired"
        result.message = _build_message(primary, first_item_name or first_item_id, expected_items)

    entry = result.to_dict()
    entry["fired_at"] = time.time()
    with _NUDGE_LOCK:
        _remember(_NUDGE_STATE, champion, entry)
        if clock is None:
            _SESSION_CLOCK.pop(champion, None)
        else:
            _remember(_SESSION_CLOCK, champion, clock)
    return _copy_entry(entry)


def dismiss_nudge(champion: str) -> bool:
    """Mark the current nudge for ``champion`` as dismissed. Returns True
    if a nudge entry existed for the champion. Idempotent - re-dismissing
    a dismissed nudge is fine.
    """
    champion = _text(champion)
    if not champion:
        return False
    with _NUDGE_LOCK:
        entry = _NUDGE_STATE.get(champion)
        if not entry:
            return False
        entry["phase"] = "dismissed"
        entry["fired"] = False
        return True


def reset_nudge_state() -> None:
    """Drop the entire cache. Test-only helper."""
    with _NUDGE_LOCK:
        _NUDGE_STATE.clear()
        _SESSION_CLOCK.clear()


def get_nudge_state_snapshot() -> dict[str, dict]:
    """Return a copy of the cache for diagnostics / tests (no list in it
    is shared with the live cache)."""
    with _NUDGE_LOCK:
        return {k: _copy_entry(v) for k, v in _NUDGE_STATE.items()}
