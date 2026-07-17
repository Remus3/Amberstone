# mdclean findings - UNVERIFIED-SKIP log (cluster C1, 2026-07-17)

Items whose prune/relocate claim could not be proven within the 2-probe budget. Rule: later
clusters must NOT prune these on the C1 citation alone - re-verify or leave in place. In-doc DONE
markers alone (sha-level unverified) permit RELOCATE-not-delete but never hard PRUNE.

## ROADMAP.md
- L40 | DEEP-AUDIT PROGRAM run banner 2026-06-11 | loop-end not probed; LEDGER 901-903 show later loop activity
- L48 | item 312 | pre-LEDGER-floor, no LEDGER entry found
- L56 | item 265 Haiku-elim foundations | cited SHAs cb46386/77c3647 not in local git
- L57 | item 243/244 live UI watch | cited SHA 25b0be3 not in local git
- L75 | item 214 Electron shell narrative | self-declares phases 1-5 shipped; cited merges 0b2eea62/33dc9b3a not in local git
- L95 | build-ORDER go-live | cited SHAs 2d7da9e/3eb2e2d not in local git; self-declares SHIPPED

## README.md
- L46 | roster-coverage prose | canonical = docs/DAEMON_SLAYER.md; COPY-VERBATIM-ONLY (DS-batch job), do not touch in general cleanup

## BACKLOG.md
- L51 | obj_participation OPTION (c) | SHA 7b3d351 unresolvable; self-marked CLOSED twice (relocate-only allowed)
- L52 | Dead Man's Plate stacks-schema | SHA ce563c4 unresolvable; pre-LEDGER-floor item 122
- L86-L88 | Developer experience closed item | items 153-155 pre-LEDGER-floor, SHAs unresolvable

## docs/ARCHITECTURE.md
- L219-L224 | deploy-allowlist prune plan-text | no LEDGER/SHA anchor found for the plan's status

## docs/OPERATIONS.md
- L113 | memory-topic citation | style issue only, no ground-truth anchor needed but no proof of intended replacement
- L247-L248 | play-cadence dated rationale | no anchor

## docs/DAEMON_SLAYER.md
- L10 + L123 | 547/547 items vs CLAUDE.md 706/173 | scopes may differ; NEVER recompute - DS-batch docs-sync job
- L127 | 171/172 champions x P/Q/W/E/R | roster count at 16.14.1 unverified; COPY-VERBATIM-ONLY
- L192-L194 | calibration "Status: accumulating" | core/ds_calibration.py exists; status freshness unprobed

## C2 cycle notes (2026-07-17, ROADMAP.md executed)
- Kept in place verbatim with RM ids (UNVERIFIED-SKIP per C1; only an `- **RM-NN** ` prefix added):
  L40->RM-28, L48->RM-27, L56->RM-12, L57->RM-13, L75->RM-15, L95->RM-17.
- Relocation-target deviation: the directive said docs/history_notes.md; used docs/ROADMAP_HISTORY.md
  instead - it is ROADMAP.md's self-declared append-only archive ("Entries relocated verbatim") and
  every prior ROADMAP sweep (2026-06-20 / 2026-06-25 / 2026-07-13) used it; splitting the ROADMAP
  archive across two files would orphan the existing "(full record: docs/ROADMAP_HISTORY.md)" pointers.
- docs/ORCHESTRATION_PLAN.md: no mdclean row exists (grep 0 hits) - directive said update "if exists";
  skipped.
- L28 punch-list DEDUP -> docs/LIVE_GAME_GATED_SYNC.md deferred to C6 (that doc is C6 scope);
  punch-list survives as ROADMAP RM-05 + the verbatim archive copy.
- Slice-manifest / TaskCreate phases skipped per the directive's Tier-0 single-thread override.

## C3 cycle notes (2026-07-17, BACKLOG.md executed)
- 30 blocks (37,869 bytes) relocated verbatim to docs/history_notes.md "BACKLOG relocations -
  2026-07-17 (mdclean C3)" (U+2705 transliterated to [SHIPPED] for ASCII; new BACKLOG.md is now
  fully 7-bit ASCII). Open tails kept in place as stubs (boot-utility flip, Terminus resists,
  debounce flip, WPA don't-reopen, GPI Player-Profile tail, rubric CC-axis tail, OBS/CV anchors).
- UNVERIFIED-SKIP (new): the C1 inventory attributed the cooldown_watch.js + ban_suggest_toggle.js
  deletions to a "LEDGER 765 orphan sweep" - LEDGER 765 head reads as the champ-select QA rework,
  not an orphan sweep; attribution dropped. STALE-PATH tags in BACKLOG cite the live absence probe
  (Test-Path 0, 2026-07-17) instead: web/js/panels/cooldown_watch.js (route
  dashboard/routes_cooldown_watch.py still exists), web/js/panels/ban_suggest_toggle.js,
  docs/DS_V2_PLAN.md (now docs/_archive/DS_V2_PLAN.md).
- L51/L52/L86-88 handled per the C1 relocate-only rule (verbatim relocation, no hard prune; item
  149./122. anchors confirmed present in docs/history_notes.md).
- Non-resolving SHA 917cbb89 (HZ-B --static): pruned on the LEDGER 905 anchor instead ("--static
  regen in production" + shield-lerp "BACKLOG #7 re-verified" both read directly from entry 905).
- LEDGER 888 (Stormrazor NOT-WARRANTED), 826, 827, 753-757, 905, 506, 507, 511, 885, 874 all
  confirmed present by entry-header grep; SHAs 42780b3d + ae579ef0 resolve in git.
- docs/ORCHESTRATION_PLAN.md: still no mdclean row (grep 0 hits) - no sync owed.
- Slice-manifest / TaskCreate phases skipped per the directive's Tier-0 single-thread override.

## docs/ORCHESTRATION_PLAN.md (sha-level only; in-doc DONE markers present -> relocate-only OK)
- L105-L132 | DSP swarm round | 0c2b88e5 not in local git (LEDGER 876/889 do anchor the lane)
- L133-L157 | 2026-06-17 ROUND 2 | faeaeb4a not in local git
- L158-L170 | 2026-06-18 refill | e9f70e7d not in local git
- L171-L191 | 2026-06-19 refill | SHAs uncheckable in budget
- L9-L16 | contract summary vs ops/loop/director_prompt.md | no diff performed; dedup unconfirmed

## C5 cycle notes (2026-07-17, ARCH/OPS/API/AGENTS + README executed)
- ARCHITECTURE: Machines table + 2026-06-20 rename narrative deduped -> CLAUDE.md Topology
  pointer; retired screen_agent row pruned from active data-flows (item 276); 3rd relay
  self-heal copy deduped intra-doc; item-276 ship narrative + god-modules table relocated ->
  docs/history_notes.md (U+2705 -> [DONE]); scorer count 6 -> 7 (ds.onhit; LEDGER 911 +
  core/daemon_slayer_client.py:952/1458); registry + cc_conditional hardcoded counts / ENGINE
  pins deduped -> DAEMON_SLAYER.md banner per WP-F6a; U+2260 -> !=. L219-224 deploy-allowlist
  plan LEFT IN PLACE (C1 UNVERIFIED-SKIP holds).
- OPERATIONS: restart.bat contradiction resolved to match CLAUDE.md (hard fallback after
  taskkill); RC-LiveFlipWatcher row added (rc_facts live probe: 18 RC-* tasks, watcher Running);
  RC-DS-MatchDB-MCP persistence para -> REGISTERED (live probe Running + own L69 row; reinstall
  cmd kept); memory-topic citation dropped (style restructure); bottom Python-path section
  folded into the top interpreter section. L247-248 play-cadence LEFT (UNVERIFIED holds).
- API: regenerated from dashboard/_dispatch.py + per-module GET_ROUTES/POST_ROUTES mechanical
  extraction (105 GET / 30 POST paths); /api/input dup row removed; /api/sim-state +
  /api/dev/vision-status DROPPED (repo-wide *.py grep 0 hits - dead references, not just
  undocumented); U+00B7 -> ' - '.
- AGENTS: SMB push dropped from live roles (agents/agent2_backend/smb_push.py:3,47-53
  self-declares retired ADR-011/012; stub note added); stale counts (19-file suite, ~828KB
  queue) replaced with count-free phrasing; cross-machine framing annotated 1-PC;
  U+2192/U+00B7 -> ASCII.
- README: six -> seven scoring modes + On-hit table row (wording from LEDGER 911 'sums
  ability-DPS + on-hit-auto-DPS in one DPS frame'); U+00D7 -> x; ROADMAP pointer fixed to
  'open work' + docs/LEDGER.md bullet added. L46 roster prose + L48 item/test counts UNTOUCHED
  (COPY-VERBATIM-ONLY / sync-all-md job).
- docs/ORCHESTRATION_PLAN.md: still no mdclean row (grep hits = WP-C5 build-plan rows only) -
  no sync owed.
- Slice-manifest / TaskCreate phases skipped per the directive's Tier-0 single-thread override.

## C6 (2026-07-17) - DAEMON_SLAYER + ORCHESTRATION_PLAN + LIVE_GAME_GATED_SYNC

- DAEMON_SLAYER.md 97938B -> 15829B: changelog L17-L113 + pre-compress L15 registry narrative
  relocated verbatim -> docs/history_notes.md; 34-route refresh (server.py:2097-2098 live grep);
  dup hybrid.py row deduped; tests row 11701 -> 11754 (LEDGER 911 verbatim); six -> seven
  archetypes + picker no-manual-onhit caveat (LEDGER 911); brawl row tagged LEGACY (s214);
  0 non-ASCII remain. Count/coverage prose copied verbatim only.
- ORCHESTRATION_PLAN.md 351719B -> 36133B: 8 fully-DONE round bodies (LEDGER 763/784/875/876/889/
  903 + b49ef1a7) + 52 findings entries relocated -> docs/ORCHESTRATION_FINDINGS_ARCHIVE.md
  (append-at-top); newest-10 findings kept + tail-append ordering fixed; head contract + EXCLUDED
  kept verbatim. Serves the PLAN_CTX_CAP director budget.
- LIVE_GAME_GATED_SYNC.md 181474B -> 173886B (body-only, 1980 -> 1922 lines): A1/A2/A7/A13 pruned
  to a closed-note (LEDGER 859/867); TWO-LIVE-BUGS -> D6-only; drain-result + resync-pruned +
  play-order compressed to ledger pointers; B45/B46 compressed to calibration tails (LEDGER 799);
  C15+C16 merged into the cadence-bug row (LEDGER 867); D7-hist dropped; OQ20/OQ22 discharge rows
  one-lined; hygiene (a) rows executed by C2-C6 struck; hygiene (b) 7 [ARCHIVED 2026-07-09] rows
  pruned. Live-flip ledger (now L870+) byte-untouched; all diff hunks precede it.
- UNVERIFIED-SKIP: none this cycle (every prune carried a LEDGER id / SHA / live-grep citation).
- PROPOSAL (OPERATOR-GATED, not executed): relocate the LIVE_GATED Live-flip ledger (~103KB,
  now L870-L1922) to an archive sibling keeping OWED-bearing + the 2 SYNC entries. Requires a
  same-change .claude/workflows/live-gated-resync.js edit (writer prompt ~L210 + verifier ~L235
  >400-line + OWED-harvest contract) per in-doc L952-953 + feedback_no_history_rewrite.


## C7 cycle notes (2026-07-17, cross-ref sweep + slice G + census executed)

- Slice G (folded in per C1 routing; C6 had no room): OVERLAY_BUILD_MASTER_PLAN.md 72157B ->
  ~24KB (A-D WP specs, E.1/E.2 disposition tables, Section H wave plan, Section I harness
  relocated verbatim -> docs/history_notes.md; stubs cite Section J SHAs; F1-01 status-lined
  LEDGER 685 + dropped from GATED list; F.5 collapsed to open F5-L03 (M04/M05/H02/M01 DONE per
  Section J); WP-F6a spec -> DONE status line b0720386). RC2_PLAN.md 99403B -> ~22KB (24
  findings mega-entries + TOP-10 answers + PROGRESS detail line relocated verbatim ->
  history_notes; pointers to docs/RC2_QA_CONSOLIDATED.md f05b853d + STAGES tables; HARD-PAUSE
  bullet marked SPENT per in-doc 2026-06-20 GREENLIGHT).
- Section E handled as RELOCATE-not-prune: C1's "LEDGER 744 applied" citation NOT confirmed and
  Section J shows WP-E5 still OPEN - tables preserved verbatim in history_notes with an
  executed-partially note (C2 4ab82200 + C5 86616a9f).
- Census relocations -> docs/_archive/ (git mv, tracked): 16 COMPETITOR_LIFT_*, OVERLAY_QA_
  2026-06-29 (LEDGER 686/688), AUDIT_2026-07-09_NEXT_SESSION_PLAN (LEDGER 822),
  OPERATOR_DECISION_QUEUE_2026-07-01 (LEDGER 734), CHAMP_SELECT_UI_SPEC (SUPERSEDED banner,
  LEDGER 589), UI_OVERLAY_REDESIGN_SPEC_2026-07-06 (SUPERSEDED banner, LEDGER 860). Disk-move
  only (untracked/gitignored): 11 EXTERNAL_REVIEW_*. BACKLOG repointed 12 refs to _archive
  paths; LIVE_GATED hygiene row 15 annotated EXECUTED (body region, ledger untouched).
- UNVERIFIED-SKIP / deferred (carry-forward):
  - docs/LOOP_IMPROVEMENTS_2026-06-27.md NOT relocated: tests/test_loop_gemini_timeout.py cites
    the path; retargeting is a test edit = outside Tier-0 docs-only. Needs a Tier-1 cycle.
  - ops/loop/prompts/lane_ui_prompt.md cites docs/specs/2026-07-16-ui-worktree-handoff.md which
    does not exist - it is the EXPECTED OUTPUT of an unfinished FORWARD_LEAP lane, not a broken
    link; left as-is.
  - docs/research/COMPETITOR_LIFT_AGGREGATOR_C.md left in place (research/ cohort, not the docs/
    dated set; no citation for archiving research/).
- Cross-ref fixes: tools/sync-all-md.md dropped deleted docs/BRIDGE.md from both sync-target
  lists (ADR-012:34 records deletion; Test-Path 0); docs/ELECTRON_OVERLAY.md stale "Status:
  PLAN (no code yet)" -> SHIPPED pointer (rc-shell/src on disk + Section J); docs/cost_trace.md
  disk name normalized to the git-tracked docs/COST_TRACE.md casing (code cites COST_TRACE.md:
  tools/cost_health_watchdog.py:16,60). False positives NOT edited: Share/docs/0X_* suffix
  matches, ADR-012 historical deletion statement, sync-all-md.md:87 self-documented CHANGELOG
  case, GEMINI_* configs citing the EXTERNAL_REVIEW_<date> pattern (future files, writer
  unchanged; prior review already archived per GEMINI_AUDIT_CONFIG.md:55).
- CLAUDE.md proposal written to ops/loop/reports/mdclean-claudemd-proposal.md (2 no-change
  confirmations, 2 optional slims P1/P2). CLAUDE.md untouched.
- ASCII: all touched files scan clean (0 chars >127 in edited/added content); history_notes C7
  append verbatim-clean; tools/sync-all-md.md pre-existing glyphs left (operator-gated sweep).
- Slice-manifest / TaskCreate phases skipped per the directive's Tier-0 single-thread override.
