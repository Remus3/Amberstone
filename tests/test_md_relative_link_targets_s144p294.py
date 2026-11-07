"""S144-P-294 - a living tracked *.md never links to a repo file that does not exist.

The cite family (p284 / p285 / p290 / p291 / p292) guards PROSE that names a gone script. None of them looks at a real
markdown link ``[text](relative/path)``, which GitHub renders as a clickable 404 when the target is missing or when
the path is written root-relative inside a subdirectory file. This guard resolves every inline link target against the
directory of the file that carries it and demands the target is a tracked file or directory.

Measured 2026-11-06 over the 745 tracked ``*.md``: the scan reports dangling-as-written targets in exactly three
files, all dated or verbatim records, and none in a living doc. They are out of scope by name: ``docs/_archive/`` and
``docs/superpowers/plans/`` (every plan there carries a date in its file name), and ``_VERBATIM``
(``docs/claude-md-history.md``, the pre-condense CLAUDE.md snapshot the rules forbid editing, and
``docs/history_notes.md``, the append-only deep archive: both wrote their links against the repo root).
Fenced code blocks and inline code spans are stripped first (a regex shown in prose is not a link); a trailing
``:<line>`` or ``:<line>-<line>`` on a target is a line cite and is dropped before resolving; ``http(s):``,
``mailto:`` and ``#anchor`` targets are not repo files.

S144-P-296: the link pattern is anchored on the ``](target)`` join, not on a bracket-free ``[text]`` prefix, so the
outer target of an image-wrapped badge ``[![b](img.svg)](page.md)`` (README.md line 9) is checked too. Re-measured over
the same scope: still zero dangling targets in a living doc.

``_ALLOWED`` (file, target) only shrinks and ships empty.
"""
from __future__ import annotations

import posixpath
import re
import subprocess

from tests._repo_walk import REPO_ROOT

_DATED_ROOTS = ("docs/_archive/", "docs/superpowers/plans/")
_VERBATIM = frozenset({"docs/claude-md-history.md", "docs/history_notes.md"})

# (file, link target) -> why the target is allowed to be missing. Only shrinks; ships empty.
_ALLOWED: set[tuple[str, str]] = set()

_FENCE = re.compile(r"^[ \t]*(```|~~~).*?^[ \t]*\1[^\n]*$", re.S | re.M)
_INLINE_CODE = re.compile(r"`[^`\n]*`")
# Anchored on the ``](target)`` join only: a link text that itself holds ``]`` (an image-wrapped badge,
# ``[![b](img.svg)](page.md)``) has no bracket-free text, so a ``[text]`` prefix would skip the outer target.
_LINK = re.compile(r"\]\(<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\)")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_LINE_CITE = re.compile(r":\d+(?:-\d+)?$")


def _tracked() -> frozenset[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout
    return frozenset(line for line in out.split("\n") if line)


def _scoped(tracked: frozenset[str]) -> list[str]:
    return sorted(
        p for p in tracked
        if p.endswith(".md") and not p.startswith(_DATED_ROOTS) and p not in _VERBATIM
    )


def _dirs(tracked: frozenset[str]) -> frozenset[str]:
    out: set[str] = {""}
    for p in tracked:
        parts = p.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            out.add("/".join(parts[:i]))
    return frozenset(out)


def link_targets(source: str) -> list[tuple[int, str]]:
    """(line number, raw target) for every inline repo-file link or image outside code."""
    blanked = _FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), source)
    blanked = _INLINE_CODE.sub(lambda m: " " * len(m.group(0)), blanked)
    found: list[tuple[int, str]] = []
    for m in _LINK.finditer(blanked):
        target = m.group(1)
        if target.startswith("#") or _SCHEME.match(target):
            continue
        found.append((blanked.count("\n", 0, m.start()) + 1, target))
    return found


def resolves(rel_file: str, target: str, tracked: frozenset[str], dirs: frozenset[str]) -> bool:
    path = _LINE_CITE.sub("", target.split("#", 1)[0].split("?", 1)[0])
    if not path:
        return True
    if path.startswith("/"):
        full = posixpath.normpath(path.lstrip("/"))
    else:
        full = posixpath.normpath(posixpath.join(posixpath.dirname(rel_file), path))
    if full == ".":
        return True
    if full.startswith(".."):
        return False
    return full in tracked or full.rstrip("/") in dirs


def _tree_hits() -> set[tuple[str, str]]:
    tracked = _tracked()
    dirs = _dirs(tracked)
    found: set[tuple[str, str]] = set()
    for rel in _scoped(tracked):
        src = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
        for _line, target in link_targets(src):
            if not resolves(rel, target, tracked, dirs):
                found.add((rel, target))
    return found


def test_scope_is_enumerated():
    scoped = _scoped(_tracked())
    assert "README.md" in scoped and "docs/ARCHITECTURE.md" in scoped
    assert any(p.startswith("docs/adr/") for p in scoped)
    assert not any(p.startswith(_DATED_ROOTS) for p in scoped)
    assert not (_VERBATIM & set(scoped))
    assert len(scoped) >= 300


def test_no_markdown_link_to_a_missing_repo_file():
    new = sorted(_tree_hits() - _ALLOWED)
    assert not new, (
        "markdown link target is not a tracked file or directory (links resolve against the carrying file's own "
        f"directory): {new}"
    )


def test_allowlist_is_exact():
    stale = sorted(_ALLOWED - _tree_hits())
    assert not stale, f"_ALLOWED entries that no longer match a dangling link - drop them: {stale}"


def test_exempt_names_exist():
    tracked = _tracked()
    for root in _DATED_ROOTS:
        assert any(p.startswith(root) and p.endswith(".md") for p in tracked), root
    assert _VERBATIM <= tracked


def test_scanner_is_live():
    tracked = frozenset({"docs/a.md", "docs/adr/README.md", "web/js/x.js"})
    dirs = _dirs(tracked)
    src = (
        "See [adr](adr/README.md) and [site](https://example.org/x) and [top](#anchor).\n"
        "A gone one: [x](adr/GONE.md). Root-style inside docs: [w](web/js/x.js).\n"
        "Line cite: [l](../web/js/x.js:12-20). Dir: [d](adr/). Image: ![i](x/gone.png).\n"
        "```\n[fenced](nope/fenced.md)\n```\n"
        "Inline `[code](nope/inline.md)` text.\n"
        "Badge: [![b](x/badge.svg)](adr/BADGE_GONE.md) and [![b](https://example.org/b.svg)](adr/README.md).\n"
    )
    got = {t for _n, t in link_targets(src)}
    assert got == {
        "adr/README.md", "adr/GONE.md", "web/js/x.js", "../web/js/x.js:12-20", "adr/", "x/gone.png",
        "x/badge.svg", "adr/BADGE_GONE.md",
    }
    bad = {t for t in got if not resolves("docs/a.md", t, tracked, dirs)}
    assert bad == {"adr/GONE.md", "web/js/x.js", "x/gone.png", "x/badge.svg", "adr/BADGE_GONE.md"}
    assert [n for n, t in link_targets(src) if t == "adr/GONE.md"] == [2]
