# arch: A-26 / RM-95b roster de-cap tests for the four 171-keyed sidecar extractors | section=tools-tests | frozen=no
"""Offline tests for the A-26 / RM-95b sidecar roster de-cap.

Background (all measured 2026-07-25, see docs/specs/DECISION_cdragon_cross_reference.md
GT-6): the four "independent" sidecar extractors are ONE feed, because each derives
its champion list from ``champion_abilities.json`` (171 keys) rather than from the
DDragon roster ``champions.json`` (173 keys). The two champions that fall off are
exactly Locke and Zaahen. The Meraki hop that produces ``champion_abilities.json``
is dead upstream; the roster file is not.

This module proves the de-cap in BOTH directions:
  * opt-in ON  -> the champion list is the full 173-entry roster, Locke + Zaahen in
  * opt-in OFF -> the champion list is byte-identical to the pre-de-cap behavior
    (the abilities keyspace), so no existing sidecar output moves

NO network. Every assertion runs against a tmp fixture or the committed on-disk
snapshot. 2026-07-25 (A-26 / RM-95b B1).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_TOOLS = Path(__file__).resolve().parent.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import daemon_slayer_cdragon_ratio_extract as RATIO  # noqa: E402
import daemon_slayer_cdragon_spell_extract as SPELL  # noqa: E402
import daemon_slayer_wiki_ability_extract as ABIL  # noqa: E402
import daemon_slayer_wiki_stats_extract as STATS  # noqa: E402

# The three modules that expose ``_load_champion_ids`` (list-returning).
_ID_MODULES = [
    pytest.param(STATS, id="wiki_stats"),
    pytest.param(SPELL, id="cdragon_spell"),
    pytest.param(RATIO, id="cdragon_ratio"),
]

_PATCH = "16.11.1"

# The fixture models the real shape: the roster carries two champions the
# abilities snapshot does not.
_ABILITY_KEYS = ["Aatrox", "Ahri", "Zed"]
_ROSTER_KEYS = ["Aatrox", "Ahri", "Locke", "Zaahen", "Zed"]


def _seed(tmp_path: Path) -> Path:
    """Write a minimal patch dir with a 3-key abilities file + a 5-key roster."""
    pd = tmp_path / _PATCH
    pd.mkdir(parents=True, exist_ok=True)
    (pd / "champion_abilities.json").write_text(
        json.dumps({"version": _PATCH, "data": {k: {} for k in _ABILITY_KEYS}}),
        encoding="utf-8",
    )
    (pd / "champions.json").write_text(
        json.dumps(
            {
                "version": _PATCH,
                "data": {k: {"id": k, "key": str(i)} for i, k in enumerate(_ROSTER_KEYS)},
            }
        ),
        encoding="utf-8",
    )
    return pd


# --------------------------------------------------------------------------- de-cap ON
class TestFullRosterOptIn:
    @pytest.mark.parametrize("mod", _ID_MODULES)
    def test_full_roster_reaches_the_roster_keyspace(self, mod, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "DATA_DIR", tmp_path)
        _seed(tmp_path)
        assert mod._resolve_champion_ids(_PATCH, True) == sorted(_ROSTER_KEYS)

    def test_wiki_ability_full_roster_reaches_the_roster_keyspace(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(ABIL, "DATA_DIR", tmp_path)
        _seed(tmp_path)
        assert ABIL._resolve_keep_apinames(_PATCH, full_roster=True) == set(_ROSTER_KEYS)

    @pytest.mark.parametrize("mod", _ID_MODULES)
    def test_full_roster_includes_locke_and_zaahen(self, mod, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "DATA_DIR", tmp_path)
        _seed(tmp_path)
        ids = mod._resolve_champion_ids(_PATCH, True)
        assert "Locke" in ids
        assert "Zaahen" in ids

    def test_missing_roster_file_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(SPELL, "DATA_DIR", tmp_path)
        pd = tmp_path / _PATCH
        pd.mkdir(parents=True)
        (pd / "champion_abilities.json").write_text(
            json.dumps({"data": {"Ahri": {}}}), encoding="utf-8"
        )
        with pytest.raises(SystemExit):
            SPELL._resolve_champion_ids(_PATCH, True)


# --------------------------------------------------------------------------- de-cap OFF (behavior preserving)
class TestDefaultIsUnchanged:
    @pytest.mark.parametrize("mod", _ID_MODULES)
    def test_default_is_the_abilities_keyspace(self, mod, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "DATA_DIR", tmp_path)
        _seed(tmp_path)
        assert mod._resolve_champion_ids(_PATCH, False) == sorted(_ABILITY_KEYS)

    @pytest.mark.parametrize("mod", _ID_MODULES)
    def test_default_excludes_locke_and_zaahen(self, mod, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "DATA_DIR", tmp_path)
        _seed(tmp_path)
        ids = mod._resolve_champion_ids(_PATCH, False)
        assert "Locke" not in ids
        assert "Zaahen" not in ids

    @pytest.mark.parametrize("mod", _ID_MODULES)
    def test_default_ignores_the_roster_file_entirely(self, mod, tmp_path, monkeypatch):
        """No roster file on disk -> the default path must still work."""
        monkeypatch.setattr(mod, "DATA_DIR", tmp_path)
        pd = tmp_path / _PATCH
        pd.mkdir(parents=True)
        (pd / "champion_abilities.json").write_text(
            json.dumps({"data": {k: {} for k in _ABILITY_KEYS}}), encoding="utf-8"
        )
        assert mod._resolve_champion_ids(_PATCH, False) == sorted(_ABILITY_KEYS)

    def test_wiki_ability_default_is_the_abilities_keyspace(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ABIL, "DATA_DIR", tmp_path)
        _seed(tmp_path)
        assert ABIL._resolve_keep_apinames(_PATCH, full_roster=False) == set(_ABILITY_KEYS)

    def test_wiki_ability_resolver_delegates_to_the_legacy_loader(self, monkeypatch):
        """The default path must go through ``_load_champion_apinames`` so every
        existing test seam that stubs that loader keeps working."""
        calls: list[str] = []
        monkeypatch.setattr(
            ABIL, "_load_champion_apinames", lambda p: calls.append(p) or {"Ahri"}
        )
        assert ABIL._resolve_keep_apinames(_PATCH, full_roster=False) == {"Ahri"}
        assert calls == [_PATCH]

    @pytest.mark.parametrize("mod", _ID_MODULES)
    def test_resolver_delegates_to_the_legacy_loader(self, mod, monkeypatch):
        """The default path must go through ``_load_champion_ids`` so every
        existing test seam that stubs that loader keeps working."""
        calls: list[str] = []
        monkeypatch.setattr(
            mod, "_load_champion_ids", lambda p: calls.append(p) or ["Ahri"]
        )
        assert mod._resolve_champion_ids(_PATCH, False) == ["Ahri"]
        assert calls == [_PATCH]


# --------------------------------------------------------------------------- CLI surface
class TestCliFlag:
    @pytest.mark.parametrize(
        "mod", _ID_MODULES + [pytest.param(ABIL, id="wiki_ability")]
    )
    def test_full_roster_flag_defaults_off(self, mod):
        src = Path(mod.__file__).read_text(encoding="utf-8")
        assert "--full-roster" in src, "extractor exposes no --full-roster opt-in"
        assert "store_true" in src


# --------------------------------------------------------------------------- committed snapshot (on-disk, no network)
class TestCommittedSnapshot:
    """The real numbers, read off the committed patch dir. No network."""

    @staticmethod
    def _patch_dir() -> Path:
        root = _TOOLS.parent / "data" / "daemon_slayer"
        return root / (root / "current.txt").read_text(encoding="utf-8").strip()

    def test_the_gap_is_exactly_locke_and_zaahen(self):
        pd = self._patch_dir()
        roster = json.loads((pd / "champions.json").read_text(encoding="utf-8"))["data"]
        abil = json.loads(
            (pd / "champion_abilities.json").read_text(encoding="utf-8")
        )["data"]
        assert len(roster) == 173
        assert len(abil) == 171
        assert sorted(set(roster) - set(abil)) == ["Locke", "Zaahen"]
        assert not set(abil) - set(roster)

    def test_full_roster_on_the_committed_snapshot_is_173(self):
        patch = (_TOOLS.parent / "data" / "daemon_slayer" / "current.txt").read_text(
            encoding="utf-8"
        ).strip()
        ids = SPELL._resolve_champion_ids(patch, True)
        assert len(ids) == 173
        assert {"Locke", "Zaahen"} <= set(ids)

    def test_default_on_the_committed_snapshot_is_still_171(self):
        patch = (_TOOLS.parent / "data" / "daemon_slayer" / "current.txt").read_text(
            encoding="utf-8"
        ).strip()
        ids = SPELL._resolve_champion_ids(patch, False)
        assert len(ids) == 171
        assert not {"Locke", "Zaahen"} & set(ids)


# --------------------------------------------------------------------------- wiki title list (the actual payoff)
_MODULE_TEXT = (
    'return {\n'
    '  ["Ahri"] = {\n    ["id"] = 103,\n    ["apiname"] = "Ahri",\n'
    '    ["skill_q"] = {[1] = "Orb of Deception"},\n  },\n'
    '  ["Locke"] = {\n    ["id"] = 805,\n    ["apiname"] = "Locke",\n'
    '    ["skill_q"] = {[1] = "Ritual Nails"},\n'
    '    ["skill_r"] = {[1] = "Purgatory"},\n  },\n'
    '  ["Zaahen"] = {\n    ["id"] = 904,\n    ["apiname"] = "Zaahen",\n'
    '    ["skill_e"] = {[1] = "Aureate Rush"},\n  },\n}\n'
)


class TestWikiTitlesGained:
    """The de-cap's actual payoff: Template:Data titles that were never requested."""

    @staticmethod
    def _titles(keep):
        skills = ABIL._parse_champion_skills(_MODULE_TEXT)
        return [d + "/" + n for _api, d, n in ABIL._build_titles(skills, keep)]

    def test_default_requests_no_locke_or_zaahen_pages(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ABIL, "DATA_DIR", tmp_path)
        _seed(tmp_path)
        titles = self._titles(ABIL._resolve_keep_apinames(_PATCH, False))
        assert titles == ["Ahri/Orb of Deception"]

    def test_full_roster_requests_locke_and_zaahen_pages(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ABIL, "DATA_DIR", tmp_path)
        _seed(tmp_path)
        titles = self._titles(ABIL._resolve_keep_apinames(_PATCH, True))
        assert titles == [
            "Ahri/Orb of Deception",
            "Locke/Ritual Nails",
            "Locke/Purgatory",
            "Zaahen/Aureate Rush",
        ]


# --------------------------------------------------------------------------- ASCII hygiene
class TestAscii:
    def test_source_is_ascii(self):
        src = Path(__file__).read_bytes()
        assert all(b < 128 for b in src), "non-ASCII byte in an authored test file"
