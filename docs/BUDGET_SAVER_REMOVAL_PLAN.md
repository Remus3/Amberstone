# budget_saver Removal Plan (operator directive 2026-07-09)

Grounded next-session checklist to REMOVE the `budget_saver` subsystem entirely.

**Why:** operator's ruling - the lean / cheap 8B-local-model fallback (LEDGER 810: the LEAN_CLAUDE.md
auto-swap shims + a LiteLLM/Ollama proxy + the `RC-BudgetSaverProxy` / `RC-BudgetSaverWatchdog`
scheduled tasks) produced low-quality autonomous work that kept getting redone properly by the full
model, so it was net-negative. Do NOT re-pitch a budget-saver / lean-profile / 8B-local fallback.
Memory: `project_budget_saver_removal`.

**Safety baseline (verified 2026-07-09 by the footprint map):** the working-tree `CLAUDE.md` is the FULL
canonical 223-line version - NO lean swap is currently in effect, so removal is safe. `budget_saver` has
ZERO production/loop/CLAUDE.md/ROADMAP coupling - it is fully self-contained under `ops/budget_saver/`
plus OS-level state (2 tasks + some Machine env vars + live proxy/ollama processes). Nothing outside the
dir imports or launches it.

## Operator-decision points (settle BEFORE executing)

1. **Two vault SPECS depend on budget-saver as their runtime vehicle** (spec-only, nothing executes today):
   `docs/specs/RC_KNOWLEDGE_VAULT_SPEC.md` (routes INGEST/LINT via `budget-saver-smart`, QUERY via the 8B
   `budget-saver`) and `docs/specs/CANONICAL_LLM_VAULT_SPEC.md` (same). Also the memory
   `project_llm_wiki_and_wallpaper_gen_plans` ("execute later via budget-saver"). Removing budget_saver
   orphans their launch mechanism. DECIDE: archive both specs, rewrite them to use the full model, or drop
   the vault program. (Recommend: archive to `docs/_archive/` until the vault program is re-scoped.)
2. **`env.local.ps1` holds live API keys** (`LITELLM_MASTER_KEY`, `DEEPSEEK_API_KEY`, `NVIDIA_NIM_API_KEY`).
   Shred the file on delete AND consider rotating those 3 keys (they sat on disk). DECIDE: rotate now or accept.

## Teardown order (execute)

1. **Stop live state.** Unregister the 2 tasks + stop the proxy/ollama:
   - `Unregister-ScheduledTask -TaskName RC-BudgetSaverProxy,RC-BudgetSaverWatchdog -Confirm:$false`
     (both are live: Proxy=Running, Watchdog=Ready; sole install point is `ops/budget_saver/setup.ps1:51-81`
     - watchdog block :51-68, proxy block :70-81 - no registration exists anywhere else).
   - `taskkill /F` the LiteLLM proxy on `127.0.0.1:4000` (started by `start-proxy.ps1`) + any Ollama on
     `127.0.0.1:11434`. Never `Stop-Process` (hangs the MCP pipe per CLAUDE.md).
2. **Remove tracked files.** `git rm -r -f ops/budget_saver/` (34 tracked files; `-f` is REQUIRED because
   `lean-settings.json` has an uncommitted working-tree mod - the held-back bypassPermissions block from
   LEDGER 822 - which is correctly discarded with the delete, nothing to preserve).
3. **Delete gitignored / untracked from disk** (not in git): `rm -rf ops/budget_saver/` clears the large
   `.venv/` (isolated LiteLLM Python 3.12 env - biggest disk item), `.claude/`, `__pycache__/`, `state.json`,
   `usage_signal.json`, `qualification_scorecard.json`, `watchdog.log`, `budget_saver_armed.flag`, and
   **SHRED `env.local.ps1`** (secrets - see decision 2). Also `rm "C:/Riot Commander/CLAUDE.md.full"` (a 25KB
   gitignored swap-backup leftover, byte-identical to the committed `CLAUDE.md`).
4. **Clean `.gitignore`.** Remove root `.gitignore:256-258` (the 2-line `# Budget-saver context-swap backup`
   comment + the `/CLAUDE.md.full` entry - the backup can no longer be created once the shims are gone).
5. **Docs.** Delete or archive `docs/specs/BUDGET_SAVER_SPEC.md` + `docs/specs/BUDGET_SAVER_PLAN.md`
   (dedicated budget-saver design/impl docs); resolve the 2 vault specs per decision 1. `docs/OPERATIONS.md`
   needs NOTHING stripped (it has no RC-BudgetSaver task rows - the planned pointer was never landed).
   KEEP append-only history intact (LEDGER items 808/810/821/822/823 + `docs/history_notes.md`) - `LEDGER.md`
   mandates no history rewrite; the removal is a NEW ledger entry, not an edit of the ship records.
6. **Machine env vars (optional clean-up).** `setup.ps1:38-41` set `OLLAMA_FLASH_ATTENTION` /
   `OLLAMA_KV_CACHE_TYPE` / `OLLAMA_CONTEXT_LENGTH` / `OLLAMA_HOST`; `watchdog.py` sets `RC_BUDGET_SAVER`
   (nothing reads it). Clear them for a clean box.
7. **Trim transient notes.** `WAKEUP_NOTES.md` budget-saver lines get pruned on the next wrap (not
   load-bearing).

## What will NOT break (verified)

- No production import/launch coupling; no loop/cron reader (`watchdog.py`'s "the loop controller reads on
  next start" was aspirational - never wired).
- Removing `ops/budget_saver/tests/` is a NET CLEANUP: those 10 tests import `litellm`/`yaml` absent from
  RC's main Python 3.14 env, so they are a latent collection-error surface in the schedule-only
  `nightly-full-suite` (part of the pre-existing red backdrop). Deleting the dir removes it.
- Cross-repo (informational, out of scope): `budget-saver-unified.ps1:38-47` offers a Sibling-A launch
  option pointing at a SEPARATE repo's own `C:\Sibling-A\ops\budget_saver` - unaffected by removing THIS
  repo's dir.

## Acceptance

`git status` clean of `ops/budget_saver/`; `Get-ScheduledTask RC-BudgetSaver*` returns nothing; no proxy on
`:4000`; `ruff` + the authored-source hygiene tests green; a full `pytest` no longer errors collecting
`ops/budget_saver/tests/`; a new LEDGER entry records the removal. `CLAUDE.md` unchanged (full canonical).
