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
| dashboard/_champ_select.py:92 | HAIKU | YES (record_anthropic_response) | ON-DEMAND (dash brief) | champ_select_brief |
| tft/tft_coach_engine.py:692 | HAIKU | YES (record_anthropic_response, cache_control ephemeral) | POLLING (45s debounce) | tft_coach |
| tft/tft_pbe_engine.py:421 | HAIKU | YES (record_anthropic_response) | POLLING (game tick) | tft_pbe |
| tft/tft_live_analysis.py:292 | HAIKU | YES (record_anthropic_response) | POLLING (vision cycle) | tft_live_analysis |
| tft/tft_live_analysis.py:316 | HAIKU | YES (record_anthropic_response) | POLLING (aug select) | tft_live_aug_select |
| tft/tft_vision_reader.py:186 | SONNET | YES (record_anthropic_response) | POLLING (vision local fallback) | tft_vision |
| agents/agent7_context/warm_session.py:154 | HAIKU | YES (record_anthropic_response) | WARM (persistent session) | agent7_warm |

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

- **All 11 previously-UNTRACKED call sites are now WIRED** (audit 2026-05-23):
  all TFT engines (coach + PBE + live analysis x2 + vision reader), champ-select
  brief (dashboard), experimental builder, replay coach, champ-select coach,
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

1. **SHIPPED** - All 11 untracked `messages.create` sites now feed
   `core.cost_tracker.record_anthropic_response(resp, model=..., purpose=...)`
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
  `replay_coach`, `champ_select_brief`, `agent7_warm`
- `tft_coach`, `tft_pbe`, `tft_live_analysis`, `tft_live_aug_select`,
  `tft_vision`

Tests pin the wire-in at each site (grep-based; see
`tests/test_cost_tracker_response_helper.py::WiredSitesGrepTests`) so a
future regression that rips the wire out fails CI before any live cadence
hits the missing telemetry.
