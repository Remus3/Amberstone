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
import threading
import time
from dataclasses import dataclass, field
from typing import Iterable, Optional

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

# Module-level dedup cache. Threadlock since the dashboard's HTTP server
# is multi-threaded.
_NUDGE_STATE: dict[str, dict] = {}
_NUDGE_LOCK: threading.Lock = threading.Lock()


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
    Empty / falsy entries are skipped too.
    """
    for raw in owned_item_ids or ():
        if raw in (None, "", 0, "0"):
            continue
        sid = str(raw).strip()
        if not sid or sid in _NON_SIGNAL_ITEM_IDS:
            continue
        return sid
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
    """
    if not isinstance(lc, dict):
        return ""
    gid = lc.get("game_id")
    if gid:
        return str(gid)
    gt = lc.get("game_time_s")
    if gt is None:
        return ""
    try:
        start_floor = int((time.time() - float(gt)) / 60)
    except (TypeError, ValueError):
        return ""
    return f"{champion}@{start_floor}"


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
    ranked = out.get("ranked") or []
    if not ranked:
        return None

    top_ids = {str(r.get("item_id", "")) for r in ranked if r.get("item_id")}
    top_names = [str(r.get("item_name", "")) for r in ranked[:3] if r.get("item_name")]
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
    gm = (lc.get("game_mode") or "").upper()
    if "ARAM" in gm:
        return "ARAM"
    if "ARENA" in gm or "CHERRY" in gm:
        return "ARENA"
    if "BRAWL" in gm:
        return "BRAWL"
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
    primary = (cs_archetype_pick.get("primary") or "").strip().lower()
    if not primary:
        return {}
    # Default DDragon-tag picks aren't operator intent - only fire when
    # the operator explicitly picked or accepted a prior nudge.
    source = (cs_archetype_pick.get("source") or "").strip().lower()
    if source == "default":
        return {}

    if not isinstance(lc, dict) or not lc:
        return {}
    champion = (cs_archetype_pick.get("champion")
                or (lc.get("champion") if isinstance(lc, dict) else "")
                or (coach.get("champion") if isinstance(coach, dict) else "")
                or "")
    champion = str(champion).strip()
    if not champion:
        return {}

    owned_item_ids = lc.get("owned_item_ids") or []
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

    session_token = _session_token(lc, champion)
    if not session_token:
        return {}

    with _NUDGE_LOCK:
        existing = _NUDGE_STATE.get(champion)
        # If we already evaluated this (champion, session_token) pair,
        # return the cached decision verbatim.
        if existing and existing.get("session_token") == session_token:
            return dict(existing)
        # Stale entry (different session) -> fall through to re-evaluate.

    # Resolve item name for the message + payload. liveclient owned_items
    # is a list of display names parallel to owned_item_ids; if absent,
    # we'll leave name blank - message still readable.
    owned_names = lc.get("owned_items") or []
    first_item_name = ""
    try:
        if len(owned_names) == len(owned_item_ids):
            for raw_id, name in zip(owned_item_ids, owned_names):
                if str(raw_id).strip() == first_item_id:
                    first_item_name = str(name)
                    break
    except Exception:  # noqa: BLE001
        first_item_name = ""

    level = int(lc.get("level") or 1)
    mode_engine = _engine_mode(lc)

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
        _NUDGE_STATE[champion] = entry
    return dict(entry)


def dismiss_nudge(champion: str) -> bool:
    """Mark the current nudge for ``champion`` as dismissed. Returns True
    if a nudge entry existed for the champion. Idempotent - re-dismissing
    a dismissed nudge is fine.
    """
    if not champion:
        return False
    champion = str(champion).strip()
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


def get_nudge_state_snapshot() -> dict[str, dict]:
    """Return a deep-ish copy of the cache for diagnostics / tests."""
    with _NUDGE_LOCK:
        return {k: dict(v) for k, v in _NUDGE_STATE.items()}
