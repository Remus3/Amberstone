"""Forward-capture archiver for League replay (.rofl) files.

WHY THIS EXISTS - measured against the live client 2026-07-19:

`POST /lol-replays/v1/rofls/{gameId}/download` returns 204 for any game id, but
`GET /lol-replays/v1/metadata/{gameId}` then reports `state: "incompatible"` for
anything not on the CURRENT game patch - confirmed for a patch-16.13 match (only
ONE patch behind, client on 16.14.794.5912) and for a 14.24 match from Dec 2024.
So replays are hard patch-locked: a .rofl can only be obtained while its own
patch is live, and no route retroactively downloads history. There is also no
third-party source for personal match replays.

Consequence: `data/rewind_history.db` holds 2961 matches spanning 60 patches
(11.8 .. 16.13) and exactly TWO .rofl files exist on disk. The historical gap is
permanent. The only thing that can still be saved is the FORWARD stream, and the
client prunes its own Replays directory, so replays must be copied out promptly.

This module is that copy step. It is deliberately boring:
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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

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


def _load_index(index_path: Path) -> dict:
    """Read the archive index, recovering loudly from a corrupt one."""
    if not index_path.exists():
        return {"replays": {}}
    try:
        raw = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        # Recover, but never silently: a swallowed corrupt index would quietly
        # re-copy everything and hide real disk trouble.
        logger.warning(
            "rofl archive index unreadable (%s) - rebuilding from disk: %s",
            index_path, exc,
        )
        return {"replays": {}}
    if not isinstance(raw, dict) or not isinstance(raw.get("replays"), dict):
        logger.warning(
            "rofl archive index has unexpected shape (%s) - rebuilding", index_path
        )
        return {"replays": {}}
    return raw


def _atomic_write_json(target: Path, payload: dict) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(target)


def _atomic_copy(src: Path, dst: Path) -> None:
    """Copy via a tmp sibling then replace - a partially written 13 MB replay
    must never be visible under its final name."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    try:
        shutil.copy2(src, tmp)
        tmp.replace(dst)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError as exc:
                logger.warning("could not clean tmp artifact %s: %s", tmp, exc)


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
