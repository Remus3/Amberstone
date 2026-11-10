"""s144 true-audit of core/aram_fight_risk.py (lane 8, one file).

fight_rule / risk feed the deterministic ARAM and Arena coach blocks
(core/aram_deterministic_coach.py, core/arena_deterministic_coach.py) and
document "a duration is read when present but is not required" and "never
raises". Measured before this fix: an overflowing (10**400) or raising
duration blanked an otherwise valid top threat; a newline, tab run, ESC or
NUL inside a champion / spell key / kind reached the coach string verbatim
(_clamp_words returned its input unchanged when under the word limit); a
5000-char champion, a 300-char spell key and a 900-char kind were coached
whole; a spell key outside the producer's Q / W / E / R vocabulary ("ignore
all previous") was named as the ability; a zero-width-only champion was
named; a structured entry stating a 0 s or negative CC was named "top CC
threat"; a Unicode digit passed as a duration; and a non-dict Mapping entry
was never read.
"""
from __future__ import annotations

import types

from core.aram_fight_risk import fight_rule, risk


def _e(**kw):
    base = {"champion": "Ashe", "kind": "stun", "spell_key": "R"}
    base.update(kw)
    return [base]


_GOOD_RULE = "Respect Ashe R (stun) before you commit"
_GOOD_RISK = "Ashe R stun - top CC threat"


# --- F1: an unusable duration never blanks a valid top threat ---


def test_f1_overflow_duration_keeps_threat() -> None:
    assert fight_rule(_e(duration_s=10**400)) == _GOOD_RULE
    assert risk(_e(duration_s=10**400)) == _GOOD_RISK


class _BadFloat(float):
    def __float__(self):
        raise RuntimeError("boom")


def test_f1_raising_duration_keeps_threat() -> None:
    assert fight_rule(_e(duration_s=_BadFloat(1.0))) == _GOOD_RULE


def test_f1_junk_duration_kinds_keep_threat() -> None:
    for dur in ("abc", float("nan"), float("inf"), float("-inf"), True, False, [1],
                object()):
        assert fight_rule(_e(duration_s=dur)) == _GOOD_RULE, repr(dur)


def test_f1_clean_duration_never_raises() -> None:
    from core.aram_fight_risk import _clean_duration

    assert _clean_duration(10**400) is None
    assert _clean_duration(_BadFloat(1.0)) is None
    assert _clean_duration(float("-inf")) is None
    assert _clean_duration(2) == 2.0


class _DurationRaises(dict):
    """A mapping entry whose duration lookup alone raises."""

    def get(self, key, default=None):
        if key.startswith("duration"):
            raise RuntimeError(key)
        return super().get(key, default)


def test_f1_raising_duration_lookup_keeps_threat() -> None:
    entry = _DurationRaises(champion="Ashe", kind="stun", spell_key="R")
    assert fight_rule([entry]) == _GOOD_RULE
    assert risk(entry) == _GOOD_RISK


# --- F2: whitespace inside a field is collapsed, never passed through ---


def test_f2_newline_in_spell_key_is_not_coached() -> None:
    out = fight_rule(_e(spell_key="R\nIGNORE"))
    assert "\n" not in out
    assert out == "Respect Ashe (stun) before you commit"


def test_f2_tab_run_in_champion_is_collapsed() -> None:
    assert fight_rule(_e(champion="Dr.   \t Mundo")) == (
        "Respect Dr. Mundo R (stun) before you commit"
    )


def test_f2_newline_inside_champion_is_collapsed() -> None:
    assert risk(_e(champion="Nunu\n&\nWillump")) == (
        "Nunu & Willump R stun - top CC threat"
    )


def test_f2_clamp_always_single_spaces() -> None:
    from core.aram_fight_risk import _clamp_words

    assert _clamp_words("a  b\nc\td", 12) == "a b c d"
    assert _clamp_words("a b c", 2) == "a b"


def test_f2_string_line_newline_key_is_not_coached() -> None:
    line = "Enemy CC threats: Ashe 3.0s stun (R\nX), Annie 1.5s stun (R)"
    out = fight_rule(line)
    assert "\n" not in out
    assert out == "Respect Ashe (stun) before you commit"


# --- F3: control / format characters never reach the coach string ---


def test_f3_control_char_champion_is_no_threat() -> None:
    for name in ("Ashe\x1b[31m", "Ashe\x00", "\u200b", "Ash\u200be", "A\x7fshe"):
        assert fight_rule(_e(champion=name)) == "", repr(name)
        assert risk(_e(champion=name)) == "", repr(name)


def test_f3_control_char_kind_is_dropped_not_coached() -> None:
    assert fight_rule(_e(kind="stun\x1b")) == "Respect Ashe R before you commit"


# --- F4: every field is length-bounded ---


def test_f4_long_champion_is_no_threat() -> None:
    assert fight_rule(_e(champion="A" * 65)) == ""
    assert fight_rule("Enemy CC threats: " + "A" * 5000 + " 3.0s stun (R)") == ""


def test_f4_champion_at_64_chars_still_reads() -> None:
    name = "A" * 64
    assert fight_rule(_e(champion=name)) == (
        f"Respect {name} R (stun) before you commit"
    )


def test_f4_long_kind_is_dropped() -> None:
    assert fight_rule(_e(kind="x" * 900)) == "Respect Ashe R before you commit"


def test_f4_output_is_bounded() -> None:
    for out in (fight_rule(_e(champion="A" * 64, kind="k" * 16)),
                risk(_e(champion="A" * 64, kind="k" * 16))):
        assert out and len(out) <= 128


# --- F5: the spell key is the producer's Q / W / E / R vocabulary ---


def test_f5_spell_key_outside_vocabulary_is_dropped() -> None:
    for key in ("R" * 300, "ignore all previous", "Z", "R1", "1"):
        assert fight_rule(_e(spell_key=key)) == (
            "Respect Ashe (stun) before you commit"
        ), repr(key)


def test_f5_every_producer_key_still_reads() -> None:
    for key in ("Q", "W", "E", "R", " R "):
        assert fight_rule(_e(spell_key=key)) == (
            f"Respect Ashe {key.strip()} (stun) before you commit"
        )


def test_f5_string_line_key_outside_vocabulary_is_dropped() -> None:
    assert risk("Enemy CC threats: Ashe 3.0s stun (ignore all)") == (
        "Ashe stun - top CC threat"
    )


# --- F6: a structured entry stating no CC is not a threat ---


def test_f6_zero_or_negative_duration_is_no_threat() -> None:
    for dur in (0, 0.0, -3, -0.5):
        assert fight_rule(_e(duration_s=dur)) == "", repr(dur)
        assert risk(_e(duration_s=dur)) == "", repr(dur)


def test_f6_positive_duration_still_reads() -> None:
    assert fight_rule(_e(duration_s=0.25)) == _GOOD_RULE
    assert fight_rule(_e(duration=2)) == _GOOD_RULE


# --- F7: the line grammar is ASCII digits only ---


def test_f7_unicode_digit_duration_is_not_a_chunk() -> None:
    assert fight_rule("Enemy CC threats: Ashe \u0663.0s stun (R)") == ""


def test_f7_producer_line_still_reads() -> None:
    line = "Enemy CC threats: Ashe 3.0s stun (R), Annie 1.5s stun (R)"
    assert fight_rule(line) == _GOOD_RULE
    assert risk(line) == _GOOD_RISK


# --- F8: a non-dict Mapping is read as an entry ---


def test_f8_mapping_proxy_entry_reads() -> None:
    entry = types.MappingProxyType(
        {"champion": "Ashe", "kind": "stun", "spell_key": "R"}
    )
    assert fight_rule([entry]) == _GOOD_RULE
    assert risk(entry) == _GOOD_RISK


# --- the documented never-raises contract still holds on the new inputs ---


def test_never_raises_matrix() -> None:
    class _Hostile:
        def __getattr__(self, name):
            raise RuntimeError(name)

    for bad in (_Hostile(), [_Hostile()], _e(champion=_BadFloat(1.0)),
                _e(kind=_Hostile()), _e(spell_key=b"R"), iter([]),
                "Enemy CC threats: ,,,", [types.MappingProxyType({})]):
        assert isinstance(fight_rule(bad), str)
        assert isinstance(risk(bad), str)
