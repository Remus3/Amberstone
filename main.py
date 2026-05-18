# arch: RC entry point; starts supervisor + RC process | section=orchestration | frozen=yes
"""
main.py - Riot Commander entry point.

Handles:
- Argument parsing (--debug)
- API key loading from API-Key-Claude.txt
- Logging setup (rotating, 3 MB max)
- ResourceManager for clean exit
- DevRuntime for heartbeat + hot-reload + file-based commands
- Mode detection + coach lazy-loading
- LCU auto-accept
- OverlayApp launch (asyncio scheduler since T2 #8)
"""

import sys
import os
import argparse
from pathlib import Path

# - Resolve app directory
APP_DIR = Path(__file__).parent.resolve()
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

# - Parse arguments
def _parse_args():
    p = argparse.ArgumentParser(prog="Riot Commander", add_help=False)
    p.add_argument("--debug", action="store_true", default=False,
                   help="Enable verbose logging and console output")
    args, _ = p.parse_known_args()
    if os.environ.get("RIOT_COMMANDER_DEBUG") == "1":
        args.debug = True
    return args

args = _parse_args()

# - Logging (must come before any other import that logs)
from core.log_setup import setup as _log_setup, get as _log_get
_log_setup(APP_DIR, debug=args.debug)
_log = _log_get("main")
_log.info("Riot Commander starting  debug=%s  python=%s", args.debug, sys.version.split()[0])

# - API key
def _load_api_key():
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key.startswith("sk-ant-"):
        return key

    key_file = APP_DIR / "API-Key-Claude.txt"
    if key_file.exists():
        key = key_file.read_text(encoding="utf-8").strip()
        if key.startswith("sk-ant-"):
            os.environ["ANTHROPIC_API_KEY"] = key
            _log.info("API key loaded from API-Key-Claude.txt")
            return key

    _log.error("No valid Anthropic API key found. "
               "Edit API-Key-Claude.txt or run install.bat")
    return ""

_load_api_key()

# - Config validation (Phase 1 Step 1)
# Non-fatal: logs results but never aborts startup.
try:
    from core.config_validator import validate_all as _validate_configs
    _validate_configs()
except Exception as _e:
    _log.warning("Config validation skipped (non-fatal): %s", _e)

# - Resource manager
from core.resource_manager import ResourceManager
rm = ResourceManager(APP_DIR)
rm.start_memory_watchdog(interval_s=60.0)

# - DevRuntime (heartbeat + hot-reload + file-based commands)
_dev_runtime = None
try:
    # Item 6: load ops/rc_config.json as the single authoritative source
    _rc_cfg: dict = {}
    _rc_cfg_path = APP_DIR / "ops" / "rc_config.json"
    if _rc_cfg_path.exists():
        try:
            _rc_cfg = __import__('json').loads(_rc_cfg_path.read_text(encoding='utf-8-sig'))
        except Exception as _e:
            _log.warning("Failed to load rc_config.json: %s", _e)

    from ops.rc_dev_runtime import DevRuntime
    _dev_runtime = DevRuntime(
        project_root          = APP_DIR,
        app_name              = "riot-commander",
        runtime_dir           = _rc_cfg.get("runtime_dir", "ops/runtime"),
        heartbeat_interval    = float(_rc_cfg.get("heartbeat_interval_s", 1.0)),
        command_poll_interval = float(_rc_cfg.get("command_poll_interval_s", 0.5)),
        admin_bridge_enabled  = bool(_rc_cfg.get("admin_bridge_enabled", False)),
    )
    _dev_runtime.start()
    _log.info("DevRuntime started (heartbeat + command listener admin=%s)",
              _rc_cfg.get('admin_bridge_enabled', False))
except Exception as e:
    _log.warning("DevRuntime init failed (non-fatal): %s", e)

# - Asyncio scheduler (T2 #8 C4, 2026-05-01)
# Construct the AppLoop singleton early so the module pollers below
# (metrics_cache, liveclient_cache, log_retention, vision_tracker via
# the dashboard, obs_publisher via the dashboard) can spawn_task on it
# instead of starting daemon threads. The loop only starts running when
# `app.run()` calls `loop.run_forever()` near the end of `main()`.
try:
    from app._loop import ensure_loop as _ensure_app_loop
    _ensure_app_loop()
except Exception as _e:
    _log.warning("ensure_loop failed (non-fatal, modules will use thread fallback): %s", _e)

# - Metrics cache (Phase 1 Step 2)
# Background thread reads runtime artifacts every 5s.
# Uses the same runtime_dir authority as DevRuntime: resolved from _rc_cfg,
# relative paths resolved against APP_DIR, absolute paths used as-is.
# Non-fatal: missing files and errors are silently tolerated.
_metrics_cache = None
try:
    from core.metrics_cache import MetricsCache as _MetricsCache
    _raw_rt = _rc_cfg.get("runtime_dir", "ops/runtime")
    _rt_path = Path(_raw_rt)
    if not _rt_path.is_absolute():
        _rt_path = APP_DIR / _rt_path
    _metrics_cache = _MetricsCache(runtime_dir=_rt_path)
    _metrics_cache.start()
    _log.info("MetricsCache started (refresh=5s  runtime_dir=%s)", _rt_path)
except Exception as _e:
    _log.warning("MetricsCache start failed (non-fatal): %s", _e)

# - Live Client snapshot cache (Tier 1 #2, 2026-05-01)
# One shared 0.5s background poll feeds 4 mode coaches + vision_tracker +
# decision_detector. Pre-refactor each consumer hit the relay on its own
# thread (~6-8 polls/sec idle); now ~2/sec total.
try:
    from core.liveclient_cache import start as _lc_start
    _lc_start()
except Exception as _e:
    _log.warning("liveclient_cache start failed (non-fatal): %s", _e)

# - Log retention (Tier 1 #3, 2026-05-01)
# log_setup.py prunes >30d files only at boot; on a long-lived RC the dir
# grew to 191 MB. Hourly sweep deletes >14d *.log* and caps total at 100 MB.
try:
    from core.log_retention import start as _lr_start
    _lr_start(APP_DIR / "logs")
except Exception as _e:
    _log.warning("log_retention start failed (non-fatal): %s", _e)

# - Web dashboard (iPad extended display via Duet to Game-PC)
try:
    from web_dashboard import start_dashboard as _start_dash
    _start_dash(APP_DIR)
except Exception as _e:
    _log.warning("Web dashboard start failed (non-fatal): %s", _e)

# - Bridge monitor (RC mirror of Peer's bridge_monitor sidecar, 2026-05-02)
# Polls dashboard._bridge_log every 2s; auto-pongs `kind=task summary=ping
# target=rc` so Peer can probe RC's half of the channel. State persisted to
# ops/runtime/bridge_monitor_state.json. Spec: docs io RC peer/
# PEER_VIP_BRIDGE_MONITOR_FOR_RC_2026-05-02.md.
try:
    from core.bridge_monitor import start as _start_bridge_monitor
    _start_bridge_monitor()
except Exception as _e:
    _log.warning("bridge_monitor start failed (non-fatal): %s", _e)

# - Coach integration
import coach_integration as _ci
_ci._APP_DIR = APP_DIR

# - Launch overlay
def main():
    _log.info("Starting overlay application")
    try:
        import overlay as _ov

        # Patch OverlayApp to use ResourceManager
        _orig_init = _ov.OverlayApp.__init__

        def _patched_init(self_app, *a, **kw):
            _orig_init(self_app, *a, **kw)
            rm.register(self_app)

        _ov.OverlayApp.__init__ = _patched_init

        # Patch clean quit
        _orig_quit = _ov.OverlayApp._quit

        def _patched_quit(self_app):
            _log.info("OverlayApp._quit - triggering ResourceManager")
            if _dev_runtime:
                _dev_runtime.stop()
            rm.shutdown()
            _orig_quit(self_app)

        _ov.OverlayApp._quit = _patched_quit

        app = _ov.OverlayApp()

        # - Wire DevRuntime state provider + reload callbacks (Items 2, 4, 6)
        if _dev_runtime:
            # Item 4: state provider uses real health pulse values
            _dev_runtime.set_state_provider(app.get_health_state)

            # Item 2: register remediation callbacks
            _dev_runtime.register_reload_callback(
                "restart_game_poll", app.restart_game_poll)
            _dev_runtime.register_reload_callback(
                "rebuild_panel_game_bottom", app.rebuild_panel_game_bottom)
            _dev_runtime.register_reload_callback(
                "rebuild_panel_game_rtop",   app.rebuild_panel_game_rtop)
            _dev_runtime.register_reload_callback(
                "rebuild_panel_game_rbot",   app.rebuild_panel_game_rbot)
            _log.info("DevRuntime: state provider + 4 remediation callbacks registered")

        _log.info("Overlay running")

        # - LCU auto-accept (always starts; self-heals when League opens)
        try:
            from lcu.lcu_client import LcuClient
            _lcu = LcuClient()
            _lcu.connect()  # best-effort; loop retries if not connected yet
            _lcu.start_auto_accept(interval=1.0)
            if _lcu._port:
                _log.info("LCU auto-accept ENABLED (port %s)", _lcu._port)
            else:
                _log.info("LCU auto-accept ARMED (League not open yet - will connect when lockfile appears)")
            # AUDIT-PHASE-2-API-WIRE: pass LcuClient to ClientPanel for rune page display
            try:
                _panel = app.client_windows.get("main")
                if _panel and hasattr(_panel, "set_lcu_client"):
                    _panel.set_lcu_client(_lcu)
                    _log.debug("LCU rune page wired to ClientPanel")
            except Exception as _e:
                _log.debug("LCU panel wiring: %s", _e)
            # RC Rune Writer: auto-applies recommended rune page during champ select
            try:
                from lcu.lcu_rune_writer import RuneWriter as _RuneWriter
                _rune_writer = _RuneWriter(_lcu)
                _rune_writer.start()
                _log.info("RuneWriter started - rune auto-apply active (replaces Overlay App E)")
                # POSTGAME: end-of-game stats collector (isolated - not used for coaching)
                try:
                    from lcu.lcu_postgame_collector import init_collector as _init_pgc
                    _init_pgc(_lcu)
                    _log.info("PostgameCollector: end-of-game stats capture active")
                except Exception as _pgc_e:
                    _log.debug("PostgameCollector init skipped: %s", _pgc_e)
            except Exception as _e:
                _log.warning("RuneWriter init failed: %s", _e)
        except Exception as e:
            _log.debug("LCU init failed: %s", e)

        app.run()

    except Exception:
        import traceback
        tb = traceback.format_exc()
        _log.critical("Overlay crashed:\n%s", tb)
        if _dev_runtime:
            _dev_runtime.write_fatal(tb)
        raise
    finally:
        _log.info("Overlay exited - running final cleanup")
        if _dev_runtime:
            _dev_runtime.stop()
        if _metrics_cache:
            _metrics_cache.stop()
        rm.shutdown()


if __name__ == "__main__":
    main()
