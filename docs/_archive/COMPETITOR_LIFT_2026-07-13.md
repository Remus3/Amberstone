# Competitor Lift - Aggregator D + Aggregator C RE-REVIEW (R112, 2026-07-13)

## Verdict up front

CLEAN no-ship, category DRAINED. The R112 directive asked for a Section-7b
heavyweight deep-dive of aggregator D ("champion synergy, counter-stats") and
aggregator C ("combat patterns, build deltas"). Ground-truth premise check
before any web fetch: BOTH targets were already fully torn down, one of them
three days ago, and all four named sub-angles resolve to already-triaged
findings. No lift from either site is simultaneously (a) presentation-only over
existing RC data / DS math, (b) free of a new Riot/Claude dependency, (c) free
of a schema lift, (d) snapshot-testable, AND net-new (not already shipped or
already parked in BACKLOG-FUTURE). This is the R44 / R85 / R94 / R98 / R100
research-only precedent, not a build cycle.

## Why this is a re-review, not a fresh teardown (premise correction)

The gemini director's own premise-check line only diffed this pick against the
immediately-prior cycle ("NOT-A-DUPLICATE-OF: LIFT1"), so it did not catch that
both named targets already have full artifacts in the repo:

- Aggregator D: `docs/COMPETITOR_LIFT_2026-06-27_AGGREGATOR_D.md` (R34, 2026-06-27) -
  12 findings F1-F12, each on the 6-point checklist, triage table at that file's
  lines 205-218. F1 (popular-vs-winrate dual build) SHIPPED in-run.
- Aggregator C: `docs/COMPETITOR_LIFT_2026-07-10.md` (R89, 2026-07-10, three days
  ago) - two features F1/F2 on the 6-point checklist, decomposed to
  F1a/F1b/F2a/F2b in BACKLOG.md:224-230. F2 (combat-style archetype chip)
  SHIPPED in-run.

Per the standing "audit proposals are intent, verify vs ground truth" rule
(memory feedback_audit_proposals_are_intent) and the OQ7/OQ10 "PREMISE STALE -
already shipped, re-verified fresh" pattern, the correct execution is to
re-verify the drained state rather than re-run a redundant web scrape of two
Cloudflare-gated sites that would only re-derive closed findings.

## The four named sub-angles map 1:1 to already-triaged findings

| Directive angle | Prior finding | Disposition |
|---|---|---|
| aggregator D champion synergy | R34 F11 (duo/pairwise synergy grid; COMPETITOR_LIFT_2026-06-27_AGGREGATOR_D.md:185-193) | FUTURE - RC has `/api/duo-synergy` (`core/synergy_external_source.py` + `core/smoothed_rates_101qq.py`, item 277); a non-champ-select home is a product-placement call, not a presentation lift. |
| aggregator D counter-stats | R34 F3 (per-opponent matchup delta-stats table; COMPETITOR_LIFT_2026-06-27_AGGREGATOR_D.md:76-97) | FUTURE - inputs are RECORDED (`core/match_metrics.py:246` csd_at_15, `core/draft_elo_db.py:167` matchup_winrate) but NO aggregator exists; needs a new aggregation over the gitignored `rewind_history.db` = "do not build blind in-run". |
| aggregator C combat patterns | R89 F2 (combat-style archetype tag; 2026-07-10.md:126-224) | SHIPPED - `web/js/panels/archetype_chip.js`, the CARRY/BRUISER/TANK/MAGE/ASSASSIN/ENCHANTER chip on the champ-select My Pick card (LEDGER, R89 build outcome). |
| aggregator C build deltas | R89 F1/F1a (build-page Weak/Strong/Synergy chips; 2026-07-10.md:47-49) + R34 F2 (delta-vs-baseline signature; `core/personal_build_wr.py:224`) | FUTURE / SHIPPED - the per-item delta-vs-baseline column is already SHIPPED (R34 F2, the signed +pp/-pp lift column); the WR "best/worst counters" list half is FUTURE (needs the live-WR lane wired into champ-select, a data dependency). |

## The one residual that passes the cheap gates is still not net-new

The only not-shipped, not-CLOSED finding across BOTH targets that passes
presentation-only + no-new-dependency + no-schema-lift + snapshot-testable is
R89 F2a (Arena My Pick archetype-chip parity - the SR/ARAM chip does not yet
render on the Arena `_csvArenaPaneHtml` pane, `champ_select.js:931`). It is a
pure-JS parity add. But:

- It is already logged FUTURE at BACKLOG.md:226, so it fails the "net-new" clause
  (this cycle would not be discovering it).
- It is LOW-lift (marginal Arena parity of an already-shipped chip), not the
  HIGH-lift the directive's build-gate requires.
- Its R89-scoped trigger is "next Arena champ-select pass", not a competitor-lift
  cycle - building it here jumps its queue for negligible gain.

Every other candidate (R34 F3/F8/F11, R89 F1a) needs a new aggregation or a
live-WR / 101qq data dependency and is already BACKLOG-FUTURE with a
do-not-build-blind label. The CLOSED set (global-meta tier lists, OTP / elite
strips, curated "how to play against" prose, pre-game behavioral badges, live
overlay) stays CLOSED per ADR-006 single-player-corpus + the
no-new-Claude-dependency guardrail.

## Independent verifier confirmation

A read-only verifier subagent, reading only the in-repo priors (no web fetch),
independently confirmed: both sites fully torn down; all four named angles map
to already-triaged findings (2 SHIPPED, 2 FUTURE/data-dependent); the sole
gate-passing residual (F2a) is already BACKLOG-FUTURE and is not a named angle.
VERDICT: DRAINED - no new NOW-buildable slice.

## Loop-health (second confirmation - the competitor-lift well is dry)

BACKLOG.md:240 already carries the R100 (2026-07-10, Overlay App F) LOOP-HEALTH
note that the live-scouting / live-overlay competitor category is DRAINED and a
future competitor pick should target a DIFFERENT category or rotate to the
meatier lanes. R112 re-picking two already-torn-down stat aggregators is the
second confirmation that the whole stat-aggregator + scouting competitor
category is drained. The prior teardowns cover the field:

- Stat aggregators: Aggregator B (R10), the 2026-06-16 survey, Aggregator D (R34),
  Guide Site Q (R44), Aggregator H (R71), Aggregator N, Aggregator S, Aggregator C (R89).
- Live scouting / overlay: the R81 live-overlay lift + Overlay App F (R100), mapped
  ~90% onto FU02 + R81 + `core/event_callouts.py`.

## Recommendation - rotate the director off competitor-lift

The high-leverage move is not a marginal Arena chip; it is to stop the director
re-picking a drained category. A PART C durable hand-off has been written to
`ops/loop/control/gemini_ask.txt` asking the next director cycle to rotate to a
live lane:

1. DS-sweep Meraki(16.13.1)-vs-registry refute rotation (the R88/R97/R111 lane -
   fresh unmodeled item combat-stat / EHP / pen seams, ENGINE bump + Tier-2).
2. Haiku-to-ZERO Lane A (combat-trigger scenario precompute) or Lane E
   (client-side CV vision atlas) precompute programs (charter section 4b PRIMARY
   north star).

A future competitor pick, if any, must target a genuinely un-torn-down category
(draft theory, replay-VOD, economy-wave tooling), never a re-pick of a site
already in `docs/COMPETITOR_LIFT_*.md`.

## Lift policy honored

No in-run ship, so no vendored code. Consistent with the 14 prior
`docs/COMPETITOR_LIFT_*.md` artifacts and the deferred-to-release name-scrub
policy (memory project_pre_release_name_scrub - the broad content + history
scrub fires only at the public-release trigger, not now), competitor names
appear in this docs artifact only, not in any repo source. Public data sources
the pipeline legitimately uses (Riot Data Dragon, CommunityDragon, Meraki, the
LoL wiki, Riot API) are credited and retained.
