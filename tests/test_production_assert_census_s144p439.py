"""S144-P-439 - every production ``assert`` statement is a named, reasoned row.

``python -O`` (or ``PYTHONOPTIMIZE``) strips every ``assert`` and its operands. Code that uses one as RUNTIME VALIDATION of
caller or configuration input therefore stops validating, silently, under that flag; code that uses one only to narrow a
type or to state an internal invariant loses nothing a reader needs.

Measured 2026-11-08 over every tracked production ``.py`` (AST; an ``assert`` in a string, comment or docstring never
counts): 11 statements in 7 files, and nothing in the tree launches Python with ``-O`` / ``-OO`` or sets
``PYTHONOPTIMIZE`` (grep of ``*.py``, ``*.ps1``, ``*.bat``, ``*.json``, ``*.toml``, ``*.yml``, ``*.cfg``), so every one
runs live today. Every one is a row in ``_ROWS`` with its class:

- ``narrow``: the assert only tells a type checker an Optional is set; the code above already guarantees it (usually the
  next line would raise anyway; at ``self_shred.py`` it would return None, but a non-empty candidate list rules that out).
- ``invariant``: an internal consistency check over module constants or this function's own output.
- ``validation``: checks input a subclass or caller supplies. NONE may be added without a reason; the one row today is
  ``lib/scrapers/_base.py`` ``ScraperBase.__init__`` (an empty ``site`` makes the cache directory the scrape root).
  Converting it to ``raise`` also changes ``tests/test_pt018_ruf036_prod_ratchet_s144p175.py``, which pins
  ``AssertionError``; the file was changed on ``lane/true-audit`` the same session, so it is filed for the merger.

The row key is ``(file, assert source)``; the set is exact, so a site that goes away must be dropped. A second test
refuses an assert whose operand has a side effect (a call that is not a pure read, a walrus): ``-O`` would delete it.

Out of scope: ``tests/`` and ``*/tests/`` (pytest rewrites those), the ``agents/agent3_testing/suite/`` test harness,
``docs/`` (one-off analysis scripts) and the vendored ``ops/fleet_kit/``. Named blind spot: ``raise AssertionError`` written by hand is not an ``assert`` statement.
"""
from __future__ import annotations

import ast

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_SKIP_PREFIXES = ("tests/", "docs/", "ops/fleet_kit/", "agents/agent3_testing/suite/")

_NARROW = "narrow"
_INVARIANT = "invariant"
_VALIDATION = "validation"

_ROWS = {
    ("agents/daemon_slayer/self_shred.py", "assert best is not None"):
        (_NARROW, "the candidates list is checked non-empty above, so the loop always sets best"),
    ("agents/supervisor.py", "assert self._scheduler is not None"):
        (_NARROW, "the scheduler property; a None would fail on the next attribute access anyway"),
    ("core/post_game_score.py", "assert len(FEATURE_NAMES) == WPA_FEATURE_COUNT"):
        (_INVARIANT, "import-time check of two module constants; tests pin the same equality"),
    ("core/post_game_score.py", "assert len(FEATURE_SCALES) == WPA_FEATURE_COUNT"):
        (_INVARIANT, "import-time check of two module constants; tests pin the same equality"),
    ("lib/scrapers/_base.py", "assert self.site, 'subclass must set site and base_url'"):
        (_VALIDATION, "subclass config; under -O an empty site caches into the scrape root. FILED for the merger: "
                      "lane/true-audit also changed this file, and an existing test pins AssertionError"),
    ("lib/scrapers/_base.py", "assert self.base_url, 'subclass must set site and base_url'"):
        (_VALIDATION, "subclass config; same row as the site check above"),
    ("tft/tft_roll_odds.py", "assert c.units_per_cost is not None"):
        (_NARROW, "built by _tables, which always fills it; the next line would raise TypeError anyway"),
    ("tools/credential_history_scan.py", "assert proc.stdin"):
        (_NARROW, "Popen(stdin=PIPE) always sets it"),
    ("tools/credential_history_scan.py", "assert proc.stdout"):
        (_NARROW, "Popen(stdout=PIPE) always sets it"),
    ("tools/web_ascii_sweep.py", "assert out[0].start == 0, 'span coverage is not total'"):
        (_INVARIANT, "the merge loop's own output covers the text from 0; a developer-tool self-check"),
    ("tools/web_ascii_sweep.py", "assert out[-1].end == total, 'span coverage is not total'"):
        (_INVARIANT, "the merge loop's own output covers the text to the end; a developer-tool self-check"),
}


def _asserts(source: str) -> list[tuple[int, str, ast.Assert]]:
    """``(lineno, assert source, node)`` per ``assert`` statement."""
    tree = ast.parse(source)
    return sorted(
        ((n.lineno, ast.unparse(n), n) for n in ast.walk(tree) if isinstance(n, ast.Assert)),
        key=lambda t: t[0],
    )


def _production_files():
    return [p for p in repo_files(REPO_ROOT, ("*.py",))
            if not relative_posix(p).startswith(_SKIP_PREFIXES) and "/tests/" not in relative_posix(p)]


def _side_effects(node: ast.Assert) -> list[str]:
    """Operand shapes ``-O`` would delete along with the assert: a walrus, or a call to something not named as a pure read."""
    pure = {"len", "isinstance", "issubclass", "callable", "hasattr", "all", "any", "set", "tuple", "list", "dict",
            "sorted", "min", "max", "abs", "bool", "int", "str", "float", "type", "id"}
    out = [ast.unparse(n) for n in ast.walk(node) if isinstance(n, ast.NamedExpr)]
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            name = n.func.id if isinstance(n.func, ast.Name) else None
            if name not in pure:
                out.append(ast.unparse(n))
    return out


def _found() -> dict[tuple[str, str], list[ast.Assert]]:
    files = _production_files()
    assert len(files) > 100, "the tracked-file walk returned almost nothing"
    found: dict[tuple[str, str], list[ast.Assert]] = {}
    for p in files:
        rel = relative_posix(p)
        try:
            sites = _asserts(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for _lineno, src, node in sites:
            found.setdefault((rel, src), []).append(node)
    return found


def test_every_production_assert_is_a_named_row():
    found = _found()
    assert len(found) >= 8, "the walk saw almost no assert, so an empty list proves nothing"
    new = sorted(set(found) - set(_ROWS))
    assert not new, (
        "production assert (python -O strips it): raise a real exception, or name the row, its class and reason "
        f"in _ROWS: {new}")
    stale = sorted(set(_ROWS) - set(found))
    assert not stale, f"stale _ROWS entry (the assert is gone, drop it): {stale}"
    for key, (cls, reason) in _ROWS.items():
        assert cls in {_NARROW, _INVARIANT, _VALIDATION}, key
        assert reason, f"{key} carries a reason"


def test_validation_rows_are_pinned_to_the_one_known_class():
    """A ``validation`` row is a defect with a filing; a new one must be argued, not slipped in."""
    validation = sorted(k for k, (cls, _r) in _ROWS.items() if cls == _VALIDATION)
    assert validation == [
        ("lib/scrapers/_base.py", "assert self.base_url, 'subclass must set site and base_url'"),
        ("lib/scrapers/_base.py", "assert self.site, 'subclass must set site and base_url'"),
    ]


def test_no_production_assert_operand_has_a_side_effect():
    bad = {key: _side_effects(nodes[0]) for key, nodes in _found().items() if _side_effects(nodes[0])}
    assert not bad, f"an assert whose operand does work is deleted under python -O: {bad}"


def test_the_detector_flags_each_shape():
    src = (
        "assert x\n"
        "def f():\n"
        "    assert y is not None, 'why'\n"
        's = "assert z"\n'
        "# assert w\n"
    )
    assert [(ln, s) for ln, s, _n in _asserts(src)] == [(1, "assert x"), (3, "assert y is not None, 'why'")]
    assert _asserts("def f():\n    '''assert q'''\n") == []


def test_the_side_effect_detector_flags_a_walrus_and_an_impure_call():
    walrus = _asserts("assert (n := compute()) > 0\n")[0][2]
    assert _side_effects(walrus)
    call = _asserts("assert register(item)\n")[0][2]
    assert _side_effects(call) == ["register(item)"]
    pure = _asserts("assert len(a) == len(b) and isinstance(x, int)\n")[0][2]
    assert _side_effects(pure) == []
