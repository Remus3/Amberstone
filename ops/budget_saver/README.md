# RC Budget-Saver - local fallback brain

When the Claude plan hits 0, keep RC operating on a local-first brain behind a LiteLLM
proxy. It is STILL Claude Code end to end - all your skills, MCP, hooks, memory, TDD, and
git keep working. Only the model behind Claude Code changes.

## TL;DR

```powershell
# 1. one-time: stand up the stack (idempotent, re-runnable)
powershell -NoProfile -File "C:\Riot Commander\ops\budget_saver\setup.ps1"

# 2. copy env.example.ps1 -> env.local.ps1 and set a master key (cloud keys optional)
#    (env.local.ps1 is gitignored)

# 3. start the proxy (leave it running; or let the watchdog warm it)
powershell -NoProfile -File "C:\Riot Commander\ops\budget_saver\start-proxy.ps1"

# 4. launch Claude Code on the local brain
powershell -NoProfile -File "C:\Riot Commander\ops\budget_saver\budget-saver.ps1"
```

## The three launch profiles

| Shim | Main model | Use when |
|---|---|---|
| `budget-saver.ps1` | `rc-main` (local llama3.1, escalates on ctx/error) | Default. Local-first, auto-escalates big-context or failed turns to DeepSeek. |
| `budget-saver-local.ps1` | `rc-local` (local only, NO cloud) | Privacy-sensitive work. Nothing leaves the machine. Accept the quality hit. |
| `budget-saver-smart.ps1` | `rc-deepseek-pro` | A hard session where you want the best cheap brain and accept per-token cost. |

All three launch with a lean profile (`--strict-mcp-config --mcp-config lean-mcp.json
--settings lean-settings.json`) that disables plugins + connectors to shrink the per-turn
context - the biggest lever for keeping turns inside the local model's window.

## How it works

```
claude (all RC machinery)  ->  ANTHROPIC_BASE_URL=127.0.0.1:4000 + ANTHROPIC_AUTH_TOKEN
   ->  LiteLLM proxy :4000  (/v1/messages, Anthropic format, tool-calling)
        |-- ollama_chat/llama3.1:8b  @127.0.0.1:11434   (local, $0, DEFAULT)
        |-- deepseek/deepseek-v4-flash | -v4-pro          (cheap escalation)
        +-- nvidia_nim/...nemotron-super-49b              (free fallback if DeepSeek down)
```

- Main turns -> `ANTHROPIC_MODEL`. Background/haiku-tier -> `ANTHROPIC_DEFAULT_HAIKU_MODEL`.
- LiteLLM `fallbacks` escalate on error; `context_window_fallbacks` escalate an
  over-budget turn to DeepSeek (1M context, near-free with prefix caching).

## Model choice (why llama3.1, not qwen-coder)

`qwen2.5-coder` is a stronger coder but - confirmed live at the Ollama `/api/chat` layer -
it emits tool calls as PLAIN TEXT, not structured `tool_calls`, so Claude Code cannot drive
it. `llama3.1:8b` returns proper `tool_calls`, and at ~5 GB it leaves ~6 GB of VRAM for a
32k KV cache (set via `num_ctx: 32768` in config.yaml). Qwen models stay pulled as code
specialists but are off the driver path. `llama3-groq-tool-use:8b` is a proven alternative
(also passes the tool probe): `probe_ollama_tools.py <model>`.

## Local quality - be realistic

The stack is proven end to end (claude -> proxy -> llama3.1 -> valid tool_use, live). But
llama3.1:8b is an 8B budget brain: fed RC's large CLAUDE.md + tool schemas, it follows
complex instructions poorly and can emit confused output. This is the known ceiling, not a
bug - it is a KEEP-LIGHTS-ON fallback, not an Opus clone.

- Best local use: trivial edits, doc/WAKEUP text, running + reporting tests, grep/summarize,
  git - small-context tasks where a wrong answer is cheap to catch (your test / precommit /
  verifier gates hold soundness).
- For real work (engine, multi-file, anything subtle): use `budget-saver-smart.ps1`
  (DeepSeek) or add a DeepSeek key so the default profile escalates. DeepSeek is ~50-100x
  cheaper than Opus and far more capable than any 12 GB local model.
- Biggest local-quality lever: shrink what the model sees. The lean profile already drops
  plugins/connectors; for heavier local use, launch from a trimmed instruction set so the
  8B is not drowning in RC-specific context (C11 in the spec).

Note: the shims set `MAX_THINKING_TOKENS=0` for the local profiles - llama3.1 has no
thinking mode, and without this Ollama returns a 500 on the `thinking` param Claude Code
sends. The smart (DeepSeek) profile keeps thinking on.

## Escalation keys (optional - local works without them)

Local (llama3.1) is tokenless and needs no keys. To enable escalation, put real keys in
`env.local.ps1`:
- `DEEPSEEK_API_KEY` - platform.deepseek.com (cheap: ~$0.14/1M in, ~$0.28/1M out on Flash).
- `NVIDIA_NIM_API_KEY` - build.nvidia.com (free, ~40 RPM - last-resort fallback only).

## Monitor

- LiteLLM admin UI: `http://127.0.0.1:4000/ui` (login `admin` / your `LITELLM_MASTER_KEY`) -
  spend, per-model latency, request stream.
- LiteLLM metrics: `http://127.0.0.1:4000/metrics` (Prometheus; RC already scrapes /metrics).
- Budget-Saver status page: `http://127.0.0.1:4100` (current profile/model, defer-queue
  depth, proxy health) - run `.venv\Scripts\pythonw.exe monitor.py`.
- RC loop-monitor: `https://legion-rc:8888/loop-monitor` - per-tool-call timeline of what the
  agent is doing.

## Auto-flip watchdog

`RC-BudgetSaverWatchdog` (registered by setup.ps1, 15-min poll) arms budget-saver mode as
the Claude budget nears 0: it warms the stack and sets a flag + `RC_BUDGET_SAVER=1` for the
NEXT launch / loop cycle. It does NOT hot-swap a live claude process - it arms the next
session. The usage signal is read from `usage_signal.json` (feed it from a real budget
source - e.g. hook RC-CostHealthWatchdog - to make auto-flip fire on real data).

## The DEFER-TO-CLAUDE queue

The hardest ~5-10% (DS engine rewrites, subtle multi-file refactors, architecture) will not
converge on the cheap brain. Append them to `defer_queue.jsonl` (via `defer_queue.py`) and
drain when Claude credits return, instead of thrashing DeepSeek. Your test / precommit /
verifier gates keep soundness regardless of which brain drives.

## Requirements / notes

- The Ollama desktop app must be running (it autostarts on login and self-heals its server
  on `127.0.0.1:11434`).
- Proxy venv uses Python 3.12 (litellm 1.91.0 requires >=3.10,<3.14; RC main is 3.14). The
  venv is isolated at `.venv/` and never touches RC's environment.
- LiteLLM pinned to 1.91.0 (the 1.82.7/1.82.8 releases shipped malware). setup.ps1 checks
  for the `litellm_init.pth` stealer signature and includes `prometheus_client`.
- Everything binds 127.0.0.1 only.

## Files

- `setup.ps1` - idempotent installer. `start-proxy.ps1` / `start-ollama.ps1` - launchers.
- `config.yaml` - LiteLLM model list + routing. `lean-mcp.json` / `lean-settings.json` - lean profile.
- `budget-saver*.ps1` - the 3 launch profiles. `env.example.ps1` - copy to `env.local.ps1`.
- `routing.py` - policy. `defer_queue.py` - defer list. `state.py` - run state. `monitor.py` - status page.
- `qualify.py` + `qual_tasks/` - RC-native model eval. `watchdog.py` - auto-flip.
- `tests/` - unit tests + `smoke_toolcall.py` (GATE) + `probe_ollama_tools.py`.
