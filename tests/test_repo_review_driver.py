"""ops/loop/repo_review.py - the headless full-tree review driver (MAIN 2246 s8).

Pins: the universe (tracked / ignored / untracked / worktree units) and its
reconciliation; every unit lands in exactly one batch; the reviewer answer is
validated against its batch; the run fails CLOSED on a route or kit refusal
(no fallback, the whole driver halts "blocked"); every run goes through
fleet_route with kind build, a non-empty label and read-only flags; the stop
file and the driver's own run cap halt before a spawn.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

from ops.loop import fleet_route
from ops.loop import headless_env as he

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "ops" / "loop" / "repo_review.py"


@pytest.fixture()
def rr(tmp_path, monkeypatch):
    name = "repo_review_under_test"
    spec = importlib.util.spec_from_file_location(name, SRC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    stage = tmp_path / "stage"
    monkeypatch.setattr(mod, "STAGE", stage)
    monkeypatch.setattr(mod, "MANIFEST", stage / "manifest.jsonl")
    monkeypatch.setattr(mod, "BATCHES", stage / "batches.json")
    monkeypatch.setattr(mod, "PROMPTS", stage / "prompts")
    monkeypatch.setattr(mod, "RAW", stage / "raw")
    monkeypatch.setattr(mod, "FINDINGS", stage / "findings")
    monkeypatch.setattr(mod, "SUMMARY", stage / "summary.json")
    monkeypatch.setattr(mod, "STOP_FILE", tmp_path / "REPO_REVIEW_STOP")
    monkeypatch.setattr(mod, "LOG", tmp_path / "repo_review.log")
    monkeypatch.setitem(sys.modules, "rc_ops_loop_fleet_route", fleet_route)
    yield mod
    sys.modules.pop(name, None)


def _row(p, st="T", cls=None, sz=10, refs=1):
    return {"p": p, "st": st, "sz": sz, "mt": "2026-10-01", "lc": "2026-09-30",
            "cls": cls, "refs": refs}


# ---------------------------------------------------------------- classify / plan

@pytest.mark.parametrize("path,status,want", [
    ("core/__pycache__/x.cpython-314.pyc", "I", "pycache"),
    ("stray.pyc", "I", "pycache"),
    (".ruff_cache/0.15.12/abc", "I", "toolcache"),
    ("agents/.pytest_cache/v/cache/nodeids", "I", "toolcache"),
    ("rc-shell/node_modules/electron/index.js", "I", "node_modules"),
    ("web/data/ddragon/16.1.1/img/a.png", "I", "ddragon-web"),
    ("data/meta_build/ddragon/16.11.1/x.json", "I", "meta-build"),
    ("ops/runtime/responder_export/abc/x.py", "I", "responder-export"),
    ("python-embed/Lib/os.py", "I", "python-embed"),
    ("moon_sync_inbox/2026-10-08-note.md", "I", "inbox"),
    (".claude/worktrees/agent-x/", "W", "worktrees"),
    ("core/build_order.py", "T", None),
    ("docs/LEDGER.md", "T", None),
])
def test_classify(rr, path, status, want):
    assert rr.classify(path, status) == want


def test_every_unit_lands_in_exactly_one_batch(rr):
    rows = [_row(f"core/m{i:03d}.py") for i in range(400)]
    rows += [_row(f"data/d{i:03d}.json") for i in range(500)]
    rows += [_row("CLAUDE.md"), _row("docs/LEDGER.md"), _row("README.md")]
    rows += [_row(f"x/__pycache__/m{i}.pyc", "I", "pycache") for i in range(50)]
    rows += [_row(".claude/worktrees/a/", "W", "worktrees")]
    batches = rr.plan_batches(rows, cap=100)
    seen = [p for b in batches for p in b["paths"]]
    assert sorted(seen) == sorted(r["p"] for r in rows), "a unit is missing or doubled"
    assert len(seen) == len(set(seen))
    kinds = {b["id"]: b["kind"] for b in batches}
    assert kinds["MD01"] == "mdcore"
    md = next(b for b in batches if b["id"] == "MD01")
    assert set(md["paths"]) == {"CLAUDE.md", "docs/LEDGER.md", "README.md"}
    assert {b["cls"] for b in batches if b["kind"] == "class"} == {"pycache", "worktrees"}
    for b in batches:
        if b["kind"] == "files":
            assert sum(rr.weight(p) for p in b["paths"]) <= 100 + 1e-9
    assert len({b["id"] for b in batches}) == len(batches)


def test_plan_is_deterministic(rr):
    rows = [_row(f"tools/t{i}.py") for i in range(300)]
    assert rr.plan_batches(rows, cap=50) == rr.plan_batches(list(reversed(rows)), cap=50)


# ---------------------------------------------------------------- prompt

def test_files_prompt_lists_every_unit_and_is_ascii(rr):
    rows = [_row("tools/a.py", refs=0), _row("tools/b.md", st="I", refs=None)]
    batch = {"id": "B01", "kind": "files", "title": "tools", "paths": ["tools/a.py", "tools/b.md"]}
    text = rr.build_prompt(batch, {r["p"]: r for r in rows}, 7)
    assert "Batch B01 of 7" in text
    assert "tools/a.py | T |" in text and "tools/b.md | I |" in text
    assert "KF-A6" in text and "KF-P1" in text, "the known findings ride every prompt"
    text.encode("ascii")


def test_class_prompt_carries_facts_and_sample(rr, tmp_path):
    rows = [_row(f"pkg/__pycache__/m{i}.cpython-314.pyc", "I", "pycache") for i in range(100)]
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "m1.py").write_text("x = 1\n", encoding="utf-8")
    batch = {"id": "C01", "kind": "class", "cls": "pycache", "title": "pycache",
             "paths": [r["p"] for r in rows]}
    text = rr.build_prompt(batch, {r["p"]: r for r in rows}, 3, root=tmp_path)
    assert "ONE BULK CLASS: pycache - 100 units" in text
    assert "99 orphan .pyc" in text
    assert text.count("pkg/__pycache__/") >= rr.SAMPLE_N


# ---------------------------------------------------------------- parse

def _answer(bid="B01", n=2, findings=None):
    return json.dumps({"batch": bid, "manifest_count": n, "reviewed_clean_count": n,
                       "folders": [], "findings": findings or []})


@pytest.mark.parametrize("text,ok", [
    (_answer(), True),
    ("```json\n" + _answer() + "\n```", True),
    ("Here it is: " + _answer() + " done", True),
    (_answer(bid="B02"), False),
    (_answer(n=3), False),
    ("", False),
    ("no json here", False),
])
def test_parse_answer(rr, text, ok):
    batch = {"id": "B01", "paths": ["a", "b"]}
    doc, reason = rr.parse_answer(text, batch)
    assert (doc is not None) is ok
    assert (reason is None) is ok


def test_parse_answer_normalises_findings(rr):
    f = [{"sev": "urgent", "topic": "O", "paths": "a", "finding": "x", "proposed": "maybe",
          "acceptance": "a test passes"}, "junk"]
    doc, _ = rr.parse_answer(_answer(findings=f), {"id": "B01", "paths": ["a", "b"]})
    (one,) = doc["findings"]
    assert one["sev"] == "info" and one["paths"] == ["a"] and one["proposed"] == "FILE"


# ---------------------------------------------------------------- runner

class FakeSpawn:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, prompt, bid):
        self.calls.append(bid)
        a = self.answers.pop(0) if self.answers else None
        if isinstance(a, Exception):
            raise a
        text = a(bid) if callable(a) else a
        return {"rc": 0, "result": text, "model": "sonnet"}, None


def _batches():
    return [{"id": "B01", "kind": "files", "title": "a", "paths": ["a/x.py", "a/y.py"]},
            {"id": "B02", "kind": "files", "title": "b", "paths": ["b/z.py"]}]


def _rows():
    return {p: _row(p) for p in ("a/x.py", "a/y.py", "b/z.py")}


def _good(bid):
    return _answer(bid=bid, n={"B01": 2, "B02": 1}[bid])


def _progress(tmp_path):
    return json.loads((tmp_path / "ops/loop/control/progress/repo-review.json").read_text())


def test_runner_reviews_every_batch_and_reports_done(rr, tmp_path):
    spawn = FakeSpawn([_good, _good])
    runner = rr.Runner(_batches(), _rows(), parallel=1, spawn=spawn, root=tmp_path)
    assert runner.run() == 0
    assert sorted(spawn.calls) == ["B01", "B02"]
    assert rr.batch_done("B01") and rr.batch_done("B02")
    prog = _progress(tmp_path)
    assert prog["status"] == "done" and prog["pct"] == 100 and prog["checklist"] == []
    s = rr.compile_summary([_row(p) for p in _rows()], _batches())
    assert s["reviewed"] == s["units"] == 3


def test_runner_retries_once_then_fails(rr, tmp_path):
    spawn = FakeSpawn(["garbage", "still garbage", _good])
    runner = rr.Runner(_batches(), _rows(), parallel=1, spawn=spawn, root=tmp_path)
    assert runner.run() == 1
    assert spawn.calls == ["B01", "B01", "B02"]
    assert not rr.batch_done("B01") and rr.batch_done("B02")
    assert _progress(tmp_path)["status"] == "failed"


def test_refusal_halts_the_whole_driver_blocked(rr, tmp_path):
    spawn = FakeSpawn([rr.Halt("proxy-unreachable", "headless route refused: kit")])
    runner = rr.Runner(_batches(), _rows(), parallel=1, spawn=spawn, root=tmp_path)
    assert runner.run() == 3
    assert spawn.calls == ["B01"], "no further spawn after a refusal - fail closed"
    prog = _progress(tmp_path)
    assert prog["status"] == "blocked" and "refused" in prog["reason"]


def test_stop_file_halts_before_any_spawn(rr, tmp_path):
    rr.STOP_FILE.write_text("stop", encoding="utf-8")
    spawn = FakeSpawn([_good, _good])
    assert rr.Runner(_batches(), _rows(), parallel=1, spawn=spawn, root=tmp_path).run() == 2
    assert spawn.calls == []


def test_driver_run_cap_halts(rr, tmp_path):
    spawn = FakeSpawn([_good, _good])
    runner = rr.Runner(_batches(), _rows(), parallel=1, max_runs=1, spawn=spawn, root=tmp_path)
    assert runner.run() == 2
    assert spawn.calls == ["B01"]


def test_only_selection_judges_only_the_selected_batches(rr, tmp_path):
    spawn = FakeSpawn([_good])
    runner = rr.Runner(_batches(), _rows(), parallel=1, spawn=spawn, root=tmp_path)
    assert runner.run(only={"B02"}) == 0
    assert spawn.calls == ["B02"]
    prog = _progress(tmp_path)
    assert prog["status"] == "running" and [r["id"] for r in prog["checklist"]][0] == "B01"


def test_done_batches_are_not_rerun(rr, tmp_path):
    spawn = FakeSpawn([_good, _good])
    rr.Runner(_batches(), _rows(), parallel=1, spawn=spawn, root=tmp_path).run()
    again = FakeSpawn([])
    assert rr.Runner(_batches(), _rows(), parallel=1, spawn=again, root=tmp_path).run() == 0
    assert again.calls == []


# ---------------------------------------------------------------- the kit door

def test_spawn_refuses_without_route_and_starts_nothing(rr, monkeypatch, tmp_path):
    monkeypatch.setattr(he, "_read_user_var", lambda name: None)
    monkeypatch.setattr(he, "_probe", lambda h, p, t: pytest.fail("probe on an unset var"))
    monkeypatch.setattr(he, "REFUSAL_LOG", tmp_path / "refusals.log")
    with mock.patch("subprocess.run", side_effect=AssertionError("spawned with no route")), \
         mock.patch("subprocess.Popen", side_effect=AssertionError("spawned with no route")):
        with pytest.raises(rr.Halt):
            rr._spawn("PROMPT", "B01", timeout=5)


def test_spawn_goes_through_fleet_route_read_only(rr, monkeypatch):
    monkeypatch.setattr(he, "_read_user_var", lambda name: "http://127.0.0.1:65534")
    monkeypatch.setattr(he, "_probe", lambda h, p, t: None)
    calls = []

    def _fake(root, code, prompt, **kw):
        calls.append({"code": code, "prompt": prompt, **kw})
        return {"rc": 0, "result": "x", "model": "sonnet"}

    monkeypatch.setattr(fleet_route, "_kit_spawn", _fake)
    line, _proc = rr._spawn("PROMPT", "B07", timeout=5)
    (c,) = calls
    assert c["code"] == "RC" and c["prompt"] == "PROMPT"
    assert c["writes_code"] is False and c["bare"] is False, "sonnet: the kit picks by writes_code"
    assert c["kind"] == "build" and c["note"] == "repo-review-B07"
    assert c["stdin"] is True, "the whole prompt rides stdin"
    extra = list(c["extra"])
    assert extra == list(rr.READ_ONLY_EXTRA)
    allowed = extra[extra.index("--allowedTools") + 1].split(",")
    assert allowed == ["Read", "Grep", "Glob"]
    denied = extra[extra.index("--disallowedTools") + 1].split(",")
    for tool in ("Edit", "Write", "Bash", "PowerShell", "Agent"):
        assert tool in denied
    assert extra[extra.index("--permission-mode") + 1] == "dontAsk"
    assert not any("fallback" in a.lower() for a in extra)


def test_load_by_path_never_hands_out_a_half_loaded_module(rr, tmp_path):
    """Measured 2026-10-09: four worker threads raced the first fleet_route load
    and saw a module with no RouteRefused yet."""
    import threading
    src = tmp_path / "slow_mod.py"
    src.write_text("import time\ntime.sleep(0.3)\nREADY = True\n", encoding="utf-8")
    name = "repo_review_slow_mod_under_test"
    got, threads = [], []
    try:
        for _ in range(4):
            t = threading.Thread(target=lambda: got.append(
                getattr(rr._load_by_path(name, src), "READY", False)))
            threads.append(t)
            t.start()
        for t in threads:
            t.join(10)
    finally:
        sys.modules.pop(name, None)
    assert got == [True] * 4


# ---------------------------------------------------------------- universe

def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _point_at(rr, monkeypatch, repo):
    stage = repo / "ops" / "runtime" / "repo_review"
    monkeypatch.setattr(rr, "ROOT", repo)
    monkeypatch.setattr(rr, "STAGE", stage)
    monkeypatch.setattr(rr, "MANIFEST", stage / "manifest.jsonl")
    monkeypatch.setattr(rr, "BATCHES", stage / "batches.json")
    monkeypatch.setattr(rr, "FINDINGS", stage / "findings")
    monkeypatch.setattr(rr, "SUMMARY", stage / "summary.json")


def test_delta_batches_new_units_marks_gone_and_excludes_review_output(rr, tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "core").mkdir(parents=True)
    (repo / ".gitignore").write_text("ops/runtime/\n", encoding="utf-8")
    (repo / "core" / "keep_mod.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "core" / "drop_mod.py").write_text("y = 2\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "commit", "-q", "-m", "init")
    _point_at(rr, monkeypatch, repo)
    assert rr.cmd_enumerate() == 0
    first = {r["p"] for r in rr.load_manifest()}
    assert not any(p.startswith("ops/runtime/repo_review/") for p in first), \
        "the review's own staging output is not its subject"
    (repo / "core" / "drop_mod.py").unlink()
    (repo / "core" / "new_mod.py").write_text("z = 3\n", encoding="utf-8")
    assert rr.cmd_delta() == 0
    batches = rr.load_batches()
    (d,) = [b for b in batches if b["id"].startswith("D")]
    assert d["paths"] == ["core/new_mod.py"]
    rows = {r["p"]: r for r in rr.load_manifest()}
    assert rows["core/drop_mod.py"].get("gone") is True
    for b in batches:  # every batch answered: the compile must equal the disk now
        rr._atomic_write(rr._result_path(b["id"]), json.dumps(
            {"status": "ok", "answer": {"findings": []}}))
    s = rr.compile_summary(rr.load_manifest(), batches)
    disk_now = json.loads(rr.BATCHES.read_text())["deltas"][-1]["counts_now"]["disk_units"]
    assert s["units"] == s["reviewed"] == disk_now == 3
    assert s["gone"] == 1


def test_build_manifest_reconciles_tracked_ignored_untracked(rr, tmp_path):
    repo = tmp_path / "repo"
    (repo / "core" / "__pycache__").mkdir(parents=True)
    (repo / "logs").mkdir()
    (repo / ".gitignore").write_text("logs/\n__pycache__/\n", encoding="utf-8")
    (repo / "core" / "a.py").write_text("import beta_mod\n", encoding="utf-8")
    (repo / "core" / "beta_mod.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "core" / "__pycache__" / "a.cpython-314.pyc").write_bytes(b"\0")
    (repo / "logs" / "x.log").write_text("l\n", encoding="utf-8")
    (repo / "new.txt").write_text("u\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", ".gitignore", "core/a.py", "core/beta_mod.py")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "commit", "-q", "-m", "init")
    man = rr.build_manifest(repo)
    st = {r["p"]: r["st"] for r in man["rows"]}
    assert st == {".gitignore": "T", "core/a.py": "T", "core/beta_mod.py": "T",
                  "core/__pycache__/a.cpython-314.pyc": "I", "logs/x.log": "I",
                  "new.txt": "U"}
    c = man["counts"]
    assert c["disk_units"] == 6 and c["tracked_on_disk"] == 3
    assert c["ignored"] == 2 and c["untracked"] == 1 and c["tracked_missing_on_disk"] == 0
    rows = {r["p"]: r for r in man["rows"]}
    assert rows["core/beta_mod.py"]["refs"] == 1, "a.py imports beta_mod"
    assert rows["core/a.py"]["refs"] == 0, "nothing mentions a.py"
    assert rows["core/a.py"]["lc"], "a tracked file carries its last commit date"
    assert rows["core/__pycache__/a.cpython-314.pyc"]["cls"] == "pycache"
