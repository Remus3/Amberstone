# T4 - rendered-frame analysis of replays

Authored 2026-07-26. Status: **GO. Experiments 1 and 4 RAN AND PASSED against
a live replay - the technique is measured, not inferred.** Results in section
0. The remaining experiments in section 6 are still open.

Companions: `docs/REPLAY_FRAME_ANALYSIS_SPEC.md` (acquisition),
`docs/REPLAY_T2_PARSE_CRITERIA.md` (what the data tiers can and cannot answer).

## 0. MEASURED RESULT - the go/no-go passed

Run 2026-07-26 against a live replay paused at t=420.0, camera in fps mode at
(7200, 3000, 5176), fov 60, fog off, interface off.

**Experiment 4 first (determinism), because experiment 1 depends on it:**

    two identical renders, pixel delta over threshold 30 ..... 0 px

Exactly zero, and zero again under every combination of particles /
floatingText / banners / environment / champions toggled off. **The paused
render IS deterministic.** A first attempt appeared to show a 96337 px noise
floor; that was my error - the frames were grabbed before the scene had
settled after a camera move, not because anything was animating. Always settle
after a camera change before the first grab.

**Experiment 1 (the go/no-go):**

    minions ON vs minions OFF ....... 11694 px changed (0.317% of frame)
    minions ON vs minions ON ........      0 px changed
    connected components >= 40 px ...      8 blobs

Signal against a zero noise floor. **The toggle isolates a real entity class.**

**Composition test - differential mask through the existing back-projection:**
taking each blob's foot point (bottom of the mask column, matching the
`screenPositionBottom` convention) and running `screen_to_map`:

| blobs | mean distance off the mid-lane axis | max |
|---|---|---|
| 6 blobs >= 500 px | **76 units** | 137 |
| all 8 | 515 units | 3653 |

The six substantial blobs have centroid (7023, 7069) and span x 6618..7467,
z 6695..7394 - a minion wave sitting on the mid-lane diagonal. The single
outlier is a 175 px blob 3653 units away, i.e. a different entity elsewhere on
screen, not a failure of the projection.

**So the full chain works end to end:** toggle diff -> connected components ->
foot point -> ray/ground-plane solve -> map coordinates that land on the actual
lane, to ~76 units. For reference a champion radius is ~65 units.

WAVE STATE IS THEREFORE NO LONGER BLOCKED. It was blocked at every data tier
and is measurable from frames.

### Experiment 2 - champion mask vs screenPositionBottom (free ground truth)

Champions appear BOTH as pixels and as a reported screen position, so the mask
can be scored with no labelling. Diffing the `champions` toggle and matching
each reported position to its nearest mask blob:

| camera height | champions on screen | changed px | median error | within 60 px |
|---|---|---|---|---|
| 6000 | 7 | 2380 | 172 px | 2 of 7 |
| 3500 | 6 | 7977 | **42 px** | 5 of 6 |
| 2500 | 4 | 20966 | 56 px | 3 of 4 |

PASSES at a working height, and the first run failing was MY setup error: at
h=6000 a champion covers only ~340 px, which sits at the blob-detection floor.
The minion go/no-go had run at h=3000 and I did not carry that over.

**CAMERA HEIGHT IS A DETECTION PARAMETER, not just a framing choice.** Working
range is roughly h=2500..3500. Higher trades entity size for map coverage, and
past ~6000 entities stop being reliably separable. Any sampling pass has to
pick height per what it is detecting, and a wide overhead shot is NOT free.

**The champion mask FRAGMENTS**: 10 blobs for 6 champions, 13 for 4. A model
splits into parts, so blob COUNT is not entity count and naive counting
overcounts. Cluster before counting - and note the minion result did not show
this as strongly, so per-class clustering needs its own check.

Champion detection is also mostly redundant, since `screenPositionBottom`
already gives champion positions directly. Its value here is exactly what it
was used for: scoring the technique against truth.

### Experiment 3 - do ENEMY wards render under fogOfWar=false? YES

Diffing the `healthBarWards` toggle at t=900 with fog off, h=3500:

    changed px .......... 8618
    blobs >= 25 px ......   13

and sampling each blob's colour in the ON frame gives BOTH team colours:

    area 814  RGB (146, 74, 73)   red
    area 807  RGB ( 66,122,146)   blue
    area 733  RGB (  4, 70,101)   blue
    area 518  RGB (110, 33, 34)   red

**So enemy wards DO render with fog disabled, and WARD COVERAGE UNBLOCKS.**
Vision coverage was blocked at T1/T2 because `WARD_PLACED` carries no position;
it is recoverable here. The near-identical blob areas (814/813/811, 518/518/518)
are consistent with fixed-size markers rather than noise.

TWO CAVEATS before building on it:

1. **The marker is a HEALTH BAR, drawn ABOVE the ward, not at its feet.** The
   back-projection assumes a ground point, so ward map positions will carry a
   systematic offset until that is calibrated - most cheaply by placing a known
   ward and solving the delta, exactly as the camera intrinsics were solved.
2. **The blob count is NOT verified against a ward count.** Wards expire and
   the timeline emits no expiry event, so placed-minus-killed is only an upper
   bound. 13 blobs is plausible for mid-game but is UNCONFIRMED.

For reference the `characters` toggle changed 59313 px across 81 blobs at the
same instant - a much broader class than wards. It was not characterised
further.

### Experiment 4 - buff camps: INCONCLUSIVE, and it found a method defect

Measured 2026-07-26 on a live operator replay, camera parked over the
blue-side red buff at h=3500, pitch 56, fov 60, `interfaceAll`/`fogOfWar`/
`particles`/`floatingText` off.

**THE DEFECT, AND IT INVALIDATES ANY DIFF TAKEN WITHOUT A WARM-UP. The first
`/replay/render` POST after a pause or a camera move causes a one-time change
of about 35,000 px that NEVER REVERTS.** Measured directly by toggling an
entity class off and back on and re-diffing against the original base:

```
control grab-vs-grab                                      0
characters   off-vs-base=  54071   RESTORED-vs-base=  34954
champions    off-vs-base=  37213   RESTORED-vs-base=  34954
minions      off-vs-base=  37250   RESTORED-vs-base=  34954
```

The identical 34954 under all three toggles is the tell: it is not an entity
class, it is a constant added to every measurement. **A single dummy toggle
round-trip before grabbing the base fixes it completely** - RESTORED-vs-base
becomes exactly 0 for all three, and the real numbers appear:

```
post-warmup control                                       0
characters   off-vs-base=  27410   RESTORED-vs-base=      0
champions    off-vs-base=   2258   RESTORED-vs-base=      0
minions      off-vs-base=   2296   RESTORED-vs-base=      0
```

**Every future T4 diff MUST warm up and MUST assert RESTORED-vs-base == 0.**
The grab-vs-grab control that experiments 1 to 3 used does NOT catch this: it
reads 0 while the base is already stale. The 11694 px wave-state figure and
the 13-blob ward figure were taken without a warm-up and should be re-measured
before either is built on.

**What the corrected numbers say.** `characters` removes 27410 px where
`champions` removes 2258 and `minions` removes 2296, so about **83 percent of
the `characters` class at a camp-aimed pose is neither a champion nor a lane
minion**. Neutral entities render and are separable in principle.

**Why it is still INCONCLUSIVE.** The residual
`characters AND NOT champions AND NOT minions` is not a clean camp signal: it
contains STATIC objects. Sampled at t=100, 400 and 800 s from an unmoved
camera, the largest residual blob is **6213 px at map (5121,4735) at all three
times, to the pixel**. A living monster's idle animation cannot produce an
identical pixel count at three different game instants; jungle plants and
scenery can. Residual totals were 22874 / 15448 / 13933 px, so the class does
vary with time, but the variation is not attributable.

**The next experiment, not run here:** diff the SAME pose at TWO TIMES with
identical toggles. Static scenery cancels; anything that moved or died does
not. That is the discriminator this run lacked, and it needs no new
machinery.

### Experiment 4b - re-measure of wave state and wards under the warm-up

Run 2026-07-26 immediately after the defect above, same live replay, t=900 s,
camera on the mid-lane centroid (7023,7069) at h=3500, fov 60, fog off.

**WAVE STATE SURVIVES. THE MAGNITUDE DOES NOT.** With control 0 and
RESTORED-vs-base 0, the `minions` toggle changes **4787 px across 7 blobs**,
against the originally reported 11694 px / 8 blobs - the original was inflated
roughly 2.4x by the missing warm-up. The capability claim is unaffected:
minions render as a separable class, and the blobs landing on the mid-lane
axis land tightly (64, 7 and 92 units off it, consistent with the original
76-unit mean). The remaining blobs sit 1593 to 3204 units off-axis and are
other-lane or jungle units in frame, not wave members, so **blob count is not
wave size** and off-axis distance is the filter that separates them.

**WARDS: METHOD CLEAN, COUNT NOT REPLICATED.** `healthBarWards` gives 1595 px
across **2 blobs** with RESTORED 0. This does NOT refute the original 13 - that
run used a different game and framing, and a mid-lane pose sees fewer wards
than a wide one. What it establishes is that the ward class restores
deterministically and renders, which is what the capability rests on.

**A CORRECTION TO EXPERIMENT 4'S WARM-UP RULE, measured.** A first attempt here
read RESTORED=4728 on `minions`, and the obvious inference - that the minions
class is non-deterministic - is WRONG. Three consecutive `minions` round-trips
immediately afterwards each returned exactly 0, as did two `healthBarWards`
round-trips. The residual was the one-time settle still draining, because the
warm-up used a DIFFERENT toggle (`banners`) from the one being measured. So the
rule is stronger than experiment 4 stated:

> Warm up with the SAME toggle you are about to measure, and assert
> RESTORED-vs-base == 0. Discard any measurement where it is not 0.

### Experiment 4c - the two-time discriminator WORKS, and it is bimodal

Run 2026-07-26. Camera parked over the blue-side red buff, unmoved, at t=100 s
and t=800 s with identical toggles. All six RESTORED checks returned 0.

Scenery cancels between two instants; anything that moved, died or respawned
does not. Applied to the neutral residual
(`characters AND NOT champions AND NOT minions`):

| blob px | map | changed by t=800 | verdict |
|---|---|---|---|
| 6213 | 5121,4735 | **0 pct** | STATIC |
| 3740 | 6516,3295 | 12 pct | STATIC |
| 1571 | 4033,6362 | **98 pct** | MOVER |
| 1246 | 9000,8297 | 3 pct | STATIC |
| 1212 | 11323,3928 | 0 pct | STATIC |
| 815 | 6937,5248 | **100 pct** | MOVER |
| 439 | 3870,3763 | 0 pct | STATIC |

**The separation is bimodal with nothing in between** - 0/0/3/12 percent
against 98/100. There is no threshold to tune, which is what makes this usable.

**The 6213-px blob that appeared identical at t=100, 400 and 800 in experiment
4 is now PROVEN static** at 0 percent changed over 700 seconds. That confirms
the suspicion 4 could only raise: the neutral residual is dominated by scenery.
Roughly 2400 px of ~19300 are movers, so **about 87 percent of what
`characters` removes at a camp-aimed pose is world geometry, not entities.**

**What this means for camps.** The right signal is a state CHANGE, not a
presence. A camp alive at both instants reads static like a plant does; a camp
killed, respawned or pulled between them reads as a mover. So camp TIMING is
measurable by differencing two instants, while camp PRESENCE at a single
instant is not separable from scenery by this method. Two movers were isolated
here, at (4033,6362) and (6937,5248); confirming they are camps rather than
pets or other neutrals still needs ground truth, which no data tier supplies
(`ELITE_MONSTER_KILL` covers only DRAGON/HORDE/RIFTHERALD/BARON).

**Warm-up, third correction.** A SEEK re-arms the one-time settle, and one
same-toggle round-trip is not enough to drain it after a seek plus a camera
move - the strict RESTORED==0 assert fired on the first attempt. Two
round-trips per toggle plus a 2.5 s settle after the seek drove all six to 0.
Keep the assert; it is the only thing that catches this.

### Experiment 5 - capture geometry

Full-screen `PIL.ImageGrab` returns **2560 x 1440**, matching the viewport the
back-projection intrinsics were solved for (`LEGION_2560x1440_FOV60`). No
rescaling needed on this machine; a different resolution needs a re-solve.

### Experiment 6 - unattended operation: NEGATIVE by construction

The capture path is a FULL-SCREEN grab, so the game must be visible and
unoccluded. Anything covering the window is captured instead of it. **T4
therefore cannot run unattended alongside other work on the same display.**

UNMEASURED and the only plausible escape: a window-directed capture
(Win32 `PrintWindow`) can sometimes capture an occluded window. Untested here.
Until it is tested, plan T4 as attended and exclusive.

## 1. Why this tier has to exist

Three items on the operator's list are BLOCKED at every data tier, and they are
blocked for one reason: **the entity is rendered but never exposed.**

| blocked item | rendered? | in any API? |
|---|---|---|
| wave state | YES, minions are drawn | no minion entity anywhere |
| ward coverage | YES, wards are drawn | `WARD_PLACED` has no position |
| buff camps / sharing | YES | camps are never named, only counted |

So the pixels carry information the JSON does not. That is the whole argument
for T4, and it is why "second by second" was the right instinct: the data tiers
cap out at 60 s for position and have no minion concept at all.

## 2. What makes this CHEAP here, versus generic video CV

Do not build a video pipeline. Two measured properties of the replay API make
frame capture deterministic rather than statistical:

**Seek is exact when paused.** VERIFIED: `POST /replay/playback {"paused":
true, "time": 600.0}` lands on exactly 600.0. So there is no frame extraction,
no timestamp alignment, no dropped-frame problem, and no need to record video
at all. Sample the instants you care about.

**The same instant can be re-rendered.** Because the game is paused and the
camera is fully controllable, one timestamp can be photographed many times with
different render settings and an identical camera. That is the key.

### 2.1 Differential rendering - the core idea

`/replay/render` exposes per-entity-class toggles. The full verified key list
includes: `minions`, `champions`, `characters`, `particles`, `environment`,
`banners`, `floatingText`, `fogOfWar`, `healthBarMinions`, `healthBarWards`,
`healthBarChampions`, `healthBarStructures`, `healthBarPets`, `outlineSelect`,
`outlineHover`, plus the whole `interface*` family.

So, at one paused instant with a fixed camera:

```
frame A = render with minions ON
frame B = render with minions OFF        (nothing else changed)
diff(A, B) = exactly the minion pixels
```

No model, no labels, no training set. The difference is deterministic because
the only variable is the toggle. Repeat per class:

| target | toggle to flip | yields |
|---|---|---|
| minions / wave | `minions` | minion pixel mask -> counts, clustering, lane position |
| wards | `healthBarWards` | ward markers -> ward positions |
| champions | `champions` | champion pixel mask (cross-check against `screenPositionBottom`) |
| ability effects | `particles` | spell-effect mask -> cast detection |
| terrain removal | `environment` | isolates all entities from the map art |

Then apply the ALREADY-CALIBRATED back-projection
(`core/replay_camera.screen_to_map`, measured ~19 map units self-consistency)
to convert any detected screen position into map coordinates.

**That composition is the actual proposal: differential render for
segmentation, existing ray solve for geometry.** Neither half needs machine
learning.

### 2.2 Self-validation is available for free

Champions appear BOTH as rendered pixels and as `screenPositionBottom` values.
So the champion mask can be scored against a known ground truth on every single
frame, with no labelling. If the champion diff does not land on the reported
screen positions, the technique is wrong and we find out immediately rather
than after building on it. **Run this before trusting any minion output.**

## 3. What T4 would unblock

| item | how |
|---|---|
| Wave state | minion mask -> cluster by lane -> per-lane minion count and centroid. Wave position, size, and which side it is pushing toward all follow |
| Over-extended lane | champion map position vs the wave centroid, not vs a fixed lane midpoint |
| Pre-minion positioning | already T3-capable via back-projection; T4 adds what they were doing |
| Ward coverage | ward markers -> map positions -> vision-area polygons over time |
| Buff camps | camp presence at known camp coordinates, sampled over time, gives spawn and clear intervals that the API never names |
| Ability casts | particle diff at a champion's position, timestamped to the sampled instant |

## 4. Cost model - be honest about it

Per sampled instant: 1 seek + N renders + N screenshots, where N is the number
of entity classes wanted. At ~2.5 s settle per seek and ~1.5 s per render
change, one instant with 3 classes is roughly 10 s of wall clock.

- 1 sample / 30 s of game = ~50 samples for a 25 min game = ~8 min per game
- 1 sample / 5 s = ~300 samples = ~50 min per game

**This is interactive and one game at a time, exactly like T3.** It does not
scale to the ladder and must not be planned as if it does. T4 is for a small,
hand-curated deep corpus; T1/T2 remain the breadth tier.

UNMEASURED: whether the settle time can be shortened, and whether the game
renders correctly while its window is not focused (which decides whether this
can run unattended alongside other work).

## 5. Existing RC assets to reuse, not rebuild

- `vision_server` at `:8889` already accepts frames and serves `/latest-frame`.
- `modes/shared_vision._capture_screen()` is the existing capture path.
- The tiered OCR-then-Sonnet routing already exists for text regions
  (`reference_tiered_vision_routing`), which is the right tool for HUD numbers
  (cooldowns, timers) that differential rendering cannot isolate.
- OBS is installed on Legion if a video path is ever genuinely needed. It is
  not needed for paused sampling.

Differential rendering handles ENTITIES. OCR handles HUD TEXT. Sonnet vision is
the escalation for anything neither resolves. Do not use a vision model for
work a toggle-diff answers deterministically.

## 6. Experiments that decide this - run before building

Each is a single live-replay probe. Ordered so a failure kills the plan early
and cheaply.

1. **Does `minions` actually remove minions from the render?** Flip it at a
   paused instant, screenshot both, diff. If the toggle is cosmetic-only or
   ignored, the entire technique dies here. THIS IS THE GO/NO-GO.
2. **Champion mask vs `screenPositionBottom`.** Diff on `champions` and check
   the mask centroids land on the reported screen positions. This scores the
   method against free ground truth.
3. **Do ENEMY wards render with `fogOfWar=false`?** If fog-off reveals only
   allied vision, ward coverage stays half-blocked.
4. **Is the render deterministic across two identical requests?** Screenshot
   the same instant twice with no changes; a non-empty diff means animation or
   particles keep advancing while paused, and every diff needs a noise floor.
5. **Capture path and resolution.** Establish how the frame is captured
   (existing `:8889` path vs a direct grab) and at what resolution, since the
   back-projection intrinsics are viewport-specific
   (`LEGION_2560x1440_FOV60`).
6. **Does it render unfocused?** Decides attended vs unattended operation.

## 7. Honest position

The primitives are real and measured: exact pausable seek, full camera control,
render toggles that stick, and a calibrated ~19-unit screen-to-map solve. The
composition of those into entity segmentation is a REASONABLE INFERENCE and
nothing more until experiment 1 passes.

If experiment 1 fails, the fallback is conventional CV on the rendered frame
(template matching for minion sprites, colour keying for team), which is
weaker, needs tuning per patch, and should be treated as a separate decision -
not as an automatic next step.
