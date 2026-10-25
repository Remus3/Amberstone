"""RM-859 - archive-split helper for test-leaked shadow rows.

RM-852 (35b2524f3) attributed 669 enemy-less Kai'Sa rows in the live
``data/aram_coach_shadow.jsonl`` to build_state test harnesses and excluded
them at READ time only. RM-859 moves them out of the live file under the
data-fix doctrine (the RM-867 / RM-872 shape): byte-exact into a gitignored
archive, the kept rows atomically replacing the live file, nothing deleted.
The leaked rows are INTERLEAVED with real ones (21 runs), so unlike RM-872's
tail split the original is reproduced by re-interleaving at recorded
positions, not by concatenation.

Every test here works in tmp_path only. The helper has no default live path
(``--live`` / ``--archive`` are required), and the game probe is injected, so
no test can touch the live tree or the network.
"""
from __future__ import annotations

import hashlib
import json
import os

import pytest

from tools import aram_shadow_report as rep
from tools import shadow_archive_split as sas

_ENEMIES = ["Ashe", "Annie", "Leona", "Malphite", "Sett"]


def _row(i, enemies, action="POKE", live="trade"):
    return {
        "ts": f"2026-07-01T00:00:{i:02d}.000000+00:00",
        "mode": "aram", "champ": "Kai'Sa" if not enemies else "Ezreal",
        "enemy_comp": list(enemies),
        "deterministic": {"action": action, "choices": []},
        "live_haiku": {"action": live},
    }


def _line(rec, eol=b"\r\n"):
    return json.dumps(rec).encode("utf-8") + eol


# Leak at the head, a run in the middle, and the tail: the live shape (21
# interleaved runs, first row and last row both leaked).
_LEAK_AT = {0, 2, 3, 6, 9}


def _corpus(n=10, eol=b"\r\n"):
    lines = [_line(_row(i, [] if i in _LEAK_AT else _ENEMIES), eol)
             for i in range(n)]
    return lines


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _idle():
    return False


@pytest.fixture
def live(tmp_path):
    p = tmp_path / "data" / "aram_coach_shadow.jsonl"
    p.parent.mkdir()
    p.write_bytes(b"".join(_corpus()))
    return p


@pytest.fixture
def archive(live):
    return live.parent / "aram_coach_rm859_test_leak_2026-07_2026-07_shadow.jsonl"


def _leftovers(d):
    return sorted(x.name for x in d.iterdir() if x.name.endswith(".tmp"))


# ---------------------------------------------------------------------------
# 1. Order preservation, byte-exactness, reproducibility.
# ---------------------------------------------------------------------------


def test_split_preserves_order_and_bytes(live, archive):
    original = live.read_bytes()
    lines = _corpus()
    out = sas.archive_split(live, archive, game_live=_idle)
    kept = [ln for i, ln in enumerate(lines) if i not in _LEAK_AT]
    leaked = [ln for i, ln in enumerate(lines) if i in _LEAK_AT]
    assert live.read_bytes() == b"".join(kept)
    assert archive.read_bytes() == b"".join(leaked)
    assert out["sha256_before"] == _sha(original)
    assert out["rows_before"] == 10
    assert (out["rows_kept"], out["rows_archived"]) == (5, 5)
    assert out["archived_positions"] == sorted(_LEAK_AT)
    assert out["archived_runs"] == [[0, 1], [2, 2], [6, 1], [9, 1]]
    assert out["verified"] is True


def test_reinterleave_reproduces_original_sha(live, archive):
    original = live.read_bytes()
    out = sas.archive_split(live, archive, game_live=_idle)
    back = sas.reinterleave(sas.split_lines(live.read_bytes()),
                            sas.split_lines(archive.read_bytes()),
                            out["archived_positions"])
    assert back == original
    assert out["reinterleave_sha256"] == _sha(original)


def test_positions_rebuild_from_runs(live, archive):
    out = sas.archive_split(live, archive, game_live=_idle)
    assert sas.positions_from_runs(out["archived_runs"]) == out["archived_positions"]


def test_malformed_and_blank_lines_are_kept_in_place(tmp_path):
    p = tmp_path / "x_shadow.jsonl"
    body = [_line(_row(0, [])), b"not json\r\n", b"\r\n",
            _line(_row(1, _ENEMIES)), _line(_row(2, []))]
    p.write_bytes(b"".join(body))
    a = tmp_path / "x_rm859_test_leak_shadow.jsonl"
    out = sas.archive_split(p, a, game_live=_idle)
    assert p.read_bytes() == body[1] + body[2] + body[3]
    assert a.read_bytes() == body[0] + body[4]
    assert out["archived_positions"] == [0, 4]


def test_lf_only_file_stays_lf(tmp_path):
    p = tmp_path / "x_shadow.jsonl"
    body = _corpus(eol=b"\n")
    p.write_bytes(b"".join(body))
    a = tmp_path / "x_rm859_test_leak_shadow.jsonl"
    sas.archive_split(p, a, game_live=_idle)
    assert b"\r" not in p.read_bytes() + a.read_bytes()


def test_predicate_is_the_report_predicate():
    """One predicate: the split moves exactly what RM-852's reader excludes."""
    for enemies in ([], [""], ["  "], _ENEMIES, ["Ashe"]):
        rec = _row(0, enemies)
        assert sas.is_enemy_less_row(_line(rec)) is (not rep.has_enemy_comp(rec))
    no_key = _row(0, [])
    del no_key["enemy_comp"]
    assert sas.is_enemy_less_row(_line(no_key)) is True
    assert sas.is_enemy_less_row(b"not json\r\n") is False
    assert sas.is_enemy_less_row(b"\r\n") is False
    assert sas.is_enemy_less_row(b"[1, 2]\r\n") is False


def test_report_after_split_keeps_gate_and_drops_exclusion(live, archive):
    before = rep.build_report(live)
    sas.archive_split(live, archive, game_live=_idle)
    after = rep.build_report(live)
    assert before["enemy_less_excluded"] == 5
    assert after["enemy_less_excluded"] == 0
    for key in ("gated", "dead_state", "non_dead", "action", "choices",
                "field_presence"):
        assert after[key] == before[key], key
    assert after["total"] == before["total"] - 5


# ---------------------------------------------------------------------------
# 2. Atomic replace.
# ---------------------------------------------------------------------------


def test_live_file_is_written_only_by_one_atomic_replace(live, archive,
                                                         monkeypatch):
    calls = []
    real = os.replace

    def spy(src, dst):
        calls.append((os.fspath(src), os.fspath(dst)))
        return real(src, dst)

    monkeypatch.setattr(sas.os, "replace", spy)
    sas.archive_split(live, archive, game_live=_idle)
    onto_live = [c for c in calls if c[1] == os.fspath(live)]
    assert len(onto_live) == 1
    src = onto_live[0][0]
    assert os.path.dirname(src) == os.fspath(live.parent)
    assert src != os.fspath(live)
    assert _leftovers(live.parent) == []


def test_failed_live_replace_leaves_live_untouched_and_no_archive(
        live, archive, monkeypatch):
    original = live.read_bytes()
    real = os.replace

    def fail_on_live(src, dst):
        if os.fspath(dst) == os.fspath(live):
            raise PermissionError("held open")
        return real(src, dst)

    monkeypatch.setattr(sas.os, "replace", fail_on_live)
    monkeypatch.setattr(sas.time, "sleep", lambda s: None)
    with pytest.raises(sas.SplitAborted) as exc:
        sas.archive_split(live, archive, game_live=_idle)
    assert exc.value.reason == "replace_failed"
    assert live.read_bytes() == original
    assert not archive.exists()
    assert _leftovers(live.parent) == []


def test_existing_archive_is_never_clobbered(live, archive):
    archive.write_bytes(b"prior\n")
    original = live.read_bytes()
    with pytest.raises(sas.SplitAborted) as exc:
        sas.archive_split(live, archive, game_live=_idle)
    assert exc.value.reason == "archive_exists"
    assert archive.read_bytes() == b"prior\n"
    assert live.read_bytes() == original


def test_nothing_to_archive_writes_nothing(tmp_path):
    p = tmp_path / "x_shadow.jsonl"
    p.write_bytes(_line(_row(1, _ENEMIES)))
    a = tmp_path / "x_rm859_test_leak_shadow.jsonl"
    with pytest.raises(sas.SplitAborted) as exc:
        sas.archive_split(p, a, game_live=_idle)
    assert exc.value.reason == "nothing_to_archive"
    assert not a.exists()
    assert _leftovers(tmp_path) == []


def test_torn_last_line_aborts(tmp_path):
    p = tmp_path / "x_shadow.jsonl"
    p.write_bytes(_line(_row(0, [])) + b'{"torn":')
    a = tmp_path / "x_rm859_test_leak_shadow.jsonl"
    with pytest.raises(sas.SplitAborted) as exc:
        sas.archive_split(p, a, game_live=_idle)
    assert exc.value.reason == "no_trailing_newline"
    assert not a.exists()


# ---------------------------------------------------------------------------
# 3. Append during the split is merged, never lost.
# ---------------------------------------------------------------------------


def test_rows_appended_during_split_are_merged(live, archive):
    new = [_line(_row(40, _ENEMIES, action="ALL IN")),
           _line(_row(41, _ENEMIES, action="BACK OFF"))]

    def writer_appends(round_no):
        if round_no == 0:
            with live.open("ab") as fh:
                fh.write(b"".join(new))

    lines = _corpus()
    out = sas.archive_split(live, archive, game_live=_idle,
                            _before_replace=writer_appends)
    kept = [ln for i, ln in enumerate(lines) if i not in _LEAK_AT]
    assert live.read_bytes() == b"".join(kept) + b"".join(new)
    assert archive.read_bytes() == b"".join(
        ln for i, ln in enumerate(lines) if i in _LEAK_AT)
    assert out["tail_rows_merged"] == 2
    assert out["rows_live_after"] == 7
    assert out["verified"] is True


def test_appends_across_several_rounds_are_all_merged(live, archive):
    new = [_line(_row(50 + k, _ENEMIES)) for k in range(3)]

    def writer_appends(round_no):
        if round_no < 3:
            with live.open("ab") as fh:
                fh.write(new[round_no])

    out = sas.archive_split(live, archive, game_live=_idle,
                            _before_replace=writer_appends)
    assert live.read_bytes().endswith(b"".join(new))
    assert out["tail_rows_merged"] == 3


def test_non_append_change_aborts_without_touching_live(live, archive):
    def rewriter(round_no):
        live.write_bytes(b"rewritten\n")

    with pytest.raises(sas.SplitAborted) as exc:
        sas.archive_split(live, archive, game_live=_idle,
                          _before_replace=rewriter)
    assert exc.value.reason == "live_changed_not_append"
    assert live.read_bytes() == b"rewritten\n"
    assert not archive.exists()
    assert _leftovers(live.parent) == []


# ---------------------------------------------------------------------------
# 4. A live game aborts.
# ---------------------------------------------------------------------------


def test_abort_when_a_game_is_live(live, archive):
    original = live.read_bytes()
    with pytest.raises(sas.SplitAborted) as exc:
        sas.archive_split(live, archive, game_live=lambda: True)
    assert exc.value.reason == "game_live"
    assert live.read_bytes() == original
    assert not archive.exists()
    assert _leftovers(live.parent) == []


def test_abort_when_a_game_starts_mid_split(live, archive):
    original = live.read_bytes()
    answers = iter([False, True])
    with pytest.raises(sas.SplitAborted) as exc:
        sas.archive_split(live, archive, game_live=lambda: next(answers))
    assert exc.value.reason == "game_live"
    assert live.read_bytes() == original
    assert not archive.exists()
    assert _leftovers(live.parent) == []


@pytest.mark.parametrize("state, expected", [
    ({"mode_key": "client", "liveclient": None}, False),
    ({"mode_key": "idle", "liveclient": {}}, False),
    ({"mode_key": "aram", "liveclient": {"champion": "Ezreal"}}, True),
    ({"mode_key": "aram", "liveclient": None}, True),
    ({"mode_key": "sr"}, True),
    ({"mode_key": "arena"}, True),
    ({"mode_key": "tft"}, True),
    ({"mode_key": "brawl"}, True),
    ({"mode_key": "client", "liveclient": {"champion": "Ezreal"}}, True),
    ({}, False),
])
def test_game_is_live_reads_mode_key_and_liveclient(state, expected):
    assert sas.game_is_live(state) is expected


def test_state_probe_fails_closed():
    def boom():
        raise OSError("dashboard down")

    assert sas.probe_game_live(fetch=boom) is True
    assert sas.probe_game_live(fetch=lambda: ["not", "a", "dict"]) is True
    assert sas.probe_game_live(fetch=lambda: {"mode_key": "client"}) is False


# ---------------------------------------------------------------------------
# 5. No route to the live tree from a test.
# ---------------------------------------------------------------------------


def test_cli_has_no_default_live_or_archive_path():
    with pytest.raises(SystemExit):
        sas.main([])
    with pytest.raises(SystemExit):
        sas.main(["--live", "x_shadow.jsonl"])


def test_cli_dry_run_writes_nothing(live, archive, capsys):
    original = live.read_bytes()
    rc = sas.main(["--live", str(live), "--archive", str(archive),
                   "--dry-run", "--json"])
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["rows_archived"] == 5 and doc["dry_run"] is True
    assert doc["window"] == "2026-07_2026-07"
    assert live.read_bytes() == original
    assert not archive.exists()


def test_cli_abort_exits_nonzero(live, archive, monkeypatch, capsys):
    monkeypatch.setattr(sas, "probe_game_live", lambda fetch=None: True)
    rc = sas.main(["--live", str(live), "--archive", str(archive)])
    assert rc == 2
    assert "game_live" in capsys.readouterr().out
    assert not archive.exists()
