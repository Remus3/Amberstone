"""NOW-7 measurement pass: a REPORT-ONLY logger-leak detector.

DEFAULT-OFF. Inert unless the environment carries ``RC_LOGGER_LEAK_REPORT=1``.
It ASSERTS NOTHING and can never turn a green test red: every failure inside
the detector itself is swallowed and counted, never raised into the test.

WHAT IT MEASURES. NOW-6 (docs/ROADMAP_HISTORY.md, 2026-10-01) was a test that
left ``propagate = False`` on a module logger, which blinded ``caplog`` in a
DIFFERENT file 18 files later. This module snapshots, for the root logger and
every ``logging.Logger`` in ``logging.root.manager.loggerDict``:

    propagate / level / handlers (by identity) / disabled

immediately before a test's SETUP and immediately after its TEARDOWN, and
appends one JSON line per changed attribute. Wrapping the whole
setup-call-teardown protocol means a function-scoped fixture that mutates and
then restores (``caplog.set_level``) is NOT reported, which is correct.

A logger CREATED during the test is compared against the stdlib default
(propagate True, level NOTSET, no handlers, not disabled). Merely creating a
logger by importing a module is not a leak; creating one and cutting its
propagation is.

KNOWN ATTRIBUTION LIMITS (read before trusting a row):
  - a SESSION- or MODULE-scoped fixture that mutates a logger is credited to
    the first test that set it up, and its restore (if any) to the last;
  - a mutation made at IMPORT time during collection happens before any test
    and is never credited to anyone;
  - background threads mutating loggers are credited to whichever test is
    running at the time.

OUTPUT. One JSONL file PER PROCESS (named by pid and xdist worker id), under
``RC_LOGGER_LEAK_REPORT_DIR`` or by default ``ops/runtime/logger_leak_report/``,
which is gitignored. Per-process files because Windows O_APPEND is not atomic
across processes. A row with ``"attribute": "_detector_error"`` is the
detector's OWN failure, deliberately bucketed under a name that is NOT a
subject property so it can never be read as a leak.

Registered from tests/conftest.py by importing the hook name. Can also be
loaded standalone with ``-p tests._logger_leak_report``.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest

ENV_FLAG = "RC_LOGGER_LEAK_REPORT"
ENV_DIR = "RC_LOGGER_LEAK_REPORT_DIR"
_DEFAULT_DIR = Path(__file__).resolve().parents[1] / "ops" / "runtime" / "logger_leak_report"
_ROOT_NAME = "<root>"
_DEFAULT_STATE = {"propagate": True, "level": logging.NOTSET, "handlers": (), "disabled": False}


def is_enabled(environ=None) -> bool:
    environ = os.environ if environ is None else environ
    return str(environ.get(ENV_FLAG, "")).strip() == "1"


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
            "handlers": tuple(lg.handlers),
            "disabled": lg.disabled,
        }
    return out


def _render(attr, value):
    if attr == "handlers":
        return [_describe_handler(h) for h in value]
    if attr == "level":
        return logging.getLevelName(value)
    return value


def diff(before: dict, after: dict) -> list:
    """Leak rows as (logger, attribute, before, after, created) tuples."""
    rows = []
    for name, now in after.items():
        prior = before.get(name)
        created = prior is None
        base = _DEFAULT_STATE if created else prior
        for attr in ("propagate", "level", "disabled"):
            if now[attr] != base[attr]:
                rows.append((name, attr, _render(attr, base[attr]), _render(attr, now[attr]), created))
        if tuple(id(h) for h in now["handlers"]) != tuple(id(h) for h in base["handlers"]):
            rows.append((name, "handlers", _render("handlers", base["handlers"]),
                         _render("handlers", now["handlers"]), created))
    return rows


def record(nodeid: str, rows: list, path: Path) -> int:
    if not rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for name, attr, b, a, created in rows:
            fh.write(json.dumps({"nodeid": nodeid, "logger": name, "attribute": attr,
                                 "before": b, "after": a, "created": created}) + "\n")
    return len(rows)


def _record_error(nodeid: str, exc: BaseException, path: Path) -> None:
    try:
        record(nodeid, [(_ROOT_NAME, "_detector_error", None, repr(exc), False)], path)
    except Exception:  # noqa: BLE001 - the detector must never fail a test
        pass


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item, nextitem):
    if not is_enabled():
        return (yield)
    path = report_path()
    try:
        before = snapshot()
    except Exception as exc:  # noqa: BLE001
        _record_error(item.nodeid, exc, path)
        return (yield)
    try:
        return (yield)
    finally:
        try:
            record(item.nodeid, diff(before, snapshot()), path)
        except Exception as exc:  # noqa: BLE001
            _record_error(item.nodeid, exc, path)
