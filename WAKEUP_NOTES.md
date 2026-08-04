# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-30, automatic via `scripts/wakeup_prune.py --keep 3` (relocated the RM-118 EHP-ranker session `2026-07-29f`; newest 3 = headless run 2026-07-30-01 `2026-07-30a` + headless run 2026-07-29-01 `2026-07-29h` + RM-118 hybrid-ranker `2026-07-29g`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-08-04e - RM-118 stranded-seam ledger DRAINED to its declined floor (ENGINE 1.271.0)

LEDGER 1191. Picked the top open row in ROADMAP NOW, exactly as the prior note said.

The ledger held 14. Ten are DECLINED BY DESIGN and stay - the 5 target/caster-state
seams (arc operator-CLOSED s232) and the 5 per-item shield opt-ins (operator-gated
live flip pending). The 4 that were real debt now reach their routes AND
`core/daemon_slayer_client.py` in the same slice: `apply_crit_chance_overrides` ->
`/dps`, `apply_ability_hsp_amp` -> `/hps`, `apply_cast_rate_propensity_prior` +
`assume_ms_utility` -> `/hybrid` and `/rank-bruiser`.

**The row was easier than it looked, and the reason is the durable finding.** Three
of the four carried a decline reason that read as a blocker - "needs a measurement
first", "engine-only by design", "an unmeasured second live flip on the same
auto-attack term". All three were about a DEFAULT FLIP. This slice ships route
EXPOSURE, default-off and byte-identical. The counts were right; the reasons were
answering a question nobody asked. Filed as memory
`feedback_decline_reason_goes_stale_before_the_count`: a row's count gets
re-measured every session, its reason never does.

Both prior durables held and both were exercised. Route ownership came from
`inspect.signature` over the whole package, never from a sibling docstring. The
TRANSPORT question was asked separately from the flag - and here the answer was
"none needed", all four being pure booleans over inputs the owning routes already
parse. That is the opposite of the rune and vamp lanes; the CHECK is what
distinguishes them, not the outcome.

Asymmetries are asserted, not assumed: `/rank-enchanter` must never carry the HSP
ability flag, `/rank` must never carry the crit overrides, `/dps` must never carry
either hybrid seam. Emitting any of those manufactures reachability with no reader.

DEFAULT-OFF proven three ways, the third being the useful one: a full regen of all
six committed build-order tables (3 modes x 2 families, 173 champions) whose only
diff is the version stamp. **Note the trap that cost 151 seconds:** the tracked
tables come from `core/build_order_precompute.py` + `core/build_order_variants.py`
(`--mode all --champions all --static`), NOT from
`tools/daemon_slayer_build_orders_generate.py`, which writes a gitignored path and
leaves `git status` clean while printing success. Memory
`reference_build_order_regen_wrong_generator`.

Ledger drains: `STRANDED_TODAY` 14 -> 10; `_UNREACHABLE_OK` 65 pairs / 16 routes ->
59 / 15, the `/rank-bruiser` row emptying entirely. New
`test_stranded_lane_route_seams_rm118.py`, 25 tests / 56 subtests, with a negative
control per seam. Suites fresh from the REPO ROOT: DS 10366 passed / 6520 subtests,
RC 18225 passed / 108 skipped / 0 failed. Ruff clean. Share mirror re-synced at 520
files with its own outward-voice CHANGELOG + README entry. Live on `:8860` after
`taskkill /F /PID` then `schtasks /Run /TN RC-DaemonSlayer`: `/health` 1.271.0 and
all six (route, seam) pairs answer over HTTP with every ON path moving.

---

# 2026-08-04d - RM-150 CLOSED: narrowing a listener turned out to be a client sweep

LEDGER 1190. Picked the top open row in ROADMAP NOW.

Both LEDGER 1177 leftovers shipped. `:8889` binds `127.0.0.1` via
`vision_server._bind_host()` (`RC_VISION_BIND`, blank treated as unset so an empty
env export cannot re-open the wildcard), and the four `_j(500, {"error": str(e)})`
sites plus the `/monitor` 404's `Path.home()` candidate list fold into one `_err500`
that logs the cause and answers `{"error": "internal error"}`.

**The row's own live-gate trap fired and the answer was NO.** It warned the row
would be live-gated if any ONLOGON agent was pinned to the LAN IP. Three were -
`lcu_agent`, `screen_agent`, `phase_watcher`, all `192.168.8.230:8889` - but that is
a code sweep, not a game. All three repointed to loopback with an env override on
the `liveclient_relay._upload_url` precedent, and the sweep is now an
allowlist-driven test reading `_AGENT_ALLOWED` off disk, because a hand-listed
version missed `phase_watcher` the first time. The generalization is in memory
`reference_wildcard_bind_hides_its_clients`: a wildcard bind HIDES its clients, so
narrowing one is a client sweep before it is a bind change.

Deploy needed the LEDGER 1179 order and it mattered - the live port owner was pid
6764 started 8/3, i.e. still pre-1177 code. `taskkill /F /PID` FIRST, then
`restart_trigger.txt`. Live after: `:8889` on `127.0.0.1` only, LAN IP actively
refused, `/health` `/stats` `/sync/list` 200 as positive controls, traversal still
404, `/monitor` body path-free, `RC-LCUAgent` re-run and posting at `age 0.0s`.
Suite 18225 passed / 108 skipped / 0 failed; 4 mutations all RED.

One honest weakness recorded in the ledger: `test_repointed_agents_expose_an_env_override`
is a source pin and did NOT fire on the agent mutation (the explanatory comment
leaves the env-var name in the file). The LAN-IP sweep is the load-bearing guard.

**Memory consolidation ran second, on operator request (`/consolidate-memory`).**
`MEMORY.md` 20.3 KB / 132 lines -> 17.2 / 116. Nothing deleted. Four STALE FACTS
corrected, each wrong against the repo, not merely verbose: the Perseus memory said
"NOT yet adopted" three lines above its own ADOPTED section (adopted since
2026-07-29, LEDGER 1107); the index said CCR link-ingest was at "Phases 1-6" when
RM-127 is CLOSED with all 7 shipped; it said "remove pathmode once Perseus runs"
when pathmode was removed 2026-07-28; and `user_operator_profile.md` still described
delegating to a Game-PC Claude, retired 2026-05-29. Retired `feedback_wenyan_output_default`
(dialect reverted 2026-06-27, merged into `feedback_caveman_default_fleet`) and
`project_atx_financial` (separate repo, bridge decommissioned 2026-06-24).

The index bulk was FILENAMES, not prose, so rewording could not reach budget -
delegated two domain clusters onto the existing `INDEX_ds.md` pattern:
`INDEX_overlay_ui.md` (30) + `INDEX_riot_api.md` (19). `drift_guard.py` follows
`INDEX_*` one level deep, so those are honored.

**The lesson worth keeping:** the drift guard CAUGHT this pass mid-cleanup. I had
unindexed two FIXED-bug memories to save bytes; the guard breached on exactly those
two. Re-indexed rather than adding an `open_bug_` exemption - adding an exemption to
accommodate your own tidying is the "loosen the check" move the ritual forbids. The
only exempt prefixes are `project_ds_sweep_` and `_`, and that is now stated in the
index footer so the next pass does not retry it.

---

# 2026-08-04c - RM-157 CLOSED: the invoice finally read, and it validated the reconstruction

Commits: `4cc862d0` (reconstruction + re-price), `027d1031` (invoice + BACKLOG filing),
`5adef80f` (doc-budget relocation). LEDGER 1188 + 1189.

Both routes to the billed number were shut at session start and were RE-PROBED, not
inherited: no `user` scope (billing 404), `list_connected_browsers` empty, repo PRIVATE.
Rather than stall, rebuilt the billing FORMULA from `runs/{id}/jobs` - GitHub bills
private Actions per JOB, ceil to the minute, 1x on ubuntu-latest, and the `repo` scope
already reads every input. Mid-session the operator granted `user`, so the invoice
became readable and CONFIRMED the derivation to ~6 percent (derived 2682 billed min for
Aug 1-4 vs the invoice's 2846 month-to-date). That validation is the durable result and
is written into memory as a general technique.

Numbers that settle earlier guesses: rate is **0.006/min** (not the 0.008 list figure I
first estimated with), allotment is **~3000/mo**, and the old
`settings/billing/{actions,shared-storage}` endpoints are now **410 Gone** - only
`users/{u}/settings/billing/usage` works. Actions Linux billed min: Apr 26 / May 1467 /
Jun 3003 / **Jul 6030 (first real bill, NET 18.13 USD)** / Aug 1-4 alone 2846. Doubling
month over month.

Call: **KEEP the per-push full suite.** ~64 USD/mo, and it buys the only pre-merge gate
on a repo with ZERO pull_request runs and a ~11 percent catch rate (4 of the 37 push
checks that completed FAILED). Every cheap narrowing was already taken, so further cuts
cut coverage.

Do NOT redo: RM-157 is CLOSED and its row is relocated to `docs/ROADMAP_HISTORY.md`
(2026-08-04) with a pointer left in ROADMAP. Do not restore the `/done` dispatch. Do not
re-pitch deleting the per-push suite on cost share - cite a catch rate. The push-volume
lever (branch-plus-PR for the headless loop) is FILED in `BACKLOG.md` under Platform /
observability, not open work in ROADMAP.

Next: pick the top open ROADMAP item. Watch the monthly `usage` row rather than the
cadence projection - July's 6030 is the last full-month fact.
