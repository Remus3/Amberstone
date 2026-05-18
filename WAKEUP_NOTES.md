# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# ✅ RESOLVED 2026-05-17 — champ-select wrong for ARAM / ARAM-Mayhem / Arena

**Fixed `3eb2e2d`, proven live.** Root cause was a flat **queue-ID gap**, NOT
the phase/retention/router hypothesis in the leads below: ARAM Mayhem reports
`queueId=2400` (KIWI) but `core/queue_modes` only mapped `920` (Poro King —
the codebase had conflated 920↔2400) and the agent's `is_aram` likewise
omitted 2400 → `is_aram=False` → `_csvDetectMode`→"sr", bench/quick-swap
never rendered; `mode_key` stuck "client". The "phase:InProgress already"
signature was the *old broken state*, not Mayhem reporting InProgress —
disproven live (`cs_debug.raw_phase=ChampSelect`), so the phase-driven
view-router was correct and left unchanged. The plain-ARAM/Arena half was a
genuine transient champ_select loss → fixed by new `dashboard/_cs_retention.py`.
**Proven in a real Mayhem champ-select:** `queue_id=2400 is_aram=True
mode_key=aram`, populated `bench`, `raw_phase=ChampSelect`. Deployed (RC pid
12668 + Game-PC agent pid 8464 via bridge). Full write-up: ROADMAP ✅ keystone
entry + the 2026-05-17 (late) hand-off below. The original investigation leads
are kept verbatim below as the (partly-off) historical record — do not act on
them, the bug is closed.

Operator report, verbatim: *"the champ select screen is all wrong for aram + aram mayhem + arena."*
No detail captured yet — "all wrong" is unspecified (layout vs data vs render vs which elements). When picked up, gather specifics live: needs a champ-select pop in **each** of ARAM, ARAM-Mayhem, and Arena to see what's broken (a Game-PC `capture_monitor` of the dashboard during champ-select is fine — capture is only Vanguard-unsafe *in-game*, not in champ-select/client).
Leads for whoever investigates: champ-select had heavy recent churn (s164–s214 redesign, s208 legacy `#cs-overlay` retirement) and this 2026-05-17 session disabled the Game-PC screen agents + reworked the shortcut-only boot model — view-router / mode-detection regressions are plausible suspects. Not yet investigated; fix not started.

**2026-05-17 live-session leads (operator detail + code probe — partial diagnosis):**
- **Operator-reported specific symptom:** the **quick-swap (ARAM bench champion swap) is not active** on RC's champ-select screen for ARAM **and** ARAM-Mayhem.
- **Code path EXISTS end-to-end (capture-free probe this session) — the bug is NOT missing UI code:** `web/js/panels/champ_select.js` has `_csvBenchHtml(cs)` (renders the 5-cell bench from `cs.bench`) + `_csvWireBench(body)` (wires `.csv-bench-cell` click → `bench_swap` LCU cmd), both gated `if (mode === "aram")`; `_csvDetectMode(cs)` maps queue **450 AND 920 (Mayhem)** + `cs.is_aram` → `"aram"`; Game-PC `tools/gamepc_lcu_agent.py` populates `cs.bench` from `sess.benchChampions` and has the `bench_swap` POST handler (`/lol-champ-select/v1/session/bench/swap/{cid}`).
- **Strong hypothesis (root cause lead):** across **3 ARAM-Mayhem games this session**, every `/api/state` check during/just-after "champ-select" showed `lcu.phase: InProgress` **already** + `champ_select: {}` (`cs.keys: []`). RC never observed a populated champ-select state for ARAM-Mayhem. With empty `cs`, `_csvDetectMode` falls through to `"sr"` (no queue_id/is_aram) → the bench/quick-swap branch never fires → matches BOTH "champ-select all wrong" AND "quick swap not active". So the defect is **upstream of the UI**: the Game-PC LCU agent isn't forwarding (or RC isn't retaining) the ARAM-Mayhem champ-select session through the very fast ChampSelect→InProgress transition.
- **Next step for the fix (not done):** instrument/inspect `gamepc_lcu_agent.py` champ-select handling for **KIWI / queue 920** specifically — verify the agent even enters its champ-select poll/forward path for Mayhem (it may gate on queue types that exclude Mayhem), and/or add last-champ-select-snapshot retention in the RC state-builder so the dashboard view survives the sub-second transition. Needs a live ARAM-Mayhem champ-select with the agent instrumented (champ-select capture/curl is Vanguard-safe). The "fast transition" is itself a bug signature, not just bad luck — RC has missed the champ-select window on 3/3 Mayhem games.

---

# 2026-05-17 (done) — known-carry wakeup_prune FIXED + ROADMAP medium #3/#4 closed + lobby-bug hand-off staged

Three threads, all shipped. Code = `ef30b6f`; docs-sync commit follows.

- **wakeup_prune.py FIXED (the known-carry — closed, don't re-investigate).** Root cause confirmed empirically: `SESSION_RE` matched only legacy `# sNNN wrap`; recent dated/pinned headings tail-dumped into `extras`, inverting newest/oldest → crash at moved_ids (a lucky guard vs mis-archiving the newest sessions + un-pinning RESOLVED). Fix: widen regex to dated `# YYYY-MM-DD`, position-aware leading-pin fold into header, hardened moved_ids label. TDD +7 (20 total); phase7_polish 43 green. Executed the real prune (5 oldest → history_notes; pin retained).
- **ROADMAP medium #3 CLOSED.** Resilient `_log_startup`: ProgramData fallback + stderr echo + never-raise. **Deliberately rejected** the SYSTEM→Admin+logon ops change (DS not supervisor-watched → unattended-reboot regression) — don't redo it. TDD +10, live-smoked.
- **ROADMAP medium #4 CLOSED (verified not-a-bug, don't re-investigate).** Externally-reported bonus-AD-zeroing augment: Maw / Death's Dance / Endless Hunger all `defensive_only`/non-DPS in `effects.py`; Sterak's Claws keyed off base AD; EHP shield throughput is the Phase-1.5 deferral → nothing to over-rank.
- ROADMAP medium #1/#2 left BLOCKED (Phase-3 auto-action gate uncleared, 0 samples); #5 deferred (own scoped session, CLAUDE #88).

**NEXT SESSION FIRST:** lobby "change mode" button half-wired — Practice Tool / ARAM Mayhem / Arena won't switch (standard queues fine). Full recon + per-mode root causes + the 2 patch-structural changes (Brawl removed; Arena 2v8→3x6) are in **CLAUDE #89** + ROADMAP High-priority top. Recon is done — don't re-grep cold; needs a live client to verify.

---

# 2026-05-17 (late) — KEYSTONE champ-select/Mayhem FIXED+proven live · s220 surrender slice · reframe plan locked

Operator-driven, off the "start the next item" → keystone → "start what is
next" → s220 chain.

**Keystone (the actual blocking KNOWN BUG) — CLOSED.** Two commits:
- `3eb2e2d` fix(champ-select): queue 2400→aram (`core/queue_modes` + agent
  `_ARAM_QUEUE_IDS` mirror w/ anti-drift parity test) + `dashboard/_cs_retention.py`
  (transient-loss retention, wired into `build_state()` before pre-flip) +
  agent `cs_debug` breadcrumb + `tests/conftest.py` autouse isolation for the
  new process-global cache. 1159 tests pass.
- Root cause was the flat **queue-2400-unmapped** gap, NOT the hand-off's
  phase/retention/router fear. Disproven live: `cs_debug.raw_phase=ChampSelect`
  (router was right — deliberately NOT changed). Don't re-pitch a view-router
  change for this.
- **Proven in a real live Mayhem champ-select:** `queue_id=2400 is_aram=True
  mode_key=aram`, `bench=[420,38,27,12,887,238,83]`, `raw_phase=ChampSelect`.
- Deployed: RC reloaded via `restart_trigger.txt` (pid 14340→12668,
  last_reload_ok=true); Game-PC `gamepc_lcu_agent.py` redeployed via bridge
  `task-08722043fb4c` (~45s round-trip → agent pid 13960→8464). The
  session-start "⚠ stale gamepc bridge daemon" was only the *health publisher*
  — the task loop is alive (45s round-trip).
- Load-bearing detail: Mayhem's `/lol-champ-select/v1/session` omits
  `gameData.queue` (all-None, s154 behavior); the agent's
  `/lol-gameflow/v1/session` fallback recovers 2400 — that path is essential
  and confirmed working. A future "robust mapId/gameMode signal" can't use the
  CS session's queue_obj (empty for Mayhem).

**s220 Post Game Review reframe — STARTED, direction locked.**
- Slice 1 shipped `a5405ee` feat(post-game-review): surrender tag —
  `_enrich_from_lcu` surfaces `ended_in_surrender`/`ended_in_early_surrender`
  (surfacing-only, no new fetch) → hero badge `(FF)`/`(REMAKE)` +
  `data-surrender` attr. 5 tests; snapshot/timeline/view-router green.
- **Operator decisions (locked, don't re-litigate):** (1) PGR stays a
  **single-match richer aggregator G layout**, NOT a multi-match list (History
  view owns browsing). (2) The 0–100 score is an **RC heuristic over the
  already-enriched stats** (no Claude/Riot dependency) — I propose weights for
  sign-off in S3.
- Staged plan: **S2** = structure (persistent header + 10-player score strip +
  aggregator G roster row + color-coding + #9 augments frontend + hero §1 polish:
  KDA min-width, 2-line champ name, drop "ARAM", Sustain rename) · **S3** =
  score+rank+👑+MVP-purple-card · **S4** = AI Analysis/Graph/Build tabs
  (repurpose Comp/Chart/Timeline/Insights) · **S5** = Replay page. Each is its
  own session + the per-page UI-audit ritual.

**⚠ Process note (honest hand-off):** while verifying the keystone I ran a
Game-PC `mcp__gamepc__capture_monitor` against monitor 1 — `/api/state` had
shown `raw_phase=ChampSelect` but the operator had already fast-flipped into
the live game (the very transition this keystone is about), so the capture
landed **in-game, un-gated** — the Vanguard-BSOD-risk surface. No BSOD
observed, but this violated the operator-gated capture discipline. **Capture
stays operator-gated: operator says "now" AND holds until "got it". Do not
infer champ-select-safety from a single `/api/state` read during no-draft
modes — the flip is sub-read-cycle fast.**

**NEXT:** **S2 aggregator G structure session.** Needs the visual loop (a real
ingested match render + the per-page UI-audit ritual per
`feedback_phase3_fixture_ritual.md`) — best run when the operator has a fresh
standard-queue last match. Keystone needs nothing further (data path proven);
only the operator's own eyes on the rendered bench in a future Mayhem
champ-select as optional reassurance. Small still-open: `only_item_ids`
carry-branch fix (RUN-1 (b), needs a DS restart).

**⚠ TOOLING (wakeup_prune) — §6c SKIPPED again, now FULLY root-caused (don't
re-diagnose):** `scripts/wakeup_prune.py` still crashes (`SESSION_RE.search(b)
.group(0)` → None, line 105). The eve-entry's partial diagnosis ("chokes on
the pinned KNOWN-BUG block") was incomplete. **Real root cause:** `SESSION_RE`
(`^# s\d+…wrap\b`) only matches the *old* `# sNNN wrap` heading format, but
every recent session uses the *dated* format (`# 2026-05-17 (late) — …`,
`# 2026-05-17 (eve) — …`, `# 2026-05-17 OVERNIGHT RUN-1 — …`) which it does
NOT match. So `split_sessions` dumps ALL current sessions + the pinned
RESOLVED block into `extras`; only ancient `# sNNN wrap` blocks register as
sessions. A pure line-105 crash-guard would therefore **mis-archive the
NEWEST sessions and un-pin the RESOLVED block while keeping s231-233** — worse
than crashing. **Correct fix (own slot, NOT /done-tail — rewrites WAKEUP +
history_notes via atomic write, high blast radius):** (1) widen `SESSION_RE`
to also match `^# \d{4}-\d{2}-\d{2}\b`; (2) in `split_sessions`, fold any
leading non-session block (the pinned `# ✅ RESOLVED …` / `# ⚠ …` block) into
the header so it's never archived; (3) `--dry-run` and eyeball that the
RIGHT (oldest) blocks move before writing. Until then §6c stays skipped;
WAKEUP grows unbounded (marginal bridge cold-load cost — tolerable, not a
/clear blocker).

---

# 2026-05-17 (eve) — build-order UI (B+C) + live augment-OCR PROVEN + KNOWN-BUG keystone lead

Operator-driven session off the OVERNIGHT RUN-1 hand-off.

**Shipped:** `2d7da9e` build-order UI — (B) collapsible vertical "Build Order"
card in the champ-select My Pick panel + (C) in-game `#ds-pill` next-2-in-order
glance, both consuming the already-live `/api/build-order`. New
`web/js/panels/build_order.{js,css}` + hooks in champ_select.js/item_build.js;
ADR-008 auto-served (no RC restart — go-live was already serving from the
morning restart). Headless-verified: node --check, 38 snapshot+view-router
green. Density pass applied (collapsed→1-line for the tight My Pick panel).

**Augment — RESOLVED + PROVEN:** rigorous AT-picker-open probe (Game-PC
`C:\RC-Agent\rc_augment_probe.py`) → **no capture-free LCU/:2999 augment API**
exists for Mayhem (all `/lol-cherry/*`+`/lol-game-augments/*` 404; :2999
"augment" = i18n red-herring). On-demand `mcp__gamepc__capture_monitor`
survived **2/2 full Mayhem matches** incl. match-end + augment pickers → no
BSOD → augment-OCR→coach **proven end-to-end live** (read Prismatic+Gold
pickers, operator took the rec'd Magic Missile). Upgraded to "working
augment-OCR substrate, operator-gated". DON'T re-pitch the augment API
(dead); continuous DXGI screen-agent stays DISABLED; capture stays
operator-gated. Latency protocol: operator says "now" AND holds pick until
"got it".

**KNOWN-BUG keystone (root-cause lead, see the ⚠ section up top):** 3/3
ARAM-Mayhem games showed `champ_select:{}` / `phase:InProgress` already —
RC never holds champ-select state for Mayhem. UI code IS present; defect is
upstream (gamepc_lcu_agent.py forwarding / state retention through the
sub-second ChampSelect→InProgress flip). **Blocks BOTH the KNOWN BUG fix
AND the build-order B-card live verify** — this is the next keystone.

**Other notes (in the docs commit):** ROADMAP — surrender-tag / pengu-list
(`Desktop/pengu list.txt`) / DS-augment-flag / augment-resolution. Lolmath
gap review at `Desktop/LOLMATH_GAP_REVIEW_2026-05-17.md` (no scrape drift,
no gaps where lolmath leads, reverse-gap shareables listed — don't re-run).

**NEXT:** (1) champ-select-state-for-Mayhem keystone (instrument
`gamepc_lcu_agent.py` for KIWI/queue-920 + state retention) — unblocks the
KNOWN BUG + B-card; (2) then C-pill curl-verify + B-card live-verify (a
non-Mayhem champ-select renders fine); (3) productize augment capture→OCR
→coach. Nothing mid-game; safe.

**⚠ TOOLING BUG (found this /done):** `scripts/wakeup_prune.py` crashes
(`SESSION_RE.search(b).group(0)` → None, line 105) — it treats every
`---`-delimited block as a dated session and chokes on the **pinned
`# ⚠ KNOWN BUG` non-session block** at the top of this file (added
2026-05-17; the pruner predates it). Prune was SKIPPED this /done — WAKEUP
is intact but unpruned (longer than the 3-session target → bridge cold-load
cost). **Fix before next /done:** make the pruner skip the file-header +
any non-`SESSION_RE` pinned block (or relocate the KNOWN BUG section out of
the `---` ledger). Until fixed, every /done's §6c will fail the same way —
don't re-investigate from scratch.
