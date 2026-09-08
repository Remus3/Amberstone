"""Auto-derives module map + phase journal in docs/ARCHITECTURE.md from `# arch:` markers in .py files.

Two marker forms, both starting with `# arch:`:

1. File-header marker (must appear in first 8 lines of a .py file):
       # arch: <role description> | section=<section> | frozen=<yes|no>

   Disambiguator: contains a `|` separator. Sections = orchestration, vision,
   coaching, dashboard, core, bridge, tools, tft, agents, test.
   These populate the `archmap:start/end` block (per-section module tables).

2. Inline phase-journal marker (anywhere in a .py file):
       # arch: phase <id> [(YYYY-MM-DD)] - <one-line note>

   Disambiguator: starts with the literal `phase` keyword and uses an em-dash
   before the note. The optional date is encouraged for new markers.
   These populate the `phasejournal:start/end` block (chronological table).

Running without flags rewrites both blocks in ARCHITECTURE.md in-place.
Running with --check exits 1 if either block would change (use in pre-commit).

Note: the frozen-file list in CLAUDE.md is manually maintained because it
includes non-Python files (.ps1, .json, .xml, .md) that cannot carry # arch: headers.
"""
import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).parent.parent

SKIP_DIRS = {
    "__pycache__", ".git", ".claude", "node_modules",
    "_archive", "docs",
    # `ops/runtime` is gitignored SCRATCH, not source, and it can contain a
    # full copy of the repo: the inbox responder caches a tracked-only
    # `git archive origin/main` export under
    # `ops/runtime/responder_export/<sha12>/`. MEASURED 2026-09-08 - without
    # this entry a regen on a machine holding that cache swept 194 of its
    # files into `docs/ARCHITECTURE.md` as if they were source, and the doc
    # then FLAPPED with whether the cache happened to exist on whichever
    # machine committed next. Anything under a runtime dir is by definition
    # not part of the architecture map.
    "runtime",
}

# Files skipped only by the phase-journal scan (their docstrings/comments
# contain literal `# arch: phase ...` examples that would self-pollute the journal).
PHASE_SCAN_SKIP_FILES = {
    "tools/gen_archmap.py",
}

SECTION_ORDER = [
    "orchestration",
    "vision",
    "coaching",
    "dashboard",
    "mc",
    "core",
    "bridge",
    "tools",
    "tft",
    "agents",
    "test",
]

SECTION_TITLES = {
    "orchestration": "Orchestration (all frozen - do not edit without sign-off)",
    "vision": "Vision + data pipeline",
    "coaching": "Coaching",
    "dashboard": "Dashboard",
    "mc": "Mission Control (:8895 control plane)",
    "core": "Core utilities",
    "bridge": "Bridge tools",
    "tools": "Tools / ops",
    "tft": "TFT engine",
    "agents": "Phase 3 agents",
    "test": "Tests",
}

ARCH_RE = re.compile(
    r"#\s*arch:\s*(?P<role>[^|]+?)\s*\|\s*section=(?P<section>\w+)\s*\|\s*frozen=(?P<frozen>yes|no)",
    re.IGNORECASE,
)

# Inline phase-journal marker. Matches:
#   # arch: phase 0.13 - bounded bootstrap window
#   # arch: phase 4.2 (2026-05-08) - bridge envelope schema additions
#   # arch: phase 7 P2-C - clear stale choices on force scan
PHASE_RE = re.compile(
    r"#\s*arch:\s*phase\s+(?P<id>[^-(]+?)\s*(?:\((?P<date>\d{4}-\d{2}-\d{2})\)\s*)?-\s*(?P<note>.+?)\s*$",
    re.IGNORECASE,
)


def _collect() -> dict[str, list[tuple[str, str, bool]]]:
    """Returns {section: [(rel_path, role, frozen), ...]} sorted by path."""
    data: dict[str, list] = {s: [] for s in SECTION_ORDER}

    for py in sorted(ROOT.rglob("*.py")):
        parts = set(py.relative_to(ROOT).parts)
        if parts & SKIP_DIRS:
            continue
        try:
            head = py.read_text(encoding="utf-8", errors="replace").splitlines()[:8]
        except OSError:
            continue
        for line in head:
            m = ARCH_RE.search(line)
            if m:
                section = m.group("section").lower()
                role = m.group("role").strip()
                frozen = m.group("frozen").lower() == "yes"
                rel = py.relative_to(ROOT).as_posix()
                if section in data:
                    data[section].append((rel, role, frozen))
                break

    return data


def _collect_phase_markers() -> list[tuple[str, str, str, int, str]]:
    """Returns [(phase_id, date_or_empty, rel_path, lineno, note), ...] sorted by date desc, then phase_id."""
    rows: list[tuple[str, str, str, int, str]] = []

    for py in sorted(ROOT.rglob("*.py")):
        parts = set(py.relative_to(ROOT).parts)
        if parts & SKIP_DIRS:
            continue
        rel = py.relative_to(ROOT).as_posix()
        if rel in PHASE_SCAN_SKIP_FILES:
            continue
        try:
            text = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            m = PHASE_RE.search(line)
            if not m:
                continue
            phase_id = m.group("id").strip()
            date = (m.group("date") or "").strip()
            note = m.group("note").strip()
            rows.append((phase_id, date, rel, lineno, note))

    # Sort: dated rows first (by date desc), then undated rows (by phase_id)
    def _sort_key(row: tuple[str, str, str, int, str]) -> tuple[int, int, str]:
        phase_id, date, *_ = row
        if date:
            return (0, -_date_to_int(date), phase_id)
        return (1, 0, phase_id)

    rows.sort(key=_sort_key)
    return rows


def _date_to_int(date_str: str) -> int:
    """ISO date YYYY-MM-DD -> integer for sorting."""
    y, m, d = date_str.split("-")
    return int(y) * 10000 + int(m) * 100 + int(d)


def _render_archmap(data: dict) -> str:
    lines = ["<!-- archmap:start - auto-generated by tools/gen_archmap.py; do not edit manually -->"]
    for section in SECTION_ORDER:
        entries = data.get(section, [])
        if not entries:
            continue
        title = SECTION_TITLES.get(section, section.title())
        lines.append(f"\n### {title}")
        lines.append("| File | Role |")
        lines.append("|---|---|")
        for rel, role, frozen in entries:
            frozen_tag = " [FROZEN]" if frozen else ""
            lines.append(f"| `{rel}` | {role}{frozen_tag} |")
    lines.append("\n<!-- archmap:end -->")
    return "\n".join(lines)


def _render_phase_journal(rows: list[tuple[str, str, str, int, str]]) -> str:
    lines = ["<!-- phasejournal:start - auto-generated by tools/gen_archmap.py; do not edit manually -->"]
    if not rows:
        lines.append("\n_No `# arch: phase ...` markers found in tree._")
    else:
        lines.append("\n| Phase | Date | Location | Note |")
        lines.append("|---|---|---|---|")
        for phase_id, date, rel, lineno, note in rows:
            date_cell = date or "-"
            lines.append(f"| {phase_id} | {date_cell} | `{rel}:{lineno}` | {note} |")
    lines.append("\n<!-- phasejournal:end -->")
    return "\n".join(lines)


def _replace_between(text: str, start_marker: str, end_marker: str, replacement: str) -> str:
    start_re = re.compile(re.escape(start_marker) + r".*?$", re.MULTILINE)
    end_re = re.compile(r"^.*?" + re.escape(end_marker), re.MULTILINE)
    m_start = start_re.search(text)
    m_end = end_re.search(text, m_start.end() if m_start else 0)
    if not m_start or not m_end:
        return text  # sentinels missing - leave file unchanged
    return text[: m_start.start()] + replacement + text[m_end.end() :]


def _update_file(path: pathlib.Path, start_marker: str, end_marker: str, new_block: str, check: bool) -> bool:
    """Returns True if the file was (or would be) changed."""
    original = path.read_text(encoding="utf-8")
    updated = _replace_between(original, start_marker, end_marker, new_block)
    if updated == original:
        return False
    if not check:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(updated, encoding="utf-8")
        tmp.replace(path)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Exit 1 if ARCHITECTURE.md would change")
    args = parser.parse_args()

    data = _collect()
    phase_rows = _collect_phase_markers()
    arch_md = ROOT / "docs" / "ARCHITECTURE.md"
    archmap_block = _render_archmap(data)
    phase_block = _render_phase_journal(phase_rows)

    archmap_changed = _update_file(
        arch_md,
        "<!-- archmap:start",
        "<!-- archmap:end -->",
        archmap_block,
        args.check,
    )
    # Read fresh after potential archmap rewrite so the second update sees up-to-date file.
    phase_changed = _update_file(
        arch_md,
        "<!-- phasejournal:start",
        "<!-- phasejournal:end -->",
        phase_block,
        args.check,
    )

    if archmap_changed or phase_changed:
        if args.check:
            which = []
            if archmap_changed:
                which.append("archmap")
            if phase_changed:
                which.append("phase journal")
            print(
                f"{', '.join(which)} out of sync - run `python tools/gen_archmap.py` to update: docs/ARCHITECTURE.md",
                file=sys.stderr,
            )
            return 1
        print("Updated: docs/ARCHITECTURE.md")
    else:
        print("archmap + phase journal up to date.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
