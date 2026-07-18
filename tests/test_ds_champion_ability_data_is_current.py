"""RM-81: `champion_ability_data_is_current` is the staleness companion to the
RM-79 presence guard.

`champion_has_ability_data` answers "is the champion PRESENT in the Meraki
snapshot?". It returns True for Mel, yet her stored W is still the pre-26.03
invulnerability on a 35s cooldown against a live 38s shield - present, but
wrong. This function answers the orthogonal "are the values still RIGHT?".

Both fail-soft directions are pinned below, because getting them backwards is
what would make the signal dangerous: a missing report must not flag the whole
roster, and a champion missing from a present report must not be called stale.
"""
from __future__ import annotations

import json

import core.daemon_slayer_client as M


def _reset():
    M._champ_stale_index = None


def _point_at(monkeypatch, tmp_path, payload, patch="16.14.1"):
    (tmp_path / "current.txt").write_text(patch, encoding="utf-8")
    (tmp_path / patch).mkdir(parents=True, exist_ok=True)
    if payload is not None:
        (tmp_path / patch / "ability_staleness.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
    monkeypatch.setattr(M, "_DS_DATA_DIR", tmp_path)
    _reset()


def test_listed_champion_is_not_current(monkeypatch, tmp_path):
    _point_at(monkeypatch, tmp_path, {"stale_champions": ["Mel", "Maokai"]})
    assert M.champion_ability_data_is_current("Mel") is False
    assert M.champion_ability_data_is_current("Maokai") is False


def test_unlisted_champion_is_current(monkeypatch, tmp_path):
    _point_at(monkeypatch, tmp_path, {"stale_champions": ["Mel"]})
    assert M.champion_ability_data_is_current("Garen") is True


def test_resolves_ddragon_id_and_display_name(monkeypatch, tmp_path):
    _point_at(monkeypatch, tmp_path, {"stale_champions": ["Master Yi"]})
    assert M.champion_ability_data_is_current("MasterYi") is False
    assert M.champion_ability_data_is_current("Master Yi") is False


def test_missing_report_fails_soft_to_current(monkeypatch, tmp_path):
    """Absence of evidence is not evidence of staleness."""
    _point_at(monkeypatch, tmp_path, None)
    assert M.champion_ability_data_is_current("Mel") is True


def test_unreadable_report_fails_soft_to_current(monkeypatch, tmp_path):
    _point_at(monkeypatch, tmp_path, {"stale_champions": ["Mel"]})
    (tmp_path / "16.14.1" / "ability_staleness.json").write_text(
        "{not json", encoding="utf-8"
    )
    _reset()
    assert M.champion_ability_data_is_current("Mel") is True


def test_empty_stale_list_marks_everyone_current(monkeypatch, tmp_path):
    _point_at(monkeypatch, tmp_path, {"stale_champions": []})
    assert M.champion_ability_data_is_current("Mel") is True


def test_orthogonal_to_the_rm79_presence_guard(monkeypatch, tmp_path):
    """The two guards answer different questions and must not be conflated."""
    _point_at(monkeypatch, tmp_path, {"stale_champions": ["Mel"]})
    M._champ_ability_index = {"mel": True}
    try:
        assert M.champion_has_ability_data("Mel") is True
        assert M.champion_ability_data_is_current("Mel") is False
    finally:
        M._champ_ability_index = None
