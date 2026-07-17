LANE R - DEEP RESEARCH (2026-07-16 night run, headless, autonomous, zero questions).
You are in a dedicated git worktree on branch docs/research-20260716. Wall-clock target
3h max: at cap, commit what exists, push, exit cleanly. Chat output caveman ultra.

TASKS (fan out subagents; web research via WebSearch/WebFetch):
1. DS meta-valuation: real-meta build habits vs DS ranking for the champs flagged in
   memory feedback_ds_sweep_meta_valuation_research. START with Kai'Sa poke -> Manamune
   (memory project_ds_sweep_kaisa_poke_manamune): does the current meta run it, at what
   win/pick rate, and does the DS poke build value it - cite DS scorer file:line for the
   current treatment. Then 4-6 more champs where meta habit and DS reco likely diverge.
2. Patch 16.15 lookahead: item/champ changes that will hit DS ENGINE ingest next patch,
   including the shield-lerp next-patch-gated item. Sources: official patch preview,
   reliable patch-note aggregators.
3. Competitor feature lifts (Section 7b 6-point depth): findings go ONLY to
   C:\Users\Administrator\Desktop\research-20260716.md - NEVER into the repo (name-scrub
   rule; no competitor names in repo content or commit messages).

OUTPUT: NEW files only, under docs/research/2026-07-16-*.md (one per task 1 and 2),
cited (URL + access date), 7-bit ASCII, no em/en dashes. NO edits to existing files,
NO engine/code changes, NO restarts, NO test-suite runs (Tier-0).

LANDING: commit on this branch (git commit -F tmpfile, ASCII msg). Then try landing to
main: git fetch origin; git rebase origin/main; git push origin HEAD:main - retry x3 on
race (other autonomous lanes push tonight). If still refused, push the branch
(git push -u origin docs/research-20260716) and stop. Final act: append a 5-line summary
to ops/loop/reports/lane_research.done.txt in the MAIN checkout path C:\Riot Commander.
