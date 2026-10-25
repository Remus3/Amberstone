"""RM-878: every RC pytest run gets its own temp root, so a concurrent run cannot reap it.

The defect (LEDGER 1847, the RM-875 slice): one batch ended with 145 setup
ERRORs, every one ``FileNotFoundError: [WinError 3]`` on
``<temp>/pytest-of-<user>/pytest-146``, the run's own basetemp, removed while
the run was live. pytest's default root ``<temp>/pytest-of-<user>``
(``_pytest/tmpdir.py`` ``getbasetemp``) is ONE directory per user, shared by
every pytest process of every tree and worktree on the box. pytest's own
retention sweep spares a numbered dir only while it holds a ``.lock``
(``_pytest/pathlib.py`` ``ensure_deletable``: no lock means deletable), the
lock is taken only when ``keep != 0`` (``make_numbered_dir_with_cleanup``), and
any other actor that sweeps that root (a sibling tree's cleaner, a temp sweep)
follows no lock at all.

The fix (``tests/_basetemp_guard.py``): a top-level run claims a fresh
``<temp>/pytest-rc/<token>`` held by an open marker and points
``PYTEST_DEBUG_TEMPROOT`` at it, so pytest's numbered dirs, lock and
``failed`` / count-1 retention all run INSIDE a root no other run sweeps; xdist
workers and nested runs inherit it; the claim's own run removes it at
unconfigure when nothing failed, and every claim reaps the roots of dead runs.

Every behaviour test here runs a REAL child pytest with the system temp
redirected into this test's ``tmp_path`` (TMP / TEMP / TMPDIR), so neither the
live ``pytest-of-<user>`` root nor the live ``pytest-rc`` base is touched.
"""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests import _basetemp_guard as guard  # noqa: E402

CF = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
INI = "[pytest]\ntmp_path_retention_policy = failed\ntmp_path_retention_count = 1\n"
SCRUB = ("PYTEST_DEBUG_TEMPROOT", "PYTEST_ADDOPTS", "PYTEST_PLUGINS",
         "PYTEST_CURRENT_TEST", "PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT",
         "PYTEST_XDIST_TESTRUNUID")

HOLD = '''
import os
import time
from pathlib import Path


def test_hold(tmp_path, tmp_path_factory):
    bt = tmp_path_factory.getbasetemp()
    sig = Path(os.environ["RM878_SIG"])
    tmp = sig / "ready.tmp"
    tmp.write_text(str(bt), encoding="utf-8")
    tmp.replace(sig / "ready")
    deadline = time.time() + 90
    while not (sig / "go").exists() and time.time() < deadline:
        time.sleep(0.05)
    assert (sig / "go").exists(), "the harness never released the hold"
    assert bt.is_dir(), f"live basetemp {bt} was deleted mid-run"
    assert tmp_path.is_dir(), f"live tmp_path {tmp_path} was deleted mid-run"
    tmp_path_factory.mktemp("after")
'''

RECORD = '''
import os
from pathlib import Path


def _rec(tmp_path, name):
    out = Path(os.environ["RM878_OUT"])
    wid = os.environ.get("PYTEST_XDIST_WORKER", "-")
    env = os.environ.get("PYTEST_DEBUG_TEMPROOT", "")
    (out / (name + ".txt")).write_text(wid + "|" + str(tmp_path) + "|" + env,
                                       encoding="utf-8")
'''

PASS = "def test_ok(tmp_path):\n    (tmp_path / 'f').write_text('x')\n"
FAIL = "def test_red(tmp_path):\n    (tmp_path / 'f').write_text('x')\n    assert False\n"


# ---- harness ------------------------------------------------------------------

def _setup(tmp_path: Path):
    """Return (probe dir, child env, redirected system temp)."""
    systemp = tmp_path / "t"
    systemp.mkdir()
    probe = tmp_path / "p"
    probe.mkdir()
    (probe / "pytest.ini").write_text(INI, encoding="ascii")
    (probe / "test_hold.py").write_text(HOLD, encoding="ascii")
    (probe / "test_pass.py").write_text(PASS, encoding="ascii")
    (probe / "test_fail.py").write_text(FAIL, encoding="ascii")
    env = dict(os.environ)
    for k in SCRUB:
        env.pop(k, None)
    for k in ("TMP", "TEMP", "TMPDIR"):
        env[k] = str(systemp)
    return probe, env, systemp


def _cmd(probe: Path, *args: str, rc: bool = True):
    """A child pytest on the probe. ``rc=True`` loads RC's temp hooks exactly as
    the rootdir conftest re-exports them; ``rc=False`` is another tree's run."""
    plugin = ["-p", "tests._basetemp_guard"] if rc else []
    # Test files go in ABSOLUTE: a path pytest cannot find makes it fall back to
    # the invocation dir (cwd = REPO) for initial conftests, which would load
    # RC's own conftests into the probe.
    args = [str(probe / a) if a.endswith(".py") else a for a in args]
    return [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *plugin,
            "--rootdir", str(probe), "-c", str(probe / "pytest.ini"), *args]


def _run(probe: Path, env: dict, *args: str, rc: bool = True):
    return subprocess.run(_cmd(probe, *args, rc=rc), cwd=str(REPO), env=env,
                          capture_output=True, text=True, timeout=180,
                          creationflags=CF)


def _hold_while(tmp_path: Path, probe: Path, env: dict, during, a_args=()):
    """Run A (holds its tmp_path), call ``during(a_basetemp)`` while A is live,
    then release A. Returns (A exit code, A output, A basetemp)."""
    sig = tmp_path / "sig"
    sig.mkdir()
    env = dict(env, RM878_SIG=str(sig))
    a = subprocess.Popen(_cmd(probe, *a_args, "test_hold.py"), cwd=str(REPO),
                         env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, creationflags=CF)
    out = ""
    try:
        deadline = time.time() + 90
        while not (sig / "ready").exists():
            if a.poll() is not None or time.time() > deadline:
                break
            time.sleep(0.05)
        if not (sig / "ready").exists():
            (sig / "go").write_text("go", encoding="ascii")
            out, _ = a.communicate(timeout=120)
            pytest.fail("run A never reached its hold:\n" + out)
        a_bt = Path((sig / "ready").read_text(encoding="utf-8"))
        during(a_bt)
    finally:
        if a.returncode is None:
            (sig / "go").write_text("go", encoding="ascii")
            out, _ = a.communicate(timeout=120)
    return a.returncode, out, a_bt


def _claims(systemp: Path):
    base = systemp / guard.RUN_BASE_NAME
    return sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []


def _shared_runs(systemp: Path):
    return [p for p in systemp.glob("pytest-of-*/pytest-*")
            if p.is_dir() and not p.is_symlink()]


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


# ---- concurrency: a live run cannot be reaped -----------------------------------

def test_a_sweep_of_the_shared_default_root_cannot_reach_a_live_run(tmp_path):
    """The LEDGER 1847 shape: while A is live, something sweeps every numbered
    dir in ``<temp>/pytest-of-<user>`` with no regard for locks. Before RM-878
    A's basetemp lived there and A died with the batch's FileNotFoundError."""
    probe, env, systemp = _setup(tmp_path)

    def sweep(_a_bt):
        for run in _shared_runs(systemp):
            shutil.rmtree(run, ignore_errors=True)

    rc, out, a_bt = _hold_while(tmp_path, probe, env, sweep)
    assert rc == 0, out
    assert not any(_under(a_bt, p) for p in systemp.glob("pytest-of-*")), a_bt
    assert _under(a_bt, systemp / guard.RUN_BASE_NAME), a_bt


def test_two_concurrent_pytest_runs_cannot_reap_each_other(tmp_path):
    """pytest's own sweep, measured: A runs lockless (``retention_policy =
    none`` gives ``keep = 0``, so ``make_numbered_dir_with_cleanup`` takes no
    ``.lock``); B is another tree's plain pytest run in the shared default root
    whose test fails, so its numbered dir outlives it, and its atexit
    ``cleanup_numbered_dir`` removes every lockless dir numbered below
    ``max - keep``. Before RM-878 that was A's live basetemp."""
    probe, env, systemp = _setup(tmp_path)
    b_codes = []

    def other_tree_run(_a_bt):
        b_codes.append(_run(probe, env, "test_fail.py", rc=False).returncode)

    rc, out, a_bt = _hold_while(tmp_path, probe, env, other_tree_run,
                                a_args=("-o", "tmp_path_retention_policy=none"))
    assert b_codes == [1]
    assert rc == 0, out
    assert _under(a_bt, systemp / guard.RUN_BASE_NAME), a_bt


def test_concurrent_rc_runs_get_separate_roots_and_a_claim_spares_a_live_root(tmp_path):
    """B and C start while A is live: each claim sweeps dead roots and must
    leave A's (held) root alone. Afterwards only the failed run's root stays
    (retention count 1), and the next run reaps it - nothing piles up."""
    probe, env, systemp = _setup(tmp_path)
    seen = {}

    def others(a_bt):
        seen["during"] = _claims(systemp)
        seen["b"] = _run(probe, env, "test_pass.py")
        seen["c"] = _run(probe, env, "test_fail.py")
        seen["after_bc"] = _claims(systemp)

    rc, out, a_bt = _hold_while(tmp_path, probe, env, others)
    assert rc == 0, out
    assert seen["b"].returncode == 0, seen["b"].stdout + seen["b"].stderr
    assert seen["c"].returncode == 1, seen["c"].stdout + seen["c"].stderr
    assert len(seen["during"]) == 1, seen["during"]
    a_root = seen["during"][0]
    assert _under(a_bt, a_root)
    # B removed its own root on a pass; C kept one for its failure; A's survived.
    assert a_root in seen["after_bc"] and len(seen["after_bc"]) == 2, seen["after_bc"]
    left = _claims(systemp)
    assert len(left) == 1 and left[0] != a_root, left
    kept = list(left[0].glob("pytest-of-*/pytest-*/test_red*"))
    assert kept, "the failed test's tmp_path must be kept for the post-mortem"
    assert _shared_runs(systemp) == [], "no RC run may land in the shared root"
    d = _run(probe, env, "test_pass.py")
    assert d.returncode == 0, d.stdout + d.stderr
    assert _claims(systemp) == [], "a new claim reaps the dead failed root"


# ---- xdist ----------------------------------------------------------------------

def test_xdist_workers_share_their_controllers_root(tmp_path):
    pytest.importorskip("xdist")
    probe, env, systemp = _setup(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    for f in ("a", "b"):
        body = RECORD + "".join(
            f"\n\ndef test_{f}{i}(tmp_path):\n    _rec(tmp_path, '{f}{i}')\n"
            for i in range(4))
        (probe / f"test_rec_{f}.py").write_text(body, encoding="ascii")
    env = dict(env, RM878_OUT=str(out_dir))
    r = _run(probe, env, "-n", "2", "test_rec_a.py", "test_rec_b.py")
    assert r.returncode == 0, r.stdout + r.stderr
    rows = [p.read_text(encoding="utf-8").split("|") for p in out_dir.glob("*.txt")]
    assert len(rows) == 8, rows
    workers = {w for w, _, _ in rows}
    assert workers == {"gw0", "gw1"}, workers
    envs = {e for _, _, e in rows}
    assert len(envs) == 1, envs
    root = Path(envs.pop())
    assert root.parent.resolve() == (systemp / guard.RUN_BASE_NAME).resolve(), root
    for wid, tp, _ in rows:
        tp = Path(tp)
        assert _under(tp, root), (tp, root)
        assert f"popen-{wid}" in tp.parts, tp
    assert not root.exists(), "a passing run removes its own root"
    assert _claims(systemp) == [] and _shared_runs(systemp) == []


# ---- reaping ----------------------------------------------------------------------

def test_sweep_reaps_dead_roots_and_spares_live_and_fresh_ones(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    old = time.time() - 3600
    dead_marked = base / "aaa111"
    (dead_marked / "pytest-of-u" / "pytest-0").mkdir(parents=True)
    (dead_marked / guard.MARKER_NAME).write_text("1", encoding="ascii")
    dead_unmarked = base / "bbb222"
    dead_unmarked.mkdir()
    fresh_unmarked = base / "ccc333"
    fresh_unmarked.mkdir()
    note = base / "note.txt"
    note.write_text("not a run root", encoding="ascii")
    for p in (dead_marked, dead_unmarked):
        os.utime(p, (old, old))
    live = guard.claim_run_root(base)
    assert live is not None
    try:
        removed = guard.sweep_dead_roots(base, keep_dead=0)
        assert sorted(removed) == sorted([dead_marked, dead_unmarked]), removed
        assert not dead_marked.exists() and not dead_unmarked.exists()
        assert fresh_unmarked.is_dir(), "an unmarked root inside the grace window is spared"
        assert live.path.is_dir(), "a held root is live and is never reaped"
        assert note.is_file()
    finally:
        live.close()
    assert guard.sweep_dead_roots(base, keep_dead=0) == [live.path]


def test_sweep_keeps_the_newest_dead_roots_up_to_keep_dead(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    now = time.time()
    roots = []
    for i, age in enumerate((300, 200, 100)):
        r = base / f"r{i}"
        r.mkdir()
        (r / guard.MARKER_NAME).write_text("1", encoding="ascii")
        os.utime(r, (now - age, now - age))
        roots.append(r)
    removed = guard.sweep_dead_roots(base, keep_dead=1)
    assert sorted(removed) == sorted(roots[:2])
    assert roots[2].is_dir()


def test_a_killed_runs_root_is_reaped_but_not_while_its_owner_lives(tmp_path):
    base = tmp_path / "base"
    code = (
        "import sys, time\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, {str(REPO)!r})\n"
        "from tests import _basetemp_guard as g\n"
        f"c = g.claim_run_root(Path({str(base)!r}))\n"
        "print(c.path, flush=True)\n"
        "time.sleep(120)\n"
    )
    p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE,
                         text=True, creationflags=CF)
    try:
        root = Path(p.stdout.readline().strip())
        assert root.is_dir(), root
        assert guard.owner_alive(root) is True
        assert guard.sweep_dead_roots(base, keep_dead=0) == []
        assert root.is_dir()
    finally:
        p.kill()
        p.wait(timeout=30)
        p.stdout.close()
    deadline = time.time() + 10
    removed = []
    while time.time() < deadline:
        removed = guard.sweep_dead_roots(base, keep_dead=0)
        if removed:
            break
        time.sleep(0.2)
    assert removed == [root]
    assert not root.exists()


# ---- what the claim respects --------------------------------------------------------

def test_a_caller_chosen_root_and_an_explicit_basetemp_claim_nothing(tmp_path):
    probe, env, systemp = _setup(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (probe / "test_rec.py").write_text(
        RECORD + "\n\ndef test_r(tmp_path):\n    _rec(tmp_path, 'r')\n", encoding="ascii")
    env = dict(env, RM878_OUT=str(out_dir))

    caller = tmp_path / "caller"
    caller.mkdir()
    r = _run(probe, dict(env, PYTEST_DEBUG_TEMPROOT=str(caller)), "test_rec.py")
    assert r.returncode == 0, r.stdout + r.stderr
    tp = Path((out_dir / "r.txt").read_text(encoding="utf-8").split("|")[1])
    assert _under(tp, caller), tp
    assert _claims(systemp) == []

    bt = tmp_path / "bt"
    r = _run(probe, env, "--basetemp", str(bt), "test_rec.py")
    assert r.returncode == 0, r.stdout + r.stderr
    tp = Path((out_dir / "r.txt").read_text(encoding="utf-8").split("|")[1])
    assert _under(tp, bt), tp
    assert _claims(systemp) == []


def test_no_claim_inside_a_session_scratchpad(tmp_path):
    probe, env, systemp = _setup(tmp_path)
    sp = tmp_path / "Temp" / "claude" / "E--Proj" / "0000-session" / "scratchpad"
    sp.mkdir(parents=True)
    for k in ("TMP", "TEMP", "TMPDIR"):
        env[k] = str(sp)
    r = _run(probe, env, "test_pass.py")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (sp / guard.RUN_BASE_NAME).exists()


def test_run_base_is_under_the_system_temp_dir():
    assert guard.TEMPROOT_VAR == "PYTEST_DEBUG_TEMPROOT"
    assert guard.run_base() == Path(tempfile.gettempdir()).resolve() / guard.RUN_BASE_NAME
    assert not guard.RUN_BASE_NAME.startswith("pytest-of-")


# ---- wiring ---------------------------------------------------------------------------

def test_rootdir_conftest_reexports_both_temp_hooks():
    tree = ast.parse((REPO / "conftest.py").read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "tests._basetemp_guard":
            names |= {a.name for a in node.names if a.asname in (None, a.name)}
    assert {"pytest_configure", "pytest_unconfigure"} <= names, names


def test_this_run_is_on_a_claimed_root(tmp_path, pytestconfig):
    """The live wiring: this very run (or its xdist controller) claimed a root,
    or the caller chose one; only an explicit --basetemp, or a system temp dir
    inside a session scratchpad, leaves the variable unset."""
    root = os.environ.get(guard.TEMPROOT_VAR)
    if not root:
        explained = (pytestconfig.option.basetemp
                     or guard._scratchpad_root(guard.run_base()) is not None)
        assert explained, "PYTEST_DEBUG_TEMPROOT is unset: the claim did not run"
        pytest.skip("explicit --basetemp or a scratchpad temp dir: nothing claimed")
    assert _under(tmp_path, Path(root)), (tmp_path, root)
