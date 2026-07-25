"""RM-04 A-01b: seam-forward ``widen_carry_pool`` through the RC DS client.

The engine side already works: ``agents/daemon_slayer/rank.py`` accepts
``widen_carry_pool`` (rank_items signature) and ``agents/daemon_slayer/server.py``
parses it off the POST body. RC's live client
(``core/daemon_slayer_client.py``) never mentioned the flag, so the widen seam
could not reach RC's carry chokepoint at all and A-01 was unmeasurable in
production.

These tests pin the DSP2 ``exempt_offclass_by_win`` contract for the new flag:

  a) DEFAULT (False) emits NO ``widen_carry_pool`` key - the wire payload is
     byte-identical to the pre-seam request.
  b) True emits ``widen_carry_pool: True`` in the POST body.

The HTTP layer (``_post_json``) is mocked, so DS :8893 does not need to be up.
"""

from __future__ import annotations

import json

import pytest

from core import daemon_slayer_client as dsc


@pytest.fixture()
def captured_bodies(monkeypatch):
    """Capture every ``_post_json`` body; answer with an empty ranking."""
    bodies: list[tuple[str, dict]] = []

    def _fake_post_json(path, body, timeout=dsc.DEFAULT_TIMEOUT):
        bodies.append((path, dict(body)))
        return {"ranked": []}

    monkeypatch.setattr(dsc, "_post_json", _fake_post_json)
    return bodies


def _rank_kwargs() -> dict:
    return {
        "level": 11,
        "item_ids": ["3031", "3153"],
        "mode": "SR",
        "target_armor": 80.0,
        "target_mr": 55.0,
        "top": 8,
    }


# --------------------------------------------------------------------------
# rank_for (the thin POST /rank client)
# --------------------------------------------------------------------------

def test_rank_for_default_omits_widen_carry_pool(captured_bodies):
    rows = dsc.rank_for("Jinx", **_rank_kwargs())
    assert rows == []
    assert len(captured_bodies) == 1
    path, body = captured_bodies[0]
    assert path == "/rank"
    assert "widen_carry_pool" not in body


def test_rank_for_true_emits_widen_carry_pool(captured_bodies):
    rows = dsc.rank_for("Jinx", widen_carry_pool=True, **_rank_kwargs())
    assert rows == []
    _path, body = captured_bodies[0]
    assert body.get("widen_carry_pool") is True


def test_rank_for_false_is_byte_identical_to_flagless(captured_bodies):
    dsc.rank_for("Jinx", **_rank_kwargs())
    dsc.rank_for("Jinx", widen_carry_pool=False, **_rank_kwargs())
    assert len(captured_bodies) == 2
    assert json.dumps(captured_bodies[0][1], sort_keys=True) == json.dumps(
        captured_bodies[1][1], sort_keys=True
    )


# --------------------------------------------------------------------------
# rank_for_primary_archetype (the archetype dispatcher; carry -> ds.dps)
# --------------------------------------------------------------------------

def test_dispatcher_carry_default_omits_widen_carry_pool(captured_bodies):
    out = dsc.rank_for_primary_archetype("Jinx", "carry", **_rank_kwargs())
    assert out is not None and out.get("scorer") == "dps"
    assert captured_bodies, "dispatcher never reached the HTTP layer"
    _path, body = captured_bodies[-1]
    assert "widen_carry_pool" not in body


def test_dispatcher_carry_true_emits_widen_carry_pool(captured_bodies):
    out = dsc.rank_for_primary_archetype(
        "Jinx", "carry", widen_carry_pool=True, **_rank_kwargs()
    )
    assert out is not None and out.get("scorer") == "dps"
    _path, body = captured_bodies[-1]
    assert body.get("widen_carry_pool") is True


def test_dispatcher_accepts_flag_as_tail_keyword():
    """The new parameter must be keyword-accepted and default False."""
    import inspect

    for fn in (dsc.rank_for, dsc.rank_for_primary_archetype):
        sig = inspect.signature(fn)
        assert "widen_carry_pool" in sig.parameters, fn.__name__
        param = sig.parameters["widen_carry_pool"]
        assert param.default is False, fn.__name__
        assert param.kind is inspect.Parameter.KEYWORD_ONLY, fn.__name__
