# CV-1: Frame Capture on Windows with a Fullscreen/Borderless League Client

Research slice 1 of the RC computer-vision program. Scope: how to get pixels off the
screen fast enough for a sub-100ms coaching loop, on Legion (Windows 10 Pro 19045),
with League running on the SAME PC under Riot Vanguard.

Everything below is either cited to a primary source or explicitly marked UNVERIFIED.
No benchmark figure in this document was invented.

---

## 0. SCOPE FENCE - what CV is allowed to be for

Riot's Live Client Data API at `https://127.0.0.1:2999` already returns, for free, with
zero latency and zero error rate: exact **gold**, **CS (creepScore)**, **items owned +
slot**, **level**, **KDA**, **ability ranks (abilities Q/W/E/R level)**, **respawnTimer**,
**isDead**, **scores**, and a full **event feed** (kills, dragons, barons, turrets, aces).

**Any capture recommendation whose payoff is re-deriving gold, CS, items, level, KDA, or
ability ranks from pixels is WRONG and is dropped on sight.** That is strictly worse data
obtained at strictly higher cost with a nonzero error rate.

This has a direct consequence for RC's own plan doc: `docs/OBS_CV_MINIMAP_PLAN.md` section
3 row #2 ("Timer / gold / level / CS / KDA - OCR - extend to all coaches' TIERED_FIELDS -
Replaces Sonnet: Yes") should be **struck**. Not because OCR cannot read those numbers, but
because `:2999` already hands them over exactly. Row #6 in that table already reached the
same conclusion for death timers and was correctly pruned on 2026-07-05; row #2 is the same
mistake still standing. (Row #2 has residual value only as a degraded-mode fallback for a
`:2999` outage, which on a 1-PC ADR-011 topology is not a real failure mode.)

The **only** things CV legitimately buys RC, i.e. the gap `:2999` does not fill:

| Gap | Why :2999 cannot serve it |
|---|---|
| Summoner-spell + ability **cooldowns** (self, ally, enemy) | `:2999` exposes no cooldown timers at all |
| **Cast / ability-usage events** (utilization telemetry) | `:2999` has no per-cast event |
| **Minimap champion identity + position** | `:2999` has no coordinates (memory `reference_liveclient_no_positions`) |
| **Recall channel** in progress | no API signal |
| **Enemy/ally HP + mana bars** for non-self players | `:2999` gives self only, enemies not at all |
| **Objective spawn state** from the on-screen timer/icon | only static schedule otherwise |
| **Fog-of-war / vision state** | not exposed |

Every capture path below is judged **only** on how well it serves that list. The list is
dominated by two things: **small crops** (a ~416px minimap, a few HUD strips) needed at
**high cadence** (10-30 FPS, because a cooldown sweep and a roam are transient), not
full 2560x1440 frames at 2s.

---

## 1. RC's CURRENT BASELINE (read, not researched)

Verified by reading the files, not assumed:

| Component | What it actually does today |
|---|---|
| `core/screen_grab.py:33-45` | `PIL.ImageGrab.grab()` - single GDI BitBlt of the **entire primary desktop** at native res, then `JPEG q92` encode, then `base64`. Returns a dict. |
| `core/vision_profiles.py:309-310` | Same `PIL.ImageGrab.grab` seam, injectable `_grabber`. |
| `core/minimap_blob_detect.py:357-361` | `ImageGrab.grab()` **full desktop**, then crops the ~416px minimap out of it. Pure-numpy blob detect, deliberately no OpenCV. |
| `vision_server/_frame.py` | In-process self-grab, **downscales every frame to 1280 wide**, throttled ~1/1.5s, serves `:8889/latest-frame`. |
| `screen_agent.py` | DISABLED, no scheduled task (per `docs/ARCHITECTURE.md:233`). Historical DXGI agent, retired. |
| `core/obs_frame_source.py` + `core/obs_publisher.py` | OBS-WebSocket v5 `GetSourceScreenshot` -> base64 JPEG. **DEFAULT OFF** (`obs.frame_source`). Tested by `tests/test_obs_frame_source.py` against a stubbed WS, never live. |
| Cadence | ~2s POST / 1.5s throttle. Operator plays at **2560x1440** (memory `reference_vision_ocr_capture_pipeline`). |

So the baseline is: **GDI BitBlt of a 2560x1440 desktop, at best 1 frame per 1.5s, then a
JPEG encode, then base64, then HTTP over localhost.** Three full CPU roundtrips and an
image codec per frame, to deliver data that is then mostly cropped away.

That is a completely reasonable design **for feeding an LLM every 2 seconds**. It is not a
design that can hold 10-30 FPS, and no amount of tuning makes it one. The upgrade is not
"make the 2s lane faster" - it is "add a second lane that never touches JPEG, base64, or
HTTP."

---

## 2. CAPTURE COMPARISON TABLE

| API | Zero-copy GPU-side? | Measured FPS cost to the game | Fullscreen behaviour | Can target ONE window while game is fullscreen? | Wrapper + version + licence | Verified? |
|---|---|---|---|---|---|---|
| **DXGI Desktop Duplication** | **YES to the surface.** `AcquireNextFrame` hands back an `IDXGIResource` -> `ID3D11Texture2D`, i.e. a live GPU texture; MSDN: "apps can use the full power of the GPU to process the image updates". Format always `DXGI_FORMAT_B8G8R8A8_UNORM`. Also gives `GetFrameDirtyRects` / `GetFrameMoveRects` so you can skip unchanged pixels. Becomes a CPU roundtrip only when you copy to a staging texture - which every Python wrapper does. | **No quantified in-game FPS-loss figure found.** GStreamer/LosslessScaling community position: DXGI is the lower-overhead of the two and is "ultra-efficient for full-screen capture". Treat the number as UNVERIFIED. | Exclusive fullscreen: MS's own "ways to capture the screen" says most FSE D3D/OpenGL apps cannot be captured, **but DX11.1+ exclusive-mode apps can**, unless they opt out. Borderless: fine. | **NO.** Duplicates a whole display **output**. There is no window-scoped mode. You crop by coordinates and you will capture RC's own overlay if it sits on top. | `dxcam` **0.3.0** (2026-03-12), **MIT**, Python >=3.10, wheels cp310-cp314. Fork `bettercam` **1.0.0** (2023-11-22), **MIT**, Python >=3.8, but pulls in OpenCV as a hard dep. | Version/licence/date: VERIFIED from PyPI. GPU-surface claim: VERIFIED from MSDN. Window-targeting impossibility: VERIFIED. |
| **Windows.Graphics.Capture (WGC)** | **YES to the surface.** `Direct3D11CaptureFrame.Surface` is an `IDirect3DSurface` backed by `ID3D11Texture2D`, pulled from a `Direct3D11CaptureFramePool` you created on your own D3D device. Frames arrive by `FrameArrived` event or `TryGetNextFrame` pull. CPU roundtrip only on your own readback. | **No quantified in-game FPS-loss figure found.** OBS community measurement position: WGC and BitBlt are "roughly the same performance"; WGC has "slightly more overhead than DXGI, though usually negligible". UNVERIFIED as a number. | **Exclusive fullscreen: NOT RELIABLE.** Microsoft Q&A (Jack Dang, MS External Staff, 2026-03-02): "true Exclusive Fullscreen can bypass that system, capture in this mode is not guaranteed and may behave inconsistently". **Borderless fullscreen is the documented supported configuration**: "Borderless Fullscreen keeps the game inside the normal desktop composition process ... which is why WGC works reliably in that mode." | **YES - this is WGC's decisive advantage.** `GraphicsCaptureItem` can be created from an HWND. Per-window capture is **occlusion-proof**: the target renders even when covered (OBS forum). That means RC's own overlay no longer pollutes the frame. | `windows-capture` **2.0.0** (2026-04-14), **MIT**, Rust+Python, exposes `window_name`, `frame.to_numpy(copy=False)`. Also `winrt-Windows.Graphics.Capture` (raw WinRT projection, MIT) if you want to hold the D3D surface yourself. | Surface type + frame model: VERIFIED from Microsoft Learn (doc dated 2026-05-13). Fullscreen caveat: VERIFIED from MS Q&A. Package version/licence: VERIFIED from PyPI. |
| **OBS + obs-websocket** | **NO - worst case of all four.** `GetSourceScreenshot` makes OBS render the source, **encode to PNG/JPEG**, **base64** it, ship it over a localhost WebSocket, then your Python base64-decodes and PIL-decodes it. Two CPU roundtrips plus two image-codec passes per frame, plus a socket. | Not measured. **Structurally** this is the JPEG+base64 path RC already has, with a second process and a socket bolted on. | Depends entirely on which OBS source type - see VANGUARD FLAGS, this is where the landmine is. | Yes via a Window Capture source - but see the Vanguard flag; and the throughput makes it moot. | `obs-websocket-py` **0.5.3**, **MIT**, but **no PyPI release in over 12 months, flagged as low-attention/possibly discontinued**. Live alternatives: `obsws-python` 1.6.0 (v5 SDK), `simpleobsws`. **RC should add none of them** - `core/obs_publisher.py` already speaks OBS-WS v5 correctly with raw `websockets`, incl. the SHA256 auth handshake and the recv-queue drain fix. | Package status: VERIFIED. Throughput: **UNVERIFIED as a number**, asserted only as a structural argument from the documented request shape. |
| **PrintWindow (window-directed GDI)** | **NO. Always a CPU roundtrip.** Blits into an HBITMAP/DIB section through GDI. `PW_RENDERFULLCONTENT` (Windows 8.1+) is required for any DirectComposition / hardware-accelerated window. | Not measured; the cost is a synchronous `WM_PRINT` into the target window, which is a cost paid **by the game's own message loop**, not by your process. That is the wrong place to pay it. | Cannot work at all in exclusive fullscreen (no composed window content to print). On a D3D swapchain-rendered client area the result is typically a black rectangle even with `PW_RENDERFULLCONTENT`. | Nominally yes (it takes an HWND) - but see previous column; for a D3D game this is the option that names the right target and returns the wrong pixels. | Pure `ctypes`/`pywin32`, no wrapper needed. | Flag semantics + 8.1 requirement: VERIFIED from Microsoft Learn. **Black-frame-on-D3D behaviour: PARTIALLY VERIFIED** - widely reported, no clean primary source located. Marked UNVERIFIED below. |
| *(baseline for reference)* **GDI BitBlt** - what RC uses now | NO. `PIL.ImageGrab` / `mss` both BitBlt into system memory. | DXcam README benchmark, counting **newly rendered frames only**: `python-mss` **75.87 FPS avg, sd 0.5447** vs DXcam **239.19, sd 1.25** vs D3DShot **118.36, sd 0.3224**. | Occlusion-blind (grabs whatever is on top, including RC's own overlay). Unreliable under exclusive fullscreen. | No. | `mss` **10.2.0** (2026-04-23), **MIT**, Python 3.9-3.14, zero deps. `Pillow` ImageGrab (HPND). | Benchmark: VERIFIED as quoted from the DXcam README - **but the capture resolution for that table is NOT stated in the source.** See UNVERIFIED. |

### Max sustainable FPS at 1080p and 1440p

Being precise about what is and is not known here, because this is the number most likely
to be fabricated:

- **1080p, DXGI/dxcam:** the PyPI project description claims "240+ fps on 1080p". The
  README benchmark table (239.19 avg) does **not** state its resolution, so the 1080p
  attribution comes from the package description, not the table. Call it **>=240 FPS at
  1080p, VERIFIED-as-claimed-by-vendor**, not independently reproduced.
- **1440p, any API:** **NO published figure was found for 2560x1440.** UNVERIFIED. Do not
  quote one.
- What *can* be stated without a benchmark, as arithmetic: a 2560x1440 BGRA frame is
  **14.06 MiB**; 1920x1080 BGRA is **7.91 MiB**. At 30 FPS that is **422 MiB/s** and
  **237 MiB/s** of GPU->CPU readback respectively. A PCIe x16 link absorbs that without
  noticing. **A JPEG encoder does not.** This is the whole argument in one line: the
  bottleneck in RC's current path is not the capture, it is the `JPEG q92 + base64` in
  `core/screen_grab.py:41-43`.
- Practical ceiling for all three DWM-based paths is the **monitor refresh rate**, since
  both DXGI and WGC deliver on composition, not on demand. One open report (Apollo issue
  #676) claims WGC is pinned at 60 FPS where DXGI reached 120 on the same box; that is a
  single unresolved report - **UNVERIFIED**, but if RC ever wants >60 FPS capture it is the
  first thing to test.

### Verdict: which paths can hold a 10-30 FPS budget

| Path | Holds 10-30 FPS at 1440p? |
|---|---|
| WGC (`windows-capture`) window-directed | **YES.** The design target. |
| DXGI (`dxcam`/`bettercam`) display-scoped | **YES**, with the caveat that it captures the overlay too. |
| GDI BitBlt **of a crop rect only** (`mss` with a bbox) | **PROBABLY YES for 10 FPS**, marginal at 30. Zero new deps. Still occlusion-blind. |
| GDI BitBlt of the **full desktop** (RC today) | **NO.** |
| OBS `GetSourceScreenshot` | **NO.** |
| PrintWindow | **NO.** |

---

## 3. RECOMMENDED PATH, with assembly order

Target configuration: **League set to Borderless (not Exclusive Fullscreen)** + **WGC
window-directed capture** + **GPU-side crop before readback** + **an in-process fast lane
that never encodes an image**.

Rationale in one sentence: WGC is the only one of the four that can name the League window
while the game is fullscreen, is occlusion-proof so RC's own overlay stops corrupting its
own input, hands back a GPU texture, and involves no injection whatsoever.

**Prerequisite (operator action, blocking):** confirm League's video setting is
**Borderless**. If it is Exclusive Fullscreen, WGC capture is explicitly "not guaranteed"
per Microsoft, and DXGI becomes the only reliable option. This is a one-click setting and
it decides the whole architecture. **Do not build until it is checked.** Microsoft's own
note is that on modern Win10/11 + DX12 the FPS difference between exclusive and borderless
is "often minimal in real-world scenarios", so the cost of switching is low.

### Assembly order

**Step 0 - free win, zero new dependency, do this first regardless.**
Stop grabbing 2560x1440 and throwing 95% of it away. `PIL.ImageGrab.grab(bbox=...)` and
`mss` both take a bounding box. `core/minimap_blob_detect.py:357-361` currently grabs the
full desktop and then crops ~416px out of it; grabbing the 416px rect directly is a ~38x
reduction in pixels moved. Same for the HUD strips in `core/vision_profiles.py`. This alone
may get the minimap lane to 10 FPS without adding a single package, and it is a Tier-1
change to an already-injectable `_grabber` seam.

**Step 1 - `pip install windows-capture==2.0.0` (MIT). Prove one frame.**
Open a WGC session on the League HWND by `window_name`, pull one frame, `to_numpy(copy=False)`,
assert the shape matches the client rect and that the pixels are not black. Assert it still
returns real pixels **while the RC overlay is on top of the game** - that occlusion test is
the entire reason for choosing WGC over DXGI, so it is the acceptance criterion, not a
nice-to-have.

**Step 2 - new fast lane, parallel to `:8889`, NOT through it.**
Add an in-process ring buffer of the latest WGC frame plus its pre-computed crops. The
deterministic CV consumers (`minimap_blob_detect`, `_bar_fill_pct`, `_ult_pct`,
`_ocr_cooldown`) read numpy views out of that buffer directly. **No JPEG. No base64. No
HTTP.** Keep `:8889/latest-frame` exactly as it is, still at 2s, still JPEG+base64, still
downscaled to 1280 - it feeds Sonnet, and 2s/1280px is the correct spec for that job.
Two lanes, two cadences. Do not merge them.

**Step 3 - keep the GDI path as fallback, behind a flag.**
`core/screen_grab.py` stays. WGC has a real failure mode (exclusive fullscreen, and the
yellow border, below) and RC's fail-soft discipline applies. Config-gate the WGC lane
default-OFF, shadow it against the GDI grab, and flip only on live agreement - the same
do-not-flip-blind pattern `docs/OBS_CV_MINIMAP_PLAN.md` section 6 already mandates.

**Step 4 - only then, the CV consumers.** Cooldown sweep tracking, minimap identity, recall
detection. Those are slices 2+ of this program, not this one.

### The yellow-border problem - read before committing

WGC draws a **system-enforced yellow notification border** around the captured window,
visible to the user (though not in the captured frames). It cannot simply be turned off:

- `GraphicsCaptureSession.IsBorderRequired` exists from build **10.0.20348.0**, but the
  ability to actually turn the border off is **Windows 11 only**.
- **Legion is Windows 10 Pro 19045.** On this box the border is **not removable via the API**.
- Even on Win11 it requires `GraphicsCaptureAccess.RequestAccessAsync(Borderless)` plus a
  `graphicsCaptureWithoutBorder` manifest capability; deny the consent and the setter
  silently no-ops.

**This is the single biggest strike against WGC for RC**, and it is a UX strike, not a
technical one: a permanent yellow rectangle around League for the whole game. Two honest
responses: (a) test whether it is tolerable in practice at 1440p borderless, or (b) fall
back to **DXGI/`dxcam` display capture**, which draws no border at all, and accept that RC's
overlay will appear in the captured pixels - solvable by placing the overlay outside the crop
rects RC actually reads, which for a minimap in the screen corner is genuinely feasible.

Decide this by looking at it once, not by reasoning about it. It is a five-minute test.

### Upgrade delta over each existing RC component

| RC component today | The upgrade |
|---|---|
| `core/screen_grab.py` - full-desktop GDI BitBlt, JPEG q92, base64 | Add a bbox parameter (Step 0). Longer term, a WGC-backed sibling that returns a **numpy view, not a base64 JPEG**, for consumers that are not shipping bytes over HTTP. The base64+JPEG is correct for the `:8889` relay and wrong for everything else. |
| `core/vision_profiles.py:309` `ImageGrab.grab` seam | Already has an injectable `_grabber`. Point it at the WGC lane; no structural change needed. Good design, already there. |
| `core/minimap_blob_detect.py:357` full grab then crop | Biggest single win in the codebase. Direct-crop (Step 0), then WGC (Step 1). Minimap roam-tracking is worthless at 1/1.5s and useful at 10 FPS - this is the component whose *capability* changes, not just its speed. |
| OBS frame source (`core/obs_frame_source.py`, `tests/test_obs_frame_source.py`, plan O2) | **Drop from the realtime path.** Not for lack of quality - for the base64-JPEG-over-WebSocket round trip, and for the Vanguard flag below. Keep OBS for what it is uniquely good at: `SaveReplayBuffer` on a detected death/teamfight, and `StartRecord`/`StopRecord` for post-game review (plan O3). That part of the plan is sound. |
| `docs/OBS_CV_MINIMAP_PLAN.md` O2 rationale | **Factually wrong and should be corrected.** It says OBS Game Capture gives RC "the per-window Windows.Graphics.Capture technique for free". OBS **Game Capture** is not WGC - it is `graphics-hook64.dll` injected into the game process. OBS **Window Capture** with method "Windows 10 (1903 and up)" is the WGC one. The doc has picked the injection-based source and described it as the API-based source. See flags. |
| `:8889` 2s POST lane | **Leave it alone.** It is correctly specced for LLM scene vision. Add a second lane; do not retarget this one. |

---

## 4. WHERE IT STOPS BEING GOOD ENOUGH

Honest limits of the recommended path:

1. **Exclusive fullscreen kills WGC.** Not degrades - kills. If the operator ever flips
   League back to Exclusive Fullscreen, the fast lane goes dark. Mitigation: detect the
   window style at session start and fail loudly to the DXGI fallback rather than serving
   stale or black frames. A wrong deterministic read is worse than no read.
2. **Windows 10 caps the border fix.** As above. This does not improve until Legion moves to
   Windows 11, which is not a CV decision.
3. **Refresh-rate ceiling.** DWM-composited capture cannot exceed the monitor refresh, and
   possibly not 60 FPS under WGC (UNVERIFIED). Anything needing per-frame precision - exact
   ability cast frames, animation-cancel detection - is out of reach. 30 FPS resolves a
   cooldown sweep and a roam; it does not resolve a 6-frame cast animation.
4. **Capture is not the last bottleneck, it is the first.** Solving capture moves the
   bottleneck to OCR. Tesseract at 4x-upscale-and-binarize per snippet
   (`core/vision_tesseract._preprocess`) is not a 30 FPS component. Template matching for
   minimap identity needs OpenCV, which is not installed in the Python314 runtime. Budget
   the sub-100ms target across capture + preprocess + match, not against capture alone -
   capture is probably going to end up the cheapest third of it.
5. **Occlusion within the game.** WGC solves *RC's overlay* occluding the game. It does
   nothing about champions occluding each other on the minimap, ping animations distorting
   portraits, or a recall icon covering a health bar. Those are CV-accuracy problems and no
   capture API touches them.
6. **The scope fence is load-bearing.** If the CV program drifts back toward reading gold
   and CS off pixels, the entire latency budget gets spent re-deriving data that `:2999`
   hands over exactly. Re-read section 0 before adding any consumer.

---

## 5. VANGUARD FLAGS (whole-report scope)

### What Riot actually says

Primary source: **Riot Vanguard FAQ for Third Party Applications**,
`https://www.riotgames.com/en/DevRel/vanguard-faq`, dated **2024-04-01**, covering **League
of Legends and TFT** (not Valorant). Direct quotes:

- **Memory reading:** "External tools reading memory will no longer work, and you'll need
  to change methods."
- **Overlays:** "Overlays and internal tools using the API, game client, and in-game APIs
  should continue to function."
- **No allowlist:** "There is absolutely no allow list for Vanguard."

Riot support material additionally lists **code injection**, **automated inputs**, and
**private executables that read game memory** as prohibited.

**Precision note, stated because it matters:** the Vanguard FAQ **does not explicitly
mention screen capture or OCR** in either direction. The working position "external screen
capture is permitted" is an **inference** from (a) the explicit permission for overlays and
(b) the absence of capture from the prohibited list, combined with the observable fact that
OBS Display Capture and Window Capture work on League today. It is a well-founded inference
and it is what RC has operated on since inception. It is not a Riot quotation, and this
report will not dress it up as one.

### Techniques in this report, classified

| Technique | Verdict |
|---|---|
| **DXGI Desktop Duplication** (dxcam, bettercam, mss, RC's GDI BitBlt) | **SAFE.** OS-level display duplication. Never touches the game process - it reads the composited desktop output. No handle to League is opened. |
| **Windows.Graphics.Capture** (windows-capture, winrt projection) | **SAFE.** A documented WinRT API operating inside DWM composition. Creating a `GraphicsCaptureItem` from an HWND is not injection and not memory reading; the game process is never opened, written, or hooked. Notably, WGC is *how Windows itself* implements Game Bar capture. |
| **PrintWindow** | **SAFE** in the Vanguard sense (it is a documented user32 message send, not a hook), though it is technically useless here. |
| **An overlay window** (RC's Electron overlay, `:8888` dashboard) | **EXPLICITLY PERMITTED** by the FAQ quote above. |
| **Reading `:2999` Live Client Data and the LCU** | **EXPLICITLY PERMITTED** - "using the API, game client, and in-game APIs". |
| **OBS Game Capture** | **FLAGGED - BANNED TECHNIQUE. Do not use, do not plan around, do not ship.** OBS Game Capture works by **injecting `graphics-hook64.dll` into the game process** to intercept the present/swapchain. That is textbook code injection and it is exactly what Vanguard prohibits. This is not theoretical: **obsproject/obs-studio issue #11879, "Game Capture fails to hook League of Legends on OBS 31.0.1 / 31.0.0"**, is the live bug, with the OBS-side guidance being to use Window or Display Capture instead. Anti-cheat systems broadly (Vanguard, EAC, BattlEye, FACEIT) block it. |
| **OBS "anti-cheat compatibility hook"** | **FLAGGED - STILL AN INJECTION.** It merely switches to a *different* injection method that some anti-cheats tolerate. Tolerated is not permitted, and there is no allowlist. Do not use it as a workaround. |
| **OBS Window Capture, method "Windows 10 (1903 and up)"** | **SAFE** - this is WGC under the hood, no injection. |
| **OBS Window Capture, method "BitBlt"** | **SAFE** - GDI, no injection. |
| **OBS Display Capture** | **SAFE** - DXGI or WGC, no injection. |
| **Any capture library advertising "hook the swapchain", "present hook", "D3D hook", "inject", or "overlay via hook"** | **BANNED.** This is the class that gets accounts banned, and several popular capture wrappers are in it. Screen it explicitly before adding any capture dependency: if the README mentions hooking Present/EndScene/vkQueuePresent or injecting a DLL, reject it regardless of how fast it benchmarks. |
| **Reading League process memory for cooldowns/positions** | **BANNED** and explicitly named by Riot. Note the temptation: memory reading would trivially solve every gap in section 0's table. It is still banned. CV exists precisely because this route is closed. |

### The one correction this slice forces on RC's existing plans

`docs/OBS_CV_MINIMAP_PLAN.md` section 2, item **O2**, currently reads: "OBS Game Capture is
OCCLUSION-PROOF ... RC gets the per-window Windows.Graphics.Capture technique for free via
OBS instead of vendoring a GPL capture tool."

That sentence conflates two different OBS sources. **Game Capture is the injecting one.**
The occlusion-proof-via-WGC property belongs to **Window Capture (Windows 10 1903+ method)**.
The same section's Vanguard table row ("O2 OBS frame -> :8889 | Safe (OBS Game Capture, runs
today)") inherits the error and marks an injection-based path as Safe.

The plan's *conclusion* - that RC wants occlusion-proof per-window capture - is right. Its
*named mechanism* is a banned technique. And since this slice recommends dropping the OBS
frame path anyway on throughput grounds, the clean fix is to take WGC **directly** via
`windows-capture` rather than laundering it through OBS. Same technique, one less process,
one less JPEG, one less socket, and no ambiguity about which OBS source got configured.

---

## 6. UNVERIFIED LIST

Everything below is stated somewhere in this report as qualified, and is listed here so it
is never quoted as fact:

1. **In-game FPS cost of any capture API.** No quantified "capture costs N% of game FPS"
   benchmark was located for DXGI, WGC, or GDI. All qualitative ("negligible", "roughly the
   same"). **RC should measure this itself on Legion** - it is a one-game A/B.
2. **Capture resolution of the DXcam benchmark table** (239.19 / 75.87 / 118.36 FPS). The
   README does not state it. The "240+ fps on 1080p" attribution comes from the PyPI project
   description, a different and weaker source than the table.
3. **Any 1440p capture-throughput figure, for any API.** None found. The 14.06 MiB/frame and
   422 MiB/s figures in this report are **arithmetic**, not measurements, and are labelled as
   such.
4. **WGC 60 FPS ceiling.** One open, unresolved report (ClassicOldSong/Apollo issue #676)
   claims WGC pins at 60 where DXGI reached 120. Single source, no confirmation, no fix.
5. **PrintWindow returning black on a D3D-rendered client area.** Widely reported in
   community threads; no clean primary source found. The `PW_RENDERFULLCONTENT` flag
   semantics and its Windows 8.1 minimum **are** verified from Microsoft Learn.
6. **`GetSourceScreenshot` throughput.** No benchmark found. The "cannot hold 10-30 FPS"
   verdict is a structural argument from the documented request shape (render -> encode ->
   base64 -> WebSocket -> decode -> decode), not a measurement.
7. **`windows-capture` version.** PyPI shows **2.0.0 (2026-04-14)**; libraries.io still shows
   1.5.0. Trust PyPI, but pin explicitly and re-check at install time.
8. **`windows-capture` minimum Windows version.** Not stated in its docs. WGC itself is
   Win10 1803+ for the base API and 1903+ for the broader capture surface OBS relies on.
   Legion at 19045 clears both, so this is a portability footnote only.
9. **League of Legends' current display mode on Legion** (Exclusive Fullscreen vs Borderless).
   **Not probed by this slice.** It is the single blocking prerequisite for the recommended
   path and must be checked before any code is written.
10. **Whether the WGC yellow border is tolerable in practice** at 1440p borderless. Cannot be
    reasoned about; must be looked at once.
11. **Riot's position on screen capture specifically.** Inferred, not quoted - see section 5.
    The FAQ is silent on capture and OCR.
