# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-05-17 — `open item research.txt` liftability-triage integrated (docs only, no code)

**Operator instruction:** implement the referenced multi-agent research methodology, run it on `Desktop/open item research.txt` (~90 links), triage NOW/FUTURE/CLOSED, "go over what to keep" → 3 decisions locked → integrate.

## Methodology (reusable — memory `reference_liftability_triage.md`)
s234 link-list triage + the two referenced agent memories (investigate-command: conditions+table+"no fixes yet"; parallel-batch-agents: subagents own slices, supervisor synthesizes). 6 parallel general-purpose slice agents (WebFetch + `gh`), fixed per-link schema: what-it-is / single-most-liftable-thing / RC-fit / license. Supervisor synthesized; agents proposed no fixes.

## 3 decisions LOCKED (don't re-litigate)
1. **Fold Morello** (`noaboa07/Morello`, **MIT**) `badges.ts` + `match-insights.ts` + 5-tab card → reference impl for the s220 PGR **0–100 score** + Deep-Review tabs.
2. **Shared smoothed-rate primitive** — ONE module (Laplace/Beta over own match DB; algo ref `Maelian25/lol-draft-prediction`, **no license → reimplement clean**) for #88 augment + pick/ban synergy + PGR score. Same family already locked for #88.
3. **101.qq.com** CN duo-synergy — worth a one-off Game-PC Network-tab capture (static `game.gtimg.cn` JSON; exact path needs the live capture).

## Integrated (docs only — `/done` will commit)
- `CLAUDE.md` new active-priority **#90** (full triage + 3 decisions + CLOSED corpus).
- `ROADMAP.md`: augment-recommender item cross-linked; new 🟡 **shared smoothed-rate primitive** + 🔵 **101.qq.com capture** one-off.
- `BACKLOG.md` "Research / inspiration": DDragon-mirror item annotated with vendor-safe tooling found (download-data-dragon Unlicense + get-league-patch MIT + Nyx0ra/lol-asset-downloader MIT + OriannaBot MIT); full FUTURE + CLOSED triage block appended.
- Memory: `project_lcu_pengu_pregame_postgame.md` findings appended (LCU corpus CLOSED, KebsCS still canonical, league_record=video-not-rofl); new `reference_liftability_triage.md` + MEMORY.md index.

## Don't-redo / NEXT
- **Don't re-research:** the 27-repo LCU corpus (zero lobby payloads anywhere — #89 needs live capture/KebsCS); ML/CV/voice/`riot-offline-mode` repos; `.rofl` (reinforced CLOSED).
- **NEXT:** shared-primitive build = its own `/clear`'d scoped session (Task-1 = the #88 data-audit gate already in ROADMAP). 101.qq.com capture = one-off Game-PC step. No RC code shipped — nothing to verify live.

## Game-PC (also this session — investigated live via :8892 MCP; memory captured)
- **ARAM-Mayhem match misbehaved:** operator moved the Duet display below-main, then League booted **exclusive-Fullscreen** → window vanished (alt-tab-out) → couldn't tab back. Recovered: taskbar-close → in-game leave-prompt → switch off fullscreen. **Not RC** (screen-agent disabled s221, no capture ran during web research). **Not the Vanguard 0x50 BSOD** (window lockup at match *start*, no crash). Captured: new `feedback_gamepc_league_fullscreen_lockup.md` + `reference_gamepc_monitor_index_volatility.md` updated (Duet now 1920×1280 @ y=1080 below main; resolution discriminator still valid 1080=game/1280=dash).
- **Game-PC daemons all UP** — verified live: gamepc_lcu_agent / liveclient_relay / hotkey / mcp_server / bridge_daemon all running, RC-BridgeDaemon task Running. Operator closed only Claude Code → **do NOT restart the daemons**; only a Game-PC Claude Code session needs reopening for `/process-bridge-tasks` autoflow.
- League persisted `WindowMode=2` (Windowed @1920×1080 main monitor) — safe (only exclusive Fullscreen=0 triggers the lockup). Re-verify the Window-Mode dropdown **in-client** before any live Game-PC test (PersistedSettings.json can overwrite game.cfg; League resets to Fullscreen on some patches/driver updates). This is now effectively a precondition for the #89 lobby-verify + Mayhem-recommender live runs.

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
