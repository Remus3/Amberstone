#Requires AutoHotkey v2.0
; tools/claude_send.ahk - send a command into the Claude Code desktop app (PROVISIONAL)
; Drives the Claude Code window (ahk_exe claude.exe, title "Claude") to type a
; command (default "/clear") and press Enter - the headless self-clear-between-tasks
; primitive. SAFETY: verifies the target window exists before typing; DRY-RUN unless
; "go" is passed; 1.5s abort window with a kill-switch; logs every action. NOT wired
; into any loop or trigger - it only acts when invoked explicitly.
;
; Usage (AHK v2):
;   AutoHotkey64.exe claude_send.ahk                 -> DRY RUN, default cmd "/clear"
;   AutoHotkey64.exe claude_send.ahk "/clear" go     -> LIVE: types /clear + Enter
;   AutoHotkey64.exe claude_send.ahk "continue" go   -> LIVE: types any prompt + Enter
; Kill-switch during the abort window: Ctrl+Alt+Q.
; NOTE: relies on the Claude window focusing its prompt input on activate. If text
; lands in the wrong control, add a click on the input area before SendText.

^!q::ExitApp()  ; kill-switch

cmd := A_Args.Length >= 1 ? A_Args[1] : "/clear"
live := (A_Args.Length >= 2 && A_Args[2] = "go")
winId := "ahk_exe claude.exe"
logf := A_ScriptDir "\..\logs\claude_send.log"

LogLine(tag) {
    global cmd, logf
    FileAppend(FormatTime(, "yyyy-MM-dd HH:mm:ss") " [" tag "] cmd=" cmd "`n", logf)
}

if !WinExist(winId) {
    LogLine("ABORT-no-window")
    ExitApp(2)
}

if !live {
    LogLine("DRYRUN-would-send")
    ExitApp(0)
}

Sleep(1500)  ; abort window - Ctrl+Alt+Q still live here

WinActivate(winId)
if !WinWaitActive(winId, , 3) {
    LogLine("ABORT-activate-failed")
    ExitApp(3)
}
Sleep(250)
SendText(cmd)
Sleep(80)
Send("{Enter}")
LogLine("SENT")
ExitApp(0)
