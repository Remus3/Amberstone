# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 the operator - the kit's owner and sole copyright holder. See NOTICE.
"""Fleet kit v23 - STATUS BOARD (FLEET-COMMON 18): the per-tree LOCAL board.
Vendored byte-for-byte at ops/fleet_kit/ and pinned by MANIFEST.json. Do NOT
edit a vendored copy: report the defect to MAIN.

v23 (operator order 2026-10-25): the board is LOCAL ONLY. No claude.ai
artifact, no Artifact upload, no ArtifactData update, no board URL. Why: the
operator views the board locally; the artifact push wasted tokens. Nothing
this helper prints is a tool call.

    python ops/fleet_kit/fleet_board.py render --session <n> < checklist.txt
       -> writes <main checkout>/ops/loop/control/board/status.json,
          state.json and board.html; prints {"rendered", "file", "html", "rows"}

status.json is a JSON array of rows

    {"id", "group": running|operator|next|done, "seq", "task", "state", "detail"}

and board.html is a static, self-contained page (no script, no network, light
and dark, re-read every 60 s by an open browser tab) built from the same
rows. Open board.html in any browser. Rendering is deterministic from the
item-13 session checklist (the text the session already printed, or
progress-file "checklist" rows) plus this tree's running progress files - no
model composition. A session renders only at session start, at the
every-4-completions reprint and at /done (`render --final`), never per step.
A headless run never renders: render prints {"rendered": false, "reason":
"headless"} and writes nothing.

Tasks that were open at the last render and are gone now move to "done", in
completion order; a new session number starts a fresh done list.

`calls` is kept for a tree whose /done still names it (v19-v22): it renders
the same files and prints one line `board: <board.html> (local only, nothing
to push)`. `pushed` and `account` are kept as no-ops that print one line.
ops/status_board.json is no longer read except its optional "code" (the
page title); a tree may leave the file or delete it.

Standalone: imports nothing from the rest of the kit. ASCII source.
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

CONFIG_REL = Path("ops") / "status_board.json"
STATE_REL = Path("ops") / "loop" / "control" / "board"
PROGRESS_REL = Path("ops") / "loop" / "control" / "progress"
HTML_NAME = "board.html"
REFRESH_S = 60
GROUPS = ("running", "operator", "next", "done")
DONE_KEEP = 30
PROGRESS_MAX_AGE_S = 6 * 3600
TEXT_MAX = 160
_LINE = re.compile(r"^(?:\u2610|\[ \])\s+\+?([A-Za-z0-9][A-Za-z0-9._-]{0,15}):\s+(.+?)\s*$")
_TAIL = re.compile(r"^(.*?)\s+\(([^()]*)\)$")
_HEAD = re.compile(r"^Session\s+(\d+)\s+checklist")
# v20 (CHECKLIST-ETA-CLOCK): `38% ~20m of 32m [2:27PM]` is the ETA part too.
_CLOCK = re.compile(r"^(?:\d{1,3}% ~|started \d{1,2}:\d{2}[AP]M - )")
_OPERATOR = re.compile(r"\b(operator|you|waiting)\b", re.I)
_BLOCKED = re.compile(r"\bblocked\b", re.I)


def is_headless(environ=None):
    """True inside a fleet_headless child: the spawn helper sets
    FLEET_SUBAGENT_FIRST=off and disables background tasks."""
    env = os.environ if environ is None else environ
    return (env.get("FLEET_SUBAGENT_FIRST") == "off"
            or env.get("CLAUDE_CODE_DISABLE_BACKGROUND_TASKS") == "1")


def main_checkout(path):
    """The MAIN working tree for path, even from a linked worktree."""
    path = Path(path).resolve()
    dotgit = path / ".git"
    try:
        raw = dotgit.read_text(encoding="utf-8").strip() if dotgit.is_file() else ""
    except (OSError, UnicodeError):
        raw = ""
    if raw.startswith("gitdir:"):
        gitdir = Path(raw.split(":", 1)[1].strip())
        gitdir = (gitdir if gitdir.is_absolute() else path / gitdir).resolve()
        if gitdir.parent.name == "worktrees":
            return gitdir.parents[2]
    return path


def _clip(text):
    text = " ".join(str(text or "").split())
    text = text.encode("ascii", "replace").decode("ascii")
    return text if len(text) <= TEXT_MAX else text[:TEXT_MAX - 3] + "..."


def fmt_eta(eta_s):
    """Item 3 ETA units: s under 120 s, m under 120 m, h beyond."""
    s = max(0, int(eta_s))
    if s < 120:
        return f"~{s}s"
    if s < 7200:
        return f"~{round(s / 60)}m"
    return f"~{round(s / 3600)}h"


def parse_checklist(text):
    """(session or None, rows) from a printed item-13 checklist. The /done box,
    the header and the trailing note line are not rows."""
    session, rows = None, []
    for raw in str(text).splitlines():
        s = raw.strip()
        m = _HEAD.match(s)
        if m:
            session = int(m.group(1))
            continue
        m = _LINE.match(s)
        if not m:
            continue
        rid, rest = m.group(1), m.group(2)
        state = eta = None
        t = _TAIL.match(rest)
        if t:
            rest, inner = t.group(1), t.group(2)
            parts = [p.strip() for p in inner.split(",")]
            if len(parts) > 1 and (parts[-1].startswith("~") or _CLOCK.match(parts[-1])):
                eta = parts[-1]
                parts = parts[:-1]
            state = ", ".join(parts) or None
        rows.append({"id": rid, "task": rest, "state": state, "eta": eta})
    return session, rows


def rows_from_progress_checklist(items):
    """Progress-file "checklist" rows {id, task, state, eta_s} -> parse rows.
    Item 13 d lists remaining tasks only; a row still marked done is skipped
    (render then moves it to done like any vanished task)."""
    out = []
    for r in items or ():
        if str(r.get("state") or "").strip().lower() in ("done", "complete", "completed"):
            continue
        eta_s = r.get("eta_s")
        out.append({"id": str(r["id"]), "task": r["task"], "state": r.get("state"),
                    "eta": None if eta_s is None else fmt_eta(eta_s)})
    return out


def classify(state):
    """(group, chip state) for a checklist state."""
    if not state or state.strip().lower() == "pending":
        return "next", "queued"
    if _OPERATOR.search(state):
        return "operator", "waiting"
    if _BLOCKED.search(state):
        return "next", "blocked"
    return "running", "running"


def running_progress(root, clock=time.time):
    """Rows for this tree's progress files with status running, fresh mtime."""
    pdir = Path(root) / PROGRESS_REL
    out = []
    try:
        files = sorted(pdir.glob("*.json"))
    except OSError:
        return out
    now = clock()
    for f in files:
        try:
            if now - f.stat().st_mtime > PROGRESS_MAX_AGE_S:
                continue
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            continue
        if not isinstance(d, dict) or d.get("status") != "running":
            continue
        task = str(d.get("task") or f.stem)
        detail = []
        if isinstance(d.get("pct"), (int, float)):
            detail.append(f"{int(d['pct'])} percent")
        if isinstance(d.get("eta_s"), (int, float)):
            detail.append(fmt_eta(d["eta_s"]))
        out.append({"id": task[:24], "task": d.get("step") or task,
                    "detail": ", ".join(detail)})
    return out


def _load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return default


def _write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="ascii", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)


def dumps_rows(rows):
    """status.json text: one row per line, sorted keys, ASCII, LF."""
    if not rows:
        return "[]\n"
    return "[\n" + ",\n".join(json.dumps(r, sort_keys=True, ensure_ascii=True)
                              for r in rows) + "\n]\n"


def build(session, rows, state, final=False, progress=()):
    """Pure: (status rows, new state). state = {"session", "open": {id: task},
    "done": [{id, task, detail}], "version"}."""
    same = state.get("session") == session
    prev_open = dict(state.get("open") or {}) if same else {}
    done = list(state.get("done") or []) if same else []
    done_ids = {d["id"] for d in done}
    now_ids = [r["id"] for r in rows]
    for rid, task in prev_open.items():
        if rid not in now_ids and rid not in done_ids:
            done.append({"id": rid, "task": task, "detail": ""})
            done_ids.add(rid)
    if final:
        for r in rows:
            if r["id"] not in done_ids:
                done.append({"id": r["id"], "task": _clip(r["task"]), "detail": ""})
                done_ids.add(r["id"])
        rows = []
    done = done[-DONE_KEEP:]
    out = []
    seqs = {g: 0 for g in GROUPS}
    for r in rows:
        if r["id"] in done_ids:
            continue
        group, chip = classify(r.get("state"))
        seqs[group] += 1
        shown = r.get("state") if (group != "next" or chip == "blocked") else None
        detail = ", ".join(x for x in (shown, r.get("eta")) if x)
        out.append({"id": r["id"], "group": group, "seq": seqs[group],
                    "task": _clip(r["task"]), "state": chip, "detail": _clip(detail)})
    if not final:
        for p in progress:
            if p["id"] in now_ids:
                continue
            seqs["running"] += 1
            out.append({"id": _clip(p["id"]), "group": "running", "seq": seqs["running"],
                        "task": _clip(p["task"]), "state": "running",
                        "detail": _clip(p["detail"])})
    for i, d in enumerate(done, 1):
        out.append({"id": d["id"], "group": "done", "seq": i, "task": _clip(d["task"]),
                    "state": "done", "detail": _clip(d.get("detail"))})
    order = {g: i for i, g in enumerate(GROUPS)}
    out.sort(key=lambda r: (order[r["group"]], r["seq"]))
    new_state = {"session": session,
                 "open": {r["id"]: _clip(r["task"]) for r in rows if r["id"] not in done_ids},
                 "done": done, "version": state.get("version")}
    return out, new_state


GROUP_TITLES = (("operator", "Waiting on you", "Physical acts and grants only you can do."),
                ("running", "Running now", "Background agents working at this moment."),
                ("next", "Up next", "In execution order."),
                ("done", "Done", "This session, newest first."))

PAGE_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="__REFRESH__">
<title>__TITLE__</title>
<style>
:root { color-scheme: light dark; --bg: #faf9f5; --panel: #ffffff; --fg: #1f1e1d; --muted: #6b6a66; --line: #e3e1da; --ok: #2e7d4f; --warn: #a15c00; --bad: #b3261e; }
@media (prefers-color-scheme: dark) { :root { --bg: #1f1e1d; --panel: #2a2927; --fg: #f0eee8; --muted: #a8a69f; --line: #3d3b38; --ok: #6cc08b; --warn: #e0a54a; --bad: #f08a80; } }
body { margin: 0; background: var(--bg); color: var(--fg); font: 15px/1.45 system-ui, sans-serif; }
main { max-width: 72rem; margin: 0 auto; padding: 16px; display: flex; flex-direction: column; gap: 16px; }
h1 { font-weight: 500; font-size: 1.5rem; margin: 0; }
.take { color: var(--muted); margin: 4px 0 0; font-size: .875rem; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr)); gap: 12px; }
.tile, .card { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 12px; min-width: 0; }
.tile.you { border-color: var(--warn); }
.lbl { font-size: .8rem; color: var(--muted); display: block; }
.num { font-size: 1.5rem; font-variant-numeric: tabular-nums; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 24rem), 1fr)); gap: 12px; }
h2 { font-size: 1rem; font-weight: 600; margin: 0; }
.note { font-size: .8rem; color: var(--muted); margin: 2px 0 8px; }
.wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: .875rem; }
th { text-align: left; font-size: .75rem; color: var(--muted); font-weight: 500; padding: 4px 8px 4px 0; border-bottom: 1px solid var(--line); }
td { padding: 6px 8px 6px 0; border-bottom: 1px solid var(--line); vertical-align: top; }
tr:last-child td { border-bottom: none; }
.id, .detail { font-size: .75rem; color: var(--muted); }
.id { white-space: nowrap; }
.chip { display: inline-block; font-size: .75rem; padding: 0 8px; border-radius: 999px; border: 1px solid var(--line); color: var(--muted); white-space: nowrap; }
.chip.running { color: var(--fg); border-color: var(--fg); }
.chip.waiting { color: var(--warn); border-color: var(--warn); }
.chip.blocked { color: var(--bad); border-color: var(--bad); }
.chip.done { color: var(--ok); border-color: var(--ok); }
.empty { font-size: .8rem; color: var(--muted); }
</style>
</head>
<body>
<main>
"""
_CODE = re.compile(r"^[A-Z0-9]{1,8}$")


def _esc(text):
    return (str(text or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def page_html(title, rows, updated):
    """board.html text: static, self-contained, ASCII (rows as build() made them)."""
    t = _esc(_clip(title))
    counts = {g: 0 for g in GROUPS}
    for r in rows:
        if r["group"] != "operator" or r["state"] == "waiting":
            counts[r["group"]] += 1
    out = [PAGE_HEAD.replace("__REFRESH__", str(REFRESH_S)).replace("__TITLE__", t)
           + "<header><h1>" + t + "</h1>",
           "<p class=\"take\">The session checklist: what waits on you, what runs now, "
           "what comes next and what is done. Rendered locally " + _esc(updated) + ".</p></header>",
           "<section class=\"tiles\" aria-label=\"Counts\">"]
    for g, label in (("running", "Running now"), ("operator", "Waiting on you"),
                     ("next", "Up next"), ("done", "Done")):
        cls = "tile you" if g == "operator" else "tile"
        out.append(f"<div class=\"{cls}\"><span class=\"lbl\">{label}</span>"
                   f"<span class=\"num\">{counts[g]}</span></div>")
    out.append("</section>")
    out.append("<section class=\"grid\">")
    for g, h2, note in GROUP_TITLES:
        mine = sorted((r for r in rows if r["group"] == g),
                      key=lambda r: -r["seq"] if g == "done" else r["seq"])
        out.append(f"<article class=\"card\"><h2>{h2}</h2><p class=\"note\">{note}</p>")
        if not mine:
            out.append("<p class=\"empty\">Nothing here right now.</p></article>")
            continue
        out.append("<div class=\"wrap\"><table><thead><tr><th>ID</th><th>Task</th>"
                   "<th>State</th><th>Note</th></tr></thead><tbody>")
        for r in mine:
            out.append("<tr><td class=\"id\">" + _esc(r["id"]) + "</td><td>" + _esc(r["task"])
                       + "</td><td><span class=\"chip " + _esc(r["state"]) + "\">"
                       + _esc(r["state"]) + "</span></td><td class=\"detail\">"
                       + _esc(r["detail"]) + "</td></tr>")
        out.append("</tbody></table></div></article>")
    out.extend(("</section>", "</main>", "</body>", "</html>"))
    return "\n".join(out) + "\n"


def render(root, session, rows, final=False, environ=None, clock=time.time):
    """Write status.json, state.json and board.html locally; return a summary
    dict. Nothing is pushed anywhere (v23)."""
    if is_headless(environ):
        return {"rendered": False, "reason": "headless"}
    root = main_checkout(root)
    cfg = _load(root / CONFIG_REL, {})
    code = str(cfg.get("code") or "") if isinstance(cfg, dict) else ""
    sdir = root / STATE_REL
    state = _load(sdir / "state.json", {})
    state = state if isinstance(state, dict) else {}
    prog = running_progress(root, clock=clock)
    out, new_state = build(int(session), rows, state, final=final, progress=prog)
    new_state.pop("version", None)
    at = time.strftime("%Y-%m-%d %H:%M", time.localtime(clock()))
    title = (code + " status" if _CODE.match(code) else "Status board") + \
        f" - session {int(session)}"
    _write(sdir / "status.json", dumps_rows(out))
    _write(sdir / "state.json", json.dumps(new_state, indent=1, sort_keys=True) + "\n")
    _write(sdir / HTML_NAME, page_html(title, out, at))
    return {"rendered": True, "file": str(sdir / "status.json"),
            "html": str(sdir / HTML_NAME), "rows": len(out)}


NL = chr(10)


def calls_text(plan):
    """The `calls` verb's one line (v23: nothing to push)."""
    if not plan.get("rendered"):
        return "board not rendered: " + str(plan.get("reason", "unknown")) + NL
    return "board: " + plan["html"] + " (local only, nothing to push)" + NL


def main(argv=None):
    ap = argparse.ArgumentParser(prog="fleet_board")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for verb, hlp in (("render", "render the local board; print a JSON summary"),
                      ("calls", "render the local board; print its path (v19-v22 name)")):
        r = sub.add_parser(verb, help=hlp)
        r.add_argument("--root", default=".")
        r.add_argument("--session", type=int)
        r.add_argument("--checklist", help="checklist text file (default stdin)")
        r.add_argument("--progress", help="a progress file whose 'checklist' rows to use")
        r.add_argument("--final", action="store_true", help="/done: every task done")
    p = sub.add_parser("pushed", help="v23 no-op (the board is local only)")
    p.add_argument("--root", default=".")
    p.add_argument("--version", type=int)
    ac = sub.add_parser("account", help="v23 no-op (the board is local only)")
    ac.add_argument("--root", default=".")
    ac.add_argument("--url")
    ac.add_argument("--label")
    a = ap.parse_args(argv)
    if a.cmd in ("pushed", "account"):
        print("v23: the status board is local only; nothing to record")
        return 0
    if a.progress:
        d = _load(a.progress, {})
        session, rows = a.session, rows_from_progress_checklist(d.get("checklist"))
    else:
        text = Path(a.checklist).read_text(encoding="utf-8") if a.checklist else sys.stdin.read()
        session, rows = parse_checklist(text)
        session = a.session if a.session is not None else session
    if session is None:
        print(json.dumps({"rendered": False, "reason": "no session number"}))
        return 2
    plan = render(a.root, session, rows, final=a.final)
    if a.cmd == "calls":
        sys.stdout.write(calls_text(plan))
    else:
        print(json.dumps(plan, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
