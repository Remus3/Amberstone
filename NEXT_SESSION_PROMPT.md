# Riot Commander - next session: finish RM-115, starting with the decision that blocks it

## CONTEXT (do not re-derive)

- ENGINE **1.251.0**, patch 16.14.1. Tree clean and pushed at `fe8d5947`.
  DS `:8893` scheduled task is **Running** and `/health` reads 1.251.0.
- Suites measured fresh 2026-07-25 AFTER the last edit: DS **9692 passed / 1
  skipped / 4646 subtests**; RC `tests/` **13110 passed / 106 skipped / 460
  subtests**.
- Full writeup: `agents/daemon_slayer/CHANGELOG.md` 1.251.0 + `docs/LEDGER.md`
  1051 + `ROADMAP.md` **RM-115**.
- ROADMAP is at **71378 of 81920 bytes** (10542 headroom).

## THE ONE THING THAT MATTERS THIS SESSION

Last session shipped RM-115's first drain pass - three seams wired through every
gate they were missing, each with a live before/after and a named byte-identical
control - and **re-measured the debt, finding the filed number wrong.**

**Read `ROADMAP.md` RM-115 first; it carries both numbers and why they differ.**
The original "34 stranded" collapses reachability to a NAME, so a seam parsed by
seven routes reads as reached everywhere once ONE client function names it. Per
**(route, seam)** the real figure is **101**. Two guards now exist and they are
NOT interchangeable:

- `test_route_seams_reach_the_client.py` - name-collapsed, 33-entry ledger
- `test_route_seams_reach_the_client_per_route.py` - per (route, seam),
  101-entry ledger

**Do not treat the name-based guard's green as evidence a specific route is
wired.** It stayed green the entire time `/rank-assassin` could not set
`kit_conversion_strength`, because `rank_for` already named it on the carry path.

## 1. START HERE: settle RM-115 priority 4's open question

`hybrid.py` has ZERO occurrences of `kit_conversion_strength`, stranding Olaf /
Pantheon / RekSai / Riven at GATE 1. `rank_items_by_hybrid` (`hybrid.py:969`) is
the only target - `compute_hybrid` has no sort key, so the kwarg is inert there.
Fully specced: ~35 lines for gate 1, ~7 more for gates 2+3.

**It was NOT built because of one unresolved question, and it is a real choice,
not a formality:** what objective string does hybrid pass to `conversion_factor`?

- **Option A (minimal diff):** pass the local `axis` (`hybrid.py:1182`).
  MEASURED INERT for all four named champions - their `off_axis_stat` is 1.00 so
  every shortfall is exactly 0 (verified in-process: three different objective
  strings return identical factors). But it OVER-FIRES for Naafiri and Orianna
  (`off_axis_stat` 0.00) on a scorer whose beta term literally IS EHP. Neither
  is a bruiser, but `/rank-bruiser` accepts any champion.
- **Option B (+6 lines in `kit_conversion.py`):** add a `hybrid_{axis}` off-axis
  set = the intersection of the damage and EHP sets, and pass `f"hybrid_{axis}"`.
  `hybrid_ad = {"FlatMagicDamageMod"}` reproduces Olaf's own registry note
  ("nothing is off-axis for him except AP") verbatim.

**B is the more correct option; A is defensible if you want the smallest diff.**
Pick one, say why, then build it with a live before/after.

Probe recipe already measured: Olaf on `/rank-bruiser`, `level=11`,
`items=["3071","3111"]`, `top=300`, `enemy_ad_share=0.6 / enemy_ap_share=0.4`.
Control **Darius** - a tabled bruiser absent from `_KIT_CONVERSION`, so every
channel factor is exactly 1.0 and he MUST NOT move. Predicted: Olaf BotRK
`"3153"` #1 -> #20, Trinity Force `"3078"` #2 -> #1, Kraken `"6672"` #3 -> #58.
**Do NOT use Stridebreaker as an anchor** - `kit_conversion.py:54-58` states it
is unreachable at any setting, and the simulation confirms #34 -> #34.

Note: adding a `/rank-bruiser` parse will NOT turn the name-based guard red
(`kit_conversion_strength` is already a client keyword via `rank_for`). The
per-route guard is the one that will tell you the truth.

## 2. The largest remaining block, if you want volume instead

`/ehp`, `/hybrid`, `/rank-tank` and `/rank-bruiser` share ONE 18-19 seam
EHP-family block (`apply_item_resist_grants`, `apply_passive_mitigation`,
`apply_rune_*`, `assume_item_*`, ...). Four routes, largely the same names - one
client wiring pass would likely clear most of the 101. **Do NOT do all of them
in one session; each needs its own before/after with a named byte-identical
control.** `/beam` and `/v2/fight-report` have NO client function at all.

## 3. Also ready, fully specced, unbuilt

- **RM-96 Zilean.** Cast rate 0.00424, 15.9x below Soraka. **Trap:** seeding a
  factor off `ability_hps` MAGNITUDE gives a silent null - he is 4.66 vs Janna
  5.06, only 8 pct apart. Only the CAST RATE separates him.
- **`parse_leveling_bases`** (`ds_wiki_staleness_check.py:188-196`) keeps only
  the first label pair per `{{st}}` block; 31 of 90 blocks in a 50-page sample
  carry two or more, dropping 35 Meraki-matching labels. So
  `ability_staleness.json` is a structural undercount and
  `_ability_base_overrides`'s "exactly those six" scope derives from it.
- **B1** shipped code with no regenerated data - `--full-roster` exists but no
  16.14.1 artifact was produced with it.
- **Unfixed and filed:** the client exposes
  `rank_assassin_for(assume_magic_burst=...)`, but `server.py:1971-1973`
  documents that `rank_items_by_burst` deliberately does NOT accept it (only
  `compute_burst_damage` does). The ROUTE is correct; the defect is a client
  parameter that can never take effect. Fix direction is a genuine choice: drop
  the parameter, or lift the engine kwarg. Do not "fix" it by adding a route
  parse - that was the probe's filing and it was wrong.

## DO NOT PICK

- **RM-44 / RM-91 / RM-90-S3** - premise REFUTED, the prerequisite shipped
  1.247.0.
- **RM-48 Azir** - BLOCKED-UNFALSIFIABLE.
- **A-32 kit-pen** - 3 of 4 mis-filed, the row names the wrong module.
- **RM-85 Nasus** - MIS-FILED, it was the `top=40` trap.
- Do not re-plumb `apply_ability_base_overrides`, `apply_passive_aura_damage`,
  or `kit_conversion_strength` on `/rank-assassin` - all three shipped 1.251.0.

## HAZARDS

- **Row agreement is NOT evidence** - N rows citing one blocker is ONE
  unverified claim to check, not N votes.
- **Reproduce a finding's ORIGINAL params before contradicting its numbers.**
  Last session a handed-forward headline "did not reproduce" purely on
  parameterization; direction and magnitude held.
- `/rank*` returns `item_id` as a **STRING**; default `top` is 40; `items=[]`
  under-ranks amp/complementary items; `POST /rank` is the CARRY scorer and
  there is no `/rank-hybrid`.
- A pinned "signature tail" assertion is self-defeating under append-at-END.
- Any new DS test importing `core.*` at module level must be registered in
  `tools/ds_share_sync._HOST_DEPENDENT_TESTS` - **warn every build agent, not
  one.**
- Four doc sites on a bump; keep the Share README at **fourteen** bullets; the
  ENGINE bump also requires a PREPENDED `agents/daemon_slayer/CHANGELOG.md`
  entry or `test_changelog_tracks_engine_version.py` fails.
- Exit code is not ground truth - redirect pytest to a file. **The RC suite
  takes ~20 minutes and exceeds the foreground tool timeout; run it in the
  background.**
- If a slice's edits all land in the same two files, do NOT spawn worktree
  agents for it - that is false parallelism. Probe in parallel, then wire in the
  main thread.

## START WITH

`/clear`, then bootstrap from CLAUDE.md + MEMORY.md + WAKEUP_NOTES + git log +
ROADMAP RM-115.
