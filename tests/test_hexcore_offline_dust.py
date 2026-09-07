"""R138 guards for docs/HEXCORE_offline.html.

The offline HEXCORE explorer embeds its whole dataset as inline JS literals:
a CATS map, a NODES array, and a semicolon-joined DUST string of
``basename.py|category|parentNodeId`` triples. Nothing validates those at
runtime, so a hand-edited dust entry can silently point at a category or a
parent node that does not exist and the particle just never renders.

These tests parse the literals straight out of the HTML and assert the
referential integrity plus the ASCII-only repo rule.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HEXCORE = REPO_ROOT / "docs" / "HEXCORE_offline.html"

# The 54 net-new non-test .py files added since d584e02e. Everything under
# tests/ is excluded, which is what "non-test" means here.
EXPECTED_NEW_BASENAMES = (
    "_ability_base_overrides.py",
    "_ability_wiki_damage_registry.py",
    "_crit_conversion_overrides.py",
    "_kit_penetration.py",
    "_resist_damage_coupling.py",
    "cast_propensity.py",
    "ds_calibration_agreement.py",
    "next_buy_fallback.py",
    "ds_calibration_report.py",
    "_burst_off_axis.py",
    "_champion_ally_reach.py",
    "_item_ally_grant.py",
    "_item_health_stack.py",
    "_item_proc_heal.py",
    "_rune_flat_mitigation.py",
    "_rune_health_grants.py",
    "_rune_hsp_amp.py",
    "_rune_resist_grants.py",
    "_rune_offense_grants.py",
    "_rune_self_heal.py",
    "_rune_shield_grants.py",
    "kit_conversion.py",
    "onhit_dps.py",
    "aram_item_interaction.py",
    "aram_item_interaction_context.py",
    "fed_threat.py",
    "cc_threat.py",
    "draft_score.py",
    "ds_onhit_ap_roster.py",
    "ds_support_route_overrides.py",
    "patch_impact.py",
    "playstyle_labels.py",
    "pro_match_index.py",
    "rofl_archive.py",
    "rofl_stats_backfill.py",
    "session_hygiene.py",
    "_lcu_inprocess.py",
    "routes_draft_score.py",
    "routes_patch_impact.py",
    "routes_playstyle_labels.py",
    "routes_session_hygiene.py",
    "champ_select_shape.py",
    "snapshot_shape.py",
    "adjudicator.py",
    "aram_item_interaction_precompute.py",
    "ds_feed_index.py",
    "ds_onhit_ap_prefilter.py",
    "ds_patch_diff.py",
    "ds_wiki_staleness_check.py",
    "overlay_live_frame_probe.py",
    "pseudo_screen_overlay.py",
    "rofl_archiver.py",
    "rofl_tracked_backfill.py",
    "unresolved_token_scan.py",
)


@pytest.fixture(scope="module")
def html() -> str:
    assert HEXCORE.is_file(), f"missing {HEXCORE}"
    return HEXCORE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def dust_entries(html: str) -> list[str]:
    m = re.search(r'var DUST\s*=\s*"([^"]*)"', html)
    assert m, "could not locate the var DUST= literal"
    return [e for e in m.group(1).split(";") if e]


@pytest.fixture(scope="module")
def declared_dust_count(html: str) -> int:
    m = re.search(r"//\s*DUST:\s*(\d+)\s+real extra source files", html)
    assert m, "could not locate the // DUST: N comment"
    return int(m.group(1))


@pytest.fixture(scope="module")
def cat_keys(html: str) -> set[str]:
    start = html.index("var CATS=")
    body = html[start : html.index("var NODES=", start)]
    # keys are written bare (rules:{...}) and several share a line, so this
    # cannot be anchored to the start of a line.
    keys = set(re.findall(r"([a-z_]+)\s*:\s*\{", body))
    assert len(keys) >= 15, f"CATS parse looks wrong, got {sorted(keys)}"
    return keys


@pytest.fixture(scope="module")
def node_ids(html: str) -> set[str]:
    start = html.index("var NODES=")
    body = html[start : html.index("var DUST=", start)]
    arr = json.loads(body[body.index("[") : body.rindex("]") + 1])
    return {n["id"] for n in arr}


def test_new_source_files_present_as_dust(dust_entries: list[str]) -> None:
    basenames = {e.split("|")[0] for e in dust_entries}
    missing = sorted(b for b in EXPECTED_NEW_BASENAMES if b not in basenames)
    assert not missing, f"dust entries missing for: {missing}"


def test_declared_count_matches_actual(
    dust_entries: list[str], declared_dust_count: int
) -> None:
    assert declared_dust_count == len(dust_entries)


def test_sr_only_dust_count_matches(html: str, declared_dust_count: int) -> None:
    counts = re.findall(r"(\d+)\s+dust-file star particles", html)
    assert counts, "no 'N dust-file star particles' prose found"
    assert all(int(c) == declared_dust_count for c in counts), counts


def test_every_dust_entry_is_well_formed(
    dust_entries: list[str], cat_keys: set[str], node_ids: set[str]
) -> None:
    bad_shape: list[str] = []
    bad_cat: list[str] = []
    bad_parent: list[str] = []
    for entry in dust_entries:
        parts = entry.split("|")
        if len(parts) != 3:
            bad_shape.append(entry)
            continue
        name, cat, parent = parts
        if not name:
            bad_shape.append(entry)
        if cat not in cat_keys:
            bad_cat.append(entry)
        if parent not in node_ids:
            bad_parent.append(entry)
    assert not bad_shape, f"malformed dust entries: {bad_shape}"
    assert not bad_cat, f"dust entries with unknown category: {bad_cat}"
    assert not bad_parent, f"dust entries with unknown parent node: {bad_parent}"


def test_no_duplicate_dust_entries(dust_entries: list[str]) -> None:
    seen: set[str] = set()
    dupes: list[str] = []
    for entry in dust_entries:
        if entry in seen:
            dupes.append(entry)
        seen.add(entry)
    assert not dupes, f"duplicate dust entries: {dupes}"


def test_file_is_pure_ascii() -> None:
    raw = HEXCORE.read_bytes()
    offenders = [(i, b) for i, b in enumerate(raw) if b > 127]
    assert not offenders[:10], f"non-ascii bytes at {offenders[:10]}"


def test_engine_hud_row_has_title_tooltip(html: str) -> None:
    m = re.search(r"<[^>]*\btitle=\"([^\"]*)\"[^>]*>\s*engine:\s*DS", html)
    assert m, "engine HUD row is missing a native title= tooltip"
    assert "Daemon Slayer" in m.group(1), m.group(1)


def test_hud_engine_row_is_pointer_interactive(html: str) -> None:
    m = re.search(r"<[^>]*\btitle=\"[^\"]*\"[^>]*>\s*engine:\s*DS", html)
    assert m, "engine HUD row not found"
    assert "pointer-events:auto" in m.group(0), (
        "engine row needs pointer-events:auto or the title tooltip never fires "
        "under the HUD's pointer-events:none"
    )


def test_hud_reports_real_node_count(html: str, node_ids: set[str]) -> None:
    # Attribute-tolerant: R146 gave the countable HUD rows explanatory
    # title tooltips, and a bare-tag regex silently stopped matching
    # rather than reporting a wrong count.
    m = re.search(r"<div[^>]*>nodes:\s*(\d+)</div>", html)
    assert m, "HUD is missing a nodes: row"
    assert int(m.group(1)) == len(node_ids)


def test_hud_reports_dust_count(html: str, declared_dust_count: int) -> None:
    m = re.search(r"<div[^>]*>dust:\s*(\d+)\s+files</div>", html)
    assert m, "HUD is missing a dust: row"
    assert int(m.group(1)) == declared_dust_count


def test_main_script_block_parses_under_node(html: str) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH")
    marker = html.index("var CATS=")
    open_at = html.rindex("<script>", 0, marker)
    close_at = html.index("</script>", marker)
    body = html[open_at + len("<script>") : close_at]
    assert "var DUST=" in body, "extracted the wrong script block"

    fd, path = tempfile.mkstemp(suffix=".js", prefix="hexcore_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        proc = subprocess.run(
            [node, "--check", path],
            capture_output=True,
            text=True,
            timeout=60,
        )
    finally:
        os.unlink(path)
    assert proc.returncode == 0, proc.stderr or proc.stdout


def _repo_engine_version() -> str:
    src = (REPO_ROOT / "agents" / "daemon_slayer" / "__init__.py").read_text(
        encoding="utf-8"
    )
    m = re.search(r'^ENGINE_VERSION\s*=\s*"([^"]+)"', src, re.M)
    assert m, "could not read ENGINE_VERSION from agents/daemon_slayer/__init__.py"
    return m.group(1)


def _repo_patch() -> str:
    return (REPO_ROOT / "data" / "daemon_slayer" / "current.txt").read_text(
        encoding="utf-8"
    ).strip()


# R195: the engine/patch anchors in this file drifted silently across six
# hand refills (R146, R151, R157, R164, R188, b4df6494) because nothing tied
# them to the repo. These guards make a stale anchor a red test, not a
# cosmetic doc bug someone notices three ENGINE bumps later.
def test_hud_engine_anchor_matches_repo(html: str) -> None:
    engine, patch = _repo_engine_version(), _repo_patch()
    m = re.search(r"<div[^>]*>engine:\s*DS\s+([\d.]+)\s*/\s*patch\s+([\d.]+)</div>", html)
    assert m, "HUD is missing an engine: row"
    assert m.group(1) == engine, f"HUD engine {m.group(1)} != repo {engine}"
    assert m.group(2) == patch, f"HUD patch {m.group(2)} != repo {patch}"


def test_engine_tooltip_anchors_match_repo(html: str) -> None:
    engine, patch = _repo_engine_version(), _repo_patch()
    tips = re.findall(r'title="([^"]*ENGINE_VERSION[^"]*)"', html)
    assert tips, "no ENGINE_VERSION tooltip found"
    for tip in tips:
        assert f"ENGINE_VERSION {engine}" in tip, tip
        assert f"patch {patch}" in tip, tip


def test_daemonslayer_node_desc_engine_anchor_matches_repo(html: str) -> None:
    engine, patch = _repo_engine_version(), _repo_patch()
    m = re.search(r'"id": "daemonslayer".*?"desc": "([^"]+)"', html, re.S)
    assert m, "daemonslayer node not found"
    desc = m.group(1)
    assert f"ENGINE {engine}" in desc, desc
    assert f"patch {patch}" in desc, desc


def test_ds_test_count_anchor_is_internally_consistent(html: str) -> None:
    # The live count moves every batch, so pin consistency rather than a
    # literal: every place that cites a DS test count must cite the same one.
    counts = set(re.findall(r"(\d{4,5})\s+(?:DS\s+)?tests\b", html))
    assert counts, "no DS test-count anchor found"
    assert len(counts) == 1, f"DS test-count anchors disagree: {sorted(counts)}"
