# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

---

# 2026-06-17 - verify + fix Antigravity repo-audit batch; ratify D5 frozen extraction (operator-directed)

Antigravity implemented the `repo-audit.md` D-items; operator asked to verify + fix + flip gated items. Commits `a13d7496` (38 files) + `d16200b3` (ci.yml, separate workflow-scope push). Both pushed, CI green, RC redeployed pid 9012.

- **CI-breaker FIXED:** Antigravity put `BLE001` in `ruff.toml` select with NO baseline -> `ruff check .` 1137 errors -> CI red. Reverted that line (ratchet deferred to a `--add-noqa` pass).
- **Hot-path FIXED:** D4 narrowed `snapshot_normalizer.py` catches to a 5-type tuple (dropped IndexError/ZeroDivisionError on live data). Back to `except Exception as exc:`, kept the new `_log.debug`.
- **D9 completed:** token header was on 2/4 guarded endpoints; added to dev.js (/api/loop-control) + screen_read.js (/api/command).
- **D12 reverted:** print->logger on interactive result CLIs (daemon_slayer/cli.py, config_validator.py, adaptation_hint_cli.py, aftergame_summary.py) hid stdout; restored result->print, kept status->logger.
- **D5 RATIFIED:** frozen `app/_game_lifecycle.py` map extracted to `core/coach_registry.py`. Verified-good as-shipped: D2 D3 D6 D8 D10 D13 D14. Deleted 7 scratch `scripts/fix_*/patch_*.py`; kept install_hooks.py.

NEXT (OPEN, do NOT re-pitch the reverted changes as bugs): **D1** Share de-dup NOT done (only a local pre-commit auto-sync hook; it re-stamps `Share/MANIFEST.md` every commit). **D4 ruff ratchet** + **D9 200/401 test** + **D11 assert->raise** deferred. Precompute scripts + vision_token.py kept print->logger (status, by choice). Memory [[feedback_verify_antigravity_audit_batch]].

---

# 2026-06-17 - third-party-style repo audit + adapted auditor prompt (operator-directed)

Operator pasted an external "brutally honest enterprise auditor" prompt (meant to feed Google Antigravity) and asked to vet+adapt it, then run it grounded. Commit `04e1a391` (pushed). Docs only, ZERO code/engine/frozen touch.

- **`repo-audit-prompt.md`** - the external prompt rewritten to RC reality: right-yardstick (solo 1-PC tool, not enterprise SaaS), on-disk grounding mandate, anti-drama, pillar-5 rewritten as invariants-as-guardrails (frozen/atomic/ASCII/ENGINE-bump/Share-mirror) so an autonomous refactor agent cannot break RC. 6-point CHANGELOG of what differed from the original.
- **`repo-audit.md`** - deep/strict audit. Dual rating B+ (solo bar) / B- (strict bar). 14 grounded deficiencies D1-D14; biggest real ones: D9 unauth /api/command + /api/input on HOST="::" (tailnet-reachable); D10 floating unpinned deps / no lockfile; D2 CI runs ~5% of suite; D3 no mypy; D4 1137 broad-except; D11 405 runtime asserts (stripped under -O). Footgun-clean (eval/exec/pickle/mutable-defaults all 0). Per-item Antigravity exec specs (PRE/EDIT/VERIFY/ROLLBACK + frozen/approval gates).
- **Ground truth re-derived from git** (not subagent claims): 1668 tracked .py, 14,364 `def test_` non-Share (CLAUDE.md "1300+" is a ~10x undercount), locks 134/96, type-hint ~78% return-annotated. Appendix A lists 5 downgraded subagent figures.

GATE: hygiene trio (smart-quote/mojibake/u2500) 12 passed. No .py authored -> ruff/py_compile/DS-Share n/a.

NEXT: artifacts exist to feed Antigravity; if pursued, D2+D10+D9+D3 are the cheap strict-bar wins. The 14 D-items are candidate work, NOT committed scope. Do NOT re-run the generic enterprise prompt literally - use the adapted version in repo-audit-prompt.md. CLAUDE.md "1300+ tests" is a confirmed ~10x undercount if a doc-sync ever wants it (left as-is this session).

---

# 2026-06-17 - grounded /repo-insights report generator (operator-directed)

Operator ran `/insights`, then asked to validate its 3 "On the Horizon" suggestions and build a grounded repo-insights variant that reads the codebase instead of transcripts. Commit `c0d7876b` (pushed).

- **All 3 /insights suggestions = INVALID (already shipped) -> adjudicated docs-only, ZERO code.** (1) Anti-hallucination loop guard = `.claude/agents/verifier.md` + `tools/truth_gate.py` + ORCHESTRATION_PLAN "verifier-gate each slice". (2) Stale-premise sweeper = the director's per-cycle verify-before-redo + DRAINED queue (68 DONE / 0 OPEN). (3) Live-render sentinel = `tests/test_active_match_live_fixes.py` (null-items fixture) + `test_active_match_view.py` (coach.action + stale-map). Root cause: `/insights` reads transcripts, not the repo, so it re-pitches the very fixes that resolved its flagged friction.
- **NEW `tools/repo_insights.py`:** grounded variant - git window + LEDGER + ORCHESTRATION_PLAN + ROADMAP + ENGINE_VERSION + DS patch -> the Claude-Code-Insights HTML layout + sidecar `.json`. Horizon = the REAL EXCLUDED gated rows, not invented suggestions. Local `/repo-insights` command (`--days N`; `.claude/` gitignored so command is local-only like all RC commands). +8 hermetic smoke tests.
- First report: `~/.claude/usage-data/repo-insights-2026-06-17.html` (1475 commits / 163 ledger items / 68 DONE 0 OPEN, 30d).

GATE: ruff + ASCII + hygiene trio (smart-quote/mojibake/u2500) + 8 smoke = 20 passed. Tier-1 tooling, no engine/DS/Share/frozen/RC-restart touch.

NEXT: mold the look later via `CSS`/`PALETTE` + `# SECTION:` blocks in `repo_insights.py`. Do NOT rebuild - all 3 /insights horizon items are confirmed already-shipped (memory [[reference_repo_insights_tool]]).
