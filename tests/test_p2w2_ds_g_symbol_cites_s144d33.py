"""Guard: the P2-W2 slice-G test cites by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. tests/test_p2w2_ds_g.py (20df1767f)
carried line cites on 16 lines into data_loader.py, fight_report.py,
mana_sim.py, matchup.py, server.py and test_mana_sim.py. Every DS-module cite
had drifted (cited line -> line before this edit): ``DataSnapshot.load``
67 -> 156, ``compute_fight_report`` 157 -> 177, ``FightReport.to_dict``
110 -> 114 and its mana_pool emit 124 -> 136, ``compute_mana_bounded_combo``
494 -> 502, the ``ManaBoundedResult.mana_pool`` field 165 -> 168, the
inf-pool branch 216-220 -> 219-223, ``compute_matchup`` 209 -> 263,
``MatchupResult.to_dict`` 67 -> 117, the 0-HP guards 260-261 -> 323-324 and
``Handler._send_json`` 1740 -> 3098. The three fight_report.py cites were
stale on the day they landed: they match the file before 20df1767f added
the mana_pool coercion. Only the test_mana_sim.py:115 cite still resolved.
The same ``server.py:1740`` cite sat in the ``FightReport.to_dict`` comment
in fight_report.py itself; this edit grows that comment by one line.
Each claim was re-read by symbol at HEAD and still holds; the prose now names
the symbol that carries it, and the tests below pin those claims so a moved
or deleted construct fails here instead of leaving a cite that resolves to
SOME line forever.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
TARGET = REPO / "tests" / "test_p2w2_ds_g.py"
FIGHT_REPORT = DS / "fight_report.py"

# ``server.py:1740``, ``matchup.py:260-261``, ``test_mana_sim.py:115``.
_LINE_CITE = re.compile(
    r"(?<![A-Za-z_])(?:data_loader|fight_report|mana_sim|matchup|server"
    r"|test_mana_sim)\.py:\d"
)

# Phrases only the replacement prose carries, so deleting the prose fails here.
_NAMED_IN_PROSE = (
    "``server.Handler._send_json``",
    "``ManalessChampionTests.test_zed_energy_is_not_gated``",
    "the 0-HP guards in ``matchup.compute_matchup``",
    "the non-mana branch of\n# ``mana_sim._champion_mana_profile``",
    "mana_sim._champion_mana_profile - its non-mana branch returns the inf",
)

# The symbol list in the target docstring: (module, dotted attribute).
_SYMBOLS = (
    ("data_loader", "DataSnapshot.load"),
    ("fight_report", "compute_fight_report"),
    ("fight_report", "FightReport.to_dict"),
    ("mana_sim", "compute_mana_bounded_combo"),
    ("mana_sim", "_champion_mana_profile"),
    ("matchup", "compute_matchup"),
    ("matchup", "MatchupResult.to_dict"),
    ("server", "Handler._send_json"),
)


def _node(path: Path, dotted: str) -> tuple[str, ast.AST]:
    src = path.read_text(encoding="utf-8")
    scope: list[ast.AST] = list(ast.parse(src).body)
    node: ast.AST | None = None
    for part in dotted.split("."):
        node = next(
            (n for n in scope
             if isinstance(n, (ast.FunctionDef, ast.ClassDef))
             and n.name == part),
            None,
        )
        assert node is not None, f"{path.name} has no {dotted}"
        scope = list(getattr(node, "body", []))
    return src, node


def _segment(path: Path, dotted: str) -> str:
    src, node = _node(path, dotted)
    return ast.get_source_segment(src, node) or ""


def test_pattern_matches_the_rotted_shapes():
    for sample in (
        "``allow_nan=True`` (``agents/daemon_slayer/server.py:1740``), so an",
        "``tests/.../test_mana_sim.py:115``) - only",
        "(``matchup.py:260-261``) so a 0-HP target",
        "data_loader.DataSnapshot.load              (data_loader.py:67)",
        "(mana_sim.py:216-220). Garen is",
        "fight_report.FightReport.to_dict           (fight_report.py:110)",
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (
        "``server.Handler._send_json``",
        "agents/daemon_slayer/mana_sim.py",
        "_rank_mage.py:12",
        "ability_dps.py:1378",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_cite_left_in_target_or_fight_report():
    hits = [
        f"{path.name}:{n}: {line.strip()}"
        for path in (TARGET, FIGHT_REPORT)
        for n, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_replacement_prose_present():
    text = TARGET.read_text(encoding="utf-8")
    missing = [p for p in _NAMED_IN_PROSE if p not in text]
    assert not missing, missing


def test_fight_report_comment_names_the_encoder_by_symbol():
    body = _segment(FIGHT_REPORT, "FightReport.to_dict")
    assert "``server.Handler._send_json``" in body


def test_every_listed_symbol_resolves():
    text = TARGET.read_text(encoding="utf-8")
    for module, dotted in _SYMBOLS:
        assert f"{module}.{dotted}" in text, (module, dotted)
        _node(DS / f"{module}.py", dotted)


def test_mana_pool_is_a_mana_bounded_result_field():
    _src, node = _node(DS / "mana_sim.py", "ManaBoundedResult")
    fields = {
        n.target.id for n in node.body
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
    }
    assert "mana_pool" in fields


def test_send_json_uses_the_default_allow_nan_encoder():
    body = _segment(DS / "server.py", "Handler._send_json")
    assert "json.dumps(payload, default=str)" in body
    assert "allow_nan" not in body


def test_to_dict_coerces_a_non_finite_pool_to_none():
    body = _segment(FIGHT_REPORT, "FightReport.to_dict")
    assert (
        "self.mana_pool if math.isfinite(self.mana_pool) else None" in body
    )


def test_non_mana_branch_returns_an_infinite_pool():
    body = _segment(DS / "mana_sim.py", "_champion_mana_profile")
    branch = body.index(
        'if resource_type.strip().lower() != "mana" or base_mp <= 0.0:')
    ret = body.index("return (resource_type, math.inf, max(0.0, regen_per_s))")
    assert branch < ret


def test_matchup_guards_a_zero_hp_pool():
    body = _segment(DS / "matchup.py", "compute_matchup")
    for line in (
        "pct_b_removed = 1.0 if b_hp_eff <= 0 else",
        "pct_a_removed = 1.0 if a_hp_eff <= 0 else",
    ):
        assert line in body, line


def test_zed_energy_test_pins_the_inf_sentinel():
    body = _segment(
        DS / "tests" / "test_mana_sim.py",
        "ManalessChampionTests.test_zed_energy_is_not_gated",
    )
    assert "self.assertTrue(math.isinf(r.mana_pool))" in body
