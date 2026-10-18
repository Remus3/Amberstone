# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 the operator - the kit's owner and sole copyright holder. See NOTICE.
"""Fleet kit v19 - STATUS BOARD (FLEET-COMMON 18): the per-tree claude.ai board.
Vendored byte-for-byte at ops/fleet_kit/ and pinned by MANIFEST.json. Do NOT
edit a vendored copy: report the defect to MAIN.

Every live tree has one Dashboard-type artifact (its URL in the tree's own
`ops/status_board.json`: {"url"}, optional "code" and "dataset_version").
The board page reads ONE dataset, `datasets/board`, whose source is an uploaded `status.json`
asset: a JSON array of rows

    {"id", "group": running|operator|next|done, "seq", "task", "state", "detail"}

This helper RENDERS that file deterministically from the item-13 session
checklist (the text the session already printed, or progress-file "checklist"
rows) plus this tree's running progress files - no model composition. Why: the
operator wants a board per repo at minimal token cost, so a push is exactly

    1. python ops/fleet_kit/fleet_board.py render --session <n> < checklist.txt
       -> prints {"push", "file", "board", "if_version", "data"}
    2. Artifact publish  url=<board> file_path=<file> asset=true  -> /_blob/<id>
    3. ArtifactData update url=<board> collection=datasets doc_id=board
       if_version=<if_version> data=<data with "__URL__" replaced by the blob url>

`calls` (same arguments as render) does step 1 and prints steps 2 and 3
as the exact tool calls, so the session spends no tokens composing them;
pushes happen only at session start, at the every-4-completions reprint
and at /done (`render --final`), never per step. A headless run never pushes
(no artifact tools assumed): render prints {"push": false, "reason":
"headless"} and writes nothing. If step 3 fails on a version mismatch, run
`pushed --version <current>` and redo step 3 with that pin.

State between pushes lives in <main checkout>/ops/loop/control/board/
(state.json, status.json). Tasks that were open at the last render and are
gone now move to "done", in completion order; a new session number starts a
fresh done list. `page --title <t>` prints the board's index.html (the one
page every board uses; ASCII, no names or paths).

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
URL_PLACEHOLDER = "__URL__"
GROUPS = ("running", "operator", "next", "done")
DONE_KEEP = 30
PROGRESS_MAX_AGE_S = 6 * 3600
TEXT_MAX = 160
_LINE = re.compile(r"^(?:\u2610|\[ \])\s+\+?([A-Za-z0-9][A-Za-z0-9._-]{0,15}):\s+(.+?)\s*$")
_TAIL = re.compile(r"^(.*?)\s+\(([^()]*)\)$")
_HEAD = re.compile(r"^Session\s+(\d+)\s+checklist")
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
            if len(parts) > 1 and parts[-1].startswith("~"):
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


def dataset_update(code, session, at):
    """The datasets/board update fields; the session swaps in the blob url."""
    return {"source": {"kind": "file", "format": "json", "name": "status.json",
                       "url": URL_PLACEHOLDER},
            "updated": {"at": at, "by": f"{code} session {int(session)}"}}


def render(root, session, rows, final=False, environ=None, clock=time.time):
    """Write status.json + state; return the push plan (a dict)."""
    if is_headless(environ):
        return {"push": False, "reason": "headless"}
    root = main_checkout(root)
    cfg = _load(root / CONFIG_REL, {})
    if not cfg.get("url"):
        return {"push": False, "reason": f"no url in {CONFIG_REL.as_posix()}"}
    sdir = root / STATE_REL
    state = _load(sdir / "state.json", {})
    if state.get("version") is None:
        state["version"] = int(cfg.get("dataset_version") or 1)
    prog = running_progress(root, clock=clock)
    out, new_state = build(int(session), rows, state, final=final, progress=prog)
    pin = int(new_state["version"])
    new_state["version"] = pin + 1
    _write(sdir / "status.json", dumps_rows(out))
    _write(sdir / "state.json", json.dumps(new_state, indent=1, sort_keys=True) + "\n")
    at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(clock()))
    return {"push": True, "file": str(sdir / "status.json"), "board": cfg["url"],
            "if_version": pin, "rows": len(out),
            "data": dataset_update(cfg.get("code") or root.name, session, at)}


def pushed(root, version):
    """Record the server's current datasets/board version after a mismatch."""
    root = main_checkout(root)
    path = root / STATE_REL / "state.json"
    state = _load(path, {})
    state["version"] = int(version)
    _write(path, json.dumps(state, indent=1, sort_keys=True) + "\n")
    return state["version"]


def tool_calls(plan):
    """The two tool calls (name, input) a session makes for a push plan."""
    if not plan.get("push"):
        return []
    return [("Artifact", {"action": "publish", "url": plan["board"],
                          "file_path": plan["file"], "asset": True}),
            ("ArtifactData", {"action": "update", "url": plan["board"],
                              "collection": "datasets", "doc_id": "board",
                              "if_version": plan["if_version"], "data": plan["data"]})]


NL = chr(10)


def calls_text(plan):
    """Printable: one line per tool call plus one rule line; a no-push plan
    prints one `no push: <reason>` line."""
    calls = tool_calls(plan)
    if not calls:
        return "no push: " + str(plan.get("reason", "unknown")) + NL
    out = [f"{i} {name} {json.dumps(inp, sort_keys=True, separators=(',', ':'))}"
           for i, (name, inp) in enumerate(calls, 1)]
    out.append(f"then: in call 2 replace {URL_PLACEHOLDER} with the url call 1 returns; "
               "on a version mismatch run `fleet_board.py pushed --version <current>` and "
               "redo call 2 pinned to <current>")
    return NL.join(out) + NL


PAGE = r"""<style>
.fb { display: flex; flex-direction: column; gap: var(--cds-gap-lg); font-family: var(--font-anthropic-sans); }
.fb-head h1 { font-family: var(--font-anthropic-serif); font-weight: 400; font-size: var(--cds-font-size-title); margin: 0; text-wrap: balance; }
.fb-take { color: var(--color-fg-muted); font-size: var(--cds-font-size-body); margin: var(--cds-gap-xs) 0 0; }
.fb-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 9rem), 1fr)); gap: var(--cds-gap-md); }
.fb-tile { background: var(--color-panel); border: 1px solid var(--color-border-line); border-radius: var(--cds-radius); padding: var(--cds-pad-md); display: flex; flex-direction: column; gap: var(--cds-gap-xs); }
.fb-tile .lbl { font-size: var(--cds-font-size-caption); color: var(--color-fg-muted); letter-spacing: .02em; }
.fb-tile .num { font-family: var(--font-anthropic-serif); font-weight: 400; font-size: var(--cds-font-size-title); font-variant-numeric: tabular-nums; min-height: 1.2em; }
.fb-tile.you { border-color: var(--color-warn); }
.fb-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 24rem), 1fr)); gap: var(--cds-gap-md); }
.fb-card { background: var(--color-panel); border: 1px solid var(--color-border-line); border-radius: var(--cds-radius); padding: var(--cds-pad-lg); min-width: 0; }
.fb-card h2 { font-size: var(--cds-font-size-heading); font-weight: var(--cds-font-weight-medium); margin: 0; }
.fb-note { font-size: var(--cds-font-size-caption); color: var(--color-fg-muted); margin: var(--cds-gap-xs) 0 var(--cds-gap-sm); }
.fb-wrap { overflow-x: auto; }
.fb-card table { width: 100%; border-collapse: collapse; font-size: var(--cds-font-size-body); }
.fb-card th { text-align: left; font-size: var(--cds-font-size-caption); color: var(--color-fg-muted); font-weight: var(--cds-font-weight-medium); padding: var(--cds-pad-xs) var(--cds-pad-sm) var(--cds-pad-xs) 0; border-bottom: 1px solid var(--color-border-line); }
.fb-card td { padding: var(--cds-pad-sm) var(--cds-pad-sm) var(--cds-pad-sm) 0; border-bottom: 1px solid var(--color-border-line); vertical-align: top; }
.fb-card tbody tr:last-child td { border-bottom: none; }
.fb-id { white-space: nowrap; font-size: var(--cds-font-size-caption); color: var(--color-fg-muted); font-variant-numeric: tabular-nums; }
.fb-detail { font-size: var(--cds-font-size-caption); color: var(--color-fg-muted); }
.fb-chip { display: inline-block; font-size: var(--cds-font-size-caption); padding: 0 var(--cds-pad-sm); border-radius: 999px; border: 1px solid var(--color-border-line); color: var(--color-fg-muted); white-space: nowrap; }
.fb-chip[data-state=running] { color: var(--color-fg); border-color: var(--color-fg); }
.fb-chip[data-state=waiting] { color: var(--color-warn); border-color: var(--color-warn); }
.fb-chip[data-state=blocked] { color: var(--color-bad); border-color: var(--color-bad); }
.fb-chip[data-state=done] { color: var(--color-ok); border-color: var(--color-ok); }
.fb-empty { font-size: var(--cds-font-size-caption); color: var(--color-fg-muted); padding: var(--cds-pad-sm) 0; }
.fb-fail { display: flex; align-items: center; justify-content: center; gap: var(--cds-gap-xs); color: var(--color-fg-muted); font-size: var(--cds-font-size-caption); min-height: 3rem; }
.fb-fail::before { content: ""; width: .375rem; height: .375rem; border-radius: 50%; background: var(--color-bad); }
[data-dash-source-state=empty] { color: transparent; }
[data-dash-source-state=refreshing] { opacity: .5; transition: opacity var(--cds-dur-slow); }
</style>
<div class="fb">
  <header class="fb-head" id="top">
    <h1>__TITLE__</h1>
    <p class="fb-take">The session checklist: what runs now, what waits on you, what comes next and what is done. Pushed at session start, every fourth completion and /done.</p>
  </header>
  <section class="fb-tiles" aria-label="Counts">
    <div class="fb-tile"><span class="lbl">Running now</span><span class="num dash-skeleton" data-source="counts" data-field="n" data-where="group=running">&mdash;</span></div>
    <div class="fb-tile you"><span class="lbl">Waiting on you</span><span class="num dash-skeleton" data-source="counts" data-field="n" data-where="group=operator">&mdash;</span></div>
    <div class="fb-tile"><span class="lbl">Up next</span><span class="num dash-skeleton" data-source="counts" data-field="n" data-where="group=next">&mdash;</span></div>
    <div class="fb-tile"><span class="lbl">Done</span><span class="num dash-skeleton" data-source="counts" data-field="n" data-where="group=done">&mdash;</span></div>
  </section>
  <section class="fb-grid">
    <article class="fb-card" id="fb-operator"><h2>Waiting on you</h2><p class="fb-note">Physical acts and grants only you can do.</p><div class="fb-fail" hidden>Failed to load</div><div class="fb-wrap"><table data-source="board" data-row-key="id"><thead><tr><th data-field="id">ID</th><th data-field="task">Task</th><th data-field="state">State</th><th data-field="detail">Note</th></tr></thead><tbody></tbody></table></div></article>
    <article class="fb-card" id="fb-running"><h2>Running now</h2><p class="fb-note">Background agents working at this moment.</p><div class="fb-fail" hidden>Failed to load</div><div class="fb-wrap"><table data-source="board" data-row-key="id"><thead><tr><th data-field="id">ID</th><th data-field="task">Task</th><th data-field="state">State</th><th data-field="detail">Note</th></tr></thead><tbody></tbody></table></div></article>
    <article class="fb-card" id="fb-next"><h2>Up next</h2><p class="fb-note">In execution order.</p><div class="fb-fail" hidden>Failed to load</div><div class="fb-wrap"><table data-source="board" data-row-key="id"><thead><tr><th data-field="id">ID</th><th data-field="task">Task</th><th data-field="state">State</th><th data-field="detail">Note</th></tr></thead><tbody></tbody></table></div></article>
    <article class="fb-card" id="fb-done"><h2>Done</h2><p class="fb-note">This session, newest first.</p><div class="fb-fail" hidden>Failed to load</div><div class="fb-wrap"><table data-source="board" data-row-key="id"><thead><tr><th data-field="id">ID</th><th data-field="task">Task</th><th data-field="state">State</th><th data-field="detail">Note</th></tr></thead><tbody></tbody></table></div></article>
  </section>
</div>
<script>
dash.calc('counts', {
  inputs: ['board'],
  title: 'Tasks per group',
  description: 'Counts board rows per group; for the operator group, only rows still waiting.',
  fn: (board) => ['running', 'operator', 'next', 'done'].map((g) => ({ group: g, n: board.filter((r) => r.group === g && (g !== 'operator' || r.state === 'waiting')).length }))
});
const FB_GROUPS = [['running', 'fb-running'], ['operator', 'fb-operator'], ['next', 'fb-next'], ['done', 'fb-done']];
dash.onData(() => {
  const b = dash.data('board');
  const c = dash.data('counts');
  document.querySelectorAll('[data-source="counts"]').forEach((el) => {
    const g = new URLSearchParams(el.dataset.where).get('group');
    const row = c.status === 'ok' ? c.data.find((r) => r.group === g) : null;
    el.classList.toggle('dash-skeleton', b.status === 'loading');
    el.textContent = row ? String(row.n) : '\u2014';
  });
  for (const [g, id] of FB_GROUPS) {
    const card = document.getElementById(id);
    const tbody = card.querySelector('tbody');
    card.querySelector('.fb-fail').hidden = b.status !== 'error';
    tbody.replaceChildren();
    if (b.status !== 'ok') continue;
    const rows = b.data.filter((r) => r.group === g).sort((x, y) => g === 'done' ? Number(y.seq) - Number(x.seq) : Number(x.seq) - Number(y.seq));
    if (!rows.length) {
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = 4; td.className = 'fb-empty'; td.textContent = 'Nothing here right now.';
      tr.appendChild(td); tbody.appendChild(tr);
      continue;
    }
    for (const r of rows) {
      const tr = document.createElement('tr');
      const cell = (text, cls) => { const e = document.createElement('td'); if (cls) e.className = cls; e.textContent = text; return e; };
      tr.appendChild(cell(r.id, 'fb-id'));
      tr.appendChild(cell(r.task));
      const st = document.createElement('td');
      const chip = document.createElement('span');
      chip.className = 'fb-chip'; chip.dataset.state = r.state; chip.textContent = r.state;
      st.appendChild(chip); tr.appendChild(st);
      tr.appendChild(cell(r.detail, 'fb-detail'));
      tbody.appendChild(tr);
    }
  }
});
</script>
"""


def page(title):
    """The board's files/index.html text for a title (HTML-escaped, ASCII)."""
    t = _clip(title).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return PAGE.replace("__TITLE__", t)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="fleet_board")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for verb, hlp in (("render", "render status.json; print the push plan"),
                      ("calls", "render status.json; print the two tool calls")):
        r = sub.add_parser(verb, help=hlp)
        r.add_argument("--root", default=".")
        r.add_argument("--session", type=int)
        r.add_argument("--checklist", help="checklist text file (default stdin)")
        r.add_argument("--progress", help="a progress file whose 'checklist' rows to use")
        r.add_argument("--final", action="store_true", help="/done: every task done")
    p = sub.add_parser("pushed", help="record the server's datasets/board version")
    p.add_argument("--root", default=".")
    p.add_argument("--version", type=int, required=True)
    g = sub.add_parser("page", help="print the board index.html")
    g.add_argument("--title", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "page":
        sys.stdout.write(page(a.title))
        return 0
    if a.cmd == "pushed":
        print(json.dumps({"version": pushed(a.root, a.version)}))
        return 0
    if a.progress:
        d = _load(a.progress, {})
        session, rows = a.session, rows_from_progress_checklist(d.get("checklist"))
    else:
        text = Path(a.checklist).read_text(encoding="utf-8") if a.checklist else sys.stdin.read()
        session, rows = parse_checklist(text)
        session = a.session if a.session is not None else session
    if session is None:
        print(json.dumps({"push": False, "reason": "no session number"}))
        return 2
    plan = render(a.root, session, rows, final=a.final)
    if a.cmd == "calls":
        sys.stdout.write(calls_text(plan))
    else:
        print(json.dumps(plan, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
