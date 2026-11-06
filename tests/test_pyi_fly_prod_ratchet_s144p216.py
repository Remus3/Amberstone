"""RM-1724 - ruff PYI034 and FLY002 held at zero in production code.

Not selected by ruff.toml. Measured 2026-11-06 with ``ruff check --isolated`` (target py39) over the tracked
production code, with ``docs/`` left out (``docs/_rescore/tally.py`` is a dated research artifact):

- PYI034: ``core/coaching_data_lock.py`` ``_CombinedLock.__enter__`` returned the class by name; a subclass
  would be typed as the base. It returns ``Self`` now (imported under ``TYPE_CHECKING`` so nothing changes at
  runtime and the repo's 3.9 ruff target is untouched).
- FLY002: ``tft/tft_prompt.py`` ``_assemble`` built the same prompt twice with ``"\\n\\n".join((...))`` over
  a fixed tuple; both are f-strings now. The output bytes are pinned below against the join spelling.

Scope: tracked ``.py`` files. ``tests/``, any ``*/tests/`` directory, ``docs/``, ``agents/daemon_slayer``, the
vendored ``ops/fleet_kit`` and ``agents/agent3_testing/suite`` are out of scope. The run uses NO config
(``--isolated``), so a per-file-ignore cannot hide a finding. The baseline is empty and only shrinks.
"""
from __future__ import annotations

import collections
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

_RULES = "PYI034,FLY002"
_OUT_OF_SCOPE = (
    "tests/",
    "tools/tests/",
    "docs/",
    "agents/daemon_slayer/",
    "agents/agent3_testing/suite/",
    "ops/fleet_kit/",
)
_BASELINE: dict[str, int] = {}


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", _RULES, *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def tree_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_OUT_OF_SCOPE) and "/tests/" not in rel:
            counts[rel] += 1
    return dict(counts)


def test_no_new_findings(tree_counts):
    extra = {f: n for f, n in tree_counts.items() if n > _BASELINE.get(f, 0)}
    assert not extra, f"ruff {_RULES} findings beyond the baseline, file: count: {extra}"


def test_baseline_is_exact(tree_counts):
    stale = {f: n for f, n in _BASELINE.items() if tree_counts.get(f, 0) != n}
    assert not stale, f"baseline rows to shrink or drop (file: recorded): {stale}"


def test_probe_is_live():
    """The isolated run reports a minimal offender per rule, so an empty tree result is a real scan."""
    probe = (
        "class A:\n"
        "    def __enter__(self) -> 'A':\n"
        "        return self\n"
        "\n"
        "x = '\\n'.join(('a', 'b'))\n"
    )
    found = {d["code"] for d in _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=probe)}
    assert found == {"PYI034", "FLY002"}


def test_assemble_output_is_the_join_spelling():
    """The f-string spelling of _assemble yields the same bytes the join spelling did."""
    from tft import tft_prompt as tp

    src = (REPO_ROOT / "tft" / "tft_prompt.py").read_text(encoding="utf-8")
    assert '"\\n\\n".join((_HEAD' not in src
    sep = "\n\n"
    for prof in (tp._no_data(16, "tft_set16_meta.json"), tp.set_profile()):
        meta = tp._meta_line(prof)
        output = tp._OUTPUT.format(label=prof.pick_label, desc=tp._PICK_DESC[prof.pick_label])
        fixed = sep.join((tp._HEAD, "", meta, tp._RULES, output))
        block = tp._set_block(prof, tp.MAX_PROMPT_CHARS - len(fixed) - 4)
        assert tp._assemble(prof) == sep.join((tp._HEAD, block, meta, tp._RULES, output))


def test_combined_lock_enter_is_typed_self():
    src = (REPO_ROOT / "core" / "coaching_data_lock.py").read_text(encoding="utf-8")
    assert 'def __enter__(self) -> "_CombinedLock":' not in src
    assert 'def __enter__(self) -> "Self":' in src
