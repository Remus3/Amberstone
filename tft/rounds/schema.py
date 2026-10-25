"""tft/rounds/schema.py - the TFT per-round store contract, schema v1.

Source of truth: docs/TFT_PROGRAM.md section 1 (record schema) and section 2
(storage). This module is DATA ONLY: the closed enums, the table / column
declaration and the forward-only migration list. `tft/rounds/store.py` is the
one writer and reader.

Envelope (section 1.1): every measured scalar X is three columns, X, X_conf
(REAL 0..1) and X_src (TEXT, the closed SRC_VALUES enum). A value that was not
observed is NULL with X_src = 'absent' - never 0 - so every *_src column
defaults to 'absent' and a never-written envelope reads back as absent.

Enums are enforced by the writer, not by SQL CHECK constraints: SQLite cannot
ALTER a CHECK, so a CHECK would turn every future enum value into a table
rebuild. The writer refuses anything outside these sets (fail-soft: the row is
dropped and counted, see store.py).
"""
from __future__ import annotations

SCHEMA_VERSION = 1

# section 1.1 - the closed src enum (a guard rejects anything else)
SRC_VALUES = (
    "eog_file", "tft_log", "lcu", "riot_match_v1", "ocr", "icon", "geom",
    "derived", "llm_fallback", "manual_label", "absent",
)
ABSENT = "absent"
LLM_CONF_CAP = 0.5  # section 1.1: llm_fallback conf is capped at 0.5

# section 1.5 column enums
QUEUE_KINDS = ("normal", "ranked", "hyper_roll", "double_up", "other")
ROUND_KINDS = ("pvp", "pve", "carousel", "augment", "unknown")  # section 1.3
VERDICTS = ("win", "loss", "draw", "pve_win", "pve_loss")  # section 1.4 row 15
UNIT_PHASES = ("planning_start", "planning_end", "combat", "carousel")
# frames / raw obs may also come from a mid-planning shop capture or an augment
# overlay (section 3.2 step 1), so they take a slightly wider phase set
CAPTURE_PHASES = UNIT_PHASES + ("planning", "augment")
ZONES = ("board", "bench", "carousel")
REFRESH_CAUSES = ("round_start", "reroll", "locked", "unknown")
OFFER_KINDS = ("champion", "special", "empty")
EVENT_KINDS = ("phase", "purchase_vo", "starup_vo", "victory_vo", "planner_saved",
               "carousel_music", "eog_rewrite", "capture_skip", "disagreement")
GT_SOURCES = ("lcu_eog", "lcu_mh", "match_v1", "eog_file_final")
GT_STATUS = ("none", "partial", "full")

# Board geometry bounds (section 1.4 rows 3-4): own half 4 x 7, bench 9 slots.
HEX_ROWS = 4
HEX_COLS = 7
BENCH_SLOTS = 9

# queue_kind comes from the queue id, never from mapNumber (section 1.5; the
# legacy mapNumber-22 rule contradicts the measured Normal session, section 8
# item 10). 1090 / 1100 / 1130 per core/queue_modes.py (RM-140); 1160 Double Up
# per the LCU TFT inventory (section 0 item 3). The event queues 1220 / 1230 and
# the Set 17 revival 6110 are 'other' until a slice classifies them.
_QUEUE_KIND_BY_ID = {1090: "normal", 1100: "ranked", 1130: "hyper_roll", 1160: "double_up"}


def queue_kind_for(queue_id) -> str:
    """The section 1.5 queue_kind for a TFT queue id; 'other' when unknown."""
    if isinstance(queue_id, bool) or not isinstance(queue_id, int):
        return "other"
    return _QUEUE_KIND_BY_ID.get(queue_id, "other")


# ---------------------------------------------------------------- tables
#
# Each table is (name, columns, primary key). A column is (name, sql type). An
# ENVELOPE column expands to the (c/s) trio of section 1.5. The spec names a
# primary key for some tables only; the others get the natural key their
# writer upserts on, so a re-resolve (section 1.5 `obs` note) replaces rows
# instead of duplicating them. gt_board has no key on purpose: two identical
# units on one board are two rows.

_SRC_COL = "TEXT NOT NULL DEFAULT 'absent'"


def _env(name, sqltype):
    return ((name, sqltype), (name + "_conf", "REAL"), (name + "_src", _SRC_COL))


ROUND_ENVELOPES = {  # name -> python type of the value
    "stage": int, "round": int, "kind": str, "gold_start": int, "gold_end": int,
    "level": int, "xp_cur": int, "xp_max": int, "hp_start": int, "hp_end": int,
    "streak": int, "verdict": str, "damage_taken": int, "damage_dealt": int,
    "opponent_key": str, "opponent_is_ghost": bool,
}
ROUND_PLAIN = {"label": str, "planning_ts": float, "combat_ts": float, "end_ts": float}

_SQLTYPE = {int: "INTEGER", str: "TEXT", bool: "INTEGER", float: "REAL"}


def _round_columns():
    cols = [("match_id", "TEXT NOT NULL"), ("round_seq", "INTEGER NOT NULL")]
    cols += _env("stage", "INTEGER")
    cols += _env("round", "INTEGER")
    cols.append(("label", "TEXT"))
    cols += _env("kind", "TEXT")
    cols += [("planning_ts", "REAL"), ("combat_ts", "REAL"), ("end_ts", "REAL")]
    for name in ("gold_start", "gold_end", "level", "xp_cur", "xp_max", "hp_start",
                 "hp_end", "streak", "verdict", "damage_taken", "damage_dealt",
                 "opponent_key", "opponent_is_ghost"):
        cols += _env(name, _SQLTYPE[ROUND_ENVELOPES[name]])
    return tuple(cols)


TABLES = (
    ("schema_meta", (("key", "TEXT"), ("value", "TEXT")), ("key",)),
    ("match", (
        ("match_id", "TEXT"), ("game_id", "INTEGER"), ("set_id", "INTEGER"),
        ("set_core_name", "TEXT"), ("queue_id", "INTEGER"), ("queue_kind", "TEXT"),
        ("started_at", "REAL"), ("ended_at", "REAL"), *_env("placement", "INTEGER"),
        ("capture_profile", "TEXT"), ("extractor_version", "TEXT"), ("rc_commit", "TEXT"),
        ("gt_status", "TEXT NOT NULL DEFAULT 'none'"),
        ("gt_sources", "TEXT NOT NULL DEFAULT '[]'"),
    ), ("match_id",)),
    ("player", (
        ("match_id", "TEXT NOT NULL"), ("player_key", "TEXT NOT NULL"), ("slot", "INTEGER"),
        ("is_local", "INTEGER NOT NULL DEFAULT 0"), *_env("final_standing", "INTEGER"),
        ("eliminated_round_seq", "INTEGER"),
    ), ("match_id", "player_key")),
    ("round", _round_columns(), ("match_id", "round_seq")),
    ("unit_obs", (
        ("id", "INTEGER"), ("match_id", "TEXT NOT NULL"), ("round_seq", "INTEGER NOT NULL"),
        ("phase", "TEXT NOT NULL"), ("player_key", "TEXT NOT NULL"), ("zone", "TEXT NOT NULL"),
        ("hex_row", "INTEGER"), ("hex_col", "INTEGER"), ("bench_idx", "INTEGER"),
        ("champion_api", "TEXT"), ("star", "INTEGER"), ("items_json", "TEXT"),
        ("cost", "INTEGER"), ("conf", "REAL"), ("src", _SRC_COL), ("pos_conf", "REAL"),
        ("pos_src", _SRC_COL), ("frame_id", "TEXT"),
    ), ("id",)),
    ("shop_refresh", (
        ("match_id", "TEXT NOT NULL"), ("round_seq", "INTEGER NOT NULL"),
        ("refresh_idx", "INTEGER NOT NULL"), ("cause", "TEXT"), ("ts", "REAL"),
        ("gold_before", "INTEGER"), ("gold_after", "INTEGER"), ("conf", "REAL"),
        ("src", _SRC_COL),
    ), ("match_id", "round_seq", "refresh_idx")),
    ("shop_offer", (
        ("match_id", "TEXT NOT NULL"), ("round_seq", "INTEGER NOT NULL"),
        ("refresh_idx", "INTEGER NOT NULL"), ("slot", "INTEGER NOT NULL"), ("kind", "TEXT"),
        ("champion_api", "TEXT"), ("name_text", "TEXT"), ("cost", "INTEGER"),
        ("bought", "INTEGER"), ("bought_conf", "REAL"), ("bought_src", _SRC_COL),
        ("conf", "REAL"), ("src", _SRC_COL),
    ), ("match_id", "round_seq", "refresh_idx", "slot")),
    ("shop_odds", (
        ("match_id", "TEXT NOT NULL"), ("round_seq", "INTEGER NOT NULL"),
        ("level", "INTEGER NOT NULL"), ("p1", "REAL"), ("p2", "REAL"), ("p3", "REAL"),
        ("p4", "REAL"), ("p5", "REAL"), ("conf", "REAL"), ("src", _SRC_COL),
    ), ("match_id", "round_seq", "level")),
    ("trait_state", (
        ("match_id", "TEXT NOT NULL"), ("round_seq", "INTEGER NOT NULL"),
        ("phase", "TEXT NOT NULL"), ("player_key", "TEXT NOT NULL"),
        ("trait_api", "TEXT NOT NULL"), ("count", "INTEGER"), ("tier_index", "INTEGER"),
        ("active", "INTEGER"), ("conf", "REAL"), ("src", _SRC_COL),
    ), ("match_id", "round_seq", "phase", "player_key", "trait_api")),
    ("augment", (
        ("match_id", "TEXT NOT NULL"), ("round_seq", "INTEGER NOT NULL"),
        ("pick_idx", "INTEGER NOT NULL"), ("offered_json", "TEXT"), ("chosen_api", "TEXT"),
        ("conf", "REAL"), ("src", _SRC_COL),
    ), ("match_id", "round_seq", "pick_idx")),
    ("player_round", (
        ("match_id", "TEXT NOT NULL"), ("round_seq", "INTEGER NOT NULL"),
        ("player_key", "TEXT NOT NULL"), ("hp", "INTEGER"), ("level_badge", "INTEGER"),
        ("alive", "INTEGER"), ("standing", "INTEGER"), ("conf", "REAL"), ("src", _SRC_COL),
    ), ("match_id", "round_seq", "player_key")),
    ("event", (
        ("id", "INTEGER"), ("match_id", "TEXT NOT NULL"), ("ts", "REAL"),
        ("round_seq", "INTEGER"), ("kind", "TEXT NOT NULL"), ("payload_json", "TEXT"),
        ("src", _SRC_COL),
    ), ("id",)),
    ("frame", (
        ("frame_id", "TEXT"), ("match_id", "TEXT NOT NULL"), ("round_seq", "INTEGER"),
        ("phase", "TEXT"), ("ts", "REAL"), ("relpath", "TEXT"), ("sha256", "TEXT"),
        ("width", "INTEGER"), ("height", "INTEGER"), ("kept_reason", "TEXT"),
    ), ("frame_id",)),
    ("obs", (
        ("id", "INTEGER"), ("match_id", "TEXT NOT NULL"), ("round_seq", "INTEGER"),
        ("phase", "TEXT"), ("field", "TEXT NOT NULL"), ("value_json", "TEXT"),
        ("conf", "REAL"), ("src", _SRC_COL), ("extractor_version", "TEXT"),
        ("frame_id", "TEXT"), ("ts", "REAL"),
    ), ("id",)),
    ("gt_board", (
        ("match_id", "TEXT NOT NULL"), ("player_key", "TEXT NOT NULL"),
        ("source", "TEXT NOT NULL"), ("champion_api", "TEXT"), ("star", "INTEGER"),
        ("items_json", "TEXT"), ("cost", "INTEGER"),
    ), ()),
    ("gt_player", (
        ("match_id", "TEXT NOT NULL"), ("player_key", "TEXT NOT NULL"),
        ("placement", "INTEGER"), ("level", "INTEGER"), ("last_round", "INTEGER"),
        ("gold_left", "INTEGER"), ("damage_to_players", "INTEGER"),
        ("eliminated_at", "REAL"),
    ), ("match_id", "player_key")),
    ("accuracy", (
        ("match_id", "TEXT NOT NULL"), ("field", "TEXT NOT NULL"), ("n", "INTEGER"),
        ("correct", "INTEGER"), ("coverage", "REAL"),
        ("extractor_version", "TEXT NOT NULL DEFAULT ''"), ("computed_at", "REAL"),
    ), ("match_id", "field", "extractor_version")),
)

TABLE_NAMES = tuple(t[0] for t in TABLES)
COLUMNS = {name: tuple(c[0] for c in cols) for name, cols, _pk in TABLES}
PRIMARY_KEYS = {name: pk for name, _cols, pk in TABLES}

# Secondary indexes for the read paths (per-match, per-round fetches).
INDEXES = (
    ("ix_unit_obs_round", "unit_obs", ("match_id", "round_seq", "phase", "player_key")),
    ("ix_event_match", "event", ("match_id", "round_seq", "ts")),
    ("ix_frame_match", "frame", ("match_id", "round_seq")),
    ("ix_obs_match", "obs", ("match_id", "round_seq")),
    ("ix_gt_board_match", "gt_board", ("match_id", "source")),
    ("ix_match_started", "match", ("started_at",)),
)


def _create_table(name, cols, pk):
    body = [f"{c} {t}" for c, t in cols]
    if pk == ("id",):  # rowid alias: INTEGER PRIMARY KEY autoassigns
        body[0] = "id INTEGER PRIMARY KEY"
    elif pk:
        body.append(f"PRIMARY KEY ({', '.join(pk)})")
    return f"CREATE TABLE IF NOT EXISTS {name} (\n    " + ",\n    ".join(body) + "\n)"


def ddl_v1():
    """Every CREATE statement of schema v1, tables then indexes."""
    stmts = [_create_table(*t) for t in TABLES]
    stmts += [f"CREATE INDEX IF NOT EXISTS {ix} ON {table} ({', '.join(cols)})"
              for ix, table, cols in INDEXES]
    return tuple(stmts)


# Forward-only migrations keyed on schema_meta.schema_version: MIGRATIONS[v]
# takes a database at v - 1 to v. A database newer than SCHEMA_VERSION is
# refused (never downgraded); a later slice appends MIGRATIONS[2] and bumps
# SCHEMA_VERSION, it never edits an applied step.
MIGRATIONS = {1: ddl_v1()}
