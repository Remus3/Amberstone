"""Guards for core/lcu_events.py - the LCU WAMP event subscription registry.

The registry half is pure (no socket), so every dispatch/lifecycle rule is
unit-testable without a live client. Transport lives behind it and is not
exercised here.

Design rules under test, each one a real failure mode observed in a
client-plugin teardown (non-repo) that RC's polling path does not have:
  - unsubscribe is a closure, so a caller cannot leak a half-removed handle
  - the last unsubscribe for a URI releases the upstream subscription
  - one raising callback must not starve its siblings on the same URI
  - callbacks registered before a reconnect must not fire afterwards
"""

import pytest

from core import lcu_events


@pytest.fixture()
def registry():
    return lcu_events.SubscriptionRegistry()


def test_subscribe_returns_unsubscribe_closure(registry):
    calls = []
    unsub = registry.subscribe("/lol-gameflow/v1/gameflow-phase", calls.append)
    assert callable(unsub)
    assert registry.active_uris() == ("/lol-gameflow/v1/gameflow-phase",)
    unsub()
    assert registry.active_uris() == ()


def test_dispatch_delivers_payload_to_every_callback(registry):
    seen_a, seen_b = [], []
    registry.subscribe("/lol-gameflow/v1/gameflow-phase", seen_a.append)
    registry.subscribe("/lol-gameflow/v1/gameflow-phase", seen_b.append)
    registry.dispatch("/lol-gameflow/v1/gameflow-phase", "ChampSelect")
    assert seen_a == ["ChampSelect"]
    assert seen_b == ["ChampSelect"]


def test_unsubscribe_removes_only_that_callback(registry):
    seen_a, seen_b = [], []
    unsub_a = registry.subscribe("/x", seen_a.append)
    registry.subscribe("/x", seen_b.append)
    unsub_a()
    registry.dispatch("/x", 1)
    assert seen_a == []
    assert seen_b == [1]
    assert registry.active_uris() == ("/x",)


def test_last_unsubscribe_releases_the_uri(registry):
    released = []
    registry.on_release = released.append
    unsub = registry.subscribe("/x", lambda _: None)
    unsub()
    assert released == ["/x"]
    assert registry.active_uris() == ()


def test_first_subscribe_acquires_once_per_uri(registry):
    acquired = []
    registry.on_acquire = acquired.append
    registry.subscribe("/x", lambda _: None)
    registry.subscribe("/x", lambda _: None)
    assert acquired == ["/x"], "second subscriber must not re-acquire upstream"


def test_raising_callback_does_not_starve_siblings(registry):
    seen = []

    def boom(_payload):
        raise RuntimeError("observer blew up")

    registry.subscribe("/x", boom)
    registry.subscribe("/x", seen.append)
    registry.dispatch("/x", "payload")
    assert seen == ["payload"], "a raising observer must not kill the stream"


def test_callbacks_from_a_previous_generation_are_dropped(registry):
    seen = []
    registry.subscribe("/x", seen.append)
    registry.bump_generation()  # simulates a socket reconnect
    registry.dispatch("/x", "after-reconnect")
    assert seen == [], "stale pre-reconnect observers must not fire"


def test_dispatch_to_unknown_uri_is_a_noop(registry):
    registry.dispatch("/never-subscribed", {"a": 1})


def test_double_unsubscribe_is_safe(registry):
    released = []
    registry.on_release = released.append
    unsub = registry.subscribe("/x", lambda _: None)
    unsub()
    unsub()
    assert released == ["/x"], "release must fire exactly once"


def test_prefix_subscription_matches_child_uris(registry):
    seen = []
    registry.subscribe("/lol-champ-select/v1/session", seen.append, prefix=True)
    registry.dispatch("/lol-champ-select/v1/session/actions/3", {"id": 3})
    assert seen == [{"id": 3}]


def test_exact_subscription_does_not_match_child_uris(registry):
    seen = []
    registry.subscribe("/lol-champ-select/v1/session", seen.append)
    registry.dispatch("/lol-champ-select/v1/session/actions/3", {"id": 3})
    assert seen == []


def test_rearm_restores_listeners_after_a_reconnect(registry):
    """A reconnect must not force every caller to re-subscribe."""
    seen = []
    registry.subscribe("/x", seen.append)
    registry.bump_generation()
    registry.dispatch("/x", "stale")
    assert seen == []
    assert registry.rearm() == ("/x",)
    registry.dispatch("/x", "fresh")
    assert seen == ["fresh"]


def test_dispatch_reports_delivery_count(registry):
    registry.subscribe("/x", lambda _: None)
    registry.subscribe("/x", lambda _: None)
    assert registry.dispatch("/x", 1) == 2
    assert registry.dispatch("/nope", 1) == 0


class TestEventFrameParsing:
    """The WAMP frame parser is pure, so malformed input is testable."""

    @staticmethod
    def parse(raw):
        return lcu_events.LcuEventBus._parse_event(raw)

    def test_valid_event_frame(self):
        raw = '[8,"OnJsonApiEvent",{"uri":"/lol-gameflow/v1/gameflow-phase",' \
              '"eventType":"Update","data":"ChampSelect"}]'
        assert self.parse(raw) == ("/lol-gameflow/v1/gameflow-phase", "ChampSelect")

    def test_bytes_frame_is_decoded(self):
        raw = b'[8,"OnJsonApiEvent",{"uri":"/a","data":1}]'
        assert self.parse(raw) == ("/a", 1)

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   ",
            "not json",
            "{}",
            "[]",
            '[8,"OnJsonApiEvent"]',
            '[5,"OnJsonApiEvent",{"uri":"/a"}]',
            '[8,"OnJsonApiEvent",null]',
            '[8,"OnJsonApiEvent",{"data":1}]',
            '[8,"OnJsonApiEvent",{"uri":123}]',
            b"\xff\xfe",
        ],
    )
    def test_malformed_frames_yield_no_uri(self, raw):
        assert self.parse(raw) == (None, None)


class TestKillSwitch:
    def test_enabled_by_default(self, monkeypatch):
        monkeypatch.delenv("RC_LCU_EVENTS", raising=False)
        assert lcu_events.bus_enabled() is True

    @pytest.mark.parametrize("value", ["0", "false", "FALSE", "no", "off", " off "])
    def test_disabled_values(self, monkeypatch, value):
        monkeypatch.setenv("RC_LCU_EVENTS", value)
        assert lcu_events.bus_enabled() is False

    def test_other_values_stay_enabled(self, monkeypatch):
        monkeypatch.setenv("RC_LCU_EVENTS", "1")
        assert lcu_events.bus_enabled() is True


class TestEndpointTopic:
    """Per-endpoint WAMP topics, as an alternative to the firehose."""

    @pytest.mark.parametrize(
        ("uri", "expected"),
        [
            ("/lol-gameflow/v1/gameflow-phase",
             "OnJsonApiEvent_lol-gameflow_v1_gameflow-phase"),
            ("/lol-champ-select/v1/session",
             "OnJsonApiEvent_lol-champ-select_v1_session"),
            ("lol-summoner/v1/current-summoner",
             "OnJsonApiEvent_lol-summoner_v1_current-summoner"),
            ("/lol-gameflow/v1/gameflow-phase/",
             "OnJsonApiEvent_lol-gameflow_v1_gameflow-phase"),
        ],
    )
    def test_topic_name(self, uri, expected):
        assert lcu_events.endpoint_topic(uri) == expected

    def test_topic_is_prefixed_by_the_firehose_name(self):
        topic = lcu_events.endpoint_topic("/a/b")
        assert topic.startswith(lcu_events.WAMP_TOPIC + "_")
