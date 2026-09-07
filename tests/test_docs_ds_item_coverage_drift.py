"""Guard (RM-203): the DS item-coverage prose is re-derived from data, never recited.

``docs/DAEMON_SLAYER.md`` carried ``547/547 DDragon purchasable items`` from the
day the file was created (`4e4a8a8f`, 2026-05-06) until RM-203. It was never a
ratio: 547 was ``len(ITEM_EFFECTS)`` at that commit, written twice, and the
DDragon purchasable population measured 544 / 468 / 466 (three defensible
definitions) on that same snapshot - so no denominator ever reproduced it. The
sibling ``test_docs_daemon_slayer_drift`` deliberately pins only STABLE
identifiers (ENGINE_VERSION, patch, route list) and says so in its own docstring,
which is exactly why a fabricated count could sit in the same file for months.

This guard closes that hole for the item-coverage figures specifically: it
RE-DERIVES every number from the live snapshot on disk and compares it to the
prose, so a patch refresh that moves the item table fails locally instead of
rotting silently (CI runs no pytest on docs). It also pins the ``file:line``
citation the prose leans on - the same doc already suffered one PAST_EOF pointer
(``DAEMON_SLAYER.md:122`` repointed to ``:35`` on 2026-08-06).

Deliberately NOT pinned: the status banner at line 5 (owned by the ENGINE-bump
ritual and covered by ``test_docs_daemon_slayer_drift``) and any ``def test_``
count. ASCII only (CLAUDE.md hard rule).
"""
import json
import re
from pathlib import Path

from agents.daemon_slayer._effects_data import ITEM_EFFECTS
from agents.daemon_slayer.rank import _is_purchasable

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOC = _REPO_ROOT / "docs" / "DAEMON_SLAYER.md"
_GAP_DOC = _REPO_ROOT / "docs" / "DS_COMPLETENESS_GAP.md"
_DATA_ROOT = _REPO_ROOT / "data" / "daemon_slayer"
_CURRENT = _DATA_ROOT / "current.txt"

# The batch-55 coverage gate (agents/daemon_slayer/tests/test_effects_expansion.py)
# carves these id namespaces out of the covered population: 9xxxx Quickplay and
# 55xxxx cosmetics are shop rows the scorers are never asked to rank.
_EXCLUDED_ID_PREFIXES = ("9", "55")

_DOC_PATCH = re.compile(r"Item coverage at patch (\d+\.\d+\.\d+)")
_DOC_REGISTRY = re.compile(r"`ITEM_EFFECTS` registry (\d+) entries")
_DOC_TOTAL = re.compile(r"DDragon ships (\d+) items total")
_DOC_FLAG = re.compile(r"(\d+) carry the bare `gold\.purchasable` flag")
_DOC_GATE = re.compile(r"(\d+) clear the engine's own shop gate")
_DOC_CREDITED = re.compile(r"(\d+) of those (\d+) carry an `ITEM_EFFECTS` entry")
_DOC_GATE_RATIO = re.compile(r"own population is (\d+)/(\d+)")
_DOC_UNCREDITED_ID = re.compile(r"the lone uncredited row is `(\d+)`")
_DOC_PREDICATE_CITE = re.compile(r"`agents/daemon_slayer/rank\.py:(\d+)`")
# The exact shape of the original defect: a bare ratio with no stated population.
_BARE_RATIO = re.compile(r"\d+/\d+\s+DDragon purchasable")


def _doc_text() -> str:
    return _DOC.read_text(encoding="utf-8")


def _live_items() -> dict:
    patch = _CURRENT.read_text(encoding="utf-8").strip()
    items_path = _DATA_ROOT / patch / "items.json"
    assert items_path.is_file(), f"no items.json for live patch {patch} at {items_path}"
    return json.loads(items_path.read_text(encoding="utf-8"))["data"]


def _measured() -> dict:
    items = _live_items()
    covered = set(ITEM_EFFECTS)
    flag = {k for k, v in items.items() if (v.get("gold") or {}).get("purchasable")}
    gate = {k for k, v in items.items() if _is_purchasable(v)}
    gate_pop = {k for k in gate if not k.startswith(_EXCLUDED_ID_PREFIXES)}
    return {
        "registry": len(ITEM_EFFECTS),
        "total": len(items),
        "flag": len(flag),
        "gate": len(gate),
        "credited": len(gate & covered),
        "gate_pop": len(gate_pop),
        "gate_pop_credited": len(gate_pop & covered),
        "uncredited": sorted(gate - covered),
    }


def _one(pattern: re.Pattern, label: str) -> re.Match:
    m = pattern.search(_doc_text())
    assert m, (
        f"docs/DAEMON_SLAYER.md item-coverage line no longer states {label} in the "
        f"form this guard parses ({pattern.pattern!r}). Do not delete the figure to "
        "make the guard pass - restate it, or update the pattern with the prose."
    )
    return m


def test_doc_item_coverage_patch_matches_current_txt():
    live = _CURRENT.read_text(encoding="utf-8").strip()
    assert _one(_DOC_PATCH, "the patch its item figures were measured at").group(1) == live


def test_doc_registry_size_matches_item_effects():
    doc = int(_one(_DOC_REGISTRY, "the ITEM_EFFECTS registry size").group(1))
    assert doc == len(ITEM_EFFECTS), (
        f"docs/DAEMON_SLAYER.md says the ITEM_EFFECTS registry holds {doc} entries; "
        f"len(ITEM_EFFECTS) is {len(ITEM_EFFECTS)}."
    )


def test_doc_ddragon_populations_match_the_live_snapshot():
    m = _measured()
    doc_total = int(_one(_DOC_TOTAL, "the DDragon total item count").group(1))
    doc_flag = int(_one(_DOC_FLAG, "the gold.purchasable flag count").group(1))
    doc_gate = int(_one(_DOC_GATE, "the _is_purchasable gate count").group(1))
    assert doc_total == m["total"], f"doc DDragon total {doc_total} != measured {m['total']}"
    assert doc_flag == m["flag"], f"doc gold.purchasable count {doc_flag} != measured {m['flag']}"
    assert doc_gate == m["gate"], f"doc _is_purchasable count {doc_gate} != measured {m['gate']}"
    # The three populations are distinct by construction; if a data refresh ever
    # collapses them the prose stops earning its three separate labels.
    assert m["gate"] < m["flag"] < m["total"], (
        f"the three item populations no longer nest as gate < flag < total: {m}"
    )


def test_doc_credited_counts_match_the_engine_registry():
    m = _measured()
    credited_m = _one(_DOC_CREDITED, "the credited-of-gate ratio")
    assert int(credited_m.group(1)) == m["credited"], (
        f"doc credits {credited_m.group(1)} of the gate population; measured {m['credited']}"
    )
    assert int(credited_m.group(2)) == m["gate"], (
        f"doc gate denominator {credited_m.group(2)} != measured {m['gate']}"
    )
    ratio_m = _one(_DOC_GATE_RATIO, "the batch-55 gate-population coverage ratio")
    assert int(ratio_m.group(1)) == m["gate_pop_credited"], (
        f"doc gate-population numerator {ratio_m.group(1)} != measured {m['gate_pop_credited']}"
    )
    assert int(ratio_m.group(2)) == m["gate_pop"], (
        f"doc gate-population denominator {ratio_m.group(2)} != measured {m['gate_pop']}"
    )


def test_doc_names_the_actual_uncredited_ids():
    m = _measured()
    doc_ids = _DOC_UNCREDITED_ID.findall(_doc_text())
    assert sorted(doc_ids) == m["uncredited"], (
        f"docs/DAEMON_SLAYER.md names {sorted(doc_ids)} as the uncredited purchasable "
        f"row(s); the live snapshot leaves {m['uncredited']} uncredited."
    )


def test_doc_predicate_citation_still_points_at_is_purchasable():
    cite = _one(_DOC_PREDICATE_CITE, "the rank.py _is_purchasable file:line citation")
    lineno = int(cite.group(1))
    lines = (_REPO_ROOT / "agents" / "daemon_slayer" / "rank.py").read_text(
        encoding="utf-8"
    ).splitlines()
    assert lineno <= len(lines), f"rank.py:{lineno} is PAST_EOF ({len(lines)} lines)"
    assert lines[lineno - 1].startswith("def _is_purchasable"), (
        f"docs/DAEMON_SLAYER.md cites rank.py:{lineno} for _is_purchasable but that "
        f"line reads {lines[lineno - 1]!r}."
    )


def test_doc_carries_no_bare_purchasable_ratio():
    hit = _BARE_RATIO.search(_doc_text())
    assert hit is None, (
        f"docs/DAEMON_SLAYER.md re-acquired a bare population-free coverage ratio "
        f"({hit.group(0)!r} - the RM-203 defect). State each count beside the "
        "population it counts."
    )


def test_gap_doc_points_at_the_guarded_figures_instead_of_restating_them():
    assert "docs/DAEMON_SLAYER.md:10" in _GAP_DOC.read_text(encoding="utf-8"), (
        "docs/DS_COMPLETENESS_GAP.md lost its pointer to the guarded item-coverage "
        "line; it is a dated snapshot and must not re-inline live counts."
    )
