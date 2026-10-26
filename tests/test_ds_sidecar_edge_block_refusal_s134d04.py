"""RM-912: an edge-blocked sidecar extract must fail loudly, not just warn.

Four offline DS sidecar extractors fail soft per champion, so a host that can
reach none of their sources still produces a well-formed payload of engine
defaults / zero counts. Each ``main()`` printed a "NOT a committable sidecar"
WARNING and then wrote the file anyway:

* ``tools/daemon_slayer_wiki_stats_extract.py`` - ``_with_cast_measured`` 0
  (every attack_cast_time is the 0.25 s default). Committed snapshots
  16.11.1 .. 16.21.1 all measure 170/171 (one default fill), so the gate is a
  floor: at or above 95 percent unmeasured (an empty roster included) the run
  exits ``EXIT_CAST_UNMEASURED`` and writes nothing, dry-run included;
  ``--allow-unmeasured-cast REASON`` records ``_cast_unmeasured_override``.
* ``tools/daemon_slayer_cdragon_spell_extract.py`` - every ``_with_*`` bucket 0
  (committed snapshots: ammo 24, missile 416-427, cc 185-186, geometry 619).
* ``tools/daemon_slayer_wiki_ability_extract.py`` - ``_ability_count`` 0
  (committed snapshots: 1046).
* ``tools/daemon_slayer_cdragon_ratio_extract.py`` - ``_n_mechanical_blocks`` 0
  (committed snapshots: 838-865); this sidecar is read by the engine, and the
  ``--drift`` report is refused with it.

The three siblings keep their existing all-zero condition: exit
``EXIT_EMPTY_SIDECAR``, write nothing, and ``--allow-empty REASON`` records
``_empty_override``. Every test is synthetic (no network, no live-tree write)
except the committed-snapshot guards, which only read.
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

import daemon_slayer_cdragon_ratio_extract as R  # noqa: E402
import daemon_slayer_cdragon_spell_extract as C  # noqa: E402
import daemon_slayer_wiki_ability_extract as A  # noqa: E402
import daemon_slayer_wiki_stats_extract as W  # noqa: E402

DATA = ROOT / "data" / "daemon_slayer"
# aram live plus every other mode present, so the RM-807 (e) and RM-911
# floors stay out of the cast-floor tests
LIVE_ARAM = {"aram": {"dmg_dealt": 1.05}, "urf": {"dmg_dealt": 1.1},
             "nb": {"dmg_taken": 0.95}, "ofa": {"dmg_dealt": 0.9},
             "usb": {"dmg_taken": 1.05}, "ar": {"hp_lvl": 17.0},
             "swift": {"arm_lvl": -0.5}}


# --------------------------------------------------------------------------
# wiki_stats: _with_cast_measured floor
# --------------------------------------------------------------------------

def _wiki_payload(rows: int, measured: int) -> dict:
    champions = {f"Champ{i:03d}": {W._FIELD_MODE_MODIFIERS: dict(LIVE_ARAM)}
                 for i in range(rows)}
    return {
        "_champ_count": rows,
        "_with_cast_time": rows,
        "_with_cast_measured": measured,
        "_offset_cast_fills": 0,
        "_default_cast_fills": rows - measured,
        "_with_missile_speed": 0,
        "_cdragon_cast_fills": 0,
        "_errors": [],
        "champions": champions,
    }


class TestCheckCastMeasured:
    def test_zero_measured_refused(self):
        with pytest.raises(W.UnmeasuredCastError):
            W.check_cast_measured(_wiki_payload(171, 0))

    def test_empty_roster_refused(self):
        with pytest.raises(W.UnmeasuredCastError):
            W.check_cast_measured(_wiki_payload(0, 0))

    def test_at_floor_refused(self):
        # 8/171 measured = 163/171 = 95.3 percent unmeasured
        with pytest.raises(W.UnmeasuredCastError):
            W.check_cast_measured(_wiki_payload(171, 8))

    def test_just_below_floor_passes(self):
        # 9/171 measured = 94.7 percent unmeasured
        out = W.check_cast_measured(_wiki_payload(171, 9))
        assert out["unmeasured_fraction"] < W.CAST_UNMEASURED_FAIL_FRACTION

    def test_live_shape_passes(self):
        out = W.check_cast_measured(_wiki_payload(171, 170))
        assert out == {"rows": 171, "measured": 170,
                       "unmeasured_fraction": round(1 / 171, 4),
                       "threshold": W.CAST_UNMEASURED_FAIL_FRACTION}

    def test_override_accepts_and_records(self, capsys):
        out = W.check_cast_measured(_wiki_payload(171, 0), override_reason="offline smoke")
        assert out["override_reason"] == "offline smoke"
        assert "WARNING" in capsys.readouterr().err

    def test_blank_override_still_refused(self):
        with pytest.raises(W.UnmeasuredCastError):
            W.check_cast_measured(_wiki_payload(171, 0), override_reason="   ")

    def test_unneeded_override_is_reported_not_recorded(self, capsys):
        out = W.check_cast_measured(_wiki_payload(171, 170), override_reason="x")
        assert "override_reason" not in out
        assert "not needed" in capsys.readouterr().err

    def test_null_cast_counts_unmeasured(self):
        # --no-default-cast leaves misses null: _with_cast_time drops with them
        doc = _wiki_payload(171, 0)
        doc["_with_cast_time"] = 0
        doc["_default_cast_fills"] = 0
        with pytest.raises(W.UnmeasuredCastError):
            W.check_cast_measured(doc)


class TestWikiStatsMainGate:
    def _run(self, monkeypatch, tmp_path, payload, *extra):
        monkeypatch.setattr(W, "extract", lambda *a, **k: payload)
        out = tmp_path / "wiki_stats.json"
        rc = W.main(["--patch", "16.99.1", "--out", str(out), *extra])
        return rc, out

    def test_unmeasured_exits_and_writes_nothing(self, monkeypatch, tmp_path, capsys):
        rc, out = self._run(monkeypatch, tmp_path, _wiki_payload(171, 0))
        assert rc == W.EXIT_CAST_UNMEASURED
        assert rc != 0
        assert not out.exists()
        assert "--allow-unmeasured-cast" in capsys.readouterr().err

    def test_exit_code_distinct_from_aram_gate(self):
        assert W.EXIT_CAST_UNMEASURED not in (0, W.EXIT_ARAM_NEUTRAL)

    def test_unmeasured_dry_run_also_exits(self, monkeypatch, tmp_path):
        rc, out = self._run(monkeypatch, tmp_path, _wiki_payload(171, 0), "--dry-run")
        assert rc == W.EXIT_CAST_UNMEASURED
        assert not out.exists()

    def test_override_writes_and_records(self, monkeypatch, tmp_path):
        rc, out = self._run(monkeypatch, tmp_path, _wiki_payload(171, 0),
                            "--allow-unmeasured-cast", "cdn outage, defaults accepted")
        assert rc == 0
        doc = json.loads(out.read_text(encoding="utf-8"))
        rec = doc["_cast_unmeasured_override"]
        assert rec["reason"] == "cdn outage, defaults accepted"
        assert rec["rows"] == 171 and rec["measured"] == 0
        assert rec["threshold"] == W.CAST_UNMEASURED_FAIL_FRACTION

    def test_live_shape_writes_without_override_key(self, monkeypatch, tmp_path):
        rc, out = self._run(monkeypatch, tmp_path, _wiki_payload(171, 170))
        assert rc == 0
        doc = json.loads(out.read_text(encoding="utf-8"))
        assert "_cast_unmeasured_override" not in doc

    def test_cast_gate_applies_to_cdragon_only_source(self, monkeypatch, tmp_path):
        # cdragon-only is exempt from the ARAM gate, not from this one
        rc, out = self._run(monkeypatch, tmp_path, _wiki_payload(171, 0),
                            "--source", "cdragon")
        assert rc == W.EXIT_CAST_UNMEASURED
        assert not out.exists()

    def test_cast_override_does_not_lift_aram_gate(self, monkeypatch, tmp_path):
        doc = _wiki_payload(171, 0)
        for rec in doc["champions"].values():
            rec[W._FIELD_MODE_MODIFIERS] = {}
        rc, out = self._run(monkeypatch, tmp_path, doc,
                            "--allow-unmeasured-cast", "offline")
        assert rc == W.EXIT_ARAM_NEUTRAL
        assert not out.exists()


def _snapshots(name: str) -> list[Path]:
    return sorted(DATA.glob(f"*/{name}"))


def test_committed_snapshots_enumerated():
    for name in ("wiki_stats.json", "cdragon_spell_stats.json", "wiki_ability_stats.json",
                 "cdragon_ability_ratios.json"):
        assert len(_snapshots(name)) >= 9, name


@pytest.mark.parametrize("path", _snapshots("wiki_stats.json"), ids=lambda p: p.parent.name)
def test_committed_wiki_stats_clear_of_floor(path):
    doc = json.loads(path.read_text(encoding="utf-8"))
    out = W.check_cast_measured(doc)
    # measured 2026-10-26: 170/171 measured in every snapshot 16.11.1 .. 16.21.1
    assert out["rows"] >= 171
    assert out["unmeasured_fraction"] < 0.1


# --------------------------------------------------------------------------
# cdragon_spell_stats + wiki_ability_stats: all-zero refusal
# --------------------------------------------------------------------------

def _cdragon_payload(zero: bool) -> dict:
    n = 0 if zero else 5
    return {"_patch_segment": "16.99", "_champ_count": 171, "_with_ammo": n,
            "_with_missile": n, "_with_cc_tags": n, "_with_geometry": n,
            "_errors": [], "champions": {}}


def _ability_payload(zero: bool) -> dict:
    n = 0 if zero else 5
    return {"_ability_count": n, "_with_static": n, "_with_recharge": n,
            "_with_cc_flags": n, "_with_leveling": n, "_missing_pages": [],
            "_errors": [], "abilities": {}}


def _ratio_payload(zero: bool) -> dict:
    return {"patch_segment": "16.99", "_champ_count": 171,
            "_n_mechanical_blocks": 0 if zero else 865, "_n_fallback_blocks": 550,
            "_errors": [], "champions": {}}


SIBLINGS = [
    pytest.param(C, _cdragon_payload, "cdragon_spell_stats.json", id="cdragon_spell"),
    pytest.param(A, _ability_payload, "wiki_ability_stats.json", id="wiki_ability"),
    pytest.param(R, _ratio_payload, "cdragon_ability_ratios.json", id="cdragon_ratio"),
]


@pytest.mark.parametrize("mod,make,name", SIBLINGS)
class TestSiblingMainGate:
    def _run(self, monkeypatch, tmp_path, mod, payload, name, *extra):
        monkeypatch.setattr(mod, "extract", lambda *a, **k: payload)
        out = tmp_path / name
        rc = mod.main(["--patch", "16.99.1", "--out", str(out), *extra])
        return rc, out

    def test_empty_exits_and_writes_nothing(self, monkeypatch, tmp_path, capsys, mod, make, name):
        rc, out = self._run(monkeypatch, tmp_path, mod, make(True), name)
        assert rc == mod.EXIT_EMPTY_SIDECAR
        assert rc != 0
        assert not out.exists()
        assert "--allow-empty" in capsys.readouterr().err

    def test_empty_dry_run_also_exits(self, monkeypatch, tmp_path, mod, make, name):
        rc, out = self._run(monkeypatch, tmp_path, mod, make(True), name, "--dry-run")
        assert rc == mod.EXIT_EMPTY_SIDECAR
        assert not out.exists()

    def test_blank_override_still_refused(self, monkeypatch, tmp_path, mod, make, name):
        rc, out = self._run(monkeypatch, tmp_path, mod, make(True), name, "--allow-empty", " ")
        assert rc == mod.EXIT_EMPTY_SIDECAR
        assert not out.exists()

    def test_override_writes_and_records(self, monkeypatch, tmp_path, mod, make, name):
        rc, out = self._run(monkeypatch, tmp_path, mod, make(True), name,
                            "--allow-empty", "source retired upstream")
        assert rc == 0
        doc = json.loads(out.read_text(encoding="utf-8"))
        assert doc["_empty_override"] == {"reason": "source retired upstream"}

    def test_live_shape_writes_without_override_key(self, monkeypatch, tmp_path, mod, make, name):
        rc, out = self._run(monkeypatch, tmp_path, mod, make(False), name)
        assert rc == 0
        doc = json.loads(out.read_text(encoding="utf-8"))
        assert "_empty_override" not in doc


def test_cdragon_one_nonzero_bucket_is_not_empty(monkeypatch, tmp_path):
    payload = _cdragon_payload(True)
    payload["_with_geometry"] = 1
    monkeypatch.setattr(C, "extract", lambda *a, **k: payload)
    out = tmp_path / "x.json"
    assert C.main(["--patch", "16.99.1", "--out", str(out)]) == 0
    assert out.exists()


@pytest.mark.parametrize("path", _snapshots("cdragon_spell_stats.json"), ids=lambda p: p.parent.name)
def test_committed_cdragon_spell_stats_not_empty(path):
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert not C.sidecar_is_empty(doc)


@pytest.mark.parametrize("path", _snapshots("wiki_ability_stats.json"), ids=lambda p: p.parent.name)
def test_committed_wiki_ability_stats_not_empty(path):
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert not A.sidecar_is_empty(doc)


def test_ratio_empty_with_drift_writes_neither_file(monkeypatch, tmp_path):
    monkeypatch.setattr(R, "extract", lambda *a, **k: _ratio_payload(True))
    monkeypatch.setattr(R, "build_drift", lambda *a, **k: pytest.fail("drift built"))
    out = tmp_path / "cdragon_ability_ratios.json"
    rc = R.main(["--patch", "16.99.1", "--out", str(out), "--drift"])
    assert rc == R.EXIT_EMPTY_SIDECAR
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("path", _snapshots("cdragon_ability_ratios.json"), ids=lambda p: p.parent.name)
def test_committed_cdragon_ability_ratios_not_empty(path):
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert not R.sidecar_is_empty(doc)
