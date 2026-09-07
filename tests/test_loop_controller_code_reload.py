"""
tests/test_loop_controller_code_reload.py

MEASURED 2026-07-27: three consecutive loop cycles shipped a fix to the director
prompt assembler and NONE of them took effect.

  controller pid 18300 started 00:37:50 (ops/loop/control/RUNNING.lock ts
  1785130670.62). The fixes landed at 05:03:56 (1f880bb1), 05:24:57 (7e0e8b80)
  and 05:34:14 (d3eb3b3a). A long-lived python process imports its source ONCE,
  so the running image predated every one of them, and the live director stdin
  written at 05:45 (ops/loop/control/_gemini_in.txt) still carried the PRE-fix
  ledger section - the raw cap_bytes fallback and the old header wording - while
  the same call measured in-process off disk carried the fixed shape.

The consequence is the loop's dominant failure: the director re-emitted an
already-shipped unit (f1-phase6 item 2, closed at f173ce39 / LEDGER 1074) for
the second time, because the de-dup evidence the fix restores was assembled by
code that no longer existed on disk. Every cycle spent fixing the prompt was
spent on a process that would ignore the fix.

This is the repo's recurring "present but does nothing" class, one layer above
where R201 looked: not a guard that reads the wrong side, but a FIX THAT IS NOT
RUNNING. Locked here:

  - the controller notices when its own imported source changes on disk,
  - it re-execs at a CYCLE TOP (never mid-handshake) so the new image runs,
  - the cycle counter survives the re-exec, so max_cycles still bounds the run,
  - gemini spend survives it too, so an automatic restart cannot silently reset
    the ceiling accounting,
  - and an exec failure degrades to "keep running on stale code", never to a
    dead loop.

director_prompt.md is deliberately NOT part of the digest: build_director_body
re-reads that template from disk on every single cycle, so a template edit is
already live and re-execing for it would be a restart that buys nothing.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent


@pytest.fixture()
def lc():
    return importlib.import_module("ops.loop.loop_controller")


@pytest.fixture(autouse=True)
def _quiet_log(monkeypatch):
    """log() appends to the PRODUCTION control/controller.log.

    Every restart path logs (silence is the failure mode this module guards), so
    an unpatched test mutates a live artifact and trips the conftest hermeticity
    check. The lines are still exercised - they just land in a list.
    """
    mod = importlib.import_module("ops.loop.loop_controller")
    lines = []
    monkeypatch.setattr(mod, "log", lines.append)
    return lines


def _fake_src(tmp_path: Path, lc, body: str = "x = 1\n") -> Path:
    d = tmp_path / "src"
    d.mkdir()
    for name in lc.CODE_FILES:
        (d / name).write_text(body, encoding="utf-8")
    return d


# ---- the digest ------------------------------------------------------------

def test_the_digest_covers_every_imported_controller_source_file(lc):
    """The set is the process IMAGE, not one file.

    executor.py / adjudicator.py / slots.py / winmutex.py are imported into the
    controller image exactly as loop_controller.py is, so a fix to any of them
    is just as inert. Digesting only the main module would leave four files in
    the same hole this test exists to close.
    """
    assert "loop_controller.py" in lc.CODE_FILES
    for name in ("executor.py", "adjudicator.py", "slots.py", "winmutex.py"):
        assert name in lc.CODE_FILES, f"{name} is imported into the image too"
    here = Path(lc.__file__).resolve().parent
    for name in lc.CODE_FILES:
        assert (here / name).is_file(), f"{name} must exist next to the controller"


def test_the_digest_is_stable_and_moves_only_on_a_content_change(lc, tmp_path):
    d = _fake_src(tmp_path, lc)
    first = lc.controller_code_digest(d)
    assert first == lc.controller_code_digest(d), "a digest that drifts at rest is useless"
    (d / "executor.py").write_text("x = 2\n", encoding="utf-8")
    assert lc.controller_code_digest(d) != first


def test_the_digest_ignores_the_director_prompt_template(lc, tmp_path):
    """The template is re-read per cycle, so it is already live.

    build_director_body reads director_prompt.md off disk on every call. Putting
    it in the digest would re-exec the controller for an edit that had already
    taken effect - a restart that buys nothing and loses the cycle counter.
    """
    d = _fake_src(tmp_path, lc)
    before = lc.controller_code_digest(d)
    (d / "director_prompt.md").write_text("# edited template\n", encoding="utf-8")
    assert lc.controller_code_digest(d) == before
    assert "director_prompt.md" not in lc.CODE_FILES


# ---- the staleness verdict -------------------------------------------------

def test_no_reason_when_the_running_image_matches_disk(lc, tmp_path):
    d = _fake_src(tmp_path, lc)
    base = lc.code_file_digests(d)
    assert lc.stale_code_reason(baseline=base, src_dir=d) is None


def test_the_reason_names_the_file_that_changed(lc, tmp_path):
    d = _fake_src(tmp_path, lc)
    base = lc.code_file_digests(d)
    (d / "adjudicator.py").write_text("x = 99\n", encoding="utf-8")
    reason = lc.stale_code_reason(baseline=base, src_dir=d)
    assert reason, "a changed source file must be reported"
    assert "adjudicator.py" in reason, "the operator needs to know WHICH file"
    assert "loop_controller.py" not in reason, "unchanged files must not be blamed"


def test_a_deleted_source_file_is_also_a_change(lc, tmp_path):
    """A vanished module is a changed image, not a clean one.

    The absent-file case must not read as "nothing to compare" - that is the
    always-passing shape this module exists to remove.
    """
    d = _fake_src(tmp_path, lc)
    base = lc.code_file_digests(d)
    (d / "slots.py").unlink()
    reason = lc.stale_code_reason(baseline=base, src_dir=d)
    assert reason and "slots.py" in reason


def test_the_import_time_baseline_is_recorded(lc):
    """Without a baseline captured at import there is nothing to compare to."""
    assert isinstance(lc.CODE_DIGESTS_AT_IMPORT, dict)
    assert set(lc.CODE_DIGESTS_AT_IMPORT) == set(lc.CODE_FILES)
    # The live process IS current with disk right now (this test process just
    # imported it), so the production-default call must be quiet.
    assert lc.stale_code_reason() is None


# ---- the restart ------------------------------------------------------------

def test_the_restart_re_execs_the_same_interpreter_and_argv(lc, tmp_path):
    seen = {}

    def fake_execv(exe, argv):
        seen["exe"], seen["argv"] = exe, list(argv)
        raise AssertionError("execv replaces the process; tests must not return")

    with pytest.raises(AssertionError):
        lc.restart_for_new_code(4, "loop_controller.py changed",
                                execv=fake_execv, ctl=tmp_path,
                                argv=["ops/loop/loop_controller.py", "--config", "x.json"])
    assert seen["argv"][1:] == ["ops/loop/loop_controller.py", "--config", "x.json"], (
        "the config argument decides which loop this is - dropping it relaunches a "
        "different run")
    assert seen["argv"][0] == seen["exe"]


def test_the_restart_records_the_cycle_so_max_cycles_still_bounds_the_run(lc, tmp_path):
    lc.restart_for_new_code(7, "executor.py changed",
                            execv=lambda *a: None, ctl=tmp_path)
    assert lc.resume_cycle(ctl=tmp_path) == 7, (
        "resuming at 1 would let a code edit reset the cycle budget and run forever")


def test_an_exec_failure_keeps_the_loop_alive_on_stale_code(lc, tmp_path):
    """Degrade to the OLD behaviour, never to a dead loop.

    A stale image emits duplicate directives; a controller that died trying to
    reload emits nothing at all and the operator is asleep.
    """
    def boom(*_a):
        raise OSError("exec failed")

    assert lc.restart_for_new_code(2, "winmutex.py changed",
                                   execv=boom, ctl=tmp_path) is False


def test_resume_cycle_is_consume_once(lc, tmp_path):
    lc.restart_for_new_code(5, "r", execv=lambda *a: None, ctl=tmp_path)
    assert lc.resume_cycle(ctl=tmp_path) == 5
    assert lc.resume_cycle(ctl=tmp_path) == 1, (
        "a leftover offset would make a LATER manual restart skip cycles")


def test_a_junk_offset_falls_back_to_one(lc, tmp_path):
    (tmp_path / "resume_cycle.txt").write_text("not a number", encoding="utf-8")
    assert lc.resume_cycle(ctl=tmp_path) == 1


# ---- the ceiling must survive the automatic restart ------------------------

def test_the_resumed_run_seeds_spend_from_budget_json(lc, tmp_path):
    """An automatic restart must not silently reset the gemini ceiling.

    _ADJ_STATE lives in memory, so every restart path already forgets spend -
    tolerable when a human types the relaunch, NOT tolerable once the controller
    can relaunch itself on any code edit: ceiling_usd would never be reached.
    """
    (tmp_path / "budget.json").write_text(json.dumps(
        {"adjudicator": "gemini", "adjudicator_usd": 3.75, "gemini_usd": 3.75}),
        encoding="utf-8")
    state = {"active": "", "failed_over": False, "usd": {}}
    lc.seed_spend_from_budget(ctl=tmp_path, state=state)
    assert state["usd"].get("gemini") == pytest.approx(3.75)


def test_seeding_tolerates_a_missing_or_broken_budget_file(lc, tmp_path):
    state = {"usd": {}}
    lc.seed_spend_from_budget(ctl=tmp_path, state=state)
    assert state["usd"] == {}
    (tmp_path / "budget.json").write_text("{not json", encoding="utf-8")
    lc.seed_spend_from_budget(ctl=tmp_path, state=state)
    assert state["usd"] == {}


def test_seeding_never_lowers_spend_already_accounted(lc, tmp_path):
    """Restored accounting is a FLOOR. Overwriting a higher in-memory figure
    with a stale file would hand back money the run already spent."""
    (tmp_path / "budget.json").write_text(json.dumps(
        {"adjudicator": "gemini", "adjudicator_usd": 1.0}), encoding="utf-8")
    state = {"usd": {"gemini": 9.0}}
    lc.seed_spend_from_budget(ctl=tmp_path, state=state)
    assert state["usd"]["gemini"] == pytest.approx(9.0)


# ---- the wiring ------------------------------------------------------------

def test_main_checks_for_stale_code_at_the_cycle_top(lc):
    """The helpers are worthless unwired; this pins the call site.

    Placement matters: the check must sit at the top of the cycle loop, beside
    the STOP poll, so a re-exec can never land between a typed directive and the
    claude.done it is waiting for.
    """
    src = Path(lc.__file__).resolve().read_text(encoding="utf-8")
    body = src.split("\ndef main():", 1)[1]
    loop_at = body.index('for cycle in range(')
    guard_at = body.index("cycle_top_code_guard")
    stop_at = body.index('"STOP").exists()', loop_at)
    assert guard_at > loop_at, "the guard must be INSIDE the cycle loop"
    assert guard_at - stop_at < 800, "the guard belongs beside the cycle-top STOP poll"
    assert "resume_cycle(" in body, "main must resume at the recorded cycle"
    assert "seed_spend_from_budget(" in body, "main must restore spend accounting"


def test_the_guard_restarts_only_when_the_source_moved(lc, monkeypatch):
    calls = []
    monkeypatch.setattr(lc, "restart_for_new_code",
                        lambda cycle, reason, **kw: calls.append((cycle, reason)))
    monkeypatch.setattr(lc, "stale_code_reason", lambda: None)
    lc.cycle_top_code_guard(3)
    assert calls == [], "a current image must never be restarted"
    monkeypatch.setattr(lc, "stale_code_reason", lambda: "executor.py changed")
    lc.cycle_top_code_guard(4)
    assert calls == [(4, "executor.py changed")]
