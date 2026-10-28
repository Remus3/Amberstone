"""s144 true-audit of ``core/log_scrub.py`` (the log-injection backstop).

Measured before the fix:

F1. A lone surrogate (U+D800..U+DFFF) passed every scrub unescaped:
    ``scrub_controls``, both ``scrub_log`` arms, ``scrub_traceback`` and
    ``ScrubFilter``. ``json.loads`` turns a client's ``"\\ud800"`` into one,
    and RC's file handler (``core/log_setup.py``) encodes UTF-8 strictly, so
    ``emit`` raised ``UnicodeEncodeError`` and the WHOLE record - message or
    traceback - never reached the log. A client could erase its own
    request's log line (``log.warning("bad champ %s", champ)`` and
    ``log.exception(...)`` over ``ValueError(f"bad champ {champ}")`` both
    vanished, measured with a real ``FileHandler(encoding="utf-8")``).
F2. ``ScrubFilter``'s render-failure fallback wrote the exception type's
    ``__name__`` into ``exc_text`` raw, so a type named with an ESC or a
    newline reached the log verbatim - the one path that was meant to be
    "never the raw traceback".

Standalone ``logging.Logger`` instances keep every probe out of the global
logger manager.
"""
from __future__ import annotations

import json
import logging

import pytest

from core import log_scrub

_SURROGATES = (0xD800, 0xDBFF, 0xDC00, 0xDFFF)


def _no_surrogate(text: str) -> bool:
    return not any(0xD800 <= ord(ch) <= 0xDFFF for ch in text)


# -- F1: lone surrogates -----------------------------------------------------

@pytest.mark.parametrize("cp", _SURROGATES, ids=[f"U+{c:04X}" for c in _SURROGATES])
def test_every_scrub_escapes_a_lone_surrogate(cp):
    text = f"a{chr(cp)}b"
    want = f"a\\u{cp:04x}b"
    assert log_scrub.scrub_controls(text) == want
    assert log_scrub.scrub_log(text) == want
    assert log_scrub.scrub_log(text, None) == want      # the fallback arm


def test_the_surrogate_range_is_in_the_one_shared_table():
    from dashboard import _handler
    assert set(range(0xD800, 0xE000)) <= set(log_scrub.SCRUB_RANGES)
    assert _handler._scrub_log("x\udc80y") == "x\\udc80y"


def test_surrogate_escape_stays_idempotent_and_injective():
    raw = "p\ud800q\\udc00r"
    once = log_scrub.scrub_controls(raw)
    assert log_scrub.scrub_controls(once) == once
    logged = log_scrub.scrub_log(raw)
    assert log_scrub.scrub_controls(logged) == logged
    # The literal six characters a client types are not a real surrogate.
    assert log_scrub.scrub_log("\\ud800") != log_scrub.scrub_log("\ud800")
    assert _no_surrogate(once) and _no_surrogate(logged)


def test_scrub_traceback_escapes_a_surrogate_in_the_message():
    champ = json.loads('"Ahri\\ud800"')
    try:
        raise ValueError(f"bad champ {champ}")
    except ValueError as exc:
        text = log_scrub.scrub_traceback(exc)
    assert _no_surrogate(text)
    assert "ValueError: bad champ Ahri\\ud800" in text
    text.encode("utf-8")                                # strict, must not raise


def test_a_surrogate_record_still_reaches_a_utf8_log(tmp_path, capsys):
    """The end-to-end loss: RC's handler shape, a JSON-decoded client value."""
    champ = json.loads('{"champ": "Ahri\\ud800"}')["champ"]
    path = tmp_path / "x.log"
    lg = logging.Logger("s144.log_scrub.surrogate")
    handler = logging.FileHandler(path, encoding="utf-8")
    lg.addHandler(handler)
    lg.addFilter(log_scrub.ScrubFilter())
    try:
        lg.warning("before")
        lg.warning("bad champ %s", champ)
        try:
            raise ValueError(f"bad champ {champ}")
        except ValueError:
            lg.exception("route failed")
        lg.warning("after")
    finally:
        lg.removeHandler(handler)
        handler.close()
    body = path.read_text(encoding="utf-8")
    assert "Logging error" not in capsys.readouterr().err
    assert "bad champ Ahri\\ud800\n" in body
    assert "route failed\nTraceback (most recent call last):" in body
    assert "ValueError: bad champ Ahri\\ud800" in body
    assert body.startswith("before\n") and body.endswith("after\n")


# -- F2: the render-failure fallback -----------------------------------------

def test_scrub_filter_fallback_scrubs_the_type_name(monkeypatch):
    # CPython refuses a surrogate in a type name, so none is tried here.
    evil = type("Evil\x1b[31m\nFAKE\u2028LINE", (Exception,), {})
    monkeypatch.setattr(log_scrub, "scrub_traceback",
                        lambda *a: (_ for _ in ()).throw(RuntimeError("x")))
    rec = logging.LogRecord("t", logging.ERROR, __file__, 1, "m", (), None)
    exc = evil()
    rec.exc_info = (evil, exc, None)
    assert log_scrub.ScrubFilter().filter(rec) is True
    text = rec.exc_text
    assert text == ("Evil\\x1b[31m\\x0aFAKE\\u2028LINE "
                    "(traceback could not be rendered)")
    assert "\n" not in text and "\x1b" not in text and "\u2028" not in text


def test_scrub_filter_fallback_keeps_a_plain_type_name():
    """Negative control: an ordinary name is unchanged by the fallback."""
    rec = logging.LogRecord("t", logging.ERROR, __file__, 1, "m", (), None)

    class Odd(Exception):
        pass

    exc = Odd()
    rec.exc_info = (Odd, exc, object())       # a non-traceback tb fails format_tb
    log_scrub.ScrubFilter().filter(rec)
    assert rec.exc_text == "Odd (traceback could not be rendered)"
