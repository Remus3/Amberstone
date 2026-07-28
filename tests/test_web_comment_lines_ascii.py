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


if __name__ == "__main__":
    unittest.main()
