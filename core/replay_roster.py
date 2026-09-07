"""Roster-driven .rofl corpus for tracked players.

The operator's OWN replays are handled by `tools/rofl_archiver.py`, which pulls
a flat archive out of a 5-wide rolling window. This module adds the second
lane: a role-partitioned corpus of RANKED matches from named players the
operator wants to study.

Layout (deliberately role-first, because analysis is read role by role):

    <corpus_root>/players/<ROLE>/<Name-Tag>/<match_id>.rofl
    <corpus_root>/players/<ROLE>/<Name-Tag>/stats/<match_id>.json
    <corpus_root>/players/<ROLE>/<Name-Tag>/index.json
    <corpus_root>/players/roster_pull_log.jsonl

TWO MEASURED CONSTRAINTS SHAPE THIS AND CANNOT BE ENGINEERED AROUND
(2026-07-26, and see memory reference-riot-replays-endpoint):

1. `/replays` takes a PUUID, never a match id. There is NO fetch-by-match-id
   route, so a specific game is obtainable only while it sits in that account's
   5-wide window. Coverage therefore comes from CADENCE, not from a backfill.
   Measured on one tracked third-party account: 5 listed, all 5 alive (HTTP 206), 3 of them
   queue 420. An arbitrary third-party account works - this is not limited to
   the operator's own accounts.
2. The window rotates as games are played, so a scheduled re-pull converts it
   into a permanent archive. It also means a game is LOST if nobody pulls
   inside its residency, which is why the ranked filter must never cost an
   extra round of latency.

The pull and the extract themselves are `core.rofl_archive.download_replays` /
`extract_archive`, unchanged and already live-proven; nothing here re-implements
a transport.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from core.rofl_archive import _archived_file, default_archive_dir

ROLES = ("TOP", "JUNGLE", "MID", "BOT", "SUPPORT")

# Solo and flex only. Every other queue is a different game for analysis
# purposes, and an unrecognised queue must fail CLOSED - see plan_pull.
RANKED_QUEUES = (420, 440)

_DATA_DIR = Path(__file__).parent.parent / "data"
# The live roster lists OTHER PEOPLE'S accounts, so it is gitignored and a
# fresh clone does not have one. Fall back to the tracked example shape rather
# than raising: the loader stays exercisable everywhere, and an operator who
# wants a real corpus copies the example across.
DEFAULT_ROSTER = _DATA_DIR / "replay_roster.json"
EXAMPLE_ROSTER = _DATA_DIR / "replay_roster.example.json"


def default_roster_path() -> Path:
    """The roster the loader reads when no explicit path is given."""
    return DEFAULT_ROSTER if DEFAULT_ROSTER.exists() else EXAMPLE_ROSTER

_MATCH_ID_RE = re.compile(r"(NA1|EUW1|EUN1|KR|BR1|LA1|LA2|OC1|TR1|RU|JP1|PH2"
                          r"|SG2|TH2|TW2|VN2)[-_](\d+)", re.IGNORECASE)
_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._]")


@dataclass(frozen=True)
class RosterEntry:
    """One tracked player. The Riot ID is the durable identity, never a PUUID.

    A stored PUUID is scoped to whichever API key encrypted it, so the roster
    holds Riot IDs and resolves fresh on every run (memory
    reference-riot-puuid-rotation).
    """

    role: str
    name: str
    tag: str
    note: str = ""

    @property
    def riot_id(self) -> str:
        return f"{self.name}#{self.tag}"

    @property
    def slug(self) -> str:
        return player_slug(self.name, self.tag)


@dataclass
class PullPlan:
    """What a single account's window resolved to, before any bytes move."""

    keep: list = field(default_factory=list)       # URLs worth downloading
    rejected: dict = field(default_factory=dict)   # match_id -> queue id or None
    already: list = field(default_factory=list)    # match_id already on disk
    unparsed: list = field(default_factory=list)   # URLs with no match id


def player_slug(name: str, tag: str) -> str:
    """A Windows-safe directory name for one Riot ID.

    Riot IDs allow spaces and a broad unicode range; a path separator reaching
    a directory name would write outside the corpus, so everything outside
    [A-Za-z0-9._] collapses to an underscore. The '-' between name and tag is
    the only structural character.

    COLLISION GUARD: collapsing unicode to underscores is LOSSY, and two
    different CJK or Hangul Riot IDs of the same length produce the SAME slug -
    which would silently merge two players' replays into one directory and
    poison every per-player statistic drawn from it. So a NON-ASCII id gets a
    short digest of its true Riot ID appended.

    The digest is deliberately scoped to non-ASCII ids only. An ASCII id whose
    spaces become underscores ("never type" -> "never_type") keeps its plain
    slug, because widening the guard to every sanitised character would RENAME
    existing corpus directories and orphan the replays already inside them.
    The residual risk is an ASCII pair like "a b" vs "a_b" colliding, which is
    accepted: both are legible, unlike two identical rows of underscores.
    """
    safe_name = _UNSAFE_RE.sub("_", name)
    safe_tag = _UNSAFE_RE.sub("_", tag)
    slug = f"{safe_name}-{safe_tag}"
    if not f"{name}{tag}".isascii():
        digest = hashlib.sha256(f"{name}#{tag}".encode()).hexdigest()[:8]
        slug = f"{slug}-{digest}"
    return slug


def default_corpus_root() -> Path:
    """The corpus shares the archive root so one backup covers both lanes."""
    return default_archive_dir()


def players_root(corpus_root=None) -> Path:
    root = Path(corpus_root) if corpus_root else default_corpus_root()
    return root / "players"


def player_dir(corpus_root, role: str, name: str, tag: str) -> Path:
    role_u = str(role).upper()
    if role_u not in ROLES:
        raise ValueError(f"unknown role {role!r}; expected one of {ROLES}")
    return players_root(corpus_root) / role_u / player_slug(name, tag)


def stats_dir(player_directory) -> Path:
    return Path(player_directory) / "stats"


def match_id_of(url_or_name: str):
    """Canonical `NA1_123` match id out of a URL or filename, either spelling.

    The client writes the hyphen form and the API writes the underscore form
    for the SAME game; normalising here is what keeps a repeat pull from
    fetching 10 MB twice (measured on the live archive).
    """
    m = _MATCH_ID_RE.search(url_or_name or "")
    if not m:
        return None
    return f"{m.group(1).upper()}_{m.group(2)}"


def load_roster(path=None) -> list:
    """Parse the roster file into validated entries.

    Fails loudly on an unknown role or an untagged Riot ID rather than
    silently skipping: a typo that drops a tracked player would show up only
    as a corpus that quietly never grows.
    """
    src = Path(path) if path else default_roster_path()
    blob = json.loads(src.read_text(encoding="utf-8"))
    out = []
    for row in blob.get("players") or []:
        role = str(row.get("role", "")).upper()
        if role not in ROLES:
            raise ValueError(
                f"unknown role {row.get('role')!r} in {src}; expected {ROLES}")
        riot_id = str(row.get("riot_id", ""))
        if "#" not in riot_id:
            raise ValueError(
                f"riot_id {riot_id!r} in {src} needs a NAME#TAG form")
        name, _, tag = riot_id.partition("#")
        if not name or not tag:
            raise ValueError(f"riot_id {riot_id!r} in {src} needs a NAME#TAG form")
        out.append(RosterEntry(role=role, name=name, tag=tag,
                               note=str(row.get("note", ""))))
    return out


def plan_pull(urls, queue_lookup, queues=RANKED_QUEUES, archive_dir=None) -> PullPlan:
    """Decide which of an account's listed replays are worth 10 MB each.

    *queue_lookup* maps a match id to its queue id (Match-V5 `info.queueId`),
    returning None when it cannot be resolved. An unresolved queue is REJECTED,
    not pulled: assuming ranked would spend a full download per guess, and the
    match stays in the window for another pass anyway.
    """
    plan = PullPlan()
    wanted = set(queues or ())
    for url in urls or []:
        match_id = match_id_of(url)
        if match_id is None:
            plan.unparsed.append(url)
            continue
        if archive_dir is not None and _archived_file(Path(archive_dir), match_id):
            plan.already.append(match_id)
            continue
        queue = queue_lookup(match_id)
        if queue in wanted:
            plan.keep.append(url)
        else:
            plan.rejected[match_id] = queue
    return plan
