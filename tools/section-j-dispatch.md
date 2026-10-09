# Section-J Dispatch

> **DISPATCH (FLEET-KIT v10 banner; MAIN 2026-10-08 0839 ORDER step 4).** In an interactive main session this skill is never run inline.
> 1. The main session dispatches the WHOLE skill to ONE sub-agent (Agent tool): this file plus the invocation arguments. It relays only that agent's final output - the line(s) this skill names as its chat output, nothing when it names none - with no narration around it.
> 2. No quick-read or trivial-edit exception in the main thread; this supersedes any "may inline" line in this file. Its Bash / PowerShell / Read / Edit / Write / Grep / Glob / NotebookEdit calls meet the kit PreToolUse hook `ops/fleet_kit/fleet_subagent_first.py` (gitignored mode file `ops/loop/control/subagent_first.mode`: log first, then deny).
> 3. The dispatched sub-agent, and a headless run (the kit's `spawn()` sets `FLEET_SUBAGENT_FIRST=off`), execute this skill directly and never re-dispatch the whole of it.

> **RACE GUARDS (FLEET-KIT v12, FLEET-COMMON item 16; MAIN 2026-10-08 2031 ORDER step 5).** Enforced by the kit hook `ops/fleet_kit/fleet_claims.py` (PreToolUse + SubagentStop in the project settings), not by this text.
> 1. Every `git commit` / `git push` runs through the tree's git lock: `python ops/fleet_kit/fleet_gitlock.py run --owner <id> -- git commit -F <tmpfile>` (same shape for `git push ...`). Python code uses `fleet_gitlock.git_lock(dir, owner)`. A bare commit or push is denied.
> 2. A WHOLE suite (pytest naming no test file) runs through the machine-wide gate: `python ops/fleet_kit/fleet_suite_gate.py run --owner <id> -- <suite cmd>`. A slice that names its test files needs no gate.
> 3. `<id>` is your own claims owner id, `<session_id>.<agent_id>` (`.main` in a main thread); a deny reason names it. The hook also denies an edit, a redirect or a `git add` of a file another live agent holds - leave that file to its agent.

Read `docs/OVERLAY_BUILD_MASTER_PLAN.md` Section J tracker, identify OPEN work
packages with satisfied dependencies, and dispatch them to parallel worktree
subagents via the Workflow tool. One coordinated dispatch replaces multiple
sequential sessions.

## Trigger

- "dispatch section J"
- "section-j-dispatch"
- "fan out the open WPs"

## Procedure

### 1. Read the tracker

Read `docs/OVERLAY_BUILD_MASTER_PLAN.md` lines ~790-830 (Section J table).
Parse the markdown table: extract WP id, Wave, Deps, Tier, Status for each row.

### 2. Identify dispatchable work packages

A WP is dispatchable when:
- Status is `OPEN` (or `WIP` from last cycle - check git log)
- All dependencies are `DONE` (check the Deps column against Status column)
- Not `GATED` or `DEFER`

### 3. Assess parallelism

Group dispatchable WPs by Tier:
- T0: trivial/doc sweep (safe to parallelize freely)
- T1: feature work (can fan out if touching different files)
- T2: infrastructure (serialize or solo agent)

For T0 and T1 WPs that touch disjoint file sets, they are parallel-safe.

### 4. Build the workflow script

Craft a Workflow script that:
- Uses `pipeline()` for T1 work (overlap I/O with compute)
- Uses `parallel()` only when a barrier is genuinely needed
- Each agent gets a `schema` for structured output (summary + commit SHA)
- Each agent works in its own worktree (`isolation: "worktree"`)
- Agents read CLAUDE.md + the relevant section of the master plan for context

```javascript
export const meta = {
  name: 'section-j-dispatch',
  description: 'Fan out OPEN Section J WPs to parallel worktree agents',
  phases: [
    { title: 'Dispatch', detail: 'One agent per dispatchable WP' },
    { title: 'Verify', detail: 'Verify each WP result' },
  ],
}

phase('Dispatch')
const wps = [
  // { id: 'E5', prompt: '...', tier: 'T0', files: ['ARCHITECTURE.md', 'ROADMAP.md'] },
  // Populated from tracker parse.
]

const results = await pipeline(
  wps,
  (wp) => agent(wp.prompt, {
    label: `wp-${wp.id}`,
    phase: 'Dispatch',
    schema: {
      type: 'object',
      properties: {
        ok: { type: 'boolean' },
        commit_sha: { type: 'string' },
        summary: { type: 'string' },
        files_changed: { items: { type: 'string' } },
      },
      required: ['ok', 'summary'],
    },
    isolation: 'worktree',
  }),
)

phase('Verify')
for (const r of results.filter(Boolean)) {
  if (!r.ok) log(`WP failed: ${r.summary}`)
  else log(`WP ok: ${r.commit_sha} - ${r.summary}`)
}

// Update Section J tracker rows from OPEN -> DONE with commit SHAs.
return results.filter(Boolean)
```

### 5. Run and report

Execute the workflow. After completion:
- Verify each agent result (CI green, commit exists)
- Update Section J table rows: OPEN -> DONE with commit SHA
- Commit the updated master plan tracker
- Report: which WPs dispatched, which succeeded, which need attention

## Constraints

- **Never** dispatch GATED or DEFER work.
- **Never** dispatch a WP whose deps are not all DONE.
- Worktree agents must NOT modify frozen files (CLAUDE.md hard rule).
- Each agent commits to a feature branch; the orchestrator merges to main.
- If more than 5 WPs are dispatchable, start with the T0/T1 ones (fastest ROI).
- Skip WPs that touch the same file (conflict risk - serialize those).

## Edge cases

- **No OPEN work**: Report "Section J is fully DONE or GATED" and exit.
- **All OPEN have unmet deps**: Report what's blocking each and which dep to resolve first.
- **Tier-2 WP is the only one**: Use a solo agent (not Workflow) - T2 needs focused context.
- **Git is dirty**: Require clean main before dispatching (or verify the dirty files aren't touched by any WP).
