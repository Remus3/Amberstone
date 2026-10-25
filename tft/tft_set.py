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

LIVE-GAME-GATED (unverified): nobody has measured whether :2999 or the LCU
exposes the running set during a TFT game. LIVE_SET_KEYS are CANDIDATE key
names only; the one measured set-id spelling in the tree is the LCU team
planner's "setId": "TFTSet17" (scripts/discover_champion_codes.py:52).

A set's meta file is that set's own: a missing tft_set<N>_meta.json is
never replaced by another set's file (the old sites fell back to Set 17,
which fed Set 17 comps to a Set 18 game).
"""
from __future__ import annotations

import json
import logging
import os
import re
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

_SET_FILE_RE = re.compile(r"^tft_set(\d{1,3})_(?:meta|cdragon)\.json$")
_SET_ID_RE = re.compile(r"^(?:tft_?)?set_?(\d{1,3})(?:_\w*)?$", re.IGNORECASE)

_monotonic = time.monotonic
_live: dict = {"set": None, "at": 0.0}
_warned: set = set()


def meta_dir(root=None) -> Path:
    return Path(root if root is not None else ROOT) / "data" / "meta"


def parse_set_id(value) -> int | None:
    """18, "18", "TFTSet18", "TFTSet17_PAIRS", "TFT_Set17", "Set18" -> int."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 1 <= value <= 999 else None
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.isdigit():
        n = int(s)
        return n if 1 <= n <= 999 else None
    m = _SET_ID_RE.match(s)
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
        _live["set"] = n
        _live["at"] = _monotonic()
    return n


def clear_live_set() -> None:
    _live["set"] = None
    _live["at"] = 0.0


def noted_live_set() -> int | None:
    n = _live["set"]
    if n is None:
        return None
    if _monotonic() - _live["at"] > LIVE_TTL_S:
        clear_live_set()
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


def meta_path(set_number=None, *, pbe=False, root=None) -> Path:
    """The set's meta file; its PBE twin only when pbe and the twin exists."""
    n = set_number if set_number is not None else resolve_set(root=root)
    d = meta_dir(root)
    if pbe:
        twin = d / f"tft_set{n}_pbe_meta.json"
        if twin.exists():
            return twin
    return d / f"tft_set{n}_meta.json"


def cdragon_path(set_number=None, *, root=None) -> Path:
    n = set_number if set_number is not None else resolve_set(root=root)
    return meta_dir(root) / f"tft_set{n}_cdragon.json"


def load_json_file(path) -> dict:
    """A JSON object off disk, or {} when absent / unreadable / not an object."""
    try:
        obj = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return obj if isinstance(obj, dict) else {}


def load_meta(set_number=None, *, pbe=False, root=None) -> dict:
    return load_json_file(meta_path(set_number, pbe=pbe, root=root))


def load_cdragon(set_number=None, *, root=None) -> dict:
    return load_json_file(cdragon_path(set_number, root=root))


def comp_state(root=None) -> dict:
    """data/comp_state.json (overlay comp selector state), {} when absent."""
    return load_json_file(Path(root if root is not None else ROOT) / "data" / "comp_state.json")


def pbe_flag(root=None) -> bool:
    return bool(comp_state(root).get("pbe", False))


def _str_list(value) -> list[str]:
    if isinstance(value, dict):
        value = list(value)
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str) and v.strip()]


def roster(set_number=None, *, root=None) -> list[str]:
    """Champion display names: CDragon extract first, then the meta file."""
    n = set_number if set_number is not None else resolve_set(root=root)
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
    n = set_number if set_number is not None else resolve_set(root=root)
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
