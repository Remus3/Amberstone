"""RM-125: pin the web/ comment tokeniser used by tools/web_ascii_sweep.py.

A normalizer is only correct if you measure the side where it must NOT fire
(memory feedback_normalizer_check_false_positive_side). web/ carries Terminal-
theme UI glyphs on LIVE spans - CSS `content:` values, JS strings and template
literals, HTML text nodes and attribute values - and every one of those renders.
So the bulk of the fixtures below are FALSE-POSITIVE pins: constructs that look
comment-shaped to a naive scanner and must classify LIVE.

Glyph literals are spelled \\uXXXX so this file stays 7-bit ASCII itself.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import unittest
from pathlib import Path

from tools import web_ascii_sweep as sweeper
from tools.web_ascii_sweep import (
    COMMENT,
    LIVE,
    comment_spans,
    lang_for_path,
    live_text,
    read_source,
    scan,
    sweep_text,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WEB = _REPO_ROOT / "web"

# SHA-256 over "<relpath>\n<live-span text>\n" for every web/ source, newlines
# folded to LF.
#
# RE-CAPTURED at the `${}` regex/comment tokeniser fix, superseding the
# c7900b8c capture. It HAD to move: the digest is computed with the tokeniser's
# own classifier, and that fix corrected the comment/live partition (114 spans
# across 3 panels stopped being mis-read as LIVE). So the old value could not
# survive, and re-stamping it proves nothing on its own - the digest cannot
# police a change to the thing that computes it.
#
# What was measured instead, at the moment of the re-stamp: run the CORRECTED
# tokeniser over both the 525354ee tree and the swept tree and diff the live
# halves. They are byte-identical for all 168 web/ sources - one fixed
# classifier, two trees, so the comparison is not circular. The same diff under
# the OLD tokeniser flags web/js/panels/last_match.js, which is exactly the bug
# (it read a `/* */` banner as LIVE) and not a regression.
#
# It is pinned as a digest rather than read back out of git so the guard needs
# no history depth and can never degrade into a skip. If a later change
# legitimately edits a LIVE glyph in web/ this goes red on purpose: confirm the
# edit was intended, then re-capture with
#   python -c "import tests.test_web_ascii_sweep as t; print(t._live_half_digest())"
# A tokeniser change lands here too - re-run the two-tree diff above before
# trusting a fresh capture.
#
# RE-CAPTURED at R224 (RM-126, the overlay drag-listener leak fix), superseding
# the R223 capture. Ordinary case again: a LIVE web edit, no tokeniser change,
# so the classifier is fixed and the two-tree diff is a straight answer. Run
# over 08c8aade and the post-fix tree with the SAME tokeniser, exactly one of
# 165 web/ sources differs in its live half - web/js/lib/overlay_layout.js -
# which is the slice's whole file set and nothing else.
# RE-CAPTURED at the 16.14.1 -> 16.15.1 DDragon patch refresh, superseding the
# R224 capture. Ordinary case: a LIVE web edit, no tokeniser change, so the
# classifier is fixed and the two-tree diff is a straight answer. Run over HEAD
# and the refreshed tree with the SAME tokeniser, exactly one of 165 web/
# sources differs in its live half - web/js/lib/items_index.js, whose
# DDRAGON_FALLBACK_VERSION const is the slice's only web edit and nothing else.
_LIVE_HALF_DIGEST = "02edd9aabdf6f74220454742acf5e5afd00f9d00e7a5c057b8992a6c68f2c691"


def _web_sources() -> list[Path]:
    return [p for p in sorted(_WEB.rglob("*")) if p.is_file() and lang_for_path(p) is not None]


def _kind_at(text: str, lang: str, needle: str) -> str:
    """Span kind covering the first occurrence of `needle`."""
    offset = text.index(needle)
    for span in scan(text, lang):
        if span.start <= offset < span.end:
            return span.kind
    raise AssertionError(f"offset {offset} not covered by any span")


def _live_half_digest() -> str:
    digest = hashlib.sha256()
    for path in _web_sources():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        live = live_text(read_source(path), lang_for_path(path)).replace("\r\n", "\n")
        digest.update(rel.encode())
        digest.update(b"\n")
        digest.update(live.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


class SpansCoverTheWholeText(unittest.TestCase):
    def test_spans_are_contiguous_and_total(self) -> None:
        text = "a \u00b7 b // c \u2500\nd /* e \u2500 */ f\n"
        spans = scan(text, "js")
        self.assertEqual(spans[0].start, 0)
        self.assertEqual(spans[-1].end, len(text))
        for prev, nxt in zip(spans, spans[1:]):
            self.assertEqual(prev.end, nxt.start)
        self.assertEqual("".join(text[s.start:s.end] for s in spans), text)

    def test_lang_for_path(self) -> None:
        self.assertEqual(lang_for_path(Path("a/b.js")), "js")
        self.assertEqual(lang_for_path(Path("a/b.CSS")), "css")
        self.assertEqual(lang_for_path(Path("a/b.html")), "html")
        self.assertIsNone(lang_for_path(Path("a/b.py")))
        self.assertIsNone(lang_for_path(Path("a/b.json")))


class JsFalsePositivePins(unittest.TestCase):
    """Constructs that must NOT be swept."""

    def test_glyph_in_double_quoted_string_is_live(self) -> None:
        text = 'const a = "x \u2500 y";\n'
        self.assertEqual(_kind_at(text, "js", "\u2500"), LIVE)
        self.assertEqual(sweep_text(text, "js").changes, [])

    def test_glyph_in_single_quoted_string_is_live(self) -> None:
        text = "const a = 'x \u2192 y';\n"
        self.assertEqual(_kind_at(text, "js", "\u2192"), LIVE)
        self.assertEqual(sweep_text(text, "js").changes, [])

    def test_glyph_in_template_literal_is_live(self) -> None:
        text = "const a = `x \u00b7 ${v} \u2192 z`;\n"
        self.assertEqual(_kind_at(text, "js", "\u00b7"), LIVE)
        self.assertEqual(_kind_at(text, "js", "\u2192"), LIVE)
        self.assertEqual(sweep_text(text, "js").changes, [])

    def test_glyph_in_template_substitution_is_live(self) -> None:
        # `${}` can nest strings, braces and further templates; the whole
        # template is held LIVE rather than re-entering code mode inside it.
        text = "const a = `${o[`k \u2500`] || \"\u00b7\"} tail`;\n"
        self.assertEqual(_kind_at(text, "js", "\u2500"), LIVE)
        self.assertEqual(_kind_at(text, "js", "\u00b7"), LIVE)
        self.assertEqual(sweep_text(text, "js").changes, [])

    def test_double_slash_inside_a_string_does_not_open_a_comment(self) -> None:
        text = 'const u = "https://x.test/a";  // banner \u2500\u2500\n'
        self.assertEqual(_kind_at(text, "js", "https"), LIVE)
        self.assertEqual(_kind_at(text, "js", "// banner"), COMMENT)
        self.assertEqual(sweep_text(text, "js").text,
                         'const u = "https://x.test/a";  // banner --\n')

    def test_escaped_quote_does_not_terminate_the_string_early(self) -> None:
        text = 'const s = "a\\"//b\u2500"; // tail \u2500\n'
        self.assertEqual(_kind_at(text, "js", "//b"), LIVE)
        self.assertEqual(_kind_at(text, "js", "// tail"), COMMENT)
        result = sweep_text(text, "js")
        self.assertEqual(len(result.changes), 1)
        self.assertEqual(result.text, 'const s = "a\\"//b\u2500"; // tail -\n')

    def test_regex_literal_holding_a_block_comment_open_is_live(self) -> None:
        text = "const re = /a\\/\\*\u2500b/g;\nlet n = 1;\n"
        self.assertEqual(_kind_at(text, "js", "\u2500"), LIVE)
        self.assertEqual(sweep_text(text, "js").changes, [])

    def test_regex_literal_in_a_call_position_is_live(self) -> None:
        text = "if (/^[\u26a0\u2713\u25b6]?\\s*DEAD/i.test(s)) { n++; }\n"
        self.assertEqual(_kind_at(text, "js", "\u26a0"), LIVE)
        self.assertEqual(sweep_text(text, "js").changes, [])

    def test_html_comment_open_inside_js_is_not_a_comment(self) -> None:
        text = 'const s = "<!-- \u2500 -->";\n'
        self.assertEqual(_kind_at(text, "js", "\u2500"), LIVE)
        self.assertEqual(sweep_text(text, "js").changes, [])


class TemplateSubstitutionResync(unittest.TestCase):
    """A `${}` interior is JS CODE, so a bare quote can sit outside a string.

    Regex literals and comments both carry quotes that open nothing. Reading one
    as a string open desyncs the scanner, the template never closes, and every
    comment after it silently classifies LIVE - a guard that reports green by
    not looking. These pins measure the RESYNC point, not the interior: the
    substitution itself stays LIVE either way (that choice is pinned above by
    test_glyph_in_template_substitution_is_live), so the only observable is
    whether the code AFTER the template is tokenised at all.
    """

    def test_regex_literal_holding_quotes_does_not_run_the_template_away(self) -> None:
        text = ("const a = `x${s.replace(/['\"]/g, \"\")}y`;\n"
                "// banner \u2500\u2500\n")
        self.assertEqual(_kind_at(text, "js", "// banner"), COMMENT)
        self.assertEqual(sweep_text(text, "js").text,
                         "const a = `x${s.replace(/['\"]/g, \"\")}y`;\n// banner --\n")

    def test_the_shape_that_actually_shipped_in_web(self) -> None:
        # web/js/panels/last_match.js, champ_select.js and historical_pgr.js all
        # build attribute markup this way; the `/"/g` is what blinded the sweep.
        text = ('const li = `<li data-tt="${w.replace(/"/g, "&quot;")}">${t}</li>`;\n'
                "// tail \u2192 note\n")
        self.assertEqual(_kind_at(text, "js", "// tail"), COMMENT)
        self.assertEqual(_kind_at(text, "js", "data-tt"), LIVE)
        self.assertEqual(sweep_text(text, "js").text,
                         'const li = `<li data-tt="${w.replace(/"/g, "&quot;")}">${t}</li>`;\n'
                         "// tail -> note\n")

    def test_division_inside_a_substitution_is_not_read_as_a_regex(self) -> None:
        # The false-positive side of the same predicate: `/` after an identifier
        # is division, so it must not swallow the rest of the substitution.
        text = "const a = `${w / h} ratio`;\n// tail \u2500\n"
        self.assertEqual(_kind_at(text, "js", "\u2500"), COMMENT)
        self.assertEqual(_kind_at(text, "js", "ratio"), LIVE)
        self.assertEqual(sweep_text(text, "js").text,
                         "const a = `${w / h} ratio`;\n// tail -\n")

    def test_comment_holding_a_quote_does_not_run_the_template_away(self) -> None:
        text = "const a = `p${ f(/* don't */ x) }e`;\n// tail \u2500\n"
        self.assertEqual(_kind_at(text, "js", "// tail"), COMMENT)
        self.assertEqual(sweep_text(text, "js").text,
                         "const a = `p${ f(/* don't */ x) }e`;\n// tail -\n")

    def test_line_comment_holding_a_backtick_does_not_run_the_template_away(self) -> None:
        text = "const a = `p${ f(x) // a ` tick\n) }e`;\n// tail \u2500\n"
        self.assertEqual(_kind_at(text, "js", "// tail"), COMMENT)
        self.assertEqual(sweep_text(text, "js").changes[0].original, "\u2500")


class JsTruePositivePins(unittest.TestCase):
    """Constructs that MUST be swept."""

    def test_line_comment_glyph_is_swept(self) -> None:
        text = "// \u2500\u2500 Panel modules \u2500\u2500\nconst a = 1;\n"
        self.assertEqual(_kind_at(text, "js", "\u2500"), COMMENT)
        self.assertEqual(sweep_text(text, "js").text, "// -- Panel modules --\nconst a = 1;\n")

    def test_block_comment_glyph_is_swept(self) -> None:
        text = "/* refresh 1-2s \u2192 stale at ~4s \u00b7 severe */\nconst a = 1;\n"
        self.assertEqual(_kind_at(text, "js", "\u2192"), COMMENT)
        self.assertEqual(sweep_text(text, "js").text,
                         "/* refresh 1-2s -> stale at ~4s - severe */\nconst a = 1;\n")

    def test_division_does_not_swallow_the_following_comment(self) -> None:
        # `/` after an identifier is division, not a regex open - so the `//`
        # further along the line must still register as a comment.
        text = "const r = a / b; // note \u2500\n"
        self.assertEqual(_kind_at(text, "js", "// note"), COMMENT)
        self.assertEqual(sweep_text(text, "js").text, "const r = a / b; // note -\n")

    def test_unterminated_regex_falls_back_to_division(self) -> None:
        # A `/` in regex-allowed position whose literal never closes on the
        # same line is division; the trailing comment must survive.
        text = "const r = (a + b) / c; // note \u2500\n"
        self.assertEqual(_kind_at(text, "js", "// note"), COMMENT)
        self.assertEqual(sweep_text(text, "js").text, "const r = (a + b) / c; // note -\n")

    def test_unterminated_block_comment_runs_to_eof(self) -> None:
        text = "const a = 1;\n/* tail \u2500"
        self.assertEqual(_kind_at(text, "js", "\u2500"), COMMENT)
        self.assertEqual(sweep_text(text, "js").text, "const a = 1;\n/* tail -")


class CssPins(unittest.TestCase):
    def test_content_value_glyph_is_live(self) -> None:
        text = '.a::before { content: "\u2500-ish glyph"; }\n'
        self.assertEqual(_kind_at(text, "css", "\u2500"), LIVE)
        self.assertEqual(sweep_text(text, "css").changes, [])

    def test_block_comment_open_inside_a_css_string_is_live(self) -> None:
        text = '.a::before { content: "/* \u2500 */"; }\n'
        self.assertEqual(_kind_at(text, "css", "\u2500"), LIVE)
        self.assertEqual(sweep_text(text, "css").changes, [])

    def test_css_comment_glyph_is_swept(self) -> None:
        text = "/* \u2500\u2500\u2500 Footer \u2500\u2500\u2500 */\n.a { color: red; }\n"
        self.assertEqual(_kind_at(text, "css", "\u2500"), COMMENT)
        self.assertEqual(sweep_text(text, "css").text,
                         "/* --- Footer --- */\n.a { color: red; }\n")

    def test_css_has_no_line_comment(self) -> None:
        # `//` is not a CSS comment; a URL value must stay LIVE.
        text = ".a { background: url(https://x.test/i.png); }\n"
        self.assertEqual(comment_spans(text, "css"), [])


class HtmlPins(unittest.TestCase):
    def test_text_node_and_attribute_glyphs_are_live(self) -> None:
        text = '<p title="t \u00b7 u">text \u2192 node</p>\n'
        self.assertEqual(_kind_at(text, "html", "\u00b7"), LIVE)
        self.assertEqual(_kind_at(text, "html", "\u2192"), LIVE)
        self.assertEqual(sweep_text(text, "html").changes, [])

    def test_html_comment_glyph_is_swept(self) -> None:
        text = '<!-- s162: \u21bb AUTO pill removed -->\n<p>\u2665 -</p>\n'
        self.assertEqual(_kind_at(text, "html", "\u21bb"), COMMENT)
        self.assertEqual(_kind_at(text, "html", "\u2665"), LIVE)
        self.assertEqual(sweep_text(text, "html").text,
                         "<!-- s162: (R) AUTO pill removed -->\n<p>\u2665 -</p>\n")

    def test_embedded_script_and_style_comments_are_left_alone(self) -> None:
        # PINNED CHOICE: .html is tokenised with the HTML recogniser ONLY.
        # Modelling the <script>/<style> content-model boundary correctly (raw
        # text elements, `</script>` inside a JS string, CDATA) buys nothing
        # here - MEASURED 2026-07-28, the two inline <script> blocks in
        # web/index.html carry ZERO non-ASCII bytes. Under-sweeping is the safe
        # direction; mis-sweeping a live glyph is not.
        text = "<script>\n// js banner \u2500\n</script>\n<style>/* \u2500 */</style>\n"
        self.assertEqual(_kind_at(text, "html", "\u2500"), LIVE)
        self.assertEqual(sweep_text(text, "html").changes, [])


class FailLoudlyOnUnmappedGlyphs(unittest.TestCase):
    def test_unmapped_comment_glyph_is_reported_and_not_mangled(self) -> None:
        text = "// snow \u2603 here\nconst a = 1;\n"
        result = sweep_text(text, "js")
        self.assertEqual(result.changes, [])
        self.assertEqual([u.char for u in result.unmapped], ["\u2603"])
        self.assertEqual(result.unmapped[0].offset, text.index("\u2603"))
        self.assertEqual(result.text, text)

    def test_unmapped_glyph_on_a_live_span_is_not_reported(self) -> None:
        text = 'const a = "\u2603";\n'
        result = sweep_text(text, "js")
        self.assertEqual(result.unmapped, [])
        self.assertEqual(result.text, text)

    def test_cli_exits_nonzero_and_names_file_line_offset_codepoint(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "x.js"
            target.write_bytes("const a = 1;\n// snow \u2603\n".encode())
            proc = subprocess.run(
                [sys.executable, str(_REPO_ROOT / "tools" / "web_ascii_sweep.py"),
                 "--dry-run", "--root", tmp],
                capture_output=True, text=True, check=False,
            )
            out = proc.stdout + proc.stderr
            self.assertNotEqual(proc.returncode, 0, out)
            self.assertIn("x.js", out)
            self.assertIn(":2", out)
            self.assertIn("U+2603", out)
            self.assertIn(str("const a = 1;\n// snow \u2603\n".index("\u2603")), out)


class ByteFidelity(unittest.TestCase):
    def test_crlf_is_preserved(self) -> None:
        text = "// a \u2500\r\nconst x = 1;\r\n"
        out = sweep_text(text, "js").text
        self.assertEqual(out, "// a -\r\nconst x = 1;\r\n")
        self.assertEqual(out.count("\r\n"), text.count("\r\n"))

    def test_no_trailing_newline_is_added(self) -> None:
        text = "// a \u2500"
        self.assertEqual(sweep_text(text, "js").text, "// a -")

    def test_read_source_does_not_translate_newlines(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "x.css"
            target.write_bytes(b"/* a */\r\n.b { c: d; }\r\n")
            self.assertEqual(read_source(target), "/* a */\r\n.b { c: d; }\r\n")


class ReplacementMap(unittest.TestCase):
    def test_map_values_are_ascii(self) -> None:
        for key, value in sweeper.REPLACEMENTS.items():
            self.assertTrue(
                all(ord(c) < 128 for c in value),
                f"replacement for U+{ord(key):04X} is not ASCII",
            )

    def test_map_keys_are_single_non_ascii_chars(self) -> None:
        for key in sweeper.REPLACEMENTS:
            self.assertEqual(len(key), 1, repr(key))
            self.assertGreater(ord(key), 127, repr(key))


class WebTreeInvariants(unittest.TestCase):
    """Whole-tree pins - these are the RM-125 acceptance."""

    def test_sweep_is_idempotent_over_web(self) -> None:
        dirty: list[str] = []
        for path in _web_sources():
            text = read_source(path)
            result = sweep_text(text, lang_for_path(path))
            if result.changes or result.unmapped:
                dirty.append(f"{path.relative_to(_REPO_ROOT).as_posix()} "
                             f"changes={len(result.changes)} unmapped={len(result.unmapped)}")
        self.assertEqual(dirty, [], "web/ is not swept clean:\n" + "\n".join(dirty))

    def test_changes_only_ever_land_in_comment_spans(self) -> None:
        # One fixture carrying the same glyph on BOTH sides of every construct
        # the tokeniser knows, so the containment property is measured rather
        # than inferred from sweep_text's control flow.
        text = (
            "// lead \u2500\n"
            'const s = "keep \u2500";\n'
            "const t = `keep \u2500 ${x} \u2500`;\n"
            "const re = /keep\u2500/g;\n"
            "/* mid \u2500 */\n"
            "const u = 'keep \u2500';  // trail \u2500\n"
        )
        spans = comment_spans(text, "js")
        result = sweep_text(text, "js")
        self.assertEqual(len(result.changes), 3, "expected exactly the 3 comment glyphs")
        for change in result.changes:
            self.assertTrue(
                any(s <= change.offset < e for s, e in spans),
                f"offset {change.offset} is outside every comment span",
            )
        self.assertEqual(result.text.count("\u2500"), 5, "a live glyph was swept")

    def test_live_half_digest_matches_the_pre_sweep_capture(self) -> None:
        # THE acceptance for RM-125: the concatenated LIVE half of web/ hashes
        # to the value captured before the sweep ran.
        self.assertEqual(
            _live_half_digest(),
            _LIVE_HALF_DIGEST,
            "web/ LIVE spans drifted - a rendered byte changed. See the "
            "re-capture note on _LIVE_HALF_DIGEST.",
        )


if __name__ == "__main__":
    unittest.main()
