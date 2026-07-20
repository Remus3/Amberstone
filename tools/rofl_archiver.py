"""CLI for the .rofl archiver (core.rofl_archive).

`--pull` runs TWO independent pulls, and neither can stop the other:

  1. Riot's own `/lol/match/v5/matches/by-puuid/{puuid}/replays` - five
     pre-signed URLs per account, no game client, no patch gate. This is the
     primary route. `--no-api-pull` opts out.
  2. The local LCU, which can only fetch replays on the client's CURRENT patch
     (measured: one patch behind already reports "incompatible"). Needs a
     running client, so it is skipped for most of a 15-minute duty cycle.
     `--no-lcu-pull` opts out.

Both are SKIPS when unavailable, never failures - the scheduled task must keep
reporting 0 so that a real fault is visible when it happens.

Usage:
    python tools/rofl_archiver.py                 # default dirs, archive only
    python tools/rofl_archiver.py --pull --extract --highlights --quiet
    python tools/rofl_archiver.py --dry-run
    python tools/rofl_archiver.py --account SamplePlayer#Vayne --pull
    python tools/rofl_archiver.py --lcu-path      # ask the live client where
                                                  # its Replays dir actually is

Exit codes: 0 nothing-to-do or success, 1 one or more replays failed to copy or
download. A replay Riot no longer retains (404) is `gone`, not a failure.
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

from core import riot_api  # noqa: E402
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


def _api_pull(accounts, archive, index) -> int:
    """Pull each account's retained replays straight from Riot. Returns the
    failure count (0 when everything worked or was benignly skipped).

    Two things this deliberately does NOT do:
      - resolve a PUUID from storage. PUUIDs are encrypted PER API KEY, so a
        stored one is a dead handle the moment the key changes. Always resolve
        from the Riot ID.
      - back off. The limit on this route is 20000/10s; the binding limits are
        the 5-per-account window and the 1-hour URL expiry, neither of which
        retrying helps.
    """
    failures = 0
    for name, tag in accounts:
        riot_id = f"{name}#{tag}"
        account = riot_api.get_account_by_riot_id(name, tag)
        puuid = (account or {}).get("puuid")
        if not puuid:
            # No key, an unentitled key, or a transient error. On a 15-minute
            # schedule this is routine - report it, never fail the run.
            print(f"api pull SKIPPED for {riot_id} - could not resolve a PUUID "
                  f"(is API-Key-Riot.txt the PRODUCT key?)")
            continue

        urls = riot_api.get_replay_urls(puuid)
        if urls is None:
            print(f"api pull SKIPPED for {riot_id} - /replays returned nothing "
                  f"(the dev key is not entitled to this route)")
            continue

        ids = [rofl_archive.match_id_from_replay_url(u) for u in urls]
        rofl_archive.record_pull_observation(
            archive, riot_id, [i for i in ids if i])

        dl = rofl_archive.download_replays(urls, archive, index)
        failures += len(dl.failed)
        print(f"api pull {riot_id}: served={len(urls)} "
              f"downloaded={len(dl.downloaded)} skipped={len(dl.skipped)} "
              f"expired={len(dl.expired)} gone={len(dl.gone)} "
              f"failed={len(dl.failed)}")
        for mid in dl.downloaded:
            print(f"  v {mid}")

    report = rofl_archive.pull_rotation_report(archive)
    for riot_id, r in sorted(report.items()):
        if r["rotated"] is None:
            # One observation cannot answer the question; say so rather than
            # printing a number that reads like an answer.
            print(f"rotation {riot_id}: 1 observation - need a second pull, "
                  f"with games played in between, to tell")
        else:
            print(f"rotation {riot_id}: rotated={r['rotated']} over "
                  f"{r['observations']} observations, "
                  f"new={len(r['new_ids'])} dropped={len(r['dropped_ids'])}")
    return failures


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
    ap.add_argument("--extract", action="store_true",
                    help="extract the Layer-1 stats blob from every archived "
                         "replay into <archive>/stats/<match_id>.json")
    ap.add_argument("--force", action="store_true",
                    help="re-extract sidecars that already exist (--extract)")
    ap.add_argument("--highlights", action="store_true",
                    help="also archive highlight clips out of the client's "
                         "Highlights dir (filenames carry patch + match id)")
    ap.add_argument("--highlights-source", default=None,
                    help="override the Highlights dir to read from")
    ap.add_argument("--no-api-pull", action="store_true",
                    help="skip the sanctioned Match-V5 /replays pull (--pull "
                         "runs it by default; it needs no game client)")
    ap.add_argument("--no-lcu-pull", action="store_true",
                    help="skip the LCU half of --pull (which needs a running "
                         "client on the match's own patch)")
    ap.add_argument("--account", action="append", default=None,
                    metavar="NAME#TAG",
                    help="Riot ID to pull for; repeatable. Defaults to both "
                         "live accounts.")
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

    # The sanctioned route first: Riot serves the .rofl files itself to an
    # entitled key, with no client and no patch gate, so it runs even when the
    # LCU half below cannot. Exactly 5 per account, rotating - the archive is
    # what accumulates, which is why cadence matters more than batch size.
    api_failed = 0
    if args.pull and not args.no_api_pull:
        try:
            accounts = ([rofl_archive.parse_account(a) for a in args.account]
                        if args.account else rofl_archive.DEFAULT_ACCOUNTS)
        except ValueError as exc:
            print(f"api pull SKIPPED - {exc}")
            accounts = []
        if accounts:
            api_failed = _api_pull(accounts, archive, index)

    # A closed client is the NORMAL case on a 15-minute schedule, so a failed
    # pull is a SKIP, never a failure - and it must not stop the archive /
    # highlights / extract steps below, none of which need the LCU at all.
    pull_client = None
    if args.pull and not args.no_lcu_pull:
        try:
            pull_client = LcuReplayClient()
        except (OSError, ValueError) as exc:
            print(f"pull SKIPPED - LCU unavailable ({exc}); is the client running?")

    if pull_client is not None:
        client = pull_client
        db = Path(args.db) if args.db else _DEFAULT_DB
        gv = client.game_version()
        current = rofl_archive.patch_from_game_version(gv)
        if not current:
            print(f"pull SKIPPED - unreadable gameVersion from the client: {gv!r}")
            current = None
    if pull_client is not None and current:
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

    hl_failed = 0
    if args.highlights:
        hl_src = (Path(args.highlights_source) if args.highlights_source
                  else rofl_archive.default_highlights_dir())
        hl = rofl_archive.archive_highlights(hl_src, archive, archive / "clips.json")
        hl_failed = len(hl.failed)
        print(f"clips  : {hl_src}")
        print(f"clips  : copied={len(hl.copied)} skipped={len(hl.skipped)} "
              f"failed={hl_failed}")
        for k in hl.copied:
            print(f"  ~ {k}")
        for k in hl.failed:
            print(f"  ! {k}")

    ex_failed = 0
    if args.extract:
        ex = rofl_archive.extract_archive(archive, force=args.force)
        ex_failed = len(ex.failed)
        print(f"extract: extracted={len(ex.extracted)} skipped={len(ex.skipped)} "
              f"failed={ex_failed} -> {archive / 'stats'}")
        for mid in ex.extracted:
            print(f"  * {mid}")
        for mid in ex.failed:
            print(f"  ! {mid}")

    return 1 if (res.failed or ex_failed or hl_failed or api_failed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
