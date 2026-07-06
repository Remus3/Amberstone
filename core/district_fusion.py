# arch: API-ground-truth fusion over the CV district presence vector | section=core | frozen=no
"""core.district_fusion - ZOI Wave 2 spec C (agent-fusion).

Fuses Live Client API ground truth over the CV-derived per-district
presence vector (``zoi["districts"]``, agent-presence spec B). API GROUND
TRUTH OVERRIDES CV: blob-detected dots are presence-not-identity and can
over-count, ghost, or miss; the ``:2999`` scoreboard + event stream is a
hard fact. Four fusion steps, applied in order:

1. DEAD-CHAMP WEIGHT CAP - a dead champion cannot be present anywhere, so
   the per-team per-district presence is capped at (team_size - dead).
   Death is read fail-soft from the scoreboard player rows
   (``lc["players"]``, dashboard/_liveclient.py:176-185). NOTE verified
   2026-07-05: today those rows carry only {position, team, creep_score,
   is_active} - NO isDead/respawnTimer - so the cap is INERT until the
   summary surfaces a death field. The reader accepts is_dead / isDead
   (bool) and respawn_in_s / respawnTimer (>0) so either a _liveclient
   extension or vision_tracker-shaped rows activate it with no code
   change here.
2. STRUCTURE RECLASSIFY - a turret/inhib kill within OBJ_FUSE_WINDOW_S
   implies the killing team was present at that structure: pinned to the
   lane district (SR, lane parsed from the structure name - inhib
   ``Barracks_T2_L1``, turret ``Turret_T2_L_03_A``; token L/C/R ->
   top/mid/bot as in core/event_callouts.py:104,441-454) or to the one
   bridge (ARAM). The killer team is inferred from the owner token
   (T1=ORDER / T2=CHAOS) vs the active player's side; when the side
   cannot be determined the kill is annotated but never forces a count
   (a wrong team is worse than none).
3. OBJECTIVE CONFIRM - a dragon/baron/herald kill with a known
   killer_team within OBJ_FUSE_WINDOW_S forces that team's presence in
   dragon_pit / baron_pit (herald lives in the baron pit). Event shape:
   dashboard/_liveclient.py:265-301.
4. WARD INFERENCE (v0 hook) - SR-ONLY and has_capability(mode,
   "has_wards")-gated (core/mode_capabilities.py, fail-CLOSED). If wards
   are impossible in the mode there is NO ward-derived inference of any
   kind (ARAM / Arena hard-off). v0 ships the gate + hook only, not a
   ward model.

Mode scope: fusion applies only where the zoi gate can reach it
(``sr`` / ``aram`` - dashboard/_state_builder.py:469). ARAM keeps
MIA semantics inert by construction (shared vision; nothing here reads
fog) while dead-cap + structure-reclassify still apply. Arena / Brawl /
TFT / unknown modes are never invoked live, but calling anyway is a
graceful no-op: the fused vector mirrors the raw counts with no
annotations.

Output contract: SAME row shape as the input vector - every input key is
copied through untouched - plus exactly two additive annotation keys per
row: ``fused_present`` ({"ally": int, "enemy": int}, the API-corrected
counts) and ``fusion_notes`` (list of str tags, e.g. "dead_cap:enemy:5->3",
"structure:turret:ally", "objective:dragon:enemy").

Pure + stateless + fail-soft everywhere: no I/O, no caches, and no input
(bad numerics, unknown mode, corrupt rows, malformed events) ever raises -
degrade to pass-through / [] per the zoi_influence contract.
"""
from __future__ import annotations

from core.mode_capabilities import district_config, has_capability

#: Seconds after a structure/objective kill during which the killing team
#: is asserted present at the kill site (ZOI plan section 4, spec C).
OBJ_FUSE_WINDOW_S = 8.0

_TEAMS = ("ally", "enemy")
_DEFAULT_TEAM_SIZE = 5

# Structure-name lane token -> lane (core/event_callouts.py:104 convention).
_LANE_BY_TOKEN = {"L": "top", "C": "mid", "R": "bot"}

# Lane -> SR district id (config/minimap_grids/sr.json).
_SR_LANE_DISTRICT = {"top": "top_lane", "mid": "mid_lane", "bot": "bot_lane"}

#: The single ARAM lane district every structure kill pins to.
_ARAM_BRIDGE_ID = "aram_bridge"

# Objective name -> SR district id (herald lives in the baron pit).
_OBJECTIVE_DISTRICT = {
    "dragon": "dragon_pit",
    "baron": "baron_pit",
    "herald": "baron_pit",
}

# Structure owner token -> Riot side string (Live Client naming).
_SIDE_BY_TOKEN = {"T1": "ORDER", "T2": "CHAOS"}


# --- input readers (all fail-soft) -------------------------------------------

def _int0(value):
    """Best-effort non-negative int; 0 on any garbage."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def _present_counts(row):
    """Raw per-team presence from a presence-vector row.

    Primary contract (agent-presence spec B): ``row["team_present"] =
    {"ally": n, "enemy": n}``. Accepts ``present`` and flat ``ally`` /
    ``enemy`` spellings fail-soft so a shape drift degrades to zeros,
    never an exception.
    """
    for key in ("team_present", "present"):
        tp = row.get(key)
        if isinstance(tp, dict):
            return {t: _int0(tp.get(t)) for t in _TEAMS}
    if any(k in row for k in _TEAMS):
        return {t: _int0(row.get(t)) for t in _TEAMS}
    return {t: 0 for t in _TEAMS}


def _row_is_dead(row):
    """True when a scoreboard/tracker player row marks the champ dead.

    Accepts is_dead / isDead booleans and respawn_in_s / respawnTimer
    positive numbers. Absent fields -> alive (cap stays inert on today's
    lc rows - see module docstring).
    """
    for key in ("is_dead", "isDead"):
        if row.get(key) is True:
            return True
    for key in ("respawn_in_s", "respawnTimer"):
        v = row.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            return True
    return False


def _ally_side(players):
    """The active player's Riot side string ("ORDER"/"CHAOS"), or None."""
    for row in players:
        if isinstance(row, dict) and row.get("is_active") is True:
            side = row.get("team")
            if isinstance(side, str) and side:
                return side
    return None


def _alive_counts(lc_events):
    """Per-team alive counts {"ally": n, "enemy": n} from lc["players"].

    Team size defaults to 5 per side when the scoreboard is absent or
    side-less (cap then only trims impossible >5 blob counts). Never
    raises.
    """
    alive = {t: _DEFAULT_TEAM_SIZE for t in _TEAMS}
    try:
        players = lc_events.get("players")
        if not isinstance(players, list):
            return alive
        rows = [r for r in players if isinstance(r, dict)]
        ally_side = _ally_side(rows)
        if ally_side is None:
            return alive
        for team in _TEAMS:
            def _mine(row, _team=team):
                side = row.get("team")
                if not isinstance(side, str) or not side:
                    return False
                same = side == ally_side
                return same if _team == "ally" else not same
            mine = [r for r in rows if _mine(r)]
            if not mine:
                continue
            dead = sum(1 for r in mine if _row_is_dead(r))
            alive[team] = max(0, len(mine) - dead)
    except Exception:  # noqa: BLE001 - fail-soft contract: never raises
        return {t: _DEFAULT_TEAM_SIZE for t in _TEAMS}
    return alive


# --- event windows ------------------------------------------------------------

def _within_window(down_at_s, game_time_s):
    """True when the kill happened 0..OBJ_FUSE_WINDOW_S seconds ago."""
    try:
        age = float(game_time_s) - float(down_at_s)
    except (TypeError, ValueError):
        return False
    return 0.0 <= age <= OBJ_FUSE_WINDOW_S


def _structure_lane(name):
    """Lane ("top"/"mid"/"bot") from a structure name, or "".

    Handles both the inhib token (``Barracks_T2_L1`` - letter+digits) and
    the turret token (``Turret_T2_L_03_A`` - a bare L/C/R part). An
    unrecognized name yields "" so a naming change can never produce a
    WRONG lane (mirrors core/event_callouts.py:441-454).
    """
    if not isinstance(name, str):
        return ""
    for part in name.upper().split("_"):
        if part in _LANE_BY_TOKEN:
            return _LANE_BY_TOKEN[part]
        if (len(part) >= 2 and part[0] in _LANE_BY_TOKEN
                and part[1:].isdigit()):
            return _LANE_BY_TOKEN[part[0]]
    return ""


def _structure_killer_team(name, ally_side):
    """"ally"/"enemy" who killed the named structure, or None.

    The owner token (T1=ORDER / T2=CHAOS) names whose structure DIED; the
    killer is the opposing side, mapped onto ally/enemy via the active
    player's side. Unknown owner or unknown ally side -> None (annotate
    only, never force a count).
    """
    if not isinstance(name, str) or ally_side not in ("ORDER", "CHAOS"):
        return None
    owner_side = None
    for part in name.upper().split("_"):
        if part in _SIDE_BY_TOKEN:
            owner_side = _SIDE_BY_TOKEN[part]
            break
    if owner_side is None:
        return None
    killer_side = "CHAOS" if owner_side == "ORDER" else "ORDER"
    return "ally" if killer_side == ally_side else "enemy"


def _structure_events(lc_events, game_time_s, grid_stem, ally_side):
    """Yield (district_id, kind, team_or_None) for in-window structure kills."""
    out = []
    for key, kind in (("turret_events", "turret"), ("inhib_events", "inhib")):
        events = lc_events.get(key)
        if not isinstance(events, list):
            continue
        for ev in events:
            if not isinstance(ev, dict):
                continue
            if not _within_window(ev.get("down_at_s"), game_time_s):
                continue
            name = ev.get("name")
            if grid_stem == "aram":
                district_id = _ARAM_BRIDGE_ID
            else:
                district_id = _SR_LANE_DISTRICT.get(_structure_lane(name), "")
            if not district_id:
                continue  # unknown lane: a generic pin would be a wrong pin
            out.append((district_id, kind, _structure_killer_team(name, ally_side)))
    return out


def _objective_events(lc_events, game_time_s):
    """Yield (district_id, obj_name, team) for in-window objective kills."""
    out = []
    events = lc_events.get("objective_events")
    if not isinstance(events, list):
        return out
    for ev in events:
        if not isinstance(ev, dict):
            continue
        district_id = _OBJECTIVE_DISTRICT.get(ev.get("name"))
        if district_id is None:
            continue
        team = ev.get("killer_team")
        if team not in _TEAMS:
            continue  # "unknown" must never force presence
        if not _within_window(ev.get("down_at_s"), game_time_s):
            continue
        out.append((district_id, ev.get("name"), team))
    return out


# --- ward inference (v0: gate + hook only) --------------------------------------

def _ward_inference(rows, lc_events, game_time_s):
    """v0 ward-inference hook - NO ward model yet.

    Returns a list of (district_id, note) annotations; always [] in v0.
    The hook is ONLY invoked when has_capability(mode, "has_wards") is
    True (SR), so ward-derived inference is structurally impossible in
    ARAM / Arena / Brawl / TFT / unknown modes. Notes returned by a
    future model must be "ward:"-prefixed strings.
    """
    return []


# --- public API -----------------------------------------------------------------

def fuse_districts(districts, lc_events, mode, game_time_s):
    """Fuse Live Client ground truth over the CV district presence vector.

    Args:
        districts: the ``zoi["districts"]`` presence vector (list of
            per-district dict rows, agent-presence spec B shape).
        lc_events: the lc summary dict in scope at the splice site
            (dashboard/_state_builder.py builds it at :338-342); only
            ``players`` / ``turret_events`` / ``inhib_events`` /
            ``objective_events`` are read, all fail-soft.
        mode: mode string in any spelling core.mode_capabilities accepts
            ("sr" / "SR" / "CLASSIC" / "aram" / "KIWI" / ...).
        game_time_s: current game clock in seconds (event-window anchor).

    Returns the districts_fused vector: one output row per (dict) input
    row, every input key copied through untouched, plus ``fused_present``
    and ``fusion_notes``. Never raises; catastrophic failure -> [].
    """
    try:
        if not isinstance(districts, list):
            return []
        if not isinstance(lc_events, dict):
            lc_events = {}

        grid_stem = district_config(mode)  # None for unknown modes
        fusion_on = grid_stem in ("sr", "aram")

        rows = []
        raw = {}
        for src in districts:
            if not isinstance(src, dict):
                continue  # fail-soft: garbage rows are dropped
            out = dict(src)
            counts = _present_counts(src)
            out["fused_present"] = counts
            out["fusion_notes"] = []
            rows.append(out)
            did = out.get("id") if isinstance(out.get("id"), str) else None
            if did is not None and did not in raw:
                raw[did] = out

        if not fusion_on or not rows:
            # Arena / Brawl / TFT / unknown: never fused live (the zoi gate
            # excludes them) - graceful no-op mirror of the raw counts.
            return rows

        # 1. dead-champ weight cap - dead champs cannot count as present.
        alive = _alive_counts(lc_events)
        for out in rows:
            for team in _TEAMS:
                have = out["fused_present"][team]
                cap = alive[team]
                if have > cap:
                    out["fused_present"][team] = cap
                    out["fusion_notes"].append(
                        f"dead_cap:{team}:{have}->{cap}")

        players = lc_events.get("players")
        ally_side = _ally_side(
            [r for r in players if isinstance(r, dict)]
        ) if isinstance(players, list) else None

        def _force(district_id, team, note):
            out = raw.get(district_id)
            if out is None:
                return  # district not in this mode's vector: skip quietly
            if team in _TEAMS and alive[team] > 0:
                if out["fused_present"][team] < 1:
                    out["fused_present"][team] = 1
            if note not in out["fusion_notes"]:
                out["fusion_notes"].append(note)

        # 2. structure reclassify - recent kills pin the killer to the lane
        # district (SR) or the bridge (ARAM).
        for district_id, kind, team in _structure_events(
                lc_events, game_time_s, grid_stem, ally_side):
            _force(district_id, team,
                   f"structure:{kind}:{team if team in _TEAMS else 'unattributed'}")

        # 3. objective confirm - dragon/baron/herald kills with a known
        # killer_team force presence in the pit.
        for district_id, obj, team in _objective_events(lc_events, game_time_s):
            _force(district_id, team, f"objective:{obj}:{team}")

        # 4. ward inference - SR-only, capability-gated (fail-CLOSED). When
        # wards are impossible in the mode the hook is never even called.
        if has_capability(mode, "has_wards"):
            try:
                for district_id, note in _ward_inference(
                        rows, lc_events, game_time_s) or []:
                    _force(district_id, None, str(note))
            except Exception:  # noqa: BLE001 - hook must never break fusion
                pass

        return rows
    except Exception:  # noqa: BLE001 - fail-soft contract: never raises
        return []
