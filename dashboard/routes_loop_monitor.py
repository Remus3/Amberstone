# arch: GET /api/loop-monitor (per-tool-call timeline) | section=dashboard | frozen=no
"""GET /api/loop-monitor - per-tool-call timeline for the active session.

The TIMELINE complement to GET /api/loop-status (cycle / budget / state). It
parses the active session transcript JSONL - the very files
``ops/loop/loop_controller.meter()`` reads for billing - and pairs each
``tool_use`` block (in an assistant message) with its later ``tool_result``
block (in a user message) by ``id`` / ``tool_use_id``. The wall-clock duration
of every call is ``result.timestamp - use.timestamp``.

It answers the operator question the loop never surfaced: "this cycle has been
running 30 minutes - WHY?". The ``summary`` collapses repeated calls so a
14-run pytest battery shows as one ``Bash:pytest x14 = 26m`` row (the
"unnecessary test battery" smell), and ``inflight`` lists any ``tool_use`` with
no result yet - the live "stuck on X for Nm" signal.

Read-only, fail-soft, NO engine math, NO writes, NO new dependency. Selection of
the active transcript mirrors loop_controller.session_files(): the pinned
``session_jsonl`` from ops/loop/config.json when set, else the newest top-level
``*.jsonl`` in ``transcript_dir``. Only the main (top-level) transcript is
parsed in v1; a long subagent call appears as one in-flight ``Agent`` row.

Response (always HTTP 200 unless an unexpected top-level error -> 500):
  {
    "ok": true,
    "session": <basename|null>,
    "tool_count": <int>,                       # tool_use events in the window
    "window": {"first_iso": <str|null>, "last_iso": <str|null>},
    "summary": [ {sig, name, count, total_s, max_s, errors} ... ],  # total_s desc
    "recent": [ {name, sig, target, start_iso, duration_s, is_error, inflight} ],
    "inflight": [ {name, sig, target, start_iso, elapsed_s} ... ],
    "updated_at": <iso8601 Z>
  }
"""
from __future__ import annotations

import json
import logging
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from dashboard._dispatch import equals
from dashboard._errors import send_error

log = logging.getLogger("rc.web_dashboard")

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "ops" / "loop" / "config.json"
# Fallback transcript dir when config.json has none (mirrors the live path).
DEFAULT_TRANSCRIPT_DIR = (
    Path.home() / ".claude" / "projects" / "C--Riot-Commander"
)

# Newest-N tool calls returned in `recent`; tail cap so a multi-hour session
# JSONL (tens of MB) never blows memory - the deque keeps only the last lines,
# which is exactly the recent activity the operator is watching.
RECENT_N = 50
MAX_LINES = 8000

# Shell tools whose `command` carries the real signature (so a pytest battery
# is distinguishable from a git/curl run instead of all bucketing as "Bash").
_SHELL = {"Bash", "PowerShell"}
# Checked in order; first substring hit wins. py_compile before python so
# "python -m py_compile" buckets as py_compile, pytest before python likewise.
_KEYWORDS = (
    "pytest", "py_compile", "ruff", "taskkill", "schtasks", "restart_trigger",
    "git", "curl", "python", "node", "npm", "echo",
)

# Tools that can legitimately run for minutes (subagents, shell, web). For
# everything else a multi-minute use->result gap is NOT the tool's own time -
# it is a model-generation / API-retry stall straddling the call (observed as
# near-exact 10-min boundaries). Such gaps are billed to `stalls`, not the tool,
# so a 1-second Edit never masquerades as a 20-minute step.
LONG_TOOLS = {"Bash", "PowerShell", "Agent", "Task", "WebFetch", "WebSearch"}
STALL_S = 120.0

# toolUseResult fields that carry TRUE execution time (immune to stalls).
# WebFetch/Glob -> durationMs; subagents -> totalDurationMs. Bash/PowerShell/
# Edit/Write/Read/Grep embed nothing, so those fall back to the wall-clock gap.
def _embedded_exec_ms(tur) -> float | None:
    if not isinstance(tur, dict):
        return None
    v = tur.get("durationMs")
    if v is None:
        v = tur.get("totalDurationMs")
    return v if isinstance(v, (int, float)) and v >= 0 else None


def _near_retry_quantum(wall: float) -> bool:
    """True when a gap sits within a few seconds of a 600s (10-min) multiple -
    the observed API-retry stall cadence. Lets a shell call that merely straddled
    a stall be reclassified OUT of its tool's real-time total (a genuine test
    battery is many short calls, none landing on the 10-min boundary)."""
    if wall < 540.0:
        return False
    q = round(wall / 600.0)
    return q >= 1 and abs(wall - q * 600.0) <= 12.0


# --------------------------------------------------------------------------- fail-soft IO
def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(s) -> float | None:
    """ISO8601 (e.g. '2026-05-21T19:48:20.881Z') -> epoch seconds. None on junk."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------- session selection
def _transcript_dir() -> Path:
    cfg = _read_json(CONFIG_PATH) or {}
    td = cfg.get("transcript_dir")
    return Path(td) if td else DEFAULT_TRANSCRIPT_DIR


def _active_session_path() -> Path | None:
    """Pinned session_jsonl if set+present, else newest top-level *.jsonl.

    Mirrors loop_controller.session_files() selection (top-level only - subagent
    transcripts live under <session>/subagents/ and are excluded in v1)."""
    cfg = _read_json(CONFIG_PATH) or {}
    pin = cfg.get("session_jsonl")
    if pin:
        p = Path(pin)
        if p.exists():
            return p
    try:
        tops = sorted(_transcript_dir().glob("*.jsonl"),
                      key=lambda q: q.stat().st_mtime, reverse=True)
    except OSError:
        return None
    return tops[0] if tops else None


# --------------------------------------------------------------------------- signature / target hints
def _sig(name: str, inp: dict) -> str:
    """A grouping key. Shell tools -> '<name>:<keyword>' so pytest batteries
    cluster; everything else groups by tool name."""
    if name in _SHELL:
        low = str(inp.get("command") or "").lower()
        for kw in _KEYWORDS:
            if kw in low:
                return f"{name}:{kw}"
        tok = low.split()
        return f"{name}:{tok[0]}" if tok else name
    return name


def _target(name: str, inp: dict) -> str:
    """A short human hint of what the call acted on (file / command / pattern)."""
    for k in ("file_path", "pattern", "url", "notebook_path"):
        v = inp.get(k)
        if v:
            return str(v)[:80]
    cmd = inp.get("command")
    if cmd:
        return str(cmd)[:80]
    for k in ("description", "prompt", "query"):
        v = inp.get(k)
        if v:
            return str(v)[:80]
    return ""


# --------------------------------------------------------------------------- builder
def build_loop_timeline(session_path: Path | None = None, *,
                        recent_n: int = RECENT_N, now_ts: float | None = None,
                        max_lines: int = MAX_LINES) -> dict:
    now = now_ts if now_ts is not None else time.time()
    sp = session_path or _active_session_path()
    out = {
        "ok": True,
        "session": (sp.name if sp else None),
        "tool_count": 0,
        "window": {"first_iso": None, "last_iso": None},
        "summary": [],
        "recent": [],
        "inflight": [],
        "stalls": [],
        "updated_at": _now_iso(),
    }
    if not sp or not sp.exists():
        return out

    uses: dict[str, dict] = {}     # id -> {name, sig, target, start_ts, start_iso}
    results: dict[str, dict] = {}  # id -> {end_ts, is_error}
    try:
        with sp.open(encoding="utf-8", errors="replace") as fh:
            lines = deque(fh, maxlen=max_lines)
    except OSError:
        return out

    for line in lines:
        try:
            o = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        m = o.get("message")
        if not isinstance(m, dict):
            continue
        content = m.get("content")
        if not isinstance(content, list):
            continue
        ts = _parse_ts(o.get("timestamp"))
        if ts is None:
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            bt = b.get("type")
            if bt == "tool_use":
                tid = b.get("id")
                if not tid:
                    continue
                name = b.get("name") or "?"
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                uses[tid] = {
                    "name": name, "sig": _sig(name, inp), "target": _target(name, inp),
                    "start_ts": ts, "start_iso": o.get("timestamp"),
                }
            elif bt == "tool_result":
                tid = b.get("tool_use_id")
                if tid:
                    results[tid] = {
                        "end_ts": ts,
                        "is_error": bool(b.get("is_error")),
                        "exec_ms": _embedded_exec_ms(o.get("toolUseResult")),
                    }

    calls = []
    stalls = []
    for tid, u in uses.items():
        r = results.get(tid)
        if not r:
            # no result yet: the call is running NOW. now-start is a real elapsed.
            calls.append({**u, "duration_s": round(max(0.0, now - u["start_ts"]), 2),
                          "approx": False, "suspect": False,
                          "inflight": True, "is_error": False})
            continue
        wall = max(0.0, r["end_ts"] - u["start_ts"])
        exec_ms = r.get("exec_ms")
        if exec_ms is not None:
            dur, approx, suspect = exec_ms / 1000.0, False, False
        else:
            dur, approx = wall, True
            # fast/local tool burning minutes == a stall straddling the call,
            # not the tool's work -> flag it, and bill the gap to `stalls`.
            suspect = wall > STALL_S and (
                u["name"] not in LONG_TOOLS or _near_retry_quantum(wall))
            if suspect:
                stalls.append({"at": u["start_iso"], "gap_s": round(wall, 1),
                               "after_sig": u["sig"]})
        calls.append({**u, "duration_s": round(dur, 2),
                      "approx": approx, "suspect": suspect,
                      "inflight": False, "is_error": r["is_error"]})
    calls.sort(key=lambda c: c["start_ts"])

    out["tool_count"] = len(calls)
    if calls:
        out["window"] = {"first_iso": calls[0]["start_iso"],
                         "last_iso": calls[-1]["start_iso"]}

    # Summary: suspect (stall-inflated) calls count toward `count` but contribute
    # NO time, so a tool's total reflects real work, never a straddling stall.
    agg: dict[str, dict] = {}
    for c in calls:
        a = agg.setdefault(c["sig"], {"sig": c["sig"], "name": c["name"],
                                      "count": 0, "total_s": 0.0, "max_s": 0.0,
                                      "errors": 0, "approx": 0})
        a["count"] += 1
        if c["is_error"]:
            a["errors"] += 1
        if c["approx"] and not c["suspect"]:
            a["approx"] += 1
        if not c["suspect"]:
            a["total_s"] += c["duration_s"]
            a["max_s"] = max(a["max_s"], c["duration_s"])
    summary = sorted(agg.values(), key=lambda a: a["total_s"], reverse=True)
    for a in summary:
        a["total_s"] = round(a["total_s"], 2)
        a["max_s"] = round(a["max_s"], 2)
    out["summary"] = summary

    out["recent"] = [
        {"name": c["name"], "sig": c["sig"], "target": c["target"],
         "start_iso": c["start_iso"], "duration_s": c["duration_s"],
         "approx": c["approx"], "suspect": c["suspect"],
         "is_error": c["is_error"], "inflight": c["inflight"]}
        for c in reversed(calls[-recent_n:])
    ]
    out["inflight"] = [
        {"name": c["name"], "sig": c["sig"], "target": c["target"],
         "start_iso": c["start_iso"], "elapsed_s": c["duration_s"]}
        for c in calls if c["inflight"]
    ]
    out["stalls"] = sorted(stalls, key=lambda s: s["gap_s"], reverse=True)
    return out


# --------------------------------------------------------------------------- handler
def _serve_loop_monitor(h) -> None:
    """GET /api/loop-monitor handler."""
    try:
        payload = build_loop_timeline()
        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:  # noqa: BLE001 - last-resort guard, never 500 raw
        log.warning("api/loop-monitor: %s", exc)
        try:
            send_error(h, exc)
        except Exception:  # noqa: BLE001
            pass


_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RC Loop Monitor</title>
<style>
:root{--bg:#0a1428;--panel:#0f1c2e;--line:#1e2d44;--gold:#c8aa6e;--teal:#0ac8b9;
--tx:#cdd2e0;--mut:#7c869c;--red:#c8455a;--grn:#3fb950;--org:#d29922}
*{box-sizing:border-box}
body{margin:0 auto;max-width:1180px;background:var(--bg);color:var(--tx);padding:14px;
font:14px/1.5 'Segoe UI',system-ui,sans-serif}
header{display:flex;align-items:baseline;gap:12px;border-bottom:1px solid var(--line);
padding-bottom:8px;margin-bottom:12px;flex-wrap:wrap}
header h1{font-size:16px;margin:0;color:var(--gold);letter-spacing:.5px}
.sess{color:var(--mut);font-family:ui-monospace,Consolas,monospace;font-size:12px}
#updated{margin-left:auto;color:var(--mut);font-size:12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;
padding:10px 12px;margin-bottom:10px}
h2{font-size:12px;text-transform:uppercase;letter-spacing:.6px;color:var(--teal);margin:0 0 8px}
.muted{color:var(--mut);font-weight:400;text-transform:none;letter-spacing:0}
.row{display:flex;gap:18px;flex-wrap:wrap}
.kv .k{color:var(--mut);font-size:12px;margin-right:6px;text-transform:uppercase}
.kv .v{font-weight:600}
.pill{padding:1px 8px;border-radius:10px;font-size:12px;font-weight:700}
.pill.running{background:rgba(63,185,80,.15);color:var(--grn)}
.pill.idle{background:rgba(91,100,120,.2);color:var(--mut)}
.pill.stopped{background:rgba(200,69,90,.15);color:var(--red)}
.commit{margin-top:6px;color:var(--mut);font-family:ui-monospace,Consolas,monospace;font-size:12px}
.stop{margin-top:6px;color:var(--red);font-weight:600}
.now{font-size:14px;padding:4px 0;color:var(--gold)}
.now .tgt{color:var(--mut);font-family:ui-monospace,Consolas,monospace;font-size:12px}
table{width:100%;border-collapse:collapse}
td{padding:3px 6px;border-bottom:1px solid rgba(30,45,68,.5);vertical-align:middle}
.sig{font-family:ui-monospace,Consolas,monospace}
.cnt{color:var(--mut);text-align:right;width:46px}
.tgt{color:var(--mut);font-family:ui-monospace,Consolas,monospace;font-size:12px;
max-width:340px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.d{font-family:ui-monospace,Consolas,monospace;text-align:right;white-space:nowrap}
.d-fast{color:var(--mut)}.d-ok{color:var(--grn)}.d-warn{color:var(--org)}.d-slow{color:var(--red)}
.bar{width:28%}.bar div{height:8px;background:linear-gradient(90deg,var(--teal),var(--gold));border-radius:4px}
.err{color:var(--red);font-weight:700}.tilde{color:var(--org)}
.rinf{background:rgba(63,185,80,.06)}.rsus{background:rgba(210,153,34,.05)}
</style></head><body>
<header><h1>RC LOOP MONITOR</h1><span class="sess" id="sess"></span><span id="updated"></span></header>
<div class="card" id="loopstatus"></div>
<div class="card" id="inflight"></div>
<div class="card" id="stalls"></div>
<div class="card" id="summary"></div>
<div class="card" id="recent"></div>
<script>
var $=function(i){return document.getElementById(i)};
function dur(s){if(s==null)return'-';if(s<60)return s.toFixed(1)+'s';
if(s<3600)return (s/60).toFixed(1)+'m';return (s/3600).toFixed(2)+'h'}
function dcl(s){if(s==null)return'';if(s<1)return'd-fast';if(s<10)return'd-ok';
if(s<60)return'd-warn';return'd-slow'}
function esc(t){return (t==null?'':String(t)).replace(/[&<>]/g,function(c){
return {'&':'&amp;','<':'&lt;','>':'&gt;'}[c]})}
function tm(s){return esc((s||'').slice(11,19))}
function kv(k,v){return '<div class="kv"><span class="k">'+k+'</span><span class="v">'+v+'</span></div>'}
async function jget(u){try{var r=await fetch(u,{cache:'no-store'});return r.ok?await r.json():null}catch(e){return null}}
async function load(){
 var a=await Promise.all([jget('/api/loop-monitor'),jget('/api/loop-status')]);
 var m=a[0],s=a[1];
 $('updated').textContent=m?('updated '+(m.updated_at||'')):'(endpoint down)';
 $('sess').textContent=m&&m.session?m.session:'';
 rStatus(s);rMon(m);
}
function rStatus(s){
 var el=$('loopstatus');
 if(!s){el.innerHTML='<div class="muted">loop-status unavailable</div>';return}
 var st=(s.state||'?'),b=s.budget||{},lc=s.last_commit||{};
 var cyc=(s.cycle!=null)?(s.cycle+(s.max_cycles?(' / '+s.max_cycles):'')):'-';
 el.innerHTML='<div class="row">'
  +kv('state','<span class="pill '+st+'">'+st.toUpperCase()+'</span>')
  +kv('cycle',cyc)
  +kv('gemini',b.gemini_usd!=null?('$'+b.gemini_usd+' / '+b.gemini_ceiling):'-')
  +kv('claude',b.claude_usd_info!=null?('$'+b.claude_usd_info):'-')
  +'</div>'
  +(lc.sha?('<div class="commit">HEAD '+esc(lc.sha)+'  '+esc(lc.subject)+'</div>'):'')
  +(s.stop_reason?('<div class="stop">STOPPED: '+esc(s.stop_reason)+'</div>'):'');
}
function rMon(m){
 if(!m){$('inflight').innerHTML='<div class="muted">monitor endpoint down</div>';
  $('stalls').innerHTML='';$('summary').innerHTML='';$('recent').innerHTML='';return}
 var inf=m.inflight||[];
 $('inflight').innerHTML='<h2>Running now</h2>'+(inf.length?inf.map(function(c){
  return '<div class="now">&#9656; '+esc(c.sig)+' <span class="tgt">'+esc(c.target)
   +'</span> <span class="d d-slow">'+dur(c.elapsed_s)+'</span></div>'}).join('')
  :'<div class="muted">idle / between tool calls</div>');
 var sl=m.stalls||[];
 $('stalls').innerHTML='<h2>Stalls <span class="muted">(idle gaps - not tool time)</span></h2>'
  +(sl.length?'<table>'+sl.slice(0,8).map(function(s){
   return '<tr><td class="d d-slow">'+dur(s.gap_s)+'</td><td>after '+esc(s.after_sig)
    +'</td><td class="muted">'+tm(s.at)+'</td></tr>'}).join('')+'</table>'
   :'<div class="muted">none detected</div>');
 var sum=m.summary||[],mx=1;
 sum.forEach(function(r){if(r.total_s>mx)mx=r.total_s});
 $('summary').innerHTML='<h2>Time by tool <span class="muted">('+m.tool_count+' calls)</span></h2>'
  +'<table>'+sum.slice(0,14).map(function(r){
   var w=Math.round(100*(r.total_s||0)/mx);
   return '<tr><td class="sig">'+esc(r.sig)+(r.approx?' <span class="tilde">~</span>':'')+'</td>'
    +'<td class="cnt">x'+r.count+'</td>'
    +'<td class="bar"><div style="width:'+w+'%"></div></td>'
    +'<td class="d '+dcl(r.total_s)+'">'+dur(r.total_s)+'</td>'
    +'<td class="d muted">max '+dur(r.max_s)+'</td>'
    +(r.errors?'<td class="err">'+r.errors+'e</td>':'<td></td>')+'</tr>'}).join('')+'</table>';
 var rec=m.recent||[];
 $('recent').innerHTML='<h2>Recent calls <span class="muted">(newest first)</span></h2>'
  +'<table>'+rec.slice(0,30).map(function(c){
   return '<tr class="'+(c.inflight?'rinf':(c.suspect?'rsus':''))+'">'
    +'<td class="muted">'+tm(c.start_iso)+'</td><td class="sig">'+esc(c.sig)+'</td>'
    +'<td class="d '+(c.inflight?'d-slow':dcl(c.duration_s))+'">'+dur(c.duration_s)
    +(c.approx?' ~':'')+'</td><td class="tgt">'+esc(c.target)
    +(c.is_error?' <span class="err">!</span>':'')+'</td></tr>'}).join('')+'</table>';
}
load();setInterval(load,4000);
</script></body></html>"""


def _serve_loop_monitor_page(h) -> None:
    """GET /loop-monitor - the human-readable auto-refreshing view."""
    try:
        h._send(200, _PAGE.encode("utf-8"), "text/html; charset=utf-8")
    except Exception as exc:  # noqa: BLE001
        log.warning("loop-monitor page: %s", exc)
        try:
            send_error(h, exc)
        except Exception:  # noqa: BLE001
            pass


GET_ROUTES = [
    (equals("/api/loop-monitor"), _serve_loop_monitor),
    (equals("/loop-monitor"), _serve_loop_monitor_page),
]

POST_ROUTES: list = []
