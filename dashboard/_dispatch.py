# arch: route registration | section=dashboard | frozen=no
"""Route dispatcher for the dashboard HTTP server.

Slice 2C (2026-05-01): replaces the giant `if/elif self.path == ...`
chain in web_dashboard._Handler.do_GET / do_POST. Each routes_*
module exposes:

  GET_ROUTES  : list[tuple[matcher, handler]]    handler(h)
  POST_ROUTES : list[tuple[matcher, handler]]    handler(h, body)

`matcher` is `(path: str) -> bool`. `handler` is called with the
BaseHTTPRequestHandler (so it can use `self._send` etc.) and, for
POST, the parsed JSON body (already validated upstream for size).

Routes are tried in registration order; first match wins. Unmatched
falls back to the legacy elif chains in web_dashboard while the
migration is in progress.

Phase 4.1 (s143): POST bodies for paths in _REQUEST_MODELS are
soft-validated against dashboard.api_schema before dispatch - warnings
only, never reject. Mirrors the soft-warn pattern from
core.coaching_payload (Phase 4.3).
"""
import logging
from http.server import BaseHTTPRequestHandler
from typing import Callable

from pydantic import ValidationError

from dashboard.api_schema import (
    BridgeInboxRequest,
    BuildOrderRequest,
    CommandRequest,
    DsPreviewRequest,
    InputRequest,
    SpeakRequest,
    TeamContextRefreshRequest,
)

log = logging.getLogger("rc.dispatch")

# -- matcher factories ------------------------------------------------

def equals(path: str) -> Callable[[str], bool]:
    """Match exactly `path`, or `path?...` (path with a query string)."""
    return lambda p: p == path or p.startswith(path + "?")


def prefix(p: str) -> Callable[[str], bool]:
    """Match anything starting with prefix `p`."""
    return lambda x: x.startswith(p)


# -- registry (cached so each request doesn't rebuild the list) -------

_GET_CACHE: list | None = None
_POST_CACHE: list | None = None


def _gather_get() -> list:
    global _GET_CACHE
    if _GET_CACHE is None:
        from dashboard import (routes_static, routes_state, routes_history,
                               routes_diag, routes_coach, routes_bridge,
                               routes_ban_suggest,
                               routes_bridge_pending, routes_bridge_cadence,
                               routes_cc_blended_ehp_threat,
                               routes_cc_conditional_pressure,
                               routes_cc_pairing,
                               routes_peel_priority,
                               routes_cooldown_watch,
                               routes_ds_combo, routes_ds_knobs,
                               routes_ds_matchup,
                               routes_ds_profile,
                               routes_ds_sweep,
                               routes_ds_relscore, routes_ds_statcheck,
                               routes_aram_balance,
                               routes_damage_mix, routes_draft_elo,
                               routes_duo_synergy,
                               routes_health_peer,
                               routes_item_wpa,
                               routes_skill_wpa,
                               routes_rune_wpa,
                               routes_summspell_wpa,
                               routes_lessons,
                               routes_loadout, routes_loop_status,
                               routes_loop_monitor,
                               routes_lobby_aux, routes_metrics,
                               routes_pickban, routes_adaptive_summoners,
                               routes_ban_suggestions, routes_dictionary,
                               routes_personal_context,
                               routes_personal_build,
                               routes_player_profile,
                               routes_duration_winrate,
                               routes_champ_benchmarks,
                               routes_perf_curve,
                               routes_op_score,
                               routes_personal_vs,
                               routes_post_game_rubric,
                               routes_post_game_wpa,
                               routes_replay_events,
                               routes_spike_curve,
                               routes_spike_markers,
                               routes_sr_draft, routes_sr_user_builds,
                               routes_team_context,
                               routes_ward_heat,
                               routes_archetype, routes_last_match)
        _GET_CACHE = (list(routes_static.GET_ROUTES)
                      + list(routes_state.GET_ROUTES)
                      + list(routes_history.GET_ROUTES)
                      + list(routes_diag.GET_ROUTES)
                      + list(routes_coach.GET_ROUTES)
                      + list(routes_bridge.GET_ROUTES)
                      + list(routes_bridge_pending.GET_ROUTES)
                      + list(routes_bridge_cadence.GET_ROUTES)
                      + list(routes_ban_suggest.GET_ROUTES)
                      + list(routes_cc_blended_ehp_threat.GET_ROUTES)
                      + list(routes_cc_conditional_pressure.GET_ROUTES)
                      + list(routes_cc_pairing.GET_ROUTES)
                      + list(routes_peel_priority.GET_ROUTES)
                      + list(routes_cooldown_watch.GET_ROUTES)
                      + list(routes_ds_combo.GET_ROUTES)
                      + list(routes_ds_knobs.GET_ROUTES)
                      + list(routes_ds_matchup.GET_ROUTES)
                      + list(routes_ds_profile.GET_ROUTES)
                      + list(routes_ds_sweep.GET_ROUTES)
                      + list(routes_ds_relscore.GET_ROUTES)
                      + list(routes_ds_statcheck.GET_ROUTES)
                      + list(routes_aram_balance.GET_ROUTES)
                      + list(routes_damage_mix.GET_ROUTES)
                      + list(routes_draft_elo.GET_ROUTES)
                      + list(routes_duo_synergy.GET_ROUTES)
                      + list(routes_health_peer.GET_ROUTES)
                      + list(routes_item_wpa.GET_ROUTES)
                      + list(routes_skill_wpa.GET_ROUTES)
                      + list(routes_rune_wpa.GET_ROUTES)
                      + list(routes_summspell_wpa.GET_ROUTES)
                      + list(routes_lessons.GET_ROUTES)
                      + list(routes_loadout.GET_ROUTES)
                      + list(routes_loop_status.GET_ROUTES)
                      + list(routes_loop_monitor.GET_ROUTES)
                      + list(routes_lobby_aux.GET_ROUTES)
                      + list(routes_metrics.GET_ROUTES)
                      + list(routes_pickban.GET_ROUTES)
                      + list(routes_adaptive_summoners.GET_ROUTES)
                      + list(routes_ban_suggestions.GET_ROUTES)
                      + list(routes_dictionary.GET_ROUTES)
                      + list(routes_personal_context.GET_ROUTES)
                      + list(routes_personal_build.GET_ROUTES)
                      + list(routes_player_profile.GET_ROUTES)
                      + list(routes_duration_winrate.GET_ROUTES)
                      + list(routes_champ_benchmarks.GET_ROUTES)
                      + list(routes_perf_curve.GET_ROUTES)
                      + list(routes_op_score.GET_ROUTES)
                      + list(routes_personal_vs.GET_ROUTES)
                      + list(routes_post_game_rubric.GET_ROUTES)
                      + list(routes_post_game_wpa.GET_ROUTES)
                      + list(routes_replay_events.GET_ROUTES)
                      + list(routes_spike_curve.GET_ROUTES)
                      + list(routes_spike_markers.GET_ROUTES)
                      + list(routes_sr_draft.GET_ROUTES)
                      + list(routes_sr_user_builds.GET_ROUTES)
                      + list(routes_team_context.GET_ROUTES)
                      + list(routes_ward_heat.GET_ROUTES)
                      + list(routes_archetype.GET_ROUTES)
                      + list(routes_last_match.GET_ROUTES))
    return _GET_CACHE


def _gather_post() -> list:
    global _POST_CACHE
    if _POST_CACHE is None:
        from dashboard import (routes_static, routes_state, routes_history,
                               routes_diag, routes_coach, routes_bridge,
                               routes_bridge_pending, routes_bridge_cadence,
                               routes_bridge_pending_actions,
                               routes_coach_choice,
                               routes_health_peer,
                               routes_loadout, routes_loop_control,
                               routes_lobby_aux, routes_metrics,
                               routes_scouting,
                               routes_sr_draft, routes_sr_user_builds,
                               routes_team_context,
                               routes_archetype, routes_last_match)
        _POST_CACHE = (list(routes_static.POST_ROUTES)
                       + list(routes_state.POST_ROUTES)
                       + list(routes_history.POST_ROUTES)
                       + list(routes_diag.POST_ROUTES)
                       + list(routes_coach.POST_ROUTES)
                       + list(routes_bridge.POST_ROUTES)
                       + list(routes_bridge_pending.POST_ROUTES)
                       + list(routes_bridge_cadence.POST_ROUTES)
                       + list(routes_bridge_pending_actions.POST_ROUTES)
                       + list(routes_coach_choice.POST_ROUTES)
                       + list(routes_health_peer.POST_ROUTES)
                       + list(routes_loadout.POST_ROUTES)
                       + list(routes_loop_control.POST_ROUTES)
                       + list(routes_lobby_aux.POST_ROUTES)
                       + list(routes_metrics.POST_ROUTES)
                       + list(routes_scouting.POST_ROUTES)
                       + list(routes_sr_draft.POST_ROUTES)
                       + list(routes_sr_user_builds.POST_ROUTES)
                       + list(routes_team_context.POST_ROUTES)
                       + list(routes_archetype.POST_ROUTES)
                       + list(routes_last_match.POST_ROUTES))
    return _POST_CACHE


def dispatch_get(handler: BaseHTTPRequestHandler) -> bool:
    """Try each registered GET route in order. Returns True if one
    matched and handled the request (the handler is responsible for
    writing a response). Returns False if no route matched."""
    path = handler.path
    for matcher, fn in _gather_get():
        if matcher(path):
            fn(handler)
            return True
    return False


# -- soft-warn POST body validation -----------------------------------

# Path -> pydantic Request model. Only paths listed here are validated;
# unmapped paths pass through silently (no false-warning noise on
# routes that haven't been schema'd yet). Path lookup matches
# equals()-style routes - strip query string before lookup so
# `/api/input?foo=1` still validates.
_REQUEST_MODELS = {
    "/api/input":                   InputRequest,
    "/api/command":                 CommandRequest,
    "/api/ds-preview":              DsPreviewRequest,
    "/api/build-order":             BuildOrderRequest,
    "/api/bridge/inbox":            BridgeInboxRequest,
    "/api/speak":                   SpeakRequest,
    "/api/team-context/refresh":    TeamContextRefreshRequest,
}


def _validate_request_body(path: str, body) -> None:
    """Soft-validate POST body against api_schema. Logs WARNING per field
    error; never raises. Silent pass-through for paths not in
    _REQUEST_MODELS."""
    base = path.split("?", 1)[0]
    model_cls = _REQUEST_MODELS.get(base)
    if model_cls is None:
        return
    if not isinstance(body, dict):
        log.warning("request_body[%s]: expected dict, got %s",
                    base, type(body).__name__)
        return
    try:
        model_cls.model_validate(body)
    except ValidationError as exc:
        for err in exc.errors():
            loc = ".".join(str(x) for x in err["loc"])
            log.warning("request_body[%s] %s: %s", base, loc, err["msg"])


def dispatch_post(handler: BaseHTTPRequestHandler, body: object) -> bool:
    """Same as dispatch_get but for POST. `body` is the parsed JSON
    payload (dict) extracted upstream."""
    path = handler.path
    _validate_request_body(path, body)
    for matcher, fn in _gather_post():
        if matcher(path):
            fn(handler, body)
            return True
    return False
