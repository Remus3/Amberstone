"""Guards for core/lcu_mastery.py - key-free champion mastery for ANY player.

RC already reads the LOCAL player's mastery from the LCU. For every other
party member it falls back to Riot's Champion-Mastery-V4 web API, which costs
a dev key, a rate-limit budget, and a PUUID resolution step that is a known
400 source when the stored PUUID has rotated.

The client exposes the same data per-PUUID with none of that. This module is
that path.

One trap is pinned here deliberately. A 2024 plugin (reviewed, MIT, cleared)
used ``/lol-collections/v1/inventories/{accountId}/champion-mastery`` with a
legacy ``accountId``. That endpoint is ABSENT from the current LCU surface -
lifting it verbatim would have shipped a dead call. The live route is keyed by
PUUID, and a test asserts the route we build is the PUUID one.
"""

import pytest

from core import lcu_mastery


def entry(champion_id=22, level=7, points=123456, **extra):
    row = {
        "championId": champion_id,
        "championLevel": level,
        "championPoints": points,
        "puuid": "PU",
    }
    row.update(extra)
    return row


class TestRouteShape:
    def test_uses_the_puuid_route_not_the_dead_accountid_one(self):
        route = lcu_mastery.mastery_route("PUUID-1")
        assert route == "/lol-champion-mastery/v1/PUUID-1/champion-mastery"
        assert "lol-collections" not in route
        assert "accountId" not in route

    def test_top_route_carries_the_count_query(self):
        assert lcu_mastery.top_route("PU", 3) == (
            "/lol-champion-mastery/v1/PU/champion-mastery/top?count=3"
        )

    def test_count_is_coerced_to_int(self):
        assert lcu_mastery.top_route("PU", "5").endswith("count=5")


class TestNormalize:
    def test_maps_client_fields_to_rc_shape(self):
        got = lcu_mastery.normalize([entry(champion_id=51, level=5, points=42)])
        assert got == [{"champion_id": 51, "level": 5, "points": 42}]

    def test_sorts_by_points_descending(self):
        got = lcu_mastery.normalize([
            entry(champion_id=1, points=10),
            entry(champion_id=2, points=900),
            entry(champion_id=3, points=100),
        ])
        assert [row["champion_id"] for row in got] == [2, 3, 1]

    @pytest.mark.parametrize(
        "payload",
        [None, {}, "string", 123, [None], ["x"], [{}], [{"championId": "nope"}]],
    )
    def test_malformed_payloads_never_raise(self, payload):
        assert lcu_mastery.normalize(payload) == []

    def test_missing_numeric_fields_default_to_zero(self):
        got = lcu_mastery.normalize([{"championId": 7}])
        assert got == [{"champion_id": 7, "level": 0, "points": 0}]


class _FakeLcu:
    """Stands in for the frozen client's request surface."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, method, endpoint):
        self.calls.append((method, endpoint))
        return self.responses.get((method, endpoint))


class TestTopMasteries:
    def test_prefers_the_top_route(self):
        lcu = _FakeLcu({
            ("GET", lcu_mastery.top_route("PU", 1)): [entry(champion_id=99)],
        })
        got = lcu_mastery.top_masteries(lcu, "PU", count=1)
        assert got == [{"champion_id": 99, "level": 7, "points": 123456}]
        assert lcu.calls[0] == ("GET", lcu_mastery.top_route("PU", 1))

    def test_the_top_route_is_issued_as_a_read(self):
        """RM-350 acceptance: the top route is a read, so it is a GET.

        This pins the LCU CONTRACT, not RC's implementation. The assertion it
        replaced read ``lcu.calls[0][0] == "POST"``, which pinned the defect:
        a POST to a read route answers 405/404, ``normalize`` maps the non-list
        body to ``[]``, and the GET fallback below silently supplies the answer,
        so the fast path could never succeed against a real client while every
        test stayed green.

        REACHABILITY, measured 2026-09-06 so a later reader does not overstate
        it: ``core/lcu_mastery.py`` is imported by this test file and NOTHING
        else, so the defect was LATENT, not live. The filed row described the
        cost as landing on "every mastery lookup on the live champ-select path";
        that becomes true when the module is wired, and was not true yet. The
        live local-player mastery read is ``lcu/snapshot_shape.py``, which was
        already a GET and is not part of this fix.
        """
        lcu = _FakeLcu({})
        lcu_mastery.top_masteries(lcu, "PU", count=1)
        assert lcu.calls[0] == ("GET", lcu_mastery.top_route("PU", 1))

    def test_no_mastery_read_uses_a_mutating_verb(self):
        """Both mastery routes are reads; neither may be issued as POST/PUT/etc.

        Broader than the acceptance on purpose - it covers the fallback call as
        well as the top call, so a later edit cannot reintroduce the defect on
        the route this row did not name.
        """
        lcu = _FakeLcu({})
        lcu_mastery.top_masteries(lcu, "PU", count=3)
        assert [method for method, _ in lcu.calls] == ["GET", "GET"]

    def test_falls_back_to_the_full_list_and_slices(self):
        """When the top route is unavailable, the full list still answers."""
        lcu = _FakeLcu({
            ("GET", lcu_mastery.top_route("PU", 2)): None,
            ("GET", lcu_mastery.mastery_route("PU")): [
                entry(champion_id=1, points=10),
                entry(champion_id=2, points=500),
                entry(champion_id=3, points=250),
            ],
        })
        got = lcu_mastery.top_masteries(lcu, "PU", count=2)
        assert [r["champion_id"] for r in got] == [2, 3]

    def test_both_routes_failing_yields_empty_list(self):
        assert lcu_mastery.top_masteries(_FakeLcu({}), "PU", count=1) == []

    def test_blank_puuid_short_circuits_without_calling(self):
        lcu = _FakeLcu({})
        assert lcu_mastery.top_masteries(lcu, "", count=1) == []
        assert lcu.calls == []

    def test_transport_exception_is_contained(self):
        def boom(_method, _endpoint):
            raise RuntimeError("lcu down")

        assert lcu_mastery.top_masteries(boom, "PU", count=1) == []


class TestKillSwitch:
    def test_enabled_by_default(self, monkeypatch):
        monkeypatch.delenv("RC_LCU_MASTERY", raising=False)
        assert lcu_mastery.lcu_mastery_enabled() is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "off"])
    def test_disabled_values(self, monkeypatch, value):
        monkeypatch.setenv("RC_LCU_MASTERY", value)
        assert lcu_mastery.lcu_mastery_enabled() is False
