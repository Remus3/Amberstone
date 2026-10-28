"""Guard: four more DS tests cite by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. Each file below carried exactly one
line cite:

- ``test_ehp_heal_phase6.py`` cited ``ehp.py:23`` for the "Healing
  throughput" omission; the ``ehp`` module docstring grew a Phase-6 BT note
  above it, so :23 is now the shield bullet and the healing bullet sits lower.
- ``test_ehp_shield_phase15.py`` cited ``ehp.py:21`` for the "Shield
  throughput" omission; it still resolves, but a line cite into a docstring
  rots on the next note added above it (the heal cite above is the proof).
- ``test_guinsoo_seething_strike_r66.py`` cited
  ``test_conditional_as_base_fold_r42.py:11`` for the ungated Yun Tal
  ``bonus_as_conditional`` row; still resolving, same reason.
- ``test_mana_coupling_transport_rm118.py`` cited ``ehp.py:3966-3968`` for
  the mana lane reading ``delta_max_mp``; that range is now inside the
  health lane's ``_health_key`` docstring, and the mana read is ~60 lines
  lower in ``_mana_key``.

The tests below pin the cites and the claims they carried by symbol instead.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from agents.daemon_slayer import ehp, effects
from agents.daemon_slayer._effects_data import ITEM_EFFECTS

REPO = Path(__file__).resolve().parent.parent
TESTS = REPO / "agents" / "daemon_slayer" / "tests"
_LINE_CITE = re.compile(r"(?<![\w.])\w+\.py:\d")

TARGETS = {
    "test_ehp_heal_phase6.py": ("``ehp`` module docstring",),
    "test_ehp_shield_phase15.py": ("``ehp`` module docstring",),
    "test_guinsoo_seething_strike_r66.py": (
        "test_conditional_as_base_fold_r42.py",
        '``ITEM_EFFECTS["3032"]``',
    ),
    "test_mana_coupling_transport_rm118.py": (
        "``_mana_key``",
        "``ehp.rank_items_by_ehp``",
    ),
}


def test_pattern_matches_the_old_shapes():
    for sample in (
        "Closes the ``ehp.py:23`` Phase-6 deliberate omission",
        "Closes the ``ehp.py:21`` Phase-1.5 omission",
        "test_conditional_as_base_fold_r42.py:11), pinned at the full-stack",
        "(ehp.py:3966-3968). So the",
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (
        "``ehp.rank_items_by_ehp``",
        "test_conditional_as_base_fold_r42.py)",
        "``ehp`` module docstring",
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


def test_ehp_docstring_lists_the_shield_and_heal_omissions():
    doc = ehp.__doc__
    head, _, omissions = doc.partition("Phase 1 deliberate omissions:")
    assert omissions, "omission list heading moved"
    shield = omissions.find(
        "* Shield throughput (Sterak's lifeline, Doran's Shield, Bloodthirster)"
    )
    heal = omissions.find("* Healing throughput (lifesteal, Spirit Visage amp)")
    assert shield >= 0
    assert heal > shield


def test_r42_source_names_yun_tal_as_the_ungated_cond_as_item():
    r42 = (TESTS / "test_conditional_as_base_fold_r42.py").read_text(
        encoding="utf-8"
    )
    assert "The Yun Tal item (3032) carries the cond_as field automatically" in r42
    assert ITEM_EFFECTS["3032"].bonus_as_conditional == pytest.approx(0.08)
    assert effects.total_conditional_as([ITEM_EFFECTS["3032"]]) == pytest.approx(
        0.08
    )


def test_mana_key_reads_the_candidates_own_delta_max_mp():
    src = inspect.getsource(ehp.rank_items_by_ehp)
    assert "mana_damage_coupling(str(champion_id))" in src
    key = src[src.index("def _mana_key(") :]
    key = key[: key.index("def _hp_proc_key(")]
    assert "_mana_coupling, r.delta_max_mp, r.delta_max_mp" in key
