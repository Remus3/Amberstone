"""
tests/test_css_var_definitions_rm209.py

RM-209 - no file under web/ may reference a CSS custom property that nothing
defines.

WHY THIS NEEDS A GUARD AT ALL. A var(--x) naming a property with no
definition is invalid at computed-value time. It does not throw, it does not
warn in the console, and it passes every source grep for the token name - the
declaration is simply dropped and the element inherits instead. Where the
site carries a fallback (the shape var(--x, #1c1c24)) the FALLBACK renders,
in every theme, forever: the rule looks themeable and is in fact pinned to a
literal. Only a computed-style read finds it, which is why source review had
let eight panel stylesheets drift onto seven such names.

WHAT COUNTS AS DEFINED. Either a declaration in any scanned file
(`--x: value`), or a runtime write from a JS module
(`el.style.setProperty("--x", ...)`). The runtime-written set is DISCOVERED
by scanning rather than hardcoded, so it cannot go stale as panels come and
go: --bar-pct / --pct / --ring-pct / --buy-pct / --csv-champname-col /
--ovx-maxh / --ovx-scale / --rc-overlay-opacity / --rc-overlay-scale are all
correct as authored and pass on their writers, with no allowlist to maintain.

COMMENT HANDLING IS LOAD-BEARING, IN BOTH DIRECTIONS. CSS block comments are
stripped from .css files before scanning. A commented-out declaration must
not register as a definition - that would mask a live dangling reference and
make this guard miss the exact defect it exists to catch. Prose that merely
quotes a var() must not register as a reference either - web/mc/mc.css
deliberately quotes var(--font-mono) while explaining why it uses a literal
font stack instead. The strip preserves line numbering (each comment becomes
its own newlines) so the failure message points at the real line.

SCOPE NOTE (measured 2026-09-04). Treating web/ as one namespace and treating
the dashboard bundle (web/css + web/js) and the Mission Control bundle
(web/mc) as separate documents produce the SAME answer today, so the simpler
whole-tree form below loses nothing. The standalone pages (legacy_index.html,
mock/*.html, vision_calibrator.html) each declare and consume their own :root
block in the same file, so they are self-consistent under either reading.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

SCANNED_SUFFIXES = {".css", ".html", ".js"}

# A reference: the head of a var() call, tolerating `var( --x`.
_REF = re.compile(r"var\(\s*(--[A-Za-z0-9_-]+)")
# A declaration: a custom-property name followed by a colon. Only ever run
# against text whose var() heads have already been blanked (see _blank_refs).
_DECL = re.compile(r"(--[A-Za-z0-9_-]+)\s*:")
# A runtime write from JS.
_SETPROP = re.compile(r"setProperty\(\s*[\"'`](--[A-Za-z0-9_-]+)")
_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def _strip_css_comments(text: str) -> str:
    """Blank CSS block comments, preserving line count so reported line
    numbers stay true to the file on disk."""
    return _CSS_COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), text)


def _blank_refs(text: str) -> str:
    """Remove the name from every var() head.

    Without this, `var(--x, #fff)` would satisfy _DECL and every dangling
    reference would define itself - the guard would be vacuously green.
    """
    return _REF.sub("var(", text)


def _scanned_files() -> list[Path]:
    return sorted(
        p for p in WEB.rglob("*")
        if p.is_file() and p.suffix in SCANNED_SUFFIXES
    )


def _text(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    return _strip_css_comments(raw) if path.suffix == ".css" else raw


def _collect() -> tuple[dict[str, list[str]], set[str]]:
    """Return ({name: [file:line, ...]} references, {name} definitions)."""
    refs: dict[str, list[str]] = {}
    defined: set[str] = set()
    for path in _scanned_files():
        rel = path.relative_to(ROOT).as_posix()
        text = _text(path)
        for match in _REF.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            refs.setdefault(match.group(1), []).append(f"{rel}:{line}")
        defined.update(_SETPROP.findall(text))
        defined.update(_DECL.findall(_blank_refs(text)))
    return refs, defined


# --------------------------------------------------------------- the guard
def test_no_dangling_css_custom_property():
    refs, defined = _collect()
    dangling = sorted(name for name in refs if name not in defined)
    detail = "; ".join(
        f"{name} ({len(refs[name])} ref(s): {', '.join(refs[name][:4])})"
        for name in dangling
    )
    assert not dangling, (
        f"{len(dangling)} CSS custom propert(ies) referenced under web/ but "
        "declared nowhere and never written via style.setProperty. A var() "
        "naming an undefined property is invalid at computed-value time, so "
        "the rule silently renders its fallback literal in EVERY theme and "
        "stops following data-theme. Map the name onto a token that already "
        "exists (panels/base.css, themes.css, tokens.css) or declare it in "
        "tokens.css plus every :root[data-theme=...] block it must vary in: "
        + detail
    )


# ------------------------------------------------- the guard's own defences
# Each of these fails if the mechanism above quietly stops working. Without
# them a scan that found nothing at all would report a clean tree.
def test_guard_corpus_is_populated():
    """A guard that silently scanned zero files would pass. Pin the corpus."""
    rels = {p.relative_to(ROOT).as_posix() for p in _scanned_files()}
    assert len(rels) > 100, f"only {len(rels)} files scanned - corpus collapsed"
    for must in (
        "web/css/tokens.css",
        "web/css/themes.css",
        "web/css/panels/base.css",
        "web/css/panels/champ_benchmarks.css",
        "web/css/panels/build_order.css",
        "web/mc/mc.css",
        "web/js/main.js",
    ):
        assert must in rels, f"guard corpus missing {must}"


def test_both_scan_halves_are_live():
    """An empty refs map or an over-broad defined set makes the assertion
    above vacuously true. Assert each half independently finds real names."""
    refs, defined = _collect()
    assert len(refs) > 100, f"reference scan found only {len(refs)} names"
    # declared tokens
    assert {"--surface-3", "--text", "--border", "--signal-info"} <= defined
    # runtime-written tokens, discovered by scan rather than allowlisted
    assert {"--bar-pct", "--ring-pct", "--pct", "--ovx-scale"} <= defined
    # a reference the tree really makes
    assert "--fs-sm" in refs


def test_a_var_head_never_reads_as_a_declaration():
    """The core mechanism. If var(--x, #fff) registered --x as DEFINED, every
    dangling name would define itself and the guard could never fail."""
    sample = "a { color: var(--probe-only, #fff); }"
    assert _REF.findall(sample) == ["--probe-only"]
    assert _DECL.findall(_blank_refs(sample)) == []


def test_commented_out_declaration_is_not_a_definition():
    """Comment stripping is what stops a dead declaration from masking a live
    reference - and it must not shift the line numbers the failure reports."""
    src = "/* --ghost: #fff;\n   still inside the comment */\n.x { color: var(--ghost); }\n"
    stripped = _strip_css_comments(src)
    assert _DECL.findall(_blank_refs(stripped)) == [], "comment read as a declaration"
    assert _REF.findall(stripped) == ["--ghost"], "live reference lost to the strip"
    assert stripped.count("\n") == src.count("\n"), "comment strip shifted line numbers"


def test_quoted_var_in_a_css_comment_is_not_a_reference():
    """web/mc/mc.css argues in prose for a literal font stack and quotes
    var(--font-mono) while doing so. Prose must not create a reference."""
    src = "/* Literal stack, not var(--only-in-prose, monospace): see RM-209. */\n.x { color: red; }\n"
    assert _REF.findall(_strip_css_comments(src)) == []
