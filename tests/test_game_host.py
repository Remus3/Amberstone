"""Regression guard for the 1-PC game-host config (core/game_host.py).

After the 2026-05 Game-PC -> Legion consolidation, every live reader of the
Live Client API (:2999) and the LCU lockfile API must resolve the host via
core.game_host.GAME_HOST (default 127.0.0.1), NOT a hardcoded Game-PC LAN IP.
"""
import importlib
import os
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_GAMEPC_IP = "192.168.8.237"

# Live-path modules that must never hardcode the Game-PC IP again.
_GUARDED = [
    "game_reader/poller.py",
    "game_reader/__init__.py",
    "coaches/_base_coach.py",
    "lcu/lcu_client.py",
    "lcu/lcu_pregame.py",
    "lcu/lcu_postgame_collector.py",
    "dashboard/builders.py",
    "dashboard/routes_diag.py",
    "tft/tft_state_reader.py",
]


def test_default_host_is_localhost():
    import core.game_host as gh
    importlib.reload(gh)
    assert gh.GAME_HOST == "127.0.0.1"


def test_env_override():
    prev = os.environ.get("RC_GAME_HOST")
    os.environ["RC_GAME_HOST"] = "10.1.2.3"
    try:
        import core.game_host as gh
        importlib.reload(gh)
        assert gh.GAME_HOST == "10.1.2.3"
    finally:
        if prev is None:
            os.environ.pop("RC_GAME_HOST", None)
        else:
            os.environ["RC_GAME_HOST"] = prev
        import core.game_host as gh
        importlib.reload(gh)


def test_no_hardcoded_gamepc_ip_in_live_readers():
    offenders = []
    for rel in _GUARDED:
        text = (_ROOT / rel).read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if _GAMEPC_IP in line:
                offenders.append(f"{rel}:{i}: {line.strip()}")
    assert not offenders, "hardcoded Game-PC IP in live readers:\n" + "\n".join(offenders)


def test_ascii_only():
    # Only files authored by this slice; pre-existing modules carry operator-
    # gated non-ASCII (U+2192 arrows) swept separately.
    for rel in ["core/game_host.py", "tests/test_game_host.py"]:
        raw = (_ROOT / rel).read_bytes()
        bad = [b for b in raw if b > 0x7F]
        assert not bad, f"{rel} has {len(bad)} non-ASCII bytes"
