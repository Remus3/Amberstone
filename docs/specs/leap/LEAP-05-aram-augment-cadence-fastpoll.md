# LEAP-05 - ARAM Mayhem augment-reco cadence fast-poll

> P3 AMENDMENT (judge panel 2026-07-17, supersedes conflicting text below):
> add an env kill-switch RC_ARAM_FAST_POLL (default "1" = enabled, "0" disables the
> fast-poll and leaves the legacy 25s cadence) following the RC_DUO_SYNERGY_LIVE=0
> precedent. The fast-poll raises early-game Sonnet-tier vision cost (+~5 calls
> bounded); the operator must be able to disable it live if the on-screen confirm
> shows issues. Add one AC: with RC_ARAM_FAST_POLL=0 the interval schedule is
> byte-identical to pre-change behavior.

Status: SPEC (ready to execute)
Author: spec-author agent, 2026-07-16
Owner mode: ARAM / ARAM Mayhem coach
Tier: Tier-1 (local logic, single module) - see R5 TIER
Est: 1 short session, model claude-opus-4-8, effort high

---

## GOAL

Front-load the thinking into specs; execution sessions are typing, not deciding.

Make the ARAM Mayhem augment recommendation actually fire on-screen. The detection
path and the reco path are already PROVEN working (offline, against a saved live
augment frame). The ONLY remaining blocker is vision CADENCE: the coach polls
vision every 25s, but the ARAM Mayhem augment-select panel is on screen for only
about 10-15s at game start, so the single early tick usually lands before or after
the window and the next tick is 25s later (augment already picked). Fix = a bounded
fast early-game vision poll that guarantees a tick lands inside the augment window,
without multiplying Sonnet vision calls.

---

## EVIDENCE (all citations verified live this session)

Cadence bug (root cause):
- `coaches/aram_coach.py:495` - `_VISION_INTERVAL = 25.0` (class attr on `Coach`).
  Comment lines 491-492: "Cost-tuned 2026-05-04 ... bumped from VISION 15->25 ...
  to cut API call rate ~33%." (Stale docstring at `coaches/aram_coach.py:8` still
  says "every 15s" - Tier-0 freebie to refresh while editing.)
- `coaches/_base_coach.py:449` - the vision loop gate:
  `if forced or now - self._last_vision >= self._VISION_INTERVAL:` reads the
  INSTANCE attr `self._VISION_INTERVAL` every tick. The loop sleeps 3.0s per
  iteration (`coaches/_base_coach.py:468` `await asyncio.sleep(3.0)`).
- `coaches/_base_coach.py:286` - base default `_VISION_INTERVAL: float = 15.0`.

Augment detection + reco path (PROVEN good - do NOT re-investigate):
- `modes/shared_vision.py:306-308` - `_postprocess` aliases the relay's
  `is_augment_select` to `augment_select` at the single chokepoint (fix 67519018).
- `coaches/aram_coach.py:614-615` - the gate that fires the reco:
  `if state.get("augment_select") and state.get("augment_choices"):
   self._handle_augment_select(state)`.
- `coaches/aram_coach.py:1065` - `_handle_augment_select` sends the augment reco
  (Haiku `claude-haiku-4-5-20251001`, `coaches/aram_coach.py:1086`).
- `coaches/aram_coach.py:505-534` - `_ARAM_TIERED_FIELDS` includes `augment_select`,
  `augment_choices`, `augments` with `augment_select` validator `isinstance(v, bool)`.

Augment window timing (from the offline-characterized live eyeball, cited - NOT invented):
- `docs/LIVE_GAME_GATED_SYNC.md:90-93` - "coaches/aram_coach.py:495
  `_VISION_INTERVAL=25.0` skips the ~10-15s augment window; a fast early-game poll
  fix is OWED (operator-deferred 2026-07-12); on-screen verify stays live-gated."
- Memory `open_bug_aram_augment_reco_cadence_miss` (offline root-cause 2026-07-12):
  "The ARAM Mayhem augment screen is up only ~10-15s at game start (gameTime ~0:05,
  clock frozen). The coach fires one vision tick near game start; its single sample
  usually lands before/after the brief window, and the next tick is 25s later."
  The game clock is FROZEN at ~0:05 during augment select, so `game_seconds` stays
  low for the whole window.

Game-time source for gating (numeric, already in parsed state):
- `coaches/aram_coach.py:1117` - `game_time = finite(gd.get("gameTime", 0))`.
- `coaches/aram_coach.py:1178` - parsed state returns `"game_seconds": game_time`
  (numeric seconds). The parsed state is the exact dict handed to
  `_on_state_received(state)` (`coaches/_base_coach.py` poll loop ~415-422), so
  `state.get("game_seconds")` is available there with zero new plumbing.

Existing dynamic-tunable pattern to REUSE (this is why the change stays one module):
- `coaches/aram_coach.py:559-570` - `_on_state_received` ALREADY mutates the
  instance attr `self._DEBOUNCE_S` between `type(self)._DEBOUNCE_S` (class default)
  and `self._STABLE_DEBOUNCE_S` based on state change. The vision loop reads
  `self._VISION_INTERVAL` the same way `_maybe_coach` reads `self._DEBOUNCE_S`, so
  mutating `self._VISION_INTERVAL` from `_on_state_received` (poll runs ~every 1.5s)
  flows into the next 3s vision-loop tick with no base-class edit.

Lifecycle hooks (real, invoked - confirmed):
- `coaches/_base_coach.py:308` - `self._init_extra()` called before threads start.
- `coaches/_base_coach.py:354` - `self._reset_extra()` called in `reset_state`
  (fires on each new game). ARAM coach does NOT currently override either
  (`_init_extra`/`_reset_extra` absent from `coaches/aram_coach.py`), so adding both
  overrides is additive.

Vision tier split (the Sonnet-cost coupling to guard):
- `core/vision_routing.py:46` - `read_or_escalate(img_b64, fields, validators=...,
  escalate_fn=..., shadow_fields=...)`. OCR runs first; only fields OCR could not
  validate become `missing`, and Sonnet fires ONCE per call via
  `escalate_fn(img_b64, missing)` (`core/vision_routing.py:102-110`).
- `coaches/aram_coach.py:599` - `_run_vision` calls `r.read_tiered()` exactly once
  per invocation; `read_tiered` -> `read_or_escalate` (`modes/shared_vision.py:171-211`).
- CONSEQUENCE: `augment_select` / `augment_choices` have NO OCR region in
  `data/vision_regions.json` (they are semantic panel-text fields), so they are
  ALWAYS "missing" -> every `read_tiered()` tick fires exactly one bulk Sonnet
  escalation. There is no headless OCR-only augment detector today (calibrating one
  needs a live frame, which is live-gated). Therefore "no extra Sonnet" means
  BOUNDED, not zero: reuse the single existing `read_tiered()` call site and cap the
  number of fast ticks. See DESIGN DECISIONS.

---

## SCOPE

Headless, code + tests + shadow-log only:
1. Add a bounded fast-poll cadence to `coaches/aram_coach.py` gated on
   `game_seconds` + a per-game "augment resolved" latch + a hard fast-scan cap.
2. Reuse the EXISTING `_on_state_received` dynamic-tunable pattern to mutate
   `self._VISION_INTERVAL` - NO edit to `coaches/_base_coach.py` (the loop already
   reads the instance attr each tick).
3. RED-first unit tests: cadence progression, 12s-window coverage, bounded-Sonnet.
4. Refresh the stale `coaches/aram_coach.py:8` "every 15s" docstring (Tier-0 freebie).

## NON-SCOPE (do NOT do in this session)

- The live on-screen confirm (hold an augment ~10-15s so a fast tick lands and
  verify the reco renders). This stays LIVE-GATED. The executor APPENDS a confirm
  row to `docs/LIVE_GAME_GATED_SYNC.md` (see DONE RITUAL) - it does NOT claim the
  confirm as done.
- Arena / Brawl sibling coaches (`coaches/arena_coach.py:415` `_VISION_INTERVAL=20.0`,
  `coaches/brawl_coach.py:206` `_VISION_INTERVAL=18.0`). The mechanism is class-attr
  driven and trivially portable, but Arena already has a separate round-based
  `force_scan` augment trigger (79c4e9e9 / 10374d02) so its cadence story differs.
  Port as a fast-follow LEAP once ARAM is live-confirmed.
- Any OCR-region calibration for augment fields (`data/vision_regions.json`) -
  live-gated, and not required for this fix.
- `core/moon_proxy.py` (FROZEN) and the relay path - untouched. The coach's own
  `read_tiered()` with its own `_VISION_PROMPT` (`coaches/aram_coach.py:595`) is the
  path; the relay's TFT-prompt-for-all-modes quirk means relay Sonnet fields are NOT
  relied on for augments.
- Any later / periodic ARAM Mayhem augment window (see GHOST LIST - unverified;
  the `game_seconds < window` gate covers the PROVEN game-start window only).

---

## DESIGN DECISIONS

### Poll schedule (concrete)

New class constants on `Coach` (`coaches/aram_coach.py`, near line 495):

```
_AUGMENT_WINDOW_S      = 45.0   # game_seconds ceiling for fast-poll
_FAST_VISION_INTERVAL  = 6.0    # seconds between vision scans while in window
_AUGMENT_FAST_MAX_SCANS = 6     # hard cap on fast-cadence scans per game
```

Effective interval each poll:

```
interval = _FAST_VISION_INTERVAL   IF  game_seconds is not None
                                    AND game_seconds < _AUGMENT_WINDOW_S
                                    AND not augment_resolved
                                    AND augment_fast_scans < _AUGMENT_FAST_MAX_SCANS
         = _VISION_INTERVAL (25.0) OTHERWISE
```

Rationale for the constants:
- `_AUGMENT_WINDOW_S = 45.0`: the clock is FROZEN at ~0:05 during augment select
  (evidence), so `game_seconds` stays low for the entire window; 45s gives generous
  margin for the clock to unfreeze plus a tick or two after, while remaining a tiny
  slice of a ~15-20 min ARAM game. It is the self-terminating FALLBACK cap for games
  with no augment at all (non-Mayhem ARAM) so fast-poll cannot run forever.
- `_FAST_VISION_INTERVAL = 6.0`: the augment window is ~10-15s; the vision loop
  granularity is 3.0s (`coaches/_base_coach.py:468`). 6.0s is a clean 2x-sleep
  multiple, giving inter-scan gaps <= 6s, so ANY 12s window contains >= 2 scan
  opportunities. Not lower (e.g. 3s) to avoid needless over-scanning.
- `_AUGMENT_FAST_MAX_SCANS = 6`: at 6s over the 45s window that is ~7 possible
  ticks; capping at 6 bounds worst-case extra Sonnet vision scans to about +5 vs the
  ~1 the 25s cadence would have fired in 45s. Once hit, cadence reverts to 25s even
  if `game_seconds` is still low (belt-and-suspenders against a stuck-frozen clock).

### The augment-resolved latch (primary Sonnet guard)

- New per-instance flags, set in `_init_extra` and cleared in `_reset_extra`
  (per new game): `self._augment_resolved = False`, `self._augment_fast_scans = 0`,
  `self._fast_mode = False`.
- Set the latch the instant the augment is caught + handled, right after
  `coaches/aram_coach.py:615`:
  ```
  if state.get("augment_select") and state.get("augment_choices"):
      self._handle_augment_select(state)
      self._augment_resolved = True
  ```
  The next `_on_state_received` (within ~1.5s) then reverts the interval to 25s.
  In the common case the augment is caught within the first 1-3 in-window ticks, so
  real extra Sonnet is ~2-3 scans, self-terminating - well under the cap.

### Where each piece lives (all inside coaches/aram_coach.py)

1. Pure helper (unit-testable, NO I/O, NO Sonnet, NO game):
   ```
   def _select_vision_interval(self, game_seconds, augment_resolved, fast_scans):
       try:
           gs = float(game_seconds)
       except (TypeError, ValueError):
           return type(self)._VISION_INTERVAL
       in_window = (gs < self._AUGMENT_WINDOW_S
                    and not augment_resolved
                    and fast_scans < self._AUGMENT_FAST_MAX_SCANS)
       return self._FAST_VISION_INTERVAL if in_window else type(self)._VISION_INTERVAL
   ```
   Uses `type(self)._VISION_INTERVAL` for the default so the mutated instance attr
   never feeds back into itself (same trick as the existing `type(self)._DEBOUNCE_S`
   at `coaches/aram_coach.py:569`).

2. In `_on_state_received` (after the existing debounce block, ~line 570), append:
   ```
   gs = state.get("game_seconds")
   interval = self._select_vision_interval(
       gs, self._augment_resolved, self._augment_fast_scans)
   self._VISION_INTERVAL = interval
   self._fast_mode = (interval == self._FAST_VISION_INTERVAL)
   ```

3. In `_run_vision`, after the `_fetch_game_data() is None` gate
   (`coaches/aram_coach.py:573`, KEEP it), increment the fast-scan counter when a
   scan actually runs in fast mode:
   ```
   if self._fast_mode:
       self._augment_fast_scans += 1
   ```
   The counter feeds back into `_select_vision_interval` next poll, enforcing the cap.

`_run_vision` still calls `r.read_tiered()` EXACTLY ONCE (`coaches/aram_coach.py:599`).
No second Sonnet call site is added. The fast poll changes CADENCE only, not the
per-tick vision tier behavior - this is the meaning of "pin the fast poll to the
OCR/augment-detect tier only".

### Considered and rejected

- `data/force_scan.json` one-shot force path (`coaches/_base_coach.py:434-449`,
  suggested as an alt in the memory): rejected. It is a single external-writer
  trigger, does not sustain a fast cadence across the window, and needs an outside
  process to write the file. The dynamic-interval approach is self-contained.
- Editing `coaches/_base_coach.py` `_vision_loop` to add a base-level fast-poll:
  rejected. Wider blast radius (touches SR/TFT/Arena/Brawl); the instance-attr
  mutation pattern already exists and confines the change to one module.
- A zero-Sonnet OCR-only augment detector: not possible headless. `augment_select`
  has no OCR region; the relay path is frozen + TFT-prompted. Bounded-Sonnet is the
  honest ceiling.

### Concurrency note

`_on_state_received` runs on the poll thread; `_vision_loop` reads
`self._VISION_INTERVAL` on the vision task. This is a float assignment read/written
across threads - GIL-atomic, no lock needed, identical to the already-shipped
`self._DEBOUNCE_S` dynamic mutation. No new synchronization.

---

## TESTABLE ACCEPTANCE CRITERIA (RED-first)

Write these tests FIRST and watch them fail against current code (which has no
`_select_vision_interval`, no fast constants, no latch), THEN implement.

New file: `tests/test_aram_vision_cadence_fastpoll.py`

AC-1 Cadence unit test (game_seconds progression). Instantiate `Coach` with a temp
data file (the pure helper needs no API key), then assert:
- `_select_vision_interval(5.0,  False, 0) == 6.0`   (in window -> fast)
- `_select_vision_interval(30.0, False, 0) == 6.0`   (still < 45 -> fast)
- `_select_vision_interval(45.0, False, 0) == 25.0`  (at ceiling -> default)
- `_select_vision_interval(60.0, False, 0) == 25.0`  (past window -> default)
- `_select_vision_interval(5.0,  True,  0) == 25.0`  (latch set -> default)
- `_select_vision_interval(5.0,  False, 6) == 25.0`  (cap hit -> default)
- `_select_vision_interval(None, False, 0) == 25.0`  (no game_seconds -> safe default)

AC-2 Augment-window coverage (a 12s window between polls MUST be hit). Deterministic
simulation of the real gate `now - last_vision >= interval` with
`interval = _FAST_VISION_INTERVAL`, stepping `now` by the loop sleep 3.0s and
tracking `last_vision`. Collect scan timestamps over ~0..30s. For the worst-case
augment window opening just after a scan fires, assert at least one scan timestamp
lands inside `[W_START, W_START + 12.0]`. (With interval 6.0 + 3s steps, max
inter-scan gap is 6.0s, so any 12s window contains >= 1 scan - the test encodes this
as an assertion, it does not hard-code the answer.)

AC-3 Bounded-Sonnet (no runaway multiplication). Simulate an early-game run:
increment `fast_scans` on each fast scan and re-query `_select_vision_interval`;
assert the number of fast scans NEVER exceeds `_AUGMENT_FAST_MAX_SCANS` (6). Assert
that once `augment_resolved=True`, `_select_vision_interval` returns 25.0 for every
`game_seconds < _AUGMENT_WINDOW_S` (fast cadence stops immediately on catch).

AC-4 read_tiered fired exactly once per _run_vision (no second Sonnet probe added).
Monkeypatch `modes.shared_vision.GameVisionReader.read_tiered` to a call-counter
returning a stub state `{"augment_select": True, "augment_choices": ["A","B","C"]}`;
stub `self._fetch_game_data` -> `{}` (non-None) and `core.feature_policy.is_allowed`
-> True; set `self._api_key` to a dummy string and `self._client` to a stub so
`_handle_augment_select` is patched/no-op. Call `_run_vision` once and assert
`read_tiered` was called exactly 1 time AND `self._augment_resolved` flipped to True.
(Per Testing Discipline: wrap any class-accessed method stub with `@staticmethod`
correctly; grep-confirm every stubbed attribute exists before writing.)

AC-5 Latch lifecycle: after `_init_extra()` and after `_reset_extra()`,
`self._augment_resolved is False` and `self._augment_fast_scans == 0`.

Green bar = all of AC-1..AC-5 pass, plus `tests/test_aram_state_debounce.py` still
green (the sibling dynamic-tunable test must not regress).

---

## R5 TIER

Tier-1 (local logic, single module). Justification:
- Touches ONLY `coaches/aram_coach.py` (constants, two lifecycle-hook overrides, one
  pure helper, ~5 added lines in `_on_state_received` + `_run_vision`) plus a new
  test file. No base-class edit (the loop already reads the instance attr).
- NO schema change (`game_seconds` already exists in parsed state), NO engine /
  scorer / item-effect / `ENGINE_VERSION` touch, NO Daemon Slayer surface, NO data
  file shape change. Not Tier-2.

Verification (run ONCE, trust exit code):
```
py_compile coaches/aram_coach.py
python -m pytest tests/test_aram_vision_cadence_fastpoll.py tests/test_aram_state_debounce.py -q
```
No full dual suite, no DS `:8893` restart, no RC restart required for the test/commit
(cadence takes effect on the next coach process start; a `restart_trigger.txt` bounce
is only needed to exercise it in a live game, which is the live-gated confirm).

---

## FILES TOUCHED (by the execution session)

- `coaches/aram_coach.py` - fast-poll constants + `_init_extra`/`_reset_extra`
  overrides + `_select_vision_interval` helper + `_on_state_received` interval set +
  `_run_vision` latch/counter + refresh stale line-8 docstring. NOT frozen
  (`coaches/aram_coach.py:1` header declares `frozen=no`).
- `tests/test_aram_vision_cadence_fastpoll.py` - NEW, the RED-first tests above.
- `docs/LIVE_GAME_GATED_SYNC.md` - APPEND the on-screen confirm row (DONE RITUAL).
- `docs/LEDGER.md` - APPEND the completion entry (DONE RITUAL).

Do NOT touch: `coaches/_base_coach.py`, `core/moon_proxy.py` (FROZEN),
`data/vision_regions.json`, `modes/shared_vision.py`, `core/vision_routing.py`.

---

## EST SESSIONS

1 short session. Model `claude-opus-4-8`, effort high.

---

## DONE RITUAL

1. Confirm green: `py_compile` + the two-file pytest above pass THIS run (re-read the
   result file, do not carry a prior count forward).
2. Commit (ASCII-only message, `git commit -F <tmpfile>` if any special char) + push.
3. Append an LGS confirm row to `docs/LIVE_GAME_GATED_SYNC.md` under REMAINING
   TRULY LIVE-GATED, replacing / annotating the existing ARAM-MAYHEM augment-reco
   CADENCE bullet (`docs/LIVE_GAME_GATED_SYNC.md:90-93`): note the fast-poll SHIPPED
   headless (cite the commit SHA) and that the OWED item is now ONLY the on-screen
   confirm - "play an ARAM Mayhem game, hold the augment panel ~10-15s, verify a fast
   vision tick lands and the augment reco renders on-screen". Do NOT mark it confirmed.
4. Append a per-item entry to `docs/LEDGER.md` (append-only, newest-first) - NEVER to
   CLAUDE.md. Note: cadence fix, Tier-1, headless-green, live confirm queued to LGS.
5. Optionally trigger a live exercise later: `echo restart > restart_trigger.txt`
   then verify `ops/runtime/health.json` new pid + `alive=true` - but the on-screen
   verify itself stays live-gated (needs a real ARAM Mayhem game).

---

## GHOST LIST (do NOT re-do / re-litigate)

- The LCU / :2999 augment API is a CONFIRMED dead-end (Settled) - there is no
  capture-free augment API mid-game. Do NOT re-research it. Augment-OCR (vision) is
  the proven path.
- Detection + reco + field-alias are ALREADY PROVEN GOOD (67519018 alias fix,
  offline-verified against a saved live frame). Do NOT re-investigate
  detection/alias/path - the blocker is CADENCE only.
- The vision relay runs a hardcoded TFT prompt for ALL modes
  (`core/moon_proxy.py` `/vision`), so mode-specific Sonnet fields can silently drop.
  Do NOT rely on relay Sonnet fields for augments - use the coach's own
  `read_tiered()` with `_VISION_PROMPT`.
- KEEP the `_run_vision` gate `if self._fetch_game_data() is None: return`
  (`coaches/aram_coach.py:573`) - vision must never fire during lobby/idle. The fast
  poll changes only the interval, never this gate.
- `core/moon_proxy.py` is FROZEN. This design routes AROUND it (coach-local
  instance-attr mutation, no base-class or proxy edit). If any future variant needs
  to touch a frozen file, STOP and request explicit operator grant first.
- em-dashes / en-dashes / smart quotes are BANNED repo-wide (7-bit ASCII). Use a
  spaced hyphen for clause breaks.
- Later / periodic ARAM Mayhem augment windows: UNVERIFIED. The code models augment
  select as a single `augment_select` bool with no round/tier counter
  (`coaches/aram_coach.py:505-534`); there is no code evidence of a second/periodic
  window. The `game_seconds < 45` gate covers the PROVEN game-start window only. If
  the live confirm reveals a later window, re-arming the latch on a later
  `augment_select` edge is a fast-follow - do NOT invent it now.
