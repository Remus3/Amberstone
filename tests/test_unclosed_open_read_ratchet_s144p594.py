"""S144-P-594 - no tracked .py reads or json-loads a file handle it never closes.

``Path(p).open(...).read()``, ``open(p).read()`` and ``json.load(Path(p).open())`` open a handle and drop it on the next
bytecode. CPython's refcount closes it at once, so nothing fails on the developer's box, but PyPy and a ``-W error``
ResourceWarning run leak it, and on Windows the unclosed handle holds the file open until the collector runs. The
bare ``json.load(open(...))`` form also reads with the PLATFORM default encoding (cp1252 on Windows), so a UTF-8 file
decodes wrongly or not at all: that is the one behaviour this fix changes (``test_effects_expansion.py``'s DDragon
items read now says ``encoding="utf-8"``).

Measured 2026-11-09 by an AST walk of the tracked tree: ten sites in six files (eight ASCII-hygiene reads in four DS test
files, one DDragon items load in ``test_effects_expansion.py``, one two-line ``rb`` header sniff in
``test_rm175_aram_table_known_wrong.py``). All ten were converted (``read_text(encoding="utf-8")`` or a ``with`` block),
so the baseline is EMPTY and stays empty: a new site fails ``test_no_unclosed_open_reads``.

The shapes caught are direct: a ``.read`` / ``.readline`` / ``.readlines`` call on the RESULT of an ``open(...)`` /
``X.open(...)`` call, and ``json.load`` / ``pickle.load`` / ``yaml.safe_load`` / ``tomllib.load`` whose first argument is
such a call. A handle bound to a name and closed later is not this guard's subject (``ruff SIM115`` and the PTH123
ratchet cover the neighbours).
"""
from __future__ import annotations

import ast
from pathlib import Path

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_READERS = frozenset({"read", "readline", "readlines"})
_LOADERS = frozenset({"load", "safe_load"})
# file -> sites. Only shrinks. Empty: every measured site was converted.
_BASELINE: dict[str, int] = {}
# Modules converted by this slice: each stays tracked and clean.
_CONVERTED = (
    "agents/daemon_slayer/tests/test_cross_spell_amp_item257.py",
    "agents/daemon_slayer/tests/test_effects_expansion.py",
    "agents/daemon_slayer/tests/test_passive_damage_per_stack_item249.py",
    "agents/daemon_slayer/tests/test_passive_heal_overrides_as_aware_item253.py",
    "agents/daemon_slayer/tests/test_passive_heal_overrides_item250.py",
    "tests/test_rm175_aram_table_known_wrong.py",
)


def _is_open_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "open"
    return isinstance(func, ast.Attribute) and func.attr == "open"


def unclosed_reads(source: str) -> list[int]:
    """Line numbers of every direct read / load on an open() result in ``source``."""
    hits: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        attr = node.func.attr
        if attr in _READERS and _is_open_call(node.func.value):
            hits.append(node.lineno)
        elif attr in _LOADERS and node.args and _is_open_call(node.args[0]):
            hits.append(node.lineno)
    return sorted(hits)


def _scan() -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    files = repo_files(REPO_ROOT, ("*.py",))
    assert len(files) > 500, "the tracked-file walk returned almost nothing"
    for path in files:
        try:
            source = path.read_text(encoding="utf-8")
            lines = unclosed_reads(source)
        except (OSError, UnicodeDecodeError, SyntaxError, ValueError):
            continue  # a python-2 / template / non-UTF-8 fixture is not this guard's subject
        if lines:
            found[relative_posix(path)] = lines
    return found


def test_no_unclosed_open_reads():
    over = {f: lines for f, lines in _scan().items() if len(lines) > _BASELINE.get(f, 0)}
    assert not over, f"unclosed open().read() / json.load(open()) sites above the baseline: {over}"


def test_the_baseline_only_shrinks():
    found = _scan()
    stale = {f: n for f, n in _BASELINE.items() if len(found.get(f, [])) < n}
    assert not stale, f"baseline entries to lower or remove (fixed since): {stale}"


def test_the_converted_modules_are_clean_and_still_tracked():
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    for rel in _CONVERTED:
        assert rel in tracked, rel
        assert rel not in _BASELINE, rel
        assert unclosed_reads((REPO_ROOT / rel).read_text(encoding="utf-8")) == [], rel


def test_the_detector_sees_each_unclosed_shape():
    """Positive controls: an empty scan would pass the ratchet, so prove the detector fires."""
    probes = {
        "path_open_read": 'from pathlib import Path\nx = Path("a").open(encoding="utf-8").read()\n',
        "builtin_open_read": 'x = open("a").read()\n',
        "binary_header": 'x = p.open("rb").read(64)\n',
        "readlines": 'x = open("a").readlines()\n',
        "json_load": 'import json\nx = json.load(Path("a").open())\n',
        "yaml_safe_load": 'x = yaml.safe_load(open("a"))\n',
    }
    for name, src in probes.items():
        assert unclosed_reads(src) != [], name


def test_the_detector_ignores_the_closed_spellings():
    clean = (
        'x = Path("a").read_text(encoding="utf-8")\n'
        'with open("a") as fh:\n    y = fh.read()\n'
        'with Path("a").open("rb") as fh:\n    z = fh.read(64)\n'
        "w = json.loads(p.read_text(encoding='utf-8'))\n"
        "buf = io.StringIO('a').read()\n"
        "n = tarfile.open('a')\n"
    )
    assert unclosed_reads(clean) == []


def test_a_bare_loader_on_a_name_is_not_flagged():
    assert unclosed_reads("import json\nd = json.load(fh)\n") == []
    assert Path(__file__).is_file()
