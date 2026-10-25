"""Truth-gate: pre-commit reconciliation of worker claims against ground truth.

Protocol (insights 2026-06-10 fold-in; companion to .claude/agents/verifier.md):
  1. Re-run the real test suite fresh, capture actual exit code + counts.
  2. Re-read every file a worker claimed to edit; confirm claimed content present.
  3. Probe CI status for HEAD from the authoritative source (gh CLI).
  4. REFUSE (exit 2) if any claim cannot be independently reproduced;
     quarantined slices are listed for re-dispatch.

Reconciliation report written atomically to ops/runtime/truth_gate_report.json.

Claims JSON shape:
  {"run_id": "...",
   "suite_cmd": "%LOCALAPPDATA%/Programs/Python/Python314/python.exe -m pytest -q",            # optional; default full root suite
   "check_ci": true,                           # optional; default true
   "slices": [{"id": "S1", "claim": "...",
               "files": [{"path": "rel/or/abs.py", "must_contain": ["snippet"]}],
               "claimed_passed": 1397, "claimed_failed": 0}]}   # counts optional

suite_cmd runs WITHOUT a shell (RM-757): a list is the argv as given; a string
is split into words (shlex; on Windows one quote layer is stripped per word)
and each word has %VAR% / $VAR expanded, so `&`, `|` and `;` are plain
arguments to an executable. On Windows that holds only for a real .exe:
CreateProcess runs a .bat / .cmd through cmd.exe even without a shell, and
cmd.exe re-parses the arguments. So on Windows truth_gate launches ONLY a
head that is a .exe (argv[0] and the first word after every `--`): a literal
suffix other than .exe is refused before any lookup; a path is normalised and
made absolute; a bare name is resolved ONCE with the kit gate's PATH-only
lookup; and the head is REWRITTEN to that absolute .exe path, so the launcher
does no search of its own. Anything else - .bat, .cmd, .com, .ps1,
extensionless, unresolvable - is refused unrun ("non-exe head refused").
Deny-all, because suffix blocklists leaked. Out of scope: an attacker who can
write into a PATH directory or the repo already has code execution. POSIX is
unchanged.

RM-775 decisions on the Windows head check (adjudicated 2026-10-23):
  (a) A head that still carries a double quote once one matched outer layer
      is stripped is refused: list2cmdline escapes it as \\" but CreateProcess
      reads the module name without honouring that escape, so it would launch
      a different program than the path validated (and no Windows file name
      contains a quote).
  (b) A shell .exe head (`cmd.exe /c ...`, powershell.exe) is ALLOWED. The
      rule is that an argument is never re-parsed by an IMPLICIT cmd.exe; a
      caller naming a shell chose it, `python.exe -c` is equally arbitrary,
      and a shell-name list is the blocklist shape that leaked. Alternative
      refused: a shell-name denylist. Reverses if: a suite_cmd ever reaches
      truth_gate from a source the calling session does not author (an inbox
      or channel note, a headless worker's own file) - then re-open it as an
      allowlist of known test launchers, never a shell denylist.
  (c) `py.test -q` is refused (literal suffix `.test`), a change from the
      shell era: without a shell CreateProcess never appends .exe to a dotted
      name, so it could only run through cmd.exe's PATHEXT, the mechanism
      RM-757 removed. Spell it `py.test.exe` or `python.exe -m pytest`.
      Alternative refused: PATHEXT resolution for dotted bare names (a second
      resolver beside the kit's path_which). Reverses if: a supported
      suite_cmd with a dotted bare head is measured failing in live use.

A command the kit classifies as a whole suite
(fleet_claims.bare_whole_suite) runs through fleet_suite_gate.py run (FLEET
item 16 c); a targeted run is not gated. A gate refusal (exit 3) is reported
as "suite-gate refused", never as pytest counts.

Usage:
  %LOCALAPPDATA%/Programs/Python/Python314/python.exe tools/truth_gate.py --claims claims.json [--skip-suite] [--report PATH] [--owner ID]
"""
import argparse
import importlib.util
import json
import ntpath
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPORT = ROOT / "ops" / "runtime" / "truth_gate_report.json"
KIT_DIR = ROOT / "ops" / "fleet_kit"
GATE_SCRIPT = KIT_DIR / "fleet_suite_gate.py"
GATE_REFUSED_EXIT = 3
CANNOT_RUN_EXIT = 127
OWNER_ENV = "FLEET_CLAIM_OWNER"
IS_WINDOWS = os.name == "nt"

# The bare "py" launcher can resolve to a pytest-less interpreter (e.g. the
# python-manager pythoncore-3.14-64 install), which zeroes the suite and turns
# every gate into a blanket REFUSE. Pin the canonical project interpreter;
# fall back to whichever interpreter is running this script.
# The prefix is resolved from the environment so the pin survives a fresh clone
# under a different Windows account - a hardcoded home path is a gate that
# silently does not run, and a gate that does not run reports nothing.
_CANONICAL_PY = (Path(os.environ.get("LOCALAPPDATA")
                      or (Path.home() / "AppData" / "Local"))
                 / "Programs" / "Python" / "Python314" / "python.exe")
SUITE_PY = str(_CANONICAL_PY if _CANONICAL_PY.exists() else Path(sys.executable))
DEFAULT_SUITE_CMD = f'"{SUITE_PY}" -m pytest -q'

_SUMMARY_TOKEN = re.compile(r"(\d+)\s+(passed|failed|error|errors|skipped|"
                            r"xfailed|xpassed|deselected|warnings?)")


def parse_pytest_summary(text):
    """Parse the final pytest summary line into counts. Last matching line wins."""
    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0,
              "no_tests_ran": False}
    summary_line = None
    for line in text.splitlines():
        if _SUMMARY_TOKEN.search(line) and (" in " in line or "=" in line):
            summary_line = line
        if "no tests ran" in line:
            counts["no_tests_ran"] = True
    if summary_line:
        for num, label in _SUMMARY_TOKEN.findall(summary_line):
            if label.startswith("error"):
                counts["errors"] += int(num)
            elif label in ("passed", "failed", "skipped"):
                counts[label] = int(num)
    return counts


def _kit_module(stem):
    """A vendored fleet-kit module, loaded by path under the same
    `fleet_kit_<stem>` key tools/ci_watchdog.py uses (one instance)."""
    key = "fleet_kit_" + stem
    mod = sys.modules.get(key)
    if mod is None:
        spec = importlib.util.spec_from_file_location(key, KIT_DIR / f"{stem}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[key] = mod
        spec.loader.exec_module(mod)
    return mod


def _strip_quotes(word):
    if len(word) >= 2 and word[0] == word[-1] and word[0] in "\"'":
        return word[1:-1]
    return word


def split_cmd(cmd):
    """argv for a suite_cmd: a list as given, a string split without a shell."""
    if isinstance(cmd, (list, tuple)):
        return [str(w) for w in cmd]
    posix = not IS_WINDOWS
    words = shlex.split(cmd, posix=posix)
    if not posix:
        words = [_strip_quotes(w) for w in words]
    return [os.path.expandvars(w) for w in words]


def _file_key(word):
    """A word's basename as the OS compares file names: on Windows case-folded,
    trailing dots / spaces dropped (Windows ignores them in a file name)."""
    base = _strip_quotes(word).replace("\\", "/").rsplit("/", 1)[-1]
    return base.rstrip(" .").casefold() if IS_WINDOWS else base


def _names_gate(word):
    return _file_key(word) == _file_key(GATE_SCRIPT.name)


def _path_which(name):
    """The kit suite gate's own PATH lookup (PATH only: the cwd, relative and
    empty entries skipped, quotes stripped, PATHEXT on Windows) - one resolver
    for direct and gate-wrapped launches, never reimplemented here."""
    return _kit_module("fleet_suite_gate").path_which(name, cwd=str(ROOT))


def _resolve_head(word):
    """The absolute .exe path to launch for a command word on Windows, else None."""
    word = _strip_quotes(word)
    if '"' in word:
        return None  # RM-775 (a): CreateProcess would not launch the validated path
    word = ntpath.normpath(word)
    suffix = ntpath.splitext(word)[1]
    if suffix and suffix.casefold() != ".exe":
        return None  # the literal word is what CreateProcess would run
    if ntpath.dirname(word):
        target = ntpath.abspath(ntpath.join(str(ROOT), word))
    else:
        target = _path_which(word)
    if not target or ntpath.splitext(target)[1].casefold() != ".exe":
        return None
    return target


def launch_argv(argv):
    """(argv to launch, refused word or None). On Windows each head - argv[0]
    and the first word after EVERY `--`, whatever the wrapper - is resolved
    ONCE and rewritten to the absolute .exe path that was validated, so
    CreateProcess and the suite gate receive that path and do no search of
    their own (no check-vs-launch mismatch). A head whose literal suffix is not
    .exe, or that does not resolve to a .exe, is refused unrun. Why .exe only:
    CreateProcess runs a .bat / .cmd through cmd.exe even without a shell and
    cmd.exe re-parses the arguments; suffix blocklists kept leaking. Threat
    model: an attacker who can already write into a PATH directory or the repo
    has code execution and is out of scope. POSIX: argv unchanged."""
    if not IS_WINDOWS:
        return list(argv), None
    out = list(argv)
    heads = [0] if argv else []
    heads += [i + 1 for i, w in enumerate(argv[:-1]) if _strip_quotes(w) == "--"]
    for i in heads:
        target = _resolve_head(argv[i])
        if target is None:
            return list(argv), argv[i]
        out[i] = target
    return out, None


def refused_head(argv):
    """The head launch_argv refuses, else None (always None on POSIX)."""
    return launch_argv(argv)[1]


def resolve_owner(owner):
    """The suite-gate owner: --owner, else the claims-hook env id, else None."""
    return owner or os.environ.get(OWNER_ENV) or None


def gate_argv(argv, owner):
    """argv wrapped in the kit suite gate when it is a whole suite, else as given."""
    if any(_names_gate(w) for w in argv):
        return list(argv)
    if not _kit_module("fleet_claims").bare_whole_suite(shlex.join(argv)):
        return list(argv)
    who = resolve_owner(owner)
    flag = ["--owner", who] if who else []
    return [sys.executable, str(GATE_SCRIPT), "run", *flag, "--", *argv]


def run_suite_fresh(cmd, out_path, owner=None):
    """Run the suite, tee output to a file, read the FILE back (stale-pipe guard)."""
    out_path = Path(out_path)
    argv, head = launch_argv(split_cmd(cmd))
    if head is not None:
        reason = (f"truth_gate: refused {head!r}: on Windows only a resolved .exe "
                  "head is launched (a .bat/.cmd runs under cmd.exe, which re-parses "
                  "its arguments)")
        out_path.write_text(reason + "\n", encoding="utf-8")
        obs = parse_pytest_summary("")
        obs.update({"exit_code": None, "cmd": cmd, "argv": argv, "gated": False,
                    "gate_refused": False, "head_refused": True,
                    "refuse_reason": reason, "output_file": str(out_path)})
        return obs
    run_argv = gate_argv(argv, owner)
    gated = run_argv != argv
    with open(out_path, "w", encoding="utf-8", errors="replace") as fh:
        try:
            rc = subprocess.run(run_argv, cwd=str(ROOT),
                                stdout=fh, stderr=subprocess.STDOUT).returncode
        except OSError as exc:
            # No shell means no shell "command not found" exit: keep the run
            # a REFUSE (127, the shell's own code) instead of a crash.
            fh.write(f"truth_gate: cannot run {run_argv[:1]!r}: {exc}\n")
            rc = CANNOT_RUN_EXIT
    text = out_path.read_text(encoding="utf-8", errors="replace")
    obs = parse_pytest_summary(text)
    obs["exit_code"] = rc
    obs["cmd"] = cmd
    obs["argv"] = run_argv
    obs["gated"] = gated
    obs["gate_refused"] = gated and rc == GATE_REFUSED_EXIT
    obs["head_refused"] = False
    if obs["gate_refused"]:
        lines = [ln for ln in text.splitlines() if "SUITE-GATE" in ln]
        obs["gate_reason"] = lines[-1].strip()[:200] if lines else ""
    obs["output_file"] = str(out_path)
    return obs


def check_file_claims(file_claims):
    """Re-read each claimed file; confirm existence + every must_contain snippet."""
    out = []
    for fc in file_claims:
        p = Path(fc["path"])
        if not p.is_absolute():
            p = ROOT / p
        rec = {"path": fc["path"], "exists": p.is_file(), "missing_snippets": []}
        if rec["exists"]:
            body = p.read_text(encoding="utf-8", errors="replace")
            rec["missing_snippets"] = [s for s in fc.get("must_contain", [])
                                       if s not in body]
        out.append(rec)
    return out


def check_git():
    def _git(*args):
        # RM-861: quotepath off and a UTF-8 decode, so a non-ASCII name reads
        # as itself (a locale decode faulted on 0x81 and left stdout None).
        r = subprocess.run(["git", "-c", "core.quotepath=false", *args],
                           cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        return r.stdout or ""
    # rstrip only: a leading space is the status column of an unstaged edit.
    status = _git("status", "-s").rstrip("\n")
    head = _git("log", "--oneline", "-1").strip()
    return {"clean": status == "", "dirty_files": status.splitlines(),
            "head": head}


def check_ci(sha="HEAD"):
    """Authoritative CI status via gh. 'unavailable' if gh/runs absent."""
    try:
        if sha == "HEAD":
            r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT),
                               capture_output=True, text=True)
            sha = r.stdout.strip()
        r = subprocess.run(
            ["gh", "run", "list", "--commit", sha, "--limit", "10",
             "--json", "status,conclusion,name"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return {"status": "unavailable", "detail": r.stderr.strip()[:200],
                    "sha": sha}
        runs = json.loads(r.stdout or "[]")
        if not runs:
            return {"status": "no-runs", "sha": sha, "runs": []}
        if any(x["status"] != "completed" for x in runs):
            return {"status": "pending", "sha": sha, "runs": runs}
        if all(x["conclusion"] == "success" for x in runs):
            return {"status": "success", "sha": sha, "runs": runs}
        return {"status": "failure", "sha": sha, "runs": runs}
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        return {"status": "unavailable", "detail": str(e)[:200], "sha": sha}


def reconcile(claims, suite_obs, file_obs_by_slice, git_obs, ci_obs):
    """Cross-check every claim against observations. Any irreproducible claim
    quarantines its slice; suite red or CI failure refuses globally."""
    slices_out = []
    quarantined = []
    refused = ("non-exe head refused" if suite_obs.get("head_refused") else
               "suite-gate refused" if suite_obs.get("gate_refused") else None)
    for sl in claims.get("slices", []):
        disc = []
        for rec in file_obs_by_slice.get(sl["id"], []):
            if not rec["exists"]:
                disc.append("claimed file missing on disk: {}".format(rec["path"]))
            elif rec["missing_snippets"]:
                disc.append("claimed change absent in {}: {}".format(rec["path"], rec["missing_snippets"]))
        for key, seen in (("claimed_passed", "passed"), ("claimed_failed", "failed")):
            claimed = sl.get(key)
            if claimed is None:
                continue
            if refused:
                disc.append(f"{key}={claimed} unverified: {refused}")
            elif suite_obs[seen] != claimed:
                disc.append(f"{key}={claimed} but observed {suite_obs[seen]}")
        verdict = "CONFIRM" if not disc else "QUARANTINE"
        if verdict == "QUARANTINE":
            quarantined.append(sl["id"])
        slices_out.append({"id": sl["id"], "claim": sl.get("claim", ""),
                           "verdict": verdict, "discrepancies": disc})
    global_disc = []
    if suite_obs.get("head_refused"):
        global_disc.append(f"non-exe head refused: {suite_obs.get('refuse_reason', '')}")
    elif refused:
        global_disc.append("suite-gate refused (exit {}): {}".format(
            suite_obs.get("exit_code"), suite_obs.get("gate_reason") or "no reason line"))
    else:
        if suite_obs["failed"] > 0 or suite_obs["errors"] > 0:
            global_disc.append("suite red: {} failed, {} errors".format(suite_obs["failed"], suite_obs["errors"]))
        if suite_obs.get("exit_code") not in (0, None):
            global_disc.append("suite exit_code={}".format(suite_obs["exit_code"]))
        if suite_obs.get("no_tests_ran"):
            global_disc.append("no tests ran")
    if ci_obs.get("status") == "failure":
        global_disc.append("ci failure at {}".format(ci_obs.get("sha", "?")))
    verdict = "REFUSE" if (quarantined or global_disc) else "PROCEED"
    return {"run_id": claims.get("run_id", ""), "verdict": verdict,
            "suite": suite_obs, "git": git_obs, "ci": ci_obs,
            "slices": slices_out, "quarantined": quarantined,
            "global_discrepancies": global_disc,
            "action": ("commit allowed" if verdict == "PROCEED" else
                       "COMMIT BLOCKED - re-dispatch quarantined slices "
                       "with the discrepancy list as added context")}


def load_claims(path):
    """utf-8-sig tolerates the BOM PowerShell 5.1 Out-File -Encoding utf8 emits."""
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_report_atomic(report, target):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=2), encoding="utf-8")
    tmp.replace(target)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Truth-gate pre-commit reconciler")
    ap.add_argument("--claims", required=True)
    ap.add_argument("--report", default=str(DEFAULT_REPORT))
    ap.add_argument("--skip-suite", action="store_true",
                    help="reuse no suite run; suite counts come back zeroed "
                         "and count-claims will quarantine (debug only)")
    ap.add_argument("--owner", default=None,
                    help="suite-gate owner for a whole-suite run "
                         f"(default: env {OWNER_ENV})")
    args = ap.parse_args(argv)

    claims = load_claims(args.claims)
    if args.skip_suite:
        suite_obs = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0,
                     "no_tests_ran": False, "exit_code": None,
                     "cmd": "(skipped)"}
    else:
        suite_obs = run_suite_fresh(claims.get("suite_cmd", DEFAULT_SUITE_CMD),
                                    ROOT / "ops" / "runtime" / "truth_gate_suite.txt",
                                    owner=args.owner)
    file_obs = {sl["id"]: check_file_claims(sl.get("files", []))
                for sl in claims.get("slices", [])}
    git_obs = check_git()
    ci_obs = (check_ci() if claims.get("check_ci", True)
              else {"status": "skipped"})

    report = reconcile(claims, suite_obs, file_obs, git_obs, ci_obs)
    write_report_atomic(report, args.report)
    print(json.dumps({k: report[k] for k in
                      ("verdict", "quarantined", "global_discrepancies")}))
    print(f"report: {args.report}")
    return 0 if report["verdict"] == "PROCEED" else 2


if __name__ == "__main__":
    sys.exit(main())
