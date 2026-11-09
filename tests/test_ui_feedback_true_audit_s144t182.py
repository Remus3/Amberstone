"""True-audit s144 cycle 182: agents/agent7_context/ui_feedback.py.

Each test pins one finding of the audit (F-numbers match the cycle
report). The parser is reached by POST /api/input with sim_context=true
(agents/_supervisor_http.py _handle_input), so every input here is
untrusted: the operator's text, the client-sent history and the model's
JSON reply.
"""
from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import agents.agent7_context.ui_feedback as ufb
from agents.agent4_coach_mentor.ui_applier import MAX_CHANGES, MAX_FILE_BYTES
from tests._timing_budget import fleet_test_guard

_BASE_CSS = (
    ":root {\n  --canvas: #2B2721;\n  --text: #E8DFD3;\n  --accent2: #101010;\n}\n"
    "body {\n  font-size: 20px; font-weight: 400;\n}\n"
    ".title { font-size: 24px; }\n"
)


class _FakeScheduler:
    """Records file_task calls; returns an object with an ``id``."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def file_task(self, **kw: Any) -> SimpleNamespace:
        self.calls.append(kw)
        return SimpleNamespace(id=f"t-{len(self.calls)}")


def _parser(tmp_path: Path, monkeypatch, css: str = _BASE_CSS, llm=None):
    monkeypatch.setattr(ufb, "_PROJECT_ROOT", tmp_path)
    path = tmp_path / "web" / "css" / "panels" / "base.css"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(css.encode("utf-8"))
    sched = _FakeScheduler()
    return ufb.UIFeedbackParser(scheduler=sched, llm_spawn=llm), sched


def _env(text: Any, **extra: Any) -> dict:
    return {"ok": True, "result": {"result": text, **extra}}


def _llm_returning(envelope: Any):
    def _spawn(agent, task_id, op, payload):
        return envelope
    return _spawn


# -- F1: a result with no changes never files a ui-proposal ------------

def test_f1_font_noop_files_nothing(tmp_path: Path, monkeypatch) -> None:
    p, sched = _parser(tmp_path, monkeypatch)
    r = p.parse("make the font 1% bigger")
    assert r.intent == "ui_feedback_noop"
    assert r.filed == []
    assert sched.calls == []


def test_f1_missing_color_var_files_nothing(tmp_path: Path, monkeypatch) -> None:
    p, sched = _parser(tmp_path, monkeypatch)
    r = p.parse("set --nosuchvar to #123456")
    assert r.intent == "ui_feedback_noop"
    assert sched.calls == []


def test_f1_llm_reply_only_files_nothing(tmp_path: Path, monkeypatch) -> None:
    llm = _llm_returning(_env('{"reply": "That panel is already centered."}'))
    p, sched = _parser(tmp_path, monkeypatch, llm=llm)
    r = p.parse("is the minimap panel centered")
    assert r.reply == "That panel is already centered."
    assert r.used_llm is True
    assert r.proposed_changes == []
    assert r.filed == []
    assert sched.calls == []


# -- F2: the bypass prefix needs a word boundary -----------------------

@pytest.mark.parametrize("text", [
    "bypass devtools font bigger",
    "bypass developer mode and make the font bigger",
])
def test_f2_bypass_prefix_is_a_whole_word(tmp_path: Path, monkeypatch, text) -> None:
    p, sched = _parser(tmp_path, monkeypatch)
    r = p.parse(text)
    assert r.bypass_dev is False
    assert all(c.get("user_override") is not True for c in sched.calls)


@pytest.mark.parametrize("text", [
    "bypass dev: make the font bigger",
    "bypass dev - make the font bigger",
    "BYPASS DEV make the font bigger",
])
def test_f2_real_bypass_prefix_still_works(tmp_path: Path, monkeypatch, text) -> None:
    p, sched = _parser(tmp_path, monkeypatch)
    r = p.parse(text)
    assert r.bypass_dev is True
    assert r.proposed_changes
    assert sched.calls[-1]["user_override"] is True


# -- F3: the percentage parse ------------------------------------------

def test_f3_three_digit_percent_is_not_its_last_two_digits(
        tmp_path: Path, monkeypatch) -> None:
    p, _ = _parser(tmp_path, monkeypatch)
    r = p.parse("make the font 150% bigger")
    # 150% bigger clamps to x2.0 -> 40px base; reading "50" gave 30px.
    assert "40px" in r.reply, r.reply


def test_f3_hundred_percent_is_not_zero(tmp_path: Path, monkeypatch) -> None:
    p, _ = _parser(tmp_path, monkeypatch)
    r = p.parse("make the font 100% bigger")
    assert r.intent == "ui_feedback_font_scale", r.reply
    assert "40px" in r.reply


# -- F4: the base-font rule --------------------------------------------

def test_f4_tbody_rule_is_not_the_body_base(tmp_path: Path, monkeypatch) -> None:
    css = (
        "tbody { font-size: 12px; }\n"
        "body {\n  font-size: 20px;\n}\n"
    )
    p, _ = _parser(tmp_path, monkeypatch, css=css)
    r = p.parse("make the font 25% bigger")
    assert "base 20px" in r.reply, r.reply


def test_f4_zero_base_font_does_not_raise(tmp_path: Path, monkeypatch) -> None:
    css = "body {\n  font-size: 0px;\n}\n"
    p, sched = _parser(tmp_path, monkeypatch, css=css)
    r = p.parse("make the font bigger")   # was ZeroDivisionError -> HTTP 500
    assert r.proposed_changes == []
    assert all(c["op"] != "ui-proposal" for c in sched.calls)


# -- F5: the 8px floor -------------------------------------------------

def test_f5_shrink_never_enlarges_a_small_token(tmp_path: Path, monkeypatch) -> None:
    css = (
        "body {\n  font-size: 20px;\n}\n"
        ".tiny { font-size: 7px; }\n.hidden { font-size: 0px; }\n"
    )
    p, _ = _parser(tmp_path, monkeypatch, css=css)
    r = p.parse("make the text 20% smaller")
    content = r.proposed_changes[0]["content"]
    assert ".tiny { font-size: 7px; }" in content
    assert ".hidden { font-size: 0px; }" in content
    assert "font-size: 16px" in content


# -- F6: the colour value ----------------------------------------------

def test_f6_backslash_in_rgb_does_not_raise(tmp_path: Path, monkeypatch) -> None:
    p, sched = _parser(tmp_path, monkeypatch)
    # Was re.error ("bad escape") out of re.subn's template -> HTTP 500.
    r = p.parse(r"set --canvas to rgb(\q)")
    assert r.proposed_changes == []
    assert all(c["op"] != "ui-proposal" for c in sched.calls)


def test_f6_group_reference_is_not_expanded(tmp_path: Path, monkeypatch) -> None:
    p, _ = _parser(tmp_path, monkeypatch)
    # re.subn's template expanded \g<0> to the whole old declaration:
    # "--canvas: rgb(--canvas: #2B2721;);".
    r = p.parse(r"set --canvas to rgb(\g<0>)")
    assert r.proposed_changes == []


def test_f6_css_injection_through_rgb_is_refused(tmp_path: Path, monkeypatch) -> None:
    p, _ = _parser(tmp_path, monkeypatch)
    r = p.parse("set --canvas to rgb(0,0,0;} body{display:none)")
    for ch in r.proposed_changes:
        assert "display:none" not in ch["content"]


@pytest.mark.parametrize("val", ["#12345", "#1234567", "#123456789"])
def test_f6_invalid_hex_length_is_not_applied(tmp_path: Path, monkeypatch, val) -> None:
    p, _ = _parser(tmp_path, monkeypatch)
    r = p.parse(f"set --canvas to {val}")
    for ch in r.proposed_changes:
        assert "--canvas: #2B2721;" in ch["content"], ch["content"]


@pytest.mark.parametrize("val", ["#abc", "#abcd", "#a1b2c3", "#a1b2c3d4",
                                 "rgb(1, 2, 3)", "rgba(1, 2, 3, 0.5)"])
def test_f6_valid_colours_still_apply(tmp_path: Path, monkeypatch, val) -> None:
    p, _ = _parser(tmp_path, monkeypatch)
    r = p.parse(f"set --canvas to {val}")
    assert r.proposed_changes, r.reply
    assert f"--canvas: {val};" in r.proposed_changes[0]["content"]


# -- F7: the declaration match -----------------------------------------

def test_f7_declaration_without_semicolon_does_not_eat_next_rule(
        tmp_path: Path, monkeypatch) -> None:
    css = ":root { --canvas: #000 }\nbody { color: red; font-size: 20px; }\n"
    p, _ = _parser(tmp_path, monkeypatch, css=css)
    r = p.parse("set --canvas to #ffffff")
    content = r.proposed_changes[0]["content"]
    assert "body { color: red; font-size: 20px; }" in content, content
    assert "--canvas: #ffffff" in content


def test_f7_suffix_var_is_not_matched(tmp_path: Path, monkeypatch) -> None:
    css = ":root { --hud--text: #000; --text: #111; }\n"
    p, _ = _parser(tmp_path, monkeypatch, css=css)
    r = p.parse("set --text to #222222")
    content = r.proposed_changes[0]["content"]
    assert "--hud--text: #000;" in content, content
    assert "--text: #222222;" in content


def test_f7_var_with_digit(tmp_path: Path, monkeypatch) -> None:
    p, _ = _parser(tmp_path, monkeypatch)
    r = p.parse("set --accent2 to #fafafa")
    assert r.proposed_changes, r.reply
    assert "--accent2: #fafafa;" in r.proposed_changes[0]["content"]


# -- F8: the LLM envelope ----------------------------------------------

@pytest.mark.parametrize("env", [
    None,
    "a bare string",
    {"ok": False, "result": {"result": '{"reply": "x"}'}},
    {"ok": True, "result": {"result": '{"reply": "Credit balance is too low"}',
                            "is_error": True}},
    {"ok": True, "result": {"result": {"nested": "dict"}}},
    {"ok": True, "result": None},
])
def test_f8_unusable_envelope_degrades_to_unhandled(
        tmp_path: Path, monkeypatch, env) -> None:
    p, sched = _parser(tmp_path, monkeypatch, llm=_llm_returning(env))
    r = p.parse("rearrange the minimap to the right side")
    assert r.intent == "ui_feedback_unhandled"
    assert "Credit" not in r.reply
    assert [c["op"] for c in sched.calls] == ["ui-feedback-unhandled"]


def test_f8_prose_braces_around_the_object(tmp_path: Path, monkeypatch) -> None:
    text = 'Sure {as asked}: {"reply": "Moved it."} - done {ok}'
    p, _ = _parser(tmp_path, monkeypatch, llm=_llm_returning(_env(text)))
    r = p.parse("rearrange the minimap to the right side")
    assert r.reply == "Moved it."


def test_f8_spawn_raising_unexpected_type_degrades(tmp_path: Path, monkeypatch) -> None:
    def _boom(*a):
        raise RuntimeError("spawn died")
    p, _ = _parser(tmp_path, monkeypatch, llm=_boom)
    r = p.parse("rearrange the minimap to the right side")
    assert r.intent == "ui_feedback_unhandled"


# -- F9: the LLM changes list ------------------------------------------

def _changes_env(changes: list, reply: str = "ok") -> dict:
    import json
    return _env(json.dumps({"reply": reply, "changes": changes}))


def test_f9_one_malformed_change_refuses_the_whole_proposal(
        tmp_path: Path, monkeypatch) -> None:
    env = _changes_env([
        {"file": "web/css/panels/base.css", "content": "a {}", "summary": "s"},
        {"file": "web/index.html", "content": 42},
    ])
    p, sched = _parser(tmp_path, monkeypatch, llm=_llm_returning(env))
    r = p.parse("rearrange the minimap to the right side")
    assert r.refused is True
    assert r.proposed_changes == []
    assert all(c["op"] != "ui-proposal" for c in sched.calls)


def test_f9_too_many_changes_refused(tmp_path: Path, monkeypatch) -> None:
    env = _changes_env([
        {"file": f"web/css/panels/p{i}.css", "content": "a {}"}
        for i in range(MAX_CHANGES + 1)
    ])
    p, sched = _parser(tmp_path, monkeypatch, llm=_llm_returning(env))
    r = p.parse("rearrange the minimap to the right side")
    assert r.refused is True
    assert sched.calls == []


def test_f9_duplicate_file_refused(tmp_path: Path, monkeypatch) -> None:
    env = _changes_env([
        {"file": "web/css/panels/base.css", "content": "a {}"},
        {"file": "web/css/panels/base.css", "content": "b {}"},
    ])
    p, sched = _parser(tmp_path, monkeypatch, llm=_llm_returning(env))
    r = p.parse("rearrange the minimap to the right side")
    assert r.refused is True
    assert sched.calls == []


def test_f9_oversize_content_refused(tmp_path: Path, monkeypatch) -> None:
    env = _changes_env([
        {"file": "web/css/panels/base.css", "content": "a" * (MAX_FILE_BYTES + 1)},
    ])
    p, sched = _parser(tmp_path, monkeypatch, llm=_llm_returning(env))
    r = p.parse("rearrange the minimap to the right side")
    assert r.refused is True
    assert sched.calls == []


def test_f9_non_str_reply_and_summary_are_not_reprd(tmp_path: Path, monkeypatch) -> None:
    env = _changes_env(
        [{"file": "web/css/panels/base.css", "content": "a {}",
          "summary": {"x": 1}}],
        reply={"y": 2},  # type: ignore[arg-type]
    )
    p, sched = _parser(tmp_path, monkeypatch, llm=_llm_returning(env))
    r = p.parse("rearrange the minimap to the right side")
    assert "{" not in r.reply
    assert r.proposed_changes[0]["summary"] == ""
    assert sched.calls[-1]["op"] == "ui-proposal"


def test_f9_valid_llm_proposal_is_filed(tmp_path: Path, monkeypatch) -> None:
    env = _changes_env([
        {"file": "web/css/panels/base.css", "content": "a {}", "summary": "s"},
    ], reply="Done.")
    p, sched = _parser(tmp_path, monkeypatch, llm=_llm_returning(env))
    r = p.parse("rearrange the minimap to the right side")
    assert r.reply == "Done."
    assert r.filed == ["t-1"]
    assert sched.calls[0]["op"] == "ui-proposal"
    assert sched.calls[0]["payload"]["changes"][0]["file"] == "web/css/panels/base.css"


# -- F10: logging --------------------------------------------------------

def test_f10_off_whitelist_log_carries_no_content(
        tmp_path: Path, monkeypatch, caplog) -> None:
    env = _changes_env([
        {"file": "core/secret.py", "content": "SECRET-BODY-MARKER"},
    ])
    p, _ = _parser(tmp_path, monkeypatch, llm=_llm_returning(env))
    with caplog.at_level(logging.WARNING, logger="agent7.ui_feedback"):
        r = p.parse("rearrange the minimap to the right side")
    assert r.refused is True
    assert "SECRET-BODY-MARKER" not in caplog.text
    assert "core/secret.py" in caplog.text


def test_f10_spawn_failure_log_is_redacted(tmp_path: Path, monkeypatch, caplog) -> None:
    key = "sk-ant-api03-" + "A" * 40

    def _boom(*a):
        raise OSError(f"spawn failed with key {key}\nFORGED LINE")
    p, _ = _parser(tmp_path, monkeypatch, llm=_boom)
    with caplog.at_level(logging.WARNING, logger="agent7.ui_feedback"):
        p.parse("rearrange the minimap to the right side")
    assert key not in caplog.text
    assert "\nFORGED LINE" not in caplog.text


# -- F11: argument shapes ----------------------------------------------

@pytest.mark.parametrize("text", [None, 42, b"bytes", ["x"]])
def test_f11_non_str_text_is_empty(tmp_path: Path, monkeypatch, text) -> None:
    p, sched = _parser(tmp_path, monkeypatch)
    r = p.parse(text)  # type: ignore[arg-type]
    assert r.intent == "ui_feedback_empty"
    assert sched.calls == []


def test_f11_non_list_history_and_fixture(tmp_path: Path, monkeypatch) -> None:
    seen: list[dict] = []

    def _spawn(agent, task_id, op, payload):
        seen.append(payload)
        return _env('{"reply": "ok"}')
    p, sched = _parser(tmp_path, monkeypatch, llm=_spawn)
    r = p.parse("rearrange the minimap", history={"a": 1},  # type: ignore[arg-type]
                sim_fixture=123)  # type: ignore[arg-type]
    assert r.reply == "ok"
    assert seen[0]["history"] == []
    assert seen[0]["sim_fixture"] is None


def test_f11_history_items_are_bounded(tmp_path: Path, monkeypatch) -> None:
    seen: list[dict] = []

    def _spawn(agent, task_id, op, payload):
        seen.append(payload)
        return _env('{"reply": "ok"}')
    p, _ = _parser(tmp_path, monkeypatch, llm=_spawn)
    history = ["not a dict", 7] + [
        {"role": "user", "text": "x" * 100_000} for _ in range(10)
    ]
    p.parse("rearrange the minimap", history=history)
    sent = seen[0]["history"]
    assert len(sent) <= 5
    assert all(isinstance(h, dict) for h in sent)
    assert all(len(h["text"]) <= ufb._MAX_HISTORY_FIELD for h in sent)


def test_f11_long_fixture_name_is_clipped(tmp_path: Path, monkeypatch) -> None:
    p, sched = _parser(tmp_path, monkeypatch)
    p.parse("rearrange the minimap", sim_fixture="f" * 10_000)
    assert len(sched.calls[0]["payload"]["sim_fixture"]) <= ufb._MAX_FIXTURE_CHARS


# -- F12: ASCII output ---------------------------------------------------

def test_f12_rule_replies_and_summaries_are_ascii(tmp_path: Path, monkeypatch) -> None:
    p, _ = _parser(tmp_path, monkeypatch)
    for text in ("make the font 25% bigger", "set --canvas to #111111"):
        r = p.parse(text)
        assert r.reply.isascii(), r.reply
        assert all(c["summary"].isascii() for c in r.proposed_changes)


# -- verifier round 1 ----------------------------------------------------

def test_f8_deeply_nested_reply_degrades(tmp_path: Path, monkeypatch) -> None:
    # json's decoder raises RecursionError (not ValueError) on this, which
    # escaped parse() through input_parser._first_json_object -> HTTP 500.
    text = '{"a":' + "[" * 200_000
    p, sched = _parser(tmp_path, monkeypatch, llm=_llm_returning(_env(text)))
    r = p.parse("rearrange the minimap to the right side")
    assert r.intent == "ui_feedback_unhandled"


def test_f3_huge_percent_is_clamped_not_defaulted(tmp_path: Path, monkeypatch) -> None:
    p, _ = _parser(tmp_path, monkeypatch)
    r = p.parse("make the font 5000% bigger")
    assert "40px" in r.reply, r.reply
    r = p.parse("make the font " + "9" * 3000 + "% bigger")
    assert "40px" in r.reply, r.reply[:200]


@pytest.mark.parametrize("var", ["\u017fx", "\u212aey"])
def test_f7_var_name_is_ascii_only(tmp_path: Path, monkeypatch, var) -> None:
    css = ":root { --key: #000; --sx: #000; }\n"
    p, sched = _parser(tmp_path, monkeypatch, css=css)
    r = p.parse(f"set --{var} to #111111")
    assert r.proposed_changes == []
    assert r.reply.isascii()


def test_f8_shared_helper_skips_a_too_deep_candidate() -> None:
    # The helper is shared with InputParser, so the fix covers both.
    from agents.agent7_context.input_parser import _first_json_object
    text = '{"a":' + "[" * 200_000 + ' then {"reply": "ok"}'
    assert _first_json_object(text) == {"reply": "ok"}


# -- verifier round 2 ----------------------------------------------------

@pytest.mark.parametrize("changes", [
    [{"file": "web/css/panels/base.css", "content": "a {}\x00"}],
    [{"file": "web/js/panels/x.js", "content": "function f() { if (1) { if (2) { {"
      + " " * 300 + "\n"}],
    [{"file": "web/js/main.js", "content": "console.log(1);\n"}],
    [{"file": "web/css/panels/A.css", "content": "a {}"},
     {"file": "web/css/panels/a.css", "content": "b {}"}],
])
def test_r2_proposal_the_applier_rejects_is_never_filed(
        tmp_path: Path, monkeypatch, changes) -> None:
    import os
    if changes[0]["file"].endswith("A.css") and os.path.normcase("A") == "A":
        pytest.skip("case-folded duplicate is a Windows-only rule")
    p, sched = _parser(tmp_path, monkeypatch,
                       llm=_llm_returning(_changes_env(changes)))
    r = p.parse("rearrange the minimap to the right side")
    assert r.refused is True, r.reply
    assert sched.calls == []


def test_r2_rule_proposal_passes_the_applier_checks(tmp_path: Path, monkeypatch) -> None:
    from agents.agent4_coach_mentor.ui_applier import _validate_content
    p, sched = _parser(tmp_path, monkeypatch)
    r = p.parse("make the font 25% bigger")
    ch = r.proposed_changes[0]
    _validate_content(ch["file"], ch["content"])
    assert sched.calls[-1]["op"] == "ui-proposal"


def test_r2_long_text_is_answered_fast_without_rules(tmp_path: Path, monkeypatch) -> None:
    import time
    p, sched = _parser(tmp_path, monkeypatch)
    t0 = time.monotonic()
    r = p.parse("bigger " * 30000)
    assert time.monotonic() - t0 < fleet_test_guard.budget(2.0)
    assert r.intent == "ui_feedback_too_long"
    assert sched.calls == []


def test_r2_text_at_the_cap_still_parses(tmp_path: Path, monkeypatch) -> None:
    p, _ = _parser(tmp_path, monkeypatch)
    text = "make the font 25% bigger"
    r = p.parse(text + " " * 10 + "x" * (ufb._MAX_TEXT_CHARS - len(text) - 10))
    assert r.intent == "ui_feedback_font_scale"


def test_r2_reply_states_the_effective_change(tmp_path: Path, monkeypatch) -> None:
    p, _ = _parser(tmp_path, monkeypatch)
    r = p.parse("make the font 5000% bigger")   # 20px -> 40px cap = +100%
    assert "by 100%" in r.reply, r.reply


# -- verifier round 3 ----------------------------------------------------

@pytest.mark.parametrize("text", [
    "make the fonts bigger", "make the fonts larger", "fonts bigger please",
    "texts larger", "typeface bigger", "bigger fonts", "make the text bigger",
])
def test_r3_plural_and_typeface_still_hit_the_font_rule(
        tmp_path: Path, monkeypatch, text) -> None:
    p, _ = _parser(tmp_path, monkeypatch)
    assert p.parse(text).intent == "ui_feedback_font_scale"


@pytest.mark.parametrize("text", ["bigger context menu", "contextual larger"])
def test_r3_word_inside_a_longer_word_is_not_the_font_rule(
        tmp_path: Path, monkeypatch, text) -> None:
    p, _ = _parser(tmp_path, monkeypatch)
    assert p.parse(text).intent != "ui_feedback_font_scale"


# -- verifier round 4 ----------------------------------------------------

@pytest.mark.parametrize("text", [
    "make the fontsize bigger", "make the font-size larger", "font sizes smaller",
    "textsize bigger", "fontface bigger", "font_size bigger", "typefaces larger",
])
def test_r4_fontsize_spellings_hit_the_font_rule(tmp_path: Path, monkeypatch, text) -> None:
    p, _ = _parser(tmp_path, monkeypatch)
    assert p.parse(text).intent == "ui_feedback_font_scale"


@pytest.mark.parametrize("text", ["textbox bigger", "textual bigger"])
def test_r4_compound_words_are_not_font_requests(tmp_path: Path, monkeypatch, text) -> None:
    p, _ = _parser(tmp_path, monkeypatch)
    assert p.parse(text).intent != "ui_feedback_font_scale"


def test_r4_decimal_percent_is_not_its_fraction(tmp_path: Path, monkeypatch) -> None:
    p, sched = _parser(tmp_path, monkeypatch)
    r = p.parse("increase text by 1.5%")   # 20px * 1.015 rounds to 20px
    assert r.intent == "ui_feedback_noop", r.reply
    assert "1.5%" in r.reply
    assert sched.calls == []


def test_r4_percents_word(tmp_path: Path, monkeypatch) -> None:
    p, _ = _parser(tmp_path, monkeypatch)
    r = p.parse("shrink fonts 50percents")   # 20px * 0.5 = 10px
    assert "-> 10px" in r.reply, r.reply


def test_r4_reset_is_a_set_request(tmp_path: Path, monkeypatch) -> None:
    p, _ = _parser(tmp_path, monkeypatch)
    r = p.parse("reset --canvas to #ffffff")
    assert r.intent == "ui_feedback_color_var"
