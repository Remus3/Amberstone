"""
performance_tracker.py - Per-mode rating + match history DB.
Modes: SR, ARAM, ARENA, BRAWL, TFT (incl. Double Up 4-team grading).
Double Up placement: (alive_others+1)//2 maps individual deaths to team placement.
"""
import json
import os
import re
import logging
from datetime import datetime
from pathlib import Path
_log = logging.getLogger("rc.tracker")
# 2026-04-27: unification - the per-mode last_<mode>.json files are the
# canonical source of truth. The "last across all modes" is now derived as
# the most-recently-modified per-mode file (see _latest_rating_file). This
# removes the dual-write that ignored RC_ACCOUNT_ID namespacing.
RATINGS_DIR = "data/ratings"


def _atomic_write_json(path: Path, data: dict) -> None:
    """Atomic JSON write - CLAUDE.md SHard rules. Overlays/dashboard poll
    mid-write, so the only safe pattern is tmp.write -> os.replace.
    AUDIT C4 (2026-04-22): replaces direct path.write_text usage below."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # allow_nan=False: a stray inf/nan (e.g. a degenerate upstream
    # cs_per_min) must raise here BEFORE the tmp file is written, rather
    # than serialize to the bare ``Infinity`` / ``NaN`` tokens that a
    # strict JSON reader (the dashboard rating panel) rejects. The caller
    # wraps this in try/except + warn, so a raise just drops the one bad
    # rating and leaves the prior valid file intact.  (P2-W4 hw2 slice H)
    payload = json.dumps(data, indent=2, allow_nan=False)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)
BENCHMARKS = {"cs_per_min": 8.5, "deaths_per_10": 0.8, "kp_pct": 65, "gold_per_min": 380}
GRADE_COLORS = {"S": "#FFD700", "A": "#44FF88", "B": "#4A9EFF", "C": "#D0D0E0", "D": "#FFA84A", "F": "#FF4A6A"}
GRADE_LABEL = {"S": "DOMINANT \u2014 elite across all metrics", "A": "GREAT \u2014 above baseline, one area to sharpen",
    "B": "SOLID \u2014 on track, tighten fundamentals", "C": "AVERAGE \u2014 clear gaps to address",
    "D": "BELOW \u2014 focus on one area at a time", "F": "REBUILD \u2014 fundamentals need serious work"}
_MODE_CATEGORY = {"CLASSIC":"SR","RANKED_SOLO":"SR","RANKED_FLEX":"SR","PRACTICETOOL":None,"TUTORIAL":None,
    "ARAM":"ARAM","ARAM_UNRANKED_5X5":"ARAM","ARAM_UNRANKED_5x5":"ARAM","KIWI":"ARAM","ARENA":"ARENA","CHERRY":"ARENA",
    "NEXUSBLITZ":"BRAWL","ULTBOOK":"BRAWL","URF":"BRAWL","ARURF":"BRAWL","ONEFORALL":"BRAWL","GAMEMODEX":"BRAWL",
    "TFT":"TFT","TFT_RANKED":"TFT","TFT_UNRANKED":"TFT","TFT_DOUBLE_UP":"TFT","TFT_TURBO":"TFT","TFT_PAIRS":"TFT"}
_EXCLUDED_MODES = {"PRACTICETOOL","TUTORIAL","TUTORIAL_MODULE_1","TUTORIAL_MODULE_2","TUTORIAL_MODULE_3"}
_match_db = None
def _get_db(sd):
    global _match_db
    if _match_db is None:
        try:
            from core.match_db import MatchDB; _match_db = MatchDB(Path(sd) / "data" / "match_history.db")
        except Exception as e: _log.warning("MatchDB init failed: %s", e)
    return _match_db


# Maps the rating category back to the coaching-state JSON each coach
# writes per tick. Used by save_rating to attach the engine's last DS
# pick set to matches.raw_data so the historical row carries the
# recommendation alongside the actual outcome - calibration analysis no
# longer needs to JOIN against ds_calibration.jsonl on (champion, mode,
# approximate timestamp).
_DS_COACH_FILE_BY_CATEGORY = {
    "SR":    "coaching_data.json",
    "ARAM":  "aram_coaching_data.json",
    "ARENA": "arena_coaching_data.json",
    "BRAWL": "brawl_coaching_data.json",
}


def _ds_picks_snapshot(sd, category):
    """Return the most recent DS pick list the coach wrote for this mode.

    Soft-fails to [] - DS persistence is observability, never gates the
    match save. Caller passes the result into raw_data so the persisted
    row carries the engine's recommendation at game-end."""
    fname = _DS_COACH_FILE_BY_CATEGORY.get((category or "").upper())
    if not fname:
        return []
    p = Path(sd) / "data" / fname
    if not p.exists():
        return []
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        _log.debug("ds picks snapshot read failed (%s): %s", fname, exc)
        return []
    if not isinstance(d, dict):
        return []
    picks = d.get("daemon_slayer_picks")
    return picks if isinstance(picks, list) else []
def mode_category(gm):
    gm = (gm or "").upper().strip()
    if gm in _EXCLUDED_MODES: return ""
    cat = _MODE_CATEGORY.get(gm)
    if cat is not None: return cat
    for prefix, c in [("TFT","TFT"),("ARAM","ARAM"),("ARENA","ARENA"),("CHERRY","ARENA"),("TUTORIAL",""),("PRACTICE","")]:
        if gm.startswith(prefix): return c
    return "SR"
# 2026-04-25: multi-account scaffold. Set RC_ACCOUNT_ID to namespace
# ratings into data/ratings/<account>/. Unset = legacy flat layout
# (keeps single-account installs working with no migration). Account
# id is sanitized to [a-z0-9_-] so a stray summoner tag can't escape
# the dir.
def _account_id() -> str:
    raw = (os.environ.get("RC_ACCOUNT_ID") or "").strip().lower()
    if not raw:
        return ""
    return "".join(c for c in raw if c.isalnum() or c in "_-")[:40]


def _ratings_dir(sd):
    base = Path(sd) / RATINGS_DIR
    acct = _account_id()
    d = (base / acct) if acct else base
    d.mkdir(parents=True, exist_ok=True)
    return d


def _mode_file(sd, cat): return _ratings_dir(sd) / f"last_{cat.lower()}.json"
_RATING_CATEGORIES = ("SR", "ARAM", "ARENA", "BRAWL", "TFT")
def _latest_rating_file(sd):
    """Return the per-mode rating file with the newest mtime, or None.
    Used as the "last across all modes" pointer that replaced the
    legacy data/ratings/last_game_rating.json (2026-04-27 unification)."""
    newest = None; newest_m = -1.0
    d = _ratings_dir(sd)
    for cat in _RATING_CATEGORIES:
        p = d / f"last_{cat.lower()}.json"
        try:
            m = p.stat().st_mtime
            if m > newest_m: newest, newest_m = p, m
        except OSError: continue
    return newest
def is_valid_match(gs):
    gm = (gs.get("game_mode","") or "").upper()
    if gm in _EXCLUDED_MODES or gm.startswith("TUTORIAL") or gm.startswith("PRACTICE"): return False
    return gs.get("game_seconds", 0) >= 180

def calculate_rating(s):
    cs=s.get("cs_per_min",0);d=s.get("deaths",0);gm=max(1.0,s.get("game_mins",1));k=s.get("kills",0);a=s.get("assists",0)
    tk=max(1,s.get("ally_kills_total",1));gpm=s.get("gold_per_min",0);kp=min(100,(k+a)/tk*100);d10=(d/gm)*10;sc=0.0;n=[]
    if gm>=8:
        r=min(1.5,cs/BENCHMARKS["cs_per_min"]);sc+=r*30
        if cs<5.5:n.append(f"CS/min ({cs:.1f}) critical")
        elif cs<7.5:n.append(f"CS/min ({cs:.1f}) below target")
    else:sc+=15
    if d10<=0.5:sc+=30;n.append(f"Excellent survival ({d}d)")
    elif d10<=1.0:sc+=22
    elif d10<=1.8:sc+=12;n.append(f"{d} deaths \u2014 review avoidable ones")
    else:sc+=2;n.append(f"Too many deaths ({d})")
    r=min(1.3,kp/BENCHMARKS["kp_pct"]);sc+=r*25
    if kp<45:n.append(f"KP ({kp:.0f}%) too low")
    if gm>=8:
        r=min(1.3,gpm/BENCHMARKS["gold_per_min"]);sc+=r*15
        if gpm<280:n.append(f"GPM ({gpm}) low")
    sc=min(100,sc)
    g="S" if sc>=92 else "A" if sc>=78 else "B" if sc>=62 else "C" if sc>=46 else "D" if sc>=30 else "F"
    return g,(n or ["Well-rounded"])[:3]

def calculate_aram_rating(s):
    d=s.get("deaths",0);gm=max(1.0,s.get("game_mins",1));k=s.get("kills",0);a=s.get("assists",0)
    tk=max(1,s.get("ally_kills_total",1));kp=min(100,(k+a)/tk*100);d10=(d/gm)*10;sc=0.0;n=[]
    kda=(k+a)/max(1,d)
    if kda>=5:sc+=40;n.append(f"Dominant KDA ({kda:.1f})")
    elif kda>=3:sc+=28
    elif kda>=2:sc+=18;n.append(f"KDA ({kda:.1f}) \u2014 pick fights carefully")
    else:sc+=5;n.append(f"Low KDA ({kda:.1f})")
    if d10<=1.5:sc+=30
    elif d10<=2.5:sc+=20
    elif d10<=4.0:sc+=10;n.append(f"{d} deaths")
    else:sc+=2;n.append(f"Too many deaths ({d})")
    if kp>=70:sc+=30
    elif kp>=55:sc+=20
    else:sc+=8;n.append(f"Low KP ({kp:.0f}%)")
    sc=min(100,sc)
    g="S" if sc>=90 else "A" if sc>=75 else "B" if sc>=58 else "C" if sc>=42 else "D" if sc>=25 else "F"
    return g,(n or ["Solid ARAM"])[:3]

def calculate_arena_rating(s):
    k=s.get("kills",0);d=s.get("deaths",0);n=[];kda=(k+s.get("assists",0))/max(1,d);sc=0.0
    if kda>=4:sc+=50;n.append(f"Strong KDA ({kda:.1f})")
    elif kda>=2:sc+=30;n.append(f"KDA ({kda:.1f})")
    else:sc+=10;n.append(f"Low KDA ({kda:.1f})")
    if d<=3:sc+=30
    elif d<=6:sc+=18
    else:sc+=5;n.append(f"{d} deaths")
    sc+=min(20,k*2.5);sc=min(100,sc)
    g="S" if sc>=88 else "A" if sc>=72 else "B" if sc>=55 else "C" if sc>=40 else "D" if sc>=25 else "F"
    return g,(n or ["Solid Arena"])[:3]

def calculate_brawl_rating(s):
    k=s.get("kills",0);d=s.get("deaths",0);a=s.get("assists",0);n=[];kda=(k+a)/max(1,d);sc=0.0
    if kda>=4:sc+=45;n.append(f"Dominant KDA ({kda:.1f})")
    elif kda>=2.5:sc+=30
    elif kda>=1.5:sc+=18;n.append(f"KDA ({kda:.1f})")
    else:sc+=5;n.append(f"Low KDA ({kda:.1f})")
    if k>=15:sc+=25;n.append(f"{k} kills")
    elif k>=8:sc+=15
    else:sc+=5
    sc+=min(30,a*1.5);sc=min(100,sc)
    g="S" if sc>=88 else "A" if sc>=70 else "B" if sc>=52 else "C" if sc>=38 else "D" if sc>=22 else "F"
    return g,(n or ["Fun mode"])[:3]

_TFT_GRADE={1:"S",2:"A",3:"A",4:"B",5:"C",6:"D",7:"D",8:"F"}
_TFT_GRADE_DUO={1:"S",2:"A",3:"D",4:"F"}
_TFT_LABEL={1:"1ST PLACE \u2014 dominant lobby",2:"TOP 2 \u2014 strong board",3:"TOP 3 \u2014 solid comp",4:"TOP 4 \u2014 positive LP",5:"5TH \u2014 missed top 4",6:"6TH \u2014 board fell off",7:"7TH \u2014 major gaps",8:"8TH \u2014 full rebuild"}
_TFT_LABEL_DUO={1:"1ST \u2014 won the lobby",2:"2ND \u2014 strong run",3:"3RD \u2014 board fell off",4:"4TH \u2014 eliminated early"}

def _parse_tft_placement(s):
    if not s: return 0
    s=str(s).lower().strip();m=re.search(r'(\d)[snrt][tdh]',s)
    if m: return int(m.group(1))
    m=re.search(r'(\d)',s)
    return int(m.group(1)) if m else 0
def _identify_comp(traits,units):
    if traits:
        parsed = []
        for t in traits:
            if not t: continue
            parts = str(t).rsplit(" ", 1)
            name = parts[0]
            try: count = int(parts[1]) if len(parts) > 1 else 1
            except Exception: count = 1
            parsed.append((name, count))
        parsed.sort(key=lambda x: -x[1])
        top = [f"{n} {c}" for n, c in parsed if c > 1][:3]
        if not top: top = [f"{n}" for n, c in parsed[:2]]
        if top: return " / ".join(top)
    if units: return " + ".join([u for u in units if u and u != "unknown"][:3])
    return ""
def _core_units(units): return [u.split(" ")[0] if " " in u and "star" in u else u for u in (units or []) if u and u != "unknown"][:3]

def calculate_tft_rating(placement,stage=0,level=0,game_mins=0.0,traits=None,units=None,augments=None,is_duo=False):
    mx=4 if is_duo else 8
    if placement<1 or placement>mx: return ("", [])
    gm=(_TFT_GRADE_DUO if is_duo else _TFT_GRADE).get(placement,"C");n=[];comp=_identify_comp(traits or [],units or []);core=_core_units(units or [])
    tag=" (Double Up)" if is_duo else ""
    if placement==1:n.append(f"1st place{tag} \u2014 dominant")
    elif placement<=2:n.append(f"Top {placement}{tag} \u2014 close to winning")
    elif placement<=4 and is_duo:n.append(f"#{placement}{tag} \u2014 review board + partner sync")
    elif placement<=4:n.append("Top 4 \u2014 LP positive")
    elif placement<=6:n.append(f"#{placement} \u2014 review rolldown timing")
    else:n.append(f"#{placement} \u2014 early board needs work")
    if core:n.append(f"Core units: {', '.join(core)}")
    if 0<stage<=4:n.append(f"Eliminated Stage {stage} \u2014 stabilize earlier")
    return gm,n[:4]

def save_tft_rating(script_dir,tft_live,tft_coaching=None):
    if not tft_live: return ("", [])
    variant=(tft_coaching or {}).get("variant","standard")
    alive_others=(tft_coaching or {}).get("alive_others",7)
    is_duo=variant in ("double_up","TFT_DOUBLE_UP","TFT_PAIRS")
    mx=4 if is_duo else 8
    placement=_parse_tft_placement(tft_live.get("last_round_result","") or "")
    if placement<1 and tft_coaching:
        if is_duo:
            placement=max(1,(alive_others+1)//2)
        else:
            placement=max(1,alive_others+1)
    if placement<1 or placement>mx: return ("", [])
    ss=tft_live.get("stage_round","");sn=0
    if ss:
        try:sn=int(str(ss).split("-")[0])
        except Exception as _e: _log.debug("TFT stage parse: %s", _e)  # QUAL-002
    if not sn and tft_coaching:sn=tft_coaching.get("stage",0)
    lv=tft_live.get("level") or (tft_coaching or {}).get("level",0) or 0
    gs=(tft_coaching or {}).get("game_time_s",0);gm=max(0,gs/60) if gs else 0
    traits=tft_live.get("traits_active",[]) or [];units=tft_live.get("board_units",[]) or []
    augments=tft_live.get("augments",[]) or []
    try:
        import json as _j
        _sd = Path(script_dir)
        _cs = _j.loads((_sd / "data" / "comp_state.json").read_text(encoding="utf-8"))
        _sel = _cs.get("selected", "")
        if _sel:
            _meta_f = _sd / "data" / "meta" / "tft_set17_meta.json"
            if not _meta_f.exists():
                _meta_f = _sd / "data" / "meta" / "tft_set17_pbe_meta.json"
            if _meta_f.exists():
                _meta = _j.loads(_meta_f.read_text(encoding="utf-8-sig"))
                _cd = _meta.get("comps", {}).get(_sel, {})
                if _cd:
                    _lv8 = _cd.get("lv8") or _cd.get("lv7") or _cd.get("core_units", [])
                    _core_u = _cd.get("core_units", [])
                    _traits_from_meta = [_sel] + [f"{e} Emblem" for e in (_cd.get("emblem_value") or [])[:2]]
                    units = _lv8 if _lv8 else units
                    traits = _traits_from_meta if _traits_from_meta else traits
                    augments = augments or _cd.get("augments_best", [])[:3]
    except Exception as _e:  # QUAL-002
        import logging as _lg; _lg.getLogger(__name__).debug("TFT data enrichment: %s", _e)
    comp=_sel if _sel else _identify_comp(traits,units);core=_core_units(units)
    if not comp:comp=_identify_comp(traits,units)
    grade,notes=calculate_tft_rating(placement,sn,lv,gm,traits,units,augments,is_duo=is_duo)
    if not grade: return ("", [])
    lmap=_TFT_LABEL_DUO if is_duo else _TFT_LABEL
    _log.info("TFT rating: placement=%d is_duo=%s alive=%d variant=%s grade=%s",placement,is_duo,alive_others,variant,grade)
    _raw_placement = tft_live.get("unit_placement", "") or ""
    try:
        from tft.placement_aggregator import parse_unit_placement as _pup
        _unit_positions = _pup(_raw_placement)
    except Exception:
        _unit_positions = {}
    data={"rating":grade,"label":lmap.get(placement,""),"champion":comp or f"TFT #{placement}",
        "game_mode":"TFT_DOUBLE_UP" if is_duo else "TFT","mode_category":"TFT",
        "game_time":f"{int(gm)}:{int(gs%60):02d}" if gs else "?",
        "stats":{"kda":f"#{placement}","cs_per_min":f"Lv{lv}","gold_per_min":f"Stage {sn}" if sn else "?"},
        "notes":notes,"timestamp":datetime.now().strftime("%Y-%m-%d %H:%M"),
        "tft_placement":placement,"tft_stage":sn,"tft_level":lv,
        "tft_comp":comp,"tft_traits":traits,"tft_units":units,"tft_augments":augments,"tft_core_units":core,
        "tft_unit_positions":_unit_positions,"tft_unit_placement":_raw_placement}
    try:
        _atomic_write_json(_mode_file(script_dir, "TFT"), data)
    except Exception as _e:
        _log.warning("TFT rating save failed: %s", _e)  # QUAL-002
    db=_get_db(script_dir)
    if db:
        try:db.save_match({"mode":"TFT","champion":comp,"grade":grade,"game_time_s":gs,"tft_placement":placement,"tft_stage":sn,"tft_level":lv,"tft_comp":comp,"tft_traits":traits,"tft_units":units,"tft_augments":augments,"tft_items":"","notes":notes,"label":lmap.get(placement,"")})
        except Exception as e:_log.warning("TFT DB save failed: %s",e)
    try:
        from tft.placement_aggregator import update_heatmap as _uh
        _uh()
    except Exception as _e:
        _log.debug("Heatmap update: %s", _e)
    return grade, notes

def save_rating(script_dir,champion,game_state,ally_kills_total):
    if not is_valid_match(game_state): return ("", [])
    game_secs=game_state.get("game_seconds",0);game_mins=max(1.0,game_secs/60)
    gpm=round(game_state.get("gold",0)/game_mins);raw_mode=game_state.get("game_mode","CLASSIC")
    category=mode_category(raw_mode)
    if not category: return ("", [])
    stats={"cs_per_min":game_state.get("cs_per_min",0),"deaths":game_state.get("deaths",0),"kills":game_state.get("kills",0),"assists":game_state.get("assists",0),"game_mins":game_mins,"ally_kills_total":ally_kills_total,"gold_per_min":gpm}
    if category=="ARAM":grade,notes=calculate_aram_rating(stats)
    elif category=="ARENA":grade,notes=calculate_arena_rating(stats)
    elif category=="BRAWL":grade,notes=calculate_brawl_rating(stats)
    else:grade,notes=calculate_rating(stats)
    kda_str=game_state.get("kda","0/0/0");kp=round((stats["kills"]+stats["assists"])/max(1,ally_kills_total)*100)
    data={"rating":grade,"label":GRADE_LABEL.get(grade,""),"champion":champion,"game_mode":raw_mode,"mode_category":category,"game_time":game_state.get("game_time","0:00"),
        "stats":{"cs_per_min":round(stats["cs_per_min"],1),"kda":kda_str,"deaths":stats["deaths"],"kill_participation":kp,"gold_per_min":gpm},
        "notes":notes,"timestamp":datetime.now().strftime("%Y-%m-%d %H:%M")}
    try:
        _atomic_write_json(_mode_file(script_dir, category), data)
    except Exception as _e:
        _log.warning("Rating save failed (%s): %s", category, _e)  # QUAL-002
    db=_get_db(script_dir)
    if db:
        # 2026-05-09: snapshot the engine's last DS pick set into raw_data
        # so the persisted row carries the engine recommendation alongside
        # the actual outcome. Cuts the calibration analysis from a JSONL
        # join (ds_calibration.jsonl join matches on champion/mode/~ts) down
        # to a single SELECT.
        _ds_picks = _ds_picks_snapshot(script_dir, category)
        _raw = {"coach_action":game_state.get("coach_action",""),
                "coach_analysis":game_state.get("coach_analysis",""),
                "game_mode":raw_mode}
        if _ds_picks:
            _raw["daemon_slayer_picks"] = _ds_picks
        # Item 211: persist Live Client gameId when available so the
        # /api/last-match/ingest pipeline can row-match deterministically
        # instead of "latest non-TFT row" (which raced this writer and
        # produced Home Recent-5 items-off-by-one).
        _gid = 0
        try:
            _gid = int(game_state.get("game_id") or game_state.get("gameId") or 0)
        except (TypeError, ValueError):
            _gid = 0
        try:db.save_match({"mode":category,"champion":champion,"grade":grade,"game_time_s":game_secs,"kills":stats["kills"],"deaths":stats["deaths"],"assists":stats["assists"],"cs":game_state.get("cs",0),"cs_per_min":stats["cs_per_min"],"gold":game_state.get("gold",0),"gold_per_min":gpm,"kda_str":kda_str,"kp_pct":kp,"arena_rounds_won":game_state.get("arena_rounds_won",0),"arena_placement":game_state.get("arena_rank",0),"notes":notes,"label":GRADE_LABEL.get(grade,""),"raw_data":json.dumps(_raw,default=str),"game_id":_gid})
        except Exception as e:_log.warning("Match DB save failed: %s",e)
    # 2026-04-25: adaptation feedback loop. Translate the user's grade
    # (S/A/B/C/D/F) into a confidence multiplier on the cache entry for
    # this game's final state. Future similar states get advice weighted
    # by past success. Non-fatal - the rating save proceeds regardless.
    try:
        from coaches.feedback import apply_grade
        apply_grade(grade, game_state)
    except Exception as _fe:
        _log.debug("feedback.apply_grade failed: %s", _fe)
    # 2026-04-26: experimental-build adaptation hook. If the user opted
    # into the experimental variant for this match, archive the result
    # against the current iteration and (on poor grades) auto-generate
    # the next iteration. Marker is consumed regardless of category.
    try:
        from coaches import experimental_builder as _eb
        marker = _eb.consume_active()
        if marker and marker.get("champion") == champion:
            api_key = ""
            try:
                api_key = (Path(script_dir) / "API-Key-Claude.txt").read_text(encoding="utf-8").strip()
            except Exception: pass
            gs_for_record = {
                "kda":         kda_str,
                "kp_pct":      kp,
                "gold_per_min": gpm,
                "notes":        notes,
            }
            _eb.record_result(champion, grade, gs_for_record, api_key)
    except Exception as _ee:
        _log.debug("experimental.record_result failed: %s", _ee)
    return grade, notes

def load_rating(sd,category=""):
    try:
        p = _mode_file(sd, category) if category else _latest_rating_file(sd)
        if p and p.exists(): return json.loads(p.read_text(encoding="utf-8"))
    except Exception as _e: _log.debug("load_rating %s: %s", category or 'default', _e)  # QUAL-002
    return None
def load_all_ratings(sd):
    r={}
    for cat in ("SR","ARAM","ARENA","BRAWL","TFT"):
        d=load_rating(sd,cat)
        if d:r[cat]=d
    return r
