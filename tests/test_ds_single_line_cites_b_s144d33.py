"""Guard: four more DS tests cite by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. Each file below carried exactly one
line cite:

- ``test_ability_wiki_form_damage_rm95b.py`` cited
  ``tools/daemon_slayer_wiki_ability_extract.py:108-110`` for the wiki host
  and endpoint; those constants now sit one line lower, so the range opens on
  a comment and drops ``WIKI_RAW_MODULE``.
- ``test_aram_ability_haste_consumption.py`` cited ``engine.py:273`` for the
  write of ``scaled["aram_ability_haste"]``; :273 is now inside the
  ``engine._apply_mode_modifiers`` docstring and the write is ~30 lines lower.
- ``test_champion_ally_reach_overrides.py`` cited
  ``_item_ally_grant.py:95-105`` for the hard exclusions; it still resolves
  to ``_ALLY_GRANT_EXCLUDED_ITEM_IDS``, but a range cite rots on the next edit
  above it.
- ``test_ds_sweep_lifesteal_r181.py`` cited ``stats.py:110-111`` for the two
  vamp rows of ``stats.ITEM_STAT_KEY_MAP``; still resolving, same reason.

The tests below pin the cites and the claims they carried by symbol instead.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from agents.daemon_slayer import _item_ally_grant, engine, stats
from tools import daemon_slayer_wiki_ability_extract as wiki_extract

REPO = Path(__file__).resolve().parent.parent
TESTS = REPO / "agents" / "daemon_slayer" / "tests"
_LINE_CITE = re.compile(r"(?<![\w.])\w+\.py:\d")

TARGETS = {
    "test_ability_wiki_form_damage_rm95b.py": ("``WIKI_HOST``", "``WIKI_API``"),
    "test_aram_ability_haste_consumption.py": ("``engine._apply_mode_modifiers``",),
    "test_champion_ally_reach_overrides.py": (
        "``_item_ally_grant._ALLY_GRANT_EXCLUDED_ITEM_IDS``",
    ),
    "test_ds_sweep_lifesteal_r181.py": ("``stats.ITEM_STAT_KEY_MAP``",),
}


def test_pattern_matches_the_old_shapes():
    for sample in (
        "``tools/daemon_slayer_wiki_ability_extract.py:108-110`` uses):",
        "(engine.py:273), so the result",
        "hard-excluded at ``_item_ally_grant.py:95-105``).",
        "(stats.py:110-111). ``aggregate_item_stats`` sums",
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (
        "``engine._apply_mode_modifiers``",
        "``tools/daemon_slayer_wiki_ability_extract.py``",
        "test_beam.py:",
    ):
        assert not _LINE_CITE.search(sample), sample


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_no_line_cite_left(name):
    text = (TESTS / name).read_text(encoding="utf-8")
    hits = [
        f"{name}:{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_names_the_symbols(name):
    text = (TESTS / name).read_text(encoding="utf-8")
    for symbol in TARGETS[name]:
        assert symbol in text, f"{name}: {symbol}"


def test_wiki_extract_uses_the_cited_endpoint():
    assert wiki_extract.WIKI_HOST == "https://wiki.leagueoflegends.com"
    assert wiki_extract.WIKI_API == wiki_extract.WIKI_HOST + "/en-us/api.php"


def test_mode_modifiers_write_the_pure_aram_ah_delta():
    src = inspect.getsource(engine._apply_mode_modifiers)
    assert 'aram_ah = float(aram.get("aramAbilityHaste", 0.0))' in src
    assert 'scaled["aram_ability_haste"] = aram_ah' in src


def test_ally_grant_hard_excludes_the_four_support_items():
    excluded = _item_ally_grant._ALLY_GRANT_EXCLUDED_ITEM_IDS
    for iid in ("3109", "3050", "2524", "3876"):
        assert iid in excluded, iid
    assert "3190" not in excluded
    assert "iid in _ALLY_GRANT_EXCLUDED_ITEM_IDS" in inspect.getsource(
        _item_ally_grant
    )


def test_item_stat_key_map_routes_the_vamp_stats():
    assert stats.ITEM_STAT_KEY_MAP["PercentLifeStealMod"] == ("lifesteal", "pct")
    assert stats.ITEM_STAT_KEY_MAP["PercentSpellVampMod"] == ("spellvamp", "pct")
