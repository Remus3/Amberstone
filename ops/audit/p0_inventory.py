r"""P0 baseline full-tree inventory. Writes aggregate MD + full CSV to ops/audit/.

Run from repo root:
    "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" ops/audit/p0_inventory.py
"""
import csv
import datetime
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "ops" / "audit"
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".pytest_cache", ".ruff_cache"}


def walk(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            p = Path(dirpath) / fn
            try:
                yield p, p.stat().st_size
            except OSError:
                continue


def main() -> int:
    rows = []  # (relpath, size, ext, top)
    by_top = defaultdict(lambda: [0, 0])   # top-level dir -> [count, bytes]
    by_ext = defaultdict(lambda: [0, 0])   # extension -> [count, bytes]
    total_count = 0
    total_bytes = 0
    for p, size in walk(ROOT):
        rel = p.relative_to(ROOT)
        top = rel.parts[0] if len(rel.parts) > 1 else "(root)"
        ext = p.suffix.lower() or "(none)"
        rows.append((str(rel), size, ext, top))
        by_top[top][0] += 1
        by_top[top][1] += size
        by_ext[ext][0] += 1
        by_ext[ext][1] += size
        total_count += 1
        total_bytes += size

    tracked = set(
        subprocess.run(
            ["git", "-C", str(ROOT), "ls-files"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        ).stdout.splitlines()
    )
    tracked_bytes = 0
    tracked_count = 0
    untracked_bytes = 0
    for rel, size, _ext, _top in rows:
        if rel.replace("\\", "/") in tracked:
            tracked_count += 1
            tracked_bytes += size
        else:
            untracked_bytes += size

    rows.sort(key=lambda r: -r[1])
    csv_path = OUT_DIR / "p0_inventory_full.csv"
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    provenance = (
        f"# point-in-time snapshot generated {stamp} by ops/audit/p0_inventory.py "
        "- lists files present AT GENERATION TIME only - may include since-deleted "
        "paths - regenerate after structural deletions before trusting for an audit"
    )
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        f.write(provenance + "\n")
        w = csv.writer(f)
        w.writerow(["relpath", "bytes", "ext", "top"])
        w.writerows(rows)

    def mb(n: int) -> str:
        return f"{n / 1048576:.1f}"

    lines = []
    lines.append("# P0 baseline tree inventory")
    lines.append("")
    lines.append(f"- Total: {total_count} files, {mb(total_bytes)} MB (git dir excluded)")
    lines.append(f"- Git-tracked: {tracked_count} files, {mb(tracked_bytes)} MB")
    lines.append(
        f"- Untracked/ignored on disk: {total_count - tracked_count} files, "
        f"{mb(untracked_bytes)} MB"
    )
    lines.append("")
    lines.append("## By top-level dir (desc bytes)")
    lines.append("")
    lines.append("| dir | files | MB |")
    lines.append("|---|---|---|")
    for top, (cnt, b) in sorted(by_top.items(), key=lambda kv: -kv[1][1]):
        lines.append(f"| {top} | {cnt} | {mb(b)} |")
    lines.append("")
    lines.append("## By extension (top 25 by bytes)")
    lines.append("")
    lines.append("| ext | files | MB |")
    lines.append("|---|---|---|")
    for ext, (cnt, b) in sorted(by_ext.items(), key=lambda kv: -kv[1][1])[:25]:
        lines.append(f"| {ext} | {cnt} | {mb(b)} |")
    lines.append("")
    lines.append("## Largest 40 files")
    lines.append("")
    lines.append("| MB | tracked | path |")
    lines.append("|---|---|---|")
    for rel, size, _ext, _top in rows[:40]:
        t = "Y" if rel.replace("\\", "/") in tracked else "n"
        lines.append(f"| {mb(size)} | {t} | {rel} |")
    lines.append("")

    md_path = OUT_DIR / "P0_INVENTORY.md"
    tmp = md_path.with_suffix(".md.tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    tmp.replace(md_path)
    print(f"wrote {md_path} + {csv_path}: {total_count} files {mb(total_bytes)} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
