# arch: Live Client + LCU + relay IO for game state polling | section=vision | frozen=no
"""game_reader.poller - Live Client / LCU / vision-relay IO layer.

Holds the connectivity primitives for `GameReader`:
  - Relay path: vision server caches Game-PC's localhost Live Client API
    (Riot's :2999 binds 127.0.0.1 only; we read /latest-liveclient and
    /latest-lcu off the in-process vision server on Legion :8889).
  - Direct path: fallback when the relay snapshot is stale or absent.
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

LIVE_API = "https://192.168.8.237:2999/liveclientdata"

# Relay endpoint: gamepc_liveclient_relay.py on Game-PC pushes the localhost
# Live Client API JSON to vision server, which caches it. Riot's API binds
# 127.0.0.1 only and rejects LAN connections, so we read the cached copy.
RELAY_URL = "http://127.0.0.1:8889/latest-liveclient"
# AUDIT (2026-04-22): token resolved via core.vision_token.
try:
    from core.vision_token import get_vision_token as _get_vision_token
    RELAY_TOKEN = _get_vision_token()
except ImportError:
    RELAY_TOKEN = "8e8f131e212b329438218eca27372dde"
RELAY_MAX_AGE_S = 12.0  # treat older snapshots as stale → fall through to direct
                        # 2026-04-26: bumped from 5.0 → 12.0. Relay polls every 1s
LCU_RELAY_URL     = "http://127.0.0.1:8889/latest-lcu"
LCU_RELAY_MAX_AGE = 20.0  # LCU agent posts every 1s; 20s is a generous staleness guard
                        # but network jitter + Game-PC contention during teamfights
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
        Riot's API is localhost-only on Game-PC.

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
            # 404 from the relay is authoritative: no game running on Game-PC.
            # Distinguish this from genuine "relay unreachable" so the caller
            # can skip the direct-API fallback (which times out + spams logs).
            if e.code == 404:
                self._relay_says_no_game = True
            return None
        except Exception:
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
        except Exception:
            return ""

    def check_in_game(self):
        """Quick check: is the in-game API responding?"""
        if self._try_relay() is not None:
            return True
        try:
            self._get(f"{LIVE_API}/gamestats")
            return True
        except Exception:
            return False

    def read_game(self):
        """Full game state read. Returns dict or None if game not active."""
        # Relay path (Game-PC pushes localhost API → vision server cache)
        relay_raw = self._try_relay()
        if isinstance(relay_raw, dict):
            self.raw = relay_raw
            self.is_in_game = True
            self._read_error_count = 0
            return self._process_game(relay_raw)
        # Relay says authoritatively "no game" - skip the direct API
        # attempt (Riot's :2999 binds localhost-only on Game-PC and only
        # times out from Legion). This used to spam ~700 timeout warnings
        # per day during client mode. Reset error counter too: the relay's
        # successful 404 isn't a failure to surface.
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
                    except Exception:
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

        except Exception as exc:
            self.is_in_game = False
            import traceback as _tb
            self._warn_once(f"{exc} | {_tb.format_exc().splitlines()[-2].strip()}")
            return None

    def _warn_once(self, msg: str):
        """Rate-limited warning. Direct-API timeouts are EXPECTED post-2026-04-19
        migration whenever the relay snapshot momentarily ages past 12s
        (jitter, Game-PC contention) - the next relay tick recovers within 1-2s.
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
            except Exception:
                pass

        if not result:
            return None

        # eventdata structure differs from allgamedata - normalise
        ev = result.get("events")
        if isinstance(ev, dict) and "Events" not in ev:
            result["events"] = {"Events": list(ev.values())[0] if ev else []}
        elif isinstance(ev, list):
            result["events"] = {"Events": ev}

        _log.info("read_game: fallback ok (keys=%s)", list(result.keys()))
        return result

    def read_champ_select(self):
        """Read champ select from LCU. Returns dict or None."""
        if not self._ensure_lcu():
            return None
        try:
            session = self._lcu_get("/lol-champ-select/v1/session")
            return self._process_champ_select(session)
        except Exception:
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
                        self._lcu_port = parts[2]
                        pw = parts[3]
                        self._lcu_auth = base64.b64encode(
                            f"riot:{pw}".encode()
                        ).decode()
                        _log.debug("LCU lockfile connected: port %s", self._lcu_port)
                        return True
            except Exception as exc:
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
        except Exception:
            pass
        return False

    def _lcu_get(self, endpoint):
        url = f"https://192.168.8.237:{self._lcu_port}{endpoint}"
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Basic {self._lcu_auth}")
        with urllib.request.urlopen(req, context=self._ssl, timeout=3) as r:
            return json.loads(r.read())

    # ------------------------------------------------------------------
    # Champ select processing
    # ------------------------------------------------------------------

    def _process_champ_select(self, session):
        my_team = []
        their_team = []
        bans = []

        for pick in session.get("myTeam", []):
            champ_id = pick.get("championId", 0)
            if champ_id:
                my_team.append(str(champ_id))

        for pick in session.get("theirTeam", []):
            champ_id = pick.get("championId", 0)
            if champ_id:
                their_team.append(str(champ_id))

        for ban in session.get("bans", {}).get("myTeamBans", []):
            if ban:
                bans.append(str(ban))
        for ban in session.get("bans", {}).get("theirTeamBans", []):
            if ban:
                bans.append(str(ban))

        return {
            "phase": "champ_select",
            "my_team_ids": my_team,
            "their_team_ids": their_team,
            "ban_ids": bans,
        }
