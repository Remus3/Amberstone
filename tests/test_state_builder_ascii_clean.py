"""build_state ASCII-clean: arrow coverage + a guaranteed non-ASCII fallback.

Item 558 (commit d2170d4d) added _ascii_clean at the build_state seam so the
Haiku/Sonnet coaches' non-ASCII punctuation (em/en dashes, smart quotes,
ellipsis) is mapped to ASCII before /api/state - a repo 7-bit-ASCII hard-rule
violation reaching the user-facing HUD. Live SR play then surfaced a gap: the
coaches also emit a right-arrow U+2192 ("CRASH BOT -> SETUP DRAKE" rendered with
a real arrow in coach.action), which the item-558 table did not cover, so it
reached the in-game overlay untouched.

_ascii_clean is the single seam all four coaches pass through, so it must (a) map
the common arrow/symbol set to readable ASCII and (b) guarantee NO codepoint > 127
ever survives, even a glyph the explicit table will never enumerate (an LLM can
emit anything).

All non-ASCII inputs are constructed via chr(0xNNNN) so this test file itself
stays 7-bit ASCII (repo hard rule; same ordinal-keyed discipline as _ASCII_PUNCT).
"""

from dashboard._state_builder import _ASCII_PUNCT, _ascii_clean


def _has_non_ascii(text: str) -> bool:
    return any(ord(ch) > 127 for ch in text)


class TestItem558PunctStillMaps:
    def test_em_en_dash(self) -> None:
        assert _ascii_clean(chr(0x2014)) == "-"
        assert _ascii_clean(chr(0x2013)) == "-"

    def test_smart_quotes(self) -> None:
        assert _ascii_clean(chr(0x2018) + "x" + chr(0x2019)) == "'x'"
        assert _ascii_clean(chr(0x201C) + "x" + chr(0x201D)) == '"x"'

    def test_ellipsis(self) -> None:
        assert _ascii_clean(chr(0x2026)) == "..."


class TestArrowsAndSymbols:
    def test_right_arrow_live_repro(self) -> None:
        # The exact live coach.action shape that surfaced the gap.
        src = "CRASH BOT " + chr(0x2192) + " SETUP DRAKE"
        assert _ascii_clean(src) == "CRASH BOT -> SETUP DRAKE"

    def test_arrow_family(self) -> None:
        assert _ascii_clean(chr(0x2192)) == "->"
        assert _ascii_clean(chr(0x2190)) == "<-"
        assert _ascii_clean(chr(0x2194)) == "<->"

    def test_common_symbols(self) -> None:
        assert _ascii_clean(chr(0x2022)) == "-"   # bullet
        assert _ascii_clean(chr(0x00D7)) == "x"   # multiplication sign
        assert _ascii_clean(chr(0x00A0)) == " "   # non-breaking space


class TestNonAsciiFallback:
    def test_uncovered_glyph_never_survives(self) -> None:
        # Emoji / CJK / symbol the explicit table will never enumerate must
        # still be stripped so non-ASCII never reaches the HUD.
        for cp in (0x1F600, 0x4E2D, 0x2603):  # grinning face, CJK zhong, snowman
            out = _ascii_clean(chr(cp) + "ok")
            assert not _has_non_ascii(out), (hex(cp), out)
            assert "ok" in out

    def test_explicit_map_wins_over_fallback(self) -> None:
        # A mapped glyph keeps its readable form rather than being dropped.
        assert _ascii_clean(chr(0x2192)) == "->"


class TestRecursionAndPassthrough:
    def test_nested_dict_list(self) -> None:
        src = {"a": chr(0x2192) + "go", "b": [chr(0x2014), {"c": chr(0x2026)}]}
        assert _ascii_clean(src) == {"a": "->go", "b": ["-", {"c": "..."}]}

    def test_non_str_untouched(self) -> None:
        assert _ascii_clean({"n": 5, "f": 1.5, "b": True, "z": None}) == {
            "n": 5,
            "f": 1.5,
            "b": True,
            "z": None,
        }


class TestTableIntegrity:
    def test_keys_are_ordinals_values_are_ascii(self) -> None:
        for key, val in _ASCII_PUNCT.items():
            assert isinstance(key, int)
            assert all(ord(ch) < 128 for ch in val)
