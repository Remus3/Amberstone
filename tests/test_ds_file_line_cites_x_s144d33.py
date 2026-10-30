"""Guard: the RM-176 ammo test and the per-route seam test cite mana_sim,
data_loader and sr_draft_profile by symbol (x).

Measured 2026-10-30 at ENGINE 1.290.0, re-deriving the RM-1053 "DS test
lines" residue with guard v's pattern over agents/daemon_slayer/tests. Every
mana_sim / data_loader cite in the two files below had drifted:

- ``test_ammo_recharge_rm176.py`` cited ``data_loader.py:314``
  (``spell_ammo`` now sits further down), ``mana_sim.py:145-177``
  (``ManaBoundedResult`` moved), ``mana_sim.py:519-528`` twice (that range is
  now the ``compute_mana_bounded_combo`` docstring, not the unbounded pass)
  and ``mana_sim.py:346`` (no longer the ``_recharge_to`` call).
- ``test_route_seams_reach_the_client_per_route.py`` cited
  ``mana_sim.py:600-604`` and ``mana_sim.py:609-611`` for the gate_ammo and
  apply_ability_haste seams (both moved), and ``sr_draft_profile.py:271-304``
  for the /beam call (still right, cited by symbol for the same reason).

The tests below pin the cites, and the facts they restate, by symbol.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from agents.daemon_slayer import mana_sim
from agents.daemon_slayer.data_loader import DataSnapshot
from coaches import sr_draft_profile

REPO = Path(__file__).resolve().parent.parent
TESTS = REPO / "agents" / "daemon_slayer" / "tests"
_LINE_CITE = re.compile(r"(?<![\w.])\w+\.py:\d|(?<![\w.]):\d|\blines? \d")
_NOT_A_CITE = re.compile(r"\[:\d+\]|(?<!\w):8860\b|%:\d+%|-lines? (?=\d)")

TARGETS = {
    "test_ammo_recharge_rm176.py": (
        "``DataSnapshot.spell_ammo`` (data_loader) returns",
        "``ManaBoundedResult`` fields (the mana_sim dataclass): mana_pool,",
        "never ammo-gated -> the ``gate_mana=False`` ``_walk`` call in "
        "``compute_mana_bounded_combo``, which passes no ``gate_ammo``.",
        "rebind it -> ``_walk`` resolves the module global at call time.",
        "The reference pass is never ammo-gated (the gate_mana=False _walk "
        "call in compute_mana_bounded_combo) - exact equality, not a bound.",
    ),
    "test_route_seams_reach_the_client_per_route.py": (
        "(sr_draft_profile._call_beam) rather than going through this client",
        "(gate_ammo -> the ammo_by_slot resolve in "
        "mana_sim.compute_mana_bounded_combo, apply_ability_haste -> its "
        "total_item_ability_haste term, apply_mode_modifiers -> the "
        "self-shred physical-DPS term)",
    ),
}


def _flat(text: str) -> str:
    return " ".join(text.replace("#", " ").split())


def test_pattern_matches_the_old_shapes():
    for sample in (
        "  * ``DataSnapshot.spell_ammo`` -> data_loader.py:314, returns",
        "  * ``ManaBoundedResult`` fields -> mana_sim.py:145-177 (mana_pool,",
        "# (mana_sim.py:519-528) - exact equality, not a bound.",
        "    rebind it -> mana_sim.py:346 resolves the module global",
        "    # (sr_draft_profile.py:271-304) rather than going through",
        "    # (gate_ammo -> mana_sim.py:600-604, apply_ability_haste ->",
    ):
        assert _LINE_CITE.search(_NOT_A_CITE.sub("", sample)), sample
    for symbols in TARGETS.values():
        for sample in symbols:
            assert not _LINE_CITE.search(sample), sample


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_no_line_cite_left(name):
    text = (TESTS / name).read_text(encoding="utf-8")
    hits = [
        f"{name}:{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _LINE_CITE.search(_NOT_A_CITE.sub("", line))
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_names_the_symbols(name):
    flat = _flat((TESTS / name).read_text(encoding="utf-8"))
    for symbol in TARGETS[name]:
        assert symbol in flat, f"{name}: {symbol}"


def test_spell_ammo_is_a_data_snapshot_method():
    params = list(inspect.signature(DataSnapshot.spell_ammo).parameters)
    assert params == ["self", "champ_id", "slot"]


def test_result_carries_the_listed_fields():
    fields = set(mana_sim.ManaBoundedResult.__dataclass_fields__)
    assert {
        "mana_pool", "mana_regen_per_s", "mana_spent", "duration_s",
        "casts_allowed", "total_mitigated", "bounded_dps", "unbounded_dps",
        "oom_at_t", "hits",
    } <= fields


def _walk_calls() -> list[str]:
    src = inspect.getsource(mana_sim.compute_mana_bounded_combo)
    calls = []
    at = src.find("_walk(")
    while at != -1:
        calls.append(src[at:src.index("\n    )", at)])
        at = src.find("_walk(", at + 1)
    return calls


def test_the_unbounded_pass_is_the_one_without_gate_ammo():
    calls = _walk_calls()
    assert len(calls) == 2
    unbounded = [c for c in calls if "gate_mana=False" in c]
    assert len(unbounded) == 1
    assert "gate_ammo" not in unbounded[0]
    bounded = [c for c in calls if c is not unbounded[0]]
    assert "gate_ammo=gate_ammo" in bounded[0]


def test_walk_resolves_recharge_to_through_the_module():
    src = inspect.getsource(mana_sim._walk)
    assert "_recharge_to(st, clock)" in src


def test_the_two_fight_report_seams_live_in_the_combo():
    params = inspect.signature(mana_sim.compute_mana_bounded_combo).parameters
    assert params["gate_ammo"].default is False
    assert params["apply_ability_haste"].default is False
    src = inspect.getsource(mana_sim.compute_mana_bounded_combo)
    assert "if gate_ammo:" in src
    assert "ammo_by_slot[slot] = slot_ammo" in src
    assert (
        "total_item_ability_haste(burst.item_ids) if apply_ability_haste"
        in src
    )


def test_call_beam_holds_its_own_http_call():
    src = inspect.getsource(sr_draft_profile._call_beam)
    assert "/beam" in src
    assert "timeout=_ENGINE_TIMEOUT_S" in src
    assert sr_draft_profile._ENGINE_TIMEOUT_S == 4.0
    assert "engine HTTP" in src
    assert "engine unreachable" in src
