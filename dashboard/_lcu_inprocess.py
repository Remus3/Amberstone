# arch: in-process LCU snapshot reader for /api/state | section=dashboard | frozen=no
"""In-process LCU snapshot reader for the dashboard (RC2 RM-03 E12 lever L3).

DEFAULT-OFF alternative to the :8889 relay hop
(``dashboard/_liveclient.lcu_summary``). When ``RC_LCU_INPROCESS=1``,
``dashboard/_state_builder`` sources the whole LCU snapshot straight from a
dashboard-owned ``LcuClient`` via ``lcu.snapshot_shape.shape_snapshot`` -
byte-identical to the agent-posted payload for the ``lcu.champ_select``
sub-dict - removing the localhost round-trip through ``tools/lcu_agent`` +
the vision relay.

Landed DARK: the flag is off by default and ``lcu_summary_inprocess()``
returns None whenever the client is not connected (or anything raises), so
``_state_builder`` cleanly falls back to the relay ``lcu_summary()`` and
today's live path is unchanged. G1-00 live confirm (flag ON in a live
champ-select, byte-compare vs the relay) is owed before flipping.

The dashboard runs in the SAME process as ``main.py``'s RuneWriter
``LcuClient``, but this module owns its OWN client so there is no
startup-order coupling to the frozen ``main.py`` accessor and no
shared-mutable-state surprise. ``LcuClient`` is frozen; we only READ its
public-ish surface (``connect`` / ``_refresh_conn_if_changed`` / ``_request``
/ ``_port``), never modify it.
"""
from __future__ import annotations

import threading

from lcu.snapshot_shape import shape_snapshot

_client = None
_client_lock = threading.Lock()

# Dashboard-owned config. shape_snapshot does NOT emit config (it is
# caller-owned; see its docstring), so this is passed only for call-site
# symmetry with the agent's ``shape_snapshot(lcu_request, CONFIG)``. The
# in-process reader cannot reproduce the agent's process-owned auto_accept
# toggle - an ACCEPTED, documented flag-ON divergence (``state.lcu.config``
# is relay-only), validated live at G1-00.
_DASH_CONFIG = {
    "auto_accept": False,
    "summoner_override": False,
    "summoner_d": 4,
    "summoner_f": 32,
}


def _get_client():
    """Lazily create + best-effort connect the dashboard-owned LcuClient.

    Reused across calls. Relies on ``LcuClient``'s own
    ``_refresh_conn_if_changed`` self-heal for lockfile rotation (League
    restart) once connected, and a cold ``connect()`` when not yet connected
    or after League closed. The import is lazy so importing this module never
    drags in the frozen client at dashboard load.
    """
    global _client
    with _client_lock:
        if _client is None:
            from lcu.lcu_client import LcuClient
            _client = LcuClient()
        client = _client
    if not client._port:
        client.connect()
    else:
        client._refresh_conn_if_changed()
    return client


def _make_request(client):
    """Adapt ``LcuClient._request`` (payload | None) to the agent transport
    contract ``(payload, err)`` that shape_snapshot / shape_champ_select
    expect. err is always None: a None payload already signals 'no data',
    which every consumer tolerates (isinstance checks + phase gates)."""
    def _req(method, path, body=None):
        return client._request(method, path, data=body), None
    return _req


def lcu_summary_inprocess():
    """Return the whole LCU snapshot built in-process, or None to fall back.

    Returns None (never raises) whenever the LCU client is not connected or
    anything goes wrong, so the caller cleanly degrades to the relay
    ``lcu_summary()``.
    """
    try:
        client = _get_client()
        if not client._port:
            return None
        return shape_snapshot(_make_request(client), _DASH_CONFIG)
    except Exception:  # noqa: BLE001
        return None


def _reset_client_for_tests() -> None:
    """Drop the cached client so a test can re-drive the lazy init path."""
    global _client
    with _client_lock:
        _client = None
