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
