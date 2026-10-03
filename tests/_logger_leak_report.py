"""NOW-7: the logger-leak GATE (armed) and its report-only measurement mode.

ARMED BY DEFAULT. A test that leaves process-global logging state changed
(``propagate`` / ``level`` / ``handlers`` / ``disabled`` on root or on any
``logging.Logger`` in ``logging.root.manager.loggerDict``) gets a TEARDOWN
ERROR on that very test, naming the logger, the attribute and the change.

WHY. NOW-6 (docs/ROADMAP_HISTORY.md, 2026-10-01) was a test that left
``propagate = False`` on a module logger, which blinded ``caplog`` in a
DIFFERENT file 18 files later, so the failure landed on the victim and read as
the victim's bug. This gate moves the failure onto the leaker.

MODES (environment):
  - default                     -> gate ARMED: a leak fails the leaker.
  - ``RC_LOGGER_LEAK_REPORT=1`` -> REPORT-ONLY: the same verdicts are written
    as JSONL rows and nothing fails (the NOW-7 measurement mode).
  - ``RC_LOGGER_LEAK_GATE=0``   -> disarmed for one run (no rows, no failures).
  - a NESTED pytest (a child pytest spawned by a test of an outer run, which
    inherits the outer env) is inert in every mode - see ``classify_process``.
    Children that plant leaks on purpose (test_now6_logger_leak_regression)
    would otherwise go red inside the child.

ATTRIBUTION RULES (measured against the 2026-10-03 report-only pass,
docs/NOW7_LOGGER_LEAK_MEASUREMENT.md):
  - Snapshots are taken at the start of SETUP, around CALL, and at the end of
    TEARDOWN, by outermost (tryfirst) wrappers so pytest's own per-phase
    capture handlers are not seen; handlers whose class lives in ``_pytest``
    are ignored as well.
  - A change made in the CALL phase and still present after the test's own
    teardown is a leak of that test, raised at its teardown.
  - A change made in SETUP or TEARDOWN may belong to a class- or module-scoped
    fixture (``setUpClass`` / ``tearDownClass`` run inside the first / last
    test's setup / teardown). It is held PENDING, owned by the test that made
    it, and is clean if the value is back to the original by the end of the
    module. Still changed at the module boundary -> a leak, raised at the
    teardown of the module's last test but NAMING the owner as the leaker.
  - A logger CREATED during a test is compared against the stdlib default.
  - IMPORT-TIME configuration is baseline, not a leak. Loggers configured by
    imports at collection are in every pre-test snapshot (the session
    baseline). A module first imported DURING a test is bracketed by two
    snapshots (a sys.meta_path watcher, installed only while a test runs);
    whatever its execution changed is import-owned and dropped while it still
    holds the value the import left (coaches/_base_coach.py sets PIL.* and
    rc.lcu to WARNING at import). A test that changes it afterwards is judged
    as usual.
  - Loggers that already exist before a test (collection-time imports, the
    session baseline) are only reported when a test CHANGES them.

OUTPUT (report mode). One JSONL file PER PROCESS (named by pid and xdist
worker id), under ``RC_LOGGER_LEAK_REPORT_DIR`` or by default
``ops/runtime/logger_leak_report/`` (gitignored). Per-process files because
Windows O_APPEND is not atomic across processes. A row with
``"attribute": "_detector_error"`` is the detector's OWN failure, bucketed
under a name that is NOT a subject property so it can never be read as a leak.
A detector error never fails a test in either mode.

Registered from tests/conftest.py by importing the hook names. Can also be
loaded standalone with ``-p tests._logger_leak_report``.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
from pathlib import Path

import pytest

ENV_FLAG = "RC_LOGGER_LEAK_REPORT"
ENV_DIR = "RC_LOGGER_LEAK_REPORT_DIR"
ENV_GATE = "RC_LOGGER_LEAK_GATE"
ENV_OUTER = "RC_LOGGER_LEAK_OUTER_PID"
ENV_WORKER = "RC_LOGGER_LEAK_WORKER_PID"
_DEFAULT_DIR = Path(__file__).resolve().parents[1] / "ops" / "runtime" / "logger_leak_report"
_ROOT_NAME = "<root>"
_DEFAULT_STATE = {"propagate": True, "level": logging.NOTSET, "handlers": (), "disabled": False}
_ATTRS = ("propagate", "level", "disabled")


def is_enabled(environ=None) -> bool:
    """Report-only mode flag."""
    environ = os.environ if environ is None else environ
    return str(environ.get(ENV_FLAG, "")).strip() == "1"


def gate_armed(environ=None) -> bool:
    """The gate fails tests unless disarmed or in report-only mode."""
    environ = os.environ if environ is None else environ
    if is_enabled(environ):
        return False
    return str(environ.get(ENV_GATE, "")).strip() != "0"


def classify_process(environ, pid) -> bool:
    """True when this process is the OUTER run (or one of its xdist workers).

    The first process to load the detector stamps its pid into the env, which
    every child inherits. An xdist worker (PYTEST_XDIST_WORKER set, no worker
    stamp yet) stamps itself and stays active. Anything else that sees a
    foreign stamp is a nested pytest and is inert. Mutates ``environ``.
    """
    me = str(pid)
    outer = environ.get(ENV_OUTER)
    if not outer:
        environ[ENV_OUTER] = me
        return True
    if outer == me:
        return True
    worker = environ.get(ENV_WORKER)
    if worker == me:
        return True
    if environ.get("PYTEST_XDIST_WORKER") and not worker:
        environ[ENV_WORKER] = me
        return True
    return False


_IS_OUTER = classify_process(os.environ, os.getpid())


def report_path(environ=None) -> Path:
    environ = os.environ if environ is None else environ
    base = Path(environ.get(ENV_DIR) or _DEFAULT_DIR)
    worker = environ.get("PYTEST_XDIST_WORKER", "main")
    return base / f"leaks-{worker}-{os.getpid()}.jsonl"


def _iter_loggers():
    yield _ROOT_NAME, logging.getLogger()
    for name, lg in list(logging.root.manager.loggerDict.items()):
        if isinstance(lg, logging.Logger):
            yield name, lg


def _is_pytest_handler(h) -> bool:
    return type(h).__module__.startswith("_pytest")


def _describe_handler(h) -> str:
    target = getattr(h, "baseFilename", None)
    label = type(h).__name__
    return f"{label}({target})" if target else label


def snapshot() -> dict:
    """{logger name -> {attr -> value}}; handlers kept as identity tuples."""
    out = {}
    for name, lg in _iter_loggers():
        out[name] = {
            "propagate": lg.propagate,
            "level": lg.level,
            "handlers": tuple(h for h in lg.handlers if not _is_pytest_handler(h)),
            "disabled": lg.disabled,
        }
    return out


def _render(attr, value):
    if attr == "handlers":
        return [_describe_handler(h) for h in value]
    if attr == "level":
        return logging.getLevelName(value)
    return value


def _same(attr, a, b) -> bool:
    if attr == "handlers":
        return tuple(id(h) for h in a) == tuple(id(h) for h in b)
    return a == b


def _raw(snap, name, attr):
    state = snap.get(name)
    return (_DEFAULT_STATE if state is None else state)[attr]


def diff(before: dict, after: dict) -> list:
    """Raw change rows as (logger, attribute, before, after, created) tuples."""
    rows = []
    for name, now in after.items():
        prior = before.get(name)
        created = prior is None
        base = _DEFAULT_STATE if created else prior
        for attr in _ATTRS:
            if now[attr] != base[attr]:
                rows.append((name, attr, _render(attr, base[attr]), _render(attr, now[attr]), created))
        if not _same("handlers", now["handlers"], base["handlers"]):
            rows.append((name, "handlers", _render("handlers", base["handlers"]),
                         _render("handlers", now["handlers"]), created))
    return rows


def leak_rows(before: dict, after: dict, import_owned=None) -> list:
    """diff() minus changes an IMPORT made during the test and that still hold
    the value the import left (``import_owned``: {(logger, attr): raw value})."""
    import_owned = import_owned or {}
    out = []
    for r in diff(before, after):
        key = (r[0], r[1])
        if key in import_owned and _same(r[1], _raw(after, r[0], r[1]), import_owned[key]):
            continue
        out.append(r)
    return out


# --- import-time configuration is baseline, not a leak -----------------------
# A module first imported DURING a test (a lazy import in a fixture or a test
# body) may configure loggers as an import side effect, e.g.
# coaches/_base_coach.py `_silence_chatty_loggers()` sets PIL.* and rc.lcu to
# WARNING. In a full run that import happens at collection and is part of the
# session baseline; in a narrow run it lands inside the first test that pulls
# it in. Either way it is the module's own configuration, so every module
# execution during a test is bracketed by two snapshots and its changes are
# recorded as import-owned. The bracket is installed only while a test is in
# progress, and the module's loader is put back the moment it has executed.

_PHASE = {}
_IMPORT_OWNED = {}
_GUARD = threading.local()


class _BracketLoader:
    def __init__(self, inner):
        self._inner = inner

    def create_module(self, spec):
        create = getattr(self._inner, "create_module", None)
        return create(spec) if create is not None else None

    def exec_module(self, module):
        try:
            before = snapshot()
        except Exception:  # noqa: BLE001 - never break an import
            before = None
        try:
            self._inner.exec_module(module)
        finally:
            try:
                module.__loader__ = self._inner
                spec = getattr(module, "__spec__", None)
                if spec is not None and spec.loader is self:
                    spec.loader = self._inner
            except Exception:  # noqa: BLE001
                pass
            if before is not None:
                try:
                    after = snapshot()
                    for name, attr, *_rest in diff(before, after):
                        _IMPORT_OWNED[(name, attr)] = _raw(after, name, attr)
                except Exception:  # noqa: BLE001
                    pass

    def __getattr__(self, name):
        return getattr(self._inner, name)


class _ImportWatch:
    """sys.meta_path entry: delegates to the finders behind it, then wraps the
    found loader in a _BracketLoader. Inert outside a test."""

    def find_spec(self, fullname, path=None, target=None):
        if "pre" not in _PHASE or getattr(_GUARD, "busy", False):
            return None
        _GUARD.busy = True
        try:
            for finder in list(sys.meta_path):
                if finder is self:
                    continue
                find = getattr(finder, "find_spec", None)
                if find is None:
                    continue
                spec = find(fullname, path, target)
                if spec is None:
                    continue
                loader = spec.loader
                if loader is not None and hasattr(loader, "exec_module") \
                        and not isinstance(loader, _BracketLoader):
                    spec.loader = _BracketLoader(loader)
                return spec
            return None
        finally:
            _GUARD.busy = False

    def invalidate_caches(self):
        pass


_WATCH = _ImportWatch()


class Tracker:
    """Per-process verdict engine; one instance per run (module global below)."""

    def __init__(self):
        self.pending = {}

    def evaluate(self, nodeid, closes_module, pre, pre_call, post_call, post,
                 import_owned=None) -> list:
        """Leak verdicts for one finished test, as dicts."""
        call_keys = set()
        if pre_call is not None and post_call is not None:
            call_keys = {(r[0], r[1]) for r in diff(pre_call, post_call)}
        leaks = []
        for row in leak_rows(pre, post, import_owned):
            name, attr = row[0], row[1]
            key = (name, attr)
            ent = self.pending.get(key)
            if ent is not None and _same(attr, _raw(post, name, attr), ent["orig"]):
                del self.pending[key]  # a scope-owned change, now restored
            elif key in call_keys:
                leaks.append(self._verdict(row, "call", nodeid, nodeid))
            elif ent is None:
                self.pending[key] = {"orig": _raw(pre, name, attr), "owner": nodeid, "row": row}
        if closes_module:
            for key, ent in list(self.pending.items()):
                del self.pending[key]
                name, attr = key
                if not _same(attr, _raw(post, name, attr), ent["orig"]):
                    row = (name, attr, _render(attr, ent["orig"]),
                           _render(attr, _raw(post, name, attr)), ent["row"][4])
                    leaks.append(self._verdict(row, "scope", ent["owner"], nodeid))
        return leaks

    @staticmethod
    def _verdict(row, kind, leaker, raised_at):
        name, attr, b, a, created = row
        return {"nodeid": leaker, "logger": name, "attribute": attr, "before": b,
                "after": a, "created": created, "kind": kind, "raised_at": raised_at}


def record(nodeid: str, rows: list, path: Path) -> int:
    """Append rows. Tuples (raw diff rows) or verdict dicts are accepted."""
    if not rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            if isinstance(r, dict):
                obj = r
            else:
                name, attr, b, a, created = r
                obj = {"nodeid": nodeid, "logger": name, "attribute": attr,
                       "before": b, "after": a, "created": created}
            fh.write(json.dumps(obj) + "\n")
    return len(rows)


def _record_error(nodeid: str, exc: BaseException, path: Path) -> None:
    try:
        record(nodeid, [(_ROOT_NAME, "_detector_error", None, repr(exc), False)], path)
    except Exception:  # noqa: BLE001 - the detector must never fail a test
        pass


def format_failure(leaks: list) -> str:
    lines = ["NOW-7 logger-leak gate: logging state was left changed."]
    for v in leaks:
        where = "" if v["raised_at"] == v["nodeid"] else (
            f" (raised at {v['raised_at']}, the end of the module that owns the change)")
        lines.append(f"  leaker {v['nodeid']}: {v['logger']}.{v['attribute']} "
                     f"{v['before']!r} -> {v['after']!r}{where}")
    lines.append("Restore it (caplog.set_level, a fixture, or try/finally). "
                 f"Disarm for one run with {ENV_GATE}=0; measure with {ENV_FLAG}=1.")
    return "\n".join(lines)


_TRACKER = Tracker()

if _IS_OUTER and not any(isinstance(f, _ImportWatch) for f in sys.meta_path):
    sys.meta_path.insert(0, _WATCH)


def _active() -> bool:
    return _IS_OUTER and (is_enabled() or gate_armed())


def _module_of(nodeid: str) -> str:
    return nodeid.split("::", 1)[0]


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_setup(item):
    if _active():
        _PHASE.clear()
        _IMPORT_OWNED.clear()
        try:
            _PHASE["pre"] = snapshot()
        except Exception as exc:  # noqa: BLE001
            _record_error(item.nodeid, exc, report_path())
    return (yield)


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_call(item):
    if not _active() or "pre" not in _PHASE:
        return (yield)
    try:
        _PHASE["pre_call"] = snapshot()
    except Exception as exc:  # noqa: BLE001
        _record_error(item.nodeid, exc, report_path())
    try:
        return (yield)
    finally:
        try:
            _PHASE["post_call"] = snapshot()
        except Exception as exc:  # noqa: BLE001
            _record_error(item.nodeid, exc, report_path())


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_teardown(item, nextitem):
    if not _active() or "pre" not in _PHASE:
        return (yield)
    raised = None
    result = None
    try:
        result = yield
    except BaseException as exc:  # noqa: BLE001 - re-raised below, after bookkeeping
        raised = exc
    leaks = []
    try:
        closes = nextitem is None or _module_of(nextitem.nodeid) != _module_of(item.nodeid)
        leaks = _TRACKER.evaluate(item.nodeid, closes, _PHASE.get("pre"), _PHASE.get("pre_call"),
                                  _PHASE.get("post_call"), snapshot(), dict(_IMPORT_OWNED))
        if is_enabled():
            record(item.nodeid, leaks, report_path())
    except Exception as exc:  # noqa: BLE001
        _record_error(item.nodeid, exc, report_path())
        leaks = []
    finally:
        _PHASE.clear()
        _IMPORT_OWNED.clear()
    if raised is not None:
        raise raised
    if leaks and gate_armed():
        pytest.fail(format_failure(leaks), pytrace=False)
    return result
