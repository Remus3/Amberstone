"""Per-patch "what changed for YOUR champions" aggregation (read-only).

Joins the cross-patch Daemon Slayer snapshot diff (RM-110,
``tools/ds_patch_diff.diff_snapshots``) against the tracked player's OWN
``rewind_history.db`` play counts, so the answer is not "here is the patch
note" but "here is the slice of the patch note that touches the champions you
actually play". Deterministic - ZERO Riot / Claude / network dependency, the
Haiku-to-ZERO lane sibling of core.duration_winrate / core.session_hygiene /
core.playstyle_labels.

Never raises. A missing db, a missing snapshot, or an unreadable diff returns
an ok payload with an empty champion list and a stated reason - the panel
renders the "-" sentinel rather than an error.

Two joins, both trap-avoiding:

* ``matches.tracked_champion_id`` is a Riot NUMERIC id while every DS snapshot
  registry is keyed on the DDragon id string ("MonkeyKing"), so the bridge is
  ``champions.json``'s ``key`` field. Joining on a display name would silently
  drop champions (memory ``reference_rewind_champion_join_on_key``).
* An ITEM change is attributed to a champion only when that item id appears in
  the champion's build order for the requested mode, read off the builds diff
  itself - no second registry load, no guessing.

The diff is injectable (``diff_fn``) exactly like core.duration_winrate's
``conn`` seam, so the tests never touch ``data/`` and stay clean-checkout safe.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Callable, Optional

from core.smoothed_rates import laplace_rate

log = logging.getLogger("rc.patch_impact")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_REWIND_DB = _PROJECT_ROOT / "data" / "rewind_history.db"
_DS_DIR = _PROJECT_ROOT / "data" / "daemon_slayer"

# map_id per mode - same convention as core.duration_winrate.MODE_MAPS.
MODE_MAPS: dict[str, int] = {"sr": 11, "aram": 12, "arena": 30}
VALID_MODES = ("sr", "aram", "arena")
DEFAULT_MODE = "aram"

MIN_DURATION_S = 300      # drop remakes (mirror duration_winrate)
DEFAULT_MIN_GAMES = 5     # below this the champion is not "yours" yet
DEFAULT_TOP_N = 12        # cap the card; the tail is noise


def _open_ro() -> Optional[sqlite3.Connection]:
    if not _REWIND_DB.exists():
        return None
    try:
        return sqlite3.connect(f"file:{_REWIND_DB}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        log.warning("patch_impact open: %s", exc)
        return None


def _patch_sort_key(name: str) -> tuple:
    parts = []
    for chunk in str(name).split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(-1)
    return tuple(parts)


def available_patches(root: Optional[Path] = None) -> list[str]:
    """Snapshot patch dirs under data/daemon_slayer, oldest first."""
    base = Path(root) if root is not None else _DS_DIR
    try:
        names = [p.name for p in base.iterdir()
                 if p.is_dir() and p.name[:1].isdigit()]
    except OSError as exc:
        log.warning("patch_impact patches: %s", exc)
        return []
    return sorted(names, key=_patch_sort_key)


def champion_key_map(patch: str, root: Optional[Path] = None) -> dict[int, dict]:
    """Riot numeric champion id -> {"id": ddragon_id, "name": display name}.

    Empty dict when the snapshot is absent or malformed (never raises).
    """
    base = Path(root) if root is not None else _DS_DIR
    path = base / str(patch) / "champions.json"
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("patch_impact champions.json: %s", exc)
        return {}
    data = blob.get("data")
    if not isinstance(data, dict):
        return {}
    out: dict[int, dict] = {}
    for ddragon_id, entry in data.items():
        if not isinstance(entry, dict):
            continue
        try:
            numeric = int(entry.get("key"))
        except (TypeError, ValueError):
            continue
        out[numeric] = {"id": ddragon_id, "name": entry.get("name") or ddragon_id}
    return out


def _played_champions(map_id: int, conn: sqlite3.Connection) -> list[tuple]:
    """[(champion_id, games, wins)] over the tracked player's own matches."""
    try:
        sql = ("SELECT tracked_champion_id, COUNT(*), "
               "SUM(CASE WHEN tracked_win THEN 1 ELSE 0 END) "
               "FROM matches WHERE map_id = ? AND game_duration_s >= ? "
               "AND tracked_champion_id IS NOT NULL "
               "GROUP BY tracked_champion_id")
        return list(conn.execute(sql, (map_id, MIN_DURATION_S)).fetchall())
    except sqlite3.Error as exc:
        log.warning("patch_impact query: %s", exc)
        return []


def _index_changes(report: dict, mode: str) -> dict[str, dict]:
    """DDragon champion id -> {"champion": [...], "abilities": [...],
    "builds": [...], "build_items": set}. Fail-soft on any missing section."""
    index: dict[str, dict] = {}

    def slot(champ: str) -> dict:
        return index.setdefault(str(champ), {
            "champion": [], "abilities": [], "builds": [], "build_items": set(),
        })

    sections = report.get("sections") if isinstance(report, dict) else None
    sections = sections if isinstance(sections, dict) else {}

    champs = sections.get("champions") or {}
    for row in champs.get("changed") or []:
        if not isinstance(row, dict):
            continue
        entry = slot(row.get("id"))
        for field, pair in (row.get("fields") or {}).items():
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                entry["champion"].append({"field": field, "old": pair[0],
                                          "new": pair[1]})

    abilities = sections.get("abilities") or {}
    for row in abilities.get("changed") or []:
        if not isinstance(row, dict):
            continue
        entry = slot(row.get("champion"))
        key = row.get("key")
        if row.get("change"):
            entry["abilities"].append({"key": key, "field": row["change"],
                                       "old": None, "new": None})
            continue
        for field, pair in (row.get("fields") or {}).items():
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                entry["abilities"].append({"key": key, "field": field,
                                           "old": pair[0], "new": pair[1]})

    builds = ((sections.get("builds") or {}).get(mode) or {})
    for row in builds.get("changed") or []:
        if not isinstance(row, dict):
            continue
        entry = slot(row.get("champion"))
        pair = row.get("items")
        old, new = (pair[0], pair[1]) if isinstance(pair, (list, tuple)) and \
            len(pair) == 2 else (None, None)
        entry["builds"].append({"archetype": row.get("archetype"),
                                "old": old, "new": new})
        for side in (old, new):
            for item_id in side or []:
                entry["build_items"].add(str(item_id))

    return index


def _item_changes(report: dict) -> dict[str, dict]:
    """Item id -> {"name": str, "fields": [{"field","old","new"}]}."""
    sections = report.get("sections") if isinstance(report, dict) else None
    sections = sections if isinstance(sections, dict) else {}
    out: dict[str, dict] = {}
    for row in ((sections.get("items") or {}).get("changed") or []):
        if not isinstance(row, dict):
            continue
        fields = []
        for field, pair in (row.get("fields") or {}).items():
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                fields.append({"field": field, "old": pair[0], "new": pair[1]})
        if fields:
            out[str(row.get("id"))] = {
                "name": row.get("name") or str(row.get("id")),
                "fields": fields,
            }
    return out


def compute_patch_impact(mode: str = DEFAULT_MODE,
                         old_patch: Optional[str] = None,
                         new_patch: Optional[str] = None,
                         top_n: int = DEFAULT_TOP_N,
                         min_games: int = DEFAULT_MIN_GAMES,
                         conn: Optional[sqlite3.Connection] = None,
                         diff_fn: Optional[Callable] = None,
                         patches: Optional[list] = None,
                         key_map: Optional[dict] = None) -> dict:
    """The player's most-played champions, each annotated with what this patch
    changed for it.

    ``mode`` in VALID_MODES (else DEFAULT_MODE). ``old_patch`` / ``new_patch``
    default to the two newest snapshots on disk. ``conn`` / ``diff_fn`` /
    ``patches`` / ``key_map`` are test-injection seams. Never raises: any
    failure returns ok with ``champions: []`` and a populated ``reason``.
    """
    if mode not in MODE_MAPS:
        mode = DEFAULT_MODE
    try:
        top_n = max(1, int(top_n))
    except (TypeError, ValueError):
        top_n = DEFAULT_TOP_N
    try:
        min_games = max(1, int(min_games))
    except (TypeError, ValueError):
        min_games = DEFAULT_MIN_GAMES

    known = list(patches) if patches is not None else available_patches()
    if new_patch is None or old_patch is None:
        if len(known) < 2:
            return _empty(mode, old_patch, new_patch, top_n, min_games,
                          "fewer than two patch snapshots on disk")
        old_patch = old_patch or known[-2]
        new_patch = new_patch or known[-1]

    if diff_fn is None:
        try:
            from tools.ds_patch_diff import diff_snapshots as diff_fn  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - import is repo-local
            log.warning("patch_impact diff import: %s", exc)
            return _empty(mode, old_patch, new_patch, top_n, min_games,
                          "patch diff tool unavailable")
    try:
        report = diff_fn(old_patch, new_patch)
    except Exception as exc:  # noqa: BLE001 - never raises
        log.warning("patch_impact diff: %s", exc)
        return _empty(mode, old_patch, new_patch, top_n, min_games,
                      "patch diff failed - see logs")

    index = _index_changes(report, mode)
    items = _item_changes(report)
    names = key_map if key_map is not None else champion_key_map(new_patch)

    own = conn is None
    if own:
        conn = _open_ro()
    rows = _played_champions(MODE_MAPS[mode], conn) if conn is not None else []
    if own and conn is not None:
        try:
            conn.close()
        except sqlite3.Error:
            pass

    played = []
    total = 0
    for champ_id, games, wins in rows:
        try:
            champ_id, games, wins = int(champ_id), int(games), int(wins or 0)
        except (TypeError, ValueError):
            continue
        total += games
        if games >= min_games:
            played.append((champ_id, games, wins))
    played.sort(key=lambda r: (-r[1], r[0]))

    out = []
    for champ_id, games, wins in played[:top_n]:
        meta = names.get(champ_id) or {}
        ddragon_id = meta.get("id")
        changes = index.get(ddragon_id) if ddragon_id else None
        changes = changes or {"champion": [], "abilities": [], "builds": [],
                              "build_items": set()}
        touched = [
            {"item_id": iid, **items[iid]}
            for iid in sorted(changes["build_items"]) if iid in items
        ]
        count = (len(changes["champion"]) + len(changes["abilities"])
                 + len(changes["builds"]) + len(touched))
        out.append({
            "champion_id": champ_id,
            "champion": ddragon_id,
            "name": meta.get("name"),
            "games": games,
            "wins": wins,
            "winrate": round(100.0 * laplace_rate(wins, games), 1),
            "play_share": round(100.0 * games / total, 1) if total else None,
            "change_count": count,
            "champion_changes": changes["champion"],
            "ability_changes": changes["abilities"],
            "build_changes": changes["builds"],
            "item_changes": touched,
        })

    payload = _empty(mode, old_patch, new_patch, top_n, min_games, None)
    payload["champions"] = out
    payload["n_matches"] = total
    payload["changed_items"] = len(items)
    return payload


def _empty(mode: str, old_patch, new_patch, top_n: int, min_games: int,
           reason: Optional[str]) -> dict:
    return {
        "ok": True,
        "mode": mode,
        "old_patch": old_patch,
        "new_patch": new_patch,
        "top_n": top_n,
        "min_games": min_games,
        "n_matches": 0,
        "changed_items": 0,
        "reason": reason,
        "champions": [],
    }
