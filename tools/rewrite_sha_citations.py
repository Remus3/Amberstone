"""Remap abbreviated commit-SHA citations in authored docs after a history rewrite.

`git filter-repo` rewrites every commit id in the repository. Any doc that
cites a SHA is therefore stale the instant the rewrite lands - and this repo
cites a lot of them, overwhelmingly in `docs/LEDGER.md`. Left alone, the
rewrite would convert a mostly-resolvable citation record into a wholly
unresolvable one in a single step.

filter-repo writes `.git/filter-repo/commit-map`, a two-column
`<old-sha> <new-sha>` table covering every commit it saw. A commit that the
rewrite DROPPED maps to forty zeros. That distinction is the whole reason this
tool reports rather than just substitutes: a dropped commit's citation cannot
be repaired, and silently leaving it looks identical to a citation that was
never touched.

Design notes worth keeping:

- Citations are abbreviated to 7-40 hex chars, so the map is indexed by
  PREFIX. A prefix that matches two different old commits is reported as
  ambiguous and left alone rather than guessed at.
- The replacement is abbreviated to the SAME LENGTH as the text it replaces,
  so an 8-char citation stays 8 chars and the prose does not reflow.
- Not every 7-40 char hex run is a SHA. The default pattern requires the run
  to be delimited by a non-hex-word boundary, and `--require-backticks`
  narrows further to the repo's dominant `` `sha` `` citation style.
- Dry run is the default. `--apply` is required to write.

Usage:
    python tools/rewrite_sha_citations.py --map .git/filter-repo/commit-map \\
        docs/LEDGER.md docs/ORCHESTRATION_PLAN.md
    python tools/rewrite_sha_citations.py --map <path> --apply <files...>
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ZERO_SHA = "0" * 40
# 7 is git's historical default abbreviation; 40 is a full sha.
SHA_RE = re.compile(r"(?<![0-9a-fA-F])([0-9a-f]{7,40})(?![0-9a-fA-F])")
BACKTICKED_SHA_RE = re.compile(r"(?<=`)([0-9a-f]{7,40})(?=`)")


class CommitMap:
    """Old-sha prefix lookup over a filter-repo commit-map."""

    def __init__(self, pairs: dict[str, str]) -> None:
        self._pairs = pairs

    @classmethod
    def from_file(cls, path: Path) -> "CommitMap":
        pairs: dict[str, str] = {}
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 2:
                continue
            old, new = parts
            # filter-repo emits a literal "old new" header on some versions.
            if len(old) != 40 or len(new) != 40:
                continue
            pairs[old.lower()] = new.lower()
        if not pairs:
            raise ValueError(f"no usable old/new pairs found in {path}")
        return cls(pairs)

    def resolve(self, prefix: str) -> tuple[str, str]:
        """Return (status, new_sha) for an abbreviated old sha.

        status is one of: "ok", "unknown", "ambiguous", "dropped".
        """
        prefix = prefix.lower()
        exact = self._pairs.get(prefix)
        if exact is not None:
            matches = [exact]
        else:
            matches = [new for old, new in self._pairs.items() if old.startswith(prefix)]
            # Deduplicate: several old commits can rewrite onto one new commit.
            matches = sorted(set(matches))
        if not matches:
            return ("unknown", "")
        if len(matches) > 1:
            return ("ambiguous", "")
        new = matches[0]
        if new == ZERO_SHA:
            return ("dropped", "")
        return ("ok", new)


def rewrite_text(text: str, cmap: CommitMap, pattern: re.Pattern[str]):
    """Return (new_text, stats, problems). Pure - does no IO."""
    stats = {"ok": 0, "unknown": 0, "ambiguous": 0, "dropped": 0}
    problems: list[tuple[int, str, str]] = []

    # Precompute line numbers so a problem can be reported as file:line.
    line_starts = [0]
    for m in re.finditer(r"\n", text):
        line_starts.append(m.end())

    def line_of(pos: int) -> int:
        lo, hi = 0, len(line_starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if line_starts[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1

    def sub(m: re.Match[str]) -> str:
        token = m.group(1)
        status, new = cmap.resolve(token)
        stats[status] += 1
        if status != "ok":
            problems.append((line_of(m.start(1)), token, status))
            return token
        return new[: len(token)]

    return pattern.sub(sub, text), stats, problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--map", required=True, type=Path,
                    help="path to .git/filter-repo/commit-map")
    ap.add_argument("--apply", action="store_true",
                    help="write the files (default is a dry run)")
    ap.add_argument("--require-backticks", action="store_true",
                    help="only rewrite shas already wrapped in backticks")
    ap.add_argument("--max-problems", type=int, default=25,
                    help="how many unresolvable citations to print per file")
    args = ap.parse_args(argv)

    cmap = CommitMap.from_file(args.map)
    pattern = BACKTICKED_SHA_RE if args.require_backticks else SHA_RE

    totals = {"ok": 0, "unknown": 0, "ambiguous": 0, "dropped": 0}
    changed_any = False

    for path in args.files:
        if not path.exists():
            print(f"SKIP  {path} (does not exist)")
            continue
        original = path.read_text(encoding="utf-8")
        updated, stats, problems = rewrite_text(original, cmap, pattern)
        for k in totals:
            totals[k] += stats[k]

        verb = "would remap" if not args.apply else "remapped"
        print(f"{path}: {verb} {stats['ok']}, "
              f"dropped {stats['dropped']}, unknown {stats['unknown']}, "
              f"ambiguous {stats['ambiguous']}")
        for line_no, token, status in problems[: args.max_problems]:
            print(f"  {path}:{line_no}: {token} -> {status.upper()}")
        if len(problems) > args.max_problems:
            print(f"  ... and {len(problems) - args.max_problems} more")

        if updated != original:
            changed_any = True
            if args.apply:
                # Atomic write: overlays and other readers poll mid-write.
                tmp = path.with_suffix(path.suffix + ".tmp")
                tmp.write_text(updated, encoding="utf-8", newline="")
                tmp.replace(path)

    print(f"\nTOTAL: remapped {totals['ok']}, dropped {totals['dropped']}, "
          f"unknown {totals['unknown']}, ambiguous {totals['ambiguous']}")
    if not args.apply and changed_any:
        print("dry run - nothing written. Re-run with --apply.")
    # A dropped citation is a real, permanent loss and should be visible in
    # the exit code so a wrap script cannot skip past it.
    return 1 if totals["dropped"] else 0


if __name__ == "__main__":
    sys.exit(main())
