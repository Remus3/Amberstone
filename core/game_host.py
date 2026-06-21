# arch: local game-host config | section=core
"""
core/game_host.py - single source of truth for the host running League.

RC_GAME_HOST is where League's Live Client API (:2999) and the LCU lockfile-
based API are reachable. After the 1-PC consolidation (2026-05) League runs on
Legion itself, so the default is 127.0.0.1 (the game host is Legion-local).
Set the RC_GAME_HOST env var to override if the game ever runs on a different
host.
"""
import os

GAME_HOST = os.environ.get("RC_GAME_HOST", "127.0.0.1")
