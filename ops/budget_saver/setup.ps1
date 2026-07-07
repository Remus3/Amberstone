# ===== RC Budget-Saver idempotent installer / repair =====
# Re-runnable: check-before-act everywhere. Stands up the local (tokenless) stack.
# Proxy venv uses Python 3.12 (litellm 1.91.0 requires >=3.10,<3.14; RC main py is 3.14).
$ErrorActionPreference = "Stop"
$Root   = "C:\Riot Commander\ops\budget_saver"
$Py312  = "C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe"
$Venv   = Join-Path $Root ".venv"
$VenvPy = Join-Path $Venv "Scripts\python.exe"

Write-Output "[setup] RC Budget-Saver - idempotent stand-up"

# 1. Isolated venv on Python 3.12
if (-not (Test-Path $Py312)) { throw "Python 3.12 not found at $Py312 (litellm needs <3.14). Install Python.Python.3.13 or 3.12." }
if (-not (Test-Path $VenvPy)) { & $Py312 -m venv $Venv }
& $VenvPy -m pip install --upgrade pip | Out-Null

# 2. LiteLLM pinned + supply-chain guard (skip if already 1.91.0)
$have = ""
try { $have = ((& $VenvPy -m pip show litellm 2>$null | Select-String "Version:") -replace "Version:\s*","").Trim() } catch {}
if ($have -ne "1.91.0") { & $VenvPy -m pip install "litellm[proxy]==1.91.0" }
& $VenvPy -m pip install prometheus_client | Out-Null   # metrics dep, not bundled in litellm[proxy]; pip no-op if present
$site = & $VenvPy -c "import site; print(site.getsitepackages()[0])"
if (Test-Path (Join-Path $site "litellm_init.pth")) {
  throw "SECURITY: litellm_init.pth stealer signature found - aborting, rotate all keys on this machine."
}
Write-Output ("[setup] litellm " + (& $VenvPy -c "import importlib.metadata as m; print(m.version('litellm'))"))

# 3. Ollama (install if missing) + KV/ctx server env + model pulls
$ollamaLocal = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
$ollama = (Get-Command ollama -ErrorAction SilentlyContinue).Source
if (-not $ollama -and (Test-Path $ollamaLocal)) { $ollama = $ollamaLocal }
if (-not $ollama) {
  try { winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements --silent | Out-Null } catch {}
  Start-Sleep -Seconds 6
  if (Test-Path $ollamaLocal) { $ollama = $ollamaLocal } else { $ollama = (Get-Command ollama -ErrorAction SilentlyContinue).Source }
}
if (-not $ollama) { throw "Ollama install failed - install manually from https://ollama.com/download" }
[Environment]::SetEnvironmentVariable("OLLAMA_FLASH_ATTENTION","1","Machine")
[Environment]::SetEnvironmentVariable("OLLAMA_KV_CACHE_TYPE","q8_0","Machine")
[Environment]::SetEnvironmentVariable("OLLAMA_CONTEXT_LENGTH","32768","Machine")
[Environment]::SetEnvironmentVariable("OLLAMA_HOST","127.0.0.1:11434","Machine")
$env:OLLAMA_FLASH_ATTENTION="1"; $env:OLLAMA_KV_CACHE_TYPE="q8_0"; $env:OLLAMA_CONTEXT_LENGTH="32768"
$tags = (& $ollama list) 2>&1 | Out-String
foreach ($t in @("qwen2.5-coder:14b-instruct","qwen2.5-coder:7b-instruct")) {
  if ($tags -notmatch [regex]::Escape($t)) { & $ollama pull $t }
}
Write-Output "[setup] Ollama ready (models present, KV-quant + 32K context env set)."

# 4. Watchdog scheduled task (guarded: only if watchdog.py exists)
$wd = Join-Path $Root "watchdog.py"
if (Test-Path $wd) {
  $taskName = "RC-BudgetSaverWatchdog"
  $pyw = Join-Path $Venv "Scripts\pythonw.exe"
  if (-not (Test-Path $pyw)) { $pyw = $VenvPy }
  $action = New-ScheduledTaskAction -Execute $pyw -Argument ('"' + $wd + '"')
  $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 15)
  $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -StartWhenAvailable
  if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Set-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings | Out-Null
  } else {
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -User "Administrator" | Out-Null
  }
  Write-Output "[setup] RC-BudgetSaverWatchdog registered (15-min poll)."
} else {
  Write-Output "[setup] watchdog.py not present yet - skipping task registration (re-run setup.ps1 after it lands)."
}

Write-Output "[setup] DONE. Start proxy: . .\env.local.ps1 ; .\.venv\Scripts\litellm.exe --config .\config.yaml --port 4000"
Write-Output "[setup] Launch budget-saver: .\budget-saver.ps1   (local-only: .\budget-saver-local.ps1   smart: .\budget-saver-smart.ps1)"
