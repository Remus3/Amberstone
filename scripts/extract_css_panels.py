"""Split dashboard.css into web/css/panels/*.css files.

Run once: python scripts/extract_css_panels.py
Idempotent: safe to re-run; overwrites panel files with same content.
--check: exit 1 if panel files are missing or dashboard.css is not yet the @import router.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).parent.parent
SRC = ROOT / "web/css/dashboard.css"
PANELS_DIR = ROOT / "web/css/panels"

# (filename, start_line, end_line) — 1-based, inclusive
# Lines 1-11 (file comment + Google Fonts @import) stay in dashboard.css header.
SECTIONS = [
    ("base.css",            12,   117),   # :root, reset, tooltip, game-phase
    ("header.css",         118,  1754),   # dev-banner, header bar, pills, views, shared
    ("grid.css",          1755,  2217),   # 2x3 panel grid, team strips, minimap
    ("bridge_pending.css", 2218,  2592),  # coach decisions, bridge pending, fleet health
    ("map_state.css",     2593,  3172),   # vision overlay, stats/adaptation detail
    ("right_now.css",     3173,  3269),   # Right Now panel
    ("next.css",          3270,  3316),   # Next panel
    ("item_build.css",    3317,  3757),   # Item Build + KV pairs
    ("input_activity.css",3758,  4263),   # adapt tail, input bar, modal, footer, media
    # champ_select: two non-contiguous ranges merged (4264-4276 + 5118-5468)
    ("home.css",          4277,  5117),   # home/lobby landing view
    ("primitives.css",    5469,  5758),   # rc-card, skeletons, audit proposals
    ("dev.css",           5759,  5812),   # Dev/Sim Preview panel
]

# Non-contiguous ranges concatenated into one file
CHAMP_SELECT_RANGES = [(4264, 4276), (5118, 5468)]


def _check_mode(lines: list[str]) -> int:
    missing = []
    for fname, *_ in SECTIONS:
        p = PANELS_DIR / fname
        if not p.exists():
            missing.append(str(p.relative_to(ROOT)))
    p = PANELS_DIR / "champ_select.css"
    if not p.exists():
        missing.append(str(p.relative_to(ROOT)))
    # Check dashboard.css is now the @import router
    if "@import './panels/base.css'" not in SRC.read_text(encoding="utf-8"):
        missing.append("dashboard.css (not yet converted to @import router)")
    if missing:
        print("MISSING:", ", ".join(missing))
        print("Run: python scripts/extract_css_panels.py")
        return 1
    print("OK — all CSS panel files present and dashboard.css is @import router")
    return 0


def main(check: bool = False) -> int:
    raw = SRC.read_bytes()
    lines = raw.decode("utf-8").splitlines(keepends=True)
    total = len(lines)
    print(f"Source: {SRC.name} — {total} lines")

    if check:
        return _check_mode(lines)

    PANELS_DIR.mkdir(exist_ok=True)

    # Write each section
    for fname, start, end in SECTIONS:
        chunk = "".join(lines[start - 1 : end])
        (PANELS_DIR / fname).write_text(chunk, encoding="utf-8")
        print(f"  wrote {fname} ({end - start + 1} lines, {start}–{end})")

    # Write champ_select.css (two ranges concatenated)
    cs_chunks = []
    for s, e in CHAMP_SELECT_RANGES:
        cs_chunks.append("".join(lines[s - 1 : e]))
    cs_content = "\n".join(cs_chunks)
    (PANELS_DIR / "champ_select.css").write_text(cs_content, encoding="utf-8")
    total_cs = sum(e - s + 1 for s, e in CHAMP_SELECT_RANGES)
    print(f"  wrote champ_select.css ({total_cs} lines, ranges {CHAMP_SELECT_RANGES})")

    # Build the new dashboard.css: file header (lines 1-11) + @imports
    file_header = "".join(lines[0:11])
    imports = "\n".join(
        f"@import './panels/{fname}';"
        for fname, *_ in SECTIONS[:9]  # up through input_activity
    )
    # Insert champ_select between input_activity and home
    imports += "\n@import './panels/champ_select.css';"
    imports += "\n" + "\n".join(
        f"@import './panels/{fname}';"
        for fname, *_ in SECTIONS[9:]  # home, primitives, dev
    )

    new_dashboard = file_header + "\n" + imports + "\n"
    SRC.write_text(new_dashboard, encoding="utf-8")
    print(f"  rewrote dashboard.css → @import router ({len(new_dashboard.splitlines())} lines)")

    return 0


if __name__ == "__main__":
    check = "--check" in sys.argv
    sys.exit(main(check))
