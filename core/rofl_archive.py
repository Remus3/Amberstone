"""Archiver for League replay (.rofl) files - two sources, one archive.

THE PRIMARY SOURCE, measured 2026-07-19: Riot serves the files itself.
`GET /lol/match/v5/matches/by-puuid/{puuid}/replays` returns 200 with five
pre-signed S3 URLs, needs no game client and has no patch gate, and is an
APPROVED endpoint of the product app (834837) - the dev key 400s on it.
`download_replays` is that path. Two measured properties shape it: the bodies
arrive GZIP-framed (urllib will not decompress them for you), and an account
whose files Riot no longer retains 404s on every URL - permanent and expected,
so it is counted as `gone`, never as a failure.

That route serves exactly FIVE per account: a rolling recency window, NOT an
archive. Its value comes entirely from cadence - pull often, keep what falls
out the back - which is why every path below is idempotent and additive, and
why each pull records what it saw in `pull_log.jsonl` (see
`pull_rotation_report`).

THE SECOND SOURCE is the local client, measured against the live LCU the same
day:

`POST /lol-replays/v1/rofls/{gameId}/download` returns 204 for any game id, but
`GET /lol-replays/v1/metadata/{gameId}` then reports `state: "incompatible"` for
anything not on the CURRENT game patch - confirmed for a patch-16.13 match (only
ONE patch behind, client on 16.14.794.5912) and for a 14.24 match from Dec 2024.
So the LCU route is hard patch-locked: it can only fetch a replay while that
replay's own patch is live. This is a limit of the CLIENT, not of replay
availability in general - the Match-V5 route above has no such gate.

The client also prunes its own Replays directory, so anything it does write
must be copied out promptly.

Both paths land in one archive, keyed on match id. They spell the same match
differently - the client writes "NA1-5595187452.rofl" and the API path writes
the underscore form - so the skip check looks for EITHER, or the same game gets
downloaded twice (measured on the live archive).

This module is deliberately boring:
  - idempotent (keyed on match id, so re-running is free),
  - atomic (tmp + os.replace, per the repo's atomic-write rule - a half-copied
    13 MB binary would be indistinguishable from a good one),
  - NEVER deletes from the source (the client owns that directory),
  - and it does not silently swallow: a corrupt index is recovered from AND
    logged at WARNING (this module was written during the silent-no-op batch;
    recovery without a record is exactly the defect that program exists to fix).

Once archived, a replay can be replayed through the Replay API for per-timestamp
item reconstruction (ROADMAP RM-106b) - the only route that recovers item
progression for event modes such as KIWI, which Match-V5 refuses and the LCU
timeline does not carry.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# The scratch-name and WinError-5 retry primitives are imported rather than
# re-rolled: this module had its own copies of both and both were wrong (RM-310,
# and the shared-scratch defect polled_json fixed for itself in lane 8 cycle
# 24). The two underscore-prefixed names are package-internal by convention, not
# by contract - duplicating them is what produced the divergence being fixed
# here. polled_json imports stdlib only, so there is no import cycle.
from core.polled_json import (
    _replace_with_retry,
    _scratch_path,
    atomic_write_bytes,
    atomic_write_json,
)

logger = logging.getLogger("rc.rofl_archive")

ROFL_SUFFIX = ".rofl"

# Client naming is "<PLATFORM>-<gameId>.rofl" (a hyphen); RC / Match-V5 use
# "<PLATFORM>_<gameId>". Accept either separator, emit the underscore form so the
# key joins directly against matches.match_id in data/rewind_history.db.
_NAME_RE = re.compile(r"^(?P<platform>[A-Za-z0-9]+)[-_](?P<game_id>\d+)$")

_ENV_ARCHIVE_DIR = "RC_ROFL_ARCHIVE_DIR"
_DEFAULT_ARCHIVE = Path.home() / "Documents" / "RC_ROFL_Archive"
_DEFAULT_REPLAYS = Path.home() / "Documents" / "League of Legends" / "Replays"


_GAME_VERSION_RE = re.compile(r"^(?P<major>\d+)\.(?P<minor>\d+)(?:\.|$)")

# Terminal states observed on the live client. "checking" is the only transient
# one; anything else ends the poll.
STATE_WATCH = "watch"
STATE_INCOMPATIBLE = "incompatible"
STATE_CHECKING = "checking"


@dataclass
class PullResult:
    """Outcome of one pull pass. Lists hold match ids.

    `incompatible` is expected to be the LARGE bucket - replays are locked to
    the current patch - which is exactly why it is counted rather than dropped.
    A pull where everything came back incompatible must not look like a success.
    """

    downloaded: list = field(default_factory=list)
    incompatible: list = field(default_factory=list)
    timed_out: list = field(default_factory=list)
    failed: list = field(default_factory=list)


def patch_from_game_version(game_version):
    """"16.14.794.5912" -> "16.14". None when it cannot be parsed.

    The LCU reports a 4-part build string at
    GET /lol-replays/v1/configuration; rewind_history.db stores the 2-part
    patch. This is the join between them.
    """
    if not game_version or not isinstance(game_version, str):
        return None
    m = _GAME_VERSION_RE.match(game_version.strip())
    if not m:
        return None
    return f"{m.group('major')}.{m.group('minor')}"


def game_id_from_match_id(match_id):
    """"NA1_5592802194" -> "5592802194" (the id the LCU replay routes take)."""
    if not match_id or not isinstance(match_id, str):
        return None
    tail = match_id.rsplit("_", 1)[-1].strip()
    return tail if tail.isdigit() else None


def select_pullable(rows, current_patch, already=None):
    """Match ids worth asking the client to download.

    *rows* is an iterable of (match_id, patch). Only the CURRENT patch is
    pullable - measured: a match one patch behind already reports
    "incompatible" - so everything else is filtered out before any request is
    made rather than discovered one round-trip at a time.
    """
    already = already or set()
    out = []
    for match_id, patch in rows:
        if not patch or not match_id:
            continue
        if patch != current_patch:
            continue
        if match_id in already:
            continue
        out.append(match_id)
    return out


def pull_replays(match_ids, client, poll_interval=2.0, max_polls=15):
    """Ask the client to download each replay, then poll to a terminal state.

    *client* needs `request_download(game_id) -> int` (HTTP status) and
    `metadata(game_id) -> dict`. Injecting it keeps this loop testable without
    a live client and keeps the transport out of the logic.

    Nothing here retries: an "incompatible" verdict is final (the patch will
    only move further away), and hammering the client would be pointless.
    """
    res = PullResult()
    for match_id in match_ids or []:
        game_id = game_id_from_match_id(match_id)
        if game_id is None:
            logger.warning("skipping unparseable match id: %r", match_id)
            res.failed.append(match_id)
            continue

        status = client.request_download(game_id)
        if status not in (200, 202, 204):
            logger.warning("download request for %s returned HTTP %s", match_id, status)
            res.failed.append(match_id)
            continue

        state = None
        for _ in range(max_polls):
            state = (client.metadata(game_id) or {}).get("state")
            if state != STATE_CHECKING:
                break
            if poll_interval:
                time.sleep(poll_interval)

        if state == STATE_WATCH:
            logger.info("replay available: %s", match_id)
            res.downloaded.append(match_id)
        elif state == STATE_INCOMPATIBLE:
            # Expected for anything off the current patch. Logged at INFO, not
            # swallowed: a silent skip here would hide a fully-failed pull.
            logger.info("replay incompatible (patch-locked): %s", match_id)
            res.incompatible.append(match_id)
        elif state == STATE_CHECKING:
            logger.warning("replay still checking after %d polls: %s", max_polls, match_id)
            res.timed_out.append(match_id)
        else:
            logger.warning("replay %s ended in unexpected state %r", match_id, state)
            res.failed.append(match_id)
    return res


_BLOB_ANCHOR = b'{"gameLength"'

# Highlight clips: "16-13_NA1-5592802194_01.webm" = patch 16.13, match
# NA1_5592802194, clip index 01. The filename is a direct join key onto
# matches.match_id and onto the archived .rofl for the same game.
_CLIP_RE = re.compile(
    r"^(?P<pmaj>\d+)-(?P<pmin>\d+)_(?P<platform>[A-Za-z0-9]+)-(?P<game_id>\d+)_(?P<idx>\d+)$"
)
_CLIP_SUFFIXES = {".webm", ".mp4", ".mkv", ".avi", ".mov"}

_DEFAULT_HIGHLIGHTS = (
    Path.home() / "Documents" / "League of Legends" / "Highlights"
)


def default_highlights_dir() -> Path:
    """The client's own Highlights directory (clip capture target)."""
    return _DEFAULT_HIGHLIGHTS


def highlight_key_from_name(name: str):
    """"16-13_NA1-5592802194_01.webm" -> ("NA1_5592802194", "16.13", "01").

    None when the file is not a recognisable clip, so a stray file in the
    Highlights directory is skipped rather than fatal.
    """
    p = Path(name)
    if p.suffix.lower() not in _CLIP_SUFFIXES:
        return None
    m = _CLIP_RE.match(p.stem)
    if not m:
        return None
    match_id = f"{m.group('platform')}_{m.group('game_id')}"
    patch = f"{m.group('pmaj')}.{m.group('pmin')}"
    return match_id, patch, m.group("idx")


def archive_highlights(source_dir, archive_dir, index_path=None) -> ArchiveResult:
    """Copy every not-yet-archived highlight clip into <archive_dir>/highlights.

    Same contract as archive_replays: idempotent, atomic, and it NEVER deletes
    from the source (the client owns that directory). Keyed on
    "<match_id>_<clip_index>" so two clips of the SAME game cannot collide and
    silently drop one.
    """
    source_dir = Path(source_dir)
    archive_dir = Path(archive_dir)
    index_path = Path(index_path) if index_path else archive_dir / "clips.json"
    dest_dir = archive_dir / "highlights"

    res = ArchiveResult()
    if not source_dir.is_dir():
        logger.debug("highlights dir absent, nothing to archive: %s", source_dir)
        return res

    index = _load_index(index_path, key="clips")
    known = index["clips"]
    dirty = False

    for entry in sorted(source_dir.iterdir()):
        if not entry.is_file():
            continue
        parsed = highlight_key_from_name(entry.name)
        if parsed is None:
            continue
        match_id, patch, idx = parsed
        clip_key = f"{match_id}_{idx}"

        dest = dest_dir / entry.name
        if clip_key in known and dest.exists():
            res.skipped.append(clip_key)
            continue

        try:
            size = entry.stat().st_size
            _atomic_copy(entry, dest)
        except OSError as exc:
            # Loud: a clip we failed to copy is a clip lost once the client
            # prunes it.
            logger.warning("failed to archive clip %s: %s", entry.name, exc)
            res.failed.append(clip_key)
            continue

        known[clip_key] = {
            "file": entry.name,
            "match_id": match_id,
            "patch": patch,
            "clip_index": idx,
            "size": size,
            "archived_at": datetime.now(timezone.utc).isoformat(),
        }
        dirty = True
        res.copied.append(clip_key)
        logger.info("archived clip %s (patch %s, %d bytes)", clip_key, patch, size)

    if dirty or not index_path.exists():
        _atomic_write_json(index_path, index)
    return res


# ---------------------------------------------------------------------------
# Sanctioned Match-V5 pull (GET .../matches/by-puuid/{puuid}/replays)
# ---------------------------------------------------------------------------
#
# Riot serves the .rofl files itself, pre-signed, to an entitled API key. This
# is a strictly better route than the LCU pull above: no client, no patch gate.
# It is NOT an archive - exactly five per account, rotating - so the value comes
# from running it on a cadence and keeping what falls out the back of the
# window. Everything below is therefore idempotent and additive.

DEFAULT_ACCOUNTS = [("SamplePlayer", "Trist"), ("SamplePlayer", "Vayne")]

_AMZ_DATE_FMT = "%Y%m%dT%H%M%SZ"

# A real replay body starts with the container magic. S3 can hand back an XML
# error document under a 200; writing that under a .rofl name would poison both
# the archive and every later extract pass.
_ROFL_MAGIC = b"RIOT"


def parse_account(riot_id: str):
    """"SamplePlayer#Vayne" -> ("SamplePlayer", "Vayne"). Raises on a bare name.

    The Riot ID is the durable identity - PUUIDs are scoped to whichever API
    key resolved them, so every pull re-resolves from this pair rather than
    reading a stored PUUID.
    """
    name, sep, tag = str(riot_id or "").partition("#")
    if not sep or not name.strip() or not tag.strip():
        raise ValueError(f"expected a Riot ID of the form name#tag, got {riot_id!r}")
    return name.strip(), tag.strip()


def match_id_from_replay_url(url: str):
    """Pull "NA1_5595187452" out of a pre-signed replay URL.

    The authoritative name is in `response-content-disposition`
    (`attachment; filename="NA1_5595187452.rofl"`), which is already in RC's
    underscore form. The URL path is the fallback. None when neither parses, so
    an unexpected URL is skipped rather than fatal.
    """
    if not url:
        return None
    parts = urllib.parse.urlsplit(str(url))
    disp = urllib.parse.parse_qs(parts.query).get("response-content-disposition")
    if disp:
        m = re.search(r'filename="?([^";]+)"?', disp[0])
        if m:
            mid = match_id_from_name(m.group(1).strip())
            if mid:
                return mid
    return match_id_from_name(parts.path.rsplit("/", 1)[-1])


def replay_url_expired(url: str, now=None) -> bool:
    """True once the S3 signature is past `X-Amz-Date + X-Amz-Expires`.

    MEASURED bound: `X-Amz-Expires=3600` - one hour. An expired URL 403s with
    no useful body, so catching it here turns a mystery transport failure into
    a named outcome. A URL with no signature returns False: unknown expiry must
    not silently drop a link that may well be good.
    """
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(str(url or "")).query)
    stamp = (q.get("X-Amz-Date") or [None])[0]
    expires = (q.get("X-Amz-Expires") or [None])[0]
    if not stamp or not expires:
        return False
    try:
        signed = datetime.strptime(stamp, _AMZ_DATE_FMT).replace(tzinfo=timezone.utc)
        deadline = signed.timestamp() + int(expires)
    except (ValueError, TypeError) as exc:
        logger.warning("unparseable signature on replay URL (%s) - trying it anyway", exc)
        return False
    now = time.time() if now is None else now
    return now > deadline


def _archived_file(archive_dir: Path, match_id: str):
    """The on-disk replay for *match_id*, whichever separator it was saved
    under. None when the archive does not hold it."""
    platform, _sep, game_id = str(match_id).partition("_")
    for name in (f"{match_id}{ROFL_SUFFIX}",
                 f"{platform}-{game_id}{ROFL_SUFFIX}"):
        candidate = archive_dir / name
        if candidate.exists():
            return candidate
    return None


_PULL_LOG = "pull_log.jsonl"


def record_pull_observation(archive_dir, account, match_ids, now=None) -> None:
    """Append what one pull SAW for one account.

    The open question this answers over time: Riot serves exactly five replays
    per account - does that window ROTATE as new games are played? If it does,
    running this on a cadence converts a rolling window into a permanent
    archive, and no bulk trick is needed. That cannot be settled inside one
    run, so each run leaves evidence instead.

    Append-only JSONL, and a write failure is logged rather than raised: losing
    an observation must never fail the pull that actually saved a replay.
    """
    archive_dir = Path(archive_dir)
    row = {
        "account": account,
        "match_ids": list(match_ids or []),
        "observed_at_unix": time.time() if now is None else now,
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
        with (archive_dir / _PULL_LOG).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    except OSError as exc:
        logger.warning("could not record pull observation for %s: %s", account, exc)


def load_pull_observations(archive_dir) -> list:
    """Every recorded observation, oldest first. Corrupt lines are skipped
    LOUDLY - a silently dropped row would understate rotation."""
    path = Path(archive_dir) / _PULL_LOG
    if not path.exists():
        return []
    rows = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    # RM-291A: UnicodeDecodeError is a ValueError, not an OSError.
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("cannot read %s: %s", path, exc)
        return []
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except ValueError as exc:
            logger.warning("skipping corrupt pull-log line %d: %s", n, exc)
    return rows


def pull_rotation_report(archive_dir) -> dict:
    """Per account: did the served set change between the first and last pull?

    `rotated` is None with fewer than two observations - one sample cannot show
    rotation, and answering "False" there would fabricate a negative answer to
    the question this log exists to settle.
    """
    by_account: dict = {}
    for row in load_pull_observations(archive_dir):
        by_account.setdefault(row.get("account"), []).append(row)

    report = {}
    for account, rows in by_account.items():
        rows.sort(key=lambda r: r.get("observed_at_unix") or 0)
        first = set(rows[0].get("match_ids") or [])
        last = set(rows[-1].get("match_ids") or [])
        new_ids = sorted(last - first)
        report[account] = {
            "observations": len(rows),
            "rotated": (bool(new_ids) if len(rows) > 1 else None),
            "new_ids": new_ids,
            "dropped_ids": sorted(first - last),
            "first_seen": sorted(first),
            "last_seen": sorted(last),
        }
    return report


@dataclass
class DownloadResult:
    """Outcome of one API pull. Lists hold match ids.

    `expired` is separated from `failed` on purpose: an expired URL means the
    pull ran more than an hour after the URLs were fetched (a scheduling
    defect), while `failed` means the transfer itself broke. Collapsing them
    would hide which one is happening.
    """

    downloaded: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    expired: list = field(default_factory=list)
    gone: list = field(default_factory=list)


_GZIP_MAGIC = b"\x1f\x8b"


# This ceiling has to be generous, and the live archive says how generous.
# MEASURED 2026-09-06 over the FULL archive, walked recursively: 13896 replays,
# 180.4 GiB, ALL carrying valid RIOT magic, and the largest is 28.48 MB
# (29862216 bytes). That number is the whole argument - it is well past
# lib/http/client.py's 16 MB default, so inheriting the shared cap would have
# rejected real replays. RM-371 warned about exactly this ("must NOT simply
# inherit a small default") and the measurement confirms it. 64 MB is ~2.2x the
# largest observed replay and still bounds transfer and gzip expansion.
#
# Measure this RECURSIVELY if it is ever re-derived. The first pass here used a
# non-recursive glob of the archive root, saw 15 files, and reported a 18.6 MB
# maximum - wrong by three orders of magnitude on count and by 10 MB on the
# maximum, because 13881 of the replays live under players/<ROLE>/ subdirs
# written by this same module via tools/replay_roster_pull.py.
MAX_REPLAY_BYTES = 64 * 1024 * 1024
_READ_CHUNK_BYTES = 64 * 1024


class ReplayTooLarge(Exception):
    """A replay body ran past MAX_REPLAY_BYTES (RM-371).

    Raised by the default transport. download_replays catches it per item, so
    one oversize body cannot abort a whole sweep - the failure class this module
    was already fixed for twice (LEDGER 1176, 1311).
    """


def _read_bounded(reader, max_bytes: int) -> tuple[bytes, bool]:
    """Read at most *max_bytes* + 1 bytes.

    Returns (body, over_cap). Reading one byte past the ceiling is what lets the
    caller tell "ended exactly at the ceiling" from "ran past it" without
    buffering the overflow. Same shape as lib/http/client.py:_read_bounded.
    """
    remaining = max_bytes + 1
    chunks: list[bytes] = []
    while remaining > 0:
        chunk = reader.read(min(_READ_CHUNK_BYTES, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    body = b"".join(chunks)
    return body, len(body) > max_bytes


def _maybe_gunzip(body: bytes, max_bytes: int = MAX_REPLAY_BYTES) -> bytes:
    """MEASURED 2026-07-19: Riot's pre-signed bodies arrive GZIP-framed, and
    urllib does not decompress. Returning the compressed bytes unchanged made
    the first live pull discard 5 of 5 as "not a replay". Left as-is when it is
    not gzip, so a raw body still works.

    LANE 8: the expansion is BOUNDED, and the bound matters more here than at
    the transfer. download_replays gunzips BEFORE it validates the container
    magic, so an unbounded gzip.decompress applied the full expansion ratio
    (~1000x on compressible filler) to bytes nothing had checked yet. Bounding
    the output makes a bomb cost one chunk instead of its whole expansion.
    """
    if not body or not body.startswith(_GZIP_MAGIC):
        return body
    import zlib
    out = bytearray()
    remaining = body
    try:
        # 16 + MAX_WBITS selects the gzip container. One decompressobj handles
        # exactly ONE member, so the loop preserves gzip.decompress's
        # concatenate-every-member behaviour; without it a multi-member body
        # silently returned only its first member.
        while remaining:
            dec = zlib.decompressobj(16 + zlib.MAX_WBITS)
            # Budget is always >= 1 here: the ceiling check below returns as
            # soon as out exceeds max_bytes, and zlib treats max_length=0 as
            # UNLIMITED, so a zero budget would silently remove the bound.
            out += dec.decompress(remaining, max_bytes + 1 - len(out))
            if len(out) > max_bytes:
                logger.warning(
                    "gzip body expands past the %d byte ceiling (%d compressed)"
                    " - discarded", max_bytes, len(body),
                )
                return b""
            if not dec.eof:
                # The member did not end. Either the body is TRUNCATED or the
                # ceiling stopped us mid-stream; both are unusable.
                #
                # This check is the whole reason the bounded rewrite is safe.
                # gzip.decompress raised EOFError on a truncated body, which
                # this function turned into b"" and download_replays discarded.
                # decompressobj instead returns the partial bytes with NO
                # exception - and a truncated replay still carries the RIOT
                # prefix, so it passed validation and was written under its
                # final name, then recorded in an index that is idempotent on
                # match id, so the re-pull skipped it forever. Caught by the
                # lane 8 verifier, not by the suite.
                logger.warning(
                    "gzip body is incomplete or truncated (%d compressed,"
                    " %d decompressed so far) - discarded", len(body), len(out),
                )
                return b""
            remaining = dec.unused_data
            if remaining and not remaining.startswith(_GZIP_MAGIC):
                # Trailing bytes that are not another member. gzip.decompress
                # rejects this; so do we, rather than return a partial body.
                logger.warning(
                    "gzip body carries %d trailing non-member bytes - discarded",
                    len(remaining),
                )
                return b""
    except (OSError, EOFError, ValueError, zlib.error) as exc:
        logger.warning("gzip body would not decompress (%d bytes): %s", len(body), exc)
        return b""
    return bytes(out)


def _http_get_bytes(url: str, max_bytes: int = MAX_REPLAY_BYTES) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as resp:
        body, over_cap = _read_bounded(resp, max_bytes)
    if over_cap:
        raise ReplayTooLarge(f"replay body ran past {max_bytes} bytes: {url}")
    return body


def download_replays(urls, archive_dir, index_path=None, fetcher=None,
                     now=None) -> DownloadResult:
    """Download each pre-signed replay URL straight into the archive.

    Same contract as archive_replays: idempotent (keyed on match id, so a
    repeat pull of the same rotating window costs one skip each), atomic (a
    partial 10 MB transfer must never appear under its final name), and loud
    about every non-success.

    *fetcher* is injected so the transport stays out of the logic and the pass
    is testable without S3.
    """
    archive_dir = Path(archive_dir)
    index_path = Path(index_path) if index_path else archive_dir / "index.json"
    fetcher = fetcher or _http_get_bytes

    res = DownloadResult()
    index = _load_index(index_path)
    known = index["replays"]
    dirty = False

    for url in urls or []:
        match_id = match_id_from_replay_url(url)
        if match_id is None:
            logger.warning("cannot parse a match id out of replay URL: %s", url)
            res.failed.append(url)
            continue

        dest = archive_dir / f"{match_id}{ROFL_SUFFIX}"
        # Skip on the MATCH ID present on disk under EITHER naming convention,
        # not on this function's own filename: the client writes the hyphen
        # form ("NA1-5595187452.rofl") and archive_replays preserves it, so a
        # filename-keyed check re-downloads 10 MB and leaves two copies of one
        # game (measured on the live archive).
        if match_id in known and _archived_file(archive_dir, match_id) is not None:
            res.skipped.append(match_id)
            continue

        if replay_url_expired(url, now=now):
            # One hour is the whole window; if we are past it the fetch step
            # ran too long after the URL step.
            logger.warning("replay URL for %s expired before it was used", match_id)
            res.expired.append(match_id)
            continue

        try:
            body = fetcher(url)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                # MEASURED: an entire account's window 404s. Riot still LISTS
                # the match but no longer retains the file. Permanent and
                # expected - not a failure, or the scheduled task reports
                # LastTaskResult=1 forever and a real fault hides in it.
                logger.info("replay %s is listed but no longer retained (404)",
                            match_id)
                res.gone.append(match_id)
            else:
                logger.warning("download failed for %s: HTTP %s", match_id, exc.code)
                res.failed.append(match_id)
            continue
        except ReplayTooLarge as exc:
            logger.warning("download for %s exceeded the size ceiling: %s",
                           match_id, exc)
            res.failed.append(match_id)
            continue
        except OSError as exc:
            logger.warning("download failed for %s: %s", match_id, exc)
            res.failed.append(match_id)
            continue

        # The transport is INJECTED, so the ceiling cannot live only inside
        # _http_get_bytes - every caller supplying its own fetcher would bypass
        # it. Bound the body here as well, and do it before the gunzip, so an
        # oversize body is rejected without being expanded first.
        if len(body or b"") > MAX_REPLAY_BYTES:
            logger.warning(
                "body for %s is %d bytes, past the %d byte ceiling - discarded",
                match_id, len(body or b""), MAX_REPLAY_BYTES,
            )
            res.failed.append(match_id)
            continue

        body = _maybe_gunzip(body, MAX_REPLAY_BYTES)
        if not body or not body.startswith(_ROFL_MAGIC):
            logger.warning(
                "response for %s is not a replay (%d bytes, starts %r) - discarded",
                match_id, len(body or b""), (body or b"")[:16],
            )
            res.failed.append(match_id)
            continue

        try:
            _atomic_write_bytes(dest, body)
        except OSError as exc:
            logger.warning("could not write replay %s: %s", match_id, exc)
            res.failed.append(match_id)
            continue

        known[match_id] = {
            "file": dest.name,
            "size": len(body),
            "source": "match_v5_replays",
            "archived_at": datetime.now(timezone.utc).isoformat(),
        }
        dirty = True
        res.downloaded.append(match_id)
        logger.info("downloaded replay %s (%d bytes)", match_id, len(body))

    if dirty or not index_path.exists():
        _atomic_write_json(index_path, index)
    return res


@dataclass
class ExtractResult:
    """Outcome of a bulk extraction pass. Lists hold match ids."""

    extracted: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    failed: list = field(default_factory=list)


def extract_stats(rofl_path):
    """Pull the Layer-1 stats blob out of a .rofl. None if unreadable.

    MEASURED container shape: magic b"RIOT\\x02\\x00", then a plain UNENCRYPTED
    JSON object at the TAIL carrying gameLength / lastGameChunkId /
    lastKeyFrameId / statsJson. Real files yielded 10 players at 367
    engine-named fields each.

    Two traps, both hit on real data:
      1. There are TRAILING BYTES past the closing brace, so json.loads raises
         "Extra data" - raw_decode is required.
      2. statsJson is a STRING containing JSON, not a nested object.

    No patch gate, no game client, no third-party tool: unlike playback, which
    is hard patch-locked, extraction works on any archived replay forever.
    """
    rofl_path = Path(rofl_path)
    match_id = match_id_from_name(rofl_path.name)
    try:
        raw = rofl_path.read_bytes()
    except OSError as exc:
        logger.warning("cannot read replay %s: %s", rofl_path, exc)
        return None

    idx = raw.find(_BLOB_ANCHOR)
    if idx == -1:
        logger.warning("no stats blob found in %s (not a .rofl?)", rofl_path.name)
        return None

    try:
        meta, _end = json.JSONDecoder().raw_decode(
            raw[idx:].decode("utf-8", "replace")
        )
        players = json.loads(meta["statsJson"])
    except (ValueError, KeyError, TypeError) as exc:
        logger.warning("corrupt stats blob in %s: %s", rofl_path.name, exc)
        return None

    if not isinstance(players, list):
        logger.warning("statsJson in %s was %s, expected a list",
                       rofl_path.name, type(players).__name__)
        return None

    # Layer-1 player entries are objects (10 dicts of ~367 engine fields each) and
    # downstream sidecar consumers index each one as a dict. A valid-JSON-but-
    # wrong-shape statsJson - a list of non-dicts from a truncated or corrupt body
    # - must be rejected like any other corrupt blob, not crash: field_count reads
    # len(players[0]), which on a non-sized first entry (int/None/bool) raised an
    # uncaught TypeError that propagated out of extract_stats and aborted the whole
    # extract_archive loop, so one bad .rofl dropped every later replay in the pass
    # (a string first entry was worse - it silently produced a garbage sidecar).
    if not all(isinstance(p, dict) for p in players):
        logger.warning("statsJson in %s held non-object player entries - corrupt",
                       rofl_path.name)
        return None

    return {
        "match_id": match_id,
        "file": rofl_path.name,
        "game_length_ms": meta.get("gameLength"),
        "last_chunk_id": meta.get("lastGameChunkId"),
        "last_keyframe_id": meta.get("lastKeyFrameId"),
        "player_count": len(players),
        "field_count": len(players[0]) if players else 0,
        "players": players,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }


def extract_archive(archive_dir, stats_dir=None, force=False) -> ExtractResult:
    """Extract stats for every .rofl in *archive_dir* into JSON sidecars.

    Writes <archive_dir>/stats/<match_id>.json by default. Idempotent unless
    *force*. Failures are COUNTED, not dropped - an extraction pass where every
    file was corrupt must not read as success.

    Deliberately does NOT write to rewind_history.db: that is 1.8 GB of
    production data and merging into it is a separate, schema-aware job.
    """
    archive_dir = Path(archive_dir)
    stats_dir = Path(stats_dir) if stats_dir else archive_dir / "stats"

    res = ExtractResult()
    if not archive_dir.is_dir():
        logger.debug("archive dir absent, nothing to extract: %s", archive_dir)
        return res

    for entry in sorted(archive_dir.iterdir()):
        if not entry.is_file() or entry.suffix.lower() != ROFL_SUFFIX:
            continue
        match_id = match_id_from_name(entry.name)
        if match_id is None:
            continue

        target = stats_dir / f"{match_id}.json"
        if target.exists() and not force:
            res.skipped.append(match_id)
            continue

        data = extract_stats(entry)
        if data is None:
            res.failed.append(match_id)
            continue

        try:
            _atomic_write_json(target, data)
        except OSError as exc:
            logger.warning("could not write stats sidecar for %s: %s", match_id, exc)
            res.failed.append(match_id)
            continue

        res.extracted.append(match_id)
        logger.info("extracted %s players=%d fields=%d",
                    match_id, data["player_count"], data["field_count"])
    return res


@dataclass
class ArchiveResult:
    """What one archive pass did. Lists hold match ids, not paths."""

    copied: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    failed: list = field(default_factory=list)

    @property
    def total_seen(self) -> int:
        return len(self.copied) + len(self.skipped) + len(self.failed)


def match_id_from_name(name: str):
    """"NA1-5592802194.rofl" -> "NA1_5592802194". None if it is not a replay.

    Returns None rather than raising so a stray file in the Replays directory
    is skipped, not fatal.
    """
    p = Path(name)
    if p.suffix.lower() != ROFL_SUFFIX:
        return None
    m = _NAME_RE.match(p.stem)
    if not m:
        return None
    return f"{m.group('platform')}_{m.group('game_id')}"


def default_replays_dir() -> Path:
    """The client's own Replays directory.

    Authoritative source is the live LCU (`GET /lol-replays/v1/rofls/path`),
    which measured this exact path; this is the offline fallback.
    """
    return _DEFAULT_REPLAYS


def default_archive_dir() -> Path:
    """Archive target. Override with RC_ROFL_ARCHIVE_DIR.

    Deliberately OUTSIDE the repo: replays run 8-13 MB each and `data/` is only
    selectively gitignored, so archiving into the tree risks committing binaries.
    """
    env = os.environ.get(_ENV_ARCHIVE_DIR, "").strip()
    return Path(env) if env else _DEFAULT_ARCHIVE


def load_index(index_path) -> dict:
    """Public read of the archive index (callers need the archived-id set to
    avoid re-requesting a replay they already hold)."""
    return _load_index(Path(index_path))


def _load_index(index_path: Path, key: str = "replays") -> dict:
    """Read an archive index, recovering loudly from a corrupt one.

    *key* is the top-level collection name ("replays" for .rofl files,
    "clips" for highlights) so both archives share one implementation and one
    corrupt-index policy.
    """
    if not index_path.exists():
        return {key: {}}
    try:
        raw = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        # Recover, but never silently: a swallowed corrupt index would quietly
        # re-copy everything and hide real disk trouble.
        logger.warning(
            "archive index unreadable (%s) - rebuilding from disk: %s",
            index_path, exc,
        )
        return {key: {}}
    if not isinstance(raw, dict) or not isinstance(raw.get(key), dict):
        logger.warning(
            "archive index has unexpected shape (%s) - rebuilding", index_path
        )
        return {key: {}}
    return raw


def _atomic_write_json(target: Path, payload: dict) -> None:
    """Delegates to core/polled_json.py so the WinError-5 retry (RM-310) and the
    per-writer scratch name stay single-sourced.

    Both properties were re-rolled here and both were wrong. The replace was
    bare, so a reader holding index.json open lost the write; and the scratch
    name was derived from the destination alone, so every writer of a given
    index.json opened the SAME index.json.tmp. polled_json fixed exactly that
    for itself in lane 8 cycle 24 and this module never inherited it - the
    resolver-fix-is-not-a-consumer-fix shape.
    """
    atomic_write_json(target, payload)


def _atomic_write_bytes(target: Path, payload: bytes) -> None:
    """Write a downloaded replay via a scratch sibling then replace, leaving no
    artifact behind on failure - a truncated 10 MB body under the final name
    would be indistinguishable from a good replay. Delegated for the same
    reason as _atomic_write_json."""
    atomic_write_bytes(target, payload)


def _atomic_copy(src: Path, dst: Path) -> None:
    """Copy via a scratch sibling then replace - a partially written 13 MB
    replay must never be visible under its final name.

    Streams with copy2 rather than routing through polled_json.atomic_write_bytes,
    which would pull the whole replay through memory; the scratch NAMING and the
    WinError-5 retry are still polled_json's, so all three writers share one
    implementation of both properties.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = _scratch_path(dst)
    try:
        shutil.copy2(src, tmp)
        _replace_with_retry(tmp, dst)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError as exc:
                logger.warning("could not clean scratch artifact %s: %s", tmp, exc)


def archive_replays(source_dir, archive_dir, index_path=None) -> ArchiveResult:
    """Copy every not-yet-archived .rofl from *source_dir* into *archive_dir*.

    Idempotent and non-destructive. A missing *source_dir* is not an error - the
    Replays directory legitimately does not exist until the first replay is
    saved.
    """
    source_dir = Path(source_dir)
    archive_dir = Path(archive_dir)
    index_path = Path(index_path) if index_path else archive_dir / "index.json"

    res = ArchiveResult()
    if not source_dir.is_dir():
        logger.debug("replays dir absent, nothing to archive: %s", source_dir)
        return res

    index = _load_index(index_path)
    known = index["replays"]
    dirty = False

    for entry in sorted(source_dir.iterdir()):
        if not entry.is_file():
            continue
        match_id = match_id_from_name(entry.name)
        if match_id is None:
            continue

        dest = archive_dir / entry.name
        if match_id in known and dest.exists():
            res.skipped.append(match_id)
            continue

        try:
            size = entry.stat().st_size
            _atomic_copy(entry, dest)
        except OSError as exc:
            # Loud: a replay we failed to copy is a replay lost forever once the
            # client prunes it.
            logger.warning("failed to archive %s: %s", entry.name, exc)
            res.failed.append(match_id)
            continue

        known[match_id] = {
            "file": entry.name,
            "size": size,
            "archived_at": datetime.now(timezone.utc).isoformat(),
        }
        dirty = True
        res.copied.append(match_id)
        logger.info("archived replay %s (%d bytes)", match_id, size)

    if dirty or not index_path.exists():
        _atomic_write_json(index_path, index)
    return res
