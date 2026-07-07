# RC Budget-Saver / Local Fallback Brain - Design Spec

- Status: DESIGN (approved shape 2026-07-06; pending spec review)
- Author: Claude (Opus 4.8) + operator brainstorm
- Location convention: docs/specs/ (RC), not the superpowers default
- Related: docs/adr/ADR-011 (1-PC), reference_prom_metrics, reference_loop_monitor,
  reference_scheduled_task_env_injection, feedback_execution_efficiency_rules (R5 tiers)

## 1. Problem / Goal

Claude plan is at ~3 percent with some usage credits. When it reaches 0, RC must keep
operating in the SAME way it does now - memories, feedback, planning patterns, TDD,
GitHub, skills, commands, plugins, hooks, git, research - on a cheaper/local brain,
with no manual fiddling and a live monitor. This is a KEEP-LIGHTS-ON fallback, not an
Opus replacement.

Key elegance: everything RC needs keeps working untouched because the fallback is STILL
Claude Code. Only the model endpoint behind it changes (via ANTHROPIC_BASE_URL). No RC
workflow, memory, skill, or MCP wiring is rebuilt.

## 2. Locked decisions

- Compute tier #3: local-first + cheap key. Local Ollama is the tokenless default;
  DeepSeek is escalation for hard tasks; a free hosted-Nemotron sits as a $0 fallback
  slot BELOW DeepSeek (used only if DeepSeek is down; privacy/rate-limit caveat accepted
  for that slot only).
- Switch mechanism: auto-flip at ~0 (watchdog arms budget-saver mode), plus the manual
  launch shim is always available.
- Linchpin proxy: LiteLLM (Python, diffable config.yaml, native Anthropic /v1/messages
  with tool-calling, router + fallbacks + cost UI + Prometheus /metrics). NOT
  claude-code-router (it pivoted to a closed desktop app + SQLite config - not
  idempotently scriptable).
- Model selection is decided EMPIRICALLY by an RC-native eval harness, not assumed.

## 3. Constraints

- Hardware: Legion RTX 5070, 12 GB VRAM (~11 GB usable after desktop). Node 24, Python
  3.14, 770+ GB free disk.
- 12 GB ceiling: 14B at Q4_K_M (~9 GB) fits but leaves little room for KV cache; 7B (~5
  GB) is comfortable. 32B/70B do NOT fit (CPU spill = unusable). Cannot hold 14B + 7B
  resident at once; Ollama loads/unloads on demand (keep_alive) => swap latency.
- CONTEXT REALITY (biggest technical risk): a Claude Code turn carries a large prefix
  (system prompt + CLAUDE.md + loaded skills + tool schemas + memory + history), often
  30k-100k+ tokens. A local 14B on 12 GB cannot hold a large KV cache alongside its
  weights => local tier is realistically limited to SMALLER-context turns. Large-context
  turns must route to DeepSeek (1M window, automatic prefix caching so the repeated
  prefix is ~free) or hosted-Nemotron. The 85/15 local/escalation split is a TARGET; the
  eval harness measures the real split and it may lean more on DeepSeek. Decided by data,
  not assumed.
- Privacy: RC is a private repo (competitor name-scrub project exists). Local = zero
  leak. DeepSeek paid API tier does not train on API data (near-zero leak). Free
  hosted-Nemotron MAY retain/train - so it is fallback-only and privacy-gated.
- ASCII-only authored content (RC hard rule): no em/en dashes, no smart quotes.
- Idempotent: every installer/config step is check-before-act and re-runnable.
- Isolation: LiteLLM installs in its OWN venv under ops/budget_saver/.venv, never RC's
  main env (supply-chain containment). Ollama + LiteLLM bind 127.0.0.1 only.

## 4. Non-goals

- No NeMo Framework training / weight fine-tuning (12 GB QLoRA is multi-day, uncertain
  payoff for a temporary fallback).
- No NeMo Guardrails (RC's precommit gate + tests + verifier are stronger).
- No NeMo Evaluator infra (RC's own test suite is the deterministic oracle).
- Not an Opus replacement for the hardest ~5-10 percent (DS engine rewrites, subtle
  multi-file refactors, architecture) - those are queued DEFER-TO-CLAUDE, not thrashed.

## 5. Architecture

```
claude  (ALL RC machinery intact: skills, MCP, hooks, memory, TDD, git, plugins)
  |  ANTHROPIC_BASE_URL=http://127.0.0.1:4000  ANTHROPIC_AUTH_TOKEN=<litellm master key>
  v
LiteLLM proxy :4000  (pinned safe version, own venv, 127.0.0.1)
  |-- router + fallback chain + cost tracking + admin UI + /metrics
  |
  +--> Ollama :11434 (local, $0)      : qwen2.5-coder / nemotron-nano  [DEFAULT small ctx]
  +--> DeepSeek API (pennies)          : V4 Flash / V4 Pro-reasoner      [escalation + big ctx]
  +--> NVIDIA NIM hosted-Nemotron ($0) : fallback ONLY if DeepSeek down  [privacy-gated]
```

## 6. Components

### C1 - Ollama local inference + model bench
- Purpose: tokenless local brain on the 5070.
- Candidates to bench (verify exact tags/VRAM in plan): qwen2.5-coder:14b,
  qwen2.5-coder:7b, a Nemotron-Nano reasoning model (nemotron tag TBD), optionally
  qwen3:14b. Pick winner(s) by C9 eval - one coder for edits, optional 7B for background.
- Interface: OpenAI-compatible :11434, consumed by LiteLLM. keep_alive tuned to limit
  swap thrash. Bind 127.0.0.1.
- Depends on: Ollama runtime (install if absent), model pulls (idempotent).

### C2 - LiteLLM proxy (the gateway)
- Purpose: Anthropic /v1/messages endpoint Claude Code talks to; translate to backends.
- Version: PIN a verified-clean release. HARD BLOCK 1.82.7 and 1.82.8 (credential-stealer
  malware). Prefer newest stable > that range; verify wheel hash against PyPI at install.
- Config: ops/budget_saver/config.yaml (model_list + router_settings + general_settings).
  Diffable, version-controlled (keys via env, never committed).
- Exposes: /v1/messages (tool-calling), /ui (admin), /metrics (Prometheus).
- Depends on: own venv, master key in a gitignored file, backends C1/C3/C4.

### C3 - DeepSeek escalation
- Purpose: cheap, capable, big-context brain for hard/large-context turns.
- Models (verify IDs in plan; legacy deepseek-chat/reasoner aliases deprecate 2026-07-24):
  V4 Flash (~$0.14/M in cache-miss, ~$0.0028/M cache-hit, ~$0.28/M out) for routine-hard;
  V4 Pro / reasoner (~$0.435/M in, ~$0.87/M out) for DS damage-math and gnarly logic.
- Interface: OpenAI-compatible endpoint via LiteLLM provider. Key in gitignored env file.
- Privacy: paid API tier, no train-on-data. Acceptable for RC source.

### C4 - Hosted-Nemotron free fallback (NVIDIA NIM)
- Purpose: $0 last-resort brain if DeepSeek is unreachable.
- Interface: build.nvidia.com OpenAI-compatible endpoint, free dev key, added as the
  LOWEST-priority fallback in the LiteLLM chain.
- Privacy gate: NEVER selected for turns tagged privacy-sensitive (see C5). Free tier may
  retain data; used only for non-sensitive turns when DeepSeek is down.

### C5 - Tier router + policy (reuses R5)
- Purpose: pick the backend per turn.
- Policy inputs: R5 tier (0/1 -> local; 2 -> DeepSeek; hard/arch -> DEFER-TO-CLAUDE),
  context size (large -> DeepSeek regardless), privacy tag (sensitive -> local-only, never
  hosted), backend health (fallback order DeepSeek -> hosted-Nemotron -> local).
- Mechanism: LiteLLM model groups + fallbacks handle context/health routing. Tier and
  privacy signals are expressed through which model alias Claude Code requests
  (ANTHROPIC_MODEL for main, ANTHROPIC_SMALL_FAST_MODEL for background) plus router rules.
- DEFER-TO-CLAUDE queue: a simple append-only file (ops/budget_saver/defer_queue.jsonl)
  the operator/agent writes hard items to; surfaced in the monitor; drained when Claude
  credits return. Prevents burning the cheap brain on tasks it cannot converge.

### C6 - Launch shim (manual budget-saver mode)
- Purpose: one command to launch Claude Code on the local stack.
- ops/budget_saver/budget-saver.ps1: ensure Ollama + LiteLLM healthy (start if down),
  set ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN / ANTHROPIC_MODEL /
  ANTHROPIC_SMALL_FAST_MODEL, then exec claude. Isolated to the child process - does NOT
  alter the operator's normal claude launch.

### C7 - Auto-flip watchdog
- Purpose: arm budget-saver mode automatically as Claude budget nears 0.
- Mechanism: a scheduled task (clone the existing RC-CostHealthWatchdog pattern) polling
  remaining budget/credits (via the anthropic usage signal / ANTHROPIC_USAGE_KEY). Below
  threshold: (a) warm the stack (ensure Ollama model loaded + LiteLLM up), (b) arm a
  persistent flag + Machine env (reference_scheduled_task_env_injection pattern) so the
  NEXT session boundary / autonomous-loop cycle launches via C6, (c) notify.
- Honest limit: cannot hot-swap the brain of an already-running claude process. Auto-flip
  arms the mode for the next launch / next /clear cycle and keeps the stack warm. RC's
  headless loops read the flag at their next cycle boundary.

### C8 - Monitor
- Purpose: operator sees the whole operation - which brain, what task, plan, speed, ETA,
  cost saved.
- Surfaces (reuse existing where possible):
  - LiteLLM /ui :4000 - spend, model distribution, per-model latency, request stream.
  - LiteLLM /metrics -> RC already consumes Prometheus (reference_prom_metrics); scrape it.
  - RC loop-monitor (/loop-monitor + /api/loop-monitor) - per-tool-call timeline = what
    the agent is doing and planning. Already exists; no rebuild.
  - NEW :8888 tile "Budget Saver": current brain (Claude / DeepSeek / local-14B / local-7B
    / hosted-Nemotron), active task + R5 tier, tok/s, rough ETA, tokens/dollars saved vs
    Claude-equivalent, DEFER-TO-CLAUDE queue depth, backend health.
  - Tile data source: LiteLLM /metrics + a small state file the shim/router writes.

### C9 - Model-qualification harness (RC-native eval)
- Purpose: empirically pick local model + set the R5 -> model thresholds; measure the real
  local/DeepSeek split under RC's true context sizes.
- Method: a curated set (~15-25) of representative RC tasks spanning tiers (Tier-0 doc
  edit, Tier-1 module fix, Tier-2 scorer tweak, research-summarize, git op, grep+report),
  each with a deterministic pass check (py_compile + relevant tests + assertions). Run each
  candidate model through them headlessly via LiteLLM; score first-try pass rate,
  iterations-to-green, tok/s, and effective context handled.
- Output: ops/budget_saver/qualification_scorecard.json + a human summary. Drives C1/C5
  config. The oracle is RC's own suite - no LLM-judge, no NeMo Evaluator.

### C10 - Idempotent installer
- Purpose: stand the whole thing up (and re-converge) with no manual fiddling.
- ops/budget_saver/setup.ps1 (+ python helpers): check-before-act for Ollama install,
  model pulls, venv + verified-clean LiteLLM, config.yaml render, scheduled-task register,
  health checks. Re-running fixes drift, never double-installs. Prints a status banner.

### C11 - Lean budget-saver profile (context-shrink lever stack)
- Purpose: make the local tier carry a real majority of turns by shrinking RC's OWN
  per-turn prefix and stretching local context capacity. The big context is mostly RC's
  doing (100s of MCP tool schemas + large CLAUDE.md sent every turn), so most of the fix
  is in our control.
- Levers, largest first:
  1. Lean profile: a budget-saver Claude Code launch (via C6) enabling only essential MCP
     servers (git / filesystem / core RC), a trimmed instruction set, and aggressive
     /clear leaning on RC's file-based memory instead of long history. Cuts the prefix
     from ~30-100k toward ~8-12k.
  2. KV-cache quantization: OLLAMA_KV_CACHE_TYPE=q8_0 + flash attention (~half the KV
     memory), pushing usable local context from ~8k toward ~24-32k on 12 GB.
  3. Right-size model for headroom: a 7-8B (Q4 ~5 GB) leaves ~6 GB for KV = 32k+ context;
     often beats a 14B that OOMs on RC turns. Chosen in C9 with context-headroom scored.
  4. CPU KV-offload: for privacy-sensitive AND large-context turns, offload KV to system
     RAM (plenty free) - slower but keeps the turn local.
  5. Route-by-size (C5): whatever still overflows goes to DeepSeek (1M ctx, prefix cache,
     near-free).
- Outcome: no fixed promise of 85 percent; C9 measures the real local fraction per
  (model x KV-setting x profile). Levers 1-3 stacked make a healthy majority realistic.

## 7. Routing table (initial; tuned by C9)

| Turn kind                                   | Backend                         |
|---------------------------------------------|---------------------------------|
| Background / small-context / Tier-0/1       | Ollama local (7B/14B)           |
| Tier-2 engine/scorer, medium logic          | DeepSeek V4 Flash               |
| DS damage-math / hard reasoning             | DeepSeek V4 Pro/reasoner        |
| Large context (over local KV budget)        | DeepSeek (1M ctx, prefix cache) |
| Privacy-sensitive files                     | Ollama local ONLY (never hosted)|
| DeepSeek unreachable, non-sensitive         | hosted-Nemotron (NIM, $0)       |
| Hard/arch, no cheap convergence             | DEFER-TO-CLAUDE queue           |

## 8. Security

- Pin verified-clean LiteLLM; hard-block 1.82.7/1.82.8; verify wheel hash.
- Isolated venv (ops/budget_saver/.venv) - contain dependency risk away from RC.
- Bind Ollama + LiteLLM to 127.0.0.1 only. LiteLLM master key required.
- All provider keys in gitignored files/env; never committed. config.yaml uses
  os.environ/<VAR> references only.
- Privacy-gated routing: sensitive turns never leave the machine.

## 9. Testing strategy (TDD First)

- Unit (failing test first): routing-decision function (tier+ctx+privacy+health -> backend),
  tier->model mapping, watchdog threshold logic, config.yaml schema validation, tile data
  assembly, DEFER queue append/drain.
- Integration smoke: a canned Anthropic /v1/messages request through LiteLLM -> Ollama
  returns a valid tool-call response; a fallback path (primary down -> next backend) works.
- Eval: C9 harness is itself the acceptance test for model choice.
- Follow RC tiering for the build's own verification; run relevant suites, verify green
  before commit.

## 10. Rollout / verification order

1. C10 installer skeleton + C2 LiteLLM (pinned) + C1 Ollama one model -> smoke a
   /v1/messages tool-call.
2. C6 shim -> launch claude in budget-saver mode, confirm skills/MCP/memory all load.
3. C3 DeepSeek + C5 router/fallbacks -> confirm escalation + large-context path.
4. C9 eval harness -> pick local model, set thresholds, measure real split.
5. C4 hosted-Nemotron fallback slot (privacy-gated).
6. C8 monitor tile + metrics wiring.
7. C7 auto-flip watchdog last (after manual mode proven).

## 11. Plan-phase items to VERIFY (do not scaffold on assumptions)

- Exact Ollama model tags + measured VRAM/context fit at chosen quant on the 5070.
- Current verified-clean LiteLLM version (confirm not 1.82.7/1.82.8) + install method on
  Windows/Python 3.14.
- LiteLLM /v1/messages tool-calling fidelity with the chosen Ollama model (some local
  models emit malformed tool JSON - disqualifies for agentic use if so).
- DeepSeek current model IDs + live pricing (V4 naming; legacy alias deprecation
  2026-07-24).
- NVIDIA NIM free-tier endpoint + Nemotron model id + rate limits.
- Whether ANTHROPIC_SMALL_FAST_MODEL is honored for background routing in this Claude Code
  build.

## 12. Risks + mitigations

- R1 Local context overflow (biggest): attack with the C11 lever stack (lean profile cuts
  the prefix; KV-quant + right-sized model stretch capacity; CPU-offload for private big
  turns; route-by-size sends the rest to DeepSeek). C9 measures the real local fraction;
  no fixed promise.
- R2 Local tool-call fidelity: disqualify weak models for agentic turns in C9; keep them
  for summarize/background only.
- R3 Quality drop on hard tasks: DEFER-TO-CLAUDE queue + guardrails (tests/precommit/
  verifier) hold soundness; velocity drops, ceiling deferred.
- R4 Supply-chain (LiteLLM malware history): pin + hash-verify + isolated venv.
- R5 Auto-flip cannot hot-swap a live process: arms next-launch + warms stack; loops read
  the flag at cycle boundary.
- R6 Ollama model swap thrash on 12 GB: prefer a single model for most turns; tune
  keep_alive; decide in C9.

## 13. FUTURE (BACKLOG, not this build)

- LoRA-distill a local model on RC's Claude transcripts so the local tier gets genuinely
  good at RC-specific work. Separate multi-day project: transcript curation -> QLoRA ->
  eval via C9. Only if the local tier proves too weak in sustained practice.
