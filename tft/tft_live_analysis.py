"""
tft/tft_live_analysis.py - Vision-based comp coaching with smart round-phase timing.
Scans at planning phase (~1.5s after round start) and mid-round (~12s).
Skips combat. Force scan via right-click overrides all timing.
"""
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Optional

from core.polled_json import atomic_write_json
# RM-364: this module already runs a name-plausibility layer (_is_valid_unit,
# _clean_units, _as_name_list) that augment DESCRIPTIONS and items_equipped
# bypass entirely, so it needs a TARGETED patch and not a wrap. Applied at
# prompt assembly: moon_proxy.get_coaching is the PRIMARY egress here and
# messages.create only the fallback, so a guard at the SDK call would be
# dead code on the live path.
from core.prompt_sanitize import clean as _psan_clean

logger = logging.getLogger("rc.tft.live")

# LANE 8 CYCLE 43. The panel must never show a raw upstream error string
# (CLAUDE.md "Error Handling"), and it must not COLLAPSE either
# (feedback_no_reflow_on_data_absence) - so a failed cycle republishes the
# last known advice with a degraded marker beside it, and the raw error goes
# to logs/ only.
_DEGRADED_TEXT = "coaching paused - retrying"

# RM-302. Per-request bound for the two LOCAL-FALLBACK model calls below.
# Both are direct calls to api.anthropic.com, and the SDK default read
# timeout is 600 s (anthropic 0.96.0, DEFAULT_TIMEOUT read=600) inside a loop
# that ticks every 1.5 s. _run_cycle drops ticks rather than queueing them
# (`self._lock.acquire(blocking=False)`), so the symptom of an unbounded call
# is SILENCE, not a thread storm - and the cycle-43 degraded marker cannot
# help, because a call that never returns never raises into the handler.
# The primary path needs no bound of its own: core/moon_proxy.py TIMEOUT_S=8.
#
# 20.0 is DERIVED, not guessed, and deliberately not moon_proxy's 8 s - that
# figure bounds a LAN hop to a local relay, this is a WAN call with a
# 500-token completion. The `Live analysis in %dms` line has never once been
# emitted on this box (0 hits across 46 days of logs/, because moon_proxy
# answers first and this fallback stays cold), so the nearest MEASURED
# population stood in: the 200 records in data/coach_trace.jsonl, which are
# direct `messages.create` calls on this same model id from this same host,
# wall-clock bracketed by coaches/_base_coach.py `_record_coach_call`.
#   n=200  p50 5972 ms  p90 7048 ms  p95 7610 ms  p99 10947 ms  max 26000 ms
# 20 s is 1.8x that p99 and clears 199 of the 200, so a healthy call is not
# truncated into a false degraded panel, while worst-case silence falls from
# 600 s to 20 s per attempt.
#
# CAVEAT before anyone tunes this: the SDK RETRIES a timeout, so the true
# wall-clock ceiling is _MODEL_TIMEOUT_S x (max_retries + 1), i.e. 60 s at
# the SDK default of 2. Bounding that means passing max_retries where the
# client is constructed, which is a different row.
_MODEL_TIMEOUT_S = 20.0

_SECRET_RE = re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}")


def _safe_err(exc: object) -> str:
    """Format an upstream exception for a log line with secrets removed.

    The key reaches this module from API-Key-Claude.txt
    (coaches/tft_pbe_coach.py _read_api_key -> core/tft_worker.py) and is
    handed to the SDK, so any upstream that echoes a credential into its
    error text would land it in logs/YYYY-MM-DD.log verbatim. No upstream is
    known to do that today; this is the defence-in-depth half, and it costs
    one regex.
    """
    return _SECRET_RE.sub("sk-ant-<redacted>", str(exc))


def _first_text(resp: object) -> Optional[str]:
    """The first TEXT block of a model response, or None.

    `resp.content[0].text` assumed both that a block exists and that the
    first one is text.

    The LIVE half is the empty content list: a response can stop with no
    block at all, and `content[0]` then raises IndexError into the blanket
    handler, which logged at ERROR and published nothing.

    The non-text half is DEFENCE, not a live defect, and the distinction was
    forced by the refutation pass: neither `messages.create` call in this
    module passes a `thinking` parameter, so the SDK cannot emit a thinking
    block at these sites today. Kept because the same shape WAS live at the
    :8889 inference boundary (lane 8 cycle 20) and costs nothing here.
    """
    blocks = getattr(resp, "content", None) or []
    for b in blocks:
        if getattr(b, "type", None) == "text":
            t = getattr(b, "text", None)
            if isinstance(t, str) and t.strip():
                return t
    for b in blocks:
        t = getattr(b, "text", None)
        if isinstance(t, str) and t.strip():
            return t
    return None


def _psan_items_equipped(mapping: object) -> dict:
    """RM-364: sanitise the keys and leaf strings of `items_equipped` before
    it is json.dumps'd into the analysis prompt.

    MEASURED NUANCE, recorded so this is not later called redundant:
    `json.dumps` is a PARTIAL defense here. It already escapes a newline into
    a literal backslash-n, so the section-delimiter vector was closed - but it
    passes an instruction-override phrase through verbatim, and these values
    are vision-model output. This closes the half json does not.

    Returns a plain dict; a non-mapping input becomes {} so the caller's
    `or {}` contract is preserved.
    """
    if not isinstance(mapping, dict):
        return {}
    out = {}
    for k, v in mapping.items():
        key = _psan_clean(k, max_len=64)
        if isinstance(v, list):
            out[key] = [_psan_clean(x, max_len=64) for x in v]
        elif isinstance(v, dict):
            out[key] = _psan_items_equipped(v)
        else:
            out[key] = _psan_clean(v, max_len=64)
    return out


def _as_name_list(value: object) -> list:
    """Coerce an operator-authored JSON field to a list of clean strings.

    unit_presence.json is written by another surface and is not schema
    checked. A non-string entry used to reach `", ".join(...)`, which sits
    outside every handler in _run_analysis, so a TypeError escaped into
    _loop's blanket handler and killed EVERY scan while the bad file
    remained on disk.
    """
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    out = []
    for v in value:
        if v is None or isinstance(v, (dict, list, tuple)):
            continue
        s = str(v).strip()
        if s:
            out.append(s)
    return out
_TFT_CHAMPIONS = {
    # Set 17: Space Gods - confirmed from CommunityDragon PBE
    "Aatrox","Akali","Aurelion Sol","Aurora","Bard","Bel'Veth","Blitzcrank",
    "Briar","Caitlyn","Cho'Gath","Corki","Diana","Ezreal","Fiora","Fizz",
    "Gnar","Gragas","Graves","Gwen","Illaoi","Jax","Jhin","Jinx",
    "Kai'Sa","Karma","Kindred","LeBlanc","Leona","Lissandra","Lulu",
    "Maokai","Master Yi","Meepsie","Milio","Miss Fortune","Mordekaiser",
    "Morgana","Nami","Nasus","Nunu & Willump","Nunu","Ornn","Pantheon",
    "Poppy","Pyke","Rammus","Rek'Sai","Rhaast","Riven","Samira","Shen",
    "Sona","Tahm Kench","Talon","Teemo","The Mighty Mech","Twisted Fate",
    "Urgot","Veigar","Vex","Viktor","Xayah","Zed","Zoe",
    # Common display name variants
    "KaiSa","MissFortune","TahmKench","MasterYi","TwistedFate",
    "AurelionSol","TheMightyMech","BelVeth","NunuWillump",
    # Older set champions that may appear in ARAM/revival modes
    "Ashe","Braum","Anivia","Volibear","Sejuani","Udyr","Tryndamere",
    "Rumble","Ziggs","Smolder","Shyvana","Swain","Neeko",
    "Janna","Rakan","Annie","Katarina","Draven","Twitch","Kennen",
    "Sett","Ahri","Kayn","Nocturne","Xerath","Brand","Evelynn",
    "Nidalee","Shaco","Wukong","Jarvan IV","Rengar","Lucian","Taliyah","Qiyana","Kassadin","Malzahar","Yuumi",
    "Trundle","Dr. Mundo","Warwick","Silco","Sevika","Mel","Ambessa",
    "Heimerdinger","Jayce","Vi","Ekko","Powder",
    "Camille","Lux","Syndra","Soraka","Tristana","Zeri",
    "Sivir","Kog'Maw","Vayne","Aphelios","Orianna","Ryze","Vladimir",
    "Cassiopeia","Zyra","Vel'Koz","Seraphine","Zilean","Azir",
    "Renekton","Olaf","Sylas","Darius","Sion","Irelia",
    "Yone","Yasuo","Lee Sin","Galio","Malphite","Garen","Taric",
}
_TFT_CHAMP_LOWER={c.lower() for c in _TFT_CHAMPIONS}
_FAKE_AUGMENT_RE=re.compile(r'^augment\d*$',re.IGNORECASE)
_NOT_UNIT_LABELS={
    "reroll","buy xp","sell","level up","refresh","skip","lock","buy","xp","levelup",
    "longshot","quickstriker","vanquisher","disruptor","slayer","defender","demacia",
    "shurima","emperor","arcanist","freljord","vanguard","challenger","juggernaut",
    "invoker","bastion","brawler","commander","psionic","gunslinger","sniper",
    "anima","arbiter","dark","star","meeple","mecha","nova","primordian","stargazer",
    "space","groove","shepherd","voyager","replicator","conduit","fateweaver",
    "marauder","rogue","factory","timebreaker","astronaut","warden","darkin","dragonborn","blacksmith",
    "noxus","piltover","zaun","targon","bilgewater","void","shadow","isles","ixtal","ionia",
    # Set 16 traits that slip through from stale OCR reads
    "chemtech","enforcer","hextech","innovator","transformer","socialite","syndicate",
    "mercenary","scholar","scrap","bruiser","colossus","mutant","yordle","yordle-tech",
    # Set 17 trait names that OCR misreads as unit names
    "forgefire","n.o.v.a","eternal","harvester",
    "chronokeeper","automata","conqueror","divinity","celestial","divine","radiant",
    "contract","killer","god","boon","prismatic","silver","gold","stellar",
    # Generic trait/descriptor words not valid as unit names
    "2-star","3-star","1-star","tier","cost","unit","champion","unknown",
    "empty","front","back","mid","row","col","tank","carry","support","dps",
    "trait","origin","class","active","inactive","breakpoint",
}
_NOT_AUGMENTS={"buy xp","reroll","sell","level up","refresh","skip","lock","bruiser","defense","attack"}
def _is_valid_unit(name):
    if not name or name=="empty": return False
    b=name.split()[0].lower()
    if b in _NOT_UNIT_LABELS: return False
    if len(b)>1 and b[0]=='x' and b[1].isupper(): return False
    return len(b)>=2 and not (b.isupper() and len(b)>4)

# NOT a cache_control candidate (item 286): static portion ~669 tok < the
# 2048-tok Haiku cache floor AND the primary path is the FROZEN single-string
# core.moon_proxy.get_coaching(), so a system/user split is unreachable here.
# Guard: tests/test_prompt_cache_floor_item286.py.
_ANALYSIS_PROMPT_TEMPLATE = """\
You are a Challenger TFT coach giving real-time advice.
IMPORTANT: Only analyse YOUR board (bench/shop visible at bottom). If spectating, output "SPECTATING" in Comp.

=== CURRENT GAME STATE ===
Stage/Round: {stage_round}
Level: {level}  HP: {hp}  Gold: {gold}
Board units: {board}
Bench units: {bench}
Shop units: {shop}
Items equipped: {items_equipped}
Items on bench: {items_bench}
Active traits: {traits}
Active augments: {augments}
{loss_context}
{augment_context}

COMP IDENTIFICATION: Name after TOP 2-3 traits by count. Traits list is ground truth. Maintain comp direction.
HP: Only flag if < 25. 30-50 at stage 5+ is normal.
GRID: A=row4(front), B=row3, C=row2, D=row1(back). Cols 1-7.

RULES:
- Shop: read the CHAMPION NAME (large bold text) on each card, NOT the trait/origin tags below it.
- These are ALL TRAIT NAMES, never champion names: Timebreaker, Space Groove, Dark Star, Anima, N.O.V.A., NOVA, Meeple, Mecha, Conduit, Redeemer, Rogue, Stargazer, Psionic, Shepherd, Vanguard, Primordian, Bastion, Fateweaver, Voyager, Scholar, Bruiser, Defender, Invoker, Quickstriker, Slayer, Vanquisher, Arcanist, Juggernaut, Warden, Gunslinger, Replicator, Ixtal, Yordle, Shadow Isles, Zaun, Bilgewater, Noxus, Freljord, Demacia, Ionia, Targon, Shurima.
- If you cannot read the champion name clearly, use "unknown" - NEVER output a trait name as a shop unit. If you cannot read the champion name, use "unknown".
- Use display names. SELL only bench units. BUY only shop units. No guessing.
- If Board units has entries but they are ALL "unknown", units ARE on board but unidentified - say "board active - units unidentified" in Loss. NEVER say "empty board", "no units", "completely empty", "zero board" when board_units has entries.
- If Board units is empty at stage 3+, this means the scan happened during COMBAT - do NOT say "no units on board" or "critical deficit". Say "combat scan - board not visible".
- UnitPlacement: ONLY units from "Board units" above. NEVER include shop, bench, or suggested units.
- If Board units shows "unknown", skip those - only position units you can NAME from the board list.
- The board canvas shows YOUR current units. Do NOT add units you want the player to buy.

OUTPUT - 9 fields, one line each. NO markdown.
Comp: <dominant traits + carry>
Build: <1-2 units to star-up>
Buy: <shop units or "hold gold">
Sell: <bench units or "none">
Keep: <bench units worth holding>
AugmentPlay: <how to use augment, or "N/A">
Loss: <weakness if lost, else "N/A">
UnitPlacement: <board units positioned - "Jinx D7, Vi A1">
UnitSwap: <"Swap X for Y" or "none">
"""

# NOT a cache_control candidate (item 286): static portion ~51 tok, far below
# the 2048-tok Haiku cache floor. Guard: tests/test_prompt_cache_floor_item286.py.
_AUGMENT_SELECT_PROMPT = """\
Challenger TFT augment selection.
Stage/Round: {stage_round}  Level: {level}
Board: {board}  Traits: {traits}  Augments: {augments}
Choices:
{choices}
OUTPUT (3 lines, NO markdown):
Take: <name>
Why: <one sentence>
Gameplan: <what changes>
"""

class TftLiveAnalysis:
    _AUGMENT_ROUNDS={(2,1),(3,2),(4,2)}
    _GOD_ROUNDS={(2,4),(3,4),(4,4)}
    _CAROUSEL_EVENTS={"carousel","opening_carousel","realm_of_gods"}
    def __init__(self, api_key: str, data_file, model: str = "claude-haiku-4-5-20251001") -> None:
        import anthropic
        from tft.tft_vision_reader import TftVisionReader
        self._client=anthropic.Anthropic(api_key=api_key, base_url="https://api.anthropic.com"); self._model=model; self._data_file=data_file
        self._vision=TftVisionReader(api_key,model)
        self._lock=threading.Lock(); self._running=False; self._thread=None
        self._last_round=(0,0); self._last_vision=0.0; self._last_write={}; self._coach_state={}
        self._vision_interval=15.0; self._debug=False; self._known_augments=[]; self._last_placement=""
        self._force_flag=False; self._round_start_time=0.0; self._scanned_planning=False; self._scanned_mid=False
        self._ai_bar = None   # TftAiStatusBar reference, set via set_ai_bar()
    def start(self) -> None:
        self._running=True; self._thread=threading.Thread(target=self._loop,daemon=True,name="TftLiveAnalysis")
        self._thread.start(); logger.info("TftLiveAnalysis started")
    def shutdown(self) -> None: self._running=False
    def set_ai_bar(self, bar: object) -> None:
        """Wire a TftAiStatusBar for scan progress notifications."""
        self._ai_bar = bar
    def _notify_scanning(self, pct=0):
        try:
            if self._ai_bar: self._ai_bar.set_scanning(pct)
        except Exception: pass  # noqa: BLE001
    def _notify_done(self):
        try:
            if self._ai_bar: self._ai_bar.set_done()
        except Exception: pass  # noqa: BLE001
    def _notify_next_scan(self, at_mono):
        try:
            if self._ai_bar: self._ai_bar.notify_scan_scheduled(at_mono)
        except Exception: pass  # noqa: BLE001
    def force_scan(self) -> None:
        # arch: phase 7 P2-C - clear stale choices on augment-select force scan
        # so the fresh vision read produces new advice
        try:
            import json as _j
            _f = self._data_file
            if hasattr(_f, "exists") and _f.exists():
                _d = _j.loads(_f.read_text(encoding="utf-8"))
            else:
                _d = _j.loads(Path(str(_f)).read_text(encoding="utf-8"))
            if _d.get("augment_select"):
                _d["augment_choices"] = []
                _d["aug_take"] = ""
                _d["aug_why"] = ""
                _d["aug_plan"] = "Rescanning augment choices..."
                atomic_write_json(Path(str(self._data_file)), _d)
        except Exception as _exc:  # noqa: BLE001
            logger.debug("force_scan pre-clear failed: %s", _safe_err(_exc))
        self._force_flag = True
        logger.info("Force vision scan triggered (augment reroll path)")
    def notify_round(self, state: dict) -> None:
        self._coach_state=state; sr=(state.get("stage",0),state.get("round",0))
        if sr!=self._last_round:
            # Detect new game: stage resets to <=2 from a higher stage
            prev_stage=self._last_round[0]; new_stage=sr[0]
            if prev_stage > 2 and new_stage <= 2 and sr != (0,0):
                self._known_augments=[]; self._last_placement=""
                logger.info("New game detected (stage %s->%s) - augments cleared",self._last_round,sr)
            self._last_round=sr; self._round_start_time=time.time()
            self._scanned_planning=False; self._scanned_mid=False
    def notify_coach_state(self, state: dict) -> None: self._coach_state=state
    def _is_carousel_or_spectate(self):
        cs=self._coach_state; return cs.get("round_event","") in self._CAROUSEL_EVENTS or cs.get("is_carousel",False)
    def _loop(self):
        while self._running:
            try:
                now=time.time(); sr=self._last_round
                if self._force_flag:
                    self._force_flag=False; self._last_vision=now; self._run_cycle(); time.sleep(1.5); continue
                if self._is_carousel_or_spectate(): time.sleep(2.0); continue
                if sr in self._AUGMENT_ROUNDS or sr in self._GOD_ROUNDS:
                    # Augment/God rounds: scan once when it starts, then every 20s max
                    # (was every 5s - too expensive with sonnet)
                    if (now-self._last_vision)>=20.0: self._last_vision=now; self._run_cycle()
                    time.sleep(2.0); continue
                ra=now-self._round_start_time if self._round_start_time>0 else 999
                scan=False
                if 1.5<=ra<3.5 and not self._scanned_planning:
                    scan=True; self._scanned_planning=True; logger.debug("Vision: planning scan (%.1fs)",ra)
                # Mid-round scan removed - 1 scan/round is sufficient and halves sonnet cost
                if scan: self._last_vision=now; self._run_cycle()
                # Notify AI bar when next scan is expected (do after scan check)
                if self._ai_bar:
                    _next = self._round_start_time + (1.5 if not self._scanned_planning else 12.0)
                    self._notify_next_scan(_next)
            except Exception as e:  # noqa: BLE001
                logger.error("LiveAnalysis loop: %s", _safe_err(e))
            time.sleep(1.5)
    def _run_cycle(self):
        if not self._lock.acquire(blocking=False): return
        self._notify_scanning(10)
        # LANE 8 CYCLE 43: _notify_done() used to sit on two of the four exit
        # paths. The SPECTATING early return and any exception out of
        # self._vision.read() both left the bar reading "scanning" forever.
        # LATENT, not live - TftAiStatusBar is defined nowhere in the repo and
        # wire_ai_bar() has no production caller, so _ai_bar is always None
        # today. Structural so it cannot resurface if a bar is ever wired.
        try:
            vs=self._vision.read()
            if not vs: return
            self._notify_scanning(60)
            if vs.get("augments"): vs["augments"]=[a for a in vs["augments"] if a and not _FAKE_AUGMENT_RE.match(str(a))]
            na=[a for a in (vs.get("augments") or []) if a and a not in self._known_augments]
            if na: self._known_augments.extend(na)
            # Always inject full accumulated augments back into vs so _write sees them
            if self._known_augments:
                vs["augments"] = list(self._known_augments)
            if vs.get("is_augment_select"):
                ch=[c for c in (vs.get("augment_choices") or []) if c and (isinstance(c,dict) or str(c).lower() not in _NOT_AUGMENTS)]
                vl=[c if isinstance(c,str) else c.get("name","") for c in ch if (isinstance(c,dict) and c.get("description")) or (isinstance(c,str) and len(c.split())>=2)]
                if len(vl)>=2: self._run_augment_select(vs); return
                vs["is_augment_select"]=False
            bu=vs.get("board_units") or []
            if bu and any(str(u).upper()=="SPECTATING" for u in bu):
                logger.debug("SPECTATING detected - skipping"); return
            self._notify_scanning(90)
            self._run_analysis(vs)
        finally:
            self._notify_done()
            self._lock.release()
    @staticmethod
    def _clean_units(units,trait_names):
        r=[]
        for u in (units or []):
            if not u or u in ("empty","unknown"): continue
            s=str(u)
            if not _is_valid_unit(s): continue
            b=s.split()[0].lower()
            if b in _NOT_UNIT_LABELS or b in trait_names: continue
            r.append(s)
        return r
    def _run_analysis(self,vs):
        try:
            from core.cost_tracker import get_tracker as _gt
            if _gt().gate_disabled("tft"): return
        except Exception: pass  # noqa: BLE001
        cs=self._coach_state; rt=vs.get("traits_active") or []
        tn={t.split()[0].lower() for t in rt if t}
        bc=self._clean_units(vs.get("board_units"),tn); bn=self._clean_units(vs.get("bench_units"),tn); sc=self._clean_units(vs.get("shop_units"),tn)
        lc=f"LAST ROUND LOST - took {vs.get('round_damage','?')} damage." if vs.get("last_round_result")=="loss" else ""
        ac=f"ACTIVE AUGMENTS: {', '.join(str(a) for a in vs.get('augments',[]))}" if vs.get("augments") else ""
        # Unit presence from board/roster clicks
        # LANE 8 CYCLE 43: one read, one handler, and every field coerced.
        # This block used to read the file TWICE and bind _pd inside the try,
        # so the trailing `_pd.get(...)` was only safe by accident - the
        # conditional expression short-circuits on the same failure that
        # leaves _pd unbound. It also passed the raw JSON straight to
        # ", ".join(), outside any handler. See _as_name_list.
        _pf=Path(str(self._data_file)).parent/"unit_presence.json"
        _bc,_ep,_ml=[],[],None
        try:
            _pd=json.loads(_pf.read_text(encoding="utf-8")) if _pf.exists() else {}
            if isinstance(_pd,dict):
                _bc=_as_name_list(_pd.get("board_confirmed"))
                _ep=_as_name_list(_pd.get("extra_present"))
                _lv=_pd.get("manual_level")
                if isinstance(_lv,(int,float,str)) and str(_lv).strip():
                    _ml=str(_lv).strip()
        except Exception as _exc:  # noqa: BLE001
            logger.debug("unit_presence.json unreadable: %s", _safe_err(_exc))
        if _bc: ac=(ac+"\nCONFIRMED ON BOARD: "+", ".join(_bc)+".").strip()
        if _ep: ac=(ac+"\nALSO PRESENT (not in comp): "+", ".join(_ep)+".").strip()
        if _ml: ac=(ac+f"\nCURRENT LEVEL: {_ml} (player-confirmed).").strip()
        p=_ANALYSIS_PROMPT_TEMPLATE.format(stage_round=cs.get("stage_round","?"),level=vs.get("level") or cs.get("level","?"),
            hp=vs.get("hp") or "?",gold=vs.get("gold") or "?",board=_fmt(bc),bench=_fmt(bn),shop=_fmt(sc),
            items_equipped=json.dumps(_psan_items_equipped(vs.get("items_equipped")),indent=None),items_bench=_fmt(vs.get("items_on_bench")),
            traits=_fmt(vs.get("traits_active")),augments=_fmt(vs.get("augments")),loss_context=lc,augment_context=ac)
        try:
            t0=time.time()
            raw=None
            try:
                from core.moon_proxy import moon_proxy
                raw=moon_proxy.get_coaching(p,model=self._model)
            except Exception as _exc:  # noqa: BLE001
                logger.debug("moon_proxy.get_coaching primary path failed: %s", _safe_err(_exc))
            if raw is None:
                resp=self._client.messages.create(model=self._model,max_tokens=500,messages=[{"role":"user","content":p}],timeout=_MODEL_TIMEOUT_S)
                # AUDIT 2026-05-23 (cost-trace gap C): feed cost_tracker on
                # local-fallback path. moon_proxy primary records via vision_server.
                try:
                    from core.cost_tracker import record_anthropic_response
                    record_anthropic_response(resp, model=self._model, purpose="tft_live_analysis")
                except Exception as _exc:  # noqa: BLE001
                    logger.debug("cost_tracker record: %s", _safe_err(_exc))
                raw=_first_text(resp); logger.info("Live analysis in %dms",int((time.time()-t0)*1000))
            if not isinstance(raw,str) or not raw.strip():
                logger.warning("Live analysis: no usable text block in response")
                self._publish_degraded(vs,cs); return
            f=_parse_analysis(raw)
            if f.get("comp","").upper().startswith("SPECTATING"): logger.debug("Spectating - skip"); return
            if self._debug or not f: logger.debug("Raw:\n%s",raw[:600])
            up=f.get("unitplacement","")
            if up: self._last_placement=up
            self._write(vs,f,cs)
        except Exception as e:  # noqa: BLE001
            # CLAUDE.md "Error Handling": the raw string goes to logs/ ONLY.
            # Pre-fix this branch was the whole handler, so an exhausted
            # balance or a 400 published NOTHING and the panel held the
            # previous round's advice indefinitely with no indication.
            logger.error("Live analysis API: %s", _safe_err(e))
            self._publish_degraded(vs,cs)
    def _publish_degraded(self,vs,cs):
        """Republish live state with a friendly degraded marker.

        Keeps the last known advice so the panel still RENDERS
        (feedback_no_reflow_on_data_absence) and adds `degraded` /
        `degraded_message` beside it. Never carries the upstream error text.
        """
        try:
            ex=_load(self._data_file)
            out=dict(ex) if isinstance(ex,dict) else {"mode":"tft_live"}
            out.update({"mode":"tft_live","stage_round":cs.get("stage_round",""),
                        "level":vs.get("level") or cs.get("level"),"hp":vs.get("hp"),
                        "degraded":True,"degraded_message":_DEGRADED_TEXT})
            _write(self._data_file,out)
            # Invalidate the write gate. Without this, a recovery cycle whose
            # advice is byte-identical to the last good one compares equal to
            # _last_write, is suppressed, and leaves degraded=True on disk
            # after the outage has already cleared.
            self._last_write={}
        except Exception as _exc:  # noqa: BLE001
            logger.error("degraded publish failed: %s", _safe_err(_exc))

    def _run_augment_select(self,vs):
        try:
            from core.cost_tracker import get_tracker as _gt
            if _gt().gate_disabled("tft"): return
        except Exception: pass  # noqa: BLE001
        cs=self._coach_state; ch=vs.get("augment_choices") or []
        if not ch: return
        def _fc(c): return f"{c.get('name','?')}: {c.get('description','')}" if isinstance(c,dict) else str(c)
        p=_AUGMENT_SELECT_PROMPT.format(stage_round=cs.get("stage_round","?"),level=vs.get("level") or cs.get("level","?"),
            board=_fmt(self._clean_units(vs.get("board_units"),set())),traits=_fmt(vs.get("traits_active")),
            # RM-364: sanitise the RENDERED choice at the join, NOT inside
            # _fc - _fc also feeds the `augment_choices` list written to the
            # coaching data file below (:527), which the dashboard panel
            # renders, and cleaning there would rewrite panel text this row
            # does not authorise. max_len 300: augment descriptions are
            # genuinely long and the 200 default would truncate real content.
            augments=_fmt(vs.get("augments") or []) if vs.get("augments") else "none",choices="\n".join(f"- {_psan_clean(_fc(c), max_len=300)}" for c in ch))
        try:
            _araw=None
            try:
                from core.moon_proxy import moon_proxy
                _araw=moon_proxy.get_coaching(p,model=self._model)
            except Exception as _exc:  # noqa: BLE001
                logger.debug("moon_proxy.get_coaching augment-select path failed: %s", _safe_err(_exc))
            if _araw is None:
                _aresp=self._client.messages.create(model=self._model,max_tokens=300,messages=[{"role":"user","content":p}],timeout=_MODEL_TIMEOUT_S)
                # AUDIT 2026-05-23 (cost-trace gap C): feed cost_tracker on
                # local-fallback path. moon_proxy primary records via vision_server.
                try:
                    from core.cost_tracker import record_anthropic_response
                    record_anthropic_response(_aresp, model=self._model, purpose="tft_live_aug_select")
                except Exception as _exc:  # noqa: BLE001
                    logger.debug("cost_tracker record: %s", _safe_err(_exc))
                _araw=_first_text(_aresp)
            if not isinstance(_araw,str) or not _araw.strip():
                logger.warning("Augment select: no usable text block in response"); return
            raw=re.sub(r'\*{1,3}(.*?)\*{1,3}',r'\1',_araw)
            tk=_xf(raw,"Take"); why=_xf(raw,"Why"); plan=_xf(raw,"Gameplan")
            if not tk: tk=ch[0].get("name","") if isinstance(ch[0],dict) else str(ch[0])
            ex=_load(self._data_file)
            ex.update({"augment_select":True,"aug_take":tk,"aug_why":why or "","aug_plan":plan or "","augment_choices":[_fc(c) for c in ch]})
            _write(self._data_file,ex); logger.info("Augment select written")
        except Exception as e:  # noqa: BLE001
            logger.error("Augment select: %s", _safe_err(e))
    def _write(self,vs,f,cs):
        out={"mode":"tft_live","stage_round":cs.get("stage_round",""),"level":vs.get("level") or cs.get("level"),"hp":vs.get("hp"),
            "board_units":vs.get("board_units") or [],"bench_units":vs.get("bench_units") or [],
            "shop_units":vs.get("shop_units") or [],"traits_active":vs.get("traits_active") or [],
            "augments":vs.get("augments") or [],"last_round_result":vs.get("last_round_result"),"augment_select":False,
            "comp":f.get("comp",""),"build":f.get("build",""),"buy":f.get("buy",""),"sell":f.get("sell",""),
            "keep":f.get("keep",""),"augment_play":f.get("augmentplay",""),"loss":f.get("loss",""),
            "unit_placement":f.get("unitplacement",""),"unit_swap":f.get("unitswap","")}
        # Pre-write: strip trait names from shop_units + clamp HP
        _TN = {"timebreaker","space groove","dark star","anima","nova","n.o.v.a.","meeple","mecha",
               "conduit","redeemer","rogue","stargazer","psionic","shepherd","vanguard","primordian",
               "bastion","fateweaver","voyager","scholar","bruiser","defender","invoker","quickstriker",
               "slayer","vanquisher","arcanist","juggernaut","warden","gunslinger","replicator",
               "ixtal","yordle","shadow isles","zaun","bilgewater","noxus","freljord","demacia",
               "ionia","targon","shurima","marauder","eternal","harvester","chronokeeper",
               "challenger","gun goddess","longshot","sniper","arbiter","contract killer",
               "stellar","automata","conqueror","soul","void","arcane","channeler",
               "party crasher","divine","factory new","darkin","dragonborn",
               "astron","astronaut","primordial"}
        if "shop_units" in out:
            _cleaned = []
            for _u in out.get("shop_units", []):
                if not _u or _u == "empty": _cleaned.append(_u); continue
                _ul = str(_u).lower().strip()
                _is_t = any(_ul == t or _ul.startswith(t + " ") or _ul.startswith(t + "/") for t in _TN)
                if not _is_t and "/" in _ul:
                    _is_t = all(p.strip() in _TN for p in _ul.split("/"))
                # Also catch "unknown Trait/Trait" format
                if not _is_t and _ul.startswith("unknown "):
                    _rest = _ul[8:].strip()  # strip "unknown "
                    if _rest:
                        _is_t = any(_rest == t or _rest.startswith(t + "/") or _rest.startswith(t + " ") for t in _TN)
                        if not _is_t and "/" in _rest:
                            _is_t = all(p.strip() in _TN for p in _rest.split("/"))
                if _is_t:
                    _cleaned.append("unknown")
                else:
                    # Whitelist: only allow known Set 17 champion names
                    _name_clean = str(_u).strip().split("(")[0].strip()  # strip cost annotations
                    if _name_clean.lower() in _TFT_CHAMP_LOWER or _name_clean in _TFT_CHAMPIONS:
                        _cleaned.append(_u)
                    else:
                        _cleaned.append("unknown")
            out["shop_units"] = _cleaned
        _ohp = out.get("hp")
        if _ohp and isinstance(_ohp, (int, float)) and (_ohp > 100 or _ohp < 0): out["hp"] = 0
        # Fix false "empty board" in loss when board_units has entries
        _bu = out.get("board_units", [])
        _loss = out.get("loss", "") or ""
        if _bu and len(_bu) > 0 and any(_loss.lower().count(w) for w in ["zero board","no units","empty board","no board","critical deficit"]):
            if all(str(u) == "unknown" for u in _bu):
                out["loss"] = "board active - units unidentified"
            else:
                out["loss"] = "N/A"
        # LANE 8 CYCLE 43: this gate compared only the six ADVICE keys, so a
        # round whose advice happened to repeat published NOTHING - and
        # stage_round / hp / level / board_units stayed frozen at the previous
        # round's values for all seven polling readers, including
        # ops/rc_state_validator.py which range-checks exactly those fields.
        # Comparing the whole payload fixes that. Be honest about the cost:
        # suppression now fires only on a byte-identical payload, which is
        # rare because shop_units turns over on every reroll - so this writes
        # more often than the old gate did. That is the correct trade for a
        # file seven readers treat as current state, and the write is atomic
        # and small, but it is a real change in write frequency, not a
        # like-for-like preservation of the old behaviour.
        out["degraded"]=False; out["degraded_message"]=""
        if out!=self._last_write:
            self._last_write=dict(out); _write(self._data_file,out); logger.debug("Live analysis written")

def _fmt(lst):
    if not lst: return "none"
    return ", ".join(str(x) for x in lst if x and x!="empty") or "none"
def _parse_analysis(text):
    f={}; text=re.sub(r'\*{1,3}(.*?)\*{1,3}',r'\1',text); text=re.sub(r'^#+\s*','',text,flags=re.MULTILINE)
    for line in text.strip().splitlines():
        s=line.strip()
        if not s: continue
        for k in ["Comp","Build","Buy","Sell","Keep","AugmentPlay","Loss","UnitPlacement","UnitSwap"]:
            if s.lower().startswith(k.lower()+":"):
                v=re.sub(r'\*{1,3}(.*?)\*{1,3}',r'\1',s[len(k)+1:].strip())
                f[k.lower().replace(" ","")]=v[:200]; break
    return f
def _xf(text,key):
    for line in text.strip().splitlines():
        s=line.strip()
        if s.lower().startswith(key.lower()+":"): return s[len(key)+1:].strip()
    return ""
def _load(path):
    try:
        if path.exists(): return json.loads(path.read_text(encoding="utf-8"))
    except Exception: pass  # noqa: BLE001
    return {"mode":"tft_live"}
def _write(path, data):
    try:
        # Augment persistence: if current scan has no augments but file already has
        # accumulated augments from this game, preserve them.
        # Reset when stage drops (new game detected).
        if not data.get("augments") and path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                prev_augs = existing.get("augments") or []
                if prev_augs:
                    # Detect new game by stage comparison - reset if stage regressed to <=2
                    prev_sr = str(existing.get("stage_round", ""))
                    curr_sr = str(data.get("stage_round", ""))
                    prev_stage = int(prev_sr.split("-")[0]) if "-" in prev_sr else 0
                    curr_stage = int(curr_sr.split("-")[0]) if "-" in curr_sr else 0
                    if curr_stage >= prev_stage or prev_stage <= 2:
                        data["augments"] = prev_augs
            except Exception:  # noqa: BLE001
                pass
        # LANE 8 CYCLE 43 - RM-261 enumerated site. This derived the scratch
        # name from the DESTINATION, and core/feature_policy.py:_write_json
        # writes the SAME file the SAME way, so both writers opened
        # data/tft_live_data.tmp: the torn-destination defect lane 8 cycle 24
        # measured and fixed in core/polled_json.py. atomic_write_json gives a
        # per-writer <name>.<pid>.<token>.tmp, retries WinError 5 against a
        # polling reader, and never orphans the scratch file.
        atomic_write_json(path, data)
    except Exception as e:  # noqa: BLE001
        logger.error("Write failed: %s", _safe_err(e))
