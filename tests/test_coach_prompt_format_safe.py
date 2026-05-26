"""Regression test for coach prompt brace-escape bug (item 188+).

The 4 in-game coach system prompts (SR + ARAM + Arena + Brawl) are
wrapped in `str.format(**kwargs)` to substitute the per-tick fields
({profile}, {sr_rune_rec}, {arena_meta}, {brawl_meta}, etc).

The "Choices: ..." line in each prompt embeds a literal JSON schema
sample of the shape `[{"key":"A","label":...},...]`. Without the
double-brace escape, Python's `str.format()` parses the inner
`{"key":"A",...}` as a format field with field-name `"key"` (with
literal quotes) and raises `KeyError('"key"')`, killing the coach
silently with `coach.action / immediate / next` left empty.

Bug landed 2026-05-21 in commit `58b7d20` (Brawl + SR native choices
emit) and `b3cd60b` (ARAM/Arena phase 2 wired similarly). The 5-day
window before this regression test was added means the operator's
SR ranked game on 2026-05-25 was the first to trip the bug live.

The fix doubles `{` -> `{{` and `}` -> `}}` around the JSON object in
the schema so `str.format()` writes a single-brace literal back.

This test asserts both:
  1. `.format(**kwargs)` does NOT raise on any in-game system prompt.
  2. The rendered output retains the LITERAL schema string
     `[{"key":"A"` and `"source_tag"` so the LLM still sees a valid
     JSON example.

Any future change that adds a new JSON literal to a system prompt and
forgets to escape will fail this test before reaching production.
"""

import pytest

# Production .format() kwargs per coach module + prompt constant.
# Pulled from the actual messages.create() callers as of 2026-05-25.
_KWARGS_SR = {
    "profile": "Caitlyn (ADC carry).",
    "sr_rune_rec": "Lethal Tempo | Precision / Sorcery",
    "sr_build_note": "Crit build: Berserker -> Yun Tal -> IE -> Collector",
    "adaptation_hint": "",
}

_KWARGS_ARAM_INGAME = {
    "profile": "Jinx (ADC).",
    "mayhem_tag": "",
    "rune_rec": "Lethal Tempo | Precision / Sorcery",
    "aram_meta": "Standard ADC ARAM build",
    "augment_line": "",
    "adaptation_hint": "",
}

_KWARGS_ARENA_INGAME = {
    "profile": "Vayne (ADC).",
    "arena_meta": "Crit Arena build",
    "adaptation_hint": "",
}

_KWARGS_BRAWL = {
    "profile": "Vex (mage).",
    "brawl_meta": "AP burst Brawl build",
    "adaptation_hint": "",
    "champion": "Vex",
}


def _assert_format_ok(prompt: str, kwargs: dict, label: str) -> None:
    """Assert prompt.format(**kwargs) succeeds + retains schema literal."""
    try:
        rendered = prompt.format(**kwargs)
    except KeyError as exc:
        pytest.fail(
            f"{label}: prompt.format() raised KeyError({exc.args!r}). "
            f"Likely an unescaped `{{...}}` JSON literal in the prompt - "
            f"double the braces (`{{{{` and `}}}}`) around any literal "
            f"JSON object that should pass through .format() verbatim."
        )
    # The Choices line MUST still emit the JSON example so the LLM
    # produces a valid array. format() de-doubles braces, so a fixed
    # prompt with `[{{"key":"A"...}}, ...]` renders as `[{"key":"A"...}, ...]`.
    assert '[{"key":"A"' in rendered, (
        f"{label}: rendered prompt missing the literal "
        f'`[{{"key":"A"` schema sample - either the Choices line was '
        f"deleted or the brace-escape over-corrected and double braces "
        f"survived into the rendered output."
    )
    assert '"source_tag"' in rendered, (
        f'{label}: rendered prompt missing `"source_tag"` from the '
        f"Choices schema sample - schema appears truncated."
    )


def test_sr_system_prompt_format_safe() -> None:
    from coach_integration._sr_prompt import SR_SYSTEM_PROMPT
    _assert_format_ok(SR_SYSTEM_PROMPT, _KWARGS_SR, "SR_SYSTEM_PROMPT")


def test_aram_system_prompt_format_safe() -> None:
    from coaches.aram_coach import _SYSTEM
    _assert_format_ok(_SYSTEM, _KWARGS_ARAM_INGAME, "aram_coach._SYSTEM")


def test_arena_system_prompt_format_safe() -> None:
    from coaches.arena_coach import _SYSTEM_PROMPT
    _assert_format_ok(_SYSTEM_PROMPT, _KWARGS_ARENA_INGAME, "arena_coach._SYSTEM_PROMPT")


def test_brawl_urf_prompt_format_safe() -> None:
    from coaches.brawl_coach import _URF_SYSTEM_PROMPT
    _assert_format_ok(_URF_SYSTEM_PROMPT, _KWARGS_BRAWL, "brawl_coach._URF_SYSTEM_PROMPT")


def test_brawl_ofa_prompt_format_safe() -> None:
    from coaches.brawl_coach import _OFA_SYSTEM_PROMPT
    _assert_format_ok(_OFA_SYSTEM_PROMPT, _KWARGS_BRAWL, "brawl_coach._OFA_SYSTEM_PROMPT")


def test_brawl_nb_prompt_format_safe() -> None:
    from coaches.brawl_coach import _NB_SYSTEM_PROMPT
    _assert_format_ok(_NB_SYSTEM_PROMPT, _KWARGS_BRAWL, "brawl_coach._NB_SYSTEM_PROMPT")


def test_keyerror_quoted_repro_anchor() -> None:
    """Anchor test: pin the exact KeyError shape so future bug reports
    can map symptom to root cause without re-deriving."""
    bad = '{"key":"A","label":"foo"}'
    with pytest.raises(KeyError) as ei:
        bad.format(profile="x")
    # KeyError args are tuple of (missing_key,); the missing key here
    # is the 5-char literal `"key"` (double-quotes included).
    assert ei.value.args == ('"key"',), (
        f"Expected KeyError args=('\"key\"',) but got {ei.value.args!r}. "
        f"If this changed, Python's str.format() parsing rules changed."
    )
    assert str(ei.value) == '\'"key"\'', (
        f"Expected str(e) repr to be `'\"key\"'` (7 chars). "
        f"If this changed, log-grepping for the symptom needs updating."
    )
