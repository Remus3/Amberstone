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
_DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "rewind_history.db"


class LcuReplayClient:
    """Thin transport for the LCU replay routes.

    Auth comes from the lockfile every run - the port and token rotate on every
    client restart, so any hardcoded pair is stale almost immediately.
    """

    def __init__(self, lockfile=_LOCKFILE):
        _name, _pid, self.port, pw, _proto = Path(lockfile).read_text().split(":")
        self._ctx = ssl.create_default_context()
        self._ctx.check_hostname = False
        self._ctx.verify_mode = ssl.CERT_NONE
        self._auth = base64.b64encode(f"riot:{pw}".encode()).decode()

    def _call(self, path, method="GET"):
        req = urllib.request.Request(
            f"https://127.0.0.1:{self.port}{path}", method=method,
            data=b"{}" if method == "POST" else None,
            headers={"Authorization": f"Basic {self._auth}",
                     "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, context=self._ctx, timeout=15) as resp:
                body = resp.read()
                return resp.status, (json.loads(body) if body else None)
        except urllib.error.HTTPError as exc:
            return exc.code, None
        except (OSError, ValueError) as exc:
            logging.getLogger("rc.rofl_archive").warning("LCU call %s failed: %s", path, exc)
            return None, None

    def game_version(self):
        _s, body = self._call("/lol-replays/v1/configuration")
        return (body or {}).get("gameVersion")

    def request_download(self, game_id):
        # The /graceful variant runs a real compatibility check first; the plain
        # /download variant reports "incompatible" immediately (measured).
        status, _ = self._call(f"/lol-replays/v1/rofls/{game_id}/download/graceful", "POST")
        return status

    def metadata(self, game_id):
        _s, body = self._call(f"/lol-replays/v1/metadata/{game_id}")
        return body or {}


def _db_rows(db_path, limit=None):
    """(match_id, patch) newest-first from rewind_history.db, read-only."""
    import sqlite3
    q = "select match_id, patch from matches order by game_creation_ts desc"
    if limit:
        q += f" limit {int(limit)}"
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return list(con.execute(q))
    finally:
        con.close()


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
    ap.add_argument("--pull", action="store_true",
                    help="ask the client to download current-patch replays from "
                         "rewind_history.db before archiving")
    ap.add_argument("--db", default=None, help="rewind_history.db path (--pull)")
    ap.add_argument("--limit", type=int, default=50,
                    help="max matches to consider when pulling (default 50)")
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

    if args.pull:
        db = Path(args.db) if args.db else _DEFAULT_DB
        try:
            client = LcuReplayClient()
        except (OSError, ValueError) as exc:
            print(f"cannot pull - LCU lockfile unavailable ({exc}); is the client running?")
            return 1
        gv = client.game_version()
        current = rofl_archive.patch_from_game_version(gv)
        if not current:
            print(f"cannot pull - unreadable gameVersion from the client: {gv!r}")
            return 1
        known = set(rofl_archive.load_index(index).get("replays", {}))
        rows = _db_rows(db, args.limit)
        pullable = rofl_archive.select_pullable(rows, current, already=known)
        print(f"client patch {current} (gameVersion {gv})")
        print(f"considered {len(rows)} match(es) -> {len(pullable)} on the current patch")
        if not pullable:
            # Expected whenever the DB has not caught up to the live patch.
            # Say so plainly rather than printing a silent zero.
            print("nothing to pull: no match in the DB is on the current patch "
                  "(replays are patch-locked, so older matches can never be fetched)")
        else:
            pr = rofl_archive.pull_replays(pullable, client)
            print(f"pull: downloaded={len(pr.downloaded)} "
                  f"incompatible={len(pr.incompatible)} "
                  f"timed_out={len(pr.timed_out)} failed={len(pr.failed)}")
            for mid in pr.downloaded:
                print(f"  v {mid}")

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
