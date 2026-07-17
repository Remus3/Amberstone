LANE U - UI/UX NO-GAME (2026-07-16 night run, headless, autonomous, zero questions).
You are ALREADY in a dedicated git worktree on branch ui/overlay-item4-item8-20260716 -
do not create another worktree. Wall-clock target 3h max: at cap, commit, push branch,
write handoff, exit. Chat output caveman ultra.

SCOPE - pin first, then build:
0. Pin exact scope from docs/LEDGER.md items 859/860 + memory project_next_ingame_ui_finish
   + memory project_overlay_item4_client_settings_reorg. Cite what is already shipped;
   re-doing shipped work is a defect (verify-premise first: grep file:line before building).
1. Overlay item 4 - Client Settings reorg per
   docs/specs/2026-07-11-overlay-item4-client-settings-reorg-design.md (rename +
   consolidate Settings menu, opacity split, DS Settings panel reorg).
2. Overlay item 8 - BACKEND ONLY: mode-specific rank-tier stats from
   data/rewind_history.db per docs/specs/2026-07-11-overlay-item8-rank-tier-stats-panel.md.
   No panel render work tonight.

HARD LIMITS: TDD (failing test first). Headless tests only - run the touched modules'
tests (Tier-1), full suite NOT required tonight. NO merge to main. NO RC or DS restarts,
NO restart_trigger, NO live deploy. NO 5-phase visual fixture audit tonight (Electron
windows would fight the AHK bridge for focus) - the audit + merge happen in tomorrow's
interactive session, per the audit-before-ship ritual. Frozen files untouched. 7-bit
ASCII, no em/en dashes. ruff clean on new/edited files before committing.

LANDING: commit per coherent unit on THIS branch, then git push -u origin
ui/overlay-item4-item8-20260716. Write docs/specs/2026-07-16-ui-worktree-handoff.md ON
THE BRANCH: what shipped, test counts observed this run, what the audit session must do.
Final act: append a 5-line summary to ops/loop/reports/lane_ui.done.txt in the MAIN
checkout path C:\Riot Commander.
