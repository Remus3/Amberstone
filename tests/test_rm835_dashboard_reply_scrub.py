# arch: RM-835 - :8888 dashboard route replies never carry exception text | section=tests | frozen=no
"""RM-835: a :8888 dashboard route reply never carries exception text.

Measured at main f1ff24958, before the fix (the RM-824 class, which fixed only
``dashboard/routes_loop_control.py`` on Mission Control :8895):

- fifteen DS / analytics catch-all 500s sent ``{"ok": False, "error":
  str(exc)[:200]}`` - routes_aram_balance, routes_cc_blended_ehp_threat,
  routes_cc_conditional_pressure, routes_cc_pairing, routes_damage_mix,
  routes_ds_combo, routes_ds_knobs, routes_ds_matchup, routes_ds_profile,
  routes_ds_relscore, routes_ds_shape, routes_ds_skill_order, routes_ds_sweep,
  routes_peel_priority, routes_spike_markers;
- ``routes_ds_statcheck``'s ``(KeyError, ValueError)`` fail-soft 200 added
  ``"detail": str(exc)[:120]`` and logged nothing;
- ``routes_sr_draft``'s enqueue fault appended ``f"{cmd}: {exc}"`` to the
  reply's ``notes``;
- and the log line beside each logged the raw exception with no type name.

Each case below drives the real route function into its exception path with
an exception whose text carries a marker, a filesystem path and control
characters, and asserts that the status and the envelope keys are the route's
existing contract, that the reply carries none of that text, that the reply is
FIXED (two different exception texts give the same reply), and that the raw
cause reached the log with its type name. A source guard then sweeps every
module that registers a :8888 route (read from the dispatch tables, not a
hand list) for a reply that names an except-bound exception.
"""
from __future__ import annotations

import ast
import importlib
import json
import logging
import sys
import types
import urllib.request
from pathlib import Path

import pytest

from tests._module_view import this_thread_only

ROOT = Path(__file__).resolve().parent.parent

SECRET_PATH = r"C:\Example Repo\data\secret_rm835.db"
_CONTROL_CHARS = ("\x1b", "\r", "\n", "\x85", "\x7f")
_LEAKS = ("Example Repo", "secret_rm835", "FAKE-LINE", "Errno",
          "\\u001b", "\\r", "\\n", "\\u0085")


def _evil(marker: str) -> str:
    """Exception text with a marker, a filesystem path and control chars."""
    return f"{marker} at {SECRET_PATH} \x1b[31m\r\nFAKE-LINE\x85\x7f"


def _os_error(marker: str) -> OSError:
    # errno + strerror + filename: str() renders "[Errno 5] <text>: '<path>'",
    # the shape a share-locked or missing registry / snapshot file produces.
    return OSError(5, _evil(marker), SECRET_PATH)


# --------------------------------------------------------------------------- harness
class _Cap(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def cap():
    lg = logging.getLogger("rc.web_dashboard")
    handler, prior = _Cap(), lg.level
    lg.addHandler(handler)
    lg.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        lg.removeHandler(handler)
        lg.setLevel(prior)


class _H:
    """The `_send` stub the dashboard route modules write through. `path`
    raises when `boom` is set: every catch-all route reads it as the first
    statement inside its try, so that is the fault any statement in the
    route body would produce."""

    def __init__(self, path: str = "/", boom: BaseException | None = None):
        self._path = path
        self._boom = boom
        self.sent: tuple | None = None

    @property
    def path(self) -> str:
        if self._boom is not None:
            raise self._boom
        return self._path

    def _send(self, status, body, ctype, cache_control=None):
        self.sent = (status, body, ctype)


class _RawH:
    """send_response-style stub for routes_ds_statcheck's private _send."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.status: int | None = None
        self.chunks: list[bytes] = []

    def send_response(self, code: int) -> None:
        self.status = code

    def send_header(self, k: str, v: str) -> None:
        pass

    def end_headers(self) -> None:
        pass

    @property
    def wfile(self):
        return self

    def write(self, b: bytes) -> None:
        self.chunks.append(b)


def _strings(node):
    """Every string in a parsed JSON document, keys included."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)


def _assert_clean(raw: bytes, payload, marker: str) -> None:
    text = raw.decode("utf-8")
    for leak in (marker, *_LEAKS):
        assert leak not in text, (leak, text)
    for s in _strings(payload):
        assert not any(c in s for c in _CONTROL_CHARS), repr(s)


def _assert_logged(cap: _Cap, marker: str, type_name: str,
                   level: int = logging.WARNING) -> None:
    """The raw cause is logged with its type name, and no record carries a
    raw control character."""
    msgs = [(r.levelno, r.getMessage()) for r in cap.records]
    assert any(lv >= level and marker in m and type_name in m
               for lv, m in msgs), msgs
    for _lv, m in msgs:
        assert not any(c in m for c in _CONTROL_CHARS), repr(m)


# --------------------------------------------------------------------------- the fifteen catch-alls
# module -> (route function, request path). Each route's outer
# `except Exception` is the site; status 500 and the {ok, error} envelope are
# its existing contract.
CATCH_ALLS = {
    "routes_aram_balance": ("_serve_aram_balance", "/api/aram-balance"),
    "routes_cc_blended_ehp_threat": ("_serve_cc_blended_ehp_threat",
                                     "/api/cc-blended-ehp-threat?ally=1"),
    "routes_cc_conditional_pressure": ("_serve_cc_conditional_pressure",
                                       "/api/cc-conditional-pressure?ally=1"),
    "routes_cc_pairing": ("_serve_cc_pairing", "/api/cc-pairing?ally=1"),
    "routes_damage_mix": ("_serve_damage_mix", "/api/damage-mix?champ_id=86"),
    "routes_ds_combo": ("_serve_ds_combo", "/api/ds-combo?champion=Lux"),
    "routes_ds_knobs": ("_serve_ds_knobs", "/api/ds-knobs?champion=Lux"),
    "routes_ds_matchup": ("_serve_ds_matchup",
                          "/api/ds-matchup?champ_a=Vayne&champ_b=Lux"),
    "routes_ds_profile": ("_serve_ds_profile", "/api/ds-profile?champion=Lux"),
    "routes_ds_relscore": ("_serve_ds_relscore",
                           "/api/ds-relscore?champion=Lux"),
    "routes_ds_shape": ("_serve_ds_shape", "/api/ds-shape?champion=Lux"),
    "routes_ds_skill_order": ("_serve_ds_skill_order",
                              "/api/ds-skill-order?champion=Lux"),
    "routes_ds_sweep": ("_serve_ds_sweep", "/api/ds-sweep?champion=Lux"),
    "routes_peel_priority": ("_serve_peel_priority", "/api/peel-priority"),
    "routes_spike_markers": ("_serve_spike_markers",
                             "/api/spike-markers?champion=Lux"),
}


def _drive_catch_all(monkeypatch, name: str, marker: str):
    mod = importlib.import_module(f"dashboard.{name}")
    fn_name, path = CATCH_ALLS[name]
    if hasattr(mod, "_reset_caches"):
        mod._reset_caches()
    if name == "routes_aram_balance":
        # The one catch-all that reads no query: its first call is the grid.
        def _boom():
            raise _os_error(marker)
        monkeypatch.setattr(mod, "_get_grid", _boom)
        h = _H(path)
    else:
        h = _H(path, boom=_os_error(marker))
    getattr(mod, fn_name)(h)
    assert h.sent is not None, f"{name}: no reply was sent"
    status, raw, ctype = h.sent
    assert ctype == "application/json"
    return status, raw, json.loads(raw.decode("utf-8"))


def test_the_catch_all_table_is_the_measured_fifteen():
    assert len(CATCH_ALLS) == 15


@pytest.mark.parametrize("name", list(CATCH_ALLS))
def test_a_catch_all_500_carries_no_exception_text(name, monkeypatch, cap):
    status, raw, payload = _drive_catch_all(monkeypatch, name, "RM835MARKA")
    assert status == 500, payload
    assert set(payload) == {"ok", "error"}, payload
    assert payload["ok"] is False
    assert isinstance(payload["error"], str) and payload["error"]
    assert "see logs" in payload["error"], payload["error"]
    _assert_clean(raw, payload, "RM835MARKA")
    _assert_logged(cap, "RM835MARKA", "OSError")


@pytest.mark.parametrize("name", list(CATCH_ALLS))
def test_a_catch_all_500_message_is_fixed(name, monkeypatch):
    _s1, raw1, _p1 = _drive_catch_all(monkeypatch, name, "RM835MARKA")
    _s2, raw2, _p2 = _drive_catch_all(monkeypatch, name, "RM835MARKB")
    assert raw1 == raw2


def test_send_error_fields_keep_the_envelope_and_cannot_carry_error():
    """`fields` puts a route's own keys before `error`, and an `error` key
    among them is overwritten by the fixed line."""
    from dashboard._errors import send_error
    h = _H()
    send_error(h, _os_error("RM835MARKA"), public_msg="x failed - see logs",
               fields={"ok": False, "error": "smuggled"})
    status, raw, ctype = h.sent
    assert (status, ctype) == (500, "application/json")
    assert raw == b'{"ok": false, "error": "x failed - see logs"}'


@pytest.mark.parametrize("flag", [True, False])
def test_send_error_log_traceback_attaches_the_exception(flag, cap):
    from dashboard._errors import send_error
    try:
        raise _os_error("RM835MARKA")
    except OSError as exc:
        send_error(_H(), exc, public_msg="x failed - see logs",
                   log_traceback=flag)
    recs = [r for r in cap.records if "RM835MARKA" in r.getMessage()]
    assert len(recs) == 1, recs
    if flag:
        assert recs[0].exc_info and recs[0].exc_info[0] is OSError
    else:
        assert not recs[0].exc_info


# --------------------------------------------------------------------------- ds-statcheck detail
@pytest.fixture
def statcheck(monkeypatch):
    from dashboard import routes_ds_statcheck as sc
    sc._reset_caches()
    yield sc
    sc._reset_caches()


def _drive_statcheck(sc, monkeypatch, exc_type, marker: str):
    def _dps(*_a, **_k):
        raise exc_type(_evil(marker))
    monkeypatch.setattr(sc, "_load_engine", lambda: (object(), _dps))
    sc._reset_caches()
    h = _RawH("/api/ds-statcheck?champion=Caitlyn")
    sc._serve_ds_statcheck(h)
    raw = b"".join(h.chunks)
    return h.status, raw, json.loads(raw.decode("utf-8"))


@pytest.mark.parametrize("exc_type", [KeyError, ValueError],
                         ids=["KeyError", "ValueError"])
def test_statcheck_lookup_miss_detail_carries_no_exception_text(
        exc_type, statcheck, monkeypatch, cap):
    status, raw, payload = _drive_statcheck(statcheck, monkeypatch, exc_type,
                                            "RM835MARKA")
    # The fail-soft contract: 200, ok=false, the same four keys.
    assert status == 200, payload
    assert set(payload) == {"ok", "error", "champion", "detail"}, payload
    assert payload["ok"] is False
    assert payload["error"] == "unknown champion: Caitlyn"
    assert payload["champion"] == "Caitlyn"
    assert "see logs" in payload["detail"], payload["detail"]
    _assert_clean(raw, payload, "RM835MARKA")
    _assert_logged(cap, "RM835MARKA", exc_type.__name__, level=logging.INFO)


@pytest.mark.parametrize("exc_type", [KeyError, ValueError],
                         ids=["KeyError", "ValueError"])
def test_statcheck_lookup_miss_reply_is_fixed(exc_type, statcheck,
                                              monkeypatch):
    _s1, raw1, _p1 = _drive_statcheck(statcheck, monkeypatch, exc_type,
                                      "RM835MARKA")
    _s2, raw2, _p2 = _drive_statcheck(statcheck, monkeypatch, exc_type,
                                      "RM835MARKB")
    assert raw1 == raw2


# --------------------------------------------------------------------------- sr-draft notes
def _drive_sr_draft(monkeypatch, marker: str):
    from dashboard import routes_sr_draft as sr
    stub = types.ModuleType("web_dashboard")
    stub._VISION_TOKEN = "test-token"
    monkeypatch.setitem(sys.modules, "web_dashboard", stub)

    def _urlopen(*_a, **_k):
        raise _os_error(marker)
    monkeypatch.setattr(urllib.request, "urlopen",
                        this_thread_only(_urlopen, urllib.request.urlopen))
    h = _H("/api/sr-draft/apply")
    # Summoners only: one enqueue, so one note, and nothing else in `notes`.
    sr._serve_sr_draft_apply_post(h, {
        "champion": "Tristana", "key": "primary", "summoner_spells": [4, 12],
        "push_runes": False, "push_items": False})
    assert h.sent is not None
    status, raw, ctype = h.sent
    assert ctype == "application/json"
    return status, raw, json.loads(raw.decode("utf-8"))


def test_sr_draft_enqueue_fault_note_carries_no_exception_text(monkeypatch,
                                                               cap):
    status, raw, payload = _drive_sr_draft(monkeypatch, "RM835MARKA")
    assert status == 200, payload
    assert payload["ok"] is True
    assert payload["queued"] == []
    assert len(payload["notes"]) == 1, payload["notes"]
    note = payload["notes"][0]
    assert note.startswith("set_summoners: "), note
    assert "see logs" in note, note
    _assert_clean(raw, payload, "RM835MARKA")
    _assert_logged(cap, "RM835MARKA", "OSError")


def test_sr_draft_enqueue_fault_note_is_fixed(monkeypatch):
    _s1, raw1, _p1 = _drive_sr_draft(monkeypatch, "RM835MARKA")
    _s2, raw2, _p2 = _drive_sr_draft(monkeypatch, "RM835MARKB")
    assert raw1 == raw2


# --------------------------------------------------------------------------- docstrings
@pytest.mark.parametrize("name", ["routes_ds_matchup", "routes_ds_shape"])
def test_no_docstring_states_the_leak_as_the_contract(name):
    doc = importlib.import_module(f"dashboard.{name}").__doc__ or ""
    assert "500" in doc, "the failure-modes block must still list the 500"
    assert "str(exc)" not in doc, doc


# --------------------------------------------------------------------------- source guard
_LOG_LEVELS = {"debug", "info", "warning", "warn", "error", "exception",
               "critical", "log"}
# Calls an exception may flow into without reaching a reply: the scrubbers,
# the RM-134 envelope, RM-824's fixed-message helper, and type() /
# isinstance() (only the class, server text, can come out of them).
_SAFE_CALLS = {"scrub_log", "_scrub_log", "scrub_controls", "send_error",
               "_send_validation_error", "_fault", "type", "isinstance"}
_REPLY_CALLS = {"_send", "_send_json", "send_json"}
# RM-835: a reply list or dict built up by mutation (routes_sr_draft's
# `notes.append(f"{cmd}: {exc}")`) is a reply shape too.
_MUTATION_CALLS = {"append", "extend", "insert", "update", "setdefault"}
# Attributes of an except-bound urllib HTTPError that carry no exception
# text: the upstream status code, and the upstream server's own reply body
# (`e.read()`, which the :8888 proxy routes forward by design - the upstream's
# reply contract is its own, see the RM-835 report).
_SAFE_ATTRS = {"code", "status", "read"}


def _call_name(node: ast.Call) -> str:
    fn = node.func
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return ""


def _reply_leaks(src: str) -> list[int]:
    """Lines where an except-bound name reaches a reply shape - a dict
    literal, a ``return`` value, a ``_send`` call or a container mutation -
    before any safe call. A log call is not a reply (its scrubbing is
    RM-811's guard). An assignment that carries the exception to a later
    reply is RM-837's, not this guard's."""
    tree = ast.parse(src)
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    bad: set[int] = set()
    for h in ast.walk(tree):
        if not (isinstance(h, ast.ExceptHandler) and h.name):
            continue
        for stmt in h.body:
            for n in ast.walk(stmt):
                if not (isinstance(n, ast.Name) and n.id == h.name):
                    continue
                parent = parents.get(n)
                if isinstance(parent, ast.Attribute) and parent.attr in _SAFE_ATTRS:
                    continue
                cur = n
                while cur is not h and cur in parents:
                    cur = parents[cur]
                    if isinstance(cur, ast.Call):
                        name = _call_name(cur)
                        if name in _SAFE_CALLS or name in _LOG_LEVELS:
                            break
                        if name in _REPLY_CALLS or name in _MUTATION_CALLS:
                            bad.add(n.lineno)
                            break
                    if isinstance(cur, (ast.Dict, ast.Return)):
                        bad.add(n.lineno)
                        break
    return sorted(bad)


def _route_modules() -> list[Path]:
    """Every module that registers a :8888 route, read from the dispatch
    tables themselves, plus the request handler that serves them."""
    from dashboard import _dispatch
    mods = {fn.__module__ for _m, fn in _dispatch._gather_get()}
    mods |= {fn.__module__ for _m, fn in _dispatch._gather_post()}
    files = {ROOT / Path(*m.split(".")).with_suffix(".py") for m in mods}
    files.add(ROOT / "dashboard" / "_handler.py")
    return sorted(files)


_SWEPT = _route_modules()


def test_the_sweep_sees_every_route_module():
    """Floor: an empty or truncated walk must not read as clean. Measured at
    f1ff24958: 72 modules registered :8888 routes (73 files with the
    handler); the fifteen catch-all modules, ds-statcheck and sr-draft must
    all be in it."""
    assert len(_SWEPT) >= 65, len(_SWEPT)
    names = {p.stem for p in _SWEPT}
    for must in (*CATCH_ALLS, "routes_ds_statcheck", "routes_sr_draft"):
        assert must in names, must
    for p in _SWEPT:
        assert p.is_file(), p


def test_the_sweep_has_except_handlers_to_look_at():
    """Measured at f1ff24958: 232 except handlers bind a name in the swept
    files."""
    bound = 0
    for p in _SWEPT:
        tree = ast.parse(p.read_text(encoding="utf-8"))
        bound += sum(1 for h in ast.walk(tree)
                     if isinstance(h, ast.ExceptHandler) and h.name)
    assert bound >= 200, bound


@pytest.mark.parametrize("path", _SWEPT,
                         ids=lambda p: p.relative_to(ROOT).as_posix())
def test_no_8888_reply_names_a_bound_exception(path):
    assert _reply_leaks(path.read_text(encoding="utf-8")) == [], path


def test_the_reply_detector_is_not_vacuous():
    """The detector flags the measured pre-fix RM-835 shapes and passes the
    safe ones, line for line."""
    src = (
        "def f(h, notes):\n"
        "    try:\n"
        "        pass\n"
        "    except Exception as exc:\n"
        "        log.warning('api/ds-combo: %s', exc)\n"
        "        h._send(500, json.dumps({\n"
        "            'ok': False, 'error': str(exc)[:200],\n"            # 7
        "        }).encode('utf-8'), 'application/json')\n"
        "    except (KeyError, ValueError) as exc:\n"
        "        _send(h, 200, {'ok': False, 'detail': str(exc)[:120]})\n"  # 10
        "    except OSError as exc:\n"
        "        notes.append(f'set_summoners: {exc}')\n"              # 12
        "    except TypeError as e:\n"
        "        return e.args[0]\n"                                   # 14
        "    except urllib.error.HTTPError as e:\n"
        "        h._send(e.code, e.read(), 'application/json')\n"
        "    except RuntimeError as exc:\n"
        "        log.info('x: %s: %s', type(exc).__name__,\n"
        "                 scrub_log(str(exc)))\n"
        "        send_error(h, exc, public_msg='x - see logs',\n"
        "                   fields={'ok': False})\n"
        "    except Exception as exc:\n"
        "        raise RuntimeError('wrapped') from exc\n"
    )
    assert _reply_leaks(src) == [7, 10, 12, 14]
