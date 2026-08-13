"""B4-e (RM-189): GET /api/branch-review + /api/branch-review/runs.

The post-game half of the compliance split. Both handlers are driven through
a stub handler capturing _send(status, body, ctype) - the auto_accept /
loop_control idiom.

The reader is redirected at core.hz_choice_shadow.SHADOW_PATH to a tmp file so
the LIVE 68 MB corpus is never read by the suite, and a module-scoped guard
asserts the live file was not written.
"""
from __future__ import annotations

import json

import pytest

from core import branch_review
from dashboard import routes_coach as mod


class FakeHandler:
    def __init__(self, path: str = "/api/branch-review") -> None:
        self.path = path
        self.sent: tuple | None = None

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.sent = (status, body, ctype)


def _row(**kw):
    base = {
        "ts": "2026-08-12T20:00:00+00:00", "mode": "aram",
        "my_champion": "Annie", "enemy": "Caitlyn", "band": "L6",
        "mana_state": "full", "cd_state": "all_up", "covered": True,
        "game_time_s": 300.0, "level": 6, "item_count": 2,
        "engine_version": "1.277.0",
        "choices": [{"key": "A", "label": "Force a short trade"},
                    {"key": "B", "label": "Back off"}],
        "native_action": "POKE PHASE", "native_choices": [],
        "cv_override": None, "verdict_blocks": None,
        "game_id": None, "game_run_id": "run-one",
    }
    base.update(kw)
    return base


@pytest.fixture(autouse=True)
def corpus(tmp_path, monkeypatch):
    p = tmp_path / "hz.jsonl"
    p.write_text(
        "".join(json.dumps(r) + "\n" for r in [
            _row(game_time_s=120.0, level=3),
            _row(game_time_s=300.0, level=6),
            _row(game_time_s=600.0, level=11, game_run_id="run-two",
                 my_champion="Ashe"),
        ]),
        encoding="utf-8")
    monkeypatch.setattr(branch_review, "SHADOW_PATH", p)
    return p


@pytest.fixture(scope="module", autouse=True)
def _live_corpus_untouched():
    """The live corpus is 68 MB of validation data. Assert this module never
    writes it - a redirect regression would otherwise be invisible."""
    from pathlib import Path

    live = (Path(branch_review.__file__).resolve().parent.parent
            / "data" / "hz_choice_shadow.jsonl")
    before = live.stat().st_mtime_ns if live.exists() else None
    yield
    after = live.stat().st_mtime_ns if live.exists() else None
    assert before == after, "the LIVE shadow corpus was modified by a test"


def _get(path: str):
    h = FakeHandler(path)
    fn = _handler_for(path)
    fn(h)
    status, body, ctype = h.sent
    return status, json.loads(body), ctype


def _handler_for(path: str):
    for matcher, fn in mod.GET_ROUTES:
        if matcher(path):
            return fn
    raise AssertionError(f"no route matched {path}")


# --- behaviour -------------------------------------------------------------

def test_defaults_to_the_most_recent_run():
    status, payload, ctype = _get("/api/branch-review")
    assert status == 200
    assert ctype == "application/json"
    assert payload["game_run_id"] == "run-two"
    assert payload["my_champion"] == "Ashe"


def test_run_query_selects_a_match():
    status, payload, _ = _get("/api/branch-review?run=run-one")
    assert status == 200
    assert payload["game_run_id"] == "run-one"
    assert len(payload["branches"]) == 2


def test_unknown_run_is_200_with_a_reason_not_an_error():
    """An unknown id is a normal empty result, not a failure - the view
    renders a no-data state rather than an error banner."""
    status, payload, _ = _get("/api/branch-review?run=nope")
    assert status == 200
    assert payload["branches"] == []
    assert payload["reason"] == "run-not-found"


def test_blank_run_param_falls_back_to_most_recent():
    status, payload, _ = _get("/api/branch-review?run=")
    assert status == 200
    assert payload["game_run_id"] == "run-two"


def test_runs_listing():
    status, payload, _ = _get("/api/branch-review/runs")
    assert status == 200
    ids = [r["game_run_id"] for r in payload["runs"]]
    assert ids == ["run-two", "run-one"], "newest first"
    assert payload["runs"][1]["ticks"] == 2


def test_runs_limit_is_clamped_not_fatal():
    """_limit_param degrades a malformed value instead of 500-ing the route."""
    status, payload, _ = _get("/api/branch-review/runs?limit=abc")
    assert status == 200
    assert len(payload["runs"]) == 2


# --- registration ----------------------------------------------------------

def test_both_routes_registered_and_ordered():
    """The bare path must not swallow /runs - more-specific first."""
    paths = [m for m, _ in mod.GET_ROUTES]
    idx_runs = next(i for i, m in enumerate(paths)
                    if m("/api/branch-review/runs"))
    idx_bare = next(i for i, m in enumerate(paths)
                    if m("/api/branch-review"))
    assert idx_runs < idx_bare
    assert _handler_for("/api/branch-review/runs") is mod._serve_branch_review_runs
    assert _handler_for("/api/branch-review") is mod._serve_branch_review


def test_bare_matcher_does_not_claim_the_runs_path():
    bare = next(m for m, fn in mod.GET_ROUTES
                if fn is mod._serve_branch_review)
    assert bare("/api/branch-review") is True
    assert bare("/api/branch-review?run=x") is True
    assert bare("/api/branch-review/runs") is False


def test_no_anthropic_call_and_no_write(corpus):
    """This route is read-only by construction; a regression that made it
    write would corrupt the validation corpus."""
    before = corpus.read_bytes()
    _get("/api/branch-review")
    _get("/api/branch-review/runs")
    assert corpus.read_bytes() == before
