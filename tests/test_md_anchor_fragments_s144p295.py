"""S144-P-295 - a living tracked *.md never links to a heading anchor that the target markdown does not have.

S144-P-294 (tests/test_md_relative_link_targets_s144p294.py) demands every inline link target resolves to a tracked
file; it drops the ``#fragment`` before resolving. A link ``[x](ARCHITECTURE.md#old-heading)`` or ``[x](#old)`` whose
heading was renamed still renders, jumps nowhere and fails silently. This guard resolves the fragment against the
headings of the target markdown file (or of the carrying file for a bare ``#frag``), using GitHub's slug rule:
lower-case, markup and punctuation dropped, spaces become hyphens, a repeated heading gets ``-1``, ``-2`` ... A raw
``<a name=...>`` / ``<a id=...>`` also counts as an anchor.

Measured 2026-11-06 over the tracked ``*.md`` in P-294's scope (same dated / verbatim exemptions, shared with
that guard rather than restated): 13 links carry a fragment into a markdown file (the 12-row README contents table and the platform badge
``[![..](..)](#limitations)``) and all 13 resolve, so
``_ALLOWED`` ships empty and only shrinks. A fragment into a non-markdown target (``#L12`` on a source file) has no
heading list to check and is out of scope.
"""
from __future__ import annotations

import posixpath
import re

from tests._repo_walk import REPO_ROOT
from tests.test_md_relative_link_targets_s144p294 import (
    _FENCE,
    _INLINE_CODE,
    _SCHEME,
    _scoped,
    _tracked,
)

# (carrying file, raw link target) -> why the anchor may be missing. Only shrinks; ships empty.
_ALLOWED: set[tuple[str, str]] = set()

# Any ``](target)`` closes a link, so an image-wrapped badge ``[![alt](img)](#frag)`` is seen too (P-294's
# ``_LINK`` needs a bracket-free link text and misses it: a FILING, not touched here).
_LINK = re.compile(r"\]\(<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\)")
_HEADING = re.compile(r"^ {0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", re.M)
_HTML_ANCHOR = re.compile(r"""<a\s[^>]*?\b(?:name|id)\s*=\s*["']([^"']+)["']""", re.I)


def slug(heading: str) -> str:
    """GitHub's heading slug: the part before de-duplication."""
    text = heading.replace("`", "").strip().lower()
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(source: str) -> frozenset[str]:
    """Every anchor a markdown source offers (fenced blocks do not contribute headings)."""
    body = _FENCE.sub("", source)
    seen: dict[str, int] = {}
    found: set[str] = set()
    for m in _HEADING.finditer(body):
        base = slug(m.group(1))
        n = seen.get(base, 0)
        seen[base] = n + 1
        found.add(base if n == 0 else f"{base}-{n}")
    found.update(a.lower() for a in _HTML_ANCHOR.findall(body))
    return frozenset(found)


def fragment_links(source: str) -> list[tuple[int, str, str]]:
    """(line, path part, fragment) for every inline link that carries a non-empty fragment, outside code."""
    blanked = _FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), source)
    blanked = _INLINE_CODE.sub(lambda m: " " * len(m.group(0)), blanked)
    out: list[tuple[int, str, str]] = []
    for m in _LINK.finditer(blanked):
        target = m.group(1)
        if _SCHEME.match(target) or "#" not in target:
            continue
        path, frag = target.split("#", 1)
        path = path.split("?", 1)[0]
        if frag:
            out.append((blanked.count("\n", 0, m.start()) + 1, path, frag))
    return out


def _missing(rel: str, source: str, tracked: frozenset[str], read) -> list[tuple[str, str]]:
    bad: list[tuple[str, str]] = []
    for _line, path, frag in fragment_links(source):
        target = rel if not path else posixpath.normpath(posixpath.join(posixpath.dirname(rel), path))
        if target not in tracked or not target.endswith(".md"):
            continue  # a missing file is P-294's finding; a non-markdown target has no headings
        if frag.lower() not in anchors(read(target)):
            bad.append((rel, f"{path}#{frag}"))
    return bad


def _tree_hits() -> set[tuple[str, str]]:
    tracked = _tracked()

    def read(p: str) -> str:
        return (REPO_ROOT / p).read_text(encoding="utf-8", errors="replace")

    found: set[tuple[str, str]] = set()
    for rel in _scoped(tracked):
        found.update(_missing(rel, read(rel), tracked, read))
    return found


def test_no_markdown_link_to_a_missing_heading_anchor():
    new = sorted(_tree_hits() - _ALLOWED)
    assert not new, f"markdown link fragment matches no heading of its target (GitHub slug rule): {new}"


def test_allowlist_is_exact():
    stale = sorted(_ALLOWED - _tree_hits())
    assert not stale, f"_ALLOWED entries that no longer match a dangling anchor - drop them: {stale}"


def test_the_tree_really_has_fragment_links():
    """An empty enumeration would pass the guard above: demand the scan sees real fragment links."""
    tracked = _tracked()
    n = 0
    for rel in _scoped(tracked):
        src = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
        n += sum(1 for _l, p, _f in fragment_links(src) if (not p) or p.endswith(".md"))
    assert n >= 13, n


def test_slug_matches_github_rule():
    assert slug("What it does") == "what-it-does"
    assert slug("Daemon Slayer (build engine)") == "daemon-slayer-build-engine"
    assert slug("The `core/x.py` seam, v2") == "the-corexpy-seam-v2"
    assert slug("[Link](http://x) text") == "link-text"


def test_scanner_is_live():
    tracked = frozenset({"docs/a.md", "docs/b.md", "web/js/x.js"})
    docs = {
        "docs/a.md": (
            "# Alpha\n## Same\n## Same\n```\n# Fenced heading\n```\n"
            "<a name=\"Raw-Anchor\"></a>\n"
            "[ok](#alpha) [ok2](b.md#beta-one) [dup](#same-1) [raw](#raw-anchor) [case](#ALPHA)\n"
            "[gone](#nope) [gone2](b.md#nope-two) [fenced](#fenced-heading)\n"
            "[![badge](img.svg)](#alpha) [![badge](img.svg)](#nope-badge) [js](../web/js/x.js#L12) [web](https://example.org/p#frag) `[code](#inline)` [bare](b.md)\n"
        ),
        "docs/b.md": "## Beta one\n",
    }
    got = _missing("docs/a.md", docs["docs/a.md"], tracked, docs.__getitem__)
    assert sorted(t for _r, t in got) == ["#fenced-heading", "#nope", "#nope-badge", "b.md#nope-two"]
