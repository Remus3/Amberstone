"""RM-1397 - lcu/lcu_rune_writer.py cites its neighbours by symbol, not line.

Measured 2026-11-04: the module's comments cited lcu/lcu_client.py by line
(`:224-226`, `:173-183`, `:160`, `:384`), main.py by line (`:254`) and two of
its own functions by bare line (`:924`, `:249`, `:264-266`). Every one had
moved (`_request` is at a different line now, `_auto_accept_tick` and
`get_all_rune_pages` too), so a reader following a cite landed on unrelated
code. Each now names the class and method.

The two debounce test docstrings cited "BACKLOG.md:59", which is an
unrelated row now; the debounce is LEDGER items 506 and 507 (RM-1396 fixed
the coach modules; this closes the tests).

Pins: (a) no `<file>.<ext>:<n>` cite and no bare ` :<n>` cite in the touched
files, (b) the symbols the comments now name still exist where they say,
(c) the cite pattern still bites the old forms and spares the new ones.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

FILES = (
    "lcu/lcu_rune_writer.py",
    "tests/test_aram_state_debounce.py",
    "tests/test_arena_state_debounce.py",
)

# `x.py:12`, `x.md:12-15`, and a bare ` :264` / `(:924)` / `at :160` cite.
_FILE_CITE = re.compile(r"[\w./\-]+\.(?:py|md|ps1|js|json):\d+")
_BARE_CITE = re.compile(r"(?:^|[\s(]):\d{2,4}(?:-\d{2,4})?\b")


def _read(rel: str) -> str:
    return (ROOT / rel).read_bytes().decode("utf-8")


@pytest.mark.parametrize("rel", FILES)
def test_no_line_cite_returns(rel):
    text = _read(rel)
    assert not _FILE_CITE.findall(text), (rel, _FILE_CITE.findall(text))
    bare = [ln for ln in text.splitlines() if _BARE_CITE.search(ln)]
    assert not bare, (rel, bare)


@pytest.mark.parametrize("rel", FILES)
def test_ascii_lf_and_no_syntax_warning(rel):
    import warnings
    raw = (ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        compile(raw.decode("ascii"), rel, "exec")


# (file the symbol lives in, definition text the comment now names)
SYMBOLS = (
    ("lcu/lcu_client.py", "    def _auto_accept_tick(self)"),
    ("lcu/lcu_client.py", "    def _request(self,"),
    ("lcu/lcu_client.py", "    def get_all_rune_pages(self)"),
    ("lcu/lcu_rune_writer.py", "def build_champ_id_map()"),
    ("lcu/lcu_rune_writer.py", "    def _id_to_name(self,"),
    ("main.py", '"RuneWriter init failed'),
)


@pytest.mark.parametrize(("rel", "needle"), SYMBOLS)
def test_named_symbol_still_exists(rel, needle):
    assert needle in _read(rel), f"{rel} lost {needle!r}; re-point the comment"


@pytest.mark.parametrize("needle", (
    "LCUClient._auto_accept_tick", "LCUClient._request",
    "LCUClient.get_all_rune_pages", "RuneWriter._id_to_name",
    "RuneWriter start", "(LEDGER item 506)",
))
def test_module_still_names_what_it_cites(needle):
    text = "".join(_read(rel) for rel in FILES)
    assert needle in text, needle


def test_the_ledger_items_the_debounce_tests_cite_exist():
    ledger = _read("docs/LEDGER.md")
    assert "\n506. DONE " in ledger and "\n507. DONE " in ledger


def test_patterns_bite_the_old_forms_and_spare_the_new():
    for probe in ("(lcu/lcu_client.py:224-226)", "main.py:254", "(BACKLOG.md:59)"):
        assert _FILE_CITE.search(probe), probe
    for probe in ("(:924)", "returns {} at :264-266", "at :160 - so"):
        assert _BARE_CITE.search(probe), probe
    for probe in ("LCUClient._request (lcu/lcu_client.py)", "(LEDGER item 506)",
                  "ratio 3:45 of the pool", "http://127.0.0.1:8888"):
        assert not _FILE_CITE.search(probe) and not _BARE_CITE.search(probe), probe
