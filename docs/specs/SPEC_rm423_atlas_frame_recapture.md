# RM-423 - re-capture the 13 dashboard frames embedded in atlas.html

Filed 2026-09-14 (LEDGER 1416). The one-line tracker row lives in `ROADMAP.md`;
this is the body, relocated so the ROADMAP stays inside its size budget.

## Why this exists

`atlas.html` embeds 13 JPEG screenshots of the coaching dashboard, shown in its
snapshots gallery. As of 2026-09-14 that artifact is served publicly at
`https://remus3.github.io/Amberstone/atlas.html`, so those frames are the only
pictures of this project anyone will see.

Two of the four original defects are FIXED and are in the tree already:

- the `RIOT COMMANDER` wordmark is now `AMBERSTONE`, rendered into the original
  ink box at the original cap height and sampled colour
- the debug footer is gone (machine name, `ws://` endpoint, version string, ui
  hash), with `VOICE` and `CLIENT` preserved because they are real UI

Two are NOT fixable by editing, and this was measured rather than assumed.

## The two that need a re-capture

**Resolution.** The frames are 560x798 with a **15-pixel cap height**. Going to
1920x1080 is a 3.4x linear upscale on text that thin. No upscaler recovers glyph
identity that is not in the source - it can only make a confident guess look
sharp, which on UI text means inventing letterforms. An illustration-tuned model
is worse than useless here: it smooths glyph edges.

**The set does not match at the source.** Twelve frames are 560x798 portrait and
one (`In-Game Overlay`) is 1000x563 landscape. Cropping the twelve to landscape
would cut the UI they exist to show. **"Reads as one set" is decided at capture
time, not afterwards.**

## Capture spec

Sized so the result survives base64 embedding in a single self-contained HTML
file, which is the real constraint on `atlas.html`.

1. **Capture at 2560x1440, deliver at 1280x720.** Set the viewport to 1280x720
   with `deviceScaleFactor: 2` so the browser renders natively at 2560x1440,
   then downsample ONCE to 1280x720. **Do not resample twice.** A single
   downsample from a native render beats any upscale, and it beats capturing at
   1280 directly, because the text is rasterised at 2x and averaged down.
2. **One viewport for all 13**, including the overlay - composite it onto a
   1280x720 dark backdrop rather than shipping its own aspect ratio. This is
   what makes them read as a set.
3. **Turn the debug strip off BEFORE capturing** - machine name, `ws://`
   endpoint, version string, ui hash, `UI-MOCK:ON`. Cheaper than removing it
   afterwards, and it cannot be half-removed.
4. **WebP q80, not JPEG.** JPEG rings badly on a dark UI with thin bright text,
   which is exactly what produced the current softness. Expect roughly 60-110 KB
   per frame at 1280x720, so about 1.1-1.4 MB across 13, or near 1.9 MB once
   base64 inflates it by a third.
5. **Capture with the page fully settled** - fonts loaded, no animation
   mid-flight, no hover state. Otherwise frames differ in ways that read as
   sloppiness rather than as design.

## The tradeoff to decide, stated plainly

The current cleaned set occupies **541119 bytes** of the file. The spec above
lands near 1.9 MB. **This change GROWS the page by roughly 1.4 MB**, against a
current total of 913904 bytes. That is the decision: a correct-looking set at
more than double the page weight, on a page served over the network. Decide it
deliberately rather than discovering it at the end.

## Acceptance

- all 13 frames at one geometry, no debug strip, correct wordmark
- `pytest tests/test_atlas_dust.py` green
- `atlas.html` still pure 7-bit ASCII (`test_file_is_pure_ascii` is a byte check)
- the page still opens and drives from the Pages URL
- the gallery labels still match their images one for one - the embed maps label
  to filename and ASSERTS the pairing; do not loosen that to positional order

## When it lands

Discard the current set outright. It is a stopgap that fixed the brand and the
cruft at 560 px and nothing more.
