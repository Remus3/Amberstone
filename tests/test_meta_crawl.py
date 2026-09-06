"""Guards for core/meta_crawl.py - the participant-graph meta crawler.

RC's own calibration work measured the problem this module exists to fix: a
single account yields far too few event-mode games to separate signal from
noise (41 joinable games, verdict "cannot be separated from noise on one
account"). Walking the participant graph turns n=1 account into a real
sample without a dev key.

Everything here runs offline - the fetcher and the writer are injected.

Two rules are pinned deliberately:
  - the ARAM queue family is DERIVED from core.queue_modes, never re-listed,
    so a queue added there cannot silently fall out of the crawl
  - the accumulator writes ONCE, at the end. The reviewed client plugin
    (non-repo per the name-scrub rule) recorded 20-60 MB of repeated JSON
    serialization fragmenting a 3.5 GB heap; Python fares no better.
"""

import itertools

import pytest

from core import meta_crawl


def game(
    game_id=1,
    queue_id=2400,
    version="16.14.1",
    participants=None,
    creation=1000,
):
    if participants is None:
        participants = [
            {"puuid": "p1", "championId": 22, "win": True},
            {"puuid": "p2", "championId": 51, "win": False},
        ]
    return {
        "json": {
            "gameId": game_id,
            "queueId": queue_id,
            "gameVersion": version,
            "gameCreation": creation,
            "participants": participants,
        }
    }


class TestQueueFamily:
    def test_aram_family_is_derived_not_hardcoded(self):
        from core.queue_modes import QUEUE_ID_TO_MODE_KEY

        expected = {q for q, m in QUEUE_ID_TO_MODE_KEY.items() if m == "aram"}
        assert meta_crawl.ARAM_QUEUE_IDS == expected

    def test_mayhem_queue_is_included(self):
        assert 2400 in meta_crawl.ARAM_QUEUE_IDS

    def test_summoners_rift_is_excluded(self):
        assert 420 not in meta_crawl.ARAM_QUEUE_IDS


class TestPatchLabel:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("16.14.1", "16.14"),
            ("16.14.512.9999", "16.14"),
            ("16.9", "16.9"),
            ("", None),
            (None, None),
            ("garbage", None),
        ],
    )
    def test_patch_label(self, raw, expected):
        assert meta_crawl.patch_label(raw) == expected


class TestAccumulator:
    def test_records_wins_and_games_per_champion(self):
        acc = meta_crawl.CrawlAccumulator()
        acc.record(game(game_id=1))
        acc.record(game(game_id=2))
        stats = acc.champion_stats()
        assert stats[22]["games"] == 2
        assert stats[22]["wins"] == 2
        assert stats[51]["games"] == 2
        assert stats[51]["wins"] == 0

    def test_duplicate_game_counted_once(self):
        acc = meta_crawl.CrawlAccumulator()
        acc.record(game(game_id=7))
        acc.record(game(game_id=7))
        assert acc.total_games == 1

    def test_record_returns_participants_for_frontier_expansion(self):
        acc = meta_crawl.CrawlAccumulator()
        puuids = acc.record(game())
        assert set(puuids) == {"p1", "p2"}

    def test_duplicate_still_returns_participants(self):
        """A repeat game is worthless for stats but its players are still
        valid frontier nodes."""
        acc = meta_crawl.CrawlAccumulator()
        acc.record(game(game_id=7))
        puuids = acc.record(game(game_id=7))
        assert set(puuids) == {"p1", "p2"}

    def test_non_aram_queue_is_not_accumulated(self):
        acc = meta_crawl.CrawlAccumulator()
        acc.record(game(queue_id=420))
        assert acc.total_games == 0

    def test_patch_filter_excludes_other_patches(self):
        acc = meta_crawl.CrawlAccumulator(target_patch="16.14")
        acc.record(game(game_id=1, version="16.14.1"))
        acc.record(game(game_id=2, version="16.13.1"))
        assert acc.total_games == 1

    def test_malformed_games_are_skipped_not_raised(self):
        acc = meta_crawl.CrawlAccumulator()
        for bad in ({}, {"json": None}, {"json": {}}, {"json": {"queueId": 2400}}):
            assert acc.record(bad) == []
        assert acc.total_games == 0

    def test_smoothed_rate_is_applied(self):
        from core.smoothed_rates import laplace_rate

        acc = meta_crawl.CrawlAccumulator()
        acc.record(game(game_id=1))
        stats = acc.champion_stats()
        assert stats[22]["win_rate"] == pytest.approx(laplace_rate(1, 1))
        assert stats[22]["win_rate"] < 1.0, "a 1-0 record must not read as 100 percent"


class _FakeFetcher:
    def __init__(self, by_puuid):
        self.by_puuid = by_puuid
        self.calls = []

    def __call__(self, puuid):
        self.calls.append(puuid)
        return self.by_puuid.get(puuid, [])


class TestCrawl:
    def test_expands_across_the_participant_graph(self):
        fetcher = _FakeFetcher({
            "seed": [game(game_id=1, participants=[
                {"puuid": "seed", "championId": 1, "win": True},
                {"puuid": "other", "championId": 2, "win": False},
            ])],
            "other": [game(game_id=2, participants=[
                {"puuid": "other", "championId": 3, "win": True},
                {"puuid": "third", "championId": 4, "win": False},
            ])],
        })
        result = meta_crawl.crawl("seed", fetcher, max_games=50, max_players=10)
        assert result.total_games == 2
        assert "other" in fetcher.calls, "frontier must expand to co-participants"

    def test_never_refetches_a_visited_player(self):
        fetcher = _FakeFetcher({
            "seed": [game(game_id=1, participants=[
                {"puuid": "seed", "championId": 1, "win": True},
                {"puuid": "seed", "championId": 2, "win": False},
            ])],
        })
        meta_crawl.crawl("seed", fetcher, max_games=50, max_players=10)
        assert fetcher.calls.count("seed") == 1

    def test_respects_max_players(self):
        fetcher = _FakeFetcher({
            f"p{n}": [game(game_id=n, participants=[
                {"puuid": f"p{n}", "championId": 1, "win": True},
                {"puuid": f"p{n + 1}", "championId": 2, "win": False},
            ])]
            for n in range(20)
        })
        meta_crawl.crawl("p0", fetcher, max_games=500, max_players=3)
        assert len(fetcher.calls) <= 3

    def test_respects_max_games(self):
        fetcher = _FakeFetcher({
            "seed": [game(game_id=n) for n in range(50)],
        })
        result = meta_crawl.crawl("seed", fetcher, max_games=10, max_players=5)
        assert result.total_games <= 10

    def test_writer_is_called_exactly_once_at_the_end(self):
        """The heap-fragmentation lesson: one write, not one per batch."""
        writes = []
        fetcher = _FakeFetcher({"seed": [game(game_id=n) for n in range(30)]})
        meta_crawl.crawl(
            "seed", fetcher, max_games=30, max_players=5, writer=writes.append
        )
        assert len(writes) == 1
        assert writes[0]["total_games"] == 30

    def test_empty_seed_yields_empty_result_without_raising(self):
        result = meta_crawl.crawl("seed", _FakeFetcher({}), max_games=10, max_players=5)
        assert result.total_games == 0
        assert result.champion_stats == {}


class TestInnerLoopIsBoundedIndependently:
    """RM-355. The per-player loop must terminate on its own, not on a counter.

    ``CrawlAccumulator.record`` has FIVE early returns that decline to
    advance ``total_games``. Three of them - off-family (:134), duplicate
    (:138) and off-patch (:145) - STILL return that game's participant
    puuids, because a co-player is a valid graph node either way, so the
    frontier grows while the counter does not. Two return ``[]`` and spin
    without growing anything: a malformed envelope (:123, pinned by
    ``test_malformed_games_are_skipped_not_raised`` above) and a well-formed
    envelope with no participants (:126). Either way the counter stands
    still, which is the only thing the old exit tested.
    So ``if accumulator.total_games >= max_games: break`` is not
    an exit at all on a stream of non-advancing games, and ``fetcher`` is
    typed ``Callable[[str], Iterable[Any]]``, which admits an unbounded
    generator paging the service gateway.

    ``max_players`` cannot rescue it: the outer ``while`` is only re-tested
    between players, and this loop never returns control to it.

    Every test below uses a TRIPWIRE rather than a bare
    ``itertools.repeat``. A genuinely infinite fixture with no ceiling would
    HANG the suite on a regression instead of failing it, and a test that can
    only hang is a test nobody can safely run in CI.
    """

    TRIPWIRE = 5000

    def _endless(self, sample):
        """``itertools.repeat(sample)`` that raises instead of hanging."""

        def _fetch(_puuid):
            for pulled, item in enumerate(itertools.repeat(sample)):
                if pulled >= self.TRIPWIRE:
                    raise AssertionError(
                        f"crawl pulled {self.TRIPWIRE} games from one player "
                        "without terminating - the inner loop is unbounded"
                    )
                yield item

        return _fetch

    def test_off_family_stream_terminates(self):
        """The filed case: a non-ARAM stream never advances total_games."""
        result = meta_crawl.crawl(
            "seed", self._endless(game(queue_id=420)), max_games=10, max_players=1
        )
        assert result.total_games == 0

    def test_off_patch_stream_terminates(self):
        """Sibling: record() returns puuids but skips an off-patch game."""
        result = meta_crawl.crawl(
            "seed",
            self._endless(game(version="16.10.1")),
            max_games=10,
            max_players=1,
            target_patch="16.14",
        )
        assert result.total_games == 0

    def test_duplicate_game_stream_terminates(self):
        """Sibling: an in-family, on-patch game counts ONCE, then never again."""
        result = meta_crawl.crawl(
            "seed", self._endless(game(game_id=7)), max_games=10, max_players=1
        )
        assert result.total_games == 1

    def test_malformed_stream_terminates(self):
        """Sibling: _detail() returns None (:123), so record() advances nothing."""
        result = meta_crawl.crawl(
            "seed", self._endless({"not": "an envelope"}), max_games=10, max_players=1
        )
        assert result.total_games == 0

    def test_empty_participants_stream_terminates(self):
        """The FIFTH shape, and the one the filed row and my own first pass
        both missed: a well-formed envelope whose participants list is empty
        returns at :126, a DIFFERENT early return from the :123 malformed one.
        Found by the verifier asking whether ":126 is a separate fifth shape
        you are still glossing" - it was.
        """
        result = meta_crawl.crawl(
            "seed",
            self._endless({"json": {"gameId": 1, "queueId": 2400, "participants": []}}),
            max_games=10,
            max_players=1,
        )
        assert result.total_games == 0

    def test_frontier_growth_is_bounded_by_the_same_guard(self):
        """The unbounded loop also grew `frontier` without limit - memory, not
        just time. Bounding the loop bounds the append."""
        fetcher = self._endless(game(queue_id=420))
        result = meta_crawl.crawl("seed", fetcher, max_games=10, max_players=1)
        assert result.visited_players == 1

    def test_per_player_cap_is_honoured_on_a_finite_fetcher(self):
        """The bound is a real cap, not only a runaway backstop."""
        fetcher = _FakeFetcher({
            "seed": [game(game_id=n) for n in range(40)],
        })
        result = meta_crawl.crawl(
            "seed",
            fetcher,
            max_games=500,
            max_players=1,
            max_games_per_player=5,
        )
        assert result.total_games == 5

    def test_non_positive_cap_still_terminates(self):
        """A nonsense cap must degrade to a bounded crawl, never to a hang."""
        result = meta_crawl.crawl(
            "seed",
            self._endless(game(queue_id=420)),
            max_games=10,
            max_players=1,
            max_games_per_player=0,
        )
        assert result.total_games == 0

    def test_default_cap_does_not_shrink_an_ordinary_crawl(self):
        """The default must not silently truncate a realistic history page."""
        assert meta_crawl.DEFAULT_MAX_GAMES_PER_PLAYER >= 100
        fetcher = _FakeFetcher({"seed": [game(game_id=n) for n in range(60)]})
        result = meta_crawl.crawl("seed", fetcher, max_games=500, max_players=1)
        assert result.total_games == 60
