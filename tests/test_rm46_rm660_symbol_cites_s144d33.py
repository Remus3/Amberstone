"""Guard: the rm46 and rm660 DS tests cite by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0 (cited -> line before this edit).
test_crit_conversion_ashe_rm46.py cited Essence Reaver's crit-scaled proc as
``_effects_data.py:750`` -> 751, and its PART 7 gate params as
``OPEN_ITEMS_REVIEW_2026-07-25.md:473-482`` (resolved; an archived doc, now
cited by its "A-12 / RM-46 Ashe" entry). test_arena_botrk_current_hp_lever_rm660.py
carried eight line cites in its docstring: three still resolved
(``_effects_types.py:137``, ``_effects_types.py:262``,
``test_target_current_hp_pct_lever.py:35-41``), the pipeline-A pin
(``:186-192``) resolved too, and four had drifted: the SR 3153 proc
``_effects_data.py:603`` -> 604, the Arena row
``_effects_data.py:4520-4530`` -> 4598-4611, the re-export
``effects.py:43-45`` -> 45-47, and ``dps.py:768-778`` -> 769-779. A cite
that resolves today rots on the next insert above it, so all of them go.

The tests below pin the claims the prose leans on, so a refactor that breaks
one turns this red rather than leaving the prose stale.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect
import re
from pathlib import Path

from agents.daemon_slayer import effects
from agents.daemon_slayer._effects_data import ITEM_EFFECTS
from agents.daemon_slayer._effects_types import CallContext, PeriodicProc
from agents.daemon_slayer.dps import compute_dps

REPO = Path(__file__).resolve().parent.parent
DS_TESTS = REPO / "agents" / "daemon_slayer" / "tests"
TARGETS = (
    DS_TESTS / "test_crit_conversion_ashe_rm46.py",
    DS_TESTS / "test_arena_botrk_current_hp_lever_rm660.py",
)
# ``_effects_data.py:750`` and ``dps.py:768-778``. Not the port shape
# ``:8860``, which is no cite.
_LINE_CITE = re.compile(r"\w\.(?:py|md):\d|\bat line \d")


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _ctx(**kw) -> CallContext:
    return CallContext(base_ad=60.0, bonus_ad=0.0, level=11, **kw)


def test_pattern_matches_the_rotted_shapes():
    for sample in (
        "# (_effects_data.py:750, ``1.25*base_ad + 50*crit_chance``). Denying it",
        "  - Arena 223153 (``_effects_data.py:4520-4530``) carried",
        "re-exported by ``agents.daemon_slayer.effects`` (``effects.py:43-45``).",
        "(``test_meraki_formula_audit_pipeline_a.py:186-192``) evaluates the",
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (
        '``ITEM_EFFECTS["3508"]`` in ``_effects_data.py``',
        "``CallContext.target_current_hp_pct`` in ``_effects_types.py``",
        "DS ``:8860`` serves the main checkout",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_cite_left_in_targets():
    hits = [
        f"{path.name}:{n}: {line.strip()}"
        for path in TARGETS
        for n, line in enumerate(_source(path).splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_essence_reaver_proc_reads_crit_chance():
    (proc,) = ITEM_EFFECTS["3508"].periodics
    no_crit = proc.resolve_damage(_ctx(crit_chance=0.0))
    full_crit = proc.resolve_damage(_ctx(crit_chance=1.0))
    assert no_crit == 1.25 * 60.0
    assert full_crit - no_crit == 50.0


def test_sr_and_arena_botrk_scale_by_the_current_hp_lever():
    for item_id in ("3153", "223153"):
        (proc,) = ITEM_EFFECTS[item_id].periodics
        full = proc.resolve_damage(_ctx(target_max_hp=2000.0))
        half = proc.resolve_damage(
            _ctx(target_max_hp=2000.0, target_current_hp_pct=0.5),
        )
        assert full == 180.0, item_id
        assert half == 90.0, item_id


def test_seam_symbols_the_docstring_names_exist():
    fields = {f.name: f for f in dataclasses.fields(CallContext)}
    assert fields["target_current_hp_pct"].default == 1.0
    assert effects.CallContext is CallContext
    assert effects.ITEM_EFFECTS is ITEM_EFFECTS
    assert callable(PeriodicProc.resolve_damage)
    param = inspect.signature(compute_dps).parameters["target_current_hp_pct"]
    assert param.default == 1.0


def test_cited_test_helpers_exist():
    for name, symbol in (
        ("test_target_current_hp_pct_lever.py", "_dps"),
        (
            "test_meraki_formula_audit_pipeline_a.py",
            "test_arena_223153_mists_edge_is_9pct_target_max_hp",
        ),
    ):
        tree = ast.parse(_source(DS_TESTS / name))
        defs = {
            n.name for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef)
        }
        assert symbol in defs, (name, symbol)


def test_archived_gate_entry_still_carries_the_cited_ordering():
    path = REPO / "docs" / "_archive" / "2026-07" / "OPEN_ITEMS_REVIEW_2026-07-25.md"
    text = " ".join(_source(path).split())
    assert text.count("**A-12 / RM-46 Ashe.**") == 1
    assert (
        "Ashe BotRK #1 / Runaan's #2 / IE #8 vs Aphelios Yun Tal #1 / IE #2 "
        "/ BotRK #13"
    ) in text
