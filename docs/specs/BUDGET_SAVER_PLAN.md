# RC Budget-Saver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the Claude plan hits 0, keep RC operating on a local-first (Ollama) + DeepSeek-escalation brain behind a LiteLLM proxy, with auto-flip, RC-native model eval, and a monitor - still Claude Code end to end, so memories / skills / MCP / TDD / git are untouched.

**Architecture:** Claude Code points at a local LiteLLM proxy (`ANTHROPIC_BASE_URL=http://127.0.0.1:4000`) that exposes an Anthropic `/v1/messages` endpoint and routes each request to Ollama (local, $0), DeepSeek (cheap escalation), or a free hosted-Nemotron fallback. Task-intent is chosen by which of three launch shims the operator/loop uses; context-overflow and backend-health escalation are handled by LiteLLM native fallbacks. A watchdog arms budget-saver mode as the Claude budget nears 0.

**Tech Stack:** LiteLLM proxy 1.91.0 (isolated venv), Ollama + Qwen2.5-Coder (14B/7B), DeepSeek V4 API, NVIDIA NIM (Nemotron-Super-49B), PowerShell launch shims, Python 3.14 helpers, Windows Scheduled Task.

## Global Constraints

- ASCII only in all authored content - no em/en dashes, no smart quotes (RC hard rule). Use " - " for clause breaks.
- LiteLLM pinned EXACTLY to `1.91.0`. NEVER install `1.82.7` or `1.82.8` (credential-stealer malware). After install, assert `litellm --version` == 1.91.0 and that no `litellm_init.pth` exists in site-packages.
- Isolated venv at `ops/budget_saver/.venv` (persistent, NOT uvx - uvx dies under Vanguard). Never install into RC's main Python env.
- Bind Ollama (`:11434`) and LiteLLM (`:4000`) to `127.0.0.1` only. No LAN/0.0.0.0 exposure.
- All provider keys via `os.environ/<VAR>` in config.yaml or gitignored env files. NEVER commit a literal key.
- Atomic writes only for any runtime state file: `tmp.write_text(...); tmp.replace(target)`.
- `py_compile` every .py before declaring a task done. Launch background daemons via `pythonw.exe` / scheduled task to avoid console flash.
- Ollama defaults context to 4096 regardless of model max - the installer MUST set `OLLAMA_CONTEXT_LENGTH`, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0` or the agent silently gets a 4K window.
- Commit messages: ASCII, end with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. Branch `budget-saver`.

## Deltas from spec (post-research, all confirmed by cited docs)

1. Local DRIVER is Qwen2.5-Coder only. Nemotron-nano/mini are documented-weak at emitting valid tool calls (Ollama #8287/#6870, crewAI #4117) - dropped as local driver, kept only as an optional scratch reasoning model.
2. hosted-Nemotron fallback = `nvidia/llama-3.3-nemotron-super-49b-v1.5` (this one DOES support tool-calling), rate-capped ~40 RPM, ~1000 free credits - last-resort slot only.
3. C5 tier-router is NOT custom per-turn code. LiteLLM `fallbacks` (on error) + `context_window_fallbacks` (on ctx overflow) + three launch profiles cover it. `routing.py` remains as a pure, tested policy function + docs; `defer_queue.py` manages the DEFER-TO-CLAUDE list.
4. `ANTHROPIC_SMALL_FAST_MODEL` is deprecated -> use `ANTHROPIC_DEFAULT_HAIKU_MODEL` for the background/haiku split.
5. Lean profile must ALSO disable plugins + claude.ai connectors (via a `--settings` file), because on this box the tool-schema bloat is plugins, not `.mcp.json` (which is empty). `--strict-mcp-config` alone is insufficient.
6. Prometheus `/metrics` may be enterprise-gated on 1.91.0. Monitor (C8) reads `/metrics` if available, else falls back to LiteLLM `/spend/logs` + our own `state.json`.

## File Structure

All under `ops/budget_saver/` unless noted. Split by responsibility; each file has one job.

- `setup.ps1` - idempotent installer/repair (C10). Installs venv+LiteLLM, Ollama+models, sets env, writes state dir, registers the watchdog task. Re-runnable.
- `config.yaml` - LiteLLM model_list + router + settings (C2/C3/C4/C5). Committed (os.environ refs only).
- `lean-mcp.json` - the 2-server lean MCP set (C11).
- `lean-settings.json` - disables plugins + connectors for the lean launch (C11).
- `budget-saver.ps1` - MAIN launch shim: local-first + auto-escalation (C6).
- `budget-saver-local.ps1` - PRIVATE launch shim: local-only, no cloud fallback (C6/C11).
- `budget-saver-smart.ps1` - HARD-SESSION shim: DeepSeek-primary (C6).
- `routing.py` - pure policy `choose_model(est_tokens, tier, privacy) -> model_name` (C5, tested/docs).
- `defer_queue.py` - append/list/drain the DEFER-TO-CLAUDE queue (C5).
- `qualify.py` - RC-native model-qualification harness (C9).
- `qual_tasks/` - curated eval task fixtures for C9.
- `watchdog.py` - poll usage, arm budget-saver flag, warm stack (C7).
- `monitor.py` - standalone status page + links to LiteLLM /ui and RC loop-monitor (C8).
- `state.py` - atomic read/write of `state.json` (current profile/model/started_at) shared by shims + monitor.
- `env.example.ps1` - documents the env vars to set (keys blank); real secrets in gitignored `env.local.ps1`.
- `README.md` - ops runbook.
- `tests/` - `test_routing.py`, `test_defer_queue.py`, `test_state.py`, `test_config_valid.py`, `test_watchdog.py`, `test_qualify.py`, `test_monitor.py`.
- `.venv/`, `env.local.ps1`, `state.json`, `defer_queue.jsonl`, `qualification_scorecard.json` - all gitignored.

`.gitignore` additions (repo root or ops/budget_saver/.gitignore):
```
ops/budget_saver/.venv/
ops/budget_saver/env.local.ps1
ops/budget_saver/state.json
ops/budget_saver/defer_queue.jsonl
ops/budget_saver/qualification_scorecard.json
```

---

## Phase 1 - Foundation + smoke

### Task 1: Isolated venv + LiteLLM 1.91.0 (safety-pinned)

**Files:**
- Create: `ops/budget_saver/setup.ps1` (first section only this task)
- Create: `ops/budget_saver/tests/test_install.ps1`

**Interfaces:**
- Produces: a working `ops/budget_saver/.venv` with `litellm` 1.91.0 on PATH inside the venv; `litellm.exe` at `.venv/Scripts/litellm.exe`.

- [ ] **Step 1: Write the failing test** `ops/budget_saver/tests/test_install.ps1`

```powershell
# Asserts the venv exists, litellm is exactly 1.91.0, and no stealer .pth is present.
$ErrorActionPreference = "Stop"
$root = "C:\Riot Commander\ops\budget_saver"
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Error "FAIL: venv python missing"; exit 1 }
$ver = & $py -m litellm --version 2>&1
if ($ver -notmatch "1\.91\.0") { Write-Error "FAIL: litellm version = $ver (want 1.91.0)"; exit 1 }
$site = & $py -c "import site,sys; print(site.getsitepackages()[0])"
if (Get-ChildItem -Path $site -Filter "litellm_init.pth" -ErrorAction SilentlyContinue) {
  Write-Error "FAIL: stealer signature litellm_init.pth present - ABORT, rotate keys"; exit 1 }
Write-Output "PASS: litellm 1.91.0 clean in isolated venv"
```

- [ ] **Step 2: Run it, verify FAIL** - Run: `powershell -NoProfile -File "C:\Riot Commander\ops\budget_saver\tests\test_install.ps1"` - Expected: FAIL "venv python missing".

- [ ] **Step 3: Implement installer section** in `ops/budget_saver/setup.ps1`

```powershell
# ===== RC Budget-Saver setup.ps1 (idempotent) =====
$ErrorActionPreference = "Stop"
$Root   = "C:\Riot Commander\ops\budget_saver"
$Py314  = "C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe"
$Venv   = Join-Path $Root ".venv"
$VenvPy = Join-Path $Venv "Scripts\python.exe"

# 1. venv (idempotent)
if (-not (Test-Path $VenvPy)) {
  & $Py314 -m venv $Venv
}
& $VenvPy -m pip install --upgrade pip | Out-Null

# 2. LiteLLM pinned + clean (idempotent - pip is a no-op if satisfied)
$have = (& $VenvPy -m pip show litellm 2>$null | Select-String "Version:") -replace "Version:\s*",""
if ($have.Trim() -ne "1.91.0") {
  & $VenvPy -m pip install "litellm[proxy]==1.91.0"
}
# 3. Supply-chain guard
$site = & $VenvPy -c "import site; print(site.getsitepackages()[0])"
if (Test-Path (Join-Path $site "litellm_init.pth")) {
  throw "SECURITY: litellm_init.pth stealer signature found - aborting, rotate all keys on this machine."
}
Write-Output "[setup] LiteLLM 1.91.0 ready in isolated venv."
```

- [ ] **Step 4: Run setup + test, verify PASS** - Run: `powershell -NoProfile -File "C:\Riot Commander\ops\budget_saver\setup.ps1"` then the test from Step 1. Expected: "PASS: litellm 1.91.0 clean". If Python 3.14 forces a source build of tiktoken/orjson, install Rust from rustup.rs and re-run (this is the one known Py3.14 gotcha).

- [ ] **Step 5: Commit** - `git add ops/budget_saver/setup.ps1 ops/budget_saver/tests/test_install.ps1 && git commit -F <ascii msg file>` message: `feat(budget-saver): isolated venv + pinned litellm 1.91.0 with stealer guard`.

### Task 2: Ollama + models + server env

**Files:**
- Modify: `ops/budget_saver/setup.ps1` (append Ollama section)
- Create: `ops/budget_saver/tests/test_ollama.ps1`

**Interfaces:**
- Produces: Ollama service on `127.0.0.1:11434` with `qwen2.5-coder:14b-instruct` and `qwen2.5-coder:7b-instruct` pulled; server env vars set for KV-quant + 32K context.

- [ ] **Step 1: Write the failing test** `tests/test_ollama.ps1`

```powershell
$ErrorActionPreference = "Stop"
$tags = (& ollama list) 2>&1 | Out-String
foreach ($t in @("qwen2.5-coder:14b-instruct","qwen2.5-coder:7b-instruct")) {
  if ($tags -notmatch [regex]::Escape($t)) { Write-Error "FAIL: missing $t"; exit 1 }
}
foreach ($e in @("OLLAMA_FLASH_ATTENTION","OLLAMA_KV_CACHE_TYPE","OLLAMA_CONTEXT_LENGTH")) {
  if (-not [Environment]::GetEnvironmentVariable($e,"Machine")) { Write-Error "FAIL: env $e unset"; exit 1 }
}
Write-Output "PASS: ollama models + KV env present"
```

- [ ] **Step 2: Run it, verify FAIL** - Expected FAIL "missing qwen2.5-coder:14b-instruct" (or "ollama not recognized").

- [ ] **Step 3: Implement** - append to `setup.ps1`:

```powershell
# ===== Ollama =====
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
  winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements
  # winget may need a new shell for PATH; VERIFY-AT-INSTALL and re-run setup if 'ollama' still missing.
}
# Server env (idempotent - SetEnvironmentVariable overwrites same value harmlessly)
[Environment]::SetEnvironmentVariable("OLLAMA_FLASH_ATTENTION","1","Machine")
[Environment]::SetEnvironmentVariable("OLLAMA_KV_CACHE_TYPE","q8_0","Machine")
[Environment]::SetEnvironmentVariable("OLLAMA_CONTEXT_LENGTH","32768","Machine")
[Environment]::SetEnvironmentVariable("OLLAMA_HOST","127.0.0.1:11434","Machine")
$env:OLLAMA_FLASH_ATTENTION="1"; $env:OLLAMA_KV_CACHE_TYPE="q8_0"; $env:OLLAMA_CONTEXT_LENGTH="32768"
# Pull models (ollama pull is idempotent - skips if current)
ollama pull qwen2.5-coder:14b-instruct
ollama pull qwen2.5-coder:7b-instruct
Write-Output "[setup] Ollama models pulled, KV-quant + 32K context env set (restart Ollama service to apply)."
```

- [ ] **Step 4: Restart Ollama + run test, verify PASS** - Ollama service must restart to pick up Machine env: `Get-Process ollama* | ForEach-Object { taskkill /F /PID $_.Id }` then `ollama serve` (or let the tray app relaunch). Run test. Expected PASS. NOTE: never `Stop-Process` (RC rule) - use `taskkill /F /PID`.

- [ ] **Step 5: Commit** - message `feat(budget-saver): ollama qwen2.5-coder 14b/7b + KV-quant 32K context env`.

### Task 3: LiteLLM config.yaml (all backends + routing)

**Files:**
- Create: `ops/budget_saver/config.yaml`
- Create: `ops/budget_saver/tests/test_config_valid.py`

**Interfaces:**
- Produces: model_names `rc-main`, `rc-local`, `rc-background`, `rc-deepseek`, `rc-deepseek-pro`, `rc-nemotron`; `fallbacks` and `context_window_fallbacks` on `rc-main`.

- [ ] **Step 1: Write the failing test** `tests/test_config_valid.py`

```python
import yaml, pathlib
CFG = pathlib.Path(__file__).resolve().parents[1] / "config.yaml"

def test_config_has_expected_models_and_fallbacks():
    data = yaml.safe_load(CFG.read_text(encoding="utf-8"))
    names = {m["model_name"] for m in data["model_list"]}
    assert {"rc-main","rc-local","rc-background","rc-deepseek","rc-deepseek-pro","rc-nemotron"} <= names
    rs = data["router_settings"]
    fb = {k: v for d in rs["fallbacks"] for k, v in d.items()}
    assert "rc-deepseek" in fb["rc-main"] and "rc-nemotron" in fb["rc-main"]
    cwfb = {k: v for d in rs["context_window_fallbacks"] for k, v in d.items()}
    assert "rc-deepseek" in cwfb["rc-main"]
    # no literal secrets
    raw = CFG.read_text(encoding="utf-8")
    assert "sk-" not in raw and "nvapi-" not in raw
```

- [ ] **Step 2: Run it, verify FAIL** - Run: `ops/budget_saver/.venv/Scripts/python.exe -m pytest ops/budget_saver/tests/test_config_valid.py -v` - Expected FAIL (config.yaml missing).

- [ ] **Step 3: Implement** `ops/budget_saver/config.yaml`

```yaml
model_list:
  - model_name: rc-local            # local primary, coding + tools
    litellm_params:
      model: ollama_chat/qwen2.5-coder:14b-instruct
      api_base: http://127.0.0.1:11434
  - model_name: rc-background       # local fast, haiku-tier
    litellm_params:
      model: ollama_chat/qwen2.5-coder:7b-instruct
      api_base: http://127.0.0.1:11434
  - model_name: rc-deepseek         # cheap cloud escalation
    litellm_params:
      model: deepseek/deepseek-v4-flash
      api_key: os.environ/DEEPSEEK_API_KEY
  - model_name: rc-deepseek-pro     # reasoning tier
    litellm_params:
      model: deepseek/deepseek-v4-pro
      api_key: os.environ/DEEPSEEK_API_KEY
  - model_name: rc-nemotron         # free hosted fallback (rate-capped)
    litellm_params:
      model: nvidia_nim/nvidia/llama-3.3-nemotron-super-49b-v1.5
      api_key: os.environ/NVIDIA_NIM_API_KEY
  - model_name: rc-main             # alias Claude Code requests; local-first
    litellm_params:
      model: ollama_chat/qwen2.5-coder:14b-instruct
      api_base: http://127.0.0.1:11434

router_settings:
  fallbacks: [{"rc-main": ["rc-deepseek", "rc-nemotron"]}]
  context_window_fallbacks: [{"rc-main": ["rc-deepseek"]}]

litellm_settings:
  callbacks: ["prometheus"]
  drop_params: true

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
```

- [ ] **Step 4: Run test, verify PASS** - same pytest command. Expected PASS.

- [ ] **Step 5: Commit** - message `feat(budget-saver): litellm config.yaml - local-first routing + deepseek/nemotron fallbacks`.

### Task 4: Live smoke - proxy up, local tool-call round-trip (GATE)

**Files:**
- Create: `ops/budget_saver/tests/smoke_toolcall.py`

**Interfaces:**
- Consumes: config.yaml, running Ollama, running LiteLLM proxy.
- Produces: proof that `/v1/messages` returns a valid tool_use from the local model. THIS IS A GATE - if local tool-calling is unreliable (Qwen2.5 known quirk), the default profile becomes DeepSeek-primary and local is demoted to background/summarize only.

- [ ] **Step 1: Write the smoke test** `tests/smoke_toolcall.py`

```python
import os, json, urllib.request
URL = "http://127.0.0.1:4000/v1/messages"
KEY = os.environ["LITELLM_MASTER_KEY"]
body = {
  "model": "rc-local",
  "max_tokens": 300,
  "tools": [{"name": "get_weather", "description": "Get weather",
             "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}],
  "messages": [{"role": "user", "content": "Use get_weather for Paris."}],
}
req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST",
    headers={"content-type": "application/json", "x-api-key": KEY, "anthropic-version": "2023-06-01"})
with urllib.request.urlopen(req, timeout=120) as r:
    out = json.loads(r.read())
tool_uses = [b for b in out.get("content", []) if b.get("type") == "tool_use"]
print(json.dumps(out, indent=2)[:800])
assert tool_uses, "GATE FAIL: local model emitted no tool_use - demote local to background-only, default to DeepSeek-primary"
print("GATE PASS: local model emits valid tool_use")
```

- [ ] **Step 2: Start the proxy** - in a persistent shell with secrets set:

```powershell
. "C:\Riot Commander\ops\budget_saver\env.local.ps1"   # sets LITELLM_MASTER_KEY, DEEPSEEK_API_KEY, NVIDIA_NIM_API_KEY
& "C:\Riot Commander\ops\budget_saver\.venv\Scripts\litellm.exe" --config "C:\Riot Commander\ops\budget_saver\config.yaml" --port 4000
```

- [ ] **Step 3: Run smoke, record verdict** - Run: `ops/budget_saver/.venv/Scripts/python.exe ops/budget_saver/tests/smoke_toolcall.py`. Record GATE PASS or FAIL in the plan/commit. If FAIL, set the default shim (Task 5) to `rc-deepseek` and note local-as-background-only.

- [ ] **Step 4: Commit** - message `test(budget-saver): live /v1/messages tool-call gate + verdict`.

---

## Phase 2 - Launch shims + lean profile

### Task 5: Lean MCP/settings + three launch shims

**Files:**
- Create: `ops/budget_saver/lean-mcp.json`, `ops/budget_saver/lean-settings.json`
- Create: `ops/budget_saver/budget-saver.ps1`, `budget-saver-local.ps1`, `budget-saver-smart.ps1`
- Create: `ops/budget_saver/env.example.ps1`
- Create: `ops/budget_saver/state.py` + `tests/test_state.py`

**Interfaces:**
- Consumes: config.yaml model names, running proxy.
- Produces: `state.write(profile, model)` -> atomic `state.json`; shims that launch Claude Code lean + routed.

- [ ] **Step 1: Write failing test** `tests/test_state.py`

```python
import json, pathlib, importlib.util
spec = importlib.util.spec_from_file_location("state", pathlib.Path(__file__).resolve().parents[1] / "state.py")
state = importlib.util.module_from_spec(spec); spec.loader.exec_module(state)

def test_state_roundtrip_atomic(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "STATE_PATH", tmp_path / "state.json")
    state.write(profile="main", model="rc-main")
    got = json.loads((tmp_path / "state.json").read_text())
    assert got["profile"] == "main" and got["model"] == "rc-main" and "started_at" in got
    assert not list(tmp_path.glob("*.tmp"))  # tmp cleaned by atomic replace
```

- [ ] **Step 2: Run it, verify FAIL** - `pytest tests/test_state.py -v` - FAIL (state.py missing).

- [ ] **Step 3: Implement** `state.py`

```python
import json, os, time, pathlib
STATE_PATH = pathlib.Path(__file__).resolve().parent / "state.json"

def write(profile: str, model: str, extra: dict | None = None) -> None:
    data = {"profile": profile, "model": model, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "pid": os.getpid()}
    if extra: data.update(extra)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)

def read() -> dict:
    try: return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError: return {}
```

- [ ] **Step 4: Run test, verify PASS.**

- [ ] **Step 5: Implement lean configs + shims.**

`lean-mcp.json` (only the servers a budget-saver dev turn needs):
```json
{ "mcpServers": {
    "filesystem": { "command": "npx", "args": ["-y","@modelcontextprotocol/server-filesystem","C:\\Riot Commander"] }
} }
```

`lean-settings.json` (kills the plugin + connector tool-schema bloat):
```json
{
  "enabledPlugins": {
    "github": false, "nimble": false, "ralph-loop": false, "pyright-lsp": false,
    "playwright": false, "chrome-devtools-mcp": false, "firecrawl": false
  },
  "disableClaudeAiConnectors": true
}
```

`env.example.ps1` (copy to `env.local.ps1`, fill secrets, gitignored):
```powershell
$env:LITELLM_MASTER_KEY = ""   # any strong string; also the /ui password
$env:DEEPSEEK_API_KEY   = ""   # sk-... from platform.deepseek.com
$env:NVIDIA_NIM_API_KEY = ""   # nvapi-... from build.nvidia.com
```

`budget-saver.ps1` (MAIN - local-first + auto-escalation):
```powershell
param([Parameter(ValueFromRemainingArguments=$true)] $Rest)
$ErrorActionPreference = "Stop"
$Root = "C:\Riot Commander\ops\budget_saver"
. (Join-Path $Root "env.local.ps1")
# ensure proxy up (Task 10 provides ensure_stack); minimal check here:
try { Invoke-WebRequest "http://127.0.0.1:4000/health/liveliness" -TimeoutSec 3 | Out-Null }
catch { Write-Warning "LiteLLM proxy not reachable on :4000 - run setup.ps1 / start the proxy first." }
$env:ANTHROPIC_BASE_URL            = "http://127.0.0.1:4000"
$env:ANTHROPIC_AUTH_TOKEN          = $env:LITELLM_MASTER_KEY
$env:ANTHROPIC_MODEL               = "rc-main"        # local-first, escalates on ctx/error
$env:ANTHROPIC_DEFAULT_HAIKU_MODEL = "rc-background"  # background -> local 7B
& $Root\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,r'$Root'); import state; state.write('main','rc-main')"
claude --strict-mcp-config --mcp-config (Join-Path $Root "lean-mcp.json") --settings (Join-Path $Root "lean-settings.json") @Rest
```

`budget-saver-local.ps1` - identical except `$env:ANTHROPIC_MODEL = "rc-local"` (no fallbacks = never leaves the machine; for privacy-sensitive work) and `state.write('local','rc-local')`.

`budget-saver-smart.ps1` - identical except `$env:ANTHROPIC_MODEL = "rc-deepseek-pro"`, `$env:ANTHROPIC_DEFAULT_HAIKU_MODEL = "rc-deepseek"` and `state.write('smart','rc-deepseek-pro')`. For a hard session where you accept cloud cost for the best cheap brain. (If Task 4 GATE failed, MAIN also uses rc-deepseek.)

- [ ] **Step 6: Integration smoke** - Run: `powershell -NoProfile -File "C:\Riot Commander\ops\budget_saver\budget-saver.ps1" --print "reply with the single word OK"`. Expected: `OK` printed, and LiteLLM console shows a request to `rc-main`/ollama. Confirms routing + lean launch. VERIFY the `--settings` plugin-disable took effect (fewer tools in `/status`).

- [ ] **Step 7: Commit** - message `feat(budget-saver): lean profile + 3 launch shims (main/local/smart) + atomic state`.

---

## Phase 3 - Routing policy + DEFER queue + fallback proof

### Task 6: routing.py pure policy + tests

**Files:** Create `ops/budget_saver/routing.py`, `tests/test_routing.py`.

**Interfaces:** Produces `choose_model(est_tokens:int, tier:int, privacy:bool) -> str` returning one of the config model_names. Documents the policy LiteLLM realizes at runtime; used by the monitor to label the expected route.

- [ ] **Step 1: Failing test** `tests/test_routing.py`

```python
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("routing", pathlib.Path(__file__).resolve().parents[1] / "routing.py")
routing = importlib.util.module_from_spec(spec); spec.loader.exec_module(routing)

def test_privacy_never_leaves_machine():
    assert routing.choose_model(120_000, 2, privacy=True) == "rc-local"   # even huge+hard stays local
def test_small_routine_is_local():
    assert routing.choose_model(4_000, 0, privacy=False) == "rc-local"
def test_tier2_escalates_to_deepseek():
    assert routing.choose_model(8_000, 2, privacy=False) == "rc-deepseek"
def test_large_context_forces_deepseek():
    assert routing.choose_model(60_000, 0, privacy=False) == "rc-deepseek"
def test_hard_arch_is_deferred():
    assert routing.choose_model(8_000, 3, privacy=False) == "DEFER-TO-CLAUDE"
```

- [ ] **Step 2: Run, verify FAIL.**

- [ ] **Step 3: Implement** `routing.py`

```python
"""Pure routing policy for RC Budget-Saver. LiteLLM realizes error/ctx fallbacks at
runtime; this documents+tests the intent and lets the monitor predict the route.
Tier convention = RC R5: 0/1 routine, 2 engine/scorer, 3 hard/arch."""
LOCAL_CTX_BUDGET = 24_000  # usable local window on 12GB w/ q8_0 KV (VERIFY-AT-BENCH via C9)

def choose_model(est_tokens: int, tier: int, privacy: bool) -> str:
    if privacy:
        return "rc-local"                    # never leaves the machine, accept quality hit
    if tier >= 3:
        return "DEFER-TO-CLAUDE"             # do not thrash the cheap brain
    if est_tokens > LOCAL_CTX_BUDGET:
        return "rc-deepseek"                 # local KV would overflow
    if tier >= 2:
        return "rc-deepseek"                 # engine/scorer -> stronger brain
    return "rc-local"                        # routine, small ctx -> tokenless local
```

- [ ] **Step 4: Run, verify PASS.**
- [ ] **Step 5: Commit** - `feat(budget-saver): pure routing policy (R5 tier + ctx + privacy)`.

### Task 7: defer_queue.py + tests

**Files:** Create `ops/budget_saver/defer_queue.py`, `tests/test_defer_queue.py`.

**Interfaces:** Produces `append(item:dict)`, `load() -> list[dict]`, `drain() -> list[dict]` over `defer_queue.jsonl` (append-only jsonl, atomic).

- [ ] **Step 1: Failing test**

```python
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("dq", pathlib.Path(__file__).resolve().parents[1] / "defer_queue.py")
dq = importlib.util.module_from_spec(spec); spec.loader.exec_module(dq)

def test_append_and_load(tmp_path, monkeypatch):
    monkeypatch.setattr(dq, "QUEUE_PATH", tmp_path / "q.jsonl")
    dq.append({"task": "rewrite DS scorer", "tier": 3})
    dq.append({"task": "arch refactor", "tier": 3})
    items = dq.load()
    assert len(items) == 2 and items[0]["task"] == "rewrite DS scorer"
def test_drain_empties(tmp_path, monkeypatch):
    monkeypatch.setattr(dq, "QUEUE_PATH", tmp_path / "q.jsonl")
    dq.append({"task": "x", "tier": 3})
    drained = dq.drain()
    assert len(drained) == 1 and dq.load() == []
```

- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement** `defer_queue.py`

```python
import json, pathlib, time
QUEUE_PATH = pathlib.Path(__file__).resolve().parent / "defer_queue.jsonl"

def append(item: dict) -> None:
    item = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **item}
    with QUEUE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item) + "\n")

def load() -> list[dict]:
    if not QUEUE_PATH.exists(): return []
    return [json.loads(l) for l in QUEUE_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]

def drain() -> list[dict]:
    items = load()
    QUEUE_PATH.write_text("", encoding="utf-8")
    return items
```

- [ ] **Step 4: Run, verify PASS.**
- [ ] **Step 5: Commit** - `feat(budget-saver): DEFER-TO-CLAUDE queue (append/load/drain)`.

### Task 8: Prove the fallback chain live

**Files:** Create `ops/budget_saver/tests/smoke_fallback.py`.

**Interfaces:** Consumes running proxy + config fallbacks. Produces proof that a forced local failure escalates to DeepSeek.

- [ ] **Step 1: Write the smoke** - point `rc-main` primary at a deliberately bad ollama model name in a temp config copy (or stop Ollama), POST to `/v1/messages` model `rc-main`, assert a 200 still returns (served by `rc-deepseek` fallback) and the response header/log names the fallback.

```python
import os, json, urllib.request
URL = "http://127.0.0.1:4000/v1/messages"; KEY = os.environ["LITELLM_MASTER_KEY"]
body = {"model": "rc-main", "max_tokens": 50, "messages": [{"role": "user", "content": "say OK"}]}
req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST",
    headers={"content-type":"application/json","x-api-key":KEY,"anthropic-version":"2023-06-01"})
with urllib.request.urlopen(req, timeout=120) as r:
    assert r.status == 200
    print("PASS: fallback served 200 with Ollama down ->", r.headers.get("x-litellm-model-id"))
```

- [ ] **Step 2: Run with Ollama stopped** - `taskkill /F /PID <ollama pid>`, run the smoke, expect PASS served by DeepSeek. Restart Ollama after. (Requires DEEPSEEK_API_KEY provisioned.)
- [ ] **Step 3: Commit** - `test(budget-saver): live fallback proof local-down -> deepseek`.

---

## Phase 4 - RC-native model qualification (C9)

### Task 9: qualify.py + curated task set

**Files:** Create `ops/budget_saver/qualify.py`, `ops/budget_saver/qual_tasks/*.json`, `tests/test_qualify.py`.

**Interfaces:** Produces `qualification_scorecard.json` scoring each model_name over the task set by RC's own oracle (py_compile + a per-task assertion). Fixtures are small, self-checking RC-shaped tasks.

- [ ] **Step 1: Define the task schema + 3 seed fixtures** in `qual_tasks/`. Each fixture:

```json
{
  "id": "t01_docstring_ascii",
  "tier": 0,
  "prompt": "Return ONLY a Python function `slug(s)` that lowercases s and replaces spaces with hyphens. ASCII only.",
  "oracle": {"kind": "py_exec", "call": "slug('Hello World')", "expect": "hello-world"}
}
```
Seed at least: `t01` (tier0 pure fn), `t02_fix_bug` (tier1: given a buggy fn, return fixed), `t03_scorer_math` (tier2: a small damage-math calc with a known numeric answer). Oracle kinds: `py_exec` (exec returned code, assert call==expect), `contains` (substring), `numeric` (float within eps).

- [ ] **Step 2: Failing test** `tests/test_qualify.py`

```python
import importlib.util, pathlib, json
spec = importlib.util.spec_from_file_location("qualify", pathlib.Path(__file__).resolve().parents[1] / "qualify.py")
q = importlib.util.module_from_spec(spec); spec.loader.exec_module(q)

def test_oracle_py_exec_pass():
    code = "def slug(s):\n    return s.lower().replace(' ','-')\n"
    assert q.grade({"kind":"py_exec","call":"slug('Hello World')","expect":"hello-world"}, code) is True
def test_oracle_py_exec_fail():
    assert q.grade({"kind":"py_exec","call":"slug('Hi There')","expect":"hi-there"}, "def slug(s): return s") is False
```

- [ ] **Step 3: Implement** `qualify.py` - core:

```python
import json, os, re, glob, pathlib, urllib.request, time
ROOT = pathlib.Path(__file__).resolve().parent
URL = "http://127.0.0.1:4000/v1/messages"

def grade(oracle: dict, code: str) -> bool:
    kind = oracle["kind"]
    if kind == "contains":
        return oracle["expect"] in code
    if kind == "py_exec":
        ns = {}
        try:
            exec(code, ns)                       # sandbox note: fixtures are trusted, local-only
            return str(eval(oracle["call"], ns)) == str(oracle["expect"])
        except Exception:
            return False
    if kind == "numeric":
        m = re.search(r"-?\d+\.?\d*", code)
        return m is not None and abs(float(m.group()) - float(oracle["expect"])) < float(oracle.get("eps", 1e-6))
    return False

def _extract_code(text: str) -> str:
    m = re.search(r"```(?:python)?\n(.*?)```", text, re.S)
    return m.group(1) if m else text

def ask(model: str, prompt: str) -> tuple[str, float]:
    body = {"model": model, "max_tokens": 800, "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST",
        headers={"content-type":"application/json","x-api-key":os.environ["LITELLM_MASTER_KEY"],
                 "anthropic-version":"2023-06-01"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=180) as r:
        out = json.loads(r.read())
    txt = "".join(b.get("text","") for b in out.get("content", []) if b.get("type")=="text")
    return txt, time.time() - t0

def run(models=("rc-local","rc-background","rc-deepseek")):
    tasks = [json.loads(pathlib.Path(p).read_text()) for p in glob.glob(str(ROOT/"qual_tasks"/"*.json"))]
    card = {}
    for m in models:
        rows = []
        for t in tasks:
            try:
                txt, dt = ask(m, t["prompt"])
                ok = grade(t["oracle"], _extract_code(txt))
            except Exception as e:
                ok, dt = False, 0.0
            rows.append({"id": t["id"], "tier": t["tier"], "pass": ok, "secs": round(dt,1)})
        passed = sum(r["pass"] for r in rows)
        card[m] = {"passed": passed, "total": len(rows), "rows": rows}
    (ROOT/"qualification_scorecard.json").write_text(json.dumps(card, indent=2), encoding="utf-8")
    return card

if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
```

- [ ] **Step 4: Run unit test, verify PASS.** Then run `qualify.py` live against the proxy to produce the real scorecard; use it to confirm/adjust `LOCAL_CTX_BUDGET` and the default profile.
- [ ] **Step 5: Commit** - `feat(budget-saver): RC-native model qualification harness + seed tasks`.

---

## Phase 5 - Monitor (C8)

### Task 10: monitor.py status page + ensure_stack

**Files:** Create `ops/budget_saver/monitor.py`, `tests/test_monitor.py`. Modify `setup.ps1` (register nothing yet - just document URLs).

**Interfaces:** Produces a `render_status() -> dict` (current profile/model from state.json, defer-queue depth, proxy health, backend list) and a tiny http page at `127.0.0.1:4100` linking LiteLLM `/ui` (:4000) and RC loop-monitor (:8888/loop-monitor).

- [ ] **Step 1: Failing test** `tests/test_monitor.py` - asserts `render_status()` returns keys `profile`, `model`, `defer_depth`, `proxy_up`, and that defer_depth reflects the queue.

```python
import importlib.util, pathlib, json
base = pathlib.Path(__file__).resolve().parents[1]
def _load(n):
    s = importlib.util.spec_from_file_location(n, base / f"{n}.py"); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
def test_render_status_shape(tmp_path, monkeypatch):
    mon = _load("monitor"); state = _load("state"); dq = _load("defer_queue")
    monkeypatch.setattr(state, "STATE_PATH", tmp_path/"s.json"); state.write("main","rc-main")
    monkeypatch.setattr(dq, "QUEUE_PATH", tmp_path/"q.jsonl"); dq.append({"task":"x","tier":3})
    monkeypatch.setattr(mon, "state", state); monkeypatch.setattr(mon, "defer_queue", dq)
    s = mon.render_status()
    assert s["profile"]=="main" and s["model"]=="rc-main" and s["defer_depth"]==1 and "proxy_up" in s
```

- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement** `monitor.py` - `render_status()` (reads state + defer_queue, pings `:4000/health/liveliness`), plus a stdlib `http.server` serving an HTML page that shows the status dict and links `/ui` + loop-monitor. Serve on `127.0.0.1:4100`. Launch via `pythonw` (no console). If LiteLLM `/metrics` returns 200, embed a small cost/latency summary; else read `/spend/logs` (VERIFY-AT-INSTALL which is available on 1.91.0).
- [ ] **Step 4: Run test, verify PASS. Manually open `http://127.0.0.1:4100` and confirm links + status render.**
- [ ] **Step 5: Commit** - `feat(budget-saver): standalone monitor page + LiteLLM/loop-monitor links`.

---

## Phase 6 - Auto-flip watchdog (C7)

### Task 11: watchdog.py + scheduled task

**Files:** Create `ops/budget_saver/watchdog.py`, `tests/test_watchdog.py`. Modify `setup.ps1` (register `RC-BudgetSaverWatchdog`).

**Interfaces:** Produces `should_arm(remaining_frac:float, threshold:float) -> bool` and an `arm()` that: warms the stack (ensure Ollama model loaded + proxy up), sets a persistent flag file `budget_saver_armed.flag` + a Machine env `RC_BUDGET_SAVER=1` (reference_scheduled_task_env_injection pattern), and toasts. Honest limit: arms the NEXT launch / loop cycle; does not hot-swap a live process.

- [ ] **Step 1: Failing test** `tests/test_watchdog.py`

```python
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location("wd", pathlib.Path(__file__).resolve().parents[1] / "watchdog.py")
wd = importlib.util.module_from_spec(spec); spec.loader.exec_module(wd)
def test_arms_below_threshold():
    assert wd.should_arm(remaining_frac=0.02, threshold=0.05) is True
def test_holds_above_threshold():
    assert wd.should_arm(remaining_frac=0.20, threshold=0.05) is False
```

- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement** `watchdog.py` - `should_arm` (pure), `get_remaining_frac()` (query usage via the `anthropic-usage` signal / `ANTHROPIC_USAGE_KEY`; VERIFY the exact call - fall back to reading a cost json if unavailable), `arm()` (write flag, set Machine env `RC_BUDGET_SAVER=1`, ensure stack warm, toast via `msg` or a log line), and a `main()` polling loop-free single-shot (the scheduled task provides cadence). Guard: only arm once (check flag before re-toasting).
- [ ] **Step 4: Run unit test, verify PASS. Dry-run `watchdog.py --dry-run` and confirm it reports remaining fraction without arming.**
- [ ] **Step 5: Register the task** - append to `setup.ps1`:

```powershell
# ===== Watchdog scheduled task (idempotent) =====
$taskName = "RC-BudgetSaverWatchdog"
$py = Join-Path $Root ".venv\Scripts\pythonw.exe"
$action = New-ScheduledTaskAction -Execute $py -Argument "`"$Root\watchdog.py`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 15)
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -StartWhenAvailable
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
  Set-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings | Out-Null
} else {
  Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -RunLevel Highest -User "Administrator" | Out-Null
}
Write-Output "[setup] RC-BudgetSaverWatchdog registered (15-min poll)."
```

- [ ] **Step 6: Commit** - `feat(budget-saver): auto-flip watchdog + RC-BudgetSaverWatchdog task`.

---

## Phase 7 - Docs + idempotency + integration

### Task 12: README + OPERATIONS pointer + final re-run proof

**Files:** Create `ops/budget_saver/README.md`. Modify `docs/OPERATIONS.md` (add a Budget-Saver section pointer). Modify root `.gitignore`.

- [ ] **Step 1: Write `README.md`** - runbook: what it is, the 3 shims and when to use each, how to set `env.local.ps1`, how to start the proxy, the monitor URLs (`:4000/ui`, `:4100`, `:8888/loop-monitor`), the DEFER queue workflow, the GATE verdict from Task 4, and the "arms next launch, not live process" note.
- [ ] **Step 2: Add `.gitignore` entries** (from File Structure) and an OPERATIONS.md pointer line.
- [ ] **Step 3: Idempotency proof** - run `setup.ps1` a SECOND time on the finished install; assert it makes no changes (no re-pull, no re-pip, task already registered path taken) and exits 0. Capture output.
- [ ] **Step 4: Full-suite sanity** - run `ops/budget_saver/.venv/Scripts/python.exe -m pytest ops/budget_saver/tests -v` (unit tests) green; run RC's own relevant suite if any file outside ops/budget_saver was touched (only docs/.gitignore here -> Tier-0).
- [ ] **Step 5: Commit + push branch** - `docs(budget-saver): README + OPERATIONS pointer + idempotency proof`, then push `budget-saver` and open a PR.

---

## Self-Review

**Spec coverage:** C1 (Task 2), C2 (Task 3), C3 (Task 3/8), C4 (Task 3/8), C5 (Tasks 5/6/7), C6 (Task 5), C7 (Task 11), C8 (Task 10), C9 (Task 9), C10 (Tasks 1-2 + 11 + 12 idempotency), C11 (Task 5 lean profile + Task 2 KV env + routing ctx budget). Security section -> Task 1 stealer guard + 127.0.0.1 binds + os.environ. Monitoring -> Task 10 + LiteLLM /ui + loop-monitor. All spec sections map to a task.

**Placeholder scan:** No "TBD/implement later". `VERIFY-AT-INSTALL` / `VERIFY-AT-BENCH` markers are explicit live-validation steps (safe version confirmed 1.91.0; model IDs confirmed; env vars confirmed), not lazy gaps. Every code step carries real code.

**Type consistency:** `state.write(profile, model)`, `defer_queue.append/load/drain`, `routing.choose_model(est_tokens, tier, privacy)`, `qualify.grade(oracle, code)` / `ask` / `run`, `monitor.render_status()`, `watchdog.should_arm(remaining_frac, threshold)` - names used consistently across tasks and their tests.

**Open GATE:** Task 4 decides whether local drives tool-calls. If it fails, MAIN shim defaults to `rc-deepseek` and local is background/summarize-only - the plan already branches on this; no other task depends on local tool-calling succeeding.
