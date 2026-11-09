# arch: :8888 HTTPS dashboard server entry | section=dashboard | frozen=no
"""web_dashboard.py - entry shim for the :8888 HTTPS dashboard.

main.py imports this module at boot and calls ``start_dashboard(APP_DIR)``
inside one ``try/except``; ANY exception raised while this module imports
means the whole dashboard never starts (one warning line in the log). The
real code lives in the ``dashboard/`` package; this file only:

- re-exports the historical underscored names (``_build_state``,
  ``_Handler``, ``_set_pregame``, ...) so in-process callers that still do
  ``from web_dashboard import X`` keep working. Each is the source object
  itself, not a copy.
- resolves ``_VISION_TOKEN`` (the :8889 vision-server bearer token) through
  ``core.vision_token``, the canonical source. ``dashboard/routes_diag.py``,
  ``routes_loadout.py`` and ``routes_sr_draft.py`` import it from here
  inside their handlers.
- starts the hot-reload watcher (``core/hot_reload.py``) as an import-time
  side effect. See ``_start_hot_reload_watcher`` for the failure contract.

What the dashboard is (measured 2026-11-09, s144 true-audit; the old header
named a tablet display, a 500 ms overlay-matching poll, a scrape-only server
and an unauthenticated LAN surface, all false at HEAD):
``dashboard.server.start_dashboard`` serves HTTPS and plain HTTP on one port
from a daemon thread named "WebDashboard", bound per ``bind_host()``. It is NOT read-only - POST routes write the pregame file,
request a vision scan and forward LCU commands - and control POSTs are gated
by the peer gate plus the ``RC_DASH_TOKEN`` header check in
``dashboard/_handler.py``.
"""

import logging
import threading
from pathlib import Path

# AUDIT (2026-04-22): the vision bearer token is routed through
# core.vision_token for rotation support (env var, then config file).
# Lane 8 cycle 14: a private copy of the retired legacy constant survived here
# in an ImportError branch; it no longer matched the rotated token, so it could
# only 401 - silently. Resolve through the canonical source only.
# Resolved ONCE at import: a token rotation reaches the handlers above only
# through the restart the rotation procedure already requires
# (core/vision_token.py, "Rotation procedure", step 4).
from core.vision_token import get_vision_token as _get_vision_token

_VISION_TOKEN = _get_vision_token()

_APP_DIR: Path = Path(__file__).parent

_log = logging.getLogger("rc.web_dashboard")

# The name core.hot_reload.start_watcher gives its thread (pinned against the
# source by tests/test_web_dashboard_true_audit_s144.py).
_HOT_RELOAD_THREAD_NAME = "hot-reload-watcher"


def _start_hot_reload_watcher(app_dir: Path) -> bool:
    """Start the hot-reload watcher once per process. Never aborts the import.

    The watcher writes restart_trigger.txt when a non-frozen .py file RC has
    loaded changes (halt: ops/runtime/hot_reload_halt.txt). It is a dev
    convenience, so its failures must not cost the dashboard (s144
    true-audit; the old block caught ImportError only, and silently):

    - ``core.hot_reload`` missing: one warning, no watcher.
    - ``start_watcher`` raising OSError (the ``ops/runtime`` mkdir) or
      RuntimeError (the thread cannot start): one warning, no watcher.
      Anything else is a programming error and still raises.
    - a live thread already carrying the watcher's name: reused, so a second
      execution of this module (a re-import after a failed import) cannot
      put two watchers on one tree.

    ``start_watcher`` is looked up at call time, so the test suite's no-op
    stand-in (tests/conftest.py) still applies.

    Returns True when a watcher was started or one was already running.
    """
    # threading.enumerate() lists live threads only, so a watcher that has
    # exited (halt file) never blocks a fresh start.
    if any(t.name == _HOT_RELOAD_THREAD_NAME for t in threading.enumerate()):
        return True
    try:
        from core.hot_reload import start_watcher
    except ImportError as exc:
        _log.warning("hot-reload watcher unavailable (%s: %s); edits will "
                     "not auto-restart RC", type(exc).__name__, exc)
        return False
    try:
        start_watcher(app_dir)
    except (OSError, RuntimeError) as exc:
        _log.warning("hot-reload watcher failed to start (%s: %s); the "
                     "dashboard continues without it",
                     type(exc).__name__, exc)
        return False
    return True


# Started BEFORE the dashboard imports below on purpose: when one of them
# fails (a missing name in a module that did load), the watcher is already
# running, so the edit that fixes that module restarts RC and the dashboard
# comes back without a manual restart.
_start_hot_reload_watcher(_APP_DIR)

# 2026-05-01 (slice 2B): pure-builder helpers and their shared read-only
# sqlite cache live under `dashboard/`.
from dashboard._context import (  # noqa: E402
    DB_CONN_LOCAL as _DB_CONN_LOCAL,
    read_json as _read_json,
    ro_conn as _ro_conn,
)
from dashboard.builders import (  # noqa: E402
    SESSION_GAP_S,
    _agg_session,
    _build_diagnostics,
    _group_sessions,
    _home_streaks,
    _home_tonight_pick,
    _home_trends_14d,
    _load_match_rows,
    _ts_to_epoch,
)

# 2026-05-01 (slice 2C): static-asset helpers and the legacy_index / manifest
# / icon byte loaders.
from dashboard._static import (  # noqa: E402
    compute_asset_hash as _compute_asset_hash,
    icon_svg_bytes as _icon_svg_bytes,
    inject_asset_hash as _inject_asset_hash,
    legacy_index_html as _legacy_index_html,
    manifest_bytes as _manifest_bytes,
    resolve_safe_icon as _resolve_safe_icon,
)

# Tier 2 helper-shake (2026-05-01): the Haiku-backed champ-select brief
# generator and its 10-minute LRU cache.
from dashboard._champ_select import (  # noqa: E402, F401
    brief_via_coach as _champ_select_brief_via_coach,
)

# Tier 2 helper-shake (2026-05-01): the diagnostics cache.
from dashboard._diagnostics import (  # noqa: E402, F401
    _DIAG_CACHE,
    _DIAG_LOCK,
    _DIAG_TTL_S,
    diagnostics_cached as _diagnostics_cached,
)

# Tier 2 helper-shake (2026-05-01): the atomic JSON writers.
from dashboard._writers import (  # noqa: E402, F401
    atomic_write_json as _atomic_write_json,
    force_vision_scan as _force_vision_scan,
    set_pregame as _set_pregame,
)

# Tier 2 helper-shake (2026-05-01): the LCU and Live Client summary helpers.
from dashboard._liveclient import (  # noqa: E402, F401
    lcu_summary as _lcu_summary,
    liveclient_summary as _liveclient_summary,
)

# Tier 2 helper-shake (2026-05-01): the state-shape builder and MODE_TO_FILE.
from dashboard._state_builder import (  # noqa: E402, F401
    MODE_TO_FILE as _MODE_TO_FILE,
    build_state as _build_state,
)

# Tier 2 helper-shake (2026-05-01): the BaseHTTPRequestHandler subclass and
# the supervisor-proxy constants.
from dashboard._handler import (  # noqa: E402, F401
    Handler as _Handler,
    SUPERVISOR_ORIGIN as _SUPERVISOR_ORIGIN,
    SUPERVISOR_PROXY_PATHS as _SUPERVISOR_PROXY_PATHS,
)

# Slice 2D (2026-05-01): _DualProtocolHTTPServer and start_dashboard live in
# dashboard/server.py; main.py does `from web_dashboard import start_dashboard`.
from dashboard.server import (  # noqa: E402, F401
    _DualProtocolHTTPServer,
    start_dashboard,
)
