# spawn_lanes.ps1 - detach the 2026-07-16 night-run parallel lanes as headless
# claude -p workers, each in its OWN git worktree (separate index = no contention with
# the md-cleanup loop committing in the main checkout; no AHK, no window focus).
$ErrorActionPreference = "Stop"
$root = "C:\Riot Commander"
$rep = "$root\ops\loop\reports"
$runner = "$root\ops\loop\run_lane.ps1"
$wtbase = "C:\rc-worktrees"
$wtR = "$wtbase\research-20260716"
$wtU = "$wtbase\ui-20260716"
New-Item -ItemType Directory -Force $rep | Out-Null
New-Item -ItemType Directory -Force $wtbase | Out-Null
Get-Command claude -ErrorAction Stop | Out-Null

if (-not (Test-Path $wtR)) { git -C $root worktree add $wtR -b docs/research-20260716 }
if (-not (Test-Path $wtU)) { git -C $root worktree add $wtU -b ui/overlay-item4-item8-20260716 }

$lanes = @(
  @{ Name = "research"; Prompt = "$root\ops\loop\prompts\lane_research_prompt.md"; Cwd = $wtR; Log = "$rep\lane_research.log" },
  @{ Name = "ui";       Prompt = "$root\ops\loop\prompts\lane_ui_prompt.md";       Cwd = $wtU; Log = "$rep\lane_ui.log" }
)
foreach ($l in $lanes) {
  $p = Start-Process powershell -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$runner`"", "-PromptFile", "`"$($l.Prompt)`"", "-Cwd", "`"$($l.Cwd)`"", "-Log", "`"$($l.Log)`"" -WindowStyle Hidden -PassThru
  Write-Host "lane $($l.Name) spawned pid=$($p.Id) log=$($l.Log)"
}
Write-Host "lanes detached; done-sentinels: $rep\lane_research.done.txt / $rep\lane_ui.done.txt"
