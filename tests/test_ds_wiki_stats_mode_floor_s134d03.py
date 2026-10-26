"""RM-911: a non-ARAM wiki mode block absent on every champion must fail loudly.

``tools/daemon_slayer_wiki_stats_extract.py`` parses ``mode_modifiers`` for the
wiki modes aram / urf / nb / ofa / usb / ar / swift. ARAM has its own neutral
floor (RM-807 (e)); the other six had none, so a wiki rename of one mode's
block key wrote ``{}`` for that mode on every champion and the sidecar was
written anyway. ``agents/daemon_slayer/data_loader.py`` ``_WIKI_MODE_ALIASES``
routes ARENA / CHERRY to ``ar`` and Swiftplay to ``swift``, which the RM-172
apply_mode_modifiers seam reads.

Measured 2026-10-26 over every committed snapshot 16.11.1 .. 16.21.1 (171
rows each): ar 45, nb 32, ofa 81, swift 13, urf 100-101, usb 44. No mode has
ever been absent, and the per-mode counts are stable, so the floor is a
PRESENCE floor: a gated mode with zero blocks on the whole roster exits
``EXIT_MODE_MISSING`` and writes nothing, dry-run included. A partial drop is
left alone (a balance patch can legitimately remove blocks). The only way
past it is ``--allow-missing-mode MODE=REASON`` (repeatable), recorded in the
payload as ``_mode_missing_override``. cdragon-only runs never parse mode
blocks, so they are not gated, the same as the ARAM gate.

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

GATED = ("urf", "nb", "ofa", "usb", "ar", "swift")
LIVE_MODES = {
    "aram": {"dmg_dealt": 1.05},
    "urf": {"dmg_dealt": 1.1},
    "nb": {"dmg_taken": 0.95},
    "ofa": {"dmg_dealt": 0.9},
    "usb": {"dmg_taken": 1.05},
    "ar": {"hp_lvl": 17.0},
    "swift": {"arm_lvl": -0.5},
}


def _champions(rows: int = 171, drop: tuple[str, ...] = ()) -> dict[str, dict]:
    modes = {m: dict(b) for m, b in LIVE_MODES.items() if m not in drop}
    return {f"Champ{i:03d}": {"wiki_name": f"Champ{i:03d}",
                              W._FIELD_MODE_MODIFIERS: {m: dict(b) for m, b in modes.items()}}
            for i in range(rows)}


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


class TestCheckModePresence:
    def test_gated_set_is_every_mode_but_aram(self):
        assert set(W.GATED_MODE_KEYS) == set(GATED)
        assert set(W.GATED_MODE_KEYS) | {"aram"} == set(W._MODE_KEYS)

    def test_live_shape_passes_with_counts(self):
        out = W.check_mode_presence(_champions())
        assert out["rows"] == 171
        assert out["counts"] == {m: 171 for m in W.GATED_MODE_KEYS}
        assert out["missing"] == []
        assert "overrides" not in out

    @pytest.mark.parametrize("mode", GATED)
    def test_each_mode_absent_everywhere_refused(self, mode):
        with pytest.raises(W.MissingModeBlockError, match=rf"\b{mode}\b"):
            W.check_mode_presence(_champions(drop=(mode,)))

    def test_single_block_keeps_mode_present(self):
        champs = _champions(drop=("swift",))
        champs["Champ000"][W._FIELD_MODE_MODIFIERS]["swift"] = {"arm_lvl": -0.5}
        out = W.check_mode_presence(champs)
        assert out["counts"]["swift"] == 1
        assert out["missing"] == []

    def test_aram_absence_is_not_this_gate(self):
        # ARAM is RM-807 (e)'s neutral floor, not a presence floor
        out = W.check_mode_presence(_champions(drop=("aram",)))
        assert out["missing"] == []

    def test_empty_block_counts_absent(self):
        champs = _champions(drop=("ar",))
        for rec in champs.values():
            rec[W._FIELD_MODE_MODIFIERS]["ar"] = {}
        with pytest.raises(W.MissingModeBlockError, match="ar"):
            W.check_mode_presence(champs)

    def test_empty_roster_refused(self):
        with pytest.raises(W.MissingModeBlockError, match="empty"):
            W.check_mode_presence({})

    def test_odd_records_without_crash(self):
        champs = {"A": None, "B": "x", "C": {W._FIELD_MODE_MODIFIERS: [1]},
                  "D": {W._FIELD_MODE_MODIFIERS: {"ar": [1.0]}}}
        with pytest.raises(W.MissingModeBlockError):
            W.check_mode_presence(champs)

    def test_several_missing_named_together(self):
        with pytest.raises(W.MissingModeBlockError) as exc:
            W.check_mode_presence(_champions(drop=("ar", "nb")))
        assert "ar" in str(exc.value) and "nb" in str(exc.value)
        assert "--allow-missing-mode" in str(exc.value)

    def test_override_accepts_and_records(self, capsys):
        out = W.check_mode_presence(_champions(drop=("nb",)),
                                    overrides={"nb": "Nexus Blitz retired"})
        assert out["missing"] == ["nb"]
        assert out["overrides"] == {"nb": "Nexus Blitz retired"}
        assert "RM-911 override" in capsys.readouterr().err

    def test_override_for_one_mode_does_not_lift_another(self):
        with pytest.raises(W.MissingModeBlockError) as exc:
            W.check_mode_presence(_champions(drop=("ar", "nb")),
                                  overrides={"nb": "retired"})
        assert exc.value.missing == ["ar"]

    def test_blank_override_still_refused(self):
        with pytest.raises(W.MissingModeBlockError):
            W.check_mode_presence(_champions(drop=("ar",)), overrides={"ar": "   "})

    def test_unneeded_override_is_reported_not_recorded(self, capsys):
        out = W.check_mode_presence(_champions(), overrides={"ar": "spare"})
        assert "overrides" not in out
        assert "not needed" in capsys.readouterr().err


class TestParseOverrides:
    def test_mode_equals_reason(self):
        assert W._parse_mode_overrides(["ar=arena off-season", "nb=retired"]) == {
            "ar": "arena off-season", "nb": "retired"}

    def test_none_is_empty(self):
        assert W._parse_mode_overrides(None) == {}

    @pytest.mark.parametrize("bad", ["ar", "=reason", "aram=x", "bogus=x"])
    def test_malformed_or_ungated_rejected(self, bad):
        with pytest.raises(ValueError):
            W._parse_mode_overrides([bad])


class TestMainGate:
    def _run(self, monkeypatch, tmp_path, champions, *extra):
        monkeypatch.setattr(W, "extract", lambda *a, **k: _payload(champions))
        out = tmp_path / "wiki_stats.json"
        rc = W.main(["--patch", "16.99.1", "--out", str(out), *extra])
        return rc, out

    def test_exit_code_distinct(self):
        assert W.EXIT_MODE_MISSING not in (0, W.EXIT_ARAM_NEUTRAL, W.EXIT_CAST_UNMEASURED)

    def test_missing_mode_exits_and_writes_nothing(self, monkeypatch, tmp_path, capsys):
        rc, out = self._run(monkeypatch, tmp_path, _champions(drop=("ar",)))
        assert rc == W.EXIT_MODE_MISSING
        assert not out.exists()
        assert "--allow-missing-mode" in capsys.readouterr().err

    def test_missing_mode_dry_run_also_exits(self, monkeypatch, tmp_path):
        rc, out = self._run(monkeypatch, tmp_path, _champions(drop=("swift",)), "--dry-run")
        assert rc == W.EXIT_MODE_MISSING
        assert not out.exists()

    def test_override_writes_and_records(self, monkeypatch, tmp_path):
        rc, out = self._run(monkeypatch, tmp_path, _champions(drop=("nb", "usb")),
                            "--allow-missing-mode", "nb=retired upstream",
                            "--allow-missing-mode", "usb=event over")
        assert rc == 0
        doc = json.loads(out.read_text(encoding="utf-8"))
        rec = doc["_mode_missing_override"]
        assert rec["reasons"] == {"nb": "retired upstream", "usb": "event over"}
        assert rec["rows"] == 171
        assert rec["counts"]["nb"] == 0 and rec["counts"]["usb"] == 0

    def test_live_shape_writes_without_override_key(self, monkeypatch, tmp_path):
        rc, out = self._run(monkeypatch, tmp_path, _champions())
        assert rc == 0
        doc = json.loads(out.read_text(encoding="utf-8"))
        assert "_mode_missing_override" not in doc

    def test_bad_override_is_a_usage_error(self, monkeypatch, tmp_path):
        with pytest.raises(SystemExit) as exc:
            self._run(monkeypatch, tmp_path, _champions(), "--allow-missing-mode", "aram=x")
        assert exc.value.code == 2

    def test_cdragon_only_source_is_not_gated(self, monkeypatch, tmp_path):
        rc, out = self._run(monkeypatch, tmp_path, _champions(drop=GATED),
                            "--source", "cdragon")
        assert rc == 0
        assert out.exists()

    def test_limit_slice_skips_presence_with_note(self, monkeypatch, tmp_path, capsys):
        # the documented smoke run (--limit 5: Aatrox .. Alistar) carries no
        # swift block at 16.21.1; presence is a roster-wide fact
        rc, out = self._run(monkeypatch, tmp_path, _champions(5, drop=("swift",)),
                            "--limit", "5")
        assert rc == 0
        doc = json.loads(out.read_text(encoding="utf-8"))
        assert "_mode_missing_override" not in doc
        assert "presence floor skipped" in capsys.readouterr().err

    def test_limit_does_not_lift_aram_gate(self, monkeypatch, tmp_path):
        rc, out = self._run(monkeypatch, tmp_path, _champions(5, drop=("aram",)),
                            "--limit", "5")
        assert rc == W.EXIT_ARAM_NEUTRAL
        assert not out.exists()

    def test_aram_gate_still_runs_first(self, monkeypatch, tmp_path):
        champs = _champions(drop=("aram", "ar"))
        rc, out = self._run(monkeypatch, tmp_path, champs)
        assert rc == W.EXIT_ARAM_NEUTRAL
        assert not out.exists()


def _committed_snapshots() -> list[Path]:
    return sorted((ROOT / "data" / "daemon_slayer").glob("*/wiki_stats.json"))


def test_committed_snapshots_enumerated():
    assert len(_committed_snapshots()) >= 9


@pytest.mark.parametrize("path", _committed_snapshots(), ids=lambda p: p.parent.name)
def test_committed_snapshot_has_every_gated_mode(path):
    doc = json.loads(path.read_text(encoding="utf-8"))
    out = W.check_mode_presence(doc["champions"])
    # measured 2026-10-26: the smallest gated mode is swift at 13/171
    assert out["rows"] >= 171
    assert min(out["counts"].values()) >= 10
