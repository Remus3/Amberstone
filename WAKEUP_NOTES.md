# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-29a - Perseus Vault adopted; 5 new core modules lifted from cleared client plugins.

**Operator session. Tier-1 throughout; NO engine, no ENGINE bump, no DS bounce, no Share.**
`dc2b4e7a` `a454f76b` `543ed57c` `d0c5237f` `9a119161` `5b6bdbf2` `7bb033fd` `df92ffb7`.

**Perseus Vault is LIVE** (`~/.perseus-vault/`, local, no key). 1202 entities, **1202
embedded**. Wired via `.mcp.json` + SessionStart/SessionEnd hooks - all LOCAL and
gitignored, so a fresh clone has NO wiring (same trap as the git hooks). Re-sync with
`python tools/perseus_sync.py`. **mnemoverse and pathmode both REMOVED** (pathmode was
registered at two sites, which is why its tools appeared twice).

**Three traps measured during install - do not rediscover:** `status: healthy` is a LIE
about coverage (a fresh ingest left 91 of 1197 embedded and still reported
`semantic_recall: available` with zero warnings - only `embedded == active` proves it,
which `--verify` asserts); `init` reports encryption while `entities.body_json` stays
PLAINTEXT on disk, so encryption was dropped; `connect --hooks` writes a bash-ism
(`$(basename "$PWD")`) on Windows.

**Five new modules, 158 tests, all green:** `core/lcu_events.py` (WAMP push replacing
poll), `core/sgp_client.py`, `core/meta_crawl.py`, `core/lcu_mastery.py`,
`core/provider_cascade.py`, plus `tools/perseus_recall.py`. All re-implemented from
protocol facts - NOTHING vendored.

**A filed puzzle closed itself:** the 2026-07-05 probe recording
`na-red.lol.sgp.pvp.net` 404 on match-history-query was hitting the COMMON host. SGP
splits match-history from common; NA1 match-history is `usw2-red.pp.sgp.pvp.net`. A test
pins them apart.

**RECALL BEFORE BUILDING - I violated my own new rule and paid for it.** I "discovered"
the ability-haste inertness mechanism by grep; `project_ds_ability_haste_measured_inert`
already had it in more detail, and Perseus returns that memory at RANK 1. That is why
`tools/perseus_recall.py` exists: raw recall is ~13.4k tokens per query, the projection
is ~223 (98.3 pct smaller), because a mandatory step that expensive gets skipped.

**Do NOT redo:** Perseus install/ingest is DONE. mnemoverse + pathmode are GONE (revoke
the PATHMODE_API_KEY operator-side; removing config does not invalidate it). The license
gate + third-party lift rule is in CLAUDE.md. newDodgeTracker was reviewed and NOT built
from - GPL-3 with three credited contributors.

**Next:** the ability-haste class is REOPENED against RM-39/RM-43 (operator decision) -
**run the amplification gating experiment FIRST**; both candidate designs are moot if the
ability path is still unreachable. DDragon moved to 16.15.1 but Meraki/cdragon have NOT,
so a patch refresh now would pull a half-landed patch - wait.

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
