"""RM-1028 (RM-909 follow-up (c), part 3; filed as RM-1024) - the
"executor threads in 4 TFT / draft files" are the dashboard's ONE shared,
bounded relay pool, not a per-test leak.

MEASURED 2026-10-27 (s144 queue cycle 18). Every TFT / draft test file
(91 under tests/ plus 11 in its subdirectories) was run alone in a fresh
pytest process, and the threads alive at session end that were not alive
at session start were counted. Six files left a thread, one each, and in
every case it was a `rc-state-relay_N` worker:
tests/test_tft_board_panel_s134.py, tests/test_tft_context.py,
tests/test_tft_payload_shape_rm292d.py,
tests/test_tft_payload_unknown_vitals_s136.py,
tests/test_tft_standalone_client_s134.py and
tests/phase8_smoke/test_sr_draft_profile_stub.py. No other executor or
thread survived any of the 102 files.

That worker belongs to `dashboard/_state_builder.py` `_RELAY_POOL`, a
module-level ThreadPoolExecutor (max_workers=4) that `build_state()` uses to
overlap the liveclient relay round-trip (RC2 6.5). It is a process-lifetime
singleton by design: its workers idle on the pool's queue, the pool never
exceeds its cap however many builds run, and concurrent.futures joins its
workers at interpreter exit. `tests/test_port_cpu_footprint_rc2.py`
`RelayPoolBoundedTests` pins the pool's CONFIG (type, cap, name prefix).
These tests pin the RUNTIME claim the s141 census could not tell apart from a
leak: many concurrent builds leave only relay workers, never more than the
cap, the same workers are reused by the next burst, and every one is
registered for the exit join. The census runs in a fresh interpreter so no
earlier test's threads or pool state can move the count. The child inherits
this process's environment, so the suite's tmp redirects apply to it; its cwd
is a tmp dir, but build_state still reads repo files through APP_DIR, and
nothing it reaches writes outside a live game today.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0

# One burst = this many build_state() calls at once. Each liveclient relay
# sleeps, so the burst holds several pool tasks in flight together and drives
# the pool to its cap; a pool that grew per build would pass the cap here.
_BURST = 12

# The cap RelayPoolBoundedTests allows; the counts are checked against this
# literal, not the pool's own attribute, so a raised cap reddens them too.
_CAP = 4

_CHILD = r"""
import json, threading, time
import concurrent.futures.thread as cft
from unittest import mock
from dashboard import _state_builder as sb

def _read_json(p):
    return {"mode": "client"} if "health" in str(p) else {"action": ""}

def _lc():
    time.sleep(0.3)
    return {}

for name, kw in (("read_json", {"side_effect": _read_json}),
                 ("lcu_summary", {"return_value": {}}),
                 ("liveclient_summary", {"side_effect": _lc}),
                 ("get_team_context", {"return_value": None}),
                 ("validate_coaching_payload", {"new": lambda *a, **k: None})):
    mock.patch.object(sb, name, **kw).start()

before = {t.ident for t in threading.enumerate()}

def burst(n):
    errors = []
    def one():
        try:
            sb.build_state()
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))
    ts = [threading.Thread(target=one) for _ in range(n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(60)
    return errors

def survivors():
    time.sleep(0.2)
    return [t for t in threading.enumerate()
            if t.ident not in before and t.is_alive()]

err1 = burst(BURST)
first = survivors()
err2 = burst(BURST)
second = survivors()
print(json.dumps({
    "cap": sb._RELAY_POOL._max_workers,
    "errors": err1 + err2,
    "first": sorted(t.name for t in first),
    "second": sorted(t.name for t in second),
    "first_ids": sorted(t.ident for t in first),
    "second_ids": sorted(t.ident for t in second),
    "exit_joined": sorted(t.name for t in second if t in cft._threads_queues),
}))
""".replace("BURST", str(_BURST))


@pytest.fixture(scope="module")
def got(tmp_path_factory) -> dict:
    """One fresh-interpreter census, shared by the module's tests."""
    tmp_path = tmp_path_factory.mktemp("relay-census")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO) + os.pathsep + env.get("PYTHONPATH", "")
    # core/vision_token raises at import without a token; tests/conftest.py
    # sets one in this process, and the child must not depend on that.
    env.setdefault("RC_VISION_TOKEN", "s144q18-census-token")
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD], cwd=str(tmp_path), env=env,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=180, creationflags=_FLAGS, check=False)
    assert proc.returncode == 0, f"child failed rc={proc.returncode}:\n{proc.stderr[-1500:]}"
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, f"child printed nothing:\n{proc.stderr[-1500:]}"
    return json.loads(lines[-1])


def test_concurrent_builds_leave_only_relay_workers_within_the_cap(got):
    assert got["errors"] == [], got
    assert got["cap"] == _CAP, got
    # Positive control: the burst really drove the pool past one worker, so
    # the cap check below is not passing on a pool that never grew.
    assert len(got["first"]) >= 2, got
    assert len(got["first"]) <= _CAP, got
    assert all(n.startswith("rc-state-relay_") for n in got["first"]), got


def test_a_second_burst_reuses_the_same_workers(got):
    assert len(got["second"]) <= _CAP, got
    assert all(n.startswith("rc-state-relay_") for n in got["second"]), got
    # The pool is reused, not rebuilt: every first-burst worker is still the
    # one serving, and the second burst added at most the room left under
    # the cap.
    assert set(got["first_ids"]) <= set(got["second_ids"]), got


def test_every_surviving_relay_worker_is_joined_at_interpreter_exit(got):
    # concurrent.futures' exit hook joins exactly the workers registered in
    # its _threads_queues, so a registered worker cannot outlive the process.
    assert got["exit_joined"] == got["second"], got
