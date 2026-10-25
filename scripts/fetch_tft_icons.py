"""Fill the runtime TFT icon cache for one set (TFT-03, docs/TFT_PROGRAM.md 3.6).

    python scripts/fetch_tft_icons.py --set 18
    python scripts/fetch_tft_icons.py                  # the running set
    python scripts/fetch_tft_icons.py --set 18 --source cdragon --branch latest
    python scripts/fetch_tft_icons.py --set 18 --dry-run

Champion, item, trait and augment icons of the set are read with passive GETs
from the running League client's own lol-game-data assets over the LCU first
and CommunityDragon's mirror of the same plugin second, and written ONLY under
the gitignored data/tft/icon_cache/<set>/<category>/ with an index.json
(apiName -> file + sha256). They are Riot art: local use only, never committed,
never exported in a fixture (NOTICE). Logic: tft/assets/icon_cache.py.

Running set when --set is omitted: the LCU's tftsets.json mDefaultSet paired
with the gameflow queue id (queue 6110 runs Set 17), else the newest ingested
set (tft/tft_set.py resolve_set).

Runs at BELOW_NORMAL priority on Windows; each source keeps a minimum interval
between its GETs (--rate-limit overrides both defaults). Re-runs reuse every
cached icon whose sha256 still matches, so a second run fetches nothing.

Exit: 0 ok / partial / dry run; 1 bad arguments; 2 offline (no source answered
the catalogue; the cache is left untouched).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tft import tft_set  # noqa: E402
from tft.assets import icon_cache as ic  # noqa: E402

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_OFFLINE = 2
SOURCES = ("auto", "lcu", "cdragon")
BELOW_NORMAL_PRIORITY_CLASS = 0x4000


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--set", dest="set_number", type=int, default=None,
                    help="TFT set number (default: the running set)")
    ap.add_argument("--queue-id", type=int, default=None,
                    help="queue id for running-set detection (default: the LCU's)")
    ap.add_argument("--source", choices=SOURCES, default="auto",
                    help="auto = LCU first, CommunityDragon second")
    ap.add_argument("--branch", choices=ic.BRANCHES, default="latest",
                    help="CommunityDragon branch")
    ap.add_argument("--categories", default=",".join(ic.CATEGORIES),
                    help="comma list drawn from " + ",".join(ic.CATEGORIES))
    ap.add_argument("--rate-limit", type=float, default=None,
                    help=f"seconds between GETs per source (default lcu "
                         f"{ic.LCU_INTERVAL_S}, cdragon {ic.CDRAGON_INTERVAL_S})")
    ap.add_argument("--limit", type=int, default=None, help="max icon GETs this run")
    ap.add_argument("--force", action="store_true", help="refetch cached icons too")
    ap.add_argument("--dry-run", action="store_true",
                    help="read the catalogue, report, write nothing")
    ap.add_argument("--root", type=Path, default=None, help="repo root (default: this checkout)")
    return ap.parse_args(argv)


def build_sources(args) -> list:
    pace = {} if args.rate_limit is None else {"min_interval_s": max(0.0, args.rate_limit)}
    out = []
    if args.source in ("auto", "lcu"):
        lcu = ic.LcuSource.discover(**pace)
        if lcu is not None:
            out.append(lcu)
    if args.source in ("auto", "cdragon"):
        out.append(ic.CDragonSource(args.branch, **pace))
    return out


def lower_priority() -> None:
    """BELOW_NORMAL on Windows so a fill never competes with a running game."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.SetPriorityClass(k32.GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS)
    except (OSError, AttributeError):
        pass


def main(argv=None, *, sources=None) -> int:
    args = parse_args(argv)
    cats = tuple(c.strip() for c in args.categories.split(",") if c.strip())
    bad = [c for c in cats if c not in ic.CATEGORIES]
    if bad or not cats:
        print(f"fetch_tft_icons: unknown categories {bad or cats!r}", file=sys.stderr)
        return EXIT_USAGE
    if args.limit is not None and args.limit < 0:
        print("fetch_tft_icons: --limit must be >= 0", file=sys.stderr)
        return EXIT_USAGE
    if sources is None:
        lower_priority()
        sources = build_sources(args)
    n, how = args.set_number, "--set"
    if n is None:
        n, how = ic.detect_set(sources, queue_id=args.queue_id), "LCU tftsets.json + queue id"
        if n is None:
            n, how = tft_set.resolve_set(root=args.root), "newest ingested set"
    try:
        report = ic.fill_cache(n, sources, root=args.root, categories=cats, force=args.force,
                               limit=args.limit, dry_run=args.dry_run)
    except ValueError as exc:
        print(f"fetch_tft_icons: {exc}", file=sys.stderr)
        return EXIT_USAGE
    print(f"set {report.set_number} from {how}")
    print(report.summary())
    return EXIT_OFFLINE if report.status == "offline" else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
