"""RM-811 residuals: the log-injection class (RM-321) past the RM-811 sites.

Measured before the fix:

1. ``tools/ds_matchdb_mcp_server.py`` ``_dispatch_tool`` logged a tool's
   failure with ``exc_info=True``. The rendered traceback ends in the
   exception's own message, verbatim: a tool that raised on the client's
   text (``ValueError(f"bad champion {name}")``) wrote raw ESC / CR / LF into
   the log - a forged line under a real timestamp.
2. ``dashboard/routes_loop_control.py`` (13 sites) and
   ``dashboard/routes_loop_status.py`` (9 sites), served by Mission Control
   behind its bearer check, logged ``%s`` of the exception unscrubbed, and so
   did the shared ``dashboard/_errors.send_error`` both modules fall back to.
   The sibling sweep over ``dashboard/routes_*.py`` + ``mc/`` measured the
   same shape at 244 call sites in 74 files.
3. ``tools/usage-mcp-server.js`` echoed an object / array / boolean ``id``
   in an ordinary reply; JSON-RPC 2.0 section 4 allows only a string, a
   number or null, so the request is -32600 Invalid Request with id null.
   ``tools/ds_matchdb_mcp_server.py`` (the one other JSON-RPC server in the
   tree) had the same echo.

THE FIX: per-site ``scrub_log`` where the brief named the sites (the two
MC-served loop modules, ``_errors.send_error``, ``mc/server.py``, the
match-DB server), plus one monotone backstop instead of 244 hand edits: a
``core.log_scrub.ScrubFilter`` on every logger the ``dashboard`` and ``mc``
packages and the match-DB server create. It escapes control characters in
the formatted message and renders any traceback with each exception's text
scrubbed onto one line while the frame lines keep their structure.
"""
from __future__ import annotations

import ast
import builtins
import contextlib
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import types
from pathlib import Path
from typing import Iterator

import pytest

ROOT = Path(__file__).resolve().parent.parent
USAGE_JS = ROOT / "tools" / "usage-mcp-server.js"
NODE = shutil.which("node")
_HOST = "127.0.0.1"
_CTRL = {chr(c) for c in range(0x00, 0x20)} | {chr(c) for c in range(0x7F, 0xA0)}
_EVIL = "client said \x1b[31mINJECTED\r\nFAKE-LINE\x85\x7f"


def _ctrl_in(text: str, allow: str = "") -> list[str]:
    return sorted({hex(ord(c)) for c in text if c in _CTRL and c not in allow})


# The structural prefix a traceback line may carry before its content: the
# indent, and an exception group's box drawing ("  | ", "  +-+---", nested
# "    |   | "). A forged line is one whose content - after that prefix -
# starts with the client's text.
_LINE_PREFIX = re.compile(r"^[\s|+\-]*")


def _assert_clean(text: str, *, multiline: bool = False) -> None:
    """No control character (bar the newlines a traceback is built from) and
    no line that the client's text could have started, group-prefixed lines
    included."""
    assert _ctrl_in(text, allow="\n" if multiline else "") == [], repr(text)
    for line in text.split("\n"):
        assert not _LINE_PREFIX.sub("", line).startswith("FAKE"), repr(text)


class _Cap(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []
        self.setFormatter(logging.Formatter("%(levelname)s %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def texts(self) -> list[str]:
        """Every record as a log FILE would hold it (traceback included)."""
        return [self.format(r) for r in self.records]


@contextlib.contextmanager
def _captured(name: str) -> Iterator[_Cap]:
    lg = logging.getLogger(name)
    cap, prior = _Cap(), lg.level
    lg.addHandler(cap)
    lg.setLevel(logging.DEBUG)
    try:
        yield cap
    finally:
        lg.removeHandler(cap)
        lg.setLevel(prior)


# -- the shared helpers ------------------------------------------------------

def test_scrub_controls_escapes_controls_and_leaves_backslashes():
    from core.log_scrub import scrub_controls, scrub_log
    assert scrub_controls("C:\\Windows\\dir a\x1b\n\x85\x7f") == "C:\\Windows\\dir a\\x1b\\x0a\\x85\\x7f"
    # Idempotent over its own output and over scrub_log's: a backstop that
    # runs after a per-site scrub never double-escapes it.
    once = scrub_controls(_EVIL)
    assert scrub_controls(once) == once
    assert scrub_controls(scrub_log(_EVIL)) == scrub_log(_EVIL)


def _chained() -> BaseException:
    def inner():
        raise KeyError("inner \x1b[31m\nFAKE-INNER")

    def rm811b_outer():
        try:
            inner()
        except KeyError as e:
            err = ValueError(_EVIL)
            err.add_note("note\nFAKE-NOTE")
            raise err from e

    try:
        rm811b_outer()
    except ValueError as e:
        return e
    raise AssertionError("unreachable")


def test_scrub_traceback_keeps_frames_and_flattens_every_message():
    from core.log_scrub import scrub_traceback
    text = scrub_traceback(_chained())
    _assert_clean(text, multiline=True)
    assert text.count("Traceback (most recent call last):") == 2, text
    assert "direct cause of the following exception" in text
    assert "in rm811b_outer" in text and "in inner" in text   # frames kept
    assert "INJECTED" in text and "FAKE-NOTE" in text          # text kept
    assert "ValueError: client said" in text


def _group() -> BaseException:
    # A builtin on every Python this tree runs on (CI 3.12, the checkout
    # 3.14), so there is no fallback to skip to.
    group_type = builtins.ExceptionGroup
    try:
        raise group_type("grp\nFAKE-G", [ValueError("a\nFAKE-A"),
                                         TypeError("b")])
    except group_type as e:
        return e
    raise AssertionError("unreachable")


def test_scrub_traceback_renders_an_exception_group_safely():
    from core.log_scrub import scrub_traceback
    text = scrub_traceback(_group())
    _assert_clean(text, multiline=True)
    assert "FAKE-A" in text and "TypeError: b" in text


def test_the_group_check_catches_a_raw_sub_exception_mutant(monkeypatch):
    """Non-vacuity of the check above (verifier mutant, 2026-10-23): a
    _render_group that renders each sub-exception RAW forges the line
    "  | FAKE-A" behind the group's box prefix. _assert_clean must refuse
    it - a bare startswith("FAKE") did not."""
    import traceback

    from core import log_scrub

    def _raw_render_group(group, _seen, _depth):
        out = []
        for i, sub in enumerate(group.exceptions, 1):
            out.append(f"  +---------------- {i} ----------------\n")
            body = "".join(traceback.format_exception(sub))
            out.extend(f"  | {line}\n"
                       for line in body.rstrip("\n").split("\n"))
        return out

    monkeypatch.setattr(log_scrub, "_render_group", _raw_render_group)
    text = log_scrub.scrub_traceback(_group())
    assert "  | FAKE-A" in text                       # the mutant forges it
    with pytest.raises(AssertionError):
        _assert_clean(text, multiline=True)


def test_scrub_filter_scrubs_message_and_traceback():
    from core.log_scrub import install_scrub_filter
    lg = logging.getLogger("rm811b.filter.probe")
    install_scrub_filter(lg)
    install_scrub_filter(lg)                     # idempotent
    assert sum(type(f).__name__ == "ScrubFilter" for f in lg.filters) == 1
    with _captured(lg.name) as cap:
        lg.warning("msg %s", _EVIL)
        try:
            raise ValueError(_EVIL)
        except ValueError:
            lg.warning("boom %s", "x", exc_info=True)
            lg.exception("boom2")
    texts = cap.texts()
    assert len(texts) == 3
    for t in texts:
        _assert_clean(t, multiline=True)
    assert "INJECTED" in texts[0]
    assert "Traceback (most recent call last):" in texts[1]
    assert "Traceback (most recent call last):" in texts[2]
    assert "INJECTED" in texts[1] and "INJECTED" in texts[2]


def test_scrub_filter_leaves_a_benign_record_alone():
    """Negative control: no control character, no rewrite - msg and args
    reach the handler exactly as logged (a Windows path keeps its single
    backslashes)."""
    from core.log_scrub import install_scrub_filter
    lg = logging.getLogger("rm811b.filter.benign")
    install_scrub_filter(lg)
    with _captured(lg.name) as cap:
        lg.warning("read %s: %d rows", "E:\\data\\x.json", 5)
    (rec,) = cap.records
    assert rec.msg == "read %s: %d rows" and rec.args == ("E:\\data\\x.json", 5)
    assert rec.getMessage() == "read E:\\data\\x.json: 5 rows"


# -- 1. the match-DB MCP server: the traceback path -------------------------

@pytest.fixture
def matchdb_mod():
    import tools.ds_matchdb_mcp_server as mod
    return mod


def test_matchdb_tool_traceback_is_scrubbed(matchdb_mod, monkeypatch):
    mod = matchdb_mod

    def rm811b_boom():
        raise ValueError(_EVIL)

    monkeypatch.setitem(mod.TOOL_FUNCS, "rm811b_boom", rm811b_boom)
    with _captured("ds-matchdb-mcp") as cap:
        out = mod.handle_tools_call({"name": "rm811b_boom", "arguments": {}})
    assert out.get("isError") and "INJECTED" not in json.dumps(out), out
    texts = [t for t in cap.texts() if "raised" in t]
    assert texts, cap.texts()
    for t in texts:
        _assert_clean(t, multiline=True)
    joined = "\n".join(texts)
    assert "Traceback (most recent call last):" in joined   # still useful
    assert "in rm811b_boom" in joined and "INJECTED" in joined


def test_matchdb_ds_health_failure_log_is_scrubbed(matchdb_mod, monkeypatch):
    mod = matchdb_mod
    monkeypatch.setattr(mod, "_is_engine_up", lambda timeout=1.0: True)

    def _bad_urlopen(*_a, **_k):
        raise OSError(_EVIL)

    monkeypatch.setattr(mod, "urlopen", _bad_urlopen)
    with _captured("ds-matchdb-mcp") as cap:
        out = mod.tool_ds_health()
    assert out["health_error"] == "OSError"
    msgs = [r.getMessage() for r in cap.records if "health" in r.getMessage()]
    assert msgs and any("INJECTED" in m for m in msgs), msgs
    for m in msgs:
        _assert_clean(m)


@pytest.fixture
def matchdb(matchdb_mod):
    mod = matchdb_mod
    srv = mod._MatchDBHTTPServer((_HOST, 0), mod._Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv.server_address[1], mod
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)


def _raw(port: int, payload: bytes) -> bytes:
    buf = b""
    with socket.create_connection((_HOST, port), timeout=8) as s:
        s.sendall(payload)
        while True:
            try:
                chunk = s.recv(65536)
            except (ConnectionResetError, ConnectionAbortedError):
                break
            if not chunk:
                break
            buf += chunk
    return buf


def _rpc(port: int, mod, body: bytes) -> tuple[int, dict | None]:
    reply = _raw(port, b"POST /mcp HTTP/1.0\r\nHost: 127.0.0.1\r\n"
                 b"Authorization: Bearer " + mod.AUTH_TOKEN.encode() + b"\r\n"
                 b"Content-Type: application/json\r\n"
                 b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n"
                 + body)
    head, _, payload = reply.partition(b"\r\n\r\n")
    status = int(head.split(b"\r\n", 1)[0].split(b" ")[1])
    return status, (json.loads(payload) if payload else None)


# 1e400 / -1e400 are valid JSON that both parsers read as +/-infinity
# (verifier, 2026-10-23: JSON.parse('{"id":1e400}').id is Infinity).
_BAD_IDS = ['{"o":1}', "[1]", "[]", "{}", "true", "false", "NaN", "Infinity",
            "1e400", "-1e400"]
_BAD_ID_NAMES = ["object", "array", "empty-array", "empty-object", "true",
                 "false", "nan", "infinity", "1e400", "neg-1e400"]


@pytest.mark.parametrize("rid", _BAD_IDS, ids=_BAD_ID_NAMES)
@pytest.mark.parametrize("method", ["ping", "tools/list", "nope",
                                    "notifications/x"])
def test_matchdb_bad_id_is_invalid_request(matchdb, rid, method):
    port, mod = matchdb
    status, reply = _rpc(port, mod, (
        '{"jsonrpc":"2.0","id":' + rid + ',"method":"' + method + '"}'
    ).encode())
    assert status == 200
    assert reply == {"jsonrpc": "2.0", "id": None,
                     "error": {"code": -32600, "message": "Invalid Request"}}


@pytest.mark.parametrize("rid,want", [('"s"', "s"), ("0", 0), ("7", 7),
                                      ("1.5", 1.5), ("-3", -3),
                                      ("null", None)],
                         ids=["string", "zero", "int", "float", "negative",
                              "null"])
def test_matchdb_string_number_or_null_id_still_answers(matchdb, rid, want):
    """Negative control: every id JSON-RPC 2.0 allows is echoed."""
    port, mod = matchdb
    status, reply = _rpc(port, mod, (
        '{"jsonrpc":"2.0","id":' + rid + ',"method":"ping"}').encode())
    assert status == 200 and reply == {"jsonrpc": "2.0", "id": want,
                                       "result": {}}


# -- 3. the stdio usage MCP server: the id type ------------------------------

needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")
_PING = '{"jsonrpc":"2.0","id":99,"method":"ping"}'


def _usage(*lines: str, timeout: float = 30.0) -> tuple[int, list[dict], str]:
    env = dict(os.environ)
    env.pop("ANTHROPIC_USAGE_KEY", None)      # no key: nothing could be sent
    proc = subprocess.run(
        [NODE, str(USAGE_JS)], input="".join(f"{ln}\n" for ln in lines),
        capture_output=True, text=True, encoding="utf-8", timeout=timeout,
        cwd=str(ROOT), env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    replies = [json.loads(ln) for ln in proc.stdout.splitlines() if ln.strip()]
    return proc.returncode, replies, proc.stderr


@needs_node
@pytest.mark.parametrize("rid", ['{"o":1}', "[1]", "[]", "{}", "true", "false",
                                 "1e400", "-1e400"],
                         ids=["object", "array", "empty-array", "empty-object",
                              "true", "false", "1e400", "neg-1e400"])
@pytest.mark.parametrize("method", ["ping", "tools/list", "initialize",
                                    "tools/call", "nope",
                                    "notifications/initialized", "7"])
def test_usage_bad_id_is_invalid_request(rid, method):
    m = method if method == "7" else f'"{method}"'
    code, replies, stderr = _usage(
        '{"jsonrpc":"2.0","id":' + rid + ',"method":' + m
        + ',"params":{"name":"no_such_tool","arguments":{}}}', _PING)
    assert code == 0, stderr[-400:]
    assert replies[0] == {"jsonrpc": "2.0", "id": None,
                          "error": {"code": -32600,
                                    "message": "Invalid Request"}}, replies
    assert replies[1:] == [{"jsonrpc": "2.0", "id": 99, "result": {}}], replies


@needs_node
@pytest.mark.parametrize("rid,want", [('"s"', "s"), ("0", 0), ("7", 7),
                                      ("1.5", 1.5), ("null", None)],
                         ids=["string", "zero", "int", "float", "null"])
def test_usage_string_number_or_null_id_still_answers(rid, want):
    code, replies, _ = _usage('{"jsonrpc":"2.0","id":' + rid
                              + ',"method":"ping"}')
    assert code == 0
    assert replies == [{"jsonrpc": "2.0", "id": want, "result": {}}], replies


# -- 2. the Mission Control loop routes --------------------------------------

class _FakeH:
    def __init__(self) -> None:
        self.sent: list[tuple[int, bytes, str]] = []

    def _send(self, code, body, ctype="application/json"):
        self.sent.append((code, body, ctype))


def _assert_route_logs_clean(cap: _Cap) -> None:
    msgs = [r.getMessage() for r in cap.records if r.levelno >= logging.WARNING]
    assert msgs and any("INJECTED" in m for m in msgs), msgs
    for t in cap.texts():
        _assert_clean(t)


def test_loop_control_steer_oserror_log_is_scrubbed(monkeypatch):
    from dashboard import routes_loop_control as rlc

    def _append(*_a, **_k):
        raise OSError(_EVIL)

    fake = types.SimpleNamespace(TIERS=("note", "steer"), append=_append)
    monkeypatch.setitem(sys.modules, rlc._STEER_MODULE, fake)
    with _captured("rc.web_dashboard") as cap:
        status, _payload = rlc._steer({"text": "x", "tier": "note"}, "k1")
    assert status == 503
    _assert_route_logs_clean(cap)


def test_loop_control_steer_mutex_timeout_log_is_scrubbed(monkeypatch):
    from dashboard import routes_loop_control as rlc

    class MutexTimeout(RuntimeError):
        pass

    def _append(*_a, **_k):
        raise MutexTimeout(_EVIL)

    fake = types.SimpleNamespace(TIERS=("note", "steer"), append=_append)
    monkeypatch.setitem(sys.modules, rlc._STEER_MODULE, fake)
    with _captured("rc.web_dashboard") as cap:
        status, payload = rlc._steer({"text": "x", "tier": "note"}, "k2")
    assert status == 503 and "INJECTED" not in json.dumps(payload)
    _assert_route_logs_clean(cap)


@pytest.mark.parametrize("which", ["preview", "execute"])
def test_loop_control_interrupt_log_is_scrubbed(monkeypatch, which):
    from dashboard import routes_loop_control as rlc

    def _raise(*_a, **_k):
        raise RuntimeError(_EVIL)

    fake = types.SimpleNamespace(preview=_raise, execute=_raise)
    monkeypatch.setitem(sys.modules, rlc._INTERRUPT_MODULE, fake)
    with _captured("rc.web_dashboard") as cap:
        if which == "preview":
            status, _ = rlc._interrupt_preview()
        else:
            status, _ = rlc._do_interrupt({"fingerprint": "fp"}, "k3")
    assert status == 503
    _assert_route_logs_clean(cap)


@pytest.mark.parametrize("exc_type", [PermissionError, ValueError],
                         ids=["control-file-busy", "last-resort"])
def test_loop_control_guard_and_send_error_logs_are_scrubbed(monkeypatch,
                                                              exc_type):
    from dashboard import routes_loop_control as rlc

    def _route(*_a, **_k):
        raise exc_type(_EVIL)

    monkeypatch.setattr(rlc, "route_action", _route)
    h = _FakeH()
    with _captured("rc.web_dashboard") as cap:
        rlc._serve_loop_control(h, {"action": "x"})
    assert h.sent and b"INJECTED" not in h.sent[0][1]
    _assert_route_logs_clean(cap)
    # Two lines: the route's own and send_error's.
    assert sum("INJECTED" in r.getMessage() for r in cap.records) == 2


def test_loop_status_guard_and_send_error_logs_are_scrubbed(monkeypatch):
    from dashboard import routes_loop_status as rls

    def _boom():
        raise RuntimeError(_EVIL)

    monkeypatch.setattr(rls, "build_loop_status", _boom)
    h = _FakeH()
    with _captured("rc.web_dashboard") as cap:
        rls._serve_loop_status(h)
    assert h.sent and h.sent[0][0] == 500
    _assert_route_logs_clean(cap)
    assert sum("INJECTED" in r.getMessage() for r in cap.records) == 2


def test_loop_status_seams_log_scrubbed(monkeypatch):
    from dashboard import routes_loop_status as rls

    def _raise(*_a, **_k):
        raise RuntimeError(_EVIL)

    fake = types.SimpleNamespace(summary=_raise, lane_state=_raise)
    monkeypatch.setitem(sys.modules, rls._STEER_MODULE, fake)
    monkeypatch.setitem(sys.modules, rls._LANES_MODULE, fake)
    with _captured("rc.web_dashboard") as cap:
        assert rls._steer_summary() is None
        assert rls._lane_lock() is None
    _assert_route_logs_clean(cap)
    assert sum("INJECTED" in r.getMessage() for r in cap.records) == 2


# -- the sweep: per-site where named, a filter on every logger ---------------

_PER_SITE = [
    "dashboard/routes_loop_control.py",
    "dashboard/routes_loop_status.py",
    "dashboard/_errors.py",
    "mc/handler.py",
    "mc/server.py",
    "tools/ds_matchdb_mcp_server.py",
]
_LEVELS = {"debug", "info", "warning", "warn", "error", "exception",
           "critical", "log"}
_SCRUBBERS = {"scrub_log", "_scrub_log", "scrub_controls"}
_EXC_NAMES = {"exc", "e", "err", "error", "ex", "exception"}
_REQUEST_ATTRS = {"path", "headers", "requestline", "raw_requestline"}


def _unscrubbed_args(src: str) -> list[str]:
    """Every log-call argument that carries an exception (a name bound by
    ``except ... as`` or a conventional exception name) or request text
    (``.path`` / ``.headers`` / ``.requestline``) without a scrubber
    around it. ``type(exc).__name__`` is server text and allowed."""
    tree = ast.parse(src)
    bound = {h.name for h in ast.walk(tree)
             if isinstance(h, ast.ExceptHandler) and h.name}
    names = bound | _EXC_NAMES
    bad: list[str] = []

    def _tainted(node) -> bool:
        if (isinstance(node, ast.Attribute) and node.attr == "__name__"
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "type"):
            return False
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in _SCRUBBERS):
            return False
        if isinstance(node, ast.Name) and node.id in names:
            return True
        if isinstance(node, ast.Attribute) and node.attr in _REQUEST_ATTRS:
            return True
        return any(_tainted(c) for c in ast.iter_child_nodes(node))

    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr in _LEVELS
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id in {"log", "_log", "logger", "LOG"}):
            continue
        for a in n.args:
            if _tainted(a):
                bad.append(f"{n.lineno}: {ast.get_source_segment(src, a)}")
    return bad


@pytest.mark.parametrize("rel", _PER_SITE)
def test_named_modules_scrub_every_exception_at_the_call_site(rel):
    src = (ROOT / rel).read_text(encoding="utf-8")
    assert "log." in src or "_log." in src     # the walk has something to see
    assert _unscrubbed_args(src) == [], rel


def test_the_per_site_detector_is_not_vacuous():
    """The detector above flags the measured pre-fix shapes."""
    src = (
        "try:\n    pass\nexcept Exception as exc:\n"
        "    log.warning('a: %s', exc)\n"
        "    log.warning('b: %s', str(exc))\n"
        "    log.warning('c: %s', f'{exc!r}')\n"
        "    log.warning('d %s', h.path)\n"
        "    log.warning('ok %s %s', type(exc).__name__, scrub_log(str(exc)))\n"
        "def send_error(h, exc):\n    log.warning('%s', exc)\n"
    )
    assert sorted(int(b.split(":")[0]) for b in _unscrubbed_args(src)) == [
        4, 5, 6, 7, 10]


_MIN_PY_FILES = {"dashboard": 50, "mc": 4}


def _package_files(pkg: str) -> list[Path]:
    """Every tracked .py file under ``pkg``, subpackages included - the git
    index via tests/_repo_walk (ADR-015), not a one-level filesystem glob,
    so a future subpackage's logger is enumerated too. Floored so an empty
    (or shrunken) enumeration can never read as "every logger covered"."""
    from tests._repo_walk import repo_files
    files = repo_files(ROOT / pkg, ("*.py",))
    assert len(files) >= _MIN_PY_FILES[pkg], (pkg, len(files))
    assert (ROOT / pkg / "__init__.py") in files, files[:5]
    return files


def _logger_names(pkg: str) -> dict[str, str]:
    """name -> file:line for every getLogger call under ``pkg``."""
    return _logger_names_in(_package_files(pkg), ROOT)


def _logger_names_in(files: list[Path], root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in files:
        src = p.read_text(encoding="utf-8")
        rel = p.relative_to(root).with_suffix("")
        module = ".".join(rel.parts[:-1] if rel.name == "__init__"
                          else rel.parts)
        for n in ast.walk(ast.parse(src)):
            if not (isinstance(n, ast.Call) and n.args
                    and ((isinstance(n.func, ast.Attribute)
                          and n.func.attr == "getLogger")
                         or (isinstance(n.func, ast.Name)
                             and n.func.id == "getLogger"))):
                continue
            arg = n.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                name = arg.value
            elif isinstance(arg, ast.Name) and arg.id == "__name__":
                name = module
            else:
                raise AssertionError(f"{rel}:{n.lineno}: a getLogger name "
                                     "this guard cannot resolve")
            out.setdefault(name, f"{rel.as_posix()}:{n.lineno}")
    return out


def test_logger_enumeration_reaches_a_subpackage(tmp_path):
    """A nested file is walked and named by its dotted module path: the
    one-level glob this replaced never saw ``pkgx/sub/*.py``."""
    from tests._repo_walk import repo_files
    sub = tmp_path / "pkgx" / "sub"
    sub.mkdir(parents=True)
    (tmp_path / "pkgx" / "__init__.py").write_text(
        "import logging\nlog = logging.getLogger(__name__)\n", encoding="utf-8")
    (sub / "__init__.py").write_text("", encoding="utf-8")
    (sub / "mod.py").write_text(
        "import logging\nA = logging.getLogger(__name__)\n"
        "B = logging.getLogger('rc.nested_name')\n", encoding="utf-8")
    files = repo_files(tmp_path / "pkgx", ("*.py",), tracked_only=False)
    names = _logger_names_in(files, tmp_path)
    assert set(names) == {"pkgx", "pkgx.sub.mod", "rc.nested_name"}, names


@pytest.mark.parametrize("pkg", ["dashboard", "mc"])
def test_every_package_logger_carries_the_scrub_filter(pkg):
    import importlib
    importlib.import_module(pkg)
    names = _logger_names(pkg)
    assert len(names) >= (5 if pkg == "dashboard" else 2), names
    from core.log_scrub import ScrubFilter
    missing = {n: where for n, where in names.items()
               if not any(isinstance(f, ScrubFilter)
                          for f in logging.getLogger(n).filters)}
    assert missing == {}, missing
    for name in names:
        with _captured(name) as cap:
            logging.getLogger(name).warning("probe %s", _EVIL)
        (text,) = cap.texts()
        _assert_clean(text)
        assert "INJECTED" in text


def test_the_match_db_logger_carries_the_scrub_filter(matchdb_mod):
    from core.log_scrub import ScrubFilter
    assert any(isinstance(f, ScrubFilter) for f in matchdb_mod.log.filters)


def test_a_dashboard_route_outside_the_named_set_logs_scrubbed(monkeypatch):
    """The backstop on a real route with no per-site scrub:
    routes_static._serve_web_asset logs ``h.path`` (the client's target)
    and the exception text; the logger filter keeps the line single."""
    from dashboard import routes_static as rs

    class _BadRoot:
        def __truediv__(self, _other):
            raise OSError(_EVIL)

    monkeypatch.setattr(rs, "APP_DIR", _BadRoot())
    h = _FakeH()
    h.path = "/css/x\x1b[31m\nFAKE-TARGET.css"
    with _captured("rc.web_dashboard") as cap:
        rs._serve_web_asset(h)
    assert h.sent and h.sent[0][0] == 500
    (text,) = cap.texts()
    _assert_clean(text)
    assert "INJECTED" in text and "FAKE-TARGET" in text


def test_mc_import_probe_still_reaches_no_game_code():
    """dashboard/__init__ now imports core.log_scrub: still nothing that the
    S10 guard forbids (pydantic, the dashboard Handler, game routes)."""
    code = (
        "import sys, mc.routes\n"
        "bad = [m for m in ('pydantic', 'dashboard._handler', "
        "'dashboard._dispatch', 'dashboard.routes_state', 'web_dashboard') "
        "if m in sys.modules]\n"
        "print(bad)\nsys.exit(1 if bad else 0)\n")
    proc = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT),
                          capture_output=True, text=True, timeout=60,
                          creationflags=getattr(subprocess,
                                                "CREATE_NO_WINDOW", 0))
    assert proc.returncode == 0, proc.stdout + proc.stderr
