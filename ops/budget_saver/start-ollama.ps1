# Start the Ollama server bound to 127.0.0.1 with KV-quant + 32K context.
# Long-running. For persistence across logon, setup.ps1 registers this as a scheduled task.
$env:OLLAMA_HOST            = "127.0.0.1:11434"
$env:OLLAMA_FLASH_ATTENTION = "1"
$env:OLLAMA_KV_CACHE_TYPE   = "q8_0"
$env:OLLAMA_CONTEXT_LENGTH  = "32768"
$bin = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
if (-not (Test-Path $bin)) { $bin = (Get-Command ollama -ErrorAction SilentlyContinue).Source }
& $bin serve
