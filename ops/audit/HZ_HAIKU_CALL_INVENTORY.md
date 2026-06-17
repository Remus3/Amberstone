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
- `coaches/champ_select_coach.py:130` purpose=`champ_select_coach` - has a deterministic substrate (`dashboard/_champ_select_deterministic.py`, item 280) and an item-273 AST guard keeping the SERVED brief on Haiku.

### TIER 3 - one-shot / on-demand = lowest spend
- `coaches/aram_team_analyzer.py:201` purpose=`aram_team_analyzer` - item 280 RETIRED the main path; Haiku fallback only for <3-champ teams
- `coaches/replay_coach.py:197` purpose=`replay_coach` - post-game, once/game
- `coaches/experimental_builder.py:214` purpose=`experimental_builder` - user-triggered

(Sonnet, not Haiku: `modes/shared_vision.py:248` vision - out of charter-4b scope.)

## Binding constraint
Every remaining live-Haiku flip is do-not-flip-blind = gated on real-game precompute-vs-Haiku shadow data. The #1-frequency Tier-1 laning flip is code-complete and blocked ONLY on game volume. So the program bottleneck right now is GAMES PLAYED, not code.

## Single best NEXT precompute target (Gemini-requested)
**Tier-2 `champ_select_coach`: build the MISSING champ-select shadow capturer.**
Root cause: the deterministic substrate exists (item 280) and its docstring (`dashboard/_champ_select_deterministic.py:24`) claims it "shadow-logs this alongside", but there is NO champ-select shadow module (`core/*shadow*.py` has det/ds/hz_build/hz_choice/live_benchmark - none for champ-select) and NO `data/*champ*select*shadow*.jsonl`. So the champ-select flip track accrues ZERO validation data on every game - permanently flip-blocked until a capturer is wired.

Recommendation: mirror `core/hz_choice_shadow.py` (fail-soft, atomic append, coarse-state dedup, native-vs-precompute capture) for the champ-select brief, wired at the champ-select state-build site, so EACH queued game feeds BOTH the laning track AND the champ-select track in parallel. Code-actionable now (capturer missing, not data-blocked), root-cause-first, TDD, Tier-1. Defer the flip itself to do-not-flip-blind after data accrues.
