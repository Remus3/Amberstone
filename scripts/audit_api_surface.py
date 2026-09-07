"""
scripts/audit_api_surface.py
----------------------------
Greps the codebase for every Riot-adjacent HTTP endpoint we touch (LCU,
Riot Web API, LiveClient) and emits a tabular CSV/Markdown report.

Why: Priority 9 of NEXT_SESSION_PLAN_2026-05-10.md. We want a single
source of truth for "which endpoints does RC actually call?" so we can:
  * Catch endpoints we should be using but aren't (Priority 8 mastery
    wiring is a known example).
  * Spot dead callers when an endpoint moves or changes auth.
  * Cross-reference docs/API.md for the internal :8888 surface.

Output:
  * stdout - Markdown report grouped by surface (LCU / Web / LiveClient /
    internal :8888).
  * --csv <path> - flat CSV with (surface, method, endpoint, file, line, snippet).

Heuristics: we grep for endpoint-path literals in source files only; we
do NOT execute the HTTP layer. The grep patterns are conservative
(known prefixes; documented exclusions for fixture/cache directories
like data/, docs/, _archive/, WAKEUP_NOTES.md). Runtime-resolved paths
(e.g. f-string interpolations whose root prefix is captured by the
heuristic) are surfaced; deeper dynamic paths require a manual follow-up.

Usage:
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe scripts\\audit_api_surface.py
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe scripts\\audit_api_surface.py --csv data/api_surface.csv
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe scripts\\audit_api_surface.py --surface lcu  # one surface only
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Exclude directories that contain fixtures, vendored data, or dated artifacts.
SKIP_DIRS = {
    ".git", ".github", "__pycache__", "node_modules", ".playwright-mcp",
    "data", "logs", "ops", "ds_cache", "rewind_cache",
}
SKIP_PARTS = {"_archive"}
SKIP_FILE_SUFFIXES = {".log", ".jsonl", ".db", ".db-wal", ".db-shm",
                      ".png", ".jpg", ".jpeg", ".gif", ".ico",
                      ".pyc", ".pyo", ".mp4", ".webm"}
SKIP_FILES = {
    "audit_api_surface.py",   # this script
    "WAKEUP_NOTES.md",
    "ROADMAP.md",
    "BACKLOG.md",
    "AUDIT_PHASE_2_STATUS.md",
    "NEXT_SESSION_PLAN_2026-05-10.md",
    "CHANGELOG.md",
}

# (surface, regex) pairs. Each regex captures the endpoint path; we strip
# trailing punctuation in post-processing.
PATTERNS: dict[str, list[re.Pattern]] = {
    "lcu": [
        # LCU paths start /lol-, /riotclient/, or /lol-*/v*/* etc.
        re.compile(r"""(/lol-[a-z0-9\-]+/v\d+/[A-Za-z0-9_\-{}/$\.\(\)]+)"""),
        re.compile(r"""(/lol-[a-z0-9\-]+/v\d+)"""),
        re.compile(r"""(/riotclient/[a-z0-9\-/{}_$]+)"""),
    ],
    "web": [
        re.compile(r"""(/lol/match/v5/matches/[A-Za-z0-9_\-{}/$\(\)\.]+)"""),
        re.compile(r"""(/lol/league/v4/[A-Za-z0-9_\-{}/$\(\)\.]+)"""),
        re.compile(r"""(/lol/champion-mastery/v4/[A-Za-z0-9_\-{}/$\(\)\.]+)"""),
        re.compile(r"""(/lol/spectator/v\d+/[A-Za-z0-9_\-{}/$\(\)\.]+)"""),
        re.compile(r"""(/lol/status/v\d+/[A-Za-z0-9_\-{}/$\(\)\.]+)"""),
        re.compile(r"""(/riot/account/v1/[A-Za-z0-9_\-{}/$\(\)\.]+)"""),
        re.compile(r"""(/lol/summoner/v4/[A-Za-z0-9_\-{}/$\(\)\.]+)"""),
    ],
    "liveclient": [
        # LiveClient runs on 127.0.0.1:2999 - endpoints under /liveclientdata/.
        re.compile(r"""(/liveclientdata/[a-z0-9\-/{}_$]+)"""),
    ],
    "internal": [
        # RC's own dashboard surface - distinguish from the upstream surfaces.
        # docs/API.md is the canonical list; this regex catches Python/JS
        # references to local routes so we can cross-check that doc.
        re.compile(r"""['"](/api/[A-Za-z0-9_\-/{}\$]+)['"]"""),
    ],
}

# Files to scan - restrict to source extensions so we don't grep through
# binary data, lockfiles, etc.
SCAN_SUFFIXES = {".py", ".js", ".ts", ".jsx", ".tsx", ".ps1", ".bat",
                 ".md", ".json", ".yaml", ".yml", ".sh"}


def iter_source_files() -> list[Path]:
    """Yield candidate source files under ROOT, excluding fixture/data dirs."""
    out: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        if path.suffix in SKIP_FILE_SUFFIXES:
            continue
        if path.name in SKIP_FILES:
            continue
        if path.suffix not in SCAN_SUFFIXES:
            continue
        out.append(path)
    return out


def scan_file(path: Path, surfaces: list[str]) -> list[dict]:
    """Return matches in ``path`` for the requested surfaces."""
    rows: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return rows
    lines = text.splitlines()
    for i, line in enumerate(lines, 1):
        for surface in surfaces:
            for pat in PATTERNS[surface]:
                for m in pat.finditer(line):
                    endpoint = m.group(1).rstrip(".,;)\"'")
                    rows.append({
                        "surface": surface,
                        "endpoint": endpoint,
                        "file": path.relative_to(ROOT).as_posix(),
                        "line": i,
                        "snippet": line.strip()[:160],
                    })
    return rows


def aggregate(rows: list[dict]) -> dict:
    """Group rows by (surface, endpoint) for the markdown summary."""
    out: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        out[(r["surface"], r["endpoint"])].append(r)
    return out


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["surface", "endpoint", "file", "line", "snippet"])
        w.writeheader()
        w.writerows(rows)


def render_markdown(grouped: dict) -> str:
    """Return a markdown report grouped by surface."""
    surface_titles = {
        "lcu": "LCU (League Client) - `https://127.0.0.1:<port>`",
        "web": "Riot Web API - `https://<region>.api.riotgames.com`",
        "liveclient": "LiveClient API - `https://127.0.0.1:2999`",
        "internal": "Internal RC dashboard - `https://legion-rc:8888`",
    }
    by_surface: dict[str, list[tuple[str, list[dict]]]] = defaultdict(list)
    for (surface, endpoint), entries in grouped.items():
        by_surface[surface].append((endpoint, entries))

    lines: list[str] = [
        "# API surface audit",
        "",
        "Generated by `scripts/audit_api_surface.py` - Priority 9 of",
        "`NEXT_SESSION_PLAN_2026-05-10.md`. Each section lists endpoints",
        "RC's source code references, with caller file + line.",
        "",
        "**Limitations:** grep-only (no runtime tracing); dynamic paths whose",
        "root prefix is not literal in source will be missed. Cross-check",
        "`docs/API.md` for the internal dashboard surface - it's the",
        "canonical list for `/api/*` routes.",
        "",
    ]
    for surface in ("lcu", "web", "liveclient", "internal"):
        if surface not in by_surface:
            continue
        endpoints = sorted(by_surface[surface], key=lambda e: e[0])
        lines.append(f"## {surface_titles[surface]}")
        lines.append("")
        lines.append(f"_{len(endpoints)} distinct endpoints across "
                     f"{sum(len(e[1]) for e in endpoints)} callsites_")
        lines.append("")
        for endpoint, entries in endpoints:
            lines.append(f"### `{endpoint}`")
            lines.append("")
            lines.append("| File | Line | Snippet |")
            lines.append("|------|------|---------|")
            # cap at 8 callsites per endpoint to keep doc readable
            shown = entries[:8]
            for e in shown:
                snippet = e["snippet"].replace("|", r"\|")
                lines.append(f"| `{e['file']}` | {e['line']} | `{snippet}` |")
            if len(entries) > 8:
                lines.append(f"| ... | | _{len(entries) - 8} more callsites omitted_ |")
            lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip())
    parser.add_argument("--csv", default="",
                        help="Write CSV output to this path (in addition to stdout markdown)")
    parser.add_argument("--surface",
                        choices=("lcu", "web", "liveclient", "internal"),
                        action="append",
                        help="Restrict scan to a single surface (repeatable)")
    parser.add_argument("--md", default="",
                        help="Write markdown report to this path instead of stdout")
    args = parser.parse_args()

    surfaces = args.surface or list(PATTERNS.keys())
    files = iter_source_files()
    rows: list[dict] = []
    for f in files:
        rows.extend(scan_file(f, surfaces))

    grouped = aggregate(rows)
    md = render_markdown(grouped)

    if args.md:
        out = Path(args.md)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding="utf-8")
        print(f"Wrote markdown report -> {out}", file=sys.stderr)
    else:
        sys.stdout.write(md + "\n")

    if args.csv:
        out = Path(args.csv)
        write_csv(rows, out)
        print(f"Wrote CSV -> {out} ({len(rows)} rows)", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
