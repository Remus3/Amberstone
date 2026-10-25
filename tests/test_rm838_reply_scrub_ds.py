"""RM-838 (d): the DS :8860 reply half of the reply-leak class.

The non-DS half (a) / (b) / (c) shipped in ``tests/test_rm838_reply_scrub_non_ds.py``.
This file pins the four DS surfaces the row names:

* ``agents/daemon_slayer/server.py``: every route mapped an engine
  ``KeyError`` / ``ValueError`` to ``_ApiError(404|422, str(e))``, so the
  exception text - including a client-typed champion id carrying control
  characters - rode the :8860 error body.
* ``agents/daemon_slayer/ability_dps.py``: the abilities-snapshot-missing note
  carried the exception text (the snapshot's absolute path) into /ability-dps.
* ``agents/daemon_slayer/fight_report.py``: seven fail-soft section notes were
  built from ``_short(exc)`` (``str(exc)[:120]``) into /v2/fight-report.
* ``agents/daemon_slayer/scenario_matrix.py``: the fail-soft cell note carried
  ``str(exc)[:120]`` (reached through fight_report).

Each test raises an exception whose text carries a marker, a filesystem path and
control characters, and asserts the reply / note carries none of it, that two
different exception texts give the same reply, and that the cause reached the
log with its type name. A source guard sweeps the four modules for any use of an
except-bound name outside a logger call or the sanctioned helpers.
"""
from __future__ import annotations

import ast
import json
import logging
import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from agents.daemon_slayer import server

ROOT = Path(__file__).resolve().parent.parent

SECRET_PATH = r"C:\Example Repo\data\secret_rm838.json"
_CONTROLS = ("\x1b", "\r", "\n", "\x85", "\x7f")
_LEAKS = ("Example Repo", "secret_rm838", "FAKE-LINE")


def _evil(marker: str) -> str:
    """Exception text with a marker, a filesystem path and control chars."""
    return f"{marker} at {SECRET_PATH} \x1b[31m\r\nFAKE-LINE\x85\x7f"


def _assert_clean(text: str, marker: str) -> None:
    assert marker not in text, text
    for leak in _LEAKS:
        assert leak not in text, (leak, text)
    for ch in _CONTROLS:
        assert ch not in text, (repr(ch), text)


class _Cap(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _capture(*names: str):
    # The engine modules log under ``agents.daemon_slayer.*``; the server logs
    # under ``daemon_slayer.server``. One handler on both parents.
    cap = _Cap()
    loggers = [logging.getLogger(n) for n in names]
    priors = [lg.level for lg in loggers]
    for lg in loggers:
        lg.addHandler(cap)
        lg.setLevel(logging.DEBUG)
    try:
        yield cap
    finally:
        for lg, prior in zip(loggers, priors):
            lg.removeHandler(cap)
            lg.setLevel(prior)


@pytest.fixture
def ds_cap():
    with _capture("agents.daemon_slayer", "daemon_slayer.server") as cap:
        yield cap


def _assert_logged(cap: _Cap, marker: str, type_name: str) -> None:
    lines = [r.getMessage() for r in cap.records]
    hits = [ln for ln in lines if marker in ln]
    assert hits, lines
    assert any(type_name in ln for ln in hits), hits
    for ln in hits:
        for ch in _CONTROLS:
            assert ch not in ln, (repr(ch), ln)


# --------------------------------------------------------------------------- server.py
def _route_reject(monkeypatch, exc: BaseException) -> server._ApiError:
    from agents.daemon_slayer.data_loader import DataSnapshot

    def _boom(*_a, **_k):
        raise exc
    cache = server._SnapshotCache()
    cache.set(DataSnapshot.load())
    monkeypatch.setattr(server, "_CACHE", cache)
    monkeypatch.setattr(server, "build_champion", _boom)
    with pytest.raises(server._ApiError) as ei:
        server._route_stats({"champion": "Ahri", "level": 11})
    return ei.value


@pytest.mark.parametrize("exc_type,status", [(KeyError, 404), (ValueError, 422)])
def test_route_engine_reject_carries_no_exception_text(
        monkeypatch, ds_cap, exc_type, status):
    first = _route_reject(monkeypatch, exc_type(_evil("RM838MARKA")))
    second = _route_reject(monkeypatch, exc_type(_evil("RM838MARKB")))
    assert first.status == second.status == status
    _assert_clean(first.message, "RM838MARKA")
    assert first.message == second.message
    assert first.detail is None and second.detail is None
    _assert_logged(ds_cap, "RM838MARKA", exc_type.__name__)


def _post_json(url: str, body: dict) -> tuple[int, dict, str]:
    raw = json.dumps(body).encode("utf-8")
    req = Request(url, data=raw, method="POST",
                  headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=10) as resp:
            text = resp.read().decode("utf-8")
            return resp.status, json.loads(text), text
    except HTTPError as e:
        text = e.read().decode("utf-8")
        return e.code, json.loads(text), text


def test_unknown_champion_404_wire_body_does_not_echo_the_request(ds_cap):
    from agents.daemon_slayer.data_loader import DataSnapshot

    srv = server.start_server(host="127.0.0.1", port=0,
                              snapshot=DataSnapshot.load())
    host, port = srv.server_address
    t = threading.Thread(target=srv.serve_forever, daemon=True,
                         name="RM838DsServer")
    t.start()
    try:
        base = f"http://{host}:{port}"
        status_a, body_a, raw_a = _post_json(
            base + "/stats", {"champion": _evil("RM838MARKA"), "level": 1})
        status_b, body_b, _raw_b = _post_json(
            base + "/stats", {"champion": _evil("RM838MARKB"), "level": 1})
    finally:
        srv.shutdown()
        srv.server_close()
    assert status_a == status_b == 404
    assert set(body_a) == {"error", "status"} and body_a["status"] == 404
    assert body_a == body_b
    _assert_clean(raw_a, "RM838MARKA")
    for esc in ("\\u001b", "\\r", "\\n", "\\u0085"):
        assert esc not in raw_a, (esc, raw_a)
    _assert_logged(ds_cap, "RM838MARKA", "KeyError")


# --------------------------------------------------------------------------- ability_dps.py
def test_ability_dps_abilities_missing_note_carries_no_exception_text(
        monkeypatch, ds_cap):
    import agents.daemon_slayer.abilities as ab
    from agents.daemon_slayer.ability_dps import compute_ability_dps
    from agents.daemon_slayer.data_loader import DataSnapshot

    def _missing(marker):
        def _raise(*_a, **_k):
            raise ab.AbilitiesNotFound(_evil(marker))
        return _raise

    snap = DataSnapshot.load()
    monkeypatch.setattr(ab, "load_default", _missing("RM838MARKA"))
    first = compute_ability_dps(snap, "Lux", 11)
    monkeypatch.setattr(ab, "load_default", _missing("RM838MARKB"))
    second = compute_ability_dps(snap, "Lux", 11)
    assert list(first.notes) == ["abilities snapshot missing - see logs"], \
        first.notes
    assert list(first.notes) == list(second.notes)
    _assert_logged(ds_cap, "RM838MARKA", "AbilitiesNotFound")


# --------------------------------------------------------------------------- fight_report.py
_FIGHT_SECTIONS = {
    "compute_mana_bounded_combo": "mana",
    "compute_ability_hps": "ability_hps",
    "compute_self_shred_uplift": "self_shred",
    "compute_rune_proc_damage": "rune",
    "sweep_scenarios": "scenario",
    "compute_recharge_ledger": "recharge",
    "is_projectile": "missile",
}


def _fight_notes(monkeypatch, marker: str) -> list[str]:
    import agents.daemon_slayer.fight_report as fr

    def _boom(*_a, **_k):
        raise OSError(5, _evil(marker), SECRET_PATH)
    for name in _FIGHT_SECTIONS:
        monkeypatch.setattr(fr, name, _boom)
    rep = fr.compute_fight_report("Lux", 11, sequence=["Q", "W", "E"],
                                  runes=[8112])
    return list(rep.notes)


def test_fight_report_section_notes_carry_no_exception_text(
        monkeypatch, ds_cap):
    first = _fight_notes(monkeypatch, "RM838MARKA")
    second = _fight_notes(monkeypatch, "RM838MARKB")
    assert first == second
    failed = [n for n in first if "section failed" in n]
    allowed = {f"{s} section failed - see logs" for s in _FIGHT_SECTIONS.values()}
    assert failed, first
    assert set(failed) <= allowed, failed
    assert "mana section failed - see logs" in failed
    assert "scenario section failed - see logs" in failed
    for n in first:
        _assert_clean(n, "RM838MARKA")
        assert "Errno" not in n, n
    _assert_logged(ds_cap, "RM838MARKA", "OSError")


# --------------------------------------------------------------------------- scenario_matrix.py
def test_scenario_cell_note_carries_no_exception_text(monkeypatch, ds_cap):
    import agents.daemon_slayer.dps as dps_mod
    from agents.daemon_slayer.data_loader import DataSnapshot
    from agents.daemon_slayer.scenario_matrix import _score_cell

    def _raiser(marker):
        def _raise(*_a, **_k):
            raise OSError(5, _evil(marker), SECRET_PATH)
        return _raise

    snap = DataSnapshot.load()
    args = (snap, "Lux", 11, (), 0.0, 0.0, 0.0, 0.0, "SR", "dps")
    monkeypatch.setattr(dps_mod, "compute_dps", _raiser("RM838MARKA"))
    val_a, note_a = _score_cell(*args)
    monkeypatch.setattr(dps_mod, "compute_dps", _raiser("RM838MARKB"))
    _val_b, note_b = _score_cell(*args)
    assert val_a != val_a  # NaN, the fail-soft contract
    assert note_a == note_b == "scorer raised - see logs"
    _assert_logged(ds_cap, "RM838MARKA", "OSError")


# --------------------------------------------------------------------------- source guard
_MODULES = (
    "agents/daemon_slayer/server.py",
    "agents/daemon_slayer/ability_dps.py",
    "agents/daemon_slayer/fight_report.py",
    "agents/daemon_slayer/scenario_matrix.py",
)
# Calls that may receive an except-bound exception: logger methods, and the
# helpers that log the cause and return a fixed line.
_SANCTIONED_CALLS = {"_engine_reject", "_section_failed"}
_LOGGER_NAMES = {"_log", "_LOG"}


def _sanctioned(call: ast.Call) -> bool:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id in _SANCTIONED_CALLS
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
        return f.value.id in _LOGGER_NAMES
    return False


def _leaks(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[str] = []
    for h in ast.walk(tree):
        if not (isinstance(h, ast.ExceptHandler) and h.name):
            continue
        if isinstance(h.type, ast.Name) and h.type.id == "_ApiError":
            continue  # e.message is the server-authored line by construction
        safe: set[int] = set()
        for node in ast.walk(ast.Module(body=h.body, type_ignores=[])):
            if isinstance(node, ast.Call) and _sanctioned(node):
                for sub in ast.walk(node):
                    safe.add(id(sub))
        for node in ast.walk(ast.Module(body=h.body, type_ignores=[])):
            if (isinstance(node, ast.Name) and node.id == h.name
                    and id(node) not in safe):
                out.append(f"{path.name}:{node.lineno}")
    return out


@pytest.mark.parametrize("rel", _MODULES)
def test_no_except_bound_name_reaches_a_reply(rel):
    path = ROOT / rel
    assert path.is_file(), rel
    assert _leaks(path) == []


def test_source_guard_is_not_vacuous():
    # Positive control: the guard must flag the pre-fix shape.
    probe = ROOT / "tests" / "_rm838_guard_probe.py"
    src = (
        "def f():\n"
        "    try:\n"
        "        pass\n"
        "    except KeyError as e:\n"
        "        raise _ApiError(404, str(e))\n"
    )
    tree = ast.parse(src)
    handlers = [h for h in ast.walk(tree) if isinstance(h, ast.ExceptHandler)]
    assert handlers and handlers[0].name == "e"

    class _P:
        name = probe.name

        @staticmethod
        def read_text(encoding="utf-8"):
            return src
    assert _leaks(_P) == ["_rm838_guard_probe.py:5"]
