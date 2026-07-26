# Section-J Dispatch

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
