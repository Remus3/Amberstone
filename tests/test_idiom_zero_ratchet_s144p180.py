"""RM-1694 - six ruff rules held at zero over the whole tree: SIM905, FURB122, PT021, PT028, PT030, SLOT000.

None is selected by ruff.toml. Measured 2026-11-05 with ``ruff check --isolated`` (target py39), 11 findings in 9
files and none anywhere else (the DS package and the vendored kit were already clean for these rules):

- SIM905: ``tools/citation_audit.py`` built ``_STOPWORDS`` from a triple-quoted ``.split()``; it is a tuple of
  literals now (the frozenset is element-for-element identical, 120 words).
- FURB122: three ``for ...: f.write(x)`` loops in tests became ``f.writelines(generator)``.
- PT021: the module-scoped ``control`` fixture of ``tests/test_live_write_tracer_selftest.py`` used
  ``request.addfinalizer(monkeypatch.undo)``; it yields inside ``pytest.MonkeyPatch.context()`` now (undo still
  runs once, at module teardown; the private base is still left right after the plant).
- PT028: a test parameter with a default (``level=13.0``) is a local now.
- PT030: ``pytest.warns(UserWarning)`` in ``tests/test_lfs_policy_rm509.py`` now pins the warning text.
- SLOT000: three ``str`` subclass test doubles gained ``__slots__ = ()``.

The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding. The baseline is empty on purpose:
a new finding fails, there is nothing to shrink.
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

_RULES = ("SIM905", "FURB122", "PT021", "PT028", "PT030", "SLOT000")
_FIXED = (
    "tests/test_aram_deterministic_coach_true_audit_s144.py",
    "tests/test_arena_deterministic_coach_true_audit_s144.py",
    "tests/test_decisions_log_tail_rm238.py",
    "tests/test_lfs_policy_rm509.py",
    "tests/test_live_write_tracer_selftest.py",
    "tests/test_precomputed_anvil_advisor_true_audit_s144t136.py",
    "tests/test_repin_subagent_cli_rm795.py",
    "tests/test_snapshot_normalizer_wire_coercion.py",
    "tools/citation_audit.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", ",".join(_RULES), *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, check=False, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def tree_counts() -> dict[str, dict[str, int]]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    counts: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for d in _ruff(["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked:
            counts[rel][d["code"]] += 1
    return {rel: dict(c) for rel, c in counts.items()}


def test_no_finding_of_the_six_rules_anywhere_in_the_tree(tree_counts):
    assert not tree_counts, f"ruff {_RULES} findings, file: code: count: {tree_counts}"


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_is_ascii_and_lf(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


_PROBES = {
    "SIM905": 'WORDS = "a b c".split()\n',
    "FURB122": ("def f(rows):\n    with open('x', 'w') as fh:\n"
                "        for r in rows:\n            fh.write(r)\n"),
    "PT021": ("import pytest\n\n@pytest.fixture\ndef fx(request):\n"
              "    request.addfinalizer(print)\n    return 1\n"),
    "PT028": "def test_x(level=1):\n    assert level\n",
    "PT030": ("import pytest\n\ndef test_x():\n"
              "    with pytest.warns(UserWarning):\n        pass\n"),
    "SLOT000": "class S(str):\n    pass\n",
}


def test_every_rule_has_a_probe():
    assert set(_PROBES) == set(_RULES)


@pytest.mark.parametrize("rule", _RULES)
def test_probe_is_live(rule):
    """The isolated run reports a minimal offender, so an empty tree result is a real scan."""
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=_PROBES[rule])
    assert rule in {d["code"] for d in found}


def test_stopword_tuple_is_a_clean_word_set():
    from tools import citation_audit

    words = citation_audit._STOPWORDS
    assert len(words) == 120
    assert all(w.isalpha() and w.islower() and w.isascii() for w in words)
