"""RM-1330 (adaptive_summoners site): the spell-winrate reader keys the
same postgame table the collector writes.

GET /api/champ-select/spell-winrates and the RuneWriter's first-lock
``best_wr_spell_pair`` both read ``{prefix}_player_stats`` out of
data/postgame_stats.db, choosing the prefix with
``routes_adaptive_summoners._mode_table_prefix``. The collector chooses the
table it WRITES with ``lcu.lcu_postgame_collector._norm_mode``. The reader's
map is a hand copy whose comment says it mirrors the collector's
``_MODE_MAP``, and it had drifted: ONEFORALL and ULTBOOK games are written to
``brawl_player_stats``, but a lookup for those modes read
``sr_player_stats``, so a One for All or Ultimate Spellbook lock was offered
the SR corpus's best pair.

The RM-1330 question for this site (does an unsupported mode silently
score as SR?) closes as no-change: an LCU mode the collector does not map is
WRITTEN to the SR tables (``_norm_mode`` defaults to "SR"), so reading SR
for it is the mirror of the writer, not a mis-score. The route has no DS
engine behind it and no in-repo web caller. The tests below pin that parity
instead of a 400.

Known, recorded divergence (not pinned here, not fixed): the reader sends an
unmapped mode containing "ARAM" to the aram table, while the collector would
write such a game to sr. No such mode is measured live.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from dashboard import routes_adaptive_summoners as ras
from lcu import lcu_postgame_collector as coll


def _writer_table(mode: str) -> str:
    return coll._norm_mode(mode).lower()


@pytest.mark.parametrize("mode", sorted(coll._MODE_MAP))
def test_every_collector_mode_reads_the_table_it_was_written_to(mode):
    assert ras._mode_table_prefix(mode) == _writer_table(mode), (
        f"{mode}: collector writes {_writer_table(mode)}_player_stats, "
        f"reader reads {ras._mode_table_prefix(mode)}_player_stats")


@pytest.mark.parametrize("mode", ["oneforall", "ultbook", "Ultbook"])
def test_case_of_a_collector_mode_does_not_change_the_table(mode):
    assert ras._mode_table_prefix(mode) == "brawl"


@pytest.mark.parametrize("mode", ["", "ZZQ", "GAMEMODEX", "ARURF", "BRAWL",
                                  "TUTORIAL", "PRACTICETOOL", "STRAWBERRY"])
def test_an_unmapped_mode_reads_sr_like_the_collector_writes_it(mode):
    # The RM-1330 no-change close: unmapped modes live in the SR tables.
    assert _writer_table(mode) == "sr"
    assert ras._mode_table_prefix(mode) == "sr"


def test_reader_aliases_beyond_the_collector_are_dashboard_forms_only():
    # SR and ARENA are dashboard spellings the LCU never sends as a
    # gameMode. Any OTHER extra key would be a second hand mirror drifting.
    extra = set(ras._MODE_TO_TBL) - set(coll._MODE_MAP)
    assert extra == {"SR", "ARENA"}


# Same-root sibling: lcu.lcu_rune_writer._MODE_TAGS scopes a REMEMBERED spell
# pair by collector mode tag and says it mirrors the collector too. Missing
# ONEFORALL / ULTBOOK collapsed those modes into the SR tag, so a pair picked
# by hand in One for All was pushed on the next SR lock.
@pytest.mark.parametrize("mode", sorted(coll._MODE_MAP))
def test_rune_writer_pref_tag_matches_the_collector_tag(mode):
    from lcu import lcu_rune_writer as rw
    assert rw.mode_tag(mode) == coll._norm_mode(mode)


def test_rune_writer_pref_tag_extras_are_named():
    # SR / ARENA are dashboard spellings; BRAWL is a pref-scope tag only
    # (the writer never reads the corpus with it).
    from lcu import lcu_rune_writer as rw
    assert set(rw._MODE_TAGS) - set(coll._MODE_MAP) == {"SR", "ARENA", "BRAWL"}


def test_a_oneforall_pref_does_not_leak_into_sr(tmp_path, monkeypatch):
    from lcu import lcu_rune_writer as rw
    monkeypatch.setattr(rw, "_SPELL_PREFS_PATH",
                        tmp_path / "spell_prefs.json", raising=True)
    rw.save_champ_spell_pref("Ahri", "ONEFORALL", (4, 6))
    assert rw.load_champ_spell_pref("Ahri", "ONEFORALL") == (4, 6)
    assert rw.load_champ_spell_pref("Ahri", "CLASSIC") is None


def _corpus(conn: sqlite3.Connection) -> None:
    for tbl, pair in (("sr", (4, 14)), ("brawl", (4, 6))):
        conn.execute(
            f"CREATE TABLE {tbl}_player_stats (champion_name TEXT, "
            f"spell1_id INTEGER, spell2_id INTEGER, team_result TEXT)")
        conn.executemany(
            f"INSERT INTO {tbl}_player_stats VALUES (?, ?, ?, ?)",
            [("Ahri", pair[0], pair[1], "WIN")] * 5)


@pytest.mark.parametrize("mode,want", [
    ("ONEFORALL", (4, 6)), ("ULTBOOK", (4, 6)), ("URF", (4, 6)),
    ("CLASSIC", (4, 14)), ("ZZQ", (4, 14)),
])
def test_best_wr_spell_pair_reads_the_mode_corpus(mode, want):
    conn = sqlite3.connect(":memory:")
    try:
        _corpus(conn)
        assert ras.best_wr_spell_pair(conn, "Ahri", mode) == want
    finally:
        conn.close()


class _H:
    def __init__(self, path: str):
        self.path = path
        self.sent: list[tuple[int, bytes]] = []

    def _send(self, code, body, ctype):  # noqa: ARG002 - handler shape
        self.sent.append((code, body))


def test_route_answers_the_brawl_corpus_for_oneforall(tmp_path, monkeypatch):
    db = tmp_path / "postgame_stats.db"
    conn = sqlite3.connect(db)
    try:
        _corpus(conn)
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(ras, "_postgame_db_path", lambda: db)
    h = _H("/api/champ-select/spell-winrates?champion=Ahri&mode=ONEFORALL")
    ras._serve_spell_winrates(h)
    assert len(h.sent) == 1
    code, body = h.sent[0]
    doc = json.loads(body)
    assert code == 200
    assert doc["ok"] is True
    assert doc["best"] == [4, 6]
    assert [p["n"] for p in doc["pairs"]] == [5]
