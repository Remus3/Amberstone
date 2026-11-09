"""S144-P-333 - the only production listener bound to every interface is the dashboard's deliberate `HOST = "::"`.

ADR-011 makes every RC server local-only; `core/port_handoff.py` and `agents/daemon_slayer/cli.py` say so, and
`vision_server/__init__.py` records the 0.0.0.0 bind it dropped. Each server has its own bind test, but nothing
looked across the whole tree for a NEW wildcard bind, and ruff S104 only matches the literal "0.0.0.0" (not "::",
not an empty host, not `host=""`). Measured 2026-11-07 over every tracked non-test `.py` (vendored kit included): one
site, `dashboard/server.py` `HOST = "::"` - the dual-stack default the tailnet and LAN viewers depend on, whose
live value is `bind_host()` (PKG-5). This pins that set exactly (it only shrinks), so a second wildcard bind, or
a wildcard default copied into an argparse flag, fails here with the file and the bound name.

Detector (AST, so a docstring, comment or `split("::")` separator never counts). A string constant that is a
wildcard host (`""`, `0.0.0.0`, `::`, `0:0:0:0:0:0:0:0`, `[::]`, `::0`) is a bind site only in a binding context:
- assigned to a name that says where to listen: host / addr / bind* / listen*, with an optional word either side
  (`HOST = "::"`, `self.bind_host = ""`; `hostname` is not one);
- passed as a keyword with such a name (`serve(host="0.0.0.0")`);
- the first element of the address tuple given to a server or `bind` call (`HTTPServer(("", 80), H)`), or a
  positional host of `start_server` / `serve` / `run` / `TCPSite` (`uvicorn.run(app, "::")`);
- a wildcard reachable through `x or "::"`, `a if b else "0.0.0.0"` or `environ.get(NAME, "0.0.0.0")` in those
  contexts, or as the value of a `"host"` / `"bind"` key in a dict literal (the EMPTY string is ignored there:
  `parsed.hostname or ""` and `{"host": ""}` are "no value" records, three production sites each);
- the default of a parameter with such a name, or the `default=` of an argparse `--host`-style option.
A comparison (`host in ("", "::")`), a membership list and a message are not binding contexts.

A bare `host = ""` / `def f(host="")` IS flagged on purpose (an empty host in a binding context is the wildcard);
none exists in production today.

Known blind spots (measured by the verifier, none present in the tree today, so this is a census and not a proof):
a tuple-unpacking assignment (`HOST, PORT = "0.0.0.0", 80`), an address tuple held in a variable and passed on
(`addr = ("", 9); s.bind(addr)`), a subprocess argv (`["uvicorn", "--host", "0.0.0.0"]`), a host inside a URL
string, and `environ.get(NAME, default="::")` with the default as a keyword. The per-server bind tests
(tests/test_phase3_bind_loopback_rm231.py, tests/test_vision_server_bind_rm150.py, ...) still own each server.

Scope: tracked non-test `.py` (a `tests/` path, `test_*.py` and `conftest.py` are skipped: they assert on the
wildcard values). Nothing else is grandfathered. Positive controls below run the detector on one source per shape.
"""
from __future__ import annotations

import ast
import re

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_WILDCARDS = {"", "0.0.0.0", "::", "0:0:0:0:0:0:0:0", "[::]", "::0"}
# a name that says WHERE to listen: host, bind_host, host_bind, listen_addr, address ... ("hostname" is not one).
_NAME = re.compile(r"(?:\w*_)?(?:host|addr|address|bind\w*|listen\w*)(?:_\w+)?", re.IGNORECASE)
# Calls that take the host as a plain positional argument (asyncio / uvicorn / websockets / aiohttp spellings).
_HOST_POSITIONAL_CALLS = {"start_server", "create_server", "serve", "TCPSite", "run", "create_datagram_endpoint"}
_SERVER_CALLS = {
    "HTTPServer", "ThreadingHTTPServer", "TCPServer", "ThreadingTCPServer", "UDPServer", "ThreadingUDPServer",
    "bind",
}

# (relpath, bound name) -> why a wildcard bind is deliberate. Only shrinks.
SANCTIONED = {
    ("dashboard/server.py", "HOST"): (
        "the dual-stack default: '::' with IPV6_V6ONLY=0 answers IPv4 and IPv6 for the tailnet and LAN viewers; the "
        "live bind is bind_host() (RC_DASH_BIND, LOOPBACK_BIND for the packaged launcher)"
    ),
}


def _is_wildcard(node: ast.AST | None, *, empty_ok: bool = True) -> bool:
    """A wildcard host constant, or an expression that can evaluate to one (`or "::"`, `a if b else "0.0.0.0"`, an
    `environ.get(NAME, "::")` / `getenv` default). Inside such an expression the EMPTY string is not counted:
    `parsed.hostname or ""` is the ubiquitous "no value" fallback, not a bind (three production sites)."""
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, str):
            return False
        text = node.value.strip()
        return text in _WILDCARDS and (empty_ok or text != "")
    if isinstance(node, ast.BoolOp):
        return any(_is_wildcard(v, empty_ok=False) for v in node.values)
    if isinstance(node, ast.IfExp):
        return _is_wildcard(node.body, empty_ok=False) or _is_wildcard(node.orelse, empty_ok=False)
    if isinstance(node, ast.Call) and _callee(node) in {"get", "getenv"} and len(node.args) >= 2:
        return _is_wildcard(node.args[-1], empty_ok=False)
    return False


def _target_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Attribute):
        return [target.attr]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [n for elt in target.elts for n in _target_names(elt)]
    return []


def _callee(call: ast.Call) -> str:
    func = call.func
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")


def _scan(source: str) -> list[tuple[int, str]]:
    """(line, name) of every wildcard host in a binding context; `name` is the variable or call it binds."""
    tree = ast.parse(source)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _is_wildcard(node.value):
            found.extend((node.lineno, n) for t in node.targets for n in _target_names(t) if _NAME.fullmatch(n))
        elif isinstance(node, ast.AnnAssign) and _is_wildcard(node.value):
            found.extend((node.lineno, n) for n in _target_names(node.target) if _NAME.fullmatch(n))
        elif isinstance(node, ast.Call):
            callee = _callee(node)
            for kw in node.keywords:
                if kw.arg and _NAME.fullmatch(kw.arg) and _is_wildcard(kw.value):
                    found.append((node.lineno, kw.arg))
            addr = node.args[0] if node.args else next(
                (k.value for k in node.keywords if k.arg == "server_address"), None)
            if callee in _SERVER_CALLS and isinstance(addr, ast.Tuple) and addr.elts and _is_wildcard(addr.elts[0]):
                found.append((node.lineno, callee))
            if callee in _HOST_POSITIONAL_CALLS and any(
                    isinstance(a, ast.Constant) and _is_wildcard(a) for a in node.args[:3]):
                found.append((node.lineno, callee))
            if callee == "add_argument" and node.args and _is_wildcard(
                    next((k.value for k in node.keywords if k.arg == "default"), None)):
                flags = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
                if any(_NAME.fullmatch(f.lstrip("-").replace("-", "_")) for f in flags):
                    found.append((node.lineno, flags[0]))
        elif isinstance(node, ast.Dict):
            found.extend((k.lineno, k.value) for k, v in zip(node.keys, node.values)
                         if isinstance(k, ast.Constant) and isinstance(k.value, str)
                         and _NAME.fullmatch(k.value) and _is_wildcard(v, empty_ok=False))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            args = node.args
            positional = [*args.posonlyargs, *args.args]
            pairs = list(zip(positional[len(positional) - len(args.defaults):], args.defaults))
            pairs += [(a, d) for a, d in zip(args.kwonlyargs, args.kw_defaults) if d is not None]
            found.extend((d.lineno, a.arg) for a, d in pairs if _NAME.fullmatch(a.arg) and _is_wildcard(d))
    return sorted(set(found))


def _is_test_path(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return rel.startswith("tests/") or "/tests/" in rel or name.startswith("test_") or name == "conftest.py"


def test_the_dashboard_default_is_the_only_wildcard_bind_in_production():
    files = repo_files(REPO_ROOT, ("*.py",))
    assert len(files) > 100, "the tracked-file walk returned almost nothing"
    seen = 0
    sites: set[tuple[str, str]] = set()
    for p in files:
        rel = relative_posix(p)
        if _is_test_path(rel):
            continue
        try:
            found = _scan(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        seen += 1
        sites.update((rel, name) for _line, name in found)
    assert seen > 100, "the parse walk returned almost nothing"
    assert sites == set(SANCTIONED), (
        f"wildcard-bind sites changed (ADR-011: RC servers are local-only). new: {sorted(sites - set(SANCTIONED))}; "
        f"gone (drop from SANCTIONED): {sorted(set(SANCTIONED) - sites)}"
    )


def test_every_sanctioned_site_carries_a_reason_and_is_tracked():
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    for (rel, name), why in SANCTIONED.items():
        assert rel in tracked, rel
        assert len(why) > 40 and name, (rel, name)


def test_the_detector_sees_each_binding_shape():
    cases = {
        'HOST = "::"\n': [(1, "HOST")],
        'self.bind_host = ""\n': [(1, "bind_host")],
        'LISTEN: str = "0.0.0.0"\n': [(1, "LISTEN")],
        'serve(host="0.0.0.0")\n': [(1, "host")],
        'srv = HTTPServer(("", 80), H)\n': [(1, "HTTPServer")],
        'sock.bind(("0.0.0.0", 9))\n': [(1, "bind")],
        'ap.add_argument("--host", default="")\n': [(1, "--host")],
        'def run(host="::"):\n    pass\n': [(1, "host")],
        'def run(*, bind_addr="0:0:0:0:0:0:0:0"):\n    pass\n': [(1, "bind_addr")],
        'f = lambda listen="[::]": listen\n': [(1, "listen")],
    }
    for src, want in cases.items():
        assert _scan(src) == want, src


def test_a_loopback_bind_a_comparison_a_separator_and_a_message_are_not_flagged():
    clean = (
        'HOST = "127.0.0.1"\n'
        'srv = HTTPServer(("127.0.0.1", 80), H)\n'
        'sock.bind((host, 9))\n'
        'serve(host="::1")\n'
        'if host in ("", "::"):\n    pass\n'
        'parts = raw.split("::")\n'
        'SEP = "::"\n'
        'name = ""\n'
        'hostname = ""\n'
        'self.hostname = "0.0.0.0"\n'
        'ap.add_argument("--port", default="")\n'
        'ap.add_argument("--host", default="127.0.0.1")\n'
        'def run(host="localhost", label=""):\n    pass\n'
        '"""HOST = "::" in a docstring"""\n'
        '# HOST = "::"\n'
    )
    assert _scan(clean) == []


def test_the_walk_skips_test_code_by_path():
    for rel, want in {"tests/test_x.py": True, "agents/daemon_slayer/tests/t.py": True, "tests/conftest.py": True,
                      "dashboard/server.py": False, "core/test_helper_free.py": True,
                      "vision_server/_http.py": False}.items():
        assert _is_test_path(rel) is want, rel
