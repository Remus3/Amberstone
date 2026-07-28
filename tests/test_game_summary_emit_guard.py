"""M-02: the supervisor must not file a ``game-summary`` task the
ingester is GUARANTEED to refuse.

Ground truth measured 2026-07-28 over ``agents/state/task_queue.jsonl``:
583 filed ``game-summary`` rows, of which 91 came back
``unknown game_mode`` and 79 ``missing champion`` - 170 rows (29 pct)
that round-tripped the scheduler to reach a hardcoded early return in
``agents/agent2_backend/game_ingest.py:203-216``.

Both refusals are decidable from the payload alone at emit time, so the
emitter decides them. Ingest-side refusal stays as the belt-and-braces
net; these tests pin the emit-side half.
"""

from __future__ import annotations

import logging

from agents.supervisor import _should_emit_game_summary


def _payload(**over) -> dict:
    base = {
        "prev_mode": "game",
        "new_mode": "client",
        "champion": "Ahri",
        "game_mode": "ARAM",
        "source": "aram_coaching_data.json",
    }
    base.update(over)
    return base


# ------------------------------------------------------------ refusals

def test_absent_champion_key_is_not_emitted(caplog):
    """The wire payload OMITS ``champion`` - it is not the literal
    "Unknown". That normalisation happens ingest-side."""
    p = _payload()
    del p["champion"]
    with caplog.at_level(logging.INFO, logger="supervisor"):
        assert _should_emit_game_summary(p) is False
    assert any("champion" in r.getMessage() for r in caplog.records)


def test_unknown_champion_sentinel_is_not_emitted():
    assert _should_emit_game_summary(_payload(champion="Unknown")) is False
    assert _should_emit_game_summary(_payload(champion="")) is False
    assert _should_emit_game_summary(_payload(champion=None)) is False


def test_unknown_game_mode_is_not_emitted(caplog):
    """The 91-row sibling class the champion guard alone would leave
    behind."""
    with caplog.at_level(logging.INFO, logger="supervisor"):
        assert _should_emit_game_summary(_payload(game_mode="TUTORIAL")) is False
    assert any("game_mode" in r.getMessage() for r in caplog.records)


def test_absent_game_mode_is_not_emitted():
    p = _payload()
    del p["game_mode"]
    assert _should_emit_game_summary(p) is False


def test_empty_payload_is_not_emitted():
    """The no-coaching-JSON edge case: prev/new only, nothing to ingest."""
    assert _should_emit_game_summary(
        {"prev_mode": "game", "new_mode": "client"}
    ) is False


# ------------------------------------------------------------ emissions

def test_happy_path_is_emitted():
    assert _should_emit_game_summary(_payload()) is True


def test_mode_category_is_accepted_as_the_game_mode_fallback():
    """``_select_mode_db`` is fed ``game_mode or mode_category`` ingest-side;
    the emit-side precheck must read the SAME two keys or it will suppress
    rows the ingester would have accepted."""
    p = _payload(mode_category="CHERRY")
    del p["game_mode"]
    assert _should_emit_game_summary(p) is True


def test_every_shipped_mode_db_key_passes_the_guard():
    """Derive the universe from the ingester, not from a literal list -
    a new mode added to GAME_MODE_TO_DB must not be silently suppressed."""
    from agents.agent2_backend.game_ingest import GAME_MODE_TO_DB

    for game_mode in GAME_MODE_TO_DB:
        assert _should_emit_game_summary(_payload(game_mode=game_mode)) is True, game_mode


def test_guard_is_case_insensitive_like_the_ingester():
    assert _should_emit_game_summary(_payload(game_mode="aram")) is True
