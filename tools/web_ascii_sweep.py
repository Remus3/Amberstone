"""RM-125: sweep non-ASCII out of the COMMENT half of web/ sources.

web/ carries 3153 non-ASCII characters across 31 .js/.css/.html files. A large
share of them are deliberate Terminal-theme UI glyphs on LIVE spans - CSS
`content:` values, JS strings and template literals that build visible labels,
HTML text nodes and attribute values - so a blind repo-wide strip would change
rendered pixels. Comments render nothing, which makes the comment half the
rendered-output-neutral subset and the only thing this tool touches. If reaching
an all-ASCII web/ would require altering a live byte, this tool stops and leaves
it: under-sweeping is recoverable, mis-sweeping a live glyph is not.

The recogniser is a hand-rolled state machine rather than a real parser because
the repo ships no JS/CSS front end and pulling one in for a hygiene sweep is a
worse trade than ~250 lines whose FALSE-POSITIVE side is pinned by
tests/test_web_ascii_sweep.py.

Language handling:
    .js    `//` line comments + `/* */` blocks, aware of strings, template
           literals (including `${}` substitutions) and regex literals.
    .css   `/* */` only - CSS has no line comment - aware of strings.
    .html  `<!-- -->` only. .html files embed <script>/<style>, and their inner
           comments are deliberately NOT swept; see the WHY on _scan_html.

Usage:
    python tools/web_ascii_sweep.py --dry-run [--root web]
    python tools/web_ascii_sweep.py --apply   [--root web]

Exit codes: 0 clean, 2 a comment-span glyph is absent from REPLACEMENTS (the
tool names file, line, byte offset and codepoint and writes nothing).
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple, Optional

LIVE = "live"
COMMENT = "comment"

_LANGS = {".js": "js", ".css": "css", ".html": "html"}

# Identifier-ish chars for the regex-vs-division lookback.
_IDENT_EXTRA = "_$"

# After these keywords a `/` opens a regex literal, not a division.
_REGEX_KEYWORDS = frozenset({
    "await", "case", "delete", "do", "else", "in", "instanceof", "new", "of",
    "return", "throw", "typeof", "void", "yield",
})

# After a value-closer a `/` is division.
_VALUE_CLOSERS = ")]}\"'`"

# ASCII stand-ins, item-176 doctrine: 1:1 substitution that keeps visual width
# and semantic intent, never a reflow of the surrounding prose. Keys are spelled
# \uXXXX so this file is itself 7-bit ASCII.
REPLACEMENTS = {
    # Box drawing - the banner rules that dominate the census.
    "\u2500": "-", "\u2501": "-", "\u2504": "-", "\u2505": "-",
    "\u2508": "-", "\u2509": "-", "\u254c": "-", "\u254d": "-",
    "\u2550": "=",
    "\u2502": "|", "\u2503": "|", "\u2506": "|", "\u2507": "|",
    "\u250a": "|", "\u250b": "|", "\u254e": "|", "\u254f": "|",
    "\u2551": "|",
    "\u250c": "+", "\u250d": "+", "\u250e": "+", "\u250f": "+",
    "\u2510": "+", "\u2511": "+", "\u2512": "+", "\u2513": "+",
    "\u2514": "+", "\u2515": "+", "\u2516": "+", "\u2517": "+",
    "\u2518": "+", "\u2519": "+", "\u251a": "+", "\u251b": "+",
    "\u251c": "+", "\u2524": "+", "\u252c": "+", "\u2534": "+",
    "\u253c": "+", "\u2552": "+", "\u2553": "+", "\u2554": "+",
    "\u2555": "+", "\u2556": "+", "\u2557": "+", "\u2558": "+",
    "\u2559": "+", "\u255a": "+", "\u255b": "+", "\u255c": "+",
    "\u255d": "+", "\u256c": "+",
    # Blocks / shades used as bar fills.
    "\u2580": "#", "\u2584": "#", "\u2588": "#", "\u258c": "#",
    "\u2590": "#", "\u2591": ".", "\u2592": ":", "\u2593": "#",
    # Arrows.
    "\u2190": "<-", "\u2191": "^", "\u2192": "->", "\u2193": "v",
    "\u2194": "<->", "\u2195": "^v", "\u2b05": "<-", "\u2b06": "^",
    "\u2b07": "v", "\u27a1": "->", "\u21d2": "=>", "\u21d0": "<=",
    # U+21BB / U+27F3 are the circular-arrow refresh glyph; comments that use
    # them are describing that UI affordance, so `(R)` reads as "the refresh
    # glyph" without re-wording the sentence around it.
    "\u21bb": "(R)", "\u27f3": "(R)", "\u21ba": "(R)",
    # Math / relational.
    "\u2212": "-", "\u00b1": "+/-", "\u00d7": "x", "\u00f7": "/",
    "\u2248": "~", "\u2260": "!=", "\u2261": "==", "\u2264": "<=",
    "\u2265": ">=", "\u221e": "inf", "\u2211": "sum", "\u220f": "prod",
    "\u221a": "sqrt", "\u2208": "in", "\u2209": "not in", "\u2205": "{}",
    "\u0394": "delta", "\u03a3": "sum", "\u03bc": "u", "\u03c3": "sigma",
    "\u03b1": "alpha", "\u03b2": "beta", "\u03bb": "lambda", "\u03c0": "pi",
    # Superscripts keep the caret so `d^2 = (dist / RADIUS)^2` still reads as
    # an exponent; a bare "2" turns the same comment into `(dist / RADIUS)2`.
    "\u00b0": "deg", "\u00b2": "^2", "\u00b3": "^3", "\u00bd": "1/2",
    "\u00bc": "1/4", "\u00be": "3/4",
    # Punctuation / separators.
    "\u00b7": "-", "\u2022": "*", "\u2023": "*", "\u25aa": "*",
    "\u2026": "...", "\u22ef": "...", "\u2013": "-", "\u2014": "-",
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u00ab": "<<", "\u00bb": ">>", "\u2039": "<", "\u203a": ">",
    "\u27e8": "<", "\u27e9": ">", "\u00a7": "S", "\u00b6": "P",
    "\u2020": "+", "\u2021": "++", "\u00a9": "(c)", "\u00ae": "(R)",
    "\u2122": "(TM)", "\u00a0": " ", "\u2009": " ", "\u200b": "",
    "\ufe0f": "", "\u200d": "",
    # Status / marks.
    "\u2713": "ok", "\u2714": "ok", "\u2705": "ok", "\u2611": "ok",
    "\u2717": "X", "\u2718": "X", "\u2715": "x", "\u2716": "x",
    "\u274c": "X", "\u26d4": "X", "\U0001f6ab": "X",
    "\u26a0": "!", "\u26a1": "!", "\u203c": "!!", "\u2757": "!",
    "\u2753": "?", "\u2754": "?",
    # Triangles / carets / dots used as pointers.
    "\u25b2": "^", "\u25b4": "^", "\u25b6": ">", "\u25b8": ">",
    "\u25ba": ">", "\u25bc": "v", "\u25be": "v", "\u25c0": "<",
    "\u25c2": "<", "\u25c4": "<", "\u25cf": "o", "\u25cb": "o",
    "\u25c9": "o", "\u25e6": "o", "\u25a0": "#", "\u25a1": "#",
    "\u25e7": "#", "\u25fc": "#", "\u2b1b": "#",
    # Misc symbols that turn up in prose.
    "\u2605": "*", "\u2606": "*", "\u2726": "*", "\u2727": "*",
    "\u2733": "*", "\u2734": "*", "\u2728": "*", "\u2665": "<3",
    "\u2764": "<3", "\u265b": "Q", "\u2694": "atk", "\u2697": "lab",
    "\u2303": "^", "\u2318": "cmd", "\u21e7": "shift", "\u23f3": "wait",
    "\u231b": "wait", "\u2699": "cfg", "\u2692": "tool",
}


class Span(NamedTuple):
    start: int
    end: int
    kind: str


@dataclass(frozen=True)
class Change:
    offset: int
    original: str
    replacement: str


@dataclass(frozen=True)
class Unmapped:
    offset: int
    char: str


@dataclass(frozen=True)
class SweepResult:
    text: str
    changes: list[Change]
    unmapped: list[Unmapped]


def lang_for_path(path) -> Optional[str]:
    return _LANGS.get(Path(path).suffix.lower())


def read_source(path) -> str:
    """Decode a source file WITHOUT newline translation.

    web/ is CRLF on disk (MEASURED: web/js/main.js holds 7564 CRLF pairs) while
    Python text mode would fold those to LF on read and re-expand to os.linesep
    on write. Round-tripping through bytes is the only way a rewrite touches
    exactly the glyphs it meant to.
    """
    return Path(path).read_bytes().decode("utf-8")


def write_source(path, text: str) -> None:
    target = Path(path)
    tmp = target.with_suffix(target.suffix + ".rm125tmp")
    tmp.write_bytes(text.encode("utf-8"))
    tmp.replace(target)


def _is_ident(ch: str) -> bool:
    return ch.isalnum() or ch in _IDENT_EXTRA


def _regex_may_start(prev: str, prev_word: str) -> bool:
    if not prev:
        return True
    if _is_ident(prev):
        return prev_word in _REGEX_KEYWORDS
    return prev not in _VALUE_CLOSERS


def _scan_string(text: str, i: int, quote: str) -> int:
    """Index just past the string literal opening at `i`."""
    n = len(text)
    j = i + 1
    while j < n:
        ch = text[j]
        if ch == "\\":
            j += 2
            continue
        if ch == quote:
            return j + 1
        if ch in "\n\r":
            # Unterminated: JS and CSS strings do not span a raw newline, so
            # give the newline back to the scanner rather than swallowing the
            # rest of the file.
            return j
        j += 1
    return n


def _scan_comment(text: str, i: int) -> Optional[int]:
    """Index just past the JS comment opening at `i`, or None if `i` opens none.

    Shared by the top-level scanner (which records the span) and the `${}`
    scanner (which only needs to step over it), so the two can never drift on
    what counts as a comment open.
    """
    nxt = text[i + 1:i + 2]
    if nxt == "/":
        n = len(text)
        j = i + 2
        while j < n and text[j] not in "\n\r":
            j += 1
        return j
    if nxt == "*":
        end = text.find("*/", i + 2)
        return len(text) if end < 0 else end + 2
    return None


def _scan_template(text: str, i: int) -> int:
    n = len(text)
    j = i + 1
    while j < n:
        ch = text[j]
        if ch == "\\":
            j += 2
            continue
        if ch == "`":
            return j + 1
        if ch == "$" and j + 1 < n and text[j + 1] == "{":
            j = _scan_template_subst(text, j + 1)
            continue
        j += 1
    return n


def _scan_template_subst(text: str, i: int) -> int:
    """Index just past the `}` closing the `${` substitution opening at `i`.

    The interior is JS CODE, not template text, so a quote character can sit
    outside any string - inside a regex literal or inside a comment. Stepping
    over those as units is not a nicety: miss one and the quote reads as a
    string open, the substitution never finds its `}`, the enclosing template
    swallows the rest of the file, and every comment past that point classifies
    LIVE and is silently never swept. `/"/g` in an attribute-escaping
    `.replace()` blinded three panels that way.
    """
    n = len(text)
    j = i + 1
    depth = 1
    prev = ""
    prev_word = ""
    while j < n:
        ch = text[j]
        if ch == "/":
            end = _scan_comment(text, j)
            if end is None and _regex_may_start(prev, prev_word):
                end = _scan_regex(text, j)
            j = j + 1 if end is None else end
            prev, prev_word = "/", ""
            continue
        if ch == "\\":
            j += 2
            continue
        if ch in "\"'":
            j = _scan_string(text, j, ch)
            prev, prev_word = ch, ""
            continue
        if ch == "`":
            j = _scan_template(text, j)
            prev, prev_word = "`", ""
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return j + 1
        if not ch.isspace():
            prev = ch
            prev_word = (prev_word + ch) if _is_ident(ch) else ""
        j += 1
    return n


def _scan_regex(text: str, i: int) -> Optional[int]:
    """Index just past the regex literal opening at `i`, or None.

    None means "this `/` was not a regex after all" - a literal that never
    closes on its own line is division, and treating it as division is the
    fail-safe direction: the worst case is a comment we decline to sweep.
    """
    n = len(text)
    j = i + 1
    in_class = False
    while j < n:
        ch = text[j]
        if ch == "\\":
            j += 2
            continue
        if ch in "\n\r":
            return None
        if ch == "[":
            in_class = True
        elif ch == "]":
            in_class = False
        elif ch == "/" and not in_class:
            j += 1
            while j < n and text[j].isalpha():
                j += 1
            return j
        j += 1
    return None


def _merge(spans: list[Span], total: int) -> list[Span]:
    out: list[Span] = []
    for span in spans:
        if span.end <= span.start:
            continue
        if out and out[-1].kind == span.kind and out[-1].end == span.start:
            out[-1] = Span(out[-1].start, span.end, span.kind)
        else:
            out.append(span)
    if out:
        assert out[0].start == 0 and out[-1].end == total, "span coverage is not total"
    return out


def _scan_js(text: str) -> list[Span]:
    n = len(text)
    spans: list[Span] = []
    live_start = 0
    i = 0
    prev = ""
    prev_word = ""
    while i < n:
        ch = text[i]
        if ch == "/":
            j = _scan_comment(text, i)
            if j is not None:
                spans.append(Span(live_start, i, LIVE))
                spans.append(Span(i, j, COMMENT))
                live_start = i = j
                continue
            if _regex_may_start(prev, prev_word):
                j = _scan_regex(text, i)
                if j is not None:
                    i = j
                    prev, prev_word = "/", ""
                    continue
            prev, prev_word = "/", ""
            i += 1
            continue
        if ch in "\"'":
            i = _scan_string(text, i, ch)
            prev, prev_word = ch, ""
            continue
        if ch == "`":
            i = _scan_template(text, i)
            prev, prev_word = "`", ""
            continue
        if not ch.isspace():
            prev = ch
            prev_word = (prev_word + ch) if _is_ident(ch) else ""
        i += 1
    spans.append(Span(live_start, n, LIVE))
    return _merge(spans, n)


def _scan_css(text: str) -> list[Span]:
    n = len(text)
    spans: list[Span] = []
    live_start = 0
    i = 0
    while i < n:
        ch = text[i]
        if ch == "/" and text[i + 1:i + 2] == "*":
            end = text.find("*/", i + 2)
            j = n if end < 0 else end + 2
            spans.append(Span(live_start, i, LIVE))
            spans.append(Span(i, j, COMMENT))
            live_start = i = j
            continue
        if ch in "\"'":
            i = _scan_string(text, i, ch)
            continue
        i += 1
    spans.append(Span(live_start, n, LIVE))
    return _merge(spans, n)


def _scan_html(text: str) -> list[Span]:
    """`<!-- -->` only.

    .html files embed <script> and <style>, and their inner comments are left
    LIVE on purpose. Getting the raw-text-element boundary right (a `</script>`
    inside a JS string, CDATA, attribute-quoted markup) is real parser work, and
    it buys nothing here: MEASURED 2026-07-28, the two inline <script> blocks in
    web/index.html carry ZERO non-ASCII bytes, and web/legacy_index.html has no
    HTML comments at all. Under-sweeping costs a residue line in the report;
    mis-sweeping costs a rendered glyph.
    """
    n = len(text)
    spans: list[Span] = []
    live_start = 0
    i = 0
    while True:
        start = text.find("<!--", i)
        if start < 0:
            break
        end = text.find("-->", start + 4)
        j = n if end < 0 else end + 3
        spans.append(Span(live_start, start, LIVE))
        spans.append(Span(start, j, COMMENT))
        live_start = i = j
    spans.append(Span(live_start, n, LIVE))
    return _merge(spans, n)


_SCANNERS = {"js": _scan_js, "css": _scan_css, "html": _scan_html}


def scan(text: str, lang: str) -> list[Span]:
    try:
        scanner = _SCANNERS[lang]
    except KeyError:
        raise ValueError(f"unknown lang {lang!r}") from None
    return scanner(text)


def comment_spans(text: str, lang: str) -> list[tuple[int, int]]:
    return [(s.start, s.end) for s in scan(text, lang) if s.kind == COMMENT]


def live_text(text: str, lang: str) -> str:
    return "".join(text[s.start:s.end] for s in scan(text, lang) if s.kind == LIVE)


def sweep_text(text: str, lang: str) -> SweepResult:
    changes: list[Change] = []
    unmapped: list[Unmapped] = []
    out: list[str] = []
    cursor = 0
    for start, end in comment_spans(text, lang):
        for offset in range(start, end):
            ch = text[offset]
            if ord(ch) < 128:
                continue
            replacement = REPLACEMENTS.get(ch)
            if replacement is None:
                unmapped.append(Unmapped(offset, ch))
                continue
            out.append(text[cursor:offset])
            out.append(replacement)
            cursor = offset + 1
            changes.append(Change(offset, ch, replacement))
    out.append(text[cursor:])
    return SweepResult("".join(out), changes, unmapped)


def iter_sources(root) -> list[Path]:
    return [p for p in sorted(Path(root).rglob("*")) if p.is_file() and lang_for_path(p)]


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Sweep non-ASCII out of web/ comment spans.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="report only")
    mode.add_argument("--apply", action="store_true", help="rewrite in place")
    parser.add_argument("--root", default="web", help="tree to sweep (default: web)")
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.is_dir():
        print(f"web_ascii_sweep: no such directory: {root}", file=sys.stderr)
        return 2

    planned: list[tuple[Path, SweepResult]] = []
    failures: list[str] = []
    live_residue = 0
    for path in iter_sources(root):
        text = read_source(path)
        result = sweep_text(text, lang_for_path(path))
        rel = path.as_posix()
        for bad in result.unmapped:
            failures.append(
                f"{rel}:{_line_of(text, bad.offset)} offset={bad.offset} "
                f"U+{ord(bad.char):04X} has no REPLACEMENTS entry"
            )
        live_residue += sum(
            1 for s in scan(text, lang_for_path(path))
            if s.kind == LIVE for c in text[s.start:s.end] if ord(c) > 127
        )
        if result.changes:
            planned.append((path, result))

    total = sum(len(r.changes) for _, r in planned)
    for path, result in planned:
        print(f"{path.as_posix()}: {len(result.changes)} comment glyphs")
    print(f"comment-span glyphs: {total} across {len(planned)} files")
    print(f"live-span residue (left alone by design): {live_residue}")

    if failures:
        print(
            f"\nREFUSING TO WRITE - {len(failures)} comment glyph(s) absent from "
            f"REPLACEMENTS:", file=sys.stderr,
        )
        for line in failures:
            print(f"  {line}", file=sys.stderr)
        return 2

    if args.apply:
        for path, result in planned:
            write_source(path, result.text)
        print(f"applied to {len(planned)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
