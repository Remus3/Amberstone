"""Guard: DS server.py cites dps / rank / ehp / hybrid by symbol (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. ``agents/daemon_slayer/server.py``
carried 21 line cites into four engine modules plus one self-cite (22 in
all), and at HEAD every one of them pointed at unrelated code. Read back against each
cite's creation commit (``git log -S``):

- ``dps.py:1058`` (346f9683e) was ``compute_dps``'s
  ``if apply_rune_offense_grants:``; ``dps.py:765`` / ``dps.py:1124``
  (7e1697e46) its ``apply_crit_chance_overrides`` parameter and gate;
  ``dps.py:890`` (bfbe2d01f) its ``if apply_crit_conversion:``;
  ``dps.py:34`` (84ed2b617) the module docstring's "Ability damage is
  **not** included".
- ``rank.py:1294-1297`` (5ea48d436) was ``rank_items``' kit-conversion
  lookup, gated on ``kit_conversion_strength > 0.0``.
- ``ehp.py:2582`` / ``ehp.py:3431`` (f3ab8ed72) were ``compute_ehp``'s
  ``if apply_build_tenacity:`` and ``rank_items_by_ehp``'s ``apply_tenacity``
  resolution; ``ehp.py:3127`` (3709ebd62) and ``ehp.py:3161-3162`` /
  ``3422 / 3618`` (346f9683e) its signature and its ``compute_ehp`` calls.
- ``hybrid.py:484-489`` / ``1037-1042`` / ``1344 / 1396-1397`` (346f9683e)
  were the rune flags in ``compute_hybrid`` / ``rank_items_by_hybrid`` and
  the ranker's per-candidate calls; ``hybrid.py:193`` / ``332`` / ``792`` /
  ``1099 / 1127`` (7e1697e46) the propensity gates (the AD-axis one has
  since moved to ``_ad_axis_ability.physical_ability_damage``), the
  ``assume_ms_utility`` branch and the ranker signature.
- ``(:1255)`` (f3ab8ed72) meant ``_route_hybrid``'s own
  ``apply_build_tenacity`` parse, which sat at 1285 in that commit - wrong
  when written.

Every claim still holds; the comments now name the function and the gate,
and each claim is pinned below so a rename or a moved gate fails here.
Scope: server.py only. The ``docs/_archive`` ``.md:<n>`` cite stays (an
archived file does not move).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
SERVER = DS / "server.py"
DPS = DS / "dps.py"
RANK = DS / "rank.py"
EHP = DS / "ehp.py"
HYBRID = DS / "hybrid.py"
AD_AXIS = DS / "_ad_axis_ability.py"

# ``dps.py:1058``, ``(hybrid.py:1037-1042)`` and a bare self-cite ``(:1255)``;
# the boundary keeps a longer module name (``_rank.py:12``) out.
_LINE_CITE = re.compile(
    r"(?<![A-Za-z_])(?:dps|rank|ehp|hybrid)\.py:\d|\(:\d+\)"
)

# Phrases only the replacement prose carries.
_NAMED_IN_PROSE = (
    "compute route to get it. ``compute_dps`` consults the registry ONLY when",
    "/dps is the SOLE owner (``compute_dps`` is the only engine function that",
    "451-457).\n    # ``rank_items`` consults the registry ONLY when",
    "gate ``if apply_crit_conversion:`` in\n    # ``compute_dps``.",
    "``items`` (``compute_ehp`` reads ``total_item_tenacity(item_ids)``",
    "matching ``_route_hybrid``'s\n    # own parse",
    "resolves it per scoring mode (its\n    # ``apply_tenacity``",
    "``rank_items_by_ehp`` takes as a parameter - the other three",
    "``rank_items_by_ehp`` names BOTH in its signature and forwards",
    "every one of them in its signature. The offense grant",
    "branches (``_ability_damage`` for AP, ``physical_ability_damage`` in",
    "on the blended score (``_ms_utility_multiplier``).",
    "auto-attack-only by design (dps.py's module docstring)",
    "``rank_items_by_hybrid`` names every one in its signature and",
    "``rank_items_by_hybrid`` names both in its signature",
)


def _function(path: Path, name: str) -> tuple[ast.FunctionDef, str]:
    text = path.read_text(encoding="utf-8")
    for node in ast.parse(text).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node, ast.get_source_segment(text, node) or ""
    raise AssertionError(f"{path.name} has no top-level def {name}")


def _params(fn: ast.FunctionDef) -> set[str]:
    args = fn.args
    return {a.arg for a in args.posonlyargs + args.args + args.kwonlyargs}


def _calls_forwarding(fn: ast.FunctionDef, kwarg: str) -> list[str]:
    return [
        ast.unparse(node.func)
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and any(k.arg == kwarg for k in node.keywords)
    ]


def _calls_in_loops(fn: ast.FunctionDef, kwarg: str) -> list[str]:
    """Calls forwarding ``kwarg`` from inside a ``for`` loop (per candidate)."""
    found = []
    for loop in ast.walk(fn):
        if isinstance(loop, ast.For):
            found += _calls_forwarding(loop, kwarg)  # type: ignore[arg-type]
    return found


def _has_if(fn: ast.FunctionDef, test_src: str) -> list[ast.If]:
    return [
        node for node in ast.walk(fn)
        if isinstance(node, ast.If) and ast.unparse(node.test) == test_src
    ]


def test_pattern_matches_the_rotted_shapes():
    for sample in (
        "it. dps.py:1058 consults",
        "owner (dps.py:765);",
        "ranker. rank.py:1294-1297 consults",
        "(ehp.py:3422 / 3618)",
        "(hybrid.py:484-489).",
        "``_route_hybrid``\n    # (:1255) and",
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (
        "dps.py's module docstring",
        "hybrid.py consults the registry",
        "_rank.py:12",
        "core/build_rank.py:40",
        "OPEN_ITEMS_REVIEW_2026-07-25.md:451-457)",
        "unreachable from :8860.",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_number_cites_into_engine_modules():
    text = SERVER.read_text(encoding="utf-8")
    hits = [
        f"server.py:{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_prose_names_the_symbols():
    text = SERVER.read_text(encoding="utf-8")
    missing = [p for p in _NAMED_IN_PROSE if p not in text]
    assert not missing, missing


def test_compute_dps_owns_and_gates_its_three_seams():
    fn, _ = _function(DPS, "compute_dps")
    params = _params(fn)
    for flag in (
        "apply_rune_offense_grants",
        "apply_crit_chance_overrides",
        "apply_crit_conversion",
    ):
        assert flag in params, f"compute_dps lost {flag}"
        assert _has_if(fn, flag), f"compute_dps no longer gates on `if {flag}:`"


def test_crit_chance_overrides_has_one_engine_owner():
    owners = []
    for path in sorted(DS.glob("*.py")):
        if path.name == "server.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.FunctionDef) and (
                "apply_crit_chance_overrides" in _params(node)
            ):
                owners.append(f"{path.name}:{node.name}")
    assert owners == ["dps.py:compute_dps"], owners
    assert "apply_crit_chance_overrides" not in _params(
        _function(RANK, "rank_items")[0]
    )


def test_dps_module_docstring_still_excludes_ability_damage():
    doc = ast.get_docstring(ast.parse(DPS.read_text(encoding="utf-8"))) or ""
    assert "Ability damage is **not** included" in doc


def test_rank_items_gates_kit_conversion_on_positive_strength():
    fn, body = _function(RANK, "rank_items")
    assert "kit_conversion_strength" in _params(fn)
    assert "if kit_conversion_strength > 0.0 else None" in body


def test_compute_ehp_reads_item_tenacity_under_its_flag():
    fn, _ = _function(EHP, "compute_ehp")
    gates = _has_if(fn, "apply_build_tenacity")
    assert gates, "compute_ehp no longer gates on `if apply_build_tenacity:`"
    assert any(
        "total_item_tenacity(item_ids" in ast.unparse(g) for g in gates
    ), "the build-tenacity gate no longer reads total_item_tenacity"


def test_tenacity_parse_shapes_match_the_comment():
    ehp_fn, _ = _function(EHP, "compute_ehp")
    ranker_fn, ranker_body = _function(EHP, "rank_items_by_ehp")
    by_name = {a.arg: a for a in ehp_fn.args.args + ehp_fn.args.kwonlyargs}
    assert ast.unparse(by_name["apply_build_tenacity"].annotation) == "bool"
    by_name = {
        a.arg: a for a in ranker_fn.args.args + ranker_fn.args.kwonlyargs
    }
    assert ast.unparse(by_name["apply_build_tenacity"].annotation) in (
        "Optional[bool]", "bool | None",
    )
    assert "apply_tenacity = (" in ranker_body
    plain = '_opt_bool(body, "apply_build_tenacity", False)'
    for route in ("_route_ehp", "_route_hybrid"):
        _, body = _function(SERVER, route)
        assert f"apply_build_tenacity = {plain}" in body, route
    for route in ("_route_rank_tank", "_route_rank_bruiser"):
        _, body = _function(SERVER, route)
        assert 'if "apply_build_tenacity" in body else None' in body, route


def test_ehp_ranker_signature_and_forwarding():
    ranker_fn, _ = _function(EHP, "rank_items_by_ehp")
    ranker = _params(ranker_fn)
    compute = _params(_function(EHP, "compute_ehp")[0])
    assert "assume_passive_flat_mitigation" in ranker
    for scalar_only in (
        "assume_passive_health_stacks",
        "assume_item_revive",
        "assume_item_stasis",
    ):
        assert scalar_only in compute, scalar_only
        assert scalar_only not in ranker, scalar_only
    for flag in ("apply_rune_self_heal", "apply_rune_shield_grants"):
        assert flag in ranker, flag
        calls = _calls_forwarding(ranker_fn, flag)
        assert calls.count("compute_ehp") >= 2, (flag, calls)
        assert "compute_ehp" in _calls_in_loops(ranker_fn, flag), flag


def test_hybrid_signatures_name_the_rune_and_axis_seams():
    runes = (
        "apply_rune_self_heal",
        "apply_rune_shield_grants",
        "apply_rune_offense_grants",
    )
    compute = _params(_function(HYBRID, "compute_hybrid")[0])
    ranker_fn, _ = _function(HYBRID, "rank_items_by_hybrid")
    ranker = _params(ranker_fn)
    for flag in runes + (
        "apply_cast_rate_propensity_prior",
        "assume_ms_utility",
    ):
        assert flag in compute, f"compute_hybrid lost {flag}"
        assert flag in ranker, f"rank_items_by_hybrid lost {flag}"
    assert "compute_dps" in _calls_in_loops(
        ranker_fn, "apply_rune_offense_grants"
    )
    for flag in runes[:2]:
        assert "compute_ehp" in _calls_in_loops(ranker_fn, flag), flag


def test_propensity_prior_gates_both_ability_branches():
    ap_fn, _ = _function(HYBRID, "_ability_damage")
    ad_fn, _ = _function(AD_AXIS, "physical_ability_damage")
    for fn in (ap_fn, ad_fn):
        assert _has_if(fn, "not apply_cast_rate_propensity_prior"), fn.name
    hybrid_text = HYBRID.read_text(encoding="utf-8")
    assert "_physical_ability_damage = physical_ability_damage" in hybrid_text


def test_ms_utility_multiplier_rides_its_flag_in_compute_hybrid():
    fn, _ = _function(HYBRID, "compute_hybrid")
    gates = _has_if(fn, "assume_ms_utility")
    assert gates
    assert any("_ms_utility_multiplier(" in ast.unparse(g) for g in gates)
