"""Hardening tests for ``core.draft_elo_db`` (true-audit S144-T-555).

The module turns the local rewind_history.db into smoothed draft priors
for /api/draft-elo, /api/ban-suggest, /api/draft-score and the player
profile. Each test below pins one weakness the audit measured:

- an EMPTY queue filter silently widened to EVERY queue (ARAM, Arena,
  One for All rows mixed into the SR draft priors);
- a str / bool / float queue id or champion id was bound as-is or
  truncated (``"420"`` became the queue set {4, 2, 0}; ``64.9`` read
  champion 64; ``True`` read champion 1);
- an id outside SQLite's 64-bit range raised OverflowError instead of
  reading as "no games";
- a long queue list hit SQLite's bound-variable limit;
- any ``side`` other than "ally" silently meant "enemy";
- ``open_ro`` pasted the path into a ``file:`` URI unescaped, so a ``#``,
  ``?`` or ``%xx`` in the path opened a DIFFERENT file.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from core import draft_elo_db
from tests._draft_elo_fixture import build_fixture_db

# Seed (tests/_draft_elo_fixture.py): champ 64 plays m1 (q420, win),
# m2 (q420, loss) and m3 (q400, win); champ 22 plays m1 (q420, win, same
# team as 64) and m2 (q420, win, opposing team).


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "rewind_history.db"
    build_fixture_db(path)
    c = draft_elo_db.open_ro(path)
    try:
        yield c
    finally:
        c.close()


def _add_rows(path: Path, match_id: str, queue_id: int, parts) -> None:
    c = sqlite3.connect(str(path))
    try:
        c.execute("INSERT INTO matches (match_id, queue_id) VALUES (?, ?)",
                  (match_id, queue_id))
        for champ, team, win in parts:
            c.execute(
                "INSERT INTO participants (match_id, champion_id, win, "
                "team_id) VALUES (?, ?, ?, ?)",
                (match_id, champ, win, team),
            )
        c.commit()
    finally:
        c.close()


# --- characterization (pins the documented contract) --------------------

def test_characterize_default_queue_set(conn):
    assert draft_elo_db.solo_winrate(conn, 64) == (2, 3, 0.6)
    assert draft_elo_db.solo_winrate(conn, 64, [420]) == (1, 2, 0.5)
    assert draft_elo_db.pair_winrate(conn, 64, 22) == (1, 1, 2 / 3)
    # matchup: 64 vs 22 on opposing teams once (m2), 64's team lost.
    assert draft_elo_db.matchup_winrate(conn, 64, 22) == (0, 1, 1 / 3)
    # ...and the reverse orientation reads 22's side of the same match.
    assert draft_elo_db.matchup_winrate(conn, 22, 64) == (1, 1, 2 / 3)


def test_unknown_champion_is_zero_games(conn):
    assert draft_elo_db.solo_winrate(conn, 9999) == (0, 0, 0.5)


def test_mirror_matchup_counts_participant_rows(tmp_path):
    """A mirror reads from the participant-row perspective: both copies
    are champ_a, so one match is two rows with exactly one win."""
    path = tmp_path / "rewind_history.db"
    build_fixture_db(path)
    _add_rows(path, "m4", 430, ((7, 100, 1), (7, 200, 0)))
    c = draft_elo_db.open_ro(path)
    try:
        assert draft_elo_db.matchup_winrate(c, 7, 7) == (1, 2, 0.5)
    finally:
        c.close()


# --- F1: an empty queue filter must not mean "every queue" ---------------

@pytest.mark.parametrize("empty", [[], (), set(), iter(())])
def test_empty_queue_filter_is_refused(conn, empty):
    with pytest.raises(ValueError):
        draft_elo_db.solo_winrate(conn, 64, empty)


def test_empty_queue_filter_refused_for_pair_and_matchup(conn):
    with pytest.raises(ValueError):
        draft_elo_db.pair_winrate(conn, 64, 22, [])
    with pytest.raises(ValueError):
        draft_elo_db.matchup_winrate(conn, 64, 22, ())


def test_empty_filter_used_to_mix_in_other_queues(tmp_path):
    """The already-bad answer: an ARAM row leaked into the SR prior."""
    path = tmp_path / "rewind_history.db"
    build_fixture_db(path)
    _add_rows(path, "m9", 450, ((64, 100, 1),))
    c = draft_elo_db.open_ro(path)
    try:
        assert draft_elo_db.solo_winrate(c, 64)[1] == 3
        with pytest.raises(ValueError):
            draft_elo_db.solo_winrate(c, 64, [])
    finally:
        c.close()


# --- F2: queue ids are ints, never strs / bools / floats -----------------

@pytest.mark.parametrize("bad", ["420", b"420", bytearray(b"420")])
def test_str_queue_ids_refused(conn, bad):
    with pytest.raises(TypeError):
        draft_elo_db.solo_winrate(conn, 64, bad)


@pytest.mark.parametrize("bad", [[True], [420.0], ["420"], [None], [420, 1.5]])
def test_non_int_queue_id_refused(conn, bad):
    with pytest.raises(TypeError):
        draft_elo_db.solo_winrate(conn, 64, bad)


def test_non_iterable_queue_ids_refused(conn):
    with pytest.raises(TypeError):
        draft_elo_db.solo_winrate(conn, 64, 420)


def test_duplicate_queue_ids_are_one_filter(conn):
    assert draft_elo_db.solo_winrate(conn, 64, [420] * 500) == (1, 2, 0.5)


def test_queue_list_over_cap_is_value_error_not_sqlite_error(conn):
    with pytest.raises(ValueError):
        draft_elo_db.solo_winrate(conn, 64, range(40000))


def test_queue_list_at_cap_is_accepted(conn):
    qids = list(range(draft_elo_db.MAX_QUEUE_IDS - 1)) + [420]
    assert draft_elo_db.solo_winrate(conn, 64, qids) == (1, 2, 0.5)


# --- F3: ids outside SQLite's 64-bit range read as "no games" -----------

@pytest.mark.parametrize("huge", [2 ** 63, 2 ** 70, -(2 ** 63) - 1])
def test_out_of_range_champion_is_zero_games(conn, huge):
    assert draft_elo_db.solo_winrate(conn, huge) == (0, 0, 0.5)
    assert draft_elo_db.pair_winrate(conn, 64, huge) == (0, 0, 0.5)
    assert draft_elo_db.matchup_winrate(conn, huge, 22) == (0, 0, 0.5)


def test_int64_bounds_still_query(conn):
    assert draft_elo_db.solo_winrate(conn, 2 ** 63 - 1) == (0, 0, 0.5)
    assert draft_elo_db.solo_winrate(conn, -(2 ** 63)) == (0, 0, 0.5)


def test_out_of_range_queue_id_matches_nothing(conn):
    assert draft_elo_db.solo_winrate(conn, 64, [2 ** 70]) == (0, 0, 0.5)
    # In-range ids beside it still filter normally.
    assert draft_elo_db.solo_winrate(conn, 64, [420, 2 ** 70]) == (1, 2, 0.5)


# --- F4: champion ids are ints, never bool / float / str ----------------

@pytest.mark.parametrize("bad", [True, 64.9, 64.0, "64", None])
def test_non_int_champion_refused(conn, bad):
    with pytest.raises(TypeError):
        draft_elo_db.solo_winrate(conn, bad)
    with pytest.raises(TypeError):
        draft_elo_db.pair_winrate(conn, 64, bad)
    with pytest.raises(TypeError):
        draft_elo_db.matchup_winrate(conn, bad, 22)


def test_index_like_int_is_accepted(conn):
    class _Idx:
        def __index__(self):
            return 64

    assert draft_elo_db.solo_winrate(conn, _Idx()) == (2, 3, 0.6)


# --- F5: side is "ally" or "enemy", nothing else -------------------------

@pytest.mark.parametrize("bad", ["Ally", "allies", "", None, "ENEMY", 1])
def test_unknown_side_refused(conn, bad):
    with pytest.raises(ValueError):
        draft_elo_db.pair_winrate(conn, 64, 22, side=bad)


def test_enemy_side_is_the_matchup(conn):
    assert (draft_elo_db.pair_winrate(conn, 64, 22, side="enemy")
            == draft_elo_db.matchup_winrate(conn, 64, 22))


# --- F6: open_ro escapes the path into the file: URI ---------------------

@pytest.mark.parametrize("dirname", ["a#b", "a%41b", "a b", "a&b"])
def test_open_ro_survives_uri_special_chars(tmp_path, dirname):
    d = tmp_path / dirname
    d.mkdir()
    path = d / "rewind_history.db"
    build_fixture_db(path)
    c = draft_elo_db.open_ro(path)
    try:
        assert draft_elo_db.solo_winrate(c, 64) == (2, 3, 0.6)
    finally:
        c.close()


def test_open_ro_env_override_with_hash_in_path(tmp_path, monkeypatch):
    d = tmp_path / "x#y"
    d.mkdir()
    path = d / "rewind_history.db"
    build_fixture_db(path)
    monkeypatch.setenv("RC_REWIND_DB", str(path))
    c = draft_elo_db.open_ro()
    try:
        assert draft_elo_db.solo_winrate(c, 64)[1] == 3
    finally:
        c.close()


def test_open_ro_is_read_only(tmp_path):
    path = tmp_path / "rewind_history.db"
    build_fixture_db(path)
    c = draft_elo_db.open_ro(path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            c.execute("DELETE FROM participants")
    finally:
        c.close()


def test_open_ro_missing_file_raises_and_creates_nothing(tmp_path):
    path = tmp_path / "absent#dir" / "rewind_history.db"
    with pytest.raises(sqlite3.OperationalError):
        draft_elo_db.open_ro(path)
    assert not path.exists()
    assert not path.parent.exists()


def test_open_ro_accepts_str_path(tmp_path):
    path = tmp_path / "rewind_history.db"
    build_fixture_db(path)
    c = draft_elo_db.open_ro(str(path))
    try:
        assert draft_elo_db.solo_winrate(c, 64)[1] == 3
    finally:
        c.close()


# --- F1 caller: /api/draft-elo must not turn "queue=," into no filter ---

class _Harness:
    def __init__(self, qs: str):
        self.path = f"/api/draft-elo?{qs}"
        self.sent_status = None
        self.sent_body = b""

    def _send(self, status, body, content_type):
        self.sent_status = status
        self.sent_body = body


_DRAFT = "ally=22,64,55,89,12&enemy=42,67,69,33,99"


@pytest.fixture
def route(tmp_path, monkeypatch):
    from dashboard import routes_draft_elo

    path = tmp_path / "rewind_history.db"
    build_fixture_db(path)
    monkeypatch.setenv("RC_REWIND_DB", str(path))
    routes_draft_elo._reset_caches()
    yield routes_draft_elo
    routes_draft_elo._reset_caches()


def _get(route, qs):
    import json

    h = _Harness(qs)
    route._serve_draft_elo(h)
    return h.sent_status, json.loads(h.sent_body)


@pytest.mark.parametrize("raw", [",", ", ,", ",,,"])
def test_route_queue_without_ids_is_400(route, raw):
    status, payload = _get(route, f"{_DRAFT}&queue={raw}")
    assert status == 400
    assert payload["ok"] is False
    assert payload["error"].startswith("queue: ")


def test_route_empty_queue_does_not_poison_default_cache(route):
    _get(route, f"{_DRAFT}&queue=,")
    status, payload = _get(route, _DRAFT)
    assert status == 200
    assert payload.get("cached") is not True


def test_route_too_many_queue_ids_is_400(route):
    qs = ",".join(str(400 + i) for i in range(route._MAX_QUEUE_IDS + 1))
    status, payload = _get(route, f"{_DRAFT}&queue={qs}")
    assert status == 400
    assert payload["error"].startswith("queue: ")


def test_route_queue_cap_is_within_module_cap(route):
    assert 1 <= route._MAX_QUEUE_IDS <= draft_elo_db.MAX_QUEUE_IDS


def test_route_out_of_range_queue_id_is_200_not_500(route):
    status, payload = _get(route, f"{_DRAFT}&queue={2 ** 70}")
    assert status == 200
    assert payload["ok"] is True
    assert payload["sample"]["min_solo"] == 0


def test_route_explicit_queue_still_filters(route):
    status, payload = _get(route, f"{_DRAFT}&queue=420")
    assert status == 200
    assert payload["ok"] is True


# --- verifier round 1: a UNC path must still open --------------------------

def test_ro_uri_unc_uses_empty_authority():
    from pathlib import PureWindowsPath

    uri = draft_elo_db._ro_uri(PureWindowsPath("//server/share/d#x/r.db"))
    assert uri == "file:////server/share/d%23x/r.db?mode=ro"


def test_ro_uri_drive_path_is_encoded():
    from pathlib import PureWindowsPath

    uri = draft_elo_db._ro_uri(PureWindowsPath(r"C:\a b\c%41\r.db"))
    assert uri == "file:///C:/a%20b/c%2541/r.db?mode=ro"


def test_ro_uri_posix_path_is_encoded():
    from pathlib import PurePosixPath

    uri = draft_elo_db._ro_uri(PurePosixPath("/srv/a#b/r.db"))
    assert uri == "file:///srv/a%23b/r.db?mode=ro"


def _admin_share(path: Path):
    """The loopback admin-share spelling of ``path``, or None."""
    import sys

    if sys.platform != "win32" or not path.drive or len(path.drive) != 2:
        return None
    unc = Path("//127.0.0.1/" + path.drive[0] + "$" + path.as_posix()[2:])
    try:
        return unc if unc.exists() else None
    except OSError:
        return None


def test_open_ro_unc_path_opens(tmp_path):
    path = tmp_path / "rewind_history.db"
    build_fixture_db(path)
    unc = _admin_share(path)
    if unc is None:
        pytest.skip("no loopback admin share on this box")
    c = draft_elo_db.open_ro(unc)
    try:
        assert draft_elo_db.solo_winrate(c, 64) == (2, 3, 0.6)
    finally:
        c.close()
