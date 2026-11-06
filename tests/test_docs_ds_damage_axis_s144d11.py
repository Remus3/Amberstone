"""Guard (RM-986): the DS doc's ``hybrid.py`` AD-axis figures stay true.

``docs/DAEMON_SLAYER.md`` said, in the present tense, that ``_damage_axis``
"resolves 92 of 173 champions to "ad"". That was the L1 count (patch
16.14.1), when the axis came from the DDragon ``info.attack`` /
``info.magic`` rating alone. Commit 9ba55608e (2026-08-02) made
``_damage_axis`` read the kit's own ``lolmath.damage_distribution`` first and
fall back to the rating only when that split is not decisive. Measured
2026-10-27 at patch 16.21.1: 85 of 173 resolve to "ad", 164 are decided by
the kit split, and the rating alone would still give 92 - so the doc was
quoting the fallback rule's count as the live one.

Every figure is measured from the snapshot named by ``current.txt``, never
from a literal here. ASCII only (CLAUDE.md hard rule).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from agents.daemon_slayer import hybrid
from agents.daemon_slayer.data_loader import DataSnapshot

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOC = _REPO_ROOT / "docs" / "DAEMON_SLAYER.md"
_HYBRID_SRC = _REPO_ROOT / "agents" / "daemon_slayer" / "hybrid.py"
_CURRENT = _REPO_ROOT / "data" / "daemon_slayer" / "current.txt"

_LIVE = re.compile(
    r"at patch (\S+) it resolves (\d+) of (\d+) to `\"ad\"` "
    r"\((\d+) decided by the kit split; the rating alone would give (\d+)\)"
)


def _hybrid_row() -> str:
    for line in _DOC.read_text(encoding="utf-8").splitlines():
        if line.startswith("| `hybrid.py` |"):
            return line
    raise AssertionError("module map lost its hybrid.py row")


@pytest.fixture(scope="module")
def axis_counts() -> dict:
    snapshot = DataSnapshot.load()
    ids = list(snapshot.champions)
    ad = sum(1 for c in ids if hybrid._damage_axis(snapshot, c) == "ad")
    kit = sum(
        1 for c in ids
        if hybrid._kit_axis_from_distribution(snapshot.champions[c]) is not None
    )
    rating_ad = 0
    for c in ids:
        info = snapshot.champions[c].get("info") or {}
        magic = int(info.get("magic", 0) or 0)
        attack = int(info.get("attack", 0) or 0)
        if not magic > attack:
            rating_ad += 1
    return {"total": len(ids), "ad": ad, "kit": kit, "rating_ad": rating_ad}


def test_live_ad_axis_sentence_matches_current_snapshot(axis_counts):
    m = _LIVE.search(_hybrid_row())
    assert m, "hybrid.py row lost its live _damage_axis count sentence"
    patch, ad, total, kit, rating_ad = m.groups()
    assert patch == _CURRENT.read_text(encoding="utf-8").strip()
    assert int(total) == axis_counts["total"]
    assert int(ad) == axis_counts["ad"]
    assert int(kit) == axis_counts["kit"]
    assert int(rating_ad) == axis_counts["rating_ad"]


def test_no_present_tense_count_outside_the_live_sentence(axis_counts):
    # Any other "resolves N of M" in the row must not contradict the live count.
    row = _LIVE.sub("", _hybrid_row())
    for n, _total in re.findall(r"resolves (\d+) of (\d+)", row):
        assert int(n) == axis_counts["ad"], f"stale present-tense count {n}"


def test_credited_damage_types_named_in_row_match_the_constant():
    row = _hybrid_row()
    assert "from PHYSICAL to PHYSICAL + TRUE" in row
    assert frozenset({"PHYSICAL", "TRUE"}) == hybrid._AD_AXIS_CREDITED_DAMAGE_TYPES


def test_three_gate_sites_call_the_physical_ability_term():
    assert "at all three gate sites" in _hybrid_row()
    tree = ast.parse(_HYBRID_SRC.read_text(encoding="utf-8"))
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_physical_ability_damage"
    ]
    assert len(calls) == 3
