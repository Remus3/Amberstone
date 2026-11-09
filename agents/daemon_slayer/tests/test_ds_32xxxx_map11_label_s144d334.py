"""S144-D-334..337 - no DS module calls a 32xxxx item id an "ARAM mirror".

WHY. DDragon ships one item under several ids. The DS prose labelled the
``32xxxx`` family "ARAM mirrors" in about sixty comment, docstring and note
lines across eighteen modules. The live feed says otherwise: every ``32xxxx``
row carries map 11 (Summoner's Rift) only, never map 12 (Howling Abyss), and
did so in every snapshot from 16.10.1 to 16.22.1. The ARAM copies are the
``12xxxx`` rows (map 12 only at 16.22.1; 126697 also carried map 35 in the
16.10.1 to 16.15.1 snapshots). The engine never keyed a mode gate on the label
(``ehp._MODE_MIRROR_ID_PREFIXES`` is a lookup prefix list), so the defect is
prose only. It still misleads anyone reading a registry to decide what ARAM
can buy. What the ``32xxxx`` family is for is unverified here: the rows cost
more and carry larger stats than their base ids.

* S144-D-334: the registry modules (``_item_*``, ``_scaling_hsp``,
  ``_hsp_amp``, the override registries, ``_effects_types``) relabel every
  ``32xxxx`` id as the map-11 copy.
* S144-D-335: ``ehp.py`` and ``hps.py`` comments do the same.
* S144-D-336: ``_effects_data.py`` section headers, comments and ``note=``
  strings do the same. A note string reaches the ``/dps`` notes text, never a
  number.
* S144-D-337: this guard. The live premise (32xxxx = map 11 only, 12xxxx =
  map 12 only) is re-derived from the current snapshot, so a re-extract that
  changes it fails here first.

MEASURED 2026-11-09 (``data/daemon_slayer/current.txt`` = 16.22.1): 26 rows
``32xxxx``, all map 11 only; 3 rows ``12xxxx``, all map 12 only. Prose-only
change; scorer output is byte-identical.

Blind spot: the scan is line-based (plus a line and its successor for a label
split across a line break). A label spread over three lines is not caught.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[3]
_DS_PKG = _ROOT / "agents" / "daemon_slayer"
_DS_DATA = _ROOT / "data" / "daemon_slayer"

_ID32 = r"(?:\b32\d{4}\b|\b32xxxx\b|\b32\*)"
_ID12 = re.compile(r"\b12\d{4}\b")
_ARAM = re.compile(r"\bARAM\b")
_TOKEN32 = re.compile(_ID32)
_MIRROR_PHRASE = re.compile(r"\bARAM[\s-]*(?:mode[\s-]*)?mirror", re.IGNORECASE)
_SPLIT = re.compile(r"\bARAM\s*$")
_LEAD32 = re.compile(r"^\s*(?:#\s*)?(?:\*\s*)?" + _ID32)


@cache
def _live_items() -> dict[str, Any]:
    patch = (_DS_DATA / "current.txt").read_text(encoding="utf-8").strip()
    doc = json.loads((_DS_DATA / patch / "items.json").read_text(encoding="utf-8"))
    return doc["data"]


def _maps(row: dict[str, Any]) -> frozenset[str]:
    return frozenset(k for k, v in (row.get("maps") or {}).items() if v)


def _prefixed(prefix: str) -> dict[str, dict[str, Any]]:
    return {
        k: v
        for k, v in _live_items().items()
        if len(k) == 6 and k.startswith(prefix)
    }


def _line_problems(lines: list[str]) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        if _ARAM.search(line) and _TOKEN32.search(line):
            out.append((i + 1, line.strip()))
            continue
        if _MIRROR_PHRASE.search(line) and not _ID12.search(line):
            out.append((i + 1, line.strip()))
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if _SPLIT.search(line) and _LEAD32.search(nxt):
            out.append((i + 1, line.strip()))
    return out


def _module_files() -> list[Path]:
    return sorted(p for p in _DS_PKG.glob("*.py") if p.is_file())


def test_live_32xxxx_rows_are_map_11_only() -> None:
    rows = _prefixed("32")
    assert rows, "no 32xxxx rows in the live snapshot - the premise needs a re-measure"
    wrong = {k: sorted(_maps(v)) for k, v in rows.items() if _maps(v) != {"11"}}
    assert not wrong, f"32xxxx rows not map-11-only: {wrong}"


def test_live_12xxxx_rows_are_map_12_only() -> None:
    rows = _prefixed("12")
    assert rows, "no 12xxxx rows in the live snapshot - the premise needs a re-measure"
    wrong = {k: sorted(_maps(v)) for k, v in rows.items() if _maps(v) != {"12"}}
    assert not wrong, f"12xxxx rows not map-12-only: {wrong}"


def test_module_scan_is_not_empty() -> None:
    files = _module_files()
    assert len(files) > 50, f"DS module scan found only {len(files)} files"
    assert any(p.name == "_effects_data.py" for p in files)
    assert any(p.name == "ehp.py" for p in files)


def test_no_ds_module_labels_a_32xxxx_id_aram() -> None:
    problems: list[str] = []
    for path in _module_files():
        lines = path.read_text(encoding="utf-8").splitlines()
        for lineno, text in _line_problems(lines):
            problems.append(f"{path.name}:{lineno}: {text}")
    assert not problems, (
        "32xxxx ids are map 11 (SR) only in the live feed; relabel these lines:\n"
        + "\n".join(problems)
    )


def test_checker_flags_planted_labels() -> None:
    planted = [
        'note="Manamune (ARAM 323004): same as SR 3004"',
        "    function ``32xxxx`` (SR/ARAM mirror) ids",
        "  * 323157   - Zhonya's ARAM mirror.",
        "    these ARAM mirrors ARE in the index",
        "    # Frozen Heart (SR 3110 / ARAM",
        "    # 323110 / Arena 223110)",
    ]
    flagged = {lineno for lineno, _ in _line_problems(planted)}
    assert flagged == {1, 2, 3, 4, 5}, flagged


def test_checker_passes_correct_labels() -> None:
    clean = [
        'note="Manamune (map-11 copy 323004): same as SR 3004"',
        "    # DSV2 (1.125.0): ARAM mirror 126697 of SR 6697",
        "    # ARAM/Arena mega-item Void Immolation (223069)",
        "    # Arena 22xxxx / map-11 32xxxx copies",
        "    ``None`` / empty -> False, so a non-Arena (SR/ARAM) call",
    ]
    assert _line_problems(clean) == []
