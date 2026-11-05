"""tests/test_champ_select_coach_audit_s144.py - lane 8 audit of
coaches/champ_select_coach.py.

`coach_pick` takes an HTTP POST body and turns it into a PAID Haiku call, so
each finding here is one of three things: a bad body that still spends, a
reply that was paid for and then thrown away, or a promise in the docstring
("never raises", "one Haiku call") that the code did not keep.

Every test stands in for the anthropic module except the two that use
_real_sdk_run, which run the real SDK with its transport patched so nothing
reaches the network.
"""
from __future__ import annotations

import logging
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from coaches import champ_select_coach as C

GOOD_REPLY = ("Advice: Stay Ahri\nSwap: none\n"
              "Summoners: Flash + Heal\nWatchout: Caitlyn")
PAUSED = "(coaching paused - retrying)"
NO_CHAMPION = "(no champion locked yet)"
FAKE_KEY = "sk-test-not-a-real-key"


class _Block:
    def __init__(self, text, type_="text"):
        self.text = text
        self.type = type_


class _Resp:
    def __init__(self, blocks, stop_reason="end_turn"):
        self.content = blocks
        self.stop_reason = stop_reason
        self.usage = None


class _Client:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []
        self.closed = 0
        self.ctor = {}
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        if isinstance(self.reply, BaseException):
            raise self.reply
        return self.reply

    def close(self):
        self.closed += 1

    @property
    def prompt(self):
        return self.calls[0]["messages"][0]["content"]


def _tracker(disabled=False):
    t = MagicMock()
    t.gate_disabled.return_value = disabled
    return t


def _run(state, reply=GOOD_REPLY, key=FAKE_KEY, tracker=None):
    """Drive coach_pick against a fake SDK; return (result, fake client)."""
    if isinstance(reply, str):
        reply = _Resp([_Block(reply)])
    client = _Client(reply)

    def _ctor(**kw):
        client.ctor = kw
        return client

    mod = types.SimpleNamespace(Anthropic=_ctor)
    with patch.dict(sys.modules, {"anthropic": mod}), \
            patch("core.cost_tracker.get_tracker",
                  return_value=tracker or _tracker()):
        out = C.coach_pick(state, key)
    return out, client


def _ahri(**extra):
    return {"my_champion": "Ahri", **extra}


# -- F1: "never raises", but a non-list team field raised TypeError ---------

@pytest.mark.parametrize("field", ["my_team", "their_team", "bench"])
@pytest.mark.parametrize("bad", [5, 1.5, True])
def test_f1_non_iterable_list_field_does_not_raise(field, bad):
    out, _ = _run(_ahri(is_aram=True, **{field: bad}))
    assert out["ok"] is True


# -- F2: a wrong-shaped list field reached the paid prompt as garbage -------

def test_f2_string_team_is_not_split_into_characters():
    _, client = _run(_ahri(my_team="Yuumi"))
    assert "Y, u, u, m, i" not in client.prompt
    assert "My team: ?" in client.prompt


def test_f2_dict_team_does_not_contribute_its_keys():
    _, client = _run(_ahri(their_team={"Zed": 1}))
    assert "Zed" not in client.prompt


def test_f2_non_string_entries_are_dropped_and_strings_kept():
    _, client = _run(_ahri(my_team=[["x", 1], 7, True, {"a": 1}, "Yuumi"]))
    assert "My team: Yuumi\n" in client.prompt


# -- F3: a champion that is not a name still bought a Haiku call ------------

@pytest.mark.parametrize("bad", [
    {"x": 1}, ["Ahri"], 7, 1.5, True,
    "   ", "\x00\x01", "\n", chr(0x200B), "???", "A" * 65,
])
def test_f3_unusable_champion_is_refused_before_any_spend(bad):
    out, client = _run({"my_champion": bad})
    assert client.calls == []
    assert out["ok"] is False
    assert out["advice"] == NO_CHAMPION


@pytest.mark.parametrize("bad", [
    chr(0x3164) + "???", chr(0x3164) + "\n", chr(0x3164) + "```",
    "system:", "```", "<system>",
])
def test_f3_name_left_with_nothing_after_sanitising_is_refused(bad):
    """The letter-or-digit test reads the SANITISED text: U+3164 is alnum but
    cleans to a space, and a bare role marker cleans to the blocked marker."""
    out, client = _run({"my_champion": bad})
    assert client.calls == []
    assert out["advice"] == NO_CHAMPION


def test_f3_team_entry_left_with_nothing_after_sanitising_is_dropped():
    _, client = _run(_ahri(my_team=["system:", chr(0x3164) + "\n", "Yuumi"]))
    assert "My team: Yuumi\n" in client.prompt


@pytest.mark.parametrize("bad", [
    # Each is at most 64 raw chars with no letter or digit, but sanitises past
    # clean()'s own 200-char cap, which would cut a token into a fragment whose
    # letters came from the sanitiser and pass the letter-or-digit test.
    "--" + "\n" * 62,
    "``` " * 16,
])
def test_f3_name_that_sanitises_past_the_cap_is_refused(bad):
    out, client = _run({"my_champion": bad})
    assert client.calls == []
    assert out["advice"] == NO_CHAMPION


def test_f3_name_that_sanitises_past_the_cap_is_dropped_not_cut():
    """Letters present, but the sanitised form is over the cap, so keeping it
    would mean cutting it, and an entry is dropped rather than cut."""
    bad = "A" + "\n" * 63
    _, client = _run(_ahri(my_team=[bad, "Yuumi"]))
    assert "My team: Yuumi\n" in client.prompt


def test_f3_injection_phrase_inside_the_limit_still_reaches_the_prompt_marked():
    name = "Vayne system: x"
    _, client = _run({"my_champion": name})
    assert "[BLOCKED:override]" in client.prompt
    assert "system:" not in client.prompt.split("Coach this pick")[0]


@pytest.mark.parametrize("name", [
    "Cho'Gath", "Nunu & Willump", "K'Sante",
    # Localized client names: Ahri in Korean, Ahri in Chinese, Lux in Russian.
    chr(0xC544) + chr(0xB9AC), chr(0x963F) + chr(0x72F8),
    chr(0x41B) + chr(0x44E) + chr(0x43A) + chr(0x441),
])
def test_f3_real_names_are_accepted(name):
    out, client = _run({"my_champion": name})
    assert out["ok"] is True
    assert f"My champion: {name}\n" in client.prompt


def test_f3_champion_of_exactly_the_limit_is_accepted():
    _, client = _run({"my_champion": "A" * 64})
    assert client.calls


def test_f3_overlong_team_entry_is_dropped_not_truncated():
    """A cut mid-phrase could leave half an injection the sanitizer's
    patterns no longer match, so an oversized entry goes whole."""
    _, client = _run(_ahri(my_team=["B" * 65, "Yuumi"]))
    assert "BBB" not in client.prompt
    assert "My team: Yuumi\n" in client.prompt


# -- F4: the string "false" read as True ------------------------------------

@pytest.mark.parametrize("flag", ["false", "0", 1, [0]])
def test_f4_non_bool_is_aram_is_not_aram(flag):
    _, client = _run(_ahri(is_aram=flag, bench=["Jinx"]))
    assert "Mode: ARAM" not in client.prompt
    assert "Bench:" not in client.prompt


def test_f4_real_true_is_aram():
    _, client = _run(_ahri(is_aram=True, bench=["Jinx"]))
    assert "Mode: ARAM\n" in client.prompt
    assert "Bench: Jinx\n" in client.prompt


# -- F5: Arena (and any ARAM queue not flagged) was told it was on SR -------

def test_f5_arena_queue_is_not_labelled_summoners_rift():
    _, client = _run(_ahri(queue_id=1750))
    assert "Mode: Arena\n" in client.prompt


@pytest.mark.parametrize("qid", [450, 2400])
def test_f5_aram_queue_reads_as_aram_without_the_flag(qid):
    _, client = _run(_ahri(queue_id=qid, bench=["Jinx"]))
    assert "Mode: ARAM\n" in client.prompt
    assert "Bench: Jinx\n" in client.prompt


@pytest.mark.parametrize("qid", [
    None, 0, -1, 420, "1750", True, float("inf"), float("nan"), [1750],
])
def test_f5_other_queue_values_keep_the_rift_label_and_do_not_raise(qid):
    _, client = _run(_ahri(queue_id=qid))
    assert "Mode: Summoner's Rift draft/blind\n" in client.prompt


# -- F6: an unbounded list became an unbounded paid prompt ------------------

@pytest.mark.parametrize("field", ["my_team", "their_team", "bench"])
def test_f6_list_fields_are_capped(field):
    names = [f"Champ{i}" for i in range(100_000)]
    _, client = _run(_ahri(is_aram=True, **{field: names}))
    assert len(client.prompt) < 2000
    assert "Champ15" in client.prompt
    assert "Champ16" not in client.prompt


def test_f6_cap_counts_entries_read_not_entries_kept():
    """The bound is on the work done for one request, so junk entries in
    front use up the budget rather than being skipped for free."""
    _, client = _run(_ahri(my_team=[None] * 16 + ["Yuumi"]))
    assert "Yuumi" not in client.prompt


# -- F7: "one Haiku call per invocation" was up to three --------------------

def test_f7_client_is_built_with_retries_off():
    _, client = _run(_ahri())
    assert client.ctor.get("max_retries") == 0
    assert client.ctor.get("base_url") == "https://api.anthropic.com"


# -- F8: a client (and its connection pool) per call, never closed ----------

def test_f8_client_closed_after_success():
    _, client = _run(_ahri())
    assert client.closed == 1


def test_f8_client_closed_after_api_error():
    _, client = _run(_ahri(), reply=RuntimeError("boom"))
    assert client.closed == 1


def test_f8_a_failing_close_does_not_lose_the_paid_answer():
    client = _Client(_Resp([_Block(GOOD_REPLY)]))
    client.close = MagicMock(side_effect=OSError("close failed"))
    mod = types.SimpleNamespace(Anthropic=lambda **kw: client)
    with patch.dict(sys.modules, {"anthropic": mod}), \
            patch("core.cost_tracker.get_tracker", return_value=_tracker()):
        out = C.coach_pick(_ahri(), FAKE_KEY)
    assert out["ok"] is True
    assert out["advice"] == "Stay Ahri"


def test_f8_a_failing_constructor_degrades_with_nothing_to_close(caplog):
    def _boom(**kw):
        raise RuntimeError("ctor failed")

    mod = types.SimpleNamespace(Anthropic=_boom)
    with caplog.at_level(logging.DEBUG, logger=C.logger.name), \
            patch.dict(sys.modules, {"anthropic": mod}), \
            patch("core.cost_tracker.get_tracker", return_value=_tracker()):
        out = C.coach_pick(_ahri(), FAKE_KEY)
    assert out["ok"] is False
    assert out["advice"] == PAUSED
    assert not any("client close" in r.getMessage() for r in caplog.records)


def _sdk_timeout():
    """A timeout of the HTTP library this SDK is built on: httpx2 from 1.x,
    httpx before. Any other library's exception would not be retried."""
    pytest.importorskip("anthropic")
    from anthropic import _base_client
    lib = getattr(_base_client, "httpx2", None) or _base_client.httpx
    return lib.TimeoutException("simulated")


def _real_sdk_run(monkeypatch, send):
    import anthropic
    from anthropic import _base_client

    made = []

    class _Recording(anthropic.Anthropic):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            made.append(self)

    monkeypatch.setattr(anthropic, "Anthropic", _Recording)
    monkeypatch.setattr(_base_client.SyncHttpxClientWrapper, "send", send)
    with patch("core.cost_tracker.get_tracker", return_value=_tracker()):
        out = C.coach_pick(_ahri(), FAKE_KEY)
    return out, made


def test_f7_real_sdk_makes_one_attempt_on_a_timeout(monkeypatch):
    timeout = _sdk_timeout()
    attempts = []

    def _send(self, *a, **kw):
        attempts.append(1)
        raise timeout

    out, _ = _real_sdk_run(monkeypatch, _send)
    assert len(attempts) == 1
    assert out["advice"] == PAUSED


def test_f8_real_sdk_client_is_closed(monkeypatch):
    timeout = _sdk_timeout()

    def _send(self, *a, **kw):
        raise timeout

    _, made = _real_sdk_run(monkeypatch, _send)
    assert len(made) == 1
    assert made[0].is_closed() is True


# -- F9: a paid reply with no parsable advice answered a blank panel --------

@pytest.mark.parametrize("reply", [
    "**Advice:** Stay Ahri\n**Swap:** Jinx\n**Summoners:** Flash\n"
    "**Watchout:** Zed",
    "**Advice**: Stay Ahri\n**Swap**: Jinx\n**Summoners**: Flash\n"
    "**Watchout**: Zed",
    "- Advice: Stay Ahri\n- Swap: Jinx\n- Summoners: Flash\n- Watchout: Zed",
    "## Advice: Stay Ahri\n## Swap: Jinx\n## Summoners: Flash\n## Watchout: Zed",
    "1. Advice: Stay Ahri\n2. Swap: Jinx\n3. Summoners: Flash\n4. Watchout: Zed",
    f"{chr(0x2022)} Advice: Stay Ahri\n{chr(0x2022)} Swap: Jinx\n"
    f"{chr(0x2022)} Summoners: Flash\n{chr(0x2022)} Watchout: Zed",
    "Advice: **Stay Ahri**\nSwap: _Jinx_\nSummoners: `Flash`\nWatchout: **Zed**",
])
def test_f9_markdown_decorated_reply_is_still_read(reply):
    out, _ = _run(_ahri(is_aram=True, bench=["Jinx"]), reply=reply)
    assert out["ok"] is True
    assert out["advice"] == "Stay Ahri"
    assert out["swap"] == "Jinx"
    assert out["summoners"] == "Flash"
    assert out["watchout"] == "Zed"


@pytest.mark.parametrize("line, expected", [
    ("**1. Advice:** Stay Ahri", "Stay Ahri"),
    ("**Advice: Stay Ahri**.", "Stay Ahri."),
    ("**Advice: Stay Ahri** - extra", "Stay Ahri - extra"),
    ("_**Advice:**_ Stay Ahri", "Stay Ahri"),
    ("**_Advice:_** Stay Ahri", "Stay Ahri"),
    ("Advice**:** Stay Ahri", "Stay Ahri"),
    ("`Advice:` Stay Ahri", "Stay Ahri"),
    ("*Advice: Stay Ahri*", "Stay Ahri"),
    ("_Advice: Stay Ahri_", "Stay Ahri"),
    ("**Advice: Stay **Ahri** now**", "Stay **Ahri** now"),
])
def test_f9_decoration_with_no_pair_is_removed(line, expected):
    assert C._parse_response(line)["advice"] == expected


@pytest.mark.parametrize("value", [
    "Stay **Ahri**", "_x_ y", "**A** and **B**", "a*b*c", "use snake_case here",
    "Flash * Heal",
])
def test_f9_markdown_inside_a_value_is_left_alone(value):
    assert C._parse_response(f"Advice: {value}")["advice"] == value


@pytest.mark.parametrize("line", [
    "**Advice: Stay Ahri**", "**Advice:**Stay Ahri", "**Advice:** Stay Ahri",
    "**Advice**: Stay Ahri", "- **Advice:** Stay Ahri", "Advice: ** Stay Ahri **",
    "__Advice: Stay Ahri__", "**Advice**: **Stay Ahri**",
])
def test_f9_bold_opened_by_the_label_is_closed_wherever_it_lands(line):
    assert C._parse_response(line)["advice"] == "Stay Ahri"


def test_f9_markup_in_the_text_survives_a_bold_label():
    fields = C._parse_response("**Advice:** Stay **Ahri** now")
    assert fields["advice"] == "Stay **Ahri** now"


def test_f9_closing_bold_of_the_label_is_not_read_as_the_value():
    fields = C._parse_response("**Advice:**\nAdvice: real")
    assert fields["advice"] == "real"


@pytest.mark.parametrize("line, expected", [
    ("* **Advice:** Stay Ahri", "Stay Ahri"),
    ("* Advice: Stay Ahri", "Stay Ahri"),
    ("* Advice: Stay **Ahri**", "Stay **Ahri**"),
    ("* Advice: **Stay Ahri**", "Stay Ahri"),
    ("* **Advice: Stay Ahri**", "Stay Ahri"),
    ("*Advice:* Stay Ahri", "Stay Ahri"),
])
def test_f9_a_star_bullet_is_not_a_bold_opener(line, expected):
    assert C._parse_response(line)["advice"] == expected


@pytest.mark.parametrize("value", [".", "-", "**", "...", "?"])
def test_f9_a_value_with_no_letter_or_digit_is_no_advice(value):
    out, _ = _run(_ahri(), reply=f"Advice: {value}")
    assert out["ok"] is False
    assert out["advice"] == PAUSED


def test_f9_a_label_needs_more_than_its_letters_nearby():
    fields = C._parse_response("Advice column: nope\nreadvice: nope")
    assert fields["advice"] == ""


@pytest.mark.parametrize("reply", ["Stay on Ahri, she is good.", "", "   \n "])
def test_f9_reply_without_advice_degrades_and_logs(reply, caplog):
    with caplog.at_level(logging.WARNING, logger=C.logger.name):
        out, _ = _run(_ahri(), reply=reply)
    assert out["ok"] is False
    assert out["advice"] == PAUSED
    assert any("no advice" in r.getMessage() for r in caplog.records)


def test_f9_refusal_degrades_even_with_text_present(caplog):
    resp = _Resp([_Block("Advice: not this")], stop_reason="refusal")
    with caplog.at_level(logging.WARNING, logger=C.logger.name):
        out, _ = _run(_ahri(), reply=resp)
    assert out["ok"] is False
    assert out["advice"] == PAUSED
    assert out["raw"] == ""
    assert any("refusal" in r.getMessage() for r in caplog.records)


def test_f9_max_tokens_stop_keeps_the_advice_it_got():
    resp = _Resp([_Block("Advice: Stay Ahri\nSwap: no")],
                 stop_reason="max_tokens")
    out, _ = _run(_ahri(), reply=resp)
    assert out["ok"] is True
    assert out["advice"] == "Stay Ahri"


# -- F10: reply block shapes ------------------------------------------------

def test_f10_none_text_does_not_raise():
    out, _ = _run(_ahri(), reply=_Resp([_Block(None)]))
    assert out["ok"] is False
    assert out["advice"] == PAUSED
    assert out["raw"] == ""


def test_f10_empty_content_degrades():
    out, _ = _run(_ahri(), reply=_Resp([]))
    assert out["ok"] is False
    assert out["advice"] == PAUSED


def test_f10_a_non_text_first_block_does_not_lose_later_text():
    first = types.SimpleNamespace(type="thinking")
    out, _ = _run(_ahri(), reply=_Resp([first, _Block(GOOD_REPLY)]))
    assert out["ok"] is True
    assert out["advice"] == "Stay Ahri"


def test_f10_text_across_several_blocks_is_joined():
    resp = _Resp([_Block("Advice: Stay Ahri"), _Block("Watchout: Zed")])
    out, _ = _run(_ahri(), reply=resp)
    assert out["advice"] == "Stay Ahri"
    assert out["watchout"] == "Zed"


# -- F11: "no swap" spelled any other way was shown as a swap ---------------

def _swap_reply(value):
    return f"Advice: a\nSwap: {value}\nSummoners: x\nWatchout: w"


@pytest.mark.parametrize("value", [
    "none", "None", "None.", "NONE", "'none'", "none - stay on Ahri",
    "No swap", "no swap needed", "N/A", "n/a", "NA", "**none**", "",
    "no", "No.", "no-swap", "No bench swap", "[none]", "-", "--",
    chr(0x201C) + "none" + chr(0x201D), "_none_",
    "Not applicable", "Not needed", "Nope", "N.A.", "nil", "Nil.", "Don't swap",
    "don" + chr(0x2019) + "t swap", "dont swap", "Nothing better on bench",
    "Keep Ahri", "Stay", "Stay on Ahri",
])
def test_f11_no_swap_spellings_are_empty(value):
    out, _ = _run(_ahri(is_aram=True, bench=["Jinx"]), reply=_swap_reply(value))
    assert out["swap"] == ""


def test_f11_a_real_swap_is_kept():
    out, _ = _run(_ahri(is_aram=True, bench=["Jinx"]),
                  reply=_swap_reply("Swap to Jinx"))
    assert out["swap"] == "Swap to Jinx"


@pytest.mark.parametrize("value", [
    "Nonetheless take Jinx", "Nocturne if on bench", "Nilah is the better pick",
    "Notable upgrade: Jinx", "Donkey Kong", "Keeper of the bench: Jinx",
])
def test_f11_a_word_starting_with_no_or_none_is_not_no_swap(value):
    out, _ = _run(_ahri(is_aram=True, bench=["Jinx"]), reply=_swap_reply(value))
    assert out["swap"] == value


def test_f11_swap_is_empty_outside_aram():
    out, _ = _run(_ahri(bench=["Jinx"]), reply=_swap_reply("Swap to Jinx"))
    assert out["swap"] == ""


def test_f11_swap_is_empty_with_an_empty_bench():
    out, _ = _run(_ahri(is_aram=True), reply=_swap_reply("Swap to Jinx"))
    assert out["swap"] == ""


# -- F12: a later blank label erased a good value ---------------------------

def test_f12_first_non_empty_value_wins():
    fields = C._parse_response("Advice: real\nAdvice:\nAdvice: later")
    assert fields["advice"] == "real"


def test_f12_a_leading_blank_label_does_not_block_a_later_value():
    fields = C._parse_response("Advice:\nAdvice: real")
    assert fields["advice"] == "real"


# -- F13: a gate that cannot be read still spends, but no longer silently ---

def test_f13_gate_failure_is_logged_and_the_coach_still_answers(caplog):
    bad = MagicMock()
    bad.gate_disabled.side_effect = TypeError("bad config value")
    with caplog.at_level(logging.WARNING, logger=C.logger.name):
        out, client = _run(_ahri(), tracker=bad)
    assert client.calls
    assert out["ok"] is True
    assert any("spend gate" in r.getMessage() and "TypeError" in r.getMessage()
               for r in caplog.records)


def test_f13_disabled_gate_still_stops_the_call():
    out, client = _run(_ahri(), tracker=_tracker(disabled=True))
    assert client.calls == []
    assert out["advice"] == "(champ-select coach disabled)"


# -- F14: a key that cannot authenticate reached the SDK --------------------

@pytest.mark.parametrize("key", [
    "", "   ", "\n", None, 5, b"bytes", "sk\nsecret", "sk secret", "sk\x00secret",
    "sk" + chr(0xE9) + "secret",
])
def test_f14_unusable_key_is_refused_before_the_sdk(key):
    out, client = _run(_ahri(), key=key)
    assert client.calls == []
    assert client.ctor == {}
    assert out["ok"] is False
    assert "API key missing" in out["advice"]


def test_f14_key_is_stripped_before_the_sdk():
    _, client = _run(_ahri(), key=f"  {FAKE_KEY}\n")
    assert client.ctor["api_key"] == FAKE_KEY


# -- F15: the key could reach the log through an exception message ----------

def test_f15_key_in_exception_text_is_redacted_from_log_and_answer(caplog):
    exc = RuntimeError(f"Illegal header value b'{FAKE_KEY}'")
    with caplog.at_level(logging.DEBUG, logger=C.logger.name):
        out, _ = _run(_ahri(), reply=exc)
    assert caplog.records, "the failure was not logged at all"
    for rec in caplog.records:
        assert FAKE_KEY not in rec.getMessage()
        assert not rec.exc_info
    assert FAKE_KEY not in repr(out)
    assert any("RuntimeError" in r.getMessage() for r in caplog.records)


def test_f15_key_surrounded_by_whitespace_is_still_redacted(caplog):
    exc = RuntimeError(f"bad header {FAKE_KEY}")
    with caplog.at_level(logging.WARNING, logger=C.logger.name):
        _run(_ahri(), reply=exc, key=f" {FAKE_KEY}\n")
    assert all(FAKE_KEY not in r.getMessage() for r in caplog.records)


class _BadStr(Exception):
    def __str__(self):
        raise ValueError("no text for you")


_NOT_A_STR = 5  # a name, so the deliberate non-str __str__ below is not a literal


class _NotStr(Exception):
    def __str__(self):
        return _NOT_A_STR


@pytest.mark.parametrize("exc_type", [_BadStr, _NotStr])
def test_f15_exception_that_cannot_render_still_degrades(exc_type, caplog):
    with caplog.at_level(logging.WARNING, logger=C.logger.name):
        out, client = _run(_ahri(), reply=exc_type())
    assert out["advice"] == PAUSED
    assert client.closed == 1
    assert any(exc_type.__name__ in r.getMessage() for r in caplog.records)


def test_f15_unprintable_stop_reason_cannot_raise(caplog):
    class _Stop:
        def __str__(self):
            raise ValueError("no text")

    with caplog.at_level(logging.WARNING, logger=C.logger.name):
        out, _ = _run(_ahri(), reply=_Resp([], stop_reason=_Stop()))
    assert out["advice"] == PAUSED
    assert any("_Stop" in r.getMessage() for r in caplog.records)


def test_f15_control_characters_in_exception_text_stay_on_one_line(caplog):
    exc = RuntimeError("line one\nFAKE LOG LINE")
    with caplog.at_level(logging.WARNING, logger=C.logger.name):
        _run(_ahri(), reply=exc)
    assert all("\n" not in r.getMessage() for r in caplog.records)


# -- F16: elapsed_ms came from the wall clock and skipped the failure path --

def test_f16_elapsed_uses_a_monotonic_clock():
    with patch.object(C.time, "time", side_effect=[1000.0, 10.0]):
        out, _ = _run(_ahri())
    assert out["elapsed_ms"] >= 0


def test_f16_elapsed_is_reported_on_the_failure_path():
    with patch.object(C.time, "perf_counter", side_effect=[1.0, 3.5]):
        out, _ = _run(_ahri(), reply=RuntimeError("boom"))
    assert out["elapsed_ms"] == 2500


# -- F17: a paid call that could not be recorded was only a DEBUG line ------

def test_f17_cost_record_failure_is_a_warning_and_keeps_the_answer(caplog):
    with caplog.at_level(logging.WARNING, logger=C.logger.name), \
            patch("core.cost_tracker.record_anthropic_response",
                  side_effect=RuntimeError("ledger down")):
        out, _ = _run(_ahri())
    assert out["ok"] is True
    assert any("cost_tracker" in r.getMessage() for r in caplog.records)


# -- Characterization: the contract the fixes must not move -----------------

def test_char_full_result_shape():
    out, _ = _run(_ahri())
    assert set(out) == {"ok", "advice", "swap", "summoners", "watchout",
                        "raw", "elapsed_ms"}
    assert out["raw"] == GOOD_REPLY


@pytest.mark.parametrize("state", [None, [], "x", 5, {}, {"my_champion": ""},
                                   {"my_champion": None}])
def test_char_bad_state_answers_no_champion_with_no_call(state):
    out, client = _run(state)
    assert client.calls == []
    assert out["advice"] == NO_CHAMPION


def test_char_gate_is_checked_before_the_key():
    out, _ = _run(_ahri(), key="", tracker=_tracker(disabled=True))
    assert out["advice"] == "(champ-select coach disabled)"


def test_char_api_error_text_never_reaches_the_answer():
    exc = RuntimeError("Error code: 429 - credit balance exhausted")
    out, _ = _run(_ahri(), reply=exc)
    assert out["advice"] == PAUSED
    assert "429" not in repr(out)


def test_char_raw_is_capped():
    out, _ = _run(_ahri(), reply="Advice: a\n" + "x" * 5000)
    assert len(out["raw"]) == 1500


def test_char_field_values_are_capped():
    out, _ = _run(_ahri(), reply="Advice: " + "x" * 5000)
    assert len(out["advice"]) == 200


def test_char_braces_in_a_name_are_not_format_fields():
    out, client = _run({"my_champion": "{mode_label}"})
    assert out["ok"] is True
    assert "My champion: {mode_label}\n" in client.prompt
