"""RM-1116 (c): tools/lcu_agent.py keeps its ingest state under the repo root.

`INGEST_STATE_FILE` (the persisted `last_game_id_ingested`, read once at agent
boot by `_load_ingest_state`) defaulted to the retired copy-out folder of
tools/legion_agent_boot.ps1, outside the repo root (CLAUDE.md "Keep runtime
records under the repo root"). The RC-LCUAgent ONLOGON task does not set
`RC_AGENT_STATE_FILE`, so the live agent wrote there. The default is now
`<repo>/ops/runtime/agent_state.json` (gitignored); the override still wins.

The old file is read ONCE, only when the default is in use and the new file is
absent, and the restored value is re-saved to the new location so the next
boot reads it from there. An override never falls back to the old file.

tests/_fleet_guard_config.py points `RC_AGENT_STATE_FILE` at tmp_path for the
whole suite, so every case here builds its paths under tmp_path and never
reads or writes a real state file. ASCII only.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import tools.lcu_agent as agent

_REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _fresh_ingest_state(monkeypatch):
    monkeypatch.setitem(agent._post_match_ingest_state, "last_game_id_ingested", None)


def test_default_resolves_under_repo_root_with_override_unset(monkeypatch):
    monkeypatch.delenv("RC_AGENT_STATE_FILE", raising=False)
    path = agent._resolve_ingest_state_file()
    assert path == _REPO_ROOT / "ops" / "runtime" / "agent_state.json"
    assert path.resolve().is_relative_to(_REPO_ROOT.resolve())
    assert path == agent._DEFAULT_INGEST_STATE_FILE


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_override_falls_back_to_the_default(monkeypatch, blank):
    # The old os.environ.get(name, default) turned "" into Path(""), i.e. the
    # agent's current folder.
    monkeypatch.setenv("RC_AGENT_STATE_FILE", blank)
    assert agent._resolve_ingest_state_file() == agent._DEFAULT_INGEST_STATE_FILE


def test_override_wins(monkeypatch, tmp_path):
    target = tmp_path / "elsewhere" / "state.json"
    monkeypatch.setenv("RC_AGENT_STATE_FILE", str(target))
    assert agent._resolve_ingest_state_file() == target


def test_import_time_constant_comes_from_the_resolver():
    # Read from source: the module is imported at collection time, before the
    # suite guard sets the per-test override, so comparing the live constant
    # with a fresh resolve would compare two different environments.
    src = Path(agent.__file__).read_text(encoding="utf-8")
    assert "\nINGEST_STATE_FILE = _resolve_ingest_state_file()\n" in src
    assert src.count("\nINGEST_STATE_FILE = ") == 1


def _point(monkeypatch, tmp_path, *, overridden: bool = False):
    new = tmp_path / "repo" / "ops" / "runtime" / "agent_state.json"
    legacy = tmp_path / "copy-out" / "agent_state.json"
    monkeypatch.setattr(agent, "_DEFAULT_INGEST_STATE_FILE", new)
    monkeypatch.setattr(agent, "_LEGACY_INGEST_STATE_FILE", legacy)
    active = tmp_path / "override.json" if overridden else new
    monkeypatch.setattr(agent, "INGEST_STATE_FILE", active)
    return new, legacy, active


def _write(path: Path, gid) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps({"last_game_id_ingested": gid}).encode("ascii"))


def test_legacy_file_is_read_once_and_migrated(monkeypatch, tmp_path):
    new, legacy, _ = _point(monkeypatch, tmp_path)
    _write(legacy, 1000000501)
    agent._load_ingest_state()
    assert agent._post_match_ingest_state["last_game_id_ingested"] == 1000000501
    assert json.loads(new.read_text(encoding="utf-8"))["last_game_id_ingested"] == 1000000501
    # The old file is left in place (it is outside the repo root; never ours to delete).
    assert legacy.is_file()


def test_new_file_wins_over_legacy(monkeypatch, tmp_path):
    new, legacy, _ = _point(monkeypatch, tmp_path)
    _write(new, 1000000502)
    _write(legacy, 1000000401)
    agent._load_ingest_state()
    assert agent._post_match_ingest_state["last_game_id_ingested"] == 1000000502


def test_override_never_reads_the_legacy_file(monkeypatch, tmp_path):
    new, legacy, active = _point(monkeypatch, tmp_path, overridden=True)
    _write(legacy, 1000000401)
    agent._load_ingest_state()
    assert agent._post_match_ingest_state["last_game_id_ingested"] is None
    assert not active.exists()
    assert not new.exists()


def test_no_file_anywhere_stays_fresh(monkeypatch, tmp_path):
    new, _, _ = _point(monkeypatch, tmp_path)
    agent._load_ingest_state()
    assert agent._post_match_ingest_state["last_game_id_ingested"] is None
    assert not new.exists()


def test_save_writes_the_active_path(monkeypatch, tmp_path):
    new, legacy, _ = _point(monkeypatch, tmp_path)
    monkeypatch.setitem(agent._post_match_ingest_state, "last_game_id_ingested", 1000000503)
    agent._save_ingest_state()
    assert json.loads(new.read_text(encoding="utf-8"))["last_game_id_ingested"] == 1000000503
    assert not legacy.exists()
