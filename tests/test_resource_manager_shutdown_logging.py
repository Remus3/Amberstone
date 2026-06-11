"""
ResourceManager.shutdown() must not spray "--- Logging error ---" noise when
its log handlers' streams are already closed (the normal state when atexit
fires after pytest/logging teardown - the P2 audit saw the line-329
"ResourceManager.shutdown() complete" record raise into Handler.handleError
in the pytest tail).

The fix contract: shutdown() suppresses logging-internal emit errors for its
own duration (logging.raiseExceptions toggled off) and restores the previous
value afterwards.
"""
import io
import logging

from core.resource_manager import ResourceManager


def _rm(tmp_path):
    return ResourceManager(tmp_path)


def test_shutdown_emits_no_logging_error_noise_on_closed_stream(tmp_path, capsys):
    rm = _rm(tmp_path)
    log = logging.getLogger("rc.resources")
    prev_level = log.level
    log.setLevel(logging.INFO)  # live RC runs INFO via core/log_setup.py
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    log.addHandler(handler)
    stream.close()  # simulate post-teardown closed handler stream
    try:
        rm.shutdown()
    finally:
        log.removeHandler(handler)
        log.setLevel(prev_level)
    err = capsys.readouterr().err
    assert "Logging error" not in err
    assert "ResourceManager.shutdown() complete" not in err


def test_shutdown_restores_logging_raise_exceptions(tmp_path):
    prev = logging.raiseExceptions
    rm = _rm(tmp_path)
    rm.shutdown()
    assert logging.raiseExceptions is prev


def test_shutdown_second_call_is_noop(tmp_path):
    rm = _rm(tmp_path)
    rm.shutdown()
    rm.shutdown()  # idempotent re-entry stays silent and does not raise
