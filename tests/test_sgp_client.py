"""Guards for core/sgp_client.py - the service-gateway match-history client.

Everything here is offline: region normalization, host selection, URL shape,
token-candidate ordering and response parsing are all pure or transport-
injected. No live call is made.

The load-bearing fact this file pins: SGP splits MATCH-HISTORY hosts from
COMMON hosts. A 2026-07-05 RC probe recorded `na-red.lol.sgp.pvp.net`
returning 404 NO_METHOD_MATCHING_PATH for match-history-query and filed it as
a puzzle. It is not a puzzle - that is the COMMON host. The match-history host
for NA1 is `usw2-red.pp.sgp.pvp.net`. Conflating the two is the single easiest
way to reintroduce that dead end, so it is asserted here.
"""

import json

import pytest

from core import sgp_client


class TestRegionNormalization:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("EUW1", "EUW"),
            ("euw1", "EUW"),
            ("NA", "NA1"),
            ("na1", "NA1"),
            ("EUNE", "EUN1"),
            ("TR", "TR1"),
            ("JP", "JP1"),
            ("BR", "BR1"),
            ("OCE", "OC1"),
            ("LAN", "LA1"),
            ("LAS", "LA2"),
            ("RU", "RU"),
            ("KR", "KR"),
        ],
    )
    def test_routing_codes(self, raw, expected):
        assert sgp_client.normalize_region(raw) == expected

    def test_unknown_region_is_passed_through_uppercased(self):
        assert sgp_client.normalize_region("zz9") == "ZZ9"

    def test_blank_region_falls_back_to_default(self):
        assert sgp_client.normalize_region("") == sgp_client.DEFAULT_REGION
        assert sgp_client.normalize_region(None) == sgp_client.DEFAULT_REGION


class TestHostSelection:
    def test_na_match_history_host_is_not_the_common_host(self):
        """The exact trap that produced a filed 404 dead end."""
        hosts = sgp_client.hosts_for_region("NA1")
        assert hosts.match_history == "https://usw2-red.pp.sgp.pvp.net"
        assert hosts.common == "https://na-red.lol.sgp.pvp.net"
        assert hosts.match_history != hosts.common

    @pytest.mark.parametrize(
        ("region", "expected_mh"),
        [
            ("NA1", "https://usw2-red.pp.sgp.pvp.net"),
            ("BR1", "https://usw2-red.pp.sgp.pvp.net"),
            ("EUW", "https://euc1-red.pp.sgp.pvp.net"),
            ("TR1", "https://euc1-red.pp.sgp.pvp.net"),
            ("KR", "https://apne1-red.pp.sgp.pvp.net"),
            ("JP1", "https://apne1-red.pp.sgp.pvp.net"),
            ("SG2", "https://apse1-red.pp.sgp.pvp.net"),
            ("OC1", "https://apse1-red.pp.sgp.pvp.net"),
        ],
    )
    def test_regional_match_history_hosts(self, region, expected_mh):
        assert sgp_client.hosts_for_region(region).match_history == expected_mh

    def test_unknown_region_falls_back_without_raising(self):
        hosts = sgp_client.hosts_for_region("ZZ9")
        assert hosts.match_history.startswith("https://")

    def test_riot_hosts_use_plain_443_not_the_tencent_port(self):
        """21019 is Tencent-only. A prior filing had it as the headline port."""
        for region in ("NA1", "EUW", "KR"):
            assert ":21019" not in sgp_client.hosts_for_region(region).match_history


class TestUrlShape:
    def test_match_history_url_carries_pagination(self):
        url = sgp_client.match_history_url("https://h", "PUUID-1", 40, 20)
        assert url == (
            "https://h/match-history-query/v1/products/lol/player/PUUID-1/SUMMARY"
            "?startIndex=40&count=20"
        )


class _FakeTransport:
    """Records calls; returns queued (status, body) pairs."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, url, headers):
        self.calls.append((url, headers))
        if not self._responses:
            return 404, b""
        return self._responses.pop(0)


class TestTokenAcquisition:
    def test_tries_candidates_in_order_and_reports_the_winner(self):
        """The first candidate 403s; the client must fall through and record
        which source actually authenticated."""
        lcu_calls = []

        def fake_lcu(endpoint):
            lcu_calls.append(endpoint)
            if endpoint == sgp_client.TOKEN_ENDPOINTS[0]:
                return None
            return {"accessToken": "TOKEN-B"}

        token, source = sgp_client.acquire_token(fake_lcu)
        assert token == "TOKEN-B"
        assert source == sgp_client.TOKEN_ENDPOINTS[1]
        assert lcu_calls[0] == sgp_client.TOKEN_ENDPOINTS[0]

    def test_bare_string_token_is_accepted(self):
        """The league-session-token endpoint returns a raw string, not a dict."""
        token, _ = sgp_client.acquire_token(lambda _e: "RAW-TOKEN")
        assert token == "RAW-TOKEN"

    def test_all_candidates_failing_yields_none(self):
        token, source = sgp_client.acquire_token(lambda _e: None)
        assert token is None
        assert source is None


class TestMatchHistory:
    def test_parses_games_and_sends_bearer(self):
        payload = json.dumps({"games": [{"json": {"gameId": 1}}]}).encode()
        transport = _FakeTransport([(200, payload)])
        client = sgp_client.SgpClient(
            region="NA1", token="TK", transport=transport
        )
        games = client.match_history("PU", start=0, count=20)
        assert games == [{"json": {"gameId": 1}}]
        url, headers = transport.calls[0]
        assert url.startswith("https://usw2-red.pp.sgp.pvp.net/match-history-query")
        assert headers["Authorization"] == "Bearer TK"

    def test_non_200_returns_empty_list(self):
        client = sgp_client.SgpClient(
            region="NA1", token="TK", transport=_FakeTransport([(403, b"nope")])
        )
        assert client.match_history("PU") == []

    def test_malformed_body_returns_empty_list(self):
        client = sgp_client.SgpClient(
            region="NA1", token="TK", transport=_FakeTransport([(200, b"not json")])
        )
        assert client.match_history("PU") == []

    def test_missing_games_key_returns_empty_list(self):
        client = sgp_client.SgpClient(
            region="NA1", token="TK", transport=_FakeTransport([(200, b"{}")])
        )
        assert client.match_history("PU") == []

    def test_iter_pages_stops_on_short_page(self):
        full = json.dumps({"games": [{"i": n} for n in range(3)]}).encode()
        short = json.dumps({"games": [{"i": 99}]}).encode()
        client = sgp_client.SgpClient(
            region="NA1", token="TK",
            transport=_FakeTransport([(200, full), (200, short)]),
        )
        got = list(client.iter_match_history("PU", page_size=3, max_games=100))
        assert len(got) == 4

    def test_iter_pages_respects_max_games(self):
        full = json.dumps({"games": [{"i": n} for n in range(3)]}).encode()
        client = sgp_client.SgpClient(
            region="NA1", token="TK",
            transport=_FakeTransport([(200, full)] * 10),
        )
        got = list(client.iter_match_history("PU", page_size=3, max_games=5))
        assert len(got) == 5
