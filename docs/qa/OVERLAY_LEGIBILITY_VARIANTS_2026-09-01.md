# DS3 - In-game overlay legibility variants (2026-09-01)

STATUS: **PREPARED, NOT DECIDED.** This document exists so an operator-present
session can pick a variant in minutes. It does not close DS3, and no variant is
wired on anywhere. `web/css/overlay.css` is untouched by this work.

The ruling being prepared, verbatim from `docs/qa/UI_UX_PROGRAM_QA_2026-07-22.md:72`:

> DS3 | Overlay theme target | **Share the chosen palette, keep a documented
> in-game legibility variant** (stronger border/backing over game pixels)

--------------------------------------------------------------------------------
## 0. THE HARD CONSTRAINT, STATED PLAINLY
--------------------------------------------------------------------------------

There is **no League client running, no live game, and no archive of real game
frames on this machine**. The only game-adjacent images in the tree are the
minimap crops under `assets/wards/*.png`. Nothing below was rendered over real
game pixels.

Every render here uses a **synthetic backdrop proxy**. Every contrast figure is
computed from the browser's own resolved sRGB against one of those proxies.
No OCR pass was run. No legibility "pass" was awarded. The three proxies were
chosen to bracket the extremes a real frame spans, and they are a **screening
tool** - they can eliminate a variant, they cannot elect one.

**The pick needs the operator, over real gameplay.** Section 6 lists exactly
what only eyes on a live frame can settle.

--------------------------------------------------------------------------------
## 1. WHAT THE OVERLAY DOES TODAY (cited, not remembered)
--------------------------------------------------------------------------------

All citations are `web/css/overlay.css` unless marked otherwise. Everything is
scoped under `body[data-shell="overlay"]`.

> **TWO PROVENANCE NOTES, both measured 2026-09-01, both load-bearing.**
>
> 1. **Line numbers are against the `lane/uiux` WORKING TREE at the time of
>    writing.** A concurrent lane landed the B-OVL-4 `.am-pane-chips` block into
>    `web/css/overlay.css` at `:507` and into `web/css/panels/active_match.css`
>    at `:109` while this pass was running, which pushed every overlay.css
>    anchor past `:507` down by 13 lines. All citations below were re-pinned by
>    fixed-string grep AFTER that landing. Nothing in that block touches any rule
>    cited here.
> 2. **The renders and the contrast numbers were measured against the SERVED
>    build, not this worktree.** `tools/overlay_legibility_preview.py` drives the
>    live RC dashboard at `https://127.0.0.1:8888`, which serves from
>    `C:\Riot Commander`, and the served `overlay.css` was byte-identical to this
>    branch's `HEAD` (42984 bytes) rather than to the working tree (44688 bytes).
>    The delta is only the B-OVL-4 addition above, which paints a chip row in
>    `w-build` and touches none of the measured targets, so the figures stand.
>    Re-running the harness after the lane merges will re-measure against the
>    merged CSS.

### 1.1 The widget shell

`:161-202` `.ovx-widget` - the frame every cue mount inherits:

| Property | Value | Line |
|---|---|---|
| width | `var(--ovx-w, 210px)` fixed | 170 |
| padding | `6px 8px` | 172 |
| background | `rgba(var(--ovx-bg), 0.58)` = `rgba(22,32,46,0.58)` | 173 |
| border | `1px solid var(--ovx-panel-border)` = `rgba(200,170,110,0.70)` | 178 (token at 62) |
| border-radius | `7px` | 179 |
| box-shadow | `inset 0 1px 0 rgba(gold,0.45)`, `0 0 0 1px rgba(10,14,20,1)`, `0 4px 14px rgba(0,0,0,0.55)` | 180-182 |

Supporting chrome: an uppercase gold pane head with a `rgba(gold,0.28)` rule
under it (`:206-216`); nested rows and chips on `rgba(var(--ovx-bg-nested),0.9)`
(`:231-235`); `#rn-lead` overrides its own backing to the same nested 0.9
(`:256-258`); a 7px gold hex-notch drawn as `::before` / `::after`
(`:572-583`); and two deliberate frame-strip carve-outs, `w-trinket`
(`:608-614`) and `w-mmrect` (`:627-639`), which must stay frameless under any
variant.

### 1.2 The ink tiers

| Ink | Value | Size | Line |
|---|---|---|---|
| w-call ACTION verb | `rgb(var(--ovx-text))` = white | `--fs-ov-call` 14px / 700 | 339-344 |
| w-call ACTION verb, table path | white | 14px / 700 | 417-422 |
| w-call RIGHT-NOW | `rgb(var(--ovx-cyan))` | `--fs-ov-chip` 13px / 600 | 331-337 |
| w-call OBJECTIVE footer | `rgba(var(--ovx-text), 0.55)` | `--fs-ov-sigil` 12px | 387-396 |
| pane head | `rgba(var(--ovx-gold), 0.90)` | `--fs-ov-head` 11px | 206-216 |
| w-lead tag | `rgba(var(--ovx-text), 0.55)` | inherited | 262-264 |
| w-callouts ETA chip | `rgba(var(--ovx-gold), 0.85)` | `--fs-ov-chip` | 274-276 |
| w-callouts ETA NOW | `rgb(var(--ovx-cyan))` on `rgba(cyan,0.18)` | `--fs-ov-chip` | 277-281 |

The sub-floor overlay type tokens are at `:33-36`.

### 1.3 THE DEFECT THIS WORK FOUND (measured, not reasoned)

`web/css/overlay.css:217-224` intends the `.am-pane` widgets to drop their
dashboard backing and take the Hextech shell:

```
body[data-shell="overlay"] .ovx-widget .am-pane,
body[data-shell="overlay"] .ovx-widget.am-pane { background: transparent; ... }
```
specificity **(0,3,1)**.

`web/css/panels/active_match.css:92-100` says:

```
#view-active-match .am-pane { background: var(--surface-head); ... }
```
specificity **(1,1,0)**. An id outranks any number of classes, so
**active_match.css wins and the overlay rule never applies.**

Measured live through `getComputedStyle` in the running overlay
(`tools/overlay_legibility_preview.py`, baseline cell, 2026-09-01):

```
w-arambalance  rgba(22, 32, 46, 0.58)     <- intended Hextech backing
w-build        oklch(0.27 0.06 302)       <- OPAQUE dashboard --surface-head
w-call         oklch(0.27 0.06 302)       <- OPAQUE dashboard --surface-head
w-callouts     rgba(22, 32, 46, 0.58)
w-choices      rgba(22, 32, 46, 0.58)
w-launcher     rgba(22, 32, 46, 0.58)
w-lead         rgba(10, 14, 20, 0.9)
w-mmrect       rgba(0, 0, 0, 0)           <- intended, frameless
w-nextbuy      rgba(22, 32, 46, 0.58)
w-objgauges    rgba(22, 32, 46, 0.58)
w-ovds         oklch(0.27 0.06 302)       <- OPAQUE dashboard --surface-head
w-stats        rgba(22, 32, 46, 0.58)
root --surface-head = oklch(0.27 0.060 302)
```

Three consequences, all of which are DS3's actual subject matter:

1. **The PRIMARY widget is not see-through at all.** `w-call` paints a fully
   opaque plate. The doctrine's premise (`docs/OVERLAY_DOCTRINE.md` section 5,
   "panel backing #16202E at 0.85 alpha") is not what ships on the one widget
   that matters most.
2. **It is off-palette.** `oklch(0.27 0.06 302)` is the dashboard purple. The
   doctrine says "no color literal outside this table reaches a widget"
   (section 5). This one does, through a token.
3. **It is a chrome split inside a single surface** - three widgets on an
   opaque purple plate, eight on a 0.58 Hextech wash, one frameless. That is
   the exact disease DS1 ordered collapsed ("Collapse to ONE chrome").

Because of (1), the baseline's strong `w-call` contrast numbers in section 4
are **backdrop-independent by accident**, not by design. Any variant that
restores the intended transparency will make those numbers backdrop-dependent
again. That is not a regression in the variant; it is the defect becoming
visible.

**All three variants below therefore repeat their backing rule at
`#view-active-match .am-pane.ovx-widget` specificity.** Whichever variant wins,
that repair should land - it is a standalone bug fix.

--------------------------------------------------------------------------------
## 2. THE BACKDROP PROXIES
--------------------------------------------------------------------------------

Built procedurally (seeded, so a re-render is comparable), 1280x720, upscaled
`background-size: cover` behind the transparent overlay body. Sources are
written to `tools/pseudo_screen_out/_backdrop_<name>.png`.

| Proxy | Mean sRGB | What it stresses | Why it is the worst case |
|---|---|---|---|
| `bright_rift` | `(195.5, 182.7, 138.8)` | see-through backings, low-alpha ink, thin strokes | A low-alpha dark backing composites UP toward the game. Sand and river at noon is the brightest sustained field on the map, so this is where a 0.58 wash stops being a backing. Specular highlights near 248 are included. |
| `dark_pit` | `(18.8, 20.0, 35.0)` | the FRAME, not the text | Text contrast is trivially easy here. What fails is occlusion: a heavy scrim that reads as premium over sand reads as a black rectangle punched into the game. This is the doctrine rule-8 data-ink cost, and it is invisible on a bright proxy. |
| `chroma_fight` | `(127.3, 109.9, 127.2)` | the CATEGORY channel | Mid luminance, very high saturation, high spatial frequency. Six saturated VFX blobs (red / cyan / magenta / green / gold / violet). A red band marker beside a red VFX blob stops being a category (rule 10) and the single-pop-out guarantee (rule 4) is what is actually at risk - not the luminance ratio. |

Limitation to keep in mind: a real frame is not stationary and is not uniform.
These proxies are uniform in statistics but not in the specific way a champion
model, a health bar, or a spell indicator sits under a widget.

--------------------------------------------------------------------------------
## 3. THE VARIANTS
--------------------------------------------------------------------------------

Each block is the complete, self-contained CSS the harness injects. Nothing
here is in a production stylesheet. Selectors are as-authored.

Shared to all three: `w-trinket` (`overlay.css:608`) and `w-mmrect`
(`overlay.css:627`) keep their frameless treatment, because their own selectors
carry higher specificity than the generic `.ovx-widget` rule. That is intended.
A glyph cue and a minimap outline must never grow a plate.

### V1 - "hairline + scrim"

Registry key: `v1_hairline_scrim`

Optimizes rules 1 and 8 jointly: the box does not grow, only its backing alpha
and an outer scrim ring change. The gold hairline, the 7px radius and the
etched top bevel all survive, so the Hextech read is unchanged.

Trades away: occlusion. At 0.90 the game is barely visible through a widget,
which over `dark_pit` is close to a solid panel.

```css
body[data-shell="overlay"] .ovx-widget,
body[data-shell="overlay"] #view-active-match .am-pane.ovx-widget {
  background: rgba(var(--ovx-bg), 0.90);
  border: 1px solid rgba(var(--ovx-gold), 0.78);
  border-radius: 7px;
  box-shadow: inset 0 1px 0 rgba(var(--ovx-gold), 0.45),
              0 0 0 1px rgba(var(--ovx-bg-nested), 1),
              0 0 0 5px rgba(4, 6, 9, 0.38),
              0 6px 18px rgba(0, 0, 0, 0.62);
}
body[data-shell="overlay"] .ovx-widget[data-ovx-id="w-call"],
body[data-shell="overlay"] #view-active-match .am-pane.ovx-widget[data-ovx-id="w-call"] {
  background: rgba(var(--ovx-bg), 0.95);
  border-color: rgba(var(--ovx-gold), 0.95);
  box-shadow: inset 0 4px 16px -4px rgba(var(--ovx-cyan), 0.45),
              inset 0 1px 0 rgba(var(--ovx-gold), 0.50),
              0 0 0 1px rgba(var(--ovx-bg-nested), 1),
              0 0 0 5px rgba(4, 6, 9, 0.42),
              0 6px 20px rgba(0, 0, 0, 0.66);
}
body[data-shell="overlay"] .ovx-widget .cd-chip,
body[data-shell="overlay"] .ovx-widget .rc-chip,
body[data-shell="overlay"] .ovx-widget .rc-co-row,
body[data-shell="overlay"] #rn-lead {
  background: rgba(var(--ovx-bg-nested), 0.96);
}
body[data-shell="overlay"] .ovx-widget[data-ovx-id="w-call"] #am-call-body
  > div[data-call-line="objective"] > span:last-child {
  color: rgba(var(--ovx-text), 0.80) !important;
}
body[data-shell="overlay"] #rn-lead .rc-lead-tag {
  color: rgba(var(--ovx-text), 0.80);
}
body[data-shell="overlay"] .rc-co-eta {
  color: rgba(var(--ovx-gold), 0.98);
}
```

### V2 - "solid plate"

Registry key: `v2_solid_plate`

Optimizes rule 1 absolutely. Every pair becomes backdrop-independent because
the plate admits no game pixels, so nothing can wash out at any brightness.
Also collapses the chrome split by force.

Trades away: rule 8 outright, and the doctrine section-0 premise that the
overlay floats over the game. Over `dark_pit` this is a dev-tool plate, which
is precisely the "utterly not it" failure the doctrine opens with.

```css
body[data-shell="overlay"] .ovx-widget,
body[data-shell="overlay"] #view-active-match .am-pane.ovx-widget {
  background: rgba(var(--ovx-bg-nested), 0.97);
  border: 2px solid rgba(var(--ovx-gold), 1);
  border-radius: 4px;
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.95),
              0 8px 22px rgba(0, 0, 0, 0.75);
}
body[data-shell="overlay"] .ovx-widget[data-ovx-id="w-call"],
body[data-shell="overlay"] #view-active-match .am-pane.ovx-widget[data-ovx-id="w-call"] {
  background: rgb(var(--ovx-bg-nested));
  border-color: rgba(var(--ovx-cyan), 1);
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.95),
              0 0 14px -2px rgba(var(--ovx-cyan), 0.55),
              0 8px 22px rgba(0, 0, 0, 0.8);
}
body[data-shell="overlay"] .ovx-widget .cd-chip,
body[data-shell="overlay"] .ovx-widget .rc-chip,
body[data-shell="overlay"] .ovx-widget .rc-co-row,
body[data-shell="overlay"] #rn-lead {
  background: rgba(var(--ovx-bg), 0.96);
}
body[data-shell="overlay"] .ovx-widget[data-ovx-id="w-call"] #am-call-body
  > div[data-call-line="objective"] > span:last-child {
  color: rgba(var(--ovx-text), 0.85) !important;
}
body[data-shell="overlay"] #rn-lead .rc-lead-tag {
  color: rgba(var(--ovx-text), 0.85);
}
```

### V3 - "outline + halo"

Registry key: `v3_outline_halo`

Optimizes rule 8 hardest: near-zero occlusion, the game visible through every
ambient widget, legibility carried by a hard dark text halo (the broadcast
subtitle technique). The PRIMARY keeps a light 0.55 plate because it is the one
element that must never be ambiguous.

Trades away: guaranteed contrast. Computed contrast becomes text-vs-GAME, so it
is backdrop-dependent by construction, and section 4 shows it failing badly on
the bright proxy. The halo is a rendered-pixel effect that no `getComputedStyle`
number can score, so V3 is the variant whose real quality this harness is least
able to judge.

```css
body[data-shell="overlay"] .ovx-widget,
body[data-shell="overlay"] #view-active-match .am-pane.ovx-widget {
  background: transparent;
  border: 1px solid rgba(var(--ovx-gold), 0.55);
  border-radius: 7px;
  box-shadow: none;
}
body[data-shell="overlay"] .ovx-widget[data-ovx-id="w-call"],
body[data-shell="overlay"] #view-active-match .am-pane.ovx-widget[data-ovx-id="w-call"] {
  background: rgba(var(--ovx-bg-nested), 0.55);
  border-color: rgba(var(--ovx-gold), 0.95);
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.90);
}
body[data-shell="overlay"] .ovx-widget .cd-chip,
body[data-shell="overlay"] .ovx-widget .rc-chip,
body[data-shell="overlay"] .ovx-widget .rc-co-row,
body[data-shell="overlay"] #rn-lead {
  background: rgba(var(--ovx-bg-nested), 0.42);
}
body[data-shell="overlay"] .ovx-widget,
body[data-shell="overlay"] .ovx-widget * {
  text-shadow: 0 0 2px rgba(0, 0, 0, 0.95),
               0 0 5px rgba(0, 0, 0, 0.85),
               1px 0 0 rgba(0, 0, 0, 0.92),
               -1px 0 0 rgba(0, 0, 0, 0.92),
               0 1px 0 rgba(0, 0, 0, 0.92),
               0 -1px 0 rgba(0, 0, 0, 0.92);
}
body[data-shell="overlay"] .ovx-widget[data-ovx-id="w-call"] #am-call-body
  > div[data-call-line="objective"] > span:last-child {
  color: rgba(var(--ovx-text), 0.92) !important;
}
body[data-shell="overlay"] #rn-lead .rc-lead-tag {
  color: rgba(var(--ovx-text), 0.92);
}
body[data-shell="overlay"] .rc-co-eta {
  color: rgb(var(--ovx-gold));
}
```

--------------------------------------------------------------------------------
## 4. MEASURED CONTRAST
--------------------------------------------------------------------------------

Method: `getComputedStyle` in the live page, resolved through a 1x1 canvas
round-trip so an `oklch()` token resolves to real sRGB. This matters here and is
not theoretical - the `w-lead` value line and the `w-callouts` row line both
compute to `oklch(0.94 0.02 305)`, and `--surface-head` computes to
`oklch(0.27 0.060 302)`. A source grep for a hex would have measured a value the
browser is not using.

The effective surface is built by walking the ancestor chain, compositing every
`background-color` layer in paint order, and compositing the residual over the
backdrop's mean sRGB. The ink is then composited over that surface (the 0.55
alpha tiers are alpha-composited, so their *rendered* colour is what is scored).
WCAG 2.x relative luminance, computed from resolved sRGB.

**Threshold: 4.5:1.** The overlay authors 11px to 14px, so the 3.0:1 large-text
allowance does not apply to any target here.

Every figure below names its **PAIR**: `ink rgb(...) vs surface rgb(...)`, and
the surface named is the composite for that specific backdrop.

Full machine-readable data, including the per-target surface chain:
`tools/pseudo_screen_out/legibility_report.json`.

### 4.1 The primary: `w-call` ACTION verb (white, 14px/700)

| Variant | vs bright_rift | vs dark_pit | vs chroma_fight | Surface |
|---|---|---|---|---|
| `baseline` | 15.39 | 15.39 | 15.39 | `rgb(44,30,63)` OPAQUE, identical on all three - the section 1.3 defect |
| V1 | 14.95 | 16.50 | 15.60 | `rgb(31,40,51)` / `rgb(22,31,45)` / `rgb(27,36,50)` |
| V2 | 19.34 | 19.34 | 19.34 | `rgb(10,14,20)` OPAQUE by design |
| V3 | **6.89** | 18.83 | 11.10 | `rgb(93,91,74)` / `rgb(13,17,27)` / `rgb(62,58,68)` |

Ink is `rgb(255,255,255)` in every cell.

### 4.2 The faint tier: `w-call` OBJECTIVE footer (12px)

Authored `rgba(255,255,255,0.55)` at baseline, so its rendered ink differs per
variant and per surface.

| Variant | vs bright_rift | vs dark_pit | vs chroma_fight | Ink / surface (bright_rift) |
|---|---|---|---|---|
| baseline | 5.61 | 5.61 | 5.61 | `rgb(160,154,168)` vs `rgb(44,30,63)` |
| V1 | 10.06 | 10.92 | 10.43 | `rgb(210,212,214)` vs `rgb(31,40,51)` |
| V2 | 13.97 | 13.97 | 13.97 | `rgb(218,219,220)` vs `rgb(10,14,20)` |
| V3 | 6.16 | 15.99 | 9.71 | `rgb(242,242,241)` vs `rgb(93,91,74)` |

### 4.3 Everything else, on the bright_rift proxy (the hard one)

| Target | baseline | V1 | V2 | V3 |
|---|---|---|---|---|
| w-call RIGHT-NOW, `rgb(10,200,185)` | 7.31 | 7.10 | 9.19 | **3.27 FAIL** |
| w-build pane head, gold 11px | 5.89 | 5.27 | 6.98 | **1.10 FAIL** |
| w-lead value line, `rgb(238,232,246)` | 13.88 | 15.32 | 12.75 | **4.15 FAIL** |
| w-lead tag | 5.89 | 11.92 | 11.42 | 4.51 |
| w-callouts row line | 15.14 | 15.98 | 13.75 | **4.15 FAIL** |
| w-callouts ETA chip, gold 0.85 | 5.49 | 7.32 | 4.97 | **1.98 FAIL** |

Surfaces for the V3 column, in order: `rgb(93,91,74)`, `rgb(195,183,139)` (i.e.
the raw backdrop - the pane head sits on NO backing at all under V3),
`rgb(118,112,89)`, `rgb(118,112,89)`, `rgb(118,112,89)`, `rgb(126,120,98)`.

The same table on `dark_pit` has V3 passing everything at 6.86 to 18.83, and on
`chroma_fight` V3 fails only the pane head (1.99) and the ETA chip (3.44).
V3 is a bright-field failure, specifically.

### 4.4 Rendered-pixel spread inside the `w-call` box

The only figure here that sees V3's halo at all, because a halo is invisible to
`getComputedStyle`. Luminance statistics over the actual final PNG crop.

| Variant | bright_rift | dark_pit | chroma_fight |
|---|---|---|---|
| baseline | mean 52.6 sd 41.9 | mean 51.9 sd 41.1 | mean 52.2 sd 41.1 |
| V1 | mean 55.4 sd 42.7 | mean 46.6 sd 45.1 | mean 50.5 sd 44.0 |
| V2 | mean 31.0 sd 50.6 | mean 31.0 sd 50.6 | mean 31.0 sd 50.6 |
| V3 | mean 98.2 sd 35.9 | mean 31.5 sd 48.1 | mean 62.7 sd 40.2 |

Read this as: V2's box is identical on all three backdrops (it is opaque). V3's
box mean swings 31 to 98, i.e. the widget's own brightness is dictated by the
game. V1 swings 47 to 55, a narrow band. This is the occlusion-vs-stability
tradeoff in one number, and it is a *spread statistic, not a contrast ratio*.

### 4.5 What was NOT measured, and why

- **`w-call ACTION verb (table path)`** (`.am-call-thead`, overlay.css:417-422) is
  ABSENT in every fixture. It only exists when a coach markdown table leaks into
  a field value. Unmeasured.
- **`w-callouts ETA chip NOW`** (`.rc-co-eta.rc-co-now`, overlay.css:277-281) is
  ABSENT in every fixture. All four mocks carry ETAs of 5:00 / 5:00 / 14:00, so
  the cyan NOW state never renders. **This is the one target most at risk on the
  `chroma_fight` proxy** (cyan ink on a cyan-tinted 0.18 wash, next to cyan VFX)
  and it is exactly the one there is no fixture for. Unmeasured.
- **The combat-shed state.** All four committed `ui_mock` fixtures
  (`sr`, `aram`, `mayhem`, `complete`) stamp `body[data-fight="1"]`, so
  `overlay.css:735` hides the OBJECTIVE row and the pane heads are
  `display:none`. Their colour pairs above are real (computed style resolves on
  a hidden element and the ancestor chain is intact), but they are not in the
  default PNGs. The harness `--show-shed` flag un-hides them for the visual pass
  without changing any colour; both PNG sets exist.
- **`w-choices` A/B chips** were not added as contrast targets. They are a
  tier-3 preattentive channel and their risk is hue collision, not luminance.

--------------------------------------------------------------------------------
## 5. WHAT THE NUMBERS DO AND DO NOT SETTLE
--------------------------------------------------------------------------------

Settled by measurement, on these proxies:

- **V3 is eliminated as an unconditional default.** Six targets fail AA on the
  bright proxy, two of them below 2:1. It could survive as a *conditional*
  treatment (see section 6), but not as the shipped state.
- **The baseline passes AA on every painted target on all three proxies.** That
  is an honest result and it must not be over-read: it passes *because* the
  primary widget is accidentally opaque (section 1.3) and because the nested
  0.9 backings hold. It is not passing by design.
- **V1 and V2 both raise every faint tier well clear of the floor.** The faint
  tier moves from 5.61 to 10.06 (V1) or 13.97 (V2) on the bright proxy.
- **V2 is the only variant with zero backdrop variance.** Every V2 figure is
  identical across all three proxies.

Not settled by measurement:

- Whether a 0.90 backing (V1) reads as premium or as intrusive at speed.
- Whether the outer scrim ring reads as a frame or as a smudge.
- Whether V2's opacity violates the operator's own 2026-06-21 "so intrusive"
  objection that produced the 0.58 in the first place.
- Whether the halo in V3 actually works over real VFX. WCAG cannot score it.
- Whether any of this survives the doctrine rule-1 1.5s glance budget.

--------------------------------------------------------------------------------
## 6. WHAT THE OPERATOR MUST DECIDE
--------------------------------------------------------------------------------

These need eyes on real gameplay. None can be closed headless.

1. **The occlusion budget.** How much of the game may a widget hide? This is a
   preference, not a metric. V1 at 0.90 and V2 at 0.97 differ by very little in
   contrast and a great deal in feel. Decide the alpha by looking, then the
   variant follows.
2. **Bright-field reality.** Does the bright proxy actually resemble the worst
   real frame? Mid-river at noon with a bright champion model under the widget
   is the real test. If real frames are less extreme than the proxy, V3 comes
   back into contention; if more extreme, V1 may need to go past 0.90.
3. **The V3 halo, over VFX.** The only way to score a text halo is to read the
   text over a real teamfight. If it holds, V3 is the doctrine-purest answer.
4. **The `w-call` transparency question.** Fixing section 1.3 makes the primary
   widget see-through for the first time. The operator has never seen that.
   It may be an improvement or it may be the reason nobody noticed the bug.
5. **Whether the variant is a mode or the default.** DS3 says "keep a documented
   in-game legibility variant", which reads as an operator-selectable state, not
   a replacement. If it is selectable, where does it live - the overlay settings
   strip beside Size / Transparency (SP3, `docs/qa/UI_UX_PROGRAM_QA_2026-07-22.md`)?
   And should it auto-engage on `data-fight="1"`, when reading matters most?
6. **The NOW chip.** Cyan on a cyan wash, over cyan VFX, unmeasurable here for
   lack of a fixture. Either watch for it live at a real objective timer, or
   commission a fixture with `eta_s: 0`.
7. **Whether the section 1.3 repair ships on its own.** It is a bug regardless
   of which variant wins, and it is arguably a DS1 chrome-collapse item rather
   than a DS3 item.

--------------------------------------------------------------------------------
## 7. HOW TO RESUME
--------------------------------------------------------------------------------

Prerequisite: the RC supervisor must be up, serving `https://127.0.0.1:8888`.
No League, no LCU, no live game needed - the frames come from the committed
`data/ui_mock/active_match_<mode>.json` fixtures.

```
PY="C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe"

# Full matrix: 4 variants x 3 backdrops, PNGs + contrast report.
$PY tools/overlay_legibility_preview.py

# Same, with the combat-shed OBJECTIVE footer and pane heads un-hidden
# (colours unchanged - this only puts them in the picture).
$PY tools/overlay_legibility_preview.py --show-shed

# One cell.
$PY tools/overlay_legibility_preview.py --variant v1_hairline_scrim --backdrop bright_rift

# Numbers only, no PNG writes (fast).
$PY tools/overlay_legibility_preview.py --no-shots

# A different fixture.
$PY tools/overlay_legibility_preview.py --mode aram
```

Artifacts, all under `tools/pseudo_screen_out/` (gitignored as of this work -
`.gitignore` did NOT cover this directory before; the entry was added):

```
legib_<variant>_<backdrop>_sr_2560.png          combat-shed state (12 files)
legib_<variant>_<backdrop>_sr_shed_2560.png     shed rows un-hidden (12 files)
_backdrop_<name>.png                            the three proxy sources
legibility_report.json                          every pair, chain and ratio
```

To try a fourth variant: add an entry to `VARIANTS` in
`tools/overlay_legibility_preview.py` and add its name to the spec section 3.
`tests/test_overlay_legibility_variants_spec.py` asserts the registry and this
document list the same names, so it will fail until both are updated.

To adopt a variant: move its CSS block into `web/css/overlay.css`, keeping the
`#view-active-match .am-pane.ovx-widget` specificity repair, then run the
5-phase UI fixture audit before the commit (CLAUDE.md "UI Fixture Ritual").

Related: `docs/OVERLAY_DOCTRINE.md` (the 10 rules),
`docs/UI_CAPTURE_RECIPES.md`, `tools/pseudo_screen_overlay.py` (the harness this
one is built on).
