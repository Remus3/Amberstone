#Requires AutoHotkey v2.0
#SingleInstance Force
SetTitleMatchMode 2
; directed-headless-upgrade GUI bridge (the HANDS). The ONLY GUI actor.
; Polls control\gemini.ready; types its lines into the TARGET window; acks by DELETING
; gemini.ready. That deletion IS the "typed" signal loop_controller waits on (wait_gone,
; 120s), so NOTHING else may delete it - a partial or unfocused type must leave it in
; place and let the controller report a clean "AHK never typed" timeout instead.
; Target is FILE-DRIVEN (config not code), so this script is never edited between runs:
;   control\ahk_mode.txt      = "dry" (type into Notepad RC-LOOP-DRYRUN) or "live"
;   control\target_hwnd.txt   = HWND of the dedicated Claude window. ONE claude.exe
;                               process owns MULTIPLE project windows (Image/RC/Claude,
;                               2026-07-16), so pid alone is AMBIGUOUS across them -
;                               the hwnd pins the exact window (LW a703ac1 parity).
;                               target_pid.txt is informational only.
;   control\ahk_timings.json  = tunables, re-read at EVERY gemini.ready pickup so the
;                               operator can retune a LIVE loop without restarting
;                               anything. Seeded from ops\loop\ahk_timings.default.json
;                               by launch_loop.ps1. Every key has a hardcoded fallback
;                               below, so a missing/malformed file degrades to the
;                               shipped behavior rather than breaking the hands.
; Emits control\ahk_heartbeat.txt (ONE bare unix-epoch-seconds integer) at ~1Hz for its
; whole life, including mid-directive; the controller treats >60s stale as a dead bridge
; instead of burning a full cycle deadline on dead air.
; control\ahk_partial.flag records a directive that only PARTIALLY typed, and latches the
; bridge against re-sending THAT directive (re-typing it would double-send the lines that
; already landed). The latch is SCOPED BY CONTENT HASH, not by cycle number, and a
; different directive auto-clears it - see ContentTag() for why the CYCLE=n header cannot
; be used and why an absolute latch is unacceptable in an autonomous loop.
; Live mode with a missing/empty target_hwnd.txt ABORTS the bridge outright.
; Exits when control\STOP appears.

CTL := "C:\Riot Commander\ops\loop\control"
READY := CTL "\gemini.ready"
TYPED := CTL "\typed.flag"
STOPF := CTL "\STOP"
MODEF := CTL "\ahk_mode.txt"
HWNDF := CTL "\target_hwnd.txt"
TIMEF := CTL "\ahk_timings.json"
PARTF := CTL "\ahk_partial.flag"
BEATF := CTL "\ahk_heartbeat.txt"
BEATT := CTL "\ahk_heartbeat.tmp"
DRY_TITLE := "RC-LOOP-DRYRUN"

; Hardcoded fallbacks. These ARE the pre-hardening literals - a bridge launched with the
; shipped defaults must reproduce the previous timing behavior exactly.
DEF := Map(
    "line_pause_ms", 1500,          ; was LINE_PAUSE
    "pre_enter_pause_ms", 350,      ; settle between SendText and {Enter}
    "enter_retry_pause_ms", 250,    ; gap before the second {Enter} - see the double-Enter
                                    ; scar at the send site (a swallowed Enter leaves the
                                    ; directive typed-but-unsent until the deadline)
    "clear_pause_ms", 5000,         ; was CLEAR_PAUSE - the TUI session reset takes a
                                    ; moment; typing the next prompt into the resetting
                                    ; window loses keystrokes (operator, 2026-07-16)
    "slash_split_pause_ms", 400,    ; gap between the lone "/" and the command word
    "pre_type_settle_ms", 500,      ; settle after a confirmed activation
    "activate_retries", 3,
    "activate_timeout_sec", 5,      ; per-attempt WinWaitActive budget
    "idle_guard_ms", 2000,          ; physical-idle required before stealing focus
    "idle_guard_max_defer_ms", 30000)
T := DEF.Clone()

; Sequence state, read by the fatal handler so an uncaught fault is diagnosable.
g_seq_active := 0
g_seq_cycle := ""
g_seq_typed := 0
g_seq_tag := ""

OnError(BridgeFatal)

LogMsg(s) {
    global CTL
    try FileAppend(FormatTime(, "yyyy-MM-dd HH:mm:ss") " " s "`n", CTL "\ahk_bridge.log")
}

BridgeFatal(err, mode) {
    global PARTF, g_seq_active, g_seq_cycle, g_seq_typed, g_seq_tag
    msg := "UNCAUGHT ERROR"
    try msg .= ": " err.Message " (" err.File ":" err.Line ")"
    LogMsg(msg)
    if (g_seq_active) {
        LogMsg("LATCH SET (fatal): " g_seq_cycle " typed=" g_seq_typed " tag=" g_seq_tag)
        rec := FormatTime(, "yyyy-MM-dd HH:mm:ss") " " g_seq_cycle " typed=" g_seq_typed " tag=" g_seq_tag " reason=uncaught bridge error`n"
        try FileAppend(rec, PARTF)
    }
    ; An AHK error dialog is MODAL: it would park the hands of an autonomous loop forever
    ; with no signal. Exit instead, so the heartbeat goes stale and the controller sees a
    ; dead bridge within its staleness window.
    ExitApp(1)
}

Beat() {
    global BEATF, BEATT
    ; LIVENESS CONTRACT with loop_controller: ahk_heartbeat.txt holds ONE bare
    ; unix-epoch-seconds integer and nothing else (no prefix, no key, trailing newline
    ; neither required nor written). Written temp-then-move because an in-place rewrite
    ; can be observed empty or half-written; MoveFileEx replace on one volume is atomic,
    ; so a mid-write read yields the PREVIOUS integer, never garbage.
    try {
        if FileExist(BEATT)
            FileDelete(BEATT)
        FileAppend(DateDiff(A_NowUTC, "19700101000000", "Seconds"), BEATT)
        FileMove(BEATT, BEATF, 1)
    }
    catch {
        ; a transient sharing violation must never kill the bridge; next tick retries
    }
}

SleepBeat(ms) {
    ; Any wait longer than the heartbeat period still has to beat. A long directive
    ; (many lines x line_pause plus the /clear settle) would otherwise look like a dead
    ; bridge to the controller while it is typing perfectly well.
    remain := ms
    while (remain > 0) {
        chunk := remain > 1000 ? 1000 : remain
        Sleep chunk
        remain -= chunk
        Beat()
    }
}

ReadNum(txt, key, dflt) {
    ; AHK v2 ships no JSON parser and the hands of the loop take NO dependency for this,
    ; so the timings file is read with a tolerant "key": <int> lookup: leading/trailing
    ; whitespace, key ORDER, unknown keys and comment keys are all tolerated. Anything
    ; absent, non-numeric or negative falls back to the hardcoded default so a typo
    ; degrades to shipped behavior instead of wedging the bridge.
    if (txt = "")
        return dflt
    if !RegExMatch(txt, '"' key '"\s*:\s*(-?\d+)', &m)
        return dflt
    v := Integer(m[1])
    return (v < 0) ? dflt : v
}

LoadTimings() {
    global TIMEF, DEF, T
    txt := ""
    try {
        if FileExist(TIMEF)
            txt := FileRead(TIMEF)
    }
    catch {
        txt := ""
    }
    for k, v in DEF
        T[k] := ReadNum(txt, k, v)
    ; zero is a legal "disabled" value for the pauses and the idle guard, but a zero
    ; retry count or activation timeout would mean "never confirm focus" - refuse it.
    if (T["activate_retries"] < 1)
        T["activate_retries"] := DEF["activate_retries"]
    if (T["activate_timeout_sec"] < 1)
        T["activate_timeout_sec"] := DEF["activate_timeout_sec"]
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
        ExitApp()
    }
    return "ahk_id " hwnd
}

ActivateTarget(win, retries, timeoutSec) {
    ; Returns non-zero ONLY on CONFIRMED activation. The WinWaitActive return value used
    ; to be discarded, so an activation timeout fell straight through into the type loop
    ; and sprayed a whole directive plus its Enter keys into whatever window happened to
    ; hold focus. Never type unfocused - a caller that gets 0 here must not type.
    Loop retries {
        if !WinExist(win)
            return 0
        try WinActivate(win)
        catch {
            return 0
        }
        if WinWaitActive(win, , timeoutSec)
            return 1
        LogMsg("activation attempt " A_Index "/" retries " timed out for [" win "]")
        SleepBeat(300 * A_Index)      ; linear backoff - a focus thief is usually brief
    }
    return 0
}

RestoreForeground(prior, targetHwnd) {
    ; The bridge force-activates its target; without this an autonomous cycle would
    ; permanently steal the operator's foreground window. Strictly AFTER the handshake so
    ; it can never race the typing, and skipped when the prior foreground WAS the target
    ; (the steady autonomous case), where restoring would only cause a flicker.
    if (!prior || prior = targetHwnd)
        return
    if !WinExist("ahk_id " prior)
        return
    try WinActivate("ahk_id " prior)
}

IdleGuard() {
    global T
    ; Do not yank focus out from under a human at the keyboard. A_TimeIdlePhysical is ms
    ; since the last physical input; with no keyboard/mouse hook installed it degrades to
    ; A_TimeIdle, which can only OVER-report activity here (the bridge sleeps, it does not
    ; type, while deferring), so the guard errs safe either way. Deliberately NOT applied
    ; per line: mid-sequence the correct answer is abort, not defer.
    thresh := T["idle_guard_ms"]
    if (thresh <= 0)
        return
    cap := T["idle_guard_max_defer_ms"]
    waited := 0
    while (A_TimeIdlePhysical < thresh) {
        if (waited >= cap) {
            ; HARD CAP: this guard must never be able to deadlock an autonomous loop.
            LogMsg("idle guard: operator still active after " waited "ms - cap reached, proceeding")
            return
        }
        SleepBeat(250)
        waited += 250
    }
    if (waited > 0)
        LogMsg("idle guard: deferred " waited "ms for physical operator input")
}

ContentTag(s) {
    ; Identity of a directive, used ONLY to decide whether an incoming gemini.ready is the
    ; SAME one a partial type failed on.
    ; NOT keyed on the CYCLE=n header: the controller's one-shot stall recovery REUSES the
    ; stalled cycle number (stall_recovery_directive, pinned by
    ; tests/test_loop_stall_recovery.py to emit "CYCLE=7" for cycle 7). A header-keyed
    ; latch would therefore refuse the very recovery directive that exists to unwedge a
    ; stalled bridge, and the controller would hard-stop 120s later. Bodies always differ,
    ; so hash the FULL content instead.
    ; Polynomial rolling hash with an explicit modulus - AHK v2 has no hash builtin, and an
    ; unbounded multiply would overflow 64-bit. 131 * 1e9 stays far inside the range.
    ; Length is prefixed so a hash collision alone cannot alias two directives.
    h := 0
    Loop Parse, s
        h := Mod(h * 131 + Ord(A_LoopField), 1000000007)
    return StrLen(s) "-" h
}

PartialTag() {
    global PARTF
    ; "" means either no flag, or a flag this bridge did not write (see the untagged
    ; branch in the main loop - that case is held absolutely, on purpose).
    txt := ""
    try {
        if FileExist(PARTF)
            txt := FileRead(PARTF)
    }
    catch {
        return ""
    }
    if RegExMatch(txt, "tag=(\S+)", &m)
        return m[1]
    return ""
}

WritePartial(cycleHdr, typedCount, tag) {
    global PARTF
    ; Single-record STATE file answering "which directive was partially typed", so the
    ; latch can be scoped to it. The append-only HISTORY of latch/clear events lives in
    ; ahk_bridge.log, because a latched bridge keeps heartbeating and is otherwise
    ; indistinguishable from a healthy one.
    rec := FormatTime(, "yyyy-MM-dd HH:mm:ss") " " cycleHdr " typed=" typedCount " tag=" tag " reason=focus lost mid-sequence, re-activation failed`n"
    try {
        if FileExist(PARTF)
            FileDelete(PARTF)
        FileAppend(rec, PARTF)
    }
    catch {
        LogMsg("WARNING: could not write ahk_partial.flag - the in-process latch still holds for this directive")
    }
}

LatchDue(&lastTs) {
    ; Latch state is logged on transition and then RE-STATED every 60s. Every latch set and
    ; every auto-clear is recorded; the periodic re-statement is what turns a chronic focus
    ; problem into a visible repeating pattern rather than one line lost in the log.
    if (lastTs && A_TickCount - lastTs < 60000)
        return 0
    lastTs := A_TickCount
    return 1
}

LogMsg("ahk bridge start")
Beat()
latchTag := ""       ; content tag of a partially-typed directive we must NOT re-send
latchLogTs := 0
Loop {
    Beat()
    if FileExist(STOPF) {
        LogMsg("STOP seen, exit")
        ExitApp()
    }
    if FileExist(READY) {
        content := FileRead(READY)
        tag := ContentTag(content)
        ; SCOPED LATCH. A partial type leaves lines already sitting in the target window,
        ; so re-sending THAT directive would double-send them. But an ABSOLUTE latch
        ; (clearable only by relaunch) would let one mid-run focus steal wedge the loop
        ; until a human intervened, which defeats autonomous looping. So the latch is
        ; scoped to the failed directive's CONTENT: same content holds, anything else
        ; clears it and proceeds.
        holdTag := ""
        if FileExist(PARTF) {
            holdTag := PartialTag()
            if (holdTag = "") {
                ; No tag=... means this bridge did not write the flag (an operator pause,
                ; or a truncated write). Absolute hold is the safe reading of an unknown
                ; flag, and deleting the file clears it.
                if LatchDue(&latchLogTs)
                    LogMsg("LATCH HOLD (untagged): ahk_partial.flag has no tag=... - refusing every pickup until the file is removed. Bridge is ALIVE and still heartbeating.")
                Sleep 1000
                continue
            }
        }
        else if (latchTag != "") {
            holdTag := latchTag        ; flag write failed earlier; in-process latch stands
        }
        if (holdTag != "") {
            if (holdTag = tag) {
                if LatchDue(&latchLogTs)
                    LogMsg("LATCH HOLD: incoming gemini.ready is the SAME directive that partially typed (tag=" tag ") - refusing to re-send it. Bridge is ALIVE and still heartbeating, so the controller's stale-heartbeat check CANNOT see this state; this log line is the only signal of it.")
                Sleep 1000
                continue
            }
            ; Different content = a new directive supersedes the partial one. This is the
            ; path the controller's one-shot stall recovery takes: it reuses the stalled
            ; CYCLE number, so only the content distinguishes it from what stalled.
            LogMsg("LATCH AUTO-CLEAR: new directive tag=" tag " differs from partially-typed tag=" holdTag " - clearing ahk_partial.flag and proceeding normally")
            try FileDelete(PARTF)
            latchTag := ""
            latchLogTs := 0
        }
        LoadTimings()
        lines := StrSplit(content, "`n", "`r")
        cycleHdr := lines.Length ? Trim(lines[1]) : "CYCLE=?"
        win := Target()
        if !WinExist(win) {
            LogMsg("target window not found: " win)
            Sleep 1500
            continue
        }
        targetHwnd := WinExist(win)
        prior := WinExist("A")
        IdleGuard()
        if !ActivateTarget(win, T["activate_retries"], T["activate_timeout_sec"]) {
            ; gemini.ready stays UNCONSUMED: the controller's 120s wait_gone then reports
            ; a clean "AHK never typed" instead of the directive landing in a stranger.
            LogMsg("ACTIVATION FAILED for [" win "] - not typing, gemini.ready left unconsumed")
            Sleep 1500
            continue
        }
        SleepBeat(T["pre_type_settle_ms"])
        typed := 0
        aborted := 0
        g_seq_active := 1
        g_seq_cycle := cycleHdr
        g_seq_typed := 0
        g_seq_tag := tag
        for idx, lineText in lines {
            if (idx = 1)                 ; skip CYCLE=n header
                continue
            if (Trim(lineText) = "")
                continue
            ; RE-ASSERT FOCUS BEFORE EVERY LINE. A directive is many lines over many
            ; seconds; a notification, the operator or an installer can steal focus
            ; mid-sequence, and the remaining lines would land in the thief.
            if !WinActive("ahk_id " targetHwnd) {
                LogMsg("focus lost before line " idx " - re-activating [" win "]")
                if !ActivateTarget("ahk_id " targetHwnd, T["activate_retries"], T["activate_timeout_sec"]) {
                    aborted := 1
                    break
                }
                SleepBeat(T["pre_type_settle_ms"])
            }
            if (SubStr(lineText, 1, 1) = "/") {
                ; Slash-command line: commit the leading "/" on its own and pause so
                ; the Claude TUI slash-menu opens BEFORE the command word arrives.
                ; SendText of the whole short string raced that menu and the "/" landed
                ; AFTER the word ("clear/" not "/clear"), so /clear silently no-op'd and
                ; the session never reset (2026-06-06). The leading-slash split forces
                ; the slash ahead of the word.
                SendText("/")
                Sleep T["slash_split_pause_ms"]
                SendText(SubStr(lineText, 2))
            } else {
                SendText(lineText)
            }
            Sleep T["pre_enter_pause_ms"]
            ; DOUBLE ENTER, on purpose. A single {Enter} is swallowed often enough that
            ; the directive lands in the composer and is NEVER SUBMITTED - the cycle then
            ; sits typed-but-unsent until the deadline with no error (operator observed
            ; live 2026-07-26; same failure class as the /clear -> clear/ race and the
            ; slash palette eating Enter, both scarred above). The retry is safe rather
            ; than a gamble: if the first Enter DID submit, the composer is now empty and
            ; Enter on an empty composer is a no-op.
            Send("{Enter}")
            Sleep T["enter_retry_pause_ms"]
            Send("{Enter}")
            typed += 1
            g_seq_typed := typed
            if (SubStr(Trim(lineText), 1, 6) = "/clear")
                SleepBeat(T["clear_pause_ms"])
            SleepBeat(T["line_pause_ms"])
        }
        g_seq_active := 0
        if (aborted) {
            ; Diagnosable, not silent: record WHICH cycle stopped and HOW MANY lines
            ; landed. gemini.ready is left unconsumed on purpose - a partial type is not
            ; a type, and the controller must see a timeout rather than a false ack.
            WritePartial(cycleHdr, typed, tag)
            LogMsg("LATCH SET: PARTIAL " cycleHdr " aborted after " typed " lines (tag=" tag ") - gemini.ready left unconsumed. Latched against THIS directive only; a different directive auto-clears it.")
            latchTag := tag
            latchLogTs := A_TickCount
        }
        else {
            FileDelete(READY)          ; READY consumed = the "typed" signal the controller waits on
            LogMsg("typed " typed " lines into [" win "]")
            RestoreForeground(prior, targetHwnd)
        }
    }
    Sleep 1000
}
