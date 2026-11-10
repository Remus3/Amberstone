"""S144-T-744: hardening guards for core/lcu_mastery.py.

The module builds an LCU URL from a caller-supplied PUUID and parses the
client's mastery rows. Each class below pins one confirmed finding:

- the PUUID went into the URL raw, so "/", "?", "#" or ".." re-targeted the
  read at another LCU route (the frozen client concatenates the endpoint onto
  the base URL unquoted);
- a non-string PUUID was str()-ed into the route (123 -> "123",
  b"x" -> "b'x'");
- a negative count sliced rows[:-n] and returned all BUT the last n rows, a
  bool count read as 1, and a NaN / junk count was swallowed and logged as an
  LCU failure;
- a bool championId (True == 1) became champion 1, a zero / negative id was
  kept, a bool or negative level / points was kept and sorted on;
- a duplicate championId produced the same champion twice in a top-N list;
- the failure log dropped the exception type and carried a PUUID prefix.
"""

import logging

import pytest

from core import lcu_mastery

REAL_SHAPE_PUUID = "a1B2-c3D4_e5F6" * 5  # 70 chars, the real alphabet


class _FakeLcu:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def __call__(self, method, endpoint):
        self.calls.append((method, endpoint))
        return self.responses.get((method, endpoint))


class TestPuuidIsNeverInjectedIntoTheRoute:
    @pytest.mark.parametrize(
        "puuid",
        [
            "../../lol-summoner/v1/current-summoner#",
            "PU/../../lol-login/v1/session",
            "PU?x=1",
            "PU#frag",
            "PU%2F..",
            "PU UID",
            "PU\nUID",
            "P\u00e9U",
            "PU\x00",
            "x" * 200,
        ],
    )
    def test_routes_refuse_a_puuid_outside_the_puuid_alphabet(self, puuid):
        with pytest.raises(ValueError):
            lcu_mastery.mastery_route(puuid)
        with pytest.raises(ValueError):
            lcu_mastery.top_route(puuid, 1)

    @pytest.mark.parametrize(
        "puuid",
        [
            "../../lol-summoner/v1/current-summoner#",
            "PU?x=1",
            "PU\nUID",
            "x" * 200,
        ],
    )
    def test_top_masteries_never_calls_the_client_with_a_bad_puuid(self, puuid):
        lcu = _FakeLcu()
        assert lcu_mastery.top_masteries(lcu, puuid, count=1) == []
        assert lcu.calls == []

    @pytest.mark.parametrize("puuid", [123, b"PU", ["PU"], 1.5, True])
    def test_a_non_string_puuid_is_refused_not_stringified(self, puuid):
        lcu = _FakeLcu()
        assert lcu_mastery.top_masteries(lcu, puuid, count=1) == []
        assert lcu.calls == []
        with pytest.raises(ValueError):
            lcu_mastery.mastery_route(puuid)

    def test_a_real_shape_puuid_is_accepted(self):
        assert lcu_mastery.mastery_route(REAL_SHAPE_PUUID) == (
            f"/lol-champion-mastery/v1/{REAL_SHAPE_PUUID}/champion-mastery"
        )

    @pytest.mark.parametrize("puuid", ["  PU  ", "PU\n", "\tPU"])
    def test_a_padded_puuid_is_stripped_before_the_call(self, puuid):
        lcu = _FakeLcu()
        lcu_mastery.top_masteries(lcu, puuid, count=1)
        assert lcu.calls[0] == (
            "GET", "/lol-champion-mastery/v1/PU/champion-mastery/top?count=1"
        )


class TestCount:
    def _full_list(self):
        return {
            ("GET", lcu_mastery.mastery_route("PU")): [
                {"championId": i, "championLevel": 5, "championPoints": 100 - i}
                for i in range(1, 6)
            ],
        }

    @pytest.mark.parametrize("count", [0, -1, -3, True, False, None, 1.5,
                                       float("nan"), "x", "-2", "", "\u0663"])
    def test_a_junk_or_non_positive_count_answers_empty_without_a_call(self, count):
        lcu = _FakeLcu(self._full_list())
        assert lcu_mastery.top_masteries(lcu, "PU", count=count) == []
        assert lcu.calls == []

    def test_a_negative_count_never_returns_all_but_the_last_rows(self):
        lcu = _FakeLcu(self._full_list())
        got = lcu_mastery.top_masteries(lcu, "PU", count=-2)
        assert len(got) != 3

    @pytest.mark.parametrize("count", [0, -1, True, 1.5, "x", "\u0663"])
    def test_top_route_refuses_a_junk_count(self, count):
        with pytest.raises(ValueError):
            lcu_mastery.top_route("PU", count)

    def test_an_ascii_digit_string_count_still_works(self):
        assert lcu_mastery.top_route("PU", " 5 ").endswith("count=5")

    def test_a_huge_count_is_clamped(self):
        route = lcu_mastery.top_route("PU", 10**30)
        assert route.endswith(f"count={lcu_mastery.MAX_COUNT}")
        lcu = _FakeLcu(self._full_list())
        got = lcu_mastery.top_masteries(lcu, "PU", count=10**30)
        assert [r["champion_id"] for r in got] == [1, 2, 3, 4, 5]


    def test_an_int_subclass_count_reaches_the_route_as_a_plain_int(self):
        class Sneaky(int):
            def __format__(self, spec):
                return "1&x=/../../lol-login"

        assert lcu_mastery.top_route("PU", Sneaky(3)).endswith("count=3")
        lcu = _FakeLcu()
        lcu_mastery.top_masteries(lcu, "PU", count=Sneaky(3))
        assert lcu.calls[0] == (
            "GET", "/lol-champion-mastery/v1/PU/champion-mastery/top?count=3"
        )

    def test_a_digit_string_longer_than_six_is_refused(self):
        with pytest.raises(ValueError):
            lcu_mastery.top_route("PU", "9999999")


class TestNormalizeValues:
    @pytest.mark.parametrize("cid", [True, False, 0, -7, 1.0, None, "22"])
    def test_a_bad_champion_id_is_dropped(self, cid):
        assert lcu_mastery.normalize(
            [{"championId": cid, "championLevel": 5, "championPoints": 9}]
        ) == []

    @pytest.mark.parametrize("value", [True, False, -1, -500, 2.5,
                                       float("nan"), "7", None])
    def test_a_bad_level_or_points_reads_as_zero(self, value):
        got = lcu_mastery.normalize(
            [{"championId": 7, "championLevel": value, "championPoints": value}]
        )
        assert got == [{"champion_id": 7, "level": 0, "points": 0}]
        assert type(got[0]["level"]) is int
        assert type(got[0]["points"]) is int

    def test_a_negative_points_row_never_outranks_a_real_one(self):
        got = lcu_mastery.normalize([
            {"championId": 1, "championLevel": 1, "championPoints": -5},
            {"championId": 2, "championLevel": 1, "championPoints": 0},
        ])
        assert all(r["points"] >= 0 for r in got)

    def test_a_duplicate_champion_keeps_its_highest_points_row_once(self):
        got = lcu_mastery.normalize([
            {"championId": 22, "championLevel": 3, "championPoints": 10},
            {"championId": 51, "championLevel": 5, "championPoints": 50},
            {"championId": 22, "championLevel": 7, "championPoints": 900},
        ])
        assert got == [
            {"champion_id": 22, "level": 7, "points": 900},
            {"champion_id": 51, "level": 5, "points": 50},
        ]

    def test_a_top_n_never_lists_one_champion_twice(self):
        lcu = _FakeLcu({
            ("GET", lcu_mastery.top_route("PU", 2)): [
                {"championId": 22, "championLevel": 7, "championPoints": 900},
                {"championId": 22, "championLevel": 7, "championPoints": 900},
                {"championId": 51, "championLevel": 5, "championPoints": 50},
            ],
        })
        got = lcu_mastery.top_masteries(lcu, "PU", count=2)
        assert [r["champion_id"] for r in got] == [22, 51]

    def test_valid_rows_are_unchanged(self):
        payload = [
            {"championId": 1, "championLevel": 4, "championPoints": 10, "puuid": "PU"},
            {"championId": 2, "championLevel": 7, "championPoints": 900},
            {"championId": 3, "championLevel": 5, "championPoints": 250},
        ]
        assert lcu_mastery.normalize(payload) == [
            {"champion_id": 2, "level": 7, "points": 900},
            {"champion_id": 3, "level": 5, "points": 250},
            {"champion_id": 1, "level": 4, "points": 10},
        ]


class TestFailureLog:
    def test_the_failure_log_names_the_type_and_no_puuid(self, caplog):
        secret = "SECRETPUUIDabcdef"  # rc-credential-scan: allow-fixture

        def boom(_method, _endpoint):
            raise ConnectionResetError("peer " + secret)

        with caplog.at_level(logging.INFO, logger=lcu_mastery.__name__):
            assert lcu_mastery.top_masteries(boom, secret, count=1) == []
        text = " ".join(r.getMessage() for r in caplog.records)
        assert "ConnectionResetError" in text
        assert secret[:6] not in text

    @pytest.mark.parametrize(
        ("puuid", "count"),
        [("PU?x=1", 1), ("PU", -2), ("PU", True), (123, 1)],
    )
    def test_a_refused_input_is_not_logged_as_an_lcu_failure(self, caplog, puuid, count):
        with caplog.at_level(logging.DEBUG, logger=lcu_mastery.__name__):
            assert lcu_mastery.top_masteries(_FakeLcu(), puuid, count=count) == []
        assert caplog.records == []


class TestDuplicateOrder:
    def test_the_highest_points_row_wins_whatever_its_position(self):
        got = lcu_mastery.normalize(
            [
                {"championId": 22, "championLevel": 7, "championPoints": 900},
                {"championId": 22, "championLevel": 3, "championPoints": 10},
            ]
        )
        assert got == [{"champion_id": 22, "level": 7, "points": 900}]
