# Auto-Ops Verb Expansion Gate Probe

Slice F probe of ROADMAP.md L124: "Auto-ops verb expansion - once Phase 3
auto-action success rate clears 95%, add: `tail .* log`, `restart agent .*`,
`verify .*` to Legion `auto_ops_verbs`."

## Gate verdict: DEFERRED

Sample size AND frozen-file constraint both block this run.

## Phase 3 auto-action success rate

Source: `ops/runtime/bridge_action_history.db` table `outcomes`
(rowid, task_id, ts, source, lane, pattern_matched, status, cost_usd,
latency_s, summary, prompt, body_keys, error_brief).

- N rows: 2
- Status: ok=2, err=0
- Lane: auto-read=2, auto-ops=0
- Rate: 2 / (2 + 0) = 100% (degenerate at N=2)
- Time range: 2026-05-03T08:03:01 to 2026-05-03T08:03:18 (~17s)
- Sources: both `legion-self-test` (Phase 4 cache test, NOT real bridge task)
- Since 2026-05-03: 0 (22 days idle)

Corroborating (all consistent with zero-cadence):
- `bridge_watcher_health.json`: auto_actions_24h=0, auto_*_since_boot=0
- `bridge_watcher_state.json`: auto_actions_24h=0
- `bridge_log.jsonl`: 1011 lines, 0 kind=action_outcome

## Gate threshold

95% success over N=50+. Current N=2, gate NOT cleared.

## ETA estimate

At 2 outcomes / 22 days = 0.091/day, N=50 takes ~550 days. Indeterminate.
Gate clears only after operator enables auto-action lanes for live use
(ROADMAP L125 has same chicken-and-egg gating).

## auto_ops_verbs canonical location

File: `tools/bridge_watcher_config.json` (FROZEN per CLAUDE.md hard-rule
L53). Legion auto_ops_verbs at L10-13 (4 verbs):
- `restart RC`
- `regen cert`
- `pull from origin/main`
- `verify .* health`

Gamepc L69-72 (4 verbs). Atx L98-101 (5 verbs).

## Frozen-file constraint

Even with gate cleared, operator MUST grant frozen-file write
authorization for `tools/bridge_watcher_config.json` before this slice
can ship. The watcher's own config is in its own `escalate_always` list.

## Ready-to-ship pseudocode

When BOTH (gate clears, frozen-grant given), apply surgical edit to
`tools/bridge_watcher_config.json` L10-13 legion auto_ops_verbs array:

```json
"auto_ops_verbs": [
  "restart RC", "regen cert", "pull from origin/main",
  "verify .* health",
  "tail .* log",
  "restart agent .*",
  "verify .*"
]
```

Semantic flags:

1. `tail .* log` ALREADY in legion auto_read_patterns (L6). Moving to
   auto_ops ELEVATES tier (read-only -> Bash-armed). The auto-read
   Read,Grep,Glob set already covers tail-via-Read. Only flip if true
   Bash `Get-Content -Tail` is needed; alternative is to skip this verb
   and just add the other 2.
2. `verify .*` is broader than existing `verify .* health`. Recommend
   narrower `verify .* (health|state|cert|build)` to bound surface.
3. `restart agent .*` already in gamepc auto_ops (L70). On legion,
   agents = supervisor + bridge-daemon + bridge-watcher + vision-server.
   Need `bash_restricted` (L15-27) extended with `schtasks /Run /TN
   RC-* *` or per-agent restart commands; current bash_restricted is
   rooted in specific RC commands not a generic restart-agent verb.

### Drift-guard test (new file)

`tests/test_auto_ops_verbs_expanded.py`:

```python
"""Pin post-expansion legion auto_ops_verbs allowlist."""
import json, pathlib

def test_legion_auto_ops_verbs_post_expansion():
    cfg = json.loads(pathlib.Path(
        "tools/bridge_watcher_config.json").read_text(encoding="utf-8"))
    verbs = cfg["legion"]["auto_ops_verbs"]
    for v in ["restart RC", "regen cert", "pull from origin/main",
              "verify .* health", "tail .* log",
              "restart agent .*", "verify .*"]:
        assert v in verbs
    assert len(verbs) == 7
```

### Safety re-check before flip

1. `bash_restricted` (L15-27) bans `rm -rf`, force-push, hard-reset
2. `escalate_always` (L31-62) covers every frozen file
3. Run `bridge_watcher_classify.py::_test()` against expanded config

## Carries forward

- Gate NOT cleared at item 188 ship time
- `tools/bridge_watcher_config.json` STILL frozen
- ROADMAP L124 STILL operator-gated on rate-AND-grant
- Re-probe cadence: after operator enables auto-action lanes for >=1
  week of live use AND DB shows N=50+ outcomes
