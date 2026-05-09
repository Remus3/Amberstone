"""Phase 4.1 dispatch-level soft-warn validation tests.

Covers `dashboard._dispatch._validate_request_body` — the soft-warn POST
body validator that mirrors the Phase 4.3 coaching_payload pattern.
Validation never rejects; it only logs warnings. These tests pin the
warning surface so a future schema drift becomes visible.
"""
from __future__ import annotations

import logging

import pytest

from dashboard._dispatch import _REQUEST_MODELS, _validate_request_body


# Single source of truth — anything that adds a path here without
# updating api_schema.py will fail this test.
_EXPECTED_KNOWN_PATHS = {
    "/api/input",
    "/api/command",
    "/api/ds-preview",
    "/api/bridge/inbox",
    "/api/speak",
}


def _warnings(caplog) -> list[str]:
    return [r.getMessage()
            for r in caplog.records
            if r.levelno == logging.WARNING]


class TestRegistry:
    def test_request_models_covers_expected_paths(self):
        assert set(_REQUEST_MODELS.keys()) == _EXPECTED_KNOWN_PATHS

    def test_models_are_pydantic_basemodel_subclasses(self):
        from pydantic import BaseModel
        for path, cls in _REQUEST_MODELS.items():
            assert issubclass(cls, BaseModel), (
                f"{path} -> {cls.__name__} is not a BaseModel")


class TestUnmappedPath:
    """Paths not in _REQUEST_MODELS should pass silently — no false noise."""

    def test_unknown_path_with_garbage_body_is_silent(self, caplog):
        with caplog.at_level(logging.WARNING, logger="rc.dispatch"):
            _validate_request_body("/api/totally-unknown",
                                   {"this": "could be anything"})
        assert _warnings(caplog) == []

    def test_unknown_path_with_non_dict_body_is_silent(self, caplog):
        with caplog.at_level(logging.WARNING, logger="rc.dispatch"):
            _validate_request_body("/api/coach/toggle", ["not", "a", "dict"])
        assert _warnings(caplog) == []


class TestKnownPathValid:
    def test_input_minimal_valid(self, caplog):
        with caplog.at_level(logging.WARNING, logger="rc.dispatch"):
            _validate_request_body("/api/input", {"text": "hello"})
        assert _warnings(caplog) == []

    def test_command_minimal_valid(self, caplog):
        with caplog.at_level(logging.WARNING, logger="rc.dispatch"):
            _validate_request_body("/api/command", {"command": "refresh"})
        assert _warnings(caplog) == []

    def test_ds_preview_minimal_valid(self, caplog):
        with caplog.at_level(logging.WARNING, logger="rc.dispatch"):
            _validate_request_body("/api/ds-preview", {"champion": "Vayne"})
        assert _warnings(caplog) == []

    def test_ds_preview_full_valid(self, caplog):
        with caplog.at_level(logging.WARNING, logger="rc.dispatch"):
            _validate_request_body("/api/ds-preview", {
                "champion": "Vayne", "mode": "ARAM",
                "level": 11, "items": ["3046", "3094"],
            })
        assert _warnings(caplog) == []

    def test_bridge_inbox_minimal_valid(self, caplog):
        with caplog.at_level(logging.WARNING, logger="rc.dispatch"):
            _validate_request_body("/api/bridge/inbox", {
                "source": "peer", "summary": "ping",
            })
        assert _warnings(caplog) == []

    def test_speak_minimal_valid(self, caplog):
        with caplog.at_level(logging.WARNING, logger="rc.dispatch"):
            _validate_request_body("/api/speak", {"text": "hello world"})
        assert _warnings(caplog) == []


class TestKnownPathInvalid:
    """The point of soft-warn: catch contract drift loudly in logs."""

    def test_input_missing_required_text_warns(self, caplog):
        with caplog.at_level(logging.WARNING, logger="rc.dispatch"):
            _validate_request_body("/api/input", {})
        msgs = _warnings(caplog)
        assert any("text" in m for m in msgs), msgs

    def test_input_wrong_type_warns(self, caplog):
        with caplog.at_level(logging.WARNING, logger="rc.dispatch"):
            _validate_request_body("/api/input", {"text": 12345})
        msgs = _warnings(caplog)
        assert any("text" in m for m in msgs), msgs

    def test_input_extra_field_warns_forbid_extra(self, caplog):
        # InputRequest uses _ForbidExtra — extras should warn.
        with caplog.at_level(logging.WARNING, logger="rc.dispatch"):
            _validate_request_body("/api/input",
                                   {"text": "ok", "rogue": True})
        msgs = _warnings(caplog)
        assert any("rogue" in m for m in msgs), msgs

    def test_command_extra_field_warns_forbid_extra(self, caplog):
        with caplog.at_level(logging.WARNING, logger="rc.dispatch"):
            _validate_request_body("/api/command",
                                   {"command": "refresh", "extra": 1})
        msgs = _warnings(caplog)
        assert any("extra" in m for m in msgs), msgs

    def test_bridge_inbox_extra_field_passes_allow_extra(self, caplog):
        # BridgeInboxRequest uses _AllowExtra — extras should NOT warn.
        with caplog.at_level(logging.WARNING, logger="rc.dispatch"):
            _validate_request_body("/api/bridge/inbox", {
                "source": "peer", "summary": "ok",
                "rich_metadata": {"deep": {"nested": True}},
            })
        assert _warnings(caplog) == []

    def test_bridge_inbox_missing_summary_warns(self, caplog):
        with caplog.at_level(logging.WARNING, logger="rc.dispatch"):
            _validate_request_body("/api/bridge/inbox", {"source": "peer"})
        msgs = _warnings(caplog)
        assert any("summary" in m for m in msgs), msgs

    def test_ds_preview_missing_champion_warns(self, caplog):
        with caplog.at_level(logging.WARNING, logger="rc.dispatch"):
            _validate_request_body("/api/ds-preview", {"mode": "SR"})
        msgs = _warnings(caplog)
        assert any("champion" in m for m in msgs), msgs

    def test_ds_preview_wrong_type_level_warns(self, caplog):
        with caplog.at_level(logging.WARNING, logger="rc.dispatch"):
            _validate_request_body("/api/ds-preview", {
                "champion": "Vayne", "level": "high",
            })
        msgs = _warnings(caplog)
        assert any("level" in m for m in msgs), msgs


class TestNonDictBody:
    @pytest.mark.parametrize("body", [None, [], "raw string", 42])
    def test_non_dict_warns_for_known_path(self, body, caplog):
        with caplog.at_level(logging.WARNING, logger="rc.dispatch"):
            _validate_request_body("/api/input", body)
        msgs = _warnings(caplog)
        assert any("expected dict" in m for m in msgs), (body, msgs)


class TestQueryString:
    """equals() matcher accepts ?query suffixes; validator must too."""

    def test_query_string_strips_before_lookup(self, caplog):
        with caplog.at_level(logging.WARNING, logger="rc.dispatch"):
            _validate_request_body("/api/input?ts=12345", {"text": "ok"})
        assert _warnings(caplog) == []

    def test_query_string_still_warns_on_invalid(self, caplog):
        with caplog.at_level(logging.WARNING, logger="rc.dispatch"):
            _validate_request_body("/api/input?ts=12345", {})
        msgs = _warnings(caplog)
        assert any("text" in m for m in msgs), msgs


class TestDispatchPostIntegration:
    """Confirm dispatch_post actually calls the validator before route
    dispatch and never raises out of it."""

    def test_dispatch_post_invokes_validator(self, monkeypatch, caplog):
        from dashboard import _dispatch

        # Stub _gather_post so we don't pull live route registry.
        called = {}

        def _stub_handler(_h, body):
            called["body"] = body

        monkeypatch.setattr(_dispatch, "_gather_post",
                            lambda: [(lambda p: p == "/api/input",
                                      _stub_handler)])

        class _FakeHandler:
            path = "/api/input"

        with caplog.at_level(logging.WARNING, logger="rc.dispatch"):
            ok = _dispatch.dispatch_post(_FakeHandler(), {})  # missing text
        assert ok is True
        assert called["body"] == {}  # dispatch still proceeded
        msgs = _warnings(caplog)
        assert any("text" in m for m in msgs), msgs

    def test_dispatch_post_no_validator_noise_for_unmapped_path(
            self, monkeypatch, caplog):
        from dashboard import _dispatch

        def _stub_handler(_h, _body):
            pass

        monkeypatch.setattr(_dispatch, "_gather_post",
                            lambda: [(lambda p: p == "/api/coach/toggle",
                                      _stub_handler)])

        class _FakeHandler:
            path = "/api/coach/toggle"

        with caplog.at_level(logging.WARNING, logger="rc.dispatch"):
            ok = _dispatch.dispatch_post(_FakeHandler(),
                                         {"mode": "tft", "disabled": True})
        assert ok is True
        assert _warnings(caplog) == []
