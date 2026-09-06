# arch: Arena mode coach - DS-before-Haiku | section=coaching | frozen=no
"""
coaches/arena_coach.py  - v2  (ARCH-002 BaseCoach inheritance)

Arena (2v2v2v2) full coaching engine.
Inherits lifecycle from coaches.BaseCoach.
Self-polls Riot API every 1.5s.
Vision fires every 12s (Sonnet): augment choices, item anvil, round phase.
Writes: data/arena_coaching_data.json

ARCH-002 (full) - 2026-04-18
Also fixes: _parse_fields called without keys (silent TypeError -> no coaching output)
"""

import os
import sys
import json
import logging
from core.safe_coach_output import safe_coach_output
from pathlib import Path

from coaches._base_coach import (
    BaseCoach,
    finite,
    load_json,
    safe_write,
    mirror_live_stats,
    parse_field,
    parse_fields,
    fmt_abilities,
)
from coaches._arena_item_advisor import recompute_arena_build
from core import live_metrics
from core.daemon_slayer_resolver import resolve_inventory as _ds_resolve_inventory
from core.cc_blended_ehp_context import cc_blended_ehp_impact_line
from core.cc_conditional_impact_context import (
    cc_conditional_impact_line,
)
from core.death_patterns_loader import personal_context_block
# RM-364: the augment/anvil choice lists are Haiku-VISION OCR output joined
# straight into a prompt. Applied at ASSEMBLY, not at messages.create - the
# TFT builders proved an API-call-side guard can sit on a dead path.
from core.prompt_sanitize import clean_iter as _clean_for_prompt
from core.enemy_cc_threat_context import enemy_cc_threat_line

logger = logging.getLogger("rc.coaches.arena")

_APP_DIR = Path(__file__).parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

# -- Same-state Haiku-skip debounce (BACKLOG.md:59) ----------------------------
# Arena sibling of the ARAM seam (aram_coach.py). DEFAULT-OFF, fidelity-gated.
# When OFF (default) behavior is byte-identical to the always-call-Haiku path.
# When ON (RC_ARENA_STATE_DEBOUNCE=1), _run_coach computes a COARSE signature of
# only the coaching-relevant snapshot fields (continuous values bucketed so tiny
# jitter does not bust the cache); if the signature equals the last-coached
# signature AND the cached coaching is younger than the hard max-staleness
# ceiling, the redundant messages.create is skipped and the prior coaching
# artifact is reused. The ceiling guarantees the coach can never go truly stale:
# once it expires, the next tick always re-calls Haiku even on an unchanged
# signature. Serves the cost objective + Haiku-to-ZERO north star without
# trading fidelity (the cardinal "never trade fidelity for cost").
# Validate against a live/replayed game before flipping ON (do-not-flip-blind).
# Scope is the per-tick _run_coach ONLY; the event-driven _handle_augment_select
# / _handle_anvil calls fire on a discrete vision event (not per tick) and are
# correctly NOT debounced.
_STATE_DEBOUNCE = os.getenv("RC_ARENA_STATE_DEBOUNCE", "0") == "1"
# Hard max-staleness ceiling (seconds): the longest the coach may reuse a cached
# same-state coaching before it MUST re-call Haiku regardless of signature.
# 45s sits above the stable poll cadence (_STABLE_DEBOUNCE_S=22s) so a stable
# board skips at most ~1 redundant call between refreshes, yet is short enough
# that the coach text never feels frozen mid-game.
_STATE_DEBOUNCE_MAX_STALE_S = 45.0


def _coach_state_signature(state: dict, vision_state: dict) -> tuple:
    """COARSE signature of only the coaching-relevant Arena snapshot fields.

    Continuous / noisy values are BUCKETED so sub-bucket jitter (a 1% HP tick,
    a handful of gold) does NOT bust the cache and force a redundant Haiku call.
    Discrete tactical state (round, level, kda, alive-team count, owned items,
    augments, the NEXT opponent identity, camp/anvil phase) IS in the signature
    so any real change always re-calls.

    Only the next opponent's HP is bucketed in (25% bands) - hashing every
    team's HP would bust the cache every tick as each team jitters, while the
    fight that matters is the one against the next/current opponent. My HP is in
    10% bands (aligns with the prompt's HP decision-tree at 70/40/25). Used only
    when _STATE_DEBOUNCE is ON.
    """
    state = state or {}
    vs = vision_state or {}

    def _bucket(v, size, default=0):
        try:
            return int(float(v) // size)
        except (TypeError, ValueError):
            return default

    hp_band = _bucket(state.get("hp_pct", 100), 10)
    # Gold in ~300g bands: enough to shift a completed-item recommendation,
    # small enough to ignore per-tick passive income.
    gold_band = _bucket(state.get("gold", 0), 300)
    teams = state.get("teams", []) or []
    next_opp = next(
        (t.get("name", "") for t in teams if t.get("is_next_opponent")), ""
    )
    next_opp_hp = _bucket(
        next((t.get("hp_pct", 100) for t in teams if t.get("is_next_opponent")), 100),
        25,
    )
    anvil = vs.get("anvil_choices", []) or []
    anvil_t = tuple(anvil) if isinstance(anvil, list) else ()

    return (
        state.get("champion", ""),
        state.get("game_mode", "CHERRY"),
        int(state.get("round", 0) or 0),
        int(state.get("level", 1) or 1),
        hp_band,
        gold_band,
        str(state.get("kda", "")),
        int(state.get("alive_teams", 8) or 8),
        tuple(state.get("items", []) or []),
        tuple(state.get("augments", []) or []),
        next_opp,
        next_opp_hp,
        bool(vs.get("camp_phase")),
        anvil_t,
    )


# -- System prompt -------------------------------------------------------------
_SYSTEM_PROMPT = """\
You are a Challenger-level Arena 2v2v2v2 coach. Rotating opponents, no waves, HP carries between rounds.

CHAMPION: {profile}
Champion build guide: {arena_meta}
{adaptation_hint}
═══ ARENA PRIORITY DECISION TREE ═══
Opponent HP > 70%: standard fight - do NOT overcommit; trade efficiently and kite
Opponent HP 40-70%: all-in when your burst combo is up + escape ready
Opponent HP < 40%: play safe - they will desperate all-in; kite and poke to close
Your HP < 25%: NEVER all-in; kite, disengage, survive to next camp phase
Your HP > 70%: aggressive - you can afford to make plays and take risks

═══ ROUND FIGHT RULES ═══
Your pair: stay within 300 units of your partner. Peel for each other.
Engage when: BOTH abilities are off cooldown + carry is isolated + escape path clear
Disengage when: you or partner HP < 20% OR enemy pair has both CC abilities ready
Target priority: 1) [E] carry (lowest HP, highest threat), 2) [E] CC holder, 3) tank last
Augment active: use EVERY fight - never save for "perfect" moment
Kiting: orbwalk every single auto. Never stand still during fights.
Anvil phase: ALWAYS take. Complete carry item first, then defensive stat stick.

═══ CAMP PHASE ═══
Always: buy components, upgrade if 2 copies available, heal at campfire
Priority spend: carry item completion > defensive component > sell weakest unit
Augment select at camp: pick damage amp or reset-on-kill for carry; HP/resist for tank

═══ AUGMENT SELECTION FRAMEWORK ═══
1. Does it combo with your kit? (e.g. dash → Sudden Impact; CC → Glacial Augment)
2. Does it scale with your items? (AD items → Conqueror; AP → Luden's)
3. Is it reliable in 2v2? (avoid conditional augments requiring 5+ enemies)
Best for carries: Cut Down, Sudden Impact, Eyeball Collection, Absolute Focus
Best for tanks: Bone Plating, Grasp, Shield Bash, Unflinching

NAME TAGS: [A]Ally[/A]  [E]Enemy[/E]  [T]timing[/T]

OUTPUT FORMAT - exactly 7 fields, NO markdown:
Action: <1-3 WORDS ALL-CAPS - e.g. ALL IN / KITE BACK / BUY ITEMS / FOCUS CARRY / CAMP PHASE>
Round strategy: <opponent HP + your HP + correct approach, use [E] tag, max 20 words>
Fight rule: <exact engage condition with [E] carry + specific ability window, max 20 words>
Augment advice: <if augment select: take X - why. Else: play your current augment this way>
Anvil advice: <if anvil open: take X to complete Y. Else: next component to build>
Target priority: <kill [E]name[/E] first - why - then who>
Risk: <[E]ability[/E] to dodge + when it's up>
Choices: <OPTIONAL compact single-line JSON array of 2-3 micro-decisions the player faces RIGHT NOW. Schema: [{{"key":"A","label":"<3-5 word option>","expected_outcome":"<one sentence what likely happens>","confidence":"low" or "mid" or "high","source_tag":"<3-10 char descriptor>"}}, ...]. Keys are A/B/C in order. Use confidence honestly: "high" only for textbook plays; "mid" for situational reads; "low" for high-uncertainty calls. Set source_tag to a short descriptor like "augment-pick", "round-trade", "duo-rotate", "anvil-buy", "fight-trade". Return [] if no clean binary decision is on the clock. Do NOT inflate; an empty array is better than padded choices. Output MUST be a single line of valid JSON (no markdown, no line breaks inside the array).>
""" + personal_context_block()

_USER_TEMPLATE = """\
=== Arena Round {round} ===
Your champion: {champion}
Partner: {partner}
HP: {hp_pct}%  Gold: {gold}g  Level: {level}  KDA: {kda}
Items: {items}

Your rank: #{rank} of {alive} teams remaining
Next opponent: {next_opp}

Team health rankings:
{team_rankings}

Active augments: {augments}
My abilities: {my_abilities}
{enemy_cc_threats}
{cc_blended_ehp_impact}
{cc_conditional_impact}
DS top items ({ds_label} ranked, own-items-accounted): {ds_picks}
{vision_context}
"""

_AUGMENT_SELECT_PROMPT = """\
You are a Challenger Arena coach. Choose the best augment.

Current state:
Champion: {champion}  Partner: {partner}
Items: {items}  HP: {hp_pct}%  Round: {round}

AUGMENT CHOICES:
{choices}

NO markdown. Output exactly:
Take: <augment name>
Why: <one sentence - why it works for this champion + round>
Gameplan: <how to fight differently because of this augment>
"""

_OUTPUT_KEYS = [
    "action", "round strategy", "fight rule",
    "augment advice", "anvil advice", "target priority", "risk", "choices",
]


_AUG_NAME_MAP_CACHE: dict[str, str] | None = None


def _patch_dir_key(p: Path) -> tuple:
    """Numeric sort key for patch snapshot dirs ("16.10.1" > "16.9.1").

    Plain lexicographic reverse sort put 16.9.x ahead of 16.10.x at every
    .9/.10 minor boundary, selecting a stale arena_augments.json.
    Non-version dirs (build_orders, laning_scenarios) sort last.
    """
    try:
        return tuple(int(x) for x in p.name.split("."))
    except ValueError:
        return (-1,)


def _augment_name_map() -> dict[str, str]:
    """Lazy display-name -> apiName lookup built from arena_augments.json.

    Keys are lowercased + whitespace-stripped display names; values are the
    cdragon apiName (e.g. ``"the brutalizer"`` -> ``"TheBrutalizer"``).
    apiName->apiName self-mapping is also installed so a Haiku response that
    happens to return the apiName resolves cleanly.

    Returns ``{}`` if the snapshot is missing - caller treats that as
    "no resolver available" and skips augment persistence on that tick.
    """
    global _AUG_NAME_MAP_CACHE
    if _AUG_NAME_MAP_CACHE is not None:
        return _AUG_NAME_MAP_CACHE
    out: dict[str, str] = {}
    try:
        snap_dir = _APP_DIR / "data" / "daemon_slayer"
        patches = sorted(
            [p for p in snap_dir.iterdir() if p.is_dir()],
            key=_patch_dir_key, reverse=True,
        )
        for patch_dir in patches:
            f = patch_dir / "arena_augments.json"
            if not f.exists():
                continue
            data = json.loads(f.read_text(encoding="utf-8"))
            for aug in data.get("augments") or []:
                api = str(aug.get("apiName") or "").strip()
                name = str(aug.get("name") or "").strip()
                if not api:
                    continue
                if name:
                    out[name.lower().replace(" ", "")] = api
                out[api.lower()] = api
            break
    except Exception as exc:  # noqa: BLE001
        # Never commit a failed OR partially built map to the process-lifetime
        # cache. Pinning a partial map is worse than pinning an empty one: only
        # SOME augments stop resolving, so the symptom reads as bad data rather
        # than a crash, and augment persistence is skipped for the rest of the
        # process (see this function's docstring). Leaving the cache unset makes
        # the next call retry.
        logger.warning(
            "arena augment name map build failed (%d partial entries "
            "discarded, retrying on next call): %s",
            len(out), exc,
        )
        return {}
    _AUG_NAME_MAP_CACHE = out
    return out


def _resolve_augment_apiname(display: str) -> str | None:
    """Resolve a Haiku-returned display name to an apiName, or None."""
    if not display:
        return None
    key = display.strip().lower().replace(" ", "")
    if not key:
        return None
    return _augment_name_map().get(key)


# -- data-driven augment ranking (CLAUDE #88) ----------------------------------
# Parallel to the Haiku augment pick, not a fallback: vision-OCR says *what's
# offered*, the recommender says *which to take* by historical win-rate
# (own match history blended toward an external Mayhem prior - Option B).

_RECO_MODE_BY_GAMEMODE = {"KIWI": "mayhem", "CHERRY": "arena", "ARENA": "arena"}


def _reco_mode_for(game_mode) -> str:
    """Liveclient gameData.gameMode -> recommender mode. Default mayhem:
    that is the proven OCR path + the only mode with own-history/external
    data today (Task-1 audit 2026-05-17)."""
    return _RECO_MODE_BY_GAMEMODE.get(str(game_mode or "").upper(), "mayhem")


def _parse_stage(round_val) -> int | None:
    """Mayhem augment stage 1-5 from the coach's ``~N`` round string.
    None outside that range - stage priors only sharpen Mayhem; Arena
    rounds are not Mayhem stages."""
    import re
    m = re.search(r"\d+", str(round_val or ""))
    if not m:
        return None
    s = int(m.group(0))
    return s if 1 <= s <= 5 else None


def _augment_recommendation(gs: dict, choices: list, picked_apinames: list) -> dict:
    """Compact surface fields for the data-driven ranking, or {} when
    nothing is usable. Never raises (the LLM pick is unaffected)."""
    try:
        from core import augment_external_source as _aes
        from core import augment_recommender as _arec
        meta = _aes.get_augment_meta()
        offered = [
            aid for c in (choices or [])
            if (aid := meta.resolve_id(str(c)))
        ]
        if not offered:
            return {}
        picked = [
            aid for a in (picked_apinames or [])
            if (aid := meta.resolve_id(str(a)))
        ]
        mode = _reco_mode_for(gs.get("game_mode"))
        stage = _parse_stage(gs.get("round")) if mode == "mayhem" else None
        res = _arec.recommend(offered, picked, mode=mode, stage=stage)
        if not res.ranked:
            return {}
        top = res.top
        return {
            "aug_reco": [
                {
                    "id":     s.augment_id,
                    "name":   s.name,
                    "rarity": s.rarity,
                    "score":  round(s.score, 4),
                    "conf":   round(s.confidence, 3),
                    "n_own":  s.n_own,
                    "ext_wr": None if s.ext_wr is None else round(s.ext_wr, 3),
                    "own_wr": round(s.own_wr, 3),
                    "syn":    round(s.synergy, 4),
                }
                for s in res.ranked
            ],
            "aug_reco_top":       top.name,
            "aug_reco_top_score": round(top.score, 4),
            "aug_reco_conf":      round(top.confidence, 3),
            "aug_reco_mode":      res.mode,
            "aug_reco_stage":     res.stage,
            "aug_reco_n_matches": res.n_matches,
            "aug_reco_external":  res.used_external,
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("Arena augment recommender: %s", exc)
        return {}


# ==============================================================================
# Coach class
# ==============================================================================


def _load_arena_build_note(champion: str) -> str:
    """Load champion build note from aram_champion_builds.json for Arena.
    Arena uses the same item shop as SR. ARAM builds are valid but notes
    should be read in Arena context: no health packs, heal at camp, shorter fights.
    """
    try:
        p = _APP_DIR / "data" / "meta_build" / "aram_champion_builds.json"
        if not p.exists():
            return ""
        data = json.loads(p.read_text(encoding="utf-8"))
        entry = data.get(champion)
        if not entry or isinstance(entry, str):
            return ""
        tier = entry.get("aram_tier", "")
        note = entry.get("build_note", "")
        fb   = entry.get("full_build", [])
        vt   = entry.get("vs_tanks", "")
        vh   = entry.get("vs_healing", "")
        build_str = ", ".join(fb) if fb else ""
        # Arena framing: carry item first, no health packs context
        result = f"{tier} tier - {note}" if tier and note else note or tier
        if build_str:
            result += f" | Full build: {build_str}"
        if vt:
            result += f" | vs tanks: {vt}"
        if vh:
            result += f" | vs healing: {vh}"
        return result[:350]
    except Exception:  # noqa: BLE001
        return ""


class Coach(BaseCoach):
    """Arena 2v2v2v2 coach. Inherits full lifecycle from BaseCoach."""

    GAME_MODES     = ("ARENA", "CHERRY")
    _MODE_NAME     = "arena"
    _DATA_FILENAME = "arena_coaching_data.json"

    # Tunable overrides - Arena is faster-paced, shorter debounce.
    # Cost-tuned 2026-05-04 (post-audit): bumped from VISION 12->20 / DEBOUNCE
    # 4->8 / FAST_PATH 1.5->3.0 to halve API call rate. Pre-bump rates were
    # firing ~450 coach calls per 30-min arena game; new rates ~225 calls.
    _VISION_INTERVAL   = 20.0
    _DEBOUNCE_S        = 8.0
    _STABLE_DEBOUNCE_S = 22.0
    _FAST_PATH_MIN_S   = 3.0
    _HP_DROP_THRESHOLD = 10.0

    # -- BaseCoach hooks -------------------------------------------------------

    def _init_extra(self) -> None:
        """Arena-specific state: stateful round counter + picked augments."""
        self._last_round         = 0
        self._event_round_count  = 0
        self._last_event_count   = 0
        self._picked_augments: list[str] = []

    def _reset_extra(self) -> None:
        self._last_round        = 0
        self._event_round_count = 0
        self._last_event_count  = 0
        self._picked_augments   = []

    # D6 (2026-07-08): Cherry LCU augment endpoint removed in 16.13.
    # Round-based force_scan trigger replaces the dead LCU path so vision
    # pulls forward to OCR the ~30s augment picker window. Arena augment
    # rounds: 2 (silver), 5 (gold), 8 (gold), 11 (prismatic).
    _AUGMENT_ROUNDS = frozenset({2, 5, 8, 11})

    def _on_state_received(self, state: dict) -> None:
        """Inject approximate round number + picked augments into state."""
        state["round"] = self._update_round_from_events(state)
        # Hand the augment apiName list to downstream consumers (coach
        # prompt + daemon_slayer rank call). The list is already apiName-
        # mapped at persistence time.
        state["augments"] = list(self._picked_augments)
        # D6 round-based force_scan bump: when the approximate round
        # transitions into an augment round, bump force_scan.json so the
        # vision loop pulls forward to OCR the transient picker panel.
        # Replaces the dead Cherry LCU endpoint probe (all /lol-cherry-*
        # namespaces return 404 on 16.13.1).
        if (
            self._event_round_count in self._AUGMENT_ROUNDS
            and self._event_round_count != self._last_round
        ):
            try:
                import time as _time_d6
                from pathlib import Path as _Path_d6
                # Lane 8 cycle 24: was a hand-rolled tmp+replace whose scratch
                # name came from the destination alone. data/force_scan.json
                # has FOUR writers (core/hotkeys.py:103,
                # dashboard/_writers.py:68, tools/lcu_agent.py:1372 in its own
                # process, and this one), so that shared scratch name was a
                # real collision, and the bare replace had none of the
                # WinError 5 retry the polled helper carries.
                from core.polled_json import atomic_write_json as _awj_d6
                _fp = _Path_d6(__file__).parent.parent / "data" / "force_scan.json"
                _awj_d6(_fp, {"force": _time_d6.time()})
                logger.debug("force_scan bumped for round=%d", self._event_round_count)
            except Exception:  # noqa: BLE001
                pass
        # Dynamic debounce: relax polling rate when game state is stable
        prev = self._last_state
        if prev:
            changed = (
                state.get("round") != prev.get("round") or
                state.get("items") != prev.get("items") or
                (prev.get("hp_pct", 100) - state.get("hp_pct", 100)) >= 10 or
                sum(1 for t in state.get("teams", []) if t.get("is_dead")) !=
                sum(1 for t in prev.get("teams", []) if t.get("is_dead"))
            )
            self._DEBOUNCE_S = (
                type(self)._DEBOUNCE_S if changed else self._STABLE_DEBOUNCE_S
            )

    def _fast_path_trigger(self, state: dict, prev: dict) -> bool:
        new_round = (
            self._event_round_count != self._last_round
            and self._event_round_count > 0
        )
        hp_drop = (
            prev.get("hp_pct", 100) - state.get("hp_pct", 100)
        ) >= self._HP_DROP_THRESHOLD
        if new_round:
            self._last_round = self._event_round_count  # advance tracker
        return new_round or hp_drop

    # -- BaseCoach abstract implementations ------------------------------------

    def _blank_artifact_data(self) -> dict:
        return {
            "mode": "arena", "action": "", "round_strategy": "",
            "fight_rule": "", "augment_advice": "", "anvil_advice": "",
            "target_priority": "", "risk": "", "teams": [],
            "round": 0, "rank": "?", "alive_teams": 8, "hp_pct": 100,
            "game_id": "",
        }

    def _parse_raw_state(self, raw: dict) -> dict:
        return _parse_arena_state(raw)

    # -- Round tracker ---------------------------------------------------------

    def _update_round_from_events(self, state: dict) -> str:
        """
        Stateful round tracker - increments only when cumulative combat-event
        count grows. Returns labeled "~N" (approximate) string.
        API has no native Arena round counter.
        """
        new_count = state.get("_raw_event_count", 0)
        if new_count > self._last_event_count:
            self._event_round_count = min(self._event_round_count + 1, 30)
            self._last_event_count  = new_count
        return f"~{max(self._event_round_count, 1)}"

    # -- Target-bonus-HP estimator (Phase 4 batch 19 wire-in) -----------------

    def _estimate_target_bonus_hp(self, state: dict | None = None) -> float:
        """Estimate enemy bonus HP from items, falling back to round count.

        Primary path (s73): sum bonus HP across the worst-case alive
        opponent's items. ``_parse_arena_state.teams[i]["items"]`` carries
        the LCU-supplied display names; ``daemon_slayer_resolver``
        resolves them to IDs and looks up ``FlatHPPoolMod`` from the
        patch-current DDragon snapshot. We pick MAX across alive
        opponents (not avg) because LDR Giant Slayer is "vs high-bonus-HP
        targets" - the engine should escalate the recommendation when
        ANY enemy is tanky, not when the average is.

        Fallback path (s72): linear ramp 0->1500 across rounds 2..10
        when no enemy items are visible (early game, vision gap, or
        pre-game state). Curve saturates at LDR's 1500 HP cap so
        precision stops mattering past round 10.

        Returns 0.0 when neither signal is available (collapses to "no
        signal" in the engine - procs no-op).
        """
        state = state or {}
        teams = state.get("teams") or []
        # Worst-case alive opponent - not is_you, not is_partner, not dead.
        opp_items: list[list[str]] = [
            (t.get("items") or []) for t in teams
            if not t.get("is_you")
            and not t.get("is_partner")
            and not t.get("is_dead")
        ]
        if any(opp_items):
            # Resolve names -> ids -> bonus HP per opponent; max wins.
            # s74: pin mode='arena' so the alias-ID path is intentional,
            # not riding on the byName setdefault first-seen-wins quirk.
            from core import daemon_slayer_resolver as _ds_res
            best = 0.0
            for items in opp_items:
                if not items:
                    continue
                ids = _ds_res.resolve_many(items, mode="arena")
                hp = _ds_res.total_bonus_hp(ids)
                if hp > best:
                    best = hp
            if best > 0:
                return min(1500.0, best)

        # Fallback: round-based heuristic. Linear ramp rounds 2..10 ->
        # 167..1500, capped thereafter; 0 for round <= 1 (pre-game).
        round_count = max(0, int(self._event_round_count))
        if round_count <= 1:
            return 0.0
        return min(1500.0, max(0.0, (round_count - 1) * 1500.0 / 9.0))

    # -- Vision ----------------------------------------------------------------

    def _run_vision(self) -> None:
        if self._fetch_game_data() is None:
            return
        try:
            from core.feature_policy import is_allowed as _fp_ok
            if not _fp_ok("arena", "live_coaching"):
                return
        except Exception:  # noqa: BLE001
            pass
        try:
            reader = ArenaVisionReader(self._api_key)
            state  = reader.read()
            if not state:
                return
            self._vision_state = state
            if state.get("augment_select") and state.get("augment_choices"):
                self._handle_augment_select(state)
                return
            if state.get("anvil_choices"):
                self._handle_anvil(state)
            # v2: panel is gone, so HUD slots are the canonical augment record.
            # Only overrides when ALL slots resolve - partial reads keep Haiku's list.
            self._reconcile_augment_hud(state)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Arena vision run: %s", exc)

    # -- Coach -----------------------------------------------------------------

    @safe_coach_output("Arena")
    def _run_coach(self, state: dict) -> None:
        try:
            from core.feature_policy import is_allowed as _fp_ok, write_disabled_placeholder as _fp_wr
            if not _fp_ok("arena", "live_coaching"):
                _fp_wr("arena")
                return
        except Exception:  # noqa: BLE001
            pass
        if not self._client:
            return
        try:
            from coach_integration import CHAMPION_PROFILES, GENERIC_PROFILE
            champ   = state.get("champion", "Unknown")
            profile = CHAMPION_PROFILES.get(champ, GENERIC_PROFILE)
            arena_meta = _load_arena_build_note(champ)
            _hint = ""
            if os.environ.get("RC_COACH_ADAPTATION") == "1":
                try:
                    from coaches.adaptation_hint import format_hint_line as _fhl
                    _hint = _fhl(champ, "arena", None)
                except Exception:  # noqa: BLE001
                    pass
            system  = _SYSTEM_PROMPT.format(profile=profile, arena_meta=arena_meta, adaptation_hint=_hint)

            teams = state.get("teams", [])
            rankings = "\n".join(
                f"  {'[YOU]' if t.get('is_you') else '     '} "
                f"{t.get('name', '?')[:12]:12}  {t.get('hp_pct', 100):3d}%"
                + (" [NEXT OPP]" if t.get("is_next_opponent") else "")
                + (" [DEAD]"     if t.get("is_dead")           else "")
                for t in sorted(teams, key=lambda x: -x.get("hp_pct", 0))
            ) or "  Team data loading..."

            partner  = next((t.get("name", "?") for t in teams if t.get("is_partner")),  "Unknown")
            next_opp = next((t.get("name", "?") for t in teams if t.get("is_next_opponent")), "Unknown")
            augments = ", ".join(state.get("augments", [])) or "none"

            vs = self._vision_state
            vision_ctx = ""
            if vs.get("camp_phase"):
                vision_ctx = "CAMP PHASE ACTIVE - buy/upgrade items and heal now."
            elif vs.get("anvil_choices"):
                vision_ctx = f"ITEM ANVIL available: {', '.join(vs.get('anvil_choices', []))}"

            # s182 (2026-05-13): rank_for() -> archetype dispatcher.
            _ds_dispatch = None
            _ds_picks_str = "unavailable"
            _ds_label = "DPS"
            try:
                from coach_integration.enemy_stats import compute_enemy_stats as _ds_enemy_stats
                from coach_integration.archetype_dispatch import (
                    dispatch_for_coach as _ds_dispatch_for_coach,
                    display_label as _ds_display_label,
                )
                # Trinkets + consumables share the Live Client inventory array
                # with shop items, so the raw list charges the engine's 6-slot
                # budget for a slot no build item occupies - and the same list
                # is persisted as the calibration row's owned_items below.
                owned_ids = _ds_resolve_inventory(state.get("items", []), mode="arena")
                target_bonus_hp = self._estimate_target_bonus_hp(state)
                _lvl = int(state.get("level", 1)) or 1
                # s170: replaces hardcoded target_armor=80.0 with level-aware
                # Arena curve. Item-aware bonus_hp estimator wins via override
                # when enemies show items.
                _es = _ds_enemy_stats(
                    mode="arena",
                    game_seconds=int(state.get("game_seconds", 0) or 0),
                    level=_lvl,
                    bonus_hp_override=target_bonus_hp if target_bonus_hp > 0 else None,
                    enemy_champions=state.get("enemy_comp", []),
                )
                _ds_dispatch = _ds_dispatch_for_coach(
                    champion=champ,
                    mode_engine="ARENA",
                    level=_lvl,
                    item_ids=owned_ids,
                    enemy_stats=_es,
                    augments=state.get("augments") or None,
                    top=5,
                    # R5 self-HP: absent -> dispatch guard yields 0.0 (OFF).
                    caster_hp=state.get("hp"),
                    caster_hp_max=state.get("hp_max"),
                )
                if _ds_dispatch is not None:
                    _ds_picks_str = _ds_dispatch.picks_str
                    _ds_label = _ds_display_label(_ds_dispatch.scorer)
            except Exception as _ds_exc:  # noqa: BLE001
                logger.debug("Arena daemon_slayer pre-call: %s", _ds_exc)
            if _ds_dispatch is not None and _ds_dispatch.rows:
                try:
                    from core.ds_calibration import log_ds_run as _ds_log
                    # D-01b: Arena never surfaces a Live Client game_id, so mint
                    # the shared per-match key (same seam the metric streamer
                    # uses) or these rows stay permanently unjoinable.
                    _ds_mk = live_metrics.match_key(
                        self, {"champion": champ,
                               "game_time_s": state.get("game_seconds")},
                        state, "ARENA")
                    _ds_log(champion=champ, mode="ARENA", level=int(state.get("level", 1)) or 1,
                            owned_items=list(owned_ids), match_key=_ds_mk,
                            ds_picks=[{"item_id": _r["id"], "item_name": _r["name"],
                                       "delta_dps": _r["delta_dps"], "gold": _r["gold"],
                                       "scorer": _r["scorer"]}
                                      for _r in _ds_dispatch.display_rows])
                except Exception:  # noqa: BLE001
                    pass

            # Arena enemy roster: every team-name that is not me, not my
            # partner, alive or dead - drive enemy_cc_threat_line off it.
            # Skips champion-mode placeholders ("Player0" etc) by length:
            # championName-derived names are always non-empty alphanumerics.
            _arena_enemies = [
                t.get("name")
                for t in teams
                if not t.get("is_you") and not t.get("is_partner")
            ]
            user = _USER_TEMPLATE.format(
                round         = state.get("round", 0),
                champion      = champ,
                partner       = partner,
                hp_pct        = state.get("hp_pct",  100),
                gold          = state.get("gold",    0),
                level         = state.get("level",   1),
                kda           = state.get("kda",     "0/0/0"),
                items         = ", ".join(state.get("items", [])) or "none",
                rank          = state.get("rank",    "?"),
                alive         = state.get("alive_teams", 8),
                next_opp      = next_opp,
                team_rankings = rankings,
                augments      = augments,
                my_abilities  = fmt_abilities(state.get("my_abilities", {})),
                enemy_cc_threats = enemy_cc_threat_line(
                    _arena_enemies,
                    state.get("game_mode", "CHERRY"),
                ),
                cc_blended_ehp_impact = cc_blended_ehp_impact_line(
                    _arena_enemies,
                    state.get("game_mode", "CHERRY"),
                ),
                cc_conditional_impact = cc_conditional_impact_line(
                    _arena_enemies,
                    state.get("game_mode", "CHERRY"),
                ),
                ds_picks      = _ds_picks_str,
                ds_label      = _ds_label,
                vision_context = vision_ctx,
            )

            # -- Same-state Haiku-skip debounce (DEFAULT-OFF) --------------
            # When ON, skip the redundant messages.create if the coarse
            # coaching-relevant signature is unchanged AND the cached
            # coaching is younger than the hard max-staleness ceiling. The
            # prior coaching artifact is already on disk (written by the
            # last non-skipped tick) so reuse is a no-op write. When OFF
            # (default) this block is inert and behavior is byte-identical.
            if _STATE_DEBOUNCE:
                import time as _time_dbnc
                _sig = _coach_state_signature(state, vs)
                _last_sig = getattr(self, "_state_dbnc_sig", None)
                _last_ts = getattr(self, "_state_dbnc_ts", 0.0)
                _now_dbnc = _time_dbnc.time()
                if (
                    _last_sig is not None
                    and _sig == _last_sig
                    and (_now_dbnc - _last_ts) < _STATE_DEBOUNCE_MAX_STALE_S
                ):
                    logger.debug(
                        "Arena state-debounce: signature unchanged "
                        "(age %.1fs < %.0fs ceiling) - reusing cached coaching",
                        _now_dbnc - _last_ts, _STATE_DEBOUNCE_MAX_STALE_S,
                    )
                    return

            import time as _time_a
            _t0 = _time_a.perf_counter()
            # AUDIT 2026-04-29 (gap E): cache_control: ephemeral on the
            # system prompt - system prompt is reused every tick.
            resp = self._client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=650,
                system=[{"type": "text", "text": system,
                         "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
                timeout=20,
            )
            # AUDIT 2026-04-29 (gap A): cost + trace telemetry.
            self._record_coach_call(resp, system=system, user=user,
                                    t0_perf=_t0,
                                    model="claude-haiku-4-5-20251001",
                                    purpose="arena_coach")
            raw    = resp.content[0].text
            # ARCH-002 bug fix: pass keys argument (was missing - caused silent TypeError)
            fields = parse_fields(raw, _OUTPUT_KEYS)
            if not fields:
                logger.warning("Arena: no fields parsed")
                return

            # Passthrough for the optional native-emit `choices` JSON array.
            # The model returns a single-line JSON list (per the OUTPUT FORMAT
            # block); parse_fields stores it as a string. We read the decoded
            # list off the shared validated CoachOutput model (one seam) and
            # write a real Python list into the artifact so the dashboard's
            # state builder picks it up via core.coach_choices.parse_choices.
            # from_fields routes `choices` through the model's before-validator,
            # which silently swallows malformed/non-list input and returns []
            # so the synthesizer fallback in _state_builder covers the tick.
            # The choices field is OPTIONAL by contract.
            from core.coach_output import CoachOutput
            _choices_list = CoachOutput.from_fields(fields).choices

            current = load_json(self._out)
            current.update({
                "action":          fields.get("action",          "").upper(),
                "round_strategy":  fields.get("round strategy",  ""),
                "fight_rule":      fields.get("fight rule",       ""),
                "augment_advice":  fields.get("augment advice",  ""),
                "anvil_advice":    fields.get("anvil advice",    ""),
                "target_priority": fields.get("target priority", ""),
                "risk":            fields.get("risk",            ""),
                "choices":       _choices_list,
                "teams":           teams,
                "round":           state.get("round",        0),
                "rank":            state.get("rank",         "?"),
                "alive_teams":     state.get("alive_teams",  8),
                "hp_pct":          state.get("hp_pct",       100),
                "wins":            state.get("wins",         0),
                "losses":          state.get("losses",       0),
                "game_time_s":     state.get("game_seconds", 0),
                "camp_phase":      vs.get("camp_phase",      False),
                # (audit cycle 4) Mirror ARAM coach: write champion +
                # ally_spells to the artifact so the dashboard's header
                # champion-pill flips immediately at champ-pop instead of
                # waiting for the /api/locked-champion fallback poll.
                "champion":        champ,
                "ally_spells":     {champ: [{"spell": state.get("summoner_d", ""), "cd_s": 0},
                                            {"spell": state.get("summoner_f", ""), "cd_s": 0}]}
                                  if champ and (state.get("summoner_d") or state.get("summoner_f")) else {},
            })
            mirror_live_stats(current, state)

            # Per-round item advisor (s33). Replaces the static champ-select
            # item_build (frozen full_build joined) with a recommendation
            # that dedups against owned items + re-ranks by alive opponents'
            # tank/healer counts. Pure rule-based; no Haiku call.
            try:
                alive_opps = [
                    t.get("name", "") for t in teams
                    if not t.get("is_dead")
                    and not t.get("is_you")
                    and not t.get("is_partner")
                ]
                new_build = recompute_arena_build(
                    champion=champ,
                    current_items=state.get("items", []),
                    gold=state.get("gold", 0),
                    alive_opponents=alive_opps,
                    hp_pct=state.get("hp_pct", 100),
                )
                if new_build:
                    current["item_build"] = ", ".join(new_build)
            except Exception as exc:  # noqa: BLE001
                logger.debug("arena item advisor: %s", exc)

            if _ds_dispatch is not None:
                current["daemon_slayer_picks"] = _ds_dispatch.display_rows

            safe_write(self._out, current)
            # -- Same-state Haiku-skip debounce: record the signature + ts of
            # THIS just-coached state so the next tick can skip a redundant
            # call. Only tracked when the gate is ON; inert (and byte-identical)
            # when OFF. Computed from the same state/vs that drove this call so
            # the cached artifact matches the signature.
            if _STATE_DEBOUNCE:
                import time as _time_dbnc2
                self._state_dbnc_sig = _coach_state_signature(state, vs)
                self._state_dbnc_ts = _time_dbnc2.time()
            logger.debug("Arena coaching written (%d fields)", len(fields))
            # Live metric streaming (feature-flagged; core.live_metrics gate).
            live_metrics.stream(self, current, state, self._MODE_NAME)
            try:
                from core.coaching_timestamps import write_coaching_ts as _wts
                _wts("arena")
            except Exception:  # noqa: BLE001
                # D-class: callee already swallows (core/coaching_timestamps.py:73-74
                # returns None), so narrowing this handler would be dead code.
                pass
        except Exception as exc:
            raise exc

    def _handle_augment_select(self, vision_state: dict) -> None:
        if not self._client:
            return
        gs      = self._last_state
        choices = vision_state.get("augment_choices", [])
        # Data-driven ranking, parallel to Haiku (CLAUDE #88). Conditioned
        # on the picks made in PRIOR rounds - snapshot before the Haiku
        # block appends this round's pick. Offline + never raises.
        picked_before = list(self._picked_augments)
        reco_fields   = _augment_recommendation(gs, choices, picked_before)
        champ   = gs.get("champion", "Unknown")
        teams   = gs.get("teams", [])
        partner = next((t.get("name", "?") for t in teams if t.get("is_partner")), "?")
        prompt  = _AUGMENT_SELECT_PROMPT.format(
            champion = champ,
            partner  = partner,
            items    = ", ".join(gs.get("items", [])) or "none",
            hp_pct   = gs.get("hp_pct", 100),
            round    = gs.get("round",  0),
            # RM-364: sanitised HERE and not at `choices` above, because the
            # raw list must still reach _augment_recommendation - that ranker
            # matches augment names against a data table, and a [\n] token or
            # a [BLOCKED:override] marker would break the lookup it needs.
            # A newline inside one OCR choice forges an extra "- " bullet.
            choices  = "\n".join(f"- {c}" for c in _clean_for_prompt(choices)),
        )
        try:
            import time as _time_b
            _t0b = _time_b.perf_counter()
            resp = self._client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=250,
                messages=[{"role": "user", "content": prompt}], timeout=15,
            )
            self._record_coach_call(resp, system="", user=prompt,
                                    t0_perf=_t0b,
                                    model="claude-haiku-4-5-20251001",
                                    purpose="arena_aug_select")
            raw      = resp.content[0].text
            take     = parse_field(raw, "Take")
            api_name = _resolve_augment_apiname(take)
            if api_name and api_name not in self._picked_augments:
                self._picked_augments.append(api_name)
            current = load_json(self._out)
            current.update({
                "augment_select":  True,
                "aug_take":        take,
                "aug_why":         parse_field(raw, "Why"),
                "aug_plan":        parse_field(raw, "Gameplan"),
                "augment_choices": choices,
                # Persist the apiName list so the dashboard / postgame
                # collector can see what the engine was given. Source is
                # the Haiku recommendation - see project_arena_augments_not_persisted.
                "augments_picked": list(self._picked_augments),
                "augments_source": "haiku_rec",
                **reco_fields,
            })
            safe_write(self._out, current)
            # Do-not-flip-blind: record the Haiku take vs the deterministic
            # augment_recommender ranking for offline agreement analysis
            # (core.augment_shadow.summarize_agreement). The served output
            # above is unchanged - this appends a shadow row only, fail-soft.
            try:
                from core import augment_shadow as _augsh
                _augsh.log_augment_advice(
                    {
                        "mode":     reco_fields.get("aug_reco_mode"),
                        "champion": champ,
                        "round":    gs.get("round", 0),
                        "stage":    reco_fields.get("aug_reco_stage"),
                        "offered":  list(choices or []),
                        "picked":   list(picked_before),
                    },
                    {"take": take, "why": current.get("aug_why", ""),
                     "plan": current.get("aug_plan", "")},
                    reco_fields,
                )
            except Exception:  # noqa: BLE001
                # D-class: callee already swallows (core/augment_shadow.py:112-113),
                # so narrowing this handler would be dead code.
                pass
        except Exception as exc:  # noqa: BLE001
            logger.error("Arena augment select: %s", exc)
            # The recommender is a parallel signal (S5) - persist it even
            # when the Haiku call fails, so the data-driven ranking still
            # surfaces during an LLM outage.
            if reco_fields:
                try:
                    current = load_json(self._out)
                    current.update({
                        "augment_select":  True,
                        "augment_choices": choices,
                        **reco_fields,
                    })
                    safe_write(self._out, current)
                except Exception as exc2:  # noqa: BLE001
                    # D-class: callees already swallow (coaches/_base_coach.py:66-68
                    # load_json -> {}, :100-102 safe_write returns).
                    logger.debug("Arena augment reco persist: %s", exc2)

    def _reconcile_augment_hud(self, vision_state: dict) -> None:
        """Override _picked_augments from vision-confirmed HUD slots.

        v1 (s49) source = Haiku recommendation at augment-select panel time.
        v2 = Sonnet reads the HUD augment tray after the panel disappears.
        Vision is canonical because the player may have deviated from
        Haiku's pick (or Haiku may have mis-resolved a name).

        Conservative override: ALL slots must resolve via the apiName map.
        Partial reads (one icon Sonnet can't ID) preserve Haiku's list to
        avoid wiping a known-good record with unreliable vision.
        """
        slots = vision_state.get("augment_hud_slots") or []
        if not slots:
            return
        resolved: list[str] = []
        seen: set[str] = set()
        for raw in slots:
            api = _resolve_augment_apiname(str(raw or ""))
            if not api:
                logger.debug("HUD reconcile: skipping (unresolved %r in %s)", raw, slots)
                return  # all-or-nothing guard
            if api not in seen:
                resolved.append(api)
                seen.add(api)
        if resolved == self._picked_augments:
            # Vision confirmed Haiku's picks - still tag source so the
            # artifact reflects the upgrade in confidence.
            try:
                current = load_json(self._out)
                if current.get("augments_source") != "vision_hud":
                    current["augments_source"] = "vision_hud"
                    current["augments_picked"] = list(self._picked_augments)
                    safe_write(self._out, current)
            except Exception as exc:  # noqa: BLE001
                # D-class: callees already swallow (coaches/_base_coach.py:66-68
                # load_json -> {}, :100-102 safe_write returns).
                logger.debug("HUD reconcile (confirm) write: %s", exc)
            return
        logger.info(
            "HUD reconcile: overriding picks %s -> %s",
            self._picked_augments, resolved,
        )
        self._picked_augments = resolved
        try:
            current = load_json(self._out)
            current["augments_picked"] = list(self._picked_augments)
            current["augments_source"] = "vision_hud"
            safe_write(self._out, current)
        except Exception as exc:  # noqa: BLE001
            # D-class: callees already swallow (coaches/_base_coach.py:66-68
            # load_json -> {}, :100-102 safe_write returns).
            logger.debug("HUD reconcile write: %s", exc)

    def _handle_anvil(self, vision_state: dict) -> None:
        choices = vision_state.get("anvil_choices", [])
        if not choices or not self._client:
            return
        gs = self._last_state
        # RM-364: OCR text, joined into an inline f-string with no cap, no
        # filter and no delimiter discipline before this line.
        safe_choices = _clean_for_prompt(choices)
        prompt = (
            f"Arena item anvil. Champion: {gs.get('champion','?')}. "
            f"Current items: {', '.join(gs.get('items', []) or ['none'])}. "
            f"Anvil choices: {', '.join(safe_choices)}. "
            f"HP: {gs.get('hp_pct', 100)}%. Round: {gs.get('round', 0)}. "
            "NO markdown. Output: Take: <item>\nWhy: <one line reason>"
        )
        try:
            import time as _time_c
            _t0c = _time_c.perf_counter()
            resp = self._client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=100,
                messages=[{"role": "user", "content": prompt}], timeout=10,
            )
            self._record_coach_call(resp, system="", user=prompt,
                                    t0_perf=_t0c,
                                    model="claude-haiku-4-5-20251001",
                                    purpose="arena_anvil")
            raw      = resp.content[0].text
            take     = parse_field(raw, "Take")
            why      = parse_field(raw, "Why")
            current = load_json(self._out)
            current["anvil_advice"] = f"Take: {take} - {why}"
            safe_write(self._out, current)
            # Do-not-flip-blind: record the Haiku take vs the deterministic
            # precomputed_anvil_advisor ranking for offline agreement analysis
            # (core.anvil_shadow.summarize_agreement). The served anvil_advice
            # above is unchanged - this appends a shadow row only, fail-soft.
            # alive_opponents is the per-tick coach loop's local (built from
            # `teams`), not carried on self, so we pass [] for the base ideal
            # path here; alive-opponent enrichment is a future refinement.
            try:
                from core import precomputed_anvil_advisor as _anvadv
                from core import anvil_shadow as _anvsh
                det = _anvadv.compute_anvil_pick(
                    champion=gs.get("champion"),
                    current_items=list(gs.get("items", []) or []),
                    anvil_choices=list(choices or []),
                    alive_opponents=[],
                    hp_pct=gs.get("hp_pct", 100),
                )
                _anvsh.log_anvil_advice(
                    {
                        "mode":     "arena",
                        "champion": gs.get("champion"),
                        "round":    gs.get("round", 0),
                        "offered":  list(choices or []),
                        "owned":    list(gs.get("items", []) or []),
                    },
                    {"take": take, "why": why},
                    det,
                )
            except Exception:  # noqa: BLE001
                pass
        except Exception as exc:  # noqa: BLE001
            logger.error("Arena anvil: %s", exc)


# -- Vision reader -------------------------------------------------------------

class ArenaVisionReader:
    PROMPT = """\
Analyze this Arena (2v2v2v2) League of Legends screenshot.
Return ONLY valid JSON:
{
  "augment_select": false,
  "augment_choices": [],
  "anvil_choices": [],
  "augment_hud_slots": [],
  "camp_phase": false,
  "round_number": 1
}
Rules:
- augment_select: true if large augment card selection panel visible
- augment_choices: list of augment names if selection visible
- anvil_choices: list of item names if item anvil visible
- augment_hud_slots: list of currently-equipped augment names visible in
  the player's bottom HUD (small icons in the augment tray adjacent to
  abilities/items). Empty list if none visible. Only include augments
  you can confidently identify by icon.
- camp_phase: true if in the between-round camp phase (not in combat arena)
- Return ONLY the JSON
"""

    TIERED_FIELDS = [
        "timer",               # OCR canary (validates in-game frame)
        "round_number",
        "augment_select", "augment_choices", "anvil_choices",
        "augment_hud_slots", "camp_phase",
        # B-01b re-home: the live relay answers every mode with the TFT prompt
        # (vision_server/_inference.py:36), which emits the augment flag as
        # `is_augment_select`. modes/shared_vision._postprocess aliases it into
        # the consumed `augment_select` at :606, so it IS a requested field for
        # this mode - declaring it here stops RC_VISION_MERGE_STRICT filtering
        # it out before the alias runs. Arena has augments.
        "is_augment_select",
        # Lane E CV OCR shadow-only numerics (logged, not consumed)
        "ally_1_hp", "ally_2_hp", "ally_3_hp", "ally_4_hp",
        "gold", "level", "cs", "kda",
    ]
    SHADOW_FIELDS = [
        "ally_1_hp", "ally_2_hp", "ally_3_hp", "ally_4_hp",
        "gold", "level", "cs", "kda",
    ]
    TIERED_VALIDATORS = {
        "round_number":      lambda v: isinstance(v, int) and 1 <= v <= 30,
        "augment_select":    lambda v: isinstance(v, bool),
        "is_augment_select": lambda v: isinstance(v, bool),
        "augment_choices":   lambda v: isinstance(v, list),
        "anvil_choices":     lambda v: isinstance(v, list),
        "augment_hud_slots": lambda v: isinstance(v, list),
        "camp_phase":        lambda v: isinstance(v, bool),
        "ally_1_hp":         lambda v: isinstance(v, (int, float)) and 0 <= v <= 100,
        "ally_2_hp":         lambda v: isinstance(v, (int, float)) and 0 <= v <= 100,
        "ally_3_hp":         lambda v: isinstance(v, (int, float)) and 0 <= v <= 100,
        "ally_4_hp":         lambda v: isinstance(v, (int, float)) and 0 <= v <= 100,
        "gold":              lambda v: isinstance(v, int) and 0 <= v <= 99999,
        "level":             lambda v: isinstance(v, int) and 1 <= v <= 18,
        "cs":                lambda v: isinstance(v, int) and 0 <= v <= 1000,
        "kda":               lambda v: isinstance(v, str) and v.count("/") == 2,
    }

    def __init__(self, api_key: str):
        import anthropic
        from modes.shared_vision import GameVisionReader
        r = GameVisionReader.__new__(GameVisionReader)
        r._client = anthropic.Anthropic(api_key=api_key, base_url="https://api.anthropic.com")
        r._model  = "claude-sonnet-4-6"
        r._last   = {}
        r.PROMPT  = self.PROMPT
        r.TIERED_FIELDS = self.TIERED_FIELDS
        r.TIERED_VALIDATORS = self.TIERED_VALIDATORS
        r.SHADOW_FIELDS = self.SHADOW_FIELDS
        self._reader = r

    def read(self) -> "dict | None":
        return self._reader.read_tiered()


# -- Arena game state parser ---------------------------------------------------

def _parse_arena_state(raw: dict) -> dict:
    ap     = raw.get("activePlayer", {})
    gd     = raw.get("gameData", {})
    all_p  = [p for p in (raw.get("allPlayers", []) or []) if isinstance(p, dict)]
    events = (raw.get("events", {}) or {}).get("Events", [])

    game_time = finite(gd.get("gameTime", 0))
    game_mode = gd.get("gameMode", "ARENA")

    stats  = ap.get("championStats", {}) or {}
    hp     = int(finite(stats.get("currentHealth", 0)))
    hp_max = int(finite(stats.get("maxHealth", 1), 1))
    hp_pct = int(100 * hp / max(hp_max, 1))

    my_name = (ap.get("summonerName") or ap.get("riotIdGameName") or "").split("#")[0]
    me = None
    for p in all_p:
        pn = (p.get("summonerName") or "").split("#")[0]
        if pn == my_name or p.get("championName") == ap.get("championName"):
            me = p
            break

    sc      = (me or {}).get("scores", {}) or {}
    items   = [
        it.get("displayName", "")
        for it in ((me or {}).get("items") or [])
        if isinstance(it, dict) and it.get("displayName")
    ]

    alive        = sum(1 for p in all_p if not p.get("isDead"))
    my_team_id   = (me or {}).get("team", "ORDER") if me else "ORDER"
    # Phase 4 batch 19 wire-in (s73): surface per-player items so the
    # coach-side estimator can sum enemy bonus HP deterministically
    # instead of using the round-count heuristic. displayName list mirrors
    # the local-player ``items`` field above.
    teams = [
        {
            "name":             p.get("championName", f"Player{i}"),
            "hp_pct":           100 if not p.get("isDead") else 0,
            "is_you":           p is me,
            "is_partner":       p.get("team") == my_team_id and p is not me,
            "is_dead":          p.get("isDead", False),
            "is_next_opponent": False,
            "items":            [
                it.get("displayName", "")
                for it in (p.get("items") or [])
                if isinstance(it, dict) and it.get("displayName")
            ],
        }
        for i, p in enumerate(all_p)
    ]

    # Rank: only emit numeric rank when vision data provides real HP variance
    rank_str   = "?"
    hp_values  = [t["hp_pct"] for t in teams if not t["is_dead"]]
    if any(v not in (0, 100) for v in hp_values) and teams:
        for idx, t in enumerate(sorted(teams, key=lambda t: -t["hp_pct"])):
            if t["is_you"]:
                rank_str = f"~{idx + 1}"
                break

    combat_events = [
        ev for ev in events
        if isinstance(ev, dict) and ev.get("EventName") in (
            "TurretKilled", "ChampionKill", "FirstBlood"
        )
    ]

    return {
        "game_mode":        game_mode,
        "game_seconds":     game_time,
        "champion":         (me or ap).get("championName", "Unknown"),
        "hp_pct":           hp_pct,
        # R5 self-HP: raw numeric hp/hp_max so dispatch_for_coach can derive
        # caster_missing_hp_pct (state.get("hp") was absent -> seam zeroed).
        "hp":               hp,
        "hp_max":           hp_max,
        "gold":             int(finite(ap.get("currentGold", 0))),
        "level":            int(finite(ap.get("level", 1), 1)),
        "kda":              f"{sc.get('kills',0)}/{sc.get('deaths',0)}/{sc.get('assists',0)}",
        "items":            items,
        "wins":             sc.get("kills", 0),
        "losses":           sc.get("deaths", 0),
        "alive_teams":      (alive + 1) // 2,
        "rank":             rank_str,
        "round":            None,  # set by Coach._on_state_received
        "teams":            teams,
        "augments":         [],
        "_raw_event_count": len(combat_events),
    }
