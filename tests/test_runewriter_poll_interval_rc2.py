"""RC2 P6.2 - champ-select rune/spell auto-apply responsiveness floor.

RuneWriter.POLL_INTERVAL governs how fast RC reacts to a hover/lock across
ALL modes (lcu/lcu_rune_writer.py). The IO timing map (docs/_archive/2026-07-28-research-consolidation/
RC2_RESEARCH_io_timing_map.md) found 2.0s was the slowest champ-select cadence;
RC2 tightened it to 1.0s (port-safe: one loop, +0.5 calls/s on the lockfile
port) and made it env-tunable. Guard the responsiveness floor against
regression and verify the RC_RUNEWRITER_POLL_SEC override.
"""
import importlib

import lcu.lcu_rune_writer as rw


def test_poll_interval_responsiveness_floor():
    # Champ-select auto-apply must not regress slower than 1.0s.
    assert 0 < rw.RuneWriter.POLL_INTERVAL <= 1.0


def test_poll_interval_env_override(monkeypatch):
    monkeypatch.setenv("RC_RUNEWRITER_POLL_SEC", "0.75")
    mod = importlib.reload(rw)
    try:
        assert mod.RuneWriter.POLL_INTERVAL == 0.75
    finally:
        monkeypatch.delenv("RC_RUNEWRITER_POLL_SEC", raising=False)
        importlib.reload(mod)
