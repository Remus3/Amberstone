"""S144-P-372 - no production ``.read_text()`` / ``.write_text(x)`` that leaves ``encoding=`` to the locale.

Without ``encoding=`` Python decodes and encodes with the locale code page (cp1252 on a stock Windows box), so a UTF-8
file holding one non-ASCII byte (a champion name, a localized ability string, a path under a non-ASCII user name)
either raises or is silently mojibaked, and the script behaves differently under ``PYTHONUTF8=1``.

The sibling ratchet ``tests/test_unspecified_encoding_prod_ratchet_s144p303.py`` runs ruff PLW1514, and that rule only
fires where ruff can TYPE the receiver as a ``pathlib.Path`` (``Path('x').read_text()``). It is blind to a receiver it
cannot infer - ``cfg_path = Path(__file__).parent.parent / 'config' / 'x.json'; cfg_path.read_text()``, a lockfile
taken from a list, a ``td / 'x'`` temp dir passed in as a parameter - so it reported "All checks passed" over 13
production calls in five files. This census is the AST complement: it does not care what the receiver is.

Measured 2026-11-08 over every tracked ``*.py``: 13 production sites with no ``encoding=`` -
``coach_integration/_coach.py`` (coach_settings.json), ``scripts/probe_missing_codes.py`` (the ASCII LCU lockfile and a
JSON cache, twice), ``scripts/team_planner_sync.py`` (the lockfile), ``tools/dev_cli.py`` (a write-probe byte) and
``tools/run_phase2_perf.py`` (eight benchmark fixture writes). All now pass ``encoding="utf-8"``; the baseline is
EMPTY on purpose.

Shapes read: an attribute call ``.read_text(...)`` with no ``encoding`` keyword and no positional argument (the first
positional IS the encoding), and ``.write_text(...)`` with no ``encoding`` keyword and fewer than two positional
arguments (the second positional is the encoding). A call carrying ``**kwargs`` is skipped (it may carry the
encoding). Out of scope, stated: ``ops/fleet_kit/`` (vendored byte-for-byte, MAIN's) and every test tree - about 80
test-code sites remain and are filed, not hidden (ASCII fixtures written and read back by the same process; a test-code
ratchet is its own slice). Named blind spots: ``open(p)`` / ``Path.open()`` with no encoding (ruff PLW1514 types
those), ``subprocess`` ``text=True`` without ``encoding=``, and ``io.open``.
"""
from __future__ import annotations

import ast

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_OUT_OF_SCOPE = ("tests/", "ops/fleet_kit/")

# rel path -> bare call count. EMPTY: only shrinks, and it is already at the floor.
_BASELINE: dict[str, int] = {}


def scan_source(src: str) -> list[tuple[int, str]]:
    """(line, method) of every ``.read_text`` / ``.write_text`` call that leaves the encoding to the locale."""
    hits: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(src)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        method = node.func.attr
        if method not in ("read_text", "write_text"):
            continue
        if any(k.arg is None for k in node.keywords):
            continue  # **kwargs may carry encoding=
        if any(k.arg == "encoding" for k in node.keywords):
            continue
        # read_text(encoding, errors): first positional is the encoding. write_text(data, encoding, ...): second.
        if len(node.args) >= (1 if method == "read_text" else 2):
            continue
        hits.append((node.lineno, method))
    return sorted(hits)


def test_scanner_is_live():
    """Each unsafe shape is reported and each safe spelling is quiet (an empty scan proves nothing alone)."""
    bare = (
        "p.read_text()\n",
        "cfg = Path(__file__).parent / 'x.json'\ncfg.read_text()\n",
        "p.read_text(errors='replace')\n",
        "p.write_text('x')\n",
        "p.write_text(json.dumps(d), newline='\\n')\n",
        "(a / 'b').write_text(s)\n",
    )
    for src in bare:
        assert scan_source(src), src
    safe = (
        "p.read_text(encoding='utf-8')\n",
        "p.read_text('utf-8')\n",
        "p.write_text('x', encoding='utf-8')\n",
        "p.write_text('x', 'utf-8')\n",
        "p.write_text('x', newline='\\n', encoding='utf-8')\n",
        "p.read_text(**kw)\n",
        "p.write_text('x', **kw)\n",
        "read_text()\n",
        "p.read_bytes()\n",
    )
    for src in safe:
        assert scan_source(src) == [], src


def _tree_hits() -> dict[str, int]:
    out: dict[str, int] = {}
    for path in repo_files():
        rel = relative_posix(path)
        if rel.startswith(_OUT_OF_SCOPE) or "/tests/" in rel:
            continue
        try:
            src = (REPO_ROOT / rel).read_text(encoding="utf-8")
            hits = scan_source(src)
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        if hits:
            out[rel] = len(hits)
    return out


def test_no_locale_encoded_path_text_io():
    hits = _tree_hits()
    new = {rel: n for rel, n in hits.items() if n > _BASELINE.get(rel, 0)}
    assert not new, f"Path.read_text() / write_text() with no encoding= (locale code page on Windows): {new}"


def test_baseline_is_exact():
    hits = _tree_hits()
    stale = {rel: n for rel, n in _BASELINE.items() if hits.get(rel, 0) < n}
    assert not stale, f"baseline rows that no longer offend, drop them: {stale}"


def test_scan_covers_the_measured_files():
    """The walk must reach the five fixed files, or an empty result would be a scan that saw nothing."""
    seen = {relative_posix(p) for p in repo_files()}
    for rel in ("coach_integration/_coach.py", "scripts/probe_missing_codes.py", "scripts/team_planner_sync.py",
                "tools/dev_cli.py", "tools/run_phase2_perf.py"):
        assert rel in seen, rel
