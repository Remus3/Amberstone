"""ops/loop/lane_status_landdue.py: MAIN ORDER 2026-11-14 0930 section 3, LAND DUE.

One line per lane in the lane status file (ops/loop/control/progress/s144-lanes.json)
with `git rev-list --count main..lane/<x>`, and LAND DUE on any lane more than 100
ahead. Paths are under tmp_path; git is faked except in the one real-repo test."""
from __future__ import annotations

import json
import subprocess

from ops.loop import lane_status_landdue as LD

LANES = ("gated", "queue", "uiux", "repo")


def test_line_per_lane_and_land_due_only_above_100():
    lines = LD.land_due_lines({"gated": 20, "queue": 100, "uiux": 101, "repo": None})
    assert lines == [
        "gated 20 ahead of main",
        "queue 100 ahead of main",
        "uiux 101 ahead of main LAND DUE",
        "repo ? ahead of main (count unavailable)",
    ]


def test_ahead_counts_runs_rev_list_count_main_dot_dot_lane(tmp_path):
    seen = []

    def run(args, **kw):
        seen.append(list(args))
        lane = args[-1].split("lane/", 1)[1]
        if lane == "repo":
            return subprocess.CompletedProcess(args, 128, stdout="", stderr="bad ref")
        return subprocess.CompletedProcess(args, 0, stdout={"gated": "7\n", "queue": "158\n",
                                                            "uiux": "0\n"}[lane], stderr="")

    counts = LD.ahead_counts(tmp_path, LANES, run=run)
    assert counts == {"gated": 7, "queue": 158, "uiux": 0, "repo": None}
    assert seen[0][:4] == ["git", "rev-list", "--count", "main..lane/gated"]


def test_stamp_merges_the_block_and_keeps_every_other_key(tmp_path):
    status = tmp_path / "s144-lanes.json"
    status.write_bytes(json.dumps({"task": "s144-lanes", "pct": 5, "daily": {"x": 1}}).encode())
    block = LD.stamp(tmp_path, LANES, status_path=status,
                     counts={"gated": 1, "queue": 106, "uiux": 0, "repo": 158})
    doc = json.loads(status.read_text(encoding="ascii"))
    assert doc["task"] == "s144-lanes" and doc["daily"] == {"x": 1}
    assert doc["land_due"] == block
    assert block["due"] == ["queue", "repo"] and block["threshold"] == 100
    assert "queue 106 ahead of main LAND DUE" in block["lines"]
    assert block["lanes"]["gated"] == {"ahead": 1, "land_due": False}
    assert b"\r" not in status.read_bytes()


def test_stamp_caches_the_counts_between_calls(tmp_path):
    status = tmp_path / "s.json"
    status.write_bytes(b"{}")
    calls = []

    def run(args, **kw):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="3\n", stderr="")

    cache: dict = {}
    LD.stamp(tmp_path, LANES, status_path=status, run=run, cache=cache, now=100.0)
    LD.stamp(tmp_path, LANES, status_path=status, run=run, cache=cache, now=150.0)
    assert len(calls) == len(LANES)
    LD.stamp(tmp_path, LANES, status_path=status, run=run, cache=cache, now=100.0 + LD.TTL_S)
    assert len(calls) == 2 * len(LANES)


def test_real_repo_count(tmp_path):
    def g(*a):
        subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    g("init", "-q", "-b", "main")
    g("config", "user.email", "t@example.invalid")
    g("config", "user.name", "t")
    g("commit", "-q", "--allow-empty", "-m", "base")
    g("branch", "lane/queue")
    g("checkout", "-q", "lane/queue")
    for i in range(3):
        g("commit", "-q", "--allow-empty", "-m", f"c{i}")
    assert LD.ahead_counts(tmp_path, ("queue", "absent")) == {"queue": 3, "absent": None}
