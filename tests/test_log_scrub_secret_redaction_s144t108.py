"""s144 true-audit cycle 108 (RM-1383): ``core/log_scrub.py`` redacts
key-shaped secrets on the logger-wide backstop.

Measured before the fix (cycle 107 filed it from dashboard/_errors.py):

F1. ``ScrubFilter`` rewrote a record only for control characters. A
    message holding an Anthropic key (``sk-ant-...``) reached the log
    unchanged, so ``dashboard._errors.send_error`` - the last-resort error
    path of every :8888 / :8895 route - logged any key an exception quoted.
F2. ``scrub_traceback`` (the ``exc_text`` the filter renders) carried the
    same key in the exception line, so ``log.exception`` leaked it too.
F3. A Riot API key (``RGAPI-...``) and a header-shaped token value
    (``X-RC-Token: ...``, ``Authorization: Bearer ...``,
    ``ANTHROPIC_API_KEY=...``) passed the same way.
F4. An ``exc_text`` a caller had already set was passed on as it was, key
    included (the filter renders only an unset one).
F5. A record whose format fails is left for the handler's error path, which
    prints its raw ``msg`` and ``args`` to stderr - key included.

Every fake secret below is built at run time, so no line of this file holds
a credential-shaped literal for the pre-push scan to refuse.
``scrub_log`` itself stays a pure, injective control-character escaper
(its exact output is pinned elsewhere); the redaction lives in the
backstop and the traceback renderer.
"""
from __future__ import annotations

import logging
import re

import pytest

from core import log_scrub

_ANT = "sk-" + "ant-"
KEY = _ANT + "api03-" + "Ab9_" * 12            # an Anthropic-key shape
ADMIN = _ANT + "admin01-" + "Zz8-" * 10        # the admin family
RIOT = "RG" + "API-" + "0a1b2c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d"
TOKEN = "f" * 8 + "0123456789abcdef" + "e" * 8  # a token_hex(16) shape


def _record(msg, args=(), exc_info=None):
    return logging.LogRecord("t", logging.WARNING, __file__, 1, msg, args,
                             exc_info)


def _filtered(msg, args=(), exc_info=None):
    rec = _record(msg, args, exc_info)
    assert log_scrub.ScrubFilter().filter(rec) is True
    return rec


# -- the primitive -----------------------------------------------------------

@pytest.mark.parametrize("secret", [KEY, ADMIN, RIOT],
                         ids=["anthropic", "anthropic_admin", "riot"])
def test_redact_secrets_removes_a_bare_key(secret):
    out = log_scrub.redact_secrets(f"call failed: {secret} rejected")
    assert secret not in out
    assert out.startswith("call failed: ") and out.endswith(" rejected")
    assert "[redacted]" in out


@pytest.mark.parametrize("text", [
    f"X-RC-Token: {TOKEN}",
    f"{{'X-RC-Token': '{TOKEN}'}}",
    f'{{"x-riot-token": "{TOKEN}"}}',
    f"Authorization: Bearer {TOKEN}",
    f"ANTHROPIC_API_KEY={TOKEN}",
    f"x-api-key={TOKEN}",
], ids=["rc-header", "rc-dict", "riot-json", "bearer", "env", "x-api-key"])
def test_redact_secrets_removes_a_header_shaped_value(text):
    out = log_scrub.redact_secrets(text)
    assert TOKEN not in out
    assert "[redacted]" in out


def test_redact_secrets_keeps_the_header_name_and_scheme():
    assert (log_scrub.redact_secrets(f"Authorization: Bearer {TOKEN}")
            == "Authorization: Bearer [redacted]")
    assert (log_scrub.redact_secrets(f"ANTHROPIC_API_KEY={KEY}")
            == "ANTHROPIC_API_KEY=[redacted]")
    assert (log_scrub.redact_secrets(f"key {KEY} end")
            == f"key {_ANT}[redacted] end")
    # The value ends at its closing quote, so the repr around it survives.
    assert (log_scrub.redact_secrets(f"{{'X-RC-Token': '{TOKEN}', 'n': 1}}")
            == "{'X-RC-Token': '[redacted]', 'n': 1}")


@pytest.mark.parametrize("text", [
    f"X-RC-Token: {TOKEN} and {KEY} and {RIOT}",
    "nothing secret here",
    "",
])
def test_redact_secrets_is_idempotent(text):
    once = log_scrub.redact_secrets(text)
    assert log_scrub.redact_secrets(once) == once


@pytest.mark.parametrize("text", [
    "authorization failed for user",          # no ':' or '=' after the name
    "token expired at 12:00",
    f"{_ANT}short",                            # under the 8-char floor
    "RGAPI is the Riot key prefix",
    r"<repo>\data\x.json read",
])
def test_redact_secrets_leaves_ordinary_text_alone(text):
    assert log_scrub.redact_secrets(text) == text


def test_redact_secrets_covers_the_credential_scan_key_families():
    """Parity with tools/credential_patterns.py: every Anthropic- and Riot-
    family key the push scan refuses is also redacted from a log line."""
    from tools import credential_patterns as cp
    fams = dict(cp._FAMILIES)
    for name, sample in (("anthropic", KEY), ("anthropic_admin", ADMIN),
                         ("riot_api_key", RIOT)):
        assert re.search(fams[name], sample), name     # the sample is real
        assert sample not in log_scrub.redact_secrets(sample), name


# -- F1: the filter's message path --------------------------------------------

def test_filter_redacts_a_key_in_the_message_args():
    rec = _filtered("upstream said: %s", (f"invalid x-api-key {KEY}",))
    assert KEY not in rec.getMessage()
    assert rec.getMessage() == f"upstream said: invalid x-api-key {_ANT}[redacted]"


def test_filter_redacts_a_key_in_a_preformatted_message():
    rec = _filtered(f"boom {RIOT}")
    assert RIOT not in rec.getMessage()


def test_filter_redacts_and_still_escapes_controls():
    rec = _filtered("x %s", (f"\x1b[31m{KEY}\n",))
    msg = rec.getMessage()
    assert KEY not in msg and "\x1b" not in msg and "\n" not in msg


def test_filter_leaves_a_clean_record_untouched():
    """Negative control: no secret, no control - msg and args survive."""
    rec = _filtered("read %s: %d rows", ("<repo>\\data\\x.json", 5))
    assert rec.msg == "read %s: %d rows" and rec.args == ("<repo>\\data\\x.json", 5)


# -- F2: the rendered traceback ------------------------------------------------

def _raised(text):
    try:
        raise RuntimeError(text)
    except RuntimeError as exc:
        return exc


def test_scrub_traceback_redacts_the_exception_line():
    out = log_scrub.scrub_traceback(_raised(f"401 for key {KEY}"))
    assert KEY not in out
    assert f"RuntimeError: 401 for key {_ANT}[redacted]" in out


def test_scrub_traceback_redacts_a_chained_cause():
    try:
        try:
            raise ValueError(f"X-RC-Token: {TOKEN}")
        except ValueError as inner:
            raise RuntimeError("wrapper") from inner
    except RuntimeError as exc:
        out = log_scrub.scrub_traceback(exc)
    assert TOKEN not in out and "X-RC-Token: [redacted]" in out


def test_filter_renders_a_redacted_exc_text():
    exc = _raised(f"bad {KEY}")
    rec = _filtered("route failed", exc_info=(type(exc), exc, exc.__traceback__))
    assert KEY not in rec.exc_text
    assert "route failed" == rec.getMessage()


# -- F4: a caller-set exc_text -------------------------------------------------

def test_filter_redacts_a_preset_exc_text_without_reformatting_it():
    exc = _raised("x")
    rec = _record("m", exc_info=(type(exc), exc, exc.__traceback__))
    rec.exc_text = f"Traceback (most recent call last):\nRuntimeError: {KEY}"
    log_scrub.ScrubFilter().filter(rec)
    assert rec.exc_text == ("Traceback (most recent call last):\n"
                            f"RuntimeError: {_ANT}[redacted]")


# -- F5: a record whose format fails ---------------------------------------------

def _unformattable_line(rec):
    msg = rec.getMessage()                       # formats now
    assert msg.startswith(log_scrub.UNFORMATTABLE)
    assert "\n" not in msg and "\x1b" not in msg
    return msg


@pytest.mark.parametrize("msg,args", [
    ("%s %s", (f"key {KEY}",)),                  # one arg for two slots
    (f"{KEY} %d", ("not a number",)),            # the key in the template
    ("%s %s", ({"X-RC-Token": TOKEN},)),         # a dict arg
    ("%d", (RuntimeError(f"bad {RIOT}"),)),      # a non-str arg
], ids=["str-arg", "template", "dict-arg", "exc-arg"])
def test_an_unformattable_record_with_a_secret_becomes_one_redacted_line(
        msg, args):
    rec = _filtered(msg, args)
    line = _unformattable_line(rec)
    for secret in (KEY, TOKEN, RIOT):
        assert secret not in line
    assert "[redacted]" in line


def test_an_unformattable_non_str_msg_with_a_secret_is_redacted():
    rec = _filtered(RuntimeError(f"bad {KEY}"), ("extra",))
    assert KEY not in _unformattable_line(rec)


def test_redaction_cannot_turn_a_bad_record_into_raw_injected_output():
    """The verifier's repro: redacting the template in place ate a ``%s``,
    so the record formatted with its RAW args - ESC and newline included."""
    rec = _filtered("X-RC-Token=%s %s", ("\x1b[31mINJ\nFAKE LINE",))
    line = _unformattable_line(rec)
    assert "FAKE LINE" in line and "\\x1b" in line


def test_an_unformattable_line_escapes_a_custom_repr_control():
    """``repr`` of a str escapes controls; a custom ``__repr__`` need not."""
    class Loud:
        def __repr__(self):
            return f"\x1b[31m{KEY}\nFAKE"

    rec = _filtered("%s %s", (Loud(),))
    line = _unformattable_line(rec)
    assert KEY not in line and "\\x1b[31m" in line and "\\x0aFAKE" in line


def test_an_unformattable_record_without_a_secret_is_left_alone():
    """Negative control: the old contract - the handler reports it."""
    rec = _filtered("%s %s", ("plain",))
    assert rec.msg == "%s %s" and rec.args == ("plain",)
    with pytest.raises(TypeError):
        rec.getMessage()


def test_an_unformattable_record_with_a_broken_repr_is_left_alone():
    class Broken:
        def __repr__(self):
            raise RuntimeError("no repr")

    arg = Broken()
    rec = _filtered("%s %s", (arg,))
    assert rec.args == (arg,)


# -- verifier findings 3-5: header lists, line breaks, frame lines -------------

def test_a_header_tuple_list_is_redacted():
    text = f"headers=[('Authorization', 'Bearer {TOKEN}'), ('X-RC-Token', '{TOKEN}')]"
    out = log_scrub.redact_secrets(text)
    assert TOKEN not in out
    assert out == ("headers=[('Authorization', 'Bearer [redacted]'), "
                   "('X-RC-Token', '[redacted]')]")


@pytest.mark.parametrize("text,want", [
    (f"[(b'X-RC-Token', b'{TOKEN}')]", "[(b'X-RC-Token', b'[redacted]')]"),
    (f"{{b'Authorization': b'Bearer {TOKEN}'}}",
     "{b'Authorization': b'Bearer [redacted]'}"),
    (f"{{'X-RC-Token': b'{TOKEN}'}}", "{'X-RC-Token': b'[redacted]'}"),
    (f'{{\\"X-RC-Token\\": \\"{TOKEN}\\"}}', '{\\"X-RC-Token\\": \\"[redacted]\\"}'),
    (f"Authorization: Token {TOKEN}", "Authorization: Token [redacted]"),
    (f"Authorization: Digest {TOKEN}", "Authorization: Digest [redacted]"),
    (f"MY_ANTHROPIC_API_KEY={TOKEN}", "MY_ANTHROPIC_API_KEY=[redacted]"),
    (f"RC_DASH_TOKEN={TOKEN}", "RC_DASH_TOKEN=[redacted]"),
    (f"rc_vision_token: {TOKEN}", "rc_vision_token: [redacted]"),
    (f"RIOT_API_KEY={TOKEN}", "RIOT_API_KEY=[redacted]"),
], ids=["bytes-tuple", "bytes-dict", "bytes-value", "escaped-json",
        "token-scheme", "digest-scheme", "prefixed-env", "rc-dash-env",
        "rc-vision-env", "riot-env"])
def test_round_two_header_shapes_are_redacted(text, want):
    """Verifier round 2: each of these kept the token (or redacted only the
    ``b`` prefix / the scheme word, leaving the token after it)."""
    out = log_scrub.redact_secrets(text)
    assert TOKEN not in out
    assert out == want
    assert log_scrub.redact_secrets(out) == out


def test_an_unformattable_record_whose_format_error_quotes_a_key():
    """Verifier round 2 (N2): handleError prints the format error's
    traceback too, so a __str__ that raises with a key leaked to stderr."""
    class Quiet:
        def __repr__(self):
            return "Quiet()"

        def __str__(self):
            raise ValueError(f"bad {KEY}")

    rec = _filtered("%s", (Quiet(),))
    line = _unformattable_line(rec)
    assert KEY not in line
    assert line.endswith(f"error=ValueError: bad {_ANT}[redacted]")


def test_a_header_name_never_eats_the_next_line():
    assert (log_scrub.redact_secrets("authorization:\nnext line")
            == "authorization:\nnext line")
    assert (log_scrub.redact_secrets("Authorization: Bearer\nnext")
            == "Authorization: [redacted]\nnext")


def test_scrub_traceback_redacts_a_frame_source_line(tmp_path):
    src = tmp_path / "leaky_mod.py"
    src.write_bytes(f"def boom():\n    raise ValueError('x')  # {KEY}\n"
                    .encode("ascii"))
    ns = {}
    exec(compile(src.read_text(), str(src), "exec"), ns)
    try:
        ns["boom"]()
    except ValueError as exc:
        out = log_scrub.scrub_traceback(exc)
    assert "raise ValueError('x')" in out          # the frame line is there
    assert KEY not in out and f"{_ANT}[redacted]" in out


# -- end to end: the dashboard's last-resort error path ------------------------

class _H:
    def __init__(self):
        self.sent = None

    def _send(self, status, payload, ctype):
        self.sent = (status, payload, ctype)


def test_send_error_never_logs_the_key(caplog):
    from dashboard import _errors
    h = _H()
    with caplog.at_level(logging.WARNING, logger="rc.web_dashboard"):
        _errors.send_error(h, RuntimeError(f"auth failed with {KEY}"),
                           log_traceback=True)
    text = "\n".join(r.getMessage() + "\n" + (r.exc_text or "")
                     for r in caplog.records)
    assert caplog.records, "send_error logged nothing"
    assert KEY not in text
    assert f"{_ANT}[redacted]" in text
    assert KEY.encode() not in h.sent[1]


def test_a_key_never_reaches_a_real_log_file(tmp_path):
    path = tmp_path / "x.log"
    lg = logging.Logger("s144t108.log_scrub.secret")
    handler = logging.FileHandler(path, encoding="utf-8")
    lg.addHandler(handler)
    lg.addFilter(log_scrub.ScrubFilter())
    try:
        lg.warning("lcu said %s", f"Authorization: Basic {TOKEN}")
        try:
            raise ValueError(f"riot rejected {RIOT}")
        except ValueError:
            lg.exception("match fetch failed")
    finally:
        lg.removeHandler(handler)
        handler.close()
    body = path.read_text(encoding="utf-8")
    assert TOKEN not in body and RIOT not in body
    assert "Authorization: Basic [redacted]" in body
    assert "ValueError: riot rejected RGAPI-[redacted]" in body
