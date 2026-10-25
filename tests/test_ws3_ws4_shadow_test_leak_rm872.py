"""RM-872 - the WS3 objective-playbook and WS4 macro-response shadow logs
refuse rows only a test can write, and their flip-readiness reports exclude
the ones already in the durable store.

THE MEASUREMENT (2026-10-25, read-only, the live files in the main checkout):
``data/objective_playbook_shadow.jsonl`` holds 3314 of 49788 rows, and
``data/macro_response_shadow.jsonl`` 3312 of 48890, that no game wrote. Every
one has ``game_time_s`` null or the champion ``Champ0``; no other row has
either. They are suite leakage through ``dashboard/_state_builder.py``, which
called both writers with the default ``SHADOW_PATH`` until RM-406
(``88625e224``, 2026-09-11T17:52:29Z) put the two modules into conftest's
``_SHADOW_MODULES``:

- ``tests/test_state_builder_archetype_pick.py`` (2 tests, Caitlyn, sr),
  ``tests/test_state_builder_archetype_nudge.py`` (4 tests, Nasus, client) and
  ``tests/test_state_builder_latency_rc2.py`` (2 tests, Ahri and Caitlyn,
  client) hand ``build_state()`` a liveclient summary with a champion and no
  game clock. Re-run under the redirect with a capture plugin, they write
  records JSON-identical (minus ts / engine_version) to all 2404 / 2402
  non-Champ0 leaked rows.
- ``tests/test_state_cooldowns.py`` (deleted in ``18b62300f``,
  2026-08-12T02:05:25Z) used ``{"champion": "Champ0", "game_time_s": 60}`` and
  ``{"champion": "Champ0"}``. Its harness, re-run on HEAD minus the removed
  cooldown module, reproduces 907 of the 910 Champ0 rows per file; the last
  3 differ only in an older lead_state.
- Timing: the first rows are minutes after (or, for the macro writer and the
  latency test, minutes before the commit of) ``dbdd235e1`` / ``73aeda551`` /
  ``33c9b16d9`` on 2026-06-20; the last Champ0 row (2026-08-09) precedes the
  deletion, and the last row of all (2026-09-11T16:23:13Z) precedes RM-406.

A REAL tick never carries either signature: the only production liveclient
source, ``dashboard/_liveclient.py`` ``liveclient_summary``, stamps
``game_time_s`` (an int, 0 at load) before it can stamp ``champion`` and
returns ``{}`` on any failure, and the dashboard callers gate on that
champion. No League champion is named ``Champ<digits>``.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

import core.macro_response_shadow as mrs
import core.objective_playbook_shadow as ops
from dashboard import _deterministic_coaching as dc
from dashboard import _state_builder
from tools import macro_response_shadow_report as mrep
from tools import objective_playbook_shadow_report as orep

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PLAY = {"tag": "playbook_dragon", "line": "Drake: match prio, ward both pits",
         "eta_s": 20.0, "kind": "playbook"}
_MACRO = {"tag": "macro_stagnation", "line": "Stalled - take a side lane",
          "eta_s": None, "kind": "macro_response"}

# (writer, the kwarg that carries its deterministic row)
_WRITERS = [
    pytest.param(ops, ops.log_objective_playbook, "playbook", _PLAY, id="ws3"),
    pytest.param(mrs, mrs.log_macro_response, "macro", _MACRO, id="ws4"),
]


@pytest.fixture(autouse=True)
def _fresh_writer_state():
    for mod in (ops, mrs):
        mod._LAST_SIG.clear()
        mod._LAST_GT.clear()
    dc._reset_caches_for_tests()
    yield
    for mod in (ops, mrs):
        mod._LAST_SIG.clear()
        mod._LAST_GT.clear()
    dc._reset_caches_for_tests()


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()
            if x.strip()]


# ---------------------------------------------------------------------------
# 1. The writers refuse the two leaked shapes and keep every real one.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("mod", "fn", "kw", "row"), _WRITERS)
def test_writer_refuses_a_row_with_no_game_clock(tmp_path, mod, fn, kw, row):
    """The archetype / latency harness shape: a champion, no game time."""
    p = tmp_path / "s.jsonl"
    out = fn("client", "Nasus", **{kw: row}, lead_state="even", phase="early",
             game_time_s=None, path=p)
    assert out is None
    assert not p.exists()


@pytest.mark.parametrize(("mod", "fn", "kw", "row"), _WRITERS)
def test_writer_refuses_the_placeholder_champion(tmp_path, mod, fn, kw, row):
    """The deleted test_state_cooldowns shape: Champ0 WITH a game clock."""
    p = tmp_path / "s.jsonl"
    out = fn("client", "Champ0", **{kw: row}, lead_state="behind",
             phase="early", game_time_s=60, path=p)
    assert out is None
    assert not p.exists()


@pytest.mark.parametrize(("mod", "fn", "kw", "row"), _WRITERS)
def test_writer_keeps_a_real_tick_at_game_time_zero(tmp_path, mod, fn, kw, row):
    """Control: 0 is a real game clock (load screen), never a missing one."""
    p = tmp_path / "s.jsonl"
    out = fn("sr", "Caitlyn", **{kw: row}, native_objective="ward river",
             lead_state="even", phase="early", game_time_s=0, path=p)
    assert out is not None
    assert [r["game_time_s"] for r in _rows(p)] == [0]


@pytest.mark.parametrize(("mod", "fn", "kw", "row"), _WRITERS)
def test_writer_keeps_real_champion_names_near_the_placeholder(
        tmp_path, mod, fn, kw, row):
    """Control: only Champ<digits> is a placeholder."""
    p = tmp_path / "s.jsonl"
    for i, name in enumerate(("Champ", "Champion", "Champ0x", "Kai'Sa")):
        assert fn("sr", name, **{kw: row}, game_time_s=100.0 + 10 * i,
                  path=p) is not None
    assert len(_rows(p)) == 4


@pytest.mark.parametrize(("mod", "fn", "kw", "row"), _WRITERS)
def test_refused_row_records_no_dedup_signature(tmp_path, mod, fn, kw, row):
    """A refused row must not suppress the next real row in its 5 s bucket
    (None buckets as 0, the same bucket as game_time_s 1)."""
    p = tmp_path / "s.jsonl"
    assert fn("sr", "Caitlyn", **{kw: row}, lead_state="even",
              game_time_s=None, path=p) is None
    assert fn("sr", "Caitlyn", **{kw: row}, lead_state="even",
              game_time_s=1, path=p) is not None
    assert [r["game_time_s"] for r in _rows(p)] == [1]


def test_no_real_champion_matches_the_placeholder():
    """Every tracked champion profile name passes the predicate."""
    names = [p.stem for p in (_REPO_ROOT / "data" / "champion_profiles").glob("*.json")]
    assert len(names) > 150  # the roster is really there
    for mod in (ops, mrs):
        assert [n for n in names if mod.is_test_signature(n, 300)] == []


def test_both_writers_share_one_predicate():
    cases = [("Champ0", 60), ("Champ12", 1.5), ("Caitlyn", None), ("Champ0", None),
             ("Caitlyn", 0), ("Caitlyn", 1300.0), ("Champion", 5), ("", 5)]
    for champ, gt in cases:
        assert ops.is_test_signature(champ, gt) == mrs.is_test_signature(champ, gt)
        assert orep.is_test_leak_row({"my_champion": champ, "game_time_s": gt}) \
            == ops.is_test_signature(champ, gt)
        assert mrep.is_test_leak_row({"my_champion": champ, "game_time_s": gt}) \
            == ops.is_test_signature(champ, gt)


# ---------------------------------------------------------------------------
# 2. The production path: build_state with the leaking harness shape writes
#    nothing; with a real clock it writes (so the absence is meaningful).
# ---------------------------------------------------------------------------


class _FakeSnap:
    def __init__(self, data, age_s: float = 0.0):
        self.data = data
        self.ts = 0.0
        self.fetched_at = 0.0
        self.no_game = False
        self._age = age_s

    @property
    def age_s(self) -> float:
        return self._age


def _build_state(lc: dict) -> dict:
    """The tests/test_state_builder_archetype_nudge.py harness shape."""
    health = {"alive": True, "pid": 1, "mode": "client", "ui_pulse_age_s": 0}
    with (
        mock.patch.object(_state_builder, "read_json",
                          side_effect=lambda p: health
                          if p == "ops/runtime/health.json" else {}),
        mock.patch.object(_state_builder, "lcu_summary", return_value={}),
        mock.patch.object(_state_builder, "liveclient_summary", return_value=lc),
        mock.patch.object(_state_builder, "get_team_context", return_value=None),
        mock.patch.object(_state_builder, "validate_coaching_payload",
                          lambda *_a, **_k: None),
        mock.patch("core.archetype_picks.get_archetype_for", return_value={}),
        mock.patch("core.archetype_mismatch.compute_nudge_payload",
                   return_value={}),
        mock.patch("core.liveclient_cache.get", return_value=_FakeSnap(None)),
    ):
        return _state_builder.build_state()


def test_conftest_redirect_covers_both_writers(tmp_path):
    """The RM-406 redirect is what stopped the leak; pin it for these two."""
    from tests import conftest as cf
    for mod in (ops, mrs):
        assert mod.__name__ in cf._SHADOW_MODULES
        assert tmp_path in Path(mod.SHADOW_PATH).parents
        assert (_REPO_ROOT / "data") not in Path(mod.SHADOW_PATH).parents


@pytest.mark.parametrize("lc", [
    pytest.param({"champion": "Nasus"}, id="no-clock"),
    pytest.param({"champion": "Champ0", "game_time_s": 60}, id="champ0"),
    pytest.param({"champion": "Champ0"}, id="champ0-no-clock"),
])
def test_build_state_leak_shapes_write_nothing(lc):
    _build_state(lc)
    assert _rows(Path(ops.SHADOW_PATH)) == []
    assert _rows(Path(mrs.SHADOW_PATH)) == []


def test_build_state_real_clock_still_writes():
    """Control: the same harness with a game clock reaches both writers."""
    _build_state({"champion": "Nasus", "game_time_s": 300})
    for mod in (ops, mrs):
        rows = _rows(Path(mod.SHADOW_PATH))
        assert [(r["my_champion"], r["game_time_s"]) for r in rows] == [("Nasus", 300)]


# ---------------------------------------------------------------------------
# 3. A real liveclient tick always carries a game clock, so it is never
#    refused - even when the frame has no gameTime at all.
# ---------------------------------------------------------------------------


def _allgamedata(game_data: dict) -> dict:
    me = {"summonerName": "Me", "championName": "Caitlyn", "team": "ORDER",
          "items": [], "scores": {"kills": 0, "deaths": 0, "assists": 0,
                                  "creepScore": 0}, "level": 1}
    foe = dict(me, summonerName="Foe", championName="Ezreal", team="CHAOS")
    return {"activePlayer": {"summonerName": "Me", "level": 1,
                             "championStats": {}},
            "allPlayers": [me, foe], "gameData": game_data,
            "events": {"Events": []}}


@pytest.mark.parametrize("game_data", [
    pytest.param({"gameTime": 312.4, "gameMode": "CLASSIC"}, id="clock"),
    pytest.param({"gameMode": "CLASSIC"}, id="no-gameTime-key"),
    pytest.param({}, id="empty-gameData"),
])
def test_real_liveclient_tick_carries_a_clock_and_is_logged(tmp_path, game_data):
    from dashboard._liveclient import liveclient_summary
    with mock.patch("core.liveclient_cache.get",
                    return_value=_FakeSnap(_allgamedata(game_data))):
        lc = liveclient_summary()
    assert lc.get("champion") == "Caitlyn"
    assert isinstance(lc.get("game_time_s"), int)
    det = {"callouts": [_PLAY, _MACRO], "lead_projection": {"state": "even"}}
    p_ob, p_mr = tmp_path / "ob.jsonl", tmp_path / "mr.jsonl"
    dc.shadow_log_objective_playbook({}, lc, det, "sr", path=p_ob)
    dc.shadow_log_macro_response({}, lc, det, "sr", path=p_mr)
    assert [r["my_champion"] for r in _rows(p_ob)] == ["Caitlyn"]
    assert [r["my_champion"] for r in _rows(p_mr)] == ["Caitlyn"]


# ---------------------------------------------------------------------------
# 4. The reports exclude the leaked rows already in the store, at READ time.
# ---------------------------------------------------------------------------


def _ob_row(champ, gt, native="Take drake now"):
    return {"ts": "2026-08-01T00:00:00+00:00", "mode": "sr",
            "my_champion": champ, "game_time_s": gt, "phase": "mid",
            "lead_state": "even", "playbook_tag": "playbook_dragon",
            "playbook_line": "Drake: group and take it",
            "native_objective": native, "engine_version": "1.270.0"}


def _mr_row(champ, gt, native="Rotate and force a pick"):
    return {"ts": "2026-08-01T00:00:00+00:00", "mode": "sr",
            "my_champion": champ, "game_time_s": gt, "phase": "mid",
            "lead_state": "even", "macro_tag": "macro_stagnation",
            "macro_line": "Stalled - force vision and a pick",
            "native_objective": native, "engine_version": "1.270.0"}


def _write(path: Path, rows) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


@pytest.mark.parametrize(("rep", "mk"), [
    pytest.param(orep, _ob_row, id="ws3"),
    pytest.param(mrep, _mr_row, id="ws4"),
])
def test_report_excludes_leaked_rows_from_every_block(tmp_path, rep, mk):
    real = [mk("Caitlyn", 600.0 + i) for i in range(3)]
    # Leaked rows that WOULD count as both-present (a native objective): the
    # exclusion must not lean on the leaked rows' usual null native prose.
    leaked = [mk("Nasus", None), mk("Champ0", 60), mk("Champ0", None),
              {k: v for k, v in mk("Ahri", 1.0).items() if k != "game_time_s"}]
    rpt = rep.build_report(_write(tmp_path / "s.jsonl", real + leaked))
    cov = rpt["coverage"]
    assert cov["total"] == 3
    assert cov["both_present"] == 3
    assert cov["test_leak_excluded"] == 4
    assert rpt["alignment"]["both_present"] == 3
    assert set(cov["by_champion_both_top15"]) == {"Caitlyn"}
    assert sum(p["n"] for p in rpt["confusion"]["pairs"]) == 3


@pytest.mark.parametrize(("rep", "mk"), [
    pytest.param(orep, _ob_row, id="ws3"),
    pytest.param(mrep, _mr_row, id="ws4"),
])
def test_report_keeps_real_rows_including_game_time_zero(tmp_path, rep, mk):
    rows = [mk("Caitlyn", 0), mk("Kai'Sa", 1300.0)]
    rpt = rep.build_report(_write(tmp_path / "s.jsonl", rows))
    assert rpt["coverage"]["total"] == 2
    assert rpt["coverage"]["test_leak_excluded"] == 0


@pytest.mark.parametrize(("rep", "mk"), [
    pytest.param(orep, _ob_row, id="ws3"),
    pytest.param(mrep, _mr_row, id="ws4"),
])
def test_report_human_output_names_the_exclusion(tmp_path, rep, mk, capsys):
    p = _write(tmp_path / "s.jsonl", [mk("Caitlyn", 600.0), mk("Champ0", 60)])
    assert rep.main(["--path", str(p)]) == 0
    assert "test_leak_excluded=1" in capsys.readouterr().out
