"""CLI for the forward-capture .rofl archiver (core.rofl_archive).

Replays are hard patch-locked (measured 2026-07-19: a match ONE patch behind
already reports `state: "incompatible"` from the LCU), and the client prunes its
own Replays directory - so a replay not copied out promptly is gone permanently.
Run this after games, or on a schedule.

Usage:
    python tools/rofl_archiver.py                 # default dirs
    python tools/rofl_archiver.py --dry-run
    python tools/rofl_archiver.py --source <dir> --archive <dir>
    python tools/rofl_archiver.py --lcu-path      # ask the live client where
                                                  # its Replays dir actually is

Exit codes: 0 nothing-to-do or success, 1 one or more replays failed to copy.
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import ssl
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import rofl_archive  # noqa: E402

_LOCKFILE = Path(r"C:\Riot Games\League of Legends\lockfile")


def _lcu_replays_path():
    """Ask the running client for its Replays directory.

    Returns None if the client is not up or the call fails - the caller falls
    back to the default path rather than treating this as fatal.
    """
    try:
        _name, _pid, port, pw, _proto = _LOCKFILE.read_text().split(":")
    except (OSError, ValueError) as exc:
        logging.getLogger("rc.rofl_archive").info(
            "LCU lockfile unavailable (%s) - using the default replays path", exc
        )
        return None
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    auth = base64.b64encode(f"riot:{pw}".encode()).decode()
    req = urllib.request.Request(
        f"https://127.0.0.1:{port}/lol-replays/v1/rofls/path",
        headers={"Authorization": f"Basic {auth}"},
    )
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
            return Path(json.loads(resp.read()))
    except (OSError, ValueError) as exc:
        logging.getLogger("rc.rofl_archive").info(
            "LCU replays-path query failed (%s) - using the default", exc
        )
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Archive League .rofl replays.")
    ap.add_argument("--source", default=None, help="Replays dir to read from")
    ap.add_argument("--archive", default=None, help="archive dir to write to")
    ap.add_argument("--index", default=None, help="index json path")
    ap.add_argument("--lcu-path", action="store_true",
                    help="ask the running client for its Replays dir")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be archived, copy nothing")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    source = Path(args.source) if args.source else None
    if source is None and args.lcu_path:
        source = _lcu_replays_path()
    if source is None:
        source = rofl_archive.default_replays_dir()
    archive = Path(args.archive) if args.archive else rofl_archive.default_archive_dir()
    index = Path(args.index) if args.index else archive / "index.json"

    if args.dry_run:
        if not source.is_dir():
            print(f"source dir absent: {source}")
            return 0
        known = set()
        if index.exists():
            try:
                known = set(json.loads(index.read_text(encoding="utf-8"))["replays"])
            except (OSError, ValueError, KeyError, TypeError):
                # Dry-run only: an unreadable index just means "assume nothing
                # is archived", which over-reports rather than under-reports.
                known = set()
        pending = [
            n for n in sorted(p.name for p in source.iterdir() if p.is_file())
            if (mid := rofl_archive.match_id_from_name(n)) and mid not in known
        ]
        print(f"source : {source}")
        print(f"archive: {archive}")
        print(f"would archive {len(pending)} replay(s):")
        for n in pending:
            print(f"  {n}")
        return 0

    res = rofl_archive.archive_replays(source, archive, index)
    print(f"source : {source}")
    print(f"archive: {archive}")
    print(f"copied={len(res.copied)} skipped={len(res.skipped)} failed={len(res.failed)}")
    for mid in res.copied:
        print(f"  + {mid}")
    for mid in res.failed:
        print(f"  ! {mid}")
    return 1 if res.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
