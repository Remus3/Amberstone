# CV slice 3 - detectors and cross-frame tracking

Authored 2026-07-28 for Riot Commander (Legion, Windows, sub-100ms budget).
Scope: detector shortlist with licences, the classical-vs-neural adjudication
per target, and whether tracking is needed at all.

**Headline position, stated up front so the tables can be read against it:**

1. For every target on the priority list except one, a neural detector is the
   WRONG tool, and I can show the numbers on RC's own machine.
2. The one place a net earns its keep is the main-viewport champion/entity
   segmentation, and even there the replay-render toggle-diff already beats it
   (`docs/REPLAY_T4_FRAME_CV.md`, measured 2026-07-26).
3. Minimap IDENTITY - the thing RC previously declared unrecoverable - is
   recoverable, and the lever is NOT a neural net. It is masking the team-colour
   ring out of the correlation. Measured below: 27px icons go from 93.3 percent
   top-1 to 100 percent, with the nearest-confuser margin tripling from 0.212 to
   0.674. Section "CLASSICAL vs NEURAL PER TARGET" row 2 carries the argument.
4. Tracking (ByteTrack / OC-SORT / BoT-SORT) is NOT needed. Argument in its own
   section. Short form: RC does not have a data-association problem, it has a
   10-way assignment problem against a known roster with an authoritative event
   feed as a side channel, and that is a Hungarian solve over a 10x10 matrix,
   not a MOT tracker.

---

## MEASUREMENT PROVENANCE

Two classes of number appear below and they are NOT interchangeable.

- **MEASURED (me, Legion, 2026-07-28)** - I ran it on this machine this session.
  Marked `[M]`. Hardware: Legion, Python 3.14, cv2 5.0.0, numpy 2.5.0, CPU only.
- **CLAIMED (vendor / paper)** - taken from a repo README, model card, or paper.
  I did not reproduce any of them. Marked `[C]`. Every third-party latency and
  mAP figure in the DETECTOR TABLE is `[C]`. Treat them as marketing-adjacent:
  they are almost all TensorRT FP16 batch-1 on a datacentre T4, which is not
  RC's deployment and not RC's contention profile.

**Runtime dependency probe `[M]`:** on the RC Python 3.14 runtime today,
`cv2` 5.0.0, `numpy` 2.5.0, `PIL` 12.3.0 and `pytesseract` 0.3.13 are all
PRESENT. `onnxruntime` and `torch` are BOTH ABSENT. This is a material cost line
against every neural option: RC currently ships zero ML inference dependencies,
and adding one is a 300MB (onnxruntime-gpu) to 2.5GB (torch+CUDA) footprint on a
machine that is simultaneously running League, Vanguard, OBS and the RC stack.
Note also that `docs/OBS_CV_MINIMAP_PLAN.md:39` still claims "opencv is NOT
installed in the Python314 runtime" - that line is STALE, cv2 is installed.

---

## DETECTOR TABLE

Licence is the column that decides this, so it leads.

| Model | Version / date | Licence | Weights licence if different | mAP (COCO val, AP50:95) | Latency | Verified? |
|---|---|---|---|---|---|---|
| **YOLOv5** | Ultralytics, relicensed 2023 | **AGPL-3.0** | same | n/a here | n/a | licence `[C]` high confidence |
| **YOLOv8** | Ultralytics 2023 | **AGPL-3.0** | same | - | - | licence `[C]` |
| **YOLO11** | Ultralytics 2024 | **AGPL-3.0** | same | - | - | licence `[C]` |
| **YOLOv12** | THU-MIG, Feb 2025, NeurIPS 2025 | **AGPL-3.0** | same | N 40.6 | 1.64 ms T4 TRT FP16 | `[C]` |
| **YOLOv13** | 2025 | **AGPL-3.0** | same | N 41.6 | 1.97 ms T4 | `[C]`, secondary source, weaker |
| **YOLO26** | Ultralytics, Sept 2025 | **AGPL-3.0** + Enterprise | same | n 40.9 | ~1.7 ms T4 | `[C]`, secondary source |
| **YOLOv7** | Academia Sinica, 2022 | **GPL-3.0** | same | - | - | `[C]` |
| **YOLOv9** | WongKinYiu, 2024 | **GPL-3.0** | same | - | - | `[C]` |
| **YOLOv6** | Meituan, 2022 | **GPL-3.0** | same | - | - | `[C]` |
| **YOLOv10** | THU, 2024 | **AGPL-3.0** | same | N 38.5 | ~1.7 ms T4 | `[C]` |
| **YOLOX** | Megvii, 2021 | **Apache-2.0** | Apache-2.0 | - | - | `[C]`, LICENSE file seen |
| **YOLO-NAS** | Deci, 2023 | Apache-2.0 (framework) | **NON-COMMERCIAL** custom Deci licence on the pretrained weights | - | - | `[C]`, LICENSE.YOLONAS.md |
| **RTMDet** | OpenMMLab, 2022 | **Apache-2.0** | Apache-2.0 | tiny 41.1 (4.8M params); x 52.6 | "300+ FPS on RTX 3090" | `[C]` |
| **RT-DETR / v2** | Baidu + lyuwenyu, CVPR 2024 | **Apache-2.0** | Apache-2.0 | v2-S 48.1; L -; X - | S 217 FPS, L 114 FPS, X 74 FPS on T4 | `[C]` |
| **D-FINE** | USTC, Oct 2024, ICLR 2025 Spotlight | **Apache-2.0** | Apache-2.0 (repo does not separate them) | N 42.8 / S 48.5 / M 52.3 / L 54.0 / X 55.8 | N 2.12 / S 3.49 / M 5.62 / L 8.07 / X 12.89 ms, T4 TRT10.4 FP16 bs1 | `[C]`, best-documented of the set |
| **DEIM** (training recipe over D-FINE/RT-DETR) | Intellindust, Dec 2024, CVPR 2025 | **Apache-2.0** | Apache-2.0 | DEIM-D-FINE-L 54.7 / X 56.5 | 124 / 78 FPS T4 | `[C]` |
| **RF-DETR** | Roboflow, Mar 2025, ICLR 2026 | **Apache-2.0** (Nano..Large) | **PML 1.0** on XL / 2XL | L 56.5; 2XL 60.1 | Nano 2.3 ms; L 6.8 ms; 2XL 17.2 ms | `[C]` |

### The AGPL problem, stated plainly

**AGPL-3.0 is disqualifying for RC if RC is ever a product.** Ultralytics is
explicit: compliance under AGPL-3.0 means publicly releasing the complete
corresponding source of the ENTIRE derivative work - the larger application,
modifications, scripts, config files, and where applicable the model weights.
An Enterprise licence is required to use Ultralytics YOLO without open-sourcing
your whole project.

Three things make this worse than it first looks for RC specifically:

- **The network clause bites.** RC serves a dashboard over HTTPS on `:8888` and
  a DS server on `:8893`. AGPL section 13 is triggered by network interaction,
  not distribution. Even a "it only runs on my machine" posture stops being
  clearly safe the moment another user's browser talks to that port. RC's own
  architecture (a local HTTP server as the primary UI) is the exact shape AGPL
  was written to capture.
- **It is viral across the whole repo, not the CV module.** Importing
  `ultralytics` from `core/` would put the AGPL obligation on Daemon Slayer, the
  coaches, the dashboard, and the DS Share package.
- **The AGPL family is most of the YOLO line.** v5, v8, v11, v12, v13, v10, 26.
  The GPL-3.0 ones (v6, v7, v9) are only marginally better: still copyleft, just
  without the network clause.

**Practical consequence: if a net is used at all, it must come from the
Apache-2.0 column.** That is RTMDet, RT-DETR / RT-DETRv2, D-FINE, DEIM, YOLOX,
and RF-DETR Nano-through-Large. **YOLO-NAS is a trap** - the framework is
Apache-2.0 but the pretrained weights carry a non-commercial Deci licence, so
the useful half is not free. **RF-DETR XL / 2XL is the same trap** at a
different tier (PML 1.0).

**If a net is needed, the recommendation is D-FINE-N or RTMDet-tiny.** D-FINE
has the cleanest licence-plus-documented-latency combination in the table
(Apache-2.0, 42.8 AP at a claimed 2.12 ms, 4M params). RTMDet-tiny is the
fallback if the DETR-style decoder proves awkward to export. Both are
fine-tuning targets, not off-the-shelf: COCO classes are irrelevant to League.

**Every latency figure above is a T4 with TensorRT, unloaded.** RC's GPU is
simultaneously rendering League. Nobody in the sources measured inference under
game contention, and it is the only number that would actually matter. Marked
UNVERIFIED below.

---

## CLASSICAL vs NEURAL PER TARGET

This is the section that answers the question that matters most.

### The measurements the verdicts rest on

**(a) Classical latency, RC's own code, RC's own atlas `[M]`:**

| operation | input | latency |
|---|---|---|
| `vision_template_match.match_icon`, roster of 10 | 32x32 RGB crop | **0.94 ms** |
| `vision_template_match.match_icon`, full 173-champion catalog | 32x32 RGB crop | 16.0 ms |
| `vision_atlas_precompute.dhash` | 32x32 grey crop | **0.186 ms** |
| `minimap_blob_detect.detect_team_dots`, synthetic | 416x416 | 2.54 ms |
| `minimap_blob_detect.detect_team_dots`, REAL corpus frame | 416x416 | 11.0 - 19.2 ms |

A full minimap pass - blob detect plus roster-scoped identity on up to 10 dots -
is **19 + (10 x 0.94) = ~28 ms, on CPU, with zero GPU and zero new
dependencies.** The sub-100ms budget is met with 70ms of headroom. Note the
173-catalog number (16 ms) is 17x the roster-scoped number (0.94 ms): **scoping
the candidate set to the live 10-champion roster is worth more than any model
choice**, and RC already has that plumbing (`_candidate_stems`, `_live_roster`).

**(b) Real icon size, measured on RC's real corpus frames `[M]`.** Using
`minimap_geometry.compute_minimap_rect(1.62, False, 2560, 1440)` -> rect
416x416 at (2134, 1014), applied to
`data/vision_calib_reference/*MinimapScale_1.6200*.jpg`:

    top blob areas 500 - 1200 px  =>  equivalent diameters ~25 - 39 px

So real champion icons at RC's live settings are **25 to 39 px across**. This is
not an estimate carried forward from a memory file; it is off the frames on
disk. It matters because accuracy is a steep function of exactly this number.

**(c) Identity accuracy vs icon size, modelled minimap render `[M]`.** I
composited each champion icon as the game draws it - circular crop of the
portrait, a 3px team-colour ring, over a randomised dark terrain background,
with an optional HP-bar occlusion strip - and scored roster-of-10 top-1 over 150
trials per cell:

| icon px | occlusion | full-square correlation (what RC does now) | ring-masked inner disc | margin, before -> after |
|---|---|---|---|---|
| 20 | 0 | 79.3% | **100.0%** | 0.154 -> 0.587 |
| 20 | 35% | 57.3% | 86.0% | 0.097 -> 0.224 |
| **27** | 0 | 93.3% | **100.0%** | 0.212 -> **0.674** |
| **27** | 20% | 98.0% | **100.0%** | 0.204 -> 0.545 |
| **27** | 35% | 87.3% | 97.3% | 0.136 -> 0.312 |
| 32 | 0 | 98.7% | 100.0% | 0.255 -> 0.675 |
| 32 | 35% | 89.3% | 98.0% | 0.134 -> 0.301 |
| 40 | 35% | 96.0% | 99.3% | 0.175 -> 0.334 |

**The single change is masking the outer annulus and the square corners out of
the Pearson correlation.** Nothing neural. Nothing retrained. The ring is a
KNOWN, FIXED, TEAM-COLOURED artifact at a KNOWN radius, and including it in the
correlation was injecting a large constant signal identical across all ten
candidates, which is precisely what destroys a nearest-confuser margin. RC's
`vision_template_match._USE_CIRCLE_MASK` is `False` today (line 75) and
`_mask()` returns a full 255 square (line 214). The circular-mask path already
exists in the code and is switched off.

### The per-target table

| # | Target | Classical sufficient? | Verdict and why |
|---|---|---|---|
| 1 | **Champion positions - minimap** | **YES, already 90% shipped** | `minimap_blob_detect` finds the dots today at 11-19 ms `[M]`. The count problem is already fixed (`champ_min_px` + `max_per_team`, live-verified 2026-07-13). **CLASSICAL WINS.** A net would need a labelled per-patch dataset, a GPU, a new 300MB-2.5GB dependency, and would still be solving a problem that a saturation threshold solves in 19 ms. |
| 2 | **Champion IDENTITY - minimap** | **YES, and this reverses RC's prior conclusion** | See below - this row gets its own argument. |
| 3 | **Champion positions - main viewport** | **NO for live. Moot anyway.** | The viewport shows at most a handful of champions, occluded by terrain, effects and the HUD, at wildly varying scale. This is the one genuine detection problem. BUT: (a) `screenPositionBottom` from the replay API already gives champion screen positions for free, so the detector is redundant where it is testable (`REPLAY_T4` experiment 2); (b) the toggle-diff isolates the champion class deterministically with zero model; (c) live, positions are only needed on the minimap anyway, where row 1 answers it. **Do not build this.** |
| 4 | **Wave state / lane push direction** | **NO net needed - use the toggle diff** | `REPLAY_T4` experiment 4b, MEASURED: the `minions` render toggle isolates 4787 px across 7 blobs against a ZERO noise floor, and foot-point back-projection lands wave blobs 7 to 92 map units off the lane axis (champion radius is ~65). **Differential rendering beats any detector** because it is exact, not statistical, and needs no training set. Caveat: it is REPLAY-ONLY (requires `/replay/render`), so it does not solve live wave state. For LIVE wave state there is no classical answer and no neural answer that fits the budget - see WHERE EACH STOPS. |
| 5 | **Ward coverage** | **NO net needed - toggle diff (replay); UNSOLVED live** | `REPLAY_T4` experiment 3: `healthBarWards` diff yields ward markers in both team colours with fog off. Two calibration caveats stand (the marker is an HP bar drawn ABOVE the ward, so map positions carry a systematic offset; blob count is not ward count). Live, wards on the minimap are small fixed sprites from a set of ~4 - that is a template/dhash problem, not a detection problem. **CLASSICAL.** |
| 6 | **Enemy cooldowns from the HUD** | **YES - and it is OCR, not detection at all** | Fixed screen rect, fixed font, digits 0-9 plus a decimal. RC already ships `pytesseract` + Tesseract live `[M]` and a tiered OCR-then-Sonnet router. **A detector is categorically the wrong tool** - there is nothing to localise; the region is known. If Tesseract is unreliable on the game font, the fix is a 10-glyph digit template atlas at 0.19 ms per dhash `[M]`, not a net. **CLASSICAL, decisively.** Also note: ALLY cooldowns come free from `:2999` (ability ranks + the summoner-spell panel); only ENEMY cooldowns need pixels, and those are inferred from cast events, not read as numbers. |
| 7 | **Recall / base detection** | **YES - and mostly not CV at all** | Self-recall: the recall bar is a fixed-position fixed-art HUD element - one template match, 0.94 ms. Base detection for ANY champion: `:2999` gives exact HP/mana, and full-HP-plus-full-mana-plus-position-at-fountain is a state test, not a vision task. Enemy recall is not visible to you anyway unless you have vision, in which case the minimap dot vanishing at their fountain is the signal. **CLASSICAL / NON-CV.** |
| 8 | **Fight start and end** | **NOT CV AT ALL** | `:2999` emits `ChampionKill`, `FirstBlood`, `Multikill`, `Ace` with `EventTime`. Damage taken is derivable from HP deltas on `allPlayers` at poll rate. RC already consumes exactly this in `core/decision_detector.py` and `core/event_callouts.py`. **Any pixel-based fight detector is strictly worse than the event feed** - it would be less accurate, higher latency, and would need the fight to be on screen. **DO NOT BUILD.** |
| 9 | **Objective contest windows** | **NOT CV AT ALL** | `DragonKill`, `BaronKill`, `HeraldKill`, `TurretKilled`, `InhibKilled` all arrive on the event feed with timestamps; `core/decision_detector.py:199` already computes respawn windows from them. Contest PREDICTION needs who-is-near-the-pit, which is row 1 (minimap dots) plus a spawn timer. **Zero new CV.** |

### Row 2 in full - why minimap identity works now where it did not before

RC's memory of record (`project_zoi_minimap_reality`) says: presence is
recoverable, IDENTITY is not; colour masking cannot isolate per-champion; true
per-champion tracking "needs template-matching the champion portraits - a
dedicated CV build, flagged risky on a ~416px crop", and two Gemini passes said
do not attempt blind.

That conclusion was correct about COLOUR. It was never tested against a
ring-masked correlation. Four things are different now, and none of them is a
neural net:

1. **The prior conclusion was about colour segmentation, not template
   matching.** `minimap_blob_detect.py:16` says so in its own docstring:
   "Distinguishing champions specifically needs template matching". The negative
   result closed the colour door and explicitly left this one open. This is not
   re-litigating a settled finding; it is walking through the door the finding
   pointed at.
2. **The icons are bigger than the risk assessment assumed.** The "risky on a
   ~416px crop" framing treats 416 as the constraint. The constraint is the ICON
   diameter, and measured on real frames it is **25-39 px `[M]`**, not the ~27px
   worst case, and 32-39px is comfortably inside the working range even
   unmasked (98.7% at 32px `[M]`).
3. **The team ring is the confound, and it is removable.** Measured: masking it
   takes 27px from 93.3% to 100% and triples the margin `[M]`. The ring is a
   fixed-radius, fixed-width, known-colour annulus. This is the highest-value
   single change available anywhere in this document and it is a boolean flip
   plus a radius constant in code RC already owns
   (`vision_template_match._USE_CIRCLE_MASK`, currently `False`).
4. **The candidate set is 10, not 173.** `:2999` `allPlayers` gives the exact
   roster. `_live_roster()` already does this. 17x cheaper and dramatically
   easier `[M]`.

**What I am NOT claiming.** Every accuracy number in that table is from a
SYNTHETIC composite where the template and the ground truth derive from the same
DDragon PNG. It measures robustness to scale, ring, background and occlusion. It
does NOT measure the real domain gap. Before this ships it must be re-run
against the 12 real frames in `data/vision_calib_reference/` with hand-labelled
dot identities. I did not do that here and nobody should treat the 100 percent
as a live number. See UNVERIFIED LIST items 1 and 2.

**Where the neural net would actually be better and I am choosing against it
anyway:** a small CNN classifier over the 10-way roster would likely be more
robust to skin art, engine anti-aliasing and partial occlusion than a Pearson
correlation. That is a real advantage. It is outweighed by: a new 300MB+
dependency on a machine already running League and Vanguard, a per-patch
retraining obligation as Riot ships champions and reworks art, a labelled
dataset that does not exist, and a 0.94 ms CPU baseline that already meets
budget. **Revisit only if the real-frame validation comes back under ~90 percent
after ring-masking.** That is the trigger condition, written down so it is a
decision and not a preference.

---

## TRACKING TABLE

| Tracker | Version / date | Licence | Latency | Dependencies | Needs appearance embeddings? | Verified? |
|---|---|---|---|---|---|---|
| **ByteTrack** | ECCV 2022, FoundationVision | **MIT** | 29.6 FPS end-to-end on V100 incl. YOLOX detection | torch, YOLOX, pycocotools, cython_bbox, lap, scipy | No | licence + FPS `[C]` from repo README |
| **OC-SORT** | 2023, noahcao | **MIT** | **700 FPS for the association step alone on an i9-3.0GHz CPU** when detections are supplied; 28 FPS end-to-end on RTX 2080Ti | numpy, scipy, filterpy, lap | No | `[C]` from repo README |
| **BoT-SORT** | 2022/23, NirAharon | **MIT** | not stated in repo | as ByteTrack + optional ReID net + camera-motion compensation (OpenCV ECC/ORB) | Optional (BoT-SORT-ReID variant) | `[C]` |
| **DeepSORT** | 2017, nwojke | **GPL-3.0** | - | TensorFlow-era, plus a cosine-metric ReID net | **Yes, mandatory** | `[C]` |
| **BoxMOT** (multi-tracker library) | mikel-brostrom | **AGPL-3.0** | - | wraps all of the above | varies | `[C]` |
| Ultralytics built-in BoT-SORT / ByteTrack | - | **AGPL-3.0** (the wrapper, regardless of the upstream MIT) | - | ultralytics | - | `[C]` |

Licence notes that matter:

- The upstream trackers are permissively licensed (MIT). **The convenient
  wrappers are not.** BoxMOT is AGPL-3.0 and Ultralytics' bundled trackers are
  AGPL-3.0. Using ByteTrack via `ultralytics.track()` imports the AGPL
  obligation even though ByteTrack itself is MIT. If a tracker is ever used,
  vendor the upstream MIT association code, not the wrapper.
- **DeepSORT is GPL-3.0 and needs a ReID network.** It is the wrong choice on
  both licence and architecture grounds. Do not use it.
- OC-SORT's **700 FPS CPU association figure `[C]`** is the number that matters
  if any of this were needed: the association step is pure numpy plus a Kalman
  filter and does not need a GPU at all. That is also the number that makes the
  next section's argument, because it shows how cheap the thing is - and it is
  still not worth adding.

---

## IS TRACKING NEEDED AT ALL - the argument

**No. Take the position: do not add a MOT tracker to RC.**

### What a MOT tracker is actually for

ByteTrack, OC-SORT and BoT-SORT solve one problem: given a stream of
class-agnostic, identity-free bounding boxes from a detector, stitch them into
consistent tracks across frames when you do not know how many objects there are,
which ones are the same object, or when one leaves and another enters. Every
design decision in them follows from that: the Kalman filter exists because
object count and motion are unknown; the low-score-box association in BYTE
exists because occluded pedestrians produce weak detections; the ReID embedding
in BoT-SORT/DeepSORT exists because appearance is the only tiebreaker when two
identical-looking pedestrians cross.

**RC has none of those unknowns.**

### The four facts that dissolve the problem

**1. The cardinality is known and fixed at 10.** `:2999` `allPlayers` gives the
exact roster, every champion name, both teams. There is no "how many objects"
question, no track birth, no track death. A tracker's entire state-management
apparatus is answering a question RC already has the answer to.

**2. The identities are known a priori.** This is the decisive one. A MOT
tracker's output is "object 7 in frame N is object 7 in frame N+1" - a
RELATIVE, arbitrary label. RC does not want that. RC wants "this dot is
Thresh". A tracker cannot produce that. Only classification against a known
roster can, and once you have classification per frame, association across
frames is free - the identity IS the association. **Tracking is a workaround for
not being able to classify. RC can classify (100% top-1 at 27px ring-masked
`[M]`), so the workaround is redundant.**

**3. The correct algorithm is a 10x10 Hungarian solve, not a tracker.** Per
frame: up to 10 dots, up to 10 known champions, a cost matrix of
`(1 - identity_confidence)` optionally blended with distance from the previous
frame's position. `scipy.optimize.linear_sum_assignment` on a 10x10 matrix is
tens of microseconds and enforces the one-champion-one-dot constraint that a
greedy argmax over `score_all` currently violates. This is roughly 30 lines and
uses scipy, which the runtime already has. It is strictly better than a tracker
here because it exploits the mutual-exclusion constraint that a MOT tracker
cannot express.

**4. The event feed disambiguates the hard cases for free.** The cases where a
tracker would earn its keep are exactly the ones `:2999` already answers:
   - **Champion disappears from the minimap.** Tracker: guess whether it is
     occluded or gone. RC: check `allPlayers[i].isDead` and `respawnTimer`. If
     dead, it is not occluded, it is dead, and you know exactly when it comes
     back.
   - **Two icons overlap and one dot vanishes.** Confirmed real failure mode -
     the game itself draws only one portrait when champions coincide, so this is
     not even a detection failure, it is a RENDERING fact and NO CV of any kind
     can recover it. A tracker cannot either. What recovers it is a motion prior
     plus the knowledge that both champions are alive - i.e. carry the last known
     position forward with decaying confidence, which is 5 lines, not a library.
   - **Champion enters/leaves fog.** Tracker: track death and re-birth, with an
     ID switch on re-entry. RC: the champion is alive, it went into fog, its
     last known position is stale by N seconds. That staleness is the coaching
     signal ("enemy jungler unseen for 22s") and it is DESTROYED by a tracker
     that helpfully interpolates through the gap.

That last point deserves emphasis. **A tracker would actively harm RC's product.**
The coaching value of the minimap is knowing what you DO NOT know - which enemy
is missing and for how long. A Kalman filter's job is to paper over exactly that
gap with a plausible extrapolation. RC wants the gap preserved and measured.

### The steelman, and why it fails

The strongest case for tracking: at 2 Hz polling with 25-39px icons, a
per-frame classifier will occasionally mis-assign, and temporal smoothing would
fix it. True. But the fix is a per-champion exponential-moving-average of
identity confidence plus a position gate - not ByteTrack. A tracker brings
Kalman state, track lifecycle, IoU association, lost-track buffers and a
dependency, to deliver temporal smoothing RC can write in 30 lines against a
roster it already knows. The cost/benefit is not close.

The second steelman: main-viewport entity tracking across frames for fight
analysis. This fails on target priority - fight start/end is target 8, and
target 8 is answered by the event feed, not by pixels at all.

**Verdict: NO tracker. Build the 10x10 Hungarian assignment with an
event-feed-informed cost matrix and a decaying last-known-position prior. Zero
new dependencies (scipy is present via the existing stack), microsecond-scale,
and it produces named champions rather than arbitrary track IDs.**

---

## WHERE EACH STOPS BEING GOOD ENOUGH

Honest failure boundaries. Each of these is a real limit, not a hedge.

**Classical template matching stops when:**

- **Icon diameter drops below ~20 px.** Measured `[M]`: at 20px with 35 percent
  occlusion, ring-masked top-1 falls to 86.0 percent and the margin collapses to
  0.224. RC is safe at 25-39px today, but a user at 1920x1080 with a small
  MinimapScale would be under this floor. Mitigation is a settings check, not a
  model: RC already reads `game.cfg`, and raising MinimapScale is a legal,
  Vanguard-irrelevant client SETTING (not a client file modification).
- **Skin art diverges from the DDragon base icon.** This is the largest
  unquantified risk in the whole document. RC's atlas is 173 base champion PNGs.
  If the game draws a skin-specific minimap portrait, every match against that
  champion degrades. Community threads requesting skin-specific minimap icons
  are weak evidence that it does NOT happen by default, but that is inference,
  not measurement. UNVERIFIED item 1.
- **Occlusion exceeds ~35 percent.** Ping markers, the camera-position rectangle,
  the cursor, and overlapping icons all cut into the disc. Beyond a third of the
  icon, margins fall under 0.3 and confusion begins.
- **Riot reworks champion icon art mid-patch.** The atlas is a per-patch asset.
  This is a refresh job, cheap, but it is a standing maintenance obligation.
  Same obligation a fine-tuned net would have, only far cheaper to discharge -
  re-download DDragon icons versus re-label and retrain.

**Colour blob detection (`minimap_blob_detect`) stops when:**

- Terrain, HP bars and structures share the team colour. Already documented and
  already worked around by the size floor and per-team cap, but the cap "keeps
  top-confidence dots, not the RIGHT ones" - a known, recorded limitation.
- Ally champions render teal in some frames and blue in others depending on
  visibility state. Already documented from live frames.
- **Raw blob count on real frames is ~90 at min_px=5 `[M]`** - the signal-to-
  noise ratio before the size floor is roughly 9:1 against. The floor works, but
  it is doing heavy lifting and it is tuned, not derived.

**Differential rendering (T4 toggle-diff) stops when:**

- **It is replay-only.** It requires `/replay/render` and a paused game. It
  cannot run live at all. Wave state and ward coverage are therefore SOLVED for
  post-game review and UNSOLVED for live coaching.
- Without the warm-up round-trip it silently produces numbers inflated ~2.4x.
  Documented and fixed by an assert, but it is a sharp edge.
- Camera height is a detection parameter (working range ~2500-3500), and blob
  count is not entity count - champion masks fragment 10 blobs for 6 champions.

**A neural detector would stop when:**

- The training set goes stale. Every new champion, every art rework, every skin.
  The measured precedent is direct: DeepLeague's YOLO9000 covered only ~56 of
  ~140 champions because professional play has champion selection bias `[C]`,
  and a PandaScore SSD trained on that data "did not generalize to champions not
  present in the training dataset" `[C]`. **This is the single most important
  external data point in this document**: the exact task, attempted with nets,
  repeatedly, and the failure mode was always dataset coverage - not model
  capacity. Henry Zhu's Faster R-CNN fixed it by generating SYNTHETIC training
  data from the icon set `[C]`, which is a tacit admission that the icon set is
  the ground truth and the net is an expensive interpolator over it.
- GPU contention with League. Every cited latency is an unloaded T4. UNVERIFIED.
- The licence audit happens. AGPL on a networked dashboard is not survivable for
  a product.

**The Dota2-Vis counterpoint, stated fairly `[C]`:** YOLO11l reached 0.974
precision / 0.906 recall / 0.729 mAP50:95 on 2,477 annotated Dota 2 minimap
images, and it is the best-measured neural minimap result available. But read
the setup: **the game was configured to display players using COLOUR AND SYMBOL
icons instead of hero portraits, specifically to make the detector independent
of the hero pool and avoid retraining when new heroes ship.** They removed the
identity problem from the task in order to make the net tractable. That is a
concession, and it is the same concession RC would have to make. RC does not
have to make it, because RC has the portrait atlas and a 10-champion roster.

---

## UNVERIFIED LIST

Ranked by how much a wrong answer would cost.

1. **Does the LoL minimap draw skin-specific portraits, or always the base
   champion icon?** Load-bearing for the entire classical identity
   recommendation. Weak indirect evidence (community feature requests for
   skin-specific minimap icons) points to "base icon", but this is INFERENCE.
   Resolve by inspecting a real frame with a known skin against
   `data/icons/champions/`. Cheap - the corpus frames are already on disk.
2. **All identity accuracy figures are SYNTHETIC composites.** Template and
   ground truth share a source PNG. The real-frame number is unmeasured. Must be
   validated against the 12 frames in `data/vision_calib_reference/` with
   hand-labelled dot identities before any flip. The 100 percent figures are a
   ceiling, not a forecast.
3. **Neural inference latency under game GPU contention.** Every `[C]` latency
   is an unloaded T4 with TensorRT. Nobody measured a detector running while a
   game renders on the same GPU. If a net is ever seriously considered this must
   be measured first, not assumed from the vendor table.
4. **The ring geometry constants.** I modelled a 3px ring at radius `size/2`.
   The real ring width and radius as a fraction of icon diameter are unmeasured.
   The masking result is directionally robust (it held across 20/27/32/40 px and
   three occlusion levels) but the exact optimum shrink is not calibrated.
5. **RTMDet "300+ FPS on RTX 3090" and YOLOv13 / YOLO26 figures** come from
   secondary sources (blog aggregators), not the primary papers. Lower
   confidence than the D-FINE and RT-DETR rows, which came from repo READMEs.
6. **BoT-SORT latency is not stated anywhere I could find**, including its own
   repo. Left blank rather than guessed.
7. **Whether Tesseract is actually accurate on the League HUD font** for the
   cooldown-readout target. `pytesseract` is installed and RC has a tiered OCR
   router, but I did not measure per-field accuracy. The fallback (a 10-glyph
   digit template atlas) is cheap enough that this is low-risk either way.
8. **Vanguard posture on a fine-tuned local detector.** Nothing in this document
   proposes memory reads, injection or hooking, so nothing here is flagged. RC's
   existing GDI BitBlt / PIL ImageGrab capture is recorded as Vanguard-safe, and
   ADR-011 records that OBS must use Display Capture (WGC) because **Game
   Capture's hook injection trips Vanguard**. That constraint is a CAPTURE
   constraint and is unchanged by anything in this slice - detectors and trackers
   consume frames and are Vanguard-irrelevant. The one thing to keep flagged for
   whoever owns the capture slice: **do not adopt any capture library that hooks
   the game process**, and note that DXGI/phase_watcher capture was already
   retired under ADR-011.

---

## Sources

- [Ultralytics License](https://www.ultralytics.com/license) - AGPL-3.0 vs Enterprise
- [Ultralytics AGPL-3.0 Open Source License](https://www.ultralytics.com/legal/agpl-3-0-software-license)
- [Ultralytics YOLO26 Docs](https://docs.ultralytics.com/models/yolo26)
- [YOLOX LICENSE (Apache-2.0)](https://github.com/Megvii-BaseDetection/YOLOX/blob/main/LICENSE)
- [YOLOv6 LICENSE](https://github.com/meituan/YOLOv6/blob/main/LICENSE)
- [YOLOv9 LICENSE](https://github.com/WongKinYiu/yolov9/blob/main/LICENSE.md)
- [YOLOv12 repo](https://github.com/sunsmarterjie/yolov12) / [arXiv 2502.12524](https://arxiv.org/abs/2502.12524)
- [YOLO-NAS licence](https://github.com/Deci-AI/super-gradients/blob/master/LICENSE.YOLONAS.md)
- [RT-DETR repo + LICENSE](https://github.com/lyuwenyu/RT-DETR/blob/main/LICENSE)
- [D-FINE repo](https://github.com/Peterande/D-FINE) / [OpenReview](https://openreview.net/pdf?id=MFZjrTFE7h)
- [DEIM CVPR 2025](https://openaccess.thecvf.com/content/CVPR2025/papers/Huang_DEIM_DETR_with_Improved_Matching_for_Fast_Convergence_CVPR_2025_paper.pdf)
- [RTMDet configs + arXiv 2212.07784](https://github.com/open-mmlab/mmdetection/blob/main/configs/rtmdet/README.md)
- [RF-DETR repo](https://github.com/roboflow/rf-detr) / [Roboflow blog](https://blog.roboflow.com/rf-detr-nano-small-medium/)
- [ByteTrack repo](https://github.com/FoundationVision/ByteTrack) / [arXiv 2110.06864](https://arxiv.org/abs/2110.06864)
- [OC-SORT repo](https://github.com/noahcao/OC_SORT)
- [BoT-SORT repo](https://github.com/NirAharon/BoT-SORT)
- [deep_sort repo (GPL-3.0)](https://github.com/nwojke/deep_sort)
- [Dota2-Vis: CV for MOBA Analytics](https://arxiv.org/html/2606.26970v1)
- [PandaScore: LoL champion coordinates from the minimap](https://medium.com/pandascore-stories/league-of-legends-getting-champion-coordinates-from-the-minimap-using-deep-learning-48a49d35bb74)
- [Henry Zhu: ML with League of Legends - Minimap Detection Part 2](https://maknee.github.io/blog/2021/League-ML-Minimap-Detection2/)
- [DeepLeague](https://medium.com/@farzatv/deepleague-leveraging-computer-vision-and-deep-learning-on-the-league-of-legends-mini-map-giving-d275fd17c4e0)
- [Riot Vanguard (Wikipedia)](https://en.wikipedia.org/wiki/Riot_Vanguard)
