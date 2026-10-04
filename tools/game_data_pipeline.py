# arch: multi-source game-data pipeline CLI (fetch cache -> reconciled build with provenance + caveats -> verify / diff) | section=tools | frozen=no
"""Game-data reconciliation pipeline (P1-4).

    python tools/game_data_pipeline.py build [--patch 16.18.1]
    python tools/game_data_pipeline.py diff --from 16.18.1 --to 16.19.1

``build`` fetches every source for the patch (raw bodies cached under
``data/game_data/_cache/<patch>/``, so a re-run skips work already done),
reconciles them (``data/game_data/<patch>/champions.json`` / ``items.json``
with a per-field ``_provenance`` map, ``caveats.json`` with every disagreement
and the value chosen, ``report.json``), and prints the verification report.

Exit codes: 0 = built, zero unexplained disagreements; 1 = built but the
verify step found an unexplained disagreement; 2 = a required source could not
be fetched or parsed (nothing is written).

Network etiquette: official API first, one in-process client (blocklist,
1 request/second per host, environment proxies ignored), one request per
source file per patch, cached; the wiki is read through a single raw-module
request, never by page scraping.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.game_data import build as gd_build  # noqa: E402
from lib.game_data import fetch as gd_fetch  # noqa: E402

DATA_ROOT = ROOT / "data" / "game_data"


def _summary(report: dict) -> list[str]:
    lines = [f"patch {report['patch']}"]
    for src, c in report["counts_by_source"].items():
        lines.append(f"  {src}: {c['champions']} champions, {c['items']} items")
    for src, why in report["excluded_sources"].items():
        lines.append(f"  {src}: EXCLUDED ({why})")
    lines.append(f"reconciled fields: {report['reconciled_fields']}")
    lines.append(f"unexplained disagreements: {len(report['unexplained'])}")
    return lines


def cmd_build(args: argparse.Namespace, client=None) -> int:
    data_root = Path(args.data_root)
    try:
        fetched = gd_fetch.fetch(args.patch, client=client, cache_dir=data_root / "_cache")
    except gd_fetch.MissingSourceError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 2
    b = gd_build.reconcile(fetched)
    gd_build.write_build(b, data_root / b.version)
    for line in _summary(b.report):
        print(line)
    return 1 if b.report["unexplained"] else 0


def cmd_diff(args: argparse.Namespace) -> int:
    data_root = Path(args.data_root)
    d = gd_build.diff_builds(data_root / args.from_patch, data_root / args.to_patch)
    print(json.dumps(d, indent=1, sort_keys=True))
    return 0


def main(argv: list[str] | None = None, client=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-root", default=str(DATA_ROOT))
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--patch", default=None, help="patch to build (default: newest in the version feed)")
    d = sub.add_parser("diff")
    d.add_argument("--from", dest="from_patch", required=True)
    d.add_argument("--to", dest="to_patch", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "build":
        return cmd_build(args, client=client)
    return cmd_diff(args)


if __name__ == "__main__":
    sys.exit(main())
