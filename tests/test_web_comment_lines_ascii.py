"""RM-125: every COMMENT-span character under web/ must be 7-bit ASCII.

web/ carried 3153 non-ASCII characters across 31 .js/.css/.html files. The
majority are deliberate Terminal-theme UI glyphs sitting on LIVE spans - CSS
`content:` values, JS template literals that build visible labels, HTML text
nodes and attribute values - and rewriting those changes rendered pixels.
Comments render nothing, so the comment half is the rendered-output-neutral
subset and is the only half this guard covers. The live half is deliberately
out of scope; see tests/test_web_ascii_sweep.py for the pin that proves the
sweep left it byte-identical.

Scope note: this is a whole-tree guard, not a per-file allowlist. Any new
web/ source is covered the moment it lands.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from tools.web_ascii_sweep import comment_spans, lang_for_path, read_source

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WEB = _REPO_ROOT / "web"


def _web_sources() -> list[Path]:
    return [p for p in sorted(_WEB.rglob("*")) if p.is_file() and lang_for_path(p) is not None]


class WebCommentSpansAreAscii(unittest.TestCase):
    def test_sources_are_discovered(self) -> None:
        # A tokeniser that classified nothing would make the guard below pass
        # vacuously, so pin that the corpus is non-empty and covers all three
        # languages.
        sources = _web_sources()
        self.assertTrue(_WEB.is_dir(), f"missing {_WEB}")
        self.assertGreater(len(sources), 100, "web/ source discovery collapsed")
        langs = {lang_for_path(p) for p in sources}
        self.assertEqual(langs, {"js", "css", "html"})

    def test_every_comment_char_is_ascii(self) -> None:
        offenders: list[str] = []
        total = 0
        per_file: dict[str, int] = {}
        for path in _web_sources():
            rel = path.relative_to(_REPO_ROOT).as_posix()
            text = read_source(path)
            lang = lang_for_path(path)
            for start, end in comment_spans(text, lang):
                for offset in range(start, end):
                    codepoint = ord(text[offset])
                    if codepoint > 127:
                        total += 1
                        per_file[rel] = per_file.get(rel, 0) + 1
                        line = text.count("\n", 0, offset) + 1
                        offenders.append(f"{rel}:{line} offset={offset} U+{codepoint:04X}")
        if offenders:
            worst = sorted(per_file.items(), key=lambda kv: -kv[1])[:10]
            summary = "\n".join(f"  {n:5d} {f}" for f, n in worst)
            self.fail(
                f"{total} non-ASCII chars in comment spans across {len(per_file)} files.\n"
                f"Worst files:\n{summary}\n"
                f"First 20 offenders:\n" + "\n".join(offenders[:20])
            )


# The defect class is "non-ASCII in authored .js/.css/.html", and web/ is where
# it concentrates, not where it ends. A whole-repo enumeration found exactly one
# authored file outside web/ carrying the class; everything else that scanned
# dirty is third-party (data/meta_build scraped pages, .obsidian vendored
# plugins, node_modules), which the repo rule does not govern.
_NON_WEB_AUTHORED = ("tools/usage-mcp-server.js",)


class NonWebAuthoredSourcesAreAscii(unittest.TestCase):
    def test_the_enumerated_files_still_exist(self) -> None:
        # A renamed or deleted file would silently drop out of the guard below.
        for rel in _NON_WEB_AUTHORED:
            self.assertTrue((_REPO_ROOT / rel).is_file(), f"missing {rel}")

    def test_every_comment_char_is_ascii(self) -> None:
        offenders: list[str] = []
        for rel in _NON_WEB_AUTHORED:
            path = _REPO_ROOT / rel
            text = read_source(path)
            lang = lang_for_path(path)
            self.assertIsNotNone(lang, f"{rel} is not a language this tokeniser knows")
            for start, end in comment_spans(text, lang):
                for offset in range(start, end):
                    codepoint = ord(text[offset])
                    if codepoint > 127:
                        line = text.count("\n", 0, offset) + 1
                        offenders.append(f"{rel}:{line} offset={offset} U+{codepoint:04X}")
        self.assertEqual(offenders, [], f"{len(offenders)} non-ASCII comment chars:\n" + "\n".join(offenders[:20]))


if __name__ == "__main__":
    unittest.main()
