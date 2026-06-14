"""
lcu/lcu_rune_writer.py - Champion select rune auto-writer for Riot Commander.

Polls LCU champ select session every 2s.
When a champion is selected (intent OR locked), loads the recommended
rune page from rune_recommendations_{aram|sr}.json and writes it to
the LCU immediately - replacing the Overlay App E workflow.

Manages only pages prefixed "RC: " - never touches user-created pages.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger("rc.lcu.runes")

_APP_DIR = Path(__file__).parent.parent

# -- Rune ID constants (from ddragon_runes.json) ----------------------------

# Tree IDs
_TREES = {
    "Precision":   8000,
    "Domination":  8100,
    "Sorcery":     8200,
    "Inspiration": 8300,
    "Resolve":     8400,
}

# Keystone -> ID
_KEYSTONES = {
    # Precision
    "Press the Attack": 8005,
    "Lethal Tempo":     8008,
    "Fleet Footwork":   8021,
    "Conqueror":        8010,
    # Domination
    "Electrocute":      8112,
    "Dark Harvest":     8128,
    "Hail of Blades":   9923,
    # Sorcery
    "Summon Aery":      8214,
    "Arcane Comet":     8229,
    "Phase Rush":       8230,
    # Resolve
    "Grasp of the Undying": 8437,
    "Aftershock":       8439,
    "Guardian":         8465,
    # Inspiration
    "Glacial Augment":  8351,
    "Unsealed Spellbook": 8360,
    "First Strike":     8369,
}

# Primary tree rows 1-3 defaults (ADC-optimised)
# These are the 3 non-keystone row picks for the PRIMARY tree.
# Layout: [row1_id, row2_id, row3_id]
_PRIMARY_ROWS: dict[str, dict[str, list[int]]] = {
    "Precision": {
        # Row1: Absorb Life(9101) / Triumph(9111) / Presence of Mind(8009)
        # Row2: Legend:Alacrity(9104) / Legend:Haste(9105) / Legend:Bloodline(9103)
        # Row3: Coup de Grace(8014) / Cut Down(8017) / Last Stand(8299)
        "_default":       [9111, 9104, 8014],   # Triumph + Alacrity + CdG
        "Conqueror":      [9111, 9104, 8014],   # Conqueror -> Triumph+Alacrity+CdG
        "Fleet Footwork": [8009, 9104, 8014],   # FoF -> PoM+Alacrity+CdG
    },
    "Domination": {
        # Row1: Cheap Shot(8126) / Taste of Blood(8139) / Sudden Impact(8143)
        # Row2: Sixth Sense(8137) / Grisly Mementos(8140) / Deep Ward(8141)
        # Row3: Treasure Hunter(8135) / Relentless Hunter(8105) / Ultimate Hunter(8106)
        "_default": [8139, 8137, 8135],  # Taste of Blood + Sixth Sense + Treasure Hunter
    },
    "Sorcery": {
        # Row1: Axiom Arcanist(8224) / Manaflow Band(8226) / Nimbus Cloak(8275)
        # Row2: Transcendence(8210) / Celerity(8234) / Absolute Focus(8233)
        # Row3: Scorch(8237) / Waterwalking(8232) / Gathering Storm(8236)
        "_default": [8226, 8210, 8236],  # Manaflow + Transcendence + Gathering Storm
    },
    "Resolve": {
        # Row1: Demolish(8446) / Font of Life(8463) / Shield Bash(8401)
        # Row2: Conditioning(8429) / Second Wind(8444) / Bone Plating(8473)
        # Row3: Overgrowth(8451) / Revitalize(8453) / Unflinching(8242)
        "_default": [8401, 8473, 8453],  # Shield Bash + Bone Plating + Revitalize
    },
    "Inspiration": {
        # Row1: Hextech Flashtraption(8306) / Magical Footwear(8304) / Cash Back(8321)
        # Row2: Triple Tonic(8313) / Time Warp Tonic(8352) / Biscuit Delivery(8345)
        # Row3: Cosmic Insight(8347) / Approach Velocity(8410) / Jack Of All Trades(8316)
        "_default": [8304, 8345, 8347],  # Magical Footwear + Biscuit + Cosmic Insight
    },
}

# Secondary tree - best 2 picks for each tree (ADC-optimised)
# Layout: [pick1_id, pick2_id]
_SECONDARY_PICKS: dict[str, list[int]] = {
    "Precision":   [9111, 9104],   # Triumph + Legend: Alacrity
    "Domination":  [8143, 8135],   # Sudden Impact + Treasure Hunter
    "Sorcery":     [8226, 8236],   # Manaflow Band + Gathering Storm
    "Resolve":     [8473, 8453],   # Bone Plating + Revitalize
    "Inspiration": [8304, 8347],   # Magical Footwear + Cosmic Insight
}

# Stat shards: [row1, row2, row3]
_SHARDS_SR   = [5005, 5008, 5001]  # Attack Speed | Adaptive Force | Health Scaling
_SHARDS_ARAM = [5005, 5008, 5001]  # Attack Speed | Adaptive Force | Health Scaling

# Lazy {rune display-name: perk id} map, built from ddragon_runes.json the
# first time it's needed. Lets a user-curated build override the hardcoded
# minor-rune defaults below (item 212) without re-listing every id here.
_PERK_BY_NAME: Optional[dict[str, int]] = None


def _perk_by_name() -> dict[str, int]:
    """Return {rune display-name: id} parsed from data/meta/ddragon_runes.json.

    Cached after the first read. Returns an empty dict if the file is
    missing or malformed so callers fall back to defaults rather than crash.
    """
    global _PERK_BY_NAME
    if _PERK_BY_NAME is None:
        m: dict[str, int] = {}
        try:
            p = _APP_DIR / "data" / "meta" / "ddragon_runes.json"
            for tree in json.loads(p.read_text(encoding="utf-8")):
                for slot in tree.get("slots", []):
                    for r in slot.get("runes", []):
                        nm, rid = r.get("name"), r.get("id")
                        if isinstance(nm, str) and isinstance(rid, int):
                            m[nm] = rid
        except Exception as exc:
            # Audit cycle 10 (P2-W1-app-B): do NOT cache the failure -
            # pre-fix a transient read error pinned an empty map for the
            # process lifetime (cache-poisoning class), silently dropping
            # every user-curated minor-rune override from then on.
            _log.debug("perk-by-name load failed: %s", exc)
            return {}
        _PERK_BY_NAME = m
    return _PERK_BY_NAME


# -- Core resolver ---------------------------------------------------------

def build_perk_ids(
    keystone: str,
    primary_tree: str,
    secondary_tree: str,
    is_aram: bool = False,
    minor_primary: Optional[list[str]] = None,
    minor_secondary: Optional[list[str]] = None,
) -> Optional[list[int]]:
    """
    Resolve (keystone name, primary_tree name, secondary_tree name) → 9-element perk_ids.
    Returns None if keystone or trees are unrecognised.

    Layout: [keystone, pri_row1, pri_row2, pri_row3, sec1, sec2, shard1, shard2, shard3]

    minor_primary / minor_secondary (item 212): optional user-chosen rune
    display-names. When the FULL set resolves (3 primary rows / 2 secondary
    picks) they override the hardcoded defaults; any miss keeps defaults so a
    malformed page is never pushed.
    """
    ks_id = _KEYSTONES.get(keystone)
    if not ks_id:
        _log.warning("Unknown keystone %r - skipping rune write", keystone)
        return None

    pri_id = _TREES.get(primary_tree)
    sec_id = _TREES.get(secondary_tree)
    if not pri_id or not sec_id:
        _log.warning("Unknown trees %r / %r", primary_tree, secondary_tree)
        return None

    if primary_tree == secondary_tree:
        _log.warning("Primary and secondary trees are the same (%r) - using Resolve as secondary", secondary_tree)
        secondary_tree = "Resolve" if primary_tree != "Resolve" else "Precision"
        sec_id = _TREES[secondary_tree]

    # Primary rows: look for keystone-specific override, fall back to _default
    pri_rows_map = _PRIMARY_ROWS.get(primary_tree, {})
    pri_rows = pri_rows_map.get(keystone) or pri_rows_map.get("_default", [])
    if len(pri_rows) < 3:
        _log.warning("No primary row defaults for %r", primary_tree)
        return None

    sec_picks = _SECONDARY_PICKS.get(secondary_tree, [])
    if len(sec_picks) < 2:
        _log.warning("No secondary pick defaults for %r", secondary_tree)
        return None

    # item 212: honor user-chosen minor runes when the full set resolves.
    # Any unresolved name or wrong count keeps the defaults above so we
    # never push a malformed page.
    name_map = _perk_by_name()
    if minor_primary:
        mp = [name_map.get(n) for n in minor_primary]
        if len(mp) == 3 and all(isinstance(x, int) for x in mp):
            pri_rows = mp
    if minor_secondary:
        ms = [name_map.get(n) for n in minor_secondary]
        if len(ms) == 2 and all(isinstance(x, int) for x in ms):
            sec_picks = ms

    shards = _SHARDS_ARAM if is_aram else _SHARDS_SR

    return [ks_id, pri_rows[0], pri_rows[1], pri_rows[2],
            sec_picks[0], sec_picks[1],
            shards[0], shards[1], shards[2]]


def load_rune_rec(champion: str, mode: str) -> Optional[tuple[str, str, str]]:
    """
    Load (keystone, primary_tree, secondary_tree) from rune_recommendations_{mode}.json.
    Returns None if champion not found.
    """
    _ARAM_MODES = {"ARAM", "KIWI", "ARAM_5V5", "ARAM_MAYHEM", "CLASSIC_ARAM"}
    fname = (
        "rune_recommendations_aram.json"
        if mode.upper() in _ARAM_MODES or "ARAM" in mode.upper()
        else "rune_recommendations_sr.json"
    )
    try:
        p = _APP_DIR / "data" / "meta_build" / fname
        if not p.exists():
            _log.warning("Rune rec file not found: %s", fname)
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        rec = data.get(champion)
        if not rec or not isinstance(rec, dict):
            _log.debug("No rune rec for %r in %s", champion, fname)
            return None
        ks  = rec.get("keystone", "")
        pri = rec.get("primary_tree", "")
        sec = rec.get("secondary_tree", "")
        if ks and pri and sec:
            return (ks, pri, sec)
        return None
    except Exception as exc:
        _log.debug("load_rune_rec: %s", exc)
        return None


def build_champ_id_map() -> dict[int, str]:
    """Build {champion_id_int: display_name} from ddragon_champions.json."""
    try:
        p = _APP_DIR / "data" / "meta" / "ddragon_champions.json"
        raw = json.loads(p.read_text(encoding="utf-8"))
        result: dict[int, str] = {}
        for name, info in (raw.get("data") or {}).items():
            try:
                cid = int(info.get("key", -1))
                if cid >= 0:
                    result[cid] = info.get("name", name)  # display name e.g. "Miss Fortune" not "MissFortune"
            except (ValueError, TypeError):
                pass
        _log.debug("Champion ID map: %d entries", len(result))
        return result
    except Exception as exc:
        _log.warning("build_champ_id_map: %s", exc)
        return {}



# -- Summoner spell preference reader --------------------------------------

# ARAM spell IDs
_SPELL_FLASH    = 4
_SPELL_SNOWBALL = 32   # Mark (ARAM)
_SPELL_EXHAUST  = 3
_SPELL_TELEPORT = 12
_SPELL_IGNITE   = 14
_SPELL_HEAL     = 7

_SPELL_PREFS_PATH = _APP_DIR / "data" / "spell_prefs.json"

def load_spell_pair(mode: str, is_aram: bool) -> tuple[int, int]:
    """
    Load (spell1_id, spell2_id) from spell_prefs.json.
    is_aram: True for ARAM/KIWI; False for SR.
    Falls back to safe defaults if file missing or invalid.
    """
    try:
        if _SPELL_PREFS_PATH.exists():
            prefs = json.loads(_SPELL_PREFS_PATH.read_text(encoding='utf-8'))
            key   = "aram_mode" if is_aram else "sr_mode"
            pref  = prefs.get(key, "snowball" if is_aram else "teleport")
        else:
            pref = "snowball" if is_aram else "teleport"
    except Exception:
        pref = "snowball" if is_aram else "teleport"

    if is_aram:
        if pref == "exhaust":
            return (_SPELL_FLASH, _SPELL_EXHAUST)
        # snowball or ai or anything else -> Flash + Snowball
        return (_SPELL_FLASH, _SPELL_SNOWBALL)
    else:
        if pref == "exhaust":
            return (_SPELL_FLASH, _SPELL_EXHAUST)
        if pref == "ignite":
            return (_SPELL_FLASH, _SPELL_IGNITE)
        # teleport or ai or anything else -> Flash + Teleport
        return (_SPELL_FLASH, _SPELL_TELEPORT)


# ARAM-family mode strings the LCU lobby / champ-select reports.
_ARAM_MODE_STRINGS = frozenset(
    {"ARAM", "KIWI", "ARAM_5V5", "ARAM_MAYHEM", "CLASSIC_ARAM"}
)


def resolve_spell_pair(champion: str, mode: str) -> tuple[int, int]:
    """Resolve the INTENDED summoner-spell pair for a champ + LCU game mode.

    CS2 (2026-06-08): the operator-facing source of truth is the same
    spell_prefs.json the RuneWriter already reads via load_spell_pair -
    sr_mode=teleport (Flash+Teleport) for SR, aram_mode=snowball
    (Flash+Snowball) for ARAM. This wrapper turns the raw LCU mode
    string into the is_aram bool load_spell_pair expects, routing
    KIWI / ARAM Mayhem to the ARAM pair, everything else to SR.

    ``champion`` is accepted for forward-compat (a future per-champ
    override could key off it) but is not used today - the pair is
    mode-driven so it stays correct for every champion.
    """
    is_aram = (mode or "").upper() in _ARAM_MODE_STRINGS or "ARAM" in (mode or "").upper()
    return load_spell_pair(mode, is_aram)


# Audit cycle 10 (P2-W1-app-B): serializes save_spell_pref writers -
# concurrent calls shared one .tmp name (cycle-9 shared-tmp race class)
# and a transient os.replace WinError 5 silently dropped the write.
# Mirrors coaches/_base_coach.safe_write (lock + bounded replace retry).
_SPELL_PREFS_LOCK = threading.Lock()


def save_spell_pref(mode_key: str, value: str) -> None:
    """Write updated spell preference to spell_prefs.json (atomic write)."""
    try:
        with _SPELL_PREFS_LOCK:
            if _SPELL_PREFS_PATH.exists():
                prefs = json.loads(_SPELL_PREFS_PATH.read_text(encoding='utf-8'))
            else:
                prefs = {}
            prefs[mode_key] = value
            tmp = _SPELL_PREFS_PATH.with_suffix('.tmp')
            tmp.write_text(json.dumps(prefs, indent=2, ensure_ascii=False),
                           encoding='utf-8')
            for attempt in range(3):
                try:
                    tmp.replace(_SPELL_PREFS_PATH)
                    break
                except PermissionError:
                    # os.replace transient WinError 5 under concurrent
                    # read - retry with backoff, give up after 3.
                    if attempt == 2:
                        _log.warning("save_spell_pref: replace gave up after 3 tries")
                        try:
                            tmp.unlink(missing_ok=True)
                        except OSError:
                            pass
                    else:
                        time.sleep(0.015 * (2 ** attempt))
    except Exception as exc:
        _log.debug("save_spell_pref: %s", exc)


# ==============================================================================
# RuneWriter
# ==============================================================================

class RuneWriter:
    """
    Background thread that monitors champion select and auto-writes
    the RC-recommended rune page to the LCU client.

    Replaces Overlay App E / Moba rune auto-apply.
    Only manages pages with the prefix "RC: " - never touches other pages.
    """

    PAGE_PREFIX = "RC: "
    POLL_INTERVAL = 2.0   # seconds between champ-select polls
    MAX_RETRIES   = 3     # attempts to write rune page on failure

    def __init__(self, lcu_client) -> None:
        self._lcu = lcu_client
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._task: Optional[Any] = None
        self._champ_id_map: dict[int, str] = {}
        self._last_applied_champion: str = ""  # champion we last wrote runes for
        self._last_applied_mode: str = ""
        self._in_champ_select = False

    def start(self) -> None:
        self._champ_id_map = build_champ_id_map()
        self._stop_event.clear()
        try:
            from app._loop import get_loop as _get_loop
            _sched = _get_loop()
        except Exception:
            _sched = None
        if _sched is not None:
            self._task = _sched.spawn_task(self._run_async())
            _log.info("RuneWriter started (%d champion IDs loaded, async)", len(self._champ_id_map))
        else:
            self._thread = threading.Thread(
                target=self._run, name="RuneWriter", daemon=True
            )
            self._thread.start()
            _log.info("RuneWriter started (%d champion IDs loaded, thread)", len(self._champ_id_map))

    def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            try: self._task.cancel()
            except Exception: pass
            self._task = None
        _log.info("RuneWriter stopped")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._poll()
            except Exception as exc:
                _log.debug("RuneWriter poll error: %s", exc)
            self._stop_event.wait(self.POLL_INTERVAL)

    async def _run_async(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.to_thread(self._poll)
            except Exception as exc:
                _log.debug("RuneWriter poll error: %s", exc)
            try:
                await asyncio.sleep(self.POLL_INTERVAL)
            except asyncio.CancelledError:
                return

    def _poll(self) -> None:
        session = self._lcu.get_champ_select()

        if not session or not isinstance(session, dict):
            # Not in champ select
            if self._in_champ_select:
                _log.debug("RuneWriter: champ select ended")
                self._in_champ_select = False
                self._last_applied_champion = ""
                self._last_applied_mode = ""
            return

        self._in_champ_select = True

        # Get game mode from lobby
        mode = self._detect_game_mode()

        # CS2 (2026-06-08): self-correct summoner spells on EVERY poll, before
        # the champion-detected early-return below. The client randomises the
        # spell defaults (Flash+Heal / Flash+Teleport) on champ-select entry;
        # correcting only once (the old side-effect of a successful rune write)
        # left the wrong pair stuck if the rune POST failed (3-page account
        # cap) or the client re-randomised after RC's single push. _sync_spells
        # is idempotent - it PATCHes only when the live pair differs - so
        # running it every 2s costs nothing once the spells are right.
        self._sync_spells(session, mode)

        # Find my champion (intent or locked)
        champion_name = self._detect_my_champion(session)
        if not champion_name:
            return  # still picking, nothing to apply yet

        # Only re-apply if champion or mode changed
        if (champion_name == self._last_applied_champion and
                mode == self._last_applied_mode):
            return

        _log.info("RuneWriter: champion=%s mode=%s - applying runes", champion_name, mode)
        success = self._apply_runes(champion_name, mode)
        if success:
            self._last_applied_champion = champion_name
            self._last_applied_mode = mode
        else:
            _log.warning("RuneWriter: rune write failed for %s/%s", champion_name, mode)

    def _sync_spells(self, session: dict, mode: str) -> bool:
        """CS2: push the intended summoner-spell pair when it differs.

        Reads the live (spell1Id, spell2Id) for my cell out of the champ-
        select session, resolves the intended pair for the mode via
        resolve_spell_pair (spell_prefs.json: Flash+TP for SR, Flash+
        Snowball for ARAM), and delegates to LcuClient.set_summoner_spells
        with current_pair set so the PATCH is skipped when already correct.

        Fail-soft: returns False without raising / without an LCU write when
        the session is missing, my cell can't be found, or the LCU call
        errors. Returns True when the spells are correct (either already, or
        after a successful PATCH).
        """
        if not session or not isinstance(session, dict):
            return False
        try:
            my_cell = session.get("localPlayerCellId", -1)
            my_pick = None
            for player in session.get("myTeam", []) or []:
                if isinstance(player, dict) and player.get("cellId") == my_cell:
                    my_pick = player
                    break
            if my_pick is None:
                return False  # my cell not in the session yet - nothing to do
            try:
                cur = (int(my_pick.get("spell1Id", 0) or 0),
                       int(my_pick.get("spell2Id", 0) or 0))
            except (TypeError, ValueError):
                cur = (0, 0)
            want1, want2 = resolve_spell_pair("", mode)
            return bool(self._lcu.set_summoner_spells(
                want1, want2, current_pair=cur))
        except Exception as exc:
            _log.debug("RuneWriter: _sync_spells: %s", exc)
            return False

    def _detect_game_mode(self) -> str:
        """Detect current game mode from lobby config."""
        try:
            lobby = self._lcu._request("GET", "/lol-lobby/v2/lobby")
            if lobby and isinstance(lobby, dict):
                gc = lobby.get("gameConfig", {})
                return gc.get("gameMode", "CLASSIC").upper()
        except Exception:
            pass
        return "CLASSIC"

    def _detect_my_champion(self, session: dict) -> str:
        """
        Find my champion name from the champ select session.
        Returns champion name string (from ddragon) or "" if not yet selected.
        Prefers locked champion (championId) over intent (championPickIntent).
        """
        try:
            my_cell = session.get("localPlayerCellId", -1)
            my_team = session.get("myTeam", [])

            for player in my_team:
                if not isinstance(player, dict):
                    continue
                if player.get("cellId") != my_cell:
                    continue

                # Locked champion takes priority
                champ_id = player.get("championId", 0)
                if champ_id and champ_id > 0:
                    return self._id_to_name(champ_id)

                # Intent (hovered) champion
                intent_id = player.get("championPickIntent", 0)
                if intent_id and intent_id > 0:
                    return self._id_to_name(intent_id)

                return ""  # found my slot but no champ selected

        except Exception as exc:
            _log.debug("_detect_my_champion: %s", exc)
        return ""

    def _id_to_name(self, champ_id: int) -> str:
        """Resolve champion ID to display name."""
        name = self._champ_id_map.get(champ_id, "")
        if not name:
            _log.debug("Unknown champion ID %d - refreshing map", champ_id)
            self._champ_id_map = build_champ_id_map()
            name = self._champ_id_map.get(champ_id, "")
        return name

    def _apply_runes(self, champion: str, mode: str) -> bool:
        """
        Load rune recommendation and write page to LCU.
        Returns True on success.
        """
        is_aram = mode in ("ARAM", "KIWI", "ARAM_5V5", "ARAM_MAYHEM")

        rec = load_rune_rec(champion, mode)
        if not rec:
            # Fall back to ARAM runes for ARAM modes, SR runes for others
            fallback_mode = "ARAM" if is_aram else "CLASSIC"
            _log.debug("No rune rec for %s/%s - using generic %s defaults", champion, mode, fallback_mode)
            # Use a safe default for ADC: Lethal Tempo / Precision / Domination
            rec = ("Lethal Tempo", "Precision", "Domination")

        keystone, primary_tree, secondary_tree = rec
        perk_ids = build_perk_ids(keystone, primary_tree, secondary_tree, is_aram)
        if not perk_ids:
            return False

        pri_id = _TREES.get(primary_tree, 0)
        sec_id = _TREES.get(secondary_tree, 0)
        if not pri_id or not sec_id:
            _log.warning("Unknown tree IDs for %s / %s", primary_tree, secondary_tree)
            return False

        mode_tag = "ARAM" if is_aram else "SR"
        page_name = f"{self.PAGE_PREFIX}{champion} {mode_tag}"

        success = self._write_page(page_name, pri_id, sec_id, perk_ids)

        # Summoner spells are owned by _sync_spells (CS2, 2026-06-08), which
        # runs every _poll BEFORE this rune write and is self-correcting +
        # idempotent. The previous "push spells iff the rune write succeeded"
        # side-effect was the CS2 root cause: a failed rune POST (3-page
        # account cap) skipped the spell push entirely, leaving the client's
        # randomised Flash+Heal / Flash+TP default in place. No spell write
        # here anymore - it would be a redundant unconditional double-PATCH.

        return success

    def _write_page(
        self,
        name: str,
        primary_style_id: int,
        sub_style_id: int,
        selected_perk_ids: list[int],
    ) -> bool:
        """
        Delete any existing RC-managed pages, then POST the new page.
        Returns True on success.
        """
        # 1. Delete existing RC pages
        try:
            pages = self._lcu.get_all_rune_pages() or []
            for p in pages:
                if (isinstance(p, dict) and
                        p.get("isDeletable") and
                        str(p.get("name", "")).startswith(self.PAGE_PREFIX)):
                    page_id = p.get("id")
                    if page_id:
                        self._lcu._request("DELETE", f"/lol-perks/v1/pages/{page_id}")
                        _log.debug("Deleted old RC page: %s (id=%s)", p.get("name"), page_id)
        except Exception as exc:
            _log.debug("_write_page delete step: %s", exc)

        # 2. POST new page
        payload = {
            "name":             name,
            "primaryStyleId":   primary_style_id,
            "subStyleId":       sub_style_id,
            "selectedPerkIds":  selected_perk_ids,
            "current":          True,
            "isRecommendationOverride": False,
        }

        # 2026-04-27 audit: exponential backoff (0.5s, 1s, 2s) instead of
        # flat 0.5s. Champ-select windows often have multiple LCU calls
        # in-flight; a flat retry hammers the client during the exact
        # 1.5s window when it's most likely transiently busy. Also: log
        # the final failure at WARNING so a sustained outage surfaces.
        last_exc: Exception | None = None
        for attempt in range(self.MAX_RETRIES):
            try:
                result = self._lcu._request("POST", "/lol-perks/v1/pages", data=payload)
                if result and isinstance(result, dict) and result.get("id"):
                    page_id = result["id"]
                    # 3. Set as active page
                    self._lcu._request("PUT", "/lol-perks/v1/currentpage",
                                       data={"id": page_id})
                    _log.info(
                        "RuneWriter: wrote [%s] id=%s  perks=%s",
                        name, page_id, selected_perk_ids
                    )
                    return True
                else:
                    _log.debug("POST page attempt %d failed: %s", attempt + 1, result)
            except Exception as exc:
                last_exc = exc
                _log.debug("_write_page POST attempt %d: %s", attempt + 1, exc)
            if attempt < self.MAX_RETRIES - 1:
                time.sleep(0.5 * (2 ** attempt))

        _log.warning("RuneWriter: gave up after %d attempts for [%s]: %s",
                     self.MAX_RETRIES, name, last_exc)
        return False
