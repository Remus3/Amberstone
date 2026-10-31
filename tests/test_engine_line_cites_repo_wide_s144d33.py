"""Guard: no tracked .py file cites ``ability_dps``, ``dps`` or ``hps`` by line (RM-1053).

RM-1053 was filed in s144 cycle 38 as 93 tracked .py lines citing one of
the three DS engine modules ``ability_dps`` / ``dps`` / ``hps`` by line
number, across about 30 files. Its acceptance: convert the rotted cites to
symbol cites file by file, then widen a guard of the s144d30 / s144d31 shape
(the RM-1050 ``onhit_dps`` guard, the ``cast_propensity`` guard) to those
three engine files repo-wide once the live count is zero.

Measured 2026-10-31 at ENGINE 1.290.0 over the 3540 other tracked .py files
``tests/_repo_walk`` reaches: 135 lines in 32 files still match. Every one of
the 32 is an RM-1051 / RM-1053 symbol-cite guard, and every hit is that
guard recording the old cite it retired (its docstring, its pattern samples
or its needle comments). Those are dated records: true when written, kept on
purpose so each guard can re-derive what it replaced. Nothing else matches.

So the repo-wide rule is: zero such lines anywhere, except the exact per-file
counts in ``_DATED_RECORDS``. The table is a ratchet. A new cite in any other
file fails; a new cite in a listed guard fails (its count rises); a cite a
guard drops fails too until its count is lowered here, so the table only ever
shrinks. This module keeps its own samples split so it carries no hit itself.

The leading boundary keeps longer module names out: ``onhit_dps`` has the
RM-1050 guard and ``ability_hps`` has its own (the RM-1053 missing-HP amp
guard).
Scope is tracked ``*.py`` only; ``agents/daemon_slayer/CHANGELOG.md`` and the
docs ledgers are dated records and are not swept.
"""
from __future__ import annotations

import re
from pathlib import Path

from tests import _repo_walk

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
ENGINE_FILES = ("ability_dps.py", "dps.py", "hps.py")

_LINE_CITE = re.compile(r"(?<![A-Za-z_])(?:ability_dps|dps|hps)\.py:\d")

# The RM-1051 / RM-1053 guards that record the cites they retired, with
# the exact number of matching lines each carried on 2026-10-31.
_DATED_RECORDS = {
    "tests/test_ability_dps_hps_symbol_cites_s144d33.py": 9,
    "tests/test_ad_axis_registry_symbol_cites_s144d33.py": 15,
    "tests/test_cast_propensity_symbol_cites_s144d31.py": 9,
    "tests/test_crit_chance_overrides_r212_symbol_cites_s144d33.py": 2,
    "tests/test_crit_conversion_route_plumb_rm46_symbol_cites_s144d33.py": 2,
    "tests/test_crit_overflow_symbol_cites_s144d33.py": 4,
    "tests/test_ds_file_line_cites_s_s144d33.py": 6,
    "tests/test_ds_file_line_cites_t_s144d33.py": 4,
    "tests/test_ds_file_line_cites_u_s144d33.py": 3,
    "tests/test_ds_route_test_docstring_symbol_cites_s144d33.py": 12,
    "tests/test_ds_single_line_cites_q_s144d33.py": 3,
    "tests/test_dsv1_burn_valuation_symbol_cites_s144d33.py": 3,
    "tests/test_ehp_crit_vamp_symbol_cites_s144d33.py": 6,
    "tests/test_extra_shot_crit_symbol_cites_s144d33.py": 6,
    "tests/test_hps_missing_hp_amp_symbol_cites_s144d33.py": 1,
    "tests/test_kit_axis_ap_pct_sum_symbol_cites_s144d33.py": 3,
    "tests/test_p2w2_ds_a_symbol_cites_s144d33.py": 2,
    "tests/test_p2w2_ds_b_symbol_cites_s144d33.py": 1,
    "tests/test_p2w2_ds_d_symbol_cites_s144d33.py": 1,
    "tests/test_p2w2_ds_g_symbol_cites_s144d33.py": 1,
    "tests/test_p2w2_ds_h_symbol_cites_s144d33.py": 1,
    "tests/test_pet_summon_rm97_symbol_cites_s144d33.py": 5,
    "tests/test_rm118_mana_coupling_symbol_cites_s144d33.py": 4,
    "tests/test_rm169_symbol_cites_s144d33.py": 2,
    "tests/test_rm36_dual_split_symbol_cites_s144d33.py": 3,
    "tests/test_rm46_rm660_symbol_cites_s144d33.py": 2,
    "tests/test_rm90_enchanter_pool_symbol_cites_s144d33.py": 3,
    "tests/test_robustness_p1l12_symbol_cites_s144d33.py": 7,
    "tests/test_route_seam_test_symbol_cites_s144d33.py": 2,
    "tests/test_server_engine_symbol_cites_s144d33.py": 7,
    "tests/test_stranded_hsp_symbol_cites_s144d33.py": 3,
    "tests/test_target_state_caller_p1l4_symbol_cites_s144d33.py": 3,
}


def _hits() -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in _repo_walk.iter_repo_files(REPO, ("*.py",)):
        text = path.read_text(encoding="utf-8", errors="replace")
        n = sum(1 for line in text.splitlines() if _LINE_CITE.search(line))
        if n:
            counts[_repo_walk.relative_posix(path, REPO)] = n
    return counts


def test_walk_is_not_vacuous():
    files = {p.resolve() for p in _repo_walk.iter_repo_files(REPO, ("*.py",))}
    for name in ENGINE_FILES:
        assert (DS / name).resolve() in files, name
    assert (DS / "tests" / "test_dps.py").resolve() in files
    assert len(files) > 500, len(files)


def test_pattern_matches_the_rotted_shapes():
    for sample in (
        "``ability_dps" + ".py:1261``",
        "(dps" + ".py:911)",
        "``hps" + ".py:679``",
        "agents/daemon_slayer/dps" + ".py:34",
        "ability_dps" + ".py:371,384",
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (
        "onhit_dps" + ".py:494",
        "ability_hps" + ".py:12",
        "_ability_hps" + ".py:3",
        "ability_dps.py",
        "dps.compute_dps",
        "hps.py's",
        "SPEC:109-114",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_dated_records_are_symbol_cite_guards():
    shape = re.compile(r"^tests/test_\w+_s144d3[13]\.py$")
    bad = [rel for rel in _DATED_RECORDS if not shape.match(rel)]
    assert bad == [], bad
    for rel in _DATED_RECORDS:
        text = (REPO / rel).read_text(encoding="utf-8")
        assert "def test_" in text and "_LINE_CITE" in text, rel


def test_no_line_cites_into_the_engine_beyond_the_dated_records():
    hits = _hits()
    new = {rel: n for rel, n in hits.items() if rel not in _DATED_RECORDS}
    assert new == {}, "cite ability_dps / dps / hps by symbol, not by line: " + repr(new)
    drift = {
        rel: (_DATED_RECORDS[rel], hits.get(rel, 0))
        for rel in _DATED_RECORDS
        if hits.get(rel, 0) != _DATED_RECORDS[rel]
    }
    assert drift == {}, "(recorded, now) per guard; lower the table, never raise it: " + repr(drift)
