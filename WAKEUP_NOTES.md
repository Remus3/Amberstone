# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-28p - RM-97 probed: the gap is real, "scores zero" was two-thirds wrong.

**Headless loop cycle 32 (R225). Tier-1, ENGINE-IMPACT NONE.** `99af7bab`.
A characterization pin over a filed-but-never-probed DS gap.

**The spec held; two of its three clauses did not.** RM-97 says persistent pet
damage is structurally unmodelled and that `ds.ability` "prices them at exactly
zero". The first half is true. The second is true of the DAMAGE NUMERATOR only -
`objdamage.py:79-83` credits SUMMON_DPS at 0.55 and `zonecontrol.py:73-77`
credits SUMMON at 0.60, and both enumerate the identical champion list by name.
The class is already credited on two non-damage axes.

**And the class is not uniform.** 7 pet-bearing forms carry ZERO
`attribute_kind == "damage"` blocks (Zyra P + W, Heimerdinger Q **both** turret
forms - the brief assumed one, Ivern R, Yorick P, Yorick R). But 3 summon forms
carry exactly one damage block and ARE credited: Malzahar W Void Swarm, Annie R
Summon: Tibbers (the summon burst only), Elise W Volatile Spiderling (a one-shot
explosion). **So the honest sentence is "no PERSISTENT-ENTITY uptime model", not
"no summon ever scores"** - the second reads as an unbuilt feature, the first
names the missing schema and explains why no scorer tweak reaches it.

**The near-miss is the reusable half.** Yorick R's ONLY block is a mist-walker
COUNT at `damage_blocks[0]`, and Malzahar W's index-0 block is a DURATION in
seconds. Both are harmless for exactly one reason: `_select_blocks`
(`ability_dps.py:459`) filters on `attribute_kind` BEFORE taking index 0. Drop
that filter and a unit count and a duration score as magic damage.

**Grep was 472 instances and 470 of them were prose.** The `summon` half is
almost all SUMMONER-SPELL traffic; every pet-name hit is a docstring, comment or
`source_quote`. The only two scoring sites in the entire 472 are the two
registries above. A big grep count is not a big surface.

**Pinned, not fixed:** `agents/daemon_slayer/tests/test_pet_summon_damage_uncredited_rm97.py`,
12 tests / 27 subtests. Zyra L11/SR/30/30/no items: W dps 0.0 at rank 2
(unlocked - the zero is the filter, not a lock), Q 9.147609147609147, E
1.2968849332485697, R 1.0865999671969822; the P row is ABSENT not zero
(`SPELL_KEYS` excludes it), so the pin asserts what was observed rather than
what the plan expected. RM-97 stays SPEC-ONLY / OPEN; a fix is still a schema
lift, deliberately not built.

**Process lesson, and it cost the first full-suite run:** a test-only,
ENGINE-IMPACT-NONE cycle STILL owes the DS Share sync. A new file under
`agents/daemon_slayer/tests/` is a mirrored DS source, so
`test_ds_share_sync_determinism.py` went red with `DRIFT (missing from
Share/src)`. **The mirror obligation attaches to the PATH, not to whether any
engine math moved.**

**Gates:** 24082 passed / 106 skipped / 7070 subtests in 143.03s (`-n 8`, repo
root). Verifier CONFIRM, adversarial - it mutation-checked two assertions for
tautology and both survived.

---

# 2026-07-28o - RM-126 fixed, and the obvious fix would have been wrong.

**Headless loop cycle 31 (R224). Tier-1, ENGINE-IMPACT NONE.** `65beb575`. The
pointer-listener leak R223 filed but did not fix.

**The bug was exactly as filed.** `_placeAll` re-runs `_makeHandle` every repaint;
its only guard asked "does a `.ovx-handle` child exist"; every renderer that
rebuilds its mount destroys that child; so both el-level binds re-ran on the same
surviving element, forever.

**The ROADMAP row prescribed "attach once per element" and that alone is a trap.**
`_installDrag` returns a `begin` closure that gets bound to the `.ovx-handle`
child, and that child is LEGITIMATELY recreated each repaint. Early-return before
the binds but hand back a FRESH `begin` and you get code that passes any "bound
exactly once" assertion and is broken - the surviving el-level listeners close
over the FIRST call's drag state while the new handle drives a second, unobserved
copy. Leak traded for silent desync. Shipped fix stores `begin` on the element and
returns the STORED one, plus a separate `el.dataset.ovxBodyDrag` latch for the body
`pointerdown`, placed AFTER the handle bind so the fresh handle keeps rebinding.

**The named UI harness did not exist, so I measured instead of skipping.** The
directive routed validation through "the ui_recon Playwright harness + :8810
static preview" - neither is on disk. But node v24.15.0 is installed,
`overlay_layout.js` has ZERO imports and exports `_makeHandle` through
`_internals`, so it loads under a stubbed DOM. Three passes with the handle child
dropped between them: **12 el-level binds on baseline `08c8aade`, 4 on the fixed
tree**, handle rebinding 3x on both sides. The leak measured and the fix measured.
Worth remembering that a "no harness" directive step is often a 20-line node
script away from a real answer.

**The reusable lesson from the enumeration.** 19 `addEventListener` sites, 4
defective, 15 clean, 0 new. `_ensureLauncher` is re-entered by the same observer
and by `resetOverlayLayout` yet never leaked, because it early-returns on
`querySelector("#w-launcher")` - it asks whether the HOST exists, not whether a
CHILD of the host exists. **The defect class is not "unguarded listener attach",
it is "guarded on a child's existence when the listener's host is the parent".**
That is the grep for next time.

**Gates:** DS 10100 / 5701 subtests. RC 13968 / 106 skipped / 1342 subtests. First
RC run was 1 failed - the `_LIVE_HALF_DIGEST` pin firing by design on a LIVE web
byte; re-stamped after the two-tree diff showed 1 of 165 web/ sources changed, then
re-run clean. **OWED:** overlay visual PNG (zero markup/CSS bytes changed), same
standing debt as R223.

---

# 2026-07-28n - The commit gate's ruff half was dead on the channel that matters, for three weeks.

**Operator session (not a loop cycle). Tier-1, ENGINE-IMPACT NONE.** `15d07d3c` + `569dd364`. The filed question from `425fbb75`: why did `tools/precommit_gate.py` not block the net-new ruff UP031 that `afcbcf79` put in its OWN source.

**The filed hypothesis was wrong and cheap to refute.** It was not "local ruff differs from the runner's" - local ruff 0.15.12 flags that exact line under the project `ruff.toml`, measured. The gate never asked it. It shelled to `sys.executable -m ruff`, and `.githooks/pre-commit` launches the gate through the `py` launcher, which on Legion resolves to the dep-less pythoncore runtime with NO ruff. rc=1, empty stdout, `findings = []`, pass. **Fail-open AND fail-silent.**

**The gate runs on two channels with two different interpreters and the invocation was hardcoded for one at a time.** PreToolUse gets Python314 pythonw (owns ruff); the git hook gets the launcher. `ceb2f584` (2026-07-07) flipped launcher -> `sys.executable` to fix the first and silently broke the second - the AUTHORITATIVE one per CLAUDE.md, and the only one a headless bypass run gets. The stale comment above the call still described pre-`ceb2f584` behaviour, which is why it read as correct on every review since.

**Fix:** `_ruff_candidates` / `_resolve_ruff` probe `--version` and take the first that answers. No ruff anywhere still exits 0 (blocking a fresh clone would wedge the loop; CI is the backstop) but now WRITES THE WARNING. Phase-1 repro went EXIT=0 -> EXIT=2.

**Then CI went red on my fix, and both failures were mine and both were right.** `test_skip_condition_hygiene.py` classified my `requires_ruff` mark UNRESOLVED because it gated on a subprocess probe the resolver cannot see - re-gated on `find_spec` + `shutil.which`. `test_bare_py_ban.py` caught the launcher spelled before a script path in prose. **That second one paid for itself:** the launcher was in my candidate list as a fallback, and the launcher is precisely the dep-less runtime that caused the bug. Dropped; the Legion fallback is now the canonical absolute interpreter.

**For next time:** neither guard is reachable from the /done section-0 gate (ruff + touched module + 3 hygiene suites). They are repo-wide tracked-surface guards in `tests/` that only the full run reaches. A tools/ or tests/ change with prose about interpreters should run `tests/test_bare_py_ban.py tests/test_skip_condition_hygiene.py` locally before pushing.

**Do NOT redo:** the diagnosis is closed - do not re-open "local ruff differs from the runner". `tools/edit_lint_check.py` carries the same `sys.executable` assumption and was deliberately LEFT: it is PostToolUse-only under Python314 (correct there) and advisory, not blocking.

**Live at wrap:** the gemini loop (pid 9380, run `eadf15e3`) is mid-cycle on R223 - its `docs/ORCHESTRATION_PLAN.md` row is unstaged and says `(fill sha)`. I pushed its two R223 commits along with mine; leave the plan row to it.
