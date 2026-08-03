"""Lane 8 deep audit of ``tools/liveclient_relay.py`` - the Legion-local Live
Client relay - plus the shared defect it turned out to have three siblings of.

Selected by risk criterion 1 (it forwards the Riot Live Client `:2999`
envelope, which RC does not author) and criterion 4 (**zero** dedicated tests,
and it runs live as the ``RC-LiveClientRelay`` scheduled task). Recorded
expectation before reading: a timeout-less HTTP call able to wedge the relay
loop, and no shape validation before forwarding.

**EXPECTATION REFUTED on the timeouts** - recorded so it is not
re-investigated. Both HTTP calls are already bounded: ``_try_one`` uses
``timeout=2`` and ``upload`` uses ``timeout=3``. There is no unbounded call in
this file.

**FINDING 1 - every diagnostic this module emits is discarded.** The
scheduled task's ``<Command>`` is ``pythonw.exe`` (read from the task XML),
which has no console, and the module reports exclusively through ``print()``.
So ``ok 4821B in 42ms``, ``[err] tried both schemes``, ``err <exc>`` - all of
it goes nowhere. The bitter part is that the module already KNOWS this: its
own comment warns that a stale token "401s every /upload-liveclient silently
(pythonw, no console) -> relay cache empty -> the app never sees the live game
-> coach dead". It diagnosed the failure mode precisely and then kept
``print()`` as its only channel. Fixed by logging to ``logs/`` on the
in-tree precedent (``tools/daemon_slayer_extract.py:98-105``: basicConfig with
a StreamHandler AND a FileHandler).

**FINDING 2 - a dead token literal, in three files that the dashboard SERVES
UNAUTHENTICATED.** ``_resolve_auth_token`` ends in a hardcoded 32-hex
fallback, directly under a comment saying "Never reintroduce a token hardcode
as the live path". Measured: the literal does NOT match the live
``config/vision_token.txt``, so it is dead - but ``dashboard/routes_static.py``
lists this file in ``_AGENT_ALLOWED`` and ``_serve_agent_file`` has **no auth
check at all**, and the dashboard binds ``HOST = "::"``. Probed live:
``GET /agent/liveclient_relay.py`` returns the body containing the literal, to
anyone on the LAN or tailnet. The same literal is in ``tools/screen_agent.py``,
``tools/lcu_agent.py`` and ``tools/phase_watcher.py`` - all also served,
and the fourth was found by the allowlist-driven test below, not by the
hand grep that preceded it. Today that publishes a dead
string; the day someone "fixes" the fallback by pasting the live token, it
publishes the live one.

Worse in combination with Finding 1: if ``config/vision_token.txt`` ever goes
missing, the resolver silently returns the WRONG token, every upload 401s, and
the only report of it is a ``print()`` into a void.

**FINDING 3 - the upload target is a hardcoded LAN IP.** ``LEGION_URL``
points at ``http://192.168.8.230:8889``. That address is still bound on this
box (measured), so it works today, but post-ADR-011 both ends are the SAME
machine, so this sends the ``X-RC-Token`` in cleartext across the LAN
interface when loopback would do, and a DHCP change kills the relay silently
(Finding 1 again). CLAUDE.md already states the principle for the other
direction - "the game host is config not code" (``core/game_host.py``).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SECRET_LITERAL = re.compile(r"""['"][0-9a-f]{32}['"]""")


def _agent_allowlist() -> set[str]:
    """Read the served-file allowlist off disk, not from a restatement."""
    src = (_REPO / "dashboard" / "routes_static.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", "") == "_AGENT_ALLOWED"
                        for t in node.targets)):
            return {e.value for e in node.value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    raise AssertionError("_AGENT_ALLOWED not found in routes_static.py")


def _source_allowlist() -> set[str]:
    """Allowlisted entries that are TRACKED source text we can scan."""
    return {n for n in _agent_allowlist()
            if n.endswith((".py", ".ps1", ".md"))}


class TestNoSecretsInPubliclyServedFiles:
    """`_serve_agent_file` has no auth gate - assume anything here is public."""

    def test_allowlist_is_non_empty(self):
        """Guard the guard - an empty allowlist would make the sweep vacuous."""
        names = _agent_allowlist()
        assert len(names) >= 4, f"allowlist looks wrong: {names}"
        assert "liveclient_relay.py" in names

    @pytest.mark.parametrize("name", sorted(_source_allowlist()))
    def test_served_file_has_no_secret_shaped_literal(self, name):
        # No skip branch by deliberate design: a skip here would be an
        # always-passing guard, which tests/test_skip_condition_hygiene.py
        # correctly rejects. The parametrize set is filtered by EXTENSION
        # (a content property, deterministic in any checkout) rather than by
        # what happens to exist on this box - `rc_rootCA.pem` is gitignored
        # (`.gitignore:5 *.pem`) so it is present in the main tree and absent
        # in a worktree, and an existence-based filter would silently shrink
        # coverage depending on where the suite ran. It is a public CA cert,
        # not a secret carrier. Verified live: GET /agent/rc_rootCA.pem -> 200.
        path = _REPO / "tools" / name
        assert path.is_file(), (
            f"tools/{name} is allowlisted for /agent/ but missing from this "
            "checkout - the route can only 500 for it")
        hits = _SECRET_LITERAL.findall(path.read_text(encoding="utf-8"))
        assert not hits, (
            f"tools/{name} carries a 32-hex literal and is served "
            f"unauthenticated by /agent/{name}: {hits}")


class TestTokenResolverFailsLoudly:
    """A missing config must not silently yield a WRONG token."""

    def test_no_hardcoded_fallback(self, monkeypatch):
        import tools.liveclient_relay as relay
        monkeypatch.setattr(relay, "_token_candidates", lambda: [])
        monkeypatch.delenv("RC_VISION_TOKEN", raising=False)
        assert relay._resolve_auth_token() == "", (
            "resolver still invents a token when no config resolves - every "
            "upload then 401s and, under pythonw, says so to nobody")

    def test_env_override_still_wins(self, monkeypatch):
        """Positive control - the documented env path must keep working."""
        import tools.liveclient_relay as relay
        monkeypatch.setenv("RC_VISION_TOKEN", "  env-token  ")
        assert relay._resolve_auth_token() == "env-token"

    def test_config_file_is_read_when_present(self, monkeypatch, tmp_path):
        """Positive control - the canonical config path must keep working."""
        import tools.liveclient_relay as relay
        cfg = tmp_path / "vision_token.txt"
        cfg.write_text("from-config\n", encoding="utf-8")
        monkeypatch.delenv("RC_VISION_TOKEN", raising=False)
        monkeypatch.setattr(relay, "_token_candidates", lambda: [cfg])
        assert relay._resolve_auth_token() == "from-config"


class TestDiagnosticsSurvivePythonw:
    """print() under pythonw is a no-op; the relay must log to a file."""

    def test_module_logs_to_a_file(self, tmp_path):
        """Proven in a FRESH interpreter, because in-process is unprovable.

        The first version of this test inspected `logging.getLogger(...)
        .handlers` from inside pytest and was VACUOUS - `logging.basicConfig`
        is a documented no-op when the root logger already has handlers, and
        pytest installs its own, so the assertion was reading PYTEST's
        FileHandler and passed even with the module's removed (measured: the
        mutation stayed green at 19 passed). Caught by mutation testing, which
        is the only reason it is not still sitting here as false assurance.

        A subprocess gets a clean logging state, so this measures the module.
        """
        import subprocess
        import sys
        import uuid
        # The marker MUST be unique per run. A fixed string passed here too:
        # logs/liveclient_relay.log survives between runs, so an earlier
        # successful run's line satisfied the assertion even with the
        # FileHandler removed (measured - the mutation stayed green a SECOND
        # time). Stale artifact, not a working guard.
        marker = f"probe-{uuid.uuid4().hex}"
        probe = (
            f"import sys; sys.path.insert(0, r'{_REPO}');"
            "import tools.liveclient_relay as r;"
            f"r.log.info('{marker}');"
            "import logging; logging.shutdown();"
            "print(r._LOG_FILE)"
        )
        out = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                             text=True, timeout=60, cwd=str(_REPO))
        assert out.returncode == 0, f"probe failed: {out.stderr[-400:]}"
        log_path = Path(out.stdout.strip().splitlines()[-1])
        assert log_path.exists(), (
            f"module wrote no log file at {log_path} - the scheduled task "
            "runs pythonw.exe, so a StreamHandler-only setup is discarded")
        body = log_path.read_text(encoding="utf-8", errors="replace")
        assert marker in body, (
            "this run's line never reached the log file - the module is not "
            "configuring a FileHandler")

    def test_no_bare_prints_remain_in_the_relay(self):
        src = (_REPO / "tools" / "liveclient_relay.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        prints = [n.lineno for n in ast.walk(tree)
                  if isinstance(n, ast.Call)
                  and getattr(n.func, "id", "") == "print"]
        assert not prints, (
            f"print() calls remain at lines {prints} - under pythonw they go "
            "nowhere; use the module logger")


class TestUploadTargetIsConfigurable:
    """A hardcoded LAN IP is both DHCP-fragile and needless cleartext."""

    def test_default_target_is_loopback(self):
        import tools.liveclient_relay as relay
        assert "127.0.0.1" in relay._upload_url(), (
            "relay still defaults to a hardcoded LAN IP - both ends are the "
            "same machine post-ADR-011, so the token crosses the LAN for "
            "nothing and a DHCP change kills the relay silently")

    def test_target_is_env_overridable(self, monkeypatch):
        import tools.liveclient_relay as relay
        monkeypatch.setenv("RC_VISION_UPLOAD_URL", "http://10.0.0.9:8889/x")
        assert relay._upload_url() == "http://10.0.0.9:8889/x"
