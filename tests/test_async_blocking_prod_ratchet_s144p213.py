"""RM-1721 - ruff ASYNC rules held at zero in production code, and FileIngest reads off the loop.

ruff.toml selects no ASYNC rule and no earlier ratchet covers the family. Measured 2026-11-06 with
``ruff check --isolated`` (target py39): production code carried 2 findings, both ASYNC240 in
``agents/agent2_backend/file_ingest.py``: ``FileIngest._check_one`` ran ``path.stat()`` and
``path.read_text()`` straight on the supervisor's event loop, once per watched file every poll tick.
Both now run in the default executor through the two module helpers ``_stat_blocking`` and
``_read_text_blocking`` (the same executor the pre-flip mirror below them already used), so a slow
disk or a locked file stalls a worker thread, not the WebSocket broadcaster.

Scope: tracked ``.py`` files. ``tests/``, any ``*/tests/`` directory, ``agents/daemon_slayer``, the
vendored ``ops/fleet_kit`` and the ``agents/agent3_testing/suite`` suite (two ASYNC251 time.sleep calls
in test code) are out of scope. The run uses NO config (``--isolated``), so a per-file-ignore cannot
hide a finding. The baseline is empty and only shrinks.
"""
from __future__ import annotations

import collections
import importlib.util
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from tests._asyncio_isolation import run_coro
from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_NEEDS_RUFF = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="ruff is not importable by this interpreter",
)

_RULE = "ASYNC"
_OUT_OF_SCOPE = (
    "tests/",
    "tools/tests/",
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
    for d in _ruff(["--select", _RULE, "."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_OUT_OF_SCOPE) and "/tests/" not in rel:
            counts[rel] += 1
    return dict(counts)


@_NEEDS_RUFF
def test_no_new_findings(tree_counts):
    extra = {f: n for f, n in tree_counts.items() if n > _BASELINE.get(f, 0)}
    assert not extra, f"ruff {_RULE} findings beyond the baseline, file: count: {extra}"


@_NEEDS_RUFF
def test_baseline_is_exact(tree_counts):
    stale = {f: n for f, n in _BASELINE.items() if tree_counts.get(f, 0) != n}
    assert not stale, f"baseline rows to shrink or drop (file: recorded): {stale}"


@_NEEDS_RUFF
def test_probe_is_live():
    """The isolated run reports a minimal offender, so an empty tree result is a real scan."""
    probe = "import time\nasync def f():\n    time.sleep(1)\n"
    found = _ruff(["--select", _RULE, "--stdin-filename", "probe_mod.py", "-"], stdin=probe)
    assert any(d["code"].startswith(_RULE) for d in found)


def test_file_ingest_stats_and_reads_off_the_event_loop(tmp_path, monkeypatch):
    """_check_one's stat and read run on a worker thread, not the loop thread."""
    from agents.agent2_backend import file_ingest as fi

    path = tmp_path / "aram_coaching_data.json"
    path.write_text('{"k": 1}', encoding="utf-8")
    seen: dict[str, int] = {}

    real_stat, real_read = fi._stat_blocking, fi._read_text_blocking

    def stat(p):
        seen["stat"] = threading.get_ident()
        return real_stat(p)

    def read(p):
        seen["read"] = threading.get_ident()
        return real_read(p)

    monkeypatch.setattr(fi, "_stat_blocking", stat)
    monkeypatch.setattr(fi, "_read_text_blocking", read)

    sent: list[dict] = []

    class _WS:
        async def broadcast_push(self, env):
            sent.append(env)

    async def drive() -> int:
        ingest = fi.FileIngest(_WS())
        await ingest._check_one(path, "aram", mode="aram", envelope_type="state")
        return threading.get_ident()

    loop_thread = run_coro(drive())
    assert seen["stat"] != loop_thread
    assert seen["read"] != loop_thread
    assert sent and sent[0]["payload"] == {"k": 1}
