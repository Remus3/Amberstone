"""Audit 2026-05-18: the carry/dps branch silently dropped only_item_ids.

`rank_for` had no `only_item_ids` param while the 5 sibling rankers
(tank/bruiser/mage/assassin/enchanter) all threaded it, so an ADC
build-order plan restricted to a curated pool no-oped the restriction.
These tests pin the fix: `rank_for` threads `only`, and
`rank_for_primary_archetype`'s carry fall-through passes it through.
"""
from __future__ import annotations

import core.daemon_slayer_client as dsc


def _capture(monkeypatch):
    captured: dict = {}

    def fake_post(path, body, timeout=dsc.DEFAULT_TIMEOUT):
        captured["path"] = path
        captured["body"] = body
        return {"ranked": [{"item_id": "3094", "item_name": "RFC",
                            "delta_dps": 12.0, "gold": 2600}]}

    monkeypatch.setattr(dsc, "_post_json", fake_post)
    return captured


def test_rank_for_threads_only(monkeypatch):
    cap = _capture(monkeypatch)
    rows = dsc.rank_for(
        "Caitlyn", level=11, item_ids=["3006"],
        only_item_ids=["3094", "1038", "3031"],
    )
    assert cap["path"] == "/rank"
    assert cap["body"]["only"] == ["3094", "1038", "3031"]
    assert rows and rows[0].item_id == "3094"


def test_rank_for_omits_only_when_not_given(monkeypatch):
    cap = _capture(monkeypatch)
    dsc.rank_for("Caitlyn", level=11, item_ids=["3006"])
    assert "only" not in cap["body"]  # backward-compat: pre-fix callers unchanged


def test_rank_for_filters_falsy_only_ids(monkeypatch):
    cap = _capture(monkeypatch)
    dsc.rank_for("Caitlyn", level=11, item_ids=[], only_item_ids=["3094", "", None])
    assert cap["body"]["only"] == ["3094"]


def test_primary_archetype_carry_threads_only(monkeypatch):
    cap = _capture(monkeypatch)
    out = dsc.rank_for_primary_archetype(
        "Caitlyn", "carry", level=11, item_ids=["3006"],
        only_item_ids=["3094", "1038"],
    )
    assert out["scorer"] == "dps"
    assert cap["path"] == "/rank"
    assert cap["body"]["only"] == ["3094", "1038"]


def test_primary_archetype_empty_arch_fallthrough_threads_only(monkeypatch):
    cap = _capture(monkeypatch)
    out = dsc.rank_for_primary_archetype(
        "Caitlyn", "", level=11, item_ids=["3006"],
        only_item_ids=["3094"],
    )
    # empty/unknown archetype falls through to ds.dps (carry path)
    assert out["scorer"] == "dps"
    assert cap["body"]["only"] == ["3094"]


def test_primary_archetype_carry_no_only_is_backward_compat(monkeypatch):
    cap = _capture(monkeypatch)
    dsc.rank_for_primary_archetype("Caitlyn", "carry", level=11, item_ids=["3006"])
    assert "only" not in cap["body"]
