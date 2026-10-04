"""Guard: P3 A3b-2 cycle-30 (item 427) - dashboard/summary cluster ASCII sweep.

builders_last_match.py + defensive_picks.py are now 100% ASCII (readable-math
glyphs and middot separators converted per-hit). aftergame_summary.py's two
win/loss status markers U+2713/U+26A0 at the _pick action line are RENDERED
glyphs deferred to P8; since RM-300 they are written as escapes, so the source
is ASCII and the rendered line is unchanged.
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _non_ascii(rel: str) -> list[int]:
    return [c for c in (ROOT / rel).read_bytes() if c > 127]


def test_builders_last_match_is_ascii():
    assert _non_ascii("dashboard/builders_last_match.py") == []


def test_defensive_picks_is_ascii():
    assert _non_ascii("core/defensive_picks.py") == []


def test_aftergame_summary_source_is_ascii_status_markers_are_escapes():
    # RM-300 (2026-10-04) shrank the P8-deferred residual: the win/loss status
    # pair U+2713 / U+26A0 is now written as escapes, so the SOURCE is 7-bit
    # ASCII while the rendered action line is unchanged. Whether the rendered
    # marker itself should become ASCII is still the P8 question.
    assert _non_ascii("core/aftergame_summary.py") == []
    txt = (ROOT / "core/aftergame_summary.py").read_text(encoding="ascii")
    assert 'marker = "\\u2713" if meta["win"] else "\\u26a0"' in txt
