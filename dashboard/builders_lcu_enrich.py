"""LCU / Match-V5 enrichment builders for the Post Game Review page.

Payload-boundary slice of the former monolithic `dashboard.builders`
(AUTONOMOUS_AUDIT spec 4.C, 2026-05-18). Holds the three functions that
parse external/untrusted Riot payloads: `_enrich_from_lcu`,
`_enrich_match_timeline`, `_attach_match_timeline`.

`dashboard.builders` re-exports these names so existing call sites keep
working without churn. Behavior is pinned by tests/test_builders_enrich.py +
tests/test_last_match_timeline.py + tests/test_last_match_surrender.py +
tests/test_builders_lcu_enrich_hardening_s144t217.py.

Trust boundary (true-audit s144 cycle 217): every field read here comes from
a payload RC did not author, and `_build_last_match` catches a raise only at
its outermost handler - so ONE wrong-shaped field used to turn the whole Post
Game Review payload, the DB match row included, into "internal error". The
parsers therefore never raise: a non-dict entry is skipped, a non-numeric or
non-finite number reads as 0 (`_as_int`), a non-string name reads as "", and
only the field that was bad degrades.
"""
import math

from dashboard._context import log as _log

# PGR S5 lane-comparison @N: the minute the per-participant gold/cs snapshot
# targets (aggregator G "gold@10 / cs@10"). The frame nearest this mark is used;
# a sub-10-minute game falls back to its last frame.
_AT_N_TARGET_MIN = 10


def _as_int(value, default=0):
    """Coerce one untrusted numeric field to an int, never raising.

    Keeps the old ``int(x or 0)`` reading for every value it accepted (int,
    bool, finite float, numeric string) and returns ``default`` for the
    values that used to raise: a non-numeric string, NaN / Infinity, or a
    list / dict."""
    if isinstance(value, int):          # bool included: int(True) == 1
        return int(value)
    if isinstance(value, float):
        return int(value) if math.isfinite(value) else default
    if isinstance(value, str):
        text = value.strip()
        try:
            return int(text)
        except ValueError:
            pass
        try:
            num = float(text)
        except ValueError:
            return default
        return int(num) if math.isfinite(num) else default
    return default


def _as_str(value) -> str:
    """A string field, or "" for anything else (a dict name must never
    reach the page as "{'x': 1}")."""
    return value if isinstance(value, str) else ""


def _as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _dicts(value) -> list:
    """The dict entries of a list field; a non-list field reads as []."""
    if not isinstance(value, (list, tuple)):
        return []
    return [v for v in value if isinstance(v, dict)]


def _pid(value):
    """A participant id as an int, or None when the value is not one.

    LCU and Match-V5 send ints; a numeric string ("1") or an integral float
    is accepted so a re-serialised payload still resolves. A bool, a list,
    a dict or a non-numeric string is None - never a dict key that raises."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isfinite(value) and value.is_integer():
            return int(value)
        return None
    if isinstance(value, str):
        text = value.strip()
        # 19 digits covers any int64 id; a longer run would also trip
        # Python's int-from-str digit limit (ValueError past 4300 digits).
        if text.isascii() and text.isdigit() and len(text) <= 19:
            return int(text)
    return None


def _is_team_id(value) -> bool:
    """A team id the timeline can bucket and sort on (int or str)."""
    return isinstance(value, str) or (
        isinstance(value, int) and not isinstance(value, bool))


def _team_sort_key(value):
    return (isinstance(value, str), value if isinstance(value, int) else 0,
            str(value))


def _enrich_from_lcu(lcu_detail: dict, tracked_puuid: str) -> dict:
    """Parse a full LCU /lol-match-history/v1/games/{gameId} payload into
    the shape the Post Game Review page renders.

    Locates the operator's participant via puuid -> participantId, then
    extracts: win/loss, full build (item0-item6), summoner spells,
    runes (keystone + tree paths + stat perks), damage breakdown,
    Arena augments, vision, and the full 10-player roster (KDA + items
    + champion + summoner names + is_me flag). Team-level objectives
    are surfaced alongside (dragons, baron, towers, first-blood/tower,
    bans).

    Returns an empty dict when the operator cannot be located - caller
    treats None / {} as "no enriched data yet, render placeholders". Never
    raises: a wrong-shaped entry is skipped and a wrong-shaped field reads
    as 0 / "" / [] (module docstring, trust boundary).
    """
    if not isinstance(lcu_detail, dict) or not isinstance(tracked_puuid, str):
        return {}
    tracked = tracked_puuid.strip()
    if not tracked:
        return {}

    identities = _dicts(lcu_detail.get("participantIdentities"))
    participants = _dicts(lcu_detail.get("participants"))
    if not identities or not participants:
        return {}

    # Resolve operator's participantId via puuid match + identity lookup.
    me_pid = None
    ident_by_pid: dict = {}
    for ident in identities:
        pid = _pid(ident.get("participantId"))
        if pid is None:
            continue
        player = _as_dict(ident.get("player"))
        ident_by_pid[pid] = player
        if me_pid is None and _as_str(player.get("puuid")).strip() == tracked:
            me_pid = pid
    if me_pid is None:
        return {}

    # Operator's participant + stats
    me_part: dict = {}
    for p in participants:
        if _pid(p.get("participantId")) == me_pid:
            me_part = p
            break
    if not me_part:
        return {}
    s = _as_dict(me_part.get("stats"))

    out: dict = {}
    out["champion_id"] = me_part.get("championId")
    out["team_id"]     = me_part.get("teamId")
    out["win"]         = bool(s.get("win"))
    out["champ_level"] = _as_int(s.get("champLevel"))
    out["spell1_id"]   = me_part.get("spell1Id")
    out["spell2_id"]   = me_part.get("spell2Id")
    out["items"]       = [_as_int(s.get(f"item{i}")) for i in range(7)]
    out["runes"] = {
        "keystone":       s.get("perk0"),
        "primary_style":  s.get("perkPrimaryStyle"),
        "sub_style":      s.get("perkSubStyle"),
        "primary":        [s.get(f"perk{i}") for i in range(4)],
        "secondary":      [s.get(f"perk{i}") for i in range(4, 6)],
    }
    out["damage"] = {
        "dealt_to_champs":     _as_int(s.get("totalDamageDealtToChampions")),
        "physical_to_champs":  _as_int(s.get("physicalDamageDealtToChampions")),
        "magic_to_champs":     _as_int(s.get("magicDamageDealtToChampions")),
        "true_to_champs":      _as_int(s.get("trueDamageDealtToChampions")),
        "taken":               _as_int(s.get("totalDamageTaken")),
        "self_mitigated":      _as_int(s.get("damageSelfMitigated")),
        "to_objectives":       _as_int(s.get("damageDealtToObjectives")),
        "to_turrets":          _as_int(s.get("damageDealtToTurrets")),
    }
    # s219 v6: healing + shielding contribution to teammates (self-heal
    # excluded - that's a stat about your own sustain, not team-care).
    out["support"] = {
        "total_heal":              _as_int(s.get("totalHeal")),
        "heal_on_teammates":       _as_int(s.get("totalHealsOnTeammates")),
        "shield_on_teammates":     _as_int(s.get("totalDamageShieldedOnTeammates")),
        "heal_plus_shield":        _as_int(s.get("totalHealsOnTeammates"))
                                    + _as_int(s.get("totalDamageShieldedOnTeammates")),
        "units_healed":            _as_int(s.get("totalUnitsHealed")),
    }
    out["arena_augments"] = [_as_int(s.get(f"playerAugment{i}"))
                              for i in range(1, 7)]
    out["vision"] = {
        "score":          _as_int(s.get("visionScore")),
        "wards_placed":   _as_int(s.get("wardsPlaced")),
        "wards_killed":   _as_int(s.get("wardsKilled")),
        "control_wards":  _as_int(s.get("visionWardsBoughtInGame")),
    }

    # Full 10-player roster
    roster: list = []
    for p in participants:
        s2 = _as_dict(p.get("stats"))
        pid = _pid(p.get("participantId"))
        player = ident_by_pid.get(pid, {}) if pid is not None else {}
        roster.append({
            "participant_id":    pid,
            "team_id":           p.get("teamId"),
            "champion_id":       p.get("championId"),
            "game_name":         (_as_str(player.get("gameName"))
                                  or _as_str(player.get("summonerName"))),
            "tag_line":          _as_str(player.get("tagLine")),
            "is_me":             pid is not None and pid == me_pid,
            "kills":             _as_int(s2.get("kills")),
            "deaths":            _as_int(s2.get("deaths")),
            "assists":           _as_int(s2.get("assists")),
            "cs":                _as_int(s2.get("totalMinionsKilled"))
                                  + _as_int(s2.get("neutralMinionsKilled")),
            "gold":              _as_int(s2.get("goldEarned")),
            "damage_to_champs":  _as_int(s2.get("totalDamageDealtToChampions")),
            "damage_taken":      _as_int(s2.get("totalDamageTaken")),
            "vision_score":      _as_int(s2.get("visionScore")),
            "champ_level":       _as_int(s2.get("champLevel")),
            "items":             [_as_int(s2.get(f"item{i}")) for i in range(7)],
            "summoner1":         p.get("spell1Id"),
            "summoner2":         p.get("spell2Id"),
            # s219 v7: per-player augments for ARAM Mayhem (KIWI) +
            # Arena (CHERRY). Empty list when the LCU fields aren't
            # populated (typical SR / non-augment modes return 0s).
            "augments":          [_as_int(s2.get(f"playerAugment{i}"))
                                   for i in range(1, 7)],
            "win":               bool(s2.get("win")),
        })
    out["roster"] = roster

    # Team-level objectives
    teams_out: list = []
    for t in _dicts(lcu_detail.get("teams")):
        bans = t.get("bans")
        teams_out.append({
            "team_id":           t.get("teamId"),
            "win":               (_as_str(t.get("win")).lower() == "win"),
            "first_blood":       bool(t.get("firstBlood")),
            "first_tower":       bool(t.get("firstTower")),
            "first_baron":       bool(t.get("firstBaron")),
            "first_dragon":      bool(t.get("firstDargon")),  # sic: LCU typo
            "first_inhibitor":   bool(t.get("firstInhibitor")),
            "baron_kills":       _as_int(t.get("baronKills")),
            "dragon_kills":      _as_int(t.get("dragonKills")),
            "tower_kills":       _as_int(t.get("towerKills")),
            "inhibitor_kills":   _as_int(t.get("inhibitorKills")),
            "rift_herald_kills": _as_int(t.get("riftHeraldKills")),
            "horde_kills":       _as_int(t.get("hordeKills")),
            "bans":              (list(bans) if isinstance(bans, (list, tuple))
                                  else []),
        })
    out["teams"] = teams_out

    # Top-level match metadata
    out["game_id"]            = lcu_detail.get("gameId")
    out["game_mode"]          = lcu_detail.get("gameMode")
    out["queue_id"]           = lcu_detail.get("queueId")
    out["map_id"]             = lcu_detail.get("mapId")
    out["game_duration_s"]    = _as_int(lcu_detail.get("gameDuration"))
    out["game_creation_ts"]   = lcu_detail.get("gameCreation")
    out["game_creation_date"] = lcu_detail.get("gameCreationDate")
    out["game_version"]       = lcu_detail.get("gameVersion")
    out["end_of_game_result"] = lcu_detail.get("endOfGameResult")
    # s220 surrender tag: LCU stamps these on every participant's stats
    # (game-wide value). Surfacing-only - lets the hero badge an FF'd
    # loss vs a played-out one, and flag an early-surrender remake.
    # Pre-s220 ingested rows lack the keys -> bool(None) -> False.
    out["ended_in_surrender"]       = bool(s.get("gameEndedInSurrender"))
    out["ended_in_early_surrender"] = bool(s.get("gameEndedInEarlySurrender"))

    return out


def _enrich_match_timeline(timeline: dict, lcu_detail: dict,
                           my_team_id) -> dict:
    """Parse a Riot Match-V5 timeline payload (.../matches/{id}/timeline)
    into the per-minute differential series + objective-event ribbon the
    Post Game Review "Timeline" tab renders (s220 Item E, phase 1).

    Match-V5 nests the per-minute frames under ``info``; a flat top-level
    ``frames`` list is also accepted (defensive). Participant->team comes
    from the stashed LCU match detail - Match-V5 timelines only map
    participantId->puuid, not teamId.

    All diffs are ally_total - enemy_total, so a positive value means the
    operator's team was ahead. Per-frame participant `position` data is
    deliberately NOT parsed here - that's the phase-2 interactive replay
    minimap, which reads the same Match-V5 timeline.

    Output shape:
      {
        "frame_interval_ms": 60000,
        "duration_s": 1930,
        "minutes": [0, 1, 2, ...],            # one x value per frame
        "series": {"gold": [...], "xp": [...], "cs": [...]},
        "final":  {"gold": int, "xp": int, "cs": int},
        "events": [{"t_s", "clock", "kind", "team", "label"}, ...],
      }
    Returns {} on any structural problem (Arena / round-based modes carry
    no per-minute frames - the caller renders a placeholder). Never raises:
    a wrong-shaped frame or event is skipped and a wrong-shaped number reads
    as 0, so one bad element no longer drops the whole timeline."""
    if not isinstance(timeline, dict) or not isinstance(lcu_detail, dict):
        return {}
    info = timeline.get("info")
    src = info if (isinstance(info, dict) and info.get("frames")) else timeline
    frames = src.get("frames")
    if not isinstance(frames, list) or not frames:
        return {}

    # participantId -> teamId from the detail payload.
    pid_team: dict = {}
    for p in _dicts(lcu_detail.get("participants")):
        pid = _pid(p.get("participantId"))
        if pid is not None:
            pid_team[pid] = p.get("teamId")
    if not pid_team:
        return {}
    teams_seen = sorted({v for v in pid_team.values() if _is_team_id(v)},
                        key=_team_sort_key)
    my_tid = my_team_id if (_is_team_id(my_team_id)
                            and my_team_id in teams_seen) else (
        teams_seen[0] if teams_seen else 100)

    interval = _as_int(src.get("frameInterval"), 60000)
    if interval <= 0:
        interval = 60000

    minutes: list = []
    s_gold: list = []
    s_xp: list = []
    s_cs: list = []
    frame_snaps: list = []   # (ts_ms, {pid_str: {gold, cs}}) for the @N pick
    for idx, fr in enumerate(frames):
        if not isinstance(fr, dict):
            continue
        pf = _as_dict(fr.get("participantFrames"))
        ally = {"gold": 0, "xp": 0, "cs": 0}
        enemy = {"gold": 0, "xp": 0, "cs": 0}
        pid_snap: dict = {}
        for raw_pid, pdata in pf.items():
            if not isinstance(pdata, dict):
                continue
            pid = _pid(pdata.get("participantId")) or _pid(raw_pid)
            if pid is None:
                continue
            gold = _as_int(pdata.get("totalGold"))
            cs = (_as_int(pdata.get("minionsKilled"))
                  + _as_int(pdata.get("jungleMinionsKilled")))
            bucket = ally if pid_team.get(pid) == my_tid else enemy
            bucket["gold"] += gold
            bucket["xp"]   += _as_int(pdata.get("xp"))
            bucket["cs"]   += cs
            pid_snap[str(pid)] = {"gold": gold, "cs": cs}
        ts_ms = _as_int(fr.get("timestamp"), None)
        if ts_ms is None:
            ts_ms = idx * interval
        minutes.append(round(ts_ms / 60000.0))
        s_gold.append(ally["gold"] - enemy["gold"])
        s_xp.append(ally["xp"] - enemy["xp"])
        s_cs.append(ally["cs"] - enemy["cs"])
        frame_snaps.append((ts_ms, pid_snap))

    # Per-participant @N snapshot: the frame nearest the 10-minute mark
    # (sub-10-min games fall back to their last frame). by_pid carries the
    # gold + cs the lane-comparison panel pairs me-vs-opponent on.
    at_n: dict = {}
    if frame_snaps:
        target_ms = _AT_N_TARGET_MIN * 60000
        chosen_ts, chosen_snap = min(
            frame_snaps, key=lambda fs: abs((fs[0] or 0) - target_ms))
        at_n = {
            "target_minute": _AT_N_TARGET_MIN,
            "minute": round((chosen_ts or 0) / 60000.0),
            "by_pid": chosen_snap,
        }

    def _ev_team(ev: dict) -> str:
        killer = _pid(ev.get("killerId")) or 0
        if killer in pid_team:
            return "ally" if pid_team[killer] == my_tid else "enemy"
        ktid = ev.get("killerTeamId")
        if ktid in teams_seen:
            return "ally" if ktid == my_tid else "enemy"
        # BUILDING_KILL.teamId is the team that LOST the structure.
        lost = ev.get("teamId")
        if lost in teams_seen:
            return "enemy" if lost == my_tid else "ally"
        return "neutral"

    _MON = {
        "DRAGON":       ("dragon",  "Dragon"),
        "RIFTHERALD":   ("herald",  "Rift Herald"),
        "BARON_NASHOR": ("baron",   "Baron"),
        "HORDE":        ("grubs",   "Void Grubs"),
        "ATAKHAN":      ("atakhan", "Atakhan"),
    }
    events: list = []
    first_blood_taken = False
    for fr in frames:
        if not isinstance(fr, dict):
            continue
        evs = fr.get("events")
        for ev in (evs if isinstance(evs, list) else []):
            if not isinstance(ev, dict):
                continue
            et = _as_str(ev.get("type"))
            # A negative stamp would render "-1:59"; clamp to the start.
            t_s = max(0, _as_int(ev.get("timestamp")) // 1000)
            clock = f"{t_s // 60}:{t_s % 60:02d}"
            if et == "CHAMPION_KILL" and not first_blood_taken:
                first_blood_taken = True
                events.append({"t_s": t_s, "clock": clock,
                               "kind": "first_blood", "team": _ev_team(ev),
                               "label": "First Blood"})
            elif et == "ELITE_MONSTER_KILL":
                kind, lbl = _MON.get(_as_str(ev.get("monsterType")),
                                     ("objective", "Objective"))
                sub = _as_str(ev.get("monsterSubType"))
                if kind == "dragon" and sub:
                    pretty = sub.replace("_DRAGON", "").replace("_", " ").title()
                    if pretty:
                        lbl = f"{pretty} Dragon"
                events.append({"t_s": t_s, "clock": clock, "kind": kind,
                               "team": _ev_team(ev), "label": lbl})
            elif et == "BUILDING_KILL":
                bt = _as_str(ev.get("buildingType"))
                if bt == "TOWER_BUILDING":
                    events.append({"t_s": t_s, "clock": clock,
                                   "kind": "tower", "team": _ev_team(ev),
                                   "label": "Tower"})
                elif bt == "INHIBITOR_BUILDING":
                    events.append({"t_s": t_s, "clock": clock,
                                   "kind": "inhibitor", "team": _ev_team(ev),
                                   "label": "Inhibitor"})
    events.sort(key=lambda e: e["t_s"])
    # Bound payload - a stomp can rack up 20+ structures; 60 keeps the
    # ribbon readable and raw_data lean.
    if len(events) > 60:
        events = events[:60]

    dur = _as_int(lcu_detail.get("gameDuration"))
    if dur <= 0:
        last = next((f for f in reversed(frames) if isinstance(f, dict)), {})
        dur = max(0, _as_int(last.get("timestamp")) // 1000)

    return {
        "frame_interval_ms": interval,
        "duration_s": dur,
        "minutes": minutes,
        "series": {"gold": s_gold, "xp": s_xp, "cs": s_cs},
        "final": {
            "gold": s_gold[-1] if s_gold else 0,
            "xp":   s_xp[-1] if s_xp else 0,
            "cs":   s_cs[-1] if s_cs else 0,
        },
        "at_n": at_n,
        "events": events,
    }


def _fold_at_n_into_roster(enriched: dict) -> None:
    """Copy the timeline `at_n` per-participant snapshot onto each roster
    entry as gold_at_n / cs_at_n / at_n_minute, so the lane-comparison
    panel reads @N straight off the participant row (no re-walk of frames).

    No-op when the timeline or its at_n block is absent (event modes / no
    per-participant frames). Never raises - PGR must not break over it."""
    try:
        at_n = ((enriched.get("timeline") or {}).get("at_n")) or {}
        by_pid = at_n.get("by_pid") or {}
        if not by_pid:
            return
        minute = at_n.get("minute")
        for entry in (enriched.get("roster") or []):
            snap = by_pid.get(str(entry.get("participant_id")))
            if isinstance(snap, dict):
                entry["gold_at_n"] = snap.get("gold")
                entry["cs_at_n"] = snap.get("cs")
                entry["at_n_minute"] = minute
    except Exception:  # never break the page over the @N fold  # noqa: BLE001
        return


# Match-V5 routing cluster by platform id. Match-V5 (incl. /timeline)
# uses the regional cluster, not the platform cluster. Per Riot's developer
# portal routing table: AMERICAS serves NA / BR / LAN / LAS, ASIA serves KR /
# JP, EUROPE serves EUNE / EUW / ME1 / TR / RU, and SEA serves OCE and the
# SG2 / TW2 / VN2 shards (PH2 / TH2 merged into SG2 but their historical
# match ids keep their own prefix). OC1 used to sit under "americas" here,
# which sent every OCE timeline to a cluster that cannot serve it; RC's own
# SGP table (core/sgp_client.py) already puts OC1 on the apse1 shard. A
# platform NOT in this table (PBE1, a junk value) makes no Match-V5 call -
# the old "americas" default was a guaranteed-wrong call.
_MV5_REGION_BY_PLATFORM = {
    "NA1": "americas", "BR1": "americas", "LA1": "americas",
    "LA2": "americas",
    "EUW1": "europe", "EUN1": "europe", "TR1": "europe", "RU": "europe",
    "ME1": "europe",
    "KR": "asia", "JP1": "asia",
    "OC1": "sea", "SG2": "sea", "TW2": "sea", "VN2": "sea",
    "PH2": "sea", "TH2": "sea",
}


def _game_id(value):
    """The LCU gameId as a positive int, or None.

    Refuses a bool (``True`` used to build ``NA1_True``), a non-integral or
    non-finite float, a string that is not plain digits (``"12/34"``) and a
    list / dict, so only a real match id reaches Match-V5."""
    gid = _pid(value)
    return gid if gid is not None and gid > 0 else None


def _attach_match_timeline(enriched: dict, lcu_detail: dict) -> None:
    """Fetch the Riot Match-V5 timeline for this game and attach the
    parsed result to ``enriched["timeline"]`` (s220 Item E, phase 1).

    The LCU exposes no per-game timeline endpoint, so the authoritative
    source is Match-V5 (.../matches/{platform}_{gameId}/timeline) - exactly
    the consumer s148 anticipated. ``core.riot_api.get_match_timeline``
    is immutable-cached: one Riot call per match, then served from cache.

    Degrades silently - when the Riot key is missing/revoked (returns
    None) or anything raises, ``enriched["timeline"]`` is simply not set
    and the frontend shows its "Timeline pending" placeholder. This must
    never break /api/last-match."""
    try:
        if not isinstance(lcu_detail, dict):
            return
        platform = _as_str(lcu_detail.get("platformId")).strip().upper()
        region = _MV5_REGION_BY_PLATFORM.get(platform)
        game_id = _game_id(lcu_detail.get("gameId"))
        if region is None or game_id is None:
            return
        # S134 N3: Match-V5 serves League only - a TFT game would cost one
        # wasted call and a misleading 403 "revoked key" warning.
        from core.queue_modes import is_tft_context
        if is_tft_context(queue_id=lcu_detail.get("queueId"),
                          game_mode=lcu_detail.get("gameMode"),
                          map_id=lcu_detail.get("mapId")):
            return
        match_id = f"{platform}_{game_id}"
        from core import riot_api  # lazy - avoids import cost on cold paths
        timeline = riot_api.get_match_timeline(match_id, region=region)
        if not isinstance(timeline, dict):
            return
        parsed = _enrich_match_timeline(
            timeline, lcu_detail, enriched.get("team_id"))
        if parsed:
            enriched["timeline"] = parsed
            _fold_at_n_into_roster(enriched)
    except Exception as exc:  # never break the page over a timeline  # noqa: BLE001
        _log.warning("_attach_match_timeline: %s", exc)
