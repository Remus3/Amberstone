"""RM-916: three main() hardening items on the wiki_stats extractor gates.

``tools/daemon_slayer_wiki_stats_extract.py`` ``main()`` runs three floors in a
fixed order: cast (RM-912, exit 4), ARAM (RM-807 (e), exit 3), mode presence
(RM-911, exit 5). The RM-911 verifier left three notes:

(a) nothing pinned the cast gate running BEFORE the mode gate, so a reorder
    would report a host edge block as a renamed mode block;
(b) under ``--limit`` the presence floor is skipped, and an
    ``--allow-missing-mode`` passed with it was dropped without a word;
(c) a ``--limit`` at or above the resolved roster size is not a slice at all,
    yet it still skipped the presence floor, so ``--limit 999`` was a silent
    way past the gate.

Every test is synthetic: ``extract`` and the roster resolver are stubbed, and
the only write goes to tmp_path.
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

LIVE_MODES = {
    "aram": {"dmg_dealt": 1.05},
    "urf": {"dmg_dealt": 1.1},
    "nb": {"dmg_taken": 0.95},
    "ofa": {"dmg_dealt": 0.9},
    "usb": {"dmg_taken": 1.05},
    "ar": {"hp_lvl": 17.0},
    "swift": {"arm_lvl": -0.5},
}
ROSTER = 171


def _champions(rows: int = ROSTER, drop: tuple[str, ...] = ()) -> dict[str, dict]:
    modes = {m: b for m, b in LIVE_MODES.items() if m not in drop}
    return {f"Champ{i:03d}": {"wiki_name": f"Champ{i:03d}",
                              W._FIELD_MODE_MODIFIERS: {m: dict(b) for m, b in modes.items()}}
            for i in range(rows)}


def _payload(champions: dict[str, dict], measured: bool = True) -> dict:
    n = len(champions)
    return {
        "_champ_count": n,
        "_with_cast_time": n,
        "_with_cast_measured": n if measured else 0,
        "_offset_cast_fills": 0,
        "_default_cast_fills": 0 if measured else n,
        "_with_missile_speed": 0,
        "_cdragon_cast_fills": 0,
        "_errors": [],
        "champions": champions,
    }


def _run(monkeypatch, tmp_path, payload, *extra, roster: int = ROSTER):
    monkeypatch.setattr(W, "extract", lambda *a, **k: payload)
    monkeypatch.setattr(W, "_resolve_champion_ids",
                        lambda patch, full_roster: [f"Champ{i:03d}" for i in range(roster)])
    out = tmp_path / "wiki_stats.json"
    rc = W.main(["--patch", "16.99.1", "--out", str(out), *extra])
    return rc, out


class TestGateOrder:
    def test_cast_gate_runs_before_mode_gate(self, monkeypatch, tmp_path, capsys):
        # (a) unmeasured AND missing ar: the edge block is the root cause, so
        # the cast floor must be the one that answers
        payload = _payload(_champions(drop=("ar",)), measured=False)
        rc, out = _run(monkeypatch, tmp_path, payload)
        assert rc == W.EXIT_CAST_UNMEASURED
        assert not out.exists()
        err = capsys.readouterr().err
        assert "RM-912" in err
        assert "RM-911" not in err

    def test_cast_override_then_mode_gate_answers(self, monkeypatch, tmp_path):
        # once the cast floor is overridden, the mode floor still stops the run
        payload = _payload(_champions(drop=("ar",)), measured=False)
        rc, out = _run(monkeypatch, tmp_path, payload,
                       "--allow-unmeasured-cast", "edge block adjudicated")
        assert rc == W.EXIT_MODE_MISSING
        assert not out.exists()


class TestLimitOverrideNotice:
    def test_override_under_slice_is_reported_ignored(self, monkeypatch, tmp_path, capsys):
        # (b) the reason given must not vanish silently
        rc, out = _run(monkeypatch, tmp_path, _payload(_champions(5, drop=("swift",))),
                       "--limit", "5", "--allow-missing-mode", "swift=smoke")
        assert rc == 0
        err = capsys.readouterr().err
        assert "presence floor skipped" in err
        assert "--allow-missing-mode" in err and "ignored" in err
        doc = json.loads(out.read_text(encoding="utf-8"))
        assert "_mode_missing_override" not in doc

    def test_no_override_no_ignored_notice(self, monkeypatch, tmp_path, capsys):
        rc, _ = _run(monkeypatch, tmp_path, _payload(_champions(5, drop=("swift",))),
                     "--limit", "5")
        assert rc == 0
        assert "ignored" not in capsys.readouterr().err


class TestLimitCoveringRoster:
    @pytest.mark.parametrize("limit", [ROSTER, ROSTER + 1, 999])
    def test_limit_at_or_above_roster_is_gated(self, monkeypatch, tmp_path, capsys, limit):
        # (c) ids[:limit] is the whole roster, so presence is measurable
        rc, out = _run(monkeypatch, tmp_path, _payload(_champions(drop=("ar",))),
                       "--limit", str(limit))
        assert rc == W.EXIT_MODE_MISSING
        assert not out.exists()
        assert "presence floor skipped" not in capsys.readouterr().err

    def test_limit_covering_roster_honours_override(self, monkeypatch, tmp_path):
        rc, out = _run(monkeypatch, tmp_path, _payload(_champions(drop=("nb",))),
                       "--limit", "999", "--allow-missing-mode", "nb=retired")
        assert rc == 0
        doc = json.loads(out.read_text(encoding="utf-8"))
        assert doc["_mode_missing_override"]["reasons"] == {"nb": "retired"}

    def test_limit_below_roster_still_a_slice(self, monkeypatch, tmp_path, capsys):
        rc, out = _run(monkeypatch, tmp_path,
                       _payload(_champions(ROSTER - 1, drop=("swift",))),
                       "--limit", str(ROSTER - 1))
        assert rc == 0
        assert out.exists()
        assert "presence floor skipped" in capsys.readouterr().err

    def test_full_roster_flag_reaches_resolver(self, monkeypatch, tmp_path):
        seen = []
        monkeypatch.setattr(W, "extract", lambda *a, **k: _payload(_champions(173, drop=("ar",))))

        def _resolver(patch, full_roster):
            seen.append(full_roster)
            return [f"Champ{i:03d}" for i in range(173 if full_roster else ROSTER)]

        monkeypatch.setattr(W, "_resolve_champion_ids", _resolver)
        out = tmp_path / "wiki_stats.json"
        rc = W.main(["--patch", "16.99.1", "--out", str(out),
                     "--full-roster", "--limit", "172"])
        # 172 < 173: a slice of the full roster, not the whole of it
        assert rc == 0
        assert seen == [True]

    def test_no_limit_never_resolves_roster_in_main(self, monkeypatch, tmp_path):
        calls = []
        monkeypatch.setattr(W, "extract", lambda *a, **k: _payload(_champions()))
        monkeypatch.setattr(W, "_resolve_champion_ids",
                            lambda patch, full_roster: calls.append(1) or [])
        rc = W.main(["--patch", "16.99.1", "--out", str(tmp_path / "w.json")])
        assert rc == 0
        assert calls == []
