#!/usr/bin/env python3
"""CI gate for the sibling-name sweep's TREE arm.

WHY THIS FILE EXISTS AND WHY CI DOES NOT CALL THE SWEEP DIRECTLY
---------------------------------------------------------------
``tools/sibling_name_sweep.py`` has two arms. ``--pre-push`` is DIFF scoped and
is wired in ``.githooks/pre-push``. ``--tree`` walks the whole git index and was
wired nowhere, which means every clean verdict this repository has produced
means "clean since the last push", never "clean".

The obvious remedy - a CI step that runs ``--tree`` - is WORSE THAN NOTHING,
and that is measured, not feared. In a checkout with no per-host config, which
is exactly what a CI runner has:

    python tools/sibling_name_sweep.py --tree
    [sibling-sweep] DEGRADED - no per-host config on this machine ...
    [sibling-sweep] clean: 166858934 bytes, 4759 file(s), 0 commit message(s)
    exit 0

``load_config`` returns MODE_DEGRADED when ``ops/moon_sync_repos.json`` is
absent (sibling_name_sweep.py:344). ``_run_scan`` builds needles only under
MODE_ARMED, and ``assert_non_vacuous`` is called only in that same branch
(sibling_name_sweep.py:1098-1100). So the needle arm runs with zero needles,
silently, and the step exits 0. A green tick that proves nothing is this
repository's single most-recorded failure mode, so the job gets a gate that
cannot produce one.

WHAT THIS GATE ASSERTS BEFORE IT REPORTS ANY VERDICT
----------------------------------------------------
1. A POSITIVE CONTROL. A fabricated needle is armed through the same loader the
   real one uses, and it must be caught in a tracked file AS A NAME hit - not
   merely as a structural one. If the needle arm is dead, this fails and the
   tree verdict is never printed.
2. A NEGATIVE CONTROL. The same armed configuration over a file that does not
   carry the token must find nothing. A gate that halts on everything fails in
   the direction that gets it disabled.
3. Both controls again through the real CLI, because the hook consumes EXIT
   CODES and 2 (HALT) must never collapse into 3 (FAULT) or 0.
4. A NON-EMPTY CORPUS floor. A sparse, broken or partial checkout must not read
   as a clean repository (ADR-015).
5. FAULT is never collapsed into a pass.

THE CONTROL NEEDLE IS FABRICATED, AND THE DRIVE PREFIX IS ASSEMBLED
------------------------------------------------------------------
``CONTROL_NAME`` resolves to nothing; it is a token invented here so that this
very file is the haystack for its own positive control - no temporary file, and
the control runs over a REAL tracked blob. The drive prefix is built at run time
rather than spelled, because a literal drive-rooted path anywhere in this file
is a live hit for the sweep's own STRUCTURAL arm, and the job would then halt on
itself. ``test_the_gate_module_carries_no_drive_rooted_path`` pins that.

WHAT THIS GATE DOES NOT CLAIM
-----------------------------
That CI runs the REAL-NAME needle arm. It cannot. The names live only in
gitignored per-host config and this repository is PUBLIC, so the only routes are
an operator-set repository secret (which this job reads as
``RC_MOON_SYNC_REPOS``, so arming it is a settings change and not a code change)
or a scheduled LOCAL task on the machine that holds the config. Until one of
those lands, the tree arm in CI is the config-free STRUCTURAL half plus proven
machinery, and every DEGRADED run says so in capitals. An honest partial verdict
is the goal; a silent one is the thing being banned.

Residual blind spots, stated rather than hidden: LFS OBJECT content is never
scanned (the pointer is, and scans clean truthfully); ``paths-ignore`` keeps
docs-only pushes out of push CI entirely, so the nightly ``schedule`` run is
what bounds how long an md-only byte can sit unscanned - which is why the job
must not be gated away from that event.
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import sibling_name_sweep as sweep  # noqa: E402

EXIT_OK = 0
EXIT_FAIL = 1

# ---------------------------------------------------------------------------
# Anti-vacuity floors.
#
# MEASURED on this tree at 8c576c180: 4759 files, 166858934 bytes scanned. The
# floors sit an order of magnitude below that, because their job is to catch a
# sparse checkout, a failed LFS smudge or a broken path list - not to police the
# tree's size. The sweep already FAULTs on a literally empty enumeration
# (`git ls-files returned nothing - a vacuous tree walk`); these catch the
# nearly-empty case, which looks identical in a log and is not an error.
# ---------------------------------------------------------------------------
MIN_TREE_FILES = 1000
MIN_TREE_BYTES = 1_000_000

# A fabricated token. It names no project, resolves to nothing, and is safe to
# read in a public log. It appears literally on the line below, which is what
# makes THIS FILE the haystack for its own positive control.
CONTROL_NAME = "Zzz-Sweep-Control-Project"

# The file that does NOT carry the token, used as the negative control. It is
# guaranteed to exist (the gate cannot run without it) and it is structurally
# clean, which is asserted by the sweep's own tree arm on every run.
NEGATIVE_CONTROL_FILE = "tools/sibling_name_sweep.py"
POSITIVE_CONTROL_FILE = "tools/sibling_sweep_ci.py"

_DEGRADED_NOTICE = (
    "[sweep-ci] THE NEEDLE ARM DID NOT RUN. It did not pass; it did not "
    "execute. Only the config-free STRUCTURAL arm was evaluated over the tree, "
    "plus the fabricated controls above. To arm the real-name arm here, set the "
    "RC_MOON_SYNC_REPOS repository secret to the per-host path list; the job "
    "already reads it, so no code change is needed. Until then this verdict is "
    "PARTIAL and must not be quoted as 'the tree is clean'."
)


def control_path() -> str:
    """The fabricated control path, assembled so no drive-rooted literal ever
    appears in this file's bytes."""
    return "C" + ":" + "\\" + CONTROL_NAME


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def _synthetic_config():
    return sweep.config_from_parts([control_path()], {})


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Controls, in process. These give STRUCTURED findings, so the positive control
# can assert the NAME arm fired rather than inferring it from an exit code that
# the structural arm could equally have produced.
# ---------------------------------------------------------------------------
def check_positive_control() -> CheckResult:
    cfg = _synthetic_config()
    if cfg.mode != sweep.MODE_ARMED:
        return CheckResult(
            "positive-inprocess", False,
            f"the synthetic config did not arm (mode={cfg.mode})",
        )
    try:
        needles = sweep.build_needles(cfg)
        sweep.assert_non_vacuous(needles)
    except AssertionError as exc:
        return CheckResult("positive-inprocess", False, f"needle build failed: {exc}")
    findings = sweep.scan_text(
        needles, cfg.codes, _read(POSITIVE_CONTROL_FILE),
        path=POSITIVE_CONTROL_FILE, source="TREE", status="T",
    )
    named = [f for f in findings if f.slot >= 0 and f.severity == sweep.SEV_NAME]
    if not named:
        return CheckResult(
            "positive-inprocess", False,
            "a planted needle in a tracked file produced ZERO name findings, so "
            "the needle arm is dead and any tree verdict would be meaningless",
        )
    return CheckResult(
        "positive-inprocess", True,
        f"{len(named)} name finding(s) on the fabricated needle",
    )


def check_negative_control() -> CheckResult:
    cfg = _synthetic_config()
    needles = sweep.build_needles(cfg)
    text = _read(NEGATIVE_CONTROL_FILE)
    findings = sweep.scan_text(
        needles, cfg.codes, text,
        path=NEGATIVE_CONTROL_FILE, source="TREE", status="T",
    )
    findings += sweep.structural_findings(
        text, path=NEGATIVE_CONTROL_FILE, source="TREE", status="T"
    )
    if findings:
        return CheckResult(
            "negative-inprocess", False,
            f"{len(findings)} finding(s) on a control that carries neither the "
            "fabricated needle nor a drive-rooted path, so the gate halts on "
            "everything and would be disabled within a day",
        )
    return CheckResult("negative-inprocess", True, "no findings, as required")


# ---------------------------------------------------------------------------
# Controls, through the real CLI. The hook reads EXIT CODES: 0 clean, 2 HALT,
# 3 FAULT. Those are the contract, and they are not exercised by an in-process
# call.
# ---------------------------------------------------------------------------
def _run_cli(rel_file: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["RC_MOON_SYNC_REPOS"] = control_path()
    env.pop(sweep.BYPASS_ENV, None)
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "sibling_name_sweep.py"),
         "--scan-file", rel_file],
        cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=300,
    )


def check_cli_positive() -> CheckResult:
    proc = _run_cli(POSITIVE_CONTROL_FILE)
    if proc.returncode != sweep.EXIT_HALT:
        return CheckResult(
            "positive-cli", False,
            f"expected exit {sweep.EXIT_HALT} (HALT), got {proc.returncode}. "
            "A FAULT or a clean exit here means the hook's contract is broken.",
        )
    if "ARMED" not in proc.stderr:
        return CheckResult(
            "positive-cli", False,
            "the CLI did not report ARMED under an explicit RC_MOON_SYNC_REPOS",
        )
    return CheckResult("positive-cli", True, f"exit {proc.returncode} (HALT), ARMED")


def check_cli_negative() -> CheckResult:
    proc = _run_cli(NEGATIVE_CONTROL_FILE)
    if proc.returncode != sweep.EXIT_CLEAN:
        return CheckResult(
            "negative-cli", False,
            f"expected exit {sweep.EXIT_CLEAN} (clean), got {proc.returncode}",
        )
    return CheckResult("negative-cli", True, f"exit {proc.returncode} (clean)")


def run_controls() -> List[CheckResult]:
    return [
        check_positive_control(),
        check_negative_control(),
        check_cli_positive(),
        check_cli_negative(),
    ]


# ---------------------------------------------------------------------------
# The tree arm
# ---------------------------------------------------------------------------
def scan_tree():
    """Run the whole-tree arm and return (cfg, stats, findings).

    ``sweep._run_scan`` is reached by name deliberately: it is the one place
    that decides needles-or-not from the mode, and re-implementing that decision
    here would be a second copy of the exact rule this gate is testing.
    """
    cfg = sweep.load_config(root=REPO_ROOT)
    stats = sweep.ScanStats()
    blobs = sweep.collect_tree_blobs(REPO_ROOT, stats)
    stats.diff_nonempty = bool(blobs)
    findings = sweep._run_scan(cfg, blobs, stats)
    return cfg, stats, findings


def _finding_table(findings: Sequence) -> List[str]:
    """Findings WITHOUT literals. `render_report` is equally literal-free but
    its prose says "the push is halted", which is false in a CI job; a job that
    lies about what it did is the thing being fixed here.

    The table is printed over the FULL finding list, known entries included and
    flagged, rather than over the undeclared subset. The index column has to
    line up with `--tree --explain <idx>`, and that flag indexes the sweep's own
    sorted list - a table over a filtered subset would hand the operator index
    numbers that resolve to the wrong finding.
    """
    lines = ["  idx  slot   severity     shape                     file:line"]
    for i, f in enumerate(findings):
        slot = "struct" if f.slot < 0 else f"#{f.slot}"
        flag = "  [KNOWN]" if f.path in sweep.KNOWN_EXCEPTIONS else ""
        lines.append(
            f"  {i:<4} {slot:<6} {f.severity:<12} {f.shape:<25} "
            f"{f.path}:{f.line}{flag}"
        )
    lines.append(
        "  Literals are NEVER printed. Resolve one on the machine that holds "
        "the config: python tools/sibling_name_sweep.py --tree --explain <idx>"
    )
    return lines


def evaluate(
    cfg,
    stats,
    findings: Sequence,
    *,
    min_files: int = MIN_TREE_FILES,
    min_bytes: int = MIN_TREE_BYTES,
) -> Tuple[bool, List[str]]:
    """Pure decision function: (ok, report_lines). No literal ever reaches the
    returned lines, because they are printed into a PUBLIC CI log."""
    lines: List[str] = [sweep.mode_banner(cfg)]
    failures: List[str] = []

    if cfg.mode == sweep.MODE_FAULT:
        failures.append(
            "[sweep-ci] FAULT - the sweep could not run. 'The gate fired' and "
            "'the gate could not run' are different facts and this one is NOT a "
            "clean pass."
        )
    elif cfg.mode == sweep.MODE_DEGRADED:
        lines.append(_DEGRADED_NOTICE)

    if stats.files < min_files:
        failures.append(
            f"[sweep-ci] VACUOUS - the tree arm enumerated {stats.files} file(s), "
            f"below the floor of {min_files}. An empty enumeration and a clean "
            "tree are the same verdict to every consumer (ADR-015), so this is "
            "a broken checkout, not a clean repository."
        )
    if stats.scanned_bytes < min_bytes:
        failures.append(
            f"[sweep-ci] VACUOUS - the tree arm scanned {stats.scanned_bytes} "
            f"byte(s), below the floor of {min_bytes}."
        )

    known = [f for f in findings if f.path in sweep.KNOWN_EXCEPTIONS]
    unknown = [f for f in findings if f.path not in sweep.KNOWN_EXCEPTIONS]

    if known:
        lines.append("")
        lines.append(
            "[sweep-ci] KNOWN, NAMED, VISIBLE EXCEPTION (reported every run, "
            "never a silent allowlist):"
        )
        for rel in sorted({f.path for f in known}):
            n = sum(1 for f in known if f.path == rel)
            lines.append(f"  {rel}  ({n} finding(s))")
            lines.append(f"    reason: {sweep.KNOWN_EXCEPTIONS[rel]}")
        lines.append(
            "  This tolerance is PATH scoped and lives in the sweep's own "
            "registry, not in this job. A NEW finding at the same path is not "
            "distinguishable from the declared one, which is a stated limit of "
            "the tolerance rather than an oversight."
        )

    if unknown:
        failures.append(
            f"[sweep-ci] HALT - {len(unknown)} undeclared finding(s) in the tree. "
            "These are not covered by any declared exception."
        )
        lines.append("")
        lines.extend(_finding_table(findings))

    lines.append("")
    lines.append(
        f"[sweep-ci] coverage: {stats.files} file(s), {stats.scanned_bytes} "
        f"byte(s) content-scanned, {stats.binary_blobs} binary/LFS blob(s) NOT "
        f"content-scanned ({stats.unscanned_bytes} bytes), {stats.lfs_pointers} "
        "LFS pointer(s) scanned as text - a pointer scans clean truthfully but "
        "the OBJECT it points at is never seen by this sweep, and that is a real "
        f"blind spot. {stats.decode_failures} undecodable character(s)."
    )
    return (not failures), lines + failures


def main(argv: Optional[Sequence[str]] = None) -> int:
    print("[sweep-ci] TREE arm gate for tools/sibling_name_sweep.py")

    controls_ok = True
    for check in run_controls():
        print(f"[sweep-ci] control {check.name}: "
              f"{'PASS' if check.ok else 'FAIL'} - {check.detail}")
        controls_ok = controls_ok and check.ok
    if not controls_ok:
        print("[sweep-ci] FAIL - the detection machinery did not prove itself, "
              "so any verdict about the tree would be meaningless. Not running "
              "the tree arm; a clean report from unproven machinery is exactly "
              "the green tick this gate exists to prevent.")
        return EXIT_FAIL

    try:
        cfg, stats, findings = scan_tree()
    except sweep.GitFault as exc:
        print(f"[sweep-ci] FAIL - FAULT during the tree walk: {exc}")
        return EXIT_FAIL
    except AssertionError as exc:
        print(f"[sweep-ci] FAIL - the sweep refused to run vacuously: {exc}")
        return EXIT_FAIL
    except OSError as exc:
        print(f"[sweep-ci] FAIL - FAULT during the tree walk: {exc}")
        return EXIT_FAIL

    ok, lines = evaluate(cfg, stats, findings)
    for line in lines:
        print(line)
    print(f"[sweep-ci] {'PASS' if ok else 'FAIL'}")
    return EXIT_OK if ok else EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
