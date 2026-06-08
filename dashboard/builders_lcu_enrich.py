"""LCU / Match-V5 enrichment builders for the Post Game Review page.

Payload-boundary slice of the former monolithic `dashboard.builders`
(AUTONOMOUS_AUDIT spec 4.C, 2026-05-18). Holds the three functions that
parse external/untrusted Riot payloads: `_enrich_from_lcu`,
`_enrich_match_timeline`, `_attach_match_timeline`.

`dashboard.builders` re-exports these names so existing call sites keep
working without churn. Function bodies are extracted byte-verbatim -
behavior is pinned by tests/test_builders_enrich.py +
tests/test_last_match_timeline.py + tests/test_last_match_surrender.py.
"""
from dashboard._context import log as _log

# PGR S5 lane-comparison @N: the minute the per-participant gold/cs snapshot
# targets (aggregator G "gold@10 / cs@10"). The frame nearest this mark is used;
# a sub-10-minute game falls back to its last frame.
_AT_N_TARGET_MIN = 10


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

    Returns an empty dict on any structural mismatch - caller treats
    None / {} as "no enriched data yet, render placeholders".
    """
    if not isinstance(lcu_detail, dict) or not tracked_puuid:
        return {}

    identities = lcu_detail.get("participantIdentities") or []
    participants = lcu_detail.get("participants") or []
    if not identities or not participants:
        return {}

    # Resolve operator's participantId via puuid match
    me_pid = None
    for ident in identities:
        player = ident.get("player") or {}
        if str(player.get("puuid") or "").strip() == tracked_puuid:
            me_pid = ident.get("participantId")
            break
    if me_pid is None:
        return {}

    # Build identity lookup
    ident_by_pid: dict = {}
    for ident in identities:
        pid = ident.get("participantId")
        if pid is not None:
            ident_by_pid[pid] = ident.get("player") or {}

    # Operator's participant + stats
    me_part: dict = {}
    for p in participants:
        if p.get("participantId") == me_pid:
            me_part = p
            break
    if not me_part:
        return {}
    s = me_part.get("stats") or {}

    out: dict = {}
    out["champion_id"] = me_part.get("championId")
    out["team_id"]     = me_part.get("teamId")
    out["win"]         = bool(s.get("win"))
    out["champ_level"] = int(s.get("champLevel") or 0)
    out["spell1_id"]   = me_part.get("spell1Id")
    out["spell2_id"]   = me_part.get("spell2Id")
    out["items"]       = [int(s.get(f"item{i}") or 0) for i in range(7)]
    out["runes"] = {
        "keystone":       s.get("perk0"),
        "primary_style":  s.get("perkPrimaryStyle"),
        "sub_style":      s.get("perkSubStyle"),
        "primary":        [s.get(f"perk{i}") for i in range(4)],
        "secondary":      [s.get(f"perk{i}") for i in range(4, 6)],
    }
    out["damage"] = {
        "dealt_to_champs":     int(s.get("totalDamageDealtToChampions") or 0),
        "physical_to_champs":  int(s.get("physicalDamageDealtToChampions") or 0),
        "magic_to_champs":     int(s.get("magicDamageDealtToChampions") or 0),
        "true_to_champs":      int(s.get("trueDamageDealtToChampions") or 0),
        "taken":               int(s.get("totalDamageTaken") or 0),
        "self_mitigated":      int(s.get("damageSelfMitigated") or 0),
        "to_objectives":       int(s.get("damageDealtToObjectives") or 0),
        "to_turrets":          int(s.get("damageDealtToTurrets") or 0),
    }
    # s219 v6: healing + shielding contribution to teammates (self-heal
    # excluded - that's a stat about your own sustain, not team-care).
    out["support"] = {
        "total_heal":              int(s.get("totalHeal") or 0),
        "heal_on_teammates":       int(s.get("totalHealsOnTeammates") or 0),
        "shield_on_teammates":     int(s.get("totalDamageShieldedOnTeammates") or 0),
        "heal_plus_shield":        int(s.get("totalHealsOnTeammates") or 0)
                                    + int(s.get("totalDamageShieldedOnTeammates") or 0),
        "units_healed":            int(s.get("totalUnitsHealed") or 0),
    }
    out["arena_augments"] = [int(s.get(f"playerAugment{i}") or 0)
                              for i in range(1, 7)]
    out["vision"] = {
        "score":          int(s.get("visionScore") or 0),
        "wards_placed":   int(s.get("wardsPlaced") or 0),
        "wards_killed":   int(s.get("wardsKilled") or 0),
        "control_wards":  int(s.get("visionWardsBoughtInGame") or 0),
    }

    # Full 10-player roster
    roster: list = []
    for p in participants:
        s2 = p.get("stats") or {}
        pid = p.get("participantId")
        player = ident_by_pid.get(pid, {})
        roster.append({
            "participant_id":    pid,
            "team_id":           p.get("teamId"),
            "champion_id":       p.get("championId"),
            "game_name":         player.get("gameName") or player.get("summonerName") or "",
            "tag_line":          player.get("tagLine") or "",
            "is_me":             pid == me_pid,
            "kills":             int(s2.get("kills") or 0),
            "deaths":            int(s2.get("deaths") or 0),
            "assists":           int(s2.get("assists") or 0),
            "cs":                int(s2.get("totalMinionsKilled") or 0)
                                  + int(s2.get("neutralMinionsKilled") or 0),
            "gold":              int(s2.get("goldEarned") or 0),
            "damage_to_champs":  int(s2.get("totalDamageDealtToChampions") or 0),
            "damage_taken":      int(s2.get("totalDamageTaken") or 0),
            "vision_score":      int(s2.get("visionScore") or 0),
            "champ_level":       int(s2.get("champLevel") or 0),
            "items":             [int(s2.get(f"item{i}") or 0) for i in range(7)],
            "summoner1":         p.get("spell1Id"),
            "summoner2":         p.get("spell2Id"),
            # s219 v7: per-player augments for ARAM Mayhem (KIWI) +
            # Arena (CHERRY). Empty list when the LCU fields aren't
            # populated (typical SR / non-augment modes return 0s).
            "augments":          [int(s2.get(f"playerAugment{i}") or 0)
                                   for i in range(1, 7)],
            "win":               bool(s2.get("win")),
        })
    out["roster"] = roster

    # Team-level objectives
    teams_out: list = []
    for t in (lcu_detail.get("teams") or []):
        teams_out.append({
            "team_id":           t.get("teamId"),
            "win":               (str(t.get("win") or "").lower() == "win"),
            "first_blood":       bool(t.get("firstBlood")),
            "first_tower":       bool(t.get("firstTower")),
            "first_baron":       bool(t.get("firstBaron")),
            "first_dragon":      bool(t.get("firstDargon")),  # sic: LCU typo
            "first_inhibitor":   bool(t.get("firstInhibitor")),
            "baron_kills":       int(t.get("baronKills") or 0),
            "dragon_kills":      int(t.get("dragonKills") or 0),
            "tower_kills":       int(t.get("towerKills") or 0),
            "inhibitor_kills":   int(t.get("inhibitorKills") or 0),
            "rift_herald_kills": int(t.get("riftHeraldKills") or 0),
            "horde_kills":       int(t.get("hordeKills") or 0),
            "bans":              list(t.get("bans") or []),
        })
    out["teams"] = teams_out

    # Top-level match metadata
    out["game_id"]            = lcu_detail.get("gameId")
    out["game_mode"]          = lcu_detail.get("gameMode")
    out["queue_id"]           = lcu_detail.get("queueId")
    out["map_id"]             = lcu_detail.get("mapId")
    out["game_duration_s"]    = int(lcu_detail.get("gameDuration") or 0)
    out["game_creation_ts"]   = lcu_detail.get("gameCreation")
    out["game_creation_date"] = lcu_detail.get("gameCreationDate")
    out["game_version"]       = lcu_detail.get("gameVersion")
    out["end_of_game_result"] = lcu_detail.get("endOfGameResult")
    # s220 surrender tag: LCU stamps these on every participant's stats
    # (game-wide value). Surfacing-only - lets the hero badge an FF'd
    # loss vs a played-out one, and flag an early-surrender remake.
    # Pre-s220 ingested rows lack the keys → bool(None) → False.
    out["ended_in_surrender"]       = bool(s.get("gameEndedInSurrender"))
    out["ended_in_early_surrender"] = bool(s.get("gameEndedInEarlySurrender"))

    return out


def _enrich_match_timeline(timeline: dict, lcu_detail: dict,
                           my_team_id) -> dict:
    """Parse a Riot Match-V5 timeline payload (.../matches/{id}/timeline)
    into the per-minute differential series + objective-event ribbon the
    Post Game Review "Timeline" tab renders (s220 Item E, phase 1).

    Match-V5 nests the per-minute frames under ``info``; a flat top-level
    ``frames`` list is also accepted (defensive). Participant→team comes
    from the stashed LCU match detail - Match-V5 timelines only map
    participantId→puuid, not teamId.

    All diffs are ally_total − enemy_total, so a positive value means the
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
    no per-minute frames - the caller renders a placeholder)."""
    if not isinstance(timeline, dict):
        return {}
    info = timeline.get("info")
    src = info if (isinstance(info, dict) and info.get("frames")) else timeline
    frames = src.get("frames")
    if not isinstance(frames, list) or not frames:
        return {}

    # participantId -> teamId from the detail payload.
    pid_team: dict = {}
    for p in (lcu_detail.get("participants") or []):
        pid = p.get("participantId")
        if pid is not None:
            try:
                pid_team[int(pid)] = p.get("teamId")
            except (TypeError, ValueError):
                continue
    if not pid_team:
        return {}
    teams_seen = sorted({v for v in pid_team.values() if v is not None})
    my_tid = my_team_id if my_team_id in teams_seen else (
        teams_seen[0] if teams_seen else 100)

    interval = int(src.get("frameInterval") or 60000)

    minutes: list = []
    s_gold: list = []
    s_xp: list = []
    s_cs: list = []
    frame_snaps: list = []   # (ts_ms, {pid_str: {gold, cs}}) for the @N pick
    for idx, fr in enumerate(frames):
        pf = fr.get("participantFrames") or {}
        ally = {"gold": 0, "xp": 0, "cs": 0}
        enemy = {"gold": 0, "xp": 0, "cs": 0}
        pid_snap: dict = {}
        for raw_pid, pdata in pf.items():
            if not isinstance(pdata, dict):
                continue
            try:
                pid = int(pdata.get("participantId") or raw_pid)
            except (TypeError, ValueError):
                continue
            gold = int(pdata.get("totalGold") or 0)
            cs = (int(pdata.get("minionsKilled") or 0)
                  + int(pdata.get("jungleMinionsKilled") or 0))
            bucket = ally if pid_team.get(pid) == my_tid else enemy
            bucket["gold"] += gold
            bucket["xp"]   += int(pdata.get("xp") or 0)
            bucket["cs"]   += cs
            pid_snap[str(pid)] = {"gold": gold, "cs": cs}
        ts_ms = fr.get("timestamp")
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
        try:
            killer = int(ev.get("killerId") or 0)
        except (TypeError, ValueError):
            killer = 0
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
        for ev in (fr.get("events") or []):
            if not isinstance(ev, dict):
                continue
            et = ev.get("type") or ""
            t_s = int(ev.get("timestamp") or 0) // 1000
            clock = f"{t_s // 60}:{t_s % 60:02d}"
            if et == "CHAMPION_KILL" and not first_blood_taken:
                first_blood_taken = True
                events.append({"t_s": t_s, "clock": clock,
                               "kind": "first_blood", "team": _ev_team(ev),
                               "label": "First Blood"})
            elif et == "ELITE_MONSTER_KILL":
                kind, lbl = _MON.get(ev.get("monsterType") or "",
                                     ("objective", "Objective"))
                sub = ev.get("monsterSubType") or ""
                if kind == "dragon" and sub:
                    pretty = sub.replace("_DRAGON", "").replace("_", " ").title()
                    if pretty:
                        lbl = f"{pretty} Dragon"
                events.append({"t_s": t_s, "clock": clock, "kind": kind,
                               "team": _ev_team(ev), "label": lbl})
            elif et == "BUILDING_KILL":
                bt = ev.get("buildingType") or ""
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

    dur = int(lcu_detail.get("gameDuration") or 0)
    if dur <= 0 and frames:
        last_ts = frames[-1].get("timestamp") or 0
        dur = int(last_ts / 1000)

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
    except Exception:  # never break the page over the @N fold
        return


# Match-V5 routing cluster by platform id. Match-V5 (incl. /timeline)
# uses the regional cluster, not the platform cluster. Default americas.
_MV5_REGION_BY_PLATFORM = {
    "NA1": "americas", "BR1": "americas", "LA1": "americas",
    "LA2": "americas", "OC1": "americas",
    "EUW1": "europe", "EUN1": "europe", "TR1": "europe", "RU": "europe",
    "KR": "asia", "JP1": "asia",
}


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
        platform = str(lcu_detail.get("platformId") or "").upper()
        game_id = lcu_detail.get("gameId")
        if not platform or not game_id:
            return
        match_id = f"{platform}_{game_id}"
        region = _MV5_REGION_BY_PLATFORM.get(platform, "americas")
        from core import riot_api  # lazy - avoids import cost on cold paths
        timeline = riot_api.get_match_timeline(match_id, region=region)
        if not isinstance(timeline, dict):
            return
        parsed = _enrich_match_timeline(
            timeline, lcu_detail, enriched.get("team_id"))
        if parsed:
            enriched["timeline"] = parsed
            _fold_at_n_into_roster(enriched)
    except Exception as exc:  # never break the page over a timeline
        _log.warning("_attach_match_timeline: %s", exc)
