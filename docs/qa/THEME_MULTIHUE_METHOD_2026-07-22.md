# Multi-hue theme methodology (research 2026-07-22) - for the coordinated-palette rebuild

Operator direction: theme palettes must be COORDINATED MULTI-HUE (like splash art) - a dominant base,
a structural metal, a primary, and a scarce pop/complement, blended via gradients + hue-shifts that
pull the eye - NOT a flat single accent on grey. Genre validation: the LoL client itself is
proportional multi-hue (gold frames ~30% structural, blue scarce ~10% eye-pull accent, grey ~60%);
competitors (Overlay App E/Aggregator C/Aggregator A) sit at the FLAT end, so coordinated palettes read MORE on-brand.

## Method
- COLORSPACE = OKLCH/OKLab. Perceptually uniform (even lightness across hues), independent L/C/H (so
  color-mix hover/active is hue-locked), and no muddy gradient midpoints. Author every token OKLCH-first
  with a hex fallback line ABOVE it (hex first, then oklch() override on same property). Gradients:
  `linear-gradient(in oklch, ...)` with an EXPLICIT middle stop that is LIGHTER and HIGHER-CHROMA than
  the endpoints (keeps it luminous). Support = Baseline widely available (2023+); color-mix Safari 16.2+.
- PROPORTION = 60-30-10 with a 7/3 primary-pop split: base canvas ~60%, surfaces+structural-metal ~30%,
  primary accent ~7%, pop/complement ~3%. Scarcity IS the eye-pull; keep large areas low-chroma, spend
  high chroma on the small 10%.
- HARMONY per palette (OKLCH hue angles): analogous 15-30 apart, complementary 180, split-comp +/-30 off
  complement, triadic 120. img4 = analogous purple/magenta run + cyan SPLIT-complement pop (not true
  complement green); equalize chroma across the family (~0.19-0.24 C), separate by lightness.
- VARIANCE DEPLOYMENT (color must move, not sit): gradient fills on progress/decomposition tracks
  (--hextech-fill), theme-tinted glow blooms (--glow), panel-header sweeps, gradient hairlines, pop-
  colored FOCUS RINGS, color-mix hover/active. Pop = the "reward color": reserve for gradient ends,
  focus, single exception chips. Primary carries structure/volume; metal frames; base recedes.
- ACCESSIBILITY: body text >=4.5:1 (near-white L>=0.93 on L 0.15-0.30 base); status good/warn/bad kept
  at their OWN fixed L/C + icon-paired, never resting on hue alone; in red-family palettes keep
  decorative red as gradient/glow only and semantic bad-red a solid chip at a distinct lightness.

## Per-palette OKLCH recipes (hex = fallback; validate via oklch.com, clamp sRGB)
Shared status triad (all): good oklch(0.72 0.15 148)/#4fb56a, warn oklch(0.80 0.14 85)/#e0b23e,
bad oklch(0.58 0.20 28)/#d54432.

**P1 Ember (black/red/gold/white; warm analogous, tension=value):** canvas oklch(0.16 0.020 25)/#181110,
surf 0.21/#241814, s2 0.26/#31221c, s3 0.31/#3f2c24, gold 0.80 0.130 88/#e3b04d, primary-red
0.56 0.220 27/#cf3a2e, pop-white 0.97 0.008 90/#f7f2ea, fill #cd382c->#e0873a->#eec158,
glow rgb(217 74 60/.35).

**P2 Hextech (blue-black/gold/aqua/white; near-complementary = the native LoL language):** canvas
0.16 0.030 250/#0e1420, surf 0.21/#16202f, s2 0.26/#1f2c40, s3 0.31/#293951, gold 0.82 0.130 88/#e8be5c,
primary-aqua 0.82 0.110 195/#59ddd6, pop-white 0.97/#eff4f9, fill #2a5aa8->#3e9fc2->#59ddd6,
glow rgb(89 221 214/.40).

**P3 Bloodmoon (black/red/gold/light-red; analogous mono-with-shift, lowest clash):** canvas
0.15 0.020 22/#160f0e, surf 0.20/#221613, s2 0.25/#2f1f1a, s3 0.30/#3d2822, gold 0.80 0.130 85/#e3af4a,
primary-red 0.55 0.220 25/#cc372c, pop-light-red 0.72 0.160 22/#f47563, fill #bd3226->#e05446->#f47563,
glow rgb(228 84 70/.35).

**P4 Arcane (purple/magenta/cyan; analogous run + split-comp cyan pop; metal = LAVENDER-SILVER not gold):**
canvas 0.16 0.040 300/#17101f, surf 0.22/#231730, s2 0.27/#2f1f42, s3 0.32/#3b2853, metal
0.72 0.045 305/#ad9dbd, primary-purple 0.58 0.190 305/#9646d9, pop-cyan 0.80 0.130 195/#35d9d2,
magenta-secondary 0.66 0.230 335/#e5449a, fill #9646d9->#e5449a->#35d9d2 (magenta MID lighter+chromatic),
glow magenta rgb(229 68 154/.40) + cyan rim rgb(53 217 210/.30).

## Build handoff
OKLCH property + hex fallback line above; hover/active via color-mix(in oklch, ...); all gradients
`in oklch` with a lighter+higher-chroma mid stop; pop area <=~3%; validate+clamp before commit.

Status: Arcane (P4) being built first as the proof-of-method exemplar (theme5_ renders). If it reads
right, apply the same method to Ember/Bloodmoon/Hextech/moonlit and re-tune the flat candidates.
Sources: evilmartians OKLCH, MDN, web.dev Baseline, css-tricks, Riot Nexus "Visual Language of Hextech".
