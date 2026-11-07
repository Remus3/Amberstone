# Render a tracked scheduled-task template (ops\<Name>.xml) into the UTF-16 file
# that schtasks /Create /XML imports. RM-723: the tracked templates carry no
# machine values (no checkout root, account, computer name or SID); this fills
# them at install time. It touches no scheduled task.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File tools\install_render_task_xml.ps1 -Name RC-DaemonSlayer -OutFile <file>
#   ... -PythonW <path to pythonw.exe>   (optional override of the pinned interpreter)
#
# Placeholders:
#   __RC_REPO__     this checkout's root (the parent of tools\)
#   __RC_USER__     the logged-on account ($env:USERNAME)
#   __RC_PYTHONW__  the pinned interpreter, by default
#                   $env:LOCALAPPDATA\Programs\Python\Python314\pythonw.exe of the
#                   INSTALLING account. Resolved here, not left as %LOCALAPPDATA%,
#                   because a SYSTEM task's own LOCALAPPDATA is the system profile:
#                   an absent interpreter makes a task that silently does nothing.
#
# Refuses (non-zero exit, no file written): a name that is not RC-<word>, a
# missing template, an absent interpreter, a placeholder left unfilled, or a
# rendered document that does not parse as XML.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][string]$OutFile,
    [string]$PythonW = ''
)

$ErrorActionPreference = 'Stop'

if ($Name -notmatch '^RC-[A-Za-z0-9]+$') {
    throw "install_render_task_xml: not a task name: $Name"
}
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$template = Join-Path $repo ('ops\' + $Name + '.xml')
if (-not (Test-Path -LiteralPath $template -PathType Leaf)) {
    throw "install_render_task_xml: no template ops\$Name.xml"
}

if (-not $PythonW) {
    if (-not $env:LOCALAPPDATA) { throw 'install_render_task_xml: LOCALAPPDATA is not set' }
    $PythonW = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314\pythonw.exe'
}
if (-not (Test-Path -LiteralPath $PythonW -PathType Leaf)) {
    throw "install_render_task_xml: interpreter not found: $PythonW"
}
if (-not $env:USERNAME) { throw 'install_render_task_xml: USERNAME is not set' }

$text = [System.IO.File]::ReadAllText($template, [System.Text.Encoding]::UTF8)
$text = $text.Replace('__RC_REPO__', [System.Security.SecurityElement]::Escape($repo))
$text = $text.Replace('__RC_USER__', [System.Security.SecurityElement]::Escape($env:USERNAME))
$text = $text.Replace('__RC_PYTHONW__', [System.Security.SecurityElement]::Escape($PythonW))

$left = @([regex]::Matches($text, '__RC_[A-Z0-9_]+__') | ForEach-Object { $_.Value })
if ($left.Count -gt 0) {
    throw ("install_render_task_xml: unfilled placeholder(s) in ops\$Name.xml: " + ($left -join ', '))
}
$null = [xml]$text

# UTF-16 LE with a BOM: the encoding schtasks /Query /XML exports and /XML imports.
$utf16 = New-Object System.Text.UnicodeEncoding($false, $true)
[System.IO.File]::WriteAllText($OutFile, $text, $utf16)
Write-Output "install_render_task_xml: ops\$Name.xml -> $OutFile"
