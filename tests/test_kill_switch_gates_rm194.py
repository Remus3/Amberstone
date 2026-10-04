"""RM-194: the documented kill switches RC_META_CRAWL and RC_SGP must GATE.

Before the fix each `*_enabled()` helper had exactly one reference, its own
def, so setting the env var to 0 changed nothing. These tests use RECORDING
spies (never raising ones: the code under test is fail-soft and an
AssertionError is an Exception it would swallow).
"""

from core import meta_crawl, sgp_client


def _game(puuids):
    return {
        "json": {
            "queueId": 450,
            "gameVersion": "16.14.1",
            "participants": [{"puuid": p, "championId": 1, "win": True} for p in puuids],
        }
    }


class TestMetaCrawlGate:
    def test_disabled_crawl_makes_zero_fetcher_and_writer_calls(self, monkeypatch):
        monkeypatch.setenv("RC_META_CRAWL", "0")
        fetched, written = [], []

        def fetcher(puuid):
            fetched.append(puuid)
            return [_game(["a", "b"])]

        result = meta_crawl.crawl("seed", fetcher, writer=written.append)
        assert fetched == []
        assert written == []
        assert result.total_games == 0
        assert result.visited_players == 0

    def test_enabled_crawl_still_fetches(self, monkeypatch):
        # Positive control: the same spy records a call when the gate is open.
        monkeypatch.setenv("RC_META_CRAWL", "1")
        fetched = []

        def fetcher(puuid):
            fetched.append(puuid)
            return []

        meta_crawl.crawl("seed", fetcher, max_players=1)
        assert fetched == ["seed"]


class TestSgpGate:
    def _client(self, calls):
        def transport(url, headers):
            calls.append(url)
            return 200, b'{"games": [{"id": 1}]}'

        return sgp_client.SgpClient("NA1", "tok", transport=transport)

    def test_disabled_sgp_makes_zero_transport_calls(self, monkeypatch):
        monkeypatch.setenv("RC_SGP", "0")
        calls = []
        client = self._client(calls)
        assert client.match_history("p" * 20) == []
        assert list(client.iter_match_history("p" * 20)) == []
        assert calls == []

    def test_enabled_sgp_still_calls_transport(self, monkeypatch):
        monkeypatch.setenv("RC_SGP", "1")
        calls = []
        client = self._client(calls)
        assert client.match_history("p" * 20) == [{"id": 1}]
        assert len(calls) == 1
