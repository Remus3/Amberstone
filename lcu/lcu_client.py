# arch: LCU auth + command client | section=core | frozen=yes
"""
lcu/lcu_client.py - League Client Update (LCU) API client.
Auto-accept queue pops + ARAM bench swap + rune page read (API-001).

LCU API: https://{RC_GAME_HOST}:{port} with Basic auth "riot:{password}"
Lockfile: {LeaguePath}/lockfile -> processName:pid:port:password:protocol

AUDIT-PHASE-2-API-001 - 2026-04-18
  Added: get_current_rune_page(), get_all_rune_pages(), format_rune_page()
  Added: _build_rune_id_map() - resolves perk IDs to names via local DDragon data
"""
import asyncio
import json
import ssl
import logging
import time
import threading
import base64
from pathlib import Path
from typing import Any, Optional
import urllib.error
import urllib.request

from core.game_host import GAME_HOST

_log = logging.getLogger("rc.lcu")

_APP_DIR = Path(__file__).parent.parent

_LOCKFILE_PATHS = [
    Path(r"C:\Riot Games\League of Legends\lockfile"),
    Path(r"C:\Riot Games\League of Legends (PBE)\lockfile"),
    Path(r"D:\Riot Games\League of Legends\lockfile"),
    Path(r"D:\Riot Games\League of Legends (PBE)\lockfile"),
]

# Seconds between repeats of the lockfile-not-found notice within a single gap.
# The first notice of each gap is exempt (see connect()). 60 s keeps a day of
# League-never-launched under ~1500 lines per process instead of ~86400, and is
# safe for tools/lcu_push_watcher.py: its _RE_LOCKFILE_GAP state machine latches
# gap_pending until the next "LCU connected:" line and never reads timestamps,
# so ONE line per gap - which the immediate first notice guarantees - is enough.
_LOCKFILE_MISSING_REPEAT_S = 60.0


from lcu.lcu_pregame import LcuPregame as _PGMixin

class LcuClient(_PGMixin):
    def __init__(self):
        self._port = None
        self._auth = None
        self._ssl = ssl.create_default_context()
        self._ssl.check_hostname = False
        self._ssl.verify_mode = ssl.CERT_NONE
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._task: Optional[Any] = None  # AppLoop task when riding asyncio
        self._rune_id_map: dict = {}  # perk id -> name, lazy-loaded
        # 2026-07-01 lockfile-rotation resilience
        # (reference_runewriter_dies_after_game1): remember which lockfile we
        # connected from + its mtime so _refresh_conn_if_changed() can cheaply
        # detect a League restart (rotated port/password) and re-auth WITHOUT
        # an RC restart.
        self._lockfile_path = None
        self._lockfile_mtime = None
        # 2026-07-29: the not-found notice is a TRANSITION, not a heartbeat.
        # _auto_accept_tick calls connect() at 1 Hz whenever _port is falsy, so
        # an unconditional INFO here reached 20144 of 21082 log lines (95.6
        # percent) on a day League never launched. Repeat 20144 carries no
        # information repeat 1 did not, and it buried every other line the
        # cost/health watchdog reads.
        self._lockfile_missing_logged = False
        # Monotonic timestamp of the last not-found line this process emitted.
        # Wall clock is deliberately not used: it can step backwards over NTP or
        # DST and would then stall the notice for hours.
        self._lockfile_missing_last_log = 0.0

    def connect(self):
        for lf in _LOCKFILE_PATHS:
            if lf.exists():
                # AUDIT 2026-04-28 (deferred-frozen): narrow from bare
                # Exception. Lockfile parse can fail with: OSError (read
                # fails), IndexError (split has < 4 parts), ValueError
                # (port int() fails), UnicodeDecodeError (non-utf8).
                try:
                    parts = lf.read_text(encoding="utf-8").strip().split(":")
                    self._port = int(parts[2])
                    pw = parts[3]
                    self._auth = base64.b64encode(f"riot:{pw}".encode()).decode()
                    self._lockfile_path = lf
                    try:
                        self._lockfile_mtime = lf.stat().st_mtime
                    except OSError:
                        self._lockfile_mtime = None
                    _log.info("LCU connected: port %d (from %s)", self._port, lf)
                    self._lockfile_missing_logged = False
                    return True
                except (OSError, IndexError, ValueError, UnicodeDecodeError) as e:
                    _log.warning("LCU lockfile parse (%s): %s", type(e).__name__, e)
        # Demoting the repeat to DEBUG saved nothing ON DISK: core/log_setup.py
        # sets the file handler to DEBUG unconditionally ("always verbose to
        # file"), so on 2026-08-04 this one line was 13316 of 13692 lines (97.3
        # percent) at 1.97 lines/sec across the two 1 Hz pollers. The repeat is
        # therefore rate-limited as well as demoted. The FIRST notice of each
        # gap stays immediate and INFO - that transition is the diagnostic, and
        # a re-opened gap must not be swallowed by a still-running window.
        now = time.monotonic()
        if not self._lockfile_missing_logged:
            _log.info("LCU lockfile not found - client may not be running")
            self._lockfile_missing_logged = True
            self._lockfile_missing_last_log = now
        elif now - self._lockfile_missing_last_log >= _LOCKFILE_MISSING_REPEAT_S:
            _log.debug("LCU lockfile not found - client may not be running")
            self._lockfile_missing_last_log = now
        return False

    def _refresh_conn_if_changed(self) -> None:
        """Re-auth when the LCU lockfile rotates (League restart) so a
        long-lived RC survives a client restart WITHOUT an RC restart.

        Mirrors the RC-LCUAgent's ensure_lcu_conn() (tools/lcu_agent.py), the
        reference pattern that already survives a rotation. mtime-guarded: the
        every-tick (1 Hz) call is a pure stat() fast-path while the lockfile is
        unchanged, so it neither re-parses nor log-spams. Swaps port/auth on a
        real rotation; clears them when the lockfile is gone (League closed) so
        the connect() cold-start path reconnects cleanly on the next launch.

        Only acts once already connected; the initial connect is left to
        connect() (and the _auto_accept_tick cold-start). See
        reference_runewriter_dies_after_game1 (2026-07-01).
        """
        if not self._port:
            return  # not yet connected - connect() owns the cold start
        for lf in _LOCKFILE_PATHS:
            try:
                mtime = lf.stat().st_mtime
            except OSError:
                continue  # this install path absent - try the next
            if lf == self._lockfile_path and mtime == self._lockfile_mtime:
                return  # unchanged since last read - fast path, no re-parse
            try:
                parts = lf.read_text(encoding="utf-8").strip().split(":")
                port = int(parts[2])
                pw = parts[3]
            except (OSError, IndexError, ValueError, UnicodeDecodeError) as e:
                _log.warning("LCU lockfile parse (%s): %s", type(e).__name__, e)
                return
            auth = base64.b64encode(f"riot:{pw}".encode()).decode()
            if port != self._port or auth != self._auth:
                _log.info("LCU reconnected: port %d (lockfile rotated, from %s)",
                          port, lf)
            self._port = port
            self._auth = auth
            self._lockfile_path = lf
            self._lockfile_mtime = mtime
            return
        # No lockfile on any known path -> League closed. Clear creds so a later
        # launch reconnects via connect()/the cold-start path.
        _log.info("LCU lockfile gone - client closed; creds cleared")
        self._port = None
        self._auth = None
        self._lockfile_path = None
        self._lockfile_mtime = None

    def _request(self, method, endpoint, data=None, _retry=True):
        if not self._port or not self._auth:
            return None
        url = f"https://{GAME_HOST}:{self._port}{endpoint}"
        headers = {
            "Authorization": f"Basic {self._auth}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        body = json.dumps(data).encode() if data else None
        # RC2 E7 / P6.4 (L6, operator frozen-grant 2026-06-30): opt-in pooled
        # keep-alive reuse cuts the per-call LCU TCP+TLS handshake on the
        # every-tick auto-accept path. DEFAULT-OFF (RC_LCU_POOL) so the urlopen
        # path below stays byte-identical until the operator opts in. The pooled
        # branch preserves _request's contract: 2xx -> parsed JSON ({} when the
        # body is empty), non-2xx -> None (mirrors the urlopen HTTPError -> None
        # so a 404 error body never leaks as a dict to callers), and a fail-soft
        # pool None falls through to the per-call urlopen read. Lazy import keeps
        # the frozen top-level import block untouched (same pattern as LIFT 5).
        from core import lcu_pool
        if lcu_pool.pool_enabled():
            res = lcu_pool.get_shared_pool().request(
                GAME_HOST, self._port, method, endpoint,
                headers=headers, body=body,
            )
            if res is not None:
                status, payload = res
                if not (200 <= status < 300):
                    return None
                try:
                    raw = payload.decode()
                    return json.loads(raw) if raw.strip() else {}
                except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                    return None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        # AUDIT P-rc-frozen-lcu-urlopen (2026-04-22): context-manager the
        # urlopen so the socket closes even if json.loads raises mid-read.
        try:
            with urllib.request.urlopen(req, context=self._ssl, timeout=3) as resp:
                raw = resp.read().decode()
            return json.loads(raw) if raw.strip() else {}
        except (urllib.error.URLError, OSError, TimeoutError):
            # Connection-level failure - most often a dead port after a League
            # restart rotated the lockfile. Re-read it; if it rotated, retry
            # ONCE on the fresh port. reference_runewriter_dies_after_game1.
            if _retry:
                self._refresh_conn_if_changed()
                if self._port:
                    return self._request(method, endpoint, data=data, _retry=False)
            return None
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return None

    # === Auto-Accept ===========================================================

    def accept_queue(self):
        return self._request("POST", "/lol-matchmaking/v1/ready-check/accept")

    def get_queue_state(self):
        return self._request("GET", "/lol-matchmaking/v1/ready-check")

    def start_auto_accept(self, interval=1.0):
        self._running = True
        self._last_locked_champ = ""   # track last champion we applied runes for
        self._last_locked_mode  = ""
        try:
            from app._loop import get_loop as _get_loop
            _sched = _get_loop()
        except Exception:
            _sched = None
        if _sched is not None:
            self._task = _sched.spawn_task(self._auto_accept_loop_async(interval))
            _log.info("Auto-accept started (%.1fs interval, async)", interval)
        else:
            self._thread = threading.Thread(
                target=self._auto_accept_loop, args=(interval,), daemon=True
            )
            self._thread.start()
            _log.info("Auto-accept started (%.1fs interval, thread)", interval)

    def stop_auto_accept(self):
        self._running = False
        if self._task is not None:
            try: self._task.cancel()
            except Exception: pass
            self._task = None

    def _auto_accept_tick(self) -> None:
        # Keep creds fresh across a League restart (lockfile rotation) even when
        # no request is in flight - the 1 Hz heartbeat that heals RuneWriter and
        # every other consumer sharing this instance.
        # reference_runewriter_dies_after_game1.
        self._refresh_conn_if_changed()
        if not self._port:
            self.connect()
        if self._port:
            state = self.get_queue_state()
            if state and isinstance(state, dict):
                ps = state.get("playerResponse", "")
                not_responded = ps in ("None", None, "")
                if state.get("state") == "InProgress" and not_responded:
                    # LIFT 5: honor the dashboard auto-accept toggle. NON-frozen
                    # pref module, default ON, so this is byte-identical to the
                    # historical always-accept behavior until the operator turns
                    # it off via POST /api/lcu/auto-accept. Lazy import keeps the
                    # frozen top-level import block untouched.
                    from core.auto_accept_pref import is_enabled as _aa_enabled
                    if _aa_enabled():
                        self.accept_queue()
                        _log.info("Queue auto-accepted!")
            self._maybe_apply_runes()

    def _auto_accept_loop(self, interval):
        while self._running:
            try:
                self._auto_accept_tick()
            except Exception:
                # Parity with the async sibling in _auto_accept_loop_async: a
                # raising tick must never kill the loop, but it must leave a
                # traceback. This thread path is the non-AppLoop fallback and
                # had ZERO trace, the same blind spot as the 2026-07-04 silent
                # death. Kept at debug (not warning) deliberately: this loop
                # runs at 1 Hz, so a persistently failing tick would otherwise
                # flood the 3 MB log. core/log_setup.py sends DEBUG to file
                # unconditionally, so the traceback is still on disk.
                _log.debug("auto-accept tick raised; loop continues",
                           exc_info=True)
            time.sleep(interval)

    async def _auto_accept_loop_async(self, interval):
        while self._running:
            try:
                await asyncio.to_thread(self._auto_accept_tick)
            except asyncio.CancelledError:
                return
            except BaseException:  # noqa: BLE001
                # A tick raising ANYTHING other than an external cancel must
                # never kill the 1 Hz self-heal loop (layer-2, closes the
                # 8d2b4e2b caveat). exc_info gives a traceback if it ever fires
                # - the 2026-07-04 silent-death left no logged trace. Next
                # iteration re-runs _refresh_conn_if_changed(). Fail-soft.
                _log.debug("auto-accept tick raised; loop continues", exc_info=True)
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                return

    def _maybe_apply_runes(self) -> None:
        """Check champ select state and apply recommended runes on lock-in."""
        try:
            session = self.get_champ_select()
            if not isinstance(session, dict):
                # Not in champ select - reset tracking
                self._last_locked_champ = ""
                self._last_locked_mode  = ""
                return

            # Find our local cell ID
            local_cell = session.get("localPlayerCellId", -1)
            my_pick = None
            for pick in session.get("myTeam", []):
                if isinstance(pick, dict) and pick.get("cellId") == local_cell:
                    my_pick = pick
                    break
            if not my_pick:
                return

            champ_id = my_pick.get("championId", 0)
            action_type = my_pick.get("assignedPosition", "")
            completed = my_pick.get("completed", False)  # True when locked in

            if not champ_id or not completed:
                return

            # Resolve champion name from ID using DDragon
            champ_name = self._champ_id_to_name(champ_id)
            if not champ_name:
                return

            # Determine game mode from session
            game_mode = "sr"
            queue_id = session.get("gameData", {}).get("queue", {}).get("id", 0) if "gameData" in session else 0
            # ARAM-family queue IDs (canonical set: core/queue_modes.py):
            # 450 ARAM, 720 ARAM Clash, 920 Poro King, 2400 ARAM Mayhem
            # (item 87: Mayhem reports queueId 2400, NOT 920 - audit c10).
            if queue_id in (450, 720, 920, 2400):
                game_mode = "aram"

            if champ_name == self._last_locked_champ and game_mode == self._last_locked_mode:
                return  # already applied for this champion this session

            _log.info("Champ select locked: %s (mode=%s) - applying rune page", champ_name, game_mode)
            ok = self.apply_recommended_rune_page(champ_name, game_mode)
            if ok:
                self._last_locked_champ = champ_name
                self._last_locked_mode  = game_mode
            else:
                _log.debug("No rune rec for %s/%s - rune page not changed", champ_name, game_mode)
        except Exception as exc:
            _log.debug("_maybe_apply_runes: %s", exc)

    def _champ_id_to_name(self, champ_id: int) -> str:
        """Resolve champion ID to name using DDragon champion data."""
        try:
            p = _APP_DIR / "data" / "meta" / "ddragon_champions.json"
            if not p.exists():
                return ""
            data = json.loads(p.read_text(encoding="utf-8"))
            for name, entry in data.get("data", {}).items():
                if isinstance(entry, dict) and int(entry.get("key", -1)) == champ_id:
                    return entry.get("name", name)
        except Exception:
            pass
        return ""

    # === ARAM Champion Select ==================================================

    def get_champ_select(self):
        return self._request("GET", "/lol-champ-select/v1/session")

    def bench_swap(self, champ_id):
        return self._request("POST", f"/lol-champ-select/v1/session/bench/swap/{champ_id}")

    def get_bench_champions(self):
        session = self.get_champ_select()
        if session and isinstance(session, dict) and "benchChampions" in session:
            return [c.get("championId") for c in session["benchChampions"] if isinstance(c, dict)]
        return []

    # === TFT Team Planner ======================================================

    def import_team_code(self, code):
        return self._request("POST", "/lol-tft-team-planner/v1/team/import", {"code": code})

    def get_team_planner(self):
        return self._request("GET", "/lol-tft-team-planner/v1/team/local")

    def set_team(self, champions):
        return self._request("PUT", "/lol-tft-team-planner/v1/team/local", {"champions": champions})

    # === Rune Pages (AUDIT-PHASE-2-API-001) ====================================

    def get_current_rune_page(self) -> "dict | None":
        """
        GET /lol-perks/v1/currentpage
        Returns the currently active rune page dict, or None.
        Response includes: id, name, primaryStyleId, subStyleId, selectedPerkIds
        """
        return self._request("GET", "/lol-perks/v1/currentpage")

    def get_all_rune_pages(self) -> "list | None":
        """
        GET /lol-perks/v1/pages
        Returns all saved rune pages as a list, or None.
        """
        result = self._request("GET", "/lol-perks/v1/pages")
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            # Some LCU versions return {data: [...]}
            return result.get("data") or result.get("pages") or None
        return None

    def format_rune_page(self, page: "dict | None" = None) -> str:
        """
        Resolve a rune page dict to a readable summary string.
        If page is None, fetches the current page first.

        Returns strings like:
          "Lethal Tempo | Precision / Resolve (Bone Plating, Revitalize)"
          "[ADC-Jinx] Lethal Tempo | Precision / Domination"
          "" on failure

        Uses local ddragon_runes.json for ID->name resolution.
        Falls back to raw IDs if the file is unavailable.
        """
        if page is None:
            page = self.get_current_rune_page()
        if not isinstance(page, dict):
            return ""

        id_map = self._build_rune_id_map()
        perk_ids = page.get("selectedPerkIds", [])
        page_name = page.get("name", "")

        if not perk_ids:
            return page_name or ""

        # selectedPerkIds layout:
        #   [0]    keystone
        #   [1-3]  primary tree rows 1-3
        #   [4-5]  secondary tree 2 chosen perks
        #   [6-8]  stat shards
        keystone = id_map.get(perk_ids[0], str(perk_ids[0])) if perk_ids else "?"
        pri_id   = page.get("primaryStyleId", 0)
        sec_id   = page.get("subStyleId",     0)
        pri_tree = id_map.get(pri_id, "")
        sec_tree = id_map.get(sec_id, "")

        sec_rune_names = [
            id_map.get(pid, str(pid))
            for pid in perk_ids[4:6]
            if pid
        ]
        sec_detail = f" ({', '.join(sec_rune_names)})" if sec_rune_names else ""

        parts = [keystone]
        if pri_tree:
            parts.append(pri_tree)
        if sec_tree:
            parts.append(f"{sec_tree}{sec_detail}")

        summary = " | ".join(parts[:1])
        if len(parts) > 1:
            summary += " - " + " / ".join(parts[1:])

        if page_name:
            summary = f"[{page_name}] {summary}"

        return summary.strip()


    # === Rune Page Write (auto-apply recommended page) =========================

    # Default perk ID configs for common ADC setups.
    # Format: (keystone_name, primary_tree, secondary_tree) -> {primaryStyleId, subStyleId, selectedPerkIds}
    # selectedPerkIds layout: [keystone, pri_r1, pri_r2, pri_r3, sec_r1, sec_r2, shard1, shard2, shard3]
    # Stat shards: 5005=AS, 5008=Adaptive, 5002=Armor, 5003=MR, 5001=Health
    _PERK_CONFIGS = {
        ("Lethal Tempo",   "Precision", "Domination"): {
            "primaryStyleId": 8000, "subStyleId": 8100,
            "selectedPerkIds": [8008, 9111, 9104, 8014, 8139, 8135, 5005, 5008, 5002]},
        ("Lethal Tempo",   "Precision", "Sorcery"): {
            "primaryStyleId": 8000, "subStyleId": 8200,
            "selectedPerkIds": [8008, 9111, 9104, 8014, 8226, 8210, 5005, 5008, 5002]},
        ("Lethal Tempo",   "Precision", "Resolve"): {
            "primaryStyleId": 8000, "subStyleId": 8400,
            "selectedPerkIds": [8008, 9111, 9104, 8014, 8444, 8453, 5005, 5008, 5002]},
        ("Lethal Tempo",   "Precision", "Inspiration"): {
            "primaryStyleId": 8000, "subStyleId": 8300,
            "selectedPerkIds": [8008, 9111, 9104, 8014, 8304, 8347, 5005, 5008, 5002]},
        ("Fleet Footwork", "Precision", "Sorcery"): {
            "primaryStyleId": 8000, "subStyleId": 8200,
            "selectedPerkIds": [8021, 9111, 9104, 8014, 8226, 8210, 5005, 5008, 5002]},
        ("Fleet Footwork", "Precision", "Domination"): {
            "primaryStyleId": 8000, "subStyleId": 8100,
            "selectedPerkIds": [8021, 9111, 9104, 8014, 8139, 8135, 5005, 5008, 5002]},
        ("Fleet Footwork", "Precision", "Resolve"): {
            "primaryStyleId": 8000, "subStyleId": 8400,
            "selectedPerkIds": [8021, 9111, 9104, 8014, 8444, 8453, 5005, 5008, 5002]},
        ("Press the Attack", "Precision", "Domination"): {
            "primaryStyleId": 8000, "subStyleId": 8100,
            "selectedPerkIds": [8005, 9111, 9104, 8014, 8139, 8135, 5005, 5008, 5002]},
        ("Press the Attack", "Precision", "Sorcery"): {
            "primaryStyleId": 8000, "subStyleId": 8200,
            "selectedPerkIds": [8005, 9111, 9104, 8014, 8226, 8210, 5005, 5008, 5002]},
        ("Conqueror",      "Precision", "Resolve"): {
            "primaryStyleId": 8000, "subStyleId": 8400,
            "selectedPerkIds": [8010, 9111, 9104, 8014, 8444, 8453, 5005, 5008, 5001]},
        ("Conqueror",      "Precision", "Domination"): {
            "primaryStyleId": 8000, "subStyleId": 8100,
            "selectedPerkIds": [8010, 9111, 9104, 8014, 8139, 8135, 5005, 5008, 5001]},
        ("Arcane Comet",   "Sorcery",   "Precision"): {
            "primaryStyleId": 8200, "subStyleId": 8000,
            "selectedPerkIds": [8229, 8226, 8210, 8237, 9111, 9104, 5008, 5008, 5002]},
        ("Arcane Comet",   "Sorcery",   "Domination"): {
            "primaryStyleId": 8200, "subStyleId": 8100,
            "selectedPerkIds": [8229, 8226, 8210, 8237, 8126, 8135, 5008, 5008, 5002]},
        ("Arcane Comet",   "Sorcery",   "Inspiration"): {
            "primaryStyleId": 8200, "subStyleId": 8300,
            "selectedPerkIds": [8229, 8226, 8210, 8237, 8304, 8347, 5008, 5008, 5002]},
        ("Summon Aery",    "Sorcery",   "Precision"): {
            "primaryStyleId": 8200, "subStyleId": 8000,
            "selectedPerkIds": [8214, 8226, 8210, 8237, 9111, 9104, 5008, 5008, 5002]},
        ("Summon Aery",    "Sorcery",   "Domination"): {
            "primaryStyleId": 8200, "subStyleId": 8100,
            "selectedPerkIds": [8214, 8226, 8210, 8237, 8139, 8135, 5008, 5008, 5002]},
        ("Electrocute",    "Domination","Sorcery"): {
            "primaryStyleId": 8100, "subStyleId": 8200,
            "selectedPerkIds": [8112, 8139, 8137, 8135, 8226, 8210, 5008, 5008, 5002]},
        ("Dark Harvest",   "Domination","Sorcery"): {
            "primaryStyleId": 8100, "subStyleId": 8200,
            "selectedPerkIds": [8128, 8139, 8137, 8135, 8226, 8210, 5008, 5008, 5002]},
        ("Hail of Blades", "Domination","Precision"): {
            "primaryStyleId": 8100, "subStyleId": 8000,
            "selectedPerkIds": [9923, 8139, 8137, 8135, 9111, 9104, 5005, 5008, 5002]},
        ("Aftershock",     "Resolve",   "Precision"): {
            "primaryStyleId": 8400, "subStyleId": 8000,
            "selectedPerkIds": [8439, 8463, 8429, 8451, 9111, 9104, 5005, 5008, 5001]},
        ("Grasp of the Undying", "Resolve", "Precision"): {
            "primaryStyleId": 8400, "subStyleId": 8000,
            "selectedPerkIds": [8437, 8446, 8429, 8451, 9111, 9104, 5005, 5008, 5001]},
    }
    _RC_PAGE_PREFIX = "RC - "

    def apply_recommended_rune_page(self, champion: str, mode: str = "aram") -> bool:
        """
        Load the recommended rune page for champion+mode from meta_build JSON,
        resolve to perk IDs, delete existing RC-managed pages, and create + activate
        a new page. Returns True on success.
        """
        if not self._port or not self._auth:
            _log.debug("apply_recommended_rune_page: LCU not connected")
            return False
        try:
            rec = self._load_rune_rec(champion, mode)
            if not rec:
                _log.debug("apply_recommended_rune_page: no rec for %s/%s", champion, mode)
                return False

            keystone = rec.get("keystone", "")
            primary  = rec.get("primary_tree", "")
            secondary = rec.get("secondary_tree", "")
            if not keystone or not primary:
                return False

            cfg = self._PERK_CONFIGS.get((keystone, primary, secondary))
            if not cfg:
                # Try flipping secondary
                cfg = self._PERK_CONFIGS.get((keystone, primary, "Domination"))
            if not cfg:
                _log.debug("apply_recommended_rune_page: no perk config for %s / %s / %s",
                           keystone, primary, secondary)
                return False

            page_name = f"{self._RC_PAGE_PREFIX}{champion} ({mode.upper()})"

            # Delete existing RC pages to stay under page limit
            pages = self.get_all_rune_pages() or []
            for p in pages:
                if isinstance(p, dict) and str(p.get("name", "")).startswith(self._RC_PAGE_PREFIX):
                    self._request("DELETE", f"/lol-perks/v1/pages/{p['id']}")
                    _log.debug("Deleted stale RC rune page: %s (id=%s)", p.get("name"), p.get("id"))

            # Create new page
            payload = {
                "name":           page_name,
                "primaryStyleId": cfg["primaryStyleId"],
                "subStyleId":     cfg["subStyleId"],
                "selectedPerkIds": cfg["selectedPerkIds"],
                "current":        True,
                "order":          0,
            }
            result = self._request("POST", "/lol-perks/v1/pages", payload)
            if not isinstance(result, dict):
                _log.warning("apply_recommended_rune_page: POST failed for %s", champion)
                return False

            new_id = result.get("id")
            if new_id:
                self._request("PUT", "/lol-perks/v1/currentpage", {"id": new_id})
                _log.info("Rune page applied: %s (id=%s) - %s | %s / %s",
                          page_name, new_id, keystone, primary, secondary)
            return True
        except Exception as exc:
            _log.error("apply_recommended_rune_page: %s", exc)
            return False

    def _load_rune_rec(self, champion: str, mode: str) -> "dict | None":
        """Load rune recommendation dict for champion from meta_build JSON."""
        try:
            _ARAM_MODES = {"aram", "kiwi", "aram_5v5", "aram_mayhem", "mayhem"}
            fname = (
                "rune_recommendations_aram.json"
                if mode.lower() in _ARAM_MODES
                else "rune_recommendations_sr.json"
            )
            p = _APP_DIR / "data" / "meta_build" / fname
            if not p.exists():
                return None
            data = json.loads(p.read_text(encoding="utf-8"))
            return data.get(champion)
        except Exception:
            return None


    def _build_rune_id_map(self) -> dict:
        """
        Build perk ID -> display name lookup from local DDragon rune data.
        Result is cached on first call (data is static per patch).
        """
        if self._rune_id_map:
            return self._rune_id_map
        try:
            p = _APP_DIR / "data" / "meta" / "ddragon_runes.json"
            trees = json.loads(p.read_text(encoding="utf-8"))
            result: dict = {}
            for tree in trees:
                if not isinstance(tree, dict):
                    continue
                result[tree["id"]] = tree.get("name", "")
                for slot in tree.get("slots", []):
                    for rune in slot.get("runes", []):
                        if isinstance(rune, dict) and rune.get("id"):
                            result[rune["id"]] = rune.get("name", str(rune["id"]))
            self._rune_id_map = result
            _log.debug("Rune ID map loaded: %d entries", len(result))
        except Exception as exc:
            _log.debug("_build_rune_id_map: %s", exc)
        return self._rune_id_map
