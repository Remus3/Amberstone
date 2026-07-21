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

# config + lcu_port (G1-00 CHECK 2 follow-up, 2026-07-20)

``shape_snapshot`` deliberately emits NEITHER key - both are caller/transport
owned (``lcu/snapshot_shape.py:337-340``) - so the agent adds them itself in
``tools/lcu_agent.capture_state`` (``config`` at :293, ``lcu_port`` at :298).
This module now does the same, so the flag-ON ``state.lcu`` payload matches
the relay payload for those two keys:

  * ``lcu_port`` - the dashboard-owned ``LcuClient`` already parsed it from
    the SAME lockfile the agent reads, so it is derived locally. Stringified
    because the agent stores ``read_lockfile()`` field 2 verbatim and never
    int-casts it (``tools/lcu_agent.py:141-151`` + :165), while
    ``LcuClient.connect`` does (``lcu/lcu_client.py:69``).

  * ``config`` - the agent's ``CONFIG`` (``tools/lcu_agent.py:120-125``) is
    PROCESS-MEMORY ONLY. Nothing persists it: the sole writer is the
    ``set_config`` branch of ``execute_command`` (:388-393) and there is no
    read-back or file write anywhere, so an agent restart silently resets it
    to the boot defaults. There is therefore no shared file to read. The two
    near-miss candidates are both wrong:
      - ``core/auto_accept_pref.py`` -> ``data/auto_accept_pref.json`` is a
        DIFFERENT mechanism (it gates the frozen in-process
        ``_auto_accept_tick``). MEASURED 2026-07-20: the file said
        ``{"enabled": true}`` while the live ``state.lcu.config.auto_accept``
        was ``false``. Sourcing config from it would flip the operator's
        Settings checkbox to a value the agent does not hold.
      - ``vision_server._relay._lcu_state`` holds the agent's posted copy,
        but the vision server is a SEPARATE process (``dashboard/server.py``
        Popens it), so that module-level dict is empty in this process.
    What is left is the relay-posted copy over the existing
    ``dashboard._liveclient.lcu_summary()`` read. That returns the agent's
    OWN dict - real truth, not a synthesized constant - so this module reads
    it TTL-throttled (``_CONFIG_TTL_S``) and caches the last non-empty value.
    The flag-ON path therefore stays strictly CHEAPER than the flag-OFF path,
    which calls ``lcu_summary()`` on every single build.
    Boot defaults are the last-resort fallback only (agent never posted); a
    drift guard in ``tests/rc2_l3/test_lcu_inprocess_config_port_l3.py`` pins
    them to ``tools/lcu_agent.CONFIG``.
    DURABLE FIX (proposed, out of this module's scope): the dashboard is the
    SOLE origin of every ``set_config`` (``dashboard/routes_loadout.py:31`` +
    the ``/api/lcu-cmd`` POST at :350), so it could persist the config to
    ``data/`` exactly like ``core/auto_accept_pref.py`` does and own it
    outright - which is also what the eventual agent retirement requires.
"""
from __future__ import annotations

import threading
import time

from lcu.snapshot_shape import shape_snapshot

_client = None
_client_lock = threading.Lock()

# Last-resort mirror of the agent's boot CONFIG (tools/lcu_agent.py:120-125),
# used ONLY when the agent has never posted a snapshot this process has seen.
# Drift-guarded by test_lcu_inprocess_config_port_l3.
_AGENT_CONFIG_DEFAULTS = {
    "auto_accept": False,
    "summoner_override": False,
    "summoner_d": 4,
    "summoner_f": 32,
}

# Min seconds between relay reads for config. Config only changes on an
# operator click, and the relay itself only refreshes on the agent's ~1 Hz
# push, so a short TTL keeps the pill responsive while cutting the round-trip
# count well below the flag-OFF path (one read per build).
_CONFIG_TTL_S = 3.0
_config_lock = threading.Lock()
_config_cache: dict = {"config": None, "ts": None}


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


def _read_relay_snapshot() -> dict:
    """One read of the agent-posted LCU snapshot off the :8889 relay.

    Thin, patchable seam over ``dashboard._liveclient.lcu_summary`` (which
    already returns ``{}`` on a down / stale relay and never raises). Imported
    lazily so this module stays cheap to import.
    """
    from dashboard._liveclient import lcu_summary
    return lcu_summary()


def _agent_config() -> dict:
    """Return the agent's live CONFIG, TTL-throttled off the relay snapshot.

    Falls back to the last value observed this process, then to the agent's
    boot defaults. Never raises.
    """
    now = time.monotonic()
    with _config_lock:
        cached = _config_cache["config"]
        ts = _config_cache["ts"]
        fresh = ts is not None and (now - ts) < _CONFIG_TTL_S
    if fresh:
        return dict(cached) if cached is not None else dict(_AGENT_CONFIG_DEFAULTS)

    observed = None
    try:
        snap = _read_relay_snapshot()
        cfg = snap.get("config") if isinstance(snap, dict) else None
        if isinstance(cfg, dict) and cfg:
            observed = dict(cfg)
    except Exception:  # noqa: BLE001
        observed = None

    with _config_lock:
        _config_cache["ts"] = now
        if observed is not None:
            _config_cache["config"] = observed
        cached = _config_cache["config"]
    return dict(cached) if cached is not None else dict(_AGENT_CONFIG_DEFAULTS)


def lcu_summary_inprocess():
    """Return the whole LCU snapshot built in-process, or None to fall back.

    Key order mirrors ``tools/lcu_agent.capture_state``: caller-owned
    ``config`` + ``lcu_port`` first, then the shape_snapshot assembly.

    Returns None (never raises) whenever the LCU client is not connected or
    anything goes wrong, so the caller cleanly degrades to the relay
    ``lcu_summary()``.
    """
    try:
        client = _get_client()
        if not client._port:
            return None
        config = _agent_config()
        snap = {"config": config, "lcu_port": str(client._port)}
        snap.update(shape_snapshot(_make_request(client), config))
        return snap
    except Exception:  # noqa: BLE001
        return None


def _reset_client_for_tests() -> None:
    """Drop the cached client so a test can re-drive the lazy init path."""
    global _client
    with _client_lock:
        _client = None
    _reset_config_cache_for_tests()


def _reset_config_cache_for_tests() -> None:
    """Forget every observed config so the fallback path is re-drivable."""
    with _config_lock:
        _config_cache["config"] = None
        _config_cache["ts"] = None


def _expire_config_cache_for_tests() -> None:
    """Expire the TTL but KEEP the last observed value, so a test can drive
    the next relay read without losing the 'hold last known' behavior."""
    with _config_lock:
        _config_cache["ts"] = None
