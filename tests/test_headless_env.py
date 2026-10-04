"""Headless account routing: every `claude` spawn this tree starts rides the proxy.

Operator contract 2026-10-02. A headless run (inbox responder, lanes, loop
executor, adjudicator, CI watchdog, ephemeral supervisor agent, weekly hygiene)
must reach Claude through a local subscription proxy whose URL lives ONLY in the
user environment variable `CLAUDE_HEADLESS_BASE_URL`. The helper copies it into
the CHILD environment as `ANTHROPIC_BASE_URL` and nowhere else, and it FAILS
CLOSED: unset, non-loopback, malformed or not listening means no spawn at all -
never a direct `claude`. Deleting the variable is the kill switch.

Every value here is a FAKE (ports in the 6553x range, never the live one), and
every probe and registry read is monkeypatched or aimed at a socket this test
owns. The autouse fixture in `tests/conftest.py` installs an "open fake route"
for the rest of the suite; the tests below override it explicitly.
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from ops.loop import headless_env as he
from tests import _repo_walk

REPO = Path(__file__).resolve().parent.parent
FAKE_URL = "http://127.0.0.1:65531"
FAKE_URL_2 = "http://127.0.0.1:65532"
# Bound at IMPORT, before the conftest autouse fake replaces the module seams.
_REAL_PROBE = he._probe
_REAL_READ = he._read_user_var


@pytest.fixture
def route(monkeypatch, tmp_path):
    """Explicit control of both seams, plus a private refusal log."""
    state = {"registry": he.REGISTRY_ABSENT, "probe": None, "probed": []}

    def fake_read(name):
        return state["registry"]

    def fake_probe(host, port, timeout):
        state["probed"].append((host, port))
        return state["probe"]

    monkeypatch.setattr(he, "_read_user_var", fake_read)
    monkeypatch.setattr(he, "_probe", fake_probe)
    monkeypatch.setattr(he, "REFUSAL_LOG", tmp_path / "headless_route.log")
    return state


# ---------------------------------------------------------------------------
# Fail-closed refusals
# ---------------------------------------------------------------------------


def test_unset_var_is_refused(route):
    route["registry"] = he.REGISTRY_ABSENT
    with pytest.raises(he.HeadlessRouteRefused) as ei:
        he.resolve_base_url(environ={})
    assert ei.value.reason == "unset"
    assert route["probed"] == []


def test_registry_readable_but_value_deleted_ignores_stale_process_env(route):
    """The kill switch: a long-lived parent that inherited the var before the
    operator deleted it must still refuse. The store is the authority whenever
    it is readable; the process env is consulted only when it is not."""
    route["registry"] = None  # store readable, value absent
    with pytest.raises(he.HeadlessRouteRefused) as ei:
        he.resolve_base_url(environ={he.ENV_VAR: FAKE_URL})
    assert ei.value.reason == "unset"


def test_empty_value_is_refused(route):
    route["registry"] = "   "
    with pytest.raises(he.HeadlessRouteRefused) as ei:
        he.resolve_base_url(environ={})
    assert ei.value.reason == "unset"


@pytest.mark.parametrize("url", [
    "http://10.0.0.5:65531",
    "http://example.invalid:65531",
    "http://192.168.1.10:65531",
])
def test_non_loopback_host_is_refused_without_probing(route, url):
    route["registry"] = url
    with pytest.raises(he.HeadlessRouteRefused) as ei:
        he.resolve_base_url(environ={})
    assert ei.value.reason == "not_loopback"
    assert route["probed"] == []


@pytest.mark.parametrize("url", ["ftp://127.0.0.1:65531", "127.0.0.1:65531", "http://", "nonsense"])
def test_malformed_url_is_refused(route, url):
    route["registry"] = url
    with pytest.raises(he.HeadlessRouteRefused) as ei:
        he.resolve_base_url(environ={})
    assert ei.value.reason in {"bad_url", "not_loopback"}
    assert route["probed"] == []


def test_port_not_listening_is_refused(route):
    route["registry"] = FAKE_URL
    route["probe"] = "connect_refused"
    with pytest.raises(he.HeadlessRouteRefused) as ei:
        he.resolve_base_url(environ={})
    assert ei.value.reason == "proxy_down"
    assert route["probed"] == [("127.0.0.1", 65531)]


def test_real_probe_refused_on_a_closed_loopback_port(monkeypatch, tmp_path):
    """The real `_probe`, against a port this test bound and then released."""
    monkeypatch.setattr(he, "REFUSAL_LOG", tmp_path / "r.log")
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    assert _REAL_PROBE("127.0.0.1", port, 1.0) is not None


def test_real_probe_open_on_a_listening_loopback_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    try:
        assert _REAL_PROBE("127.0.0.1", s.getsockname()[1], 1.0) is None
    finally:
        s.close()


def test_refusal_is_logged_without_the_url(route):
    route["registry"] = FAKE_URL
    route["probe"] = "connect_refused"
    with pytest.raises(he.HeadlessRouteRefused):
        he.resolve_base_url(environ={}, caller="unit-test")
    text = he.REFUSAL_LOG.read_text(encoding="utf-8")
    row = json.loads(text.strip().splitlines()[-1])
    assert row["caller"] == "unit-test"
    assert row["reason"] == "proxy_down"
    assert "65531" not in text and "127.0.0.1" not in text


# ---------------------------------------------------------------------------
# The happy path and its scope
# ---------------------------------------------------------------------------


def test_set_and_open_sets_child_env_only(route, monkeypatch):
    route["registry"] = FAKE_URL
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    base = {"PATH": "x", "ANTHROPIC_BASE_URL": "http://stale.invalid"}
    before_parent = dict(os.environ)
    env = he.headless_child_env(base)
    assert env["ANTHROPIC_BASE_URL"] == FAKE_URL
    assert env["PATH"] == "x"
    assert base["ANTHROPIC_BASE_URL"] == "http://stale.invalid"  # input not mutated
    # Key NAMES only, never the environment itself, in an assert operand.
    now = dict(os.environ)
    drift = sorted(k for k in set(now) | set(before_parent) if now.get(k) != before_parent.get(k))
    assert drift == []  # parent untouched
    parent_has_base_url = "ANTHROPIC_BASE_URL" in now
    assert parent_has_base_url is False


def test_child_env_defaults_to_a_copy_of_os_environ(route, monkeypatch):
    route["registry"] = FAKE_URL
    monkeypatch.setenv("RC_HEADLESS_ENV_MARKER", "1")
    env = he.headless_child_env()
    assert env["RC_HEADLESS_ENV_MARKER"] == "1"
    assert env["ANTHROPIC_BASE_URL"] == FAKE_URL
    parent_value = os.environ.get("ANTHROPIC_BASE_URL")
    assert parent_value != FAKE_URL


def test_registry_value_preferred_over_process_env(route):
    route["registry"] = FAKE_URL
    assert he.resolve_base_url(environ={he.ENV_VAR: FAKE_URL_2}) == FAKE_URL


def test_process_env_is_the_fallback_when_the_store_is_unreadable(route):
    route["registry"] = he.REGISTRY_ABSENT
    assert he.resolve_base_url(environ={he.ENV_VAR: FAKE_URL_2}) == FAKE_URL_2


def test_localhost_is_loopback(route):
    route["registry"] = "http://localhost:65533"
    assert he.resolve_base_url(environ={}) == "http://localhost:65533"
    assert route["probed"] == [("localhost", 65533)]


def test_read_user_var_never_raises():
    # Real read of a name that is certainly absent: None (store readable) or
    # REGISTRY_ABSENT (no store on this platform). Never an exception.
    got = _REAL_READ("RC_HEADLESS_ENV_DEFINITELY_ABSENT_7f3a")
    assert got is None or got is he.REGISTRY_ABSENT


# ---------------------------------------------------------------------------
# CLI - the PowerShell runners call this
# ---------------------------------------------------------------------------


def test_cli_refuses_with_exit_3(route, capsys):
    route["registry"] = he.REGISTRY_ABSENT
    assert he.main(["--url"], environ={}) == he.EXIT_REFUSED
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unset" in captured.err


def test_cli_prints_url_on_success(route, capsys):
    route["registry"] = FAKE_URL
    assert he.main(["--url"], environ={}) == 0
    assert capsys.readouterr().out.strip() == FAKE_URL


def test_cli_runs_as_a_bare_script_with_the_var_unset(tmp_path):
    """The .ps1 runners call the file by path from a worktree cwd, so it must
    import nothing from the repo. With the var unset in BOTH the process env
    and (we cannot clear the real store, so) via an override, it refuses."""
    env = {k: v for k, v in os.environ.items() if k.upper() != he.ENV_VAR}
    env["RC_HEADLESS_ENV_FORCE_UNSET"] = "1"
    env["RC_HEADLESS_ENV_LOG"] = str(tmp_path / "r.log")
    p = subprocess.run([sys.executable, str(REPO / "ops" / "loop" / "headless_env.py"), "--url"],
                       cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode == he.EXIT_REFUSED, p.stderr
    assert p.stdout == ""


# ---------------------------------------------------------------------------
# Static guard: every spawn path is routed
# ---------------------------------------------------------------------------

# Python modules that start a headless `claude`. Each must route through
# `headless_child_env` OR through `ops/loop/fleet_route.py` (FLEET-KIT-v1),
# which asks `headless_env.resolve_base_url` first and fails closed on it.
# tests/test_headless_route_spawn_paths.py drives each one with the var deleted.
#
# KIT_ROUTED: started only through the fleet kit.
# LEGACY_ROUTED: still on headless_child_env, because FLEET-KIT-v1 cannot
# express what they need (named kit gaps, reported to MAIN): the responder's
# agreement-pinned model + measured argv tail, and the executor's --resume
# continuity, operator-set effort and process-tree kill.
KIT_ROUTED = {
    "ops/loop/adjudicator.py",
    "tools/ci_watchdog.py",
    "agents/_supervisor_ephemeral.py",
    "ops/loop/drain_waves_2_3.py",
}
# KIT_ROUTED files that also start a NON-claude child (git / gh) hidden, so
# CREATE_NO_WINDOW in them is not a second claude launcher. Reason per file.
_KIT_ROUTED_OWN_NO_WINDOW = {
    "tools/ci_watchdog.py": "its git/gh runner `_run`",
    "ops/loop/drain_waves_2_3.py": "its `git worktree add` runner `_git`",
}
LEGACY_ROUTED = {
    "ops/loop/executor.py",
    "tools/inbox_responder_spawn.py",
}
PY_SPAWN_SITES = KIT_ROUTED | LEGACY_ROUTED
# Files that NAME the CLI without spawning it, each with its reason.
PY_NON_SPAWN = {
    "agents/_supervisor_common.py": "defines the CLAUDE_CLI constant only",
    "agents/supervisor.py": "re-exports CLAUDE_CLI",
    "tools/inbox_responder_procs.py": "the responder's generic process seam; its "
                                      "only claude caller is inbox_responder_spawn.real_spawner",
    "tools/inbox_responder_runner.py": "resolves cfg.claude_exe; every spawn goes "
                                       "through inbox_responder_spawn.real_spawner",
}
_PY_NAMES_CLI = re.compile(
    r"""["']claude(\.cmd|\.exe)?["']|\bCLAUDE_CLI\b|\bDEFAULT_CLAUDE_CMD\b|\bclaude_exe\b""")

# PowerShell runners that invoke `claude -p`. Each must dot-source the shared
# gate before its first invocation. Interactive / GUI launchers are excluded:
# they open a session, they do not spawn a headless one.
_PS_INVOKES = re.compile(r"&\s*(\$claude|claude)\s+-p\b", re.IGNORECASE)


def test_python_spawn_inventory_is_exhaustive():
    found = set()
    for path in _repo_walk.repo_files(REPO, ("*.py",)):
        rel = _repo_walk.relative_posix(path, REPO)
        if rel.startswith("tests/") or "/tests/" in rel or "/suite/" in rel:
            continue
        # the stub, the gate itself, and the fleet route + vendored kit (the
        # door every KIT_ROUTED site goes through, pinned by its own tests)
        if rel in {"ops/loop/claude_stub.py", "ops/loop/headless_env.py",
                   "ops/loop/fleet_route.py", "ops/fleet_kit/fleet_headless.py"}:
            continue
        if _PY_NAMES_CLI.search(path.read_text(encoding="utf-8", errors="replace")):
            found.add(rel)
    assert found, "empty enumeration would pass vacuously"
    unknown = found - PY_SPAWN_SITES - set(PY_NON_SPAWN)
    assert not unknown, f"new module names the claude CLI - route it or allowlist it: {unknown}"


@pytest.mark.parametrize("rel", sorted(LEGACY_ROUTED))
def test_python_spawn_site_routes_through_helper(rel):
    assert "headless_child_env(" in (REPO / rel).read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", sorted(KIT_ROUTED))
def test_kit_routed_site_goes_through_fleet_route_only(rel):
    text = (REPO / rel).read_text(encoding="utf-8")
    assert "fleet_route" in text and ".spawn(" in text
    # one path, the kit's: no second env builder or direct process start left
    assert "headless_child_env(" not in text
    assert "CREATE_NO_WINDOW" not in text or rel in _KIT_ROUTED_OWN_NO_WINDOW, \
        "the kit owns the hidden console for the claude spawn"


def test_fleet_route_fails_closed_through_the_gate():
    """LEDGER 1460 survives the kit: the URL the kit sees comes from
    headless_env.resolve_base_url, and the kit's probe is RC's probe."""
    text = (REPO / "ops" / "loop" / "fleet_route.py").read_text(encoding="utf-8")
    assert "resolve_base_url(" in text
    assert "._probe(" in text


def test_every_powershell_claude_invocation_is_gated():
    hits = []
    for path in _repo_walk.repo_files(REPO, ("*.ps1",)):
        text = path.read_text(encoding="utf-8", errors="replace")
        if not _PS_INVOKES.search(text):
            continue
        rel = _repo_walk.relative_posix(path, REPO)
        hits.append(rel)
        gate = text.find("Assert-HeadlessRoute")
        first = _PS_INVOKES.search(text).start()
        assert "headless_route.ps1" in text, f"{rel} does not dot-source the gate"
        assert 0 <= gate < first, f"{rel} invokes claude before the gate"
    assert set(hits) >= {"ops/loop/run_lane.ps1"}, hits


# FLEET-KIT-v1: these PowerShell runners start their run through the fleet
# kit's CLI door, never `claude -p` directly. A refusal there is exit 3 with
# nothing started, and the runner must stop on it rather than retry.
PS_KIT_ROUTED = ("tools/headless_run.ps1", "tools/weekly_hygiene_run.ps1")


@pytest.mark.parametrize("rel", PS_KIT_ROUTED)
def test_powershell_runner_goes_through_the_fleet_route(rel):
    text = (REPO / rel).read_text(encoding="utf-8")
    assert not _PS_INVOKES.search(text), f"{rel} still invokes claude directly"
    assert "fleet_route.py" in text
    assert "$code -eq 3" in text and "exit 3" in text, f"{rel} does not stop on a refusal"


def test_powershell_gate_calls_the_python_helper_and_scopes_to_process():
    text = (REPO / "ops" / "loop" / "headless_route.ps1").read_text(encoding="ascii")
    assert "headless_env.py" in text
    assert "$env:ANTHROPIC_BASE_URL" in text
    # never user-wide or machine-wide
    assert "SetEnvironmentVariable" not in text
    assert "setx" not in text.lower()
    assert "--auto-fallback" not in text


def test_no_tracked_source_sets_anthropic_base_url_persistently():
    offenders = []
    this_file = Path(__file__).resolve()
    scanned = 0
    for path in _repo_walk.repo_files(REPO, ("*.py", "*.ps1", "*.bat", "*.cmd")):
        # This guard names its own needles, so it must not scan itself. It was
        # green before its first commit only because the walk is TRACKED-ONLY
        # and the file was untracked - the self-match landed with the commit.
        if path.resolve() == this_file:
            continue
        scanned += 1
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"setx\s+ANTHROPIC_BASE_URL|SetEnvironmentVariable\(\s*['\"]ANTHROPIC_BASE_URL",
                     text, re.IGNORECASE):
            offenders.append(_repo_walk.relative_posix(path, REPO))
        if "auto-fallback" in text and "teamclaude" in text:
            offenders.append(_repo_walk.relative_posix(path, REPO))
    assert scanned, "empty enumeration would pass vacuously"
    assert not offenders
