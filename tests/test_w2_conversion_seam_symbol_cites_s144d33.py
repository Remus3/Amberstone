"""Guard: the W2 conversion-seam test cites by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. The W2 plumb test
(tests/test_ds_client_conversion_seam_plumb_w2.py) carried line cites on 17
lines, written by the W2 plumb (51e6dd0cf) and the transport hardening
(ca2dbb5c5), into server.py, rank.py, kit_conversion.py,
_crit_conversion_overrides.py, core/daemon_slayer_client.py and
core/build_order_precompute.py. Two still land on their target
(kit_conversion.py:269, _crit_conversion_overrides.py:95); the rest had
drifted, and a line cite into a file other commits keep editing resolves to
SOME line forever, so it never fails loudly. Each claim was re-read by symbol
at HEAD. Two were not true as written:

- "server.py:2630 builds a stdlib ThreadingHTTPServer and never raises
  request_queue_size". Line 2630 held the stock constructor in the parent of
  ca2dbb5c5, but that same commit also raised the backlog:
  ``_RcThreadingHTTPServer`` sets ``request_queue_size = 128``. The prose now
  records the stock backlog as the measured past state.
- "Both keys live ONLY on POST /rank". True at 51e6dd0cf, but 041984580 and
  c09d9397b later taught ``_route_rank_assassin`` and ``_route_rank_bruiser``
  to parse ``kit_conversion_strength``. ``apply_crit_conversion`` is still
  ``_route_rank`` only, and the test below pins both parser sets exactly.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
W2 = REPO / "tests" / "test_ds_client_conversion_seam_plumb_w2.py"
DS = REPO / "agents" / "daemon_slayer"
CLIENT = REPO / "core" / "daemon_slayer_client.py"
PRECOMPUTE = REPO / "core" / "build_order_precompute.py"

# ``server.py:488``, ``core/daemon_slayer_client.py:95-112``, and the bare
# grep-record shapes ``server.py 481/488`` and ``(line 1840``.
_LINE_CITE = re.compile(
    r"(?<![A-Za-z_])(?:server|rank|kit_conversion|_crit_conversion_overrides"
    r"|daemon_slayer_client|build_order_precompute)\.py(?::| )\d"
    r"|\(line \d"
)

# Phrases only the replacement prose carries, so deleting the prose fails here.
_NAMED_IN_PROSE = (
    "server (``_route_rank`` in ``agents/daemon_slayer/server.py``)",
    "(a ``rank_items`` parameter in ``agents/daemon_slayer/rank.py``)",
    "``agents/daemon_slayer/kit_conversion.py`` ``_KIT_CONVERSION``",
    "since 041984580 / c09d9397b ``_route_rank_assassin`` and",
    "``rank_for_primary_archetype`` (its carry + kit-less-fallback chokepoint)",
    "``rank_items``' RM-86 L1 gate",
    "``_post_json`` (``core/daemon_slayer_client.py``) maps EVERY transport",
    "``DEFAULT_TIMEOUT = 0.5`` s",
    "``request_queue_size = 128``",
    "core/daemon_slayer_client.py _post_json, not a ranking change",
    "``_install_static_transport`` in ``core/build_order_precompute.py``",
)


def _function(path: Path, fn: str) -> tuple[str, ast.AST]:
    src = path.read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == fn:
            return src, node
    raise AssertionError(f"{path.name} has no {fn}")


def _segment(path: Path, fn: str) -> str:
    src, node = _function(path, fn)
    return ast.get_source_segment(src, node) or ""


def _parsers(key: str) -> set[str]:
    """Every server.py function passing ``key`` as a string call argument."""
    src = (DS / "server.py").read_text(encoding="utf-8")
    return {
        node.name
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.FunctionDef)
        for call in ast.walk(node) if isinstance(call, ast.Call)
        for a in call.args
        if isinstance(a, ast.Constant) and a.value == key
    }


def test_pattern_matches_the_rotted_shapes():
    for sample in (
        "server (``agents/daemon_slayer/server.py:488``) and",
        "(``rank.py:921``).",
        "``agents/daemon_slayer/kit_conversion.py:106``) is",
        "(_crit_conversion_overrides.py:95) are read",
        "``core/daemon_slayer_client.py:95-112``",
        "``core/build_order_precompute.py:604-638`` uses",
        "returns server.py 481/488/511/512 and rank.py 918/921",
        "(line 1840, the carry",
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (
        "agents/daemon_slayer/server.py",
        "``rank_items``' RM-86 L1 gate",
        "burst.py:522",
        "my_server.py:12",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_cite_left_in_w2_test():
    hits = [
        f"{W2.name}:{n}: {line.strip()}"
        for n, line in enumerate(W2.read_text(encoding="utf-8").splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_replacement_prose_present():
    text = W2.read_text(encoding="utf-8")
    missing = [p for p in _NAMED_IN_PROSE if p not in text]
    assert not missing, missing


def test_conversion_seam_parser_sets_are_exact():
    assert _parsers("apply_crit_conversion") == {"_route_rank"}
    assert _parsers("kit_conversion_strength") == {
        "_route_rank", "_route_rank_bruiser", "_route_rank_assassin",
    }


def test_route_rank_reads_both_seams_with_the_cited_defaults():
    body = _segment(DS / "server.py", "_route_rank")
    assert '_opt_float(body, "kit_conversion_strength", 0.0)' in body
    assert '_opt_bool(body, "apply_crit_conversion", False)' in body


def test_rank_items_takes_both_and_gates_the_registry_on_positive():
    _, node = _function(DS / "rank.py", "rank_items")
    params = {a.arg for a in node.args.args + node.args.kwonlyargs}
    assert {"kit_conversion_strength", "apply_crit_conversion"} <= params
    assert "if kit_conversion_strength > 0.0 else None" in _segment(
        DS / "rank.py", "rank_items")


def test_registries_named_in_prose_exist():
    kc = (DS / "kit_conversion.py").read_text(encoding="utf-8")
    assert "\n_KIT_CONVERSION: dict[str, KitConversion] = {" in kc
    assert "\ndef registry_champion_ids() -> frozenset[str]:" in kc
    cc = (DS / "_crit_conversion_overrides.py").read_text(encoding="utf-8")
    assert "\n_CRIT_CONVERSION: dict[str, CritConversionEntry] = {" in cc


def test_rank_for_has_one_call_site_inside_the_dispatcher():
    src = CLIENT.read_text(encoding="utf-8")
    callers = [
        node.name
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.FunctionDef)
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
        and call.func.id == "rank_for"
    ]
    assert callers == ["rank_for_primary_archetype"], callers


def test_client_transport_claims_hold():
    src = CLIENT.read_text(encoding="utf-8")
    assert "\nDEFAULT_TIMEOUT = 0.5 " in src
    post = _segment(CLIENT, "_post_json")
    assert ("except (URLError, HTTPError, socket.timeout, TimeoutError, "
            "ConnectionError)") in post
    assert "return None" in post


def test_server_backlog_is_raised():
    assert "request_queue_size = 128" in _segment(
        DS / "server.py", "_RcThreadingHTTPServer")
    assert "_RcThreadingHTTPServer((host, port), Handler)" in _segment(
        DS / "server.py", "start_server")


def test_static_transport_rebinds_post_json():
    assert "dsc._post_json = _inprocess_post" in _segment(
        PRECOMPUTE, "_install_static_transport")
