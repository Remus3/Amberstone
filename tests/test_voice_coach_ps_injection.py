"""voice_coach must never let speech text become PowerShell code.

`coaches/voice_coach.py` speaks through a powershell.exe child. It used to
build the script by single-quoting the text and doubling ASCII `'` only. But
PowerShell 5.1 also ends a single-quoted string on U+2018 / U+2019 / U+201A /
U+201B, so a text such as  x<U+2019>); Write-Output INJECTED; (<U+2019>  closed
the literal and ran the command between - command injection through POST
/api/speak, which is not a control endpoint, needs no token and is reachable
by any script caller that can reach :8888.

The fix is not a wider escape table: the script is a constant and the text
travels out of band, in the child's environment, where PowerShell reads it as
a plain string and never parses it.

Spy shape: speak() wraps its launch in `except Exception`, so these tests use
a RECORDING Popen spy plus the return value, never a raise-based spy (memory:
reference_raise_based_spy_is_vacuous_under_fail_soft). Source stays ASCII; the
curly quotes are built with chr().
"""
from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from coaches import voice_coach
from core import live_game_gate

_REAL_POPEN = subprocess.Popen
_QUOTES = ("'", chr(0x2018), chr(0x2019), chr(0x201A), chr(0x201B))

# Each payload tries to end the literal (or the Speak( call) and run a marker
# command. Paren-closing forms are the ones that actually parse inside
# $s.Speak(...); the bare forms cover a script shape without the call parens.
PAYLOADS = tuple(
    [f"x{q}); Write-Output INJECTED; ({q}" for q in _QUOTES]
    + [f"x{q}; Write-Output INJECTED; {q}" for q in _QUOTES]
    + [
        'x"); Write-Output INJECTED; ("',
        "x $(Write-Output INJECTED) y",
        "x; Write-Output INJECTED",
        "x `); Write-Output INJECTED; (` y",
        "x\n); Write-Output INJECTED; (\ny",
    ]
)


class _PopenSpy:
    """Recording stand-in for subprocess.Popen. Never raises."""

    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return mock.MagicMock()


def _argv(call) -> list:
    args, kwargs = call
    return list(args[0] if args else kwargs["args"])


class _Base(unittest.TestCase):
    def setUp(self):
        self.spy = _PopenSpy()
        for p in (
            mock.patch.object(voice_coach.subprocess, "Popen", self.spy),
            mock.patch.object(live_game_gate, "live_game_now", return_value=False),
        ):
            p.start()
            self.addCleanup(p.stop)

    def _speak(self, text: str, rate: int = 0):
        # speak() keeps module-level dedup + rate-limit state; reset it so
        # every payload actually reaches the spawn.
        voice_coach._LAST_TS = 0.0
        voice_coach._LAST_TEXT = ""
        spoke = voice_coach.speak(text, rate=rate)
        self.assertTrue(spoke, f"speak() refused {text!r}")
        return self.spy.calls[-1]


class ScriptIsConstantTests(_Base):
    def test_no_caller_bytes_reach_the_command_line(self):
        for text in PAYLOADS:
            with self.subTest(text=text):
                argv = _argv(self._speak(text))
                joined = "\x00".join(argv)
                self.assertNotIn("INJECTED", joined)
                for q in _QUOTES[1:]:
                    self.assertNotIn(q, joined)

    def test_script_is_identical_for_every_text(self):
        scripts = {_argv(self._speak(t))[-1] for t in PAYLOADS + ("hello",)}
        self.assertEqual(len(scripts), 1, scripts)

    def test_text_travels_in_the_child_environment_verbatim(self):
        for text in PAYLOADS:
            with self.subTest(text=text):
                _args, kwargs = self._speak(text)
                env = kwargs.get("env")
                self.assertIsInstance(env, dict, "no env passed to the child")
                self.assertIn(text.strip(), env.values())

    def test_child_environment_keeps_the_parent_environment(self):
        # powershell.exe needs SystemRoot / PATH; a bare env breaks the spawn.
        _args, kwargs = self._speak("hello")
        env = kwargs["env"]
        for key, val in os.environ.items():
            self.assertEqual(env.get(key), val, key)

    def test_rate_reaches_the_child_without_entering_the_script(self):
        _args, kwargs = self._speak("hello", rate=-3)
        self.assertIn("-3", kwargs["env"].values())
        self.assertNotIn("-3", _argv(self.spy.calls[-1])[-1])

    def test_spawn_shape_is_unchanged(self):
        args, kwargs = self._speak("hello")
        argv = _argv((args, kwargs))
        self.assertEqual(argv[:6], ["powershell.exe", "-NoProfile", "-NonInteractive",
                                    "-WindowStyle", "Hidden", "-Command"])
        self.assertEqual(kwargs.get("creationflags"), 0x08000000)
        self.assertIs(kwargs.get("stdin"), subprocess.DEVNULL)
        self.assertIs(kwargs.get("stdout"), subprocess.DEVNULL)
        self.assertIs(kwargs.get("stderr"), subprocess.DEVNULL)

    def test_length_cap_still_applies_to_the_out_of_band_text(self):
        _args, kwargs = self._speak("a" * 500)
        self.assertIn("a" * voice_coach._MAX_CHARS, kwargs["env"].values())
        self.assertNotIn("a" * (voice_coach._MAX_CHARS + 1), kwargs["env"].values())


_PS51 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / \
    "WindowsPowerShell" / "v1.0" / "powershell.exe"

# Swaps the SAPI synthesizer for an object whose Speak() echoes its argument,
# so the module's own script runs end to end without making a sound.
_STUB_SYNTH = (
    "(New-Object PSObject | Add-Member -PassThru NoteProperty Rate 0 | "
    "Add-Member -PassThru ScriptMethod Speak { param($t) 'SPOKE:' + $t })"
)


@unittest.skipUnless(os.name == "nt" and _PS51.is_file(),
                     "needs Windows PowerShell 5.1")
class PowerShellEndToEndTests(_Base):
    """Runs the module's real script and env through powershell.exe 5.1 with
    the synthesizer stubbed, and proves the marker never runs as a command."""

    def _run_stubbed(self, call) -> list:
        args, kwargs = call
        script = _argv((args, kwargs))[-1]
        self.assertIn("New-Object System.Speech.Synthesis.SpeechSynthesizer", script)
        stub = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
                + script.replace("Add-Type -AssemblyName System.Speech;", "")
                .replace("New-Object System.Speech.Synthesis.SpeechSynthesizer",
                         _STUB_SYNTH))
        # The Popen spy patches the shared subprocess module, so the real
        # spawn needs the real Popen back for this one call.
        with mock.patch.object(subprocess, "Popen", _REAL_POPEN):
            r = subprocess.run(
                [str(_PS51), "-NoProfile", "-NonInteractive", "-Command", stub],
                env=kwargs.get("env"), capture_output=True, timeout=60,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        return r.stdout.decode("utf-8", "replace").splitlines()

    def test_quote_break_payloads_never_execute(self):
        for text in PAYLOADS:
            with self.subTest(text=text):
                lines = [ln.strip() for ln in self._run_stubbed(self._speak(text))]
                self.assertNotIn("INJECTED", lines, lines)

    def test_negative_control_text_is_spoken_verbatim(self):
        """Without this the injection assertion is vacuous: a script that
        never reaches Speak() would print nothing and pass it."""
        text = "x" + chr(0x2019) + "); Write-Output INJECTED; (" + chr(0x2019)
        out = "\n".join(self._run_stubbed(self._speak(text)))
        self.assertIn("SPOKE:" + text, out)


if __name__ == "__main__":
    unittest.main()
