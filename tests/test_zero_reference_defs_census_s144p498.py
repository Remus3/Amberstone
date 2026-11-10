"""Census - no top-level def / class in the production packages has zero references (S144-P-498).

A top-level, undecorated function or class in ``core/``, ``coaches/``, ``modes/``, ``lib/`` or
``dashboard/`` whose bare name occurs exactly ONCE in the tracked text of the repo (its own
``def`` / ``class`` line) has no caller of any kind: no import, no call, no test, no doc, no
``getattr`` string. Such a name is dead weight a reader has to rule out by hand. The RM-195 guard
removed four of these one by one; this census holds the whole class at zero.

Measured 2026-11-09 over the tracked tree: five hits (the fifth, a documentation-only response
model, is the one named exemption); four were removed in the same commit -
``core/augment_recommender._scan_own_history`` (a private one-line wrapper that only dropped the
error half of ``_scan_own_history_checked``, which every caller uses directly),
``dashboard/_arm_confirm.consumed_count`` (a lock-guarded ``len()`` accessor beside the used
``armed_count``), and the two response models ``OkResponse`` / ``ErrorResponse`` in
``dashboard/api_schema.py`` (no route, no ``_REQUEST_MODELS`` entry, no doc and no test names
either; ``api_schema`` is never enumerated by introspection).

What counts as a reference: a whole-word occurrence in any tracked ``.py`` / ``.js`` / ``.mjs`` /
``.ps1`` / ``.md`` / ``.yml`` / ``.yaml`` / ``.bat`` / ``.cmd`` / ``.xml`` / ``.txt`` / ``.toml``
/ ``.json`` file outside ``data/`` and outside the append-only history prose (the ledgers, the
archive, the roadmap and backlog, the history notes), plus nothing from this file. A test that
calls a name is a reference (the symbol is test-only, not dead); a name defined in two modules
counts twice and is not reported (conservative). Decorated defs (routes, fixtures, properties)
are skipped.

If a hit is real but must stay, name it in ``_EXEMPT`` with the reason - never by weakening the
scan. A new hit fails ``test_no_zero_reference_def``; an exemption that gains a reference fails
``test_exemptions_are_still_needed``.
"""
from __future__ import annotations

import ast
import collections
import functools
import re
from pathlib import Path

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_SCOPE = ("core/", "coaches/", "modes/", "lib/", "dashboard/")
_CORPUS_PATTERNS = (
    "*.py", "*.js", "*.mjs", "*.ps1", "*.md", "*.yml", "*.yaml", "*.bat", "*.cmd",
    "*.xml", "*.txt", "*.toml", "*.json",
)
# Append-only history prose: a name that survives only there is not in use.
_HISTORY = (
    "data/",
    "docs/_archive/",
    "docs/handoff-archive/",
    "docs/LEDGER.md",
    "LEDGER.md",
    "BACKLOG.md",
    "ROADMAP.md",
    "docs/ROADMAP_HISTORY.md",
    "docs/history_notes.md",
    "docs/claude-md-history.md",
)
_THIS = Path(__file__).resolve()
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# (path, name) -> why it stays.
_EXEMPT: dict[tuple[str, str], str] = {
    ("dashboard/api_schema.py", "ArchetypeNudgePayload"): (
        "referenced only from history prose (s184 roadmap and history notes), so the census "
        "sees it as unused; but its field list is the one written spec of the "
        "StateResponse.archetype_nudge payload, and the model carries the comment that says so. "
        "Kept as documentation. Re-open if StateResponse never names it and the shape is "
        "documented elsewhere."
    ),
}

# The four removed symbols, asserted by name so a revert is loud.
_REMOVED = (
    ("core/augment_recommender.py", "_scan_own_history"),
    ("dashboard/_arm_confirm.py", "consumed_count"),
    ("dashboard/api_schema.py", "OkResponse"),
    ("dashboard/api_schema.py", "ErrorResponse"),
)


def _top_level_names(source: str) -> list[tuple[str, int]]:
    """Undecorated top-level def / class names with their line numbers."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    return [
        (node.name, node.lineno)
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and not node.decorator_list
        and not node.name.startswith("__")
    ]


def _zero_reference(scope_sources: dict[str, str], corpus: dict[str, str]) -> list[tuple[str, int, str]]:
    """(path, line, name) for each scope def whose name occurs once in the whole corpus."""
    counts: collections.Counter[str] = collections.Counter()
    for text in corpus.values():
        counts.update(_WORD.findall(text))
    found = []
    for path, source in sorted(scope_sources.items()):
        for name, line in _top_level_names(source):
            if counts[name] == 1:
                found.append((path, line, name))
    return found


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


@functools.lru_cache(maxsize=1)
def _load() -> tuple[dict[str, str], dict[str, str]]:
    scope: dict[str, str] = {}
    corpus: dict[str, str] = {}
    for path in repo_files(REPO_ROOT, _CORPUS_PATTERNS):
        if path.resolve() == _THIS:
            continue
        rel = relative_posix(path)
        if rel.startswith(_HISTORY):
            continue
        text = _read(path)
        corpus[rel] = text
        if rel.endswith(".py") and rel.startswith(_SCOPE):
            scope[rel] = text
    return scope, corpus


def test_scanner_is_live():
    """Positive and negative controls on synthetic modules."""
    scope = {
        "core/a.py": (
            "def used_here():\n    pass\n\n"
            "def nobody_calls():\n    pass\n\n"
            "class Orphan:\n    pass\n\n"
            "@route\ndef decorated_orphan():\n    pass\n\n"
            "def __dunder_orphan__():\n    pass\n"
        ),
    }
    corpus = dict(scope)
    corpus["tests/test_a.py"] = "from core.a import used_here\nused_here()\n"
    found = {(name, line) for _, line, name in _zero_reference(scope, corpus)}
    assert found == {("nobody_calls", 4), ("Orphan", 7)}
    # a doc mention is a reference: the name is no longer reported
    corpus["docs/X.md"] = "see `nobody_calls` and Orphan\n"
    assert _zero_reference(scope, corpus) == []
    # a name defined in two modules counts twice and is conservative
    scope2 = {"core/a.py": "def dup():\n    pass\n", "core/b.py": "def dup():\n    pass\n"}
    assert _zero_reference(scope2, dict(scope2)) == []


def test_the_walk_is_not_vacuous():
    scope, corpus = _load()
    assert "core/augment_recommender.py" in scope
    assert "dashboard/api_schema.py" in scope
    assert "docs/API.md" in corpus
    assert len(scope) > 100 and len(corpus) > len(scope)
    assert not any(rel.startswith("data/") for rel in corpus)


def test_no_zero_reference_def():
    scope, corpus = _load()
    found = [
        f"{path}:{line} {name}"
        for path, line, name in _zero_reference(scope, corpus)
        if (path, name) not in _EXEMPT
    ]
    assert not found, (
        "top-level defs with no reference anywhere (delete them, or name an exemption "
        "with a reason):\n  " + "\n  ".join(found)
    )


def test_exemptions_are_still_needed():
    scope, corpus = _load()
    live = {(path, name) for path, _line, name in _zero_reference(scope, corpus)}
    stale = sorted(key for key in _EXEMPT if key not in live)
    assert not stale, f"exemptions that no longer offend (drop them): {stale}"


def test_the_four_removed_symbols_stay_removed():
    for rel, name in _REMOVED:
        names = {n for n, _ in _top_level_names(_read(REPO_ROOT / rel))}
        assert name not in names, f"{rel} defines {name} again"


def test_the_live_neighbours_are_kept():
    """armed_count has a test caller and _scan_own_history_checked is the real scan."""
    arm = {n for n, _ in _top_level_names(_read(REPO_ROOT / "dashboard/_arm_confirm.py"))}
    rec = {n for n, _ in _top_level_names(_read(REPO_ROOT / "core/augment_recommender.py"))}
    assert "armed_count" in arm
    assert "_scan_own_history_checked" in rec
