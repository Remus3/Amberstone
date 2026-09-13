"""Planted-specimen self-test for `tools/live_write_tracer.py` (RM-408).

WHY THIS FILE EXISTS
--------------------
The tracer's output is UNFALSIFIABLE without a control. A run whose four
patched routes (`builtins.open`, `io.open`, `os.replace`, `os.rename`) never
intercepted anything emits a report that is byte-identical to the report of a
genuinely clean tree: totals 0 files / 0 units / 0 tests. LEDGER 1392's headline
AFTER figure rests on that instrument, so "the zeros are real" needs evidence
that the routes FIRED, not the absence of evidence that they did not.

This module supplies that evidence. It plants a specimen through each patched
route into a PRIVATE root that is watched only for the duration of one check,
plants NEGATIVE specimens the tracer must stay silent about, scrubs every
specimen before the report is built, and asserts the instrument can be re-armed
and re-fired inside one process.

TWO LIMITS THIS CONTROL DOES NOT AND CANNOT CLAIM AWAY
------------------------------------------------------
1. SUBPROCESSES ARE INVISIBLE. The tracer wraps four names in ONE interpreter
   (`tools/live_write_tracer.py:60-66`). A test that shells out - subprocess,
   os.system, a spawned supervisor, an AHK or PowerShell call - can write
   anywhere in the live tree and neither the tracer nor this control will see
   it. Green here means "the in-process routes fire", never "nothing wrote".
2. A CONTROL PROVES THE ROUTES FIRE, NEVER THAT THE WATCH SET IS COMPLETE.
   Every positive arm below plants into a path this control itself chose to be
   inside `_WATCH_SUBTREES` (`tools/live_write_tracer.py:105`). Nothing here
   tests whether that watch set names every subtree holding operator state, and
   a path the watch set omits is invisible to the instrument AND to this test.

WHERE THE SPECIMENS GO, AND WHY IT IS SAFE
------------------------------------------
Into `_scratch/live_write_tracer_selftest/<unique>/` at the repo root of
whichever checkout runs the test. `_scratch/` is gitignored and is NOT one of
the tracer's watched subtrees (`ops/runtime`, `logs`, `data`,
`moon_sync_inbox`), so a specimen can never collide with operator state even
when this test runs from the live checkout. The tracer root is then pointed at
a private subdirectory of that scratch dir via `RC_TRACER_ROOT`, so the watch
set for the duration of a check covers nothing but specimens. Every check
removes its own tree in a `finally`.

WHY NOT A pytest tmp_path
-------------------------
`key_for` excludes the system temp dir and any path carrying the `pytest-of-`
segment (`tools/live_write_tracer.py:170-175`), on purpose. A specimen planted
in `tmp_path` would be discarded by the instrument for reasons that have
nothing to do with whether the routes fire, and the control would read as a
false negative - the exact failure a sibling repo's first run hit on Windows
8.3 short paths.
"""
from __future__ import annotations

import builtins
import io
import json
import os
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

from tools import live_write_tracer

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRATCH_BASE = _REPO_ROOT / "_scratch" / "live_write_tracer_selftest"

# Distinct nodeids per route, so the report's `written_by` / `replaced_by` maps
# prove WHICH arm credited a path rather than only that something did.
_NODEID_APPEND = "selftest::open_append_route"
_NODEID_ATOMIC = "selftest::os_replace_route"
_NODEID_PATHLIB = "selftest::pathlib_io_open_route"
_NODEID_NEGATIVE = "selftest::negative_control"

# ASCII, and deliberately NEWLINE-FREE. A text handle is measured in CHARACTERS
# (`tools/live_write_tracer.py:40-49`) while the rename path is measured in
# on-disk BYTES, and on Windows a text handle turns each "\n" into CRLF. With no
# newline in the payload the two units coincide, so every assertion below can be
# an exact equality instead of a lower bound.
_APPEND_PAYLOAD = "rc-tracer-selftest-open-append"
_ATOMIC_PAYLOAD = '{"rc_tracer_selftest": "os-replace-route"}'
_PATHLIB_PAYLOAD = '{"rc_tracer_selftest": "pathlib-write-text"}'
_NEGATIVE_PAYLOAD = "rc-tracer-selftest-must-never-be-reported"

_APPEND_KEY = "data/selftest_append.log"
_ATOMIC_DST_KEY = "data/selftest_atomic.json"
_ATOMIC_TMP_KEY = "data/selftest_atomic.json.tmp"
_PATHLIB_KEY = "data/selftest_pathlib.json"
_NEGATIVE_UNWATCHED_KEY = "notes/selftest_negative_unwatched.txt"


class _StubConfig:
    """Stand-in for a pytest Config - the tracer reads exactly one option.

    `pytest_configure` consults `numprocesses` through `_is_xdist_controller`
    (`tools/live_write_tracer.py:395-403`) and touches nothing else on config;
    `pytest_unconfigure` ignores it entirely.
    """

    @staticmethod
    def getoption(name, default=None):
        return default


@contextmanager
def _private_base(tag):
    """A private scratch base, removed however the body exits."""
    base = _SCRATCH_BASE / f"{os.getpid()}-{tag}-{uuid.uuid4().hex[:8]}"
    base.mkdir(parents=True, exist_ok=False)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)
        # Leave no trace of the control itself when nothing else is running.
        # Both rmdir calls remove an EMPTY directory only, so a concurrent
        # check's base - or anything else a tree keeps under `_scratch/` -
        # makes the call fail harmlessly rather than deleting another's state.
        for leftover in (_SCRATCH_BASE, _SCRATCH_BASE.parent):
            try:
                leftover.rmdir()
            except OSError:
                break


def _plant_and_report(base, monkeypatch):
    """Arm the tracer on a private root, plant every specimen, scrub, report.

    Returns a dict carrying the parsed report plus the EVIDENCE that each
    specimen really reached the disk. The evidence half is what makes the
    control non-vacuous: a plant step that silently no-ops would otherwise
    produce empty maps that look exactly like a correctly-silent instrument.
    """
    root = base / "root"
    outside = base / "outside"
    report_path = base / "live_write_trace.json"
    (root / "data").mkdir(parents=True)
    (root / "notes").mkdir(parents=True)
    outside.mkdir(parents=True)

    append_path = root / _APPEND_KEY
    atomic_dst = root / _ATOMIC_DST_KEY
    atomic_tmp = root / _ATOMIC_TMP_KEY
    pathlib_path = root / _PATHLIB_KEY
    negative_unwatched = root / _NEGATIVE_UNWATCHED_KEY
    negative_outside = outside / "selftest_negative_outside.txt"

    monkeypatch.setenv("RC_TRACER_ROOT", str(root))
    monkeypatch.setenv("RC_TRACER_REPORT", str(report_path))
    # Without this the report path is suffixed per worker
    # (`tools/live_write_tracer.py:471-475`) and this control would read a file
    # that was never written, which presents as a clean zero.
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)

    config = _StubConfig()
    # The real plugin may be loaded over this very run (`-p tools.live_write_tracer`).
    # Arming a second tracer clobbers its module state, and the plugin's own
    # `pytest_unconfigure` would then leave `_state` at None for the rest of the
    # outer run - a silently disarmed instrument. Hand it back on the way out.
    outer_state = live_write_tracer._state
    evidence = {}
    live_write_tracer.pytest_configure(config)
    try:
        tracer = live_write_tracer._state
        evidence["tracer_armed"] = tracer is not None and tracer is not outer_state
        evidence["patched_builtins_open"] = builtins.open is not tracer.orig_open
        evidence["patched_io_open"] = io.open is not tracer.orig_io_open
        evidence["patched_os_replace"] = os.replace is not tracer.orig_replace

        # NEGATIVE arms first, so a classifier that promotes everything is
        # caught even if a later positive arm raises.
        tracer.nodeid = _NODEID_NEGATIVE
        negative_unwatched.write_text(_NEGATIVE_PAYLOAD, encoding="ascii")
        with open(negative_outside, "w", encoding="ascii") as handle:
            handle.write(_NEGATIVE_PAYLOAD)

        # POSITIVE arm 1 - the builtins.open append route.
        tracer.nodeid = _NODEID_APPEND
        with open(append_path, "a", encoding="ascii") as handle:
            handle.write(_APPEND_PAYLOAD)

        # POSITIVE arm 2 - the repo-standard atomic write, whose destination is
        # only ever touched by the rename.
        tracer.nodeid = _NODEID_ATOMIC
        with open(atomic_tmp, "w", encoding="ascii") as handle:
            handle.write(_ATOMIC_PAYLOAD)
        evidence["atomic_tmp_on_disk"] = os.path.getsize(atomic_tmp)
        os.replace(atomic_tmp, atomic_dst)

        # POSITIVE arm 3 - pathlib, which reaches io.open rather than
        # builtins.open (`tools/live_write_tracer.py:489-495`).
        tracer.nodeid = _NODEID_PATHLIB
        pathlib_path.write_text(_PATHLIB_PAYLOAD, encoding="ascii")

        evidence["append_on_disk"] = os.path.getsize(append_path)
        evidence["atomic_dst_on_disk"] = os.path.getsize(atomic_dst)
        evidence["pathlib_on_disk"] = os.path.getsize(pathlib_path)
        evidence["negative_unwatched_on_disk"] = os.path.getsize(negative_unwatched)
        evidence["negative_outside_on_disk"] = os.path.getsize(negative_outside)
        evidence["watched_root_files"] = sum(
            1 for _ in (root / "data").iterdir()
        )
        evidence["atomic_tmp_consumed"] = not atomic_tmp.exists()

        # SCRUB before the report is built. The report is assembled from
        # in-memory state (`tools/live_write_tracer.py:342-368`), so removing
        # the specimens first costs nothing - and skipping it would leave a
        # manufactured finding in every tree this control ever runs in.
        shutil.rmtree(root)
        shutil.rmtree(outside)
        evidence["scrubbed"] = not root.exists() and not outside.exists()

        live_write_tracer.pytest_sessionfinish(session=None, exitstatus=0)
    finally:
        live_write_tracer.pytest_unconfigure(config)
        live_write_tracer._state = outer_state

    evidence["report_written"] = report_path.is_file()
    report = json.loads(report_path.read_text(encoding="ascii"))
    return {"report": report, "evidence": evidence}


@pytest.fixture(scope="module")
def control(request):
    """One armed-and-fired control, shared by the arms that only read it."""
    monkeypatch = pytest.MonkeyPatch()
    request.addfinalizer(monkeypatch.undo)
    with _private_base("main") as base:
        return _plant_and_report(base, monkeypatch)


def _assert_non_vacuous(result):
    """Every claim below is worthless unless the specimens actually existed."""
    evidence = result["evidence"]
    assert evidence["tracer_armed"] is True
    assert evidence["patched_builtins_open"] is True
    assert evidence["patched_io_open"] is True
    assert evidence["patched_os_replace"] is True
    assert evidence["append_on_disk"] == len(_APPEND_PAYLOAD)
    assert evidence["atomic_tmp_on_disk"] == len(_ATOMIC_PAYLOAD)
    assert evidence["atomic_dst_on_disk"] == len(_ATOMIC_PAYLOAD)
    assert evidence["pathlib_on_disk"] == len(_PATHLIB_PAYLOAD)
    assert evidence["negative_unwatched_on_disk"] == len(_NEGATIVE_PAYLOAD)
    assert evidence["negative_outside_on_disk"] == len(_NEGATIVE_PAYLOAD)
    assert evidence["atomic_tmp_consumed"] is True
    assert evidence["watched_root_files"] >= 3
    assert evidence["scrubbed"] is True
    assert evidence["report_written"] is True
    # A watched root that was never populated cannot prove anything about the
    # routes, so the report itself must be non-empty too.
    assert result["report"]["totals"]["units"] > 0
    assert result["report"]["totals"]["files"] >= 3


def test_control_is_not_vacuous(control):
    """The control must fail if it planted nothing, not report a clean pass."""
    _assert_non_vacuous(control)


def test_open_append_route_fires(control):
    report = control["report"]
    assert report["wrote_units"].get(_APPEND_KEY) == len(_APPEND_PAYLOAD)
    assert report["written_by"].get(_APPEND_KEY) == [_NODEID_APPEND]
    # Data reached the path, so it must NOT be filed as an empty open
    # (`tools/live_write_tracer.py:344-351`).
    assert _APPEND_KEY not in report["opened_for_write_only"]


def test_os_replace_route_fires_and_tmp_is_reported_separately(control):
    report = control["report"]
    # The destination is credited by the rename, and its `written_by` list stays
    # empty - the signature of a correct atomic write, not a gap in the trace.
    assert report["wrote_units"].get(_ATOMIC_DST_KEY) == len(_ATOMIC_PAYLOAD)
    assert report["replaced_by"].get(_ATOMIC_DST_KEY) == [_NODEID_ATOMIC]
    assert _ATOMIC_DST_KEY not in report["written_by"]
    # The tmp half is reported, in its own bucket, and never summed into totals.
    assert report["atomic_tmp_units"].get(_ATOMIC_TMP_KEY) == len(_ATOMIC_PAYLOAD)
    assert _ATOMIC_TMP_KEY not in report["wrote_units"]
    assert report["totals"]["units"] == sum(report["wrote_units"].values())


def test_pathlib_route_is_covered_by_the_io_open_patch(control):
    """pathlib reaches io.open, a separate binding from builtins.open.

    Deleting `io.open = traced_open` at `tools/live_write_tracer.py:495` reds
    exactly this arm - that mutation is what promotes the patch's presence from
    an assumption to a measurement.
    """
    report = control["report"]
    assert report["wrote_units"].get(_PATHLIB_KEY) == len(_PATHLIB_PAYLOAD)
    assert report["written_by"].get(_PATHLIB_KEY) == [_NODEID_PATHLIB]


def test_negative_specimens_are_never_reported(control):
    """Without this arm a classifier mutated to promote everything passes."""
    report = control["report"]
    for name in ("wrote_units", "atomic_tmp_units", "written_by",
                 "replaced_by", "opened_for_write_only"):
        assert _NEGATIVE_UNWATCHED_KEY not in report[name]
        for key in report[name]:
            assert "negative" not in key.lower(), f"{name} promoted {key}"
    # The out-of-root specimen has no repo-relative key at all, so the only
    # honest check is that its nodeid reached no map anywhere in the report.
    assert _NODEID_NEGATIVE not in json.dumps(report)


def test_control_regenerates_within_one_process(request):
    """The instrument must be re-armable - one-shot state would hide a stale run.

    Both cycles run in THIS process, after the module fixture already armed and
    disarmed the tracer once, so a passing pair also proves
    `pytest_unconfigure` restores cleanly enough to arm again.
    """
    monkeypatch = pytest.MonkeyPatch()
    request.addfinalizer(monkeypatch.undo)
    results = []
    for tag in ("regen-a", "regen-b"):
        with _private_base(tag) as base:
            results.append(_plant_and_report(base, monkeypatch))
    for result in results:
        # Held to the same anti-vacuous bar as the first firing - a re-arm that
        # plants nothing is exactly the silent pass this control exists to stop.
        _assert_non_vacuous(result)
        report = result["report"]
        assert report["wrote_units"].get(_APPEND_KEY) == len(_APPEND_PAYLOAD)
        assert report["wrote_units"].get(_ATOMIC_DST_KEY) == len(_ATOMIC_PAYLOAD)
        assert report["wrote_units"].get(_PATHLIB_KEY) == len(_PATHLIB_PAYLOAD)
        assert _NODEID_NEGATIVE not in json.dumps(report)
