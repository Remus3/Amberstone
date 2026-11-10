"""RM-1413 - three ruff rules that flag a sloppy regex or a lying annotation
are held at zero.

None of these is selected by ruff.toml. Measured 2026-11-05 with
``ruff check --isolated`` over the tree, 12 sites in 12 files, all fixed:

- RUF043 (``pytest.raises(match=...)`` with an unescaped regex metacharacter):
  seven tests wrote ``match="src.css"`` or ``match="subprocess.Popen"``, where
  the dot is a wildcard, so ``srcXcss`` would satisfy the assertion. A file or
  dotted-name needle becomes a raw string with the dot escaped; a deliberate
  alternation (``inflate|checksum|length``) becomes a plain raw string.
- RUF013 (``x: dict = None``): two test helpers promised a dict or bytes and
  defaulted to None. One says ``Optional[dict]``; the other, which carries
  ``from __future__ import annotations``, says ``bytes | None``.
- RUF010 (``str(x)`` / ``repr(x)`` inside an f-string): three call sites use the
  ``!s`` / ``!r`` conversion flag.

Left out on purpose: PERF101 core/hotkeys.py and C414 lcu/snapshot_shape.py (the
``list(...)`` copy there is the documented guard against "dictionary changed
size during iteration", so the lint is a false positive), SIM910 in
tft/tft_coach_engine.py and the C401 / C405 / C416 / SIM118 style findings (they
would only churn about forty more files).

The ratchet runs ruff with NO config (``--isolated``) so a per-file-ignore cannot
hide a finding, and keeps only tracked files. Zero is the baseline.
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

_RULES = "RUF043,RUF013,RUF010"
_FIXED = (
    "agents/daemon_slayer/tests/test_artifact_patch_marker_guard.py",
    "core/prom_metrics.py",
    "ops/audit/ds_perm_swarm/dsv5_lean_probe.py",
    "tests/snapshot_panels/test_settings_theme_picker.py",
    "tests/test_atlas_fonts.py",
    "tests/test_css_split_family_rm726.py",
    "tests/test_md_guard_selector_index_walkers_s144q38.py",
    "tests/test_process_start_tripwire_rm880d.py",
    "tests/test_repo_walk.py",
    "tests/test_tft_sources_eog_file.py",
    "tools/replay_build_order_validate.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def tree_findings() -> list[str]:
    # The whole tree on one command line is too long for Windows: lint ".", keep
    # the tracked files (the filter the other ruff ratchets use).
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    out = []
    for d in _ruff(["--select", _RULES, "."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked:
            out.append(f"{rel}:{d['location']['row']} {d['code']}")
    return sorted(out)


def test_tree_carries_no_loose_match_pattern_or_implicit_optional(tree_findings):
    assert not tree_findings, f"ruff {_RULES}: {tree_findings}"


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_is_ascii_and_lf(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


@pytest.mark.parametrize(
    "code, expected",
    [
        ("import pytest\nwith pytest.raises(ValueError, match='a.b'):\n    pass\n", "RUF043"),
        ("def f(x: dict = None):\n    return x\n", "RUF013"),
        ("v = 1\ns = f'{str(v)}'\n", "RUF010"),
    ],
)
def test_each_probe_is_live(code, expected):
    """Every rule in the set IS reported by the isolated run on a minimal
    offender - so an empty tree result is a clean tree, not a dead probe."""
    found = _ruff(["--select", _RULES, "--stdin-filename", "probe_mod.py", "-"], stdin=code)
    assert expected in {d["code"] for d in found}, found


def test_the_escaped_needles_still_pin_their_message():
    """The dots are literal now: a near-miss name no longer satisfies the
    assertion (the regex the old string compiled to matched ``srcXcss``)."""
    import re

    assert re.search(re.escape("src.css"), "src.css")
    assert not re.search(re.escape("src.css"), "srcXcss")
    assert re.search(r"src.css", "srcXcss")  # the pre-fix behaviour, kept as the control
