# O3e finding (RC s164, read-only) - verdict: RULED OUT - no startup-token regression in 11-02..11-09

## CORRECTION (verifier-measured, supersedes the sonnet-switch inference in Findings 2 and 4)

The ds p10 cache_creation drop (84-93k on 10-27..10-31 -> ~53k from 11-04/11-05) is a RUN-MIX shift: pre-11-01 ds rows were 27-34-turn working cycles, from 11-04 most ds runs are 6-7-turn empty cycles. It is NOT caused by the 11-01 sonnet switch: opus ds runs on 11-08/11-11/11-13/11-14 show the same 48-53k floor, and research had 62k 6-turn empty cycles under opus on 10-28. Verdict: RULED OUT - no startup-token regression in 11-02..11-09; the per-run median rise is the empty/working mix, which O2 back-off now addresses.

## Original finding (as filed; Findings 2 and 4 are superseded by the correction above)


Data: ops/loop/control/headless_usage.jsonl (4098 rows). Fields: input_tokens, cache_creation, cache_read, num_turns. No first-turn field exists; cache_creation is the proxy.
No usage rows exist for 2026-11-02 and 11-03 (only drive rows 11-02).

Per-run median cache_creation by day (turns median):
- ds: 10-28..10-31 97k-110k (27-34 turns); 11-04..11-08 52k-58k (6-7 turns); 11-09 142k (57); 11-10 159k (57); 11-11 49k (6); 11-12 131k (54); 11-13/14 53k (6-7)
- research: 10-30/31 131k-135k (41); 11-04..11-07 55k-66k (6-7); 11-08 143k (49); 11-09/10 57k-63k; 11-11 160k (68); 11-12 120k; 11-13 137k; 11-14 166k (60)
- repo (control): 10-28 111k; 11-04..11-14 82k-100k (23-31 turns); no step
- uiux (control): 117k-122k to 11-01; 11-04..11-14 122k-147k; no step

Findings:
1. The 104k / 125k medians are a MIX of two run shapes: empty cycles (6-7 turns, cache_creation 47k-58k for ds, 51k-66k research) and working cycles (50-68 turns, 120k-165k). The floor (startup + empty-cycle cost) is ~50-55k and is FLAT 11-04..11-14 (ds p10 53k on 11-05 and 52k on 11-14). No upward step in the floor.
2. Step date: ds/research floor DROPPED between 11-01 and 11-04 (ds p10 ~90k -> ~54k), coinciding with the sonnet-5-5 switch on 11-01 14:30 (ds 11-04..11-07 all sonnet) and a shift to short empty cycles. It is a drop, not a regression. Inference: the move to opus from 11-08/11-09 raises per-run totals via longer working cycles (57 turns), not via startup size.
3. Startup-loaded artifacts, bytes before -> after in the 11-02..11-09 window:
   - CLAUDE.md 54412 (at 11-01) -> 56651 (11-04) -> 56723 (11-10): +2.3k bytes (about +600 tokens), commits 938b71c9f, 139c55af7, f2f40f47f (docs only). Too small to explain 50k+ swings.
   - tools/rc_facts.py 121999 -> 121999 (11-04) -> 125068 (11-10): script size, not injected output (output size NOT measured).
   - .claude/ (settings, commands) and ops/loop/control/lane_prompts/** are gitignored: no git history; lane prompt files (s134-ds.md 49653 B, s133-research.md 42415 B, last mtimes Oct 25-31) show no 11-02..11-09 edit by mtime. Skill files are untracked-by-git so cannot be diffed.
   - fleet_route.py commit 3d7a0bb6a (11-06) is CLI arg/encoding hardening; no flag or prompt-load change seen.
4. Non-commit causes: model switch (opus -> sonnet 11-01, ds/research back to opus 11-08/09) is the visible correlate; usage rows record model per run.

Missing to close: per-turn first-request usage (needs transcript jsonl under ~/.claude/projects for the lane worktrees), the 11-02/11-03 gap, SessionStart rc_facts output bytes, MEMORY.md size history (outside repo).
Why ds/research moved to opus: not found in the repo within this probe (MAIN asks for it; model-change log is a separate bullet).
