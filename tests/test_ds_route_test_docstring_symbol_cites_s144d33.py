"""Guard: six DS route tests cite the engine by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. Six ``agents/daemon_slayer/tests``
modules carried 27 line cites - 23 into dps.py / rank.py / ehp.py / hps.py /
hybrid.py / server.py, one into a sibling test, a bare ``at :3431`` and two
``(:<n>)`` - and at HEAD all but two had drifted off their target
(``ehp.py:3431`` and the sibling test's ``:42``, the ``setUpModule`` holding
the cited call, still land). Each claim was re-read against HEAD by symbol and
still holds:

- ``dps.py:34`` = dps.py's module docstring ("Ability damage is **not**
  included"); ``dps.py:508`` = ``_rotation_attack_dps``;
  ``dps.py:945/950/967`` = ``compute_dps`` keying ``stats_for_rotation`` by
  "crit" / "as" / "ad"; ``dps.py:758`` = ``compute_dps``'s ``rune_ids``
  parameter; ``dps.py:1058`` / ``dps.py:1124`` = its
  ``if apply_rune_offense_grants:`` / ``if apply_crit_chance_overrides:``.
- ``ehp.py:1389`` / ``ehp.py:2582`` = ``compute_ehp``'s
  ``apply_build_tenacity`` parameter and gate; ``ehp.py:3204`` / ``:3431`` =
  ``rank_items_by_ehp``'s tri-state parameter and its ``apply_tenacity``
  resolution; ``ehp.py:1372`` / ``ehp.py:3127`` = the two signatures naming
  ``assume_passive_flat_mitigation``; ``ehp.py:1570-1571`` /
  ``ehp.py:3161-3162`` = the two signatures naming the rune heal / shield
  flags; ``ehp.py:1763`` / ``ehp.py:1888`` = ``compute_ehp``'s
  ``if apply_rune_shield_grants:`` / ``if apply_rune_self_heal:``.
- ``rank.py:918`` / ``rank.py:1294-1297`` = ``rank_items``'
  ``kit_conversion_strength`` parameter and its ``> 0.0`` lookup gate.
- ``hps.py:863`` = ``rank_items_by_hps``' signature; ``hps.py:685`` =
  ``compute_hps``' ``amp_factor if apply_ability_hsp_amp else 1.0``.
- ``hybrid.py:193 / 332 / 792 / 1363`` = the propensity gates in
  ``hybrid._ability_damage`` and (moved since)
  ``_ad_axis_ability.physical_ability_damage``, and the
  ``if assume_ms_utility:`` branches of ``compute_hybrid`` /
  ``rank_items_by_hybrid``.
- ``server.py:968`` / ``(:1255)`` / ``(:1397)`` = the ``apply_build_tenacity``
  parses of ``_route_rank_tank`` / ``_route_hybrid`` / ``_route_rank_bruiser``;
  ``server.py:421-501`` = ``_route_rank``'s ``rank_items`` call;
  ``test_rank_route_seam_passthrough.py:42`` = its ``server._CACHE.set``.

Each claim is pinned below so a rename or a moved gate fails here. Scope:
the six files' dps / rank / ehp / hps / hybrid / server cites; their
``ability_dps.py:<n>`` cites are a separate RM-1053 residue.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
DS_TESTS = DS / "tests"

FILES = (
    "test_ad_axis_ability_damage_rm39.py",
    "test_ehp_build_tenacity_route_rm334.py",
    "test_ehp_survivability_route_seams_rm118.py",
    "test_kit_conversion_route_exposure.py",
    "test_rune_lane_route_seams_rm118.py",
    "test_stranded_lane_route_seams_rm118.py",
)

# ``ehp.py:3431``, ``(:1255)``, ``at :3431`` and a cited test module; the
# boundary keeps ``ability_dps.py:371`` (a separate residue) and ``:8860`` out.
_LINE_CITE = re.compile(
    r"(?<![A-Za-z_])(?:dps|rank|ehp|hps|hybrid|server)\.py:\d"
    r"|\(:\d+\)|\bat :\d|_passthrough\.py:\d"
)

# Phrases only the replacement prose carries, per file.
_NAMED_IN_PROSE = {
    "test_ad_axis_ability_damage_rm39.py": (
        "and dps.py's module docstring says the AD branch omits",
        "``_rotation_attack_dps``\n    (in ``dps.py``) reads ONLY",
        '(``compute_dps`` keys it by "crit" / "as" / "ad")',
    ),
    "test_ehp_build_tenacity_route_rm334.py": (
        "236 and consumes it under its own ``if apply_build_tenacity:``",
        "``_route_rank_tank``, ``_route_hybrid``\nand ``_route_rank_bruiser``.",
        "resolved per scoring mode into its ``apply_tenacity``,",
        "per scoring mode (its\n        ``apply_tenacity`` - ON for cc_blended",
    ),
    "test_ehp_survivability_route_seams_rm118.py": (
        "is on ``compute_ehp`` AND\n    ``rank_items_by_ehp`` (both",
    ),
    "test_kit_conversion_route_exposure.py": (
        "kit_conversion_strength: float = 0.0)`` - its signature.",
        "``kit_conversion(...) if kit_conversion_strength > 0.0 else None``",
        "builds the ``rank_items`` call.",
        "its ``setUpModule``'s\n    ``server._CACHE.set(_SNAP)``",
    ),
    "test_rune_lane_route_seams_rm118.py": (
        "parameter with the seam\nand the route never carried either.",
        "``compute_ehp`` and on ``rank_items_by_ehp`` (both signatures)",
        "``if apply_rune_offense_grants:`` in ``compute_dps``",
    ),
    "test_stranded_lane_route_seams_rm118.py": (
        "``apply_ability_hsp_amp`` in its\n    signature,",
        "``if apply_crit_chance_overrides:`` in\n``compute_dps``;",
        "``hybrid._ability_damage`` and\n"
        "``_ad_axis_ability.physical_ability_damage``",
    ),
}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _function(path: Path, name: str) -> ast.FunctionDef:
    for node in _tree(path).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{path.name} has no top-level def {name}")


def _params(fn: ast.FunctionDef) -> set[str]:
    args = fn.args
    return {a.arg for a in args.posonlyargs + args.args + args.kwonlyargs}


def _default(fn: ast.FunctionDef, name: str) -> str:
    args = fn.args
    positional = args.posonlyargs + args.args
    pairs = list(zip(positional[len(positional) - len(args.defaults):],
                     args.defaults))
    pairs += [(a, d) for a, d in zip(args.kwonlyargs, args.kw_defaults) if d]
    for arg, default in pairs:
        if arg.arg == name:
            return ast.unparse(default)
    raise AssertionError(f"{fn.name}.{name} has no default")


def _has_if(fn: ast.FunctionDef, test_src: str) -> bool:
    return any(
        isinstance(node, ast.If) and ast.unparse(node.test) == test_src
        for node in ast.walk(fn)
    )


def _sources(fn: ast.FunctionDef) -> list[str]:
    return [ast.unparse(node) for node in ast.walk(fn)]


def test_pattern_matches_the_rotted_shapes():
    for sample in (
        "``dps.py:34`` says",
        "(dps.py:945/950/967 read",
        "236 (ehp.py:1389) and",
        "``_route_hybrid`` (:1255) and",
        "per scoring mode at :3431,",
        "(hps.py:863),",
        "``_route_rank_tank`` (server.py:968),",
        "- test_rank_route_seam_passthrough.py:42 precedent.",
        "(dps.py:1124, hps.py:685, hybrid.py:193 / 332 /",
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (
        "``ability_dps.py:371`` idiom",
        "dps.py's module docstring",
        "OFFLINE ONLY: no live :8860, no network.",
        "through ``:8860``, so",
        "OPEN_ITEMS_REVIEW_2026-07-25.md measured",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_number_cites_into_engine_modules():
    hits = []
    for name in FILES:
        lines = (DS_TESTS / name).read_text(encoding="utf-8").splitlines()
        hits += [
            f"{name}:{n}: {line.strip()}"
            for n, line in enumerate(lines, 1)
            if _LINE_CITE.search(line)
        ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_prose_names_the_symbols():
    missing = []
    for name, phrases in _NAMED_IN_PROSE.items():
        text = (DS_TESTS / name).read_text(encoding="utf-8")
        missing += [f"{name}: {p!r}" for p in phrases if p not in text]
    assert not missing, "\n".join(missing)


def test_dps_claims():
    dps = DS / "dps.py"
    doc = ast.get_docstring(_tree(dps)) or ""
    assert "Ability damage is **not** included" in doc
    _function(dps, "_rotation_attack_dps")
    fn = _function(dps, "compute_dps")
    assert "rune_ids" in _params(fn)
    for flag in ("apply_rune_offense_grants", "apply_crit_chance_overrides"):
        assert _has_if(fn, flag), f"compute_dps lost `if {flag}:`"
    keys = {
        node.slice.value
        for node in ast.walk(fn)
        if isinstance(node, ast.Subscript)
        and ast.unparse(node.value) == "stats_for_rotation"
        and isinstance(node.slice, ast.Constant)
    }
    assert {"crit", "as", "ad"} <= keys, keys


def test_ehp_claims():
    ehp = DS / "ehp.py"
    compute = _function(ehp, "compute_ehp")
    ranker = _function(ehp, "rank_items_by_ehp")
    shared = (
        "assume_passive_flat_mitigation",
        "apply_rune_self_heal",
        "apply_rune_shield_grants",
    )
    for flag in shared:
        assert flag in _params(compute), f"compute_ehp lost {flag}"
        assert flag in _params(ranker), f"rank_items_by_ehp lost {flag}"
    for flag in ("apply_build_tenacity", *shared[1:]):
        assert _has_if(compute, flag), f"compute_ehp lost `if {flag}:`"
    assert _default(compute, "apply_build_tenacity") == "False"
    assert _default(ranker, "apply_build_tenacity") == "None"
    assert any(
        src.startswith("apply_tenacity = apply_build_tenacity if")
        and "score_by == 'cc_blended'" in src
        for src in _sources(ranker)
    ), "rank_items_by_ehp no longer resolves apply_tenacity per scoring mode"


def test_rank_kit_conversion_claims():
    fn = _function(DS / "rank.py", "rank_items")
    assert _default(fn, "kit_conversion_strength") == "0.0"
    assert any(
        src.startswith("kit_conversion(")
        and src.endswith("if kit_conversion_strength > 0.0 else None")
        for src in _sources(fn)
    )


def test_hps_claims():
    hps = DS / "hps.py"
    assert "apply_ability_hsp_amp" in _params(_function(hps, "compute_hps"))
    assert "apply_ability_hsp_amp" not in _params(
        _function(hps, "rank_items_by_hps")
    )
    assert "amp_factor if apply_ability_hsp_amp else 1.0" in _sources(
        _function(hps, "compute_hps")
    )


def test_hybrid_claims():
    for path, name in (
        (DS / "hybrid.py", "_ability_damage"),
        (DS / "_ad_axis_ability.py", "physical_ability_damage"),
    ):
        assert _has_if(
            _function(path, name), "not apply_cast_rate_propensity_prior"
        ), f"{name} lost its propensity gate"
    for name in ("compute_hybrid", "rank_items_by_hybrid"):
        assert _has_if(_function(DS / "hybrid.py", name), "assume_ms_utility")


def test_server_claims():
    server = DS / "server.py"
    for name in ("_route_rank_tank", "_route_hybrid", "_route_rank_bruiser"):
        assert "'apply_build_tenacity'" in " ".join(
            _sources(_function(server, name))
        ), f"{name} no longer parses apply_build_tenacity"
    calls = [
        node for node in ast.walk(_function(server, "_route_rank"))
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "rank_items"
    ]
    assert calls and any(
        k.arg == "kit_conversion_strength" for k in calls[0].keywords
    )
    setup = _function(DS_TESTS / "test_rank_route_seam_passthrough.py",
                      "setUpModule")
    assert "server._CACHE.set(_SNAP)" in _sources(setup)
