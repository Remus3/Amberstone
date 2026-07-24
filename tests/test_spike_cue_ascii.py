"""Guard: R185 ui-audit-spike-cue - in-game Spike Cue overlay widget ASCII lock.

The 5-phase Section-3b UI audit (STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII /
HIERARCHY) of the Spike Cue overlay widget - the transient one-shot glyph that
fires the instant the operator crosses an ULTIMATE power spike (level 6 ULT
ONLINE / 11 ULT R2 / 16 ULT R3), rendered off the live `/api/state.liveclient.level`
and mounted at `#am-spike-cue` (web/index.html:2176) as the `w-spike` urgent
overlay widget - landed CLEAN:

  STRUCTURE - a `.spike-cue` flex container holding a `.spike-chip` (glyph +
  label); self-gates on body[data-shell="overlay"] (spike_cue.js:109-112, a no-op
  on the 1920 dashboard); rising-edge cross detection (crossedSpike) so the cue
  fires ONCE on the level cross, not every 2s tick; sig-dedup via `_shownFor`;
  self-expiring 8s hide-timer (doctrine rule 6 - alerts self-expire, no dismissal);
  fail-soft `hidden=true` when there is no fresh cross (HONEST NO-DATA).

  TYPOGRAPHY - the chip sizes on the overlay sub-floor token `var(--fs-ov-chip)`
  (13px, a DOCUMENTED operator-exception for the game-distance HUD; item-184 / R8
  / R33), NOT the dashboard --fs-xs 16px floor. This is already enforced by
  tests/test_overlay_css_typography_tokens.py (spike_cue.css is in its
  `_OVERLAY_CUE_CSS` set); the `var(--fs-ov-chip, 13px)` fallback is not a bare px
  literal and the relative-em glyph size (0.9em) is intentional.

  HIT-TARGETS - N/A (a pure transient display chip, zero clickables).

  HIERARCHY - a single glanceable urgent cyan uppercase chip with one rationed
  one-shot pulse (doctrine rule 5); readable at the 1920x1080 baseline with no
  scroll.

  ASCII - both surface files carry ZERO non-ASCII bytes. The up-triangle is a CSS
  `content: "\25B2"` escape (the rule carries the glyph, not the authored byte -
  repo ASCII hard rule).

This guard locks that clean state so a future edit cannot slip an em/en dash, a
smart quote, or a raw unicode glyph into the surface.
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

# CLAUDE.md hard-rule banned glyphs: en dash, em dash, and the four smart quotes.
_BANNED = {0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D}

# The two Spike Cue overlay surface files, both currently 100% ASCII.
_SURFACE = (
    "web/js/panels/spike_cue.js",
    "web/css/panels/spike_cue.css",
)


def _non_ascii(rel: str) -> list[int]:
    return [b for b in (ROOT / rel).read_bytes() if b > 127]


def test_spike_cue_surface_is_pure_ascii():
    for rel in _SURFACE:
        assert _non_ascii(rel) == [], rel


def test_no_banned_glyph_anywhere_in_spike_cue_surface():
    for rel in _SURFACE:
        txt = (ROOT / rel).read_text(encoding="utf-8")
        hits = sorted({hex(ord(c)) for c in txt if ord(c) in _BANNED})
        assert hits == [], (rel, hits)


def test_spike_cue_surface_has_no_non_ascii_residual():
    # Total lock: the Spike Cue surface carries no non-ASCII residual at all.
    # The up-triangle glyph is a CSS \25B2 escape, so the authored bytes stay
    # 7-bit; any byte > 127 means the lock has been broken.
    for rel in _SURFACE:
        txt = (ROOT / rel).read_text(encoding="utf-8")
        residual = sorted({ord(c) for c in txt if ord(c) > 127})
        assert residual == [], (rel, [hex(c) for c in residual])
