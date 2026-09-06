# arch: Live Client + LCU + relay IO for game state polling | section=vision | frozen=no
"""game_reader.poller - Live Client / LCU / vision-relay IO layer.

Holds the connectivity primitives for `GameReader`:
  - Relay path: read /latest-liveclient + /latest-lcu off the vision server
    on Legion :8889. Post-1-PC (ADR-011) the vision server self-heals that
    cache by reading :2999 in-process, so the RC-LiveClientRelay agent is an
    optimization, not a dependency - the relay endpoint stays fresh either way.
  - Direct path: fallback to :2999 (GAME_HOST) when the relay is unreachable.
  - LCU lockfile auth for champ-select reads.

`_PollerMixin` is mixed into `GameReader` (`game_reader.__init__`) - methods
freely call into `_NormalizerMixin` (e.g. `self._process_game`) via MRO.
"""

import base64
import json
import logging
import re
import ssl
import subprocess
import time as _time
import urllib.error
import urllib.request
from pathlib import Path

from core.game_host import GAME_HOST

LIVE_API = f"https://{GAME_HOST}:2999/liveclientdata"

# Relay endpoint: the RC-LiveClientRelay agent pushes Riot's localhost Live
# Client API JSON to the vision server, which caches it. Post-1-PC the vision
# server also self-reads :2999 in-process to keep this fresh if the agent is
# down (ADR-011), so this stays the primary read path for all consumers.
RELAY_URL = "http://127.0.0.1:8889/latest-liveclient"
# AUDIT (2026-04-22): token resolved via core.vision_token.
# Lane 8 cycle 14: the `except ImportError` fallback used to substitute the
# constant that `core/vision_token.py` explicitly RETIRED ("there is NO
# hardcoded fallback ... so a misconfigured deploy fails loud instead of
# silently authenticating every request with a known constant"). The literal no
# longer matches the rotated token (measured: 401 against :8889, where the
# canonical token gets 200), so the fallback could only ever fail to
# authenticate.
#
# Severity, stated honestly rather than inflated: this branch was close to
# unreachable and fail-soft even when taken. `get_vision_token()` raises
# RuntimeError - NOT ImportError - when no token is configured, so only a
# physically missing `core/vision_token.py` could trigger it; and a bad
# RELAY_TOKEN just makes `_try_relay` return None, after which `read_game`
# falls through to the direct :2999 path. This is hygiene - removing a retired
# secret-shaped literal - not the repair of a live outage.
from core.vision_token import get_vision_token as _get_vision_token

RELAY_TOKEN = _get_vision_token()
RELAY_MAX_AGE_S = 12.0  # treat older snapshots as stale -> fall through to direct
                        # 2026-04-26: bumped from 5.0 -> 12.0. Relay polls every 1s
LCU_RELAY_URL     = "http://127.0.0.1:8889/latest-lcu"
LCU_RELAY_MAX_AGE = 20.0  # LCU agent posts every 1s; 20s is a generous staleness guard
                        # but network jitter + Legion contention during teamfights
                        # pushes ages over 5s often, causing wasteful direct-API
                        # timeout cycles. 12s gives generous margin while still
                        # catching genuinely-stale data (game ended hours ago).

_log = logging.getLogger("game_reader.poller")


class _PollerMixin:
    """HTTP/relay/LCU primitives. State (`_lcu_port`, `_ssl`, etc.) is
    initialized by `GameReader.__init__`."""

    # AUDIT-PHASE-2-GR-001: lockfile-based LCU auth (replaces deprecated wmic)
    _LCU_LOCKFILE_PATHS = [
        Path(r"C:\Riot Games\League of Legends\lockfile"),
        Path(r"C:\Riot Games\League of Legends (PBE)\lockfile"),
        Path(r"D:\Riot Games\League of Legends\lockfile"),
        Path(r"D:\Riot Games\League of Legends (PBE)\lockfile"),
    ]

    # ------------------------------------------------------------------
    # Public - call from overlay's poll loop
    # ------------------------------------------------------------------

    def _try_relay(self):
        """Pull the latest Live Client snapshot from vision server's relay
        cache. Returns the parsed JSON dict (data field) or None if missing
        or stale. This is the primary path post-2026-04-19 migration since
        Riot's API is localhost-only and now read Legion-local in-process.

        Side-effect: sets `self._relay_says_no_game = True` when the relay
        returns its authoritative "no_liveclient_yet" 404. `read_game`
        uses this to skip the wasteful direct-API attempt that always
        times out when no game is running.
        """
        self._relay_says_no_game = False
        try:
            req = urllib.request.Request(
                RELAY_URL, headers={"X-RC-Token": RELAY_TOKEN}
            )
            with urllib.request.urlopen(req, timeout=2) as r:
                wrap = json.loads(r.read())
            if "error" in wrap:
                return None
            age = _time.time() - wrap.get("ts", 0)
            if age > RELAY_MAX_AGE_S:
                return None
            return wrap.get("data")
        except urllib.error.HTTPError as e:
            # 404 from the relay is authoritative: no game running (the vision
            # server's in-process self-read of :2999 also came up empty).
            # Distinguish this from genuine "relay unreachable" so the caller
            # can skip the direct-API fallback (which times out + spams logs).
            if e.code == 404:
                self._relay_says_no_game = True
            return None
        except Exception:  # noqa: BLE001
            return None

    def _try_lcu_game_id(self) -> str:
        """Read game_id from the LCU relay on the vision server.

        Returns '' if the relay is stale, unavailable, or game_id not yet
        set (e.g. phase != InProgress). No caching - the vision server
        already caches the last upload-lcu payload.
        """
        try:
            req = urllib.request.Request(
                LCU_RELAY_URL, headers={"X-RC-Token": RELAY_TOKEN}
            )
            with urllib.request.urlopen(req, timeout=1.0) as r:
                wrap = json.loads(r.read())
            if _time.time() - wrap.get("ts", 0) > LCU_RELAY_MAX_AGE:
                return ""
            return str((wrap.get("data") or {}).get("game_id") or "")
        except Exception:  # noqa: BLE001
            return ""

    def check_in_game(self):
        """Quick check: is the in-game API responding?"""
        if self._try_relay() is not None:
            return True
        try:
            self._get(f"{LIVE_API}/gamestats")
            return True
        except Exception:  # noqa: BLE001
            return False

    def read_game(self):
        """Full game state read. Returns dict or None if game not active."""
        # Relay path (Legion-local push of localhost API -> vision server cache)
        relay_raw = self._try_relay()
        if isinstance(relay_raw, dict):
            self.raw = relay_raw
            self.is_in_game = True
            self._read_error_count = 0
            return self._process_game(relay_raw)
        # Relay says authoritatively "no game" - skip the direct API attempt.
        # (Legacy 2-PC note: Riot's :2999 bound localhost-only and, in the
        # retired 2-PC topology, timed out from Legion, spamming ~700
        # warnings/day in client mode; the relay 404 short-circuit killed
        # that. Now read Legion-local in-process.) Reset the error
        # counter too: the relay's successful 404 isn't a failure to surface.
        if getattr(self, "_relay_says_no_game", False):
            self.is_in_game = False
            self._read_error_count = 0
            return None
        try:
            raw = self._get(f"{LIVE_API}/allgamedata")

            # Guard: API sometimes returns a JSON-encoded string or null during
            # loading screen transitions instead of the expected dict.
            if not isinstance(raw, dict):
                if isinstance(raw, str):
                    # Attempt 1: double-encoded JSON (string that contains JSON)
                    try:
                        decoded = json.loads(raw)
                        if isinstance(decoded, dict):
                            raw = decoded
                            _log.info("read_game: double-decode recovered valid dict")
                        else:
                            self._warn_once(f"allgamedata string: {raw[:120]!r}")
                            raw = self._read_game_fallback()
                    except Exception:  # noqa: BLE001
                        self._warn_once(f"allgamedata non-JSON string: {raw[:120]!r}")
                        raw = self._read_game_fallback()
                else:
                    raw = self._read_game_fallback()

            if not isinstance(raw, dict):
                self.is_in_game = False
                return None

            self.raw = raw
            self.is_in_game = True
            self._read_error_count = 0
            return self._process_game(raw)

        except Exception as exc:  # noqa: BLE001
            self.is_in_game = False
            import traceback as _tb
            self._warn_once(f"{exc} | {_tb.format_exc().splitlines()[-2].strip()}")
            return None

    def _warn_once(self, msg: str):
        """Rate-limited warning. Direct-API timeouts are EXPECTED post-2026-04-19
        migration whenever the relay snapshot momentarily ages past 12s
        (jitter, Legion contention) - the next relay tick recovers within 1-2s.
        Demote to DEBUG so the log doesn't fill with cosmetic warnings; only
        promote to WARNING after a sustained outage (~5 minutes of failures)."""
        count = getattr(self, "_read_error_count", 0) + 1
        self._read_error_count = count
        if count == 1 or count % 150 == 0:    # ~5 min @ 2s polls
            _log.warning("read_game [%dx, sustained]: %s", count, msg)
        elif count % 15 == 0:
            _log.debug("read_game [%dx]: %s", count, msg)

    def _read_game_fallback(self):
        """
        Assemble game state from individual Riot endpoints.
        Used when /allgamedata returns a non-dict response.
        """
        endpoints = {
            "gameData":     f"{LIVE_API}/gamestats",
            "activePlayer": f"{LIVE_API}/activeplayer",
            "allPlayers":   f"{LIVE_API}/allplayers",
            "events":       f"{LIVE_API}/eventdata",
        }
        result = {}
        for key, url in endpoints.items():
            try:
                data = self._get(url)
                if isinstance(data, (dict, list)):
                    result[key] = data
            except Exception:  # noqa: BLE001
                pass

        if not result:
            return None

        # eventdata structure differs from allgamedata - normalise
        ev = result.get("events")
        if isinstance(ev, dict) and "Events" not in ev:
            result["events"] = {"Events": self._normalise_events(ev)}
        elif isinstance(ev, list):
            result["events"] = {"Events": ev}

        _log.info("read_game: fallback ok (keys=%s)", list(result.keys()))
        return result

    @staticmethod
    def _normalise_events(ev: dict) -> list:
        """Pull the event list out of an unexpected /eventdata envelope.

        Lane 8 cycle 14: this used to be `list(ev.values())[0]`, which trusts
        the key ORDER of a foreign payload - so a dict whose first value was a
        version string handed that string downstream AS the event list. Select
        by shape instead, and return [] when nothing list-shaped is present.
        """
        for value in ev.values():
            if isinstance(value, list):
                return value
        return []

    def read_champ_select(self):
        """Read champ select from LCU. Returns dict or None."""
        if not self._ensure_lcu():
            return None
        try:
            session = self._lcu_get("/lol-champ-select/v1/session")
            return self._process_champ_select(session)
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _get(self, url):
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, context=self._ssl, timeout=2) as r:
            return json.loads(r.read())

    def _ensure_lcu(self):
        if self._lcu_port and self._lcu_auth:
            return True
        # Primary: lockfile (works on Windows 10 and 11, no wmic needed)
        for lf in self._LCU_LOCKFILE_PATHS:
            try:
                if lf.exists():
                    parts = lf.read_text(encoding="utf-8").strip().split(":")
                    if len(parts) >= 4:
                        # Lane 8 cycle 14: validate before caching. League
                        # writes this file at client startup, so a torn read is
                        # a real race, and `_lcu_port` is cached on the instance
                        # for the process lifetime - accepting garbage once
                        # breaks every later LCU request until a restart.
                        port, pw = parts[2], parts[3]
                        if not (port.isdigit() and 0 < int(port) <= 65535):
                            _log.debug(
                                "LCU lockfile %s: bad port %r - skipping", lf, port
                            )
                            continue
                        if not pw:
                            _log.debug(
                                "LCU lockfile %s: empty auth field - skipping", lf
                            )
                            continue
                        self._lcu_port = port
                        self._lcu_auth = base64.b64encode(
                            f"riot:{pw}".encode()
                        ).decode()
                        _log.debug("LCU lockfile connected: port %s", self._lcu_port)
                        return True
            except Exception as exc:  # noqa: BLE001
                _log.debug("LCU lockfile %s: %s", lf, exc)
        # Fallback: wmic (Windows 10 only, deprecated on Win11)
        try:
            result = subprocess.run(
                ["wmic", "process", "where",
                 "name='LeagueClientUx.exe'", "get", "commandline"],
                capture_output=True, text=True, timeout=5, creationflags=0x08000000
            )
            port = re.search(r"--app-port=(\d+)", result.stdout)
            token = re.search(r"--remoting-auth-token=([\w_-]+)", result.stdout)
            if port and token:
                self._lcu_port = port.group(1)
                self._lcu_auth = base64.b64encode(
                    f"riot:{token.group(1)}".encode()
                ).decode()
                return True
        except Exception:  # noqa: BLE001
            pass
        return False

    def _lcu_get(self, endpoint):
        # RC2 P6.4 (L6): pooled keep-alive connection reuse to cut the per-call
        # LCU TCP+TLS handshake churn. DEFAULT-ON (RC_LCU_POOL) since the E7
        # flip 2026-06-30, validated over a live game 2026-07-01 - an UNSET env
        # pools, and explicit RC_LCU_POOL=0 is the only way back to the
        # byte-identical urlopen path below; a pooled fail-soft None falls
        # through to the per-call read either way. RM-358: this comment claimed
        # the opposite default for two months after the flip, and that misread
        # cost real triage time (RM-345 was first graded latent-behind-a-flag
        # on it), so tests/test_rc_lcu_pool_default_prose_guard_rm358.py now
        # pins the prose to what pool_enabled() actually returns.
        from core import lcu_pool
        if lcu_pool.pool_enabled():
            res = lcu_pool.get_shared_pool().request(
                GAME_HOST, self._lcu_port, "GET", endpoint,
                headers={"Authorization": f"Basic {self._lcu_auth}"},
            )
            if res is not None:
                return json.loads(res[1])
        url = f"https://{GAME_HOST}:{self._lcu_port}{endpoint}"
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Basic {self._lcu_auth}")
        with urllib.request.urlopen(req, context=self._ssl, timeout=3) as r:
            return json.loads(r.read())

    # ------------------------------------------------------------------
    # Champ select processing
    # ------------------------------------------------------------------

    @staticmethod
    def _picks(session: dict, key: str) -> list:
        """Champion ids off one LCU team list, tolerant of wrong shapes.

        The LCU sends `null` for fields it populates later, and it sends them
        as PRESENT keys - which is why `dict.get(key, [])` is not enough: the
        default applies only when the key is ABSENT. Anything that is not a
        list of dicts contributes nothing rather than raising.
        """
        out = []
        entries = session.get(key)
        if not isinstance(entries, list):
            return out
        for pick in entries:
            if not isinstance(pick, dict):
                continue
            champ_id = pick.get("championId", 0)
            if champ_id:
                out.append(str(champ_id))
        return out

    def _process_champ_select(self, session):
        # Lane 8 cycle 14: this body had no type guards at all. A null session,
        # a present-but-null `bans` block, or a non-dict team entry each raised
        # AttributeError, which `read_champ_select` then swallowed.
        #
        # REACHABILITY, measured rather than assumed: `read_champ_select` has
        # NO production callers today (repo-wide grep finds only its own
        # definition and tests), and it is the sole caller of `_ensure_lcu`,
        # `_lcu_get` and this method - so the whole LCU branch of this module
        # is currently dead. The `_lcu_get` calls in `lcu/lcu_postgame_collector`
        # are that class's OWN same-named method, not this one
        # (`feedback_symbol_name_collision_masks_dead_code`). This is therefore
        # hardening of a dormant path, kept because the path is wired to be
        # revived, not the repair of an observed champ-select outage.
        if not isinstance(session, dict):
            return None

        my_team = self._picks(session, "myTeam")
        their_team = self._picks(session, "theirTeam")

        bans = []
        ban_block = session.get("bans")
        if isinstance(ban_block, dict):
            for side in ("myTeamBans", "theirTeamBans"):
                entries = ban_block.get(side)
                if not isinstance(entries, list):
                    continue
                for ban in entries:
                    if ban:
                        bans.append(str(ban))

        return {
            "phase": "champ_select",
            "my_team_ids": my_team,
            "their_team_ids": their_team,
            "ban_ids": bans,
        }
