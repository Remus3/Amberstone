# DEEP AUDIT CHARTER - RC & DS full-project audit/refactor program

Authored 2026-06-11 from the operator's overnight directive (verbatim intent, restructured).
This is the STANDING charter for the autonomous audit loop. Each cycle: read this file,
read the synopsis for current phase state, execute the next bounded slice, log, hand off.

## Mission

An extremely professional, exacting, complete audit + refactor + optimization + cleanup of
EVERY file in RC and DS (and rc-shell, Share, tools, ops, web, docs - the whole tree), from
three lenses simultaneously: as a programmer (correctness, structure, efficiency, security,
hardening), as a user (UX, latency, clarity), and as an outside reviewer (readability,
documentation, professionalism). Run to COMPLETION across as many sessions as needed.

## Model / harness

- Fable 5, MAX effort (effortLevel xhigh set in .claude/settings.json), 1M context: first
  cycle PROBE the 1M model id (claude-fable-5[1m]) and set it in .claude/settings.json
  "model" ONLY after verifying the session accepts it (a bad id strands the unattended run).
- Adjust claude mode usage as required (caveman stays default; drop to normal only where
  the charter demands readable reporting).

## Authorizations (operator-granted 2026-06-11, standing for this program)

1. FROZEN-FILE edits directly authorized - the CLAUDE.md frozen list is OPEN for this audit.
2. Git HISTORY may be modified; GitHub + Share gist may be modified; everything stays
   recoverable via GitHub version history - that is the explicit safety net.
3. .md REWRITES expressly allowed (full-context rewrites are safe; make every .md human
   readable + properly commented; no-history-rewrite rule SUSPENDED for this program).
4. Relocate files (largest to smallest), alter folder structure, archive/remove redundant
   files, remove scrap files.
5. PRUNE ENTIRELY: (a) all Vanguard BSOD / CV / screenshot-capture warnings and caveats -
   no more reasons to warn/remember these; (b) ALL 2-PC / gamepc references and variants -
   gamepc is retired, everything is 1-PC on Legion. Sweep code, docs, memories, comments.
6. BOM/encoding retro-sweep the ENTIRE project (the deferred smart-quote sweep folds in).
7. No spend limit. Many session loops expected (not 1, not 10). Do not stop for frivolous
   things. Do not gate on operator approval unless VERY explicitly dangerous. Questions of
   scope/direction go to GEMINI (cli back-and-forth), never wait on the operator; take the
   best-recommended, future-proof answer for the design of RC & DS.

## Program tracks (phases; synopsis carries live todo/done state)

- P0 BASELINE: full-tree inventory (file count/sizes/runtime-use vs repo bloat), test+CI
  baseline, /metrics + health probes, screenshot reference. Build the audit work-map.
- P1 STRUCTURE: folder-structure redesign where warranted; relocations; dead/scrap/redundant
  file archival or deletion; file-size + runtime-use evaluation; claude-context optimization
  (CLAUDE.md/docs bloat reduction).
- P2 CODE AUDIT: every .py/.js/.css/.ps1/.md - correctness, security hardening, efficiency,
  integrity tests; simplify processes that cause tool-usage/CI friction (BOM encoding class,
  PS5.1 quirks, stale-pipe class). Verifiable findings + concrete sourcing ONLY - never rely
  on past memory or assumptions; re-probe everything live.
- P3 PRUNE SWEEPS: vanguard/CV/capture caveats out; 2-PC/gamepc out; BOM/smart-quote/encoding
  retro-sweep; em-dash drift check.
- P4 HAIKU/SONNET TO ZERO: COMPLETE the program - retire every live Haiku call site to
  precomputed/deterministic paths (the HZ shadow tables + agreement gate are armed on all 3
  modes); flip after validation; vision Sonnet escalation path included in scope this time.
- P5 ELECTRON OVERLAY COMPLETE: full implementation to the point the web dashboard is NO
  LONGER REQUIRED in client or in game (packaging, release, in-match overlay validation).
- P6 ROADMAP/BACKLOG + NEW LIFTS: drain remaining viable items; research new lifts; implement.
- P7 UI/UX END-TO-END: League client is OPEN on the main screen + Chrome web dashboard on
  screen 2. Use MCP clicks (Windows-MCP / computer-use / chrome-devtools), research+install
  what is needed; create + use the PRACTICE TOOL in client for in-match data review; full
  UI & UX audit agents end to end.
- P8 DOCS: every .md rewritten human-readable, current, properly commented; memory files
  reconciled to post-audit reality.

## Loop mechanics (variant of gemini-headless-upgrade - NOT the stock skill)

- Driver: ops/loop (controller + AHK) clears this Claude window each cycle and feeds the
  directive; config.json directive_suffix points HERE. Gemini = director/auditor/consultant
  for scope+direction questions; avoid stale handoffs (timestamp + sha-stamp every handoff;
  a handoff older than the current HEAD's committed state is STALE - re-derive, don't trust).
- Multi-agent fanout per cycle: orchestrator-merge pattern (disjoint worktree slices,
  verifier gate + tools/truth_gate.py PROCEED before merge/commit). Validated fanout only.
- Scheduled tasks + AHK are authorized tools to keep the back-and-forth autonomous (file/
  function updates, client/app usage).
- Per cycle: commit + push + CI green + /done + /clear within viable context bounds.
- LIVE SYNOPSIS on the Desktop (C:/Users/Administrator/Desktop/RC_DEEP_AUDIT_SYNOPSIS.md,
  atomic writes): stages/phases todo/done, gemini<->claude handoff log (append, terse), no
  repeated findings. This is the operator's morning review artifact - keep it current.
- Stale/fail states (claude OR gemini): reorient and continue unless genuinely done. Never
  end the program on a transient failure.

## Hard floors that SURVIVE this charter (everything else above overrides defaults)

- ASCII-only authored content (no em/en dashes, no smart quotes) stays.
- Atomic writes stay. py_compile-before-restart stays. taskkill-not-Stop-Process stays.
- TDD + truth-gate verification discipline stays (gate every multi-slice round).
- Do not break the live product for the operator's play sessions; restart + verify health
  after runtime changes.
