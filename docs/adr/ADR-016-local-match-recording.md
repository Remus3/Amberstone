# ADR-016: Local match recording through OBS (lifts ADR-009's video-capture deferral)

**Date:** 2026-10-04
**Status:** Accepted 2026-10-04 after distinct adjudication (rulings written into this record
below). Amends ADR-009: its "future operator-gated slice MAY add local OBS video capture ... its
own ADR" clause is discharged by this record; ADR-009's decision that the Replay view is
Match-V5-timeline-driven is UNCHANGED.

## Context

ADR-009 made the Match-V5 timeline the canonical event source for the Replay view and deferred
local video capture to "a future operator-gated slice ... its own ADR + its own dependency
decision". The 2026-10-04 external-lift intake filed the recording track as RM-637..RM-641
(directive items X-37..X-41, behaviour observed in external references C, E, G and H; every
item is re-implemented clean-room, nothing is vendored, NOTICE delta zero), filed AGAINST
`docs/OBS_CV_MINIMAP_PLAN.md` O3, which already planned `StartRecord` / `StopRecord` /
`SaveReplayBuffer`.

**Reason for lifting the deferral: operator approval.** On 2026-10-04 the operator approved the
recording track in their own words, "those 3 items are approved", relayed into the intake session
by its coordinating session, with the instruction to write this ADR first, then build
RM-637..RM-641 in order, to batch every physical / credential act into ONE operator ask, and to
keep the disk guard and the retention dry-run default ON.

Ground truth this ADR stands on (measured, not assumed):
- LIVE_GAME_GATED_SYNC G6-03 (closed 2026-08-02) drove `StartRecord` by harness over
  `127.0.0.1:4455` (OBS 32.1.2, obs-websocket 5.7.3): about 6.35 GB per 25-minute match at
  2560x1440@60 (4.2 MB/s decimal, about 4.5 if the figure was GiB; a low-motion ARAM match), zero
  capture stalls by the `outputDuration` delta check. Its scope fence holds: it proves continuous
  display capture at a LOCKED resolution only.
- ADR-011: OBS records via Display / Window Capture (WGC); Game Capture (hook injection) trips
  Vanguard and is never used.
- Production code has NO record call today. `core/obs_publisher.py` already owns a fail-soft
  obs-websocket v5 client with a request/response lane; `config/coach_settings.json` (gitignored)
  carries the `obs` block, currently `enabled: false` with a password set.
- 2026-10-04 probe: OBS not running; system drive 140 GB free of 954 GB.

Alternatives considered:
1. **Keep deferring (status quo).** Rejected: the operator approved the track; the event sidecar
   already exists, so video is the missing half of the review loop.
2. **Embed a capture library (libobs, a patched OBS build, an FFmpeg / GPU-encoder pipeline in
   RC).** Rejected: licence-blocked (copyleft) or vendoring, a large new dependency on a 1-PC box
   that already runs League + Vanguard + RC, and it duplicates an OBS install the operator owns.
3. **Windows.Graphics.Capture directly into RC's own encoder.** Rejected for recording (kept as the
   frame-provider idea in the OBS plan): RC would own an encoder, a muxer and crash recovery.
4. **Drive the operator's existing OBS over obs-websocket (CHOSEN).** Zero new dependency, the
   transport is already in-tree and was proven live by G6-03, and the operator keeps full control
   of the encoder and profile.

## Decision

RC drives the operator's own OBS over obs-websocket to record matches, as an ADDITIVE layer: the
Match-V5 timeline stays the Replay view's source of truth and video only attaches to it.

- **Opt-in and default OFF.** Nothing records unless `obs.record.enabled` is true in the gitignored
  config AND the mode / queue is opted in through `core/feature_policy.py`.
- **Ownership.** The ownership token is the `outputPath` carried by the RecordStateChanged STARTED
  event that follows RC's own StartRecord. RC stops a recording only while that path is still the
  active one. If OBS is already recording when a game starts, RC starts nothing, never stops it,
  and the sidecar records `owner=operator`. The replay buffer follows the same rule.
- **Never alter the operator's OBS.** No SetRecordDirectory, no scene, source, profile or
  output-format writes. Probes are reads only (`GetVersion`, `GetProfileParameter`): chapters are
  used only when the current profile's record format is hybrid MP4 and obs-websocket is >= 5.5;
  otherwise RC degrades silently to the sidecar. RC REFUSES to start if an enabled game-capture
  input is in the active scene (ADR-011).
- **Lifecycle.** Start when gameflow reaches InProgress AND the Live Client answers; stop on the
  end-of-game block or a GameEnd event, or after N CONSECUTIVE transport failures. A parse error
  or an HTTP error status never ends a recording. Subscribe to `core/lcu_events.py`, never the
  frozen `app/_game_lifecycle.py`.
- **Alignment.** A pure `core/vod_alignment.py` proves the offset only on polls where gameTime
  advanced; markers seen before proof are provisional and rewritten at finalize; video_time is
  clamped to >= 0; a game that ends before proof falls back to 1:1.
- **Sidecar is the source of truth.** `data/recordings/<matchId>.json` (gitignored, atomic write):
  output path from the StopRecord response, game_time_offset_s, queue_id, wall stamps,
  stop_reason, owner, death count, capture diagnostics, bookmarks.
- **No "RC-owned folder" is assumed.** OBS writes wherever the operator's profile points. Retention,
  the cap and file serving operate ONLY on paths recorded in RC sidecars (the StopRecord
  outputPath) plus clips RC itself produced. A folder glob is never used.
- **Disk budget.** `core/disk_guard.py` runs as its own producer (the supervisor and health monitor
  are frozen), checked every 60 s. Live rate from GetRecordStatus outputBytes deltas; fallback
  5.0 MB/s only when that read fails. Floor 20 GB free on the recording volume; finalize buffer
  2 GB; before any start require free >= floor + 8 GB AND 8 GB of room left under the 60 GB cap of
  RC-recorded bytes. On a trip: StopRecord / StopReplayBuffer ONLY for an RC-owned recording; for an
  operator-owned one RC shows the banner only. Sending files to the Recycle Bin frees no space, so
  the guard never counts on retention to recover headroom.
- **Retention.** `core/vod_retention.py` is a pure decision plus thin IO, report-first like
  `core/data_retention.py`. Keep a file if ANY holds: manual pin, mark pressed, ranked loss, PGR
  heuristic below threshold. Kept, unpinned files age out at 14 days; over the cap the oldest
  unpinned file goes first; pinned files are never touched; if pinned files alone fill the cap,
  recording refuses to start. A non-kept file becomes a deletion CANDIDATE only after its death
  reel is read back non-empty, or when the sidecar records zero deaths. Removal is a CHECKED
  send-to-Recycle-Bin that refuses to fall back to permanent deletion (Windows silently deletes
  files too large for the bin) and confirms the item landed in the bin (fleet rule 9). **Dry-run
  is the default and stays ON** until the operator turns it off; the sidecar always survives.
- **Clips.** External ffmpeg (never vendored, `CREATE_NO_WINDOW`); stream copy snaps to keyframes,
  so a 1-2 s OBS keyframe interval is an operator setting, not something RC writes.
- **Serving.** The dashboard is reachable over the tailnet and recordings carry other players'
  voices, so a local MP4 is served from `:8888` only for a path present in a sidecar, after
  resolving the real path and rejecting junctions and symlinks, behind the existing auth, with
  HTTP Range.

## Adjudication (distinct adjudicator, 2026-10-04)

The three questions the intake directive left open were ruled by a distinct read-only adjudicator
agent; the rulings ARE the bullets above. Disk budget: the draft's 4.2 MB/s x 60 s x 1.5 formula
(about 0.38 GB) was dominated by the floor and guarded nothing, so the start precondition became
floor + 8 GB with a measured live rate (alternatives: the draft; a percentage floor). Retention:
a 14-day age-out for kept unpinned files was added because keeping every ranked loss under a
60 GB cap would block recording within days (alternatives: no age limit; 30 days). OBS collision:
upheld with an outputPath ownership token, a read-only probe set and a refusal on game capture
(alternative: trust OBS's own state alone). The adjudicator also refuted four draft defects that
are fixed above: the assumed RC-owned folder, an unconditional stop on a disk trip, Recycle Bin
treated as freeing space, and a zero-death match that could never become a candidate.

## Consequences

**Good:** the review loop gets real video with zero new dependency; every OBS-side setting stays
the operator's; disk exhaustion and silent deletion are both guarded; the sidecar keeps working
even when video is absent.
**Trade-off:** one-PC load (League + Vanguard + OBS encoder + RC) - CPU and frame time must be
measured before any default-on; chapters depend on the operator's output format; a recording
exists only while OBS is running.
**Watch for:** the resolution-swap hazard G6-03 did NOT exercise. The single batched operator ask
covers: start OBS, enable its websocket server with the password already in the config, choose the
recording disk and folder, the scene's capture source (WGC display or window capture, never game
capture), a locked resolution plus Borderless (the G6-03 scope fence), the record format
(hybrid MP4 if chapters are wanted), a 1-2 s keyframe interval, and flipping `obs.record.enabled`.
No session performs any of these.
