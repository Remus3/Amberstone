"""S144-P-316 - no tracked ``.py`` runs a shell string, evals text or unpickles bytes, held at zero.

The repo had no guard on the classic code-execution call sites (ruff here selects only E/F/I/UP/B/BLE, none of the S
rules). Measured 2026-11-07 over every tracked ``.py`` (tests included) by the detector below: zero hits, so this pins
that - a new site fails here, with the safer spelling named in ``_SAFER``, instead of reaching review as prose.

Detector (AST, so a name in a string, comment or docstring never counts):
- a call with a literal ``shell=True`` keyword (``shell=flag`` and ``**kwargs`` are not matched; any callee: ``subprocess.run``, ``Popen``, a wrapper that forwards it);
- ``os.system`` / ``os.popen`` shell launches (the spawn family is not matched);
- the builtin ``eval(...)`` / ``exec(...)`` called bare (``ast.literal_eval`` and a method named ``eval`` on some
  other object, for example a CDP ``_cdp_eval`` helper or a DS evaluator, are different names and are not matched);
- ``pickle`` / ``marshal`` / ``shelve`` ``load`` / ``loads`` / ``open`` (arbitrary-code deserialization), through the
  module name, an ``import ... as`` alias, or ``from <module> import <name>``;
- ``yaml.load`` / ``yaml.unsafe_load`` / ``yaml.full_load`` (``safe_load`` is the spelling to use).

Scope: every tracked ``.py``. TEST code (a ``tests/`` or ``*/tests/`` path, ``test_*.py``, ``conftest.py``) may still
``exec`` / ``eval`` / ``os.system`` a FIXED in-repo source - eight such sites measured 2026-11-07, each compiling a repo
file or a literal corpus - so those four names are production-only; ``shell=True``, pickle, marshal, shelve and yaml
loads are banned in test code too. The baseline is empty.
"""
from __future__ import annotations

import ast

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_MODULE_ATTRS = {
    "os": {"system", "popen"},
    "pickle": {"load", "loads", "Unpickler"},
    "marshal": {"load", "loads"},
    "shelve": {"open"},
    "yaml": {"load", "unsafe_load", "full_load", "load_all", "unsafe_load_all", "full_load_all"},
}

_BARE_BUILTINS = {"eval", "exec"}

_PRODUCTION_ONLY = {"eval", "exec", "os.system", "os.popen"}

_SAFER = {
    "shell=True": "an argv list: subprocess.run([prog, arg], ...)",
    "os.system": "subprocess.run([prog, arg], ...)",
    "os.popen": "subprocess.run([prog, arg], capture_output=True)",
    "eval": "ast.literal_eval or an explicit parser",
    "exec": "an explicit dispatch table",
    "pickle": "json (core.polled_json.atomic_write_json)",
    "marshal": "json",
    "shelve": "json",
    "yaml": "yaml.safe_load",
}


def _is_test_path(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return rel.startswith("tests/") or "/tests/" in rel or name.startswith("test_") or name == "conftest.py"


def _aliases(tree: ast.AST) -> dict[str, str]:
    """Local name -> tracked module, for ``import os`` and ``import pickle as pk``."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name in _MODULE_ATTRS:
                    out[a.asname or a.name] = a.name
    return out


def _shadowed_builtins(tree: ast.AST) -> set[str]:
    """Builtin names this file defines itself (``def eval(...)``), which a bare call then means."""
    return {n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name in _BARE_BUILTINS}


def _scan(source: str) -> list[tuple[int, str]]:
    """``(lineno, name)`` for each code-execution call site in ``source``."""
    tree = ast.parse(source)
    alias = _aliases(tree)
    shadow = _shadowed_builtins(tree)
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    out.append((node.lineno, "shell=True"))
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in _BARE_BUILTINS and fn.id not in shadow:
                out.append((node.lineno, fn.id))
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in alias:
            mod = alias[node.value.id]
            if node.attr in _MODULE_ATTRS[mod]:
                out.append((node.lineno, f"{mod}.{node.attr}"))
        elif isinstance(node, ast.ImportFrom) and node.module in _MODULE_ATTRS and node.level == 0:
            out.extend((node.lineno, f"{node.module}.{a.name}")
                       for a in node.names if a.name in _MODULE_ATTRS[node.module])
    return out


def test_no_tracked_py_runs_a_shell_string_evals_text_or_unpickles_bytes():
    files = repo_files(REPO_ROOT, ("*.py",))
    assert len(files) > 100, "the tracked-file walk returned almost nothing"
    hits: list[str] = []
    seen = 0
    for p in files:
        try:
            found = _scan(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        seen += 1
        rel = relative_posix(p)
        is_test = _is_test_path(rel)
        hits.extend(f"{rel}:{n} {name}" for n, name in found if not (is_test and name in _PRODUCTION_ONLY))
    assert seen > 100, "the parse walk returned almost nothing"
    assert not hits, f"code-execution call site in use (see _SAFER): {hits}"


def test_the_detector_sees_each_spelling():
    cases = {
        "import subprocess\nsubprocess.run('ls', shell=True)\n": [(2, "shell=True")],
        "run(cmd, shell=True, timeout=3)\n": [(1, "shell=True")],
        "import os\nos.system('x')\n": [(2, "os.system")],
        "import os as o\no.popen('x')\n": [(2, "os.popen")],
        "x = eval(s)\n": [(1, "eval")],
        "exec(code, g)\n": [(1, "exec")],
        "import pickle\npickle.loads(b)\n": [(2, "pickle.loads")],
        "import pickle as pk\npk.load(f)\n": [(2, "pickle.load")],
        "from pickle import loads\n": [(1, "pickle.loads")],
        "import marshal\nmarshal.loads(b)\n": [(2, "marshal.loads")],
        "import shelve\nshelve.open(p)\n": [(2, "shelve.open")],
        "import yaml\nyaml.load(s)\n": [(2, "yaml.load")],
        "from yaml import unsafe_load\n": [(1, "yaml.unsafe_load")],
    }
    for src, want in cases.items():
        assert _scan(src) == want, src
    for rel, want in {"tests/test_x.py": True, "agents/daemon_slayer/tests/t.py": True, "tests/conftest.py": True,
                      "tools/x.py": False, "core/test_helper_free.py": True, "agents/x/testing.py": False}.items():
        assert _is_test_path(rel) is want, rel
    assert set(_SAFER) >= {"shell=True", "os.system", "eval", "exec", "pickle", "yaml"}


def test_a_safe_spelling_a_string_and_a_look_alike_are_not_flagged():
    clean = (
        "import ast, os, subprocess, yaml, pickle\n"
        "subprocess.run(['ls'], shell=False)\n"
        "subprocess.run(['ls'], shell=flag)\n"
        "ast.literal_eval(s)\n"
        "os.getcwd()\n"
        "yaml.safe_load(s)\n"
        "pickle.dumps(o)\n"
        "page = _cdp_eval(ws, expr)\n"
        "ev.eval(x)\n"
        "doc = 'shell=True and eval(s) and os.system'\n"
        "# exec(code)\n"
    )
    assert _scan(clean) == []
    own = "def eval(x):\n    return x\neval(1)\n"
    assert _scan(own) == []
    shadow = "class os:\n    system = 1\nos.system\n"
    assert _scan(shadow) == []
