"""tft/rounds/store.py - the TFT per-round store: one writer, many readers.

Contract: docs/TFT_PROGRAM.md section 2 (storage) over the section 1.5 tables
declared in `tft/rounds/schema.py`. LLM-free: stdlib plus the repo's one
sanctioned atomic writer (`core.polled_json`, RM-258) for export files.

Writer. `RoundStore.open(path=None)` opens `data/tft/tft_rounds.db` (gitignored)
in WAL mode with a 5 s busy timeout and starts ONE daemon writer thread fed by a
bounded queue. Every public write validates its input in the caller's thread,
enqueues a closure and returns at once - True when enqueued, False when the row
was dropped. Nothing here raises into the caller's poll loop:

  * invalid input (unknown field, src outside the closed enum, a value claimed
    'absent', a conf outside 0..1 or an llm_fallback conf above 0.5, a player
    key that is not a 12-hex HMAC key, a JSON payload carrying an identity
    shape) is dropped and counted as `invalid`;
  * a full queue drops the row (`queue_full`), so a stalled disk never blocks
    the TFT poll thread;
  * a database error inside the writer rolls back that ONE row (a savepoint per
    row) and keeps the rest of the batch (`write_errors`);
  * each failure kind logs ONE warning per streak and one info line when the
    streak ends (LEDGER 1309 / 1300: TFT writers that could not report failure).

Log lines and validation messages name a field and a rule, never a value, so a
rejected identity is never echoed into `logs/` (section 1.2).

Readers open their own read-only connections (`mode=ro`), so the dashboard can
read while the poll thread writes. `flush()` waits until everything enqueued
before it has been applied; a reader that must see its own writes calls it.

Identity (section 1.2): players are `player_key(identity, salt)` = the first 12
hex of HMAC-SHA256 over the PUUID (or the display name when the PUUID is
absent) with the per-install salt in gitignored `data/tft/.salt`. The store
accepts no other player key. `export_fixture` maps keys to P1..P8 (P1 = local),
makes timestamps relative to the match start, replaces game_id / match_id,
drops frames, and refuses to write unless `scrub_violations` passes.
"""
from __future__ import annotations

import contextlib
import csv
import hashlib
import hmac
import io
import json
import logging
import queue
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, NamedTuple, Optional, Sequence

from core.polled_json import atomic_write_bytes
from tft.rounds import schema as rs

_log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
WRITER_THREAD_NAME = "tft-rounds-writer"
QUEUE_MAX = 4096
BATCH_MAX = 512
BUSY_TIMEOUT_MS = 5000
FIXTURE_GAME_ID = 1  # the stable game_id placeholder of every exported fixture


def default_db_path() -> Path:
    return REPO_ROOT / "data" / "tft" / "tft_rounds.db"


def default_salt_path() -> Path:
    return REPO_ROOT / "data" / "tft" / ".salt"


def default_exports_dir() -> Path:
    return REPO_ROOT / "data" / "tft" / "exports"


class Env(NamedTuple):
    """One measured value with its section 1.1 confidence and source."""

    value: Any
    conf: Optional[float]
    src: str


class ScrubError(ValueError):
    """export_fixture found an identity shape; nothing was written."""

    def __init__(self, violations):
        self.violations = list(violations)
        super().__init__(f"fixture scrub failed: {len(self.violations)} violation(s): "
                         + "; ".join(self.violations[:5]))


# ---------------------------------------------------------------- identity


def player_key(identity: str, salt: bytes) -> str:
    """section 1.2: first 12 hex of HMAC-SHA256(salt, PUUID or display name)."""
    if not isinstance(identity, str) or not identity:
        raise ValueError("player_key needs a non-empty identity string")
    if not isinstance(salt, (bytes, bytearray)) or len(salt) < 8:
        raise ValueError("player_key needs a salt of at least 8 bytes")
    return hmac.new(bytes(salt), identity.encode("utf-8"), hashlib.sha256).hexdigest()[:12]


def load_salt(path=None) -> bytes:
    """The per-install salt, created (32 random bytes) on first use. If it cannot
    be persisted, an in-memory salt is returned and one warning logged: keys then
    stay stable for this process only."""
    p = Path(path) if path is not None else default_salt_path()
    for _attempt in range(2):
        try:
            data = p.read_bytes()
            if len(data) >= 16:
                return data
        except OSError:
            pass
        salt = secrets.token_bytes(32)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "xb") as fh:  # exclusive create: a concurrent creator wins
                fh.write(salt)
            return salt
        except FileExistsError:
            continue  # someone else created it: read theirs
        except OSError as exc:
            _log.warning("tft rounds: salt file not writable (%s); player keys are "
                         "stable for this process only", type(exc).__name__)
            return salt
    return salt


# Identity shapes (section 1.2 and the section 2 scrub guard). KEYS: any JSON key
# matching these is an identity field. VALUES: a 36-char UUID, a Riot id
# (name#TAG), a PUUID-like base64url token, or the words puuid / riot id /
# summoner. A bare display name without a tag cannot be recognised by shape;
# that is why names are joined to keys in memory only and never handed here.
_IDENTITY_KEY = re.compile(
    r"puuid|riot_?id|summoner|game_?name|tag_?line|player_?id|account_?id|"
    r"display_?name|player_?name|^name$", re.IGNORECASE)
_UUID36 = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_RIOT_ID = re.compile(r"[^\s#]{3,16}#[A-Za-z0-9]{2,5}(?![A-Za-z0-9])")
_ID_WORDS = re.compile(r"puuid|riot[ _]?id|summoner", re.IGNORECASE)
_TOKEN = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{70,90}(?![A-Za-z0-9_-])")
_HEX = re.compile(r"[0-9a-f]+")
_KEY12 = re.compile(r"[0-9a-f]{12}")
_FIXTURE_KEY = re.compile(r"P[1-8]")


def _string_violation(s: str) -> Optional[str]:
    if _UUID36.search(s):
        return "a 36-char UUID"
    if _RIOT_ID.search(s):
        return "a Riot id shape (name#TAG)"
    if _ID_WORDS.search(s):
        return "an identity word"
    for tok in _TOKEN.findall(s):
        if not _HEX.fullmatch(tok):
            return "a PUUID-like token"
    return None


def identity_violations(obj: Any, path: str = "$") -> list:
    """Every identity shape in a JSON-like value, as 'path: reason' strings.
    The offending VALUE is never part of the message."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            kp = f"{path}.{k}"
            if isinstance(k, str) and _IDENTITY_KEY.search(k):
                out.append(f"{kp}: identity key")
            out.extend(identity_violations(v, kp))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            out.extend(identity_violations(v, f"{path}[{i}]"))
    elif isinstance(obj, str):
        why = _string_violation(obj)
        if why:
            out.append(f"{path}: {why}")
    return out


def scrub_violations(doc: Any) -> list:
    """The fixture guard: identity_violations plus the fixture key rules -
    player_key / opponent_key are P1..P8 (or null) and no 12-hex store key
    survives anywhere."""
    out = identity_violations(doc)

    def walk(obj, path):
        if isinstance(obj, dict):
            for k, v in obj.items():
                kp = f"{path}.{k}"
                if k in ("player_key", "opponent_key") and v is not None and not (
                        isinstance(v, str) and _FIXTURE_KEY.fullmatch(v)):
                    out.append(f"{kp}: not a P1..P8 fixture key")
                walk(v, kp)
        elif isinstance(obj, (list, tuple)):
            for i, v in enumerate(obj):
                walk(v, f"{path}[{i}]")
        elif isinstance(obj, str) and _KEY12.fullmatch(obj):
            out.append(f"{path}: a raw 12-hex player key")

    walk(doc, "$")
    return out


# ---------------------------------------------------------------- validation


class _Invalid(ValueError):
    pass


_UNSET = object()
_MATCH_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
_FRAME_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}")
_FIELD = re.compile(r"[A-Za-z0-9_.:-]{1,64}")
_STEM = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_SRC = frozenset(rs.SRC_VALUES)


def _need(cond, msg):
    if not cond:
        raise _Invalid(msg)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _v_match_id(v):
    _need(isinstance(v, str) and _MATCH_ID.fullmatch(v), "match_id must be 1-64 chars [A-Za-z0-9_.-]")
    return v


def _v_key(v, name="player_key"):
    _need(isinstance(v, str) and _KEY12.fullmatch(v), f"{name} must be a 12-hex player key")
    return v


def _v_int(v, name, lo=None, hi=None, nullable=True):
    if v is None:
        _need(nullable, f"{name} is required")
        return None
    _need(_is_int(v), f"{name} must be an int")
    _need(lo is None or v >= lo, f"{name} below {lo}")
    _need(hi is None or v <= hi, f"{name} above {hi}")
    return v


def _v_seq(v, name="round_seq", nullable=False):
    return _v_int(v, name, lo=1, nullable=nullable)


def _v_num(v, name, nullable=True):
    if v is None:
        _need(nullable, f"{name} is required")
        return None
    _need((isinstance(v, (int, float)) and not isinstance(v, bool)), f"{name} must be a number")
    return float(v)


def _v_bool(v, name, nullable=True):
    if v is None:
        _need(nullable, f"{name} is required")
        return None
    _need(isinstance(v, bool) or (_is_int(v) and v in (0, 1)), f"{name} must be a bool")
    return int(v)


def _v_text(v, name, maxlen=64, nullable=True):
    if v is None:
        _need(nullable, f"{name} is required")
        return None
    _need(isinstance(v, str) and 0 < len(v) <= maxlen, f"{name} must be a 1-{maxlen} char string")
    _need(_string_violation(v) is None, f"{name} carries an identity shape")
    return v


def _v_enum(v, allowed, name, nullable=False):
    if v is None and nullable:
        return None
    _need(v in allowed, f"{name} is outside its closed enum")
    return v


def _v_src(v, name="src"):
    _need(isinstance(v, str) and v in _SRC, f"{name} is outside the closed src enum")
    return v


def _v_conf(conf, src, name="conf"):
    if src == rs.ABSENT:
        _need(conf is None, f"{name} must be null when src is absent")
        return None
    _need(isinstance(conf, (int, float)) and not isinstance(conf, bool), f"{name} is required")
    conf = float(conf)
    _need(0.0 <= conf <= 1.0, f"{name} must be within 0..1")
    _need(src != "llm_fallback" or conf <= rs.LLM_CONF_CAP, f"{name} above the llm_fallback cap")
    return conf


def _v_pair(conf, src, value=_UNSET, name="conf"):
    """A row-level (conf, src) pair; with a value, the absent rule too."""
    src = _v_src(src, name.replace("conf", "src"))
    if value is not _UNSET:
        _need((value is None) == (src == rs.ABSENT), "a null value pairs with src absent, only")
    return _v_conf(conf, src, name), src


def _v_json(v, name):
    bad = identity_violations(v)
    _need(not bad, f"{name} carries an identity shape")
    try:
        return json.dumps(v, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        raise _Invalid(f"{name} is not JSON-serialisable") from None


def _v_str_list(v, name, nullable=True):
    if v is None:
        _need(nullable, f"{name} is required")
        return None
    _need(isinstance(v, (list, tuple)), f"{name} must be a list")
    for x in v:
        _v_text(x, name, nullable=False)
    return _v_json(list(v), name)


def _v_env(e, name, typ):
    """Coerce one section 1.1 envelope to its (value, conf, src) columns."""
    if e is None:
        return None, None, rs.ABSENT
    _need(isinstance(e, tuple) and len(e) == 3, f"{name} must be Env(value, conf, src) or None")
    value, conf, src = e
    src = _v_src(src, name + "_src")
    _need((value is None) == (src == rs.ABSENT), f"{name}: a null value pairs with src absent, only")
    conf = _v_conf(conf, src, name + "_conf")
    if value is None:
        return None, None, src
    if typ is bool:
        value = _v_bool(value, name, nullable=False)
    elif typ is int:
        value = _v_int(value, name, nullable=False)
    else:
        value = _v_text(value, name, nullable=False)
    if name == "kind":
        _v_enum(value, rs.ROUND_KINDS, name)
    elif name == "verdict":
        _v_enum(value, rs.VERDICTS, name)
    elif name == "opponent_key":
        _v_key(value, name)
    return value, conf, src


def _v_relpath(v):
    _need(isinstance(v, str) and 0 < len(v) <= 260 and v.isascii(), "relpath must be an ASCII path")
    parts = v.replace("\\", "/").split("/")
    _need(not v.startswith(("/", "\\")) and ":" not in v and ".." not in parts,
          "relpath must be relative to data/tft/frames")
    return "/".join(parts)


def _env_cols(name, trio):
    return {name: trio[0], name + "_conf": trio[1], name + "_src": trio[2]}


# ---------------------------------------------------------------- SQL helpers


def _upsert_sql(table, cols, key, update=None, coalesce=False):
    update = [c for c in (cols if update is None else update) if c not in key]
    sql = (f"INSERT INTO {table} ({', '.join(cols)}) "
           f"VALUES ({', '.join('?' * len(cols))}) ON CONFLICT ({', '.join(key)}) ")
    if not update:
        return sql + "DO NOTHING"
    if coalesce:
        sets = ", ".join(f"{c} = COALESCE(excluded.{c}, {table}.{c})" for c in update)
    else:
        sets = ", ".join(f"{c} = excluded.{c}" for c in update)
    return sql + "DO UPDATE SET " + sets


def _insert_sql(table, cols, replace=False):
    verb = "INSERT OR REPLACE" if replace else "INSERT"
    return f"{verb} INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"


def _touch_round(conn, match_id, round_seq):
    if round_seq is not None:
        conn.execute("INSERT INTO round (match_id, round_seq) VALUES (?, ?) "
                     "ON CONFLICT (match_id, round_seq) DO NOTHING", (match_id, round_seq))


_JSON_COLS = {"items_json": "items", "offered_json": "offered", "payload_json": "payload",
              "value_json": "value"}


def _row(r) -> dict:
    d = dict(r)
    for col, key in _JSON_COLS.items():
        if col in d:
            raw = d.pop(col)
            d[key] = None if raw is None else json.loads(raw)
    if "gt_sources" in d:
        d["gt_sources"] = json.loads(d["gt_sources"] or "[]")
    return d


def _read_version(conn) -> int:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' "
                        "AND name = 'schema_meta'").fetchone():
        return 0
    row = conn.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
    if row is None:
        return 0
    try:
        return int(row[0])
    except (TypeError, ValueError):
        raise sqlite3.DatabaseError("schema_meta.schema_version is not an integer") from None


def _migrate(conn):
    """Forward-only: apply MIGRATIONS[v] for every v above the stored version."""
    current = _read_version(conn)
    if current > rs.SCHEMA_VERSION:
        raise sqlite3.DatabaseError(
            f"schema_version {current} is newer than this code's {rs.SCHEMA_VERSION}; refused")
    for v in range(current + 1, rs.SCHEMA_VERSION + 1):
        conn.execute("BEGIN IMMEDIATE")
        try:
            for stmt in rs.MIGRATIONS[v]:
                conn.execute(stmt)
            conn.execute("INSERT INTO schema_meta (key, value) VALUES ('schema_version', ?) "
                         "ON CONFLICT (key) DO UPDATE SET value = excluded.value", (str(v),))
            conn.execute("INSERT OR IGNORE INTO schema_meta (key, value) VALUES ('created_at', ?)",
                         (repr(time.time()),))
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise


def _atomic_write_text(path: Path, text: str, encoding="ascii"):
    # RM-258 / RM-261: the one sanctioned tmp + rename (per-writer scratch name,
    # WinError 5 retry, fsync); encoded here so LF stays LF on Windows.
    atomic_write_bytes(Path(path), text.encode(encoding))


class _Streak:
    """One warning per failure streak, one info line when it ends."""

    def __init__(self, what):
        self.what = what
        self.n = 0
        self._lock = threading.Lock()

    def fail(self, detail, count=1):
        with self._lock:
            first = self.n == 0
            self.n += count
        if first:
            _log.warning("tft rounds store: %s (%s); further drops this streak are counted, "
                         "not logged", self.what, detail)

    def ok(self):
        with self._lock:
            n, self.n = self.n, 0
        if n:
            _log.info("tft rounds store: %s streak ended after %d dropped row(s)", self.what, n)


class _Op(NamedTuple):
    label: str
    fn: Callable


class _Barrier:
    def __init__(self):
        self.event = threading.Event()


_STOP = object()
_TS_KEYS = frozenset({"started_at", "ended_at", "planning_ts", "combat_ts", "end_ts", "ts",
                      "computed_at"})


# ---------------------------------------------------------------- the store


class RoundStore:
    """The per-round TFT store (section 2). Build with RoundStore.open()."""

    def __init__(self, path: Path, readonly: bool, queue_max: int):
        self.path = Path(path)
        self.readonly = readonly
        self._q: queue.Queue = queue.Queue(maxsize=max(1, int(queue_max)))
        self._closed = False
        self._error: Optional[str] = None
        self._ready = threading.Event()
        self._run_gate = threading.Event()  # cleared only by tests, to stall the writer
        self._run_gate.set()
        self._thread: Optional[threading.Thread] = None
        self._stats_lock = threading.Lock()
        self._stats = dict.fromkeys(("enqueued", "written", "invalid", "queue_full",
                                     "write_errors", "closed", "unavailable"), 0)
        self._streaks = {k: _Streak(w) for k, w in (
            ("invalid", "invalid write dropped"), ("queue_full", "write queue full, row dropped"),
            ("write_error", "database write failed, row dropped"),
            ("closed", "write after close dropped"), ("unavailable", "store unavailable, row dropped"),
            ("read", "read failed"))}

    # -- lifecycle

    @classmethod
    def open(cls, path=None, *, readonly: bool = False, queue_max: int = QUEUE_MAX,
             start_timeout: float = 15.0) -> "RoundStore":
        """Open (and create / migrate) the store. Never raises: a store that
        cannot open reports ok False with .error, drops writes, reads empty."""
        store = cls(Path(path) if path is not None else default_db_path(), readonly, queue_max)
        if readonly:
            store._probe_readonly()
        else:
            store._thread = threading.Thread(target=store._writer_main, name=WRITER_THREAD_NAME,
                                             daemon=True)
            store._thread.start()
            if not store._ready.wait(start_timeout):
                store._error = "writer did not start in time"
        if store._error:
            _log.warning("tft rounds store: not available (%s)", store._error)
        return store

    @property
    def ok(self) -> bool:
        return self._error is None and (self.readonly or self._ready.is_set())

    @property
    def error(self) -> Optional[str]:
        return self._error

    def stats(self) -> dict:
        with self._stats_lock:
            return dict(self._stats)

    def flush(self, timeout: float = 10.0) -> bool:
        """Wait until every write enqueued before this call is applied."""
        t = self._thread
        if t is None or not t.is_alive():
            return True
        b = _Barrier()
        try:
            self._q.put(b, timeout=timeout)
        except queue.Full:
            return False
        return b.event.wait(timeout)

    def close(self, timeout: float = 10.0) -> None:
        if self._closed:
            return
        self._closed = True
        t = self._thread
        if t is not None and t.is_alive():
            with contextlib.suppress(queue.Full):
                self._q.put(_STOP, timeout=timeout)
            t.join(timeout)

    # -- writer thread

    def _connect_rw(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=BUSY_TIMEOUT_MS / 1000.0,
                               isolation_level=None)
        try:
            conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
            current = _read_version(conn)
            if current > rs.SCHEMA_VERSION:  # refuse BEFORE the WAL pragma touches the file
                raise sqlite3.DatabaseError(f"schema_version {current} is newer than this "
                                            f"code's {rs.SCHEMA_VERSION}; refused")
            row = conn.execute("PRAGMA journal_mode = WAL").fetchone()
            if not row or str(row[0]).lower() != "wal":  # RM-413: read what SQLite adopted
                _log.warning("tft rounds store: journal_mode is %s, not wal; a reader can "
                             "now block the writer", row[0] if row else "unknown")
            conn.execute("PRAGMA synchronous = NORMAL")
            _migrate(conn)
        except BaseException:
            conn.close()
            raise
        return conn

    def _writer_main(self):
        try:
            conn = self._connect_rw()
        except Exception as exc:  # noqa: BLE001 - fail-soft open by contract
            self._error = f"{type(exc).__name__}: {exc}"
            self._ready.set()
            return
        self._ready.set()
        try:
            stop = False
            while not stop:
                item = self._q.get()
                self._run_gate.wait()
                batch = []
                while True:
                    if item is _STOP:
                        stop = True
                        break
                    if isinstance(item, _Barrier):
                        self._apply(conn, batch)
                        batch = []
                        item.event.set()
                    else:
                        batch.append(item)
                        if len(batch) >= BATCH_MAX:
                            break
                    try:
                        item = self._q.get_nowait()
                    except queue.Empty:
                        break
                self._apply(conn, batch)
        finally:
            with contextlib.suppress(sqlite3.Error):
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()
            while True:  # release anyone still waiting on a barrier
                try:
                    item = self._q.get_nowait()
                except queue.Empty:
                    break
                if isinstance(item, _Barrier):
                    item.event.set()

    def _apply(self, conn, batch):
        if not batch:
            return
        try:
            conn.execute("BEGIN")
        except sqlite3.Error as exc:
            self._write_failed(len(batch), exc)
            return
        done = 0
        for op in batch:
            try:
                conn.execute("SAVEPOINT op")
                try:
                    op.fn(conn)
                except Exception:
                    conn.execute("ROLLBACK TO op")
                    conn.execute("RELEASE op")
                    raise
                conn.execute("RELEASE op")
                done += 1
            except Exception as exc:  # noqa: BLE001 - one bad row never stops the batch
                self._write_failed(1, exc, op.label)
        try:
            conn.execute("COMMIT")
        except sqlite3.Error as exc:
            with contextlib.suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
            self._write_failed(done, exc)
            return
        if done:
            self._bump("written", done)
            self._streaks["write_error"].ok()

    def _write_failed(self, n, exc, label="batch"):
        if n:
            self._bump("write_errors", n)
            self._streaks["write_error"].fail(f"{label}: {type(exc).__name__}: {exc}", n)

    # -- enqueue

    def _bump(self, key, n=1):
        with self._stats_lock:
            self._stats[key] += n

    def _drop(self, kind, detail):
        self._bump(kind)
        self._streaks[kind].fail(detail)
        return False

    def _submit(self, label, build) -> bool:
        """Validate (build() raises _Invalid) and enqueue; never raises."""
        if self._closed:
            return self._drop("closed", label)
        if self.readonly or self._error is not None:
            return self._drop("unavailable", label)
        try:
            fn = build()
        except _Invalid as exc:
            return self._drop("invalid", f"{label}: {exc}")
        except Exception as exc:  # noqa: BLE001 - a validator bug must not reach the poll loop
            return self._drop("invalid", f"{label}: {type(exc).__name__}")
        try:
            self._q.put_nowait(_Op(label, fn))
        except queue.Full:
            return self._drop("queue_full", label)
        self._bump("enqueued")
        self._streaks["invalid"].ok()
        self._streaks["queue_full"].ok()
        return True

    # -- writer API (section 2)

    _MATCH_META = ("match_id", "game_id", "set_id", "set_core_name", "queue_id", "queue_kind",
                   "started_at", "capture_profile", "extractor_version", "rc_commit",
                   "gt_status", "gt_sources")

    def begin_match(self, meta: dict) -> Optional[str]:
        """Create the match row; returns its match_id, or None when dropped."""
        out = {}

        def build():
            _need(isinstance(meta, dict), "meta must be a dict")
            _need(not identity_violations(meta), "meta carries an identity shape")
            unknown = set(meta) - set(self._MATCH_META)
            _need(not unknown, "meta has a field outside the match table")
            started = _v_num(meta.get("started_at"), "started_at")
            started = time.time() if started is None else started
            mid = meta.get("match_id")
            if mid is None:
                mid = time.strftime("%Y%m%d-%H%M%S", time.localtime(started)) + "-" + secrets.token_hex(3)
            row = {
                "match_id": _v_match_id(mid),
                "game_id": _v_int(meta.get("game_id"), "game_id", lo=0),
                "set_id": _v_int(meta.get("set_id"), "set_id", lo=0),
                "set_core_name": _v_text(meta.get("set_core_name"), "set_core_name"),
                "queue_id": _v_int(meta.get("queue_id"), "queue_id", lo=0),
                "started_at": started,
                "capture_profile": _v_text(meta.get("capture_profile"), "capture_profile"),
                "extractor_version": _v_text(meta.get("extractor_version"), "extractor_version"),
                "rc_commit": _v_text(meta.get("rc_commit"), "rc_commit"),
            }
            qk = meta.get("queue_kind")
            row["queue_kind"] = (rs.queue_kind_for(row["queue_id"]) if qk is None
                                 else _v_enum(qk, rs.QUEUE_KINDS, "queue_kind"))
            if "gt_status" in meta:
                row["gt_status"] = _v_enum(meta["gt_status"], rs.GT_STATUS, "gt_status")
            if "gt_sources" in meta:
                row["gt_sources"] = self._gt_sources_json(meta["gt_sources"])
            cols = tuple(row)
            sql = _upsert_sql("match", cols, ("match_id",))
            vals = tuple(row.values())
            out["mid"] = row["match_id"]
            return lambda conn: conn.execute(sql, vals)

        return out["mid"] if self._submit("begin_match", build) else None

    @staticmethod
    def _gt_sources_json(v):
        _need(isinstance(v, (list, tuple)) and all(s in rs.GT_SOURCES for s in v),
              "gt_sources must list gt_board sources")
        return json.dumps(sorted(set(v)))

    def upsert_player(self, match_id, player_key, *, slot=_UNSET, is_local=_UNSET,
                      final_standing=_UNSET, eliminated_round_seq=_UNSET) -> bool:
        """Create or update one player row; only the fields passed are written."""
        def build():
            row = {"match_id": _v_match_id(match_id), "player_key": _v_key(player_key)}
            if slot is not _UNSET:
                row["slot"] = _v_int(slot, "slot", lo=1, hi=8)
            if is_local is not _UNSET:
                row["is_local"] = _v_bool(is_local, "is_local", nullable=False)
            if final_standing is not _UNSET:
                row.update(_env_cols("final_standing", _v_env(final_standing, "final_standing", int)))
            if eliminated_round_seq is not _UNSET:
                row["eliminated_round_seq"] = _v_seq(eliminated_round_seq, "eliminated_round_seq",
                                                     nullable=True)
            sql = _upsert_sql("player", tuple(row), ("match_id", "player_key"))
            vals = tuple(row.values())
            return lambda conn: conn.execute(sql, vals)

        return self._submit("upsert_player", build)

    def upsert_round(self, match_id, round_seq, **fields) -> bool:
        """Create the round row and write the envelopes / plain fields passed:
        an envelope is Env(value, conf, src) or None (= absent); label is text,
        planning_ts / combat_ts / end_ts are epoch seconds."""
        def build():
            row = {"match_id": _v_match_id(match_id), "round_seq": _v_seq(round_seq)}
            for name, v in fields.items():
                if name in rs.ROUND_ENVELOPES:
                    row.update(_env_cols(name, _v_env(v, name, rs.ROUND_ENVELOPES[name])))
                elif name == "label":
                    row[name] = _v_text(v, name, maxlen=16)
                elif name in rs.ROUND_PLAIN:
                    row[name] = _v_num(v, name)
                else:
                    raise _Invalid("upsert_round got a field outside the round table")
            sql = _upsert_sql("round", tuple(row), ("match_id", "round_seq"))
            vals = tuple(row.values())
            return lambda conn: conn.execute(sql, vals)

        return self._submit("upsert_round", build)

    _UNIT_FIELDS = frozenset(("zone", "hex_row", "hex_col", "bench_idx", "champion_api", "star",
                              "items", "cost", "conf", "src", "pos_conf", "pos_src", "frame_id"))
    _UNIT_COLS = ("match_id", "round_seq", "phase", "player_key", "zone", "hex_row", "hex_col",
                  "bench_idx", "champion_api", "star", "items_json", "cost", "conf", "src",
                  "pos_conf", "pos_src", "frame_id")

    def put_units(self, match_id, round_seq, phase, player_key, units: Sequence[dict],
                  zone=None) -> bool:
        """Replace one player's units for (round, phase): every zone, or only
        `zone` when given. A unit is a dict of unit_obs fields (items = list)."""
        def build():
            mid, seq = _v_match_id(match_id), _v_seq(round_seq)
            ph = _v_enum(phase, rs.UNIT_PHASES, "phase")
            key = _v_key(player_key)
            scope = _v_enum(zone, rs.ZONES, "zone", nullable=True)
            _need(isinstance(units, (list, tuple)), "units must be a list")
            rows = []
            for u in units:
                _need(isinstance(u, dict) and not set(u) - self._UNIT_FIELDS,
                      "a unit has a field outside unit_obs")
                z = _v_enum(u.get("zone", scope), rs.ZONES, "zone")
                _need(scope is None or z == scope, "a unit's zone differs from the zone rewritten")
                conf, src = _v_pair(u.get("conf"), u.get("src"))
                pconf, psrc = _v_pair(u.get("pos_conf"), u.get("pos_src", rs.ABSENT), name="pos_conf")
                fid = u.get("frame_id")
                _need(fid is None or (isinstance(fid, str) and _FRAME_ID.fullmatch(fid)), "frame_id format")
                rows.append((mid, seq, ph, key, z,
                             _v_int(u.get("hex_row"), "hex_row", 0, rs.HEX_ROWS - 1),
                             _v_int(u.get("hex_col"), "hex_col", 0, rs.HEX_COLS - 1),
                             _v_int(u.get("bench_idx"), "bench_idx", 0, rs.BENCH_SLOTS - 1),
                             _v_text(u.get("champion_api"), "champion_api"),
                             _v_int(u.get("star"), "star", 1, 4),
                             _v_str_list(u.get("items"), "items"),
                             _v_int(u.get("cost"), "cost", 0, 10),
                             conf, src, pconf, psrc, fid))
            dele = ("DELETE FROM unit_obs WHERE match_id = ? AND round_seq = ? AND phase = ? "
                    "AND player_key = ?")
            dargs = (mid, seq, ph, key)
            if scope is not None:
                dele += " AND zone = ?"
                dargs += (scope,)
            ins = _insert_sql("unit_obs", self._UNIT_COLS)

            def fn(conn):
                _touch_round(conn, mid, seq)
                conn.execute(dele, dargs)
                conn.executemany(ins, rows)
            return fn

        return self._submit("put_units", build)

    _OFFER_FIELDS = frozenset(("slot", "kind", "champion_api", "name_text", "cost", "bought",
                               "bought_conf", "bought_src", "conf", "src"))
    _OFFER_COLS = ("match_id", "round_seq", "refresh_idx", "slot", "kind", "champion_api",
                   "name_text", "cost", "bought", "bought_conf", "bought_src", "conf", "src")

    def put_shop_refresh(self, match_id, round_seq, refresh_idx, *, cause="unknown", ts=None,
                         gold_before=None, gold_after=None, conf=None, src=None,
                         offers: Sequence[dict] = ()) -> bool:
        """Write one shop refresh and replace its offers (slots 0-4)."""
        def build():
            mid, seq = _v_match_id(match_id), _v_seq(round_seq)
            idx = _v_int(refresh_idx, "refresh_idx", lo=0, nullable=False)
            c, s = _v_pair(conf, src)
            ref = (mid, seq, idx, _v_enum(cause, rs.REFRESH_CAUSES, "cause"),
                   time.time() if ts is None else _v_num(ts, "ts"),
                   _v_int(gold_before, "gold_before"), _v_int(gold_after, "gold_after"), c, s)
            _need(isinstance(offers, (list, tuple)), "offers must be a list")
            rows, slots = [], set()
            for o in offers:
                _need(isinstance(o, dict) and not set(o) - self._OFFER_FIELDS,
                      "an offer has a field outside shop_offer")
                slot = _v_int(o.get("slot"), "slot", 0, 4, nullable=False)
                _need(slot not in slots, "two offers share a slot")
                slots.add(slot)
                oc, osrc = _v_pair(o.get("conf"), o.get("src"))
                bc, bsrc = _v_pair(o.get("bought_conf"), o.get("bought_src", rs.ABSENT),
                                   name="bought_conf")
                rows.append((mid, seq, idx, slot, _v_enum(o.get("kind"), rs.OFFER_KINDS, "kind"),
                             _v_text(o.get("champion_api"), "champion_api"),
                             _v_text(o.get("name_text"), "name_text"),
                             _v_int(o.get("cost"), "cost", 0, 10),
                             _v_bool(o.get("bought"), "bought"), bc, bsrc, oc, osrc))
            up = _upsert_sql("shop_refresh", rs.COLUMNS["shop_refresh"],
                             ("match_id", "round_seq", "refresh_idx"))
            ins = _insert_sql("shop_offer", self._OFFER_COLS)

            def fn(conn):
                _touch_round(conn, mid, seq)
                conn.execute(up, ref)
                conn.execute("DELETE FROM shop_offer WHERE match_id = ? AND round_seq = ? "
                             "AND refresh_idx = ?", (mid, seq, idx))
                conn.executemany(ins, rows)
            return fn

        return self._submit("put_shop_refresh", build)

    def put_shop_odds(self, match_id, round_seq, level, odds: Sequence, *, conf, src) -> bool:
        """The odds strip p1..p5 (percent) read at `level`."""
        def build():
            mid, seq = _v_match_id(match_id), _v_seq(round_seq)
            _need(isinstance(odds, (list, tuple)) and len(odds) == 5, "odds must be 5 numbers")
            ps = [_v_num(p, "odds") for p in odds]
            _need(all(p is None or 0.0 <= p <= 100.0 for p in ps), "odds must be percents")
            c, s = _v_pair(conf, src)
            row = (mid, seq, _v_int(level, "level", 1, 10, nullable=False), *ps, c, s)
            sql = _insert_sql("shop_odds", rs.COLUMNS["shop_odds"], replace=True)

            def fn(conn):
                _touch_round(conn, mid, seq)
                conn.execute(sql, row)
            return fn

        return self._submit("put_shop_odds", build)

    _TRAIT_FIELDS = frozenset(("trait_api", "count", "tier_index", "active", "conf", "src"))

    def put_traits(self, match_id, round_seq, phase, player_key, traits: Sequence[dict]) -> bool:
        """Replace one player's trait states for (round, phase)."""
        def build():
            mid, seq = _v_match_id(match_id), _v_seq(round_seq)
            ph = _v_enum(phase, rs.UNIT_PHASES, "phase")
            key = _v_key(player_key)
            _need(isinstance(traits, (list, tuple)), "traits must be a list")
            rows, seen = [], set()
            for t in traits:
                _need(isinstance(t, dict) and not set(t) - self._TRAIT_FIELDS,
                      "a trait has a field outside trait_state")
                api = _v_text(t.get("trait_api"), "trait_api", nullable=False)
                _need(api not in seen, "a trait is listed twice")
                seen.add(api)
                c, s = _v_pair(t.get("conf"), t.get("src"))
                rows.append((mid, seq, ph, key, api, _v_int(t.get("count"), "count", lo=0),
                             _v_int(t.get("tier_index"), "tier_index", lo=0),
                             _v_bool(t.get("active"), "active"), c, s))
            ins = _insert_sql("trait_state", rs.COLUMNS["trait_state"])

            def fn(conn):
                _touch_round(conn, mid, seq)
                conn.execute("DELETE FROM trait_state WHERE match_id = ? AND round_seq = ? "
                             "AND phase = ? AND player_key = ?", (mid, seq, ph, key))
                conn.executemany(ins, rows)
            return fn

        return self._submit("put_traits", build)

    def put_augment(self, match_id, round_seq, pick_idx, offered, chosen_api, *, conf, src) -> bool:
        """One augment choice: the offered api names and the one chosen."""
        def build():
            mid, seq = _v_match_id(match_id), _v_seq(round_seq)
            c, s = _v_pair(conf, src)
            row = (mid, seq, _v_int(pick_idx, "pick_idx", lo=0, nullable=False),
                   _v_str_list(offered, "offered"), _v_text(chosen_api, "chosen_api"), c, s)
            sql = _insert_sql("augment", rs.COLUMNS["augment"], replace=True)

            def fn(conn):
                _touch_round(conn, mid, seq)
                conn.execute(sql, row)
            return fn

        return self._submit("put_augment", build)

    def put_player_round(self, match_id, round_seq, player_key, *, hp=None, level_badge=None,
                         alive=None, standing=None, conf=None, src=None) -> bool:
        """One player's HP / level badge / alive / standing for a round."""
        def build():
            mid, seq = _v_match_id(match_id), _v_seq(round_seq)
            c, s = _v_pair(conf, src)
            row = (mid, seq, _v_key(player_key), _v_int(hp, "hp"),
                   _v_int(level_badge, "level_badge", 1, 10), _v_bool(alive, "alive"),
                   _v_int(standing, "standing", 1, 8), c, s)
            sql = _insert_sql("player_round", rs.COLUMNS["player_round"], replace=True)

            def fn(conn):
                _touch_round(conn, mid, seq)
                conn.execute(sql, row)
            return fn

        return self._submit("put_player_round", build)

    def put_event(self, match_id, kind, payload=None, *, ts=None, round_seq=None, src=None) -> bool:
        """Append one event row (section 1.5 event kinds)."""
        def build():
            mid = _v_match_id(match_id)
            seq = _v_seq(round_seq, nullable=True)
            row = (mid, time.time() if ts is None else _v_num(ts, "ts"), seq,
                   _v_enum(kind, rs.EVENT_KINDS, "kind"), _v_json(payload, "payload"),
                   _v_src(src))
            sql = _insert_sql("event", ("match_id", "ts", "round_seq", "kind", "payload_json", "src"))

            def fn(conn):
                _touch_round(conn, mid, seq)
                conn.execute(sql, row)
            return fn

        return self._submit("put_event", build)

    def put_frame(self, match_id, round_seq, phase, relpath, *, ts=None, sha256=None, width=None,
                  height=None, kept_reason=None, frame_id=None) -> Optional[str]:
        """Index one kept frame (the file lives under data/tft/frames/);
        returns its frame_id, or None when dropped."""
        out = {}

        def build():
            mid = _v_match_id(match_id)
            seq = _v_seq(round_seq, nullable=True)
            ph = _v_enum(phase, rs.CAPTURE_PHASES, "phase", nullable=True)
            fid = frame_id or f"{mid}-{seq or 0}-{ph or 'x'}-{secrets.token_hex(3)}"
            _need(isinstance(fid, str) and _FRAME_ID.fullmatch(fid), "frame_id format")
            _need(sha256 is None or (isinstance(sha256, str) and _SHA256.fullmatch(sha256)),
                  "sha256 must be 64 lowercase hex")
            row = (fid, mid, seq, ph, time.time() if ts is None else _v_num(ts, "ts"),
                   _v_relpath(relpath), sha256, _v_int(width, "width", lo=1),
                   _v_int(height, "height", lo=1), _v_text(kept_reason, "kept_reason"))
            sql = _insert_sql("frame", rs.COLUMNS["frame"], replace=True)
            out["fid"] = fid

            def fn(conn):
                _touch_round(conn, mid, seq)
                conn.execute(sql, row)
            return fn

        return out["fid"] if self._submit("put_frame", build) else None

    def record_obs(self, match_id, round_seq, phase, field, value, conf, src, frame_id=None, *,
                   ts=None, extractor_version=None) -> bool:
        """Append one raw observation (section 1.5 `obs`, append-only evidence
        the TFT-07 resolver turns into the typed tables)."""
        def build():
            mid = _v_match_id(match_id)
            seq = _v_seq(round_seq, nullable=True)
            _need(isinstance(field, str) and _FIELD.fullmatch(field) and not _IDENTITY_KEY.search(field),
                  "field must be a 1-64 char name and not an identity field")
            c, s = _v_pair(conf, src, value=value)
            _need(frame_id is None or (isinstance(frame_id, str) and _FRAME_ID.fullmatch(frame_id)),
                  "frame_id format")
            row = (mid, seq, _v_enum(phase, rs.CAPTURE_PHASES, "phase", nullable=True), field,
                   _v_json(value, "value"), c, s, _v_text(extractor_version, "extractor_version"),
                   frame_id, time.time() if ts is None else _v_num(ts, "ts"))
            sql = _insert_sql("obs", ("match_id", "round_seq", "phase", "field", "value_json",
                                      "conf", "src", "extractor_version", "frame_id", "ts"))

            def fn(conn):
                _touch_round(conn, mid, seq)
                conn.execute(sql, row)
            return fn

        return self._submit("record_obs", build)

    def end_match(self, match_id, placement=None, *, ended_at=None, gt_status=None,
                  gt_sources=None) -> bool:
        """Close the match: ended_at (default now) and, when passed, the
        placement envelope and ground-truth status."""
        def build():
            sets = {"ended_at": time.time() if ended_at is None else _v_num(ended_at, "ended_at")}
            if placement is not None:
                sets.update(_env_cols("placement", _v_env(placement, "placement", int)))
            if gt_status is not None:
                sets["gt_status"] = _v_enum(gt_status, rs.GT_STATUS, "gt_status")
            if gt_sources is not None:
                sets["gt_sources"] = self._gt_sources_json(gt_sources)
            sql = f"UPDATE match SET {', '.join(f'{c} = ?' for c in sets)} WHERE match_id = ?"
            vals = (*sets.values(), _v_match_id(match_id))
            return lambda conn: conn.execute(sql, vals)

        return self._submit("end_match", build)

    _GT_BOARD_FIELDS = frozenset(("player_key", "champion_api", "star", "items", "cost"))
    _GT_PLAYER_FIELDS = frozenset(("player_key", "placement", "level", "last_round", "gold_left",
                                   "damage_to_players", "eliminated_at"))

    def attach_ground_truth(self, match_id, source, boards: Sequence[dict],
                            players: Sequence[dict], *, gt_status=None) -> bool:
        """Post-match ground truth (TFT-08): replace this source's gt_board rows,
        merge gt_player rows (a later source never blanks an earlier value), and
        add the source to match.gt_sources."""
        def build():
            mid = _v_match_id(match_id)
            src = _v_enum(source, rs.GT_SOURCES, "source")
            status = _v_enum(gt_status, rs.GT_STATUS, "gt_status", nullable=True)
            _need(isinstance(boards, (list, tuple)) and isinstance(players, (list, tuple)),
                  "boards and players must be lists")
            brows = []
            for b in boards:
                _need(isinstance(b, dict) and not set(b) - self._GT_BOARD_FIELDS,
                      "a board row has a field outside gt_board")
                brows.append((mid, _v_key(b.get("player_key")), src,
                              _v_text(b.get("champion_api"), "champion_api"),
                              _v_int(b.get("star"), "star", 1, 4),
                              _v_str_list(b.get("items"), "items"), _v_int(b.get("cost"), "cost", 0, 10)))
            prows = []
            for p in players:
                _need(isinstance(p, dict) and not set(p) - self._GT_PLAYER_FIELDS,
                      "a player row has a field outside gt_player")
                prows.append((mid, _v_key(p.get("player_key")),
                              _v_int(p.get("placement"), "placement", 1, 8),
                              _v_int(p.get("level"), "level", 1, 10),
                              _v_int(p.get("last_round"), "last_round", lo=0),
                              _v_int(p.get("gold_left"), "gold_left", lo=0),
                              _v_int(p.get("damage_to_players"), "damage_to_players", lo=0),
                              _v_num(p.get("eliminated_at"), "eliminated_at")))
            bins = _insert_sql("gt_board", rs.COLUMNS["gt_board"])
            pup = _upsert_sql("gt_player", rs.COLUMNS["gt_player"], ("match_id", "player_key"),
                              coalesce=True)

            def fn(conn):
                conn.execute("DELETE FROM gt_board WHERE match_id = ? AND source = ?", (mid, src))
                conn.executemany(bins, brows)
                conn.executemany(pup, prows)
                row = conn.execute("SELECT gt_sources FROM match WHERE match_id = ?", (mid,)).fetchone()
                have = set(json.loads(row[0] or "[]")) if row else set()
                conn.execute("UPDATE match SET gt_sources = ? WHERE match_id = ?",
                             (json.dumps(sorted(have | {src})), mid))
                if status is not None:
                    conn.execute("UPDATE match SET gt_status = ? WHERE match_id = ?", (status, mid))
            return fn

        return self._submit("attach_ground_truth", build)

    _ACC_FIELDS = frozenset(("field", "n", "correct", "coverage", "extractor_version", "computed_at"))

    def put_accuracy(self, match_id, rows: Iterable[dict]) -> bool:
        """Per-match per-field accuracy rows (TFT-08 / section 3.4)."""
        def build():
            mid = _v_match_id(match_id)
            out = []
            for r in rows:
                _need(isinstance(r, dict) and not set(r) - self._ACC_FIELDS,
                      "an accuracy row has a field outside accuracy")
                field = r.get("field")
                _need(isinstance(field, str) and _FIELD.fullmatch(field), "field name")
                cov = _v_num(r.get("coverage"), "coverage")
                _need(cov is None or 0.0 <= cov <= 1.0, "coverage must be within 0..1")
                computed = r.get("computed_at")
                out.append((mid, field, _v_int(r.get("n"), "n", lo=0),
                            _v_int(r.get("correct"), "correct", lo=0), cov,
                            _v_text(r.get("extractor_version"), "extractor_version") or "",
                            time.time() if computed is None else _v_num(computed, "computed_at")))
            sql = _insert_sql("accuracy", rs.COLUMNS["accuracy"], replace=True)
            return lambda conn: conn.executemany(sql, out)

        return self._submit("put_accuracy", build)

    # -- read API (section 2)

    def _probe_readonly(self):
        try:
            with self._reader_conn() as conn:
                v = _read_version(conn)
            if v > rs.SCHEMA_VERSION:
                self._error = f"schema_version {v} is newer than this code's {rs.SCHEMA_VERSION}"
            elif v == 0:
                self._error = "no store schema in this file"
        except (sqlite3.Error, OSError, ValueError) as exc:
            self._error = f"{type(exc).__name__}: {exc}"

    @contextlib.contextmanager
    def _reader_conn(self):
        uri = self.path.resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=BUSY_TIMEOUT_MS / 1000.0)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
            yield conn
        finally:
            conn.close()

    def _read(self, fn, empty):
        if self._error is not None:
            return empty
        try:
            with self._reader_conn() as conn:
                result = fn(conn)
        except (sqlite3.Error, OSError, ValueError) as exc:
            self._drop_read(exc)
            return empty
        self._streaks["read"].ok()
        return result

    def _drop_read(self, exc):
        self._streaks["read"].fail(f"{type(exc).__name__}: {exc}")

    def list_matches(self, set_id=None, queue_kind=None, top4_only=False) -> list:
        """Match rows, newest first, optionally filtered."""
        where, args = [], []
        if set_id is not None:
            where.append("set_id = ?")
            args.append(set_id)
        if queue_kind is not None:
            where.append("queue_kind = ?")
            args.append(queue_kind)
        if top4_only:
            where.append("placement IS NOT NULL AND placement <= 4")
        sql = "SELECT * FROM match" + (" WHERE " + " AND ".join(where) if where else "")
        sql += " ORDER BY started_at DESC, match_id"
        return self._read(lambda conn: [_row(r) for r in conn.execute(sql, args)], [])

    def get_match(self, match_id, *, rounds: bool = True) -> Optional[dict]:
        """One whole match: {match, players, events (match-level), gt_board,
        gt_player, accuracy, rounds (bundles, see iter_rounds)}; None if absent."""
        def fn(conn):
            m = conn.execute("SELECT * FROM match WHERE match_id = ?", (match_id,)).fetchone()
            if m is None:
                return None
            q = lambda sql: [_row(r) for r in conn.execute(sql, (match_id,))]  # noqa: E731
            doc = {
                "match": _row(m),
                "players": q("SELECT * FROM player WHERE match_id = ? "
                             "ORDER BY slot IS NULL, slot, player_key"),
                "events": q("SELECT * FROM event WHERE match_id = ? AND round_seq IS NULL "
                            "ORDER BY ts, id"),
                "obs": q("SELECT * FROM obs WHERE match_id = ? AND round_seq IS NULL ORDER BY id"),
                "frames": q("SELECT * FROM frame WHERE match_id = ? AND round_seq IS NULL "
                            "ORDER BY ts, frame_id"),
                "gt_board": q("SELECT * FROM gt_board WHERE match_id = ? ORDER BY source, rowid"),
                "gt_player": q("SELECT * FROM gt_player WHERE match_id = ? "
                               "ORDER BY placement IS NULL, placement, player_key"),
                "accuracy": q("SELECT * FROM accuracy WHERE match_id = ? "
                              "ORDER BY field, extractor_version"),
            }
            if rounds:
                doc["rounds"] = self._bundles(conn, match_id)
            return doc

        return self._read(fn, None)

    def iter_rounds(self, match_id) -> Iterator[dict]:
        """Every round of a match, in order, as a bundle: the round row's
        columns plus units, shop (refreshes, each with offers), odds, traits,
        augments, players (all-8 player_round), events, frames and obs."""
        return iter(self._read(lambda conn: self._bundles(conn, match_id), []))

    def live_round(self) -> Optional[dict]:
        """The latest round bundle of the open (not ended) match, or None."""
        def fn(conn):
            m = conn.execute("SELECT match_id FROM match WHERE ended_at IS NULL "
                             "ORDER BY started_at DESC LIMIT 1").fetchone()
            if m is None:
                return None
            top = conn.execute("SELECT MAX(round_seq) FROM round WHERE match_id = ?",
                               (m[0],)).fetchone()[0]
            if top is None:
                return None
            got = self._bundles(conn, m[0], round_seq=top)
            return got[0] if got else None

        return self._read(fn, None)

    _CHILDREN = (  # bundle key, table, order
        ("units", "unit_obs", "id"),
        ("odds", "shop_odds", "level"),
        ("traits", "trait_state", "phase, player_key, trait_api"),
        ("augments", "augment", "pick_idx"),
        ("players", "player_round", "player_key"),
        ("events", "event", "ts, id"),
        ("frames", "frame", "ts, frame_id"),
        ("obs", "obs", "id"),
    )

    def _bundles(self, conn, match_id, round_seq=None) -> list:
        flt, args = "match_id = ?", [match_id]
        if round_seq is not None:
            flt += " AND round_seq = ?"
            args.append(round_seq)
        rounds = [_row(r) for r in conn.execute(
            f"SELECT * FROM round WHERE {flt} ORDER BY round_seq", args)]
        by_seq = {}
        for r in rounds:
            for key in ("units", "shop", "odds", "traits", "augments", "players", "events",
                        "frames", "obs"):
                r[key] = []
            by_seq[r["round_seq"]] = r
        for key, table, order in self._CHILDREN:
            for row in conn.execute(f"SELECT * FROM {table} WHERE {flt} ORDER BY round_seq, {order}", args):
                d = _row(row)
                if d["round_seq"] in by_seq:
                    by_seq[d["round_seq"]][key].append(d)
        refreshes = {}
        for row in conn.execute(f"SELECT * FROM shop_refresh WHERE {flt} "
                                "ORDER BY round_seq, refresh_idx", args):
            d = _row(row)
            d["offers"] = []
            if d["round_seq"] in by_seq:
                by_seq[d["round_seq"]]["shop"].append(d)
                refreshes[(d["round_seq"], d["refresh_idx"])] = d
        for row in conn.execute(f"SELECT * FROM shop_offer WHERE {flt} "
                                "ORDER BY round_seq, refresh_idx, slot", args):
            d = _row(row)
            parent = refreshes.get((d["round_seq"], d["refresh_idx"]))
            if parent is not None:
                parent["offers"].append(d)
        return rounds

    # -- exports (section 2)

    def export_fixture(self, match_id, out_dir, *, name: str = "fixture") -> Path:
        """Write a scrubbed bug-test fixture `<out_dir>/<name>.json`. Raises
        ScrubError (writing nothing) when the scrub guard finds an identity
        shape, ValueError when the match is not in the store."""
        if not (isinstance(name, str) and _STEM.fullmatch(name)):
            raise ValueError("fixture name must be 1-64 chars [A-Za-z0-9_-]")
        doc = self.get_match(match_id)
        if doc is None:
            raise ValueError("no such match in the store")
        fixture = _scrub_for_fixture(doc, name)
        bad = scrub_violations(fixture)
        if bad:
            raise ScrubError(bad)
        out = Path(out_dir) / f"{name}.json"
        _atomic_write_text(out, json.dumps(fixture, ensure_ascii=True, sort_keys=True, indent=1) + "\n")
        return out

    def export_jsonl(self, match_ids: Iterable[str], out) -> Path:
        """Analysis export (local only, default under gitignored data/tft/exports):
        per match one {"record": "match"} line, then one {"record": "round"} line
        per round bundle."""
        lines = []
        for mid in match_ids:
            doc = self.get_match(mid)
            if doc is None:
                continue
            rounds = doc.pop("rounds")
            lines.append(json.dumps({"record": "match", "match_id": mid, **doc},
                                    ensure_ascii=True, sort_keys=True))
            lines.extend(json.dumps({"record": "round", **r}, ensure_ascii=True, sort_keys=True)
                         for r in rounds)
        out = Path(out)
        _atomic_write_text(out, "".join(line + "\n" for line in lines))
        return out

    def export_csv(self, match_ids: Iterable[str], out_dir) -> list:
        """Analysis export: one CSV per section 1.5 table (schema_meta aside),
        raw columns, rows of the given matches only. Returns the files written."""
        ids = list(match_ids)
        marks = ", ".join("?" * len(ids)) or "NULL"
        tables = [t for t in rs.TABLE_NAMES if t != "schema_meta"]

        def fn(conn):
            return {t: conn.execute(f"SELECT * FROM {t} WHERE match_id IN ({marks}) ORDER BY rowid",
                                    ids).fetchall() for t in tables}

        data = self._read(fn, None)
        if data is None:
            return []
        paths = []
        for t in tables:
            buf = io.StringIO()
            w = csv.writer(buf, lineterminator="\n")
            w.writerow(rs.COLUMNS[t])
            for r in data[t]:
                w.writerow(["" if v is None else v for v in tuple(r)])
            p = Path(out_dir) / f"{t}.csv"
            _atomic_write_text(p, buf.getvalue(), encoding="utf-8")
            paths.append(p)
        return paths


def _scrub_for_fixture(doc: dict, name: str) -> dict:
    """The section 2 fixture transform (no guard here; the caller runs it)."""
    players = sorted(doc["players"], key=lambda p: (not p.get("is_local"), p.get("slot") is None,
                                                    p.get("slot") or 0, p["player_key"]))
    mapping = {}
    for p in players:
        mapping.setdefault(p["player_key"], f"P{len(mapping) + 1}")
    seen = set()

    def collect(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ("player_key", "opponent_key") and isinstance(v, str):
                    seen.add(v)
                collect(v)
        elif isinstance(obj, list):
            for v in obj:
                collect(v)

    collect(doc)
    for k in sorted(seen - set(mapping)):
        mapping[k] = f"P{len(mapping) + 1}"
    t0 = doc["match"].get("started_at") or 0.0

    def walk(obj):
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                if k == "frames":
                    continue
                if k == "frame_id":
                    out[k] = None
                elif k == "match_id":
                    out[k] = name
                elif k == "game_id":
                    out[k] = FIXTURE_GAME_ID
                elif k in _TS_KEYS and isinstance(v, (int, float)) and not isinstance(v, bool):
                    out[k] = round(v - t0, 3)
                else:
                    out[k] = walk(v)
            return out
        if isinstance(obj, list):
            return [walk(v) for v in obj]
        if isinstance(obj, str) and obj in mapping:
            return mapping[obj]
        return obj

    fixture = walk(doc)
    fixture["fixture"] = {"kind": "tft_rounds_fixture", "schema_version": rs.SCHEMA_VERSION}
    return fixture
