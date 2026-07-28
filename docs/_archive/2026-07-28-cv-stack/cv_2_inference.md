# CV Slice 2 - Inference Runtimes + Pipeline Orchestration

Research date 2026-07-28. Target machine probed live this session, not assumed.

## 0. MEASURED HARDWARE (probed, not assumed)

| Item | Value | How known |
|---|---|---|
| GPU | NVIDIA GeForce RTX 5070, 12227 MiB, driver 610.62 | `nvidia-smi` this session |
| GPU arch | Blackwell consumer (GB20x), compute capability 12.x | vendor mapping |
| CPU | AMD Ryzen 7 7700X, 8C/16T | `Win32_Processor` this session |
| Display adapters enumerated | **1** (the 5070 only) | `Win32_VideoController` count = 1 |
| iGPU | 7700X ships a 2-CU RDNA2 "Radeon Graphics" iGPU, but it is **not currently enumerated** - BIOS-disabled or headless | count=1 above |
| OS | Windows 10 Pro 19045 | env |

Two consequences fall straight out and they kill two of the four candidate answers before
any benchmark:

- **OpenVINO's GPU plugin is Intel-only.** No Intel GPU exists on this box. OpenVINO here
  is a CPU-plugin-only story on an AMD CPU (oneDNN generic path, not the Xeon/Core tuned
  path its benchmarks are published on). It is not a serious candidate.
- **"Run it on the iGPU" is not currently available.** It is *architecturally* the only
  true isolation from the game, but it needs a BIOS enable first, and 2 RDNA2 CUs is
  ~0.56 TFLOPS FP32 sharing DDR5 bandwidth with the game's CPU threads. Worth one measured
  spike, not a plan.

## 1. RC BASELINE - what this is an upgrade over

Read this session:

- `vision_server/_inference.py` - three handlers. `handle_vision` posts a base64 frame to
  the **Anthropic Messages API** (Sonnet) and reports `latency_ms`. `handle_coach` same for
  Haiku. `handle_ocr` shells out to `tesseract.exe` per crop with a 10 s timeout.
- `core/vision_tesseract.py` - region-bbox OCR, docstring claims "~50ms+free per field",
  regions scaled from a 1920x1080 base in `data/vision_regions.json`.
- `core/vision_template_match.py` - OpenCV `matchTemplate` TM_CCORR_NORMED + masked Pearson,
  threshold 0.6, explicitly **default-OFF and not wired into any runtime path**.

So the baseline has **zero neural inference running locally**. There is no ONNX model, no
GPU inference process, no tracker, no event layer. The "runtime" today is: HTTP -> base64 ->
subprocess tesseract, or HTTP -> base64 -> a cloud LLM.

**The honest headline: swapping runtimes buys almost none of the 2 s -> 100 ms step change.**
Decompose the current 2 s tick:

| Stage | Rough share of the 2 s | Fixed by a runtime choice? |
|---|---|---|
| The 2 s poll interval itself | the dominant term, by construction | No - it is a `sleep`, delete it |
| Screen agent POST -> `:8889` -> coach GET `/latest-frame` | base64 encode + two HTTP hops on a JPEG | No - this is an architecture problem |
| Sonnet vision API call | ~1-2 s wall, network-bound | No - only removable by not calling it |
| Tesseract subprocess per crop | ~50 ms claimed per field, process spawn each time | No - it is a process-spawn problem |
| Actual tensor math | currently **0 ms - it does not exist** | This is the only part a runtime touches |

A local detector at 640 on this GPU is a **single-digit-millisecond** operation (see table).
Getting to sub-100 ms end to end is ~90 percent about deleting the poll interval, the HTTP
hop, the base64 round trip and the cloud call - and ~10 percent about which EP you pick.
Pick the runtime that is cheapest to *operate*, not the one with the best microbenchmark.

## 2. RUNTIME TABLE

Caveat on the resolution columns, because the brief's framing hides a trap: **a detector
does not run "at 1080p" or "at 1440p".** It runs at its network input size (640x640,
416, 320, or a crop). Capture resolution changes the *capture + resize* cost, not the conv
cost. Both rows are given separately so the number is not silently conflated.

### 2a. Inference cost - model input size is the axis that matters

| Runtime | Model / input | Measured latency | Source | Verified? |
|---|---|---|---|---|
| TensorRT 10 FP16 | YOLO11n @ 640 | **1.5 +/- 0.0 ms** | Ultralytics YOLO11 model card, T4 GPU | VERIFIED (on T4, not on a 5070) |
| TensorRT 10 FP16 | YOLO11s @ 640 | **2.5 +/- 0.0 ms** | same | VERIFIED (T4) |
| TensorRT 10 FP16 | YOLO11m @ 640 | **4.7 +/- 0.1 ms** | same | VERIFIED (T4) |
| ORT CPU | YOLO11n @ 640 | **56.1 +/- 0.8 ms** | same table, CPU ONNX column | VERIFIED as published; **hardware unstated** |
| ORT CPU | YOLO11s @ 640 | **90.0 +/- 1.2 ms** | same | VERIFIED as published, hw unstated |
| ORT TensorRT EP | ResNet152 @ 224, bs1 | **5.797 ms** | nietras.com, RTX 3070, few hundred iters + warmup | VERIFIED (3070, ResNet not YOLO) |
| ORT DirectML EP | ResNet152 @ 224, bs1 | **7.795 ms** (1.16x faster than CUDA EP) | same run | VERIFIED (3070) |
| ORT CUDA EP | ResNet152 @ 224, bs1 | **9.052 ms** | same run | VERIFIED (3070) |
| ORT CPU | ResNet152 @ 224, bs1 | **37.472 ms** | same run | VERIFIED (3070 box CPU) |
| OpenVINO GPU | YOLOv8 INT8 | 1073.97 fps claimed | OpenVINO blog, **Intel Arc A770M** | VERIFIED as published, **irrelevant hardware** |

The single most useful line in that table is the ORT one: on one real Windows box, one real
model, **DirectML EP beat the CUDA EP and TensorRT EP beat both by 1.56x**. The spread
between the three GPU EPs is under 2x. The spread between any of them and CPU is ~5x. That
ratio is the decision, not the absolute numbers.

**Do not extrapolate the T4 numbers to the 5070.** A T4 is Turing datacenter silicon at 70 W;
a 5070 is Blackwell consumer at ~250 W. The 5070 will be faster, likely substantially, but by
how much is UNVERIFIED and must be measured with `trtexec` on this box before any plan
depends on a number.

### 2b. Capture + preprocess cost - this is where 1080p vs 1440p actually shows up

Not separately benchmarked here; flagged as a required measurement. Structurally, per tick:

- 1920x1080 BGRA frame = 8.3 MB; 2560x1440 = 14.7 MB (1.78x the bytes).
- A full-frame CPU resize 1080p -> 640x640 and a 1440p -> 640x640 differ by roughly that
  same 1.78x on the resize, and identically on any PCIe upload.
- **The mitigation is the same at either resolution: do not send the full frame.** The CV
  targets (minimap, HUD cooldown row, champion nameplates) are small fixed ROIs. A 512x512
  minimap crop is 1.0 MB regardless of whether the desktop is 1080p or 1440p. Crop first,
  then the resolution question mostly evaporates.

RC's `core/vision_tesseract.py` already has the right idea - `BASE_W, BASE_H = 1920, 1080`
with proportional bbox scaling. That scaling scheme carries straight over to a detector ROI
table.

### 2c. The full runtime comparison

| | ONNX Runtime + DirectML EP | ONNX Runtime + CUDA EP | TensorRT (native or ORT-TRT EP) | OpenVINO |
|---|---|---|---|---|
| Runs on this box | Yes | Yes | Yes (needs TensorRT >= 10.8 for Blackwell) | CPU plugin only - **no Intel GPU present** |
| Relative speed (measured, 3070/ResNet152) | 7.80 ms | 9.05 ms | 5.80 ms | n/a |
| VRAM footprint | Lowest of the three GPU paths. DML allocates through D3D12 so the WDDM manager can evict under pressure | CUDA EP carries a CUDA context + cuDNN/cuBLAS workspaces; the classic complaint is several hundred MB before any weights | Engine + workspace; workspace is an explicit build-time knob you set | n/a |
| Actual weight bytes (arithmetic, not a measurement) | YOLO11n 2.6 M params -> ~5.2 MB FP16, ~2.6 MB INT8. **The weights are noise; the runtime context is the whole footprint** | same | same | same |
| Conversion friction | Lowest. Export ONNX, `onnxruntime-directml`, run. Gotcha: **no dynamic batch / free dimensions** without fixing shapes; **no multi-threaded `Run()` on one session** | Low. Export ONNX, `onnxruntime-gpu`, run. Needs the CUDA/cuDNN versions ORT was built against | Highest. Per-GPU, per-driver, per-TRT-version engine build. Engine is **not portable** - it is rebuilt on this machine and re-built again after a driver bump. Build takes minutes |
| Licence | ONNX Runtime: **MIT**. The DirectML redistributable itself is a Microsoft-licensed binary (redistributable, not OSI) | ONNX Runtime **MIT**; CUDA/cuDNN under NVIDIA's licences | TensorRT core runtime is **proprietary, NVIDIA SLA for SDKs**. The TensorRT-OSS plugin/parser repo is Apache-2.0. Not the same thing | **Apache-2.0** |
| Strategic risk | **Real.** ORT's own DirectML page says DirectML is in "sustained engineering" and new feature development moved to Windows ML | Stable, but tied to NVIDIA toolkit version churn | Stable, but you own an engine-rebuild step forever | Fine, wrong hardware |
| Vanguard | Clean - none of these touch the game process | Clean | Clean | Clean |

**Recommendation for RC: ONNX Runtime, DirectML EP, on the 5070, running crops.**
Rationale, in priority order:
1. It is within 1.35x of TensorRT on the one honest head-to-head available, and the whole
   GPU-EP spread is smaller than the error bars of the *architecture* changes that actually
   deliver the 20x.
2. Zero engine-build step. No per-driver rebuild. An `.onnx` file is the artifact, and RC
   already has an atomic-write-plus-replace discipline for artifacts.
3. It is the only path that would also work on the iGPU (DirectML enumerates any DX12
   adapter) if the isolation plan ever gets built.
4. Add ORT-TensorRT EP later as a **swap-in EP behind the same session API** if measurement
   says the 1.35x matters. Do not start there.

Counter-consideration, stated honestly: DirectML being in sustained engineering is a real
long-term smell. The mitigation is that ORT's EP abstraction means the migration is one
constructor argument, not a rewrite.

**Licence landmine, flagged because it is easy to miss:** Ultralytics YOLOv8/YOLO11/YOLO26
are **AGPL-3.0**. If RC is ever distributed (and there is a pre-release name-scrub project on
file, so distribution is contemplated), AGPL reaches the whole work. Apache-2.0 alternatives
that export to ONNX cleanly: **RT-DETR / RT-DETRv2** (Apache-2.0), **D-FINE** (Apache-2.0),
**YOLOX** (Apache-2.0). Decide this before training anything, not after.

## 3. GPU CONTENTION - what actually works on this box

The brief is right that a recommendation which tanks the game's FPS is a failed
recommendation. Here is the mechanism-by-mechanism verdict. Most of the famous answers do
not exist on Windows consumer hardware.

| Mechanism | Verdict on Win10 + GeForce 5070 | Detail |
|---|---|---|
| **CUDA MPS** | **DOES NOT EXIST HERE** | NVIDIA's own docs: MPS is 64-bit **Linux only**. Its `CUDA_MPS_CLIENT_PRIORITY` (NORMAL / BELOW_NORMAL) and `CUDA_MPS_ACTIVE_THREAD_PERCENTAGE` are exactly what we would want and are unreachable. Even there, NVIDIA calls priorities "only considered as hints" |
| **MIG** | **DOES NOT EXIST HERE** | Datacenter + RTX PRO only (A100/A30/H100/H200/GB200/B200/RTX PRO Blackwell). No GeForce SKU is on the supported list, and it is Linux-only besides |
| **CUDA stream priority** (`cudaStreamCreateWithPriority`) | **PARTIAL - useless against the game** | Two problems. (a) NVIDIA runtime docs: priorities "provide a hint ... but do not preempt already-running work"; only compute kernels are affected, not H2D/D2H copies. (b) Scope is the calling **context**, which is per-process. League is a D3D client, not a CUDA client in our context. Setting our stream low does nothing to it |
| **D3D12 command queue priority** | **PARTIAL - you can only go UP** | The enum has exactly NORMAL(0), HIGH(100), GLOBAL_REALTIME(10000). **There is no BELOW_NORMAL / IDLE queue priority.** GLOBAL_REALTIME needs privilege plus adapter/driver preemption support and fails loudly rather than downgrading. Useful hook: ORT's `SessionOptionsAppendExecutionProvider_DML1` takes an `ID3D12CommandQueue` **you** create - but the floor is NORMAL, so the best available is "tie with the game", never "yield to it" |
| **GPU preemption / WDDM TDR** | **WORKS - but it is a safety net, not a throttle** | Compute preemption at instruction-level granularity since Pascal (cc 6.0), inherited by Blackwell. WDDM 1.2+ forbids the KMD disabling DMA-packet preemption. `TdrDelay` default is 2 s. This stops our detector *hanging the display*; it does not stop it *stealing SM time* |
| **HAGS** | **PARTIAL / neutral** | Microsoft's DirectX blog is explicit: HAGS moves quanta management and context switching to a GPU scheduling processor, but "Windows continues to control prioritization". It changes who executes the schedule, not the policy. Also note DLSS 3 Frame Generation requires it on |
| **nvidia-smi controls** | **MOSTLY BLOCKED** | Compute mode (`-c EXCLUSIVE_PROCESS`) needs the **TCC** driver model, which GeForce cannot use. Persistence mode (`-pm`) is Linux-only. Application clocks (`-ac`) deprecated / Maxwell-GeForce-era. Power limit (`-pl`) may accept a write but **throttles the entire GPU including the game** - wrong direction |
| **NVIDIA Control Panel knobs** | **DOES NOT EXIST as a compute throttle** | Max Frame Rate, Low Latency Mode, Power Management all act on the graphics pipeline. "CUDA - GPUs" on a single-GPU box is all-or-nothing: it can turn CUDA off, not turn it down. **But**: capping League with Max Frame Rate is still worth doing, because it converts spare GPU into genuine idle time our detector can occupy uncontested |
| **CPU process priority** (`SetPriorityClass`) | **WORKS, but CPU only** | Worth setting BELOW_NORMAL regardless - it costs nothing and protects the game's render thread from our preprocess/postprocess work. Does not touch GPU queues |
| **`D3DKMTSetProcessSchedulingPriorityClass`** | **PARTIAL - the one real GPU-priority lever, unproven** | This is the genuine find. Exported from `Gdi32.dll`, header `d3dkmthk.h`, Vista+. The `D3DKMT_SCHEDULINGPRIORITYCLASS` enum includes **`_IDLE` and `_BELOW_NORMAL`**. It is the **only documented Windows API that expresses "run this process's GPU work below normal"**. Caveats: it lives in the display-driver DDI docs rather than app-dev Win32 docs, and **how much the NVIDIA WDDM scheduler honors IDLE/BELOW_NORMAL is UNVERIFIED** - no primary measurement found. Process Lasso exposes exactly these six classes as "GPU priorities", which is at least evidence it is real and settable |
| **Duty cycling / workload shaping** | **WORKS - this is the actual answer** | See below |
| **CPU inference instead** | **WORKS - zero GPU frame cost** | YOLO11n @ 640 ORT CPU = 56.1 ms published. On a 7700X with 2-4 threads that is very likely better, and at 320 or on a crop it drops further. Costs the game zero GPU time. A 7700X is not the bottleneck in League |
| **iGPU offload** | **NOT AVAILABLE TODAY, best-in-theory** | 2-CU RDNA2, BIOS-disabled on this box, ~0.56 TFLOPS, shares DDR5 bandwidth. Genuine hardware isolation if enabled. Untested for a YOLOn-class model |

### The mechanism that actually works: workload shaping

Every driver-level knob above is absent, hint-only, or raise-only. What is left is entirely
under RC's control and needs no cooperation from anyone:

1. **Duty cycle.** GPU steal fraction = `kernel_ms / period_ms`. A 2 ms kernel every 200 ms
   is 1 percent of the GPU. A 2 ms kernel every 16 ms is 12 percent and will be felt.
2. **Frame budget arithmetic, stated as a bound rather than a measurement.** 144 Hz is a
   **6.94 ms** frame budget; 240 Hz is **4.17 ms**. Any single un-preempted kernel comparable
   to that number eats a frame. The design target is **sub-1 ms per kernel**, which pushes
   toward small crops and INT8, not toward a bigger model.
3. **Crops, not frames.** Minimap ROI, HUD cooldown strip, nameplate band. This cuts the
   conv cost, the upload cost and the resize cost simultaneously, and it is the same
   discipline `vision_regions.json` already encodes.
4. **One process, one context, one session, model resident.** Never build a session or a
   CUDA/D3D12 context per tick - context creation dwarfs the kernel by orders of magnitude.
   RC's existing in-process `:8889` server is already the right shape for this.
5. **Sleep, do not spin,** between ticks so the process is genuinely idle.
6. **Cap League's FPS** with NVCP Max Frame Rate so the freed headroom is real.
7. **Measure with frametime percentiles** (PresentMon / CapFrameX 1 percent and 0.1 percent
   lows), never average FPS. Average FPS is exactly the metric that hides a periodic hitch.

**Honesty note:** no primary measurement was found for the specific case "a sub-5 ms kernel
every 33 ms costs the game X ms of frame time". Anyone quoting a number for that is
inventing it. What the literature does establish is that colocated kernels inflate each
other - one study measured a 1.7x per-kernel latency increase under colocation and p95
interference of ~152 percent at concurrency 2 - so the effect is real and non-trivial, and
the only responsible plan is to measure it on this box with a frametime log before shipping.

### Vanguard

All four runtimes and all three orchestration projects are clean: they consume pixels from
outside the game process. The banned techniques do not appear anywhere in this slice. What
*is* banned and is a common temptation in this exact problem space:

- Hooking `IDXGISwapChain::Present` to grab the backbuffer directly (the standard "fast
  capture" trick in game-CV tooling) - **injection, banned**.
- Reading cooldowns/positions out of game memory instead of off pixels - **banned**, and
  also unnecessary since :2999 already gives ability ranks and the event feed.
- Capture must stay external: DXGI Desktop Duplication or Windows.Graphics.Capture. Both are
  OS APIs applied to the desktop/window, not to the game process.

## 4. ORCHESTRATION TABLE

| | NVIDIA DeepStream | Frigate NVR | Norfair |
|---|---|---|---|
| Version / date | 9.1.0, 2026-07-14 | 0.17.2, 2026-06-28 | 2.3.0, 2025-04-30 |
| Licence | **Split and misleading.** GitHub monorepo source is CC-BY-4.0 AND Apache-2.0; the **actual runtime binaries are proprietary** under the NVIDIA SDK Software License Agreement + NVIDIA AI Product License. The build script downloads the proprietary runtime | **MIT** (confirmed via GitHub licence API) | **BSD-3-Clause** (confirmed, GitHub + PyPI agree) |
| Architecture | GStreamer pipeline: `nvstreammux` -> `Gst-nvinfer` (TensorRT) -> `Gst-nvtracker` -> `nvdsosd`/sinks. Metadata rides the buffer as `NvDsBatchMeta`. Tracker is a pluggable low-level lib behind the `NvMOT_*` C ABI; NVIDIA ships `libnvds_nvmultiobjecttracker.so` (IOU / NvSORT / NvDeepSORT / NvDCF / MaskTracker) | Multi-process + POSIX shm. Per-camera ffmpeg emits raw YUV420p to stdout -> `SharedMemoryFrameManager` writes once, others read by reference -> `ImprovedMotionDetector` background subtraction **gates** the detector -> detector processes run only on motion-derived regions snapped to a `region_grid` -> `NorfairTracker` -> zones -> `Dispatcher` fans out to MQTT/WebSocket | Pure-Python generalized SORT. `Tracker(distance_function, distance_threshold, ...)`, `tracker.update(detections, period, coord_transformations) -> List[TrackedObject]`. Three filter factories: `OptimizedKalmanFilterFactory` (default, hand-rolled), `FilterPyKalmanFilterFactory`, `NoFilterFactory`. Point-based, so boxes/keypoints/n-D all work. Camera-motion compensation and appearance re-ID hooks included |
| Library or framework | **Framework/appliance.** GStreamer plugin suite + C/C++ app model. Narrow exception: the tracker `.so` is dlopen-able and drivable via `NvMOT_*` directly - but it wants NV12/RGBA surfaces in CUDA device memory, not a numpy array | **All-or-nothing appliance.** Container image + config file + web UI + go2rtc + database + MQTT. No pip package, no importable API | **True library.** `pip install norfair`, `from norfair import Tracker, Detection` |
| Native Windows | **No.** Supported platforms are Ubuntu 24.04 x86 dGPU, Jetson JetPack, SBSA Docker. Windows appears only as "DeepStream on WSL" - a Linux container in WSL2, with NVIDIA's own note that "performance in WSL is not at par with Ubuntu" | **No.** Docs: "Windows is not officially supported, but some users have had success getting it to run under WSL or Virtualbox", with the caveat that GPU/Coral passthrough "may be difficult or impossible" | **Yes.** PyPI classifier "OS Independent". Core deps are numpy, scipy, filterpy, rich. **No torch. No mandatory OpenCV** (`opencv-python` is only the `[video]` extra) |
| Windows blockers | GStreamer 1.x + Linux-only proprietary `nv*` plugins, CUDA 13.2 / TensorRT 10.16 matched stack, `NvBufSurface` memory types, Ubuntu base, Docker/WSL2 | `/dev/shm` POSIX shared memory, Linux-tuned ffmpeg stdout piping, device passthrough (Coral, VAAPI/QSV/NVDEC), the whole Docker assumption | None |
| Vanguard | Clean (but irrelevant - cannot run here) | Clean (but irrelevant) | Clean |

### Lighter tracker alternatives, checked

| Library | Version | Licence | Note |
|---|---|---|---|
| supervision (Roboflow) | 0.29.1, 2026-06-23 | **MIT** | `sv.ByteTrack` + annotators; numpy/scipy/opencv/matplotlib/pillow, no torch. Viable MIT alternative, but you pull a whole toolkit for one tracker |
| boxmot | 22.0.0 | **AGPL-3.0** | BoT-SORT/DeepOCSORT/StrongSORT/ByteTrack with re-ID, **requires torch + torchvision**. AGPL is a hard blocker if RC is ever distributed |
| motpy | 0.0.10, 2021-09-22 | MIT | Minimal Kalman + IOU. **Unmaintained since 2021** - reference implementation only |

**Cross-validation worth stating:** Frigate - the most battle-tested low-latency CV appliance
of the three - pins `norfair==2.3.*` in its own wheels file. The motion-gate + Norfair
combination is not a theory, it is what the reference implementation ships.

## 5. WHAT RC CAN LIFT vs REIMPLEMENT

### LIFT directly (pip install, ship it)

- **Norfair 2.3.0, BSD-3-Clause.** Drop-in. numpy + scipy + filterpy + rich, no torch, no
  mandatory OpenCV, Windows-clean. This is the entire "track" stage of capture -> infer ->
  track -> event, for free. Champion identity across frames, minimap dot continuity through
  fog and occlusion, and detection gaps absorbed by the Kalman filter - which is exactly what
  lets RC run the detector at a low duty cycle without the output flickering.
- **ONNX Runtime (MIT) + DirectML EP.** Session API, EP abstraction, IObinding.
- **The Frigate motion-gate *design*** (not the code). Cheap always-on pixel-difference pass
  decides *whether and where* to run the expensive model; the tracker absorbs the resulting
  gaps. Frigate's specific knobs are worth copying as a starting parameter set: pixel
  threshold ~30, minimum contour area ~10-50, a "lightning threshold" that recalibrates the
  background on a whole-frame change, and permanent masks over regions that always change
  (their case is a timestamp overlay; RC's is the League HUD clock, the chat box and the
  scoreboard). ~50 lines of OpenCV, all of which RC already has as a dependency.

### REIMPLEMENT (small, and RC is better off owning it)

- **Capture.** DXGI Desktop Duplication or Windows.Graphics.Capture, external, Vanguard-safe.
  Frigate's ffmpeg-to-stdout and DeepStream's `nvstreammux` are both solving a
  many-RTSP-cameras problem RC does not have. RC has one local window.
- **The tick loop / scheduler.** RC already has `app/_loop.py` (asyncio AppLoop, frozen) and
  an in-process `:8889` server. That IS the orchestrator. Do not import a second one.
- **The event layer.** Frigate emits to MQTT; RC writes JSON to `data/` atomically and serves
  `:8888`. RC's version is already better suited to its consumers.
- **Zones.** Frigate's zone-polygon logic is trivial and RC's map geometry is fixed and
  already partly calibrated (`reference_minimap_geometry_calibration`).

### DO NOT TOUCH

- **DeepStream.** It cannot run natively on Windows at all - only as a Linux container in
  WSL2, with NVIDIA's own performance disclaimer, and the runtime is proprietary. Every
  architectural idea in it (batched mux, TensorRT nvinfer, pluggable tracker) is available
  in a Windows-native form somewhere else in this table. This is a closed door, not a
  trade-off.
- **Frigate as a component.** It is an appliance. Lift the idea, not the repo.
- **boxmot.** AGPL + torch. Both are disqualifying for RC.
- **Ultralytics as a shipped dependency.** AGPL-3.0. Fine for a research spike, a real
  problem the moment RC is distributed. Prefer RT-DETRv2 / D-FINE / YOLOX (all Apache-2.0)
  if the model is going into the product.

### The proposed shape

```
DXGI capture (external, Vanguard-safe)
  -> ROI crops from a vision_regions-style table (minimap / HUD strip / nameplate band)
  -> OpenCV motion gate (Frigate pattern) decides which crops are worth a forward pass
  -> ORT DirectML session, batch 1, fixed shapes, model resident, INT8/FP16
  -> Norfair Tracker (one per semantic class: minimap dots, viewport champions)
  -> event derivation, FUSED WITH :2999 not duplicating it
  -> atomic JSON write + :8888
```

Explicitly **not** derived from pixels: gold, CS, items, levels, KDA, ability ranks, the
event feed. :2999 gives all of those exactly and for free. CV's entire job is positions,
wave state, ward coverage, HUD cooldowns, recall/base, fight boundaries, objective contest
windows - and :2999's event feed is the *ground truth label source* for training and for
validating the fight-start detector, which is a real asset RC already owns.

## 6. WHERE EACH STOPS BEING GOOD ENOUGH

- **ORT DirectML EP** stops being good enough when (a) the measured kernel does not fit the
  sub-1 ms budget after cropping and INT8, in which case swap the EP to ORT-TensorRT and pay
  the engine-build tax; or (b) Microsoft's "sustained engineering" status turns into a real
  deprecation, in which case migrate to Windows ML or the CUDA EP - one constructor argument.
- **TensorRT** stops being good enough when the engine-rebuild-per-driver-bump becomes an
  operational liability. On a box that takes GeForce driver updates, that is a recurring
  break, and RC has a supervisor that restarts on `restart_trigger.txt`, not a build system.
  Adopt it only when a measurement proves the 1.35x matters.
- **OpenVINO** already is not good enough - wrong vendor for both the CPU-optimized path and
  the GPU plugin.
- **CPU inference** stops being good enough above roughly 3-5 detections per second at 640,
  or as soon as the crop set grows past two or three ROIs. It is the safest *first* build and
  the right fallback, not the destination.
- **The GPU-priority story** stops being good enough the moment duty cycle rises toward
  per-frame. There is no lever to pull at that point - Windows consumer hardware simply does
  not expose a below-normal GPU queue that is proven to be honored. The design must never
  arrive there.
- **Norfair** stops being good enough when identity must survive a long full occlusion or a
  teleport/recall reappearance elsewhere on the map. It has a re-ID hook but you supply the
  embeddings; it does no appearance modelling itself. For League specifically, the escape
  hatch is that :2999 and champion-portrait template matching (`core/vision_template_match.py`,
  already written) can re-anchor identity, so the tracker only has to bridge short gaps.
- **The Frigate motion gate** stops being good enough for anything that is *static and
  important* - a stationary ward, a champion standing still in a bush, a cooldown that is
  ticking without pixels moving much. Motion gating is a scheduler for *change*, and some CV
  targets are states, not events. Those need a low-frequency unconditional pass.
- **The sub-100 ms target overall** stops being achievable at the capture layer, not the
  inference layer. If DXGI Desktop Duplication on this box delivers a frame every 16.7 ms and
  the game is running at 144 Hz, there is an irreducible capture-to-decision floor in the
  1-2 frame range. Sub-100 ms is comfortable against that; sub-20 ms is not, and nothing in
  this slice changes it.

## 7. UNVERIFIED LIST

Everything below is explicitly NOT established. Do not build a plan that depends on any of
it without measuring first.

1. **Any latency number for a detector on the RTX 5070.** All measured figures in this
   document are from a T4 or an RTX 3070. The 5070 will differ. Measure with `trtexec` and
   an ORT-DML timing loop on this box.
2. **VRAM footprint of each runtime with a real model loaded.** No primary measurement found.
   The weight arithmetic (YOLO11n ~5.2 MB FP16) is arithmetic, not a measurement; the runtime
   context overhead - which dominates - is unmeasured for all three EPs on this box.
3. **Capture + resize cost at 1080p vs 1440p on this box.** Not measured. The 1.78x byte
   ratio is arithmetic, not a timing.
4. **Whether the NVIDIA WDDM scheduler actually honors
   `D3DKMT_SCHEDULINGPRIORITYCLASS_IDLE` / `_BELOW_NORMAL`.** The API is documented and real;
   its effect is entirely unmeasured. This is the highest-value single experiment in the
   whole slice - if it works, it changes the risk profile of GPU inference completely.
5. **The cost of a sub-5 ms kernel every 33 ms to League's frame time.** No primary
   measurement exists. The colocation-interference figures cited (1.7x kernel inflation,
   ~152 percent p95 interference at concurrency 2) come from general GPU-scheduling
   literature, not from a game + detector case.
6. **Whether `nvidia-smi -pl` accepts a write on a GeForce 5070 under driver 610.62.**
   Unverified, and it would throttle the game too, so it is not worth verifying.
7. **HAGS on/off effect on a mixed compute+game workload.** Only secondary blog benchmarks
   found (~noise on pure gaming), nothing primary for the mixed case.
8. **YOLO11n / YOLO11s CPU latency on a 7700X specifically.** The published 56.1 ms / 90.0 ms
   figures have **no stated benchmark hardware** on the Ultralytics page.
9. **Whether the 7700X iGPU can run a YOLOn-class model usefully via DirectML.** No benchmark
   found for a 2-CU RDNA2 part. Also currently BIOS-disabled on this machine.
10. **DeepStream EULA exact clause wording.** The licence PDFs are FlateDecode binary and
    could not be read cleanly; the summary above came from search snippets. Irrelevant in
    practice since DeepStream cannot run natively on Windows, but do not quote the terms.
11. **boxmot 22.0.0 release date.** PyPI JSON fetch did not return it.
12. **Windows Game Mode's effect on GPU queue arbitration.** No primary doc found specifying
    any GPU-scheduling behaviour.
13. **`cudaDeviceGetStreamPriorityRange` values on a 5070.** Device- and driver-reported; must
    be read at runtime. Do not assume a level count.
14. **The "MLPerf 2025 / DirectML cuts latency 70 percent" and "closes 95 percent of the gap
    to TensorRT" claims** that surfaced in search results. These appear to be
    AI-generated SEO content with no traceable primary benchmark. **Discarded, not used.**

## Sources

- [ONNX Runtime DirectML EP](https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html)
- [microsoft/onnxruntime (MIT)](https://github.com/microsoft/onnxruntime)
- [nietras - ORT TensorRT/CUDA/DirectML on RTX 3070](https://nietras.com/2021/01/25/onnxruntime/)
- [Ultralytics YOLO11 model card](https://docs.ultralytics.com/models/yolo11/)
- [TensorRT 10.8 release notes (Blackwell / GeForce 50-series)](https://docs.nvidia.com/deeplearning/tensorrt/10.16.0/getting-started/release-notes-10/10.8.0.html)
- [OpenVINO performance benchmarks](https://docs.openvino.ai/2025/about-openvino/performance-benchmarks.html)
- [NVIDIA MPS docs](https://docs.nvidia.com/deploy/mps/latest/index.html) / [nvidia-cuda-mps-control manpage](https://man.archlinux.org/man/extra/nvidia-utils/nvidia-cuda-mps-control.1.en)
- [MIG supported GPUs](https://docs.nvidia.com/datacenter/tesla/mig-user-guide/latest/supported-gpus.html)
- [CUDA Runtime API - stream management](https://docs.nvidia.com/cuda/cuda-runtime-api/group__CUDART__STREAM.html)
- [D3D12_COMMAND_QUEUE_PRIORITY](https://learn.microsoft.com/en-us/windows/win32/api/d3d12/ne-d3d12-d3d12_command_queue_priority) / [DirectX-Specs dynamic priority](https://microsoft.github.io/DirectX-Specs/d3d/D3D12_CommandQueue_Dynamic_Priority.html)
- [D3DKMTSetProcessSchedulingPriorityClass](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/d3dkmthk/nf-d3dkmthk-d3dkmtsetprocessschedulingpriorityclass) / [D3DKMT_SCHEDULINGPRIORITYCLASS](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/d3dkmthk/ne-d3dkmthk-_d3dkmt_schedulingpriorityclass)
- [Pascal Tuning Guide - Compute Preemption](https://docs.nvidia.com/cuda/pascal-tuning-guide/index.html) / [WDDM GPU Preemption](https://learn.microsoft.com/en-us/windows-hardware/drivers/display/gpu-preemption) / [TDR registry keys](https://learn.microsoft.com/en-us/windows-hardware/drivers/display/tdr-registry-keys)
- [Hardware-Accelerated GPU Scheduling](https://devblogs.microsoft.com/directx/hardware-accelerated-gpu-scheduling/)
- [nvidia-smi manual](https://docs.nvidia.com/deploy/nvidia-smi/index.html) / [NVCP Manage 3D Settings](https://www.nvidia.com/content/Control-Panel-Help/vLatest/en-us/mergedProjects/nv3d/Manage_3D_Settings_(reference).htm)
- [NVIDIA/DeepStream](https://github.com/NVIDIA/DeepStream) / [Gst-nvtracker](https://docs.nvidia.com/metropolis/deepstream/dev-guide/text/DS_plugin_gst-nvtracker.html) / [DeepStream on WSL2](https://docs.nvidia.com/metropolis/deepstream/dev-guide/text/DS_on_WSL2.html)
- [blakeblackshear/frigate](https://github.com/blakeblackshear/frigate) / [Frigate motion detection](https://docs.frigate.video/configuration/motion_detection) / [Frigate installation](https://docs.frigate.video/frigate/installation)
- [tryolabs/norfair](https://github.com/tryolabs/norfair) / [norfair on PyPI](https://pypi.org/project/norfair/)
- [Ultralytics licence](https://www.ultralytics.com/license) / [RT-DETR (Apache-2.0)](https://github.com/lyuwenyu/RT-DETR) / [YOLOX (Apache-2.0)](https://github.com/Megvii-BaseDetection/YOLOX/blob/main/LICENSE)
- [Characterizing Concurrency Mechanisms for NVIDIA GPUs (arXiv)](https://arxiv.org/pdf/2110.00459)
- [AMD Ryzen 7000 RDNA2 iGPU specs](https://videocardz.com/newz/amd-confirms-ryzen-7000-integrated-rdna2-graphics-features) / [DirectML adapter selection](https://github.com/microsoft/DirectML/blob/master/DxDispatch/doc/Guide.md)
