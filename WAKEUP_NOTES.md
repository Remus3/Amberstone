# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

---

# 2026-06-25 (cdragon 16.13 CC-detection fix [619] + snapshot_panels flake fix CI-validated [620])

Cleared both NON-gated items from 618's NEXT, both CI-green on Linux. 5 commits pushed. Each item
ROOT-CAUSE-CORRECTED a wrong 618 triage (ground-truth probes over recollection).

- ITEM 619 (cdragon SwapsInto extractor, `95972f57`): the 12 dropped CC tags were NOT a "bin-format
  parse break / pure rename, swap-count=12" (618's guess) - they were a Riot 16.13 TAXONOMY change:
  `...ImmobilizingCCSpell` -> `...CCAbility` suffix rename + 7 of 12 swap spells reclassified
  swap->DIRECT-immob. Fix in `daemon_slayer_cdragon_spell_extract.py`: match the stable `ImmobilizingCC`
  stem + `_canon_cc_tag` canonicalizes `...CCAbility`->`...CCSpell` (suffix-only, swap/direct preserved).
  Re-enabled fresh 16.13 spell_stats: _with_cc_tags=186 unchanged, HONEST swap=5/immob=181, other buckets
  byte-identical, 4 legit Riot bin deltas (Mel E snare gained; Ornn Q/Yorick W lost; Morde R gained).
  NO ENGINE bump (forward-marker inert); Share synced; DS restarted -> 16.13.1; DS-dir 7575 + cc-test 31
  green. ability_ratios + ratio_drift LEFT copy-forward (CONSUMED ratio source via abilities.py
  prefer_cdragon_ratios=True default - a separate Tier-2; NOTE doc says "False/OFF" - doc/code mismatch).

- ITEM 620 (snapshot_panels flake, `1a974bd9` re-attempt + `0fe7e3bf` fix): KEY finding - the HTTP/1.1
  keep-alive ITSELF (not the SSE gen-gating 618 blamed) breaks the Linux render tests. CI run 28159713805
  proved BOTH keep-alive variants fail the same 5 tests (spike_markers/ds_relscore/overlay_combat/
  header_single_row/player_gpi) while HTTP/1.0 passes: the gitignored ddragon PNG mirror is absent on CI
  so champion/item PNGs 404 -> send_error BrokenPipe -> wedged keep-alive pool -> half-rendered panels.
  Fix: scope keep-alive to win32 (TIME_WAIT flake is Windows-only); Linux keeps proven HTTP/1.0; SSE hold
  reverted to sleep(15). Windows 274x2 local; Linux CI 274 passed. DEVIATES from the literal "keep
  keep-alive" instruction (it is NOT Linux-sound) - implemented the intent. Corrected the stale
  `reference_snapshot_panels_session_browser_flake` memory ("CI runs no pytest" was wrong).

NEXT (operator-gated / live-blocked, unchanged from 618):
1. CI Watchdog ARM (item 204, do-not-flip-blind).
2. HZ precompute-vs-Haiku RE-MEASUREMENT - needs the regenerated 16.13.1 tables + real-game shadow rows.
3. R30/PGR live-gated tail (physical game).
4. Housekeeping: ARCHITECTURE.md:172 ENGINE/test-count drift (1.144.0/7361 vs live 1.151.0/7497) for a
   /sync-all-md. (cdragon SwapsInto extractor fix from 618's NEXT is now DONE = item 619.)

---

# 2026-06-25 (DS patch refresh 16.12.1 -> 16.13.1 - orchestrated multi-agent SWARM + precompute regen)

Ran the headline patch refresh as an orchestrated Tier-2 run. ENGINE_VERSION stays 1.151.0 (operator-confirmed
via one AskUserQuestion: patch != engine code, matching the 3-refresh convention). 2 commits pushed (`cdc4f8aa`
patch refresh + Share, 78 files / 3 LFS laning tables; `1f53f5ad` snapshot flake fix), ruff clean repo-wide.
Full per-item record: docs/LEDGER.md item 618.

- Upstream probe drove fresh-vs-copy decisions: DDragon moved 16.12->16.13; Meraki FROZEN at 25.15; CDragon
  published a fresh 16.13 build. Extract chain wrote the 19-file 16.13.1 snapshot + flipped current.txt +
  manifest content_patch backfill. New champ Locke (173 roster) fail-softs as a Meraki-miss (like Yunara/Zaahen) -
  expected new-champ-catches-up case, NOT hand-backfilled (true adperlevel unavailable upstream).
- KEY FIND (do-not-flip-blind win): the fresh CDragon 16.13 extract silently DROPPED all 12 SwapsInto CC tags
  (Aphelios Q etc.; immob survived) - an extractor regression on 16.13 bins, caught by the DS-dir suite. REVERTED
  the cdragon trio to the proven baseline rather than pin the consuming test; cdragon is an inert forward-marker
  so zero live-scoring impact - PROVEN via byte-identical Ahri build re-gen post-revert. FOLLOW-UP: fix
  daemon_slayer_cdragon_spell_extract SwapsInto detection on 16.13+ bins before re-enabling fresh cdragon.
- Precompute regen all 3 modes / 173 roster (laning ~66MB/mode LFS + build_orders + variants); read-path VERIFIED
  at 16.13.1 (lookup covered + A/B). Share re-synced (_PATCH 16.13.1, engine 1.151.0, --check clean). Live-header
  patch anchors flipped (DAEMON_SLAYER/ARCHITECTURE/routes_dictionary/items_index.js); the ref had MOVED to
  items_index.js DDRAGON_FALLBACK_VERSION (memory's main.js/pgr pointer was stale - ground-truth grep caught it).
- Verified: dual suite green (DS-dir 7511 passed; tests/ 9423 passed); DS :8893 -> 16.13.1/1.151.0; builds
  re-rank SANELY (55 AP champs adopt the engine's Liandry's-first valuation, marksman/tank/bruiser byte-stable;
  engine-driven NOT data/cdragon - the 6 items are stat-identical + the prior table was an older-engine gen).
- Secondary (parallel worktree agent): snapshot_panels at-scale Playwright flake fixed at ROOT (HTTP/1.0
  connection-per-request -> TIME_WAIT port exhaustion; fix = HTTP/1.1 keep-alive + SSE gen-gating + per-test
  reset). 274 passed x2 independent re-verify (never trusted the agent's 3x claim). REVERTED (`f68cf703`): the SSE gen-gating fails 4 CI/Linux render snapshot tests (a Windows-only verify was insufficient).

NEXT (operator-gated / live-blocked, unchanged from 617):
1. CI Watchdog ARM (item 204, do-not-flip-blind): create C:\RC-CIWatchdog\ worktree + enable repo auto-merge +
   append --arm to ops/RC-CIWatchdog.xml. Detail: docs/CI_WATCHDOG_PLAN.md + LEDGER 613.
2. HZ precompute-vs-Haiku agreement RE-MEASUREMENT (item 614 NEXT) - now ALSO needs the regenerated 16.13.1 tables
   + real-game shadow rows; do AFTER accruing live games on them. Live coach flip stays operator-gated.
3. R30/PGR live-gated tail (E.1 ACTIVE knob physical press + RC_COMP_HP_LEAN default-ON) - need a physical game.
4. Housekeeping: fix the cdragon SwapsInto extractor (above); re-attempt the snapshot_panels flake fix WITH CI/Linux validation (keep HTTP/1.1 keep-alive, rework SSE gen-gating); WAKEUP now 5 sessions (weekly-hygiene to trim to
   2-3); ARCHITECTURE.md:172 ENGINE/test-count drift (1.144.0/7361 vs live 1.151.0/7497) for a /sync-all-md.

---

# 2026-06-25 (Track-1 red-cleanup - named full-suite reds CLEARED + DS patch-drift found + auto-accept re-enabled)

Continued ledger 616's NEXT (Track 1). All 7 operator-named pre-existing full-suite reds triaged stale-test vs
real-regression (NONE were product regressions) + fixed; 1 commit (`0cdafe9c`, 12 files), CI green (3m50s).
Tier-0/1 (docs + test files; no engine/DS/Share/ENGINE_VERSION). Full suite after = 10 failed / 9414 passed,
and ALL 10 are the pre-existing snapshot_panels Playwright at-scale flake (0 non-snapshot failures); the named
logic reds are GONE. GROUND-TRUTH LESSON: my first check passed the WRONG files (`*_view.py` instead of the
note's `*_dom.py`/`*_e4_counters.py`) and nearly mis-declared the cluster green - the full suite caught it.

- ROADMAP 104KB -> 80KB: relocated 20 shipped entries to docs/ROADMAP_HISTORY.md (3 done UI bullets + 13 overlay
  SHIPPED slices R17-R28 + 4 closed sub-items), breadcrumb under the overlay header. EOL gotcha: pathlib
  read_text collapsed CRLF->LF mid-relocate; re-normalized both to uniform CRLF (git stores LF via autocrlf, diff
  clean -20/+1 + 25/0).
- aram_balance KeyError (COMPLETE 4-file sibling set): ARAM coach _USER_TMPL gained an {aram_balance} slot; added
  the key to ds_pick_consumption + the 3 cc_*/enemy_cc context test format() calls (grepped aram_tenacity= for
  ALL siblings first - the initial fix patched only 1 of 4).
- Fragile live-data guards -> hermetic: auto_accept_pref/route value-assertion replaced with a module-scoped
  byte-untouched redirect-regression guard (the flag is operator-toggleable, a False on disk is legit);
  spell_autopush_e6 first-lock isolated to tmp prefs (live spell_prefs.json mutates by_champ.SR.Caitlyn).
- Stale R30-redesign DOM tests (functionality verified intact in source, NOT regressions): last_match default tab
  = AI Analysis not Build (ledger 604); historical_pgr wiring moved into _historyMatchRowEl (0c0bdc16);
  champ_select counter-picks regex anchored to `_csvRenderSuggestions(` excluding the new NonSr sibling.
- Auto-accept RE-ENABLED (operator request; gitignored, official set_enabled path). New memory
  reference_snapshot_panels_session_browser_flake.

PATCH DRIFT (headline orchestrated NEXT): live League + RC DDragon mirror = 16.13.1 (mirror auto-refreshed
2026-06-24, the unstaged data/meta/* + new 16.13.1/ dir); DS engine current.txt = 16.12.1. The DS patch-refresh
+ patch-keyed precompute (laning/build/HZ) regen to 16.13.1 is the top multi-agent NEXT (SWARM per
reference_patch_refresh_workflow). Track-2 stays operator-gated/live-blocked: CI Watchdog ARM (do-not-flip-blind),
HZ re-measurement (needs real-game shadow + now patch-affected), R30/PGR tail (physical game).
