"""ops/loop/drain_waves_2_3.py worktree setup, slice selection and not-run reporting.

Live bug (2026-10-04): wave 2 created its three build worktrees in parallel and
two of three `git worktree add` calls failed with "could not lock config file
.git/config: File exists"; those slices never ran and were dropped from the
record with key "?". These tests pin: serialized + retried worktree creation,
--only / --waves selection with the wave-3 gate, and failed setup reported as
not-run in the result JSON and the merger prompt.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "ops" / "loop" / "drain_waves_2_3.py"

LOCK_ERR = ("Preparing worktree (new branch 'drain/wave2-atomic')\n"
            "error: could not lock config file .git/config: File exists\n"
            "error: unable to write upstream branch configuration")


@pytest.fixture()
def dw(tmp_path, monkeypatch):
    name = "drain_waves_2_3_under_test"
    spec = importlib.util.spec_from_file_location(name, SRC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "WT_BASE", tmp_path / "wt")
    monkeypatch.setattr(mod, "DRAIN_DIR", tmp_path / "drain")
    monkeypatch.setattr(mod, "PROGRESS", tmp_path / "progress")
    monkeypatch.setattr(mod, "LOG", tmp_path / "drain.log")
    monkeypatch.setattr(mod, "RESULT", tmp_path / "result.json")
    monkeypatch.setattr(mod, "STOP_FILE", tmp_path / "DRAIN_STOP")
    monkeypatch.setattr(mod, "_sleep", lambda s: None, raising=False)
    yield mod
    sys.modules.pop(name, None)


def _cp(rc: int, out: str = "", err: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["git"], rc, out, err)


class FakeGit:
    """Fake `_git`: `worktree add` fails with the lock error `fail_n` times per
    worktree path, then creates <wt>/.git. Tracks max concurrent worktree adds."""

    def __init__(self, fail_n: int = 0, always_fail: frozenset = frozenset(),
                 delay: float = 0.0):
        self.fail_n, self.always_fail, self.delay = fail_n, always_fail, delay
        self.calls = []
        self.attempts = {}
        self.branches = set()
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def __call__(self, *args, cwd=None, timeout=300):
        self.calls.append(args)
        if args[:1] == ("rev-parse",) and "--verify" in args:
            return _cp(0 if args[-1] in self.branches else 1)
        if args[:1] == ("rev-parse",):
            return _cp(0, "a" * 40 + "\n")
        if args[:1] == ("fetch",):
            return _cp(0)
        if args[:1] == ("status",):
            return _cp(0, "")
        if args[:2] == ("worktree", "add"):
            with self.lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            try:
                time.sleep(self.delay)
                if "-b" in args:
                    branch, wt = args[args.index("-b") + 1], Path(args[args.index("-b") + 2])
                else:
                    wt, branch = Path(args[2]), args[3]
                n = self.attempts.get(str(wt), 0) + 1
                self.attempts[str(wt)] = n
                if wt.name in self.always_fail or n <= self.fail_n:
                    # real git: the branch ref is created, its upstream config is not
                    self.branches.add(branch)
                    return _cp(255, "", LOCK_ERR)
                self.branches.add(branch)
                (wt / ".git").parent.mkdir(parents=True, exist_ok=True)
                (wt / ".git").write_text("gitdir: x\n", encoding="ascii")
                return _cp(0)
            finally:
                with self.lock:
                    self.active -= 1
        return _cp(0)


# ---------------------------------------------------------------- 1. serialize + retry

def test_worktree_add_retries_on_config_lock_then_succeeds(dw, monkeypatch):
    fg = FakeGit(fail_n=2)
    monkeypatch.setattr(dw, "_git", fg)
    wt = dw._ensure_worktree("Wave2", "atomic")
    assert (wt / ".git").exists()
    adds = [c for c in fg.calls if c[:2] == ("worktree", "add")]
    assert len(adds) == 3
    # the first failed add left the branch behind: the retry must attach to it, not -b again
    assert "-b" in adds[0] and "-b" not in adds[-1]


def test_worktree_add_retry_is_bounded(dw, monkeypatch):
    fg = FakeGit(always_fail=frozenset({"drain-wave2-atomic"}))
    monkeypatch.setattr(dw, "_git", fg)
    with pytest.raises(RuntimeError, match="could not lock"):
        dw._ensure_worktree("Wave2", "atomic")
    adds = [c for c in fg.calls if c[:2] == ("worktree", "add")]
    assert 2 <= len(adds) <= 5


def test_non_lock_failure_is_not_retried(dw, monkeypatch):
    calls = []

    def g(*args, cwd=None, timeout=300):
        calls.append(args)
        if args[:2] == ("worktree", "add"):
            return _cp(128, "", "fatal: invalid reference: origin/main")
        return _cp(1)
    monkeypatch.setattr(dw, "_git", g)
    with pytest.raises(RuntimeError, match="invalid reference"):
        dw._ensure_worktree("Wave2", "atomic")
    assert len([c for c in calls if c[:2] == ("worktree", "add")]) == 1


def test_concurrent_worktree_creation_is_serialized(dw, monkeypatch):
    fg = FakeGit(delay=0.05)
    monkeypatch.setattr(dw, "_git", fg)
    ts = [threading.Thread(target=dw._ensure_worktree, args=("Wave2", k))
          for k in ("atomic", "tail-roadmap", "tail-backlog")]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert fg.max_active == 1
    assert all((dw.WT_BASE / f"drain-wave2-{k}" / ".git").exists()
               for k in ("atomic", "tail-roadmap", "tail-backlog"))


# ---------------------------------------------------------------- 3. failed setup = not-run

def _fake_spawn_factory(prompts: dict):
    def fake_spawn(prompt, *, task, extra, cwd, timeout):
        prompts[task] = prompt
        if task.endswith("-merge"):
            return {"rc": 0, "result": '{"merged": [], "dropped": [], "pushed": true, '
                                      '"main_sha": "b", "halted_reason": ""}',
                    "error": None, "stderr": ""}
        if task.endswith("-verify"):
            return {"rc": 0, "result": '{"per_item": []}', "error": None, "stderr": ""}
        return {"rc": 0, "result": '{"items": []}', "error": None, "stderr": ""}
    return fake_spawn


def test_failed_worktree_setup_marked_not_run_and_listed_to_merger(dw, monkeypatch):
    fg = FakeGit(always_fail=frozenset({"drain-wave2-atomic"}))
    monkeypatch.setattr(dw, "_git", fg)
    prompts = {}
    monkeypatch.setattr(dw, "_spawn", _fake_spawn_factory(prompts))
    wave = dw.WAVES[0]
    state = {"blocked_rows": []}
    res = dw.run_wave(wave, state)
    by_key = {s["key"]: s for s in res["slices"]}
    assert set(by_key) == {"atomic", "tail-roadmap", "tail-backlog"}
    assert by_key["atomic"]["status"] == "not-run"
    assert "could not lock" in by_key["atomic"]["error"]
    assert by_key["tail-roadmap"]["status"] != "not-run"
    # no build ran for the failed slice
    assert "Wave2-atomic" not in prompts
    assert "Wave2-tail-roadmap" in prompts
    merger = prompts["Wave2-merge"]
    assert "NOT RUN" in merger and "Wave2-atomic" in merger
    assert "Wave2-tail-roadmap" not in merger.split("NOT RUN", 1)[1].split("\n", 1)[0]


def test_all_setup_failed_still_records_every_slice(dw, monkeypatch):
    fg = FakeGit(always_fail=frozenset({"drain-wave2-atomic", "drain-wave2-tail-roadmap",
                                        "drain-wave2-tail-backlog"}))
    monkeypatch.setattr(dw, "_git", fg)
    monkeypatch.setattr(dw, "_spawn", _fake_spawn_factory({}))
    res = dw.run_wave(dw.WAVES[0], {"blocked_rows": []})
    assert res["pushed"] is False
    assert sorted(s["key"] for s in res["slices"]) == ["atomic", "tail-backlog", "tail-roadmap"]
    assert all(s["status"] == "not-run" for s in res["slices"])


# ---------------------------------------------------------------- 2. --only / --waves

def test_select_only_filters_slices_and_drops_empty_waves(dw):
    sel = dw.select_waves(None, "atomic,tail-roadmap")
    assert [w["tag"] for w in sel] == ["Wave2"]
    assert [k for k, _ in sel[0]["slices"]] == ["atomic", "tail-roadmap"]


def test_select_waves_values(dw):
    assert [w["tag"] for w in dw.select_waves(None, None)] == ["Wave2", "Wave3"]
    assert [w["tag"] for w in dw.select_waves("2", None)] == ["Wave2"]
    assert [w["tag"] for w in dw.select_waves("3", None)] == ["Wave3"]
    assert [w["tag"] for w in dw.select_waves("2,3", None)] == ["Wave2", "Wave3"]
    assert [w["tag"] for w in dw.select_waves("3,2", None)] == ["Wave2", "Wave3"]


@pytest.mark.parametrize("waves,only", [("4", None), ("2", "ascii"), (None, "nope"), ("", None)])
def test_select_rejects_bad_selection(dw, waves, only):
    with pytest.raises(ValueError):
        dw.select_waves(waves, only)


def test_runs_needed_follows_selection(dw):
    assert dw.runs_needed(dw.select_waves(None, None)) == 10
    assert dw.runs_needed(dw.select_waves("2", "atomic,tail-roadmap")) == 5
    assert dw.runs_needed(dw.select_waves("3", None)) == 3


def _drive_run(dw, monkeypatch, waves_sel, wave_results):
    ran = []

    def fake_run_wave(wave, state):
        ran.append((wave["tag"], [k for k, _ in wave["slices"]]))
        return dict(wave_results[wave["tag"]])

    class K:
        RUNS_CAP = 120
        BUDGET_REL = "x"

        class RunBudget:
            def __init__(self, p):
                pass

            def used(self):
                return 0

    class HE:
        class HeadlessRouteRefused(Exception):
            pass

        @staticmethod
        def resolve_base_url(caller):
            return "http://127.0.0.1:1"

    class FR:
        @staticmethod
        def kit():
            return K

        @staticmethod
        def _headless_env():
            return HE

    monkeypatch.setattr(dw, "_fleet_route", lambda: FR)
    monkeypatch.setattr(dw, "_take_lock", lambda: True)
    monkeypatch.setattr(dw, "LOCK", dw.RESULT.with_name("lock"))
    monkeypatch.setattr(dw, "_git", FakeGit())
    monkeypatch.setattr(dw, "run_wave", fake_run_wave)
    rc = dw.run(waves_sel)
    return rc, ran


def test_wave3_gated_on_wave2_push_when_both_selected(dw, monkeypatch):
    res = {"Wave2": {"pushed": False, "halted_reason": "x"}, "Wave3": {"pushed": True}}
    rc, ran = _drive_run(dw, monkeypatch, dw.select_waves("2,3", None), res)
    assert rc == 2 and [t for t, _ in ran] == ["Wave2"]


def test_wave3_alone_runs_unconditionally(dw, monkeypatch):
    res = {"Wave3": {"pushed": True}}
    rc, ran = _drive_run(dw, monkeypatch, dw.select_waves("3", None), res)
    assert rc == 0 and ran == [("Wave3", ["ascii"])]


def test_only_reaches_run_wave(dw, monkeypatch):
    res = {"Wave2": {"pushed": True}}
    rc, ran = _drive_run(dw, monkeypatch, dw.select_waves("2", "atomic,tail-roadmap"), res)
    assert rc == 0 and ran == [("Wave2", ["atomic", "tail-roadmap"])]


def test_cli_parses_only_and_waves(dw, monkeypatch):
    seen = {}
    monkeypatch.setattr(dw, "run", lambda sel: seen.setdefault("sel", sel) and 0)
    dw.main(["--only", "atomic,tail-roadmap", "--waves", "2"])
    assert [(w["tag"], [k for k, _ in w["slices"]]) for w in seen["sel"]] == \
        [("Wave2", ["atomic", "tail-roadmap"])]


def test_cli_rejects_unknown_slice(dw):
    with pytest.raises(SystemExit) as ei:
        dw.main(["--only", "nope"])
    assert ei.value.code == 2
