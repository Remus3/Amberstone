"""Guard: ``_effects_types.py`` and ``dps.py`` cite by symbol, not line (RM-1053 part).

Measured 2026-10-30 at ENGINE 1.290.0:

- ``_effects_types.py`` cited ``ehp.py:21`` (still the "Shield throughput"
  bullet) and ``ehp.py:23`` (rotted: now the BT Ichorshield continuation line;
  the "Healing throughput" bullet sits three lines lower) for the two Phase 1
  deliberate omissions that ``ItemShield`` / ``ItemHeal`` close, twice each
  (class docstring + field comment). Both bullets live in the ``ehp`` module
  docstring's "Phase 1 deliberate omissions" list.
- ``dps.py`` cited ``engine.py:318-320`` (the item stat-block aggregation, now
  in ``engine.build_champion`` some 50 lines lower), ``engine.py:196`` (the AS
  rebuild, now ``out["as"] = ...`` in ``engine._combine_items``) and
  ``engine.py:439`` (the attack-speed-lock zeroing, now the
  ``as_lock.locks_as`` branch of ``engine.build_champion``). All three had
  rotted onto unrelated code.

The tests below pin the cites and the claims they carried by symbol instead.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from agents.daemon_slayer import ehp, engine

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
_LINE_CITE = re.compile(r"(?<![\w.])\w+\.py:\d")

TARGETS = {
    "_effects_types.py": (
        'Closes the Phase-1.5 "Shield throughput" bullet of the ``ehp`` module '
        'docstring\'s "Phase 1 deliberate omissions" list',
        'Closes the Phase-6 "Healing throughput" bullet of the ``ehp`` module '
        'docstring\'s "Phase 1 deliberate omissions" list',
        'closes the "Shield throughput" omission in the ``ehp`` module docstring',
        'closes the "Healing throughput" omission in the ``ehp`` module docstring',
    ),
    "dps.py": (
        "in the same shape ``engine.build_champion`` builds its "
        "``item_stat_blocks``",
        "``engine._combine_items`` resolves it as base_as * (1 + bonus_pct)",
        "the ``as_lock.locks_as`` branch of ``engine.build_champion`` zeroes "
        'item_totals["as_pct"]',
    ),
}


# Sibling sweep: the same rotted targets, cited from modules that still carry
# other line cites (out of this slice), so only these targets are pinned there.
_SAME_TARGET = re.compile(r"(?:ehp\.py:2[13]\b|engine\.py:(?:196|318-320|439)\b)")
SIBLINGS = {
    "ehp.py": (
        'Closes the deliberate Phase-6 omission "Healing throughput (lifesteal, '
        'Spirit Visage amp)" in the "Phase 1 deliberate omissions" list above.',
        'closes the "Shield throughput" omission in the module docstring',
    ),
    "_rune_offense_grants.py": (
        "``engine._combine_items`` resolves it as ``base_as * (1 + bonus_pct)``",
        "The ``as_lock.locks_as`` branch of ``engine.build_champion`` zeroes "
        '``item_totals["as_pct"]``',
        "``item_stat_blocks`` is the same list ``engine.build_champion`` builds",
        "(the lock the as_lock.locks_as branch of engine.build_champion applies)",
    ),
}


def _flat(text: str) -> str:
    return " ".join(text.replace("#", " ").split())


def test_pattern_matches_the_old_shapes():
    for sample in (
        "Closes the ``ehp.py:21`` Phase-1.5 omission \"Shield throughput",
        "Closes the ``ehp.py:23`` Phase-6 deliberate omission \"Healing",
        "# ehp.py:21 deliberate omission). Single ``ItemShield`` per item;",
        "# heal contribution (closes the ehp.py:23 deliberate omission). Single",
        "# from the resolved build, in the same shape engine.py:318-320 uses. It",
        "# FINAL attacks/sec (engine.py:196 resolves it as base_as * (1 + bonus_pct)).",
        "# ATTACK-SPEED-LOCK GATE: engine.py:439 zeroes item_totals[\"as_pct\"] for a",
    ):
        assert _LINE_CITE.search(sample), sample
    for symbols in TARGETS.values():
        for sample in symbols:
            assert not _LINE_CITE.search(sample), sample


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_no_line_cite_left(name):
    text = (DS / name).read_text(encoding="utf-8")
    hits = [
        f"{name}:{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_names_the_symbols(name):
    flat = _flat((DS / name).read_text(encoding="utf-8"))
    for symbol in TARGETS[name]:
        assert symbol in flat, f"{name}: {symbol}"


@pytest.mark.parametrize("name", sorted(SIBLINGS))
def test_siblings_drop_the_same_rotted_targets(name):
    text = (DS / name).read_text(encoding="utf-8")
    hits = [
        f"{name}:{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _SAME_TARGET.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)
    flat = _flat(text)
    for symbol in SIBLINGS[name]:
        assert symbol in flat, f"{name}: {symbol}"


def test_same_target_pattern_matches_the_old_shapes():
    for sample in (
        "``ehp.py:23`` deliberate Phase-6 omission \"Healing throughput",
        "# shield_hp by damage type (closes ehp.py:21 deliberate omission).",
        "per second - ``engine.py:196`` resolves it as ``base_as * (1 + bonus_pct)``.",
        "ATTACK-SPEED-LOCK CHAMPIONS GET ZERO, AND THAT IS DELIBERATE. ``engine.py:439``",
        "``item_stat_blocks`` is the same list ``engine.py:318-320`` builds from a",
        "# _passive_as_lock_overrides.as_lock_entry (engine.py:439) and grants ZERO to",
    ):
        assert _SAME_TARGET.search(sample), sample
    for symbols in SIBLINGS.values():
        for sample in symbols:
            assert not _SAME_TARGET.search(sample), sample


def test_ehp_docstring_carries_both_omission_bullets():
    doc = ehp.__doc__ or ""
    head, sep, tail = doc.partition("Phase 1 deliberate omissions:")
    assert sep, "ehp module docstring lost its omissions list"
    bullets = [ln for ln in tail.splitlines() if ln.startswith("* ")]
    assert any(
        b.startswith("* Shield throughput (Sterak's lifeline") for b in bullets
    ), bullets
    assert any(
        b.startswith("* Healing throughput (lifesteal, Spirit Visage amp)")
        for b in bullets
    ), bullets


def test_build_champion_aggregates_item_stat_blocks():
    src = inspect.getsource(engine.build_champion)
    assert 'item_stat_blocks = [rec.get("stats", {}) for rec in item_records]' in src
    assert "item_totals = aggregate_item_stats(item_stat_blocks)" in src
    dps_src = (DS / "dps.py").read_text(encoding="utf-8")
    assert 'snapshot.item(i).get("stats", {}) for i in resolved.item_ids' in dps_src


def test_combine_items_rebuilds_as_from_base():
    src = inspect.getsource(engine._combine_items)
    assert (
        'out["as"] = base_as * (1 + bonus_as_from_levels + bonus_as_from_items)'
        in src
    )


def test_build_champion_zeroes_as_pct_under_a_lock():
    src = inspect.getsource(engine.build_champion)
    assert re.search(
        r"if as_lock\.locks_as:\s*\n\s*item_totals\[\"as_pct\"\] = 0\.0", src
    ), "the locks_as branch no longer zeroes item_totals['as_pct']"
    assert src.index("as_lock.locks_as") < src.index("_combine_items(")
