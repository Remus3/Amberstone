# Riot Commander - Overlay + Build Master Plan

Authoritative build spec for the overlay redesign + adaptive build-path module. A looping
multi-agent run executes this over many sessions. Every UI work package gates on the per-page
UI-audit ritual (Section G). All authored text is 7-bit ASCII - no em/en dashes, no smart
quotes; use ' - ' for clause breaks.

## Invariants (apply to EVERY work package)

- 7-bit ASCII only. No em/en dashes, no smart quotes. Spaced hyphen ' - ' for clause breaks.
- Atomic writes only: `tmp.write_text(...); tmp.replace(target)`. Overlays poll mid-write.
- `py_compile` before any restart. Restart via `echo restart > restart_trigger.txt`.
- Per-match build state is IN-MEMORY. Nothing persists to disk except (a) a log line that the
  operator took an action (silence/defer/shift), and (b) an OPTIONAL end-of-match
  "save this build?" snapshot. No build-plan database is written.
- The adaptive module sits ABOVE Daemon Slayer (DS). It NEVER changes DS fundamentals, scoring,
  or ENGINE_VERSION. DS `/api/ds-preview` + `/api/build-order` outputs are read-only ground truth.
- Tier classification per RC R5: Tier-0 cosmetic (Edit + py_compile if .py); Tier-1 local logic
  (py_compile + that module's tests); Tier-2 schema/engine/scorer/ENGINE bump (full dual suite +
  DS :8860 restart + Share mirror). Most overlay JS/CSS is Tier-1 (own module tests + UI-audit).
- TDD: write the failing characterization/regression test FIRST.
- ADR-008 asset hash: editing `web/{js,css}/panels/*` auto-reloads, no RC restart.

---

# SECTIONS A-D - OVERLAY FIXES / BUILD PANEL / ADAPTIVE BUILD-PATH / ITEM INTERACTION (DONE)

All A/B/C/D work packages are DONE - statuses + SHAs in Section J (A1-A6, B1-B4, C1-C5, D1-D3).
Full WP specs relocated verbatim to docs/history_notes.md (mdclean C7, 2026-07-17).

---

# SECTION E - SCREENSHOT REMEDIATION BACKLOG

Disposition legend: REMOVE (delete content), CLOSED (mark item closed / move out of open queue),
PRUNE (slim stale referential header/prose), CLARIFY (resolve ambiguity), DEFER-TFT (redo fresh
later - see grouped block). The `?` mark = same disposition as X (verify-then-prune/remove).

## E.1 + E.2 - screenshot dispositions (relocated)

Raw E.1 (README/landing/docs, 0-11.PNG) + E.2 (ROADMAP open-vs-closed, 12-25.PNG) disposition
tables relocated verbatim to docs/history_notes.md (mdclean C7, 2026-07-17). Large parts were
executed by the mdclean C2-C6 sweep (ROADMAP restructure 4ab82200; living set + README 86616a9f);
WP-E5 stays OPEN (Section J) for the residue - consult the relocated tables when running it.

## E.3 - Live pre-game lobby UI (26.PNG) - feeds overlay/lobby redesign

| Element | Mark | Disposition |
|---|---|---|
| QUEUE 3340 / FIND MATCH area "DB 30 X" | X | REMOVE lobby element / queue-id not needed here |
| YOUR MAINS / PARTY MAINS -> MY TOP 8 sweep | arrow/lasso | CLARIFY - operator linking mains rows to Top 8 (data-source/layout note) |
| a specific YOUR MAINS row | circle | CLARIFY - calling out that row |
| MY TOP 8 per-row "+ avg / + sec" controls | X | REMOVE those Top 8 columns/controls |

## E.4 - DEFERRED-TFT block (redo fresh later)

Group separately. Do NOT delete the TFT pipeline now; mark these for a fresh TFT pass later:
- `coaches/tft_coach.py` "TFT Set 17 mode coach" (6.PNG)
- `mode_router.py` TFT early-exit (5.PNG)
- README/About + intro + Modes-covered TFT mentions (1.PNG, 2.PNG) - the tagline TFT removal is
  REMOVE-now (cosmetic), but the underlying TFT *feature* surfaces are DEFER-TFT.
- `item_build.js:251` TFT Set 17+ augment TODO (from hygiene sweep).

## WP-E5 - Execute the doc remediation sweep

| Field | Value |
|---|---|
| Goal | Apply E.1 + E.2 dispositions to README / ARCHITECTURE.md / ROADMAP.md / DAEMON_SLAYER.md: remove stale prose, prune engine-headers to live pointers, move CLOSED/SHIPPED items out of open queues, remove Peer/two-machine/screen_agent/Brawl content. |
| Files | `README.md`, `docs/ARCHITECTURE.md` (esp. :172 stale 1.153.0/7537 -> 1.154.0/7557 or live pointer), `ROADMAP.md`, `docs/DAEMON_SLAYER.md:5` (drift-guarded - DO NOT touch), `CLAUDE.md:6` (slim engine-recital to a pointer - CI <60KB). Stray dirs: `docs io RC peer` (remove), `assets` (clarify). |
| TDD test first | This is docs hygiene (Tier-0). No code test. Verification = grep assertions: no "Teamfight Tactics" in tagline, no two-machine prose, no Peer-bridge para, no `screen_agent` reference as live, drift-guard `tests/test_docs_daemon_slayer_drift.py` still green, CLAUDE.md < 60KB. |
| Tier | Tier-0 (doc/comment/string). Edit + size-budget check. |
| Acceptance | All E.1/E.2 REMOVE/PRUNE/CLOSED items applied; do-not-rewrite-history rule honored (AUDIT_*/PHASE_*/dated artifacts NOT rewritten - living docs only); ROADMAP open queue carries only genuinely-open items. |
| Deps | None on code. Run as its own session (large doc edit). Honor `feedback_no_history_rewrite`. |

---

# SECTION F - REMAINING-ITEMS ROUNDUP

Folded from the open/gated/future/deferred/theorized inventory + auditor proposals + inline-TODO /
stale-engine-header hygiene. Each is a work package or explicitly deferred with reason.

## F.1 - Overlay/build-adjacent open items (in-scope, sequenced into A-D)

| ID | Item | Source | Disposition |
|---|---|---|---|
| F1-01 | Overlay redesign live-deploy confirm | ROADMAP:13 | LIVE-CONFIRMED 2026-06-29 (LEDGER 685, 23e624a5) |
| F1-02 | Manual ward tracker overlay panel (optional fold into CD ledger) | ROADMAP:13 | DEFER - decide after Section A ships (one-panel-vs-two) |
| F1-04 | L4 capability-gap live SR validation (`RC_CAPGAP_SURFACE=1`) | ROADMAP:16 | GATED live SR game |
| F1-05 | E.1 ACTIVE-knob physical-press round-trip + RC_COMP_HP/IP_LEAN flip | ROADMAP:18, SS25 | GATED physical game |
| F1-06 | Electron packaging (electron-builder) + first GitHub Release | ROADMAP:74 | DEFER - operator/release trigger |
| F1-07 | ZOI champion-only isolation (template-match) | ROADMAP:53, SS19 | PARKED - low value + regression risk (2 Gemini do-not-attempt) |
| F1-08 | LBAND1 live wire-in (live_benchmark_band -> /api/state + overlay) | BACKLOG:144 | GATED - relevant to WP-A4 benchmark feed |

## F.2 - DS build-engine gated items (above-DS module does NOT change these)

All GATED on live re-rank validation + ENGINE bump (Tier-2). The adaptive module reads DS output;
flipping these seams is separate DS-batch work, not part of A-D.
- DS comprehensive per-champion cross-eval (ROADMAP:30) - GATED live re-rank.
- DS sidecar/opt-in flag flips: gate_emms / apply_mode_modifiers / aoe_targets_hit /
  apply_ability_haste / apply_passive_damage (ROADMAP:58,64-72) - GATED live validation.
- DS resist-seam survivability scorer (Anivia P / Orianna E) + percent-of-resist mode (ROADMAP:48,59) - schema-blocked.
- DS live-flip seams R5/DSP2/DSP11/R12/R30/RF1/RF3 default-ON (ROADMAP:14) - GATED.
- DS target-current-HP% flip, enemy-pen-aware EHP flip (BACKLOG:30,32) - GATED product call.
- DS forward-marker LIFT_FOUND queue (LEDGER:344) - OPEN no-consumer accessors; no ENGINE bump.
- DS calibration pipeline (ROADMAP:120) - GATED on 20+ ranked samples (0 SR records).
- Interactive Item Shaper UI (BACKLOG:28) - DEFER until DS 100% + running-coach wire.

## F.3 - Coaching / HZ / precompute gated items

- HZ laning precompute coach FLIP + hold-band recalibration (ROADMAP:44, BACKLOG:143) - GATED real-game agreement.
- Deterministic ARAM coach Stage-4 flip / champ-select brief flip (WAKEUP:31, BACKLOG:34) - GATED shadow-log.
- Antiheal callout membership review (BACKLOG:35) - GATED visual capture.
- Same-state Haiku-skip debounce flips (BACKLOG:60) - GATED fidelity.
- Matchup-engine fidelity lift (ROADMAP:55) - DEFER (coin-flip ceiling, uncertain payoff).

## F.4 - Dashboard / data-wiring deferred

- Dashboard data-wiring gaps: ~88 residual st-* ADAPTATION rows (no live producer), /api/ward-heat
  permanently empty (no WARD_PLACED producer) (ROADMAP:57) - DEFER low-value/retired-panel. NOTE
  this connects to the SS6/7 ward-stack `?` marks - operator uncertain whether ward-heat stays.
  ACTION: one explicit keep-vs-retire decision (WP-F4a below).
- R10/R34 personal-corpus aggregators (lane-counter WR, duo-synergy home, per-opponent matchup
  table, snowball rating) (BACKLOG:41,155-157) - DEFER until Build Insights expansion.
- GPI Player Profile page, Personal-build/rune-write UI, Overlay App F lobby tags (BACKLOG:138-142) - DEFER.

### WP-F4a - Ward-stack keep-vs-retire decision

| Field | Value |
|---|---|
| Goal | Resolve the SS6/7 ward-coverage `?`+strikeout marks: decide keep or retire `core/ward_events.py`, `core/ward_producer.py`, `dashboard/routes_ward_heat.py` + the empty `/api/ward-heat`. |
| Files | `core/ward_events.py`, `core/ward_producer.py`, `dashboard/routes_ward_heat.py`; producerless `/api/ward-heat`. |
| TDD test first | If retire: `test_ward_heat_route_removed.py` (route gone, no import refs). If keep: a producer test wiring WARD_PLACED. |
| Tier | Tier-1 (retire path) / Tier-2 (new producer). |
| Acceptance | Either the ward stack has a live producer + non-empty route, or it is retired with all refs removed (decommission completeness sweep). |
| Deps | Operator keep-vs-retire call (feedback_decisions_not_operator_gated -> act, record in tracker). |

## F.5 - Auditor proposals (agents/agent6_auditor)

M04 / M05 / H02 / M01 DONE 2026-06-28/29 - SHAs + closure notes in Section J. Open:

| ID | Item | Severity | Action | Tier |
|---|---|---|---|---|
| WP-F5-L03 | p0_inventory_full.csv stale post-deletion paths (rows 16915/20605/20608) | LOW | Regenerate CSV after quiescent point OR add `# inventory frozen at <date>` header | Tier-0 |

Auditor RESOLVED/MOOT (do NOT carry forward): C-01 cron silent-fail, H-04 watcher-freshness,
audit7-h01, audit8-m02, audit5 h01/h02/m01, audit6-m01, L-02 orphan gamepc.json.

## F.6 - Inline-TODO + stale-engine-header hygiene

### WP-F6a - Stale engine-header prune

DONE 2026-06-29 (b0720386; Section J row F6a): ARCHITECTURE engine header -> live pointer + guard
test. Standing rule kept: hardcoded engine-identity counts restate NOWHERE outside DAEMON_SLAYER.md.

### F.6b - Inline TODOs to surface (not all actionable now)

| TODO | File:line | Disposition |
|---|---|---|
| EHP-side enemy-CC consumer aram_tenacity_mult | `agents/daemon_slayer/ability_dps.py:90,694,1015` | DS-batch (Tier-2, gated) |
| Meraki no ability_haste_flat (item-AH data gap) | `ability_dps.py:71` | DS data note |
| Arena Silver augment lethality not modeled | `augments.py:130` | DS-batch |
| ~174/577 ratio blocks need live verify | `docs/DS_COMPLETENESS_GAP.md:85,144` | DS-batch gated |
| subtract owned sub-item values (items_recipes.json) | `web/js/panels/item_build.js:120` | RELEVANT - partial-component logic (WP-B3) needs recipe data; ~200 LOC operator-gated |
| TFT Set 17+ augment support | `item_build.js:251` | DEFER-TFT |
| Home "Tonight's Pick" hardcoded dummy | `web/js/main.js:3080`, `dashboard/builders_home.py:148,105` | DEFER - wire when queue_id ingest ships |
| retrain LR on N>=20 timelines | `core/post_game_score.py:220` | GATED data |
| is_next_opponent / arena dataset gap | `coaches/_arena_item_advisor.py:13,97` | DEFER |
| NSIS/MSIX/Inno installer | `tools/build_installer.py:8` + DISTRIBUTION/DEV/LAUNCH docs | DEFER (release trigger) |
| Auto-ops verb-expansion gate (~550-day ETA) | `tools/AUTO_OPS_VERB_EXPANSION_GATE_PROBE.md:7` | EXPLICIT PARK (close perpetual deferral - WP-F6c) |

### WP-F6c - Park the auto-ops verb-expansion gate

| Field | Value |
|---|---|
| Goal | Stop perpetually deferring the auto-ops verb-expansion gate (blocked on a 95% sample gate with ~zero accrual, ~550-day ETA). Make an explicit park/close decision instead. |
| Files | `tools/AUTO_OPS_VERB_EXPANSION_GATE_PROBE.md:7`; ROADMAP/BACKLOG entries (gated bridge/auto-ops). |
| Tier | Tier-0 (doc decision). |
| Acceptance | One explicit PARKED-with-reason entry (or close) replaces the perpetual-defer; bridge largely Peer-decommissioned context noted. |
| Deps | None. |

## F.7 - Research / theorized (condition-to-act only - do NOT build now)

`.rofl` Layer-1 spike (BACKLOG:64); PyInstaller/OBS publisher (BACKLOG:65-66); Arena S2 augment
Level-Up (trigger 26.09 PBE) (BACKLOG:109); Brawl re-enable (external trigger) (BACKLOG:110);
CommunityDragon broader catalog (trigger PGR S2) (BACKLOG:114); draft-model references (BACKLOG:111-113);
LCU deeper/KebsCS endpoints (BACKLOG:27,71); competitor teardown (BACKLOG:70-71); s220 PGR reframe
tails (ROADMAP:92,94). All THEORIZED/DEFER - keep as reference, no WP.

---

# SECTION G - UX DOCTRINE APPENDIX (R2)

Every UI work package in Sections A, B, D MUST satisfy these. Sources: Kurtenbach/Buxton marking
menus, NN/g + Baymard tooltip timing, WCAG 1.4.1 / AA contrast, HUD glance doctrine, hysteresis.

## G.1 Sizing tokens (px at 1920x1080 baseline)

| Token | Value | Use |
|---|---|---|
| `--ovl-icon-primary` | 48px | build-row item icons |
| `--ovl-icon-component` | 28px | partial-component pips |
| `--ovl-icon-action` | 40px | radial wedge icons |
| `--ovl-font-label` | 14px bold | Sell/Next tags (WCAG large-text bold floor) |
| `--ovl-font-name` | 16px | tooltip item name |
| `--ovl-font-meta` | 13px | DS-knobs row (operator font floor) |
| `--ovl-gap` | 8px | 8px spacing grid |
| `--ovl-row-h` | 64px | icon + label + padding |

MUST: never shrink content to fit - trim items shown instead. Floors ~13/15/18px.

## G.2 Color / state semantics (redundant-coded - WCAG 1.4.1: color never the only signal)

| State | Color | Redundant cue (the real signal) | Contrast |
|---|---|---|---|
| Owned | desaturated/grey | 40-50% opacity + check glyph + sorted row-left | n/a |
| Recommended next | warm gold | bright ring/glow + "-> next" tag + full opacity | >=3:1 |
| Sell/replace | red | red X overlay + dimmed icon | >=3:1 |
| Partial component | neutral | progress pip / fractional ring on target icon | >=3:1 |
| Meta (not yet relevant) | muted | lower row + smaller + no glow | >=3:1 |

Non-text UI >=3:1; tooltip body text >=4.5:1. Name tokens by purpose (`--state-owned`,
`--state-next`, `--state-sell`), not hue. Greying=owned reinforced by left-position so colorblind
read of done-vs-todo survives.

## G.3 SELL/SWAP visual language

One horizontal triplet on one line: `[A](dim, red X)  ->  [B](glow ring)` + optional 14px `swap`
tag. NEVER stack reasoning (defer the "why" to the tooltip). Animate the arrow only on first
appearance of a NEW swap, then hold static.

## G.4 Tooltip spec

Show delay 300-500ms after cursor settles; hover feedback <=100ms; tooltip body renders <=100ms;
hide grace ~0.5s (up to 1.5s if reading). Anchor on the screen-edge/HUD-corner side, expand AWAY
from the play area (never cover minimap/champion). Never appear with no cursor over the module.
Content order: bold name 16px -> one when-to-buy line 13px -> optional swap reason. Tooltip is the
ONLY place prose is allowed.

## G.5 Radial / marking-menu spec

Exactly 5 actions, one ring, depth-1 (keeps error <10% per Kurtenbach <10%-error envelope at
breadth-8/depth-1-2). 4 ordering actions on the 4 CARDINAL axes (highest-accuracy zones); the
destructive/low-frequency Silence on diagonal/center so a sloppy flick cannot mute by accident.
Mirror League Smart-Ping interaction (hold-click -> drag-direction -> release). Novice: pop menu +
select; expert: flick the mark without waiting (faster over a season, no interaction change).
Guide-ring + wedge labels for first N uses, fading to expert.

| Dir | Action | Semantic |
|---|---|---|
| N | Build-Earlier | shift left, overtakes nearest neighbor |
| E | Build-Later | shift right, overtakes nearest neighbor |
| S | Defer-Once | skip slot once, re-enter after one full item |
| W | Keep | lock pick, stop re-ranking it |
| Center/SW | Silence | stop suggesting changes, logged + reset via settings |

## G.6 Anti-flip-flop (stability)

Hysteresis (asymmetric thresholds): promote a new top recommendation only if challenger beats the
incumbent by a margin (>5-10%), not on a hairline lead. Debounce repaints (coalesce, repaint only
after input settles). Schmitt-trigger on counter-build pivots (cross HIGH threshold to add a
defensive item, fall below a LOWER threshold to drop it). Idempotent render: stash a content
signature, skip the DOM wipe if unchanged; atomic-write-then-replace so mid-write polls never see
half-state. Motion restraint: animate only on a genuine state change, once, briefly - never loop
or pulse in peripheral vision.

## G.7 MUST / SHOULD checklist (gate for every UI WP)

MUST: (1) every state = color + non-color cue; (2) non-text >=3:1, tooltip text >=4.5:1; (3) swap
= one horizontal triplet, no prose; (4) radial exactly 5, one ring, depth-1, cardinal ordering +
diagonal Silence; (5) tooltip 300-500ms show / <=100ms feedback / 0.5s hide grace; (6) tooltips
anchor toward HUD edge, away from play area, never cursor-absent; (7) show swap/next only past the
hysteresis margin, debounce, idempotent atomic render; (8) owned grey + sort left, first non-grey =
next buy; (9) animate only on real state change, once; (10) ASCII rule + 13px meta floor, trim not
shrink. SHOULD: mirror Smart-Ping; guide-ring fading novice->expert; operator scales size + picks
corner; optional audio cue for a new swap.

## G.8 Horizontal 3-row layout

```
Row 1 (Live):  [owned][owned] [A X-> B] [NEXT*] [comp-pip] [...]   L->R purchase order, full contrast
Row 2 (Meta):  [item][item][item][item][item]                      muted reference order, right-click cycles alts
Row 3 (Knobs): tier . spike . DS-version . toggles                 13px meta, no glow, never animate
```

Row1 Live vs Row2 Meta contrast IS the "live vs meta" signal (opacity + size, not color alone).
Greying owned left-to-right makes "where am I in the build" a pre-attentive read. Partial
components = sub-component at 28px + fractional ring on the target. Row3 knobs reference-only.

## G.9 Mandatory UI-audit ritual gate

Any UI page change runs the 5-phase visual-hierarchy/fixture audit subagent BEFORE commit+push:
STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY. Every MUST-FIX resolved in the same
slice. No page ships ahead of its audit. Applies to WP-A1,A4,A5,A6,B2,B3,B4,D1,D2,D3.

---

# SECTION H - SEQUENCING + DEPENDENCY GRAPH (spent)

Waves W0-W5 executed - per-WP statuses + SHAs in Section J. Full wave plan + collision map
relocated verbatim to docs/history_notes.md (mdclean C7, 2026-07-17).
Open tail = W6 hygiene: F6c auto-ops park + F5-L03 inventory csv (both OPEN in Section J).

---

# SECTION I - EXECUTION ORCHESTRATION (spent)

The run's loop-harness mechanics (per-cycle contract, stop conditions). Run complete; I3 DONE
(Section J). Relocated verbatim to docs/history_notes.md (mdclean C7, 2026-07-17).

---

# SECTION J - EXECUTION TRACKER (the loop updates this each cycle)

Status legend: OPEN (ready when deps DONE) / WIP (claimed this cycle) / DONE (merged + CI green) /
GATED (needs a live game or operator decision) / DEFER (out of this program).

| WP | Wave | Deps | Tier | Status |
|---|---|---|---|---|
| A1 settings sliders | W0 | - | T1 | DONE 2026-06-28 |
| A2 drop legacy enemy-summs | W0 | - | T1 | DONE 2026-06-28 (7205d73c) |
| A3 coach [t] strip + truncation | W0 | - | T1 | DONE 2026-06-28 (ea100097) |
| A4a role-bracket bench route | W0 | - | T2 | DONE 2026-06-28 (c172f6b5) |
| A4b stats vertical frontend | W1 | A4a | T1 | DONE 2026-06-28 (14effd16) |
| A5 enemy-spells widen+unname | W1 | - | T1 | DONE 2026-06-28 (69a3929f) |
| A6 remove pane name headers | W1 | A5 | T1 | DONE 2026-06-28 (b089d130) |
| B1 strip DS-ENGINE caption | W1 | - | T1 | DONE 2026-06-28 (62a9a10a) |
| B2 horizontal 3-row scaffold | W3 | B1, C5 | T1 | DONE 2026-06-29 (adedacde) |
| B3 Live+Meta item semantics | W4 | B2 | T1 | DONE 2026-06-29 (be48d3f7) |
| B4 MF SR fixture oracle | W3 | B2, C2 | T1 | DONE 2026-06-29 (189117d6) |
| C1 kit-synergy profiles | W2 | - | T1 | DONE 2026-06-28 (a4e1cde3) |
| C2 scoring + beam search | W2 | C1 | T1 | DONE 2026-06-29 (4f1d4126) |
| C3 live counter-build | W3 | C2 | T1 | DONE 2026-06-29 (64b7c634) |
| C4 owned re-plan + hysteresis | W3 | C2, C3 | T1 | DONE 2026-06-29 (51f3141d) |
| C5 /api/build-plan contract | W2/W4 | C2 | T2 | DONE (cedb78c2) |
| D1 item tooltip | W5 | B2 | T1 | DONE |
| D2 right-click radial | W5 | B2, D3 | T1 | DONE (UI + store + client reorder + overlay data-rc-zone; D3 owns server-honoring) |
| D3 override state + reset | W5 | C4, D2 | T1 | DONE 2026-06-29 (c24c5162) |
| E5 doc remediation sweep | W0 | - | T0 | OPEN |
| F5-M04 decisions drift | W0 | - | T1 | DONE 2026-06-28 (e599e610; drift closed at 1.1, 1.2 bump operator-declined) |
| F5-M05 smb_push deadcode | W0 | - | T1 | DONE 2026-06-28 (c20d75da; Path A defer-delete, audit-11 M-05) |
| F5-H02 task_queue leak | W0 | - | T1 | DONE 2026-06-29 (decd681f; gate-limbo reaper + 1566 orphans backfilled) |
| F5-M01 body-data-mode test | W0 | - | T1 | DONE 2026-06-29 (76a783b4; cross-seam no-flap guard tests/preflip_mode/test_body_data_mode_no_flap.py. Audit's e4b08ba SHA wrong - real fix 5bfa7ea5; existing per-seam suites pinned each half, this ties them) |
| F5-L03 inventory csv stale | W6 | - | T0 | OPEN |
| F6a stale engine-header | W0 | E5 | T1 | DONE 2026-06-29 (b0720386; ARCHITECTURE:172 -> live-pointer + guard test. CLAUDE.md untouched: 24KB < 60KB, current. test_engine_version_is_1_X rename deferred - Share-mirror churn) |
| F4a ward keep-vs-retire | W4 | operator | T1 | GATED |
| F6c park auto-ops gate | W6 | - | T0 | OPEN |
| I3 loop stall-recovery | pre | - | T1 | DONE 2026-06-28 |

GATED-on-live-game (verify-pass after W1 + W5, not a cycle): F1-04, F1-05, F1-06 (F1-01
LIVE-CONFIRMED 2026-06-29, LEDGER 685).
DS-batch (separate Tier-2 ENGINE sessions, NOT this loop): all of F.2. DEFER/THEORIZED: F.7.
