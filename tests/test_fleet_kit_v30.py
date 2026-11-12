"""FLEET-KIT v30 (MAIN 2026-11-12 0345 ORDER to all eight, cumulative v29 + v30).

v29 was never delivered; its content (rewrite gaps, OVERRUN) rides v30. The ORDER
asks RC to vendor all 24 files + MANIFEST byte-for-byte, re-embed the changed
FLEET-COMMON block (items 12, 13 a, 14 e), drop the tree-side extra_ignore for
inbox_pending_orders.json and close RM-2053 / RM-2074, keep every run-cap gate on
`budget.cap` (a bare RunBudget now resolves the machine cap, RUNS_CAP stays 120),
and make ops/loop/run_lane.ps1 take `fleet_lanes.lane_model` FIRST because it
always passes --model. These pin the vendored bytes, the RC acts and the kit
behaviour RC leans on. Key sets are SUBSETS, refusals match `Refused.code`.
CLAUDE.md carries the RC "KIT v30" rules line naming this guard; long form in
docs/FLEET_KIT_ADOPTION.md.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import tokenize
from pathlib import Path

import pytest

from tests import _fleet_guard_config as guard_cfg
from tests import _repo_walk

ROOT = Path(__file__).resolve().parent.parent
KIT = ROOT / "ops" / "fleet_kit"
RUN_LANE = ROOT / "ops" / "loop" / "run_lane.ps1"
V30_MANIFEST_SHA256 = "d2ac40250bd0efc071f0eb11c1e92ae04af88d750de200cf8ed4dc5714d07ea2"
V30_COMMON_BLOCK_SHA256 = "6205943cb187258bdd72f9799fd03cbd90354562d8f561ccf2e4c19fbedea5ee"
BEGIN, END = "<!-- FLEET-COMMON BEGIN -->\n", "<!-- FLEET-COMMON END -->"
PENDING = "ops/loop/control/inbox_pending_orders.json"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"rc_v30_probe_{name}", KIT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_rc(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _claude_md():
    return (ROOT / "CLAUDE.md").read_bytes().decode("ascii")


def _tree_with_handoff(tmp_path):
    """A tree root the kit can name: one RC-NEXT-SESSION.txt at it."""
    root = tmp_path / "tree"
    (root / "ops" / "loop" / "control").mkdir(parents=True)
    (root / "RC-NEXT-SESSION.txt").write_text("SESSION: 1\n", encoding="ascii")
    return root


def _machine_cfg(tmp_path, monkeypatch, doc):
    cfg = tmp_path / "lanes.json"
    cfg.write_text(json.dumps(doc), encoding="ascii")
    monkeypatch.setenv("FLEET_LANES_CONFIG", str(cfg))
    return cfg


# ---------------------------------------------------------------- vendoring

def test_the_vendored_kit_is_the_v30_order_bytes_and_conforms():
    raw = (KIT / "MANIFEST.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == V30_MANIFEST_SHA256
    man = json.loads(raw.decode("ascii"))
    assert man["version"] == 30 and len(man["files"]) == 24
    assert man["common_block_sha256"] == V30_COMMON_BLOCK_SHA256
    fh = _load("fleet_headless")
    assert (fh.KIT_VERSION, fh.KIT_PATCH) == (30, 0)
    for name, want in man["files"].items():
        assert hashlib.sha256((KIT / name).read_bytes()).hexdigest() == want, name
    assert fh.conformance(ROOT) == []


def test_the_common_block_carries_the_v30_items():
    text = _claude_md()
    block = text[text.index(BEGIN) + len(BEGIN):text.index(END)]
    assert hashlib.sha256(block.encode("ascii")).hexdigest() == V30_COMMON_BLOCK_SHA256
    flat = " ".join(block.split())
    for needle in ("reads OVERRUN on the status line", "`fleet_checklist.py stale`",
                   "a row past 2x reads STALE", "(+<N> more past the 20-row cap: <IDs>)",
                   "build / order / inbox / triage / report / probe"):
        assert needle in flat, needle


def test_claude_md_carries_the_kit_v30_rules_line():
    text = _claude_md()
    rc = text[text.index(END):]
    line = next(ln for ln in rc.split("\n")
                if ln.startswith("**KIT v30 (MAIN 2026-11-12 0345, cumulative v29 + v30)"))
    for needle in ("budget.cap", "lane_model", "note_pause", "RM-2053", "RM-2074",
                   "Guard `tests/test_fleet_kit_v30.py`"):
        assert needle in line, needle
    assert rc.index("**KIT v28 (") < rc.index("**KIT v30 (")
    assert (ROOT / "CLAUDE.md").stat().st_size <= 60 * 1024


# ---------------------------------------------------------------- RM-2053

def test_the_kit_ignore_holds_the_pending_orders_file_and_rc_dropped_its_copy():
    guard = _load("fleet_test_guard")
    assert PENDING in guard.IGNORE
    assert PENDING not in guard_cfg.EXTRA_IGNORE
    assert not set(guard_cfg.EXTRA_IGNORE) & set(guard.IGNORE)


# ---------------------------------------------------------------- RM-2074

def test_every_route_write_attempt_is_logged_beside_the_route_file(tmp_path):
    fh = _load("fleet_headless")
    route = tmp_path / "fleet" / "headless_route.json"
    fh.write_route("split", path=route)
    with pytest.raises(fh.Refused) as ei:
        fh.write_route("bogus", path=route)
    assert ei.value.code == "route-invalid"
    log = route.with_name("headless_route_writes.jsonl")
    assert fh.route_write_log_path(route) == log
    raw = log.read_text(encoding="ascii")
    rows = [json.loads(x) for x in raw.splitlines()]
    assert [r["outcome"] for r in rows] == ["ok", "refused"]
    for row in rows:
        assert {"ts", "verb", "armed", "outcome", "old_sha256", "new_sha256",
                "writer"} <= set(row)
        assert {"pid", "ppid", "argv0", "caller"} <= set(row["writer"])
    assert rows[0]["new_sha256"] == hashlib.sha256(route.read_bytes()).hexdigest()
    assert rows[1]["code"] == "route-invalid"
    assert str(tmp_path) not in raw, "the log names no path"


# ---------------------------------------------------------------- run cap

def test_a_bare_budget_resolves_the_machine_cap_and_runs_cap_stays_120(tmp_path, monkeypatch):
    fh = _load("fleet_headless")
    _machine_cfg(tmp_path, monkeypatch, {"runs_cap": {"RC": 300}})
    root = _tree_with_handoff(tmp_path)
    assert fh.RUNS_CAP == 120
    assert fh.RunBudget(root / fh.BUDGET_REL).cap == 300
    assert fh.RunBudget(tmp_path / "elsewhere" / "budget.json").cap == 120
    assert fh.RunBudget(root / fh.BUDGET_REL, cap=7).cap == 7
    assert fh.RunBudget(root / fh.BUDGET_REL, cap=10_000).cap == fh.RUNS_CAP_MAX == 500


def test_rc_status_writers_publish_the_machine_cap(tmp_path, monkeypatch):
    """fleet_route._idle and inbox_tick._write_status hand write_status a bare
    budget; under v30 the status file's runs_cap is the tree's machine cap."""
    _machine_cfg(tmp_path, monkeypatch, {"runs_cap": {"RC": 300}})
    route = _load_rc("rc_v30_fleet_route", "ops/loop/fleet_route.py")
    tick = _load_rc("rc_v30_inbox_tick", "ops/loop/inbox_tick.py")
    status_rel = route.kit().STATUS_REL
    root = _tree_with_handoff(tmp_path)
    route.write_idle(None, root=root)
    assert json.loads((root / status_rel).read_text(encoding="utf-8"))["runs_cap"] == 300
    summary = {"errors": []}
    tick._write_status(root, "RC", "idle", "Idle", summary)
    assert summary["errors"] == []
    assert json.loads((root / status_rel).read_text(encoding="utf-8"))["runs_cap"] == 300


def _code_names(path):
    """NAME tokens of a Python file (comments and strings excluded)."""
    src = path.read_text(encoding="utf-8")
    return {t.string for t in tokenize.generate_tokens(io.StringIO(src).readline)
            if t.type == tokenize.NAME}


def test_no_rc_gate_compares_against_the_constant_runs_cap():
    """RUNS_CAP is the constant 120 in v30; a gate that reads it stops at 120
    while the machine cap is higher. RC gates read `budget.cap`."""
    scanned, offenders = 0, []
    for path in _repo_walk.repo_files(ROOT, ("*.py",)):
        rel = path.relative_to(ROOT).as_posix()
        if not rel.startswith(("ops/", "tools/")) or rel.startswith("ops/fleet_kit/"):
            continue
        scanned += 1
        if "RUNS_CAP" in _code_names(path):
            offenders.append(rel)
    assert scanned > 50, "an empty enumeration would pass vacuously"
    assert offenders == []


# ---------------------------------------------------------------- lane model

def _route_call_keywords():
    tree = ast.parse((ROOT / "ops" / "loop" / "fleet_route.py").read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "do_spawn"]
    assert len(calls) == 1
    return {k.arg for k in calls[0].keywords}


def test_fleet_route_hands_the_kit_no_env_so_child_env_applies():
    kws = _route_call_keywords()
    assert "cwd" in kws and "run" in kws
    assert not kws & {"env", "parent", "python_first"}


def test_child_env_drops_or_sets_the_config_dir_and_puts_python_first(tmp_path):
    fh = _load("fleet_headless")
    parent = {"CLAUDE_CONFIG_DIR": str(tmp_path / "interactive"),
              "PATH": os.pathsep.join([str(tmp_path / "a"), str(tmp_path / "b")])}
    proxy = fh.child_env("http://127.0.0.1:9", parent=dict(parent))
    inherited = [k for k in ("CLAUDE_CONFIG_DIR",) if k in proxy]
    assert inherited == []
    single = fh.child_env("http://127.0.0.1:9", parent=dict(parent),
                          route={"mode": "single", "config_dir": str(tmp_path / "acct")})
    assert single["CLAUDE_CONFIG_DIR"] == str(tmp_path / "acct")
    first = proxy["PATH"].split(os.pathsep)[0]
    assert os.path.normcase(first) == os.path.normcase(str(Path(fh._PY_DIR)))
    kept = fh.child_env("http://127.0.0.1:9", parent=dict(parent), python_first=False)
    assert kept["PATH"] == parent["PATH"]


def test_lane_model_reads_the_machine_default_by_lane_or_lane_note():
    lanes = _load("fleet_lanes")
    cfg = {"lane_model": {"RC": {"repo": "claude-test-kit-default", "true-audit": "sonnet"}}}
    assert lanes.lane_model("RC", "repo", config=cfg) == "claude-test-kit-default"
    assert lanes.lane_model("RC", None, "lane-s144-repo", config=cfg) == "claude-test-kit-default"
    assert lanes.lane_model("RC", None, "lane-s144-true-audit", config=cfg) == "sonnet"
    assert lanes.lane_model("RC", None, "lane-s144-ds", config=cfg) is None
    assert lanes.lane_model("CS", "repo", config=cfg) is None


def _runner_code():
    return "\n".join(ln for ln in RUN_LANE.read_text(encoding="ascii").splitlines()
                     if ln.strip() and not ln.lstrip().startswith("#"))


def test_run_lane_reads_the_kit_lane_model_after_its_own_picks_and_before_the_route():
    code = _runner_code()
    config = code.index("$cfg.executor_model")
    trial = code.index("$env:RC_LANE_MODEL")
    kit_read = code.index("L.lane_model('RC', None, sys.argv[2])")
    kit_win = code.index("{ $model = $kitModel }")
    route = code.index('"--model", $model')
    assert config < trial < kit_read < kit_win < route
    # the accepted shape is the kit's own model rule, byte for byte
    m = re.search(r"\$kitModel -cmatch '([^']+)'\) \{ \$model = \$kitModel \}", code)
    assert m, "the runner's kit lane-model line changed shape"
    assert m.group(1) == _load("fleet_lanes")._MODEL_RE.pattern
    # PowerShell 5.1 does not escape a double quote inside a native argument
    py = re.search(r'^\$laneModelPy = "([^"]*)"$', code, re.MULTILINE)
    assert py and '"' not in py.group(1)
    # the python lookup can never turn into a refusal: it sits in try / catch and
    # the route's exit code is cleared after it
    assert code.index("$global:LASTEXITCODE = $null") > kit_win


def _powershell_51():
    root = os.environ.get("SYSTEMROOT")
    exe = Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe" \
        if root else None
    return exe if exe is not None and exe.is_file() else None


FAKE_ROUTE = (
    "import json, os, sys\n"
    "with open(os.environ['RC_V30_ROUTE_ARGV'], 'w', encoding='ascii') as fh:\n"
    "    json.dump(sys.argv[1:], fh)\n"
)


@pytest.mark.skipif(_powershell_51() is None, reason="Windows PowerShell 5.1 not present")
@pytest.mark.parametrize(("lane_models", "trial", "want"), [
    ({"repo": "claude-test-kit-default"}, "claude-test-trial", "claude-test-kit-default"),
    ({}, "claude-test-trial", "claude-test-trial"),
    ({"ds": "claude-test-kit-default"}, None, None),
])
def test_run_lane_under_powershell_51_takes_the_kit_lane_model_first(
        tmp_path, lane_models, trial, want):
    """The REAL runner bytes under Windows PowerShell 5.1, next to a copy of the
    kit's fleet_lanes and a FAKE fleet_route.py that only records its argv, so
    no claude can start. want None = the runner's own default model."""
    loop = tmp_path / "ops" / "loop"
    loop.mkdir(parents=True)
    (tmp_path / "ops" / "fleet_kit").mkdir()
    shutil.copyfile(RUN_LANE, loop / "run_lane.ps1")
    shutil.copyfile(KIT / "fleet_lanes.py", tmp_path / "ops" / "fleet_kit" / "fleet_lanes.py")
    (loop / "fleet_route.py").write_text(FAKE_ROUTE, encoding="ascii")
    cfg = tmp_path / "lanes.json"
    cfg.write_text(json.dumps({"lane_model": {"RC": lane_models}}), encoding="ascii")
    prompt = tmp_path / "s144-repo.md"
    prompt.write_text("prompt\n", encoding="ascii")
    argv_out, log = tmp_path / "route_argv.json", tmp_path / "lane.log"
    env = {k: v for k, v in os.environ.items() if k != "RC_LANE_MODEL"}
    env["FLEET_LANES_CONFIG"] = str(cfg)
    env["RC_V30_ROUTE_ARGV"] = str(argv_out)
    if trial:
        env["RC_LANE_MODEL"] = trial
    proc = subprocess.run(
        [str(_powershell_51()), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(loop / "run_lane.ps1"), "-PromptFile", str(prompt), "-Cwd", str(tmp_path),
         "-Log", str(log)],
        env=env, cwd=str(tmp_path), capture_output=True, text=True, timeout=120,
        check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    text = log.read_text(encoding="utf-8-sig", errors="replace")
    assert proc.returncode == 0, (proc.returncode, text, proc.stderr)
    argv = json.loads(argv_out.read_text(encoding="ascii"))
    default = re.search(r'^\$model = "([^"]+)"', RUN_LANE.read_text(encoding="ascii"),
                        re.MULTILINE).group(1)
    assert argv[argv.index("--model") + 1] == (want or default)
    assert argv[argv.index("--note") + 1] == "lane-s144-repo"


# ---------------------------------------------------------------- pause, kinds, caps

def test_note_pause_records_a_budget_hold_once_per_hour(tmp_path):
    lanes = _load("fleet_lanes")
    assert {"budget", "limit", "operator", "error", "usd_ceiling"} <= set(lanes.PAUSE_REASONS)
    row = lanes.note_pause(tmp_path, "RC", None, "budget", "budget wait: 400/500")
    assert row is not None and row["reason"] == "budget" and row["tree"] == "RC"
    assert lanes.note_pause(tmp_path, "RC", None, "budget", "again") is None
    assert lanes.note_pause(tmp_path, "RC", None, "not-a-reason", "x") is None
    rows = (tmp_path / lanes.PAUSE_LOG_REL).read_text(encoding="ascii").splitlines()
    assert len(rows) == 1


def test_report_and_probe_are_kinds_and_a_misaddressed_note_is_skipped():
    fh, inbox = _load("fleet_headless"), _load("fleet_inbox")
    assert {"build", "inbox", "triage", "order", "report", "probe"} <= set(fh.KINDS)
    assert {"report", "probe"} <= set(inbox.KINDS)
    assert fh.run_kind("lane-x", "report") == "report"
    other = "2026-11-12-0345-from-MAIN-ORDER-to-CS-x.md"
    assert inbox.addressee(other) == "CS"
    d = inbox.classify(other, "RC")
    assert (d.action, d.reason) == (inbox.SKIP, "addressed to CS")
    assert inbox.classify("2026-11-12-0345-from-MAIN-ORDER-to-RC-x.md", "RC").action == inbox.WORK


def test_checklist_text_clips_and_the_handoff_warns_from_90_percent(tmp_path):
    fc, fd = _load("fleet_checklist"), _load("fleet_done")
    clipped = fc.clip("x" * 300)
    assert len(clipped) == fc.TASK_MAX == 120 and clipped.endswith("...")
    assert fc.clip("a" + chr(0x2014) + "b") == "a?b"  # source stays 7-bit ASCII
    assert fd.HANDOFF_SOON_BYTES == 27648
    handoff = tmp_path / "RC-NEXT-SESSION.txt"
    handoff.write_bytes(b"x\n" * 14000)
    assert (fd.soon_warning(handoff) or "").startswith("warn: ")
    assert fd.size_warning(handoff.stat().st_size) is None
