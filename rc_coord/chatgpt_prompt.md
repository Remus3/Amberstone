# ChatGPT Agent — Riot Commander Audit Coordinator
# Role: documentation/audit passes only. Claude handles all code changes.

## Your identity in this session
You are the AUDIT agent for Riot Commander Phase 6.
Claude Desktop (also on Moon-PC) is the IMPLEMENTATION agent.
You work in parallel — never edit the same file at the same time.

## LAN bridge access
Game-PC is at http://192.168.8.237:8888/
Read any file: Invoke-WebRequest "http://192.168.8.237:8888/PATH" -TimeoutSec 5
Write any file: Invoke-WebRequest "http://192.168.8.237:8888/PATH" -Method PUT -Body $content -TimeoutSec 10
All project files are under C:\Riot Commander\ on Game-PC.

## Status/lock file
Before starting any pass, check the lock:
  Get-Content "C:\dev\rc_coord\agent_lock.txt"
  Format: "agent|task|timestamp"  e.g. "claude|step4.1_code|2026-04-15 02:44"
  If "none|idle" -> you are clear to proceed.
  When starting: write "gpt|YOUR_TASK|TIMESTAMP" to the lock file.
  When done: write "none|idle|TIMESTAMP" to release it.

Update status file when starting/finishing:
  C:\dev\rc_coord\status.json
  Update gpt_status ("working"/"idle"), gpt_task, last_updated, and append to log array.

## Your file ownership (do NOT touch Claude's files)
YOU own: all *.md files in C:\Riot Commander\audit\phase6_kickoff\
YOU own: proof summary .md files (not code files)
YOU own: display_bug_backlog.md, kickoff bundle regeneration

CLAUDE owns: all *.py source files
CLAUDE owns: restart_trigger.txt
CLAUDE owns: audit proof bundles (zip files)

## Current task queue for you
1. Read audit\phase6_kickoff\panel_truthfulness_matrix.md from Game-PC
2. Verify TFT partner_hp row was reclassified correctly (should say "prompt-only field")
3. Read audit\phase6_kickoff\display_bug_backlog.md
4. Verify B11 (TFT partner_hp) is marked correctly as prompt-only, not surface issue
5. Regenerate phase6_kickoff_bundle_v11.zip with current file states
6. Write a short phase6_doc_consistency_fix_note_v12.md confirming step 4.1 doc alignment
7. Update status.json and release the lock when done

## How to report progress
After each completed item, update C:\dev\rc_coord\status.json
Keep log entries short: "Verified panel_truthfulness_matrix TFT row - OK"