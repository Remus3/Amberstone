"""Recover the set of stored matches the operator played WITH a pro.

The original plan for this was a Riot API fan-out: resolve every pro Riot ID to
a puuid, page each pro's Match-V5 id list, and intersect with the operator's.
That is unnecessary. `data/rewind_history.db` already stores
`participants.riot_id_game_name` + `riot_id_tagline` for 29418 of 30592
participant rows, so the recovery is a local read-only SQL join costing zero
API calls. See `docs/_scratch/PRO_MATCH_RECOVERY_SPEC.md` for the measurement.

The pro roster lives in an .xlsx on the operator's Desktop. Neither openpyxl nor
pandas is installed on the Python314 interpreter, so the sheet is parsed with
stdlib zipfile + ElementTree against the two parts that matter:
`xl/sharedStrings.xml` and `xl/worksheets/sheet1.xml`.

Read-only by construction: the DB is opened `mode=ro` via URI. This module never
writes.
"""

from __future__ import annotations

import sqlite3
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any, Optional

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

DEFAULT_ROSTER_PATH = Path(
    r"C:\Users\Administrator\Desktop\Challenger\Played with Pro List.xlsx"
)

# The operator's accounts share one game name across both taglines
# (#Vayne and #Trist), so the join keys on the game name alone.
OPERATOR_GAME_NAME = "SamplePlayer"


def _sheet_rows(xlsx_path: Path) -> list[list[str]]:
    """Return sheet1 as a list of row-cell-string lists (stdlib only)."""
    with zipfile.ZipFile(xlsx_path) as z:
        shared = [
            "".join(t.text or "" for t in si.iter(_NS + "t"))
            for si in ET.fromstring(z.read("xl/sharedStrings.xml"))
        ]
        sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    rows: list[list[str]] = []
    for row in sheet.iter(_NS + "row"):
        cells: list[str] = []
        for cell in row.iter(_NS + "c"):
            value = cell.find(_NS + "v")
            if value is None or value.text is None:
                cells.append("")
            elif cell.get("t") == "s":
                cells.append(shared[int(value.text)])
            else:
                cells.append(value.text)
        rows.append(cells)
    return rows


def load_pro_roster(xlsx_path: Optional[Path] = None) -> list[dict]:
    """Parse the pro list into roster dicts.

    Sheet header is `NA Summoner | Role / Team | Pro Name`. Rows without a
    `#`-bearing Riot ID in column 0 are skipped - the sheet carries trailing
    blank rows (90 raw rows, 30 populated as of 2026-07-20).
    """
    path = Path(xlsx_path) if xlsx_path is not None else DEFAULT_ROSTER_PATH
    roster: list[dict] = []
    for cells in _sheet_rows(path)[1:]:
        if not cells or not cells[0] or "#" not in cells[0]:
            continue
        riot_id = cells[0].strip()
        game_name, _, tagline = riot_id.partition("#")
        roster.append(
            {
                "riot_id": riot_id,
                "game_name": game_name,
                "tagline": tagline,
                "role_team": cells[1].strip() if len(cells) > 1 else "",
                "pro_name": cells[2].strip() if len(cells) > 2 else "",
            }
        )
    return roster


def find_pro_matches(
    db_path: str | Path,
    roster: list[dict],
    same_team_only: bool = True,
) -> dict[str, list[dict]]:
    """Map match_id -> the pros in that match, joined locally.

    With ``same_team_only`` (the default) a match is returned only when the pro
    shared the operator's ``team_id`` - "played WITH", not "played against".
    The flag selects which matches are RETURNED; it never changes what
    ``same_team`` MEANS. Every emitted row carries the real answer, so the two
    modes agree on any match they both return.

    Never joins on puuid: `participants.puuid` holds two distinct values per
    operator tagline because the API key rotated, and a fresh API puuid will
    not match a stored one. The Riot ID is the durable identity.
    """
    uri = f"file:{Path(db_path).as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        # Loaded in BOTH modes on purpose. `same_team` is emitted on every
        # returned row, so populating this only under `same_team_only` would
        # leave the dict empty in the other mode, make `.get(match_id)` return
        # None, and pin the flag to False on matches the pro genuinely shared.
        rows = conn.execute(
            "SELECT match_id, team_id FROM participants "
            "WHERE lower(riot_id_game_name) = ?",
            (OPERATOR_GAME_NAME.lower(),),
        )
        operator_team: dict[str, int] = {mid: tid for mid, tid in rows}

        found: dict[str, list[dict]] = {}
        for pro in roster:
            rows = conn.execute(
                "SELECT match_id, team_id FROM participants "
                "WHERE lower(riot_id_game_name) = ? "
                "AND lower(riot_id_tagline) = ?",
                (pro["game_name"].lower(), pro["tagline"].lower()),
            )
            for match_id, team_id in rows:
                same_team = operator_team.get(match_id) == team_id
                if same_team_only and not same_team:
                    continue
                found.setdefault(match_id, []).append(
                    {
                        "pro_name": pro["pro_name"],
                        "role_team": pro["role_team"],
                        "riot_id": pro["riot_id"],
                        "same_team": same_team,
                    }
                )
        return found
    finally:
        conn.close()


def describe_matches(
    db_path: str | Path,
    match_ids: list[str],
) -> dict[str, dict[str, Any]]:
    """Return per-match metadata for the recovered ids (ingestion evidence)."""
    if not match_ids:
        return {}
    uri = f"file:{Path(db_path).as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        placeholders = ",".join("?" * len(match_ids))
        rows = conn.execute(
            "SELECT match_id, queue_id, patch, game_creation_ts, "
            "has_stats, has_timeline FROM matches "
            f"WHERE match_id IN ({placeholders})",
            tuple(match_ids),
        )
        return {
            r[0]: {
                "queue_id": r[1],
                "patch": r[2],
                "game_creation_ts": r[3],
                "has_stats": r[4],
                "has_timeline": r[5],
            }
            for r in rows
        }
    finally:
        conn.close()
