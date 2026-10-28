"""Guard: the RM-142 kit-axis ap_pct_sum test cites by symbol (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. The docstring of
``test_ap_pct_sum_does_not_perturb_any_dps_number`` in
``agents/daemon_slayer/tests/test_kit_axis_ap_scaling_guard.py`` said ``dps``
is DEFINED at ``ability_dps.py:1323`` (true at fcf975a5, RM-142,
2026-08-02). At HEAD that line is inside the per-key form loop and the
``dps = post_mit * measured`` assignment sits near line 1429 inside
``compute_ability_dps``.

The tests below pin the claim by symbol instead.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

from agents.daemon_slayer.ability_dps import compute_ability_dps

REPO = Path(__file__).resolve().parent.parent
TARGET = (
    REPO / "agents" / "daemon_slayer" / "tests"
    / "test_kit_axis_ap_scaling_guard.py"
)
_LINE_CITE = re.compile(r"(?<![\w.])ability_dps\.py:\d")


def test_pattern_matches_the_rotted_shape():
    assert _LINE_CITE.search("is how ``dps`` is DEFINED at ``ability_dps.py:1323``")
    for sample in (
        "``ability_dps.compute_ability_dps``",
        "a dps.py:34 cite belongs to another guard",
        "a _ability_dps.py:12 cite is not this pattern",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_cite_left_in_kit_axis_test():
    hits = [
        f"{n}: {line.strip()}"
        for n, line in enumerate(TARGET.read_text(encoding="utf-8").splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_kit_axis_test_names_the_symbol():
    assert "``ability_dps.compute_ability_dps``" in TARGET.read_text(encoding="utf-8")


def test_compute_ability_dps_still_defines_dps_that_way():
    src = inspect.getsource(compute_ability_dps)
    assert "dps = post_mit * measured" in src
    assert "post_mitigation_damage_per_cast=post_mit," in src
    assert "casts_per_sec=measured," in src
    assert "dps=dps," in src
