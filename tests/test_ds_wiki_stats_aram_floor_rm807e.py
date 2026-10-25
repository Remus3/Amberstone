"""RM-807 (e): an all-neutral wiki ARAM modifier block must fail loudly.

``tools/daemon_slayer_wiki_stats_extract.py`` parses ``mode_modifiers.aram``
from the wiki ChampionData module. A failed raw-module fetch, or a wiki rename
of the block or its keys, leaves every champion with no ARAM block (or a
neutral one), and the sidecar was written anyway: the RM-805 shape on the wiki
side. Every committed snapshot 16.11.1 .. 16.21.1 has at most 39 of 171
champions neutral (22.8 percent).

The extractor now measures the ARAM block before writing: at or above the 95
percent neutral floor it exits ``EXIT_ARAM_NEUTRAL`` and writes nothing, unless
``--allow-neutral-aram REASON`` is given, which is printed and recorded in the
payload as ``_aram_neutral_override``.

Every test is synthetic (no network, no live-tree write) except the committed
snapshot guard, which only reads.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_TOOLS = str(ROOT / "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import daemon_slayer_wiki_stats_extract as W  # noqa: E402

LIVE_ARAM = {"dmg_dealt": 1.05, "dmg_taken": 0.95}
NEUTRAL_ARAM = {"dmg_dealt": 1.0, "dmg_taken": 1.0, "ability_haste": 0.0}


def _champions(rows: int, neutral: int, *, no_block: bool = False) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i in range(rows):
        if i < neutral:
            modes = {} if no_block else {"aram": dict(NEUTRAL_ARAM)}
        else:
            modes = {"aram": dict(LIVE_ARAM), "urf": {"dmg_dealt": 1.1}}
        out[f"Champ{i:03d}"] = {"wiki_name": f"Champ{i:03d}",
                                W._FIELD_MODE_MODIFIERS: modes}
    return out


def _payload(champions: dict[str, dict]) -> dict:
    return {
        "_champ_count": len(champions),
        "_with_cast_time": len(champions),
        "_with_cast_measured": len(champions),
        "_offset_cast_fills": 0,
        "_default_cast_fills": 0,
        "_with_missile_speed": 0,
        "_cdragon_cast_fills": 0,
        "_errors": [],
        "champions": champions,
    }


class TestCheckAramNeutrality:
    def test_empty_roster_refused(self):
        with pytest.raises(W.NeutralAramModifiersError, match="empty"):
            W.check_aram_neutrality({})

    def test_no_aram_block_anywhere_refused(self):
        # the raw-module-fetch-failed shape: every champion {} mode_modifiers
        with pytest.raises(W.NeutralAramModifiersError, match="171/171"):
            W.check_aram_neutrality(_champions(171, 171, no_block=True))

    def test_all_neutral_blocks_refused(self):
        with pytest.raises(W.NeutralAramModifiersError, match="RM-807"):
            W.check_aram_neutrality(_champions(171, 171))

    def test_at_floor_refused(self):
        # 163/171 = 95.3 percent neutral, at or above the floor
        with pytest.raises(W.NeutralAramModifiersError):
            W.check_aram_neutrality(_champions(171, 163))

    def test_just_below_floor_passes(self):
        # 162/171 = 94.7 percent
        out = W.check_aram_neutrality(_champions(171, 162))
        assert out["neutral_rows"] == 162
        assert out["neutral_fraction"] < W.ARAM_NEUTRAL_FAIL_FRACTION

    def test_live_shape_passes_with_measurement(self):
        out = W.check_aram_neutrality(_champions(171, 39))
        assert out == {"rows": 171, "neutral_rows": 39,
                       "neutral_fraction": round(39 / 171, 4),
                       "threshold": W.ARAM_NEUTRAL_FAIL_FRACTION}
        assert "override_reason" not in out

    def test_override_accepts_and_records(self, capsys):
        out = W.check_aram_neutrality(_champions(171, 171), override_reason="adjudicated")
        assert out["override_reason"] == "adjudicated"
        assert out["neutral_rows"] == 171
        assert "RM-807 override" in capsys.readouterr().err

    def test_blank_override_still_refused(self):
        with pytest.raises(W.NeutralAramModifiersError):
            W.check_aram_neutrality(_champions(171, 171), override_reason="   ")

    def test_ability_haste_is_flat_not_multiplier(self):
        assert not W._aram_block_is_neutral({"ability_haste": 10.0})
        assert not W._aram_block_is_neutral({"ability_haste": -10.0})
        assert W._aram_block_is_neutral({"ability_haste": 0.0, "dmg_dealt": 1.0})

    def test_each_multiplier_key_counts(self):
        for key in W._ARAM_MULT_KEYS:
            assert not W._aram_block_is_neutral({key: 1.2}), key
            assert W._aram_block_is_neutral({key: 1.0}), key

    def test_unknown_keys_alone_read_neutral(self):
        # a wiki key rename is parser drift: it must not count as live data
        assert W._aram_block_is_neutral({"damage_dealt_renamed": 1.05})

    def test_bool_and_non_numeric_values_ignored(self):
        assert W._aram_block_is_neutral({"dmg_dealt": True, "dmg_taken": "1.05"})
        assert W._aram_block_is_neutral(None)

    def test_odd_records_read_neutral_without_crash(self):
        champs = {"A": None, "B": "x", "C": {W._FIELD_MODE_MODIFIERS: [1]},
                  "D": {W._FIELD_MODE_MODIFIERS: "x"},
                  "E": {W._FIELD_MODE_MODIFIERS: {"aram": [1.05]}}}
        with pytest.raises(W.NeutralAramModifiersError, match="5/5"):
            W.check_aram_neutrality(champs)

    def test_unneeded_override_is_reported_not_recorded(self, capsys):
        out = W.check_aram_neutrality(_champions(171, 39), override_reason="spare")
        assert "override_reason" not in out
        assert "not needed" in capsys.readouterr().err

    def test_other_modes_do_not_count(self):
        champs = {f"C{i}": {W._FIELD_MODE_MODIFIERS: {"urf": {"dmg_dealt": 1.1}}}
                  for i in range(20)}
        with pytest.raises(W.NeutralAramModifiersError):
            W.check_aram_neutrality(champs)


class TestMainGate:
    def _run(self, monkeypatch, tmp_path, champions, *extra):
        monkeypatch.setattr(W, "extract", lambda *a, **k: _payload(champions))
        out = tmp_path / "wiki_stats.json"
        rc = W.main(["--patch", "16.99.1", "--out", str(out), *extra])
        return rc, out

    def test_neutral_exits_and_writes_nothing(self, monkeypatch, tmp_path, capsys):
        rc, out = self._run(monkeypatch, tmp_path, _champions(171, 171, no_block=True))
        assert rc == W.EXIT_ARAM_NEUTRAL
        assert rc != 0
        assert not out.exists()
        assert "--allow-neutral-aram" in capsys.readouterr().err

    def test_neutral_dry_run_also_exits(self, monkeypatch, tmp_path):
        rc, out = self._run(monkeypatch, tmp_path, _champions(171, 171), "--dry-run")
        assert rc == W.EXIT_ARAM_NEUTRAL
        assert not out.exists()

    def test_override_writes_and_records(self, monkeypatch, tmp_path):
        rc, out = self._run(monkeypatch, tmp_path, _champions(171, 171),
                            "--allow-neutral-aram", "wiki block removed upstream")
        assert rc == 0
        doc = json.loads(out.read_text(encoding="utf-8"))
        rec = doc["_aram_neutral_override"]
        assert rec["reason"] == "wiki block removed upstream"
        assert rec["rows"] == 171 and rec["neutral_rows"] == 171
        assert rec["threshold"] == W.ARAM_NEUTRAL_FAIL_FRACTION

    def test_live_shape_writes_without_override_key(self, monkeypatch, tmp_path):
        rc, out = self._run(monkeypatch, tmp_path, _champions(171, 39))
        assert rc == 0
        doc = json.loads(out.read_text(encoding="utf-8"))
        assert "_aram_neutral_override" not in doc

    def test_cdragon_only_source_is_not_gated(self, monkeypatch, tmp_path):
        # the cdragon stage never parses mode_modifiers, so {} is by design
        rc, out = self._run(monkeypatch, tmp_path, _champions(171, 171, no_block=True),
                            "--source", "cdragon")
        assert rc == 0
        assert out.exists()


def _committed_snapshots() -> list[Path]:
    return sorted((ROOT / "data" / "daemon_slayer").glob("*/wiki_stats.json"))


def test_committed_snapshots_enumerated():
    assert len(_committed_snapshots()) >= 9


@pytest.mark.parametrize("path", _committed_snapshots(), ids=lambda p: p.parent.name)
def test_committed_snapshot_clear_of_floor(path):
    doc = json.loads(path.read_text(encoding="utf-8"))
    out = W.check_aram_neutrality(doc["champions"])
    assert out["rows"] >= 171
    # measured 2026-10-25: at most 39/171 neutral; leave headroom, keep a margin
    assert out["neutral_fraction"] < 0.5
