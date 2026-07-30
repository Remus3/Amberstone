"""Regression guard: RC's Anthropic clients pin base_url to the direct API.

RC coaching authenticates with the Console API key (API-Key-Claude.txt). A
user-wide ANTHROPIC_BASE_URL - set so the Claude subscription GUI/CLI routes
through the teamclaude failover proxy on :3456 (docs/OPERATIONS.md) - must NOT
redirect RC's own coaching traffic. Doing so would send an API-key request to a
subscription-OAuth proxy (broken auth) or burn the subscription weekly quota.
So every production anthropic.Anthropic(...) construction pins
base_url="https://api.anthropic.com" and ignores the env var.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DIRECT = "https://api.anthropic.com"

# Every production module that constructs an Anthropic client. Tests are
# excluded (they monkeypatch the anthropic module). Keep in sync with
# test_construction_files_list_is_exhaustive below.
CONSTRUCT_FILES = [
    "modes/shared_vision.py",
    "coach_integration/_coach.py",
    "coaches/_base_coach.py",
    "vision_server/_config.py",
    "coaches/replay_coach.py",
    "coaches/experimental_builder.py",
    "coaches/champ_select_coach.py",
    "coaches/brawl_coach.py",
    "coaches/arena_coach.py",
    "coaches/aram_team_analyzer.py",
    "coaches/aram_coach.py",
    "core/anthropic_client.py",
    "agents/agent7_context/warm_session.py",
    "tft/tft_coach_engine.py",
    "tft/tft_live_analysis.py",
    "tft/tft_pbe_engine.py",
    "tft/tft_vision_reader.py",
]

# Per-line pin check: an actual construction is `= anthropic.Anthropic(`.
# The `=` prefix skips the docstring mention in core/anthropic_client.py.
_CTOR_LINE = re.compile(r"=\s*anthropic\.Anthropic\s*\(")
# File-level scan (bare) for the exhaustiveness guard.
_CTOR_FILE = re.compile(r"anthropic\.Anthropic\s*\(")
_SKIP_DIRS = {"tests", "docs", "Share", "_archive", ".git", "node_modules"}


def test_no_unpinned_anthropic_construction():
    offenders = []
    for rel in CONSTRUCT_FILES:
        p = REPO / rel
        assert p.exists(), f"{rel} missing - update CONSTRUCT_FILES"
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if _CTOR_LINE.search(line) and "base_url" not in line:
                offenders.append(f"{rel}:{i}: {line.strip()}")
    assert not offenders, "unpinned Anthropic() construction:\n" + "\n".join(offenders)


def test_construction_files_list_is_exhaustive():
    known = {(REPO / f).resolve() for f in CONSTRUCT_FILES}
    found = set()
    for p in REPO.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        try:
            txt = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if _CTOR_FILE.search(txt):
            found.add(p.resolve())
    new = found - known
    assert not new, (
        "new Anthropic() site(s) outside CONSTRUCT_FILES - pin base_url and add "
        "here:\n" + "\n".join(str(x) for x in sorted(new))
    )


def test_tracked_anthropic_ignores_env_base_url(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://localhost:3456")
    pytest.importorskip("anthropic")
    from core.anthropic_client import tracked_anthropic

    client = tracked_anthropic("sk-ant-test-dummy", purpose="test")
    assert str(client.base_url).rstrip("/") == DIRECT
