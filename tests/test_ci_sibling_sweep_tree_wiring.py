"""The sibling-name sweep's TREE arm must be wired into CI, and the job that
runs it must be incapable of passing vacuously.

THE GAP THIS MODULE CLOSES
--------------------------
``tools/sibling_name_sweep.py`` ships two arms. ``--pre-push`` is DIFF scoped
and is wired in ``.githooks/pre-push`` ahead of the preserved
``git lfs pre-push "$@"``. ``--tree`` walks the whole git index and, until this
module landed, was wired NOWHERE - not a hook, not a CI job, not a scheduled
task.

The consequence is not subtle. Every clean verdict this repository has produced
means "clean since the last push", never "clean". An offending byte is
invisible to the diff arm the moment it is one push old, which is why the
standing record said five escapes while a tree-scope scan finds more.

THE MEASUREMENT THAT SHAPES THE DESIGN
--------------------------------------
Run in a worktree with no per-host config, which is exactly CI's situation:

    python tools/sibling_name_sweep.py --tree
    [sibling-sweep] DEGRADED - no per-host config on this machine ...
    [sibling-sweep] clean: 166858934 bytes, 4759 file(s), 0 commit message(s)
    exit 0

``load_config`` returns MODE_DEGRADED when ``ops/moon_sync_repos.json`` is
absent, ``_run_scan`` builds needles ONLY under MODE_ARMED, and
``assert_non_vacuous`` is called only in that same branch. So a bare
``--tree`` CI step exits 0 having run the NEEDLE arm with zero needles. That is
a green light that proves nothing, and it is this repository's single
most-recorded failure mode.

So the CI job does not invoke the sweep directly. It invokes
``tools/sibling_sweep_ci.py``, which proves the detection machinery is live on
a synthetic control BEFORE it reports any verdict about the tree, enforces a
non-empty-corpus floor, refuses to collapse FAULT into a pass, and tolerates
exactly the declared open exception while failing on anything else.

WHAT IS DELIBERATELY NOT ASSERTED HERE
--------------------------------------
That CI runs the real-name NEEDLE arm. It cannot without an operator-set
secret, because the names live only in gitignored per-host config and this
repository is PUBLIC. The job reads ``RC_MOON_SYNC_REPOS`` from a secret so
that arming it is a settings change and not a code change, and it states on
every DEGRADED run that the needle arm did not run. An honest partial verdict
is the thing being defended; a silent one is the thing being banned.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# HARD imports, deliberately. `pytest.importorskip` here would turn "the CI
# gate does not exist" into a green run, which is the same vacuity ADR-015
# exists to stop.
from tools import sibling_name_sweep as sweep  # noqa: E402
from tools import sibling_sweep_ci as gate  # noqa: E402

yaml = pytest.importorskip("yaml", reason="pyyaml parses the workflow; CI installs it")

_CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"
_GATE_REL = "tools/sibling_sweep_ci.py"


# ---------------------------------------------------------------------------
# Workflow wiring
# ---------------------------------------------------------------------------
def _workflow():
    """Parse ci.yml. A workflow file that does not parse is a SILENT no-op on
    GitHub, which is the same failure class this module exists to end."""
    assert _CI_YML.is_file(), f"{_CI_YML} is missing"
    doc = yaml.safe_load(_CI_YML.read_text(encoding="utf-8"))
    assert isinstance(doc, dict), "ci.yml did not parse into a mapping"
    return doc


def _gate_steps():
    """Every (job_name, job, step) whose `run` invokes the CI gate.

    ANCHORED, and this is not decoration. Every assertion below iterates this
    list, so an empty list would satisfy all of them by running zero loop
    bodies - the exact "would an EMPTY enumeration PASS your assertion" trap
    ADR-015 names. Measured here: before the job was wired, four of these five
    wiring tests passed green over nothing.
    """
    out = []
    for job_name, job in (_workflow().get("jobs") or {}).items():
        for step in job.get("steps") or []:
            if _GATE_REL in str(step.get("run") or ""):
                out.append((job_name, job, step))
    assert out, (
        f"no job in ci.yml runs {_GATE_REL} - refusing to assert anything "
        "about an empty set of gate steps"
    )
    return out


def test_ci_yml_parses_as_yaml():
    _workflow()


def test_a_ci_job_runs_the_tree_arm_gate():
    hits = _gate_steps()
    assert hits, (
        f"no job in ci.yml runs {_GATE_REL}. The tree arm is unwired, so every "
        "clean verdict this repo produces means 'clean since the last push'."
    )
    assert (REPO_ROOT / _GATE_REL).is_file(), (
        "ci.yml names a gate script that does not exist on disk; the step would "
        "fail with a FileNotFoundError rather than a verdict"
    )


def test_the_gate_step_is_not_advisory():
    """`continue-on-error: true` turns a gate into a notification."""
    for job_name, job, step in _gate_steps():
        assert step.get("continue-on-error") is not True, (
            f"job {job_name} runs the sweep gate with continue-on-error, which "
            "reports a leak as a green tick"
        )
        assert job.get("continue-on-error") is not True, (
            f"job {job_name} is continue-on-error, so its gate cannot fail CI"
        )


def test_the_gate_job_also_runs_on_the_schedule_event():
    """ci.yml carries `paths-ignore: '**/*.md'` on push and pull_request, so a
    docs-only commit runs no CI at all. `schedule` ignores paths-ignore, so the
    nightly cron is what bounds how long an md-only leak can sit unscanned. A
    job gated `if: github.event_name != 'schedule'` would reopen exactly that
    window."""
    for job_name, job, _step in _gate_steps():
        cond = str(job.get("if") or "")
        assert "schedule" not in cond, (
            f"job {job_name} has `if: {cond}`, which mentions the schedule "
            "event. The gate must run on the nightly cron too, because "
            "paths-ignore keeps docs-only pushes out of push CI entirely."
        )


def test_the_gate_job_can_be_armed_without_a_code_change():
    """The real-name arm needs the per-host config, which no CI checkout has.
    The job must read it from a secret so arming it is a settings change."""
    for job_name, job, step in _gate_steps():
        env = {}
        env.update(job.get("env") or {})
        env.update(step.get("env") or {})
        assert "RC_MOON_SYNC_REPOS" in env, (
            f"job {job_name} does not pass RC_MOON_SYNC_REPOS, so the needle "
            "arm can never be armed in CI without editing the workflow"
        )
        assert "secrets." in str(env["RC_MOON_SYNC_REPOS"]), (
            "RC_MOON_SYNC_REPOS must come from a secret. A literal value here "
            "publishes the sibling names this gate exists to protect."
        )


# ---------------------------------------------------------------------------
# The gate proves its own detection machinery
# ---------------------------------------------------------------------------
def test_positive_control_fires_on_the_needle_arm():
    """A synthetic needle planted in a tracked file must be caught AS A NAME
    hit, not merely as a structural one. Without this the job could pass with
    the needle arm dead."""
    res = gate.check_positive_control()
    assert res.ok, res.detail


def test_the_control_path_survives_a_posix_pathsep():
    """The job runs on ubuntu-latest and is authored on Windows. `os.pathsep`
    is ';' here and ':' there, so a drive-letter control path severs at its own
    colon on the runner - CI run 34538335778 is why `split_repo_list` has the
    rejoin logic at all. A control that arms locally and disarms on the runner
    would make the job pass having proved nothing, on the only machine that
    matters."""
    parts = sweep.split_repo_list(gate.control_path(), sep=":")
    assert parts == [gate.control_path()], parts
    cfg = sweep.config_from_parts(parts, {})
    assert cfg.mode == sweep.MODE_ARMED
    assert cfg.names == (gate.CONTROL_NAME,), cfg.names


def test_negative_control_does_not_fire():
    """A gate that halts on everything is as useless as one that halts on
    nothing, and it fails in the direction that gets it disabled."""
    res = gate.check_negative_control()
    assert res.ok, res.detail


def test_cli_controls_exercise_the_real_exit_code_contract():
    """The hook consumes exit codes, not return values. 2 is HALT, 3 is FAULT,
    and the two must never collapse."""
    for res in (gate.check_cli_positive(), gate.check_cli_negative()):
        assert res.ok, res.detail


def test_control_checks_are_all_wired_into_run_controls():
    names = {c.name for c in gate.run_controls()}
    assert names == {
        "positive-inprocess",
        "negative-inprocess",
        "positive-cli",
        "negative-cli",
    }, names


# ---------------------------------------------------------------------------
# The gate cannot pass vacuously
# ---------------------------------------------------------------------------
def _armed_cfg():
    return sweep.config_from_parts([gate.control_path()], {})


def _stats(files=9999, scanned=99_999_999):
    st = sweep.ScanStats()
    st.files = files
    st.scanned_bytes = scanned
    st.diff_nonempty = True
    return st


def test_a_full_corpus_with_no_findings_passes():
    ok, lines = gate.evaluate(_armed_cfg(), _stats(), [])
    assert ok, "\n".join(lines)


@pytest.mark.parametrize(
    "files,scanned",
    [
        (0, 99_999_999),
        (12, 99_999_999),
        (9999, 0),
        (9999, 17),
    ],
)
def test_an_empty_or_thin_corpus_fails_loudly(files, scanned):
    """An empty enumeration and a clean tree are the same verdict to every
    consumer (ADR-015). The floors exist so a sparse or broken checkout cannot
    be read as a clean repository."""
    ok, lines = gate.evaluate(_armed_cfg(), _stats(files, scanned), [])
    assert not ok
    assert any("VACUOUS" in ln for ln in lines), lines


def test_fault_is_not_reported_as_a_pass():
    cfg = sweep.SweepConfig(mode=sweep.MODE_FAULT, detail="config present but unreadable")
    ok, lines = gate.evaluate(cfg, _stats(), [])
    assert not ok
    assert any("FAULT" in ln for ln in lines), lines


def test_degraded_passes_but_says_so_in_capitals():
    """DEGRADED is the CI default until the secret is set. It must pass - a job
    red on day one gets disabled - while stating on every run that the needle
    arm did not run."""
    cfg = sweep.SweepConfig(mode=sweep.MODE_DEGRADED, detail="per-host config absent")
    ok, lines = gate.evaluate(cfg, _stats(), [])
    assert ok
    blob = "\n".join(lines)
    assert "DEGRADED" in blob
    assert "NEEDLE ARM DID NOT RUN" in blob, blob


# ---------------------------------------------------------------------------
# The declared exception is tolerated; nothing else is
# ---------------------------------------------------------------------------
_KNOWN_PATH = "tests/test_loop_concurrency.py"
_LITERAL = "Zzz-Literal-That-Must-Never-Be-Printed"


def _finding(path):
    return sweep.Finding(
        slot=0,
        shape=sweep.SHAPE_BARE + "/SPACED",
        view=sweep.VIEW_SPACE,
        source="TREE",
        path=path,
        line=42,
        status="T",
        severity=sweep.SEV_NAME,
        literal=_LITERAL,
        offset=7,
    )


@pytest.fixture()
def declared(monkeypatch):
    """A SYNTHETIC declared exception, injected into the sweep's own registry.

    DELIBERATELY not coupled to whichever path the registry happens to hold
    today. What this module is guarding is the MECHANISM - that a declared
    entry is tolerated, reported with its reason, and never widened into an
    amnesty - and that mechanism has to keep being tested when the registry is
    emptied or re-pointed by a different slice. A guard pinned to one path
    would either red on that slice or, worse, quietly stop exercising the
    never-suppressed property when the last entry is retired.
    """
    monkeypatch.setattr(
        sweep, "KNOWN_EXCEPTIONS",
        {_KNOWN_PATH: "synthetic declared entry for the CI gate contract"},
    )
    return _KNOWN_PATH


def test_every_real_registry_entry_carries_a_reason():
    """Shape assertion over whatever the registry holds, including nothing. A
    declared exception with an empty reason is a silent allowlist wearing a
    declaration's costume."""
    for rel, reason in sweep.KNOWN_EXCEPTIONS.items():
        assert isinstance(rel, str) and rel.strip(), rel
        assert isinstance(reason, str) and len(reason.strip()) > 40, (rel, reason)


def test_a_known_exception_alone_passes_and_is_reported(declared):
    ok, lines = gate.evaluate(_armed_cfg(), _stats(), [_finding(declared)])
    assert ok, "\n".join(lines)
    blob = "\n".join(lines)
    assert declared in blob, "the declared exception must be REPORTED, not suppressed"
    assert "KNOWN" in blob
    assert "synthetic declared entry" in blob, "the reason must travel with the exception"


def test_an_undeclared_finding_fails():
    ok, lines = gate.evaluate(_armed_cfg(), _stats(), [_finding("docs/some_new_doc.md")])
    assert not ok
    blob = "\n".join(lines)
    assert "docs/some_new_doc.md" in blob


def test_a_new_finding_alongside_the_known_one_still_fails(declared):
    """The exception must not become a blanket amnesty once it is present."""
    findings = [_finding(declared), _finding("core/whatever.py")]
    ok, _lines = gate.evaluate(_armed_cfg(), _stats(), findings)
    assert not ok


def test_an_empty_registry_tolerates_nothing(monkeypatch):
    """With no declared exception, every finding is undeclared. This is the
    state the registry reaches once its last open hit is remediated, and the
    gate must get STRICTER there, never looser."""
    monkeypatch.setattr(sweep, "KNOWN_EXCEPTIONS", {})
    ok, _lines = gate.evaluate(_armed_cfg(), _stats(), [_finding(_KNOWN_PATH)])
    assert not ok


def test_the_printed_index_column_matches_the_explain_flag(declared):
    """The table tells the operator to run `--tree --explain <idx>`, and that
    flag indexes the sweep's OWN list. A table rendered over the undeclared
    subset would print index numbers that resolve to a different finding."""
    findings = [_finding(declared), _finding("core/whatever.py")]
    _ok, lines = gate.evaluate(_armed_cfg(), _stats(), findings)
    table = [ln for ln in lines if ln.strip().startswith(("0 ", "1 "))]
    assert len(table) == len(findings), lines
    assert declared in table[0] and "[KNOWN]" in table[0]
    assert "core/whatever.py" in table[1]


# ---------------------------------------------------------------------------
# The repo is PUBLIC: CI logs must never carry a matched literal
# ---------------------------------------------------------------------------
def test_no_matched_literal_reaches_the_ci_log(declared):
    """Hook and job stderr land in public CI logs and in pasted transcripts. A
    report that spells the name it caught does not stop the leak, it relocates
    it into a place with a wider audience and no gate at all."""
    findings = [_finding(declared), _finding("core/whatever.py")]
    _ok, lines = gate.evaluate(_armed_cfg(), _stats(), findings)
    blob = "\n".join(lines)
    assert _LITERAL not in blob
    for control in gate.run_controls():
        assert _LITERAL not in control.detail


def test_the_gate_module_carries_no_drive_rooted_path():
    """A literal drive-rooted path in the gate's own source is a live hit for
    the sweep's STRUCTURAL arm, which would make the job halt on itself. The
    control path is assembled at run time for exactly this reason."""
    text = (REPO_ROOT / _GATE_REL).read_text(encoding="utf-8")
    hits = sweep.structural_findings(text, path=_GATE_REL, source="TREE", status="T")
    assert not hits, [(h.path, h.line, h.shape) for h in hits]


# ---------------------------------------------------------------------------
# MUTATION PROBES on main() itself.
#
# Every assertion above is about a helper. These two ask the only question that
# matters about the JOB: can the process exit 0 while proving nothing.
# ---------------------------------------------------------------------------
def test_main_refuses_to_report_a_tree_verdict_when_the_needle_arm_is_dead(monkeypatch, capsys):
    """Simulate the machinery failing. The gate must exit non-zero AND must not
    print a tree verdict, because a clean report from unproven machinery is
    precisely the green tick this whole job exists to prevent."""
    monkeypatch.setattr(
        gate, "check_positive_control",
        lambda: gate.CheckResult("positive-inprocess", False, "simulated dead needle arm"),
    )

    def _boom():
        raise AssertionError("scan_tree must not be reached once a control has failed")

    monkeypatch.setattr(gate, "scan_tree", _boom)
    rc = gate.main([])
    out = capsys.readouterr().out
    assert rc == gate.EXIT_FAIL
    assert "coverage:" not in out, out


def test_main_fails_on_a_vacuous_corpus_end_to_end(monkeypatch, capsys):
    """A checkout that yields almost nothing must not read as a clean repo."""
    cfg = sweep.SweepConfig(mode=sweep.MODE_DEGRADED, detail="per-host config absent")
    monkeypatch.setattr(gate, "scan_tree", lambda: (cfg, _stats(files=3, scanned=99), []))
    rc = gate.main([])
    out = capsys.readouterr().out
    assert rc == gate.EXIT_FAIL
    assert "VACUOUS" in out, out


def test_main_fails_on_an_undeclared_finding_end_to_end(monkeypatch, capsys):
    cfg = sweep.SweepConfig(mode=sweep.MODE_DEGRADED, detail="per-host config absent")
    monkeypatch.setattr(
        gate, "scan_tree", lambda: (cfg, _stats(), [_finding("web/js/panels/new.js")])
    )
    rc = gate.main([])
    out = capsys.readouterr().out
    assert rc == gate.EXIT_FAIL
    assert "web/js/panels/new.js" in out
    assert _LITERAL not in out


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------
def test_the_gate_runs_green_on_this_tree():
    """The whole point of the exercise: the job must be green on day one, or it
    gets disabled, and a disabled guard is worse than no guard. Measured at
    8c576c180 - the tree is clean under both the DEGRADED and the ARMED
    configurations on this host."""
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / _GATE_REL)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=1800,
    )
    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-4000:]
    assert "coverage:" in proc.stdout
