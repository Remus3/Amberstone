# arch: CoachIntegration - SR coaching class (Haiku + cache + DS) | section=coaching | frozen=no
"""CoachIntegration: SR coaching dispatch, budget gating, CacheEngine, atomic writers."""

import os
import json
import time
import logging
import threading
try:
    import anthropic
    _APITimeoutError = anthropic.APITimeoutError
    _APIConnectionError = anthropic.APIConnectionError
except ImportError:
    anthropic = None  # type: ignore[assignment]
    _APITimeoutError = Exception
    _APIConnectionError = Exception
from collections import deque
from datetime import datetime
from pathlib import Path

from ._profiles import CHAMPION_PROFILES, GENERIC_PROFILE, HAS_ROLE_PROFILES, get_role_profile
from ._sr_prompt import (
    SR_SYSTEM_PROMPT, _load_sr_rune_rec, _load_sr_build_note, _load_lane_matchup_note,
    _build_user_prompt, WaveTracker,
)

logger = logging.getLogger("coach")

class CoachIntegration:
    def __init__(self, data_file: Path, debug: bool = False):
        self.data_file = Path(data_file)
        self.debug = debug

        self._debounce_s = 3.0
        self._timeout_s  = 20
        self._model = "claude-haiku-4-5-20251001"
        self._patch = "current"

        cfg_path = Path(__file__).parent.parent / "config" / "coach_settings.json"
        if cfg_path.exists():
            try:
                cfg = json.loads(cfg_path.read_text())
                self._debounce_s = cfg.get("debounce_seconds", self._debounce_s)
                self._timeout_s  = cfg.get("timeout_seconds",  self._timeout_s)
                self._model      = cfg.get("model",            self._model)
            except Exception as _e:  # QUAL-002
                logger.debug("coach_settings reload: %s", _e)

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            logger.warning("ANTHROPIC_API_KEY not set - auto-coaching disabled")
        self._client = anthropic.Anthropic(api_key=api_key) if (api_key and anthropic) else None

        db_path = Path(__file__).parent.parent / "data" / "decisions.db"
        from modules.cache_engine import CacheEngine
        self._cache = CacheEngine(db_path)

        self._wave = WaveTracker()
        self._lock = threading.Lock()
        self._last_coach_time = 0.0
        self._last_state: dict = {}
        self._last_submitted_state: dict = {}
        self._pending = False

        logger.info("CoachIntegration ready (api_key=%s)", "set" if api_key else "MISSING")

    def submit_state(self, game_state: dict):
        """Called from _apply_auto_fields every 2s. Non-blocking."""
        if not self._client:
            return
        # AUDIT 2026-04-28 (2.2): per-mode kill switch.
        try:
            from core.cost_tracker import get_tracker as _gt
            if _gt().coach_disabled("sr"):
                return
        except Exception:
            pass
        if not self._should_coach(game_state):
            return
        self._last_submitted_state = game_state
        self._last_coach_time = time.time()
        t = threading.Thread(target=self._run_safe, args=(game_state,),
                             daemon=True, name="CoachCall")
        t.start()

    def request_now(self, game_state: dict):
        """Force immediate coaching call - from context menu."""
        if not self._client or not game_state:
            return
        self._last_coach_time = time.time()
        t = threading.Thread(target=self._run_safe, args=(game_state,),
                             daemon=True, name="CoachForced")
        t.start()

    def flag_last_bad(self):
        if self._last_state:
            self._cache.flag_bad(self._last_state)
            logger.info("Bad advice flagged for %s", self._last_state.get("champion"))

    def reset_state(self):
        self._last_submitted_state = {}
        self._last_state = {}
        self._last_coach_time = 0.0
        self._pending = False
        self._wave = WaveTracker()
        try:
            blank = self._default_data()
            blank["mode"] = "game"
            tmp = self.data_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(blank, indent=2), encoding="utf-8")
            tmp.replace(self.data_file)
        except Exception as _e:  # QUAL-002
            import logging as _lg; _lg.getLogger(__name__).debug("blank artifact write: %s", _e)
        logger.info("Coach state reset for new game")

    def set_wave_override(self, state: str):
        self._wave.set_override(state, duration_s=30)
        logger.info("Wave override: %s (30s)", state)

    def _state_signature(self, coach_state: dict) -> str:
        """AUDIT 2026-04-28 (5.7): compact stable hash of the coach-relevant
        state fields. If this is identical to the last call's signature,
        the previous coach response is still correct and we can skip a
        round-trip. Keep the field set narrow: drift in irrelevant fields
        (e.g., minor timer ticks) shouldn't force a new call."""
        try:
            import hashlib
            keys = (
                "champion", "wave_state", "hp_bucket", "mana_bucket",
                "gold_bucket", "level", "kda", "objective_window",
                "dead_count", "kill_window",
            )
            parts = []
            for k in keys:
                v = coach_state.get(k)
                # Bucket continuous values to absorb noise.
                # _convert outputs my_hp_pct (0.0-1.0), my_gold, my_level -
                # fix key names to match; hp_pct was the old wrong fallback.
                if k == "hp_bucket" and v is None:
                    v = int(coach_state.get("my_hp_pct", 0) * 10)
                if k == "mana_bucket" and v is None:
                    v = int(coach_state.get("my_mana_pct", 0) * 10)
                if k == "gold_bucket" and v is None:
                    v = int(coach_state.get("my_gold", 0) // 300)
                if k == "level" and v is None:
                    v = coach_state.get("my_level")
                if k == "objective_window" and v is None:
                    ot = coach_state.get("objective_timers") or {}
                    v = 1 if any(
                        isinstance(t, (int, float)) and 0 <= float(t) < 90
                        for obj, t in ot.items() if obj in ("dragon", "baron")
                    ) else 0
                parts.append(f"{k}={v}")
            return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
        except Exception:
            return ""

    def _should_coach(self, state: dict) -> bool:
        now = time.time()

        dead_count = state.get("dead_count", 0)
        last_dead  = self._last_submitted_state.get("dead_count", 0)
        new_kills  = dead_count > last_dead
        kill_window = state.get("kill_window", False)

        if (kill_window or new_kills) and now - self._last_coach_time > 2.0:
            return True

        if now - self._last_coach_time < self._debounce_s:
            return False

        last = self._last_submitted_state
        if not last:
            return True

        hp_delta     = abs(state.get("hp_pct", 50) - last.get("hp_pct", 50))
        gold_changed = (state.get("gold", 0) // 300) != (last.get("gold", 0) // 300)

        cur_obj  = state.get("obj_timers_dict", {})
        last_obj = last.get("obj_timers_dict", {})
        obj_trigger = any(
            cur_obj.get(k) is not None and cur_obj.get(k, 9999) < 90
            and last_obj.get(k, 9999) >= 90
            for k in ("dragon", "baron")
        )

        return hp_delta >= 10 or gold_changed or obj_trigger

    def _run_safe(self, game_state: dict):
        if not self._lock.acquire(blocking=False):
            logger.debug("Coach already running, skipping")
            return
        try:
            self._run(game_state)
        except Exception as e:
            logger.error("Coach error: %s", e)
            self._write_status_field(f"Coach error: {str(e)[:60]}")
        finally:
            self._lock.release()

    def _run(self, game_state: dict):
        t0 = time.time()
        coach_state = self._convert(game_state)
        self._last_state = coach_state
        # Stash the raw game_state too - _write_fields needs unprefixed
        # live stats (kda / cs / level / gold / game_time_s) to populate
        # the dashboard top-bar pills, which read from coaching_data.json
        # via the WS /push channel (raw file content, no liveclient
        # overlay). _last_state has these prefixed (my_cs, my_level...).
        self._last_gs = game_state

        cached = self._cache.get(coach_state)
        if cached:
            latency = round((time.time() - t0) * 1000)
            logger.debug("Cache hit in %dms", latency)
            self._write_fields(cached, cache_hit=True)
            return

        if not self._client:
            return

        champion   = coach_state.get("champion", "")
        profile = CHAMPION_PROFILES.get(champion)
        if not profile and HAS_ROLE_PROFILES:
            role = game_state.get("role", "bot")
            profile = get_role_profile(champion, role)
        if not profile:
            try:
                from champion_profiles import CHAMPIONS as _ALL_CHAMPS
                cp = _ALL_CHAMPS.get(champion, {})
                if cp:
                    role    = cp.get("role", "unknown")
                    dmg     = cp.get("dmg", "ad")
                    mechanic = cp.get("mechanic", "")
                    aram_tip = cp.get("aram", "")
                    spikes   = ", ".join(cp.get("spikes", [])) if cp.get("spikes") else ""
                    # SR context: omit aram_tip (ARAM-specific, not useful in SR)
                    profile  = (
                        f"{champion} ({role}, {dmg} damage). "
                        f"{mechanic} "
                        + (f"Item spikes: {spikes}." if spikes else "")
                    )
                else:
                    profile = GENERIC_PROFILE
            except Exception:
                profile = GENERIC_PROFILE
        game_mode  = game_state.get("game_mode", "CLASSIC")
        # SrAramWorker only submits CLASSIC/RANKED - always SR path.
        # ARAM/KIWI/Arena/Brawl coaching is owned by dedicated mode coaches.
        sr_rune_rec  = _load_sr_rune_rec(champion)
        sr_build_note = _load_sr_build_note(champion)
        # Audit round-9: env-gated adaptation hint. Default off; empty-safe.
        _adapt_hint = ""
        import os as _os
        if _os.environ.get("RC_COACH_ADAPTATION") == "1":
            try:
                from coaches.adaptation_hint import format_hint_line as _fhl
                _adapt_hint = _fhl(champion, "sr_ranked",
                                   game_state.get("enemy_comp") or [])
            except Exception:
                _adapt_hint = ""
        system = SR_SYSTEM_PROMPT.format(
            profile=profile,
            sr_rune_rec=sr_rune_rec or "use meta keystone for this champion",
            sr_build_note=sr_build_note or "use standard ADC build for this champion",
            adaptation_hint=_adapt_hint,
        )

        # Inject lane matchup note (adc_lane_matchups data)
        _enemy_adc = (game_state.get("enemy_comp") or [""])[0]
        game_state["_lane_matchup_note"] = _load_lane_matchup_note(_enemy_adc)
        user = _build_user_prompt(game_state, coach_state.get("wave_state", "unknown"))

        # s182 (2026-05-13): rank_for() -> archetype dispatcher.
        # `_last_ds_rows` is now `display_rows` (list of dicts) rather than
        # a list of RankedItem dataclasses; the post-prompt-merge block
        # below at `_pending_ds = getattr(...)` reads it that way.
        _ds_dispatch = None
        _ds_picks_str = "unavailable"
        _ds_label = "DPS"
        try:
            from core.daemon_slayer_resolver import resolve_inventory as _ds_resolve_inventory
            from coach_integration.enemy_stats import compute_enemy_stats as _ds_enemy_stats
            from coach_integration.archetype_dispatch import (
                dispatch_for_coach as _ds_dispatch_for_coach,
                display_label as _ds_display_label,
            )
            _owned_ids = _ds_resolve_inventory(game_state.get("items", []), mode="sr")
            _lvl = int(game_state.get("level", 1)) or 1
            # s170: replaces hardcoded target_armor=80.0 - DS now sees a
            # level-scaled armor/MR/hp target instead of the SR-mid-game
            # anchor regardless of game time. ``bonus_hp_override`` not
            # supplied here because SR coach didn't have an item-aware
            # bonus_hp estimator pre-s170 (unlike ARAM/Arena/Brawl); the
            # heuristic curve drives all four fields.
            _es = _ds_enemy_stats(
                mode="sr",
                game_seconds=int(game_state.get("game_seconds", 0) or 0),
                level=_lvl,
            )
            _ds_dispatch = _ds_dispatch_for_coach(
                champion=champion,
                mode_engine="SR",
                level=_lvl,
                item_ids=_owned_ids,
                enemy_stats=_es,
                top=5,
            )
            if _ds_dispatch is not None:
                _ds_picks_str = _ds_dispatch.picks_str
                _ds_label = _ds_display_label(_ds_dispatch.scorer)
        except Exception as _ds_exc:
            logger.debug("SR daemon_slayer pre-call: %s", _ds_exc)
        self._last_ds_rows = _ds_dispatch.display_rows if _ds_dispatch is not None else None
        if _ds_dispatch is not None and _ds_dispatch.rows:
            try:
                from core.ds_calibration import log_ds_run as _ds_log
                _ds_log(champion=champion, mode="SR", level=int(game_state.get("level", 1)) or 1,
                        owned_items=list(_owned_ids),
                        game_id=str(game_state.get("game_id") or ""),
                        ds_picks=[{"item_id": _r["id"], "item_name": _r["name"],
                                   "delta_dps": _r["delta_dps"], "gold": _r["gold"],
                                   "scorer": _r["scorer"]}
                                  for _r in _ds_dispatch.display_rows])
            except Exception:
                pass
        if _ds_picks_str != "unavailable":
            user += f"\nDS top items ({_ds_label} ranked, own-items-accounted): {_ds_picks_str}"

        if self.debug:
            logger.debug("User prompt:\n%s", user)

        # AUDIT 2026-04-28 (5.7): if the coach-relevant slice of state is
        # byte-identical to the last submitted slice, the previous response
        # is already correct - skip the API call entirely.
        sig = self._state_signature(coach_state)
        if sig and sig == getattr(self, "_last_sig", None):
            logger.debug("Coach skip: state signature unchanged (%s)", sig[:16])
            return
        # AUDIT 2026-04-28 (5.4): hard daily spend cap.
        try:
            from core.cost_tracker import get_tracker as _gt
            if not _gt().allow_call():
                logger.warning("Coach call blocked: daily budget exceeded")
                self._write_status_field("daily budget - paused until midnight")
                return
        except Exception:
            pass
        try:
            # AUDIT 2026-04-28 (5.3): mark the system prompt with
            # cache_control=ephemeral so subsequent ticks with the same
            # prefix replay at ~10% of the input-token cost. system param
            # accepts a list of content blocks for fine-grained caching.
            response = self._client.messages.create(
                model=self._model,
                max_tokens=500,
                timeout=self._timeout_s,
                system=[{
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": user}],
            )
            raw = response.content[0].text
            # AUDIT 2026-04-28 (5.8 + 2.5): record token telemetry +
            # persistent coach trace for the "why did the coach say that?"
            # dashboard tab. usage may include cache_*_input_tokens
            # depending on SDK version; fall back to plain input_tokens.
            _tin = _tout = _cr = _cw = 0
            try:
                u = getattr(response, "usage", None)
                if u is not None:
                    _tin  = getattr(u, "input_tokens", 0) or 0
                    _tout = getattr(u, "output_tokens", 0) or 0
                    _cr   = getattr(u, "cache_read_input_tokens", 0) or 0
                    _cw   = getattr(u, "cache_creation_input_tokens", 0) or 0
            except Exception:
                pass
            try:
                from core.cost_tracker import get_tracker as _gt
                _gt().record_call(
                    model=self._model,
                    input_tokens=_tin, output_tokens=_tout,
                    cache_read=_cr, cache_write=_cw,
                    purpose="sr_coach",
                )
            except Exception as _exc:
                logger.debug("cost_tracker record_call: %s", _exc)
            try:
                from core.coach_trace import append as _trace_append
                _trace_append(
                    mode="sr",
                    model=self._model,
                    system_prompt=system,
                    user_prompt=user,
                    response=raw,
                    latency_ms=int((time.time() - t0) * 1000),
                    tokens_in=_tin, tokens_out=_tout,
                    cache_read=_cr, cache_write=_cw,
                )
            except Exception as _exc:
                logger.debug("coach_trace append: %s", _exc)
            self._last_sig = sig
        except _APITimeoutError:
            logger.warning("Claude API timeout after %ds - will retry at next trigger", self._timeout_s)
            self._last_coach_time = time.time() - self._debounce_s + 2.0
            self._write_status_field("Timeout - retrying next trigger")
            return
        except _APIConnectionError:
            logger.error("Claude API unreachable")
            self._write_status_field("API unreachable")
            return
        except Exception as e:
            logger.error("Claude error: %s", e)
            self._write_status_field(str(e)[:60])
            return

        latency = round((time.time() - t0) * 1000)
        logger.info("Coach response in %dms (model=%s)", latency, self._model)
        self._cache.set(coach_state, raw)
        self._write_fields(raw, cache_hit=False)

    def _convert(self, gs: dict) -> dict:
        hp_pct = gs.get("hp_pct", 100) / 100.0
        mp_pct = gs.get("mana_pct", 100) / 100.0
        game_s = gs.get("game_seconds", 0)

        wave = self._wave.update(gs.get("cs", 0), game_s)

        enemy_comp = gs.get("enemy_comp", [])
        return {
            "champion":         gs.get("champion", ""),
            "game_time_s":      game_s,
            "my_hp_pct":        hp_pct,
            "my_mana_pct":      mp_pct,
            "my_gold":          gs.get("gold", 0),
            "my_items":         gs.get("items", []),
            "my_level":         gs.get("level", 1),
            "my_cs":            gs.get("cs", 0),
            "wave_state":       wave,
            "ally_comp":        gs.get("ally_comp", []),
            "enemy_comp":       enemy_comp,
            "lane_matchup":     {
                "enemy_adc": enemy_comp[0] if enemy_comp else "unknown",
                "enemy_sup": enemy_comp[1] if len(enemy_comp) > 1 else "unknown",
            },
            "nearby_enemies":   [],
            "objective_timers": gs.get("obj_timers_dict", {}),
            "patch_version":    self._patch,
            "kda":              gs.get("kda", ""),
            "dead_count":       gs.get("dead_count", 0),
            "kill_window":      gs.get("kill_window", False),
        }

    def _parse_response(self, text: str) -> dict:
        field_map = {
            "action":       "action",
            "immediate":    "immediate",
            "next":         "next",
            "wave":         "wave",
            "objective":    "objective",
            "fight rule":   "fight_rule",
            "reset / item": "reset_item",
            "risk":         "risk",
            "choices":      "choices",
        }
        fields = {}
        current_key = None
        current_val = []
        for line in text.strip().splitlines():
            s = line.strip()
            if not s:
                continue
            s_clean = s.lstrip("*").rstrip("*")
            import re as _re
            s_clean = _re.sub(r'^\*{1,2}(.*?)\*{1,2}(:)', r'\1\2', s_clean)
            matched = False
            for prefix, key in field_map.items():
                if s_clean.lower().startswith(prefix + ":"):
                    if current_key:
                        fields[current_key] = " ".join(current_val).strip()
                    current_key = key
                    current_val = [s_clean[len(prefix)+1:].strip()]
                    matched = True
                    break
            if not matched and current_key:
                current_val.append(s)
        if current_key:
            fields[current_key] = " ".join(current_val).strip()
        return fields

    def _write_fields(self, raw_response: str, cache_hit: bool = False,
                       update_ts: bool = True):
        fields = self._parse_response(raw_response)
        if not fields:
            logger.warning("No fields parsed from response (first 200 chars): %r",
                           raw_response[:200])
            return

        if "action" in fields:
            import re as _re
            plain = _re.sub(r'\[/?[AET]\]', '', fields["action"]).strip()
            fields["action"] = plain.upper()

        # Passthrough for the optional native-emit `choices` JSON array.
        # The model returns a single-line JSON list (per the OUTPUT FORMAT
        # block); _parse_response stores it as a string. Decode here and
        # write a real Python list into the artifact so the dashboard's
        # state builder picks it up via core.coach_choices.parse_choices.
        # On any failure: silently swallow and let the synthesizer
        # fallback in _state_builder cover the tick. The choices field
        # is OPTIONAL by contract.
        _choices_list: list = []
        _choices_raw = fields.get("choices", "").strip()
        if _choices_raw:
            try:
                _parsed = json.loads(_choices_raw)
                if isinstance(_parsed, list):
                    _choices_list = _parsed
            except Exception:
                pass
        fields["choices"] = _choices_list

        # (audit cycle 10) Mirror ARAM/Arena/Brawl pattern: surface
        # champion + ally_spells from _last_state so the dashboard
        # header pill flips immediately on SR games instead of relying
        # on the slower /api/locked-champion fallback.
        ls = getattr(self, "_last_state", None) or {}
        _champ = ls.get("champion") or ""
        if _champ:
            fields.setdefault("champion", _champ)
            _sd = ls.get("summoner_d") or ""
            _sf = ls.get("summoner_f") or ""
            if _sd or _sf:
                fields.setdefault("ally_spells", {
                    _champ: [{"spell": _sd, "cd_s": 0},
                             {"spell": _sf, "cd_s": 0}],
                })

        # 2026-05-02 (s31): force-overwrite ally_comp/enemy_comp from the
        # coach's current input. Claude's response shape doesn't include
        # comps, so the read-merge-write cycle below preserves whatever
        # was in coaching_data.json from a prior game. Without this, the
        # dashboard's RIGHT NOW / target / fight-rule panels reference the
        # PREVIOUS match's enemy comp for the first ~5 minutes of every
        # new game (until the coach engine eventually surfaces fresh
        # advice that names the actual current opponents). Use direct
        # assignment (not setdefault) - these MUST trump whatever's on
        # disk every tick.
        for _k in ("ally_comp", "enemy_comp"):
            _v = ls.get(_k)
            if _v is not None:
                fields[_k] = _v

        # Mirror live game stats from the raw gs so the dashboard top-bar
        # pills (CS / level / gold / KDA / game time) populate. Coaching
        # JSON is what file_ingest broadcasts to the WS /push channel -
        # without these keys, the pills hide via the dashboard JS's
        # `if (typeof p.cs === "number")` guards. /api/state already does
        # this via state-builder's liveclient overlay, but the WS push
        # path reads the file content directly.
        gs = getattr(self, "_last_gs", None) or {}
        for _k in ("kda", "cs", "level", "gold",
                   "game_time", "game_time_s",
                   "hp", "hp_max", "hp_pct",
                   "items", "owned_items", "enemy_team"):
            _v = gs.get(_k)
            if _v is not None:
                fields[_k] = _v

        # NOTE-003: hold the shared coaching_data_lock around the entire
        # read-modify-write cycle so the dashboard's _set_pregame /
        # /api/command refresh handlers can't clobber our update with their
        # own stale read. The lock is process-local and lives in
        # core.coaching_data_lock.
        from core.coaching_data_lock import coaching_data_lock
        retries = 3
        for attempt in range(retries):
            try:
                with coaching_data_lock():
                    if self.data_file.exists():
                        current = json.loads(self.data_file.read_text(encoding="utf-8"))
                        # 2026-04-27 audit: a partially-flushed file or a bad
                        # external write could leave non-dict JSON here, and
                        # current.update(...) would crash on TypeError. Treat
                        # it like a fresh start rather than propagating.
                        if not isinstance(current, dict):
                            logger.warning("coaching_data.json was %s, resetting", type(current).__name__)
                            current = self._default_data()
                    else:
                        current = self._default_data()

                    current.update(fields)
                    if "action" not in fields:
                        current["action"] = ""
                    current["mode"] = "game"

                    _pending_ds = getattr(self, "_last_ds_rows", None)
                    if _pending_ds is not None:
                        # s182: _pending_ds is now already in display_rows shape
                        # ({id, name, delta_dps, gold, delta, scorer}) - written
                        # directly. Empty list -> empty list (no picks this tick).
                        current["daemon_slayer_picks"] = list(_pending_ds)

                    imm = fields.get("immediate", "")
                    if imm:
                        log = current.get("log", [])
                        if isinstance(log, str):
                            log = [log]
                        ts = datetime.now().strftime("%H:%M")
                        suffix = " [C]" if cache_hit else ""
                        log.append(f"[{ts}] {imm[:60]}{suffix}")
                        current["log"] = log[-12:]

                    tmp = self.data_file.with_suffix(".tmp")
                    tmp.write_text(json.dumps(current, indent=2), encoding="utf-8")
                    tmp.replace(self.data_file)
                logger.debug("Wrote %d fields (cache=%s)", len(fields), cache_hit)
                if update_ts:
                    try:
                        from core.coaching_timestamps import write_coaching_ts as _wts
                        _wts("sr")
                    except Exception:
                        pass  # non-fatal
                return
            except Exception as e:
                if attempt < retries - 1:
                    time.sleep(0.05)
                else:
                    logger.error("Failed to write coaching_data.json: %s", e)

    def _write_status_field(self, status: str):
        self._write_fields(f"Immediate: {status}", update_ts=False)

    def _default_data(self) -> dict:
        return {
            "mode": "game",
            "action": "",
            "immediate": "", "next": "", "fight_rule": "",
            "wave": "", "objective": "", "reset_item": "",
            "risk": "", "map": "", "log": [], "pregame": "",
        }

