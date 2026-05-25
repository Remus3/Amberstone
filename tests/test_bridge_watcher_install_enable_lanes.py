"""Drift guard: tools/bridge_watcher_install.ps1 -EnableLanes param + pass-through.

Closes item 188 carry (j) prep work owed for Slice G recipe invocation per
docs/AUTO_ACTION_LANES_ENABLE_RECIPE.md. Frozen-file grant per item 189.

The -EnableLanes param accepts "", "read", "ops", "read,ops", "ops,read"
(matches bridge_watcher.py --enable-auto-action-lanes argparse semantics at
tools/bridge_watcher.py:1083). Empty (default) is no-op; classifier never
returns auto-* lanes.

If a future maintainer removes the param or rips the pass-through, the
recipe at docs/AUTO_ACTION_LANES_ENABLE_RECIPE.md becomes inert and the
gate at item 188 carry (j) re-opens. Pin both surfaces here.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL_PS1 = ROOT / "tools" / "bridge_watcher_install.ps1"


def _read_install_ps1() -> str:
    return INSTALL_PS1.read_text(encoding="utf-8")


class EnableLanesParamTests(unittest.TestCase):

    def test_install_ps1_exists(self) -> None:
        self.assertTrue(INSTALL_PS1.is_file(),
                        f"expected frozen file at {INSTALL_PS1}")

    def test_enable_lanes_param_declared(self) -> None:
        # The [string]$EnableLanes = "" line must be present in the param() block.
        text = _read_install_ps1()
        self.assertRegex(text, r'\[string\]\$EnableLanes\s*=\s*""',
                         "expected '[string]$EnableLanes = \"\"' declaration")

    def test_enable_lanes_validateset(self) -> None:
        # ValidateSet must cover the same lane tokens that bridge_watcher.py accepts.
        text = _read_install_ps1()
        match = re.search(
            r'\[ValidateSet\(([^)]+)\)\]\s*\r?\n\s*\[string\]\$EnableLanes',
            text)
        self.assertIsNotNone(match, "expected ValidateSet attribute on $EnableLanes")
        # Quoted strings are the actual tokens; comma-split would mis-segment
        # the "read,ops" / "ops,read" combined tokens.
        tokens = set(re.findall(r'"([^"]*)"', match.group(1)))
        self.assertEqual(tokens, {"", "read", "ops", "read,ops", "ops,read"})

    def test_lanes_arg_conditional_injection(self) -> None:
        # The $LanesArg variable must be conditionally set BEFORE the XML template.
        text = _read_install_ps1()
        self.assertIn('$LanesArg = ""', text,
                      "expected '$LanesArg = \"\"' init")
        self.assertRegex(
            text,
            r'if \(\$EnableLanes\)\s*\{\s*\r?\n\s*\$LanesArg\s*=\s*'
            r'" --enable-auto-action-lanes \$EnableLanes"',
            "expected conditional set of $LanesArg with --enable-auto-action-lanes flag")

    def test_lanes_arg_passed_to_watcher(self) -> None:
        # The scheduled task XML Arguments line must end with $LanesArg.
        text = _read_install_ps1()
        self.assertRegex(
            text,
            r'--data-dir "\$InstallDir" --log-dir "\$InstallDir\\logs" --poll 15\$LanesArg',
            "expected $LanesArg trailing the watcher --poll arg in the XML Arguments")

    def test_bridge_watcher_py_consumes_flag(self) -> None:
        # Sanity: the bridge_watcher.py argparse target still exists. If this
        # ever changes, the install script param + this test must be updated
        # together.
        bw = ROOT / "tools" / "bridge_watcher.py"
        self.assertTrue(bw.is_file())
        bw_text = bw.read_text(encoding="utf-8")
        self.assertIn('"--enable-auto-action-lanes"', bw_text,
                      "bridge_watcher.py must still define --enable-auto-action-lanes")

    def test_header_example_documents_param(self) -> None:
        # Operator-facing example MUST surface the -EnableLanes flag so a fresh
        # operator finds it without spelunking the param() block.
        text = _read_install_ps1()
        self.assertIn("-EnableLanes read,ops", text,
                      "expected example invocation '-EnableLanes read,ops' in header comment")

    def test_no_banned_codepoints(self) -> None:
        # CLAUDE.md hard rule: no em-dashes (U+2014), en-dashes (U+2013),
        # or smart quotes (U+2018/2019/201C/201D). The pre-existing U+2500
        # box-drawing dividers + U+00A7 + U+FEFF BOM are intentional and
        # operator-classified intentional per items 176 + 188 U+2500 sweeps.
        BANNED = {0x2014, 0x2013, 0x2018, 0x2019, 0x201C, 0x201D}
        text = _read_install_ps1()
        for i, ch in enumerate(text):
            self.assertNotIn(
                ord(ch), BANNED,
                f"banned codepoint U+{ord(ch):04X} at install.ps1 offset {i}")


if __name__ == "__main__":
    unittest.main()
