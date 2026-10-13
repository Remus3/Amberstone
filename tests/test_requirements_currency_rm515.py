"""RM-515: Python dependency currency, and the rule that decides what is pinned.

Decision (self-adjudicated, 2026-10-03): requirements.txt pins what RC's OWN
tracked source imports, exactly (`==`). `requests` / `urllib3` / `cryptography`
are NOT RC dependencies - measured, no tracked .py imports them; on Legion they
arrive with unrelated user tools (gallery_dl, mitmproxy) - so pinning them here
would freeze somebody else's environment and protect nothing RC runs. The
guard below makes that decision re-checkable: the day RC imports one of them,
it must be pinned in the same change.

certifi IS used (lib/http/client.py) and its CA bundle is security-relevant,
so it is kept current. anthropic 0.x -> 1.x and websockets 16 -> 17 are
MAJORS and stay pinned until evaluated (not done in this slice).

Amendment (session 111 merger, 2026-10-12, self-adjudicated): a module under
a `tests/` directory that loads one of these ONLY behind
`pytest.importorskip("<pkg>")` adds no RC dependency - it skips wherever the
package is absent (CI has no cryptography) - so it is exempt. First case:
`tests/test_mc_server_tls_accept_rm739.py` builds a throwaway self-signed
cert with cryptography. Alternatives rejected: pinning cryptography (freezes
the user-tool environment this decision protects, and regenerates the hashed
CI requirement sets for a test that skips there); a committed test key pair
(a PEM private key in a public tree is what tools/credential_patterns.py
`private_key_pem` exists to stop); an `openssl` subprocess (an unpinned host
tool, the same problem one level down); moving the cert test somewhere the
guard does not look (it hides the import instead of proving it optional, and
the guard's whole job is to see every tracked import). Reverses if: non-test
RC code imports one of these, or a test imports one without the importorskip
(both still fail - pinned by test_the_optional_test_import_exemption_is_narrow
and the two parametrized shape tests below it).

RM-515 AST rule (verifier finding on 8d2496a58, self-adjudicated): the first
cut matched the importorskip TEXT, so one in a comment, string or docstring,
or one that ran only AFTER a top-level import, exempted the import. The
exemption is now decided on the parsed module: a tests/ module is exempt for
package P only when it parses, holds at least one real skip statement for P,
and EVERY real `import P...` / `from P... import` in it is preceded by one in
its own statement block or an enclosing block (so the skip has run before the
import can). A skip statement is an expression or assignment statement whose
whole value is a call of `pytest.importorskip` (or of a name bound by
`from pytest import importorskip`) with first argument (or `modname=`) a
string literal equal to P or to P.<submodule>. Anything else stays a hit: a
skip nested inside another expression (`FLAG and pytest.importorskip(...)`
can short-circuit), a skip in a sibling function or inside an `if` the import
is not in, an unparseable module. Alternatives rejected: a stricter regex
(still cannot tell code from comments and strings, or order across scopes);
per-import-line exemption (the per-module all-or-nothing rule is simpler and
never weaker).
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path, PurePosixPath

import pytest

ROOT = Path(__file__).resolve().parent.parent
REQ = ROOT / "requirements.txt"

UNPINNED_BY_DECISION = ("requests", "urllib3", "cryptography")


def _pins() -> dict[str, str]:
    pins = {}
    for line in REQ.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        name, sep, ver = line.partition("==")
        assert sep, f"requirements.txt line is not an exact pin: {line!r}"
        pins[name.strip().lower()] = ver.strip()
    return pins


def _tracked_py() -> list[Path]:
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "*.py"],
                         capture_output=True, text=True, check=True).stdout
    files = [ROOT / p for p in out.split("\0") if p]
    assert len(files) > 100, "vacuous enumeration - the git index read failed"
    return files


def test_every_requirement_is_an_exact_pin():
    assert _pins()


def test_certifi_is_current_enough():
    year, month, _ = (int(x) for x in _pins()["certifi"].split("."))
    assert (year, month) >= (2026, 7), "certifi CA bundle pin went stale"


_IMPORT = re.compile(
    r"^\s*(?:import|from)\s+(" + "|".join(UNPINNED_BY_DECISION) + r")\b", re.M)


def _names_pkg(name: str | None, pkg: str) -> bool:
    return bool(name) and (name == pkg or name.startswith(pkg + "."))


def _is_skip_stmt(stmt: ast.stmt, pkg: str, bare_names: set[str]) -> bool:
    """A statement whose whole value is a real ``importorskip`` call for pkg
    (``pytest.importorskip("pkg")``, ``x = pytest.importorskip("pkg.sub")``,
    or a bare ``importorskip(...)`` bound by ``from pytest import``)."""
    if not isinstance(stmt, (ast.Expr, ast.Assign, ast.AnnAssign)):
        return False
    call = stmt.value
    if not isinstance(call, ast.Call):
        return False
    func = call.func
    if isinstance(func, ast.Attribute):
        if not (func.attr == "importorskip" and isinstance(func.value, ast.Name)
                and func.value.id == "pytest"):
            return False
    elif not (isinstance(func, ast.Name) and func.id in bare_names):
        return False
    if call.args:
        arg = call.args[0]
    else:
        arg = next((k.value for k in call.keywords if k.arg == "modname"), None)
    return isinstance(arg, ast.Constant) and isinstance(arg.value, str) and _names_pkg(arg.value, pkg)


def _stmt_lists(node: ast.AST):
    """Every statement block directly owned by node (body / orelse /
    finalbody / handler and match-case bodies)."""
    for _field, value in ast.iter_fields(node):
        if not isinstance(value, list) or not value:
            continue
        if all(isinstance(v, ast.stmt) for v in value):
            yield value
            continue
        for v in value:
            if isinstance(v, (ast.excepthandler, ast.match_case)):
                yield from _stmt_lists(v)


def _optional_test_import(rel: str, text: str, pkg: str) -> bool:
    """True when rel is under a tests/ directory and every real import of pkg
    in it runs only after a real ``pytest.importorskip("pkg")`` (see the
    session 111 amendment and its RM-515 AST rule above)."""
    if "tests" not in PurePosixPath(rel.replace("\\", "/")).parts[:-1]:
        return False
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return False
    bare_names = {a.asname or a.name for n in ast.walk(tree)
                  if isinstance(n, ast.ImportFrom) and n.module == "pytest" and not n.level
                  for a in n.names if a.name == "importorskip"}
    imports_guarded: list[bool] = []
    skip_seen = False

    def walk(block: list[ast.stmt], guarded: bool) -> None:
        nonlocal skip_seen
        for stmt in block:
            if isinstance(stmt, ast.Import):
                if any(_names_pkg(a.name, pkg) for a in stmt.names):
                    imports_guarded.append(guarded)
            elif isinstance(stmt, ast.ImportFrom):
                if not stmt.level and _names_pkg(stmt.module, pkg):
                    imports_guarded.append(guarded)
            elif _is_skip_stmt(stmt, pkg, bare_names):
                guarded = skip_seen = True
            else:
                for inner in _stmt_lists(stmt):
                    walk(inner, guarded)

    walk(tree.body, False)
    return skip_seen and all(imports_guarded)


def _unpinned_hits(files, pins) -> list[str]:
    """['<rel>: <pkg>'] for every import of an UNPINNED_BY_DECISION package in
    files ((rel, text) pairs) that requirements.txt does not pin and that is
    not an optional test-only import."""
    hits = []
    for rel, text in files:
        for m in _IMPORT.finditer(text):
            pkg = m.group(1)
            if pkg in pins or _optional_test_import(rel, text, pkg):
                continue
            hits.append(f"{rel}: {pkg}")
    return hits


def test_unpinned_transitives_are_not_imported_by_rc_source():
    files = []
    for path in _tracked_py():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        files.append((path.relative_to(ROOT).as_posix(), text))
    unpinned = _unpinned_hits(files, _pins())
    assert not unpinned, ("RC now imports a dependency requirements.txt does not "
                          f"pin - pin it in the same change: {unpinned}")


def test_the_optional_test_import_exemption_is_narrow():
    guarded = 'pytest.importorskip("cryptography")\nfrom cryptography import x509\n'
    bare = "from cryptography import x509\n"
    assert _unpinned_hits([("tests/test_x.py", guarded)], {}) == []
    assert _unpinned_hits([("agents/daemon_slayer/tests/test_x.py", guarded)], {}) == []
    # No importorskip: still a dependency.
    assert _unpinned_hits([("tests/test_x.py", bare)], {}) == ["tests/test_x.py: cryptography"]
    # Outside a tests/ directory the importorskip does not exempt it.
    assert _unpinned_hits([("mc/server.py", guarded)], {}) == ["mc/server.py: cryptography"]
    assert _unpinned_hits([("tools/tests_helper.py", guarded)], {}) == [
        "tools/tests_helper.py: cryptography"]
    # importorskip of a DIFFERENT package does not exempt this one.
    other = 'pytest.importorskip("requests")\nimport cryptography\n'
    assert _unpinned_hits([("tests/test_x.py", other)], {}) == ["tests/test_x.py: cryptography"]
    # A pin still clears it anywhere.
    assert _unpinned_hits([("mc/server.py", bare)], {"cryptography": "46.0.0"}) == []


# Shapes that LOOK guarded but are not: the importorskip text is not a real
# call, or it does not run before the import. Each must still be a hit.
_NOT_GUARDED = {
    "skip_in_comment": '# pytest.importorskip("cryptography")\nimport cryptography\n',
    "skip_in_string": "X = 'pytest.importorskip(\"cryptography\")'\nimport cryptography\n",
    "skip_in_docstring": ('"""uses pytest.importorskip("cryptography")"""\n'
                          "from cryptography import x509\n"),
    "toplevel_import_before_skip": ('import pytest\nimport cryptography\n\n'
                                    'def test_a():\n    pytest.importorskip("cryptography")\n'),
    "toplevel_import_skip_in_later_function": ('from cryptography import x509\n\n'
                                               'def test_b():\n'
                                               '    pytest.importorskip("cryptography")\n'),
    "skip_after_import_same_function": ('def test_c():\n    import cryptography\n'
                                        '    pytest.importorskip("cryptography")\n'),
    "skip_in_sibling_function": ('def test_d():\n    pytest.importorskip("cryptography")\n\n'
                                 'def test_e():\n    import cryptography\n'),
    "skip_inside_if_import_after_it": ('if FLAG:\n    pytest.importorskip("cryptography")\n'
                                       'import cryptography\n'),
    "one_guarded_one_bare": ('def test_f():\n    pytest.importorskip("cryptography")\n'
                             '    import cryptography\n\n'
                             'def test_g():\n    import cryptography\n'),
    "skip_not_on_pytest": 'fake.importorskip("cryptography")\nimport cryptography\n',
    "skip_of_prefix_named_package": ('pytest.importorskip("cryptography_shim")\n'
                                     'import cryptography\n'),
    "skip_behind_short_circuit": ('X = FLAG and pytest.importorskip("cryptography")\n'
                                  'import cryptography\n'),
    "unparseable_module": 'pytest.importorskip("cryptography")\nimport cryptography\ndef (:\n',
}


@pytest.mark.parametrize("text", list(_NOT_GUARDED.values()), ids=list(_NOT_GUARDED))
def test_a_fake_or_late_importorskip_does_not_exempt(text):
    assert "tests/test_x.py: cryptography" in _unpinned_hits([("tests/test_x.py", text)], {})


# Shapes where a real importorskip runs before every import: exempt.
_GUARDED = {
    "rm739_helper_shape": ('def _self_signed(tmp_path):\n'
                           '    pytest.importorskip("cryptography")\n'
                           '    from cryptography import x509\n'
                           '    from cryptography.hazmat.primitives import hashes\n'),
    "module_skip_then_import_in_function": ('pytest.importorskip("cryptography")\n\n'
                                            'def test_a():\n    import cryptography\n'),
    "assigned_skip": 'crypto = pytest.importorskip("cryptography")\nfrom cryptography import x509\n',
    "from_pytest_import_importorskip": ('from pytest import importorskip\n'
                                        'importorskip("cryptography")\nimport cryptography\n'),
    "submodule_skip": 'pytest.importorskip("cryptography.x509")\nimport cryptography.x509\n',
    "skip_only_no_plain_import": ('crypto = pytest.importorskip("cryptography")\n'
                                  '"""\nimport cryptography\n"""\n'),
}


@pytest.mark.parametrize("text", list(_GUARDED.values()), ids=list(_GUARDED))
def test_a_real_importorskip_before_the_import_exempts(text):
    assert _unpinned_hits([("tests/test_x.py", text)], {}) == []


def test_the_rm739_module_is_exempt_by_shape():
    rel = "tests/test_mc_server_tls_accept_rm739.py"
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert _IMPORT.search(text), "vacuous: the RM-739 module no longer imports cryptography"
    assert _optional_test_import(rel, text, "cryptography")
