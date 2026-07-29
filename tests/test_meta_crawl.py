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
