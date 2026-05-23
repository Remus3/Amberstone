"""One-shot + reusable maintenance: repair mojibake byte sequences in the repo.

Background (item 154 carry-forward, 2026-05-23): when source files were
edited on a system that mis-decoded UTF-8 as latin-1 and then RE-encoded
as UTF-8, an original em-dash (U+2014, UTF-8 bytes e2 80 94) became an
8-byte mojibake glyph: c3 a2 e2 80 9d e2 82 ac. This contains a phantom
U+201D byte sequence (e2 80 9d) flanked by U+00E2 (c3 a2) and U+20AC
(e2 82 ac). The smart-quote retro-sweep (tools/strip_smart_quotes.py)
deliberately refuses to rewrite U+201D bytes in mojibake context to
avoid corrupting the file further.

This tool performs the byte-level repair: every occurrence of the
8-byte mojibake signature is replaced with the proper 3-byte UTF-8
em-dash (U+2014). After this pass, the file's mojibake regions are
restored to a single em-dash glyph - which is itself banned by the
CLAUDE.md hard rule, so the operator should immediately follow up
with `py tools/strip_smart_quotes.py --apply` (or strip_em_dashes)
to normalize the new em-dashes to ASCII " - " (space-hyphen-space).

This script keeps itself 7-bit ASCII (signature constructed via \\xNN
byte literals, not literal mojibake bytes) so it does not self-trip
the smart-quote / mojibake drift guards. It is also self-excluded
from the walk to avoid self-mutation mid-pass.

EXCLUSIONS (immutable history / non-text, mirrors strip_smart_quotes.py
+ strip_em_dashes.py precedent + CLAUDE.md frozen-file rule):
  - .git/ , __pycache__/ , any path component '_archive' / 'node_modules'
  - *.log / *.log.N (append-only operational history)
  - *.jsonl (append-only operational ledgers)
  - binary / generated: .pyc .pyd .db .db-shm .db-wal .png .jpg .jpeg
    .gif .webp .ico .zip .gz .exe .dll .lnk .woff .woff2 .ttf .so .o .bin
  - data/daemon_slayer/**/*.json (DDragon snapshots; external data)
  - data/meta_build/**/* (dated refresh artifacts; vendored third-party HTML)
  - data/meta/ddragon_champions.json (DDragon mirror; external data)
  - this script itself

FROZEN files (per CLAUDE.md hard-rule list) are NEVER rewritten by
--apply. If they contain the mojibake signature they are LISTED
separately in the report and skipped. Operator must hand-edit if needed.

Usage:
  py tools/repair_mojibake.py            # dry-run (default): report only
  py tools/repair_mojibake.py --apply    # rewrite in place (atomic)
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

# The 8-byte mojibake signature: c3 a2 e2 80 9d e2 82 ac
# = latin-1 mis-decode of UTF-8 em-dash (e2 80 94) re-encoded as UTF-8.
# Constructed via \xNN byte escapes so this source file stays 7-bit ASCII.
MOJIBAKE_SIG = b"\xc3\xa2\xe2\x80\x9d\xe2\x82\xac"
# The proper UTF-8 byte sequence for U+2014 (EM DASH).
EM_DASH_BYTES = b"\xe2\x80\x94"

ROOT = Path(__file__).resolve().parent.parent
_SELF = Path(__file__).resolve()

# Frozen files per CLAUDE.md hard-rule. NEVER rewrite even on --apply;
# only list in report. Stored as repo-relative POSIX paths.
_FROZEN = frozenset({
    "main.py",
    "core/log_setup.py",
    "core/moon_proxy.py",
    "lcu/lcu_client.py",
    "core/game_snapshot.py",
    "ops/rc_dev_runtime.py",
    "ops/rc_supervisor.py",
    "app/__init__.py",
    "app/_loop.py",
    "app/_health_monitor.py",
    "app/_remediation.py",
    "app/_state_authority.py",
    "app/_overlay_manager.py",
    "app/_game_lifecycle.py",
    "tools/bridge_watcher_classify.py",
    "tools/bridge_watcher_actions.py",
    "tools/bridge_watcher_action_prompt.md",
    "tools/bridge_watcher_history.py",
    "tools/bridge_watcher_install.ps1",
    "tools/bridge_watcher_hook.ps1",
    "tools/bridge_watcher_config.json",
    "tools/bridge_post_result.py",
    "tools/bridge_pull_tasks.py",
    "tools/process-bridge-tasks.md",
    "tools/diagnose.md",
    "tools/caveman.md",
    "dashboard/routes_bridge_pending.py",
    "ops/RC-BridgeWatcher.xml",
})

_SKIP_DIR_PARTS = {"_archive", "node_modules"}
_SKIP_EXT = {
    ".pyc", ".pyd", ".db", ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".ico", ".zip", ".gz", ".exe", ".dll", ".lnk", ".woff", ".woff2",
    ".ttf", ".bin", ".so", ".o",
    ".jsonl",
}
_LOG_RE = re.compile(r"\.log(\.\d+)?$", re.IGNORECASE)


def _is_external_data(rel_posix: str) -> bool:
    if rel_posix.startswith("data/daemon_slayer/") and rel_posix.endswith(".json"):
        return True
    if rel_posix.startswith("data/meta_build/"):
        return True
    if rel_posix == "data/meta/ddragon_champions.json":
        return True
    return False


def _skip(path: Path, rel_posix: str) -> bool:
    if path.resolve() == _SELF:
        return True
    if set(path.parts) & _SKIP_DIR_PARTS:
        return True
    name = path.name.lower()
    if _LOG_RE.search(name):
        return True
    if name.endswith((".db-shm", ".db-wal")):
        return True
    if path.suffix.lower() in _SKIP_EXT:
        return True
    if _is_external_data(rel_posix):
        return True
    return False


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT,
        capture_output=True, check=True,
    ).stdout
    return [ROOT / p for p in out.decode("utf-8").split("\0") if p]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="rewrite files in place (default: dry-run)")
    ap.add_argument("--top", type=int, default=20,
                    help="show N highest-count files")
    args = ap.parse_args()

    by_ext: Counter[str] = Counter()
    per_file: list[tuple[int, int, int, str]] = []  # (count, pre_bytes, post_bytes, rel)
    frozen_hits: list[tuple[int, str]] = []
    total_occ = 0
    files_changed = 0
    skipped_binary = 0

    for p in _tracked_files():
        rel_posix = p.relative_to(ROOT).as_posix()
        if _skip(p, rel_posix):
            continue
        try:
            raw = p.read_bytes()
        except OSError:
            continue
        if MOJIBAKE_SIG not in raw:
            continue
        n = raw.count(MOJIBAKE_SIG)
        new = raw.replace(MOJIBAKE_SIG, EM_DASH_BYTES)
        # Sanity: result must still be valid UTF-8.
        try:
            new.decode("utf-8")
        except UnicodeDecodeError:
            skipped_binary += 1
            continue
        total_occ += n
        files_changed += 1
        by_ext[p.suffix.lower() or "<none>"] += n
        pre_bytes = len(raw)
        post_bytes = len(new)
        per_file.append((n, pre_bytes, post_bytes, rel_posix))

        is_frozen = rel_posix in _FROZEN
        if is_frozen:
            frozen_hits.append((n, rel_posix))
            continue  # NEVER rewrite frozen files

        if args.apply:
            tmp = p.with_suffix(p.suffix + ".mjtmp")
            tmp.write_bytes(new)
            os.replace(tmp, p)

    mode = "APPLIED" if args.apply else "DRY-RUN (no writes)"
    print(f"=== repair_mojibake {mode} ===")
    print("signature (hex)         : c3 a2 e2 80 9d e2 82 ac  (8 bytes)")
    print("replacement (hex)       : e2 80 94                 (3 bytes, U+2014)")
    print(f"files with mojibake     : {files_changed}")
    print(f"total signatures        : {total_occ}")
    print(f"skipped (utf8 decode)   : {skipped_binary}")
    print(f"frozen files SKIPPED    : {len(frozen_hits)}")
    print("by extension:")
    for ext, c in by_ext.most_common():
        print(f"  {ext:<8} {c}")
    print(f"top {args.top} files by signature count:")
    for n, pre, post, rel in sorted(per_file, reverse=True)[:args.top]:
        delta = pre - post
        marker = "  [FROZEN]" if rel in _FROZEN else ""
        print(f"  {n:>6}  pre={pre:>7}  post={post:>7}  delta=-{delta:>6}  {rel}{marker}")
    if frozen_hits:
        print("FROZEN-file hits (NOT rewritten; hand-edit if needed):")
        for n, rel in sorted(frozen_hits, reverse=True):
            print(f"  {n:>6}  {rel}")
    print()
    print("NEXT STEP: after --apply, the resulting U+2014 em-dashes are themselves")
    print("banned by CLAUDE.md. Follow up with:")
    print("  py tools/strip_smart_quotes.py --apply")
    print("to normalize the new em-dashes to ASCII ' - ' (space-hyphen-space).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
