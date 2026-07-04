# arch: :8888 HTTPS dashboard server entry | section=dashboard | frozen=no
"""

web_dashboard.py - Read-only HTTP dashboard for iPad extended display.



Serves a single-page dark-theme dashboard at :8888 designed for an iPad

extended display (1180x820 logical, retina). Polls coaching

artifact JSON files at 500ms cadence - same as the tkinter overlays.



Architecture:

- Daemon thread; embedded in RC main process

- Read-only: scrapes data/*.json + ops/runtime/health.json

- No auth (LAN-only)

- Mode-adaptive: routes data based on health.json.mode

"""

from pathlib import Path



# AUDIT (2026-04-22): vision bearer token routed through core.vision_token

# for rotation support (env / config file / legacy default).

try:

    from core.vision_token import get_vision_token as _get_vision_token

    _VISION_TOKEN = _get_vision_token()

except ImportError:

    _VISION_TOKEN = "8e8f131e212b329438218eca27372dde"



_APP_DIR: Path = Path(__file__).parent



# 2026-05-01 (slice 2B): pure-builder helpers + their shared

# read-only sqlite cache live under `dashboard/`. We re-bind them

# to the original underscored names so route handlers and module-

# level callers (`_diagnostics_cached`, `_build_state`) keep working

# without churn.

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



# 2026-05-01 (slice 2C): static-asset support helpers + the

# legacy_index/manifest/icon byte loaders moved into dashboard/_static.py.

# Re-bind under the original underscored names for any in-process callers.

from dashboard._static import (  # noqa: E402

    compute_asset_hash as _compute_asset_hash,

    icon_svg_bytes as _icon_svg_bytes,

    inject_asset_hash as _inject_asset_hash,

    legacy_index_html as _legacy_index_html,

    manifest_bytes as _manifest_bytes,

    resolve_safe_icon as _resolve_safe_icon,

)



# Tier 2 helper-shake (2026-05-01): the Haiku-backed champ-select brief

# generator (`brief_via_coach`) + its 10-minute LRU cache moved to

# dashboard/_champ_select.py. Re-bind under the original underscored

# name so any in-process caller that still does `from web_dashboard

# import _champ_select_brief_via_coach` keeps working without churn.

from dashboard._champ_select import (  # noqa: E402, F401

    brief_via_coach as _champ_select_brief_via_coach,

)




# Tier 2 helper-shake (2026-05-01): the diagnostics cache moved to

# dashboard/_diagnostics.py. Re-bind under the original underscored

# names so any in-process caller that still does `from web_dashboard

# import _diagnostics_cached` keeps working without churn.

from dashboard._diagnostics import (  # noqa: E402, F401

    _DIAG_CACHE,

    _DIAG_LOCK,

    _DIAG_TTL_S,

    diagnostics_cached as _diagnostics_cached,

)



# Tier 2 helper-shake (2026-05-01): the atomic JSON writers moved to

# dashboard/_writers.py. Re-bind under the original underscored names

# so any in-process caller that still does `from web_dashboard import

# _set_pregame` keeps working without churn.

from dashboard._writers import (  # noqa: E402, F401

    atomic_write_json as _atomic_write_json,

    force_vision_scan as _force_vision_scan,

    set_pregame as _set_pregame,

)



# Tier 2 helper-shake (2026-05-01): the LCU + Live Client summary

# helpers moved to dashboard/_liveclient.py. Re-bind under the original

# underscored names so in-process callers that still do

# `from web_dashboard import _liveclient_summary` keep working.

from dashboard._liveclient import (  # noqa: E402, F401

    lcu_summary as _lcu_summary,

    liveclient_summary as _liveclient_summary,

)



# Tier 2 helper-shake (2026-05-01): the state-shape builder + sim-scenario

# loader + MODE_TO_FILE moved to dashboard/_state_builder.py. Re-bind under

# the original underscored names so any in-process caller that still does

# `from web_dashboard import _build_state` keeps working without churn.

from dashboard._state_builder import (  # noqa: E402, F401

    MODE_TO_FILE as _MODE_TO_FILE,

    build_state as _build_state,

)





# Tier 2 helper-shake (2026-05-01): the BaseHTTPRequestHandler subclass

# (`Handler`) and the supervisor-proxy constants moved to

# dashboard/_handler.py. Re-bind under the original underscored names so

# any in-process caller that still does `from web_dashboard import

# _Handler` keeps working without churn.

from dashboard._handler import (  # noqa: E402, F401

    Handler as _Handler,

    SUPERVISOR_ORIGIN as _SUPERVISOR_ORIGIN,

    SUPERVISOR_PROXY_PATHS as _SUPERVISOR_PROXY_PATHS,

)





# Slice 2D (2026-05-01): _DualProtocolHTTPServer + start_dashboard live

# in dashboard/server.py. Re-export here so `from web_dashboard import

# start_dashboard` (main.py) keeps working without churn.

from dashboard.server import (  # noqa: E402, F401

    _DualProtocolHTTPServer,

    start_dashboard,

)

