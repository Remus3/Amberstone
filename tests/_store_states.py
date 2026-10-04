"""P2-5 - shared fixtures for "absent / empty-but-valid / populated" stores.

A smoke suite that proves only "no store" and "full store" misses the state a
fresh install actually lands in: the store is PRESENT and EMPTY but VALID (a
JSON `{}`, a sqlite file carrying its schema and zero rows). Reads can come
back fine there while writes fail, so every runtime store under test declares
its states ONCE here-shaped and every test parametrises over them.

States:
  ABSENT     - no file at all.
  EMPTY      - valid but empty: `{}` for a JSON dict store, the real schema
               with zero rows for a sqlite store.
  POPULATED  - valid, carrying at least one row / key.
  ZERO_BYTE  - a 0-byte file. Atomic writers make it rare, but a crash between
               create and first write, or a `touch`, leaves one. Opt-in.
  NO_TABLES  - sqlite only: a real sqlite file (header written) with no
               tables. Distinct from ZERO_BYTE on disk. Opt-in.

Every builder refuses a root inside the repo checkout, so a test can only
ever materialise a store under its own tmp_path - never real data/ or
ops/runtime files.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Union

import pytest

ABSENT = "absent"
EMPTY = "empty"
POPULATED = "populated"
ZERO_BYTE = "zero_byte"
NO_TABLES = "no_tables"

THREE_STATES = (ABSENT, EMPTY, POPULATED)
JSON_STATES_WITH_ZERO_BYTE = THREE_STATES + (ZERO_BYTE,)
SQLITE_STATES_ALL = THREE_STATES + (ZERO_BYTE, NO_TABLES)

_REPO_ROOT = Path(__file__).resolve().parents[1]


def parametrize_states(states=THREE_STATES):
    """`@parametrize_states()` -> one test per state, id = the state name."""
    return pytest.mark.parametrize("state", states, ids=list(states))


def _refuse_repo_root(root: Path) -> None:
    resolved = Path(root).resolve()
    try:
        resolved.relative_to(_REPO_ROOT)
    except ValueError:
        return
    raise AssertionError(
        f"store fixture root {resolved} is inside the repo checkout; "
        "build stores under tmp_path only")


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".fixture.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


@dataclass(frozen=True)
class StoreStates:
    """One store's states, declared once. `filename` may be a callable so a
    date-keyed store (the spend ledger) resolves its name at build time."""

    name: str
    filename: Union[str, Callable[[], str]]
    make_empty: Callable[[Path], None]
    make_populated: Callable[[Path], None]
    is_sqlite: bool = False

    def path_in(self, root: Path) -> Path:
        fname = self.filename() if callable(self.filename) else self.filename
        return Path(root) / fname

    def build(self, root: Path, state: str) -> Path:
        """Materialise `state` under `root` and return the store path."""
        _refuse_repo_root(root)
        path = self.path_in(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise AssertionError(f"{self.name}: {path} already exists")
        if state == ABSENT:
            pass
        elif state == EMPTY:
            self.make_empty(path)
        elif state == POPULATED:
            self.make_populated(path)
        elif state == ZERO_BYTE:
            _write_atomic(path, b"")
        elif state == NO_TABLES:
            if not self.is_sqlite:
                raise ValueError(f"{self.name}: NO_TABLES is a sqlite-only state")
            conn = sqlite3.connect(str(path))
            try:
                conn.execute("PRAGMA user_version = 1")  # forces a header write
                conn.commit()
            finally:
                conn.close()
        else:
            raise ValueError(f"unknown store state {state!r}")
        return path


def json_store(name: str, filename, empty, populated) -> StoreStates:
    """A JSON-file store. `empty` / `populated` are payloads (or callables
    returning one, for payloads that must be built at test time)."""

    def _maker(payload):
        def make(path: Path) -> None:
            body = payload() if callable(payload) else payload
            _write_atomic(path, json.dumps(body, indent=2).encode("utf-8"))
        return make

    return StoreStates(name, filename, _maker(empty), _maker(populated))


def sqlite_store(name: str, filename, schema: Union[str, Callable[[], str]],
                 seed: Callable[[sqlite3.Connection], None]) -> StoreStates:
    """A sqlite store. EMPTY = the schema with zero rows; POPULATED = the
    schema plus `seed(conn)`. `schema` may be a callable so the production
    DDL is imported lazily from its owner rather than copied here."""

    def _ddl() -> str:
        return schema() if callable(schema) else schema

    def make_empty(path: Path) -> None:
        conn = sqlite3.connect(str(path))
        try:
            conn.executescript(_ddl())
            conn.commit()
        finally:
            conn.close()

    def make_populated(path: Path) -> None:
        conn = sqlite3.connect(str(path))
        try:
            conn.executescript(_ddl())
            seed(conn)
            conn.commit()
        finally:
            conn.close()

    return StoreStates(name, filename, make_empty, make_populated, is_sqlite=True)
