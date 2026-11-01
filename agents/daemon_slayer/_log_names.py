"""Every logger name the Daemon Slayer package creates (RM-1280).

A ``core.log_scrub.ScrubFilter`` on one logger sees only that logger's own
records, so the RM-811 backstop has to be attached to each name the engine
logs on. The engine stays core-free: this module is plain data, and the
core-importing packages that run the engine install the filter from it -
``agents/daemon_slayer/server.py`` (:8860), ``dashboard/__init__.py``
(:8888, whose routes call the engine in-process) and
``coach_integration/__init__.py`` (the RC main process backstop when the
dashboard import fails, RM-1282; the install is idempotent).
tests/test_ds_engine_logger_scrub_s144d58.py enumerates the getLogger calls
from source, so a new engine logger fails that guard until it is listed.
"""
from __future__ import annotations

LOGGER_NAMES = (
    "agents.daemon_slayer._ability_base_overrides",
    "agents.daemon_slayer.abilities",
    "agents.daemon_slayer.ability_dps",
    "agents.daemon_slayer.burst",
    "agents.daemon_slayer.cc_conditional",
    "agents.daemon_slayer.combo",
    "agents.daemon_slayer.effects",
    "agents.daemon_slayer.fight_report",
    "agents.daemon_slayer.focus_board",
    "agents.daemon_slayer.mana_sim",
    "agents.daemon_slayer.scenario_matrix",
    "daemon_slayer.server",
    "rc.cli",
)
