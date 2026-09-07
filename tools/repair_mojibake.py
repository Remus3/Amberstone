"""One-shot + reusable maintenance: repair mojibake byte sequences in the repo.

Background (item 154 carry-forward, 2026-05-23; extended item 156): when
source files were edited on a system that mis-decoded UTF-8 as cp1252 or
latin-1 and then RE-encoded as UTF-8, dash-class glyphs became 8-byte
mojibake sequences. Two variants are observed in the repo:

  Variant A (c3 a2 e2 80 9d e2 82 ac) decodes as U+00E2 U+201D U+20AC
    (a-circ + right-double-quote + euro). The source UTF-8 glyph that
    produces this round-trip is U+2500 BOX DRAWINGS LIGHT HORIZONTAL
    (bytes e2 94 80), mis-decoded as cp1252 then re-encoded as UTF-8.

  Variant B (c3 a2 e2 82 ac e2 80 9d) decodes as U+00E2 U+20AC U+201D
    (a-circ + euro + right-double-quote). This is the canonical
    em-dash mojibake: U+2014 EM DASH (bytes e2 80 94) mis-decoded as
    cp1252 then re-encoded as UTF-8.

Both variants contain a phantom U+201D byte sequence (e2 80 9d) that
the smart-quote retro-sweep (tools/strip_smart_quotes.py) refuses to
rewrite in mojibake context. This tool repairs both: Variant A is
replaced with U+2014 em-dash (operator-policy: collapse box-drawing
ASCII-art separators into the standard dash glyph that downstream
smart-quote sweep then normalizes to ASCII ' - '), and Variant B is
also replaced with U+2014 (its true original glyph). The unified
3-byte U+2014 output is then fed to strip_smart_quotes.py for the
final ASCII normalization per CLAUDE.md.

After this pass, the file's mojibake regions are restored to single
em-dash glyphs - which are themselves banned by the CLAUDE.md hard
rule, so the operator should immediately follow up with
`$env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/strip_smart_quotes.py --apply` to normalize the new
em-dashes to ASCII " - " (space-hyphen-space).

This script keeps itself 7-bit ASCII (signatures constructed via \\xNN
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
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/repair_mojibake.py            # dry-run (default): report only
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/repair_mojibake.py --apply    # rewrite in place (atomic)
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/repair_mojibake.py --apply \
      --allow-frozen ops/rc_supervisor.py
                                          # override frozen-skip for the
                                          # listed comma-separated paths
                                          # (operator-grant required)

OPERATOR-GRANT OVERRIDE (--allow-frozen):
The --allow-frozen flag accepts a comma-separated list of frozen-file paths
to rewrite anyway. This requires explicit operator grant (see CLAUDE.md
hard-rule list + per-session approval). The flag is provided so that bulk
mojibake repair on frozen files (e.g. ops/rc_supervisor.py's 1368-byte
carry-forward from item 155) can be performed without hand-editing each
file. _HARD_SKIP_FROZEN is the defense-in-depth set: any path in that
frozenset is NEVER rewritten regardless of the flag. Currently empty so
all frozen files are operator-grantable; bump only with explicit operator
authorization (mirrors strip_smart_quotes.py precedent).
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

# 8-byte mojibake signatures. Both variants are restored to the proper
# 3-byte UTF-8 em-dash (U+2014). Constructed via \xNN byte escapes so
# this source file stays 7-bit ASCII.
#
#   Variant A: c3 a2 e2 80 9d e2 82 ac  (orig glyph: U+2500 box draw)
#   Variant B: c3 a2 e2 82 ac e2 80 9d  (orig glyph: U+2014 em-dash)
#
# MOJIBAKE_SIG is retained for backward compatibility with downstream
# code (tests, scripts) that imported the original single-signature
# constant. New code should iterate MOJIBAKE_SIGS.
MOJIBAKE_SIG = b"\xc3\xa2\xe2\x80\x9d\xe2\x82\xac"
MOJIBAKE_SIG_B = b"\xc3\xa2\xe2\x82\xac\xe2\x80\x9d"
MOJIBAKE_SIGS: tuple[bytes, ...] = (MOJIBAKE_SIG, MOJIBAKE_SIG_B)
# The proper UTF-8 byte sequence for U+2014 (EM DASH).
EM_DASH_BYTES = b"\xe2\x80\x94"

ROOT = Path(__file__).resolve().parent.parent
_SELF = Path(__file__).resolve()

# HARD SKIP: paths in this set are NEVER rewritten, even when listed in
# --allow-frozen. Defense-in-depth defaulted to empty so any frozen file
# is operator-grantable via the flag. Bump ONLY with explicit operator
# authorization for a specific path that must never be touched even by
# accidental grant (mirrors strip_smart_quotes.py precedent).
_HARD_SKIP_FROZEN: frozenset[str] = frozenset()

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
    "tools/diagnose.md",
    "tools/caveman.md",
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
    ap.add_argument("--allow-frozen", type=str, default="",
                    help=("comma-separated frozen-file paths to OVERRIDE "
                          "the frozen-skip for (operator-grant required; "
                          "paths in _HARD_SKIP_FROZEN are still NEVER "
                          "rewritten regardless of the flag)"))
    args = ap.parse_args()

    # Parse + validate the --allow-frozen override list. The hard-skip set
    # is enforced as a SECOND defensive check after the user-provided list
    # is split.
    _allow_raw = [s.strip() for s in args.allow_frozen.split(",") if s.strip()]
    _allow_frozen = frozenset(p for p in _allow_raw if p not in _HARD_SKIP_FROZEN)
    _hard_skipped_from_allow = [p for p in _allow_raw if p in _HARD_SKIP_FROZEN]

    by_ext: Counter[str] = Counter()
    per_file: list[tuple[int, int, int, str]] = []  # (count, pre_bytes, post_bytes, rel)
    frozen_hits: list[tuple[int, str]] = []
    total_occ = 0
    files_changed = 0
    skipped_binary = 0

    by_variant: Counter[str] = Counter()
    for p in _tracked_files():
        rel_posix = p.relative_to(ROOT).as_posix()
        if _skip(p, rel_posix):
            continue
        try:
            raw = p.read_bytes()
        except OSError:
            continue
        if not any(sig in raw for sig in MOJIBAKE_SIGS):
            continue
        n_a = raw.count(MOJIBAKE_SIG)
        n_b = raw.count(MOJIBAKE_SIG_B)
        n = n_a + n_b
        new = raw.replace(MOJIBAKE_SIG, EM_DASH_BYTES)
        new = new.replace(MOJIBAKE_SIG_B, EM_DASH_BYTES)
        # Sanity: result must still be valid UTF-8.
        try:
            new.decode("utf-8")
        except UnicodeDecodeError:
            skipped_binary += 1
            continue
        total_occ += n
        files_changed += 1
        by_ext[p.suffix.lower() or "<none>"] += n
        if n_a:
            by_variant["A (U+2500 source)"] += n_a
        if n_b:
            by_variant["B (U+2014 source)"] += n_b
        pre_bytes = len(raw)
        post_bytes = len(new)
        per_file.append((n, pre_bytes, post_bytes, rel_posix))

        is_frozen = rel_posix in _FROZEN
        is_hard_skip = rel_posix in _HARD_SKIP_FROZEN
        # Second defensive check: even if listed in --allow-frozen, hard-skip
        # files are NEVER rewritten.
        allow_override = (rel_posix in _allow_frozen) and not is_hard_skip
        if is_frozen and not allow_override:
            frozen_hits.append((n, rel_posix))
            continue  # NEVER rewrite frozen files (no operator grant)

        if args.apply:
            tmp = p.with_suffix(p.suffix + ".mjtmp")
            tmp.write_bytes(new)
            os.replace(tmp, p)

    mode = "APPLIED" if args.apply else "DRY-RUN (no writes)"
    print(f"=== repair_mojibake {mode} ===")
    print("variant A signature     : c3 a2 e2 80 9d e2 82 ac  (orig: U+2500)")
    print("variant B signature     : c3 a2 e2 82 ac e2 80 9d  (orig: U+2014)")
    print("replacement (hex)       : e2 80 94                 (3 bytes, U+2014)")
    print(f"files with mojibake     : {files_changed}")
    print(f"total signatures        : {total_occ}")
    print(f"skipped (utf8 decode)   : {skipped_binary}")
    print(f"frozen files SKIPPED    : {len(frozen_hits)}")
    if _allow_frozen:
        print(f"frozen files OVERRIDDEN : {len(_allow_frozen)} "
              f"(--allow-frozen): {sorted(_allow_frozen)}")
    if _hard_skipped_from_allow:
        print(f"HARD-SKIP from --allow-frozen (override IGNORED): "
              f"{sorted(_hard_skipped_from_allow)}")
    if by_variant:
        print("by variant:")
        for label, c in by_variant.most_common():
            print(f"  {label:<24} {c}")
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
    print("  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/strip_smart_quotes.py --apply")
    print("to normalize the new em-dashes to ASCII ' - ' (space-hyphen-space).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
