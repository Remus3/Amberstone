"""One-shot + reusable maintenance: purge Unicode smart quotes + ellipsis + NBSP
+ any residual em/en dashes from the repo.

Hard rule (CLAUDE.md, 2026-05-18): no em-dashes / en-dashes / smart quotes
in any authored text - keep authored content 7-bit ASCII. The em-dash
retroactive purge already shipped via tools/strip_em_dashes.py (s244,
2026-05-18). This script is the parallel smart-quote sweep:

  U+201C LEFT DOUBLE QUOTATION MARK  -> 0x22 '"'
  U+201D RIGHT DOUBLE QUOTATION MARK -> 0x22 '"'
  U+2018 LEFT SINGLE QUOTATION MARK  -> 0x27 "'"
  U+2019 RIGHT SINGLE QUOTATION MARK -> 0x27 "'"

Bonus residual sweep (defense-in-depth in case any em/en-dash drifted
back after the s244 purge, or appears in newly added files):

  U+2013 EN DASH                     -> ' - ' (space hyphen space)
  U+2014 EM DASH                     -> ' - ' (space hyphen space)

Bonus extra-ASCII normalisation:

  U+2026 HORIZONTAL ELLIPSIS         -> '...' (3 ASCII dots)
  U+00A0 NON-BREAKING SPACE          -> ' '   (ASCII space)

This script keeps itself 7-bit ASCII (codepoints via chr(), not the
literal glyphs) so it does not need to be its own exclusion for that
reason - it is still skipped to avoid self-mutation mid-walk.

MOJIBAKE GUARD: some files in the repo contain mojibake byte sequences
where bytes for U+2014 (em-dash) or U+2500 (box drawing) were latin-1
mis-decoded then re-UTF-8-encoded into multi-byte glyphs containing
the U+201D byte sequence as a middle byte. Naively rewriting that
U+201D would corrupt the file (the mojibake glyph would become a
single ASCII quote, often inside a string-literal where it then
prematurely terminates the string).

The tool uses BYTE-LEVEL CONTEXT-SENSITIVE replacement:
  - Each codepoint is rewritten as its UTF-8 byte sequence (e.g.
    e2 80 9d for U+201D) ONLY WHEN NOT adjacent to known mojibake
    neighbours (e2 82 ac for U+20AC).
  - Files where every occurrence of U+201D is mojibake-context are
    flagged in the report as MOJIBAKE-tainted but left unmodified.
  - Files where ALL occurrences are mojibake AND no other targets
    are present are skipped silently.

EXCLUSIONS (immutable history / non-text, per CLAUDE.md carve-out +
the standing don't-rewrite-history rule):
  - .git/ , __pycache__/ , any path component '_archive'
  - *.log / *.log.N (append-only operational history)
  - *.jsonl (append-only operational ledgers)
  - binary / generated: .pyc .pyd .db .db-shm .db-wal .png .jpg .jpeg
    .gif .webp .ico .zip .gz .exe .dll .lnk .woff .woff2 .ttf .so .o
    .bin
  - data/daemon_slayer/**/*.json (Riot DDragon snapshots - external
    data, not authored content)
  - data/meta_build/**/* (dated refresh artifacts; vendored HTML
    snapshots with third-party prose)
  - data/meta/ddragon_champions.json (DDragon mirror, external data)
  - node_modules/ (vendored JS deps)
  - this script itself

FROZEN files (per CLAUDE.md hard-rule list) are NEVER rewritten by
--apply. If they contain target codepoints they are LISTED separately
in the report and skipped. Operator must hand-edit if needed.

Usage:
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/strip_smart_quotes.py            # dry-run (default): report only
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/strip_smart_quotes.py --apply    # rewrite in place (atomic)
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/strip_smart_quotes.py --apply \
      --allow-frozen ops/rc_dev_runtime.py,core/moon_proxy.py
                                             # override frozen-skip for the
                                             # listed comma-separated paths
                                             # (operator-grant required;
                                             # ops/rc_supervisor.py is HARD
                                             # SKIPPED regardless, see below)

OPERATOR-GRANT OVERRIDE (--allow-frozen):
The --allow-frozen flag accepts a comma-separated list of frozen-file paths
to rewrite anyway. This requires explicit operator grant (see CLAUDE.md
hard-rule list + per-session approval). The flag is provided so trivial
frozen-file hits (a single U+2026 in a log message) can be swept without
hand-editing each file. _HARD_SKIP_FROZEN is the defense-in-depth set:
any path in that frozenset is NEVER rewritten regardless of the flag.
Currently empty so all frozen files are operator-grantable; bump only with
explicit operator authorization for a specific path that must never be
touched even by accidental grant.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

# Codepoint constants via chr() so this file stays 7-bit ASCII.
LDQUO = chr(0x201C)
RDQUO = chr(0x201D)
LSQUO = chr(0x2018)
RSQUO = chr(0x2019)
ENDASH = chr(0x2013)
EMDASH = chr(0x2014)
HELLIP = chr(0x2026)
NBSP = chr(0x00A0)

# (codepoint, utf-8 byte seq, replacement-bytes, label)
# Order matters for cumulative application; quotes first, then dashes, then misc.
_BYTE_RULES = (
    (LDQUO,  b"\xe2\x80\x9c", b"\x22",       "U+201C"),
    (RDQUO,  b"\xe2\x80\x9d", b"\x22",       "U+201D"),
    (LSQUO,  b"\xe2\x80\x98", b"\x27",       "U+2018"),
    (RSQUO,  b"\xe2\x80\x99", b"\x27",       "U+2019"),
    (ENDASH, b"\xe2\x80\x93", b" - ",        "U+2013"),
    (EMDASH, b"\xe2\x80\x94", b" - ",        "U+2014"),
    (HELLIP, b"\xe2\x80\xa6", b"...",        "U+2026"),
    (NBSP,   b"\xc2\xa0",     b" ",          "U+00A0"),
)

# Mojibake neighbour: U+20AC (EURO SIGN) bytes. If a U+201D byte sequence
# is immediately preceded by, or immediately followed by, this byte
# sequence, it is part of a mojibake glyph (latin-1 mis-decode of em-dash
# or box-drawing-horizontal). Do NOT replace.
_MOJI_NEIGHBOUR = b"\xe2\x82\xac"  # U+20AC EURO SIGN

ROOT = Path(__file__).resolve().parent.parent
_SELF = Path(__file__).resolve()

# HARD SKIP: paths in this set are NEVER rewritten, even when listed in
# --allow-frozen. Defense-in-depth defaulted to empty so any frozen file
# is operator-grantable via the flag. Bump ONLY with explicit operator
# authorization for a specific path that must never be touched even by
# accidental grant.
#
# (Historical note: ops/rc_supervisor.py was previously hard-skipped while
# it carried bulk mojibake U+201D bytes that would have been corrupted by
# a naive smart-quote sweep. Item 156 cleared the mojibake via
# tools/repair_mojibake.py with operator grant, after which the file
# became safe to sweep and was removed from this set.)
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


def _replace_201d_safe(raw: bytes) -> tuple[bytes, int, int]:
    """Replace e2 80 9d with 0x22 ONLY when not in mojibake context.

    Mojibake context: byte sequence immediately followed by e2 82 ac OR
    immediately preceded by e2 82 ac. Returns (new_bytes, n_replaced,
    n_skipped_mojibake).
    """
    src = b"\xe2\x80\x9d"
    dst = b"\x22"
    n_repl = 0
    n_moji = 0
    out: list[bytes] = []
    i = 0
    while i < len(raw):
        idx = raw.find(src, i)
        if idx < 0:
            out.append(raw[i:])
            break
        out.append(raw[i:idx])
        # Check mojibake neighbours
        prev = raw[max(0, idx - 3):idx]
        nxt = raw[idx + 3:idx + 6]
        is_moji = (nxt == _MOJI_NEIGHBOUR) or (prev == _MOJI_NEIGHBOUR)
        if is_moji:
            out.append(src)  # keep mojibake intact
            n_moji += 1
        else:
            out.append(dst)
            n_repl += 1
        i = idx + 3
    return (b"".join(out), n_repl, n_moji)


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
                          "ops/rc_supervisor.py is HARD SKIPPED regardless)"))
    args = ap.parse_args()

    # Parse + validate the --allow-frozen override list. The hard-skip set
    # is enforced as a SECOND defensive check after the user-provided list
    # is split.
    _allow_raw = [s.strip() for s in args.allow_frozen.split(",") if s.strip()]
    _allow_frozen = frozenset(p for p in _allow_raw if p not in _HARD_SKIP_FROZEN)
    _hard_skipped_from_allow = [p for p in _allow_raw if p in _HARD_SKIP_FROZEN]

    by_codepoint: Counter[str] = Counter()
    by_ext: Counter[str] = Counter()
    per_file: list[tuple[int, str]] = []
    frozen_hits: list[tuple[int, str]] = []
    moji_tainted: list[tuple[int, int, str]] = []
    total_occ = 0
    total_moji_skipped = 0
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
        # quick prefilter
        has_any = any(rule[1] in raw for rule in _BYTE_RULES)
        if not has_any:
            continue
        # Per-codepoint replacement at byte level.
        new = raw
        file_repl = 0
        file_moji = 0
        per_cp_counts: dict[str, int] = {}
        for cp_char, src_bytes, dst_bytes, label in _BYTE_RULES:
            if src_bytes not in new:
                continue
            if label == "U+201D":
                # context-sensitive: skip mojibake-context bytes
                new, n_repl, n_moji = _replace_201d_safe(new)
                if n_repl:
                    per_cp_counts[label] = n_repl
                    file_repl += n_repl
                if n_moji:
                    file_moji += n_moji
            else:
                n = new.count(src_bytes)
                per_cp_counts[label] = n
                file_repl += n
                new = new.replace(src_bytes, dst_bytes)

        if file_moji > 0:
            moji_tainted.append((file_moji, file_repl, rel_posix))
            total_moji_skipped += file_moji

        if file_repl == 0:
            continue

        # Validate the result is still valid UTF-8 (sanity check).
        try:
            new.decode("utf-8")
        except UnicodeDecodeError:
            skipped_binary += 1
            continue

        total_occ += file_repl
        files_changed += 1
        by_ext[p.suffix.lower() or "<none>"] += file_repl
        for label, c in per_cp_counts.items():
            by_codepoint[label] += c
        per_file.append((file_repl, rel_posix))

        is_frozen = rel_posix in _FROZEN
        is_hard_skip = rel_posix in _HARD_SKIP_FROZEN
        # Second defensive check: even if listed in --allow-frozen, hard-skip
        # files are NEVER rewritten.
        allow_override = (rel_posix in _allow_frozen) and not is_hard_skip
        if is_frozen and not allow_override:
            frozen_hits.append((file_repl, rel_posix))
            continue  # NEVER rewrite frozen files (no operator grant)

        if args.apply:
            tmp = p.with_suffix(p.suffix + ".sqtmp")
            tmp.write_bytes(new)
            os.replace(tmp, p)

    mode = "APPLIED" if args.apply else "DRY-RUN (no writes)"
    print(f"=== strip_smart_quotes {mode} ===")
    print(f"files with replacements : {files_changed}")
    print(f"total replacements      : {total_occ}")
    print(f"mojibake U+201D skipped : {total_moji_skipped}")
    print(f"skipped (utf8 decode)   : {skipped_binary}")
    print(f"frozen files SKIPPED    : {len(frozen_hits)}")
    if _allow_frozen:
        print(f"frozen files OVERRIDDEN : {len(_allow_frozen)} "
              f"(--allow-frozen): {sorted(_allow_frozen)}")
    if _hard_skipped_from_allow:
        print(f"HARD-SKIP from --allow-frozen (override IGNORED): "
              f"{sorted(_hard_skipped_from_allow)}")
    print("by codepoint:")
    for cp, c in by_codepoint.most_common():
        print(f"  {cp}  {c}")
    print("by extension:")
    for ext, c in by_ext.most_common():
        print(f"  {ext:<8} {c}")
    print(f"top {args.top} files by replacement count:")
    for n, rel in sorted(per_file, reverse=True)[:args.top]:
        marker = "  [FROZEN]" if rel in _FROZEN else ""
        print(f"  {n:>6}  {rel}{marker}")
    if frozen_hits:
        print("FROZEN-file hits (NOT rewritten; hand-edit if needed):")
        for n, rel in sorted(frozen_hits, reverse=True):
            print(f"  {n:>6}  {rel}")
    if moji_tainted:
        print("MOJIBAKE-tainted files (U+201D in mojibake context preserved):")
        for moji_c, repl_c, rel in sorted(moji_tainted, reverse=True):
            print(f"  moji_preserved={moji_c:>5}  clean_replaced={repl_c:>4}  {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
