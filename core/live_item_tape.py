# arch: RM-607 live inventory tape - item buy/sell/combine diff over allPlayers | section=core | frozen=no
"""Live inventory tape: an item buy / sell / combine log for all 10 players.

RM-607 (directive X-07, behaviour inspired by external reference C; no code
or constants taken from it). A PURE diff engine: it is fed consecutive
``allPlayers`` snapshots (the list inside the parsed ``/allgamedata`` payload
that ``core.liveclient_cache`` already polls - NO new poll) and emits typed
events. It owns no thread, no socket and no file; persistence lives in
``core/live_item_tape_store.py``.

Keying (the reason this module exists in this shape)
----------------------------------------------------
Players are keyed by ``(riot id, team)`` - ``riotIdGameName#riotIdTagLine``
(or the ``riotId`` field), falling back to ``summonerName`` - and NEVER by
list index or bare ``participantId``. The Live Client does not promise a
stable ``allPlayers`` order, and keying by position cross-contaminates one
player's purchases into another's when the list reorders. This follows the
per-name state map of ``core/ward_producer.py`` (``_state[summoner_name]``,
ward_producer.py:130-131 and the per-player loop at :285-303), strengthened
with the riot id and the team so two same-named players on opposite teams
stay distinct. A key seen twice in ONE snapshot is skipped for that tick
(it cannot be attributed).

Event types
-----------
Persisted at game end (``PERSISTED_TYPES``):
  ITEM_PURCHASED   an item appeared that nothing explains (count = copies /
                   stacks bought this tick).
  ITEM_SOLD        an item disappeared that nothing explains.
  ITEM_COMBINED    a completed item appeared in the SAME tick that some of its
                   DDragon ``from`` components (searched down the recipe tree)
                   disappeared; ``components`` lists the consumed ids.
Tape-only (keep the fold exact, never written as timeline rows):
  INVENTORY_BASELINE  first sighting of a player (mid-game attach is not a
                      purchase, so held items are a baseline, not buys).
  CONSUMABLE_USED     a consumable's count went down (potion drunk, ward
                      placed). A consumable SOLD back is indistinguishable
                      from use and is typed here too - never as ITEM_SOLD.
  TRINKET_SWAP        trinket-slot item changed (``components`` = old one).
  ITEM_TRANSFORMED    an item turned into another without a shop purchase:
                      a DDragon ``specialRecipe`` (Manamune -> Muramana) or a
                      zero-combine-cost upgrade (T3 role-quest boots, World
                      Atlas line choices).
  ITEM_GRANTED / ITEM_REMOVED
                      an EXCLUDED id appeared / disappeared (see below). In a
                      tick where any grant appears, otherwise-unexplained
                      removals are ITEM_REMOVED, not ITEM_SOLD, because an Ornn
                      masterwork upgrade replaces a legendary that DDragon gives
                      no ``from`` link for.

Exclusions (grants, never purchases)
------------------------------------
``build_exclusions`` unions:
  * ``GRANT_SEED_IDS`` - the DS grant / non-shop deny-lists
    (agents/daemon_slayer/rank.py ``_NON_COACHABLE_ITEM_IDS``,
    ``_ARAM_EXCLUDED_ITEM_IDS``, ``_ARENA_EXCLUDED_ITEM_IDS``; parity pinned by
    tests/test_live_item_tape.py) plus the Arena anvil vouchers and the ARAM
    stat-bonus grant, then SWEPT BY 4-DIGIT ID SUFFIX across every map-mirror
    namespace (22/32/44/66/99/12 prefixes), never by name;
  * Ornn masterworks - the ``<ornnBonus>`` description marker, the same
    marker DS uses (agents/daemon_slayer/rank.py ``_is_ornn_masterwork``);
  * champion-specific items - a truthy DDragon ``requiredChampion``;
  * Arena prismatic items - the ``44`` id namespace (measured on the 16.19.1
    catalog: 49 rows, every one map 30 only or no map).
Marker-derived classes are NOT suffix-swept (a prismatic suffix would sweep
legitimate shop items such as the 66xxxx / 22xxxx mirrors).

Known blind spots (under-count, never invent)
---------------------------------------------
  * A buy-and-undo (or buy-then-sell) between two snapshots never reaches a
    snapshot, so the tape records nothing. Likewise a component bought and
    combined inside one tick shows only the completed item.
  * A sale in the same tick as a grant is typed ITEM_REMOVED (not ITEM_SOLD).
  * ``fold(events)`` reproduces the LAST GOOD snapshot exactly; a player whose
    ``items`` field is missing in a torn payload is skipped, not emptied.
"""
from __future__ import annotations

import json
import logging
import threading
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

_log = logging.getLogger(__name__)

EV_PURCHASED = "ITEM_PURCHASED"
EV_SOLD = "ITEM_SOLD"
EV_COMBINED = "ITEM_COMBINED"
EV_BASELINE = "INVENTORY_BASELINE"
EV_CONSUMABLE_USED = "CONSUMABLE_USED"
EV_TRINKET_SWAP = "TRINKET_SWAP"
EV_TRANSFORMED = "ITEM_TRANSFORMED"
EV_GRANTED = "ITEM_GRANTED"
EV_REMOVED = "ITEM_REMOVED"

PERSISTED_TYPES: frozenset[str] = frozenset({EV_PURCHASED, EV_SOLD, EV_COMBINED})

# Live Client trinket slot (fallback when an id is not in the catalog).
_TRINKET_SLOT = 6

# A game-time drop larger than this between ticks means a NEW game (our own
# threshold: one relay hiccup never rewinds the clock by more than a few
# seconds; a new game restarts it at ~0).
_NEW_GAME_REWIND_S = 30.0

# Grant / non-shop seeds. The first five mirror the DS deny-lists (pinned by
# test); the rest are measured on the 16.19.1 catalog.
GRANT_SEED_IDS: tuple[int, ...] = (
    994403, 224403, 4403,      # Golden Spatula family (DS _NON_COACHABLE)
    663064, 443064,            # Talisman of Ascension family (DS _NON_COACHABLE)
    223069,                    # Void Immolation - Mayhem / Arena augment reward
    226668,                    # Ultra Hydra - Mayhem augment reward
    220008, 220009, 220010, 220011,  # Arena anvil / stat vouchers (inStore False)
    6032,                      # ARAM "Stat Bonus" - auto-opened stat grant
)
_ARENA_PRISMATIC_PREFIX = "44"
_ORNN_MARKER = "<ornnBonus>"

_DEFAULT_ITEMS_JSON = (Path(__file__).resolve().parent.parent
                       / "data" / "meta" / "ddragon_items.json")


# --------------------------------------------------------------------------
# Catalog
# --------------------------------------------------------------------------

class ItemCatalog:
    """The DDragon facts the tape needs, keyed by int item id."""

    def __init__(self, data: dict | None = None) -> None:
        self._from: dict[int, tuple[int, ...]] = {}
        self._special: dict[int, int] = {}
        self._base_gold: dict[int, int] = {}
        self._tags: dict[int, frozenset] = {}
        self._desc: dict[int, str] = {}
        self._req_champ: dict[int, bool] = {}
        for sid, entry in (data or {}).items():
            try:
                iid = int(sid)
            except (TypeError, ValueError):
                continue
            if not isinstance(entry, dict):
                continue
            comps = []
            for c in entry.get("from") or ():
                try:
                    comps.append(int(c))
                except (TypeError, ValueError):
                    continue
            self._from[iid] = tuple(comps)
            sr = entry.get("specialRecipe")
            if isinstance(sr, (int, str)) and str(sr).isdigit() and int(sr):
                self._special[iid] = int(sr)
            gold = entry.get("gold") if isinstance(entry.get("gold"), dict) else {}
            try:
                self._base_gold[iid] = int(gold.get("base") or 0)
            except (TypeError, ValueError):
                self._base_gold[iid] = 0
            self._tags[iid] = frozenset(entry.get("tags") or ())
            self._desc[iid] = str(entry.get("description") or "")
            self._req_champ[iid] = bool(entry.get("requiredChampion"))

    @classmethod
    def from_ddragon(cls, raw: dict) -> "ItemCatalog":
        data = raw.get("data", raw) if isinstance(raw, dict) else {}
        return cls(data if isinstance(data, dict) else {})

    def ids(self) -> Iterable[int]:
        return self._from.keys()

    def has(self, iid: int) -> bool:
        return iid in self._from

    def recipe(self, iid: int) -> tuple[int, ...]:
        return self._from.get(iid, ())

    def special_recipe(self, iid: int) -> Optional[int]:
        return self._special.get(iid)

    def base_gold(self, iid: int) -> Optional[int]:
        return self._base_gold.get(iid)

    def is_trinket(self, iid: int) -> bool:
        return "Trinket" in self._tags.get(iid, ())

    def is_consumable(self, iid: int) -> bool:
        return "Consumable" in self._tags.get(iid, ())

    def is_ornn_masterwork(self, iid: int) -> bool:
        return _ORNN_MARKER in self._desc.get(iid, "")

    def is_champion_specific(self, iid: int) -> bool:
        return self._req_champ.get(iid, False)

    def recipe_closure(self, iid: int) -> Counter:
        """Multiset of every id anywhere under ``iid``'s recipe tree."""
        out: Counter = Counter()
        stack = list(self.recipe(iid))
        guard = 0
        while stack and guard < 512:
            guard += 1
            c = stack.pop()
            out[c] += 1
            stack.extend(self.recipe(c))
        return out


_CATALOG: Optional[ItemCatalog] = None
_CATALOG_LOCK = threading.Lock()


def load_default_catalog(path: Path | None = None) -> ItemCatalog:
    """Read the tracked DDragon item catalog once. Fail-soft: empty catalog
    (every change is then a plain purchase / sale - nothing is invented)."""
    global _CATALOG
    if path is None and _CATALOG is not None:
        return _CATALOG
    p = path or _DEFAULT_ITEMS_JSON
    try:
        cat = ItemCatalog.from_ddragon(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        _log.warning("live_item_tape: catalog load failed (%s): %s", p, exc)
        return ItemCatalog()
    if path is None:
        with _CATALOG_LOCK:
            _CATALOG = cat
    return cat


def build_exclusions(catalog: ItemCatalog) -> frozenset[int]:
    """Ids whose appearance is a GRANT, never a shop purchase."""
    seed_suffixes = {str(s)[-4:] for s in GRANT_SEED_IDS}
    out: set[int] = set(GRANT_SEED_IDS)
    for iid in catalog.ids():
        sid = str(iid)
        if sid[-4:] in seed_suffixes:
            out.add(iid)                      # mirror-namespace suffix sweep
        elif catalog.is_ornn_masterwork(iid) or catalog.is_champion_specific(iid):
            out.add(iid)
        elif len(sid) == 6 and sid.startswith(_ARENA_PRISMATIC_PREFIX):
            out.add(iid)
    return frozenset(out)


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------

@dataclass(frozen=True, order=True)
class TapeEvent:
    game_time_s: float
    player: str
    team: str
    event_type: str
    item_id: int
    count: int = 1
    components: tuple[int, ...] = ()


def player_key(player: Any) -> Optional[tuple[str, str]]:
    """``(riot id, team)`` for an allPlayers entry, or None if unresolvable.

    riotIdGameName#riotIdTagLine, else ``riotId``, else ``summonerName``.
    Never a list index, never a bare participantId.
    """
    if not isinstance(player, dict):
        return None
    team = player.get("team")
    team = team if isinstance(team, str) else ""
    name = player.get("riotIdGameName")
    tag = player.get("riotIdTagLine")
    if isinstance(name, str) and name and isinstance(tag, str) and tag:
        return (f"{name}#{tag}", team)
    rid = player.get("riotId")
    if isinstance(rid, str) and "#" in rid and rid.split("#", 1)[0]:
        return (rid, team)
    sn = player.get("summonerName")
    if isinstance(sn, str) and sn:
        return (sn, team)
    return None


def _inventory(items: Any) -> Optional[tuple[Counter, set[int], set[int]]]:
    """(multiset, trinket-slot ids, snapshot-flagged consumables) or None when
    the ``items`` field is not a list (torn payload - skip, never empty)."""
    if not isinstance(items, list):
        return None
    inv: Counter = Counter()
    slot6: set[int] = set()
    flagged: set[int] = set()
    for it in items:
        if not isinstance(it, dict):
            continue
        try:
            iid = int(it.get("itemID"))
        except (TypeError, ValueError):
            continue
        if iid <= 0:
            continue
        cnt = it.get("count")
        cnt = cnt if isinstance(cnt, int) and not isinstance(cnt, bool) and cnt > 0 else 1
        inv[iid] += cnt
        if it.get("slot") == _TRINKET_SLOT:
            slot6.add(iid)
        if it.get("consumable") is True:
            flagged.add(iid)
    return inv, slot6, flagged


def fold(events: Iterable[TapeEvent]) -> dict[tuple[str, str], Counter]:
    """Replay a tape into per-player inventories (the acceptance check)."""
    inv: dict[tuple[str, str], Counter] = {}
    for e in events:
        c = inv.setdefault((e.player, e.team), Counter())
        if e.event_type == EV_BASELINE and e.item_id == 0:
            c.clear()
            continue
        if e.event_type in (EV_BASELINE, EV_PURCHASED, EV_GRANTED):
            c[e.item_id] += e.count
        elif e.event_type in (EV_SOLD, EV_CONSUMABLE_USED, EV_REMOVED):
            c[e.item_id] -= e.count
        elif e.event_type in (EV_COMBINED, EV_TRANSFORMED, EV_TRINKET_SWAP):
            for comp in e.components:
                c[comp] -= 1
            if e.item_id:
                c[e.item_id] += 1
        for k in [k for k, v in c.items() if v <= 0]:
            del c[k]
    return inv


# --------------------------------------------------------------------------
# The tape
# --------------------------------------------------------------------------

class LiveItemTape:
    """Stateful diff of consecutive allPlayers snapshots. Not thread-safe by
    itself; the module singleton below serialises access with a lock."""

    def __init__(self, catalog: ItemCatalog | None = None) -> None:
        self.catalog = catalog if catalog is not None else load_default_catalog()
        self.exclusions = build_exclusions(self.catalog)
        self.events: list[TapeEvent] = []
        # key -> (inventory multiset, ids seen in the trinket slot)
        self._state: dict[tuple[str, str], tuple[Counter, set[int]]] = {}
        self._last_time: Optional[float] = None

    def reset(self) -> None:
        self.events = []
        self._state = {}
        self._last_time = None

    def drain(self) -> list[TapeEvent]:
        """Hand back the whole tape and start a fresh one."""
        out = self.events
        self.reset()
        return out

    def ingest(self, all_players: Any, game_time_s: float) -> list[TapeEvent]:
        """Diff one snapshot against the previous one; return NEW events."""
        if not isinstance(all_players, list):
            return []
        try:
            gt = float(game_time_s)
        except (TypeError, ValueError):
            return []
        new: list[TapeEvent] = []
        if self._last_time is not None and gt < self._last_time - _NEW_GAME_REWIND_S:
            # Clock went back: a new game. Close every player (item_id 0
            # baseline = "inventory cleared") and start over.
            new.extend(TapeEvent(gt, k[0], k[1], EV_BASELINE, 0, 0)
                       for k in sorted(self._state))
            self._state = {}
        self._last_time = gt

        seen: dict[tuple[str, str], Any] = {}
        dup: set[tuple[str, str]] = set()
        for p in all_players:
            key = player_key(p)
            if key is None:
                continue
            if key in seen:
                dup.add(key)
            seen[key] = p

        for key in sorted(seen):
            if key in dup:
                continue
            parsed = _inventory(seen[key].get("items"))
            if parsed is None:
                continue
            curr, slot6, flagged = parsed
            prev = self._state.get(key)
            if prev is None:
                new.extend(TapeEvent(gt, key[0], key[1], EV_BASELINE, iid, n)
                           for iid, n in sorted(curr.items()))
            else:
                new.extend(self._diff(key, gt, prev[0], curr, prev[1] | slot6,
                                      flagged))
            self._state[key] = (curr, slot6)
        self.events.extend(new)
        return new

    # ---- classification ------------------------------------------------

    def _is_trinket(self, iid: int, slot6: set[int]) -> bool:
        if self.catalog.has(iid):
            return self.catalog.is_trinket(iid)
        return iid in slot6

    def _is_consumable(self, iid: int, flagged: set[int]) -> bool:
        return self.catalog.is_consumable(iid) or iid in flagged

    def _take(self, iid: int, pool: Counter, depth: int = 0) -> list[int]:
        """Consume ``iid``'s recipe from ``pool``: an owned direct component
        is used whole; otherwise descend into that component's recipe."""
        used: list[int] = []
        if depth > 8:
            return used
        for comp in self.catalog.recipe(iid):
            if pool[comp] > 0:
                pool[comp] -= 1
                used.append(comp)
            else:
                used.extend(self._take(comp, pool, depth + 1))
        return used

    def _diff(self, key, gt, prev: Counter, curr: Counter,
              slot6: set[int], flagged: set[int]) -> list[TapeEvent]:
        name, team = key
        added = curr - prev
        removed = prev - curr
        out: list[TapeEvent] = []

        def ev(kind: str, iid: int, count: int = 1, comps: tuple = ()) -> None:
            out.append(TapeEvent(gt, name, team, kind, iid, count, comps))

        # 1. trinket slot
        add_tr = sorted(i for i in added if self._is_trinket(i, slot6))
        rem_tr = sorted(i for i in removed if self._is_trinket(i, slot6))
        for i in add_tr + rem_tr:
            (added if i in add_tr else removed).pop(i, None)
        while add_tr or rem_tr:
            new_t = add_tr.pop(0) if add_tr else 0
            old_t = rem_tr.pop(0) if rem_tr else None
            ev(EV_TRINKET_SWAP, new_t, 1, (old_t,) if old_t is not None else ())

        # 2. grants (exclusions)
        grant_tick = False
        for i in sorted(i for i in added if i in self.exclusions):
            ev(EV_GRANTED, i, added.pop(i))
            grant_tick = True
        for i in sorted(i for i in removed if i in self.exclusions):
            ev(EV_REMOVED, i, removed.pop(i))

        # 3. consumables
        for i in sorted(i for i in added if self._is_consumable(i, flagged)):
            ev(EV_PURCHASED, i, added.pop(i))
        for i in sorted(i for i in removed if self._is_consumable(i, flagged)):
            ev(EV_CONSUMABLE_USED, i, removed.pop(i))

        # 4/5. transforms, combines, purchases - deepest recipe first so a
        # completed item claims its components before a smaller sibling does.
        order = sorted(added.elements(),
                       key=lambda i: (-sum(self.catalog.recipe_closure(i).values()), i))
        for iid in order:
            sr = self.catalog.special_recipe(iid)
            if sr is not None and removed[sr] > 0:
                removed[sr] -= 1
                ev(EV_TRANSFORMED, iid, 1, (sr,))
                continue
            if self.catalog.base_gold(iid) == 0:
                src = next((c for c in self.catalog.recipe(iid) if removed[c] > 0), None)
                if src is not None:
                    removed[src] -= 1
                    ev(EV_TRANSFORMED, iid, 1, (src,))
                    continue
            used = self._take(iid, removed)
            if used:
                ev(EV_COMBINED, iid, 1, tuple(sorted(used)))
            else:
                ev(EV_PURCHASED, iid, 1)
        # merge identical single-count purchases into one event with a count
        merged: list[TapeEvent] = []
        buys: Counter = Counter()
        for e in out:
            if e.event_type == EV_PURCHASED and not self._is_consumable(e.item_id, flagged):
                buys[e.item_id] += e.count
            else:
                merged.append(e)
        merged.extend(TapeEvent(gt, name, team, EV_PURCHASED, i, n)
                      for i, n in sorted(buys.items()))
        out = merged

        # 6. what is left disappeared unexplained
        for iid, n in sorted(removed.items()):
            if n > 0:
                ev(EV_REMOVED if grant_tick else EV_SOLD, iid, n)
        return out


# --------------------------------------------------------------------------
# Process singleton + liveclient_cache listener (the existing 0.5 s poll)
# --------------------------------------------------------------------------

_TAPE: Optional[LiveItemTape] = None
_TAPE_LOCK = threading.Lock()


def _tape() -> LiveItemTape:
    global _TAPE
    if _TAPE is None:
        _TAPE = LiveItemTape()
    return _TAPE


def tick_from_snapshot(snap: object) -> int:
    """``core.liveclient_cache.add_listener`` adapter (same shape as
    ``core.ward_producer.tick_from_snapshot``). Fail-soft; returns the number
    of new events."""
    data = getattr(snap, "data", None)
    if not isinstance(data, dict):
        return 0
    players = data.get("allPlayers")
    gd = data.get("gameData")
    gt = gd.get("gameTime") if isinstance(gd, dict) else None
    if not isinstance(players, list) or not isinstance(gt, (int, float)) \
            or isinstance(gt, bool):
        return 0
    with _TAPE_LOCK:
        return len(_tape().ingest(players, float(gt)))


def drain_tape() -> list[TapeEvent]:
    """Take the singleton's whole tape and reset it (game-end use)."""
    with _TAPE_LOCK:
        return _tape().drain()


_LISTENER_INSTALLED = False

# Kill switch / opt-in. DEFAULT OFF: with the flag off no listener is installed,
# no tape accumulates and nothing is persisted (the shared timeline_events table
# is never altered). Same truthy set as RC_SESSION_RECORDER.
FLAG_ENV = "RC_ITEM_TAPE"
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def is_enabled(environ: Optional[dict] = None) -> bool:
    import os
    env = os.environ if environ is None else environ
    return str(env.get(FLAG_ENV, "0")).strip().lower() in _TRUTHY


def install_if_enabled() -> bool:
    """Install the listener only when ``RC_ITEM_TAPE`` is on. Called from
    ``core.liveclient_cache._install_optional_taps`` (non-frozen seam)."""
    if not is_enabled():
        return False
    return install_liveclient_listener()


def install_liveclient_listener() -> bool:
    """Idempotent: register ``tick_from_snapshot`` on liveclient_cache.
    Production reaches this only through ``install_if_enabled``."""
    global _LISTENER_INSTALLED
    if _LISTENER_INSTALLED:
        return False
    try:
        from core import liveclient_cache
        liveclient_cache.add_listener(tick_from_snapshot)
    except Exception:  # noqa: BLE001 - fail-soft like ward_producer
        return False
    _LISTENER_INSTALLED = True
    return True
