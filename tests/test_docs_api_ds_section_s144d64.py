"""Guard: docs/API.md says where the DS engine lives and what /api/ds-preview does.

RM-1286. Measured at local main a5bb8c252a95 (ENGINE 1.290.0):

  * docs/API.md carried a "NOT on :8888" section for Mission Control but none
    for Daemon Slayer, so a reader of the API reference met `/api/ds-preview`
    and `/api/build-order` with no word about the engine behind them, its
    plain-HTTP transport or where its routes are listed;
  * the `/api/ds-preview` row said "DS rank_for() top-8 items ... (champ-select
    overlay)". The handler has called `rank_for_primary_archetype` since s182
    (`rank_for` is the CARRY-only path, so the row named the wrong scorer for
    every non-carry champion), the in-game active-match panel posts to the route
    too, and the row named none of the route's answers: 200 `build_complete`,
    the schema 400 from `dispatch_post`, the handler's own 400s, 503 and the 500
    its outer except reaches through `send_error`.

The route LIST stays in one place: the server.py row of docs/DAEMON_SLAYER.md,
pinned both ways by tests/test_docs_daemon_slayer_drift.py. This section points
at it and states only the count, so it must not restate any route. Facts are
read from the source with ast (importing server.py drags in the engine).

Limit, stated on purpose: this pins the facts it can read from the source plus
the exact clauses that state them. It does not stop a new false qualifier
written around a pinned clause; pinning the whole text would make every honest
edit a test edit. ASCII only.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from tests.test_docs_daemon_slayer_drift import _SERVER, _doc_route_row, _server_routes

_REPO_ROOT = Path(__file__).resolve().parent.parent
_API_DOC = _REPO_ROOT / "docs" / "API.md"
_ROUTES_STATE = _REPO_ROOT / "dashboard" / "routes_state.py"
_ERRORS = _REPO_ROOT / "dashboard" / "_errors.py"
_DISPATCH = _REPO_ROOT / "dashboard" / "_dispatch.py"
_PANELS = _REPO_ROOT / "web" / "js" / "panels"
_FETCH = re.compile(r"""fetch\(\s*["'`]/api/ds-preview""")

_HEADING = "## NOT on `:8888` - Daemon Slayer"
_ROW_START = "| `/api/ds-preview` |"
_HANDLER = "_serve_ds_preview_post"


def _doc() -> str:
    return _API_DOC.read_text(encoding="utf-8")


def _section() -> str:
    """The Daemon Slayer section body, heading included, up to the next rule."""
    text = _doc()
    start = text.find(_HEADING)
    assert start != -1, f"docs/API.md has no {_HEADING!r} section"
    end = text.find("\n---", start)
    assert end != -1, "the Daemon Slayer section is not closed by a rule"
    return text[start:end]


def _server_constant(name: str) -> object:
    tree = ast.parse(_SERVER.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(f"server.py has no module constant {name}")


def _row() -> str:
    rows = [ln for ln in _doc().splitlines() if ln.startswith(_ROW_START)]
    assert len(rows) == 1, f"expected one /api/ds-preview row, found {len(rows)}"
    return rows[0]


def _handler() -> ast.FunctionDef:
    tree = ast.parse(_ROUTES_STATE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == _HANDLER:
            return node
    raise AssertionError(f"routes_state.py has no {_HANDLER}")


def _send_error_default_status() -> int:
    """The ``status`` default of ``dashboard._errors.send_error``."""
    tree = ast.parse(_ERRORS.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "send_error":
            names = [arg.arg for arg in node.args.args]
            defaults = node.args.defaults
            index = names.index("status") - (len(names) - len(defaults))
            return ast.literal_eval(defaults[index])
    raise AssertionError("dashboard/_errors.py has no send_error")


def _handler_statuses() -> set[int]:
    """Every status past the server's POST-wide gates: literal ``h._send``
    statuses, the ``send_error`` default its outer except reaches, and the 400
    ``dispatch_post`` answers before the handler runs. The gates' own answers
    (403, 408, 411, 413, 421, ``bad_body``) are not route facts, so the row
    scopes itself with "Past the server's POST-wide gates"."""
    found: set[int] = set()
    for node in ast.walk(_handler()):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_send"
                and node.args
                and isinstance(node.args[0], ast.Constant)):
            found.add(node.args[0].value)
    if "send_error" in _handler_called_names():
        found.add(_send_error_default_status())
    dispatch = _DISPATCH.read_text(encoding="utf-8")
    assert re.search(r'"/api/ds-preview":\s+DsPreviewRequest\b', dispatch)
    assert "handler._send(400" in dispatch and "bad_request_body" in dispatch
    found.add(400)
    return found


def _handler_called_names() -> set[str]:
    return {
        node.func.id for node in ast.walk(_handler())
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


def _handler_top() -> int:
    """The ``top=`` the handler's ``rank_kwargs = dict(...)`` asks the engine for."""
    for node in ast.walk(_handler()):
        if (isinstance(node, (ast.Assign, ast.AnnAssign))
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "dict"):
            for kw in node.value.keywords:
                if kw.arg == "top":
                    return ast.literal_eval(kw.value)
    raise AssertionError(f"{_HANDLER} builds no dict(top=...) kwargs")


# -- the section -------------------------------------------------------------


def test_section_heading_names_the_served_port() -> None:
    heading = _section().splitlines()[0]
    assert f"`:{_server_constant('DEFAULT_PORT')}`" in heading


def test_section_sits_before_the_authentication_section() -> None:
    text = _doc()
    assert text.index(_HEADING) < text.index("## Authentication")


def test_section_states_the_transport() -> None:
    server_text = _SERVER.read_text(encoding="utf-8")
    assert not re.search(r"^\s*(import|from)\s+ssl\b", server_text, re.MULTILINE)
    body = " ".join(_section().split())
    assert "The engine is its own server, `agents/daemon_slayer/server.py`" in body
    host = _server_constant("DEFAULT_HOST")
    assert f"bound to `{host}` by default, plain HTTP, not HTTPS," in body


def test_section_states_the_host_gate_and_no_token() -> None:
    server_text = _SERVER.read_text(encoding="utf-8")
    assert "HostAllowlistMixin" in server_text
    lowered = server_text.lower()
    for token in ("authorization", "x-rc-token", "bearer"):
        assert token not in lowered, f"server.py now reads {token}; update docs/API.md"
    gate = (_REPO_ROOT / "core" / "http_host_gate.py").read_text(encoding="utf-8")
    assert "421" in gate
    body = " ".join(_section().split())
    assert "Its Host gate answers 421 to a name this machine does not answer to." in body
    assert "with no auth token" in body


def test_section_route_count_is_the_registered_surface() -> None:
    body = " ".join(_section().split())
    match = re.search(r"\b(\d+) routes plus the `GET /` index page\b", body)
    assert match, "the section must state its route count and the index page"
    assert int(match.group(1)) == len(_server_routes())
    assert "/" not in _server_routes(), "the count excludes the index page"


def test_section_points_at_the_one_route_list_without_restating_it() -> None:
    body = " ".join(_section().split())
    assert "This file does not list those routes" in body
    assert "the docs list is the `server.py` row of the module map in `docs/DAEMON_SLAYER.md`" in body
    assert "ThreadingHTTPServer" in _doc_route_row()
    routes = _server_routes()
    assert routes, "the route parser found nothing (an empty set would pass)"
    named = sorted(
        route for route in routes
        if re.search(rf"(?<![\w/.-]){re.escape(route)}(?![\w-])", _doc())
    )
    assert not named, (
        f"the API.md text restates DS routes {named}; "
        "the docs list lives in the docs/DAEMON_SLAYER.md server.py row"
    )


def test_section_names_where_body_keys_are_parsed() -> None:
    assert "def _route_stats(" in _SERVER.read_text(encoding="utf-8")
    body = " ".join(_section().split())
    assert "each POST route's body keys are parsed in its `_route_*` handler" in body


def test_section_names_the_client_the_dashboard_reaches_it_through() -> None:
    client = _REPO_ROOT / "core" / "daemon_slayer_client.py"
    assert "http://" in client.read_text(encoding="utf-8")
    body = " ".join(_section().split())
    assert ("`/api/ds-preview` above makes its ranking call over HTTP through "
            "`core/daemon_slayer_client.py`") in body


def test_section_says_the_capability_gap_runs_in_the_rc_process() -> None:
    """The handler's one engine path that is NOT HTTP: found by a verifier that
    watched ``agents.daemon_slayer.*`` modules load during a preview call."""
    source = ast.unparse(_handler())
    assert "from core.ds_capability_gap import build_capability_gap" in source
    gap = (_REPO_ROOT / "core" / "ds_capability_gap.py").read_text(encoding="utf-8")
    assert "from agents.daemon_slayer." in gap
    body = " ".join(_section().split())
    assert ("computes its `capability_gap` field in the RC process "
            "(`core/ds_capability_gap.py`), so an `:8860` restart does not "
            "reload that code.") in body


# -- the /api/ds-preview row -------------------------------------------------


def test_row_names_the_scorer_the_handler_really_calls() -> None:
    assert "rank_for_primary_archetype" in _handler_called_names()
    row = _row()
    assert ("from `rank_for_primary_archetype()` (the champion's archetype "
            "scorer;") in row
    assert not re.search(r"\brank_for\(\)", row)


def test_row_names_the_request_schema_dispatch_validates_with() -> None:
    dispatch = _DISPATCH.read_text(encoding="utf-8")
    schema = re.search(r'"/api/ds-preview":\s+(\w+)', dispatch).group(1)
    assert _row().startswith(f"{_ROW_START} `{schema}` |")


def test_row_top_count_is_what_the_handler_asks_for() -> None:
    assert f"Top-{_handler_top()} items" in _row()


def test_row_names_every_status_the_handler_sends() -> None:
    sent = _handler_statuses()
    assert 200 in sent, "the status parser must see the success send"
    assert sent - {200}, "the status parser must see an error send"
    row_codes = {int(c) for c in re.findall(r"\b([1-5]\d\d)\b", _row())}
    assert row_codes == sent


def test_row_names_the_full_build_reason() -> None:
    source = ast.unparse(_handler())
    assert "'ranked': []" in source and "'reason': 'build_complete'" in source
    assert "a full build is 200 with `ranked: []` and `reason` = `build_complete`" in _row()


def test_row_panels_are_exactly_the_panels_that_post_to_the_route() -> None:
    posting = {
        path.name for path in _PANELS.rglob("*.js")
        if _FETCH.search(path.read_text(encoding="utf-8", errors="replace"))
    }
    assert posting, "no panel posts to /api/ds-preview (an empty walk would pass)"
    row = _row()
    assert set(re.findall(r"`([\w.-]+\.js)`", row)) == posting
    assert "Posted by `active_match.js` and `champ_select.js`." in row


def test_row_says_what_each_failure_means() -> None:
    """Each meaning is paired with the source token that makes it true."""
    source = ast.unparse(_handler())
    dispatch = _DISPATCH.read_text(encoding="utf-8")
    row = _row()
    assert "first_ambiguous_flag" in source and "'champion required'" in source
    assert "bad_request_body" in dispatch
    assert ("400 = a body the schema rejects (`bad_request_body`), an empty "
            "`champion` or an ambiguous seam flag;") in row
    assert "out is None" in source
    assert ("503 = the engine call failed, for example down, timed out or an "
            "engine error status;") in row
    assert "except Exception" in source and "500 = an uncaught handler failure" in row
    assert "Past the server's POST-wide gates:" in row


def test_row_says_the_archetype_field_overrides_the_stored_pick() -> None:
    source = ast.unparse(_handler())
    assert "payload.get('archetype')" in source
    assert "get_archetype_for" in source
    assert "the `archetype` body field overrides the stored pick" in _row()
