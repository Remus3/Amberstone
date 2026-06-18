# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

---

# 2026-06-17 - grounded /repo-insights report generator (operator-directed)

Operator ran `/insights`, then asked to validate its 3 "On the Horizon" suggestions and build a grounded repo-insights variant that reads the codebase instead of transcripts. Commit `c0d7876b` (pushed).

- **All 3 /insights suggestions = INVALID (already shipped) -> adjudicated docs-only, ZERO code.** (1) Anti-hallucination loop guard = `.claude/agents/verifier.md` + `tools/truth_gate.py` + ORCHESTRATION_PLAN "verifier-gate each slice". (2) Stale-premise sweeper = the director's per-cycle verify-before-redo + DRAINED queue (68 DONE / 0 OPEN). (3) Live-render sentinel = `tests/test_active_match_live_fixes.py` (null-items fixture) + `test_active_match_view.py` (coach.action + stale-map). Root cause: `/insights` reads transcripts, not the repo, so it re-pitches the very fixes that resolved its flagged friction.
- **NEW `tools/repo_insights.py`:** grounded variant - git window + LEDGER + ORCHESTRATION_PLAN + ROADMAP + ENGINE_VERSION + DS patch -> the Claude-Code-Insights HTML layout + sidecar `.json`. Horizon = the REAL EXCLUDED gated rows, not invented suggestions. Local `/repo-insights` command (`--days N`; `.claude/` gitignored so command is local-only like all RC commands). +8 hermetic smoke tests.
- First report: `~/.claude/usage-data/repo-insights-2026-06-17.html` (1475 commits / 163 ledger items / 68 DONE 0 OPEN, 30d).

GATE: ruff + ASCII + hygiene trio (smart-quote/mojibake/u2500) + 8 smoke = 20 passed. Tier-1 tooling, no engine/DS/Share/frozen/RC-restart touch.

NEXT: mold the look later via `CSS`/`PALETTE` + `# SECTION:` blocks in `repo_insights.py`. Do NOT rebuild - all 3 /insights horizon items are confirmed already-shipped (memory [[reference_repo_insights_tool]]).

---

# 2026-06-17 - live-session prep batch (operator-directed; eyeball harness + DSP5/6/7 consumers + anti-tank P3.2 producer)

Operator asked to bundle-plan the live-game-gated open items for the next session, then (AskUserQuestion) to build all 4 prep items. Shipped 5 commits (`c0c46410` `b09c100d` `0357defb` `ce33870a` + LEDGER 488); ENGINE 1.139.0 -> 1.140.0.

- **Eyeball harness** `ops/audit/ds_perm_swarm/live_flip_eyeball.py`: OFF-vs-ON top-6 dump for the 9 flag-ready seams (DSV2/3/4, DSP2, DSP8, DSP11 dps+burst, RF1, RF2, RF3+RF6) - one diff/champ, no mid-game `:8893` restarts. Smoke matched every documented intent.
- **DSP5/6/7 consumers** `agents/daemon_slayer/dsp_live_consumers.py` (ENGINE 1.140.0): the substrate seams had NO consumer; now `summoner_fight_adjustments` / `enemy_rune_threat` / `ally_protected_ehp` exist (byte-identical on empty context). DS :8893 restarted 1.140.0; Share 365.
- **Anti-tank P3.2 producer** `antitank.compute_antitank_live` (Tier-1, no bump): resolves live AP/AD via `build_champion` -> `compute_antitank(stats=)`. ehp ally-resist half folded into DSP7.
- **Plan** `docs/LIVE_GAME_GATED_SYNC.md` "Next-session play order": 34 gated boxes -> 3-game min (SR/ARAM/Arena).

GATE: DS 7334 / RC 8333 / Share --check green; +15 TDD; ruff+ASCII clean. (7 RC reds on the first 12min run were a Share-sync/DS-restart SEQUENCING artifact - all green on fresh re-run; the RF2/RF6 LiveFresh lesson.)

NEXT (live session, all still DEFAULT-OFF, do-not-flip-blind): run the eyeball harness + tick the seams; DSP5/6/7 + anti-tank now need only live-input plumb + eyeball (NOT consumer-building); HZ Lane-A/B + st-* + brief-flip need a corpus (>1 game). Do NOT rebuild the consumers - they shipped. DAEMON_SLAYER.md changelog had drifted to 1.129.0 (loop skipped it); bumped to 1.140.0 + a gap-bridge pointer (1.130-1.139 canonical entries are in Share/CHANGELOG + LEDGER 464-487) - do NOT backfill those 10 versions.

---

# 2026-06-17 - RF6 ds-engine: ehp/tank survivability INJECT seam (headless gemini-loop cycle 6, round-2 refill)

**Commit `700fa6a8`** (ENGINE 1.138.0 -> 1.139.0, DEFAULT-OFF). ORCHESTRATION_PLAN RF6, the last OPEN round-2 row.

- **Problem:** RF4 found RF3's ehp/tank survivability FLOAT is a no-op for Rell - its sole tabled winner Fimbulwinter 3121 is NOT in Rell's candidate pool, so there is nothing to float.
- **Root-cause (probe-confirmed, NOT the directive's assumed "mana-item gate"):** 3121 is dropped by `_is_purchasable` - `gold.purchasable=False` because it is the non-purchasable mana-line TRANSFORM of Winter's Approach 3119 (terminal+ARAM-legal; the off-class marksman deny is marksman-only, Rell is a tank). Probe: 3121 NOT in Rell pool OFF (124 items); RF3 float ON surfaced `[]`.
- **Deviation logged (feedback_audit_proposals_are_intent):** the directive's literal "mirror RF2's `only_ids |= surv_ids`" is INSUFFICIENT - RF2's hps inject ALSO silently drops 3121 for Rakan (the union still runs through `_is_purchasable`). Implemented the INTENT via a NEW `inject_ids` force-admit param on `rank._filter_candidates` (bypasses only_ids/exclude_names/`_is_purchasable`; still honors current/non-coachable/mode-legality/terminal/budget; `None` default byte-identical for all 7 callers). `ehp.rank_items_by_ehp` passes `inject_ids=surv_ids` only when the RF3 seam is ON.
- **Scope:** ehp lane only; hps (RF2, DONE) left byte-identical. FUTURE: the same purchasable-gate gap exists for Rakan's hps 3121 - the `inject_ids` mechanism now exists to fix it (logged LIVE_GAME_GATED_SYNC.md RF6 ledger).
- **Verify:** DS :8893 bounced (PID 14148 -> /health 1.139.0); ds_share_sync 362 --check in sync; DS+Share CHANGELOG. +12 TDD (`test_survivability_item_credit_rf6.py`). DS 7324 / RC 8333, ruff+py_compile clean, no frozen files.
- **NEXT:** round-2 refill queue (RF1-RF6) DRAINED -> expect director NO_WORK or new refill.
