"""Guard: eight DS-adjacent test files cite their targets by symbol (RM-1053).

Measured 2026-10-31 at ENGINE 1.290.0. Eight test files that pin the DS
client, the build-order planner, the generator, the DS server and the DS
extractors carried 36 ``<file>.py:<n>`` cites plus two bare ``:<n>`` partner
cites. Most had drifted, for example:

- ``core/daemon_slayer_client.py:1410`` for the ``apply_squishy_burst_target``
  default (now in ``rank_for_primary_archetype``, near 3012), ``:95-112`` for
  ``_post_json`` (99), ``:33`` for ``DEFAULT_TIMEOUT`` (37) and ``:71`` for
  the ``effective_score`` parse of ``RankedItem.from_dict`` (75).
- ``core/build_order.py:597-724`` / ``:597-619`` / ``:622-696`` /
  ``:704-724`` / ``:727-731`` for ``plan_build_order``'s greedy loop, its
  ``call_kwargs``, its boots insertion and its ``out is None`` branch, and
  ``:516`` / ``:253-254`` for its ``score_by`` default and
  ``SCORE_BY_DEFAULT`` / ``SCORE_BY_VALUES`` (531 and 260-261).
- ``core/build_order_precompute.py:330-335`` / ``:604-638`` for
  ``compute_cell``'s ``order=[]`` contract and ``_install_static_transport``.
- ``tools/daemon_slayer_build_orders_generate.py:107-128`` / ``:188-207`` /
  ``:191-207`` / ``:291-301`` for the module constants, the
  ``build_order_for_class`` call site and ``_build_arg_parser``.
- ``agents/daemon_slayer/server.py:2630`` / ``:2836`` / ``:185`` for
  ``start_server``, ``Handler._read_json_body`` and ``_SnapshotCache.get``.
  The 2630 cite also described a server that "never raises
  ``request_queue_size``": true when measured, stale since
  ``_RcThreadingHTTPServer`` raised it to 128, so the comment now says so.
- The dashboard, extractor, vision, live-client and test-file cites beside
  them (``dashboard/server.py:35``, ``_handler.py:342`` / ``:152``,
  ``routes_state.py:288``, ``vision_tracker.py:55``, ``_liveclient.py:131,135``,
  the four extractor cites, ``test_drift_guard.py:34``,
  ``test_build_order_precompute.py:36``, ``test_build_order_variants.py:243-250``
  and ``test_changelog_tracks_engine_version.py:65``, whose skip is gone).
  Only ``stats.py:107-108`` and ``mia_reachability.py:165`` still landed.

The change is comment and docstring only. The tests below ratchet all eight
files to zero line cites, pin the symbol cites, and re-derive every restated
claim by AST.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

_PY_LINE = re.compile(r"(?<![\w./])[\w/]+\.py:\d")
_BARE_LINE = re.compile(r"``:\d{2,4}(?:-\d+)?``|, :\d{2,4}-\d+")

TARGETS = {
    "tests/test_archetype_dispatcher.py": (
        "(the ``apply_squishy_burst_target`` default of\n"
        "    ``rank_for_primary_archetype`` in core/daemon_slayer_client.py)",
        "``compute_variant_cell`` in core/build_order_variants.py",
    ),
    "tests/test_build_order_alias_dedupe_w3.py": (
        "``_post_json`` (in ``core/daemon_slayer_client.py``)",
        "``compute_cell`` in ``core/build_order_precompute.py``",
        "branch of ``plan_build_order`` in ``core/build_order.py``",
        "``start_server`` in ``agents/daemon_slayer/server.py``",
        "``_RcThreadingHTTPServer``, whose ``request_queue_size`` is 128",
        "``_install_static_transport`` in ``core/build_order_precompute.py``",
    ),
    "tests/test_build_orders_family_a_guard.py": (
        "``plan_build_order`` in\n``core/build_order.py`` runs a GREEDY loop",
        "``boots_step`` appended after engine call 1",
        "(``RankedItem.from_dict`` in\n    core/daemon_slayer_client.py)",
        "Mirrors the ``call_kwargs`` that ``plan_build_order``",
        "``build_order_for_class`` call site",
        "(the greedy ``for engine_call_i`` loop of ``plan_build_order``",
    ),
    "tests/test_build_orders_generate_score_by.py": (
        "``build_order_for_class`` in\n    tools/daemon_slayer_build_orders_generate.py",
        "``_build_arg_parser`` in\n    tools/daemon_slayer_build_orders_generate.py",
    ),
    "tests/test_champion_movespeed.py": (
        "the two movement-speed rows of ``ITEM_STAT_KEY_MAP``",
        "``_sr_zone`` in core/vision_tracker.py",
        "(``_item_ids``, ``liveclient_summary``)",
        "(``_ring_for`` in core/mia_reachability.py reaches it",
    ),
    "tests/test_ds_feed_index.py": (
        "(each one's ``_load_champion_ids``)",
        "(the ``--out`` argument in each one's ``main``)",
    ),
    "tests/test_body_read_timeout_rm152.py": (
        "``RC_DASH_TOKEN`` check in ``Handler.do_POST`` (``_handler.py``)",
        "(``_serve_state_stream`` in ``routes_state.py``)",
        "``Handler._proxy_to_supervisor`` (``_handler.py``)",
        "agents/daemon_slayer/server.py Handler._read_json_body",
        "_SnapshotCache.get in server.py",
    ),
    "tests/test_ds_live_route_gate.py": (
        "(the `core/daemon_slayer_client.py` module docstring",
        "(`REQUIRE_GATE_ENV` in tests/test_drift_guard.py)",
        "(`REQUIRE_TABLES_ENV` in\ntests/test_build_order_precompute.py)",
        "(`LiveEnginePivotTests.setUp` in tests/test_build_order_variants.py)",
        "neighbouring `_engine_version` docstring",
    ),
}


def _text(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _tree(rel: str) -> ast.Module:
    return ast.parse(_text(rel))


def _top(rel: str, name: str) -> ast.AST:
    for node in _tree(rel).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not defined at top level of {rel}")


def _method(rel: str, cls: str, name: str) -> ast.FunctionDef:
    for node in _top(rel, cls).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{cls}.{name} not defined in {rel}")


def _top_assign(rel: str, name: str) -> ast.expr:
    for node in _tree(rel).body:
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                return node.value
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == name and node.value is not None:
                return node.value
    raise AssertionError(f"{name} not assigned at top level of {rel}")


def _calls(func: ast.AST) -> set[str]:
    out = set()
    for n in ast.walk(func):
        if isinstance(n, ast.Call):
            out.add(ast.unparse(n.func))
    return out


def _strings(func: ast.AST) -> list[str]:
    return [
        n.value for n in ast.walk(func)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


def test_patterns_match_the_rotted_shapes():
    for sample in (
        "(core/daemon_slayer_client.py:1410), so",
        "``agents/daemon_slayer/server.py:2630`` builds",
        "# dashboard/_liveclient.py:131,135 - items",
        "(tests/test_build_order_variants.py:243-250).",
        "`agents/daemon_slayer/tests/test_changelog_tracks_engine_version.py:65`,",
    ):
        assert _PY_LINE.search(sample), sample
    for sample in ("(``:704-724``, synthetic", "generate.py:107-128, :188-207)."):
        assert _BARE_LINE.search(sample), sample
    for sample in (
        "needs the DS engine on :8860",
        "test_x.py::TestY",
        "``core.build_order``",
        "ci.yml:125",
        "1%:2%",
    ):
        assert not _PY_LINE.search(sample), sample
        assert not _BARE_LINE.search(sample), sample


def test_targets_are_the_eight_measured_files():
    # An empty parameter set would SKIP the ratchet below, not fail it.
    assert len(TARGETS) == 8
    assert all(TARGETS[rel] for rel in TARGETS)


@pytest.mark.parametrize("rel", sorted(TARGETS))
def test_targets_cite_by_symbol(rel):
    text = _text(rel)
    lines = text.splitlines()
    hits = [
        i for i, line in enumerate(lines, 1)
        if _PY_LINE.search(line) or _BARE_LINE.search(line)
    ]
    assert hits == [], (rel, hits)
    for needle in TARGETS[rel]:
        assert needle in text, (rel, needle)


def test_client_symbols():
    rel = "core/daemon_slayer_client.py"
    assert "never load-bearing" in (ast.get_docstring(_tree(rel)) or "")
    timeout = _top_assign(rel, "DEFAULT_TIMEOUT")
    assert isinstance(timeout, ast.Constant) and timeout.value == 0.5
    _top(rel, "_post_json")
    from_dict = _method(rel, "RankedItem", "from_dict")
    assert "effective_score" in _strings(from_dict)
    func = _top(rel, "rank_for_primary_archetype")
    kw = dict(zip(
        [a.arg for a in func.args.kwonlyargs], func.args.kw_defaults
    ))
    pos = func.args.args
    kw.update(zip([a.arg for a in pos[len(pos) - len(func.args.defaults):]],
                  func.args.defaults))
    d = kw["apply_squishy_burst_target"]
    assert isinstance(d, ast.Constant) and d.value is True
    _top("core/build_order_variants.py", "compute_variant_cell")


def test_plan_build_order_shape():
    rel = "core/build_order.py"
    assert ast.literal_eval(_top_assign(rel, "SCORE_BY_DEFAULT")) == "blended"
    assert ast.unparse(_top_assign(rel, "SCORE_BY_VALUES")).startswith("frozenset(")
    func = _top(rel, "plan_build_order")
    kwonly = dict(zip([a.arg for a in func.args.kwonlyargs], func.args.kw_defaults))
    assert ast.unparse(kwonly["score_by"]) == "SCORE_BY_DEFAULT"
    loops = [
        n for n in ast.walk(func) if isinstance(n, ast.For)
        and isinstance(n.target, ast.Name) and n.target.id == "engine_call_i"
    ]
    assert len(loops) == 1
    loop = loops[0]
    assigned = {
        t.id for n in ast.walk(loop) if isinstance(n, ast.Assign)
        for t in n.targets if isinstance(t, ast.Name)
    }
    assert {"call_kwargs", "boots_step"} <= assigned
    tests = [ast.unparse(n.test) for n in ast.walk(loop) if isinstance(n, ast.If)]
    assert "out is None" in tests
    assert any(isinstance(n, ast.Try) for n in ast.walk(loop))


def test_precompute_symbols():
    rel = "core/build_order_precompute.py"
    doc = ast.get_docstring(_top(rel, "compute_cell")) or ""
    assert "order=[]" in doc
    func = _top(rel, "_install_static_transport")
    targets = {
        ast.unparse(t) for n in ast.walk(func) if isinstance(n, ast.Assign)
        for t in n.targets
    }
    assert "dsc._post_json" in targets


def test_generator_symbols():
    rel = "tools/daemon_slayer_build_orders_generate.py"
    for name in ("_COMP_SHARES", "_TARGET_ARMOR", "_TARGET_MR", "_TARGET_MAX_HP",
                 "_TARGET_BONUS_HP", "_LEVEL", "_TIMEOUT"):
        _top_assign(rel, name)
    assert "plan_build_order" in _calls(_top(rel, "build_order_for_class"))
    assert "--score-by" in _strings(_top(rel, "_build_arg_parser"))


def test_ds_server_symbols():
    rel = "agents/daemon_slayer/server.py"
    start = _top(rel, "start_server")
    assert "_RcThreadingHTTPServer" in _calls(start)
    cls = _top(rel, "_RcThreadingHTTPServer")
    sizes = [
        n.value for n in cls.body if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "request_queue_size"
                for t in n.targets)
    ]
    assert len(sizes) == 1 and ast.literal_eval(sizes[0]) == 128
    _method(rel, "Handler", "_read_json_body")
    get = _method(rel, "_SnapshotCache", "get")
    assert "snapshot not loaded yet" in _strings(get)


def test_dashboard_symbols():
    host = _top_assign("dashboard/server.py", "HOST")
    assert isinstance(host, ast.Constant) and host.value == "::"
    assert "RC_DASH_TOKEN" in _strings(_method("dashboard/_handler.py", "Handler", "do_POST"))
    _method("dashboard/_handler.py", "Handler", "_proxy_to_supervisor")
    _top("dashboard/routes_state.py", "_serve_state_stream")


def test_movespeed_neighbour_symbols():
    stats = ast.literal_eval(_top_assign("agents/daemon_slayer/stats.py", "ITEM_STAT_KEY_MAP"))
    assert stats["FlatMovementSpeedMod"] == ("ms", "flat")
    assert stats["PercentMovementSpeedMod"] == ("ms", "pct")
    vt = _text("core/vision_tracker.py")
    zone = _top("core/vision_tracker.py", "_sr_zone")
    above = "\n".join(vt.splitlines()[max(0, zone.lineno - 6):zone.lineno - 1])
    assert "14800" in above
    assert "itemID" in _strings(_top("dashboard/_liveclient.py", "_item_ids"))
    assert "displayName" in _strings(_top("dashboard/_liveclient.py", "liveclient_summary"))
    assert "est_ms" in _calls(_top("core/mia_reachability.py", "_ring_for"))
    est = _top("core/champion_movespeed.py", "est_ms")
    returns = {
        ast.unparse(n.value) for n in ast.walk(est)
        if isinstance(n, ast.Return) and n.value is not None
    }
    assert "_FALLBACK_MS" in returns


@pytest.mark.parametrize("rel, outfile", [
    ("tools/daemon_slayer_wiki_stats_extract.py", "wiki_stats.json"),
    ("tools/daemon_slayer_cdragon_spell_extract.py", "cdragon_spell_stats.json"),
])
def test_extractor_symbols(rel, outfile):
    doc = ast.get_docstring(_top(rel, "_load_champion_ids")) or ""
    assert "fetched_at" in doc
    helps = [
        kw.value.value for n in ast.walk(_top(rel, "main")) if isinstance(n, ast.Call)
        and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == "--out"
        for kw in n.keywords if kw.arg == "help" and isinstance(kw.value, ast.Constant)
    ]
    assert helps and outfile in helps[0]


def test_test_file_symbols():
    gate = _top_assign("tests/test_drift_guard.py", "REQUIRE_GATE_ENV")
    assert ast.literal_eval(gate) == "RC_REQUIRE_HOOK_GATE"
    tables = _top_assign("tests/test_build_order_precompute.py", "REQUIRE_TABLES_ENV")
    assert ast.literal_eval(tables) == "RC_REQUIRE_BUILD_ORDER_TABLES"
    _method("tests/test_build_order_variants.py", "LiveEnginePivotTests", "setUp")
    rel = "agents/daemon_slayer/tests/test_changelog_tracks_engine_version.py"
    doc = ast.get_docstring(_top(rel, "_engine_version")) or ""
    assert "pulls the whole engine in" in doc
