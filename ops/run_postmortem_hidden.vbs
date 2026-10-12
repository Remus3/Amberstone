' Hidden launcher for the RC-PostmortemAnalyze scheduled task.
'
' The task executes:  wscript.exe //B //NoLogo "<repo>\ops\run_postmortem_hidden.vbs"
' (registered by ops/install_RC_PostmortemAnalyze.ps1).
'
' Why a wrapper: Windows PowerShell 5.1 is a console program, so a task that
' executes powershell.exe directly gets a conhost window that is painted first
' and hidden only after the host initialises, even with -WindowStyle Hidden
' (MAIN FIX note 2026-10-11 2226). WScript.Shell Run with window style 0
' creates the console hidden from the start. wscript.exe is a GUI program and
' //B suppresses script-error dialogs, so nothing can sit on the desktop.
'
' Run(cmd, 0, True): 0 = hidden window, True = wait for the child to exit.
' WScript.Quit returns the child's exit code, so the task's LastTaskResult
' still carries the analyzer's code (0 ok / 2 missing PUUIDs / 3 DB not found,
' 1 = wrapper FATAL). This launcher adds two of its own:
'   90 = run_postmortem_with_restart.ps1 not found next to this file
'   91 = WScript.Shell Run raised (powershell.exe could not be started)
'
' Paths derive from this file's own location; no machine path lives here.
' 7-bit ASCII, LF line endings (pinned in .gitattributes).

Option Explicit

Dim shell, fso, opsDir, target, cmd, code

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

opsDir = fso.GetParentFolderName(WScript.ScriptFullName)
target = fso.BuildPath(opsDir, "run_postmortem_with_restart.ps1")

If Not fso.FileExists(target) Then
    WScript.Quit 90
End If

cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & target & """"

On Error Resume Next
code = shell.Run(cmd, 0, True)
If Err.Number <> 0 Then
    WScript.Quit 91
End If
On Error GoTo 0

WScript.Quit code
