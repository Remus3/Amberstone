"""RM-852 - an ARAM shadow row with no enemy team is not a game tick, so it
must never reach the Haiku-retire gate.

THE MEASUREMENT (2026-10-24, read-only, live ``data/aram_coach_shadow.jsonl``):
669 of 5254 rows carry ``enemy_comp == []``, all ``champ`` Kai'Sa, all
``mode`` aram. They were written by the TEST SUITE, not by games:

- ``tests/test_state_builder_cleared_at.py::...::test_live_aram_game_still_served``
  and the four ``BuildStateSuppressesLiveDirectivesTests`` live-game cases in
  ``tests/test_b4_live_directive_suppression.py`` drive ``build_state()`` with
  ``mode_key == "aram"`` and ``lc == {"champion": "Kai'Sa", "game_time": ...}``
  - no ``enemy_team`` - so ``dashboard/_state_builder.py`` called
  ``shadow_log_aram_coach`` with the default ``SHADOW_PATH`` until RM-406
  (``88625e224``) put ``core.aram_coach_shadow`` into conftest's
  ``_SHADOW_MODULES``. Re-running those tests under the redirect yields
  deterministic blocks JSON-identical to 342 of the 669 live rows; the rest are
  the same tests under older build tables / older block schemas.
- Timing: the first enemy-less row (2026-06-28T02:39:35Z) is two minutes
  BEFORE the commit that wired the writer (``bd3d87b1e``, 02:41:16Z); the first
  action-bearing ("POKE") run starts 2026-08-12T23:51:40Z, nine minutes before
  the B4-a commit that added the b4 harness (``f630aaf0a``, 00:00:16Z); the
  last row (2026-09-11T16:22:44Z) precedes RM-406 (17:52:29Z) and nothing has
  been appended since.
- In production ``lc["champion"]`` and ``lc["enemy_team"]`` come from the SAME
  ``allPlayers`` list in the same block (``dashboard/_liveclient.py`` under
  ``if me_pl:``), so a real ARAM tick with a champion always lists its enemies
  (4585 / 4585 live rows with enemies list exactly five).

THE FIX, two lines of defence:
1. ``dashboard._deterministic_coaching.shadow_log_aram_coach`` (the only
   production path to ``core.aram_coach_shadow.log_aram_coach``) refuses a tick
   with no enemy team.
2. ``tools/aram_shadow_report.py`` counts enemy-less rows on their own and
   excludes them from every gate summary, so the 669 rows already in the
   durable store are handled at READ time - never deleted.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from dashboard import _state_builder
from dashboard._deterministic_coaching import shadow_log_aram_coach
from tools import aram_shadow_report as rep

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ENEMIES = ["Ashe", "Annie", "Leona", "Malphite", "Sett"]


def _write(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n",
                    encoding="utf-8")


_MISSING = object()


def _row(det_action, live_action, enemy_comp):
    row = {
        "mode": "aram", "champ": "Kai'Sa",
        "deterministic": {"action": det_action},
        "live_haiku": {"action": live_action},
    }
    if enemy_comp is not _MISSING:
        row["enemy_comp"] = enemy_comp
    return row


# ---------------------------------------------------------------------------
# 1. Writer: the production path refuses an enemy-less tick.
# ---------------------------------------------------------------------------


def test_writer_refuses_the_leaked_shape(tmp_path):
    """The exact lc shape the leaking tests fed build_state."""
    target = tmp_path / "aram_coach_shadow.jsonl"
    shadow_log_aram_coach(
        {"champion": "Kai'Sa", "kda": "3/1/4"},
        {"champion": "Kai'Sa", "game_time": "03:10"},
        "aram", path=target, live_path=tmp_path / "absent.json",
    )
    assert not target.exists()


def test_writer_refuses_blank_and_empty_enemy_lists(tmp_path):
    for i, enemy_team in enumerate(([], [""], [None, ""], ["  "], None, "Ashe")):
        target = tmp_path / f"s{i}.jsonl"
        shadow_log_aram_coach(
            {}, {"champion": "Kai'Sa", "enemy_team": enemy_team},
            "aram", path=target, live_path=tmp_path / "absent.json",
        )
        assert not target.exists(), f"enemy_team={enemy_team!r} was logged"


def test_writer_still_logs_a_tick_with_enemies(tmp_path):
    """Positive control - without it the refusals above pass vacuously."""
    target = tmp_path / "aram_coach_shadow.jsonl"
    shadow_log_aram_coach(
        {}, {"champion": "Kai'Sa", "enemy_team": list(_ENEMIES)},
        "aram", path=target, live_path=tmp_path / "absent.json",
    )
    rows = target.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    assert json.loads(rows[0])["enemy_comp"] == _ENEMIES


class BuildStateLeakHarnessTests(unittest.TestCase):
    """The leaking harness itself (tests/test_state_builder_cleared_at.py,
    item 281), driven end to end through build_state. conftest redirects
    SHADOW_PATH to tmp, so the row would land there - and must not."""

    def _patch(self, *, lc_payload):
        health = {"mode": "client", "aram_mode": True}
        coach_payload = {"action": "TRADE", "champion": "Kai'Sa",
                         "kda": "3/1/4"}

        def _read_json(p):
            if "health" in str(p):
                return health
            return coach_payload

        for p in [
            mock.patch.object(_state_builder, "read_json", side_effect=_read_json),
            mock.patch.object(_state_builder, "lcu_summary", return_value={}),
            mock.patch.object(_state_builder, "liveclient_summary",
                              return_value=lc_payload),
            mock.patch.object(_state_builder, "get_team_context", return_value=None),
            mock.patch.object(_state_builder, "validate_coaching_payload",
                              lambda *_a, **_kw: None),
        ]:
            p.start()
            self.addCleanup(p.stop)

    def _shadow_rows(self):
        from core import aram_coach_shadow
        path = Path(aram_coach_shadow.SHADOW_PATH).resolve()
        # Hermeticity sanity: conftest must have redirected the corpus out of
        # the repo, or this test would itself be the RM-852 leak.
        self.assertNotIn(_REPO_ROOT, path.parents, f"live path in use: {path}")
        if not path.exists():
            return []
        return [json.loads(x) for x in
                path.read_text(encoding="utf-8").splitlines() if x.strip()]

    def test_enemy_less_live_aram_tick_writes_no_shadow_row(self):
        self._patch(lc_payload={"champion": "Kai'Sa", "game_time": "03:10"})
        state = _state_builder.build_state()
        self.assertEqual(state["mode_key"], "aram")
        self.assertEqual(self._shadow_rows(), [])

    def test_live_aram_tick_with_enemies_still_writes_one_row(self):
        self._patch(lc_payload={"champion": "Kai'Sa", "game_time": "03:10",
                                "enemy_team": list(_ENEMIES)})
        _state_builder.build_state()
        rows = self._shadow_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["enemy_comp"], _ENEMIES)


# ---------------------------------------------------------------------------
# 2. Report: enemy-less rows are counted apart and excluded from the gate.
# ---------------------------------------------------------------------------


def test_has_enemy_comp_definition():
    assert rep.has_enemy_comp({"enemy_comp": ["Ashe"]}) is True
    assert rep.has_enemy_comp({"enemy_comp": ["", "Ashe"]}) is True
    for bad in ([], [""], [None], ["  "], None, "Ashe", {"a": 1}, 5):
        assert rep.has_enemy_comp({"enemy_comp": bad}) is False, bad
    # A row without the key has no provenance as a game tick: fail closed.
    assert rep.has_enemy_comp({}) is False


def test_build_report_counts_and_excludes_enemy_less(tmp_path):
    p = tmp_path / "s.jsonl"
    _write(p, [
        _row("FALL BACK", "back off", _ENEMIES),
        _row("TRADE", "poke him", _ENEMIES),
        _row("ALL IN", "back off", []),
        _row("ALL IN", "fall back", []),
        _row("ALL IN", "WAIT RESPAWN", _MISSING),
    ])
    r = rep.build_report(p)
    assert r["total"] == 5
    assert r["enemy_less_excluded"] == 3
    assert r["gated"] == 2
    assert r["dead_state"] == 0
    assert r["non_dead"] == 2
    assert r["action"]["comparable"] == 2
    assert r["action"]["agree"] == 2
    assert r["action"]["agreement_rate"] == 1.0
    assert r["choices"]["non_dead_total"] == 2
    assert sum(r["field_presence"]["action"].values()) == 2


def test_enemy_less_rows_can_no_longer_carry_the_gate(tmp_path):
    """Four enemy-less agreeing rows used to lift a 50% real sample to 83%
    (gate MET). Excluded, the real sample reads below the gate."""
    p = tmp_path / "s.jsonl"
    _write(p, [
        _row("FALL BACK", "back off", _ENEMIES),
        _row("ALL IN", "back off", _ENEMIES),
    ] + [_row("TRADE", "poke", []) for _ in range(4)])
    r = rep.build_report(p)
    assert r["action"]["comparable"] == 2
    assert r["action"]["agreement_rate"] == 0.5
    assert "below 70% gate" in r["flip_ready_hint"]
    assert "gate MET" not in r["flip_ready_hint"]


def test_only_enemy_less_rows_is_not_shadow_data(tmp_path):
    p = tmp_path / "s.jsonl"
    _write(p, [_row("TRADE", "poke", []) for _ in range(3)])
    r = rep.build_report(p)
    assert r["gated"] == 0
    assert r["enemy_less_excluded"] == 3
    assert r["action"]["comparable"] == 0
    assert "gate MET" not in r["flip_ready_hint"]
    assert "3 enemy-less" in r["flip_ready_hint"]


def test_human_output_shows_both_numbers(tmp_path, capsys):
    p = tmp_path / "s.jsonl"
    _write(p, [
        _row("FALL BACK", "back off", _ENEMIES),
        _row("TRADE", "poke", []),
    ])
    assert rep.main(["--path", str(p)]) == 0
    out = capsys.readouterr().out
    assert "total 2" in out
    assert "enemy_less_excluded 1" in out
    assert "gated 1" in out
