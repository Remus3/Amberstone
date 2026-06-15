"""Guard: P3 A3b-2 cycle-30 (item 427) - dashboard/summary cluster ASCII sweep.

builders_last_match.py + defensive_picks.py are now 100% ASCII (readable-math
glyphs and middot separators converted per-hit). aftergame_summary.py keeps
EXACTLY the two win/loss status markers U+2713/U+26A0 at the _pick action
line - a matched status-emoji pair deferred to P8 (the U+26A0 warn marker is
unmapped in GLYPH_MAP, same precedent as cycle-22 item-418). This guard locks
the sweep and pins the deferral so a future P8 pass is the only thing that may
shrink the aftergame residual.
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _non_ascii(rel: str) -> list[int]:
    return [c for c in (ROOT / rel).read_bytes() if c > 127]


def test_builders_last_match_is_ascii():
    assert _non_ascii("dashboard/builders_last_match.py") == []


def test_defensive_picks_is_ascii():
    assert _non_ascii("core/defensive_picks.py") == []


def test_aftergame_summary_residual_is_only_p8_status_markers():
    # The ONLY remaining non-ASCII = the win/loss status pair U+2713 / U+26A0,
    # both on the _pick action line, P8-deferred. No other glyph may survive.
    txt = (ROOT / "core/aftergame_summary.py").read_text(encoding="utf-8")
    residual = sorted({c for c in txt if ord(c) > 127})
    assert residual == ["⚠", "✓"], residual  # sorted by codepoint: U+26A0 < U+2713
