"""Post Game Review "last match" builders.

Payload-boundary slice of the former monolithic `dashboard.builders`
(AUTONOMOUS_AUDIT spec 4.C, 2026-05-18). Holds the last-match cluster:
`_compute_wrong_team_from_enriched`, `_compute_quick_review`,
`_build_last_match`.

`dashboard.builders` re-exports these names so existing call sites keep
working without churn. Function bodies are extracted byte-verbatim -
behavior is pinned by the last-match / quick-review tests.
"""
import sqlite3

from dashboard._context import (
    APP_DIR as _APP_DIR,
    DB_CONN_LOCAL as _DB_CONN_LOCAL,
    log as _log,
    ro_conn as _ro_conn,
)
from dashboard.builders_lcu_enrich import (
    _attach_match_timeline,
    _enrich_from_lcu,
)
from core import carry_benchmarks as _carry_benchmarks
from core.carry_share import dmg_share_pct, gold_share_pct

# match_history.db mode strings -> the Match-V5 game_mode keys the carry
# benchmark corpus (rewind_history.db) groups on. Used only when the row
# has no LCU enrichment (enriched.game_mode is preferred).
_MODE_TO_BENCH = {"SR": "CLASSIC", "ARAM": "ARAM", "ARENA": "CHERRY"}


def _bench_role(enriched, lcu_detail) -> str | None:
    """SR benchmark role (team_position vocabulary) for the operator.

    Only CLASSIC games have lane roles; every other mode benchmarks on the
    mode-wide group. The LCU participant's timeline.lane/timeline.role pair
    maps onto Match-V5 team_position: BOTTOM splits into BOTTOM (carry) vs
    UTILITY (support); TOP/JUNGLE/MIDDLE pass through."""
    if not enriched or enriched.get("game_mode") != "CLASSIC":
        return None
    me = next((r for r in (enriched.get("roster") or []) if r.get("is_me")),
              None)
    if me is None:
        return None
    pid = me.get("participant_id")
    part = next((p for p in ((lcu_detail or {}).get("participants") or [])
                 if p.get("participantId") == pid), None)
    if part is None:
        return None
    tl = part.get("timeline") or {}
    lane = str(tl.get("lane") or "").upper()
    role = str(tl.get("role") or "").upper()
    if lane == "BOTTOM":
        return "UTILITY" if role in ("SUPPORT", "DUO_SUPPORT") else "BOTTOM"
    if lane in ("TOP", "JUNGLE", "MIDDLE"):
        return lane
    return None


def _carry_normalized(match_row: dict, enriched, lcu_detail) -> dict:
    """OQ12 normalized carry-metrics block for the PGR payload.

    FROZEN CONTRACT (frontend slice codes to this verbatim):
      {"bench_key": "BOTTOM|mid" | None,
       "kp_pct":         {value, p25, p50, p75, n, band},
       "gold_share_pct": {...}, "dmg_share_pct": {...}}
    band: low iff value < p25; high iff value > p75; else avg; null when
    the value is null. No benchmark resolved -> bench_key null + all
    p/n/band null but values still populated when computable. Fail-soft:
    any exception degrades to the all-null block - PGR must never break."""
    values = {
        "kp_pct":         match_row.get("kp_pct"),
        "gold_share_pct": match_row.get("gold_share_pct"),
        "dmg_share_pct":  match_row.get("dmg_share_pct"),
    }

    def _null_metric(v):
        return {"value": v, "p25": None, "p50": None, "p75": None,
                "n": None, "band": None}

    try:
        mode = (enriched.get("game_mode") if enriched
                else _MODE_TO_BENCH.get(match_row.get("mode")))
        role = _bench_role(enriched, lcu_detail)
        bench_key, metrics = _carry_benchmarks.resolve(
            role, mode, int(match_row.get("duration_s") or 0))
        out: dict = {"bench_key": bench_key}
        for metric, v in values.items():
            bench = (metrics or {}).get(metric) or {}
            if bench_key is None or not bench:
                out[metric] = _null_metric(v)
            else:
                out[metric] = {
                    "value": v,
                    "p25":   bench.get("p25"),
                    "p50":   bench.get("p50"),
                    "p75":   bench.get("p75"),
                    "n":     bench.get("n"),
                    "band":  _carry_benchmarks.band(v, bench),
                }
        return out
    except Exception as exc:  # noqa: BLE001 - degrade, never break the page
        _log.warning("_carry_normalized: %s", exc)
        return {"bench_key": None,
                **{m: _null_metric(v) for m, v in values.items()}}


def _compute_wrong_team_from_enriched(enriched: dict, op_k: int, op_d: int, op_a: int) -> list[dict]:
    """Team-level "what went wrong" signals derived from LCU enrichment.

    enriched.teams provides:  win, first_blood, first_tower, first_baron,
      first_dragon, first_inhibitor, baron_kills, dragon_kills, tower_kills,
      inhibitor_kills, rift_herald_kills, horde_kills, bans.

    Heuristics per mode bucket:
      - SR (queueId 400/420/430/440):
          objective-control + soul + baron + tower diff
      - ARAM / Mayhem (queueId 450 / 2400 / KIWI mode):
          tower diff + KDA disparity (only rift to push on)
      - Arena (queueId 1750 live, 1700/1710 legacy / CHERRY mode):
          deferred - 4 subteam paradigm doesn't fit win/loss heuristics
      - Other: degrade gracefully to operator-side death/KDA proxies.

    Each emitted item is {text, why} - `why` backs the tooltip on hover.
    """
    out: list[dict] = []

    teams = enriched.get("teams") or []
    if len(teams) < 2:
        return out
    my_tid = enriched.get("team_id")
    me = next((t for t in teams if t.get("team_id") == my_tid), None)
    opp = next((t for t in teams if t.get("team_id") != my_tid), None)
    if not me or not opp:
        return out

    queue_id  = enriched.get("queue_id") or 0
    game_mode = (enriched.get("game_mode") or "").upper()
    is_arena   = queue_id in (1700, 1710, 1750) or game_mode == "CHERRY"
    is_aram    = (queue_id == 450 or queue_id == 2400
                  or game_mode in ("ARAM", "KIWI"))
    is_sr      = (queue_id in (400, 420, 430, 440)
                  or (game_mode == "CLASSIC" and not is_aram))

    if is_arena:
        # Arena's 4-team structure doesn't fit a single ally/enemy frame
        # cleanly. Skip team-level heuristics; the chronic + right
        # sections still fire on operator-side stats.
        return out

    # -- First-objective losses (works in SR + ARAM) --------------------
    if opp.get("first_blood") and not me.get("first_blood"):
        out.append({
            "text": "Lost first blood",
            "why":  ("Enemy team took first blood - early gold + tempo "
                     "advantage. Worth reviewing the lane / fight that opened "
                     "the match in the deep Review page."),
        })
    if opp.get("first_tower") and not me.get("first_tower"):
        out.append({
            "text": "Lost first tower",
            "why":  ("Enemy team took the first tower (250g globally + "
                     "platings + first-tower trinket bounty). Indicates "
                     "early lane pressure was conceded - common cause: "
                     "death timer + freeze break."),
        })

    # -- Tower differential (SR only - ARAM has its own framing below) -
    my_towers  = int(me.get("tower_kills") or 0)
    opp_towers = int(opp.get("tower_kills") or 0)
    if is_sr and opp_towers - my_towers >= 4:
        out.append({
            "text": f"Tower diff -{opp_towers - my_towers} (lost {opp_towers}-{my_towers})",
            "why":  (f"Enemy took {opp_towers} towers to your {my_towers} - "
                     f"map pressure was lopsided. Each tower is ~430g + "
                     f"vision real estate. Re-watching mid-game roams in "
                     f"the deep Review page would surface where the trades "
                     f"went sideways."),
        })

    if is_sr:
        # -- Dragon control + soul -------------------------------------
        my_drag  = int(me.get("dragon_kills") or 0)
        opp_drag = int(opp.get("dragon_kills") or 0)
        if opp_drag >= 4 and not me.get("win"):
            out.append({
                "text": f"Enemy got soul ({opp_drag} drakes)",
                "why":  (f"4+ dragons = Dragon Soul, a permanent team-wide "
                         f"power-spike. You finished with {my_drag}; review "
                         f"early drake setups + vision in the deep Review."),
            })
        elif opp_drag - my_drag >= 2:
            out.append({
                "text": f"Dragon control lost ({my_drag}-{opp_drag})",
                "why":  (f"Enemy took {opp_drag} dragons to your {my_drag}. "
                         f"Each dragon stack is a teamwide bonus - review "
                         f"who was contesting + your top-side trades that "
                         f"enabled the call."),
            })

        # -- Baron giveaway --------------------------------------------
        my_baron  = int(me.get("baron_kills") or 0)
        opp_baron = int(opp.get("baron_kills") or 0)
        if opp_baron > 0 and my_baron == 0:
            out.append({
                "text": f"Gave up Baron(s) x{opp_baron}",
                "why":  (f"Enemy took {opp_baron} Baron Nashor with zero "
                         f"answer from your team. Baron buff fuels minion "
                         f"empowerment + sieges; review vision setup before "
                         f"the pit fight in the deep Review."),
            })

        # -- Rift Herald -----------------------------------------------
        my_herald  = int(me.get("rift_herald_kills") or 0)
        opp_herald = int(opp.get("rift_herald_kills") or 0)
        if opp_herald > 0 and my_herald == 0:
            out.append({
                "text": "Gave up Rift Herald",
                "why":  ("Enemy took Herald with no answer. Each Herald is "
                         "~5 plates of pressure on whichever lane it gets "
                         "dumped in - review jungle / mid pathing 8-14min."),
            })

    elif is_aram:
        # ARAM Mayhem (KIWI) and ARAM Classic - tower-diff is the
        # main team-level signal; dragons/baron don't exist.
        if opp_towers > 0 and my_towers == 0:
            out.append({
                "text": f"Lost every tower trade ({opp_towers}-0)",
                "why":  (f"Enemy team broke {opp_towers} of your towers "
                         f"without taking one back - pure attrition loss. "
                         f"Common in ARAM when comp lacks AOE waveclear "
                         f"vs siege champions."),
            })

    # -- Roster aggregates (works in any 5v5 mode) ---------------------
    roster = enriched.get("roster") or []
    if roster:
        my_side  = [r for r in roster if r.get("team_id") == my_tid]
        opp_side = [r for r in roster if r.get("team_id") != my_tid]
        if my_side and opp_side:
            my_k  = sum(int(r.get("kills") or 0)  for r in my_side)
            my_d  = sum(int(r.get("deaths") or 0) for r in my_side)
            opp_k = sum(int(r.get("kills") or 0)  for r in opp_side)
            opp_d = sum(int(r.get("deaths") or 0) for r in opp_side)
            if opp_k >= my_k * 1.5 and opp_k - my_k >= 10:
                out.append({
                    "text": f"Team kill deficit ({my_k}-{opp_k})",
                    "why":  (f"Enemy outscored your team {opp_k} kills to "
                             f"{my_k} (1.5x+ ratio with a 10+ gap). Each "
                             f"team-fight you took was net-losing - review "
                             f"engage timings + comp synergy."),
                })
            my_gold  = sum(int(r.get("gold") or 0) for r in my_side)
            opp_gold = sum(int(r.get("gold") or 0) for r in opp_side)
            if opp_gold - my_gold >= 8000:
                out.append({
                    "text": f"Gold deficit -{(opp_gold - my_gold)//1000}k",
                    "why":  (f"Enemy ended {opp_gold - my_gold}g ahead "
                             f"({(opp_gold/1000):.1f}k vs {(my_gold/1000):.1f}k). "
                             f"That's roughly an extra completed mythic + "
                             f"finisher across the team - review mid-game "
                             f"objective trades."),
                })

    # -- Operator-side proxies (always fire if applicable) -------------
    if op_d >= 10:
        out.append({
            "text": f"Death count cost the team ({op_d} deaths)",
            "why":  (f"{op_d} deaths is a 10+ threshold. Even with the "
                     f"objectives + team aggregates above, each personal "
                     f"death is gold + 30+s map pressure handed back."),
        })

    if not out:
        out.append({
            "text": "No team-level red flags this match",
            "why":  ("LCU enrichment surfaced team data but nothing tripped "
                     "the heuristics (no early-objective loss, tower diff "
                     "<4, no soul/baron giveaway, no major gold/kill gap)."),
        })

    return out


def _compute_quick_review(current: dict, history: list[dict]) -> dict:
    """Compute the 3-section Quick Review for the Last Match page.

    `current` is the just-finished match row (parsed). `history` is the
    operator's most recent N non-TFT matches EXCLUDING `current`, used as
    the baseline for "chronic fail" assessment.

    Returns:
      {
        "right":      [{text, why}, ...],   # positive callouts about this match
        "wrong_team": [{text, why}, ...],   # team-level issues this match
        "my_chronic": [{text, why}, ...],   # repeated patterns across history
      }

    v1 heuristics - operator-revisable. The `why` field is shown in a
    tooltip on hover so the analysis stays explainable. Team data is not
    in match_history.db today (only operator-centric stats); the
    wrong_team section degrades gracefully until the Riot Match-V5
    enrich flow ships.
    """
    right: list[dict] = []
    wrong_team: list[dict] = []
    my_chronic: list[dict] = []

    def _kda(k: int, d: int, a: int) -> float:
        return round((k + a) / max(d, 1), 2)

    k = int(current.get("kills") or 0)
    d = int(current.get("deaths") or 0)
    a = int(current.get("assists") or 0)
    cspm = float(current.get("cs_per_min") or 0.0)
    grade = (current.get("grade") or "").upper().strip()
    kp = current.get("kp_pct")

    cur_kda = _kda(k, d, a)

    # -- right: this-match positives -------------------------------------
    if grade in ("S", "A"):
        right.append({
            "text": f"Top-tier performance ({grade})",
            "why": f"Match graded {grade} - operator scored in the top tier on "
                   f"the per-mode rubric used by the Home page Recent 5.",
        })
    if cur_kda >= 3.0:
        right.append({
            "text": f"Excellent KDA ({cur_kda})",
            "why": f"{k}/{d}/{a} = (K+A)/D = {cur_kda}, well above the 3.0 "
                   f"threshold used as the strong-performance gate.",
        })
    if cspm >= 8.0 and current.get("mode") == "SR":
        right.append({
            "text": f"Solid farm ({cspm:.1f} CS/min)",
            "why": f"{int(current.get('cs') or 0)} CS at {cspm:.1f}/min - at "
                   f"or above the 8.0 CS/min standard for SR.",
        })
    if isinstance(kp, (int, float)) and kp >= 70:
        right.append({
            "text": f"High team-fight participation ({int(kp)}% KP)",
            "why": f"You took part in {int(kp)}% of team kills - strong "
                   f"presence in skirmishes / objective fights.",
        })
    if k >= 10 and d <= 5:
        right.append({
            "text": f"Carry-tier kill output ({k} kills, {d} deaths)",
            "why": "10+ kills with <=5 deaths is a snowball signal - you "
                   "converted leads without giving them back.",
        })

    if not right:
        right.append({
            "text": "No standout positives this match",
            "why": "None of the v1 thresholds tripped (S/A grade, KDA>=3, "
                   "CS/min>=8, KP>=70%, or 10+ kills with <=5 deaths).",
        })

    # -- wrong_team: team-level issues this match ------------------------
    # If LCU enrichment is present, surface real team-level signals
    # (objectives lost, comp asymmetry, gold deficit). Falls back to
    # operator-side proxies (death spike + sub-1 KDA) when enrichment
    # is missing (e.g. agent hasn't pushed yet, or pre-s219 row).
    enriched = current.get("enriched") if isinstance(current, dict) else None
    if isinstance(enriched, dict) and enriched.get("teams"):
        wrong_team.extend(_compute_wrong_team_from_enriched(enriched, k, d, a))
    else:
        wrong_team.append({
            "text": "Team data unavailable",
            "why": "LCU match detail not ingested yet. The Legion LCU "
                   "agent auto-POSTs on EndOfGame; this section unlocks "
                   "team objectives + roster signals once that lands.",
        })
        if d >= 10:
            wrong_team.append({
                "text": f"Death count cost the team ({d} deaths)",
                "why": f"{d} deaths is a 10+ threshold - even with high KP "
                       f"({int(kp) if isinstance(kp,(int,float)) else '?'}%), "
                       f"each death is gold + 30+s map pressure handed back.",
            })
        if cur_kda < 1.0 and (k + d + a) > 0:
            wrong_team.append({
                "text": f"Sub-1 KDA ({cur_kda})",
                "why": f"{k}/{d}/{a} = {cur_kda} - below the 1.0 baseline; "
                       f"deaths outpaced (kills + assists), so each fight "
                       f"likely net-negative for the team.",
            })

    # -- my_chronic: repeated patterns across history --------------------
    if history:
        deaths_hist = sorted(int(r.get("deaths") or 0) for r in history)
        median_d = deaths_hist[len(deaths_hist) // 2] if deaths_hist else 0
        if d > median_d + 3 and median_d > 0:
            my_chronic.append({
                "text": f"Deaths above your average ({d} vs ~{median_d} median)",
                "why": f"Across your last {len(history)} non-TFT games, your "
                       f"median deaths is {median_d}. This match's {d} is "
                       f"3+ above that - repeating pattern of overcommitting.",
            })

        cspm_hist = [float(r.get("cs_per_min") or 0.0) for r in history
                     if (r.get("mode") == "SR")]
        if cspm_hist and current.get("mode") == "SR":
            median_cspm = sorted(cspm_hist)[len(cspm_hist) // 2]
            if cspm < median_cspm - 1.0:
                my_chronic.append({
                    "text": f"CS/min below your SR median ({cspm:.1f} vs ~{median_cspm:.1f})",
                    "why": f"Your SR median over the last {len(cspm_hist)} games "
                           f"is {median_cspm:.1f} CS/min. This match's "
                           f"{cspm:.1f} is 1+ below - wave-management/death-cost "
                           f"pattern worth a deeper review.",
                })

        grades_hist = [(r.get("grade") or "").upper().strip() for r in history]
        bad_grades = [g for g in grades_hist if g in ("D", "F")]
        if len(bad_grades) >= max(3, len(history) // 3):
            my_chronic.append({
                "text": f"Recent grade slump ({len(bad_grades)}/{len(history)} at D/F)",
                "why": f"{len(bad_grades)} of your last {len(history)} games "
                       f"graded D or F - a third+ of recent matches in the "
                       f"weak-performance tier. Worth a focused review session.",
            })

    if not my_chronic:
        my_chronic.append({
            "text": "No chronic pattern detected (yet)",
            "why": "Not enough recent matches to compute baselines, or this "
                   "match's stats are within +/-1 SD of your medians.",
        })

    return {
        "right":      right,
        "wrong_team": wrong_team,
        "my_chronic": my_chronic,
    }


def _build_last_match(baseline: int = 20, match_ts: str | None = None) -> dict:
    """Post Game Review payload for the Last Match page.

    Source: data/match_history.db (operator-centric - KDA / CS / gold /
    grade / DS picks). rewind_history.db is stale (Dec 2025) so we do
    NOT enrich from Match-V5 here; the v2 Refresh button will trigger
    that path.

    `match_ts` (HIST2): when None (the live default) the newest non-TFT
    row is returned - byte-identical to pre-HIST2 behavior. When set to a
    "YYYY-MM-DD HH:MM:SS" timestamp, the row whose timestamp matches
    EXACTLY is returned instead, so a History / Session match-row click
    can open that specific match's detached historical PGR. An unknown ts
    returns found=False (NOT a silent latest fallback - that would render
    the wrong match under the operator's selection). The Quick Review
    baseline still excludes the selected row by its id, so the chronic
    comparison is correct for the historical row too.

    Returns:
      {
        "found": bool,
        "match": { ... full operator-side stats ... } | None,
        "history_count": int,   # how many rows backed the Quick Review baseline
        "quick_review": {right, wrong_team, my_chronic},  # see _compute_quick_review
      }
    """
    import json
    # s220: baseline window is operator-configurable from the Settings
    # page (localStorage rc-pgr-baseline -> ?baseline= query param).
    # Clamp to a sane range; default 20 preserves pre-s220 behavior.
    try:
        baseline = int(baseline)
    except (TypeError, ValueError):
        baseline = 20
    baseline = max(5, min(50, baseline))
    match_ts = (str(match_ts).strip() or None) if match_ts is not None else None
    out: dict = {"found": False, "match": None, "history_count": 0}
    db_path = _APP_DIR / "data" / "match_history.db"
    conn = _ro_conn(db_path)
    if conn is None:
        out["error"] = "match_history.db missing"
        return out
    try:
        _cols = ("id, timestamp, mode, champion, grade, kda_str, "
                 "game_time_s, kills, deaths, assists, cs, cs_per_min, "
                 "gold, gold_per_min, kp_pct, label, raw_data")
        if match_ts:
            # HIST2: pin a specific historical row by exact timestamp.
            # mode != 'TFT' is kept so a TFT row never leaks into the PGR.
            cur = conn.execute(
                f"SELECT {_cols} FROM matches "
                "WHERE mode != 'TFT' AND timestamp = ? "
                "ORDER BY id DESC LIMIT 1",
                (match_ts,),
            )
        else:
            cur = conn.execute(
                f"SELECT {_cols} FROM matches WHERE mode != 'TFT' "
                "ORDER BY timestamp DESC LIMIT 1"
            )
        latest = cur.fetchone()
        if not latest:
            return out

        (mid, ts, mode, champ, grade, kda_str, dur,
         k, d, a, cs, cspm, gold, gpm, kp, label, raw) = latest

        ds_picks: list = []
        coach_action: str = ""
        lcu_detail: dict = {}
        tracked_puuid: str = ""
        lcu_ingested_at: str = ""
        if raw:
            try:
                rd = json.loads(raw)
                ds_picks        = rd.get("daemon_slayer_picks") or []
                coach_action    = (rd.get("coach_action") or "").strip()
                lcu_detail      = rd.get("lcu_match_detail") or {}
                tracked_puuid   = (rd.get("tracked_puuid") or "").strip()
                lcu_ingested_at = rd.get("lcu_ingested_at") or ""
            except Exception:  # noqa: BLE001
                pass

        kda_ratio = round((int(k or 0) + int(a or 0)) / max(int(d or 0), 1), 2)

        # s220 Item E: attach the Match-V5 per-minute timeline (gold/xp/cs
        # differential + objective ribbon) onto the enriched blob for the
        # Post Game Review "Timeline" tab. Server-side fetch - the LCU has
        # no timeline endpoint; Match-V5 is the source (immutable-cached,
        # degrades to a placeholder when the Riot key is unavailable).
        enriched = (_enrich_from_lcu(lcu_detail, tracked_puuid)
                    if (lcu_detail and tracked_puuid) else None)
        if enriched and lcu_detail:
            _attach_match_timeline(enriched, lcu_detail)

        match_row = {
            "id":               int(mid),
            "timestamp":        ts,
            "mode":             mode,
            "champion":         champ or "?",
            "grade":            grade or "-",
            "kda_str":          kda_str or f"{k or 0}/{d or 0}/{a or 0}",
            "kda_ratio":        kda_ratio,
            "duration_s":       int(dur or 0),
            "kills":            int(k or 0),
            "deaths":           int(d or 0),
            "assists":          int(a or 0),
            "cs":               int(cs or 0),
            "cs_per_min":       float(cspm or 0.0),
            "gold":             int(gold or 0) if gold is not None else None,
            "gold_per_min":     float(gpm or 0.0) if gpm is not None else None,
            "kp_pct":           float(kp) if kp is not None else None,
            "gold_share_pct":   (gold_share_pct(enriched.get("roster"))
                                 if enriched else None),
            "label":            label or "",
            "coach_action":     coach_action,
            "ds_picks":         ds_picks,
            "lcu_ingested_at":  lcu_ingested_at,
            "enriched":         enriched,
        }
        # OQ12 slice A: normalized carry-metrics bundle. Appended AFTER the
        # literal closes so the two keys land at the END of the payload
        # (additive - no existing consumer sees a reordered field).
        match_row["dmg_share_pct"] = (dmg_share_pct(enriched.get("roster"))
                                      if enriched else None)
        match_row["carry_normalized"] = _carry_normalized(
            match_row, enriched, lcu_detail)

        # Baseline rows for chronic-fail computation (exclude this one)
        history: list[dict] = []
        cur = conn.execute(
            "SELECT mode, grade, kills, deaths, assists, cs, cs_per_min "
            "FROM matches WHERE mode != 'TFT' AND id != ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (int(mid), baseline)
        )
        for h_mode, h_grade, hk, hd, ha, h_cs, h_cspm in cur:
            history.append({
                "mode": h_mode, "grade": h_grade,
                "kills": hk, "deaths": hd, "assists": ha,
                "cs": h_cs, "cs_per_min": h_cspm,
            })

        out["found"] = True
        out["match"] = match_row
        out["history_count"] = len(history)
        out["quick_review"] = _compute_quick_review(match_row, history)

    except sqlite3.Error as exc:
        # Evict the possibly-poisoned per-thread cached conn so the next
        # call reopens cleanly (mirrors builders.py / builders_home.py).
        _log.warning("_build_last_match: %s", exc)
        out["error"] = "internal error - see logs"
        getattr(_DB_CONN_LOCAL, "conns", {}).pop(str(db_path), None)
    except Exception as exc:  # noqa: BLE001
        _log.warning("_build_last_match: %s", exc)
        # Raw exception text can carry file paths - log it, never render it.
        out["error"] = "internal error - see logs"
    # NOTE: no conn.close() here - _ro_conn returns the SHARED per-thread
    # cached connection (dashboard/_context.py); closing it poisoned the
    # cache for every later same-thread caller (audit cycle 8 slice E).
    return out
