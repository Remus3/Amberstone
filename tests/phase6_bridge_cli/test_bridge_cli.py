"""Phase 6 — tools/bridge_cli.py contract tests.

Covers the consolidated bridge CLI:
- argparse surface (required flags, choices, defaults)
- exit codes
- envelope construction per subcommand
- side effects on the processed-tasks and last-seen state files
- BridgeMetrics counter increments
- shim files dispatch to the correct subcommand

The 7 originals (bridge_task.py, bridge_post_result.py, bridge_pull_tasks.py,
bridge_fetch.py, bridge_ping.py, bridge_heartbeat.py, bridge_post.py) are now
~10-20 LOC shims importing bridge_cli.main and prepending the subcommand to
argv. The frozen contract for the cron-facing scripts is preserved exactly.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"

# Make `tools/` importable so we can drive bridge_cli.main directly
sys.path.insert(0, str(TOOLS))

import bridge_cli  # noqa: E402

PYTHON = sys.executable


# ---------- Argparse surface --------------------------------------------


class TestArgparseSurface:
    def test_main_no_subcommand_errors(self, capsys):
        with pytest.raises(SystemExit) as exc:
            bridge_cli.main([])
        assert exc.value.code == 2

    def test_unknown_subcommand_errors(self, capsys):
        with pytest.raises(SystemExit) as exc:
            bridge_cli.main(["bogus"])
        assert exc.value.code == 2

    def test_task_requires_target_and_summary(self, capsys):
        with pytest.raises(SystemExit) as exc:
            bridge_cli.main(["task"])
        assert exc.value.code == 2

    def test_task_target_choices_enforced(self):
        with pytest.raises(SystemExit):
            bridge_cli.main(["task", "--target", "peer", "--summary", "x"])

    def test_post_result_requires_task_id(self):
        with pytest.raises(SystemExit):
            bridge_cli.main(["post-result"])

    def test_post_result_reply_to_choices(self):
        with pytest.raises(SystemExit):
            bridge_cli.main(["post-result", "task-1",
                             "--reply-to", "mars"])

    def test_pull_target_default_is_gamepc(self, monkeypatch, capsys):
        monkeypatch.setattr(bridge_cli, "_fetch_messages",
                            lambda since: {"now": 1.0, "messages": []})
        monkeypatch.setattr(bridge_cli, "_read_processed", lambda: set())
        rc = bridge_cli.main(["pull"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["target"] == "gamepc"


# ---------- task subcommand --------------------------------------------


class TestTaskSubcommand:
    def test_envelope_shape_for_task_kind(self, monkeypatch, capsys):
        seen: dict = {}

        def fake_post(env, **kw):
            seen["env"] = env
            return {"ts": 9999.0}

        monkeypatch.setattr(bridge_cli, "_post_envelope", fake_post)
        rc = bridge_cli.main([
            "task", "--target", "gamepc",
            "--summary", "do thing",
            "--prompt", "the prompt",
            "--id", "task-fixed-1",
        ])
        assert rc == 0
        env = seen["env"]
        assert env["kind"] == "task"
        assert env["id"] == "task-fixed-1"
        assert env["source"] == "legion"   # opposite of target
        assert env["target"] == "gamepc"
        assert env["summary"] == "do thing"
        assert env["body"]["prompt"] == "the prompt"
        assert "issued" in env["body"]

        out = json.loads(capsys.readouterr().out)
        assert out["task_id"] == "task-fixed-1"
        assert out["ts"] == 9999.0

    def test_no_prompt_defaults_to_note_kind(self, monkeypatch):
        seen: dict = {}
        monkeypatch.setattr(bridge_cli, "_post_envelope",
                            lambda env, **kw: seen.setdefault("env", env)
                            or {"ts": 1.0})
        rc = bridge_cli.main([
            "task", "--target", "legion", "--summary", "log-only",
        ])
        assert rc == 0
        assert seen["env"]["kind"] == "note"
        assert "prompt" not in seen["env"]["body"]

    def test_explicit_kind_task_without_prompt_fails(self, capsys):
        rc = bridge_cli.main([
            "task", "--target", "gamepc",
            "--summary", "x", "--kind", "task",
        ])
        assert rc == 2
        assert "--prompt is required" in capsys.readouterr().err

    def test_bad_body_json_returns_2(self, capsys):
        rc = bridge_cli.main([
            "task", "--target", "gamepc", "--summary", "x",
            "--prompt", "p", "--body", "{not-json}",
        ])
        assert rc == 2

    def test_post_failure_returns_1(self, monkeypatch, capsys):
        def boom(env, **kw):
            raise RuntimeError("network gone")
        monkeypatch.setattr(bridge_cli, "_post_envelope", boom)
        rc = bridge_cli.main([
            "task", "--target", "gamepc", "--summary", "x", "--prompt", "p",
        ])
        assert rc == 1
        assert "bridge post failed" in capsys.readouterr().err


# ---------- post-result subcommand -------------------------------------


class TestPostResultSubcommand:
    def test_default_target_is_opposite_of_source(self, monkeypatch):
        seen: dict = {}
        monkeypatch.setattr(bridge_cli, "_post_envelope",
                            lambda env, **kw: seen.setdefault("env", env)
                            or {"ts": 1.0})
        monkeypatch.setattr(bridge_cli, "_mark_processed",
                            lambda tid: seen.setdefault("marked", tid))
        rc = bridge_cli.main([
            "post-result", "task-abc", "--source", "gamepc",
            "--summary", "ok",
        ])
        assert rc == 0
        assert seen["env"]["target"] == "legion"
        assert seen["env"]["in_reply_to"] == "task-abc"
        assert seen["marked"] == "task-abc"

    def test_no_mark_skips_processed_write(self, monkeypatch):
        marked = []
        monkeypatch.setattr(bridge_cli, "_post_envelope",
                            lambda env, **kw: {"ts": 1.0})
        monkeypatch.setattr(bridge_cli, "_mark_processed",
                            lambda tid: marked.append(tid))
        rc = bridge_cli.main([
            "post-result", "task-no-mark", "--source", "gamepc",
            "--summary", "ok", "--no-mark",
        ])
        assert rc == 0
        assert marked == []

    def test_suggestions_array_in_body(self, monkeypatch):
        seen: dict = {}
        monkeypatch.setattr(bridge_cli, "_post_envelope",
                            lambda env, **kw: seen.setdefault("env", env)
                            or {"ts": 1.0})
        monkeypatch.setattr(bridge_cli, "_mark_processed", lambda tid: None)
        rc = bridge_cli.main([
            "post-result", "task-x", "--source", "gamepc",
            "--summary", "fail",
            "--suggestions", "check API key",
            "--suggestions", "verify peer reachable",
        ])
        assert rc == 0
        assert seen["env"]["body"]["suggestions"] == [
            "check API key", "verify peer reachable",
        ]

    def test_exit_code_in_body(self, monkeypatch):
        seen: dict = {}
        monkeypatch.setattr(bridge_cli, "_post_envelope",
                            lambda env, **kw: seen.setdefault("env", env)
                            or {"ts": 1.0})
        monkeypatch.setattr(bridge_cli, "_mark_processed", lambda tid: None)
        rc = bridge_cli.main([
            "post-result", "task-x", "--source", "gamepc",
            "--summary", "ok", "--exit-code", "3",
        ])
        assert rc == 0
        assert seen["env"]["body"]["exit_code"] == 3

    def test_from_stdin_captures_stdout_field(self, monkeypatch):
        seen: dict = {}
        monkeypatch.setattr(bridge_cli, "_post_envelope",
                            lambda env, **kw: seen.setdefault("env", env)
                            or {"ts": 1.0})
        monkeypatch.setattr(bridge_cli, "_mark_processed", lambda tid: None)
        monkeypatch.setattr(sys, "stdin",
                            io.StringIO("captured stream output\n"))
        rc = bridge_cli.main([
            "post-result", "task-x", "--source", "gamepc",
            "--summary", "ok", "--from-stdin",
        ])
        assert rc == 0
        assert seen["env"]["body"]["stdout"] == "captured stream output\n"

    def test_reply_to_atx_routes_via_core_bridge_send(self, monkeypatch):
        called: dict = {}

        def fake_send(**kw):
            called.update(kw)
            return (True, "ok")

        # core.bridge module — bridge_cli imports it lazily in cmd_post_result.
        import core.bridge as core_bridge
        monkeypatch.setattr(core_bridge, "send", fake_send)
        # Don't write the local processed file
        monkeypatch.setattr(bridge_cli, "_mark_processed", lambda tid: None)

        rc = bridge_cli.main([
            "post-result", "task-peer-1", "--source", "legion",
            "--reply-to", "peer", "--summary", "peer route",
        ])
        assert rc == 0
        assert called["target"] == "peer"
        assert called["kind"] == "result"
        assert called["in_reply_to"] == "task-peer-1"
        assert called["source"] == "legion"

    def test_reply_to_atx_failure_returns_1(self, monkeypatch, capsys):
        import core.bridge as core_bridge
        monkeypatch.setattr(core_bridge, "send",
                            lambda **kw: (False, "bridge_not_configured"))
        rc = bridge_cli.main([
            "post-result", "task-x", "--source", "legion",
            "--reply-to", "peer", "--summary", "x",
        ])
        assert rc == 1
        assert "bridge.send failed" in capsys.readouterr().err


# ---------- pull subcommand --------------------------------------------


class TestPullSubcommand:
    def _msgs(self, *items):
        # tiny helper: build a list of envelopes from (kind, id, target,
        # in_reply_to, ts) tuples
        out = []
        for k, mid, target, irt, ts in items:
            m = {"kind": k, "id": mid, "target": target, "ts": ts}
            if irt:
                m["in_reply_to"] = irt
            out.append(m)
        return out

    def test_filters_to_target_and_skips_answered(self, monkeypatch, capsys):
        msgs = self._msgs(
            ("task", "t1", "gamepc", None, 100.0),
            ("task", "t2", "gamepc", None, 200.0),
            ("task", "t3", "legion", None, 50.0),       # wrong target
            ("result", "r1", "legion", "t1", 150.0),    # answers t1
        )
        monkeypatch.setattr(bridge_cli, "_fetch_messages",
                            lambda since: {"now": 999.0, "messages": msgs})
        monkeypatch.setattr(bridge_cli, "_read_processed", lambda: set())

        rc = bridge_cli.main(["pull", "--target", "gamepc"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["count"] == 1
        assert out["tasks"][0]["id"] == "t2"

    def test_legion_target_accepts_rc_alias(self, monkeypatch, capsys):
        msgs = self._msgs(
            ("task", "peer-1", "rc",     None, 100.0),
            ("task", "leg-1", "legion", None, 200.0),
            ("task", "gpc-1", "gamepc", None, 300.0),
        )
        monkeypatch.setattr(bridge_cli, "_fetch_messages",
                            lambda since: {"now": 999.0, "messages": msgs})
        monkeypatch.setattr(bridge_cli, "_read_processed", lambda: set())

        rc = bridge_cli.main(["pull", "--target", "legion"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        ids = sorted(t["id"] for t in out["tasks"])
        assert ids == ["peer-1", "leg-1"]   # rc alias accepted, gamepc rejected

    def test_processed_ids_skipped(self, monkeypatch, capsys):
        msgs = self._msgs(
            ("task", "t1", "gamepc", None, 100.0),
            ("task", "t2", "gamepc", None, 200.0),
        )
        monkeypatch.setattr(bridge_cli, "_fetch_messages",
                            lambda since: {"now": 999.0, "messages": msgs})
        monkeypatch.setattr(bridge_cli, "_read_processed", lambda: {"t1"})

        bridge_cli.main(["pull", "--target", "gamepc"])
        out = json.loads(capsys.readouterr().out)
        assert [t["id"] for t in out["tasks"]] == ["t2"]

    def test_tasks_sorted_oldest_first(self, monkeypatch, capsys):
        msgs = self._msgs(
            ("task", "tNEW", "gamepc", None, 999.0),
            ("task", "tOLD", "gamepc", None, 100.0),
            ("task", "tMID", "gamepc", None, 500.0),
        )
        monkeypatch.setattr(bridge_cli, "_fetch_messages",
                            lambda since: {"now": 9999.0, "messages": msgs})
        monkeypatch.setattr(bridge_cli, "_read_processed", lambda: set())

        bridge_cli.main(["pull", "--target", "gamepc"])
        out = json.loads(capsys.readouterr().out)
        assert [t["id"] for t in out["tasks"]] == ["tOLD", "tMID", "tNEW"]

    def test_fetch_error_returns_0_with_empty_tasks(self, monkeypatch, capsys):
        def boom(since):
            raise OSError("net down")
        monkeypatch.setattr(bridge_cli, "_fetch_messages", boom)
        rc = bridge_cli.main(["pull", "--target", "gamepc"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["tasks"] == []
        assert "error" in out


# ---------- fetch / heartbeat / post (Stop hook) -----------------------


class TestFetchSubcommand:
    def test_writes_last_seen_even_on_empty_window(self, monkeypatch, tmp_path):
        last_seen = tmp_path / "last_seen.txt"
        monkeypatch.setattr(bridge_cli, "LAST_SEEN_FILE", str(last_seen))

        # Stub urlopen so we don't hit the network
        class FakeResp:
            def __init__(self, body): self._body = body
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return self._body

        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *a, **kw: FakeResp(json.dumps(
                {"now": 12345.0, "messages": []}).encode()),
        )
        rc = bridge_cli.main(["fetch"])
        assert rc == 0
        assert last_seen.exists()
        assert float(last_seen.read_text()) == 12345.0

    def test_filters_self_authored_messages(self, monkeypatch, tmp_path,
                                             capsys):
        monkeypatch.setattr(bridge_cli, "LAST_SEEN_FILE",
                            str(tmp_path / "ls.txt"))

        class FakeResp:
            def __init__(self, body): self._body = body
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return self._body

        msgs = [
            {"ts": 1.0, "source": "legion",  "summary": "self only"},
            {"ts": 2.0, "source": "peer",     "summary": "from peer A"},
            {"ts": 3.0, "source": "Legion",  "summary": "case-insensitive"},
        ]
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda *a, **kw: FakeResp(json.dumps(
                {"now": 99.0, "messages": msgs}).encode()),
        )
        bridge_cli.main(["fetch"])
        out = capsys.readouterr().out
        assert "from peer A" in out
        assert "self only" not in out
        assert "case-insensitive" not in out

    def test_unreachable_bridge_silent_exit_0(self, monkeypatch, tmp_path):
        monkeypatch.setattr(bridge_cli, "LAST_SEEN_FILE",
                            str(tmp_path / "ls.txt"))

        def boom(*a, **kw):
            raise OSError("legion offline")
        monkeypatch.setattr("urllib.request.urlopen", boom)
        rc = bridge_cli.main(["fetch"])
        assert rc == 0


class TestPostHookSubcommand:
    def test_extracts_last_assistant_text(self, monkeypatch, tmp_path):
        # Build a fake transcript JSONL with one assistant message
        transcript = tmp_path / "tx.jsonl"
        rows = [
            {"role": "user",      "content": "hi"},
            {"role": "assistant", "content": "hello world from claude"},
        ]
        transcript.write_text("\n".join(json.dumps(r) for r in rows))

        posted: dict = {}
        monkeypatch.setattr(bridge_cli, "_post_simple",
                            lambda payload, **kw: posted.update(payload)
                            or {"ts": 1.0})
        monkeypatch.setattr(sys, "stdin", io.StringIO(
            json.dumps({"transcript_path": str(transcript)})))

        rc = bridge_cli.main(["post", "legion"])
        assert rc == 0
        assert posted["source"] == "legion"
        assert "hello world from claude" in posted["summary"]

    def test_empty_stdin_silent_exit_0(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        rc = bridge_cli.main(["post", "legion"])
        assert rc == 0

    def test_missing_transcript_path_silent(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
        rc = bridge_cli.main(["post", "legion"])
        assert rc == 0


class TestHeartbeatOnce:
    def test_once_succeeds_on_post(self, monkeypatch):
        calls: list = []

        def fake_urlopen(req, *a, **kw):
            class R:
                def __enter__(self): return self
                def __exit__(self, *a): return False
                def read(self): return b'{"ts": 1.0}'
            calls.append(1)
            return R()

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        rc = bridge_cli.main(["heartbeat", "--once"])
        assert rc == 0
        assert len(calls) == 1

    def test_once_returns_1_on_failure(self, monkeypatch):
        def boom(*a, **kw):
            raise OSError("legion offline")
        monkeypatch.setattr("urllib.request.urlopen", boom)
        rc = bridge_cli.main(["heartbeat", "--once"])
        assert rc == 1


# ---------- BridgeMetrics --------------------------------------------


class TestBridgeMetrics:
    def test_namespace_exists_and_renders(self):
        from core.prom_metrics import BridgeMetrics, render_all
        # Class-level metrics must be registered (Counter ctor side effect)
        BridgeMetrics.posts_total.inc(kind="test", target="unit")
        body = render_all()
        assert "rc_bridge_posts_total" in body
        assert "rc_bridge_fetches_total" in body
        assert "rc_bridge_pulls_total" in body
        assert "rc_bridge_pull_pending" in body

    def test_post_increments_metric(self, monkeypatch):
        from core.prom_metrics import BridgeMetrics
        before = BridgeMetrics.posts_total._values.copy()

        monkeypatch.setattr(bridge_cli, "_mark_processed", lambda tid: None)
        # Only a post-success should increment
        monkeypatch.setattr("urllib.request.urlopen",
                            self._fake_urlopen_returning({"ts": 1.0}))

        rc = bridge_cli.main([
            "post-result", "task-metric", "--source", "gamepc",
            "--summary", "ok",
        ])
        assert rc == 0
        after = BridgeMetrics.posts_total._values
        # at least one new (kind, target) pair should be present or count up
        assert after != before

    @staticmethod
    def _fake_urlopen_returning(json_payload):
        class R:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return json.dumps(json_payload).encode()
        return lambda *a, **kw: R()


# ---------- Shim dispatch (subprocess smoke) ---------------------------


SHIMS = [
    ("bridge_task.py",          "task"),
    ("bridge_post_result.py",   "post-result"),
    ("bridge_pull_tasks.py",    "pull"),
    ("bridge_fetch.py",         "fetch"),
    ("bridge_ping.py",          "ping"),
    ("bridge_heartbeat.py",     "heartbeat"),
    ("bridge_post.py",          "post"),
]


@pytest.mark.parametrize("shim,subcmd", SHIMS)
def test_shim_help_dispatches_to_correct_subcommand(shim, subcmd):
    """Each shim's --help should mention the subcommand name in the usage line."""
    p = subprocess.run(
        [PYTHON, str(TOOLS / shim), "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert p.returncode == 0, f"{shim} --help exited {p.returncode}: {p.stderr}"
    assert f"bridge_cli {subcmd}" in p.stdout, (
        f"{shim} should dispatch to {subcmd}; help output:\n{p.stdout}"
    )


def test_shim_files_are_thin():
    """No shim should exceed ~30 LOC — they're meant to be one-liners."""
    for shim, _ in SHIMS:
        loc = sum(1 for line in (TOOLS / shim).read_text().splitlines()
                  if line.strip() and not line.strip().startswith("#"))
        assert loc < 30, f"{shim} is too fat ({loc} non-comment LOC)"
