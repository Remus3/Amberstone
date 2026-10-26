"""s134 true-audit (lane 8, cycle 17): tft/rounds/schema.py.

Contract under test (schema.py module docstring and the MIGRATIONS note): the
module is DATA ONLY - closed enums, the table / column declaration and a
forward-only migration list in which "a later slice appends MIGRATIONS[2] and
bumps SCHEMA_VERSION, it never edits an applied step". An applied step is
permanent: every database it created keeps that DDL forever, so a declaration
error that reaches the DDL can never be repaired in place.

  S1  `_create_table` made the rowid alias by POSITION: for pk ("id",) it
      overwrote body[0], whatever column sat there. A table whose id was not
      first lost its first column and declared `id` twice; a table with no id
      column at all silently lost its first column; an id declared TEXT became
      an INTEGER rowid alias without a word.
  S2  Nothing checked the declaration before it became DDL: a duplicate column,
      a primary key or an index naming a column the table does not have, or an
      index on a table that does not exist, were all emitted as DDL that only
      failed later, inside the store's writer thread, when a database opened.
  S3  The contract maps were plain dicts (ROUND_ENVELOPES, ROUND_PLAIN,
      COLUMNS, PRIMARY_KEYS, MIGRATIONS, the queue-kind table): any importer
      could rewrite the writer's validation or an applied migration step
      process-wide, with no error.
  S4  "never edits an applied step" had no guard: an edit to the v1 DDL
      passed every test, and fresh databases would then silently differ from
      every database already on disk.

Measured at local main eb90635d5: `_create_table("t", (("a", "TEXT"), ("id",
"INTEGER")), ("id",))` returned a CREATE with `id INTEGER PRIMARY KEY` and
`id INTEGER` and no column `a`; `rs.ROUND_ENVELOPES["x"] = int` succeeded.
"""
from __future__ import annotations

import hashlib
import sqlite3

import pytest

from core import queue_modes
from tft.rounds import schema as rs

# sha256 of "\n".join(MIGRATIONS[1]), ASCII. Schema v1 is APPLIED (TFT-01,
# 14645d926): every tft_rounds.db on disk was created from exactly these bytes.
# A failure here means an applied step was edited. Do NOT re-pin: revert the
# edit, append MIGRATIONS[2] and bump SCHEMA_VERSION instead.
V1_DDL_SHA256 = "774d07ce410a73b6b2b5ff9aef7d823588f1ff8fedda2fa5814b397d86b34f74"


def _mem_db(stmts):
    conn = sqlite3.connect(":memory:")
    for s in stmts:
        conn.execute(s)
    return conn


def _info(conn, table):
    return conn.execute(f"PRAGMA table_info({table})").fetchall()


# ---------------------------------------------------------------- S1


def test_s1_rowid_alias_is_the_id_column_not_the_first():
    ddl = rs._create_table("t", (("a", "TEXT"), ("id", "INTEGER")), ("id",))
    conn = _mem_db([ddl])
    info = _info(conn, "t")
    assert [r[1] for r in info] == ["a", "id"]
    assert [(r[1], r[2], r[5]) for r in info] == [("a", "TEXT", 0), ("id", "INTEGER", 1)]
    # a rowid alias autoassigns
    conn.execute("INSERT INTO t (a) VALUES ('x')")
    assert conn.execute("SELECT id FROM t").fetchone()[0] == 1


def test_s1_rowid_pk_without_an_id_column_is_refused():
    with pytest.raises(ValueError):
        rs._create_table("t", (("a", "TEXT"), ("b", "INTEGER")), ("id",))


def test_s1_rowid_alias_must_be_declared_integer():
    with pytest.raises(ValueError):
        rs._create_table("t", (("id", "TEXT"), ("a", "TEXT")), ("id",))


def test_s1_the_real_rowid_tables_keep_their_ddl():
    """The three rowid tables (unit_obs, event, obs) declare id first, so the
    by-name rule emits exactly what the by-position rule did (S4 pins it)."""
    for name, cols, pk in rs.TABLES:
        if pk == ("id",):
            assert cols[0] == ("id", "INTEGER"), name
            ddl = rs._create_table(name, cols, pk)
            assert ddl.count("id INTEGER PRIMARY KEY") == 1, name
            assert ddl.count("\n    id ") == 1, name


# ---------------------------------------------------------------- S2


def test_s2_duplicate_column_is_refused():
    with pytest.raises(ValueError):
        rs._create_table("t", (("a", "TEXT"), ("a", "INTEGER")), ())


def test_s2_composite_pk_naming_a_missing_column_is_refused():
    with pytest.raises(ValueError):
        rs._create_table("t", (("a", "TEXT"), ("b", "TEXT")), ("a", "c"))


def test_s2_index_naming_a_missing_column_is_refused(monkeypatch):
    monkeypatch.setattr(rs, "INDEXES", (("ix_bad", "event", ("match_id", "nope")),))
    with pytest.raises(ValueError):
        rs.ddl_v1()


def test_s2_index_on_an_unknown_table_is_refused(monkeypatch):
    monkeypatch.setattr(rs, "INDEXES", (("ix_bad", "nope", ("match_id",)),))
    with pytest.raises(ValueError):
        rs.ddl_v1()


def test_s2_the_real_declaration_passes_its_own_checks():
    assert rs.ddl_v1() == rs.MIGRATIONS[1]


# ---------------------------------------------------------------- S3


@pytest.mark.parametrize("name", ["ROUND_ENVELOPES", "ROUND_PLAIN", "COLUMNS",
                                  "PRIMARY_KEYS", "MIGRATIONS", "_QUEUE_KIND_BY_ID"])
def test_s3_contract_maps_are_read_only(name):
    m = getattr(rs, name)
    key = next(iter(m))
    with pytest.raises(TypeError):
        m[key] = m[key]
    with pytest.raises(TypeError):
        m["__s134_planted__"] = None
    assert "__s134_planted__" not in m


def test_s3_read_only_maps_still_read_like_dicts():
    """The store reads them with `in`, `[...]` and iteration; keep that."""
    assert "gold_start" in rs.ROUND_ENVELOPES and rs.ROUND_ENVELOPES["level"] is int
    assert "label" in rs.ROUND_PLAIN and rs.ROUND_PLAIN["end_ts"] is float
    assert rs.COLUMNS["frame"][0] == "frame_id"
    assert rs.PRIMARY_KEYS["round"] == ("match_id", "round_seq")
    assert list(rs.MIGRATIONS) == [1]
    assert dict(rs.COLUMNS).keys() == set(rs.TABLE_NAMES)


@pytest.mark.parametrize("name", ["SRC_VALUES", "QUEUE_KINDS", "ROUND_KINDS", "VERDICTS",
                                  "UNIT_PHASES", "CAPTURE_PHASES", "ZONES", "REFRESH_CAUSES",
                                  "OFFER_KINDS", "EVENT_KINDS", "GT_SOURCES", "GT_STATUS",
                                  "TABLES", "TABLE_NAMES", "INDEXES"])
def test_s3_closed_enums_and_declarations_are_tuples(name):
    v = getattr(rs, name)
    assert type(v) is tuple and v and len(set(v)) == len(v), name


# ---------------------------------------------------------------- S4


def test_s4_applied_v1_step_is_byte_pinned():
    v1 = rs.MIGRATIONS[1]
    assert type(v1) is tuple and all(type(s) is str for s in v1)
    blob = "\n".join(v1).encode("ascii")
    assert hashlib.sha256(blob).hexdigest() == V1_DDL_SHA256, (
        "schema v1 is applied: never edit it - append MIGRATIONS[2] and bump "
        "SCHEMA_VERSION")


def test_s4_migrations_cover_every_version_once():
    """store._migrate walks range(current + 1, SCHEMA_VERSION + 1) and indexes
    MIGRATIONS[v]: a gap is a KeyError inside the open transaction."""
    assert sorted(rs.MIGRATIONS) == list(range(1, rs.SCHEMA_VERSION + 1))
    assert all(type(k) is int for k in rs.MIGRATIONS)


# ---------------------------------------------------------------- characterization


@pytest.fixture(scope="module")
def v1_conn():
    conn = _mem_db(s for v in sorted(rs.MIGRATIONS) for s in rs.MIGRATIONS[v])
    yield conn
    conn.close()


def test_every_declared_table_is_created_with_its_columns_and_key(v1_conn):
    tables = {r[0] for r in v1_conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert tables == set(rs.TABLE_NAMES)
    assert len(rs.TABLE_NAMES) == len(set(rs.TABLE_NAMES))
    for name in rs.TABLE_NAMES:
        info = _info(v1_conn, name)
        assert tuple(r[1] for r in info) == rs.COLUMNS[name], name
        pk = tuple(r[1] for r in sorted(info, key=lambda r: r[5]) if r[5])
        assert pk == rs.PRIMARY_KEYS[name], name


def test_every_src_column_defaults_absent_and_every_envelope_is_a_trio(v1_conn):
    """Docstring: every *_src column defaults to 'absent', so a never-written
    envelope reads back as absent; X_conf is REAL."""
    n_src, src_only = 0, set()
    for name in rs.TABLE_NAMES:
        info = {r[1]: r for r in _info(v1_conn, name)}
        for col, r in info.items():
            if col == "src" or col.endswith("_src"):
                n_src += 1
                assert (r[2], r[3], r[4]) == ("TEXT", 1, "'absent'"), (name, col)
                stem = col[:-len("src")]
                if stem + "conf" in info:
                    assert info[stem + "conf"][2] == "REAL", (name, col)
                else:
                    src_only.add((name, col))
    # 16 round envelopes + placement + final_standing + 11 row-level srcs
    # (unit_obs and shop_offer carry two each) - an empty walk cannot pass
    assert n_src == 29
    # section 1.5: an event row carries a src but no conf; every other src pairs
    assert src_only == {("event", "src")}


def test_round_table_carries_every_declared_envelope_and_plain_field(v1_conn):
    info = {r[1]: r[2] for r in _info(v1_conn, "round")}
    for field, pytype in rs.ROUND_ENVELOPES.items():
        sqltype = {int: "INTEGER", bool: "INTEGER", str: "TEXT", float: "REAL"}[pytype]
        assert info[field] == sqltype, field
        assert info[field + "_conf"] == "REAL" and info[field + "_src"] == "TEXT", field
    for field, pytype in rs.ROUND_PLAIN.items():
        assert info[field] == {str: "TEXT", float: "REAL"}[pytype], field
    declared = {"match_id", "round_seq"} | set(rs.ROUND_PLAIN) | {
        f + sfx for f in rs.ROUND_ENVELOPES for sfx in ("", "_conf", "_src")}
    assert set(info) == declared


def test_every_index_is_created_on_its_columns(v1_conn):
    for ix, table, cols in rs.INDEXES:
        assert table in rs.COLUMNS
        got = tuple(r[2] for r in v1_conn.execute(f"PRAGMA index_info({ix})"))
        assert got == cols, ix


# ---------------------------------------------------------------- queue_kind_for


@pytest.mark.parametrize("junk", [True, False, "1100", 1100.0, b"1100", 2 ** 70, -1100,
                                  [1100], {"queue_id": 1100}, float("nan")])
def test_queue_kind_for_junk_is_other(junk):
    assert rs.queue_kind_for(junk) == "other"


def test_queue_kind_table_names_only_tft_queues_and_known_kinds():
    """Cross-module drift: every id the table classifies is a TFT queue in
    core/queue_modes.py, and every kind it yields is a QUEUE_KINDS value."""
    for qid, kind in rs._QUEUE_KIND_BY_ID.items():
        assert queue_modes.QUEUE_ID_TO_MODE_KEY.get(qid) == "tft", qid
        assert kind in rs.QUEUE_KINDS and kind != "other", qid
    tft_ids = [q for q, m in queue_modes.QUEUE_ID_TO_MODE_KEY.items() if m == "tft"]
    for qid in tft_ids:
        assert rs.queue_kind_for(qid) in rs.QUEUE_KINDS
