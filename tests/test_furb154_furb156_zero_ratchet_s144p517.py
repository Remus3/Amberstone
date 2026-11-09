"""FURB154 (repeated ``global``) and FURB156 (hardcoded charset) hold at zero (S144-P-517).

Both are ruff PREVIEW rules and ruff.toml selects neither, so nothing held the count. FURB154 flags two or
more consecutive ``global`` statements (one statement lists every name); FURB156 flags a string literal that
spells out a ``string`` module constant (``"0123456789"`` is ``string.digits``, ``"01234567"`` is
``string.octdigits``, ``"0123456789abcdefABCDEF"`` is ``string.hexdigits``).

Measured 2026-11-09 with ``ruff check --isolated --preview`` (target py39) over every tracked ``.py`` file
(production, ``tests/``, ``tools/tests``, ``agents/daemon_slayer`` and ``agents/agent3_testing`` included): 10
findings in 8 files, all fixed here with no behaviour change (the charsets are equal as strings or sets):
FURB154 in core/coaching_data_lock.py (2), core/daemon_slayer_resolver.py (1) and core/smoothed_rates_101qq.py
(2); FURB156 in agents/agent7_context/input_parser.py, core/vision_tesseract.py, tft/cv/ocr_fields.py,
tools/inbox_responder.py and tests/test_loop_status_route_lane8_cycle68.py. The baseline is empty, so it can
only stay empty.

``ops/fleet_kit`` (vendored byte-for-byte) is out of scope. The run uses NO config (``--isolated``) so a
per-file-ignore cannot hide a finding. A probe pair per rule proves the preview selection is live: an empty
tree result is then a real scan, not a rule that silently stopped being selectable.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="ruff is not importable by this interpreter",
)

_RULES = "FURB154,FURB156"
_OUT_OF_SCOPE = ("ops/fleet_kit/",)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--preview", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", _RULES, *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, check=False, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


def test_tree_has_no_findings():
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    found = []
    for d in _ruff(["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_OUT_OF_SCOPE):
            found.append(f"{rel}:{d['location']['row']} {d['code']}")
    assert not found, f"FURB154 / FURB156 findings (spell them out; the baseline is empty): {sorted(found)}"


def _probe(src: str) -> set[str]:
    return {d["code"] for d in _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=src)}


def test_probe_sees_a_repeated_global():
    assert _probe("a = b = 0\n\n\ndef f():\n    global a\n    global b\n    a = b = 1\n") == {"FURB154"}


def test_probe_sees_a_hardcoded_digit_charset():
    assert _probe('DIGITS = "0123456789"\n') == {"FURB156"}


def test_probe_sees_a_hardcoded_hex_charset():
    assert _probe('HEX = set("0123456789abcdefABCDEF")\n') == {"FURB156"}


def test_one_global_statement_and_the_string_constant_are_quiet():
    assert _probe(
        "import string\n\na = b = 0\n\n\ndef f():\n    global a, b\n    a = b = 1\n\n\nDIGITS = string.digits\n"
    ) == set()
