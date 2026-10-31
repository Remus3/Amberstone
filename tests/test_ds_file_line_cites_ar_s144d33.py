"""Guard: core/champion_movespeed.py cites its non-DS sources by symbol (RM-1053).

Measured 2026-10-31 at ENGINE 1.290.0. An earlier RM-1053 part (b107a8593,
ratchet ``ah``) moved the module's DS-targeted cite (``ITEM_STAT_KEY_MAP``)
to a symbol and left five non-DS line cites in place. All five were exact
when the module was written (62a611f2b) and all five had drifted:

- ``core/defensive_picks.py:83-88`` - the name / id alias loop in
  ``_load_champ_info``. Now seven lines lower.
- ``core/vision_tracker.py:55`` (three times) - the "League SR map is
  roughly 14800x14800" comment in the zone-labelling block above
  ``_sr_zone``. Now two lines lower.
- ``dashboard/_liveclient.py:131,135`` - the ``displayName`` / ``itemID``
  reads of the active player's items. The ``displayName`` read now lives in
  ``liveclient_summary``, 234 lines lower; the ``itemID`` read moved up into
  its ``_item_ids`` helper, 66 lines lower.

The tests below ratchet the module to zero line cites, pin the symbol cites,
re-derive each restated claim by AST or text, and confirm the original cites
were exact at the authoring commit.
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

_PY_LINE = re.compile(r"(?<![\w./])[\w/]+\.py:\s?\d")
_PROSE_LINE = re.compile(r"\blines? ~?\d{2,}")

TARGET = "core/champion_movespeed.py"
PICKS = "core/defensive_picks.py"
TRACKER = "core/vision_tracker.py"
LIVE = "dashboard/_liveclient.py"
AUTHORED_SHA = "62a611f2b"
EXTENT_COMMENT = "# League SR map is roughly 14800x14800 game units"

NEEDLES = (
    "the name / id alias loop in ``_load_champ_info`` (core/defensive_picks.py).",
    "SR map extent ~14800 units per the zone-labelling\n"
    "    comment above ``_sr_zone`` in core/vision_tracker.py).",
    "# SR map extent in game units (the zone-labelling comment above ``_sr_zone``\n"
    "# in core/vision_tracker.py).",
    "(``liveclient_summary`` and its\n"
    "    ``_item_ids`` helper in dashboard/_liveclient.py)",
    "core/vision_tracker.py zone-labelling comment above ``_sr_zone``).",
)


def _text(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _func(rel: str, name: str) -> ast.FunctionDef:
    for node in ast.parse(_text(rel)).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not defined in {rel}")


def _reads(func: ast.FunctionDef, key: str) -> bool:
    return any(
        isinstance(n, ast.Call)
        and ast.unparse(n.func).endswith(".get")
        and n.args
        and isinstance(n.args[0], ast.Constant)
        and n.args[0].value == key
        for n in ast.walk(func)
    )


def test_patterns_match_the_rotted_shapes():
    for sample in (
        "    core/defensive_picks.py:83-88.",
        "    the safe degrade; SR map extent ~14800 units per core/vision_tracker.py:55).",
        "    itemID / displayName (dashboard/_liveclient.py:131,135).\"\"\"",
    ):
        assert _PY_LINE.search(sample), sample
    for needle in NEEDLES:
        for line in needle.splitlines():
            assert not _PY_LINE.search(line), line
            assert not _PROSE_LINE.search(line), line


def test_target_cites_by_symbol():
    text = _text(TARGET)
    hits = [
        i for i, line in enumerate(text.splitlines(), 1)
        if _PY_LINE.search(line) or _PROSE_LINE.search(line)
    ]
    assert hits == [], hits
    for needle in NEEDLES:
        assert needle in text, needle


def test_load_champ_info_indexes_name_and_id_with_stripped_variants():
    func = _func(PICKS, "_load_champ_info")
    loops = [
        n for n in ast.walk(func)
        if isinstance(n, ast.For)
        and ast.unparse(n.iter) == "(entry.get('name'), entry.get('id'))"
    ]
    assert len(loops) == 1, len(loops)
    keys = {
        ast.unparse(t.slice)
        for n in ast.walk(loops[0]) if isinstance(n, ast.Assign)
        for t in n.targets if isinstance(t, ast.Subscript)
    }
    assert {
        "key",
        "key.replace(\"'\", '')",
        "key.replace(' ', '')",
        "key.replace(\"'\", '').replace(' ', '')",
    } <= keys, keys


def test_sr_zone_is_preceded_by_the_14800_extent_comment():
    lines = _text(TRACKER).splitlines()
    zone = _func(TRACKER, "_sr_zone").lineno
    above = [i for i, ln in enumerate(lines[:zone], 1) if ln.startswith(EXTENT_COMMENT)]
    assert above, "extent comment missing above _sr_zone"
    assert zone - above[-1] <= 8, (above[-1], zone)
    tgt = _text(TARGET)
    assert "_SR_MAP_EXTENT = 14800.0" in tgt


def test_liveclient_reads_display_name_and_item_id_in_the_named_symbols():
    assert _reads(_func(LIVE, "liveclient_summary"), "displayName")
    assert _reads(_func(LIVE, "_item_ids"), "itemID")
    summary = ast.unparse(_func(LIVE, "liveclient_summary"))
    assert "_item_ids(me_pl.get('items'))" in summary


def _at(sha: str, rel: str) -> list[str] | None:
    out = subprocess.run(
        ["git", "show", f"{sha}:{rel}"],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8", check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if out.returncode != 0:
        return None
    return out.stdout.splitlines()


def test_original_cites_were_exact_at_the_authoring_commit():
    picks = _at(AUTHORED_SHA, PICKS)
    if picks is None:
        return  # shallow clone without that commit: the live halves above still run
    assert picks[82].strip() == 'for key in (entry.get("name"), entry.get("id")):'
    assert picks[87].strip() == 'out[key.replace("\'", "").replace(" ", "")] = slim'
    tracker = _at(AUTHORED_SHA, TRACKER)
    assert tracker is not None and tracker[54].startswith(EXTENT_COMMENT)
    live = _at(AUTHORED_SHA, LIVE)
    assert live is not None
    assert 'it.get("displayName", "")' in live[130]
    assert 'it.get("itemID", "")' in live[134]
    authored = _at(AUTHORED_SHA, TARGET)
    assert authored is not None
    body = "\n".join(authored)
    assert "core/defensive_picks.py:83-88" in body
    assert body.count("core/vision_tracker.py:55") == 3
    assert "dashboard/_liveclient.py:131,135" in body
