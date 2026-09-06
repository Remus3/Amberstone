# arch: participant-graph crawler for event-mode champion stats | section=core | frozen=no
"""Participant-graph meta crawler for event-mode statistics.

RC's calibration work measured the ceiling of single-account data directly:
41 joinable games, with the honest verdict that the signal "cannot be
separated from noise on one account". Public Match-V5 will not close that gap
for event modes - it refuses ARAM Mayhem outright. The service gateway does
serve those games for ARBITRARY players, so a breadth-first walk over the
participant graph turns one account into a real sample with no dev key and no
rate ceiling.

Shape: seed with the operator's own PUUID, read that player's recent games,
take every co-participant as a new frontier node, repeat under explicit
bounds. Games are keyed and deduped, so the heavy overlap between co-players
in the same games costs nothing but a set lookup.

Three implementation rules are deliberate and pinned by tests:

  - The ARAM queue family is DERIVED from ``core.queue_modes``, never
    re-listed here. A queue added there must not silently fall out.
  - EVERY loop carries a bound that holds even when nothing counts. The
    frontier walk is bounded by ``max_players`` and ``max_games``, but one
    player's stream is bounded by ``max_games_per_player`` alone, because
    ``record`` has five early returns that advance neither of the other two.
    Three of them (off-family, duplicate, off-patch) keep yielding frontier
    nodes, so an unbounded stream of those grows memory as well as spinning;
    the two malformed shapes yield none and only spin.
  - Results accumulate IN MEMORY and are written ONCE at the end. A reviewed
    client plugin (kept non-repo per the name-scrub rule) recorded repeated
    20-60 MB JSON serialization fragmenting a 3.5 GB heap during a crawl.
    Python has the same failure mode.

Rates run through ``core.smoothed_rates.laplace_rate`` so a 1-0 champion
never outranks a 14-8 one - the whole reason per-champion event-mode data is
worth collecting at all.

Kill switch: ``RC_META_CRAWL=0``.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from core.queue_modes import QUEUE_ID_TO_MODE_KEY
from core.smoothed_rates import laplace_rate

_log = logging.getLogger(__name__)

# Derived, never re-listed. Adding a queue in queue_modes.py extends the crawl.
ARAM_QUEUE_IDS: set[int] = {
    queue_id for queue_id, mode in QUEUE_ID_TO_MODE_KEY.items() if mode == "aram"
}

_PATCH_RE = re.compile(r"^(\d+)\.(\d+)")

DEFAULT_MAX_GAMES = 2000
DEFAULT_MAX_PLAYERS = 200
# Bounds ONE player's stream. Deliberately independent of DEFAULT_MAX_GAMES:
# that counter only advances for an in-family, on-patch, unseen game, so it
# cannot terminate a loop reading anything else. See crawl().
DEFAULT_MAX_GAMES_PER_PLAYER = 500


def crawl_enabled() -> bool:
    """False only when the operator sets RC_META_CRAWL=0."""
    return os.environ.get("RC_META_CRAWL", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def patch_label(game_version: str | None) -> str | None:
    """``16.14.512.9999`` -> ``16.14``. None when unparseable."""
    if not game_version:
        return None
    match = _PATCH_RE.match(str(game_version).strip())
    if not match:
        return None
    return f"{match.group(1)}.{match.group(2)}"


def _detail(raw_game: Any) -> dict | None:
    """Unwrap the service-gateway envelope, tolerating any malformed shape."""
    if not isinstance(raw_game, dict):
        return None
    detail = raw_game.get("json")
    if not isinstance(detail, dict):
        return None
    return detail


def _game_key(detail: dict) -> Any:
    """Stable identity. gameId when present, else creation timestamp."""
    for field_name in ("gameId", "matchId"):
        value = detail.get(field_name)
        if value not in (None, ""):
            return (field_name, value)
    return ("gameCreation", detail.get("gameCreation"))


@dataclass
class CrawlAccumulator:
    """In-memory tally. Holds no file handle and writes nothing itself."""

    target_patch: str | None = None
    total_games: int = 0
    seen_patches: set[str] = field(default_factory=set)
    _seen_keys: set = field(default_factory=set, repr=False)
    _champions: dict[int, dict[str, int]] = field(default_factory=dict, repr=False)

    def record(self, raw_game: Any) -> list[str]:
        """Fold one game in. Returns its participant PUUIDs for frontier
        expansion - including for a duplicate game, whose players are still
        valid graph nodes even though its stats are already counted.
        """
        detail = _detail(raw_game)
        if detail is None:
            return []
        participants = detail.get("participants")
        if not isinstance(participants, list) or not participants:
            return []
        puuids = [
            p.get("puuid")
            for p in participants
            if isinstance(p, dict) and p.get("puuid")
        ]

        if detail.get("queueId") not in ARAM_QUEUE_IDS:
            return puuids

        key = _game_key(detail)
        if key in self._seen_keys:
            return puuids
        self._seen_keys.add(key)

        label = patch_label(detail.get("gameVersion"))
        if label:
            self.seen_patches.add(label)
        if self.target_patch and label != self.target_patch:
            return puuids

        self.total_games += 1
        for participant in participants:
            if not isinstance(participant, dict):
                continue
            champion_id = participant.get("championId")
            if not isinstance(champion_id, int):
                continue
            bucket = self._champions.setdefault(champion_id, {"games": 0, "wins": 0})
            bucket["games"] += 1
            if participant.get("win"):
                bucket["wins"] += 1
        return puuids

    def champion_stats(self) -> dict[int, dict[str, float]]:
        """Per-champion games / wins / smoothed win rate."""
        return {
            champion_id: {
                "games": bucket["games"],
                "wins": bucket["wins"],
                "win_rate": laplace_rate(bucket["wins"], bucket["games"]),
            }
            for champion_id, bucket in self._champions.items()
        }


@dataclass
class CrawlResult:
    total_games: int
    visited_players: int
    champion_stats: dict[int, dict[str, float]]
    seen_patches: tuple[str, ...]


def crawl(
    seed_puuid: str,
    fetcher: Callable[[str], Iterable[Any]],
    max_games: int = DEFAULT_MAX_GAMES,
    max_players: int = DEFAULT_MAX_PLAYERS,
    target_patch: str | None = None,
    writer: Callable[[dict], None] | None = None,
    max_games_per_player: int = DEFAULT_MAX_GAMES_PER_PLAYER,
) -> CrawlResult:
    """Breadth-first walk from ``seed_puuid``.

    ``fetcher(puuid)`` returns that player's raw games. ``writer``, when
    given, is called EXACTLY ONCE with the final payload - never per batch.

    THREE bounds, and the third is not redundant. ``max_players`` is tested
    only between players and ``max_games`` counts only games that were
    actually folded in, so neither can end a single player's stream:
    ``record`` has five early returns that decline to advance
    ``total_games`` - off-family, duplicate and off-patch still hand back the
    game's puuids, while the two malformed shapes hand back ``[]``, and
    neither counts - and ``fetcher`` is typed ``Iterable[Any]``, which admits an unbounded
    generator paging the service gateway. ``max_games_per_player`` is the
    bound that does not depend on anything having counted.

    The bound is tested AFTER each game is folded in, so a cap below 1
    examines exactly one game per player: a nonsense cap degrades to the
    shortest possible crawl, never to a hang. A ``max(1, ...)`` clamp was
    written here first and removed as provably inert - mutating it away left
    every test green (RM-355).
    """
    accumulator = CrawlAccumulator(target_patch=target_patch)
    visited: set[str] = set()
    frontier: list[str] = [seed_puuid]

    while frontier and len(visited) < max_players and accumulator.total_games < max_games:
        puuid = frontier.pop(0)
        if not puuid or puuid in visited:
            continue
        visited.add(puuid)
        try:
            games = fetcher(puuid) or []
        except Exception:  # noqa: BLE001 - one bad player must not end the crawl
            _log.exception("meta crawl fetch failed for %s", str(puuid)[:8])
            continue
        for examined, raw_game in enumerate(games, start=1):
            for participant_puuid in accumulator.record(raw_game):
                if participant_puuid not in visited:
                    frontier.append(participant_puuid)
            if accumulator.total_games >= max_games:
                break
            if examined >= max_games_per_player:
                break

    result = CrawlResult(
        total_games=accumulator.total_games,
        visited_players=len(visited),
        champion_stats=accumulator.champion_stats(),
        seen_patches=tuple(sorted(accumulator.seen_patches)),
    )
    if writer is not None:
        # Single write, at the end. See the module docstring.
        writer({
            "total_games": result.total_games,
            "visited_players": result.visited_players,
            "champion_stats": result.champion_stats,
            "seen_patches": list(result.seen_patches),
        })
    return result
