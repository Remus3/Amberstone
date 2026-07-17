# FORWARD LEAP PLAN - Fable 5 portfolio (authored 2026-07-16/17)

Goal line: front-load the thinking into specs; execution sessions are typing, not deciding.
Provenance: PROMPT A of docs/specs/2026-07-16-fable5-forward-leap-kickoff.md executed end-to-end -
P0 4x sonnet recon (all spot-checked) -> P1 Fable leverage ranking -> P2 8x opus spec authoring ->
P3 3x opus adversarial judges (shipped/settled, gating/tier, cold-executor) -> P4 this emit.
Judge outcome: ZERO kills, 8/8 survive; 4 specs carry a P3 AMENDMENT block at the top of the file
(that block supersedes conflicting body text). Citation spot-audit hit rate ~100 percent.

## How to use
One item per session. /clear first. Paste the item's kickoff prompt (files below) into a fresh
Opus 4.8 session. The spec file is the SOLE work source; its AMENDMENT block (if present) wins
over body text. Session ends with the /done ritual per kickoff. Do not run two engine-bump items
without landing the first (version-literal collision - see EXECUTION ORDER).

## Ranked portfolio (value order)

| Rank | Item | Spec | Real scope after evidence pass | Tier | Sessions |
|---|---|---|---|---|---|
| 1 | LEAP-01 PGR S2 layout | docs/specs/leap/LEAP-01-pgr-s2.md | Compose SHIPPED pgr_* panels into single-scroll aggregator-G-style layout; retire 3-tab split; headline score stays S3 | UI (5-phase fixture audit) | 1-2 |
| 2 | LEAP-05 ARAM augment fast-poll | docs/specs/leap/LEAP-05-aram-augment-cadence-fastpoll.md | 6s early-game vision poll (<45s, 6-scan cap, latch on fire) + RC_ARAM_FAST_POLL kill-switch; fixes real in-game reco miss | Tier-1 | 1 short |
| 3 | LEAP-03 onhit consumer completion | docs/specs/leap/LEAP-03-onhit-consumer-completion.md | /rank-onhit (+siblings) mode/phase parity; onhit into ARCHETYPES/IMPLEMENTED_SCORERS + chip tint; DS.md picker section fix | Mixed (route Tier-2 no-bump, JS asset-only) | 1 short |
| 4 | LEAP-06 R129 residuals | docs/specs/leap/LEAP-06-r129-viego-hybrid-xor.md | Viego R 120 percent AD load-side allowlist (+5 sibling exclusion tests); blend_ability_axis Riven/Jarvan; default-OFF | Tier-2 (real bump) | 1 |
| 5 | LEAP-08 C3 fed criterion | docs/specs/leap/LEAP-08-c3-fed-criterion.md | Feed the already-plumbed fed gate: est_gold estimator + route population; shadow-first double-flag OFF | Tier-1 | 1 |
| 6 | LEAP-04 build-order regen guard | docs/specs/leap/LEAP-04-build-order-precompute-backfill.md | Design-Q ANSWERED (generator routes through dock); confirmatory regen + first Family A staleness/parity guard | Tier-1 actual | 1 |
| 7 | LEAP-02 KaiSa P routing | docs/specs/leap/LEAP-02-ds-staged-passives-gwen-kaisa.md | Route KaiSa P (byte-identical, flip LGS-queued) + regression-pin Gwen P + refresh 2 stale STAGED markers | Tier-2 (bump) | 1 |
| 8 | LEAP-07 coherence calibration r2 | docs/specs/leap/LEAP-07-build-coherence-calibration-r2.md | RETIERED core-side no-bump: AP-hybrid class seam (empty map) + KaiSa Eclipse pin + Varus/MF fight_length 0.5 + regen | Tier-1-plus-regen | 1 |

## EXECUTION ORDER (dependency-safe; differs from rank)
05 -> 01 -> 03 -> 04 -> 06 -> 02 -> 07 -> 08
Constraints encoded: 07 consumes 04's regen procedure (04 strictly before 07); 06 and 02 both
bump ENGINE - serialize, and NEVER hard-pin the bump literal (read current, +1 minor, fix RED-test
literals at write time); 03 touches server.py byte-identical (safe before bumps); 05/01/08 standalone.

## P3 amendments applied (top-of-file blocks)
- LEAP-01: winprob is SR-only mode-gated (last_match.js:1476) - named in D5, slot reserved on ARAM/Arena.
- LEAP-05: RC_ARAM_FAST_POLL kill-switch (default on; =0 restores legacy 25s byte-identical).
- LEAP-06: no hard-pin of 1.217.0; strike the no-op Family A "engine field re-stamp" step.
- LEAP-07: MANDATORY retier core-side (2/3 refute) - no bump, no Share, no DS restart; RC
  restart_trigger.txt + precompute regen after LEAP-04; LEDGER 885 precedent.

## Excluded from portfolio (do not resurrect without NEW evidence)
- AD-assassin lethality reweight: CONTESTED (LEDGER 889 data-refuted R115); Lane R meta-research may re-open.
- Hexplate/Axiom ult-cadence: half-closed (history item 310 uniform-AH deliberate).
- Malignance conditional-shred + Navori Transcendence CDR uptime: real but narrower; next round.
- Ward-heat producer: NO ward x/y data source exists (BACKLOG:174 closed the sibling for exactly this).
- Haiku-elimination fidelity-or-pivot decision: needs 20+ game calibration corpus first (ROADMAP:105).
- In-game UI finish tail (LEDGER 859/860): live-gated punch list -> drain sessions, not headless specs.
- Step-3 ally-synergy + NL explainer: defer one round (collides with LEAP-04 surface churn).

## Quick wins (no spec needed; fold into any session's slack)
- item-211 orphan rewind rows (7) recovery-or-clear (ROADMAP:83).
- Deploy-allowlist prune + phase_watcher test relocate + keybind_listener archive (ARCHITECTURE.md:217,223-224).
- DAEMON_SLAYER.md drift: 8502-vs-11701 test counts (:5 vs :140); 547-vs-706 item denominators.
  (Tonight's md-cleanup loop may already clear these - re-check before touching.)

## Tonight's parallel lanes (context for morning merge)
- Lane R (pid 23776) docs/research-20260716: DS meta-valuation + KaiSa Manamune + patch 16.15;
  competitor findings NON-repo. Merge branch in the morning.
- Lane U (pid 17224) ui/overlay-item4-item8-20260716: overlay item 4 + 8 backend TDD, NO merge -
  run the 5-phase audit THEN merge.
- md-cleanup loop: 8 Tier-0 doc cycles, self-defers while LW bridge alive, window "RC" hwnd-bound.
- Morning ritual: read ops/loop/reports/lane_*.log + done-sentinels + this plan; then execute
  portfolio items one per session in EXECUTION ORDER.

## Verification ledger (what was probed tonight)
- P0 recon A/B/C/D spot-checks: LEDGER 911 top entry; DS.md:15 seven scorers; live health green
  (RC pid 27616, DS :8893 1.216.0/16.14.1/173/706, rc 3.5.0); OP:354 R119 futures verbatim.
- P2: 6 of 8 briefs shrank/corrected against ground truth (shipped items 248/249, LEDGER 823
  picker removal, dock-not-bypassed, KaiSa Eclipse drift, Zeri sim-credit gate, fed gate plumbed).
- P3: ~24 load-bearing citations re-read by judge 3 - all exact; DS :8893 second-probed alive
  after one subagent down-report (200 ok).
- 6 UNVERIFIED-SKIP markers total across specs, every one framed as an executor RED-first probe.
