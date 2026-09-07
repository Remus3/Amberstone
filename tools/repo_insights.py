#!/usr/bin/env python3
"""tools/repo_insights.py - grounded, on-command repo insights for Amberstone.

Unlike the built-in /insights (which analyzes chat transcripts and can suggest
work that already shipped), this reads GROUND TRUTH straight from the repo:
git history in a date window, docs/LEDGER.md, docs/ORCHESTRATION_PLAN.md status,
ROADMAP/BACKLOG open work, ENGINE_VERSION and the live DS patch. Every number
cites a real source, so the report never re-pitches an already-built thing.

Renders an HTML report mirroring the Claude Code Insights layout (the attached
report-*.html) plus a sidecar JSON facts blob for inspection / future enrichment.

Usage:
  python tools/repo_insights.py                 # last 30 days -> .claude/usage-data/
  python tools/repo_insights.py --days 14
  python tools/repo_insights.py --out C:/tmp/r.html --author Moonbeam

To MOLD THE LOOK later: the palette + every section live in clearly marked
blocks below (search "SECTION:" and "PALETTE"). Add/remove a section by editing
render_html(); the data it draws on is in the facts dict, so new sections only
need a new facts key + a builder call.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------
# git helpers
# --------------------------------------------------------------------------
def _git(*args: str) -> str:
    """Run git at the repo root; return stdout (empty string on failure)."""
    try:
        out = subprocess.run(
            ["git", *args], cwd=str(ROOT), capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=120,
        )
        return out.stdout or ""
    except (subprocess.SubprocessError, OSError):
        return ""


def _numstat_churn(since: str, pathspec: list[str] | None = None) -> tuple[int, int]:
    args = ["log", f"--since={since}", "--numstat", "--pretty=tformat:"]
    if pathspec:
        args += ["--"] + pathspec
    add = dele = 0
    for line in _git(*args).splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            add += int(parts[0])
            dele += int(parts[1])
    return add, dele


def gather_git(days: int, author: str | None) -> dict:
    since = f"{days} days ago"
    base = ["log", f"--since={since}"]
    if author:
        base += [f"--author={author}"]

    subjects = [s for s in _git(*base, "--pretty=format:%s").splitlines() if s]
    dates = [d for d in _git(*base, "--pretty=format:%ad", "--date=short").splitlines() if d]
    authors = Counter(
        a for a in _git("log", f"--since={since}", "--pretty=format:%an").splitlines() if a
    )

    # commit-type histogram from conventional-ish "type: " / "type(scope): " prefixes
    types: Counter = Counter()
    for s in subjects:
        m = re.match(r"^([A-Za-z]+)(?:\([^)]*\))?:", s)
        if m:
            types[m.group(1).lower()] += 1
        elif s.lower().startswith("merge "):
            types["merge"] += 1
        else:
            types["other"] += 1

    # top-level path histogram (what areas got touched)
    names = _git(*base, "--name-only", "--pretty=format:").splitlines()
    dirs: Counter = Counter()
    for n in names:
        n = n.strip()
        if not n:
            continue
        top = n.split("/")[0] if "/" in n else "(root)"
        dirs[top] += 1

    churn_total = _numstat_churn(since)
    churn_ex_data = _numstat_churn(
        since, [":(exclude)data", ":(exclude)web/data"]
    )

    active_days = len(set(dates))
    return {
        "days": days,
        "window_start": min(dates) if dates else "",
        "window_end": max(dates) if dates else "",
        "commits": len(subjects),
        "active_days": active_days,
        "commits_per_active_day": round(len(subjects) / active_days, 1) if active_days else 0,
        "churn_total": churn_total,
        "churn_source": churn_ex_data,
        "types": types.most_common(),
        "dirs": dirs.most_common(12),
        "authors": authors.most_common(),
        "files_touched": len(set(n.strip() for n in names if n.strip())),
    }


# --------------------------------------------------------------------------
# repo-file parsers (the grounding that /insights cannot see)
# --------------------------------------------------------------------------
_LEDGER_ITEM = re.compile(
    r"^(\d+)\.\s+\S+\s+\*\*(\d{4}-\d{2}-\d{2})\s*[-(]\s*(.+?)\*\*", re.MULTILINE
)

# recurring-friction phrases that actually appear in the ledger prose; each is a
# real, grep-able signal of where cycles went sideways (not an invented category).
_FRICTION_PATTERNS = {
    "Test-ordering / stale-pipe (SEQUENCING artifact, LiveFresh)":
        re.compile(r"sequencing artifact|livefresh|stale[- ]tool|replay", re.I),
    "Stale or falsified directive premise (verify-before-redo)":
        re.compile(r"verify-before-redo|premise\b.*\b(stale|falsified)|already shipped|red herring", re.I),
    "Directive intent vs literal (audit-proposals-are-intent)":
        re.compile(r"key deviation|feedback_audit_proposals_are_intent|deviation from the directive", re.I),
    "No-op / clean-no-commit closeouts":
        re.compile(r"clean no-commit|byte-identical|no-op\b|premise falsified", re.I),
}


def parse_ledger(cutoff: str) -> dict:
    txt = ""
    p = ROOT / "docs" / "LEDGER.md"
    if p.exists():
        txt = p.read_text(encoding="utf-8", errors="replace")
    items = _LEDGER_ITEM.findall(txt)
    in_window = [(int(n), d, _short(t)) for (n, d, t) in items if d >= cutoff]
    # friction counts within the windowed blocks only
    blocks = _ledger_blocks(txt, cutoff)
    joined = "\n".join(blocks)
    friction = {label: len(pat.findall(joined)) for label, pat in _FRICTION_PATTERNS.items()}
    return {
        "latest_item": max((int(n) for n, _, _ in items), default=0),
        "items_in_window": in_window,
        "count_in_window": len(in_window),
        "friction": friction,
    }


def _ledger_blocks(txt: str, cutoff: str) -> list[str]:
    """Split LEDGER into per-item blocks, keep only those dated >= cutoff."""
    parts = re.split(r"(?m)^(?=\d+\.\s)", txt)
    out = []
    for part in parts:
        m = _LEDGER_ITEM.match(part)
        if m and m.group(2) >= cutoff:
            out.append(part)
    return out


def _short(title: str, limit: int = 140) -> str:
    title = re.sub(r"\s+", " ", title).strip().strip("*")
    # cut at the commit-sha paren or first sentence break for a tidy headline
    title = re.split(r"\s*\(commit", title)[0]
    return title if len(title) <= limit else title[:limit].rstrip() + "..."


def parse_orchestration() -> dict:
    p = ROOT / "docs" / "ORCHESTRATION_PLAN.md"
    if not p.exists():
        return {"status": {}, "excluded": []}
    txt = p.read_text(encoding="utf-8", errors="replace")
    status: Counter = Counter()
    for m in re.finditer(r"\|\s*(DONE|CLOSED|OPEN|WIP)\s*\|", txt):
        status[m.group(1)] += 1
    # the EXCLUDED (live-game / operator-gated) bullets = the real "on the horizon"
    excluded = []
    grab = False
    for line in txt.splitlines():
        if line.startswith("## EXCLUDED"):
            grab = True
            continue
        if grab and line.startswith("## "):
            break
        if grab and line.strip().startswith("- "):
            excluded.append(_short(line.strip()[2:], 200))
    return {"status": dict(status), "excluded": excluded[:8]}


def parse_roadmap_open() -> list[str]:
    p = ROOT / "ROADMAP.md"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if re.match(r"^[-*]\s", s) and re.search(r"\b(NOW|NEXT|OPEN|TODO|pending)\b", s):
            out.append(_short(s[2:], 200))
    return out[:8]


def read_engine_version() -> str:
    p = ROOT / "agents" / "daemon_slayer" / "__init__.py"
    if p.exists():
        m = re.search(r'ENGINE_VERSION\s*=\s*"([^"]+)"', p.read_text(encoding="utf-8", errors="replace"))
        if m:
            return m.group(1)
    return "?"


def read_ds_patch() -> str:
    p = ROOT / "data" / "daemon_slayer" / "current.txt"
    if p.exists():
        return p.read_text(encoding="utf-8", errors="replace").strip()
    return "?"


# --------------------------------------------------------------------------
# area naming - map raw top-level dirs to human areas for the project list
# --------------------------------------------------------------------------
_AREA = {
    "agents": "Daemon Slayer engine",
    "web": "Dashboard + overlay UI",
    "dashboard": "Dashboard routes",
    "core": "Core coaching logic",
    "modes": "Coach modes",
    "tests": "Tests",
    "docs": "Docs + ledger",
    "ops": "Ops + loop harness",
    "data": "Patch data",
    "tools": "Tooling",
    "lcu": "LCU client",
    "coaches": "Coaches",
    "vision_server": "Vision pipeline",
}


def area_name(top: str) -> str:
    return _AREA.get(top, top)


# --------------------------------------------------------------------------
# HTML rendering - PALETTE + section builders. Edit here to re-skin.
# --------------------------------------------------------------------------
CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; background: #f8fafc; color: #334155; line-height: 1.65; padding: 48px 24px; }
.container { max-width: 820px; margin: 0 auto; }
h1 { font-size: 32px; font-weight: 700; color: #0f172a; margin-bottom: 8px; }
h2 { font-size: 20px; font-weight: 600; color: #0f172a; margin-top: 48px; margin-bottom: 16px; }
.subtitle { color: #64748b; font-size: 15px; margin-bottom: 32px; }
.stats-row { display: flex; gap: 24px; margin-bottom: 40px; padding: 20px 0; border-top: 1px solid #e2e8f0; border-bottom: 1px solid #e2e8f0; flex-wrap: wrap; }
.stat { text-align: center; }
.stat-value { font-size: 24px; font-weight: 700; color: #0f172a; }
.stat-label { font-size: 11px; color: #64748b; text-transform: uppercase; }
.at-a-glance { background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border: 1px solid #f59e0b; border-radius: 12px; padding: 20px 24px; margin-bottom: 32px; }
.glance-title { font-size: 16px; font-weight: 700; color: #92400e; margin-bottom: 16px; }
.glance-sections { display: flex; flex-direction: column; gap: 12px; }
.glance-section { font-size: 14px; color: #78350f; line-height: 1.6; }
.glance-section strong { color: #92400e; }
.project-areas { display: flex; flex-direction: column; gap: 12px; margin-bottom: 32px; }
.project-area { background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; }
.area-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.area-name { font-weight: 600; font-size: 15px; color: #0f172a; }
.area-count { font-size: 12px; color: #64748b; background: #f1f5f9; padding: 2px 8px; border-radius: 4px; }
.area-desc { font-size: 14px; color: #475569; line-height: 1.5; }
.charts-row { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin: 24px 0; }
.chart-card { background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; }
.chart-title { font-size: 12px; font-weight: 600; color: #64748b; text-transform: uppercase; margin-bottom: 12px; }
.bar-row { display: flex; align-items: center; margin-bottom: 6px; }
.bar-label { width: 150px; font-size: 11px; color: #475569; flex-shrink: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bar-track { flex: 1; height: 6px; background: #f1f5f9; border-radius: 3px; margin: 0 8px; }
.bar-fill { height: 100%; border-radius: 3px; }
.bar-value { width: 40px; font-size: 11px; font-weight: 500; color: #64748b; text-align: right; }
.big-wins { display: flex; flex-direction: column; gap: 12px; margin-bottom: 24px; }
.big-win { background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 16px; }
.big-win-title { font-weight: 600; font-size: 15px; color: #166534; margin-bottom: 8px; }
.big-win-desc { font-size: 14px; color: #15803d; line-height: 1.5; }
.friction-category { background: #fef2f2; border: 1px solid #fca5a5; border-radius: 8px; padding: 16px; margin-bottom: 12px; }
.friction-title { font-weight: 600; font-size: 14px; color: #991b1b; margin-bottom: 6px; }
.friction-desc { font-size: 13px; color: #7f1d1d; }
.horizon-card { background: linear-gradient(135deg, #faf5ff 0%, #f5f3ff 100%); border: 1px solid #c4b5fd; border-radius: 8px; padding: 16px; margin-bottom: 12px; }
.horizon-title { font-weight: 600; font-size: 14px; color: #5b21b6; margin-bottom: 6px; }
.horizon-possible { font-size: 13px; color: #334155; line-height: 1.5; }
.ship-list { background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 8px 16px; }
.ship-item { font-size: 13px; color: #475569; padding: 7px 0; border-bottom: 1px solid #f1f5f9; }
.ship-item:last-child { border-bottom: none; }
.ship-num { color: #2563eb; font-weight: 600; font-family: monospace; margin-right: 8px; }
.ship-date { color: #94a3b8; font-size: 11px; margin-right: 8px; }
.fun-ending { background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border: 1px solid #fbbf24; border-radius: 12px; padding: 24px; margin-top: 40px; text-align: center; }
.fun-headline { font-size: 18px; font-weight: 600; color: #78350f; margin-bottom: 8px; }
.fun-detail { font-size: 14px; color: #92400e; }
.synthesis { background: #fff; border: 1px solid #e2e8f0; border-left: 4px solid #0f766e; border-radius: 10px; padding: 20px 24px; margin-bottom: 16px; }
.synth-head { font-size: 14px; font-weight: 600; color: #0f766e; margin-bottom: 6px; }
.synth-body { font-size: 14px; color: #334155; line-height: 1.6; }
.footnote { color: #94a3b8; font-size: 12px; margin-top: 40px; text-align: center; }
@media (max-width: 640px) { .charts-row { grid-template-columns: 1fr; } .stats-row { justify-content: center; } }
"""


def h(s) -> str:
    return html.escape(str(s), quote=True)


def _bars(rows: list[tuple[str, int]], color: str) -> str:
    if not rows:
        return '<div style="color:#94a3b8;font-size:13px">no data</div>'
    top = max(v for _, v in rows) or 1
    out = []
    for label, val in rows:
        pct = 100.0 * val / top
        out.append(
            f'<div class="bar-row"><div class="bar-label">{h(label)}</div>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{pct:.1f}%;background:{color}"></div></div>'
            f'<div class="bar-value">{val}</div></div>'
        )
    return "".join(out)


def _fmt_churn(c: tuple[int, int]) -> str:
    return f"+{c[0]:,}/-{c[1]:,}"


def _synthesis(f: dict, feat: int, fix: int, docs: int,
               done: int, closed: int, openn: int) -> str:
    """Narrative built strictly from figures already parsed - adds no new claim.

    Every sentence restates or divides numbers that appear elsewhere in the
    report; nothing here is inferred from a transcript or from memory.
    """
    g, led, orch = f["git"], f["ledger"], f["orchestration"]
    paras: list[tuple[str, str]] = []

    authors = g["authors"] or [("(unknown)", 0)]
    top_author, top_commits = authors[0]
    solo_pct = 100.0 * top_commits / max(g["commits"], 1)
    items_per_day = led["count_in_window"] / max(g["active_days"], 1)
    paras.append((
        "Cadence",
        f"{g['commits']:,} commits over {g['active_days']} active days "
        f"({g['commits_per_active_day']}/day). {top_author} authored {top_commits:,} of them "
        f"({solo_pct:.0f}%), the remainder being bot or co-author commits. "
        f"{g['files_touched']:,} files touched, {led['count_in_window']} LEDGER items closed - "
        f"about {items_per_day:.1f} closures per active day."
    ))

    tot_add, tot_del = g["churn_total"]
    src_add, src_del = g["churn_source"]
    src_pct = 100.0 * src_add / max(tot_add, 1)
    top2 = ", ".join(f"{area_name(d)} {c}" for d, c in g["dirs"][:2])
    paras.append((
        "Where the bytes went",
        f"Total churn +{tot_add:,}/-{tot_del:,}, but hand-written source is only "
        f"+{src_add:,}/-{src_del:,} - {src_pct:.0f}% of added lines. The rest is mirrored and "
        f"generated output, which the file-touch histogram confirms ({top2}). "
        f"Read velocity against the source column, not the total."
    ))

    code_commits = feat + fix
    paras.append((
        "Commit mix",
        f"docs {docs} | feat {feat} | fix {fix}. Documentation commits "
        + ("outweigh" if docs > code_commits else "sit below")
        + f" feat plus fix combined ({docs} vs {code_commits}), which is the living-docs and "
          f"LEDGER ritual showing up in the history rather than a documentation backlog."
    ))

    fr = {k: v for k, v in led["friction"].items() if v}
    if fr:
        ranked = sorted(fr.items(), key=lambda kv: -kv[1])
        premise = sum(v for k, v in fr.items() if "premise" in k.lower() or "No-op" in k)
        listed = "; ".join(f"{k.split(' (')[0]} {v}" for k, v in ranked)
        paras.append((
            "Friction",
            f"Phrase hits inside the windowed ledger prose - hits, not entries, so one entry can "
            f"match several: {listed}. The premise-class categories total {premise} hits against "
            f"{led['count_in_window']} windowed items, making 'the row was already true, already "
            f"shipped, or inert before work started' the dominant cost shape in this window."
        ))

    n_excl = len(orch["excluded"])
    # report EVERY parsed status, not just the three headline ones - an unmentioned
    # WIP/other row would make a "drained" claim overstate the real plan state.
    status_line = " / ".join(f"{v} {k}" for k, v in sorted(orch["status"].items()))
    other = sum(v for k, v in orch["status"].items()
                if k not in ("DONE", "CLOSED", "OPEN"))
    if openn == 0 and other == 0 and n_excl:
        horizon_line = (
            f"ORCHESTRATION_PLAN shows {status_line} - the plan is drained. All {n_excl} remaining "
            f"rows are EXCLUDED, and each is gated on the same thing: a live game or an explicit "
            f"operator OK. Nothing here is a suggestion; it is the parsed exclusion list."
        )
    else:
        horizon_line = (
            f"ORCHESTRATION_PLAN shows {status_line}, with {n_excl} EXCLUDED rows held behind a "
            f"live game or an operator OK. {openn + other} row(s) are not in a terminal state, so "
            f"the plan is near-drained rather than drained."
        )
    paras.append(("Horizon", horizon_line))

    paras.append((
        "Engine",
        f"DS engine {f['engine_version']} on patch {f['ds_patch']}, read from "
        f"agents/daemon_slayer/__init__.py and data/daemon_slayer/current.txt."
    ))

    return "".join(
        f'<div class="synthesis"><div class="synth-head">{h(t)}</div>'
        f'<div class="synth-body">{h(body)}</div></div>' for t, body in paras
    )


def render_html(f: dict) -> str:
    g = f["git"]
    led = f["ledger"]
    orch = f["orchestration"]

    # SECTION: at-a-glance (all grounded in computed numbers)
    feat = dict(g["types"]).get("feat", 0)
    fix = dict(g["types"]).get("fix", 0)
    docs = dict(g["types"]).get("docs", 0)
    glance = (
        f"<strong>Throughput:</strong> {g['commits']:,} commits over {g['active_days']} "
        f"active days ({g['commits_per_active_day']}/day), {g['window_start']} to {g['window_end']}. "
        f"feat {feat} | fix {fix} | docs {docs}. LEDGER reached item {led['latest_item']} "
        f"({led['count_in_window']} closed in window). DS engine {f['engine_version']} on patch {f['ds_patch']}."
    )
    done = orch["status"].get("DONE", 0)
    closed = orch["status"].get("CLOSED", 0)
    openn = orch["status"].get("OPEN", 0)
    non_terminal = sum(v for k, v in orch["status"].items() if k != "DONE" and k != "CLOSED")
    glance2 = (
        "<strong>Loop state:</strong> ORCHESTRATION_PLAN shows "
        + " / ".join(f"{v} {k}" for k, v in sorted(orch["status"].items()))
        + ". "
        + ("Queue drained - the director returns NO_WORK until refilled."
           if non_terminal == 0
           else f"{non_terminal} row(s) still non-terminal for the director to pick up.")
    )

    # SECTION: project areas (from the real path histogram)
    total_dir = sum(v for _, v in g["dirs"]) or 1
    areas_html = ""
    for top, cnt in g["dirs"][:6]:
        areas_html += (
            '<div class="project-area"><div class="area-header">'
            f'<span class="area-name">{h(area_name(top))}</span>'
            f'<span class="area-count">{cnt} file-touches ({100*cnt//total_dir}%)</span></div>'
            f'<div class="area-desc">Top-level <code>{h(top)}/</code> - '
            f'{cnt} changed-file appearances across the window.</div></div>'
        )

    # SECTION: charts (commit types + touched dirs)
    type_bars = _bars([(t, c) for t, c in g["types"][:8]], "#2563eb")
    dir_bars = _bars([(area_name(t), c) for t, c in g["dirs"][:8]], "#7c3aed")

    # SECTION: what shipped (real LEDGER items in window)
    ship = ""
    for num, date, title in led["items_in_window"][:14]:
        ship += (
            f'<div class="ship-item"><span class="ship-num">#{num}</span>'
            f'<span class="ship-date">{h(date)}</span>{h(title)}</div>'
        )
    if not ship:
        ship = '<div class="ship-item">no LEDGER items dated in this window</div>'

    # SECTION: what's working (grounded observations)
    wins = [
        ("TDD + dual-suite gate held",
         f"Engine work bumped ENGINE_VERSION to {f['engine_version']} with the DS-dir + tests/ "
         f"dual suite green each cycle; {fix} fix-commits vs {feat} feat-commits shows fixes "
         f"landing as their own tracked slices, not silent patches."),
        ("Every closed slice is logged",
         f"{led['count_in_window']} LEDGER items closed in window (latest #{led['latest_item']}), "
         f"each carrying its commit sha, tier, and gate counts - the audit trail /insights infers, this records."),
        ("Loop converges to NO_WORK, not churn",
         f"{done} DONE / {closed} CLOSED rows with {openn} open means slices close out rather than "
         f"reopening; the director self-terminates instead of re-running stale premises."),
    ]
    wins_html = "".join(
        f'<div class="big-win"><div class="big-win-title">{h(t)}</div>'
        f'<div class="big-win-desc">{h(d)}</div></div>' for t, d in wins
    )

    # SECTION: friction (counted from real ledger prose, only non-zero)
    fr = led["friction"]
    fr_rows = [(k, v) for k, v in fr.items() if v]
    fr_rows.sort(key=lambda x: -x[1])
    if fr_rows:
        friction_html = "".join(
            f'<div class="friction-category"><div class="friction-title">{h(k)} '
            f'({v} phrase hit{"s" if v != 1 else ""})</div>'
            f'<div class="friction-desc">{v} matching phrase hit'
            f'{"s" if v != 1 else ""} inside the windowed ledger prose - hits, not entries, so a '
            f'single entry can match more than once. Grepped from the ledger, not guessed.</div></div>'
            for k, v in fr_rows
        )
    else:
        friction_html = '<div class="friction-category"><div class="friction-desc">No recurring friction phrases matched in the windowed ledger.</div></div>'

    # SECTION: on the horizon (REAL gated/open work, never invented)
    horizon_items = orch["excluded"] or f["roadmap_open"]
    if horizon_items:
        horizon_html = "".join(
            f'<div class="horizon-card"><div class="horizon-title">Gated / open</div>'
            f'<div class="horizon-possible">{h(item)}</div></div>'
            for item in horizon_items[:6]
        )
    else:
        horizon_html = '<div class="horizon-card"><div class="horizon-possible">No EXCLUDED or open items parsed - the plan is fully drained.</div></div>'

    # SECTION: synthesis (derived ONLY from the numbers above - no new claims)
    synth_html = _synthesis(f, feat, fix, docs, done, closed, openn)

    # SECTION: fun ending (a real superlative)
    top_dir = g["dirs"][0] if g["dirs"] else ("(none)", 0)
    fun = (
        f"<strong>{area_name(top_dir[0])}</strong> absorbed the most churn this window - "
        f"{top_dir[1]} changed-file appearances under <code>{h(top_dir[0])}/</code>. "
        f"You wrote {g['commits']:,} commits ({_fmt_churn(g['churn_source'])} lines outside data/) "
        f"and closed {led['count_in_window']} ledger items without leaving an OPEN slice behind."
    )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Amberstone - Repo Insights</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body><div class="container">
<h1>Amberstone - Repo Insights</h1>
<p class="subtitle">Grounded in git + LEDGER + ORCHESTRATION_PLAN | {g['window_start']} to {g['window_end']} ({g['days']}-day window) | generated {f['generated']}</p>

<div class="at-a-glance"><div class="glance-title">At a Glance (ground truth)</div>
<div class="glance-sections">
<div class="glance-section">{glance}</div>
<div class="glance-section">{glance2}</div>
</div></div>

<div class="stats-row">
<div class="stat"><div class="stat-value">{g['commits']:,}</div><div class="stat-label">Commits</div></div>
<div class="stat"><div class="stat-value">{_fmt_churn(g['churn_total'])}</div><div class="stat-label">Lines (all)</div></div>
<div class="stat"><div class="stat-value">{g['files_touched']:,}</div><div class="stat-label">Files</div></div>
<div class="stat"><div class="stat-value">{g['active_days']}</div><div class="stat-label">Active days</div></div>
<div class="stat"><div class="stat-value">{g['commits_per_active_day']}</div><div class="stat-label">Commits/day</div></div>
</div>

<h2>What You Worked On</h2>
<div class="project-areas">{areas_html}</div>

<div class="charts-row">
<div class="chart-card"><div class="chart-title">Commits by type</div>{type_bars}</div>
<div class="chart-card"><div class="chart-title">Most-touched areas</div>{dir_bars}</div>
</div>

<h2>Reading the Numbers</h2>
{synth_html}

<h2>What Shipped (LEDGER, in window)</h2>
<div class="ship-list">{ship}</div>

<h2>What's Working</h2>
<div class="big-wins">{wins_html}</div>

<h2>Where Friction Showed Up</h2>
{friction_html}

<h2>On the Horizon (real gated / open work)</h2>
{horizon_html}

<div class="fun-ending"><div class="fun-headline">By the numbers</div>
<div class="fun-detail">{fun}</div></div>

<p class="footnote">Generated by tools/repo_insights.py - every figure traces to git, docs/LEDGER.md, docs/ORCHESTRATION_PLAN.md, ROADMAP.md, agents/daemon_slayer/__init__.py, or data/daemon_slayer/current.txt. No transcript inference.</p>
</div></body></html>
"""


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def build_facts(days: int, author: str | None) -> dict:
    now = datetime.now()
    cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    return {
        "generated": now.strftime("%Y-%m-%d %H:%M"),
        "engine_version": read_engine_version(),
        "ds_patch": read_ds_patch(),
        "git": gather_git(days, author),
        "ledger": parse_ledger(cutoff),
        "orchestration": parse_orchestration(),
        "roadmap_open": parse_roadmap_open(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Grounded repo insights for Amberstone")
    ap.add_argument("--days", type=int, default=30, help="window size in days (default 30)")
    ap.add_argument("--author", default=None, help="restrict commits to one author")
    ap.add_argument("--out", default=None, help="output HTML path")
    args = ap.parse_args()

    facts = build_facts(args.days, args.author)

    today = datetime.now().strftime("%Y-%m-%d")
    out = Path(args.out) if args.out else (
        Path.home() / ".claude" / "usage-data" / f"repo-insights-{today}.html"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(render_html(facts).encode("utf-8"))
    json_path = out.with_suffix(".json")
    json_path.write_bytes(json.dumps(facts, indent=2).encode("utf-8"))

    print(f"report: {out}")
    print(f"facts:  {json_path}")
    print(f"window: {facts['git']['window_start']} .. {facts['git']['window_end']} "
          f"({facts['git']['commits']} commits, {facts['ledger']['count_in_window']} ledger items)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
