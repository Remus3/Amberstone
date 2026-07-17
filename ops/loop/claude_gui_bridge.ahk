#Requires AutoHotkey v2.0
#SingleInstance Force
SetTitleMatchMode 2
; gemini-headless-upgrade GUI bridge (the HANDS). The ONLY GUI actor.
; Polls control\gemini.ready; types its lines into the TARGET window; acks typed.flag.
; Target is FILE-DRIVEN (config not code), so this script is never edited between runs:
;   control\ahk_mode.txt    = "dry" (type into Notepad RC-LOOP-DRYRUN) or "live"
;   control\target_hwnd.txt = HWND of the dedicated Claude window. ONE claude.exe
;                             process owns MULTIPLE project windows (Image/RC/Claude,
;                             2026-07-16), so pid alone is AMBIGUOUS across them -
;                             the hwnd pins the exact window (LW a703ac1 parity).
;                             target_pid.txt is informational only.
; Live mode with a missing/empty target_hwnd.txt ABORTS the bridge outright.
; Exits when control\STOP appears.

CTL := "C:\Riot Commander\ops\loop\control"
READY := CTL "\gemini.ready"
TYPED := CTL "\typed.flag"
STOPF := CTL "\STOP"
MODEF := CTL "\ahk_mode.txt"
HWNDF := CTL "\target_hwnd.txt"
DRY_TITLE := "RC-LOOP-DRYRUN"
LINE_PAUSE := 1500
CLEAR_PAUSE := 5000   ; extra settle after a /clear line - the TUI session reset
                      ; takes a moment; typing the next prompt into the resetting
                      ; window loses keystrokes (operator directive 2026-07-16)

LogMsg(s) {
    global CTL
    FileAppend(FormatTime(, "yyyy-MM-dd HH:mm:ss") " " s "`n", CTL "\ahk_bridge.log")
}

Target() {
    global MODEF, HWNDF, DRY_TITLE
    mode := FileExist(MODEF) ? Trim(FileRead(MODEF)) : "live"
    if (mode = "dry")
        return DRY_TITLE
    hwnd := FileExist(HWNDF) ? Trim(FileRead(HWNDF)) : ""
    ; live mode is HWND-bound ONLY. Title fallback could type into ANOTHER project's
    ; Claude window; pid fallback is ambiguous because ONE claude.exe process owns
    ; ALL project windows (Image/RC/Claude, 2026-07-16). No hwnd = ABORT, no typing.
    if (hwnd = "") {
        LogMsg("ABORT: live mode with no target_hwnd.txt (hwnd-only policy, no title/pid fallback)")
        ExitApp
    }
    return "ahk_id " hwnd
}

LogMsg("ahk bridge start")
Loop {
    if FileExist(STOPF) {
        LogMsg("STOP seen, exit")
        ExitApp
    }
    if FileExist(READY) {
        content := FileRead(READY)
        lines := StrSplit(content, "`n", "`r")
        win := Target()
        if (win = "") {
            LogMsg("live mode with no target_pid.txt - refusing title fallback (multi-project safety)")
            Sleep 1500
            continue
        }
        if !WinExist(win) {
            LogMsg("target window not found: " win)
            Sleep 1500
            continue
        }
        WinActivate(win)
        WinWaitActive(win, , 5)
        Sleep 500
        typed := 0
        for idx, lineText in lines {
            if (idx = 1)                 ; skip CYCLE=n header
                continue
            if (Trim(lineText) = "")
                continue
            if (SubStr(lineText, 1, 1) = "/") {
                ; Slash-command line: commit the leading "/" on its own and pause so
                ; the Claude TUI slash-menu opens BEFORE the command word arrives.
                ; SendText of the whole short string raced that menu and the "/" landed
                ; AFTER the word ("clear/" not "/clear"), so /clear silently no-op'd and
                ; the session never reset (2026-06-06). The leading-slash split forces
                ; the slash ahead of the word.
                SendText("/")
                Sleep 400
                SendText(SubStr(lineText, 2))
            } else {
                SendText(lineText)
            }
            Sleep 350
            Send("{Enter}")
            typed += 1
            if (SubStr(Trim(lineText), 1, 6) = "/clear")
                Sleep CLEAR_PAUSE
            Sleep LINE_PAUSE
        }
        FileDelete(READY)              ; READY consumed = the "typed" signal the controller waits on
        LogMsg("typed " typed " lines into [" win "]")
    }
    Sleep 1000
}
