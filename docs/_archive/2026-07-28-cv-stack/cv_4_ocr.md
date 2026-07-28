# CV-4: OCR for HUD numerals under motion and particle effects

Slice scope: OCR engine selection for tiny fixed-rect HUD numeral crops in Riot Commander.
All latency figures below marked MEASURED were run by me on Legion on 2026-07-28.

Bench host: AMD Ryzen 7 7700X 8-Core, Windows 10 Pro 19045, Python 3.14.
Bench scripts left at `C:\Users\ADMINI~1\AppData\Local\Temp\claude\C--Riot-Commander\25c7f8e2-ed52-4b8d-8bfc-a7da8008f9b5\`
(`bench_tess.py`, `bench2.py`, `bench_rapid2.py`, `bench_tmpl2.py`).

**Honesty boundary on my own numbers:** crops are synthetic (Arial Bold white-on-dark,
rendered at the real region sizes taken from `data/vision_regions.json`). Latency is
driven by process/tensor cost and is font-independent, so the ms figures transfer to
real frames. **Accuracy figures do NOT transfer** - League renders its own typeface and
real frames carry real particles. Every accuracy claim below is a directional signal
from synthetic degradation, not a field measurement. The corpus that would settle it
already exists in the repo: `data/ocr_shadow.jsonl` via `RC_OCR_SHADOW_PATH`.

---

## 0. READ THIS FIRST - the named target does not exist

The task names "enemy cooldowns from the HUD" as the primary target. Two independent
walls make that unbuildable, and neither is an OCR problem:

1. **League does not render enemy cooldowns.** There is no official HUD or scoreboard
   element showing enemy summoner-spell or ability cooldowns. There are no pixels to
   read. (VERIFIED by web search; the entire third-party spell-tracker ecosystem
   exists precisely because the game does not show this.)
2. **Riot's third-party policy forbids it outright.** From the Riot compliance rules
   published for Overlay Platform M developers (VERIFIED, fetched 2026-07-28):
   - "Tracking of enemy summoner spells cooldowns, or facilitating players tracking
     these with timers" is forbidden.
   - "The use of Ultimate timers is strictly forbidden since this may provide an
     unfair advantage."
   - "Tracking of enemy ability cooldowns, or facilitating players tracking these with
     timers" is not permitted.
   - Also forbidden: "Notifications that dictate player action based on the current
     game state" and power-spike alerts.

   Riot's own policy page (`support-developer.riotgames.com/hc/en-us/articles/22698698001939`)
   returned HTTP 403 to WebFetch, so the Riot-primary text is UNVERIFIED by me. The
   Overlay Platform M compliance page is the Riot-approved platform's rendition of that policy and
   I treat it as authoritative enough to stop work.

**Consequence:** the only technique that would actually yield enemy cooldowns is reading
game memory, which is a Vanguard-banned technique AND a policy violation. **FLAGGED - do
not build.** No choice of OCR engine changes this. Drop the target.

The third bullet also matters for RC's product shape: the second clause ("notifications
that dictate player action based on the current game state") is close to what a live
coach does. That is a separate policy question, outside this slice, but it should be
raised.

### What survives as a legitimate OCR target

| Named target | Verdict |
|---|---|
| Enemy cooldowns from the HUD | **DEAD** - not rendered, and policy-forbidden. |
| Recall / base detection numerals | **NO NUMERAL EXISTS.** Recall is a channel bar with no digits. The only numeral in that path is the game clock, which `:2999` gives as `gameData.gameTime`. OCR contributes nothing here. |
| Objective-contest numerals | **LIVE, and the single best OCR target in RC.** Dragon/Baron spawn countdowns render as numerals in the top HUD bar and `:2999` exposes no objective timer of any kind (VERIFIED against the Live Client Data API field list). This is a real API gap that pixels can close. |

Whether objective/jungle timers are explicitly permitted is UNVERIFIED - the Overlay Platform M
page lists forbidden items and does not name objective timers either way, and jungle
timers are widely shipped by approved overlays. Confirm before building.

### Scope-rule enforcement against `:2999`

VERIFIED against the Live Client Data API field list: `allPlayers[]` carries
`championName, isBot, isDead, items, level, position, rawChampionName, respawnTimer,
runes, scores, skinID, summonerName, summonerSpells, team`; `activePlayer` carries
`abilities, championStats, currentGold, fullRunes, level`; plus `events` and `gameData`.
**No cooldown field and no objective-timer field exists anywhere in it.**

So `:2999` already gives, exactly and free: gold, CS, KDA, level (every player), game
clock, own HP/mana, items, and **`respawnTimer` for every player including enemies**.

RC currently OCRs 8 of these 21 calibrated regions anyway. See section 4.

---

## 1. OCR ENGINE TABLE

Per-crop, on a 40x20 crop, which is the actual unit of work here.

| Engine | Version | Licence | Per-crop latency (40x20) | 25-crop atlas | GPU? | Model size | Verified? |
|---|---|---|---|---|---|---|---|
| **Tesseract + pytesseract (RC today)** | 5.4.0.20240606 installed on Legion; 5.5.1 is current upstream | Apache-2.0 | **170.0 ms** mean (p90 172.4, min 167.1) | **3242 ms** (8-thread pool) | No. CPU only, no GPU build. | ~15-30 MB `eng.traineddata` | **MEASURED** |
| **RapidOCR (ONNXRuntime), rec-only** | `rapidocr-onnxruntime` 1.2.3 (pip resolved; see friction) - PP-OCRv3 rec | Apache-2.0 | **2.6 - 3.4 ms** (median 2.6-3.4) | **41.2 ms batched** (1.65 ms/crop); 82.4 ms sequential | Optional. On Legion, `onnxruntime` exposed only `['AzureExecutionProvider','CPUExecutionProvider']` - **CPU-only as installed**, which is what you want next to a running game. | 10.7 MB rec + 2.4 MB det + 0.6 MB cls | **MEASURED** |
| **PaddleOCR** | 3.7.0 (2026-06-11) | Apache-2.0 | Not measured by me. Vendor table: PP-OCRv5_mobile_rec **21.20 ms** CPU / 5.43 ms GPU per text-line; PP-OCRv5_server_rec 31.21 ms CPU | not measured | Yes (CUDA via paddlepaddle-gpu) | 16 MB mobile / 81 MB server rec | Version+licence VERIFIED; latency VENDOR-REPORTED on Xeon Gold 6271C / Tesla T4, **not** my hardware |
| **Fixed-font template matcher** (numpy NCC, 12 glyph templates, no engine) | n/a - ~120 lines | n/a | **0.100 ms** mean (100-263 us) | **2.51 ms** | No, and does not want one | ~12 KB of templates | **MEASURED** |

Supporting measurements, all MEASURED:

- Tesseract's 170 ms is a **fixed per-invocation cost, not recognition work**:
  - bare `tesseract.exe --version` spawn: **5.8 ms**
  - full pytesseract path on an **8x8 blank** image: **171.3 ms**
  - So ~165 ms is per-call LSTM `traineddata` load and temp-file I/O, paid again on
    every single crop. The crop content is free.
- Latency is flat across crop size and config: 40x20 = 170.0, 110x32 = 174.1,
  48x44 = 171.2, 60x90 = 171.5 ms. `--psm 7/8/10/13` all 169-175 ms.
  `--oem 1` vs `--oem 3`: 170.1 vs 174.9 ms. **`tessedit_char_whitelist` is free**
  (171.2 with vs 171.1 without) - it buys accuracy at zero latency cost, so RC should
  keep using it everywhere, but it cannot help the latency problem.
- Tesseract's thread pool scales badly, because each worker is a separate process
  loading its own copy of the model: 1 crop 171 ms, 5 crops 443 ms, 10 crops 1303 ms,
  **25 crops 3242 ms**. This is superlinear degradation, not amortisation.
- RapidOCR batching works properly (one tensor, `rec_batch_num=6`): 25 crops in
  **41.2 ms** total, i.e. 1.65 ms/crop, a further 2x over sequential.
- `pytesseract.image_to_data` (needed for any confidence value) costs **199.4 ms**,
  a further ~28 ms over `image_to_string`.

### Is a full-page OCR engine the wrong tool for a 40x20 crop?

**Yes, and the evidence is direct.** MEASURED on RapidOCR: full detect+classify+recognise
pipeline on the same 40x20 crop is **6.2 ms** versus **3.4 ms** rec-only - roughly half
the budget burned running a text *detector* over a rectangle whose location you already
calibrated. On a full 1920x1080 frame the same pipeline costs **248 ms**.

The rule that falls out: **for a calibrated fixed rect, never call the engine's top-level
entry point - call the recogniser directly.** In RapidOCR that is
`RapidOCR().text_recognizer([crop_ndarray])`. Note the trap I hit: passing
`use_det=False` to the top-level `__call__` did **not** reliably suppress detection - the
engine's `min_height=30` / `width_height_ratio=8` heuristics re-enabled it for a 110x32
crop, producing a spurious 206 ms reading that vanished (to 3.4 ms) once I drove
`text_recognizer` directly. Anyone repeating this benchmark will hit the same artefact.

And the same logic taken one step further is why the template matcher wins outright: a
CTC sequence model over a 320-wide padded tensor is still enormous overkill for
"which of 12 glyphs is this". 0.100 ms vs 2.6 ms is another 26x.

### Windows install friction

- **Tesseract**: already installed and working. Needs a separate non-pip `.exe`
  install; RC handles path resolution via `RC_TESSERACT_CMD` with a hardcoded fallback.
  Lowest friction because it is already paid for.
- **RapidOCR**: `pip install rapidocr-onnxruntime` worked first try into a clean venv,
  models bundled in the wheel (12.3 MB), **no network fetch at runtime**. **Friction
  found (MEASURED):** the current 1.4.4 release pins `Python <3.13`, so on Legion's
  Python 3.14 pip silently resolved **backwards to 1.2.3**. That is a real trap - you
  get an older PP-OCRv3 model with no warning. The newer `rapidocr` 3.x package line
  (3.9.2, 2026-07-21 per PyPI) is the actively developed one and should be checked for
  3.14 support first. Pulls in opencv-python (44 MB), onnxruntime (14 MB), numpy,
  shapely, pyclipper - about 90 MB of dependencies for a digit reader.
- **PaddleOCR**: heaviest. Requires the `paddlepaddle` framework alongside; PyPI lists
  official support only through **Python 3.13**, so Legion's 3.14 is out of band.
  Documented 2026 friction includes resolver deadlocks needing `--no-deps` workarounds,
  circular-import failures when mixing paddleocr 3.x with paddlepaddle <3.0, and missing
  `setuptools` in fresh envs. Downloads models on first run.

### Digit-only / character-restriction options

- `tessedit_char_whitelist=0123456789.:` - RC already does this per field. MEASURED
  free in latency. Keep it. Note it is honoured by the LSTM engine but is a soft
  constraint, not a hard alphabet restriction, and it did not save the decimal point
  in my tests.
- `--psm 10` (single character) is available and MEASURED at the same 170 ms, so it
  offers nothing here.
- **Fixed-font template matching** is the right-sized tool and is measured above.
- A small digit CNN (SVHN/MNIST-class, ~50 KB ONNX) is the natural upgrade from
  template matching if the templates prove brittle. Not benchmarked - but it would run
  in the same order as the template matcher, since the cost at this size is dominated by
  crop preparation, not inference. UNVERIFIED.

---

## 2. THE PARTICLE-AND-MOTION PROBLEM - what actually works

The hard part is not the glyph. It is that the background behind a semi-transparent HUD
box changes colour every frame, particles bloom over it, and a radial cooldown sweep
darkens part of the crop.

**What the evidence supports:**

1. **Max-channel extraction, not luma greyscale.** League HUD numerals are near-white
   (high in all three channels); most particle colour is saturated in one or two.
   Taking `max(R,G,B)` keeps the glyph at full strength while a saturated red or blue
   particle contributes only its own channel. RC already has the right instinct here in
   `_ocr_colored_int` and `_ocr_int_stack(channel=...)` for coloured digits, but the
   main `_preprocess` path still calls `img.convert("L")`, which is luma-weighted
   (green-heavy) and therefore *most* sensitive to exactly the green/teal particle
   families. Cheap change, likely real gain. UNVERIFIED on real frames.
2. **Adaptive threshold, not a fixed 180.** RC hardcodes `threshold=180` after an
   `autocontrast` stretch. A translucent HUD box over a bright background lifts the
   floor above 180 and the crop binarises to solid white. In my synthetic low-contrast
   case (fg 210 on bg 160) the template matcher failed outright. Otsu or a
   percentile-of-crop threshold costs microseconds and removes the magic constant.
3. **Upscaling: RC's 4x LANCZOS is nearly free and worth keeping.** MEASURED:
   `_preprocess` costs **0.122 ms**, versus the 170 ms engine call it feeds. It is
   0.07% of the budget. Note however that upscaling did **not** help RapidOCR
   (2.7 ms at 160x80 vs 3.3 ms at 40x20, same result) because the rec model resizes to
   a fixed 48-high tensor anyway - so if RC swaps engine, the 4x upscale should be
   dropped as a no-op, not carried across.
4. **Temporal median across frames is the single highest-value technique for this
   problem, and RC has none of it.** Particles and the cooldown sweep are
   *transient*; the glyph is *persistent*. Median-stacking N consecutive crops
   suppresses anything that is not stable across the window while leaving the numeral
   untouched. This is a well-established result for flicker and transient-occlusion
   removal in video (temporal median models the static scene and rejects changing
   pixels). It is also the technique that best matches this specific failure mode.
   It costs almost nothing at these crop sizes.
   The design constraint: the value being read is itself changing (a cooldown ticks
   down), so median-stack the **pixels** only over a short window (3-5 frames at the
   2 s vision cadence is already too slow - this wants the higher-rate capture path),
   or median-vote the **decoded values** with a monotonicity model. See section 3.
5. **Colour-channel isolation for known-coloured readouts** - RC already does this
   correctly (`_ocr_colored_int(channel="R"/"B")`). Keep.

**What does not work / do not bother:**
- Escalating a particle-occluded crop to Sonnet. It is the same occluded pixels, at
  ~2 s and a per-call cost, for a numeral that has already changed by the time it
  returns. Escalation is right for scene understanding, wrong for a ticking number.
- Bigger OCR models. The failure is occlusion and contrast, not model capacity.

---

## 3. REJECT PATH - confidence calibration

The brief is right that a wrong number is worse than no number. **The measured finding
is that none of the three engines' native confidence separates a correct read from an
incorrect one.** Do not build the reject path on engine confidence.

MEASURED, RapidOCR rec score on identical content under degradation:

| Crop | Read | Score |
|---|---|---|
| clean `12` | `12` | 0.576 |
| low-contrast `12` (fg 210 on bg 160) | `12` | 0.562 |
| particle overlay on `12` | `12` | 0.655 |
| cooldown-sweep wedge on `12` | `12` | 0.574 |
| uniform noise | `''` | **1e-50** |
| blank dark crop | `''` | **1e-50** |

Read that carefully: the **clean** crop scored *lower* than the particle-covered one.
The score is a near-perfect **"is there any text here"** gate (1e-50 vs 0.56-0.83, ~50
orders of magnitude of separation) and a **useless "is this read correct"** gate.

MEASURED, template-matcher NCC margin (best minus second-best correlation): correct
reads spanned 0.055-0.431 while uniform noise scored 0.119 - **overlapping**. Also
useful: my first, aspect-normalising template implementation read `4.7` as `427`,
`0.8` as `028` and `14:38` as `14238`; bottom-aligning and scaling by line height
rather than glyph height fixed all seven cases to 100% correct at the same 0.1 ms.
**Never normalise away glyph aspect ratio when the alphabet contains `.` and `:`** -
a stretched period is a digit, and `4.7` becoming `47` is a 10x error in a cooldown.

MEASURED on Tesseract: `image_to_data` returned `conf=96` on a clean `12`, at 199 ms.
Upstream tracks known unreliability in these values (tesseract issue #2746: correct
text reported at confidence 0; confidence is per-word not per-character). I did not
capture conf on a wrong read - **GAP**, worth one probe before trusting it.

Most important measured reject-path datum, and it is a Tesseract correctness result,
not a speed one:

| Glyph height | Input | Tesseract output | Parsed by `_ocr_cooldown` |
|---|---|---|---|
| 16 px | `4.7` | `4.7` | 4.7 |
| **20 px** | `4.7` | `47` | **47.0** |
| **24 px** | `4.7` | `4` | **4.0** |
| 32 px | `4.7` | `4.7` | 4.7 |
| 48 px | `4.7` | `4.7` | 4.7 |

RapidOCR read `4.7` and `0.8` correctly at 40x20. RC's `_ocr_cooldown` range-checks
`0 <= v <= 999`, so **47.0 passes and is surfaced as a 47-second cooldown**. This is
precisely the "wrong number shown mid-game" failure, reproduced (synthetically) in RC's
current shipping code path.

### The reject path that the evidence actually supports

Layer domain logic, and treat engine confidence as one weak input:

1. **Hard domain range per field**, which RC already does well - keep and tighten.
   Cooldowns specifically need a **decimal-point sanity rule**: League shows sub-10 s
   cooldowns with one decimal, so a 2-digit integer read from a crop whose glyph run
   contained 3 components should be rejected, not rounded.
2. **Monotonicity / physical-plausibility gate.** A cooldown counts *down* at 1.0 s per
   second. Any read that increases, or jumps by more than the elapsed wall time, is
   rejected without needing any confidence at all. This is the strongest available
   signal and it is free. An objective timer has the same property.
3. **Temporal N-of-M agreement.** Surface a value only when the same decoded value (or
   a value on the predicted countdown ramp) appears in at least 2 of the last 3 reads.
   This kills the isolated particle-frame garbage that no per-frame confidence catches.
4. **"Is there text" gate from the engine.** Use the RapidOCR rec score here and only
   here - measured 50-orders-of-magnitude separation makes it excellent at deciding
   "this icon is off cooldown / this region is empty". RC's `_has_text_signal`
   (MEASURED 0.021 ms) already does this job well and cheaper; keep it as the
   pre-filter and use the rec score as the confirmation.
5. **Fail to absent, never to a guess.** RC's existing "failed fields are omitted"
   contract in `read_fast_fields` is correct. Preserve it through any swap.

RC already has the instrument to calibrate all of this: the `ocr_shadow.jsonl` lane in
`core/vision_routing.py` plus `tools/ocr_shadow_report.py`. Run it against real frames
before flipping any threshold. Do not pick a number from this document.

---

## 4. RC BASELINE - keep vs swap, with the number that justifies it

### The number

RC's docstring in `core/vision_tesseract.py` claims OCR "drops latency to ~50ms+free
per field". **MEASURED on Legion: 170 ms per field, and 3242 ms for a 25-region pass.**
The docstring is off by 3.4x per field and the atlas-scale cost has never been stated.
Against a sub-100 ms target, RC's current OCR tier misses by **32x on a single crop**.

Swap justification, per crop and for RC's real 21-region atlas:

| Path | Per crop | 21-25 region pass | vs today |
|---|---|---|---|
| Tesseract (today) | 170.0 ms | 3242 ms | 1x |
| RapidOCR rec-only, batched | 1.65 ms | 41.2 ms | **79x faster** |
| Template matcher | 0.100 ms | 2.51 ms | **1291x faster** |

### But the bigger finding is that RC is OCRing the wrong things

`data/vision_regions.json` has 21 calibrated regions; the atlas adds 4 gap slots for 25.
Cross-referencing every one against the `:2999` field list:

**Scope-rule violations - `:2999` provides these exactly, for free, at any poll rate.
Delete the regions (8 of 21, 38%):**
`gold` (`activePlayer.currentGold`), `cs` and `kda` (`allPlayers[].scores`), `level`
and `ally_levels` (`allPlayers[].level`, every player), `timer`
(`gameData.gameTime`), `hp` and `mana` (`activePlayer.championStats`).

RC has the mechanism for this already - `configure_drop_fields()` exists precisely to
skip fields the Live Client relay answers. It is simply not being pointed at everything
it should be. This is the single cheapest win in the slice: **8 fewer Tesseract calls
is ~1.4 s of wall clock per pass removed, with zero accuracy risk, by deleting code.**

**Genuine API gaps - keep, and note none of them are OCR:**
`ally_1..4_hp` / `ally_1..4_mana` (8 regions - `allPlayers[]` genuinely carries no
health fields, so this is a real gap) and `ally_ults` (1). RC reads these with
`_bar_fill_pct` and `_ally_ults_strip`, pure pixel counting, no OCR engine. **That is
already the correct design.** Keep unchanged.

**Non-gameplay:** `ping`, `fps`. Harmless, but they are on `_SLOW_FIELDS` and still
cost 170 ms each when they fire.

**Genuinely uncertain:** `score_blue` / `score_red` (ARAM/Arena team score). Not
obviously in `:2999`. Verify before deleting.

**The gap nobody is filling:** there is **no `*_cd` region calibrated at all.**
`_ocr_cooldown()` and the `name.endswith("_cd")` branch in `_parse_field` exist and are
dead - no region key ever reaches them. So RC's OCR tier currently spends 100% of its
budget on fields that are either free from `:2999` or handled by non-OCR pixel
counting, and 0% on the objective-timer gap that is the one thing pixels could
usefully add.

### Recommendation

1. **Delete the 8 `:2999`-duplicated regions.** Free, immediate, largest single win.
   Do this first and independently of any engine decision.
2. **Keep Tesseract for nothing.** After step 1 the remaining OCR work is
   `score_blue`/`score_red`/`ping`/`fps` - four low-value fields. Tesseract's 170 ms
   floor cannot be tuned away (it is model load, and psm/oem/whitelist all measured
   flat), so there is no configuration that rescues it.
3. **For the objective-timer gap, build the template matcher, not an OCR engine.**
   The alphabet is 12 glyphs in a fixed game font at a fixed rect. MEASURED 0.100 ms
   with 7/7 correct once aspect ratio is preserved. It is the only option that leaves
   real headroom under a sub-100 ms budget for the rest of the pipeline.
4. **Carry RapidOCR rec-only as the fallback tier** where the template matcher's
   margin gate rejects, replacing the Sonnet escalation for numeric fields.
   MEASURED 2.6-3.4 ms, Apache-2.0, CPU-only as installed, models bundled in the wheel.
   Pin the version explicitly - the Python 3.14 silent downgrade to 1.2.3 is a real trap.
5. **Do not adopt PaddleOCR.** Same model family as RapidOCR's backend, an order of
   magnitude more install friction, no Python 3.14 support, and its own vendor-reported
   21 ms mobile-rec figure is already 12x slower than the measured RapidOCR rec-only
   path on this hardware.

Vanguard: all four options are pure consumers of an already-captured image. None
requires injection, hooking, or memory reads. **No Vanguard flag on the engine choice.**
The only Vanguard-banned technique in this slice is the memory read that enemy cooldowns
would require, which is separately policy-forbidden - see section 0.

---

## 5. WHERE EACH STOPS BEING GOOD ENOUGH

**Tesseract + pytesseract** stops being good enough the moment you have more than one
crop or care about latency at all. Its 170 ms is a fixed per-invocation model load, so
the cost is *per crop* and scales superlinearly under a thread pool (25 crops = 3.2 s).
It is fine for a one-shot read of a static screen. It is not fine for a per-tick HUD
sweep. Secondary limit: it dropped the decimal in `4.7` at 2 of 5 tested glyph heights.
Note there is an escape hatch I did not test - `tesserocr` binds the Tesseract C++ API
in-process and would amortise the model load across calls. That would likely close most
of the gap and keeps the existing engine. UNVERIFIED, and Windows/Python 3.14 build
friction is likely severe.

**RapidOCR rec-only** stops being good enough when 1.65-3.4 ms per crop is still too
much, i.e. if you want to run at capture frame rate across dozens of regions rather than
at a coaching tick. It also carries ~90 MB of dependencies (opencv, onnxruntime, numpy,
shapely) for what is ultimately digit reading, and its confidence score cannot tell you
whether a read is right. It stops being appropriate entirely if you route it through
the top-level `__call__` instead of `text_recognizer` - the detector heuristics will
silently re-enable and cost you 60x.

**PaddleOCR** stops being good enough at the install boundary on this machine: no
Python 3.14 support, framework dependency, documented resolver and circular-import
failures. Its accuracy edge over RapidOCR is meaningless for a 12-glyph alphabet.

**Template matching** stops being good enough the moment the assumptions break, and they
are strong assumptions: fixed font, fixed scale, fixed rect. It will break on a League
HUD-scale change, a resolution the atlas is not calibrated for, a client font update, or
a patch that restyles the HUD. It has no graceful degradation - it returns a confident
wrong glyph. **This is exactly why it must be paired with the layered reject path in
section 3 and a fallback tier, never shipped alone.** Its NCC margin also proved a poor
standalone reject signal (correct reads down to 0.055 overlapping noise at 0.119).

**All of the above** stop being good enough when the numeral is fully occluded. No
engine recovers information that is not in the pixels; that is what temporal median and
the N-of-M gate are for, and past ~50% occlusion across the whole window the correct
output is "unknown", not a number.

---

## 6. UNVERIFIED LIST

Marked honestly. Do not treat these as findings.

1. **Riot's primary policy text.** `support-developer.riotgames.com/.../22698698001939`
   returned HTTP 403. Section 0 rests on the Overlay Platform M-published Riot compliance rules.
   Read the Riot original before acting on the policy conclusion.
2. **Whether objective / jungle timers are explicitly permitted.** The compliance page
   enumerates forbidden items and does not mention them. Widely shipped in practice.
   Confirm before building the one target I recommend building.
3. **All accuracy figures.** Synthetic Arial Bold crops, not League's typeface, not real
   particles. Latency transfers; accuracy does not. The `4.7 -> 47` Tesseract failure is
   a synthetic reproduction and must be re-run on real frames before being called a bug.
4. **Tesseract confidence on a *wrong* read.** I measured conf=96 on a correct read only.
   The useful experiment is the conf value on the `4.7 -> 47` failure. Not run.
5. **`tesserocr` in-process binding.** Would plausibly remove most of the 165 ms model
   load and preserve the existing engine. Not attempted; Windows + Python 3.14 build
   friction unknown.
6. **Small digit CNN latency.** Asserted to be template-matcher-class. Not benchmarked.
7. **PaddleOCR latency on this hardware.** All PaddleOCR figures are vendor-reported on
   Xeon Gold 6271C / Tesla T4. Not independently measured.
8. **`score_blue` / `score_red` availability in `:2999`.** Assumed to be a genuine gap;
   not confirmed against a live ARAM/Arena payload.
9. **Behaviour under real game load.** All benchmarks ran with League not running.
   Tesseract's pool numbers in particular will degrade further under contention.
10. **`rapidocr` 3.x (3.9.2)** Python 3.14 support and whether its newer PP-OCRv5 models
    change the per-crop figure. I measured the 1.2.3 / PP-OCRv3 path that pip actually
    resolved.
11. **RapidOCR GPU providers.** Legion exposed CPU-only. Whether `onnxruntime-directml`
    would help, and whether it would contend with League's rendering, is untested -
    though CPU-only is the preferable answer next to a running game regardless.
