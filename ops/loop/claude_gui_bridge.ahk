#Requires AutoHotkey v2.0
#SingleInstance Force
SetTitleMatchMode 2
; gemini-headless-upgrade GUI bridge (the HANDS). The ONLY GUI actor.
; Polls control\gemini.ready; types its lines into the TARGET window; acks typed.flag.
; Target is FILE-DRIVEN (config not code), so this script is never edited between runs:
;   control\ahk_mode.txt  = "dry" (type into Notepad RC-LOOP-DRYRUN) or "live"
;   control\target_pid.txt = PID of the dedicated Claude window (live mode)
; Exits when control\STOP appears.

CTL := "C:\Riot Commander\ops\loop\control"
READY := CTL "\gemini.ready"
TYPED := CTL "\typed.flag"
STOPF := CTL "\STOP"
MODEF := CTL "\ahk_mode.txt"
PIDF := CTL "\target_pid.txt"
DRY_TITLE := "RC-LOOP-DRYRUN"
LINE_PAUSE := 1500

LogMsg(s) {
    global CTL
    FileAppend(FormatTime(, "yyyy-MM-dd HH:mm:ss") " " s "`n", CTL "\ahk_bridge.log")
}

Target() {
    global MODEF, PIDF, DRY_TITLE
    mode := FileExist(MODEF) ? Trim(FileRead(MODEF)) : "live"
    if (mode = "dry")
        return DRY_TITLE
    pid := FileExist(PIDF) ? Trim(FileRead(PIDF)) : ""
    ; live mode is PID-bound ONLY. The old title fallback ("Claude", substring match)
    ; could type into ANOTHER project's Claude window (Sibling-A runs a sibling
    ; loop on this desktop, 2026-07-16). No pid file = no target = no typing.
    return pid ? "ahk_pid " pid : ""
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
            Sleep LINE_PAUSE
        }
        FileDelete(READY)              ; READY consumed = the "typed" signal the controller waits on
        LogMsg("typed " typed " lines into [" win "]")
    }
    Sleep 1000
}
