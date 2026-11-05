"""RM-1527 - eight small ruff idiom rules are held at a baseline that only shrinks.

None of these rules is selected by ruff.toml. Measured 2026-11-05 with ``ruff check --isolated``
(target py39): production code carried 14 sites in 11 modules outside the owned paths below.

- TRY201: ``raise exc`` inside ``except Exception as exc`` (three coach ``_run_coach`` bodies);
  bare ``raise`` re-raises the same object without adding the handler line to the traceback.
- C408: ``dict(a=1, ...)`` call with literal keyword names; ``{"a": 1, ...}`` builds the same dict.
- C416: ``{k: v for k, v in pairs}``; ``dict(pairs)`` is the same mapping.
- RSE102: ``raise Cls()`` written with empty parentheses on a class that is only instantiated.
- SIM117: two nested ``with`` statements where one carries both contexts.
- ISC002: two string literals joined by a backslash continuation; parentheses are the explicit form.
- PLC0206: ``for key in d: d[key] = f(d[key])``; ``d.items()`` names the value once.
- PERF402: a ``for`` loop whose only statement is ``out.append(x)``; ``out.extend(...)`` is the same.

The baseline is the findings that stay because someone else owns the file: the packaged-app
launcher and the portable build tool (excluded from lanes by the main session). A baseline entry
that stops offending fails ``test_baseline_is_exact`` until it is dropped; a new finding anywhere
else fails ``test_no_new_findings``.

Scope: production code. ``tests/``, any ``*/tests/`` directory, ``agents/daemon_slayer``, the
``agents/agent3_testing/suite`` test suite and ``tools/ds_cross_eval`` are out of scope. The run
uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding.
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

_RULES = ("C408", "C416", "ISC002", "PERF402", "PLC0206", "RSE102", "SIM117", "TRY201")
_OUT_OF_SCOPE = (
    "tests/",
    "tools/tests/",
    "agents/daemon_slayer/",
    "agents/agent3_testing/suite/",
    "tools/ds_cross_eval/",
)
# file -> finding count that stays because another owner holds the file. Only shrinks.
_BASELINE = {
    "ops/launcher/update_cycle.py": 2,
    "tools/build_portable.py": 1,
}
_FIXED = (
    "coaches/aram_coach.py",
    "coaches/arena_coach.py",
    "coaches/brawl_coach.py",
    "core/build_order.py",
    "dashboard/_lcu_inprocess.py",
    "dashboard/routes_ds_profile.py",
    "dashboard/routes_state.py",
    "lcu/lcu_postgame_collector.py",
    "lib/http/client.py",
    "lib/ingest_receipt.py",
    "scripts/retrofill_match_metrics.py",
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
def tree_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["--select", ",".join(_RULES), "."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_OUT_OF_SCOPE) and "/tests/" not in rel:
            counts[rel] += 1
    return dict(counts)


def test_no_new_findings(tree_counts):
    extra = {f: n for f, n in tree_counts.items() if n > _BASELINE.get(f, 0)}
    assert not extra, f"ruff {_RULES} findings beyond the baseline, file: count: {extra}"


def test_baseline_is_exact(tree_counts):
    """A baseline row that no longer offends (or offends less) must shrink or go."""
    stale = {f: n for f, n in _BASELINE.items() if tree_counts.get(f, 0) != n}
    assert not stale, f"baseline rows to shrink or drop (file: recorded): {stale}"


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_is_ascii_and_lf(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_stays_clean(rel, tree_counts):
    assert rel not in tree_counts


_PROBE = (
    "def f(h, pairs, xs, lock, p):\n"
    "    d = {k: 1 for k in h}\n"
    "    a = dict(x=1)\n"
    "    b = {k: v for k, v in pairs}\n"
    "    out = []\n"
    "    for x in xs:\n"
    "        out.append(x)\n"
    "    for key in d:\n"
    "        d[key] = d[key] + 1\n"
    "    with lock:\n"
    "        with open(p) as fh:\n"
    "            fh.read()\n"
    "    s = 'a' \\\n"
    "        'b'\n"
    "    try:\n"
    "        pass\n"
    "    except Exception as exc:\n"
    "        raise exc\n"
    "    raise ValueError()\n"
)


def test_probe_is_live():
    """The isolated run reports minimal offenders, so an empty tree result is a real scan."""
    found = _ruff(["--select", ",".join(_RULES), "--stdin-filename", "probe_mod.py", "-"],
                  stdin=_PROBE)
    assert {d["code"] for d in found} == set(_RULES), sorted({d["code"] for d in found})


def test_rewrites_are_equivalent():
    """The premise of each fix: same value or same exception object, same order."""
    pairs = [("b", 1), ("a", 2)]
    assert {k: v for k, v in pairs} == dict(pairs)
    assert list(dict(pairs)) == ["b", "a"]
    assert dict(level=1, mode="x") == {"level": 1, "mode": "x"}
    src = [1, 2, 3]
    looped: list = []
    for x in src:
        looped.append(x)
    ext: list = []
    ext.extend(src)
    assert looped == ext
    d = {"p": 1, "q": 2}
    for key, cur in d.items():
        d[key] = cur + 10
    assert d == {"p": 11, "q": 12}
    err = RuntimeError("boom")
    with pytest.raises(RuntimeError) as bare:
        try:
            raise err
        except Exception:
            raise
    assert bare.value is err
