"""
performance_tracker.py - Per-mode rating + match history DB.
Modes: SR, ARAM, ARENA, BRAWL, TFT (incl. Double Up 4-team grading).
Double Up placement: (alive_others+1)//2 maps individual deaths to team placement.
"""
import json
import os
import re
import logging
import time
from datetime import datetime
from pathlib import Path

from core.polled_json import atomic_write_bytes

_log = logging.getLogger("rc.tracker")
# 2026-04-27: unification - the per-mode last_<mode>.json files are the
# canonical source of truth. The "last across all modes" is now derived as
# the most-recently-modified per-mode file (see _latest_rating_file). This
# removes the dual-write that ignored RC_ACCOUNT_ID namespacing.
RATINGS_DIR = "data/ratings"


def _atomic_write_json(path: Path, data: dict) -> None:
    """Atomic JSON write - CLAUDE.md hard rules. Overlays/dashboard poll
    mid-write, so the only safe pattern is tmp.write -> os.replace.
    AUDIT C4 (2026-04-22): replaces direct path.write_text usage below.

    Lane 8 cycle 23: the replace step now goes through
    ``core.polled_json.atomic_write_bytes``, which carries the bounded
    PermissionError backoff. This used to be a BARE ``os.replace``, and
    that is a measured defect on Windows rather than a theoretical one:
    ``os.replace`` raises PermissionError (WinError 5) whenever a
    concurrent reader holds the destination open, a plain CPython
    ``open()`` handle is enough, and these rating files have a real
    cross-process reader in ``agents/supervisor.py:794-805``. Measured
    on Python 3.14 / win32: the bare call raised in under a millisecond
    against a reader that released after 80 ms, while the retry-backed
    call rode it out and landed its content.

    ``core/polled_json.py:30-35`` already recorded this and the same fix
    already shipped to ``ops/rc_supervisor.atomic_write_json`` on
    2026-05-02; this module simply held a private copy that never got it.
    The retry buys the TRANSIENT window only - under a permanently held
    handle it still raises, exactly as that helper's comment claims.

    Bytes, not text: ``Path.write_text`` rewrites LF as CRLF on Windows
    (reference_windows_write_text_crlf_byte_count), so the encode is
    explicit here and the byte count on disk matches the payload."""
    # allow_nan=False: a stray inf/nan (e.g. a degenerate upstream
    # cs_per_min) must raise here BEFORE the tmp file is written, rather
    # than serialize to the bare ``Infinity`` / ``NaN`` tokens that a
    # strict JSON reader (the dashboard rating panel) rejects. The caller
    # wraps this in try/except + warn, so a raise just drops the one bad
    # rating and leaves the prior valid file intact.  (P2-W4 hw2 slice H)
    payload = json.dumps(data, indent=2, allow_nan=False)
    # An exhausted retry must not leave a stray scratch file beside the target
    # - the sibling lane 8 cycle 22 audit records the repo treating an orphaned
    # tmp after a failed replace as a defect in its own right
    # (tests/test_sr_user_builds_lane8_cycle22.py:28). Lane 8 cycle 24 moved
    # that cleanup INTO atomic_write_bytes, which now removes its own scratch
    # file on every failure path. The mirror that used to live here unlinked
    # ``<dest>.tmp``, a name the helper no longer uses, so keeping it would be
    # a no-op dressed as a guarantee.
    atomic_write_bytes(path, payload.encode("utf-8"))


def _num(value, default=0):
    """Coerce a metric to a number, treating a present-but-NULL field the
    same as a missing one.

    Every numeric read in this module used ``game_state.get(key, default)``,
    which supplies the default only when the KEY IS ABSENT and passes a
    present ``None`` straight through to the arithmetic. Measured lane 8
    cycle 23: six fields (ally_kills_total, cs_per_min, gold, game_seconds,
    deaths, kills) each crashed ``save_rating`` with a TypeError on a null.

    That is not a cosmetic crash. Both call sites - ``app/_game_lifecycle``
    ``.py:201`` and ``:230`` - wrap the call in ``except Exception``, so the
    raise is swallowed and the user silently loses BOTH the rating file and
    the match_history.db row, while the caller still logs success. The
    upstream Live Client feed is one RC does not control and has changed
    shape before, so a null is a shape this boundary has to absorb.

    The caller is a FROZEN file, so the coercion belongs here at the
    boundary - which is the correct place for it regardless."""
    if isinstance(value, bool):
        # A bool where a metric was expected is wrong input, not the 0/1 it
        # would silently arithmetic as.
        return default
    if isinstance(value, (int, float)):
        return value
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _redact(text: str, secret: str) -> str:
    """Strip a credential out of a string that is about to be logged.

    The experimental-builder hook hands the Anthropic API key to
    ``record_result``; if that call raises with the credential embedded in
    its message (the ordinary shape for a client that echoes the request it
    built), the outer handler would write the key into
    ``logs/YYYY-MM-DD.log``. CLAUDE.md forbids the key reaching any log
    line, so the handler redacts before formatting rather than trusting the
    callee's exception text.

    The length floor keeps an empty or trivially short value from matching
    everywhere in the message."""
    if secret and len(secret) >= 8 and secret in text:
        return text.replace(secret, "[redacted]")
    return text
BENCHMARKS = {"cs_per_min": 8.5, "deaths_per_10": 0.8, "kp_pct": 65, "gold_per_min": 380}
GRADE_COLORS = {"S": "#FFD700", "A": "#44FF88", "B": "#4A9EFF", "C": "#D0D0E0", "D": "#FFA84A", "F": "#FF4A6A"}
GRADE_LABEL = {"S": "DOMINANT - elite across all metrics", "A": "GREAT - above baseline, one area to sharpen",
    "B": "SOLID - on track, tighten fundamentals", "C": "AVERAGE - clear gaps to address",
    "D": "BELOW - focus on one area at a time", "F": "REBUILD - fundamentals need serious work"}
_MODE_CATEGORY = {"CLASSIC":"SR","RANKED_SOLO":"SR","RANKED_FLEX":"SR","PRACTICETOOL":None,"TUTORIAL":None,
    "ARAM":"ARAM","ARAM_UNRANKED_5X5":"ARAM","ARAM_UNRANKED_5x5":"ARAM","KIWI":"ARAM","ARENA":"ARENA","CHERRY":"ARENA",
    "NEXUSBLITZ":"BRAWL","ULTBOOK":"BRAWL","URF":"BRAWL","ARURF":"BRAWL","ONEFORALL":"BRAWL","GAMEMODEX":"BRAWL",
    "TFT":"TFT","TFT_RANKED":"TFT","TFT_UNRANKED":"TFT","TFT_DOUBLE_UP":"TFT","TFT_TURBO":"TFT","TFT_PAIRS":"TFT"}
_EXCLUDED_MODES = {"PRACTICETOOL","TUTORIAL","TUTORIAL_MODULE_1","TUTORIAL_MODULE_2","TUTORIAL_MODULE_3"}
_match_db = None
def _get_db(sd):
    """The MatchDB under THIS script root.

    s134 N8 / RM-888: this cached the first root it was ever handed and
    returned that database for every later call, whatever ``sd`` said - so one
    process that touched the real root first sent every later save (a tmp test
    root included) into the live data/match_history.db. That is the measured
    shape of the 8,209 TFT junk rows (one game id, 7,817 x "Dark Star Vertical"
    / 8th / 0 s, 114 x "Test Comp" - tests/test_tft_set_resolver.py's literal).
    The cache now holds only while the root is the same: it is keyed by the
    RESOLVED path, compared against the cached instance's OWN path (so a caller
    that swaps `_match_db` directly can never leave a stale key behind), and the
    instance replaced is closed. The instance keeps the path as given."""
    global _match_db
    try:
        given = Path(sd) / "data" / "match_history.db"
        path = given.resolve()
    except (OSError, TypeError, ValueError, RuntimeError) as e:
        _log.warning("MatchDB path for %r unusable: %s", sd, e)
        return None
    cur = _match_db
    try:
        cur_path = Path(getattr(cur, "_path", "")).resolve() if cur is not None else None
    except (OSError, TypeError, ValueError, RuntimeError):
        cur_path = None
    if cur is None or cur_path != path:
        _match_db = None
        if cur is not None:
            try: cur.close()
            except Exception as e: _log.debug("MatchDB close failed: %s", e)  # noqa: BLE001
        try:
            from core.match_db import MatchDB; _match_db = MatchDB(given)
        except Exception as e:  # noqa: BLE001
            _log.warning("MatchDB init failed: %s", e)
            return None
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
    except Exception as exc:  # noqa: BLE001
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
    # _num, not a bare .get: a present-but-null game_seconds used to raise
    # TypeError comparing None >= 180 on the FIRST line of save_rating.
    return _num(gs.get("game_seconds", 0)) >= 180

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
    elif d10<=1.8:sc+=12;n.append(f"{d} deaths - review avoidable ones")
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
    elif kda>=2:sc+=18;n.append(f"KDA ({kda:.1f}) - pick fights carefully")
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
_TFT_LABEL={1:"1ST PLACE - dominant lobby",2:"TOP 2 - strong board",3:"TOP 3 - solid comp",4:"TOP 4 - positive LP",5:"5TH - missed top 4",6:"6TH - board fell off",7:"7TH - major gaps",8:"8TH - full rebuild"}
_TFT_LABEL_DUO={1:"1ST - won the lobby",2:"2ND - strong run",3:"3RD - board fell off",4:"4TH - eliminated early"}

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
            except Exception: count = 1  # noqa: BLE001
            parsed.append((name, count))
        parsed.sort(key=lambda x: -x[1])
        top = [f"{n} {c}" for n, c in parsed if c > 1][:3]
        if not top: top = [f"{n}" for n, c in parsed[:2]]
        if top: return " / ".join(top)
    if units: return " + ".join([u for u in units if u and u != "unknown"][:3])
    return ""
_STAR_SUFFIX = re.compile(r"\s+\d+\s*-?\s*star$", re.IGNORECASE)
def _core_units(units):
    # The star suffix only: "Mama Beak 1-star" -> "Mama Beak" (a bare split on
    # the first space cut a two-word unit name to its first word).
    return [_STAR_SUFFIX.sub("", u) for u in (units or [])
            if isinstance(u, str) and u and u != "unknown"][:3]

def calculate_tft_rating(placement,stage=0,level=0,game_mins=0.0,traits=None,units=None,augments=None,is_duo=False):
    mx=4 if is_duo else 8
    if placement<1 or placement>mx: return ("", [])
    gm=(_TFT_GRADE_DUO if is_duo else _TFT_GRADE).get(placement,"C");n=[];comp=_identify_comp(traits or [],units or []);core=_core_units(units or [])
    tag=" (Double Up)" if is_duo else ""
    if placement==1:n.append(f"1st place{tag} - dominant")
    elif placement<=2:n.append(f"Top {placement}{tag} - close to winning")
    elif placement<=4 and is_duo:n.append(f"#{placement}{tag} - review board + partner sync")
    elif placement<=4:n.append("Top 4 - LP positive")
    elif placement<=6:n.append(f"#{placement} - review rolldown timing")
    else:n.append(f"#{placement} - early board needs work")
    if core:n.append(f"Core units: {', '.join(core)}")
    if 0<stage<=4:n.append(f"Eliminated Stage {stage} - stabilize earlier")
    return gm,n[:4]

def _tft_game_id() -> int:
    """RM-889 (4): the finished TFT game's Riot gameId, or 0 = unknown (the
    matches.game_id schema DEFAULT, the same "no id" value save_rating writes).

    The legacy-path fallback since s134 N8 (the game's own record names its id
    when one exists): neither TFT data file the frozen caller hands over
    carries an id; the standalone client's per-round TFTEoGStats.json does, and
    read_eog returns it only while FRESH (EOG_MAX_AGE_S) and a TFT game, so a
    file older than that window reads as unknown (a game lasts far longer, so a
    fresh file is this game's). Never raises, and never returns a value the
    INTEGER column rejects: the id is metadata, never worth the row."""
    try:
        from tft import tft_standalone as _tsa
        eog = _tsa.read_eog()
        # ASCII digits only: int() alone takes True, 1.5, "-5", "1_000" and
        # full-width digits, none of which is a game id.
        s = str(eog.get("gameId") if isinstance(eog, dict) else "").strip()
        gid = int(s) if s.isascii() and s.isdigit() else 0
    # Broad on purpose: ImportError is the known type, and a reader fault
    # (e.g. RecursionError from a hostile JSON nest) must still cost only the
    # id, never the row.
    except Exception as e:  # noqa: BLE001
        _log.debug("TFT game id unavailable: %s", e)
        return 0
    # SQLite INTEGER is signed 64-bit: a larger id raised OverflowError inside
    # save_match and lost the whole row (S134 verifier).
    return gid if 0 < gid < 2**63 else 0


_TFT_DUO_VARIANTS = ("double_up", "TFT_DOUBLE_UP", "TFT_PAIRS")
# A legacy-path rating (vision feed / coaching file) has no end time of its
# own; it is the game that just ended.
_TFT_SOURCE_VISION = "vision_last_round"
_TFT_SOURCE_ALIVE = "coaching_alive_others"


def _tft_final(script_dir, game_id=None, store_only=False):
    """s134 N8: the ended game's real record (tft/tft_final_board.py) - the
    RM-616 store first, the standalone client's finished per-round file
    second - or None. Never raises: the legacy inputs still rate."""
    try:
        from tft import tft_final_board as _fb
        if store_only:
            return _fb.store_final(game_id, root=Path(script_dir))
        return _fb.resolve_final(Path(script_dir), game_id=game_id)
    except Exception as e:  # noqa: BLE001
        _log.warning("TFT final-board read failed: %s", e)
        return None


def _tft_input_game_id(tft_live, tft_coaching):
    for src in (tft_live, tft_coaching):
        gid = _num((src or {}).get("game_id"), 0)
        if isinstance(gid, (int, float)) and gid > 0:
            return int(gid)
    return None


def _legacy_tft_placement(tft_live, tft_coaching, is_duo):
    """(placement, source) from the pre-N8 inputs, (0, "") when they hold none.

    N8 root cause: ``alive_others`` used to default to 7 when the coaching
    file did not carry it - and the declared blank it is reset to at TFT game
    end never does - so every unknown placement became 8th / F. It now counts
    only when the file carries it AND it can be a result: the local player is
    out (health 0 / is_dead) or nobody else is alive. A live player with others
    alive is a mid-game snapshot, not a placement."""
    placement = _parse_tft_placement((tft_live or {}).get("last_round_result", "") or "")
    if placement >= 1:
        return placement, _TFT_SOURCE_VISION
    tc = tft_coaching or {}
    # _num: a null alive_others / health is "absent" (lane 8 cycle 23).
    alive = _num(tc.get("alive_others"), None)
    if alive is None or alive < 0:
        return 0, ""
    hp = _num(tc.get("health"), None)
    if tc.get("is_dead") is not True and hp is not None and hp > 0 and alive > 0:
        return 0, ""
    alive = int(alive)
    placement = max(1, (alive + 1) // 2) if is_duo else max(1, alive + 1)
    return placement, _TFT_SOURCE_ALIVE


def _planner_target(script_dir):
    """RM-889: the selected comp's TARGET board, under its own key
    (``tft_comp_target``), or None. It used to OVERWRITE the measured units /
    traits / augments (and back-fill an empty reading), so the rating file and
    the match_history.db row recorded the guide, not the game. Only when the
    resolved set's meta defines the selected comp (the _planner_comp rule);
    only on the legacy game-end path, never on a re-rate of a stored game."""
    try:
        _sd = Path(script_dir)
        _cs = json.loads((_sd / "data" / "comp_state.json").read_text(encoding="utf-8"))
        _sel = _cs.get("selected", "") if isinstance(_cs, dict) else ""
        if not _sel or not isinstance(_sel, str):
            return None
        from tft import tft_set as _ts
        _meta_f = _ts.meta_path(root=_sd)
        if not _meta_f.exists():
            _meta_f = _ts.meta_path(pbe=True, root=_sd)
        if not _meta_f.exists():
            return None
        _meta = json.loads(_meta_f.read_text(encoding="utf-8-sig"))
        comps = _meta.get("comps") if isinstance(_meta, dict) else None
        _cd = comps.get(_sel) if isinstance(comps, dict) else None
        if not isinstance(_cd, dict) or not _cd:
            return None
        return {
            "units": list(_cd.get("lv8") or _cd.get("lv7") or _cd.get("core_units") or []),
            "traits": [_sel] + [f"{e} Emblem" for e in (_cd.get("emblem_value") or [])[:2]],
            "augments": list(_cd.get("augments_best") or [])[:3],
        }
    except Exception as _e:  # QUAL-002  # noqa: BLE001 - best-effort label
        _log.debug("TFT planner target: %s", _e)
        return None


def _planner_comp(script_dir):
    """The overlay comp planner's selection (data/comp_state.json), ONLY when
    the resolved set's meta defines that comp. N8: the live file held a Set 17
    comp ("Dark Star Vertical", 2026-09-03) that the Set 18 meta does not have,
    and it named a Set 18 game. The selection is a plan, not the board, so it
    never replaces observed units / traits / augments."""
    try:
        _sd = Path(script_dir)
        _cs = json.loads((_sd / "data" / "comp_state.json").read_text(encoding="utf-8"))
        _sel = _cs.get("selected", "") if isinstance(_cs, dict) else ""
        if not _sel or not isinstance(_sel, str):
            return ""
        # RM-840: the resolved set's meta (tft/tft_set.py), its PBE twin
        # second - never a hard-wired tft_set17_*.json.
        from tft import tft_set as _ts
        _meta_f = _ts.meta_path(root=_sd)
        if not _meta_f.exists():
            _meta_f = _ts.meta_path(pbe=True, root=_sd)
        if not _meta_f.exists():
            return ""
        _meta = json.loads(_meta_f.read_text(encoding="utf-8-sig"))
        comps = _meta.get("comps") if isinstance(_meta, dict) else None
        return _sel if isinstance(comps, dict) and comps.get(_sel) else ""
    except Exception as _e:  # QUAL-002  # noqa: BLE001 - best-effort label
        _log.debug("TFT planner comp: %s", _e)
        return ""


def _tft_rating_record(script_dir, final, tft_live, tft_coaching, variant):
    """Build (grade, notes, data, row) for one TFT game, or None.

    ``final`` (tft/tft_final_board.final_from_record) wins outright when
    present: placement, board, traits, level, stage and length all come from
    the game's own record. Otherwise the legacy live / coaching inputs."""
    tft_live = tft_live or {}
    tc = tft_coaching or {}
    is_duo = variant in _TFT_DUO_VARIANTS
    if final:
        is_duo = is_duo or bool(final.get("is_duo"))
        placement = final["placement"]
        if is_duo and placement > 4 and placement == final.get("lobby_placement"):
            placement = (placement + 1) // 2
        source = final.get("source") or ""
        sn = int(final.get("stage") or 0)
        lv = int(final.get("level") or 0)
        gs = final.get("game_length_s") or 0
        traits = list(final.get("traits") or [])
        units = list(final.get("units") or [])
        augments = list(final.get("augments") or [])
        comp = final.get("comp") or _identify_comp(traits, units)
        game_id = int(final.get("game_id") or 0)
        extra = {"tft_game_id": game_id, "tft_set": final.get("set_number") or 0,
                 "tft_hp": final.get("hp"), "tft_board": final.get("board") or [],
                 "tft_placement_source": source,
                 "tft_lobby_placement": final.get("lobby_placement")}
        ended = final.get("ended_at_unix")
        raw_placement = ""
    else:
        placement, source = _legacy_tft_placement(tft_live, tc, is_duo)
        if placement < 1:
            return None
        ss = tft_live.get("stage_round", ""); sn = 0
        if ss:
            # Narrowed 2026-07-19: the only raising statement is int(); it raises
            # ValueError on a non-numeric stage prefix. TypeError covers a
            # stage_round whose str()/split shape is not a plain string.
            try: sn = int(str(ss).split("-")[0])
            except (TypeError, ValueError) as _e: _log.debug("TFT stage parse: %s", _e)  # QUAL-002
        # _num on the feed-supplied stage: a null used to crash the `0<stage<=4`
        # compare in calculate_tft_rating (lane 8 cycle 23).
        if not sn: sn = _num(tc.get("stage", 0))
        lv = tft_live.get("level") or tc.get("level", 0) or 0
        gs = tc.get("game_time_s", 0) or 0
        traits = tft_live.get("traits_active", []) or []
        units = tft_live.get("board_units", []) or []
        augments = tft_live.get("augments", []) or []
        comp = ((_planner_comp(script_dir) if not (traits or units) else "")
                or _identify_comp(traits, units))
        game_id = _tft_input_game_id(tft_live, tc) or _tft_game_id()
        extra = {"tft_game_id": game_id, "tft_placement_source": source}
        target = _planner_target(script_dir)
        if target:
            extra["tft_comp_target"] = target
        ended = None
        raw_placement = tft_live.get("unit_placement", "") or ""
    mx = 4 if is_duo else 8
    if placement < 1 or placement > mx:
        return None
    gm = max(0, gs / 60) if gs else 0
    core = _core_units(units)
    grade, notes = calculate_tft_rating(placement, sn, lv, gm, traits, units, augments, is_duo=is_duo)
    if not grade:
        return None
    lmap = _TFT_LABEL_DUO if is_duo else _TFT_LABEL
    try:
        from tft.placement_aggregator import parse_unit_placement as _pup
        _unit_positions = _pup(raw_placement)
    except Exception:  # noqa: BLE001
        _unit_positions = {}
    data = {"rating": grade, "label": lmap.get(placement, ""), "champion": comp or f"TFT #{placement}",
            "game_mode": "TFT_DOUBLE_UP" if is_duo else "TFT", "mode_category": "TFT",
            "game_time": f"{int(gm)}:{int(gs % 60):02d}" if gs else "?",
            "stats": {"kda": f"#{placement}", "cs_per_min": f"Lv{lv}" if lv else "Lv?",
                      "gold_per_min": f"Stage {sn}" if sn else "?"},
            "notes": notes, "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "tft_placement": placement, "tft_stage": sn, "tft_level": lv,
            "tft_comp": comp, "tft_traits": traits, "tft_units": units, "tft_augments": augments,
            "tft_core_units": core,
            "tft_unit_positions": _unit_positions, "tft_unit_placement": raw_placement}
    data.update(extra)
    data["tft_ended_at_unix"] = float(ended) if ended else time.time()
    items = [i for u in (extra.get("tft_board") or []) for i in (u.get("items") or [])]
    row = {"mode": "TFT", "champion": comp, "grade": grade, "game_time_s": gs,
           "tft_placement": placement, "tft_stage": sn, "tft_level": lv, "tft_comp": comp,
           "tft_traits": traits, "tft_units": units, "tft_augments": augments,
           "tft_items": items, "notes": notes, "label": lmap.get(placement, ""),
           "game_id": game_id,
           "raw_data": json.dumps({"game_mode": data["game_mode"], "placement_source": source,
                                   "set": extra.get("tft_set"), "hp": extra.get("tft_hp"),
                                   "lobby_placement": extra.get("tft_lobby_placement"),
                                   "board": extra.get("tft_board") or []}, default=str)}
    _log.info("TFT rating: placement=%d is_duo=%s source=%s game=%s variant=%s grade=%s",
              placement, is_duo, source or "-", game_id or "-", variant, grade)
    return grade, notes, data, row


def _tft_db_write(script_dir, row) -> None:
    db = _get_db(script_dir)
    if not db:
        return
    try:
        # One row per game: a known game id updates the row an earlier rating
        # of the same game wrote (game end, then the store record landing).
        if row.get("game_id"):
            db.upsert_by_game_id(row)
        else:
            db.save_match(row)
    except Exception as e:  # noqa: BLE001
        _log.warning("TFT DB save failed: %s", e)


def _tft_heatmap() -> None:
    try:
        from tft.placement_aggregator import update_heatmap as _uh
        _uh()
    # LEFT BROAD 2026-07-19: update_heatmap -> build_heatmap
    # (tft/placement_aggregator.py:45) re-walks and re-parses the whole ratings
    # dir, so the reachable set is at least ImportError / OSError / KeyError /
    # TypeError / ValueError and is not closed by inspection. Could not rule out
    # further types from build_heatmap's own callees, so the handler stays broad.
    # Level lifted debug -> warning: the two sibling save failures (the rating
    # write and the DB write) both log at warning, so a silently-dead heatmap
    # was the only invisible failure here.
    except Exception as _e:  # noqa: BLE001
        _log.warning("Heatmap update: %s", _e)


def save_tft_rating(script_dir,tft_live,tft_coaching=None,report=None,game_id=None):
    """Rate the TFT game that just ended (the lifecycle game-end trigger).

    s134 N8: placement / board / traits / comp come from the game's own record
    (``_tft_final``) whenever one exists; the vision / coaching inputs are the
    fallback, and with no placement source at all NOTHING is written (it used
    to write a fabricated 8th / F). ``game_id`` is optional: the standalone
    client's per-round file names the game otherwise."""
    _report_set(report, False, False)
    tft_live = tft_live if isinstance(tft_live, dict) else {}
    tc = tft_coaching if isinstance(tft_coaching, dict) else {}
    variant = tc.get("variant", "standard") or "standard"
    final = _tft_final(script_dir, game_id or _tft_input_game_id(tft_live, tc))
    if final is None and not tft_live:
        return ("", [])
    built = _tft_rating_record(script_dir, final, tft_live, tc, variant)
    if built is None:
        _log.info("TFT rating skipped: no placement source (store, per-round file, "
                  "vision, coaching) holds this game's result")
        return ("", [])
    grade, notes, data, row = built
    _written = False
    try:
        _atomic_write_json(_mode_file(script_dir, "TFT"), data)
        _written = True
    except Exception as _e:  # noqa: BLE001
        _log.warning("TFT rating save failed: %s", _e)  # QUAL-002
    _report_set(report, True, _written)
    _tft_db_write(script_dir, row)
    _tft_heatmap()
    return grade, notes


def _tft_file_end(cur: dict):
    """End time of the game a last_tft.json describes: its own stamp, else
    the minute-resolution local timestamp of a pre-N8 file, else None."""
    v = cur.get("tft_ended_at_unix")
    if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
        return float(v), 0.0
    ts = cur.get("timestamp")
    if isinstance(ts, str):
        try:
            return datetime.strptime(ts, "%Y-%m-%d %H:%M").timestamp(), 120.0
        except ValueError:
            return None
    return None


def _tft_is_newest(script_dir, game_id, ended) -> bool:
    """May the rating of ``game_id`` (ended at ``ended``) replace last_tft.json?
    Yes for the same game, a missing / unreadable file, or a game that ended
    no earlier than the file's (a pre-N8 file's minute stamp gets 120 s)."""
    try:
        cur = json.loads(_mode_file(script_dir, "TFT").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    if not isinstance(cur, dict):
        return True
    if _num(cur.get("tft_game_id"), 0) == game_id:
        return True
    fe = _tft_file_end(cur)
    if fe is None:
        return True
    if not ended:
        return False
    return float(ended) >= fe[0] - fe[1]


def plan_tft_rating(script_dir, game_id, store_dir=None):
    """The rating rate_tft_game would write for ``game_id``, WITHOUT writing:
    {"game_id", "grade", "notes", "data" (last_tft.json body), "row" (the
    match_history.db row), "ended", "newest" (may it replace last_tft.json)},
    or None when the store has no usable record. Reads only (the N8 backfill's
    dry run plans with it)."""
    try:
        gid = int(game_id)
    except (TypeError, ValueError):
        return None
    if gid <= 0:
        return None
    if store_dir is None:
        final = _tft_final(script_dir, gid, store_only=True)
    else:
        try:
            from tft import tft_final_board as _fb
            final = _fb.store_final(gid, root=Path(script_dir), store_dir=store_dir)
        except Exception as e:  # noqa: BLE001
            _log.warning("TFT store read for game %s failed: %s", gid, e)
            final = None
    if not final:
        return None
    built = _tft_rating_record(script_dir, final, {}, {}, "standard")
    if built is None:
        return None
    grade, notes, data, row = built
    ended = final.get("ended_at_unix")
    if ended:
        data["timestamp"] = datetime.fromtimestamp(ended).strftime("%Y-%m-%d %H:%M")
        row["timestamp"] = datetime.fromtimestamp(ended).strftime("%Y-%m-%d %H:%M:%S")
    return {"game_id": gid, "grade": grade, "notes": notes, "data": data, "row": row,
            "ended": ended, "newest": _tft_is_newest(script_dir, gid, ended)}


def rate_tft_game(script_dir, game_id, store_dir=None):
    """(Re)rate one TFT game from its RM-616 store record - called when the
    record lands (lcu/lcu_postgame_collector.py), and by the N8 backfill.

    The EOG capture can land after the lifecycle game-end rating (match 3:
    09:29:44 vs 09:28:52) and the match-history record later still, so this
    is where the rating catches up: the game's match_history.db row is updated
    in place (matched on game_id; inserted when the game had none, stamped
    with the game's end), and last_tft.json is rewritten only when this is the
    newest rated game. Returns (grade, notes); ("", []) when the store has no
    usable record."""
    plan = plan_tft_rating(script_dir, game_id, store_dir=store_dir)
    if plan is None:
        return ("", [])
    gid = plan["game_id"]
    if plan["newest"]:
        try:
            _atomic_write_json(_mode_file(script_dir, "TFT"), plan["data"])
        except Exception as _e:  # noqa: BLE001
            _log.warning("TFT rating save failed (game %s): %s", gid, _e)
    else:
        _log.info("TFT rating for game %s: last_tft.json holds a newer game - kept", gid)
    _tft_db_write(script_dir, plan["row"])
    _tft_heatmap()
    return plan["grade"], plan["notes"]


def _report_set(report, rated, written):
    """RM-259: fill the caller's optional out-of-band outcome dict. The
    return value cannot carry it - app/_game_lifecycle.py unpacks
    ``g, n = save_rating(...)`` - so a caller that needs to know whether
    the rating FILE was actually written passes ``report={}``."""
    if isinstance(report, dict):
        report["rated"] = bool(rated)
        report["file_written"] = bool(written)


def save_rating(script_dir,champion,game_state,ally_kills_total,report=None):
    _report_set(report, False, False)
    if not is_valid_match(game_state): return ("", [])
    # Every numeric read goes through _num: the upstream feed supplies these
    # and a present-but-null field used to crash the whole save (six measured
    # fields), which the frozen caller then swallowed - see _num's docstring.
    game_secs=_num(game_state.get("game_seconds",0));game_mins=max(1.0,game_secs/60)
    gpm=round(_num(game_state.get("gold",0))/game_mins);raw_mode=game_state.get("game_mode","CLASSIC")
    category=mode_category(raw_mode)
    if not category: return ("", [])
    # S134 N3: this is the LEAGUE rating (CS / KDA / KP). A TFT game used to
    # fall through to calculate_rating and overwrite last_tft.json with an SR
    # grade; TFT is rated only by save_tft_rating.
    if category=="TFT":
        _log.info("save_rating: TFT game - League rating skipped (save_tft_rating owns TFT)")
        return ("", [])
    stats={"cs_per_min":_num(game_state.get("cs_per_min",0)),"deaths":_num(game_state.get("deaths",0)),"kills":_num(game_state.get("kills",0)),"assists":_num(game_state.get("assists",0)),"game_mins":game_mins,"ally_kills_total":_num(ally_kills_total,1),"gold_per_min":gpm}
    if category=="ARAM":grade,notes=calculate_aram_rating(stats)
    elif category=="ARENA":grade,notes=calculate_arena_rating(stats)
    elif category=="BRAWL":grade,notes=calculate_brawl_rating(stats)
    else:grade,notes=calculate_rating(stats)
    # stats["ally_kills_total"], not the raw arg: max(1, None) raises.
    kda_str=game_state.get("kda") or "0/0/0";kp=round((stats["kills"]+stats["assists"])/max(1,stats["ally_kills_total"])*100)
    data={"rating":grade,"label":GRADE_LABEL.get(grade,""),"champion":champion,"game_mode":raw_mode,"mode_category":category,"game_time":game_state.get("game_time","0:00"),
        "stats":{"cs_per_min":round(stats["cs_per_min"],1),"kda":kda_str,"deaths":stats["deaths"],"kill_participation":kp,"gold_per_min":gpm},
        "notes":notes,"timestamp":datetime.now().strftime("%Y-%m-%d %H:%M")}
    _written = False
    try:
        _atomic_write_json(_mode_file(script_dir, category), data)
        _written = True
    except Exception as _e:  # noqa: BLE001
        _log.warning("Rating save failed (%s): %s", category, _e)  # QUAL-002
    _report_set(report, True, _written)
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
        except Exception as e:_log.warning("Match DB save failed: %s",e)  # noqa: BLE001
    # 2026-04-25: adaptation feedback loop. Translate the user's grade
    # (S/A/B/C/D/F) into a confidence multiplier on the cache entry for
    # this game's final state. Future similar states get advice weighted
    # by past success. Non-fatal - the rating save proceeds regardless.
    try:
        from coaches.feedback import apply_grade
        apply_grade(grade, game_state)
    except Exception as _fe:  # noqa: BLE001
        _log.debug("feedback.apply_grade failed: %s", _fe)
    # 2026-04-26: experimental-build adaptation hook. If the user opted
    # into the experimental variant for this match, archive the result
    # against the current iteration and (on poor grades) auto-generate
    # the next iteration. Marker is consumed regardless of category.
    # api_key is hoisted OUT of the inner block so the handler below can
    # redact it. It stays "" on every path that never reads the file.
    api_key = ""
    try:
        from coaches import experimental_builder as _eb
        marker = _eb.consume_active()
        if marker and marker.get("champion") == champion:
            try:
                # RM-487 (2026-10-03): this read API-Key-Claude.txt and
                # NOTHING else - the file-only shape ba4bb74be fixed in
                # dashboard/routes_coach.py - so with the key living only in
                # ANTHROPIC_API_KEY it handed "" to record_result. The shared
                # reader gives env first, file fallback, and swallows its own
                # OSError / UnicodeDecodeError. Pinned by
                # tests/test_api_key_load_order.py.
                from coaches._base_coach import read_api_key
                api_key = read_api_key(Path(script_dir))
            # Path() raises TypeError on a non-path script_dir and ValueError
            # on a NUL in it (lane 8 cycle 23); OSError kept for an exists()
            # that cannot stat the directory.
            except (OSError, TypeError, ValueError): pass
            gs_for_record = {
                "kda":         kda_str,
                "kp_pct":      kp,
                "gold_per_min": gpm,
                "notes":        notes,
            }
            _eb.record_result(champion, grade, gs_for_record, api_key)
    except Exception as _ee:  # noqa: BLE001
        # _redact, not a bare %s: this handler logs an exception raised by a
        # callee that was just handed the API key, and CLAUDE.md forbids the
        # key reaching any log line.
        #
        # HONEST SCOPE - this is defense in depth, not a live leak fix. Lane 8
        # cycle 23 measured the current path CLEAN for two independent
        # reasons: experimental_builder._call_haiku catches everything at
        # :236 so no anthropic exception escapes record_result, and the SDK's
        # own exception surfaces carry no credential under %s formatting.
        # It is guarded anyway because the margin is one formatting change
        # wide - repr() of the UnicodeEncodeError raised by a non-ASCII key
        # file DOES embed the key, so switching this line to %r or to
        # log.exception would have leaked it. The guard removes the handler's
        # dependence on what the callee happens to raise.
        _log.debug("experimental.record_result failed: %s",
                   _redact(str(_ee), api_key))
    return grade, notes

def load_rating(sd,category=""):
    try:
        p = _mode_file(sd, category) if category else _latest_rating_file(sd)
        if p and p.exists(): return json.loads(p.read_text(encoding="utf-8"))
    # Narrowed 2026-07-19: _ratings_dir().mkdir, Path.exists and read_text all
    # raise OSError; read_text can raise UnicodeDecodeError and json.loads
    # JSONDecodeError, both ValueError subclasses; Path(sd) raises TypeError on
    # a non-path sd. _latest_rating_file already swallows its own OSError
    # (:131). Those are every raising statement in the try.
    except (OSError, TypeError, ValueError) as _e: _log.debug("load_rating %s: %s", category or 'default', _e)  # QUAL-002
    return None
def load_all_ratings(sd):
    r={}
    for cat in ("SR","ARAM","ARENA","BRAWL","TFT"):
        d=load_rating(sd,cat)
        if d:r[cat]=d
    return r
