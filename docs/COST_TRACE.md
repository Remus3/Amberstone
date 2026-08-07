# LLM Call + Cost Trace (audit 2026-05-19, Phase 0 task 3)

Single source of cost truth: `core/cost_tracker.py::record_call(model, input_tokens,
output_tokens, cache_read, cache_write, purpose)` -> atomic `data/spend/YYYY-MM-DD.json`
(`total_usd`, `by_model`, `by_purpose`) + Prometheus (`rc_coach_calls_total`,
`rc_coach_tokens_total`, `rc_coach_cost_usd_total`). The DASHBOARD TOTAL is exactly
`get_tracker().daily_spend()["total_usd"]`, read by `dashboard/routes_metrics.py:85`,
`dashboard/routes_coach.py:27`, `dashboard/routes_state.py:205`. Local pricing table
(USD / 1M tok): haiku 0.80 in / 4.00 out; sonnet 3.00 / 15.0; opus 15.0 / 75.0.

`core/moon_proxy.py` does NOT call Anthropic - it HTTP-forwards to the in-process
vision server `:8889`, which calls Anthropic in `vision_server/_inference.py` and
records there. moon_proxy only does the 2s vision dedupe accounting.

## Call-site matrix (tier | tracked? | cadence | purpose)

| Site | Tier | Tracked | Cadence | purpose= |
|---|---|---|---|---|
| coach_integration/_coach.py:354 | HAIKU | YES (record_call :382) | POLLING (SR game loop) | sr_coach |
| coaches/arena_coach.py:587 | HAIKU | YES (_record_coach_call) | POLLING (game tick) | arena_coach |
| coaches/arena_coach.py:695 | HAIKU | YES | EVENT (augment select) | arena_aug_select |
| coaches/arena_coach.py:805 | HAIKU | YES | EVENT (anvil) | arena_anvil |
| coaches/aram_coach.py:743 | HAIKU | YES (cache_control ephemeral) | POLLING (game tick) | aram_coach |
| coaches/aram_coach.py:910 | HAIKU | YES | EVENT (augment select) | aram_aug_select |
| coaches/brawl_coach.py:439 | HAIKU | YES (cache_control ephemeral) | POLLING (game tick) | brawl_coach |
| vision_server/_inference.py:141 | SONNET | YES (_record_to_cost_tracker) | ON-DEMAND (/vision relay) | vision_relay |
| vision_server/_inference.py:176 | HAIKU | YES (_record_to_cost_tracker) | ON-DEMAND (/coach relay) | coach_relay |
| modes/shared_vision.py:251 | SONNET | YES (record_call :274) | POLLING (vision fallback) | vision_direct |
| coaches/aram_team_analyzer.py:161 | HAIKU | YES (record_anthropic_response) | ON-DEMAND (team comp) | aram_team_analyzer |
| coaches/experimental_builder.py:207 | HAIKU | YES (record_anthropic_response) | ON-DEMAND (build gen) | experimental_builder |
| coaches/champ_select_coach.py:116 | HAIKU | YES (record_anthropic_response) | EVENT (champ select) | champ_select_coach |
| coaches/replay_coach.py:192 | HAIKU | YES (record_anthropic_response) | ON-DEMAND (replay) | replay_coach |
| ~~dashboard/_champ_select.py:92~~ | RETIRED 2026-06-06 | n/a | n/a | ~~champ_select_brief~~ |
| tft/tft_coach_engine.py:692 | HAIKU | YES (record_anthropic_response, cache_control ephemeral) | POLLING (45s debounce) | tft_coach |
| tft/tft_pbe_engine.py:421 | HAIKU | YES (record_anthropic_response) | POLLING (game tick) | tft_pbe |
| tft/tft_live_analysis.py:292 | HAIKU | YES (record_anthropic_response) | POLLING (vision cycle) | tft_live_analysis |
| tft/tft_live_analysis.py:316 | HAIKU | YES (record_anthropic_response) | POLLING (aug select) | tft_live_aug_select |
| tft/tft_vision_reader.py:186 | SONNET | YES (record_anthropic_response) | POLLING (vision local fallback) | tft_vision |
| agents/agent7_context/warm_session.py:154 | HAIKU | YES (record_anthropic_response) | WARM (persistent session) | agent7_warm |

**CORRECTION 2026-08-06 - the `champ_select_brief` row above is RETIRED, not
stale-by-line-number.** It was accurate when this matrix was audited
(2026-05-19). The Haiku-elimination program flipped that surface on 2026-06-06
(items 273/276/280/283): `dashboard/_champ_select.py` is now a 26-line facade
whose `brief_via_coach` is a pure delegation to
`dashboard/_champ_select_deterministic.brief_deterministic`, with ZERO Anthropic
call and no `record_anthropic_response`. The `champ_select_brief` purpose key
survives in `core/cost_tracker.py:151` (a purpose-map entry, not a producer) and
can no longer accrue spend. The row is struck rather than deleted so the
`champ_select_brief` key in old `data/spend/*.json` ledgers stays explainable.
The `champ_select_coach` row above it is a DIFFERENT surface
(`coaches/champ_select_coach.py`, the pick-advisor) and IS still on Haiku.

**Every line number in the matrix above is from the 2026-05-19 audit and most
have since drifted** (measured 2026-08-06: e.g. `coaches/arena_coach.py:587` is
now `:797`, `coaches/aram_coach.py:743` is now `:1099`). Trust the matrix for
WHICH sites call Anthropic and with what cadence; do not trust it for where in
the file. `grep -rn "messages\.create" --include="*.py"` is the live census.

**DO NOT STRIP THE STALE LINE NUMBERS.** They are load-bearing despite being
wrong: `tests/test_cost_trace_matrix_is_live.py` identifies a row by its
`path.py:N` shape, so a row without one silently drops out of the guard's view.
The guard therefore requires EVERY row of this table to carry one, and fails if
any row stops parsing. Re-point them if you like; deleting them disarms the
guard. The table is 21 rows (20 live-tier plus the struck retired row) and the
guard pins that count exactly.

Tracked sites correctly extract `usage.input_tokens / output_tokens /
cache_read_input_tokens / cache_creation_input_tokens` (see
`coaches/_base_coach.py:506-518`); cache fields ARE wired - ledger
`cache_in/cache_write = 0` means the recorded ARAM/SR window simply got no
cache-read hits, not a plumbing gap.

## Opus / advisor path

No `def advisor(` and no Opus `messages.create` exist at runtime. `claude-opus-4-7`
appears ONLY in config/role tables: `ops/phase3_setup.py:77,80` (Agent-4 model_deep,
Agent-6 auditor), `agents/_supervisor_common.py:46` (AGENT_MODELS["6"]),
`core/cost_tracker.py:82` (pricing). Agent-6 (Opus auditor) is the budget-limited
Phase-3 cron; its spend would land in `record_call` only if the Phase-3 agent runtime
issues the call with model=claude-opus-4-7. Every recent ledger shows ZERO opus -
Opus is not a live billed path in the captured window.

## Reconciliation: tracked ledger vs dashboard total

The dashboard total IS the ledger (`daily_spend()["total_usd"]`); they are
definitionally equal and internally consistent (`total_usd` == sum of
`by_model[*].usd` == sum of `by_purpose[*].usd`, verified below). So there is no
tracked-vs-dashboard discrepancy. The real gap WAS **tracked ledger vs true
Anthropic billing**:

- **All 11 previously-UNTRACKED call sites were WIRED** (audit 2026-05-23);
  **10 of those wires survive - see the 2026-08-06 correction above.** The
  champ-select brief wire went away with the call site itself on 2026-06-06, and
  its `WiredSitesGrepTests` case was deleted with it. The list reads: all TFT
  engines (coach + PBE + live analysis x2 + vision reader), ~~champ-select
  brief (dashboard)~~, experimental builder, replay coach, champ-select coach,
  aram_team_analyzer, agent7 warm session. Each funnels through the shared
  `core.cost_tracker.record_anthropic_response(resp, model=..., purpose=...)`
  helper. The previously-latent gap (TFT/Arena/champ-select sessions invisible
  to the dashboard) is closed.
- A construction-layer shim `core.anthropic_client.tracked_anthropic(api_key,
  *, purpose, default_model="")` is available as defense-in-depth so a future
  12th call site is auto-tracked just by switching the import.
- Recorded spend is still an ESTIMATE (local pricing table, not Anthropic
  invoice); the gap between ledger and Anthropic billing now reflects pricing
  drift only, NOT untracked surface.

### Spend ledger (4 most recent, internal-consistency checked)

- 2026-05-17: total 1.024042, calls 340, by_model haiku 1.024042/340,
  by_purpose aram_coach 1.024042/340. SUM OK.
- 2026-05-16: total 3.950813, calls 926 = haiku 1.851704/628 (aram_coach) +
  sonnet 2.099109/298 (vision_relay). SUM OK.
- 2026-05-15: total 0.314323, calls 70 = haiku 0.128422/43 (aram_coach) +
  sonnet 0.185901/27 (vision_relay). SUM OK.
- 2026-05-14: total 0.470071, calls 161 = haiku 0.470071/161 (sr_coach). SUM OK.

## Recommended follow-ups - SHIPPED 2026-05-23

1. **SHIPPED** - All 11 untracked `messages.create` sites were wired to feed
   `core.cost_tracker.record_anthropic_response(resp, model=..., purpose=...)`
   (**10 today** - the champ-select brief site was retired 2026-06-06, see the
   correction above; this sentence read "All 11 ... now feed", present tense,
   until 2026-08-06)
   after a successful response. The helper is a single module-level chokepoint
   (sibling of the existing `coaches/_base_coach._record_coach_call` private
   method and `vision_server/_inference._record_to_cost_tracker` private
   helper) so the pricing-table + Prometheus path stays unified across coaches,
   TFT, dashboard champ-select, agent7 warm session.
2. **SHIPPED** - `core/anthropic_client.py` exposes
   `tracked_anthropic(api_key, *, purpose, default_model="")` returning a real
   `anthropic.Anthropic` client with `messages.create` rebound to a wrapper
   that auto-records. Defense-in-depth: future call sites that switch the
   import are tracked by default, even if the caller forgets to call the
   helper explicitly. Recording failures are swallowed; real API errors
   propagate.

Wired sites (`purpose` label is the by_purpose key in
`data/spend/YYYY-MM-DD.json`):

- `aram_team_analyzer`, `experimental_builder`, `champ_select_coach`,
  `replay_coach`, ~~`champ_select_brief`~~ (retired 2026-06-06, see the
  correction above - its `WiredSitesGrepTests` case was removed with the wire,
  so 10 of the 11 sites below are pinned, not 11), `agent7_warm`
- `tft_coach`, `tft_pbe`, `tft_live_analysis`, `tft_live_aug_select`,
  `tft_vision`

Tests pin the wire-in at each site (grep-based; see
`tests/test_cost_tracker_response_helper.py::WiredSitesGrepTests`) so a
future regression that rips the wire out fails CI before any live cadence
hits the missing telemetry.

## Prompt-cache floor (item 286) - aram_aug_select / tft_live_analysis CLOSED

The min cacheable prompt prefix for `claude-haiku-4-5-20251001` is **2048
tokens** (vs 1024 for Sonnet/Opus). A `cache_control` marker on a prefix below
that floor is INERT - the API does not cache it. The `aram_aug_select` /
`tft_live_analysis` "static/data split for caching" lane (re-surfaced as NEXT in
items 273/280/283/284) was measured to a decision in item 286 and CLOSED as
not-viable. Static portions (placeholders blanked):

| Prompt (purpose) | static chars | ~tok | vs 2048 floor |
|---|---|---|---|
| `aram_aug_select` (`_AUG_SELECT_PROMPT`) | 231 | ~62 | far below |
| `tft_live_analysis` (`_ANALYSIS_PROMPT_TEMPLATE`) | 2477 | ~669 | below |
| `tft_live_aug_select` (`_AUGMENT_SELECT_PROMPT`) | 188 | ~51 | far below |

Three independent blockers: (1) all static portions are far below the 2048-tok
floor, so caching yields ZERO benefit even after a perfect static-first split;
(2) `tft_live_analysis`'s primary call routes through the FROZEN single-string
`core.moon_proxy.get_coaching(prompt: str, ...)`, so a system/user split is
unreachable without editing a frozen file; (3) moving instructions user->system
is fidelity-gated on a live game. Guard: `tests/test_prompt_cache_floor_item286.py`
(fails loudly if a template later grows past the floor = re-derive + implement).

The `cache_control` pattern is correct ONLY where the static system prompt
clears 2048 tok: `tft_pbe` (`TFT_PBE_SYSTEM_PROMPT` ~2649c real ~2450 tok) is the
one live beneficiary; `tft_coach`'s `TFT_SYSTEM_PROMPT` (944 tok) carries a marker
that is itself sub-floor/inert (forward-marker, left as-is).
