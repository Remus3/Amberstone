"""Guard: the R197 stranded-seam test cites by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. agents/daemon_slayer/tests/
test_stranded_hsp_seam_r197.py carried line cites on 10 lines into
ult_rates.py, server.py, ehp.py, hybrid.py, ability_dps.py, ability_hps.py
and dps.py, written by 86386861a (RM-207), 51c14dec8 (RM-202 depth 1) and
6da719c2f (RM-333). Six had drifted: the ``**assumed_share_kwargs`` splat
moved from server.py:1155 to 1321, the lazy ``compute_cc_pressure`` import
from ehp.py:2510 to 2545, the ``apply_dual_scaling_split=`` forward from
hybrid.py:657 to 661, the two ability_dps lookups from 1378 / 1501 to 1420 /
1549, and the dps lookup from 1369 to 1414. Four still resolve
(ult_rates.py:80, 167 and 205, ability_hps.py:925): those lines hold the same
text at HEAD as at 6da719c2f. They are named by symbol too, so the next edit
cannot strand them. Each claim was re-read by
symbol at HEAD and still holds; the tests below pin those claims, so a moved
or deleted construct fails here instead of leaving a cite that resolves to
SOME line forever.

The target's own RM-333 reason check asserted ``".py:" in reason``, which
REQUIRED a line cite; it now requires a ``<module>.<symbol>`` that resolves
in the package, which is the stronger check.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
TARGET = DS / "tests" / "test_stranded_hsp_seam_r197.py"

# ``ult_rates.py:167``, ``server.py:1155``, ``ability_dps.py:1378 and :1501``.
_LINE_CITE = re.compile(
    r"(?<![A-Za-z_])(?:ult_rates|server|ehp|hybrid|ability_dps|ability_hps|dps)"
    r"\.py:\d"
    r"|\band :\d"
)

# Phrases only the replacement prose carries, so deleting the prose fails here.
_NAMED_IN_PROSE = (
    "``ult_rates.get_ult_casts_per_sec`` and\n"
    "# ``ult_rates.get_spell_casts_per_sec``) was in NEITHER universe",
    "the ``**assumed_share_kwargs`` splat into\n"
    "    ``rank_items_by_ehp`` in ``server._route_rank_tank``",
    "``compute_ehp`` (a deliberate lazy import",
    "# ``hybrid.compute_hybrid`` forwards ``apply_dual_scaling_split=",
    "``ult_rates.get_ult_casts_per_sec`` and\n"
    "    ``ult_rates.get_spell_casts_per_sec``) was in NEITHER universe",
)

# The RM-333 reason is an implicitly concatenated literal, so its phrases are
# matched against the evaluated ledger value, not the source text.
_NAMED_IN_REASON = (
    "ability_dps.compute_ability_dps (both lookups), "
    "ability_hps.compute_ability_hps and dps.compute_dps",
    "the live default, ult_rates.APPLY_CANONICAL_CAST_RATE_KEYS, which "
    "stays False",
)

_LOOKUPS = {"get_ult_casts_per_sec", "get_spell_casts_per_sec"}


def _func(path: Path, fn: str) -> tuple[str, ast.FunctionDef]:
    src = path.read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == fn:
            return src, node
    raise AssertionError(f"{path.name} has no {fn}")


def _segment(path: Path, fn: str) -> str:
    src, node = _func(path, fn)
    return ast.get_source_segment(src, node) or ""


def _lookup_calls(path: Path) -> list[tuple[str, ast.Call]]:
    """Every ult_rates cast-rate lookup call, with its enclosing function."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in _LOOKUPS):
                out.append((fn.name, node))
    # A nested def would be walked twice; keep the innermost owner only.
    seen: dict[int, tuple[str, ast.Call]] = {}
    for owner, call in out:
        seen[id(call)] = (owner, call)
    return list(seen.values())


def test_pattern_matches_the_rotted_shapes():
    for sample in (
        "``get_spell_casts_per_sec``, ult_rates.py:205) was",
        "    ``server.py:1155``, and it reported",
        "``compute_ehp`` (ehp.py:2510, a deliberate",
        "# ``hybrid.py:657`` forwards",
        '"intermediaries - ability_dps.py:1378 "',
        '"and :1501, ability_hps.py:925, dps.py:1369 - and"',
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (
        "``ult_rates.get_ult_casts_per_sec``",
        "agents/daemon_slayer/server.py",
        "test_stranded_hsp_seam_r197.py::STRANDED_TODAY",
        "engine.py:217",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_cite_left_in_target():
    hits = [
        f"{TARGET.name}:{n}: {line.strip()}"
        for n, line in enumerate(
            TARGET.read_text(encoding="utf-8").splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_replacement_prose_present():
    text = TARGET.read_text(encoding="utf-8")
    missing = [p for p in _NAMED_IN_PROSE if p not in text]
    assert not missing, missing


def test_tristate_reason_names_the_intermediaries_by_symbol():
    tree = ast.parse(TARGET.read_text(encoding="utf-8"))
    for node in tree.body:
        if (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                and node.target.id == "STRANDED_TRISTATE"):
            ledger = ast.literal_eval(node.value)
            break
    else:
        raise AssertionError("target has no STRANDED_TRISTATE")
    reason = ledger["apply_canonical_cast_rate_keys"]
    missing = [p for p in _NAMED_IN_REASON if p not in reason]
    assert not missing, missing


def test_reason_check_no_longer_demands_a_line_cite():
    text = TARGET.read_text(encoding="utf-8")
    assert 'self.assertIn(".py:", reason' not in text
    assert "reason cites no resolvable <module>.<symbol>" in text


def test_both_lookups_carry_the_tristate_kwarg_and_the_global_is_false():
    path = DS / "ult_rates.py"
    for fn in sorted(_LOOKUPS):
        _, node = _func(path, fn)
        args = node.args.args
        names = [a.arg for a in args]
        assert "apply_canonical_cast_rate_keys" in names, fn
        i = names.index("apply_canonical_cast_rate_keys")
        default = node.args.defaults[i - (len(args) - len(node.args.defaults))]
        assert isinstance(default, ast.Constant) and default.value is None, fn
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "APPLY_CANONICAL_CAST_RATE_KEYS"):
            assert isinstance(node.value, ast.Constant)
            assert node.value.value is False
            break
    else:
        raise AssertionError("ult_rates has no APPLY_CANONICAL_CAST_RATE_KEYS")


def test_server_never_names_the_cast_rate_seam():
    src = (DS / "server.py").read_text(encoding="utf-8")
    assert src.count("apply_canonical_cast_rate_keys") == 0


def test_assumed_share_splat_lands_in_rank_items_by_ehp_in_route_rank_tank():
    _, node = _func(DS / "server.py", "_route_rank_tank")
    hits = [
        call for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
        and call.func.id == "rank_items_by_ehp"
        and any(k.arg is None and isinstance(k.value, ast.Name)
                and k.value.id == "assumed_share_kwargs" for k in call.keywords)
    ]
    assert len(hits) == 1


def test_cc_pressure_is_a_function_local_import_in_compute_ehp():
    body = _segment(DS / "ehp.py", "compute_ehp")
    assert "from .cc_pressure import compute_cc_pressure" in body


def test_compute_hybrid_forwards_dual_scaling_split_under_the_route_name():
    body = _segment(DS / "hybrid.py", "compute_hybrid")
    assert "apply_dual_scaling_split=apply_ad_axis_dual_scaling_split" in body


def test_four_lookup_calls_in_three_intermediaries_none_carries_the_kwarg():
    calls = []
    for mod in ("ability_dps.py", "ability_hps.py", "dps.py"):
        calls += [(mod, owner, c) for owner, c in _lookup_calls(DS / mod)]
    owners = sorted((mod, owner, c.func.id) for mod, owner, c in calls)
    assert owners == [
        ("ability_dps.py", "compute_ability_dps", "get_spell_casts_per_sec"),
        ("ability_dps.py", "compute_ability_dps", "get_ult_casts_per_sec"),
        ("ability_hps.py", "compute_ability_hps", "get_spell_casts_per_sec"),
        ("dps.py", "compute_dps", "get_ult_casts_per_sec"),
    ]
    for mod, owner, c in calls:
        first = c.args[0]
        assert ast.unparse(first) == "resolved.champion_name", (mod, owner)
        assert all(k.arg != "apply_canonical_cast_rate_keys"
                   for k in c.keywords), (mod, owner)
