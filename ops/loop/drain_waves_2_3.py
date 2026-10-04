"""Headless launcher for waves 2 and 3 of the orchestrated RC open-rows drain.

Runs SEQUENTIALLY, every headless `claude` through RC's one door into the fleet
kit (`ops/loop/fleet_route.spawn` -> `ops/fleet_kit/fleet_headless.spawn`, with
the fail-closed proxy gate of `ops/loop/headless_env.py` in front of it):

  wave 2: three BUILD runs (atomic, tail-roadmap, tail-backlog), each in its own
          worktree cut from origin/main, at most 3 at once; a separate read-only
          VERIFIER run per build (the producer never grades itself); then ONE
          MERGER run in the main tree (cherry-pick verified commits, bookkeeping,
          sibling-name sweep before push, halt without push on any hit).
  wave 3: the same shape for the single `ascii` slice - only if wave 2's merger
          pushed (wave 3 is cut from origin/main AFTER wave 2).

Prompt text is the workflow script's COMMON / WAVE2 / wave-3 ascii / verifier /
merger prompts, vendored as files under ops/loop/prompts/drain_w*.md with a
headless addendum (result file, worktree, read-only verifier).

Files (all gitignored, written atomically):
  ops/loop/control/progress/drain-waves-2-3.json   launcher progress (item 12)
  ops/loop/control/progress/<Wave>-<slice>[-verify].json, <Wave>-merge.json
  ops/loop/control/drain/*.json                     per-run result / input files
  ops/loop/control/drain/*.out.txt                  per-run final text + stderr
  ops/runtime/drain_waves_2_3_result.json           final result
  logs/drain_waves_2_3.log                          launcher log

Kit choices (FLEET-COMMON item 10): writes_code=True everywhere, so the kit picks
`opus`; effort is the kit's pick for the note (medium) because fleet_route has no
effort parameter (kit-gap, not patched here). Permissions follow the lane runner
(ops/loop/run_lane.ps1): --dangerously-skip-permissions; the verifier also gets
--disallowedTools Edit,Write,NotebookEdit. No ops/loop/slots.py slot is taken:
its slot root lives outside the repo root, which is RC's halt boundary.

Halt switch: create ops/loop/control/DRAIN_STOP; checked before every spawn. The
global ops/loop/control/STOP belongs to the loop controller and is NOT read here.

Usage:
  pythonw ops/loop/drain_waves_2_3.py            # real run (background)
  python  ops/loop/drain_waves_2_3.py --dry-run  # print spawn argv, spawn nothing
  pythonw ops/loop/drain_waves_2_3.py --waves 2 --only atomic,tail-roadmap
                                                 # re-run just those slices
  --waves 2|3|2,3 selects waves (default 2,3); --only <slice keys, comma-separated>
  keeps only those slices (a wave left with none is skipped). With wave 2 and 3
  both selected, wave 3 still runs only if wave 2's merger pushed; --waves 3
  alone runs wave 3 unconditionally.

Worktrees are created SERIALLY (one lock, before any run is spawned) and a
`git worktree add` that fails on the "could not lock" class (.git/config,
index.lock) is retried with short backoff, at most WT_ADD_TRIES times. A slice
whose worktree setup still fails is recorded as status "not-run" in the result
JSON and listed as NOT RUN in the merger prompt.
Exit: 0 done, 1 failed, 2 halted (merger did not push / DRAIN_STOP), 3 refused.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASK = "drain-waves-2-3"
CALLER = "drain_waves_2_3"
PROMPTS = ROOT / "ops" / "loop" / "prompts"
CONTROL = ROOT / "ops" / "loop" / "control"
PROGRESS = CONTROL / "progress"
DRAIN_DIR = CONTROL / "drain"
STOP_FILE = CONTROL / "DRAIN_STOP"
RESULT = ROOT / "ops" / "runtime" / "drain_waves_2_3_result.json"
LOCK = ROOT / "ops" / "runtime" / "drain_waves_2_3.lock"
LOG = ROOT / "logs" / "drain_waves_2_3.log"
WT_BASE = ROOT / ".claude" / "worktrees"

BUILD_TIMEOUT_S = 7200
VERIFY_TIMEOUT_S = 3600
MERGE_TIMEOUT_S = 5400
MAX_PARALLEL = 3
RUNS_NEEDED = 10  # full plan: 3 build + 3 verify + 1 merge + 1 build + 1 verify + 1 merge
WT_ADD_TRIES = 5
WT_ADD_BACKOFF_S = (0.5, 1.0, 2.0, 4.0)
_LOCK_MARKERS = ("could not lock", "index.lock", "unable to create",
                 "unable to write upstream branch configuration")
BG_WAIT_MS = "2400000"  # same ceiling as ops/loop/run_lane.ps1

BUILD_EXTRA = ("--dangerously-skip-permissions",)
VERIFY_EXTRA = ("--dangerously-skip-permissions", "--disallowedTools",
                "Edit,Write,NotebookEdit")
MERGE_EXTRA = BUILD_EXTRA

WAVES = (
    {"tag": "Wave2", "note": "Wave 2 of 3, cut from origin/main AFTER wave 1 merge (main @@BASE_SHA@@).",
     "slices": (("atomic", "drain_w2_atomic.md"),
                ("tail-roadmap", "drain_w2_tail_roadmap.md"),
                ("tail-backlog", "drain_w2_tail_backlog.md"))},
    {"tag": "Wave3", "note": "Wave 3 of 3, cut from origin/main after wave 2.",
     "slices": (("ascii", "drain_w3_ascii.md"),)},
)
# Wave-relative share of the launcher's 0-100 progress.
WAVE_SPAN = {"Wave2": (0, 60), "Wave3": (60, 100)}
ETA_S = {"Wave2": BUILD_TIMEOUT_S // 2 + VERIFY_TIMEOUT_S // 2 + MERGE_TIMEOUT_S // 2,
         "Wave3": BUILD_TIMEOUT_S // 2 + VERIFY_TIMEOUT_S // 2 + MERGE_TIMEOUT_S // 2}

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
_log_lock = threading.Lock()
_wt_lock = threading.Lock()  # serializes `git worktree add` / branch creation
_sleep = time.sleep  # seam for tests


# ---------------------------------------------------------------- io helpers

def _say(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}"
    with _log_lock:
        try:
            LOG.parent.mkdir(parents=True, exist_ok=True)
            with LOG.open("a", encoding="ascii", errors="replace", newline="\n") as fh:
                fh.write(line + "\n")
        except OSError:
            pass
        if sys.stdout is not None:  # pythonw: stdout is None
            try:
                sys.stdout.write(msg + "\n")
                sys.stdout.flush()
            except (OSError, ValueError):
                pass


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(text, encoding="ascii", errors="replace", newline="\n")
    tmp.replace(path)


def _write_json(path: Path, obj) -> None:
    _atomic_write(path, json.dumps(obj, indent=1, ensure_ascii=True))


def _progress(task: str, pct, step: str, eta_s, status: str) -> None:
    doc = {"task": task, "pct": max(0, min(100, int(pct))), "step": str(step)[:200],
           "eta_s": None if eta_s is None else max(0, int(eta_s)), "status": status,
           "updated": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    try:
        _write_json(PROGRESS / f"{task}.json", doc)
    except OSError:
        pass


def _load_by_path(name: str, path: Path):
    mod = sys.modules.get(name)
    if mod is not None:
        return mod
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _fleet_route():
    return _load_by_path("rc_ops_loop_fleet_route", ROOT / "ops" / "loop" / "fleet_route.py")


def _git(*args, cwd: Path = ROOT, timeout: float = 300) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout,
                          stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)


def _prompt_file(name: str) -> str:
    return (PROMPTS / name).read_text(encoding="ascii").strip("\n")


def _fill(text: str, values: dict) -> str:
    for k, v in values.items():
        text = text.replace(f"@@{k}@@", str(v))
    if "@@" in text:
        raise ValueError("unfilled placeholder in prompt: " + text[text.index("@@"):][:40])
    return text


def _last_json(text: str):
    """The last top-level JSON object in a run's final text, or None."""
    if not text:
        return None
    dec = json.JSONDecoder()
    i = text.rfind("{")
    while i >= 0:
        try:
            obj, _end = dec.raw_decode(text[i:])
            if isinstance(obj, dict):
                return obj
        except ValueError:
            pass
        i = text.rfind("{", 0, i)
    return None


def _read_result(path: Path, final_text: str):
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(obj, dict):
            return obj
    except (OSError, ValueError):
        pass
    return _last_json(final_text)


# ---------------------------------------------------------------- plan

def _paths(tag: str, key: str) -> dict:
    lo = tag.lower()
    return {
        "branch": f"drain/{lo}-{key}",
        "worktree": WT_BASE / f"drain-{lo}-{key}",
        "build_task": f"{tag}-{key}",
        "verify_task": f"{tag}-{key}-verify",
        "build_result": DRAIN_DIR / f"{tag}-{key}.build.json",
        "verify_result": DRAIN_DIR / f"{tag}-{key}.verify.json",
    }


def build_prompt(tag: str, note: str, key: str, rows_file: str, base_sha: str) -> str:
    p = _paths(tag, key)
    common = _fill(_prompt_file("drain_w23_common.md"), {
        "WORKTREE": p["worktree"], "BRANCH": p["branch"], "BASE_SHA": base_sha,
        "RESULT_FILE": p["build_result"]})
    wave_note = _fill(note, {"BASE_SHA": base_sha})
    rows = _prompt_file(rows_file)
    return (f"{common}\n{wave_note}\nSLICE: {tag}-{key}. Progress file name: "
            f"{tag}-{key}.json.\nROWS:\n{rows}\n")


def verify_prompt(tag: str, key: str) -> str:
    p = _paths(tag, key)
    return _fill(_prompt_file("drain_w23_verifier.md"), {
        "BUILD_RESULT": p["build_result"], "WORKTREE": p["worktree"],
        "BRANCH": p["branch"], "SLICE": f"{tag}-{key}", "TASK": p["verify_task"],
        "RESULT_FILE": p["verify_result"]}) + "\n"


def merge_prompt(tag: str, not_run=()) -> str:
    """`not_run`: (slice task, reason) pairs whose worktree setup failed."""
    extra = ""
    if not_run:
        extra = ("NOT RUN (worktree setup failed; no build, no verdict, nothing to merge - "
                 "list each in notes as not-run, do not drop or close its rows): "
                 + "; ".join(f"{t}: {' '.join(str(r).replace('@@', '@ @').split())[:160]}"
                             for t, r in not_run))
    return _fill(_prompt_file("drain_w23_merger.md"), {
        "TAG": tag, "MERGE_INPUT": DRAIN_DIR / f"{tag}-merge-input.json",
        "EXTRA": extra, "RESULT_FILE": DRAIN_DIR / f"{tag}.merge.json"}) + "\n"


# ---------------------------------------------------------------- spawning

class Halted(RuntimeError):
    pass


def _spawn(prompt: str, *, task: str, extra, cwd: Path, timeout: float) -> dict:
    """One headless run through fleet_route. Returns {rc, result, error, stderr}."""
    if STOP_FILE.exists():
        raise Halted(f"{STOP_FILE.name} present before {task}")
    fr = _fleet_route()
    out = DRAIN_DIR / f"{task}.out.txt"
    _say(f"spawn {task} cwd={cwd} timeout={int(timeout)}s prompt={len(prompt)} chars")
    t0 = time.time()
    try:
        line, proc = fr.spawn(prompt, caller=CALLER, note=f"drain-{task}", writes_code=True,
                              bare=False, extra=tuple(extra), cwd=cwd, timeout=timeout)
    except fr.RouteRefused as exc:
        _say(f"REFUSED {task}: {exc.reason} {exc.detail}")
        return {"rc": None, "result": None, "error": f"refused:{exc.reason}", "stderr": ""}
    except subprocess.TimeoutExpired:
        _say(f"TIMEOUT {task} after {int(time.time() - t0)}s (process tree killed by kit)")
        return {"rc": None, "result": None, "error": "timeout", "stderr": ""}
    text = line.get("result")
    if text is None and proc is not None:
        text = proc.stdout
    stderr = (getattr(proc, "stderr", "") or "") if proc is not None else ""
    try:
        _atomic_write(out, f"rc={line.get('rc')} model={line.get('model')} "
                           f"effort={line.get('effort')} cost={line.get('cost_usd')}\n"
                           f"--- result ---\n{text or ''}\n--- stderr ---\n{stderr[-20000:]}\n")
    except OSError:
        pass
    _say(f"end {task} rc={line.get('rc')} {int(time.time() - t0)}s")
    return {"rc": line.get("rc"), "result": text, "error": line.get("error"), "stderr": stderr}


def _is_lock_error(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in _LOCK_MARKERS)


def _ensure_worktree(tag: str, key: str) -> Path:
    """Create (or reuse) the slice worktree. Serialized across threads by
    `_wt_lock`; a "could not lock" failure is retried with backoff. Branch
    existence is re-probed every attempt: a failed `-b` add can leave the branch
    ref behind (its upstream config write lost), so the retry attaches to it."""
    p = _paths(tag, key)
    wt, branch = p["worktree"], p["branch"]
    with _wt_lock:
        if (wt / ".git").exists():
            _say(f"reuse worktree {wt}")
            return wt
        WT_BASE.mkdir(parents=True, exist_ok=True)
        err, attempt = "", 0
        for attempt in range(1, WT_ADD_TRIES + 1):
            exists = _git("rev-parse", "--verify", "--quiet", branch).returncode == 0
            args = (["worktree", "add", str(wt), branch] if exists
                    else ["worktree", "add", "-b", branch, str(wt), "origin/main"])
            r = _git(*args)
            if r.returncode == 0 and (wt / ".git").exists():
                return wt
            err = (r.stderr or r.stdout or "").strip()
            if not _is_lock_error(err) or attempt == WT_ADD_TRIES:
                break
            delay = WT_ADD_BACKOFF_S[min(attempt - 1, len(WT_ADD_BACKOFF_S) - 1)]
            _say(f"worktree add {branch} attempt {attempt} hit a git lock; retry in {delay}s")
            _sleep(delay)
        raise RuntimeError(f"worktree add failed for {branch} after {attempt} attempt(s): "
                           f"{err[:300]}")


def _new_entry(tag: str, key: str) -> dict:
    p = _paths(tag, key)
    return {"key": key, "branch": p["branch"], "worktree": str(p["worktree"]),
            "status": "pending", "build": None, "verdict": None, "error": None}


def _setup_worktrees(tag: str, slices) -> dict:
    """Create every slice worktree SERIALLY, before any run is spawned.
    Returns {key: (Path, None) | (None, error)}."""
    out = {}
    for key, _rows in slices:
        try:
            out[key] = (_ensure_worktree(tag, key), None)
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            err = f"worktree: {exc}"
            _say(f"{tag}-{key} NOT RUN: {err[:200]}")
            _progress(_paths(tag, key)["build_task"], 0, err, None, "failed")
            out[key] = (None, err)
    return out


def _slice(tag: str, note: str, key: str, rows_file: str, base_sha: str,
           wt: Path | None = None) -> dict:
    p = _paths(tag, key)
    entry = _new_entry(tag, key)
    if wt is None:
        try:
            wt = _ensure_worktree(tag, key)
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            entry["error"] = f"worktree: {exc}"
            entry["status"] = "not-run"
            _progress(p["build_task"], 0, entry["error"], None, "failed")
            return entry
    entry["status"] = "ran"
    _progress(p["build_task"], 0, "build run starting", BUILD_TIMEOUT_S, "running")
    b = _spawn(build_prompt(tag, note, key, rows_file, base_sha), task=p["build_task"],
               extra=BUILD_EXTRA, cwd=wt, timeout=BUILD_TIMEOUT_S)
    entry["build"] = _read_result(p["build_result"], b["result"])
    if entry["build"] is None:
        entry["error"] = f"build produced no result ({b['error'] or 'rc=' + str(b['rc'])})"
        _progress(p["build_task"], 100, entry["error"], 0, "failed")
        return entry
    _write_json(p["build_result"], entry["build"])  # pin what the verifier reads
    _progress(p["verify_task"], 0, "verifier run starting", VERIFY_TIMEOUT_S, "running")
    v = _spawn(verify_prompt(tag, key), task=p["verify_task"], extra=VERIFY_EXTRA,
               cwd=wt, timeout=VERIFY_TIMEOUT_S)
    entry["verdict"] = _read_result(p["verify_result"], v["result"])
    if entry["verdict"] is None:
        entry["error"] = f"verifier produced no verdict ({v['error'] or 'rc=' + str(v['rc'])})"
        _progress(p["verify_task"], 100, entry["error"], 0, "failed")
    else:
        _progress(p["verify_task"], 100, "verdict recorded", 0, "done")
    return entry


def run_wave(wave: dict, state: dict) -> dict:
    tag, (lo, hi) = wave["tag"], WAVE_SPAN[wave["tag"]]
    _progress(TASK, lo, f"{tag}: fetch origin", ETA_S[tag], "running")
    f = _git("fetch", "origin", timeout=600)
    if f.returncode != 0:
        raise RuntimeError(f"git fetch failed: {f.stderr.strip()[:300]}")
    base_sha = _git("rev-parse", "origin/main").stdout.strip()
    _say(f"{tag}: base origin/main {base_sha}")
    _progress(TASK, lo + 2, f"{tag}: {len(wave['slices'])} build+verify runs from {base_sha[:9]}",
              ETA_S[tag], "running")
    setup = _setup_worktrees(tag, wave["slices"])
    entries = []
    runnable = []
    for key, rows in wave["slices"]:
        wt, err = setup[key]
        if wt is None:
            e = _new_entry(tag, key)
            e["status"], e["error"] = "not-run", err
            entries.append(e)
        else:
            runnable.append((key, rows, wt))
    if runnable:
        with cf.ThreadPoolExecutor(max_workers=min(MAX_PARALLEL, len(runnable))) as ex:
            futs = [(key, ex.submit(_slice, tag, wave["note"], key, rows, base_sha, wt))
                    for key, rows, wt in runnable]
            for key, fut in futs:
                try:
                    entries.append(fut.result())
                except Halted:
                    raise
                except Exception as exc:  # noqa: BLE001 - one slice must not sink the wave record
                    e = _new_entry(tag, key)
                    e["status"], e["error"] = "failed", f"{type(exc).__name__}: {exc}"
                    entries.append(e)
    order = {key: i for i, (key, _rows) in enumerate(wave["slices"])}
    entries.sort(key=lambda e: order.get(e.get("key"), len(order)))
    not_run = [(f"{tag}-{e['key']}", e.get("error")) for e in entries
               if e.get("status") == "not-run"]
    not_run_tasks = [t for t, _ in not_run]
    summary = [{"key": e.get("key"), "status": e.get("status"), "error": e.get("error")}
               for e in entries]
    for e in entries:
        if isinstance(e.get("build"), dict):
            for it in e["build"].get("items") or []:
                if isinstance(it, dict) and it.get("status") in ("blocked", "skipped"):
                    state["blocked_rows"].append(f"{it.get('id')}: {it.get('summary')}")
    merge_input = DRAIN_DIR / f"{tag}-merge-input.json"
    _write_json(merge_input, entries)
    if not any(isinstance(e.get("verdict"), dict) for e in entries):
        return {"merged": [], "dropped": [], "pushed": False, "main_sha": "",
                "halted_reason": "no slice produced a verdict - merger not run",
                "slices": summary, "not_run": not_run_tasks}
    dirty = _git("status", "--porcelain", "--untracked-files=no").stdout.strip()
    if dirty:
        return {"merged": [], "dropped": [], "pushed": False, "main_sha": "",
                "halted_reason": "main tree has tracked changes - merger not run",
                "slices": summary, "not_run": not_run_tasks}
    _progress(TASK, lo + (hi - lo) * 2 // 3, f"{tag}: merger run", MERGE_TIMEOUT_S, "running")
    _progress(f"{tag}-merge", 0, "merger run starting", MERGE_TIMEOUT_S, "running")
    m = _spawn(merge_prompt(tag, not_run), task=f"{tag}-merge", extra=MERGE_EXTRA, cwd=ROOT,
               timeout=MERGE_TIMEOUT_S)
    res = _read_result(DRAIN_DIR / f"{tag}.merge.json", m["result"])
    if not isinstance(res, dict):
        res = {"merged": [], "dropped": [], "pushed": False, "main_sha": "",
               "halted_reason": f"merger produced no result ({m['error'] or 'rc=' + str(m['rc'])})"}
    res["slices"] = summary
    res["not_run"] = not_run_tasks
    return res


# ---------------------------------------------------------------- selection

def select_waves(waves_arg: str | None, only_arg: str | None) -> list:
    """Filter WAVES by --waves ("2", "3", "2,3") and --only (slice keys).
    Waves left with no slice are dropped. Raises ValueError on a bad value."""
    by_num = {w["tag"][len("Wave"):]: w for w in WAVES}
    if waves_arg is None:
        nums = list(by_num)
    else:
        nums = [n.strip() for n in waves_arg.split(",") if n.strip()]
        if not nums or any(n not in by_num for n in nums):
            raise ValueError(f"--waves must be from {sorted(by_num)} (comma-separated), "
                             f"got {waves_arg!r}")
    chosen = [w for n, w in by_num.items() if n in nums]  # WAVES order, never user order
    keys = None
    if only_arg is not None:
        keys = [k.strip() for k in only_arg.split(",") if k.strip()]
        known = {k for w in chosen for k, _ in w["slices"]}
        bad = [k for k in keys if k not in known]
        if not keys or bad:
            raise ValueError(f"--only: unknown slice(s) {bad or only_arg!r} for the selected "
                             f"waves; known: {sorted(known)}")
    out = []
    for w in chosen:
        slices = tuple((k, r) for k, r in w["slices"] if keys is None or k in keys)
        if slices:
            out.append({**w, "slices": slices})
    if not out:
        raise ValueError("selection is empty")
    return out


def runs_needed(waves) -> int:
    """Build + verify per slice, plus one merger per wave."""
    return sum(2 * len(w["slices"]) + 1 for w in waves)


# ---------------------------------------------------------------- lock

def _pid_alive(pid: int) -> bool:
    try:
        slots = _load_by_path("rc_ops_loop_slots", ROOT / "ops" / "loop" / "slots.py")
        return bool(slots.pid_alive(pid))
    except Exception:  # noqa: BLE001 - unknown = assume alive (fail closed)
        return True


def _take_lock() -> bool:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("ascii"))
            os.close(fd)
            return True
        except FileExistsError:
            try:
                pid = int(LOCK.read_text(encoding="ascii").strip() or 0)
            except (OSError, ValueError):
                pid = 0
            if pid and _pid_alive(pid):
                return False
            try:
                LOCK.unlink()  # stale lock of a dead launcher: a pid record, not data
            except OSError:
                return False
    return False


# ---------------------------------------------------------------- main

def _finish(state: dict, status: str, code: int) -> int:
    state["status"] = status
    state["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    head = _git("rev-parse", "main").stdout.strip()
    state["main_sha"] = state.get("main_sha") or head
    _write_json(RESULT, state)
    _progress(TASK, 100, f"{status}: merged {len(state['merged_ids'])}, dropped "
              f"{len(state['dropped_ids'])}, pushed {state['pushed']}", 0,
              "done" if status == "done" else "failed")
    _say(f"finish status={status} result={RESULT}")
    return code


def run(waves=None) -> int:
    waves = list(WAVES) if waves is None else list(waves)
    needed = runs_needed(waves)
    if not _take_lock():
        _say("another drain_waves_2_3 launcher holds the lock - exiting")
        return 3
    os.environ["CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"] = BG_WAIT_MS  # this process + children only
    state = {"task": TASK, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "waves": {},
             "merged_ids": [], "dropped_ids": [], "pushed": False, "main_sha": "",
             "blocked_rows": [], "not_run": [], "status": "running",
             "selection": {w["tag"]: [k for k, _ in w["slices"]] for w in waves}}
    try:
        k = _fleet_route().kit()
        used = k.RunBudget(ROOT / k.BUDGET_REL).used()
        if used + needed > k.RUNS_CAP:
            _say(f"run budget {used}/{k.RUNS_CAP} leaves no room for {needed} runs")
            state["error"] = "run budget"
            return _finish(state, "refused", 3)
        fr = _fleet_route()
        he = fr._headless_env()
        try:
            he.resolve_base_url(caller=CALLER)
        except he.HeadlessRouteRefused as exc:
            state["error"] = f"refused:{exc.reason}"
            return _finish(state, "refused", 3)
        # Selected waves run in order; a later wave runs only if the earlier
        # SELECTED wave pushed (so --waves 3 alone runs wave 3 unconditionally).
        for wave in waves:
            res = run_wave(wave, state)
            state["waves"][wave["tag"]] = res
            state["not_run"] += list(res.get("not_run") or [])
            state["merged_ids"] += list(res.get("merged") or [])
            state["dropped_ids"] += list(res.get("dropped") or [])
            state["pushed"] = bool(res.get("pushed"))
            state["main_sha"] = res.get("main_sha") or state["main_sha"]
            _write_json(RESULT, state)
            if not res.get("pushed"):
                state["error"] = f"{wave['tag']} not pushed: {res.get('halted_reason')}"
                return _finish(state, "halted", 2)
        return _finish(state, "done", 0)
    except Halted as exc:
        state["error"] = str(exc)
        return _finish(state, "halted", 2)
    except Exception as exc:  # noqa: BLE001 - the result file must say how it ended
        state["error"] = f"{type(exc).__name__}: {exc}"
        _say(f"FAILED {state['error']}")
        return _finish(state, "failed", 1)
    finally:
        try:
            LOCK.unlink()
        except OSError:
            pass


def dry_run(waves=None) -> int:
    """Resolve the route and print the argv each run would use. Spawns nothing,
    counts no budget, creates no worktree, writes no progress file."""
    fr = _fleet_route()
    k = fr.kit()
    he = fr._headless_env()
    print(f"route: ops/loop/fleet_route.spawn -> ops/fleet_kit/fleet_headless.spawn "
          f"(kit v{k.KIT_VERSION}); gate ops/loop/headless_env.resolve_base_url")
    try:
        url = he.resolve_base_url(caller=CALLER + "_dryrun")
    except he.HeadlessRouteRefused as exc:
        print(f"REFUSED (fail closed): {exc.reason} {exc.detail}".rstrip())
        return 3
    try:
        k.check_url(url)
        exe = k.claude_exe()
    except k.Refused as exc:
        print(f"REFUSED by kit (fail closed): {exc}")
        return 3
    print("proxy: set, loopback, listening (URL not printed)")
    budget = k.RunBudget(ROOT / k.BUDGET_REL)
    waves = list(WAVES) if waves is None else list(waves)
    print(f"budget: {budget.used()}/{k.RUNS_CAP} used in window; this launcher needs "
          f"{runs_needed(waves)}")
    base_sha = _git("rev-parse", "origin/main").stdout.strip() or "<origin/main>"
    plan = []
    for wave in waves:
        tag = wave["tag"]
        for key, rows in wave["slices"]:
            p = _paths(tag, key)
            plan.append((p["build_task"], build_prompt(tag, wave["note"], key, rows, base_sha),
                         BUILD_EXTRA, p["worktree"], BUILD_TIMEOUT_S))
            plan.append((p["verify_task"], verify_prompt(tag, key), VERIFY_EXTRA,
                         p["worktree"], VERIFY_TIMEOUT_S))
        plan.append((f"{tag}-merge", merge_prompt(tag), MERGE_EXTRA, ROOT, MERGE_TIMEOUT_S))
    rc = 0
    for task, prompt, extra, cwd, timeout in plan:
        k.check_door(False, extra, False)
        model, effort = k.pick_model(True), k.pick_effort(f"drain-{task}")
        argv = k.build_argv(exe, prompt, model, effort, False, None, extra)
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
        shown = [f"<prompt {len(prompt)} chars sha256:{digest}>" if a == prompt else a for a in argv]
        ok = len(prompt) <= k.ARGV_PROMPT_MAX and all(c < "\x80" for c in prompt)
        rc = rc or (0 if ok else 1)
        print(f"\n[{task}] cwd={cwd} timeout={timeout}s ascii+size_ok={ok}")
        print("  argv: " + " ".join(shown))
    return rc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="print the spawn argv each run would use; spawn nothing")
    ap.add_argument("--waves", default=None, metavar="2|3|2,3",
                    help="waves to run (default 2,3); wave 3 after wave 2 still needs "
                         "wave 2's merger to push")
    ap.add_argument("--only", default=None, metavar="KEYS",
                    help="comma-separated slice keys to run, e.g. atomic,tail-roadmap")
    args = ap.parse_args(argv)
    try:
        waves = select_waves(args.waves, args.only)
    except ValueError as exc:
        ap.error(str(exc))
    return dry_run(waves) if args.dry_run else run(waves)


if __name__ == "__main__":
    raise SystemExit(main())
