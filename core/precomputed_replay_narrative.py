"""core/precomputed_replay_narrative.py - deterministic replay-narrative substrate.

The HZ (Haiku-to-ZERO) precompute substrate for postgame replay coaching. The
served path, ``coaches/replay_coach.analyze_match`` (Haiku), is currently
DORMANT; this module is the deterministic candidate that builds the SAME shape
of output (a summary paragraph, an impact-ranked key-moments list, and
per-component lessons) with NO Claude / Riot / live-game dependency - purely
from the ``rewind_history.db`` blob that ``coaches/replay_coach._load_match``
already returns.

This is the do-not-flip-blind PRECOMPUTE side. It is SHADOW-ONLY: nothing here
flips the live coach. ``core/replay_narrative_shadow.py`` records the
deterministic narrative alongside the live coach output for offline validation,
mirroring ``core/det_coach_shadow.py`` / ``core/champ_select_shadow.py``.

Reused upstream (grounded, cited):
  * ``coaches/replay_coach._load_match`` (replay_coach.py:55-74) returns
    ``{"match": dict, "participants": [dict], "events": [dict]}``; this is the
    exact blob shape ``build_narrative`` consumes.
  * ``core.post_game_rubric.compute_role_grade`` (post_game_rubric.py:378) for
    the numeric per-component scores feeding LESSONS. We do NOT re-derive the
    rubric math.
  * ``core.obj_participation`` column model (obj_participation.py:63-83) for the
    objective-participation ratio. ``compute_obj_participation`` needs a live
    sqlite connection (obj_participation.py:157), which the blob does not carry,
    so we apply the SAME column model directly to the in-blob participant rows
    (``_obj_participation_from_rows``). This keeps ``build_narrative`` a pure
    function over the blob with no DB re-open.

Pure function, fail-soft on every missing/malformed field - never raises.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from core.obj_participation import _challenges_objectives
from core.post_game_rubric import compute_role_grade

log = logging.getLogger("rc.precomputed_replay_narrative")

# Objective columns summed per participant row to approximate
# objective-participation. Same set as core.obj_participation._OBJ_COLUMNS
# (obj_participation.py:63-70) so the deterministic narrative scores the same
# axis the live rubric route does.
_OBJ_COLUMNS = (
    "dragon_kills",
    "baron_kills",
    "objectives_stolen",
    "objectives_stolen_assists",
    "first_tower_kill",
    "first_tower_assist",
)

# Timeline event types that we surface as candidate key-moments. Kept narrow so
# the impact ranking is over genuinely match-shaping events, not every level-up.
_MOMENT_EVENT_TYPES = frozenset(
    {
        "CHAMPION_KILL",
        "CHAMPION_SPECIAL_KILL",
        "ELITE_MONSTER_KILL",
        "BUILDING_KILL",
        "TURRET_PLATE_DESTROYED",
    }
)

# CHAMPION_SPECIAL_KILL carries its type only in raw_json. Verified live over
# the 63505 rows in rewind_history.db: killType is one of KILL_FIRST_BLOOD /
# KILL_MULTI / KILL_ACE, KILL_MULTI alone adds multiKillLength, killer_id is
# populated and victim_id is always NULL - the companion CHAMPION_KILL row at
# the same timestamp carries the victim. A special-kill line therefore names
# the killer and the feat, never a victim.
_MULTI_KILL_NAMES = {
    2: "Double Kill",
    3: "Triple Kill",
    4: "Quadra Kill",
    5: "Penta Kill",
}

# Elite monsters and buildings, named and tiered. Counted over the live
# timeline_events table: HORDE 3336 / RIFTHERALD 664 / BARON_NASHOR 577 /
# DRAGON 2479 over six subtypes + ELDER_DRAGON 43 + UNKNOWN 51 / ATAKHAN 143,
# and OUTER 6684 / NEXUS_TURRET 4810 / INHIBITOR 4803 / BASE 3661 / INNER 2462.
#
# Impact was previously "BARON or DRAGON -> 60, any other elite -> 45", which
# priced a 6-minute infernal the same as Baron, an Elder the same as either,
# and voidgrubs above a champion kill. (label, impact) keyed by the subtype
# where one exists, else the monster type.
_MONSTER_TIERS: dict[str, tuple[str, float]] = {
    "ELDER_DRAGON": ("Elder Dragon", 70.0),
    "BARON_NASHOR": ("Baron Nashor", 60.0),
    "ATAKHAN": ("Atakhan", 55.0),
    "FIRE_DRAGON": ("Infernal Drake", 45.0),
    "EARTH_DRAGON": ("Mountain Drake", 45.0),
    "WATER_DRAGON": ("Ocean Drake", 45.0),
    "AIR_DRAGON": ("Cloud Drake", 45.0),
    "CHEMTECH_DRAGON": ("Chemtech Drake", 45.0),
    "HEXTECH_DRAGON": ("Hextech Drake", 45.0),
    "DRAGON": ("Drake", 45.0),
    "RIFTHERALD": ("Rift Herald", 40.0),
    "HORDE": ("Voidgrub", 22.0),
}
_MONSTER_FALLBACK = ("an objective", 40.0)

# Buildings tier by lane depth. The inhibitor rows carry
# building_type=INHIBITOR_BUILDING with a NULL tower_type and the old impact
# branch read tower_type only, so all 4803 inhibitors scored as ordinary
# towers despite the branch intending otherwise.
_BUILDING_TIERS: dict[str, tuple[str, float]] = {
    "INHIBITOR_BUILDING": ("Inhibitor", 50.0),
    "NEXUS_TURRET": ("Nexus Turret", 48.0),
    "BASE_TURRET": ("Base Turret", 44.0),
    "INNER_TURRET": ("Inner Turret", 40.0),
    "OUTER_TURRET": ("Outer Turret", 35.0),
}
_BUILDING_FALLBACK = ("a structure", 35.0)


def _monster_tier(event: dict[str, Any]) -> tuple[str, float]:
    """(label, impact) for an ELITE_MONSTER_KILL, subtype first."""
    subtype = (event.get("monster_subtype") or "").upper()
    if subtype in _MONSTER_TIERS:
        return _MONSTER_TIERS[subtype]
    monster = (event.get("monster_type") or "").upper()
    return _MONSTER_TIERS.get(monster) or _MONSTER_FALLBACK


def _building_tier(event: dict[str, Any]) -> tuple[str, float]:
    """(label, impact) for a BUILDING_KILL, tower tier first."""
    tower = (event.get("tower_type") or "").upper()
    if tower in _BUILDING_TIERS:
        return _BUILDING_TIERS[tower]
    building = (event.get("building_type") or "").upper()
    return _BUILDING_TIERS.get(building) or _BUILDING_FALLBACK


def _as_float(value: Any) -> float:
    """Best-effort float coercion. Returns 0.0 on any failure."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _as_int(value: Any) -> int:
    """Best-effort int coercion. Returns 0 on any failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _fmt_clock(ms: Any) -> str:
    """Format a timestamp_ms as M:SS. Fail-soft to 0:00."""
    seconds = _as_int(ms) // 1000
    if seconds < 0:
        seconds = 0
    return f"{seconds // 60}:{seconds % 60:02d}"


def _row_obj_total(row: dict[str, Any]) -> float:
    """Sum one participant row's objective contribution.

    Mirrors the core.obj_participation 9-column model: the 6 SQL columns plus
    riftHeraldTakedowns + voidMonsterKill + the non-overlapping turret count
    (turret_takedowns beyond the first-tower binary sentinels). Fail-soft on
    every missing/malformed field.
    """
    base = sum(_as_float(row.get(col)) for col in _OBJ_COLUMNS)
    herald, void, turret_raw = _challenges_objectives(row.get("challenges_json"))
    # turret_takedowns is also a real participants column; prefer it when the
    # challenges blob is absent so the credit is not silently dropped.
    if turret_raw <= 0:
        turret_raw = _as_float(row.get("turret_takedowns"))
    ftk = _as_float(row.get("first_tower_kill"))
    fta = _as_float(row.get("first_tower_assist"))
    turret_extra = max(turret_raw - ftk - fta, 0.0)
    return base + herald + void + turret_extra


def _obj_participation_from_rows(
    participants: list[dict[str, Any]],
    team_id: Any,
    puuid: Any,
) -> float:
    """Objective-participation ratio for the operator over their team total.

    Applies the core.obj_participation column model (obj_participation.py:63-83)
    to the in-blob participant rows so no live DB connection is needed. Returns
    a float in [0.0, 1.0]; 0.0 when the team took no objectives (the rubric
    correctly under-scores a zero-objective game) or on any degenerate input.
    """
    if not participants:
        return 0.0
    numerator = 0.0
    denominator = 0.0
    for row in participants:
        if not isinstance(row, dict):
            continue
        if row.get("team_id") != team_id:
            continue
        row_total = _row_obj_total(row)
        denominator += row_total
        # Match the operator row by puuid when available, else by champion name
        # equality is not reliable; puuid is the stable key.
        if puuid and row.get("puuid") == puuid:
            numerator = row_total
    if denominator <= 0:
        return 0.0
    ratio = numerator / denominator
    if ratio < 0.0:
        return 0.0
    if ratio > 1.0:
        return 1.0
    return ratio


def _find_operator_row(
    participants: list[dict[str, Any]],
    match: dict[str, Any],
) -> dict[str, Any] | None:
    """Locate the operator's participant row from the blob.

    The matches row carries tracked_champion_id + tracked_team_id but no puuid,
    so we match on champion_id within the tracked team, falling back to
    champion_name, then to the first row of the tracked team.
    """
    if not participants:
        return None
    tracked_team = match.get("tracked_team_id")
    tracked_cid = match.get("tracked_champion_id")
    tracked_name = match.get("tracked_champion_name")

    team_rows = [
        r for r in participants
        if isinstance(r, dict) and r.get("team_id") == tracked_team
    ]
    pool = team_rows or [r for r in participants if isinstance(r, dict)]
    if not pool:
        return None
    if tracked_cid is not None:
        for r in pool:
            if r.get("champion_id") == tracked_cid:
                return r
    if tracked_name:
        for r in pool:
            if r.get("champion_name") == tracked_name:
                return r
    return pool[0]


def _special_kill(event: dict[str, Any]) -> tuple[str, int]:
    """Parse a CHAMPION_SPECIAL_KILL row into (kill_type, multi_kill_length).

    raw_json arrives as the stored JSON string, or already parsed when a caller
    hydrated it. Returns ("", 0) for anything unrecognised so every consumer can
    branch on a plain string and never sees None.
    """
    raw = event.get("raw_json")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return ("", 0)
    if not isinstance(raw, dict):
        return ("", 0)
    kill_type = raw.get("killType")
    if not isinstance(kill_type, str):
        return ("", 0)
    return (kill_type, _as_int(raw.get("multiKillLength")))


def _multi_kill_name(length: int) -> str:
    """Riot caps multiKillLength at 5; anything else degrades to a count."""
    return _MULTI_KILL_NAMES.get(length) or f"{length}-kill streak"


# Riot's multikill window. Consecutive kills further apart than this start a
# new streak rather than extending the current one.
_MULTI_KILL_WINDOW_MS = 10_000


def _suppressed_special_kill_ids(events: list) -> set[int]:
    """id()s of CHAMPION_SPECIAL_KILL rows another row already describes.

    Two distinct redundancies, both measured against the 63505 special-kill
    rows in rewind_history.db:

    1. RUNG COLLAPSE. A pentakill does not arrive as one row - Riot emits a
       rung at every step, so one feat lands as double -> triple -> quadra ->
       penta. On NA1_5094273204 a 14:42 Quadra and a 14:46 Penta by the same
       player are the same streak, and keeping both spends two of the five
       moment slots on one event. A streak continues while the same killer's
       next rung is strictly longer and lands inside the multikill window; only
       the terminal rung is a moment.

    2. COINCIDENT ACE. A multikill that also aces emits a KILL_ACE alongside
       the KILL_MULTI, describing one feat twice. The distribution is sharply
       bimodal: 5202 aces sit at EXACTLY 0 ms from a same-killer multikill and
       every other ace is 6 s or more away, so coincidence is exact-timestamp
       rather than a window, and no ace that stands on its own is at risk. The
       multikill is the more specific description, so the ace yields.

    KILL_FIRST_BLOOD is deliberately NOT folded in. It also collides with a
    KILL_MULTI on the same timestamp (2 occurrences - a first-blood double
    kill), but "first blood" and "double kill" are two different facts about
    the same instant rather than one fact told twice.

    Keyed on id() rather than on a value tuple because two genuinely distinct
    rows can be byte-identical, and returning a set of dropped identities would
    take both.
    """
    multi_by_killer: dict[Any, list] = {}
    aces: list = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        if (ev.get("event_type") or "") != "CHAMPION_SPECIAL_KILL":
            continue
        kill_type = _special_kill(ev)[0]
        if kill_type == "KILL_MULTI":
            multi_by_killer.setdefault(ev.get("killer_id"), []).append(ev)
        elif kill_type == "KILL_ACE":
            aces.append(ev)

    suppressed: set[int] = set()

    for rows in multi_by_killer.values():
        rows.sort(key=lambda e: _as_int(e.get("timestamp_ms")))
        for cur, nxt in zip(rows, rows[1:]):
            gap = _as_int(nxt.get("timestamp_ms")) - _as_int(cur.get("timestamp_ms"))
            longer = _special_kill(nxt)[1] > _special_kill(cur)[1]
            if longer and 0 <= gap <= _MULTI_KILL_WINDOW_MS:
                suppressed.add(id(cur))

    multi_instants = {
        (ev.get("killer_id"), _as_int(ev.get("timestamp_ms")))
        for rows in multi_by_killer.values()
        for ev in rows
    }
    for ev in aces:
        if (ev.get("killer_id"), _as_int(ev.get("timestamp_ms"))) in multi_instants:
            suppressed.add(id(ev))

    return suppressed


def _moment_impact(event: dict[str, Any], operator_pid: Any) -> float:
    """Score a single timeline event for impact ranking.

    Higher = more match-shaping. Epic monsters and buildings rank above plain
    kills; a kill/death/assist the operator was directly involved in is boosted
    so the operator's own moments float to the top. Bounty + shutdown_bounty add
    a gold-swing signal. Fully deterministic.
    """
    etype = event.get("event_type") or ""
    impact = 0.0
    if etype == "ELITE_MONSTER_KILL":
        impact = _monster_tier(event)[1]
    elif etype == "BUILDING_KILL":
        impact = _building_tier(event)[1]
    elif etype == "TURRET_PLATE_DESTROYED":
        impact = 20.0
    elif etype == "CHAMPION_KILL":
        impact = 30.0
        impact += _as_float(event.get("bounty")) / 50.0
        impact += _as_float(event.get("shutdown_bounty")) / 25.0
    elif etype == "CHAMPION_SPECIAL_KILL":
        kill_type, length = _special_kill(event)
        if kill_type == "KILL_MULTI":
            # 42 / 54 / 66 / 78 for double through penta. Calibrated against
            # the fixed anchors above: a double kill sits between a plain kill
            # and an outer tower, and a pentakill clears the 60-point epic
            # monster floor because it is the headline of any game it happens
            # in. A KILL_MULTI with no length is a multikill by definition, so
            # it floors at 2 rather than scoring as nothing.
            impact = 30.0 + 12.0 * (max(2, length) - 1)
        elif kill_type == "KILL_ACE":
            impact = 55.0
        elif kill_type == "KILL_FIRST_BLOOD":
            impact = 32.0
        else:
            # Unrecognised killType: still a moment, ranked below a plain kill.
            impact = 25.0

    # Operator involvement boost (killer / victim / assist).
    if operator_pid is not None:
        if event.get("killer_id") == operator_pid:
            impact += 25.0
        elif event.get("victim_id") == operator_pid:
            impact += 20.0
        else:
            assists = event.get("assisting_ids_json")
            if assists:
                try:
                    parsed = json.loads(assists) if isinstance(assists, str) else assists
                    if isinstance(parsed, list) and operator_pid in parsed:
                        impact += 10.0
                except (ValueError, TypeError):
                    pass
    return impact


def _describe_moment(event: dict[str, Any], operator_pid: Any,
                     names: dict[Any, str] | None = None) -> str:
    """Build a deterministic one-line description of a timeline event.

    *names* maps participant_id -> champion name. Optional and defaulted so
    every existing caller keeps working; when absent, kills involving other
    players degrade to the old generic wording rather than emitting "None
    kills None". The row already carries killer_id and victim_id, so throwing
    the identities away was a loss with no upside - the bar to clear is a
    chapter line like "First Blood - Vayne kills Lee Sin".
    """
    names = names or {}
    clock = _fmt_clock(event.get("timestamp_ms"))
    etype = event.get("event_type") or "EVENT"
    if etype == "ELITE_MONSTER_KILL":
        label = _monster_tier(event)[0]
        if event.get("killer_id") == operator_pid:
            return f"{clock} - you took {label}"
        taker = names.get(event.get("killer_id"))
        return (f"{clock} - {label} taken by {taker}" if taker
                else f"{clock} - {label} taken")
    if etype == "BUILDING_KILL":
        label = _building_tier(event)[0]
        if event.get("killer_id") == operator_pid:
            return f"{clock} - you destroyed {label}"
        taker = names.get(event.get("killer_id"))
        return (f"{clock} - {label} destroyed by {taker}" if taker
                else f"{clock} - {label} destroyed")
    if etype == "TURRET_PLATE_DESTROYED":
        return f"{clock} - turret plate destroyed"
    if etype == "CHAMPION_SPECIAL_KILL":
        kill_type, length = _special_kill(event)
        is_operator = event.get("killer_id") == operator_pid
        killer = names.get(event.get("killer_id"))
        if kill_type == "KILL_MULTI":
            feat = _multi_kill_name(max(2, length))
            if is_operator:
                return f"{clock} - you got a {feat}"
            return f"{clock} - {killer} {feat}" if killer else f"{clock} - {feat}"
        if kill_type == "KILL_ACE":
            if is_operator:
                return f"{clock} - you aced the enemy team"
            if killer:
                return f"{clock} - {killer} aces the enemy team"
            return f"{clock} - enemy team aced"
        if kill_type == "KILL_FIRST_BLOOD":
            if is_operator:
                return f"{clock} - First Blood - you drew first blood"
            if killer:
                return f"{clock} - First Blood - {killer}"
            return f"{clock} - First Blood"
        return f"{clock} - special kill"
    if etype == "CHAMPION_KILL":
        killer = names.get(event.get("killer_id"))
        victim = names.get(event.get("victim_id"))
        if event.get("killer_id") == operator_pid:
            tag = f"you killed {victim}" if victim else "you secured a kill"
        elif event.get("victim_id") == operator_pid:
            tag = f"{killer} killed you" if killer else "you were killed"
        elif killer and victim:
            tag = f"{killer} kills {victim}"
        else:
            tag = "a kill traded"
        shutdown = _as_float(event.get("shutdown_bounty"))
        suffix = " (shutdown)" if shutdown > 0 else ""
        return f"{clock} - {tag}{suffix}"
    return f"{clock} - {etype.replace('_', ' ').lower()}"


# Per-component lesson templates keyed by the compute_role_grade component key.
# Each entry is (low_lesson, high_lesson); the deterministic builder picks one
# by comparing the component's normalized strength against the role weight.
_LESSON_TEMPLATES: dict[str, tuple[str, str]] = {
    "kda": (
        "KDA trailed the role baseline - prioritise surviving fights and "
        "trading deaths for objectives.",
        "Strong KDA this game - your fight selection and positioning paid off.",
    ),
    "cs_per_min": (
        "CS per minute was below the role median - tighten your wave farming "
        "between skirmishes.",
        "CS per minute beat the role median - your farming was efficient.",
    ),
    "obj_participation": (
        "Low objective participation - rotate to drakes/baron/towers with your "
        "team more often.",
        "High objective participation - you were present for the key takedowns.",
    ),
    "vision": (
        "Vision score lagged the role baseline - place and clear more wards "
        "around objectives.",
        "Good vision score - your warding gave the team map control.",
    ),
    "dpm": (
        "Damage per minute was under the role median - look for more committed "
        "fight windows to apply damage.",
        "High damage per minute - you were a real threat in fights.",
    ),
}


def _lessons_from_grade(grade: dict[str, Any]) -> list[str]:
    """Turn the rubric component scores into deterministic LESSONS.

    Reuses the numeric components from core.post_game_rubric.compute_role_grade
    (post_game_rubric.py:422-436). We do NOT re-derive the rubric math; we only
    interpret the per-component contribution as a low/high lesson. The two
    weakest components yield improvement lessons; the single strongest yields a
    reinforcement lesson, so the operator always gets at least one positive.
    """
    components = grade.get("components")
    if not isinstance(components, dict) or not components:
        return []
    # Sort ascending by contribution; the lowest are the biggest gaps.
    ranked = sorted(
        (
            (key, _as_float(val))
            for key, val in components.items()
            if key in _LESSON_TEMPLATES
        ),
        key=lambda kv: kv[1],
    )
    if not ranked:
        return []
    lessons: list[str] = []
    # Up to two improvement lessons (lowest contributions).
    for key, _val in ranked[:2]:
        lessons.append(_LESSON_TEMPLATES[key][0])
    # One reinforcement lesson (highest contribution), if distinct.
    top_key, _top_val = ranked[-1]
    if top_key not in {k for k, _ in ranked[:2]}:
        lessons.append(_LESSON_TEMPLATES[top_key][1])
    return lessons


def _build_summary(
    match: dict[str, Any],
    operator_row: dict[str, Any] | None,
    grade: dict[str, Any],
    key_moment_count: int,
) -> str:
    """Compose the deterministic SUMMARY string from the match header + grade."""
    champ = (
        (operator_row or {}).get("champion_name")
        or match.get("tracked_champion_name")
        or "Unknown"
    )
    win = "WIN" if match.get("tracked_win") else "LOSS"
    dur_min = _as_int(match.get("game_duration_s")) // 60
    kills = _as_int(match.get("tracked_kills"))
    deaths = _as_int(match.get("tracked_deaths"))
    assists = _as_int(match.get("tracked_assists"))
    mode = match.get("game_mode") or "?"
    patch = match.get("patch") or "?"
    role = grade.get("role") or "?"
    g_score = grade.get("total_score")
    g_bucket = grade.get("percentile_grade") or "?"
    score_str = f"{g_score:.0f}" if isinstance(g_score, (int, float)) else "?"
    return (
        f"{champ} ({role}) {win} in {dur_min} min on patch {patch} ({mode}). "
        f"KDA {kills}/{deaths}/{assists}, rubric grade {g_bucket} "
        f"({score_str}/100) across {key_moment_count} key moments."
    )


def build_narrative(blob: dict[str, Any] | None) -> dict[str, Any]:
    """Build a deterministic replay narrative from a rewind_history.db blob.

    Args:
        blob: the dict returned by ``coaches/replay_coach._load_match``
            (replay_coach.py:55-74) - ``{"match": dict, "participants": [dict],
            "events": [dict]}``. ``None`` or any malformed shape is fail-soft.

    Returns:
        A dict with keys:
          * ``ok`` (bool): True when a summary was produced.
          * ``summary`` (str): one-paragraph deterministic result + grade story.
          * ``key_moments`` (list[dict]): impact-ranked timeline moments, each
            ``{"clock", "event_type", "impact", "text"}``, highest impact first.
          * ``lessons`` (list[str]): rubric-component improvement/reinforcement
            lessons from core.post_game_rubric.
          * ``grade`` (dict): the raw compute_role_grade result (role,
            total_score, components, percentile_grade) for downstream use.

    Pure + deterministic; never raises (fail-soft to an empty-but-shaped dict).
    """
    out: dict[str, Any] = {
        "ok": False,
        "summary": "",
        "key_moments": [],
        "lessons": [],
        "grade": {},
    }
    try:
        if not isinstance(blob, dict):
            return out
        match = blob.get("match")
        if not isinstance(match, dict) or not match:
            return out
        participants = blob.get("participants")
        if not isinstance(participants, list):
            participants = []
        events = blob.get("events")
        if not isinstance(events, list):
            events = []

        operator_row = _find_operator_row(participants, match)

        # Build rubric stats from the operator row (preferred) or the matches
        # tracked_* fields (fallback). Reuses the exact stats keys
        # compute_role_grade expects (post_game_rubric.py:403-410).
        if operator_row is not None:
            cs = _as_int(operator_row.get("total_minions_killed")) + _as_int(
                operator_row.get("neutral_minions_killed")
            )
            obj_pct = _obj_participation_from_rows(
                participants,
                operator_row.get("team_id"),
                operator_row.get("puuid"),
            )
            stats = {
                "kills": _as_int(operator_row.get("kills")),
                "deaths": _as_int(operator_row.get("deaths")),
                "assists": _as_int(operator_row.get("assists")),
                "cs": cs,
                "game_time_s": _as_int(match.get("game_duration_s")),
                "vision_score": _as_int(operator_row.get("vision_score")),
                "damage_dealt_to_champions": _as_int(
                    operator_row.get("total_damage_dealt_to_champs")
                ),
                "obj_participation_pct": obj_pct,
            }
            role = (
                operator_row.get("team_position")
                or operator_row.get("role")
                or match.get("tracked_lane")
                or ""
            )
        else:
            stats = {
                "kills": _as_int(match.get("tracked_kills")),
                "deaths": _as_int(match.get("tracked_deaths")),
                "assists": _as_int(match.get("tracked_assists")),
                "cs": 0,
                "game_time_s": _as_int(match.get("game_duration_s")),
                "vision_score": 0,
                "damage_dealt_to_champions": 0,
                "obj_participation_pct": 0.0,
            }
            role = match.get("tracked_lane") or ""

        grade = compute_role_grade(stats, role)

        operator_pid = (
            operator_row.get("participant_id") if operator_row is not None else None
        )

        # Impact-rank the timeline. Score every candidate event, sort by impact
        # descending (stable on timestamp for ties), keep the top 5.
        scored: list[tuple[float, int, dict[str, Any]]] = []
        superseded = _suppressed_special_kill_ids(events)
        for ev in events:
            if not isinstance(ev, dict):
                continue
            if (ev.get("event_type") or "") not in _MOMENT_EVENT_TYPES:
                continue
            if id(ev) in superseded:
                continue
            impact = _moment_impact(ev, operator_pid)
            scored.append((impact, _as_int(ev.get("timestamp_ms")), ev))
        scored.sort(key=lambda t: (-t[0], t[1]))

        names = {
            p.get("participant_id"): p.get("champion_name") or p.get("champion")
            for p in participants
            if isinstance(p, dict) and (p.get("champion_name") or p.get("champion"))
        }

        # Dedup on event IDENTITY, not on the clock. Three matches in the live
        # db carry 6x and 12x duplicated timeline rows (the writer uses
        # INSERT OR IGNORE but the table had no UNIQUE constraint for it to
        # bite on), and one narrative came out as five copies of the same
        # 1:45 kill. Keying on the clock alone would instead delete real
        # teamfight kills that legitimately share a second.
        key_moments: list[dict[str, Any]] = []
        seen: set[tuple] = set()
        for impact, _ts, ev in scored:
            # The special-kill type is part of the identity: a pentakill that
            # aces emits a KILL_MULTI and a KILL_ACE row at the SAME timestamp
            # with the same killer and a NULL victim, so without it the two
            # collide and one of the game's two headline moments is silently
            # dropped.
            ident = (
                ev.get("timestamp_ms"), ev.get("event_type"),
                ev.get("killer_id"), ev.get("victim_id"),
                ev.get("participant_id"), ev.get("building_type"),
                ev.get("monster_type"), _special_kill(ev),
            )
            if ident in seen:
                continue
            seen.add(ident)
            key_moments.append(
                {
                    "clock": _fmt_clock(ev.get("timestamp_ms")),
                    "event_type": ev.get("event_type") or "",
                    "impact": round(impact, 1),
                    "text": _describe_moment(ev, operator_pid, names),
                }
            )
            if len(key_moments) == 5:
                break

        lessons = _lessons_from_grade(grade)
        summary = _build_summary(match, operator_row, grade, len(key_moments))

        out.update(
            {
                "ok": bool(summary),
                "summary": summary,
                "key_moments": key_moments,
                "lessons": lessons,
                "grade": grade,
            }
        )
        return out
    except Exception:  # noqa: BLE001 - fail-soft, never raise on the build path
        log.debug("build_narrative failed", exc_info=True)
        return out
