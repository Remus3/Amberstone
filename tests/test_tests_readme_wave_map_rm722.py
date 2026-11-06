"""Guard: tests/README.md maps every deep-audit wave / slice test file (RM-722 (e)).

The deep-audit waves named their regression modules by wave and slice
(``test_p2w1_core_a.py`` is P2 wave 1, core, slice A), which says nothing to a
reader who was not there. ``tests/README.md`` is the map from each such file to
what it pins. This guard keeps the map whole:

* every ``tests/test_p2w<N>_*.py`` module is named in the README, and
* every ``test_p2w<N>_*.py`` name the README mentions is a file that exists,

so a new wave module cannot land unmapped and a renamed or deleted one cannot
leave a dead row behind.
"""
from __future__ import annotations

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent
README = TESTS / "README.md"

_WAVE_FILE = re.compile(r"^test_p2w\d+_[a-z0-9_]+\.py$")
_WAVE_NAME_IN_README = re.compile(r"\btest_p2w\d+_[a-z0-9_]+\.py\b")


def _wave_files() -> set[str]:
    return {p.name for p in TESTS.glob("test_p2w*.py") if _WAVE_FILE.match(p.name)}


def _readme_text() -> str:
    assert README.is_file(), "tests/README.md is the wave / slice map (RM-722 (e))"
    return README.read_text(encoding="utf-8")


def test_the_wave_family_is_not_empty():
    # An empty enumeration would pass both checks below vacuously.
    assert len(_wave_files()) >= 30


def test_every_wave_module_is_mapped():
    text = _readme_text()
    unmapped = sorted(n for n in _wave_files() if n not in text)
    assert not unmapped, f"add these to tests/README.md: {unmapped}"


def test_the_readme_names_only_real_wave_modules():
    named = set(_WAVE_NAME_IN_README.findall(_readme_text()))
    assert named, "the README maps no wave module"
    dead = sorted(named - _wave_files())
    assert not dead, f"tests/README.md names files that do not exist: {dead}"


def test_the_readme_is_ascii_and_lf_only():
    raw = README.read_bytes()
    assert raw.isascii()
    assert b"\r" not in raw
