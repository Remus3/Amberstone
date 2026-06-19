# Live-Haiku call inventory - charter-4b Haiku-to-ZERO next-target map

Cycle 55 (2026-06-16), Gemini-directed (DECISION B). Read-only audit. No code change, no engine bump, no flip.
Model across all sites: `claude-haiku-4-5-20251001`. North star = drive live in-game Haiku spend to ZERO via precompute + do-not-flip-blind validation.

## Ranked by execution frequency (= Haiku spend)

### TIER 1 - per-tick in-game coaches (~8s cadence, continuous per game) = dominant spend
- `coaches/aram_coach.py:768,937` - ARAM live coach (Coach(BaseCoach))
- `coaches/arena_coach.py:634,758,868` - Arena live coach + augment rec + augment-resolve
- `coaches/sr_coach.py` (Coach(CoachIntegration)) - SR live coach (per-tick via integration loop)
- `coaches/tft_coach.py` / `tft_pbe_coach.py` - TFT live
- `coaches/brawl_coach.py:475` - RETIRED mode (deadcode, not live; brawl off champ-select)

HZ precompute TARGETS this tier. Status: laning verdict (action/choices) flip = data-blocked (capturer complete 456+458+459, awaiting alive ticks under guard); build lean = item-457 done / build agreement structurally N/A (item 456 finding).

### TIER 2 - per-champ-select (once/game, pre-game, debounced)
- `coaches/champ_select_coach.py:130` purpose=`champ_select_coach` - the pick-advisor (`/api/champ-select-coach` POST via `dashboard/routes_coach.py:156`). STILL ON HAIKU. NOTE (cycle 56 correction): this is a DISTINCT surface from the champ-select BRIEF. The brief (`dashboard/_champ_select.py` brief_via_coach) + its substrate `_champ_select_deterministic.py` (item 280) were FLIPPED off Haiku 2026-06-06 (items 273/276/280/283); the "AST guard keeping the SERVED brief on Haiku" no longer holds. The pick-advisor has NO deterministic substrate of its own.

### TIER 3 - one-shot / on-demand = lowest spend
- `coaches/aram_team_analyzer.py:201` purpose=`aram_team_analyzer` - item 280 RETIRED the main path; Haiku fallback only for <3-champ teams
- `coaches/replay_coach.py:197` purpose=`replay_coach` - post-game, once/game
- `coaches/experimental_builder.py:214` purpose=`experimental_builder` - user-triggered

(Sonnet, not Haiku: `modes/shared_vision.py:248` vision - out of charter-4b scope.)

## Binding constraint
Every remaining live-Haiku flip is do-not-flip-blind = gated on real-game precompute-vs-Haiku shadow data. The #1-frequency Tier-1 laning flip is code-complete and blocked ONLY on game volume. So the program bottleneck right now is GAMES PLAYED, not code.

## Single best NEXT precompute target (Gemini-requested)
**CYCLE-56 CORRECTION (verified against live code):** the target below is REFUTED. It was named off the STALE docstring at `dashboard/_champ_select_deterministic.py:24` ("shadow-logs this alongside"), NOT the live served surface. `dashboard/_champ_select.py` shows the champ-select BRIEF was already FLIPPED off Haiku 2026-06-06 (items 273/276/280/283; "Haiku eliminated"): `brief_via_coach` returns `brief_deterministic(...)` with zero Anthropic call. A shadow capturer for the brief would compare the deterministic output against itself = validates nothing. Cycle 56 did NOT build it; the stale docstring was corrected.

CORRECTED remaining champ-select Haiku target = `coaches/champ_select_coach.py:130` (the pick-advisor, a DIFFERENT surface). It has NO deterministic substrate, so a shadow lane needs a NEW precompute pick-advisor candidate built FIRST (then shadow-validate, then flip) - a net-new design cycle + Gemini decision, NOT the "mirror hz_choice_shadow + wire" simple task named below.

--- ORIGINAL cycle-55 recommendation (RETAINED for provenance, now refuted) ---
**Tier-2 `champ_select_coach`: build the MISSING champ-select shadow capturer.**
Root cause: the deterministic substrate exists (item 280) and its docstring (`dashboard/_champ_select_deterministic.py:24`) claims it "shadow-logs this alongside", but there is NO champ-select shadow module (`core/*shadow*.py` has det/ds/hz_build/hz_choice/live_benchmark - none for champ-select) and NO `data/*champ*select*shadow*.jsonl`. So the champ-select flip track accrues ZERO validation data on every game - permanently flip-blocked until a capturer is wired.

Recommendation: mirror `core/hz_choice_shadow.py` (fail-soft, atomic append, coarse-state dedup, native-vs-precompute capture) for the champ-select brief, wired at the champ-select state-build site, so EACH queued game feeds BOTH the laning track AND the champ-select track in parallel. Code-actionable now (capturer missing, not data-blocked), root-cause-first, TDD, Tier-1. Defer the flip itself to do-not-flip-blind after data accrues.

## UPDATE 2026-06-18 (run 2026-06-18-03) - pick-advisor substrate + capturer BUILT

The corrected Tier-2 target (the `champ_select_coach` PICK-ADVISOR, not the already-flipped brief) now has BOTH missing pieces (commit `a31ef769`):
- `core/champ_select_advisor_deterministic.advise_pick` - the deterministic v1 candidate the pick-advisor lacked. Composes surfaces RC already trusts: `aram_comp_verdict` (ARAM bench swap + comp factors) + archetype tags. Mirrors coach_pick's advice fields {advice, swap, summoners, watchout}. No Anthropic call, fail-soft.
- `core/champ_select_shadow.log_champ_select_advice` - the missing capturer (mirrors `hz_choice_shadow`), wired fail-soft at `dashboard/routes_coach.py` AFTER the live coach_pick. Records native Haiku advice vs the deterministic candidate to `data/champ_select_shadow.jsonl` per distinct pick state. NO change to served output.

The pick-advisor flip is now DATA-BLOCKED, not code-blocked: each queued game with a champ-select feeds the validation lane. NEXT = accrue real-game shadow rows -> det-vs-Haiku agreement analysis -> THEN the flip (do-not-flip-blind). The v1 deterministic candidate is intentionally conservative (e.g. archetype-keyed summoners); refine it once agreement data shows where it diverges from Haiku.

## UPDATE 2026-06-19 (run 2026-06-19-01) - laning bottleneck reclassified: CALIBRATION, not volume

Ran `tools/hz_shadow_report.py` over the accrued real-game shadow logs (1490
laning rows / 1488 build rows). The "Binding constraint" claim above ("bottleneck
= GAMES PLAYED, not code") is now SUPERSEDED for the #1-frequency Tier-1 LANING
flip: enough games have accrued for a clear signal (693 comparable-covered ticks,
42% table coverage), and the binding constraint is AGREEMENT QUALITY, not volume.

- **Laning agreement is 39% (160/406 comparable-covered).** Flipping today would
  change ~60% of laning verdicts vs what Haiku says - the do-not-flip-blind gate
  is correctly holding. The blocker is the precompute's calibration, not games.
- **Root cause (confusion matrix, now emitted by the report):** the precompute
  verdict vocabulary only ever produces `back_off` (225) or `trade` (181). It has
  NO `hold` / `farm` band, but Haiku says `hold` on 114 of the 406 comparable
  ticks (28%). And it is back_off-biased (precompute back_off 225 vs Haiku 69).
  Top mismatches: precompute `back_off` while Haiku `trade` x112; precompute
  `back_off` while Haiku `hold` x57; precompute `trade` while Haiku `hold` x57.
- **NEXT (Tier-2, operator/Gemini-gated - a product-calibration call, NOT a blind
  overnight edit):** add a `hold`/even band to the laning scenario verdict mapping
  (`agents/daemon_slayer/scenario_matrix.py` / `fight_report.py`) + soften the
  back_off threshold, regenerate the `data/daemon_slayer/laning_scenarios` tables
  (LFS), then re-run `hz_shadow_report.py` and confirm agreement climbs before any
  flip. The report's new confusion matrix is the per-iteration measurement.
- The BUILD agreement lane is still 0/0 comparable (the native Haiku build side
  logs no comparable verdict) - build flip-readiness remains unmeasured, separate
  from laning.
