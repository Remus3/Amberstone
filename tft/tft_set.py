"""
tft/tft_set.py
The ONE place the TFT lane decides which TFT set's data files to read (RM-840).

Before RM-840 six sites hard-wired data/meta/tft_set17_*.json. Set 18 has
been live since about 2026-08-26 and Set 17 stays playable beside it, so the
answer is no longer a constant.

Resolution order (resolve_set):
  1. a live set id passed by the caller, then one noted from live game data
     (note_live_set / note_live_set_from_game_data), fresh for LIVE_TTL_S;
  2. the operator pin in the RC_TFT_SET environment variable;
  3. the NEWEST ingested set - any N with data/meta/tft_set<N>_meta.json or
     data/meta/tft_set<N>_cdragon.json on disk.
A candidate is honoured only when that set is ingested: RC cannot serve data
it does not have, so a live set id for an unknown set falls through.

LIVE-GAME-GATED (unverified): no measured key names the RUNNING set.
LIVE_SET_KEYS are CANDIDATE key names only. Measured 2026-10-25 (session
134, a live Set 18 TFT game): the game ran as a standalone client and
NOTHING listened on :2999 (connection refused), so no :2999 key exists to
read; the LCU gameflow session carries no set key (only map assets named
"TFT_Set18_..."). The measured set-id spellings in the tree are the LCU team
planner's previous-context "setId": "TFTSet17" (Set 17 era) and "TFTSet18"
(Set 18 lobby) - the planner's view, not the game's (scripts/
discover_champion_codes.py PLANNER_CONTEXT).

LT-01 closure (session 134, measured): post-game only, the LCU
/lol-end-of-game/v1/tft-eog-stats document carries players[].setCoreName
"TFTSet18" (the local player's own setCoreName is ""; read the players[]
row whose isLocalPlayer is true). In ANY phase the LCU game data
tftsets.json "mDefaultSet" names the default set ("TFTSet18"), but the
client also offers a revival queue for an older set (queue 6110 "Set 17
(Normal)"), so the running set = mDefaultSet PAIRED with the gameflow
session queue id: set_from_lcu / note_live_set_from_lcu (QUEUE_SETS).
read_lcu_set_facts does the two LCU reads; core/tft_worker.py TftWorker
calls it from the TFT poll loop, refreshed inside LIVE_TTL_S, when it is
built with an LCU request, else reads only the queue id off the relayed LCU
agent snapshot (snapshot_tft_queue_id) (S134). The noted set then routes the round
schedule (tft/tft_state_reader.py round_schedule), the roll odds
(tft/tft_data.py tier_odds_for_set) and the XP table (xp_to_next_level)
through resolve_set.

A set's meta file is that set's own: a missing tft_set<N>_meta.json is
never replaced by another set's file (the old sites fell back to Set 17,
which fed Set 17 comps to a Set 18 game).

Input contract (s144 true-audit): every reader here takes values RC did not
author (a dashboard ?set= query, the RC_TFT_SET env pin, LCU payloads, live
game data, comp_state.json) and never raises on junk. A set id is ASCII
digits 1-999 only; a value that is not one is no set id. A set_number handed
to a path builder is parsed the same way; one that does not parse names no
set (a path that reads as absent, an empty roster), so it never borrows
another set's file and no caller value is ever interpolated into a file
name. Only None means "the resolved set". Only a file name the path builders produce
counts as ingested ("tft_set018_*" or "tft_set0_*" never does).
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path

logger = logging.getLogger("rc.tft.set")

ROOT = Path(__file__).resolve().parent.parent

# The set the lane was hard-wired to before RM-840. Used ONLY when no set at
# all is ingested under the root (a bare checkout or a test tree).
FALLBACK_SET = 17
ENV_PIN = "RC_TFT_SET"
LIVE_TTL_S = 180.0
LIVE_SET_KEYS = (
    "setId", "tftSetId", "tftSet", "setCoreName", "tftSetCoreName",
    "tftSetNumber",
)

# ASCII only: \d and \w would otherwise match any Unicode digit / word char,
# and a non-ASCII digit either breaks int() ("\u00b2") or names a file the
# path builders never produce. No leading zero, so every match round-trips
# through meta_path / cdragon_path.
_SET_FILE_RE = re.compile(r"^tft_set([1-9]\d{0,2})_(?:meta|cdragon)\.json$", re.ASCII)
_SET_ID_RE = re.compile(r"^(?:tft_?)?set_?(\d{1,3})(?:_\w*)?$", re.IGNORECASE | re.ASCII)
_DIGITS_RE = re.compile(r"\d{1,9}", re.ASCII)

_monotonic = time.monotonic
# The noted live set and when it was noted. Written by the TFT worker thread,
# read by coach and dashboard threads: the pair is only ever read or written
# under _live_lock, so a reader never pairs one note's set with another's time.
_live: dict = {"set": None, "at": 0.0}
_live_lock = threading.Lock()
_warned: set = set()


def meta_dir(root=None) -> Path:
    return Path(root if root is not None else ROOT) / "data" / "meta"


def _ascii_int(value) -> int | None:
    """A non-bool int, or an ASCII digit string (surrounding whitespace ok,
    at most 9 digits); None for anything else. Never raises."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        s = value.strip()
        if _DIGITS_RE.fullmatch(s):
            return int(s)
    return None


def parse_set_id(value) -> int | None:
    """18, "18", "TFTSet18", "TFTSet17_PAIRS", "TFT_Set17", "Set18" -> int.

    ASCII digits only, 1-999; anything else (a non-ASCII digit, a huge digit
    string, a float, a bool, a container) is None. Never raises."""
    n = _ascii_int(value)
    if n is not None:
        return n if 1 <= n <= 999 else None
    if not isinstance(value, str):
        return None
    m = _SET_ID_RE.match(value.strip())
    if not m:
        return None
    n = int(m.group(1))
    return n if 1 <= n <= 999 else None


def ingested_sets(root=None) -> list[int]:
    """Sets with a meta file or a CDragon extract under data/meta, ascending."""
    d = meta_dir(root)
    try:
        names = [p.name for p in d.iterdir()]
    except OSError:
        return []
    found = set()
    for name in names:
        m = _SET_FILE_RE.match(name)
        if m:
            found.add(int(m.group(1)))
    return sorted(found)


def default_set(root=None) -> int | None:
    sets = ingested_sets(root)
    return sets[-1] if sets else None


def note_live_set(value) -> int | None:
    """Record the set a live game reports; None/unparseable clears nothing."""
    n = parse_set_id(value)
    if n is not None:
        at = _monotonic()
        with _live_lock:
            _live["set"] = n
            _live["at"] = at
    return n


def clear_live_set() -> None:
    with _live_lock:
        _live["set"] = None
        _live["at"] = 0.0


def noted_live_set() -> int | None:
    """The noted set while fresh (LIVE_TTL_S), else None (and the note is
    dropped). The clock is read BEFORE the pair, and the pair is read and
    expired under the lock, so a note landing concurrently is either seen
    whole or survives for the next read - never answered with the old set."""
    now = _monotonic()
    with _live_lock:
        n = _live["set"]
        if n is None:
            return None
        if now - _live["at"] > LIVE_TTL_S:
            _live["set"] = None
            _live["at"] = 0.0
            return None
        return n


def note_live_set_from_game_data(game_data) -> int | None:
    """Note a set id carried by live game data under a candidate key."""
    if not isinstance(game_data, dict):
        return None
    for key in LIVE_SET_KEYS:
        n = note_live_set(game_data.get(key))
        if n is not None:
            return n
    return None


# Queues that run a set other than the client's mDefaultSet, measured from the
# LCU queue list 2026-10-25 (lol-game-queues: 6110 "Set 17 (Normal)").
QUEUE_SETS = {6110: 17}


def set_from_lcu(default_set=None, queue_id=None) -> int | None:
    """The running set from LCU facts: a revival queue's own set first, else
    the tftsets.json mDefaultSet ("TFTSet18" -> 18); None when neither parses."""
    q = _ascii_int(queue_id)
    if q in QUEUE_SETS:
        return QUEUE_SETS[q]
    return parse_set_id(default_set)


def note_live_set_from_lcu(default_set=None, queue_id=None) -> int | None:
    """Note the running set from mDefaultSet + queue id (see set_from_lcu)."""
    n = set_from_lcu(default_set, queue_id)
    return note_live_set(n) if n is not None else None


# The two LCU reads behind set_from_lcu, at the paths measured 2026-10-25
# (ops/runtime/tft_qa/LCU_TFT_INVENTORY.md, rows "Set / patch metadata" and
# "Queue / mode"). Caller: core/tft_worker.py TftWorker (S134).
TFTSETS_URI = "/lol-game-data/assets/v1/tftsets.json"
GAMEFLOW_SESSION_URI = "/lol-gameflow/v1/session"


def lcu_default_set(tftsets) -> str | None:
    """tftsets.json LCTFTModeData.mDefaultSet.SetName ("TFTSet18"), or None."""
    node = tftsets
    for key in ("LCTFTModeData", "mDefaultSet", "SetName"):
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    if isinstance(node, str) and node.strip():
        return node.strip()
    return None


def lcu_tft_queue_id(session) -> int | None:
    """gameData.queue.id of a gameflow session whose queue gameMode is TFT."""
    if not isinstance(session, dict):
        return None
    data = session.get("gameData")
    q = data.get("queue") if isinstance(data, dict) else None
    if not isinstance(q, dict) or q.get("gameMode") != "TFT":
        return None
    qid = _ascii_int(q.get("id"))
    if qid is None or qid <= 0:
        return None
    return qid


_SNAPSHOT_IN_GAME = frozenset({"GameStart", "InProgress", "Reconnect"})


def snapshot_tft_queue_id(snapshot) -> int | None:
    """The TFT queue id stamped into an LCU agent snapshot in game, or None.

    lcu/snapshot_shape.py (S134 P0) writes game_queue_id / game_queue_mode
    from the gameflow session at GameStart / InProgress / Reconnect; the
    vision relay carries that snapshot (tft/tft_standalone.py
    relay_lcu_snapshot). It carries no mDefaultSet.
    """
    if not isinstance(snapshot, dict):
        return None
    if snapshot.get("phase") not in _SNAPSHOT_IN_GAME:
        return None
    mode = snapshot.get("game_queue_mode")
    return lcu_tft_queue_id({"gameData": {"queue": {
        "id": snapshot.get("game_queue_id"),
        "gameMode": mode.strip().upper() if isinstance(mode, str) else None}}})


def read_lcu_set_facts(request, default_set=None) -> tuple:
    """(mDefaultSet name, TFT queue id) through an LCU ``request(method, path)
    -> (payload, err)`` callable (lcu/snapshot_shape.py transport contract).

    (None, None) when the session is not a TFT game: with no queue id the set
    is not noted at all, because mDefaultSet alone is wrong for a revival
    queue. tftsets.json is read only when the queue does not already name its
    set (QUEUE_SETS) and the caller holds no default_set from an earlier read.
    """
    session, _ = request("GET", GAMEFLOW_SESSION_URI)
    qid = lcu_tft_queue_id(session)
    if qid is None:
        return None, None
    if qid in QUEUE_SETS:
        return default_set, qid
    if default_set is None:
        tftsets, _ = request("GET", TFTSETS_URI)
        default_set = lcu_default_set(tftsets)
    return default_set, qid


def env_pin() -> int | None:
    return parse_set_id(os.environ.get(ENV_PIN, ""))


def resolve_set(live_set=None, *, root=None) -> int:
    available = ingested_sets(root)
    for source, candidate in (
        ("live", parse_set_id(live_set)),
        ("live-noted", noted_live_set()),
        (ENV_PIN, env_pin()),
    ):
        if candidate is None:
            continue
        if candidate in available:
            return candidate
        if (source, candidate) not in _warned:
            _warned.add((source, candidate))
            logger.warning(
                "TFT set %s from %s is not ingested (have %s) - ignored",
                candidate, source, available)
    return available[-1] if available else FALLBACK_SET


# The file-name token for an explicit set_number that is not a set id. It is
# no set (_SET_FILE_RE never matches it, no writer produces it), so its path
# reads as absent: an explicit bad set never borrows another set's file.
_NO_SET = "_invalid"


def _explicit_or_resolved(set_number, root) -> int | None:
    """None (absent) -> the resolved set; an explicit value -> its set id, or
    None when it is not one. Never a raw caller value."""
    if set_number is None:
        return resolve_set(root=root)
    return parse_set_id(set_number)


def meta_path(set_number=None, *, pbe=False, root=None) -> Path:
    """The set's meta file; its PBE twin only when pbe and the twin exists."""
    n = _explicit_or_resolved(set_number, root)
    d = meta_dir(root)
    if n is None:
        return d / f"tft_set{_NO_SET}_meta.json"
    if pbe:
        twin = d / f"tft_set{n}_pbe_meta.json"
        if twin.exists():
            return twin
    return d / f"tft_set{n}_meta.json"


def cdragon_path(set_number=None, *, root=None) -> Path:
    n = _explicit_or_resolved(set_number, root)
    return meta_dir(root) / f"tft_set{_NO_SET if n is None else n}_cdragon.json"


def load_json_file(path) -> dict:
    """A JSON object off disk, or {} when absent / unreadable / not an object.

    RecursionError is "unreadable" too: a deeply nested document blows the
    decoder's stack, and that must not escape into a coach path."""
    try:
        obj = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, RecursionError):
        return {}
    return obj if isinstance(obj, dict) else {}


def load_meta(set_number=None, *, pbe=False, root=None) -> dict:
    return load_json_file(meta_path(set_number, pbe=pbe, root=root))


def load_cdragon(set_number=None, *, root=None) -> dict:
    return load_json_file(cdragon_path(set_number, root=root))


def comp_state(root=None) -> dict:
    """data/comp_state.json (overlay comp selector state), {} when absent."""
    return load_json_file(Path(root if root is not None else ROOT) / "data" / "comp_state.json")


_PBE_ON = frozenset({"true", "1", "yes", "on"})


def pbe_flag(root=None) -> bool:
    """data/comp_state.json's PBE switch (see pbe_enabled)."""
    return pbe_enabled(comp_state(root))


def pbe_enabled(state) -> bool:
    """A comp_state "pbe" value is on only for True, 1 or a "true"/"1"/"yes"/
    "on" string (any case); "false", "0", 2, a list and every other value is
    off, so a stringly-typed "false" never routes the coach to the PBE twin.
    For a caller that already holds the comp_state dict."""
    value = state.get("pbe", False) if isinstance(state, dict) else False
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in _PBE_ON
    return False


def _str_list(value) -> list[str]:
    if isinstance(value, dict):
        value = list(value)
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str) and v.strip()]


def roster(set_number=None, *, root=None) -> list[str]:
    """Champion display names: CDragon extract first, then the meta file.
    An explicit set_number that is not a set id has no roster."""
    n = _explicit_or_resolved(set_number, root)
    if n is None:
        return []
    names = _str_list(load_cdragon(n, root=root).get("champions"))
    if names:
        return names
    meta = load_meta(n, root=root)
    for key in (f"champions_set{n}", "champions", "unit_costs"):
        names = _str_list(meta.get(key))
        if names:
            return names
    return []


def trait_names(set_number=None, *, root=None) -> list[str]:
    n = _explicit_or_resolved(set_number, root)
    if n is None:
        return []
    names = _str_list(load_cdragon(n, root=root).get("all_traits"))
    return names or _str_list(load_meta(n, root=root).get("all_traits"))


def all_champion_names(root=None) -> set[str]:
    """Every ingested set's roster: a live game may be on any of them."""
    out: set[str] = set()
    for n in ingested_sets(root):
        out.update(roster(n, root=root))
    return out


def all_trait_names(root=None) -> set[str]:
    out: set[str] = set()
    for n in ingested_sets(root):
        out.update(trait_names(n, root=root))
    return out
