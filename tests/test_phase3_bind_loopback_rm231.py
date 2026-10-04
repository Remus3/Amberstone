"""RM-231: the Phase 3 supervisor's :8890 / :8891 bind defaults to loopback.

It hardcoded `0.0.0.0`, so both ports were LAN- and tailnet-reachable. The
client set was enumerated before the flip (every in-repo client reaches them
on 127.0.0.1; see `agents/_supervisor_common._env_bind_host`). This pins the
chosen bind so it cannot drift back, and pins the deliberate escape hatch.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agents import _supervisor_common as common

ROOT = Path(__file__).resolve().parent.parent


def test_default_bind_is_loopback():
    assert common._env_bind_host("RC_TEST_UNSET_BIND_RM231") == "127.0.0.1"


@pytest.mark.parametrize("raw,expected", [
    ("0.0.0.0", "0.0.0.0"),
    ("100.70.22.55", "100.70.22.55"),
    ("  127.0.0.1 ", "127.0.0.1"),
    ("legion-rc", "127.0.0.1"),      # hostnames are refused, not resolved
    ("0.0.0.0; rm", "127.0.0.1"),
    ("", "127.0.0.1"),
])
def test_override_accepts_only_ip_literals(monkeypatch, raw, expected):
    monkeypatch.setenv("RC_TEST_BIND_RM231", raw)
    assert common._env_bind_host("RC_TEST_BIND_RM231") == expected


def test_module_constant_resolves_to_loopback_without_override():
    env = {k: v for k, v in os.environ.items() if k != "RC_PHASE3_BIND_HOST"}
    out = subprocess.run(
        [sys.executable, "-c",
         "from agents._supervisor_common import BIND_HOST; print(BIND_HOST)"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert out.returncode == 0, out.stderr[-500:]
    assert out.stdout.strip() == "127.0.0.1"


@pytest.mark.parametrize("rel", [
    "agents/_supervisor_http.py",
    "agents/supervisor.py",
    "agents/agent2_backend/ws_server.py",
])
def test_no_wildcard_bind_literal_in_code(rel):
    """No string constant "0.0.0.0" in executable code (docstrings and
    comments may still record the history)."""
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    doc_nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)):
                doc_nodes.add(id(body[0].value))
    hits = [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and n.value == "0.0.0.0"
            and id(n) not in doc_nodes]
    assert hits == [], f"{rel}: wildcard bind literal at lines {hits}"


def test_web_server_binds_bind_host(monkeypatch, tmp_path):
    from agents import _supervisor_http as http_mod
    monkeypatch.setattr(http_mod, "WEB_ROOT", tmp_path)
    srv = http_mod.start_web_server(port=0)
    try:
        assert srv.server_address[0] == "127.0.0.1"
    finally:
        srv.shutdown()
        srv.server_close()


def test_ws_server_default_host_is_loopback():
    from agents.agent2_backend import ws_server
    assert ws_server.DEFAULT_HOST == "127.0.0.1"
