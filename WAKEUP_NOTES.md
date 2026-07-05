# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) + 2026-06-29 WP-D1 session (full in LEDGER 670) + R47 UI-audit cycle 16 (2026-06-30, full in LEDGER 702) + E11 sweep (2026-07-04, LEDGER 773-774) archived. Only the last 3 sessions kept here.

---

# 2026-07-05 (player-snapshot card SHIPPED - GPI-24h Home + role-rubric PGR; subagent-driven TDD; LEDGER 782)

Built the player-snapshot card end-to-end on branch `feat/player-snapshot-card` (PUSHED, head `b1a0c3b8` + LEDGER `68f37197`; NOT merged) via superpowers subagent-driven-development: 10 tasks, fresh implementer + spec/quality reviewer per task, a verifier gate + an Opus whole-branch review. Spec (2026-07-04) -> plan (`docs/superpowers/plans/2026-07-04-player-snapshot-card.md`) -> build.
- TASK 1 corrected a stale recon: rc-shell is a LIVE 2-surface Electron app; the companion window loads the shared `web/` tree from :8888, so v1 mounts in `web/` with ZERO `rc-shell/src` edits. The prior "overlay gone / all :8888" claim was WRONG (MEMORY was right).
- Backend: `player_gpi.py` `since_ts` window + win/streak/K-P/kda_mean/strongest-axis; new DB-pure `/api/player-snapshot` route (registered in `_dispatch.py`).
- Frontend: presentational `renderPlayerSnapshot` (tokens-only, ASCII, SVG arc-gauge dial); Home adapter (GPI 24h per mode tab + hero ABSORB); PGR adapter (role-rubric fold, NO new fetch, hero/rubric SUPPRESS); View Profile -> first production mount of the GPI radar.
- Verify: 5-phase UI audit 0 MUST-FIX; verifier 132/132; snapshot_panels 336; the Opus review caught 1 CRITICAL (PGR radar mounted into a `display:none` subtree) - FIXED `b1a0c3b8` (per-view containers). RC reloaded pid 12284, live `/api/player-snapshot` returns a valid model.
- Also: appended the operator's session-2 URLs to the canonical `_handoff_competitor_deep_research.md` (memory dir, non-repo per name-scrub); deleted a stray repo-root copy.

NEXT (operator /clears + starts on MAIN): open a PR for `feat/player-snapshot-card` -> main + merge (CI is PR-gated, no branch-push run) OR merge when ready. Then the Fable-5 competitor deep-research fan-out (QUEUED, memory-dir handoff, run in a dedicated Fable-5 session) + the lolmath DS-knob coverage check (separate). Operator-glance owed: dial arc-gauge vs `luna-sever-2.jpg`.
DO NOT redo: rc-shell IS alive (companion = the :8888 web tree in Electron - do NOT re-pitch "overlay gone"); the card is BUILT + reviewed + pushed on `feat/player-snapshot-card` (do NOT rebuild); the 1 Critical is FIXED; the model contract + 65/35 dial bands + visual-only absorb/suppress are settled.

---

# 2026-07-04 (/live-gated-drain continuation - A1/A2 layer-2 + D6 headless fixes built + armed, full resync rebuilt; LEDGER 780)

Continuation of the FULL DRAIN (LEDGER 779). Built the 2 caught-bug headless fixes spec-first (2 Plan subagents) + worktree build agents + an independent verifier gate + lead frozen-diff review, Opus 4.8 max orchestrated. Both MERGED main + armed live; both still owe a live re-validate.
- A1/A2 LAYER-2 (`1ab7000e`, FROZEN lcu_client.py + lcu_rune_writer.py): premise REFUTED - the 3 spawn_task loops ALREADY guard Exception, so "add a try/except" would be redundant dead code. Real gap = a BaseException escaping `except Exception` kills the coroutine (postgame collector already handled it; auto-accept + RuneWriter did not). Split the tick-arm into `except CancelledError: return` + `except BaseException: log`. Closes layer-1's caveat. NEW test_lcu_loop_resilience.py (5, RED-first). NOT proven to fix the incident - the root cause (AppLoop-stop / to_thread-starvation) is UNCONFIRMED (no traceback was logged); layer-1 self-heal is the alive-loop mitigation, the League-restart re-validate is definitive.
- D6 (`79c4e9e9`, tools/lcu_agent.py): phase_watcher is DEAD (do NOT hook there - inert). RC-LCUAgent capture_state gains an Arena-gated /lol-cherry-game-intra-event/v1/augments probe + an edge-latch force_scan bump so the vision scan catches the transient augment panel -> augment/anvil shadow seed. NEW test (8). D2 shares the root cause.
- Verify: 52 pass / 0 fail fresh, py_compile + frozen import smoke OK, ruff clean. RC pid 6440->24344 (auto-accept + RuneWriter up async, no boot break); RC-LCUAgent restarted.
- `/live-gated-resync`: rate-limited first attempt (transient server throttle from the 52-agent burst, NOT a usage limit), SUCCEEDED on resume - rebuilt LIVE_GAME_GATED_SYNC.md (1533 lines, ASCII, audit.pass), pruned 11 closed rows, open_now=95, est 4 sessions, ARENA NEEDED=YES, B41 disambiguated -> B41b.
- Operator live finding (mid-session): user-builds runes have NO hover tooltip -> chip task_9a485b62 (fix candidate build_insights.js _runeImgTag, a DDragon-runesReforged tooltip).

NEXT (live re-validate, operator-paced): restart League mid-session -> champ-select to confirm A1/A2 auto-push (definitive layer-1+2 test); 1 Arena game for D6 seeding + D3 boot-anvil / D9 Goredrinker rolls; opportunistic ARAM Mayhem C11/C12/C3/C15/C16; F3 PGR auto-show recheck. Accrual G1 0.4626 / G2 +3.6% flip_ready=False - HOLD. Unplayed seams B2-B19/B31-B40 via the headless harness.
DO NOT redo: the loops ALREADY guard Exception (layer-2 is the BaseException split, not a new loop); D6 is in RC-LCUAgent not phase_watcher (dead); the silent-death root cause is UNCONFIRMED (if the re-validate shows the loop still dies -> liveness-watchdog / to_thread-timeout). Duplicate chips task_c122811d + task_660c82b7 could NOT be dismissed (operator already started them) - close those sessions manually.

---

# 2026-07-04 (/live-gated-drain FULL DRAIN - 4 queues one sitting; LEDGER 779; layer-1 fix 90b350c8)

Ran the full live-gated drain (ARAM Vayne + practice-SR Zilean + real-SR Ezreal draft-q400 + Arena
Kai'Sa) in one sitting, Opus 4.8 max orchestrated, live-watch cadence (ScheduleWakeup) between games.
Evidence: scratch drain_evidence_2026-07-04.md.
- CLOSED (live evidence): B23 objective gauges, B21 objective callouts (Cloud Drake), E1 ACTIVE knob +
  E2 panel cycle (signal files 18:01 + operator attest), B28 frames, B5 DSP2 exempt_offclass eyeball
  SANE (Ezreal floats Trinity Force), F1 PGR + @N (gold@10 3167v3791 / cs@10 64v88), F2 REPLAY1
  freshness, F4 PGR render, D7 Arena Match-V5 ingest (Kai'Sa - Arena IS eligible), C1 ARAM 3-variant
  render half.
- 2 LIVE BUGS CAUGHT: (1) A1/A2 champ-select auto-push REGRESSION - the in-process spawn_task loops
  (auto-accept + RuneWriter) silently die after a mid-session League restart -> shared LcuClient pinned
  to the dead port -> no push (operator set spells manually; READ path survived = separate RC-LCUAgent
  process). LAYER-1 self-heal MERGED 90b350c8 + pushed (RuneWriter._poll re-heals; verifier 62/0;
  non-frozen); LAYER-2 (frozen lcu_client.py resilient loops, operator-approved) = follow-up task; A1/A2
  stay OPEN pending re-validate. (2) D6 Arena augment/anvil shadow not seeding - nothing bumps
  data/force_scan.json on the Cherry augment event so the free-running 20s vision scan misses the
  transient panel (OCR+writers ARE built); D2 shares it; fix task; gated on a live Arena game.
- Accrual: B20/R55 3/3; rails G1 laning 0.4626 / build 0.6484 (HOLD), G2 +3.6% flip_ready=False @665 (HOLD).

NEXT: A1/A2 layer-2 (FROZEN lcu_client.py resilient spawn_task loops) + a League-restart re-validate;
D6 force_scan-on-Cherry-augment-event fix; THEN the full /live-gated-resync structural rebuild (run once
these closes are in LEDGER - it verifies done-claims against repo state, can't validate live closes).
Still gated: D2/D3/D9 Arena rolls (D3 no boot anvil / D9 no Goredrinker in 8 rounds), F3 PGR auto-show
recheck (didn't fire - companion on HOME post-game), ARAM C11/C12/C15/C16 scenario rolls, unplayed-champ
seams B2-B19/B31-B40 (harness sweep available headless). DO NOT redo: layer-1 is on main (flip point =
RuneWriter._poll, do NOT rebuild); D6 is a force_scan-TRIGGER gap not an OCR-feed gap; two operator-
started fix chips (task_c122811d + task_660c82b7) overlap the two refined chips (task_3e9433f2 +
task_ebbdf78b) - reconcile. RC NOT restarted this session (layer-1 activation + re-validate owed).
