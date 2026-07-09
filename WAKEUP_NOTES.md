# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) + 2026-06-29 WP-D1 session (full in LEDGER 670) + R47 UI-audit cycle 16 (2026-06-30, full in LEDGER 702) + E11 sweep (2026-07-04, LEDGER 773-774) archived + /live-gated-drain (2026-07-04, LEDGER 780) archived 2026-07-05 + HZ-regrn+ARAM-leak-fix (2026-07-08, LEDGER 814-815) + enemy-spells CSS fix (2026-07-08, LEDGER 816). Only the last 3 sessions kept here.

---

# 2026-07-09 (CI baseline repair -- nightly-full-suite red)

Follow-through on item 822's deferred NOTE: the schedule-only nightly-full-suite (14k, NOT in push/PR CI)
was red on main; RC-CIWatchdog never fixed it (ci-fix/29013242484 had 0 commits ahead). Fixed ~24
deterministic failures in 4 verified slices. Full detail: LEDGER 823. Commits 40afd582 58ce5397 ccbafd5e
adcf0cbe (all pushed; push-CI green). Confirmation nightly dispatched on the fixed HEAD.

Slices:
- S1 40afd582: regen build_order_variants_{sr,aram,arena} at ENGINE 1.184.0 (were 1.182.0 from the 809
  bump; MUST pass explicit --champions for full-roster 173 cells - bare --mode all yields the 10-champ
  seed). $py->$venvPy in BUDGET_SAVER_PLAN.md (bare-py regex). liveStrip->strip test literal.
- S2 58ce5397: made the kit-axis guards hermetic. test_archetype_axis_correction + build_order_axis_parity
  read the live data/cs_archetype_picks.json; the operator's Katarina->bruiser user_cs pick legitimately
  overrides the kit axis. Monkeypatch _load_picks to {} in the default tests; skip picked champs in parity.
- S3 ccbafd5e: u2500-sweep / rc2_p73-quarantine / pengu-skeleton referenced gitignored _archive/ + relocated
  pengu/ files absent on a fresh checkout -> converted missing-target fails to skips.
- S4 adcf0cbe (real logic): a force-cleared coach was re-populated with deterministic action by the
  deterministic layer AFTER apply_cleared_at emptied it -> gated the synthesis on a _was_cleared flag. RC
  restarted (pid 9016 -> 17632, reload_ok).

LEFT RED (DS-judgment, logged to BACKLOG "DS scorer calibration", NOT fixed blind):
- test_beam boots_unique=False: 19a76d8b's T3-boot exclusion + frozenset dedup make a multi-boot build
  unreachable from a boots-only pool. Retire the test or re-scope boots_unique (DS-batch call).
- test_aram_coach_shadow_wire Kalista IE: the generic on-hit AD template (finding B) drops crit IE - may be
  meta-correct for on-hit Kalista. DS-meta call. The Katarina AD build = real bruiser-scorer-not-axis-aware
  gap (finding A/B family).
Pre-existing full-suite-LOAD flakes (coach_poll_offload x2, ds_matchdb_mcp auth) all pass in isolation - untouched.

---

# 2026-07-09 (deep-audit EXECUTION -- lanes 2-7)

Executed docs/AUDIT_2026-07-09_NEXT_SESSION_PLAN.md (Opus 4.8, orchestrated). Lanes 0/1 were already
done (174c44c9). Full detail: LEDGER 822. Commits 20df6d2b..bafc98a7 (pushed; check-job CI green).

Landed (3 verifier-gated worktree slices + inline tails):
- Lane 2 (Slice A): cost_tracker -> ops/rc_config.json path fix + budget test; champ_select fabricated
  ban-pct -> 0 (name-only, matches pick path); last_match tier-averages "estimate/reference" caption (+ CSS).
- Lane 3 (Slice B): deleted ops_ui_actions.py + ws_client.js + stub.css + settings.json (+ hash/pkg entries).
- Lane 4 (Slice C, behavior-preserving, ENGINE unbumped, Share in-sync): compute_dps(only_phase=),
  liveclient_summary from core.liveclient_cache, coach _poll_loop via asyncio.to_thread.
- Lane 3.2/3.3: deleted ward_cue + cc_pairing FRONTENDS (backends stay: /api/cc-pairing, core/ward_cue.py).
- Lane 6 subset: archived 4 DS plans + 5 one-shots to docs/_archive (back-refs retargeted; 101qq test path fixed).
- Lane 7: DS_COMPLETENESS_GAP snapshot banner (+2 line-refs renumbered); D6 row refresh (10374d02).
- Lane 5: rm commit_tmp; data/*_shadow.jsonl + /commit_*.txt gitignore globs; committed budget-saver-unified.ps1;
  git rm --cached data/force_scan.json + gitignore.

Verify: pre-push = ci.yml `check` scope all green (ruff / DS-share-sync in-sync / hygiene 13 / smoke 512 /
snapshot_panels 352). RC restarted (pid 5448 -> 9016, last_reload_ok, /api/state builds clean).

FLAGS / OWED:
- nightly-full-suite (schedule-only) is PRE-EXISTING red (~27 tests: pengu/ + top-level _archive/ absent on
  THIS checkout, build_order_variants stamp drift from the 809 engine bump, a bare-py in docs/specs/
  BUDGET_SAVER_PLAN.md). NOT this session, NOT in the push/PR gate; RC-CIWatchdog already on it (ci-fix/29013242484).
  Cheapest real fix: regen `python -m core.build_order_variants --static --mode all` (+ ASCII the BUDGET_SAVER doc).
- OWED live eyeballs: 2.2 champ-select ban cells (name-only) + 2.3 last_match caption -- need matching game state.
  Run /live-gated-resync next session to fold these into LIVE_GAME_GATED_SYNC.md (Lane 6/7 touched that doc).
- DS :8893 perf (only_phase) activates on the next DS restart -- behavior-preserving, live output unchanged now.
- lean-settings.json bypassPermissions change left uncommitted per operator decision.

Prior 2026-07-09 sweep session (2 workflow passes -> the plan + P1 fixes) = LEDGER 821 (fully executed above).

---

# 2026-07-08 (/live-gated-drain Arena + ARAM Mayhem)

Session -- 1 Arena game (Kai'Sa 11-7) + 1 ARAM Mayhem game (Jinx vs Kog'Maw/Sion/Yuumi/Yasuo/Bard):

Arena items (NO code changes -- observation only):
- D6 shadow: force_scan trigger fix (10374d02) NOT loaded (committed after RC boot). RC restarted end-of-session.
- D2: Cherry augment endpoints known-404 on 16.13.1.
- D3: no boot anvil rolled.
- D4/D5/D9: no roll/not evaluable (Goredrinker not picked, mode_modifiers GET identical ON/OFF).

ARAM PASS (4 items):
- C13 enemy_spells: 5 enemies x 2 spells correct
- C12 antiheal POSITIVE: heal_threat detected (Yuumi Heal + Sion sustain)
- C1 build logic: BotRK recommended for Jinx (correct on-hit ADC)
- C14 debounce OFF: coach refreshes coherently (fight_rule = CC threats)

PENDING:
- CSS visual verify: overlay still hidden at session time
- Arena retest after RC restart (b39a9fca + 10374d02 now loaded)

Shadow accrual: arena_coach_shadow.jsonl 463 rows / hz_choice_shadow.jsonl 45307.

NEXT: Arena game to test D6 shadow seeding post-restart, or CSS visual verify via overlay snapshot.
