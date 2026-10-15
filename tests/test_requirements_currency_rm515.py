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
the guard's job is to see every tracked import of these packages that the
RM-741 detector rule below can see). Reverses if: non-test
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

RM-741 detector rule (session 117, self-adjudicated): the first detector was a
line-start regex, so `import os, cryptography`, `import os; import
cryptography`, `if X: import cryptography` (ruff E701 / E702 are ignored
repo-wide) and every importlib.import_module / __import__ call went unseen, in
production code and tests alike. The detector now walks the parsed module:
every `ast.Import` alias and every absolute `ast.ImportFrom` module, at any
depth, counts by its top-level name; so does the string-literal first
argument (or `name=`) of a call to `importlib.import_module`, a bare
`import_module` or `__import__`. A relative import (`from . import x`,
`from .x import y`, a literal starting with '.') names no third-party package
and never counts; text in a comment or string is not an import. A dynamic
import is never cleared by the importorskip exemption (that rule orders import
STATEMENTS only): a test that needs one uses the importorskip return value. A
module that does not parse is a hit for every unpinned package: the guard
cannot see what it imports, so it never vouches for it (measured 2026-10-15:
no tracked .py fails to parse under 3.12 or 3.14). Out of scope BY DESIGN -
deliberately disguised code, not a slip a reviewer misses: a shadowed or
rebound `pytest` / `importorskip` (it can fake the exemption), a non-literal
import_module / __import__ argument, an alias of importlib or import_module,
and an import done through exec / eval / compile or a subprocess.
Alternatives rejected: widening the regex (cannot read a comma list, a
one-liner after `;` / `:` or a call argument, and still matches strings);
counting an unparseable module only when it names a package (an
unreadable module is exactly where the guard must not vouch).
"""
from __future__ import annotations

import ast
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


def _is_dynamic_import(call: ast.Call) -> bool:
    """``importlib.import_module(...)``, a bare ``import_module(...)`` or
    ``__import__(...)``."""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id in ("import_module", "__import__")
    return (isinstance(func, ast.Attribute) and func.attr == "import_module"
            and isinstance(func.value, ast.Name) and func.value.id == "importlib")


def _imports(text: str) -> tuple[set[str], set[str]] | None:
    """(static, dynamic) top-level names of every absolute import in text, or
    None when it does not parse (see the RM-741 detector rule above).

    static: each ``import a.b, c`` alias and each ``from a.b import x``
    module, at any depth (after ``;``, behind ``if X:``, in a function).
    dynamic: the string-literal first argument (or ``name=``) of an
    _is_dynamic_import call. Relative imports (level > 0, or a literal that
    starts with '.') name no third-party package and are skipped."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    static: set[str] = set()
    dynamic: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            static.update(a.name.split(".", 1)[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if not node.level and node.module:
                static.add(node.module.split(".", 1)[0])
        elif isinstance(node, ast.Call) and _is_dynamic_import(node):
            if node.args:
                arg = node.args[0]
            else:
                arg = next((k.value for k in node.keywords if k.arg == "name"), None)
            if (isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                    and arg.value and not arg.value.startswith(".")):
                dynamic.add(arg.value.split(".", 1)[0])
    return static, dynamic


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
    """['<rel>: <pkg>'], once per file and package, for every import of an
    UNPINNED_BY_DECISION package in files ((rel, text) pairs) that
    requirements.txt does not pin and that is not an optional test-only
    import. A dynamic import is never optional; an unparseable file is a hit
    for every unpinned package (the RM-741 detector rule above)."""
    hits = []
    for rel, text in files:
        found = _imports(text)
        for pkg in UNPINNED_BY_DECISION:
            if pkg in pins:
                continue
            if found is None:
                hits.append(f"{rel}: {pkg}")
                continue
            static, dynamic = found
            if pkg in dynamic or (pkg in static and not _optional_test_import(rel, text, pkg)):
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
    found = _imports(text)
    assert found is not None, "the RM-739 module no longer parses"
    static, dynamic = found
    assert "cryptography" in static, "vacuous: the RM-739 module no longer imports cryptography"
    assert "cryptography" not in dynamic, "a dynamic import is never exempt"
    assert _optional_test_import(rel, text, "cryptography")
    assert _unpinned_hits([(rel, text)], {}) == []


# RM-741: real imports the first (line-start regex) detector never saw. Each
# must be a hit on a production path and on a tests/ path (no importorskip).
_MISSED_BY_THE_REGEX = {
    "comma_list": "import os, cryptography\n",
    "comma_list_submodule_alias": "import os.path, cryptography.x509 as x509\n",
    "semicolon_import": "import os; import cryptography\n",
    "semicolon_from": "X = 1; from cryptography import x509\n",
    "if_one_liner": "if FLAG: import cryptography\n",
    "try_one_liner": "try: import cryptography\nexcept ImportError: pass\n",
    "importlib_import_module": 'import importlib\nimportlib.import_module("cryptography")\n',
    "importlib_import_module_name_kw": ('import importlib\n'
                                        'm = importlib.import_module(name="cryptography")\n'),
    "bare_import_module_submodule": ('from importlib import import_module\n'
                                     'm = import_module("cryptography.x509")\n'),
    "dunder_import": 'm = __import__("cryptography")\n',
    "dunder_import_in_function": 'def load():\n    return __import__("cryptography")\n',
    "unparseable_comma_list": "import os, cryptography\ndef (:\n",
}


@pytest.mark.parametrize("rel", ["mc/server.py", "tests/test_x.py"], ids=["prod", "tests"])
@pytest.mark.parametrize("text", list(_MISSED_BY_THE_REGEX.values()), ids=list(_MISSED_BY_THE_REGEX))
def test_every_import_shape_is_seen_rm741(text, rel):
    assert f"{rel}: cryptography" in _unpinned_hits([(rel, text)], {})


# RM-741: text that names a package but imports no third-party one. The AST
# detector must not count it (a relative import is first-party by definition).
_NOT_AN_IMPORT = {
    "relative_from_dot": "from . import cryptography\n",
    "relative_from_dot_module": "from .cryptography import x509\n",
    "relative_from_parent": "from ..requests import get\n",
    "relative_import_module": ('import importlib\n'
                               'm = importlib.import_module(".cryptography", __package__)\n'),
    "import_in_a_string": 'X = """\nimport cryptography\n"""\n',
    "import_in_a_comment": "# import cryptography\n",
    "prefix_named_package": "import cryptography_shim\n",
}


@pytest.mark.parametrize("rel", ["mc/server.py", "tests/test_x.py"], ids=["prod", "tests"])
@pytest.mark.parametrize("text", list(_NOT_AN_IMPORT.values()), ids=list(_NOT_AN_IMPORT))
def test_a_relative_or_textual_import_is_not_a_hit_rm741(text, rel):
    assert _unpinned_hits([(rel, text)], {}) == []


# RM-741: the importorskip exemption orders import STATEMENTS only, so a
# dynamic import in a tests/ module is never cleared by it.
_DYNAMIC_IN_A_SKIPPING_TEST = {
    "dynamic_in_sibling_function": ('def test_d():\n    pytest.importorskip("cryptography")\n\n'
                                    'def test_e():\n    importlib.import_module("cryptography")\n'),
    "dynamic_after_skip_same_function": ('def test_f():\n    pytest.importorskip("cryptography")\n'
                                         '    m = __import__("cryptography")\n'),
}


@pytest.mark.parametrize("text", list(_DYNAMIC_IN_A_SKIPPING_TEST.values()),
                         ids=list(_DYNAMIC_IN_A_SKIPPING_TEST))
def test_a_dynamic_import_is_never_exempted_rm741(text):
    assert _unpinned_hits([("tests/test_x.py", text)], {}) == ["tests/test_x.py: cryptography"]


def test_an_unparseable_module_is_a_hit_for_every_unpinned_package_rm741():
    # It names no package at all: the guard cannot see what it imports, so it
    # never vouches for it. A pin still clears that package.
    text = "def (:\n"
    assert _unpinned_hits([("mc/server.py", text)], {}) == [
        f"mc/server.py: {p}" for p in UNPINNED_BY_DECISION]
    assert _unpinned_hits([("tests/test_x.py", text)], {"requests": "2.0.0"}) == [
        f"tests/test_x.py: {p}" for p in UNPINNED_BY_DECISION if p != "requests"]
