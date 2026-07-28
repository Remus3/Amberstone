# CV-5 - training pipelines that consume auto-generated replay masks

Authored 2026-07-28. Research slice: which detector architectures and training
pipelines best consume T4 differential-render masks, and what still needs human
labels. Licence and version facts below were pulled live from the GitHub REST
API and PyPI this session; anything not pulled is marked UNVERIFIED.

## 0. THE FRAME THIS SLICE HAS TO BE READ IN - and a correction to "unlimited"

RC has already measured the mask-generation half. `docs/REPLAY_T4_FRAME_CV.md`
carries it and this document does not restate it. Four of its results set every
constraint below:

- The paused render is deterministic: **0 px** delta on two identical renders,
  including with particles on. Measured, not inferred.
- The `minions` toggle removes minions: **4787 px / 7 blobs** post-warm-up at
  t=900, h=3500 (the widely-quoted 11694 was inflated ~2.4x by a missing
  warm-up).
- Champion masks **FRAGMENT**: 10 blobs for 6 champions, 13 for 4.
- The one-time settle after a seek or camera move adds a constant ~34954 px to
  every diff until it drains. The mandated gate is warm up with the SAME toggle
  and assert RESTORED-vs-base == 0.

And `docs/REPLAY_FRAME_ANALYSIS_SPEC.md` plus `core/replay_seek.py` set the
supply: `/replays` is forward-harvest only, patch-locked playback, T4 is
attended and exclusive, and `:2999` `allPlayers[].position` is a ROLE STRING -
Riot exposes **no champion map coordinates live in SR, ARAM or Practice**.

Two consequences that reframe the whole task.

**(a) This is DISTILLATION, not labelling.** The toggle diff already gives a
perfect mask, so a model buys nothing offline. The model exists solely to run
where the toggles do not: on an ordinary live frame, at RC's 2 s vision cadence,
with the HUD on and fog on and a locked camera, where `:2999` refuses to give
positions at all. Every architecture and augmentation decision below follows
from "train in the replay renderer, infer on a live frame".

**(b) "Unlimited auto-masks" is FALSE, and this is the single most important
correction in this document.** The masks are free per instant; the INSTANTS are
not. From the T4 cost model: ~2.5 s settle per seek plus ~1.5 s per render
change, plus the mandated two same-toggle round-trips after a seek. Call it
10-15 s for one instant with 3 classes, attended and exclusive on one display.

    8 h attended  ->  roughly 2000-2900 instants
    per instant   ->  1 input frame + N class masks

So the realistic corpus is **10^3 to low 10^4 frames drawn from tens of
matches**, not 10^6 from thousands. The failure mode the operator predicted
(correlated data) is therefore not a scale-stage problem to solve later - it is
the FIRST-ORDER problem from frame one. It also rules out training anything
large from scratch and rules in a small model on a frozen pretrained backbone
with aggressive augmentation. Plan the pipeline for a small, heavily correlated,
pixel-perfect dataset. That is a different engineering problem from the one
"free unlimited masks" suggests, and getting it wrong costs a rebuild.

Wall clock, not labelling, is the binding constraint. Any proposal that spends
capture time to buy label quality is spending the scarce resource.

## ARCHITECTURE FIT

**The auto-masks are CLASS masks, not INSTANCE masks.** The toggles are
per-entity-class. There is no per-entity toggle. A diff on `minions` yields one
binary map of "minion pixels", with no separation between two overlapping
minions, and RC measured that connected components are NOT instances (10 blobs
for 6 champions). So instance supervision is not free, and any pipeline that
assumes COCO-style per-instance polygons is assuming a label the renderer does
not emit.

That single fact decides the architecture: **semantic segmentation is the
natural consumer**, with instances recovered downstream by the clustering plus
foot-point plus `core/replay_camera.screen_to_map` chain RC already validated to
~76 map units. Instance segmentation is the right consumer for exactly one class
(champions) because that is the only class with a free instance seed.

| arch | pipeline | version (verified 2026-07-28) | licence | consumes masks how | verified? |
|---|---|---|---|---|---|
| Semantic seg (UNet / DeepLabV3+ / SegFormer heads) | segmentation_models.pytorch (`qubvel-org/smp`) | v0.5.0 tag 2025-04-17, repo pushed 2026-07-28 | **MIT** | native - a HxW class-index map is exactly what the toggle diff produces. Zero conversion, zero information thrown away | YES - gh api |
| Semantic seg (full toolbox, many heads) | MMSegmentation | v1.2.2 (2023-12-14), repo last pushed **2024-08-13** | Apache-2.0 | native, plus `reduce_zero_label` / ignore-index support for the AA halo band | YES - gh api. Staleness is the risk, not the licence |
| Instance seg, real-time, permissive | **RF-DETR (`RFDETRSeg*`)** | 1.8.3 (2026-06-29), pushed 2026-07-27 | **Apache-2.0** (the `rfdetr_plus` add-on is PML 1.0 - do not pull it) | needs per-instance polygons; only obtainable for champions via `screenPositionBottom` seeding | YES - gh api + repo README |
| Instance seg (Mask R-CNN family) | torchvision `maskrcnn_resnet50_fpn_v2` + `references/detection` | torchvision 0.28.0, 2026-07-08 | **BSD** (PyPI classifier) | per-instance masks + boxes; boxes derivable from masks trivially | YES - PyPI |
| Instance seg (research toolbox) | Detectron2 | no tag since v0.6 (2021-11-15) but repo pushed **2026-07-24** | Apache-2.0 | COCO-format instance polygons/RLE | YES - gh api. Install from git, not PyPI |
| RTMDet-Ins | MMDetection | v3.3.0 (2024-01-05), repo last pushed **2024-08-21** | Apache-2.0 | COCO instance format | YES - gh api |
| RTMDet-Ins | **MMYOLO** | v0.6.0 (2023-08-15), pushed 2024-07-14 | **GPL-3.0 - NOT Apache** | same | YES - gh api. **TRAP: the same model is Apache via MMDetection and GPL via MMYOLO. Take the MMDetection path** |
| YOLO-seg (instance) and YOLO semantic-seg | Ultralytics | 8.4.108, 2026-07-27 | **AGPL-3.0-or-later** | polygon label lines per instance; a separate semantic task exists in YOLO26 | YES - LICENSE file + PyPI |
| SAM / SAM2 | facebookresearch/sam2 | pushed 2026-05-30 | Apache-2.0 | **not a training consumer** - see below | YES - gh api |
| SAM3 | facebookresearch/sam3 | pushed 2026-07-28 | **NOASSERTION = custom Meta SAM licence** | promptable-concept labeller for classes no toggle isolates | YES - gh api licence field |
| Sliced inference / fine-tuning wrapper | SAHI | 0.12.2, 2026-07-20 | **MIT** | wraps any of the above; the small-object lever | YES - gh api |

### The licence call

**Ultralytics AGPL-3.0 is a live product constraint, not a formality.**
Ultralytics states that models produced by the AGPL training code are themselves
AGPL. RC ships a dashboard over HTTPS on `:8888`; AGPL section 13 is the network
clause, and a distributed RC build serving inference from an Ultralytics-trained
weight file is the exact shape AGPL is written to catch. Whether that claim over
WEIGHTS (as opposed to code) is enforceable is a legal question and is
**UNVERIFIED** here - but the safe engineering answer is trivially available:
**RF-DETR-Seg (Apache-2.0) and smp (MIT) do the same jobs with no copyleft.**
Use Ultralytics only as a throwaway internal baseline you never ship, or not at
all. Do not let a convenient `pip install ultralytics` decide the licence of the
product.

**The OpenMMLab stack is functionally frozen.** MMDetection, MMSegmentation,
MMYOLO and MMDeploy all last pushed in mid-2024 - roughly two years stale as of
today, with no releases since 2023-2024. The licences are fine (except MMYOLO);
the mmcv/PyTorch version pinning is what will hurt. Treat MMDetection as a
reference implementation to read, not a dependency to adopt.

### Recommended consumer, in order

1. **Primary: multi-class semantic segmentation via smp (MIT).** One model, one
   HxW output, K+1 channels for {background, minion, ward-marker, champion,
   neutral-mover, ...}. The auto-mask IS the target - no format conversion, no
   instance assumption, no anchors, no NMS. Downstream, RC's existing
   connected-components -> foot point -> `screen_to_map` chain converts pixels
   to the target outputs (wave centroid and size, ward map position, champion
   map position). This is the shortest path from mask supervision to the
   TARGET OUTPUTS, and it is the only one that needs no label the renderer
   cannot emit.
2. **Secondary, champions only: instance segmentation via RF-DETR-Seg
   (Apache-2.0).** Justified only because champions have a free instance seed
   (below). Its payoff is real: `:2999` gives no live coordinates, so a live
   champion locator is not redundant with anything.
3. **Do not train a plain box detector on boxes derived from masks.** It throws
   away the pixel supervision you paid for and it is strictly worse for the
   actual targets, which are ground-contact points and areas, not boxes. A box
   around a fragmented champion mask is also wrong in a way the mask is not.
4. **SAM-family is not a training consumer here.** SAM exists to produce masks
   when you have none; we have perfect ones. Two narrow real uses: (a) SAM2 as
   an edge REFINER on the anti-aliased halo, probably unnecessary given the
   ignore-band treatment below; (b) **SAM3 concept prompts as a labeller for
   things no toggle isolates** - "recall animation", "backing channel", a
   specific monster camp. That is a genuine gap-filler, but the custom Meta SAM
   licence has to be read before it touches a shipped product.

### The one free instance seed, and one untested route to more

Champions render BOTH as pixels and as `screenPositionBottom`. RC measured
median 42 px error at h=3500, 5 of 6 within 60 px. So for champions you get, per
frame, for free:

- instance separation (assign each mask blob to its nearest reported position),
- **the class label - which champion it is** - because `allPlayers` names them.

That is a 170-way identity label at zero cost, which is the single most valuable
free label in the whole corpus and it exists for exactly one entity class.
Caveat it properly: fragmentation means blob-to-position is many-to-one, so the
assignment must be nearest-position-wins with a distance cap, not one-to-one,
and blobs beyond the cap must be dropped rather than forced.

**UNTESTED and cheap: `outlineSelect` / `outlineHover`.** RC's verified toggle
list includes both. If the replay client can be made to select or hover a
single entity, then diffing that toggle isolates ONE entity - a genuine
per-instance mask for any class, including minions and wards, which nothing else
in the toggle set provides. One probe decides it. If it works, instance
segmentation becomes trainable for every class and the architecture
recommendation moves up a tier. This is the highest-value unrun experiment in
this document.

### The domain gap is the biggest technical risk, and it is fixable for free

Every T4 experiment RC ran used `interfaceAll` off, `fogOfWar` off, particles
off, an fps camera at h=2500-3500. A live frame has the HUD on, fog ON, particles
on, and the locked default camera. A model trained on the former and run on the
latter is a covariate-shift failure waiting to happen, and it will look like a
model bug rather than a data bug.

**The fix costs nothing and must be a hard rule of the capture harness:**

    INPUT image  = render with LIVE-REALISTIC settings (HUD on, fog on,
                   particles on, live camera mode and height)
    MASK         = diff( that same render , that same render minus ONE class )
    NEVER train on the ablated frame. The ablated frame is a measuring
    instrument, not a training sample.

This preserves realism exactly and the diff is still class pixels - just the
subset a player could actually see, which is precisely what a live model should
learn. It also changes what is learnable: with fog ON, enemy wards do not
render, so a fog-on ward model learns ALLIED ward coverage only. RC's experiment
3 result (enemy wards do render with fog off) is a replay-analysis capability,
not a live-inference one. Do not conflate them.

Two more capture-harness rules in the same family:

- **Turn off every `healthBar*` toggle in BOTH frames when you want a body
  mask.** Toggling `minions` also removes their health bars, which are drawn
  ABOVE the unit, so the blob's top is a bar and its vertical extent is wrong.
  RC hit exactly this with wards - the marker is a health bar drawn above the
  ward, so ward foot points carry a systematic offset until calibrated.
- **Match the camera to the live one.** The back-projection intrinsics are
  viewport-specific (`LEGION_2560x1440_FOV60`) and RC measured that camera
  height is a DETECTION parameter, not a framing choice. Training at h=3500 and
  inferring at the live locked height is a scale shift on top of everything
  else.

## WHAT AUTO-MASKS CANNOT TEACH

Be blunt: the toggle diff teaches **where a class's pixels are, in one frame,
with the render settings you chose**. Everything else on the target list needs
another source. The list below is organised by WHY the mask cannot supply it,
because the reason determines the substitute.

### 1. Class identity inside a lumped toggle group

`characters` is one toggle covering champions, minions, monsters, pets, plants
and - RC measured this - **about 87 percent static world geometry** at a
camp-aimed pose. There is no `monsters` toggle and no `pets` toggle. So:

- **Neutral monster vs pet vs plant: NOT separable.** RC isolated two movers at
  (4033,6362) and (6937,5248) and could not confirm they were camps rather than
  pets, because no data tier names camps (`ELITE_MONSTER_KILL` covers only
  DRAGON / HORDE / RIFTHERALD / BARON). This needs human labels or a
  concept-prompt labeller (SAM3), full stop.
- **Minion type (melee / caster / cannon / super): NOT separable.** One
  `minions` toggle. Cannon-wave detection is a real coaching signal and it needs
  either human labels on a few hundred crops or a hand-written appearance rule.
- **Ward type (stealth / control / trinket / farsight): UNVERIFIED whether the
  marker even differs.** RC measured near-identical blob areas (814/813/811,
  518/518/518) consistent with fixed-size markers. If the markers are visually
  identical, no amount of data fixes it.
- **Ward TEAM is free, not human.** RC sampled blob colour in the ON frame and
  got both team colours cleanly (red ~(146,74,73), blue ~(66,122,146)). Colour
  keying, not learning.

### 2. Anything defined by GAME STATE rather than pixels

This is the largest category and it is categorically outside what a segmenter
can be taught, no matter how much data:

- **"Is this wave slow-pushing / freezing / crashing?"** Push direction is a
  DERIVATIVE - it needs two or more instants and the minion-count differential
  between the two sides. The mask gives you the wave at time t. The state is a
  function of t and t-dt. Compute it, do not learn it.
- **"Is this ward warded-by-us?"** Team colour answers ally-vs-enemy. "Placed by
  the support 40 s ago and expiring in 50 s" is bookkeeping over
  `WARD_PLACED` events plus a ward-duration table, and RC already knows
  `WARD_PLACED` carries no position - so the JOIN between a detected ward pixel
  and the event that placed it is itself an inference, not a label.
- **"Has a fight started?"** A fight is a multi-agent temporal predicate. See
  the event-feed section; it is weakly labellable, never mask-labellable.
- **"Is this lane over-extended?"** Relational - champion position versus wave
  centroid. Both operands come from masks; the predicate does not.

### 3. Temporal and event boundaries

Every auto-mask is a SINGLE PAUSED INSTANT. There is no motion, no
before/after, no duration. Fight start/end, objective contest windows, recall
start/complete, respawn, back-timing - none of these have a pixel definition in
one frame. They need a label from the event feed (next section), a hand-written
temporal rule, or human annotation of boundaries.

**Recall specifically:** the `particles` toggle gives you a free mask of the
recall VFX pixels but no label saying "this is a recall". The cheapest label is
a weak rule using the seek sampler's measured-ground-truth inventory: position
teleports to fountain and inventory changes at t+8 s implies the particle blob
at t was a recall channel. That is a derived label with a false-positive rate
that must be measured, not a free one.

### 4. Occlusion semantics

The mask of a champion behind a wall is the VISIBLE fragment. Nothing in the
diff says "this is one entity, 60 percent occluded" versus "this is a small
entity". RC's fragmentation measurement (10 blobs / 6 champions) is this
problem showing up already. Amodal completion, occlusion ordering and
"is-this-two-units-or-one" are not derivable from a class mask and are the
single strongest argument for the `outlineSelect` probe.

### 5. Things the toggle set simply does not separate

- **Minimap icons.** The minimap is drawn by the `interface*` family, which is
  all-or-nothing: you can mask the minimap REGION, never a single champion icon
  inside it. Per-icon supervision does not exist. Minimap icons are also fixed
  circular portraits with team-coloured rings on a fixed background - that is
  template-matching territory with a deterministic answer, not learned
  detection. Do not train a detector for the minimap; build a matcher.
- **HUD numbers.** Cooldowns, timers and gold are text. Segmentation does not
  read text. RC's existing tiered OCR-then-Sonnet route
  (`reference_tiered_vision_routing`) is the correct tool and already exists.
- **Enemy cooldowns.** UNVERIFIED and worth checking BEFORE any work: whether
  the live SR HUD renders enemy ability or summoner cooldowns at all. If those
  pixels do not exist, the target is dead regardless of the detector, and the
  only route is observe-the-cast plus a timer, which is a particle-mask plus
  bookkeeping problem, not a HUD-OCR problem.

### 6. Free but easy to miss: HUD region masks

The one place the `interface*` family IS useful for supervision: diffing an
interface toggle on/off yields the **exact pixel extent of that HUD element at
whatever resolution the client is running**. That auto-calibrates
`data/vision_regions.json` instead of hand-tuning it, at any resolution, per
patch, for free. It is not a detector, it is a ROI generator for the OCR lane -
and it is probably the highest ratio of value to effort in this entire
document, because it improves a shipped RC subsystem with one afternoon of
capture and no model at all.

## FREE LABELS FROM THE :2999 EVENT FEED

**Verified structurally in RC's own code:** `core/replay_seek.py:137`
`get_allgamedata()` hits `{base}/liveclientdata/allgamedata` against the same
`:2999` that serves `/replay/render` and `/replay/playback`. So during a
PAUSED replay at a known instant t, the render and the full game state are
available from the same process at the same instant. That is an exactly aligned
label channel with zero synchronisation problem - the game is stopped.

The event names RC already parses (`dashboard/_state_cooldowns.py:16-18`,
`dashboard/_liveclient.py`, `game_reader/snapshot_normalizer.py`):
`ChampionKill`, `DragonKill`, `BaronKill`, `HeraldKill`, `TurretKilled`,
`InhibKilled`, `Multikill`, `Ace`, `FirstBlood`, `FirstBrick`, `GameStart`,
`MinionsSpawning`, `GameEnd` - each with an `EventTime`.

The feed is CUMULATIVE, so one call at the end of a replay gives every event
time for the whole match. That means **every sampled frame can be labelled
retrospectively with signed time-to and time-since every event type** without
re-seeking. This is the cheapest labelling channel available and it is
essentially free.

What it buys, concretely:

| target | free label from the feed | how |
|---|---|---|
| fight start / end | WEAK but usable | a `ChampionKill` at T implies a fight was underway in [T-8, T]; cluster kills within a window to bound start and end. Label frames `pre_fight` / `in_fight` / `post_fight` by offset |
| objective contest window | WEAK, good enough | `DragonKill` / `BaronKill` / `HeraldKill` at T implies contest in [T-45, T]. Frames in that window near the pit are positives |
| ace / teamfight outcome | STRONG | `Ace` and `Multikill` are unambiguous |
| wave timing | STRONG | `MinionsSpawning` anchors wave phase exactly |
| structure state | STRONG | `TurretKilled` / `InhibKilled` carry the structure name |
| per-frame roster metadata | STRONG | `allPlayers` gives champion, team, level, items, KDA, respawn timer at that instant - free stratification keys for the dataset |
| champion identity per mask blob | STRONG | `screenPositionBottom` + `allPlayers[].championName` (see above) |

Two honest limits. First, **the feed labels the MATCH TIMELINE, not the FRAME**
- "a kill happened at 14:32" does not say the killer is in this viewport. Any
frame-level positive needs the viewport-membership check, which comes from the
back-projection, not the feed. Second, and this is the scope rule the operator
set: gold, CS, items, levels and KDA are all in this feed for free, LIVE. **Any
CV pipeline whose payoff is re-deriving them is wrong and should be killed on
sight.** Their role here is as dataset METADATA and as weak temporal labels,
never as a prediction target.

The complement is what justifies the CV work at all: RC measured that `:2999`
exposes **no champion map coordinates** in SR, ARAM or Practice
(`allPlayers[].position` is a role string). Positions, wave state and ward
coverage are the genuine gaps. Build for those and nothing else.

## DATA HYGIENE AT SCALE

Restating section 0's correction because it drives everything here: the corpus
will be **10^3 to low 10^4 frames from TENS of matches**, all on one patch,
captured on one machine at one resolution. Under those conditions the naive
metric will be spectacular and meaningless.

### Split by MATCH, and by more than match

The video-frame leakage literature is unambiguous and the effect sizes are
large: without group splitting by source video, frames from the same clip land
in both train and val and the score is unfairly optimistic. One published
dataset analysis found 83.7 percent of validation clips had a training clip from
the same video. Frames from one League match at nearby timestamps are far more
correlated than frames from two different videos, because the map, the skins,
the camera path and the lighting are all literally identical.

Group the split on the **match id**, and then also check these axes do not leak:

| axis | why it leaks | split or stratify |
|---|---|---|
| match | same skins, same map state, same players | **hard group split** - non-negotiable |
| camera pose | the same pose at two times is near-identical background | never put two times of one pose across the split |
| skin set | a skin is a texture; learning the skin is not learning the class | stratify; report per-skin val |
| patch / build | RC measured TWO builds inside patch 16.14 alone (`.5912`, `.9266`) | hold out a whole build as a drift canary |
| map / mode | SR vs ARAM are different backgrounds entirely | separate models or explicit stratification |
| resolution | intrinsics are viewport-specific | one resolution per model, or normalise |

### Deduplicate on content, not on filename

Two instants 5 s apart with an unmoved camera differ by a handful of moving
entities on an identical background - near-duplicates by any perceptual measure.
Concretely:

1. Perceptual hash (dhash/phash) every input frame, drop exact and near-exact
   collisions. Cheap first pass, catches the accidental re-captures.
2. Embed every frame (CLIP or any pretrained backbone), cluster, and cap the
   number of frames retained per cluster. The published cluster-based
   anti-leakage method does exactly this - CLIP features, dimensionality
   reduction, DBSCAN/agglomerative clustering, then distribute whole CLUSTERS
   into train/val/test rather than frames. Adopt that, do not reinvent it.
   `lightly` (MIT, actively maintained) implements selection over embeddings if
   you do not want to hand-roll it.
3. Deduplicate on the MASK too, not just the image. Two frames whose masks are
   near-identical contribute one gradient of information regardless of how
   different the background looks.

### Pose and time sampling

Since capture time is the scarce resource, spend it on DECORRELATION rather than
density. Three rules:

- **Prefer a new match over a new instant in the same match.** A new match
  changes skins, wave layouts, ward placements, lighting and player behaviour at
  once. A new instant changes a few sprites. On a fixed time budget, breadth
  dominates depth for generalisation - this is a direct consequence of the
  grouping argument above, not a measured constant.
- **Randomise camera pose per sample**, within the h=2500-3500 working range RC
  measured. A grid of fixed poses is a recipe for a model that has memorised
  seven backgrounds.
- **Stratify sample times against the event feed**, so rare states (a fight, an
  objective contest, a cannon wave, a full-clear jungle window) are represented
  in proportion to their coaching value, not their wall-clock frequency. The
  feed makes this free.

### How many DISTINCT matches actually buy generalisation

**Do not accept a number, including from me - measure it.** No published figure
transfers to this setting. The protocol is cheap and definitive:

1. Capture N matches. Build a held-out val set of whole matches never used for
   training, and additionally a held-out BUILD.
2. Train on 2, 4, 8, 16, ... distinct matches, frames held constant per point so
   the only variable is match diversity.
3. Plot val IoU against distinct-match count. The curve flattens where extra
   matches stop paying. That inflection is the answer, and it is specific to
   this game, this class set and this camera policy.
4. Report the frame-level score AND the match-level score. A per-match score
   with a variance across held-out matches is the honest number; a pooled
   frame-level score hides that the model works on three matches and fails on
   the fourth.

The prediction worth stating so it can be falsified: because the backgrounds are
a FIXED map with a FIXED asset set, generalisation should saturate at a much
lower distinct-match count than a natural-image dataset would need, and the
residual failure mode will be **skins**, not scenes. If that is right, the
sampling policy should optimise for skin diversity specifically, which is
selectable at capture time from `allPlayers`.

## THE DIFFERENCING CAVEAT - confirmed or refuted, and where determinism BREAKS

### The operator's static-scenery note: HALF CONFIRMED, and the other half must be refuted

**Confirmed for the case it came from.** When a class is constructed by SET
SUBTRACTION of two different toggles - `characters AND NOT champions AND NOT
minions` - the residual is dominated by static scenery. RC measured it: a
6213 px blob at (5121,4735) identical to the pixel at t=100, 400 and 800, and
about **87 percent of what `characters` removes at a camp-aimed pose is world
geometry**. The two-time discriminator works and is bimodal with nothing between
(0/0/3/12 percent versus 98/100), so there is no threshold to tune. That is a
strong, correct, measured result.

**Refuted as a general rule, and this matters.** For a SINGLE toggle diff -
`minions` ON versus OFF, same pose, same instant - static scenery **cannot**
contaminate the mask, because scenery is present in both frames and cancels
exactly. The proof is already in RC's own data: the identical-render control is
**0 px**. Zero. If scenery were leaking into a single-toggle diff, the control
would not be zero.

So the precise statement is:

> Static scenery contaminates a mask built by SUBTRACTING TWO DIFFERENT ENTITY
> CLASSES, because the broader class group itself contains static props. It does
> not contaminate a single-toggle diff at a fixed pose and instant. Two-time
> differencing is the fix for the former and is unnecessary - and harmful - for
> the latter.

**Harmful how:** a two-time diff produces a CHANGE mask, not an OBJECT mask. It
marks pixels that differ between t1 and t2, which for a moving entity is the
UNION of where it was and where it is, minus the intersection. Feeding that to a
segmentation trainer as if it were an object mask teaches the model a
motion-shaped ghost. **Never put a two-time diff into the training corpus.** Use
it where RC used it: as an offline discriminator to decide whether a residual
blob is a mover, and hence whether that blob's SINGLE-TOGGLE mask deserves a
label. Discriminator, not supervision.

### Alpha, threshold and anti-aliased edges

RC used absdiff over a threshold of 30. At a class boundary the rendered pixel
is a BLEND of the entity and what is behind it, so the diff magnitude ramps
smoothly from full to zero across a 1-2 px ring. Any hard threshold therefore
either erodes or dilates the mask by about a pixel, systematically, everywhere.
For a 25-30 px ward marker that is a several-percent area error on every single
training sample - a consistent bias, which is exactly the kind a model learns
perfectly.

Three handlings, in increasing order of correctness:

1. **Ignore-band (recommended, cheap).** Threshold at two levels: high (clearly
   class) and low (clearly background). Everything between becomes an
   **ignore-index** pixel excluded from the loss. Every serious semantic-seg
   pipeline supports this natively (Cityscapes convention, MMSeg
   `ignore_index`, smp via a mask). It removes the bias instead of choosing a
   direction for it.
2. **Soft targets.** Keep the normalised absdiff magnitude as an alpha matte and
   train against soft labels with a soft Dice. Strictly more information;
   slightly more plumbing.
3. Post-hoc morphological correction. Do not - it hard-codes a guess.

### Two contamination sources RC has not yet named

- **Shading and shadows.** Removing an entity also removes the shadow it casts
  and any ambient-occlusion it contributed. Those pixels enter the diff, so the
  mask is class pixels UNION class-caused shading change. For a foot point this
  can drag the blob bottom into the shadow and bias the ground contact.
  Detection: shadow deltas are LOW-magnitude, so the ignore-band above partly
  suppresses them already. Worth one measurement - render a lone unit over flat
  ground and check whether the diff extends past its silhouette.
- **Overhead markers.** Already covered under the domain-gap rules, but it
  belongs here too: toggling a class also toggles its health bars, drawn ABOVE.
  RC saw this on wards. Turn `healthBar*` off in both frames or your masks have
  a stalk.

### Where bit-determinism BREAKS

RC measured 0 px on identical paused renders including with particles on. That
is the strongest possible result for the paused case, and the mechanism is
clear: paused freezes the simulation, so particle systems, animation blend
trees and floating text are all frozen too. Do not generalise it further than
that measurement supports. The known and suspected breakers:

| mechanism | risk here | status |
|---|---|---|
| **The one-time settle after a seek or camera move** | **REAL and MEASURED** - a constant ~34954 px added to every diff until drained | RC measured it. The mandated fix (warm up with the SAME toggle, assert RESTORED-vs-base == 0, two round-trips after a seek plus 2.5 s) is the single most important line in the capture harness |
| Temporal AA / motion-vector accumulation | would make frame N depend on frame N-1, breaking pairwise diffs even when paused | UNVERIFIED whether the League renderer uses TAA. RC's 0 px control is evidence against it MATTERING at these poses, but that is one pose |
| Animated/scrolling textures (water, river, lava, banners) | would make identical requests differ | UNVERIFIED. Frozen under pause is the likely explanation for the 0 px, but the river was not specifically framed |
| Particle RNG seeded from wall clock or frame counter | classic mask corruptor | UNVERIFIED in general, but RC measured 0 px WITH particles on, which is direct evidence against it for the paused case |
| Dynamic resolution scaling / adaptive quality | changes sampling between the two renders | UNVERIFIED. Pin every graphics setting and never change them mid-corpus |
| GPU driver or DirectX version change | silently shifts the render mid-corpus | Pin, and record the driver version in each frame's metadata |
| Window occlusion, resize, DPI change | RC measured the capture path is a FULL-SCREEN grab: anything covering the window is captured instead of it | REAL - T4 is attended and exclusive today |

**The hygiene rule that makes all of this survivable: record the determinism
receipt with every single sample.** Store, per frame, the identical-render
control value, the RESTORED-vs-base value, the toggle set, the camera pose, the
game build, the driver version and the resolution. Then a corrupted subset can
be EXCISED later by query instead of poisoning the corpus invisibly. RC has
already been bitten once by exactly this - the 11694 px wave figure and the
13-blob ward figure were both taken before the warm-up rule existed and both had
to be re-measured. A corpus with no per-frame receipt cannot be repaired; it can
only be thrown away.

### The occlusion escape, with a Vanguard verdict

RC records the `PrintWindow` path as UNMEASURED. Two findings:

- `PrintWindow` with `PW_RENDERFULLCONTENT` is documented as Windows 8.1+, and
  DirectX applications in EXCLUSIVE fullscreen commonly return black; borderless
  windowed is what makes window-directed capture work at all. So the escape is
  conditional on the client running borderless, not exclusive fullscreen.
- **The better escape is the Windows Graphics Capture API**
  (`Windows.Graphics.Capture`, `Direct3D11CaptureFramePool`,
  `GraphicsCaptureItem`). It is a first-party OS API that acquires frames from a
  specific application window. It involves **no hooking and no injection**, so
  it is clean under the Vanguard constraint. Creating a `GraphicsCaptureItem`
  directly from an HWND without the interactive picker uses
  `IGraphicsCaptureItemInterop::CreateForWindow`, which is the path OBS's WGC
  window capture takes - **UNVERIFIED by direct fetch this session**, flagged as
  such.

**Vanguard flag, and it is a sharp one:** OBS is installed on Legion, and OBS
has two capture modes that are NOT equivalent here. **"Game Capture" injects
`graphics-hook64.dll` into the game process - that is injection and hooking, and
it is BANNED under this constraint** even though it is widely whitelisted in
practice. **"Window Capture (WGC)" and "Display Capture" do not inject and are
permitted.** If anyone wires OBS into the capture harness, the mode selection is
a compliance decision, not a performance one.

Everything else proposed in this document - HTTPS to `127.0.0.1:2999`,
screen or window capture, offline training - is external observation and touches
no banned technique.

## SMALL-OBJECT AND IMBALANCE NOTES

### The objects are not actually tiny, IF you control the camera - and that is a trap

From RC's measurements at h=3500: minion blobs about 680 px each (4787 px / 7
blobs), ward markers 500-814 px, champions failing at h=6000 with about 340 px.
A 680 px blob is roughly 26x26 - small, but comfortably above the tiny-object
regime. Camera height IS the object-scale knob and RC already proved it is a
detection parameter.

The trap: **you control camera height at CAPTURE time and you do not control it
at INFERENCE time.** If the live locked camera sits higher than 3500, then
training at a convenient height produces a model that never sees the scale it
must work at. Measure the live camera's effective height FIRST and capture at
that height, even if detection is harder there. Optimising the training corpus
for easy detection is optimising the wrong objective.

The genuinely tiny targets are minimap icons, and the recommendation there is
not a detector at all - fixed-size circular portraits on a fixed background are
template matching with a deterministic answer.

### Resolution and stride - the failure that looks like a model problem

RC captures at 2560x1440. The reflex is to resize to 640 for training. Do the
arithmetic: 4x downsample turns a 26 px ward into 6.5 px, and a P3 head at
stride 8 has ONE feature cell covering it. That is not a hard detection problem,
it is an impossible one, and it will present as "the model cannot see wards"
rather than "we destroyed the signal in the dataloader".

Three fixes, in order of preference:

1. **Tile, do not resize.** SAHI (MIT, 0.12.2, actively maintained, integrates
   with torchvision / Detectron2 / MMDetection / Ultralytics / RT-DETR) is the
   off-the-shelf implementation of slicing-aided inference and fine-tuning. The
   published gains for small objects are substantial and the technique applies
   on top of any detector.
2. **Add a P2 head** (stride 4) if you keep a single-shot detector.
3. **For the semantic-seg primary, keep the native resolution and use a
   high-resolution decoder.** Semantic seg sidesteps the anchor problem
   entirely, which is a further argument for it as the primary consumer.

### Assignment, if a detection or instance head is used

IoU is highly sensitive to location deviation for small boxes - a few pixels of
shift collapses IoU to zero, which corrupts label assignment in anchor-based
detectors. The established fixes model boxes as 2D Gaussians and replace IoU in
the assigner:

- **NWD** (Normalized Wasserstein Distance) plus ranking-based assignment - can
  be dropped into the assigner, the NMS and the loss of any anchor-based
  detector in place of IoU.
- **RFLA** - Gaussian receptive-field label assignment via KL divergence between
  Gaussians.

Neither is needed if the primary is semantic segmentation. Both become relevant
the moment a champion instance head or a minimap detector is trained. Note this
is the second reason to prefer semantic seg for the bulk of the classes: it has
no assigner to get wrong.

### Foreground imbalance, and the loss that actually matters

RC measured the minion class at **0.317 percent of the frame** in the original
run (lower post-warm-up). Wards will be far below that. Under a plain
cross-entropy loss a segmenter reaches 99.7 percent pixel accuracy by predicting
all background, and the training curve looks healthy while the model has learned
nothing.

- **Never report pixel accuracy.** Report per-class IoU and per-class recall,
  and report the rare classes separately from the common ones.
- **Region-based or compound losses, not plain CE.** Dice optimises the
  overlap directly and is more sensitive to minority regions; Tversky adds
  tunable false-positive/false-negative weighting; Focal Tversky combines the
  Tversky index with a focal term and is specifically aimed at class imbalance
  AND small structures. The published comparisons are consistent that plain
  Dice and plain Focal both degrade on the smallest structures while Focal
  Tversky is designed for exactly that intersection. Start with
  weighted-CE + Dice as the compound baseline and try Focal Tversky as the
  first variation. smp ships Dice, Focal and Tversky losses directly.
- **Oversample frames that contain the rare class.** Frame-level selection is
  free here because the mask tells you the class is present before you train.
  Curate a sampler that guarantees a minimum ward-positive fraction per batch.
- **Class-balanced capture beats class-balanced loss.** Since sampling is under
  our control, aim the camera at ward-dense and objective-dense regions
  deliberately, instead of sampling uniformly and then fighting a 1000:1 ratio
  in the loss. This is the advantage of a synthetic corpus and it is normally
  unavailable; use it.

## ASSEMBLY ORDER

Ordered so a failure kills the next stage cheaply, and so the cheapest real
value lands first.

**Stage 0 - two probes, hours, before any model exists.**
- **Probe A: does `outlineSelect` / `outlineHover` isolate a SINGLE entity?**
  This is the highest-leverage unrun experiment in the document. Yes moves the
  whole plan to instance segmentation for every class. No locks in semantic
  segmentation. One afternoon.
- **Probe B: HUD region masks via `interface*` diffs, and auto-generate
  `data/vision_regions.json`.** Zero model, ships value into an existing RC
  subsystem immediately, and validates the capture harness end to end. Do this
  first regardless of what happens to the rest.

**Stage 1 - capture harness, and it must be right before it is fast.**
Mandatory from commit one: warm up with the SAME toggle; assert
RESTORED-vs-base == 0 and DISCARD anything else; render the INPUT with
live-realistic settings and diff only the target toggle; `healthBar*` off in
both frames when a body mask is wanted; camera height matched to the LIVE
camera; and a per-frame determinism receipt written alongside every sample
(control value, RESTORED value, toggles, pose, build, driver, resolution).
Also snapshot `allgamedata` at every instant and the full event list once per
replay. A harness without the receipt produces a corpus that cannot be repaired.

**Stage 2 - measure the live camera and the domain gap before capturing at
scale.** Determine the live locked-camera height and viewport, and confirm the
target objects are separable at THAT height. If they are not, the live model is
not viable at that camera and the finding is worth more than a corpus.

**Stage 3 - smallest useful corpus, one class, one honest split.**
Minions only. Tens of matches, match-grouped split, a held-out BUILD, perceptual
dedup, embedding-cluster split. Train smp (MIT) multi-class semantic seg at
native resolution with weighted-CE + Dice and an ignore-band on the AA halo.
Success criterion is NOT IoU - it is the end-to-end one RC already has:
mask -> connected components -> foot point -> `screen_to_map`, scored against
the mid-lane axis, versus the ~76 map units the toggle diff itself achieves. The
model has to be compared to the instrument it is distilling, not to a COCO
number.

**Stage 4 - the distinct-match saturation curve.** Train on 2 / 4 / 8 / 16
distinct matches at constant frame count. Report per-match val variance. This
tells you whether stage 5 is worth the wall clock, and nothing else does.

**Stage 5 - add classes, in value order.** Wards next (fog-on means allied wards
only - be explicit that this is the live-achievable target). Then champions,
where instance segmentation via RF-DETR-Seg (Apache-2.0) is justified by the
free `screenPositionBottom` instance-and-identity seed, and where the payoff is
real because `:2999` gives no live coordinates at all.

**Stage 6 - temporal derivations on top, never inside, the model.** Push
direction, freeze/slow-push classification, over-extension, fight windows and
objective contests are computed from a SEQUENCE of per-frame model outputs plus
the event feed. They are not segmentation targets and must not be trained as
such.

**Never build:** anything that re-derives gold, CS, items, levels, KDA or the
event feed. All free live at `:2999`.

## UNVERIFIED LIST

1. Whether `outlineSelect` / `outlineHover` can be driven to isolate a single
   entity in a replay. Untested; decides the architecture tier.
2. Whether the League renderer uses temporal AA or any frame-to-frame
   accumulation. RC's 0 px paused control is evidence it does not matter at the
   poses tested; it is not proof it never matters.
3. Whether animated textures (river, water, banners) advance while paused. Not
   specifically framed in any RC experiment.
4. Whether particle systems are seeded per-frame. RC measured 0 px with
   particles ON, which is strong evidence against, for the paused case only.
5. Whether removing an entity also removes its shadow / AO contribution into the
   diff. Named here; not measured.
6. Whether ward markers differ visually by ward TYPE (stealth / control /
   trinket / farsight). RC's near-identical blob areas suggest fixed-size
   markers.
7. Whether the live SR HUD renders ENEMY ability or summoner cooldowns anywhere.
   If not, that target is dead independent of any detector.
8. The live locked-camera effective height and viewport, versus the h=2500-3500
   working range RC measured in the replay fps camera.
9. `IGraphicsCaptureItemInterop::CreateForWindow` as the non-picker route to a
   `GraphicsCaptureItem` from an HWND. Believed to be the OBS WGC path; not
   fetched from Microsoft documentation this session.
10. Whether `PrintWindow` with `PW_RENDERFULLCONTENT` captures THIS client
    specifically, and whether the client runs borderless or exclusive
    fullscreen. Exclusive fullscreen commonly returns black.
11. Whether Ultralytics' claim that AGPL-3.0 propagates to trained WEIGHTS (not
    just code) is legally enforceable. Not a question this document can answer;
    the engineering mitigation (RF-DETR / smp) makes it moot.
12. RF-DETR-Seg's exact fine-tuning dataset format. COCO is strongly implied by
    the repo but was not confirmed from the training docs.
13. Detectron2's real support level. Repo pushed 2026-07-24 but the last tagged
    release is v0.6 from 2021-11-15; install-from-git is required.
14. Whether mmcv / MMDetection still install cleanly against a current PyTorch.
    The whole OpenMMLab stack last pushed mid-2024.
15. Every generalisation number in the DATA HYGIENE section. No distinct-match
    count is asserted; the saturation protocol is given precisely so a number
    can be measured rather than guessed.
16. Riot acceptable-use for bulk replay harvesting (already RC's B13, still
    open) - it gates the corpus, not the training pipeline.
