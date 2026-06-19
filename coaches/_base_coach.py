"""
coaches/_base_coach.py - AUDIT-PHASE-2-ARCH-002

Shared utilities AND base class for ARAM, Arena, and Brawl coaches.

Section 1: Utility functions (unchanged from Phase 2 session 4-5)
Section 2: BaseCoach ABC - full lifecycle base for all non-TFT coaches

ARCH-002 (full) - 2026-04-18 (T2 #6 update - overlay methods removed 2026-05-01)
  Extracted: __init__, submit_state, reset_state, shutdown,
             _poll_loop, _vision_loop, _maybe_coach,
             _ensure_data, _write_blank_artifact, _fetch_game_data
  Each mode overrides: _DATA_FILENAME, _MODE_NAME, _blank_artifact_data(),
             _parse_raw_state(), _run_coach(), _run_vision()
  Optional hooks: _init_extra(), _reset_extra(), _on_state_received(),
             _fast_path_trigger(), _VISION_INTERVAL, _DEBOUNCE_S,
             _FAST_PATH_MIN_S, _HP_DROP_THRESHOLD
"""
import abc
import asyncio
import json
import logging
import math
import os
import re
import ssl
import threading
import time
import urllib.request
from pathlib import Path

_log = logging.getLogger("rc.coaches.base")

# Root directory (two levels up from coaches/)
_APP_DIR = Path(__file__).parent.parent


# ==============================================================================
# SECTION 1 - Utility functions
# ==============================================================================

def read_api_key(app_dir: Path = _APP_DIR) -> str:
    """Load Anthropic API key from file or environment."""
    p = app_dir / "API-Key-Claude.txt"
    if p.exists():
        try:
            k = p.read_text(encoding="utf-8").strip()
            if k.startswith("sk-ant-"):
                return k
        except Exception:  # noqa: BLE001
            pass
    return os.environ.get("ANTHROPIC_API_KEY", "")


def load_json(path: Path) -> dict:
    """Load a JSON file safely. Returns {} on any error."""
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        _log.debug("load_json %s: %s", path.name, exc)
    return {}


# Serializes same-process writers (coach thread + vision worker target the
# same artifact and share one .tmp name; unserialized write_text calls can
# interleave and corrupt the tmp before replace). Cross-process safety still
# comes from the atomic replace itself.
_SAFE_WRITE_LOCK = threading.Lock()


def safe_write(path: Path, data: dict) -> None:
    """Atomic JSON write via .tmp -> replace.
    Retries up to 3x on Windows WinError 5 (Defender/lock races).
    """
    tmp = path.with_suffix(".tmp")
    with _SAFE_WRITE_LOCK:
        try:
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            _log.error("safe_write write %s: %s", path.name, exc)
            return
        for attempt in range(3):
            try:
                tmp.replace(path)
                return
            except PermissionError:
                if attempt == 2:
                    _log.warning("safe_write %s: gave up after 3 retries", path.name)
                    try: tmp.unlink(missing_ok=True)
                    except Exception: pass  # noqa: BLE001
                else:
                    import time as _tw; _tw.sleep(0.015 * (2 ** attempt))
            except Exception as exc:  # noqa: BLE001
                _log.error("safe_write %s: %s", path.name, exc)
                return


def mirror_live_stats(payload: dict, state: dict) -> None:
    """Mirror raw live-game stats into a coaching JSON payload.

    The dashboard's WS push channel receives the full coaching JSON; its
    JS reads `p.cs / p.kda / p.level / p.gold / p.game_time_s` for the
    top-bar pills (rendered by the live dashboard JS). Without these in the
    per-mode coaching JSON, the `typeof p.X === "number"` guards hide
    the pills (-- symptom; s32 finding).

    None-skip semantics: only writes keys actually present on `state`,
    so absent fields don't overwrite anything. Mode coaches use
    `game_seconds` while dashboard JS reads `game_time_s` - mapped here.
    """
    for k in ("cs", "kda", "level", "gold"):
        v = state.get(k)
        if v is not None:
            payload[k] = v
    if "game_time_s" not in payload:
        gs = state.get("game_seconds")
        if gs is not None:
            payload["game_time_s"] = gs


def parse_field(text: str, key: str) -> str:
    """Extract a single labeled field from coach response text."""
    for line in text.strip().splitlines():
        s = line.strip()
        if s.lower().startswith(key.lower() + ":"):
            return s[len(key) + 1:].strip()
    return ""


def parse_fields(text: str, keys: list) -> dict:
    """
    Extract multiple labeled fields from coach response text.
    Strips markdown bold/headers before parsing.

    Positional fallback (2026-04-26): when Haiku occasionally omits the
    "Label:" prefixes and just emits values one-per-line in the same
    order the prompt declared, map them positionally so the cycle isn't
    a total loss. Triggered only when the labeled pass returned 0 fields
    AND we have at least len(keys)//2 non-empty lines.
    """
    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)
    text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)
    fields: dict = {}
    raw_lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    for line in raw_lines:
        for key in keys:
            if line.lower().startswith(key + ":"):
                val = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', line[len(key) + 1:].strip())
                fields[key] = val[:220]
                break
    if not fields and len(raw_lines) >= max(2, len(keys) // 2):
        # Positional fallback: map lines to keys in declared order.
        for key, line in zip(keys, raw_lines):
            fields[key] = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', line)[:220]
    return fields


def finite(v, default: float = 0.0) -> float:
    """Coerce a Live Client numeric to a finite float.

    json.loads accepts the non-standard NaN/Infinity tokens, and int() on
    a NaN/inf float raises (ValueError/OverflowError) - which silently
    killed a whole parse tick. Non-numeric or non-finite input collapses
    to `default`.
    """
    try:
        f = float(v)
    except (TypeError, ValueError):
        return float(default)
    return f if math.isfinite(f) else float(default)


def make_ssl_ctx() -> ssl.SSLContext:
    """Create an SSL context suitable for Riot's local API (self-signed cert)."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _silence_chatty_loggers() -> None:
    """Damp PIL DEBUG (~3500/4700 lines/day) + lcu_client lockfile INFO
    spam (~1/sec post-migration; LCU lives on Game-PC not Legion).
    Idempotent - safe to call multiple times. Module-level call below
    runs once at first import."""
    import logging as _lg
    for name in ("PIL", "PIL.PngImagePlugin", "PIL.Image", "PIL.JpegImagePlugin"):
        _lg.getLogger(name).setLevel(_lg.WARNING)
    # lcu_client.py spams "LCU lockfile not found - client may not be running"
    # at INFO every poll. Bump to WARNING so the message only surfaces if
    # something actually goes wrong (the WARNING level on this logger covers
    # the real failures we'd want to see).
    _lg.getLogger("rc.lcu").setLevel(_lg.WARNING)


_silence_chatty_loggers()


def fetch_game_data(ssl_ctx: "ssl.SSLContext | None" = None) -> "dict | None":
    """
    Fetch /allgamedata from the Riot Live Client API.
    Returns parsed dict or None if the API is not responding.
    """
    ctx = ssl_ctx or make_ssl_ctx()
    try:
        from core.game_host import GAME_HOST
        req = urllib.request.Request(
            f"https://{GAME_HOST}:2999/liveclientdata/allgamedata"
        )
        with urllib.request.urlopen(req, context=ctx, timeout=2) as r:
            return json.loads(r.read())
    except Exception:  # noqa: BLE001
        return None


# ==============================================================================
# SECTION 2 - BaseCoach ABC
# ==============================================================================

def fmt_abilities(abilities: dict) -> str:
    """Format ability cooldown dict for Haiku prompt.
    Input: {q: {name, cooldown, level}, ...}
    Output: Q:Tumble(lv3) cd=0.5s | W:SilverBolts(lv3) | ...
    """
    if not abilities:
        return "unknown"
    parts = []
    for slot in ("q", "w", "e", "r"):
        ab = abilities.get(slot)
        if not ab:
            continue
        name = ab.get("name", slot.upper())
        cd   = ab.get("cooldown")
        lvl  = ab.get("level")
        part = f"{slot.upper()}:{name}"
        if lvl is not None:
            part += f"(lv{lvl})"
        if cd is not None:
            part += f" cd={cd}s"
        parts.append(part)
    return " | ".join(parts) or "unknown"


class BaseCoach(abc.ABC):
    """
    AUDIT-PHASE-2-ARCH-002 (full) - 2026-04-18

    Shared lifecycle base for ARAM, Arena, and Brawl coaches.
    Owns: __init__, poll/vision loops, debounce, overlay polling, teardown.

    Subclasses MUST set:
        GAME_MODES      tuple[str, ...]   mode strings this coach handles
        _MODE_NAME      str               logging / thread label
        _DATA_FILENAME  str               output JSON filename under data/

    Subclasses MAY override tunables (class attrs):
        _VISION_INTERVAL    float   seconds between vision scans   (default 15)
        _DEBOUNCE_S         float   normal coaching debounce        (default 8)
        _FAST_PATH_MIN_S    float   fast-path minimum gap           (default 5)
        _HP_DROP_THRESHOLD  float   HP% drop that triggers fast path (default 20)

    Subclasses MUST implement abstract methods:
        _blank_artifact_data()      -> dict
        _parse_raw_state(raw)       -> dict
        _run_coach(state)           -> None
        _run_vision()               -> None

    Subclasses MAY override hooks:
        _init_extra()               called before threads start (set mode state)
        _reset_extra()              called in reset_state (clear mode counters)
        _on_state_received(state)   called after parse, before storage
        _fast_path_trigger(state, prev) -> bool  custom debounce bypass
    """

    # -- Class attrs (override in subclass) ------------------------------------
    GAME_MODES:            tuple = ()
    _MODE_NAME:            str   = "base"
    _DATA_FILENAME:        str   = ""
    _VISION_INTERVAL:      float = 15.0
    _DEBOUNCE_S:           float = 8.0
    _FAST_PATH_MIN_S:      float = 5.0
    _HP_DROP_THRESHOLD:    float = 20.0

    # -- Lifecycle -------------------------------------------------------------

    def __init__(self, data_file, debug: bool = False):
        self._data_file         = Path(data_file)
        self._debug             = debug
        self._running           = False
        self._overlay: dict     = {}
        self._lock              = threading.Lock()
        self._last_state: dict  = {}
        self._last_coach: float = 0.0
        self._vision_state: dict = {}
        self._last_vision: float = 0.0
        self._last_force_check: float = 0.0

        self._out = self._data_file.parent / self._DATA_FILENAME

        # Hook: subclass sets mode-specific state before threads launch
        self._init_extra()

        self._ensure_data()
        self._api_key = read_api_key(_APP_DIR)
        self._client = None
        if self._api_key:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self._api_key)

        self._running = True
        _mn = self._MODE_NAME.capitalize()
        # T2 #8 C3 (2026-05-01): poll/vision loops run on the AppLoop event
        # loop instead of dedicated daemon threads. Falls back to threads if
        # the AppLoop isn't running (tests, standalone scripts).
        try:
            from app._loop import get_loop as _get_loop
            _sched = _get_loop()
        except Exception:  # noqa: BLE001
            _sched = None
        if _sched is not None:
            _sched.spawn_task(self._poll_loop())
            _sched.spawn_task(self._vision_loop())
        else:
            threading.Thread(
                target=lambda: asyncio.run(self._poll_loop()),
                daemon=True, name=f"{_mn}Poll",
            ).start()
            threading.Thread(
                target=lambda: asyncio.run(self._vision_loop()),
                daemon=True, name=f"{_mn}Vision",
            ).start()
        try:
            from core.hotkeys import register_coach as _hk_reg
            _hk_reg(self)
        except Exception:  # noqa: BLE001
            pass
        logging.getLogger(f"rc.coaches.{self._MODE_NAME}").info(
            "%s Coach started", _mn
        )

    def submit_state(self, state: dict) -> None:
        pass

    def reset_state(self) -> None:
        self._last_state = {}
        self._last_coach = 0.0
        self._reset_extra()
        self._write_blank_artifact()

    def shutdown(self) -> None:
        self._running = False
        try:
            from core.hotkeys import unregister_coach as _hk_unreg
            _hk_unreg(self)
        except Exception:  # noqa: BLE001
            pass
        logging.getLogger(f"rc.coaches.{self._MODE_NAME}").info(
            "%s Coach shutdown", self._MODE_NAME.capitalize()
        )

    # -- Loops -----------------------------------------------------------------

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                self._poll_tick()
            except Exception as exc:  # noqa: BLE001
                logging.getLogger(f"rc.coaches.{self._MODE_NAME}").debug(
                    "%s poll: %s", self._MODE_NAME, exc
                )
            await asyncio.sleep(1.5)

    def _poll_tick(self) -> None:
        """One synchronous poll iteration (extracted for testability).

        Captures the PREVIOUS poll state before overwriting _last_state so
        _fast_path_trigger compares against genuinely-prior data. Pre-fix
        the assignment happened first, making prev identical to state and
        leaving the hp-drop / new-kill fast path dead (audit cycle 9).
        """
        raw = self._fetch_game_data()
        if not raw:
            return
        state = self._parse_raw_state(raw)
        if not state:
            return
        self._on_state_received(state)
        prev = self._last_state
        self._last_state = state
        self._maybe_coach(state, prev)

    async def _vision_loop(self) -> None:
        _force_file = _APP_DIR / "data" / "force_scan.json"
        while self._running:
            try:
                now = time.time()
                forced = False
                try:
                    if _force_file.exists():
                        _ft = json.loads(
                            _force_file.read_text(encoding="utf-8")
                        ).get("force", 0)
                        if _ft > self._last_force_check:
                            self._last_force_check = _ft
                            forced = True
                except Exception:  # noqa: BLE001
                    pass
                if forced or now - self._last_vision >= self._VISION_INTERVAL:
                    self._last_vision = now
                    # Spend-gate: skip the Sonnet vision scan when the
                    # "vision" gate is disabled (Settings kill-switch).
                    # Re-read each tick so a toggle applies live.
                    _vision_off = False
                    try:
                        from core.cost_tracker import get_tracker as _gt
                        _vision_off = _gt().gate_disabled("vision")
                    except Exception:  # noqa: BLE001
                        pass
                    if not _vision_off:
                        # _run_vision does blocking HTTP (vision relay + Sonnet);
                        # marshal to a thread so we don't stall the loop.
                        await asyncio.to_thread(self._run_vision)
            except Exception as exc:  # noqa: BLE001
                logging.getLogger(f"rc.coaches.{self._MODE_NAME}").debug(
                    "%s vision: %s", self._MODE_NAME, exc
                )
            await asyncio.sleep(3.0)

    def _maybe_coach(self, state: dict, prev: "dict | None" = None) -> None:
        # AUDIT 2026-04-28 (2.2): per-mode kill switch - toggled from the
        # dashboard ops tab via /api/coach/toggle.
        try:
            from core.cost_tracker import get_tracker as _gt
            if _gt().coach_disabled(self._MODE_NAME):
                return
        except Exception:  # noqa: BLE001
            pass
        # AUDIT 2026-04-28 (5.4): hard daily-budget gate.
        try:
            from core.cost_tracker import get_tracker as _gt
            if not _gt().allow_call():
                return
        except Exception:  # noqa: BLE001
            pass
        now      = time.time()
        # prev is supplied by _poll_tick (the state from the PRIOR poll);
        # fall back to _last_state only for legacy direct callers.
        prev     = (prev if prev is not None else self._last_state) or {}
        fast     = self._fast_path_trigger(state, prev)
        debounce = now - self._last_coach

        if fast and debounce > self._FAST_PATH_MIN_S:
            pass  # fall through to coaching
        elif debounce < self._DEBOUNCE_S:
            return

        # _lock guards only the spawn-decision moment (last_coach update +
        # task spawn). It is NOT held across the actual coaching call -
        # _run_coach is dispatched to a worker thread via asyncio.to_thread
        # and may take seconds. Real serialization comes from the debounce
        # check on _last_coach above; the lock just prevents two near-
        # simultaneous calls into _maybe_coach from both passing the
        # debounce window before either has bumped _last_coach.
        if not self._lock.acquire(blocking=False):
            return
        try:
            self._last_coach = now
            # A3 (DS-coach): fire-and-forget shadow-log of the deterministic
            # anti-tank + scaling power-curve hints for this matchup. Pure
            # substrate accrual - never touches the prompt, UI, or coach output.
            self._shadow_log_hints(state)
            _mn = self._MODE_NAME.capitalize()
            _state_copy = dict(state)
            try:
                from app._loop import get_loop as _get_loop
                _sched = _get_loop()
            except Exception:  # noqa: BLE001
                _sched = None
            if _sched is not None:
                _sched.spawn_task(asyncio.to_thread(self._run_coach, _state_copy))
            else:
                threading.Thread(
                    target=self._run_coach, args=(_state_copy,),
                    daemon=True, name=f"{_mn}Coach",
                ).start()
        finally:
            self._lock.release()

    def _ensure_data(self) -> None:
        try:
            self._out.parent.mkdir(parents=True, exist_ok=True)
            if not self._out.exists():
                self._write_blank_artifact()
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(f"rc.coaches.{self._MODE_NAME}").warning(
                "%s data init: %s", self._MODE_NAME, exc
            )

    def _write_blank_artifact(self) -> None:
        try:
            self._out.parent.mkdir(parents=True, exist_ok=True)
            safe_write(self._out, self._blank_artifact_data())
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(f"rc.coaches.{self._MODE_NAME}").warning(
                "%s blank artifact: %s", self._MODE_NAME, exc
            )

    def _fetch_game_data(self) -> "dict | None":
        """Read latest /allgamedata snapshot from the shared cache.

        Pre-2026-05-01 each mode coach hit the relay endpoint on its own
        1.5s thread; consolidated into core.liveclient_cache (one shared
        0.5s background poll). Returns None when the cache is empty or
        the snapshot is older than 12s (match game_reader.RELAY_MAX_AGE_S).
        """
        from core.liveclient_cache import get as _lc_get
        snap = _lc_get()
        if snap.data is None or snap.age_s > 12.0:
            return None
        return snap.data

    # -- Hooks (override as needed) --------------------------------------------

    def _init_extra(self) -> None:
        """Called in __init__ before threads start. Override for mode state."""
        pass

    def _reset_extra(self) -> None:
        """Called in reset_state. Override to reset mode-specific counters."""
        pass

    def _on_state_received(self, state: dict) -> None:
        """Called after _parse_raw_state, before _last_state assignment."""
        pass

    def _fast_path_trigger(self, state: dict, prev: dict) -> bool:
        """Return True to bypass normal debounce (FAST_PATH_MIN_S still applies)."""
        hp_drop  = (prev.get("hp_pct", 100) - state.get("hp_pct", 100)) >= self._HP_DROP_THRESHOLD
        new_kill = len(state.get("dead_enemies", [])) > len(prev.get("dead_enemies", []))
        return hp_drop or new_kill

    def _record_coach_call(self, resp, *,
                           system: str = "",
                           user: str = "",
                           t0_perf: "float | None" = None,
                           model: "str | None" = None,
                           purpose: "str | None" = None,
                           extra: "dict | None" = None) -> None:
        """AUDIT 2026-04-29 (in-game audit gap A): wire mode-coach
        Anthropic responses into the same telemetry the SR coach uses -
        cost ledger (5.8) + coach trace (2.5). Subclasses call this
        immediately after `resp = self._client.messages.create(...)`.

        Best-effort: any failure in extracting usage / writing the file
        is swallowed so a telemetry hiccup never breaks coaching.
        """
        try:
            import time as _time
            usage = getattr(resp, "usage", None)
            tin  = getattr(usage, "input_tokens", 0) or 0 if usage else 0
            tout = getattr(usage, "output_tokens", 0) or 0 if usage else 0
            cr   = getattr(usage, "cache_read_input_tokens", 0) or 0 if usage else 0
            cw   = getattr(usage, "cache_creation_input_tokens", 0) or 0 if usage else 0
            mdl  = model or getattr(resp, "model", "") or ""
            latency_ms = int((_time.perf_counter() - t0_perf) * 1000) if t0_perf is not None else 0
            try:
                from core.cost_tracker import get_tracker as _gt
                _gt().record_call(
                    model=mdl, input_tokens=tin, output_tokens=tout,
                    cache_read=cr, cache_write=cw,
                    purpose=purpose or f"{self._MODE_NAME}_coach",
                )
            except Exception as exc:  # noqa: BLE001
                _log.debug("cost_tracker record_call: %s", exc)
            try:
                from core.coach_trace import append as _trace_append
                # Pull response text defensively - content may be empty.
                resp_text = ""
                content = getattr(resp, "content", None) or []
                if content and hasattr(content[0], "text"):
                    resp_text = content[0].text or ""
                _trace_append(
                    mode=self._MODE_NAME,
                    model=mdl,
                    system_prompt=system or "",
                    user_prompt=user or "",
                    response=resp_text,
                    latency_ms=latency_ms,
                    tokens_in=tin, tokens_out=tout,
                    cache_read=cr, cache_write=cw,
                    extra=extra,
                )
            except Exception as exc:  # noqa: BLE001
                _log.debug("coach_trace append: %s", exc)
        except Exception as exc:  # noqa: BLE001
            _log.debug("_record_coach_call swallowed: %s", exc)

    def _shadow_log_hints(self, state: dict) -> None:
        """Fail-soft shadow-log of the deterministic DS-coach hints (A3).

        Records the anti-tank build hint (vs high-HP enemy comps) and the
        scaling power-curve for the current matchup to
        data/ds_coach_hints_shadow.jsonl alongside live coaching, but WITHOUT
        altering the Haiku prompt or the dashboard. This is the validation
        substrate (the champ-select Haiku-elimination shadow-log pattern): the
        deterministic hints accrue against real games so they can be surfaced
        into coach context later, once validated against the log. Champion
        name-forms are bridged to canonical DDragon ids (the DS registries key
        on those). NEVER raises - it runs in the live coach dispatch path.
        """
        try:
            from core.archetype_picks import canonical_champion_id as _canon

            def _cid(raw: str) -> str:
                try:
                    return _canon(raw) or raw
                except Exception:  # noqa: BLE001
                    return raw

            my_champ = _cid(state.get("champion") or "")
            if not my_champ:
                return
            enemies: list = []
            for e in (state.get("enemies") or []):
                if not isinstance(e, dict):
                    continue
                raw = e.get("name") or e.get("champion") or e.get("championName") or ""
                if raw:
                    enemies.append(_cid(raw))
            game_time_s = state.get("game_seconds")
            if game_time_s is None:
                game_time_s = state.get("game_time_s")
            from core.ds_coach_shadow import log_coach_hints
            log_coach_hints(
                self._MODE_NAME, my_champ, enemies, game_time_s=game_time_s
            )
        except Exception as exc:  # noqa: BLE001
            _log.debug("_shadow_log_hints swallowed: %s", exc)

    # -- Abstract --------------------------------------------------------------

    @abc.abstractmethod
    def _blank_artifact_data(self) -> dict:
        """Return the initial/blank artifact dict for this mode."""
        ...

    @abc.abstractmethod
    def _parse_raw_state(self, raw: dict) -> dict:
        """Parse /allgamedata dict -> coaching state dict."""
        ...

    @abc.abstractmethod
    def _run_coach(self, state: dict) -> None:
        """Execute a coaching API call and write result to artifact file."""
        ...

    @abc.abstractmethod
    def _run_vision(self) -> None:
        """Execute a vision scan and write partial result to artifact file."""
        ...
