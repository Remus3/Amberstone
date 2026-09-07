# SPEC: Data provenance guard + cross-patch feed index

Status: READY TO IMPLEMENT for Phases 1 and 3. Phase 2 proceeds on the Section 9 defaults
unless the operator overrides.
Revision: 2 (2026-07-19). Revision 1 failed a 3-lens completeness audit; see CHANGE LOG.
Author: synthesis session 2026-07-19, re-measured and re-integrated 2026-07-19.
Supersedes: `docs/specs/DECISION_cdragon_cross_reference.md` section "Recommendation" (see section 2)
Verification set: enumerated in Phase 1, not a tier label. See 4.1.

Every measurement in this spec was re-derived against the live tree on 2026-07-19, and every
number that a revision-1 auditor could not reproduce was re-measured rather than reworded.
Where a measurement contradicts a panel proposal, the brief, or revision 1, the contradiction
is called out inline.

---

## 1. PROBLEM

A vendored data feed sitting in `data/daemon_slayer/<patch>/` can carry content from a
different patch than its directory name, and nothing checks. The directory name is
treated as a provenance claim by every loader and every human reader, and it is not one.

### 1.1 The measurement instrument (use this exact one)

Canonical body hash: recursively strip three key-name groups, then
`md5(json.dumps(o, sort_keys=True, separators=(',',':')))`, first 8 hex.

- **Wall-clock group** - `{fetched_at, generated_at, extracted_at, _generated_at,
  source_generated_at, timestamp}`. These are fetch evidence and are consumed separately
  (3.5); they must not move a body hash.
- **Prose group** - `{generated_note, _note}`. Revision 1 filed these under the wall-clock
  group. They are free prose, carry no time value, and nothing may read them as fetch
  evidence. The regrouping does not change any hash; it changes what 3.5 is allowed to read.
- **Stamp group** - `{version, patch, _patch, rc_patch, source_patch, ddragon_version,
  patch_segment, _patch_segment, meraki_content_patch, _meraki_content_patch,
  content_patch}`.

The stamp group gained `_meraki_content_patch` and `content_patch` in revision 2. The same
semantic field - the Meraki upstream content vintage - is spelled three ways across three
files, and revision 1's list covered only one spelling, so two survived into the body hash.
It is inert only while Meraki never moves off `25.15`; the day it moves, or a re-extract
writes a different vintage, `ability_staleness.json` and `manifest.json` register a false
"body moved" and classify HEALTHY when nothing of substance changed.

**The strip is BY KEY NAME ONLY and must never be widened to a value-shape regex.** A
value-shape scan false-matches `wiki_ability_stats.json`'s
`abilities['Rakan/The Quickness'].cast_time_raw = '0.5'`, which is a cast time, not a patch.

**Revision 1 claimed the two added keys were a provable no-op. Measured: they are not.** Two
feeds move, and the corrected matrix below is the authoritative one. An implementer who
generates the lock against revision 1's matrix produces two rows that disagree with this
document on day one.

Three cheaper instruments FAIL, in three different directions, and all three were tested:

- **Whole-file md5 certifies the flagship defect as healthy.** `items_meraki.json` has five
  distinct file hashes across the five dirs purely because `fetched_at` advances
  (`2026-05-13T17:42:46-0500` -> `2026-05-27` -> `2026-06-09` -> `2026-06-25` ->
  `2026-07-16T08:59:07-0500`). Its stampless body hash is `73446cf8` in all five.
- **Byte size fails in the opposite direction.** `wiki_stats.json` differs by 10,048 bytes
  between 16.11.1 and 16.12.1 from JSON indent width alone, with identical content, and
  reverts to the exact 16.11.1 byte count at 16.14.1.
- **EOL normalization fails too, and it fails PER MACHINE.** `git config --get core.autocrlf`
  is `true` on Legion while `.gitattributes:28` pins `eol=lf` for `*.py` only, so every
  vendored `.json` is CRLF on Legion and LF in a Linux CI checkout. Measured on
  `data/daemon_slayer/16.13.1/items.json`: 860,041 bytes / md5 `6414613f` on disk with
  30,005 CRLF pairs, versus 830,036 bytes / md5 `81546b13` in the git blob with zero. Its
  canonical body is `f9ef9c1c` in both.

**Binding consequence of the third failure: `feed_lock.json` MUST NOT carry a size,
byte-count or whole-file-digest column.** All three are machine-dependent and such a column
would red every row in CI on day one.

Measured stampless body-hash matrix over
`data/daemon_slayer/{16.10.1,16.11.1,16.12.1,16.13.1,16.14.1}/` (`-` = file absent):

```
ability_staleness.json       -        -        -        -        2ad50954   uniq=1
arena_augments.json          3298a44b 3298a44b 8413698e 3b92a62d 6ba12a27   uniq=4
build_orders_aram.json       -        560b5cee e4f0c0ed 4f4ef4e5 c111787b   uniq=4
build_orders_arena.json      -        5ff52673 bbdeccea e4cda8cc e480ffea   uniq=4
build_orders_sr.json         -        0c941b74 acb61fd8 1e0b46c6 9c0a2d99   uniq=4
cdragon_ability_ratios.json  -        bb1fd9e2 bb1fd9e2 bb1fd9e2 9c67b58a   uniq=2
cdragon_ratio_drift.json     -        a6c716d5 a6c716d5 a6c716d5 39febcf3   uniq=2
cdragon_spell_stats.json     -        ee27a427 ee27a427 49e9722a 49e9722a   uniq=2
champion_abilities.json      96da30d8 96da30d8 96da30d8 96da30d8 96da30d8   uniq=1
champions.json               a7bf567a 45b29b94 fae7469b 4975bcd2 4975bcd2   uniq=4
cherry_augments.json         3b34505a 3b34505a 3b34505a 3b34505a 3b34505a   uniq=1
enchanter_items.json         3b82292c 3b82292c 3b82292c c6f74cae 56c5da94   uniq=3
items.json                   ee0303e8 8a55e344 f0288299 f9ef9c1c 43eeceb6   uniq=5
items_meraki.json            73446cf8 73446cf8 73446cf8 73446cf8 73446cf8   uniq=1
manifest.json                341d4fd3 812b1c56 0c15e3f1 55f3c39c addc41ed   uniq=5
mayhem_augment_stats.json    e1e07c87 e1e07c87 e1e07c87 e1e07c87 e1e07c87   uniq=1
pickban_targets.json         -        fccddfbb 42979176 46ece9d9 6c13d031   uniq=4
scenarios.json               702eaa46 702eaa46 702eaa46 55cce5a4 6a7a2c65   uniq=3
wiki_ability_stats.json      -        f536c0f9 f536c0f9 f536c0f9 f536c0f9   uniq=1
wiki_stats.json              -        bef0ae84 bef0ae84 bef0ae84 bef0ae84   uniq=1
```

Two structural facts fall out of this matrix and both are load-bearing later:

- **Zero of the 20 feeds has a non-contiguous body hash.** No feed's content ever reverts to
  an earlier value after moving away. Every feed's history is therefore a clean partition
  into contiguous runs, which is what makes `carried_from` a fact rather than a convention
  (3.4). A future revert would make it ambiguous, and the tool must raise rather than guess.
- **Zero of the 20 feeds has a mid-history absence gap.** Every feed appears once and then
  persists, so "the previous dir containing this feed" is always the immediately preceding
  present dir.

### 1.2 The four confirmed instances

**INSTANCE 1 - Meraki frozen, shipped a wrong coefficient.**
`items_meraki.json` body is byte-identical across all five dirs (`73446cf8`) while
`fetched_at` advances on every refresh. Its top-level keys are exactly
`['count','fetched_at','items','source']` - there is NO patch field, which is precisely why
the freeze was invisible: no field could ever disagree. Probed in the SAME `16.14.1` dir:

- `data/daemon_slayer/16.14.1/items_meraki.json` item 3084 Heartsteel:
  `grant you permanent {{as|'''bonus''' health}} equal to{{ft|8% of that amount|...`
- `data/daemon_slayer/16.14.1/items.json` item 3084 Heartsteel (DDragon):
  `...and grants <scaleHealth>10%</scaleHealth> of the damage as <scaleHealth>max Health.</scaleHealth>`
- Shipped constant `agents/daemon_slayer/_item_health_stack.py:91` = `"3084": 0.10` (correct
  today, after R137 re-sourced it; the 8% was what shipped first).

`items_meraki.json` has **ZERO runtime loaders**. Every non-test reference in `agents/`,
`core/`, `app/`, `modes/`, `dashboard/` is a docstring source-citation; the only writer is
`tools/daemon_slayer_extract.py`. **The coefficient reached the engine by a human
transcribing a number out of JSON into a hand-authored registry.** A loader-side patch guard
is structurally incapable of preventing recurrence. This is the single most important fact
in the spec and it determines the whole shape of Phase 2.

**INSTANCE 2 - CDragon ratio sidecar copied forward three patches. ALREADY FIXED.**
`cdragon_ability_ratios.json` reads `bb1fd9e2` with payload `patch = "16.11.1"` in the
16.11.1, 16.12.1 AND 16.13.1 dirs, then `9c67b58a` / `"16.14.1"` at 16.14.1. The fix shipped
in two commits (`46bbc24b` guard, `e1b42e89` re-extract + strict ON) and is live:
`agents/daemon_slayer/abilities.py:448` (`_load_cdragon_ratio_sidecar`) compares the
payload's `patch` against the requested patch, WARNs, and returns `{}` under strict;
`abilities.py:679` ships `strict_cdragon_patch: bool = True`.

**Do not re-solve this.** It is the reference implementation. Two things about it remain open
and ARE in scope: it is the ONLY payload-patch comparison in the codebase, and a second
consumer of the same file is unguarded - `core/build_planner/champ_kit_data.py:108-128`
(`_load_ability_ratios`, fail-soft and module-cached in `_RATIO_CACHE`) resolves
`_DS_DIR / patch / "cdragon_ability_ratios.json"` and reads `raw.get("champions", {})` with
no reference to `raw.get("patch")`. Per-loader fixes provably do not propagate.

**INSTANCE 3 - `enchanter_items.json` stamp tracks nothing.** `_meta.patch == "16.9.1"` in
ALL FIVE dirs, while the items body genuinely moved (`3b82292c` x3 -> `c6f74cae` at 16.13.1
-> `56c5da94` at 16.14.1) and the item count went 9 / 9 / 9 / 10 / 12.
`grep -rn 'enchanter_items' tools/ scripts/ --include=*.py` returns EMPTY: there is no
extractor, the file is hand-authored. Its loader in `agents/daemon_slayer/hps.py` resolves
`root / patch / "enchanter_items.json"` by directory and never reads `_meta.patch`.

The correct invariant here is **"body changed implies stamp changed"**, NOT "stamp equals
directory". A directory-equality rule would fire on this file forever, because the stamp
means curated-at, not content-from. This distinction is load-bearing and a naive
implementation gets it backwards.

**INSTANCE 4 - hand-typed source citations name a stale patch dir.** Full census over
authored non-test Python in `agents/`, `core/` and `tools/`, excluding `Share/`: **26
vendored-path citations** - `champion_abilities.json` 12, `items_meraki.json` 7, `items.json`
6, `champions.json` 1 - plus one loose non-path form at `_item_resist_grants.py:29`
("verbatim `items_meraki.json` 16.13.1").

Revision 1 tabled 9 sites and used "9" to size Phase 3. The in-scope population for Phase 3's
two item feeds is **13 sites** (12 stale plus `_item_health_stack.py:20`, which already names
the current patch and is the vintage-marker exemplar). The three revision 1 missed:

```
agents/daemon_slayer/_item_revive.py:28                 16.13.1/items.json        (wrapped)
agents/daemon_slayer/_item_spell_shield_overrides.py:31 16.13.1/items_meraki.json
agents/daemon_slayer/_item_survival_window.py:34        16.13.1/items_meraki.json
```

The full stale set for the two item feeds: `_item_bonus_hp_amp.py:39` and `:58`,
`_item_general_dr.py:51`, `_item_mana_health.py:30` and `:46`, `_item_omnivamp.py:25` and
`:31`, `_item_resist_grants.py:67`, `_item_revive.py:22` and `:28`,
`_item_spell_shield_overrides.py:31`, `_item_survival_window.py:34`.
`data/daemon_slayer/current.txt` reads `16.14.1`.

Note for triage: `_item_ability_haste.py:37` and `core/build_order.py:90` cite
`data/meta_build/ddragon/16.12.1/item.json`, a DIFFERENT vendored tree, correctly outside
Phase 3's `data/daemon_slayer/` scope. Revision-1 auditors mis-attributed these into the
Instance 4 census.

**Severity split matters and a naive rule gets it backwards.** The `items_meraki.json`
citations are materially INERT - the body is byte-identical across all five dirs, so a
16.13.1 read and a 16.14.1 read return the same bytes. The `items.json` citations are
materially STALE - DDragon has five distinct bodies. Any rule that flags both at the same
severity is exactly the Constraint-2 noise this spec exists to avoid. Revision 2 makes this
split COMPUTED from the lock rather than hand-asserted (4.3).

A second class must NOT be flagged: dated history. `agents/daemon_slayer/ability_hps.py:375`
("ground-truth probed at 16.11.1"), `ability_hps.py:430` and `cc_conditional.py:648` are
statements about WHEN something was observed. Those are correct forever and must never be
bumped.

### 1.3 The class revision 1 named RESTAMPED, and got wrong for all three members

Revision 1 asserted that `champion_abilities.json` (`96da30d8` x5),
`wiki_ability_stats.json` (`f536c0f9` x4) and `wiki_stats.json` (`bef0ae84` x4) are the
RESTAMPED feeds. **Measured: none of the three is, and under revision 1's own precedence two
of them could never reach the class at all** (its rule 3 outranked rule 4 and both wiki feeds
carry no timestamp, so they fell into COPIED_FORWARD). The flagship class revision 1 invented
was unreachable for two of its three named members.

The three split by the evidence they actually carry, and the split is the point:

- **`champion_abilities.json` -> FROZEN_UPSTREAM.** It IS re-fetched every refresh
  (`fetched_at` has five distinct values, `2026-05-25T15:33:34-0500` through
  `2026-07-16T08:59:28-0500`) while `version` advances 16.10.1..16.14.1. The upstream is
  dead. That is exactly the Instance-1 argument about Meraki, so calling it RESTAMPED
  contradicted this spec's own analysis.
- **`wiki_stats.json` and `wiki_ability_stats.json` -> CARRY_UNVERIFIABLE.** Neither file
  carries any wall-clock field, so the copy-forward ritual can be neither confirmed nor
  refuted from the artifact. The honest class is "no evidence either way", and its
  remediation is to make it decidable (Section 9 Q1).
- **The one genuinely RESTAMPED feed on measured data is `scenarios.json`**, which revision 1
  never mentions: identical body `702eaa46` at 16.10.1 / 16.11.1 / 16.12.1, `version` stamp
  advancing 16.10.1 -> 16.11.1 -> 16.12.1, and a genuine fetch each time (its inherited
  manifest clock advances).

The documented refresh ritual manufactures the shape. Memory
`reference_patch_refresh_workflow`: "Copy-forward wiki_stats.json + wiki_ability_stats.json
from prev + sed flip `_patch` to the new patch." Because every patch label is exactly 7
characters, the flip is byte-size-preserving.

**Consequence, and it survives the membership correction intact: a payload-patch equality
check passes all three of these**, and the repo contains a sanctioned procedure that produces
exactly the lie such a check detects. This is why the lock is content-addressed and not a
stamp compare, and the reason must be recorded in the test docstring or a later
"simplification" reverts the whole design.

### 1.4 Two instances nobody named, and they are the cheapest real wins

`cherry_augments.json` (`3b34505a` x5) and `mayhem_augment_stats.json` (`e1e07c87` x5) both
carry `rc_patch = "16.10.1"` in the 16.14.1 dir, and each carries a `fetched_at` that is
byte-identical across all five dirs. **They do not share one literal**, contrary to revision 1:

```
cherry_augments.json       fetched_at = 2026-05-18T03:58:33.339013+00:00   count 554
mayhem_augment_stats.json  fetched_at = 2026-05-18T03:58:33.211074+00:00   count 199
                           source_generated_at = 2026-05-18T02:21:07.268643Z (also frozen)
                           source_patch = "16.10"
```

They were provably never re-fetched across four patch refreshes. An implementer transcribing
revision 1's single quoted literal into a test writes a test that fails on mayhem for the
wrong reason, which is why 6.1 test 8 is specified relationally and hardcodes no timestamp.

Fetch-evidence identity is the mechanical discriminator between "never fetched" and "fetched,
upstream frozen". `items_meraki.json` has five distinct `fetched_at` values: it IS re-fetched,
the upstream is simply dead. These two have one each.

**Second correction, and it re-prices Section 9 Q1.** Revision 1 said both are
CommunityDragon-sourced. Only one is:

- `cherry_augments.json` `source` =
  `https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/cherry-augments.json`
- `mayhem_augment_stats.json` `endpoint` =
  `https://data.v2.iesdev.com/api/v1/query_objects/prod/lol/aram_mayhem_augments`

`data.v2.iesdev.com` is a third-party stats endpoint, not a Riot data CDN, and its history
retention is UNVERIFIED. The "Meraki-not-backfillable constraint does not bind them" argument
holds for cherry only.

### 1.5 What revision 1 got structurally wrong

Recorded so a later pass does not re-derive it, and so the corrections below are not read as
cosmetic:

1. **`kind` was two axes crushed into one enum.** `{pinned, latest, authored, derived}` mixes
   "was the fetch URL versioned" with "was there a fetch at all". That is why `derived` had
   no rule and why rule 1 needed the awkward "any kind except authored" escape. Corrected in
   3.3.
2. **Rule 3 COPIED_FORWARD was unsound, not under-specified.** It tested "`fetched_at`
   identical to the previous dir", and exactly 10 of the 20 feeds carry no wall-clock field
   at all, so `null == null` made it vacuously true for half the inventory. Ranked above
   rules 4/5/6, it swallowed them. Corrected in 3.5.
3. **The stamp slot was three semantic axes, one of them in a foreign version namespace.**
   Corrected in 3.3.
4. **The ladder was not total.** Implemented literally against the real tree, 14 of 67 frozen
   rows (21 percent) fell through unclassified and 6 more landed in classes the spec
   explicitly said it had designed out. Corrected in 3.5, measured at 0 fall-through.
5. **The note obligation was keyed to the wrong thing and sized against the wrong
   denominator.** Corrected in 3.4 and 4.1.
6. **One scope word did three jobs.** Corrected in 3.0.

---

## 2. DECISION RESOLVED

`docs/specs/DECISION_cdragon_cross_reference.md:3` reads `Status: PROPOSED - awaiting
operator decision`. This section decides it. Implementing agent: flip that line to
`Status: SUPERSEDED by docs/specs/SPEC_data_provenance_guard_and_index.md section 2
(2026-07-19)` and mint the ADR named below.

### 2.1 Meraki: DEAD as a numeric source. Demoted to corroboration-only, never a sole source.

Grounds, all measured:
- Five independent fetches spanning 64 days returned a byte-identical body (`73446cf8` x5).
- The recon's live probes: `patches.json` newest entry is `16.3` dated 2026-02-04; the dated
  archive at `/riot/lol/resources/old/en-US/` ends 2026-02-11. The pipeline died Feb 2026.
- `tools/upstream_drift_check.py` already says verbatim that `fetched_at` lies for Meraki,
  and its own Meraki drift lane can never fire (it requires current != previous; both sides
  are pinned at 25.15 forever).

Operational consequences, binding:
- **Do NOT add a Meraki re-fetch cadence.** Re-fetching returns the same wrong number.
- **Do NOT wait for a Meraki refresh.** Any roadmap or comment framing that says "when Meraki
  catches up" is void.
- Meraki remains vendored and remains the base layer for `champion_abilities.json` (genuinely
  loaded via `data_loader.py`, and both extractors are roster-capped by it). It is not
  deleted. It is relabelled.

**The "~11 patches" correction (the true chain is 23, per
`docs/specs/DECISION_riot_patch_note_backfill.md:154-155`) is live at FIVE authored sites,
not four.** Revision 1 listed four. Measured by repo-wide grep:

```
agents/daemon_slayer/_item_health_stack.py:28
core/daemon_slayer_client.py:1253
tools/ds_wiki_staleness_check.py:8
tools/ds_wiki_staleness_check.py:30
tests/test_ds_wiki_staleness_check.py:4          <- revision 1 missed this one
```

`Share/src/agents/daemon_slayer/_item_health_stack.py` carries a sixth copy and syncs from
the first automatically; do not hand-edit it. `_item_health_stack.py` shipped 2026-07-19, the
day AFTER the correction was measured - this is the same defect class in prose and it is
regressing, not stable.

### 2.2 CDragon: STAYS as engine-feeding numeric authority. Option C is REJECTED for now.

`DECISION_cdragon_cross_reference.md:351,421,483-487` recommends demoting CDragon to
alarm-only and promoting the wiki to numeric authority for bases/ratios/cooldowns. That
recommendation is REJECTED at this time, on three grounds:

1. **Its P0 prefix shipped and changed the facts underneath it.** The doc's reason 4
   (`:479-482`) prices the demotion against a "three-patch-stale" sidecar. It is no longer
   stale: `9c67b58a` / `"16.14.1"` at 16.14.1, with `strict_cdragon_patch: bool = True` at
   `abilities.py:679`. Note honestly that the doc itself flags reason 4 as "independent of
   everything above", so reasons 1-3 survive P0 - this is a re-cost trigger, not a refutation.
2. **The value case was cut 92% by its own program.** The doc prices Option B on "75 stale
   champions / 123 findings" (`:202-205`, `:315-317`). The `ROADMAP.md` row
   **`RM-81 data currency`** measured 6 of 75 changing any ranked item order, 2 touching a
   top-5 item, and **0 changing a recommended core build**. B2 as written has no
   does-this-move-a-ranking filter.
3. **The post-P0 blast radius is unmeasured.** LEDGER item 935's "49 of 171 champions (55
   blocks / 75 fields)" priced dropping the STALE sidecar. Demoting the FRESH one is a
   different, unmeasured number.

**Named re-open gate.** Re-open Option C only when BOTH hold: (a) the post-P0 demotion blast
radius has been measured by regenerating build orders with `prefer_cdragon_ratios=False` and
diffing, and (b) that diff moves at least one recommended core build. Absent (b), the
demotion is an architecture preference with no measured benefit and should stay closed.

### 2.3 Wiki: promoted to DATED ADJUDICATOR only. Not numeric authority. B2 rejected.

The wiki's unique, verified capability is the `|patchhistory =` block, which dates a
coefficient change to a patch. The recon's live probe of
`https://wiki.leagueoflegends.com/en-us/Heartsteel?action=raw` returned
`;[[V26.11]] * Colossal Consumption conversion to permanent bonus health increased to 10%
from 8%` and `;[[V25.04]] * ... reduced to 8% ... from 10%`. No other probed feed can date a
change. That capability is what settled the Heartsteel adjudication.

- **ADOPTED:** wiki as an on-demand dated adjudicator for a single disputed value.
- **REJECTED:** B2 (promote wiki `leveling` blocks into typed damage blocks). It is priced on
  the superseded 75 figure and has no ranking filter.
- **NOT CHANGED:** the wiki roster cap at
  `tools/daemon_slayer_wiki_ability_extract.py:506`. Its docstring at `:200-202` gives a real
  deliberate rationale ("Used to restrict the title list to the champs the DS engine actually
  models (the wiki ChampionData table has a few extra/event entries)"), so de-capping is not
  a line deletion and needs a replacement allowlist. Out of scope here.
- Pin the version-namespace offset in any wiki work: wiki `V26.N` corresponds to DDragon
  `16.N.1` (+10 on the major), date-verified by the recon (wiki V26.11 release "May 28, 2026"
  against the CDragon `16.11` dir mtime "Thu, 28 May 2026").

### 2.4 Items: DDragon `items.json` is the numeric authority. NEW - the doc never covered this.

`DECISION_cdragon_cross_reference.md` is titled and scoped to champion ability data; it
contains zero item-authority scope. This is a new decision, on the cheaper side of the house,
and it is the side where the actual defect shipped.

- `items.json` (DDragon) is the numeric authority for item coefficients. It genuinely
  refreshes: five distinct bodies over five dirs (`uniq=5`, the only feed besides `manifest`
  to do so).
- `items_meraki.json` is corroboration and prose only. It may never be the sole cited source
  for a shipped number without an explicit `SINGLE_SOURCE` classification.
- Where the two disagree, the wiki `|patchhistory =` block adjudicates and the resolution is
  cited by patch.

### 2.5 Mint an ADR - and Q3 dissolves rather than gating Phase 1

`grep -iln 'meraki|lolstaticdata|communitydragon|cdragon|wiki extractor' docs/adr/*.md`
returns only `ADR-010-arena-s2-augment-leveling.md`, whose hits are the augment formula
evaluator. **No ADR governs data sourcing at all.** `CLAUDE.md` routes all re-litigation
through `docs/adr/README.md`, so without one the next session re-opens this from the same
PROPOSED docs. Mint `ADR-013-vendored-data-source-authority.md` carrying sections 2.1-2.4 and
add its README row in the same commit.

**Revision 1 listed the ADR as Phase 1 work while its own Section 9 Q3 said the 2.2 re-open
gate "should run BEFORE the ADR is minted". That is a real self-block and it is resolved
here, not deferred:** an ADR can record a CONDITIONAL rejection, which is exactly what 2.2
already writes ("REJECTED at this time" plus a named re-open gate with two stated
conditions). Minting that text forecloses nothing and therefore needs no blast-radius
pre-requisite. Mint it in Phase 1. The 2.2 gate remains the documented re-open path and is
copied into the ADR as its named revisit condition. Q3 is removed from Section 9.

**Do NOT bump `CLAUDE.md:7`.** It reads "(indexed, 12 ADRs)" while `docs/adr/` currently
holds 11 files (`ADR-002` .. `ADR-012`). Minting ADR-013 brings the count to 12, which makes
that line correct rather than stale. Recorded explicitly so a later doc-sync pass does not
"fix" it to 13.

### 2.6 The Meraki mutability premise: adopt the existing distinction, do not overwrite it

Revision 1's section 7.2 declared "Both halves are wrong and the spec should not repeat them"
about the brief's claim that Meraki's `latest` endpoint is mutable with no versioned history.
**That refutation overreaches and would delete a true statement.** The repo already carries a
more careful reconciliation the spec neither cited nor retired, verbatim at
`agents/daemon_slayer/CHANGELOG.md:3247` and `docs/_archive/2026-07-28-research-consolidation/DS_ABILITY_SHAPING_NOTES.md:629`:

> The Meraki `latest` champions endpoint is mutable but its CONTENT is frozen at a
> [pinned patch]

Two different claims, both true:
- **Mutable** is a REPRODUCIBILITY statement: the URL is unversioned, so a re-fetch is not
  guaranteed to return what the last one did. This is what justifies the standing rule
  "never `--force` a Meraki re-extract".
- **Frozen** is a FRESHNESS statement: the bytes have not in fact moved in five fetches over
  64 days.

Note additionally that the two reconciliation sites describe the **champions** endpoint while
this spec's five-fetch evidence is the **items** feed. **ADOPTED POSITION: the endpoint is
mutable AND its content is frozen.** The demotion in 2.1 rests on frozen-ness, which is
measured, and the never-`--force` rule rests on mutability, which is untouched. Nothing in
this spec weakens `CLAUDE.md`'s Settled line.

### 2.7 Doc-sync riders (Phase 1, same commit)

These are the same defect class in prose and a session bootstrapping from them will re-do
finished work. Revision 1 scheduled two; the measured list is nine.

**Refuted-status riders (2.2 / 2.3 subject matter):**
- `ROADMAP.md` row **`RM-81 data currency`** still says "P0 SURFACED, still open (chip
  `task_d665f88b`)", still cites `abilities.py:622` and `abilities.py:430`, and still asserts
  the sidecar is "pinned 16.11.1 byte-identical across the 16.11.1 / 16.12.1 / 16.13.1 /
  16.14.1 dirs" - refuted by the measured `9c67b58a` at 16.14.1. **Corrected replacement line
  numbers: `abilities.py:676` (`prefer_cdragon_ratios: bool = True`) and `abilities.py:448`
  (`_load_cdragon_ratio_sidecar`).** Revision 1 offered `:679` for the first, which is a
  DIFFERENT flag (`strict_cdragon_patch`) and would have injected a new defect into a living
  doc.
- `docs/OPERATIONS.md`, the DS feed table section, still says "Enforcement is default-OFF
  until the 16.14 re-extract lands" and repeats the same refuted byte-identity claim.
  Enforcement is ON (`abilities.py:679`) and the re-extract landed.

**Mutability-premise riders - EDIT TO THE 2.6 DISTINCTION, DO NOT DELETE.** Each of these
states the mutability half without the content half. The edit is additive (append "but its
content is frozen at 25.15"), so none of them loses a true claim:
- `docs/specs/leap/LEAP-02-ds-staged-passives-gwen-kaisa.md:391`
- `docs/specs/leap/LEAP-04-build-order-precompute-backfill.md:278`
- `Share/docs/03_DATA_AND_SOURCES.md:30`
- `CLAUDE.md:208` (the Settled bullet whose closing clause is "Never `--force` a Meraki
  re-extract (the `latest` endpoint is mutable)"). Under `CLAUDE.md:197` a Settled-line
  correction is a PERMITTED `CLAUDE.md` edit. It is additive here, so the rule it encodes is
  unchanged.

**Share care note.** `Share/docs/03_DATA_AND_SOURCES.md` is in `ds_share_sync.py`'s
`_DOC_FILES` tuple (declared at `:70`, the file listed at `:74`) and its anchors are verified
per push. Prose edits are safe because the check is a version-anchor check, but the slice
MUST re-run `python tools/ds_share_sync.py --check` after touching it. That same file also
claims at `:249-252` that Meraki "is the only source that ships the coefficient in a
machine-readable form ... wiki carries it only as prose", which section 2.4 inverts - correct
it in the same pass or ADR-013 ships contradicted by a CI-checked in-repo doc.

**Authority riders:** the five "~11 patches" sites enumerated in 2.1.

**Ledger rider:** append the per-item completion entry to `docs/LEDGER.md` (never to
`CLAUDE.md`, which is CI size-budgeted). Revision 1 itemized every other doc obligation and
omitted this one.

---

## 3. THE SURFACE

Justified against the existing-guard coverage map. Nothing here duplicates a guard that could
be extended instead:

- `tools/upstream_drift_check.py` never opens a file under `data/daemon_slayer/` - it is a
  live-vs-sentinel detector. Its Meraki lane cannot fire. Not extensible to this.
- `tools/ds_wiki_staleness_check.py` / RM-81 compares stored champion abilities against the
  live wiki. Champion-side only, no item-side coverage.
- `tools/ds_share_sync.py --check` proves mirror equals source, not freshness.
- `ops/audit/item_ah_drift_check.py` re-derives 220 AH ids from DDragon. Wholesale-covers
  `_item_ability_haste.py` and is strictly better than annotation; not duplicated here.
- **`tools/daemon_slayer_abilities_extract.py` - the shipped Meraki content-freshness guard
  (`_meraki_content_patch` at `:727`, `_EXPECTED_MERAKI_CONTENT_PATCH = "25.15"` at `:128`,
  drift warning at `:791-801`).** Revision 1's coverage map omitted this entirely while
  asserting nothing was duplicated. Evaluated now, and the honest verdict is that it
  INDEPENDENTLY DERIVED this spec's central insight rather than duplicating the mechanism -
  its docstring at `:729-735` already says the content patch is "independent of the
  `fetched_at` wall-clock (which reflects download time, not data age)". It is NOT a
  substitute, on four measured grounds: it is `log.warning`-only, it runs at extract time and
  never in CI (`grep -c daemon_slayer_abilities_extract .github/workflows/ci.yml` returns
  `0`), it is champion-side and Meraki-only, and it compares against a hardcoded expected
  constant rather than across patch dirs. **Decision: do not promote it and do not fold it in.
  Cite it in `tools/ds_feed_lock.py`'s module docstring as prior art for the wall-clock
  argument, so the next reader finds the two guards related rather than parallel.**
- **No existing guard compares vendored bodies across patch dirs.** That is the hole.

| Path | Single responsibility | Size |
|---|---|---|
| `tools/ds_feed_lock.py` | NEW. Canonical body hash (1.1) + `_FEED_REGISTRY` (3.3) + the total classification ladder (3.5) + `--write` / `--check` / `--report` / `--write-citation-baseline`. Walks ONLY direct semver children of `data/daemon_slayer/` (3.1). Resolves its default patch from `current.txt`, never a literal. Ends `raise SystemExit(main())`, mirroring `ops/audit/item_ah_drift_check.py` and deliberately NOT the always-`None` `main()` of `tools/ds_cdragon_drift_audit.py`. | ~300 lines |
| `data/daemon_slayer/feed_lock.json` | NEW, generated, git-tracked. Root level, NOT per-dir (3.2). Locks the FROZEN dirs only. Schema in 3.4. | ~30 KB |
| `tests/test_ds_feed_lock.py` | NEW. The guard. Thirteen assertions in 6.1, including two meta-guards and the coverage floor. | ~230 lines |
| `.github/workflows/ci.yml` | EDIT, 1 line. Append to the `smoke + regression tests` step at `:140-144`. See 3.6 - this is load-bearing. | 1 line |
| `tests/test_ds_fixture_policy.py` | EDIT, 1 line. `FROZEN_FIXTURES` at `:25` is `("16.10.1", "16.11.1")`; the lock makes all frozen dirs load-bearing. See 3.7. | 1 line |
| `core/build_planner/champ_kit_data.py` | EDIT, ~6 lines. Second unguarded consumer of `cdragon_ability_ratios.json` at `:108-128`. Call the already-public `abilities.cdragon_sidecar_patch()` (`abilities.py:433`). `core/` already imports `agents.daemon_slayer` widely, so no layering problem. | ~6 lines |
| `agents/daemon_slayer/_sources.py` | PHASE 2. `Src` frozen dataclass (7 fields), 3 `Src` kinds, 2 sibling containers, the 3-entry render enum, and the two feed-normalization pipelines. Pure data plus pure functions, no I/O at import. | ~110 lines |
| `tests/test_value_corroboration.py` | PHASE 2. The cross-feed check - the only mechanism that catches instance 1. | ~160 lines |
| `tests/test_source_citation_patch.py` | PHASE 3. Citation-vintage ratchet, driven by `feed_lock.json` (4.3). | ~110 lines |
| `data/daemon_slayer/citation_baseline.json` | PHASE 3, generated, git-tracked. The dated-history exemption set (4.3). | ~1 KB |

### 3.0 THREE SCOPES - stated separately because they genuinely differ

Revision 1 used one undifferentiated notion of "what the walk covers" for three jobs with
different membership, which is why its Phase 1 deliverable 1 ("all 20 feeds") and its scope
decision ("lock the FROZEN dirs") read as a contradiction. They were never a contradiction;
they were two different scopes sharing one word. Every test in section 6 names its scope.

| Scope | Membership | Measured | Carries |
|---|---|---|---|
| **REGISTRY** | the union of feed filenames over EVERY direct semver child, including the live dir | **20 feeds** | classification metadata only, no hashing |
| **LOCK** | frozen semver dirs (all semver dirs minus `current.txt`'s patch minus `RETIRED_FIXTURES`) x the feeds present in each | **67 rows over 19 distinct feeds** (10 + 19 + 19 + 19) | `body_md5`, `declared_patch`, `content_vintage`, `fetch_evidence`, `carried_from`, `run_len`, `class`, machine `note` |
| **LIVE-ASSERTION** | `current.txt`'s dir only | **20 feeds** | nothing persisted; assertions computed at test time |

`ability_staleness.json` is the case that forced the split: it exists ONLY at 16.14.1
(`git ls-files 'data/daemon_slayer/*/ability_staleness.json'` returns one path). It is
registry-IN, lock-OUT, live-assert-IN. The single-scope model cannot express that at all.

### 3.1 Walk scope - restrict to direct semver children

`data/daemon_slayer/` also contains `build_orders/{16.11.1..16.14.1}` and
`laning_scenarios/{16.11.1..16.13.1}`. A recursive semver walk pulls in **505.68 MiB
(530,246,086 bytes) instead of 57.69 MiB (60,492,519 bytes)** - measured 2026-07-19, a ratio
of **0.1141**. Revision 1 quoted these as "505 MB" and "57.7 MB"; the figures were right and
the UNIT was wrong. They are MiB, which is what Windows Explorer reports, and a revision-1
auditor measuring the same bytes in decimal MB got 530.2 / 60.5 and read it as a 2.8 MB drift.
There was no drift. Both numbers are nonetheless deleted from every gate (4.1 gate (c)).

Worse than size: `laning_scenarios/**/*.json` is LFS-tracked (`.gitattributes:29`, the final
line) while both CI jobs use bare `actions/checkout@v6` (`ci.yml:40`, `:66`) with no
`lfs: true` - in CI those are ~130-byte pointer stubs. Verified:
`git cat-file -s HEAD:data/daemon_slayer/laning_scenarios/16.13.1/laning_scenarios_sr.json`
returns `133` against 66,961,895 bytes on disk. Hashes would diverge between Legion and CI
permanently and produce a CI-only failure that looks exactly like a real finding.
`build_orders/16.14.1/` is additionally rewritten by every engine bump.

Rule: `root.iterdir()`, keep directories matching `^\d+\.\d+\.\d+$`.

**Ship three assertions, not one, and prefer the closed invariant over the name list:**

1. **Key-shape invariant (primary).** No registry key and no lock feed key may contain a path
   separator. This is closed: it holds for any future sibling namespace without editing an
   exclusion list, and it fails loudly the moment a recursive walk sneaks in.
2. **Name exclusion (secondary, cheaper signal).** Assert `laning_scenarios` and
   `build_orders` are absent from the lock by name.
3. **Non-recursion ratio.** Assert `shallow_bytes < 0.25 * recursive_semver_bytes`. Measured
   11.4% today, so 25% is a 2.2x margin; an accidental `rglob` takes the ratio to 1.000, an
   8.8x violation, while ordinary data growth never approaches it. This is the only
   size-derived assertion in the spec and it is a ratio, not a literal, so it is immune to
   the CRLF machine-dependence in 1.1.

**The two build_orders namespaces are genuinely different artifacts, not copies.** Under the
1.1 instrument, LOCKED namespace versus EXCLUDED namespace at all 12 shared (patch, mode)
cells:

```
16.11.1 sr    0c941b74 vs 377e4ad2
16.12.1 sr    acb61fd8 vs 38400eb2   aram e4f0c0ed vs 07b99557   arena bbdeccea vs 9a87858b
16.13.1 sr    1e0b46c6 vs 1d5797a9   aram 4f4ef4e5 vs 19ccdf9f   arena e4cda8cc vs 7bd8a597
16.14.1 sr    9c0a2d99 vs fb9e67d2   aram c111787b vs 57b5aca1   arena e480ffea vs 8bf2fcd6
```

Different at 12 of 12. The excluded namespace is also NOT a parallel population:
`data/daemon_slayer/build_orders/16.11.1/` holds ONLY `build_orders_sr.json` (aram and arena
are absent there while present in the patch dir), and `build_orders/16.14.1/` holds 6 files
including a `build_order_variants_{sr,aram,arena}.json` family with no counterpart in any
locked dir. This is why a path-keyed registry would imply a coverage promise the walk does
not keep, and why the bare-filename key plus the key-shape invariant is the right shape.

**Six loose `*.json` at the root are also skipped, and that must be recorded rather than
implied.** `spell_cast_rates.json`, `ult_cast_rates.json`, `sr_draft_presets.json`,
`user_builds.json` (untracked, runtime-mutable), `vision_atlas_manifest.json`,
`vision_region_atlas.json`. They are patch-INDEPENDENT - they sit beside the patch dirs, not
inside one - so no dir-vs-dir invariant applies. But four carry real runtime loaders
(`agents/daemon_slayer/ult_rates.py:62-63` sets `_ULT_RATE_FILE` and `_SPELL_RATE_FILE`;
`coaches/sr_draft_profile.py:52`; `core/vision_atlas_precompute.py:45`;
`core/vision_region_atlas.py:36`), which is strictly more consumption than
`items_meraki.json`'s zero, and their mtimes (May 4 / May 5 / May 12 / Jul 14) sit outside
every refresh cadence. `feed_lock.json` therefore carries a `root_feeds` array of NAMES ONLY
- no hashes, no classes, no notes - and test 12 asserts the on-disk root `*.json` set equals
it minus the untracked `user_builds.json`. That closes the silent-escape hole at zero
note-authoring cost and imports no staleness design.

### 3.2 Root-level lock, not per-dir

`tools/ds_share_sync.py:256-260` rglobs `data/daemon_slayer/<_PATCH>/` into the Share mirror
while `:253-255` picks up `current.txt` by name at the root. A root-level `feed_lock.json` is
caught by neither branch, so its PLACEMENT is Share-neutral. Verify by running
`python tools/ds_share_sync.py --check` before commit.

**Scope this claim to the file, not to the slice.** Revision 1 promoted a true file-level fact
into a false slice-level claim ("Tier-1 ... no Share re-sync") that its own test 7
contradicted: that test's remediation edited `data/daemon_slayer/16.14.1/enchanter_items.json`,
which IS inside the rglob, and the mirror reproduces the defect verbatim
(`Share/src/data/daemon_slayer/16.14.1/enchanter_items.json` has `_meta.patch = '16.9.1'`).
Revision 2 removes the collision at the source by scoping test 7 to frozen pairs (6.1),
so the slice really is Share-neutral - but the claim is now stated about placement and
verified by a gate rather than assumed.

A per-dir lock would additionally be copy-forwardable at the next refresh, i.e. subject to
the exact defect it detects.

### 3.3 The registry - two axes, not one enum, and the completed 20-row table

**DESIGN CORRECTION.** Revision 1's flat `kind` enum `{pinned, latest, authored, derived}`
crushed two orthogonal questions into one slot: `pinned`/`latest` answer "was the fetch URL
versioned", `authored`/`derived` answer "was there a fetch at all". That is why `derived` had
no classification rule and why the highest-precedence rule needed the escape "any kind except
`authored`" - every rule silently had a different domain. Patching `derived` into the old
ladder would leave the same defect for the next kind added.

Two columns replace it:

- **`origin`** in `{fetched, authored, derived}` - the ladder branches on this FIRST, so every
  rule has a defined domain.
- **`pinning`** in `{pinned, latest, content_hash, null}` - non-null only when
  `origin == fetched`.

`origin` is resolved by whether a writer exists under `tools/`, `scripts/` or `ops/`.
`pinning` is resolved from the FETCH URL, and the mechanical rule is:

> `pinned` iff the fetch URL embeds the same version token that names the output dir;
> `latest` iff the URL carries an unversioned segment such as `/latest/`;
> `content_hash` iff the URL's filename is a content hash (neither pinned nor latest).

**`content_hash` is a third case revision 1's 4-value enum could not express, and it is real
today.** `manifest.json` records `scenarios.json`'s upstream as
`https://lolmath.net/_next/static/chunks/370vfc_ounngn.js` - a Next.js chunk whose filename
is a build hash. Nothing in the ladder reads `pinning` except `STATIC_CONFIRMED`, so the
addition is safe and it stops an implementer from having to guess.

`pinning` is the discriminator that keeps the artifact under the noise constraint, and it is
proven by counterexample: `champions.json` is stampless-identical at 16.13.1/16.14.1 and that
is CORRECT, while `items_meraki.json` identical x5 is a defect. Same observable, opposite
verdict.

**The pinned exemplar's citation is corrected, and so is its framing.** Revision 1 cited
`tools/daemon_slayer_extract.py:57` as proof that DDragon is version-pinned. `:57` is
`DDRAGON_BASE = "https://ddragon.leagueoflegends.com"` - a bare host with no version, which
proves nothing. The real behaviour is stronger than a static pin: `:624` fetches
`versions.json`, `:625` binds `version = versions[0]` (the newest published version), `:627`
and `:628` interpolate THAT into the champion and item URLs, and the output directory is
named after the same string. So the dir name is DERIVED from the fetch URL's version token,
which is exactly why they can never disagree. Meraki by contrast hardcodes `/latest/` at
`:68`, and `manifest.json` records the resolved DDragon forms as `.../cdn/16.14.1/...`.

Registry rows MUST cite the URL beside the pinning, because at least one value is a bug rather
than a fact: `tools/daemon_slayer_wiki_stats_extract.py:143` hardcodes `/latest/` for the same
CommunityDragon character-bin path that its sibling
`tools/daemon_slayer_cdragon_spell_extract.py:107` pins by `{patch}`. `source_url` stores the
FULLY INTERPOLATED template, never the base constant.

**`source_url` is hand-seeded for all 20 rows, and machine cross-checked for 7 of them.**
`manifest.json` independently records fetch URLs for the 5 feeds its `outputs` block names
(`champions`, `items`, `scenarios`, `arena_augments`, `items_meraki` - identical in all five
dirs), and two more feeds carry their own URL in the payload (`cherry_augments.source`,
`mayhem_augment_stats.endpoint`). Manifest cannot cover the other 13, so it cannot replace the
registry - but test 13 asserts the 7 machine-witnessed URLs agree with the registry at
`current.txt`'s dir, so the two cannot silently diverge on the rows where a second truth
exists.

**The stamp slot is three semantic axes, and one is in a foreign version namespace.** Revision
1 gave one `stamp_field`. Four feeds carry two or more patch-shaped fields, and they are not
competing candidates for one slot:

- **Axis A - the dir-comparable 3-segment claim.** `version | patch | _patch | rc_patch |
  _meta.patch | ddragon_version`. This is `stamp_field`, and it is the only axis ever compared
  to a directory name.
- **Axis B - a 2-segment truncation of axis A.** `patch_segment | _patch_segment |
  source_patch`. **Never selected, never compared, never recorded.** A 2-segment value can
  never equal a 3-segment dir name, so selecting one makes the highest-precedence rule fire
  forever on three feeds. Measured stability confirms it would never self-correct:
  `source_patch` is `'16.10'` in all five dirs; `patch_segment` reads 16.11 / 16.11 / 16.11 /
  16.14.
- **Axis C - an upstream content vintage in a FOREIGN version namespace.**
  `meraki_content_patch | _meraki_content_patch | meraki_items.content_patch`, all valued
  `'25.15'` against a 16.x dir namespace. This is `content_vintage_field`. It is RECORDED in
  the row and **NEVER dir-compared** - comparing Riot live-patch numbering to DDragon
  numbering is a category error that can never be satisfied. The repo already names it so at
  `agents/daemon_slayer/_effects_data.py:762` ("FROZEN at content patch 25.15").

Selection rule when several axis-A candidates are present: take the one whose value has
exactly 3 dot-separated segments; if still tied, take the lexicographically first key name.
Deterministic, no judgement.

**The completed registry, measured. Phase 1 deliverable 1 is transcription, not derivation.**

| feed | origin | pinning | stamp_field | content_vintage_field | time_field |
|---|---|---|---|---|---|
| `champions.json` | fetched | pinned | `version` | - | `@manifest` |
| `items.json` | fetched | pinned | `version` | - | `@manifest` |
| `cdragon_ability_ratios.json` | fetched | pinned | `patch` | - | - |
| `cdragon_spell_stats.json` | fetched | pinned | `_patch` | - | - |
| `items_meraki.json` | fetched | latest | - | - | `fetched_at` |
| `champion_abilities.json` | fetched | latest | `version` | `meraki_content_patch` | `fetched_at` |
| `arena_augments.json` | fetched | latest | - | - | `fetched_at` |
| `cherry_augments.json` | fetched | latest | `rc_patch` | - | `fetched_at` |
| `mayhem_augment_stats.json` | fetched | latest | `rc_patch` | - | `fetched_at` |
| `wiki_stats.json` | fetched | latest | `_patch` | - | - |
| `wiki_ability_stats.json` | fetched | latest | `_patch` | - | - |
| `scenarios.json` | fetched | content_hash | `version` | - | `@manifest` |
| `enchanter_items.json` | authored | - | `_meta.patch` | - | - |
| `build_orders_aram.json` | derived | - | `version` | - | `generated_at` |
| `build_orders_arena.json` | derived | - | `version` | - | `generated_at` |
| `build_orders_sr.json` | derived | - | `version` | - | `generated_at` |
| `cdragon_ratio_drift.json` | derived | - | `patch` | - | - |
| `pickban_targets.json` | derived | - | `patch` | - | - |
| `ability_staleness.json` | derived | - | `_patch` | `_meraki_content_patch` | `_generated_at` |
| `manifest.json` | derived | - | `ddragon_version` | `meraki_items.content_patch` | `extracted_at` |

`@manifest` means the feed carries no own wall-clock field and INHERITS fetch evidence from
`manifest.json`'s `extracted_at` in the same dir, valid only because the feed is named in that
manifest's `outputs` block. Validated: `manifest.extracted_at` has 5 distinct values and is
byte-identical to `items_meraki.fetched_at` at all five dirs
(`2026-05-13T17:42:46-0500` / `2026-05-27T20:24:40-0500` / `2026-06-09T17:11:40-0500` /
`2026-06-25T02:14:05-0500` / `2026-07-16T08:59:07-0500`).

Two feeds have `stamp_field` null (`items_meraki`, `arena_augments`) and therefore can never
trigger `PATCH_STAMP_MISMATCH`. That matches 7.3's observation that a generalized
payload-patch gate cannot cover them, and it is why the lock is content-addressed.

`role` in `{engine_input, alarm, data_only, derived}` is also carried, seeded verbatim from
the labels already in `docs/OPERATIONS.md`'s DS feed table, which classifies
`cdragon_ability_ratios.json` as `**ENGINE INPUT**` and both `cdragon_spell_stats.json` and
`wiki_ability_stats.json` as `DATA-ONLY sidecar (no consumer wired yet)`. Carrying `role` is
what makes the artifact the substrate a future authority decision lands on rather than a
parallel table silent on the only axis that matters. It also disambiguates
`cdragon_ability_ratios.json` from `cdragon_ratio_drift.json`, which share an extractor and
which a provenance-only taxonomy cannot separate.

### 3.4 Lock schema

```json
{
  "generated_from_current_txt": "16.14.1",
  "registry_namespace": "data/daemon_slayer/<semver>/",
  "root_feeds": ["spell_cast_rates.json", "..."],
  "registry": {
    "<feed_path_relative_to_patch_dir>": {
      "origin": "fetched|authored|derived",
      "pinning": "pinned|latest|content_hash|null",
      "role": "engine_input|alarm|data_only|derived",
      "source_url": "<fully interpolated URL, or null for authored>",
      "stamp_field": "version|patch|_patch|rc_patch|_meta.patch|ddragon_version|null",
      "content_vintage_field": "meraki_content_patch|_meraki_content_patch|meraki_items.content_patch|null",
      "time_field": "<wall-clock key, '@manifest', or null>",
      "rationale": { "<CLASS>": "<human text, >= 40 chars>" }
    }
  },
  "frozen": {
    "<patch_dir>": {
      "<feed_path_relative_to_patch_dir>": {
        "body_md5": "<canonical, 8 hex>",
        "declared_patch": "<value at stamp_field, or null>",
        "content_vintage": "<value at content_vintage_field, or null - NEVER dir-compared>",
        "fetch_evidence": "advanced|identical|absent",
        "carried_from": "<oldest patch_dir of this row's contiguous run, or null>",
        "run_len": 4,
        "class": "<one of the 13 in 3.5>",
        "note": "<MACHINE-GENERATED by --write, never hand-authored>"
      }
    }
  }
}
```

Constraints an implementer applies mechanically:

- **The registry key is the feed's path relative to its patch dir**, which is a bare filename
  today. No key may contain a path separator (3.1).
- **No `size`, `bytes` or whole-file digest column, ever** (1.1, third instrument failure).
- **`carried_from` is a fact, not a convention.** It is the OLDEST dir of the maximal
  CONTIGUOUS run of identical `body_md5` CONTAINING this dir, and null when this dir is that
  oldest one. `run_len` is the FULL length of that run and is therefore the same value on
  every row of the run. Both come from one computation, which is what stops `run_len` and
  `FROZEN_UPSTREAM`'s "identical across 3+ dirs" from being independently derivable and
  independently wrong. This is well-defined only because the measured equality graph has zero
  non-contiguous reverts (1.1); **if a revert ever appears the tool must raise, not guess.**
  Worked instances: `wiki_stats.json` (`bef0ae84` x4) has `carried_from = null, run_len = 4`
  at 16.11.1 and `carried_from = 16.11.1, run_len = 4` at 16.12.1 / 16.13.1 / 16.14.1;
  `champions.json` (`4975bcd2` x2) has `carried_from = null` at 16.13.1 and `16.13.1` at
  16.14.1 with `run_len = 2`; `arena_augments.json` has `run_len = 2` over 16.10.1 / 16.11.1
  then `run_len = 1, carried_from = null` from 16.12.1 on.
- **`fetch_evidence` is COMPUTED, never a raw timestamp compare.** `advanced` = this dir's
  time value differs from the predecessor's; `identical` = they are equal; `absent` = either
  side is unavailable (the feed has no `time_field`, or is not in the manifest `outputs`
  block). Every rule that reasons about fetching consumes this, never the raw values. This is
  what closes revision 1's unsoundness (1.5 item 2).
- **The `note` is machine-generated by `--write`** from fields already in the row, using this
  exact template, so it regenerates deterministically and cannot go stale:
  `"<CLASS>: body identical to <carried_from> since <carried_from> (run_len=<n>);
  declared_patch=<declared_patch>; fetch evidence <fetch_evidence>."` (drop the clauses that
  do not apply).
- **The `rationale` is the human gate**, keyed by `(feed, class)` in the REGISTRY half, not
  per row. A note answers "why is this feed in this class", which is a per-feed fact; the same
  sentence attached to 2-4 rows is copy-paste that drifts independently. **Measured: 24 of the
  67 frozen rows require an explanation and they collapse to exactly 11 `(feed, class)`
  pairs** (4.1).

### 3.5 The classification ladder - 13 classes, total, measured at 0 fall-through

**DESIGN CORRECTION.** Revision 1's 7 rules were not total. Implemented literally against the
real tree, **14 of 67 frozen rows (21 percent) fell through** - 6 at 16.10.1
(`arena_augments`, `champions`, `enchanter_items`, `items`, `manifest`, `scenarios`), 7 at
16.11.1 (`build_orders` x3, `cdragon_ability_ratios`, `cdragon_ratio_drift`,
`cdragon_spell_stats`, `pickban_targets`), plus one MID-HISTORY row no auditor predicted
(`arena_augments@16.11.1`). Six more landed in classes revision 1 said it had designed out.

Notation for the ladder. `D` = this dir. `P` = the newest walked dir < `D` containing this
feed, null at first appearance. `moved` = `body_md5 != P`'s `body_md5`. `ev` = the row's
`fetch_evidence`. `run` = the maximal contiguous run containing `D` (3.4). `newest` = the
newest dir in the CURRENT SCOPE (16.13.1 for the lock).

Evaluated top to bottom, first match wins:

**TIER A - within-row rules, evaluated before everything.**

| # | Class | Condition |
|---|---|---|
| A0 | `SKIPPED_FETCH` | `origin == fetched` and `moved` is false and `ev == identical` |
| A1 | `PATCH_STAMP_MISMATCH` | `origin != authored` and `stamp_field` is set and `declared_patch != D` |

**TIER B - the base case revision 1 had no rule for.**

| # | Class | Condition |
|---|---|---|
| B | `BASELINE` | `P` is null - this feed has no predecessor inside the walk scope |

**TIER C - branched by `origin`, so every rule has a defined domain.**

| origin | Class | Condition |
|---|---|---|
| authored | `STAMP_UNMAINTAINED` | `moved` and the stamp did not move |
| authored | `AUTHORED_EDITED` | `moved` and the stamp moved |
| authored | `AUTHORED_STABLE` | not `moved` |
| derived | `HEALTHY` | `moved` |
| derived | `DERIVED_NOT_REGENERATED` | not `moved` - the generator did not re-run |
| fetched | `HEALTHY` | `moved` |
| fetched | `CARRY_UNVERIFIABLE` | `ev == absent` |
| fetched | `STATIC_CONFIRMED` | `pinning == pinned` |
| fetched | `FROZEN_UPSTREAM` | `run_len >= 3` and `newest` is inside `run` |
| fetched | `RESTAMPED` | `stamp_field` set and the stamp moved vs `P` |
| fetched | `UNCHANGED_UPSTREAM` | else |

**Three precedence choices are load-bearing and all three are corrections:**

1. **`BASELINE` is a fact, not a defect** - first observation, no note required. But
   `PATCH_STAMP_MISMATCH` does not need a predecessor and is evaluated BEFORE it, so a
   first-appearance row carrying a bad stamp is still caught. On today's data no
   first-appearance row has a stamp mismatch, so all 19 land on `BASELINE`.
2. **`SKIPPED_FETCH` outranks `PATCH_STAMP_MISMATCH`** because the stamp is DOWNSTREAM of the
   fetch - re-fetching fixes both, so leading with the stamp verdict points the reader at the
   wrong remediation. Verified this does not weaken instance 2: `cdragon_ability_ratios` has
   no timestamp, so `ev == absent`, so `SKIPPED_FETCH` cannot fire, and
   `PATCH_STAMP_MISMATCH` still catches it.
3. **`CARRY_UNVERIFIABLE` outranks `STATIC_CONFIRMED` and `FROZEN_UPSTREAM`**, so a feed with
   no fetch evidence is never exonerated.

`COPIED_FORWARD` is RETIRED. It is split into `SKIPPED_FETCH` (positive evidence of no fetch)
and `CARRY_UNVERIFIABLE` (no evidence either way), because the single class conflated a
finding with an evidence gap and, on the raw-timestamp test, swallowed half the inventory.

**Measured result: 67 of 67 frozen rows and 87 of 87 five-dir rows classify, 0 fall-through.**

| class | frozen rows (67) | all five dirs (87) |
|---|---|---|
| `HEALTHY` | 21 | 31 |
| `BASELINE` | 19 | 20 |
| `FROZEN_UPSTREAM` | 6 | 8 |
| `SKIPPED_FETCH` | 6 | 8 |
| `PATCH_STAMP_MISMATCH` | 5 | 5 |
| `CARRY_UNVERIFIABLE` | 4 | 7 |
| `AUTHORED_STABLE` | 2 | 2 |
| `RESTAMPED` | 2 | 2 |
| `STAMP_UNMAINTAINED` | 1 | 2 |
| `UNCHANGED_UPSTREAM` | 1 | 1 |
| `STATIC_CONFIRMED` | 0 | 1 |
| `AUTHORED_EDITED` | 0 | 0 |
| `DERIVED_NOT_REGENERATED` | 0 | 0 |

All six of the spec's required day-one verdicts are preserved and were re-verified against
this ladder: instance 2 `cdragon_ability_ratios@16.12.1` -> `PATCH_STAMP_MISMATCH`; instance 3
`enchanter_items@16.13.1` -> `STAMP_UNMAINTAINED`; 1.4 `cherry_augments@16.12.1` and
`mayhem_augment_stats@16.12.1` -> `SKIPPED_FETCH` (the class now NAMES the finding, where
revision 1's ladder masked it under `PATCH_STAMP_MISMATCH`); instance 1
`items_meraki@16.13.1` -> `FROZEN_UPSTREAM`; and `champions.json@16.14.1` ->
`STATIC_CONFIRMED`.

**The `champions.json` false positive is killed here for the first time.** Revision 1 claimed
its design killed it; measured, revision 1's own ladder classified `champions.json@16.14.1`
as `COPIED_FORWARD`, a pure false positive, because the feed has no timestamp and
`null == null` satisfied rule 3. It is `pinned` + evidence-inherited-from-manifest that kills
it, not "pinned + identical body" alone.

**`AUTHORED_EDITED` and `DERIVED_NOT_REGENERATED` are belt-only** - unexercised by today's
data, and each carries a mechanical RED-first setup in 6.1 so a later reader does not delete
them as dead code. `cdragon_ratio_drift.json` is the only derived copy-forward in history and
it is caught one tier earlier by `PATCH_STAMP_MISMATCH`, which is exactly why the derived body
rule is currently unexercised - and exactly why the belt is worth keeping.

`NOTE_EXEMPT = {BASELINE, HEALTHY, STATIC_CONFIRMED, AUTHORED_STABLE, AUTHORED_EDITED,
UNCHANGED_UPSTREAM}`. Every other class requires a resolvable `(feed, class)` rationale.

### 3.6 CI wiring is load-bearing, not a formality

Verified: `ci.yml:36` gates the `nightly-full-suite` job to
`github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'`, and
`pytest tests/ agents/daemon_slayer/tests/` appears exactly once, at `:58`, inside it. The
per-push `check` job (`:60`, `if: github.event_name != 'schedule'`) runs only named targets:
`:136` (three hygiene files), `:140-144` (`phase2_smoke`, `snapshot_regressions`,
`phase8_smoke`, `fu02_team_context`), `:148` (`snapshot_panels/`).

A test dropped into `tests/` without the ci.yml line is **nightly-only**. LEDGER item 958
records the nightly RED for 12 consecutive days with the root cause stated verbatim: "the push
`check` job is green BY CONSTRUCTION". There is no failure-notification step in `ci.yml`.
Append `tests/test_ds_feed_lock.py` to the `:140-144` invocation. The guard is pure stdlib so
it runs under the `check` job's minimal deps, and it hashes the 67-row lock scope in **0.68 s**
(the 87-row walk scope in 0.87 s), comfortably inside the job's `timeout-minutes: 10` at `:64`.

### 3.7 `FROZEN_FIXTURES` extension - read the file's own ruling first

`tests/test_ds_fixture_policy.py:25` is `FROZEN_FIXTURES = ("16.10.1", "16.11.1")` and `:26`
is `RETIRED_FIXTURES = ("16.9.1",)`. Extend `FROZEN_FIXTURES` to all frozen dirs (16.10.1,
16.11.1, 16.12.1, 16.13.1). Note two things the panel got wrong:

- The file's docstring carries a dated 2026-06-11 ruling that these dirs exist for TEST PINS
  and that "The live patch dir ... is NOT a fixture - it moves on every patch refresh." Do NOT
  add the live dir to the tuple, and do NOT overload the tuple's stated purpose - add a
  comment naming the lock as a second consumer.
- The deletion fear is partly unfounded: `tools/ddragon_mirror_refresh.py` prune is scoped to
  the web mirror and never touches `data/daemon_slayer/`. This is cheap insurance against
  manual deletion, not a live threat.

That file asserts only dir EXISTENCE and retired-dir absence (`:29-45`,
`test_frozen_fixture_dirs_present` and `test_retired_fixture_dirs_stay_gone`), never content
immutability - which is why test 7's remediation in 6.1 is fixture-policy-neutral.

`RETIRED_FIXTURES` already exists, so the repo has a tombstone concept. The lock schema must
be able to express a retired dir before the first prune, not after: a dir listed in
`RETIRED_FIXTURES` is skipped by the lock walk.

---

## 4. PHASING

### 4.1 PHASE 1 - lock + guard over the frozen dirs. Hours, no network.

**Scope decision that makes this survivable: lock the FROZEN dirs, not the live dir.**

Measured with the canonical instrument, replaying every commit touching
`data/daemon_slayer/16.14.1/` since the dir was created: baseline `21db5626` (2026-07-16, 19
new feeds) plus five post-baseline commits, of which **4 would red a live-dir lock**:

```
2dddff04  touched 1   canonical-MOVED 0   adds ability_staleness.json  -> reds test 3
544d6362  touched 5   canonical-MOVED 5   build_orders x3, cdragon_ability_ratios, cdragon_ratio_drift
b7d7096f  touched 1   canonical-MOVED 1   enchanter_items.json
43a2e0ea  touched 3   canonical-MOVED 1   build_orders_arena.json only
843f83a3  touched 3   canonical-MOVED 0   CANONICALLY INERT (generated_at only)
```

**Two revision-1 auditors reported this as "5 of 5" and were both wrong, for the same
reason: they counted files TOUCHED while the lock hashes canonical BODIES.** `cde08721`
reports "3 files changed, 3 insertions(+), 3 deletions(-)" and moves zero canonical bodies -
`build_orders_sr` is `9c0a2d99` before and after. `91664dbf` touched three build_orders files
and moved one. Revision 1's "4 of 5" and its named file list were correct, and the
disagreement is itself a demonstration of this spec's central thesis: a file-touch count and a
canonical-body count give different answers, and only one of them is the question.

So: a lock over the live dir reds 4 times in 3 days on ordinary work, and every red's
remediation is `--write; git commit` - the rubber stamp, trained in week one. Meanwhile each
dir goes quiet once it stops being current (16.10.1 last touched 2026-05-30, 16.11.1
2026-06-06, 16.12.1 2026-06-18, 16.13.1 2026-07-12). The lock is tamper-evidence over the
irreplaceable history and it never reds on ordinary work. The live dir gets a `--report` plus
three mechanical assertions that cannot false-positive (6.1 tests 6, 8, 13).

**Deliverables:**

1. `tools/ds_feed_lock.py` with the 20-row registry of 3.3 transcribed, covering all 20
   REGISTRY-SCOPE feeds (19 lockable plus `ability_staleness.json`, which is live-dir-only).
2. `data/daemon_slayer/feed_lock.json` generated over 16.10.1..16.13.1: **67 rows, of which 24
   are non-exempt, carrying machine notes generated by `--write` (zero human cost) and
   resolving to exactly 11 hand-authored `(feed, class)` rationales.** The exhaustive list, so
   nobody has to derive it:

   ```
   cdragon_ability_ratios.json  PATCH_STAMP_MISMATCH  (2 rows: 16.12.1, 16.13.1)
   cdragon_ratio_drift.json     PATCH_STAMP_MISMATCH  (2 rows: 16.12.1, 16.13.1)
   cdragon_spell_stats.json     PATCH_STAMP_MISMATCH  (1 row:  16.12.1)
   champion_abilities.json      FROZEN_UPSTREAM       (3 rows: 16.11.1, 16.12.1, 16.13.1)
   cherry_augments.json         SKIPPED_FETCH         (3 rows: 16.11.1, 16.12.1, 16.13.1)
   enchanter_items.json         STAMP_UNMAINTAINED    (1 row:  16.13.1)
   items_meraki.json            FROZEN_UPSTREAM       (3 rows: 16.11.1, 16.12.1, 16.13.1)
   mayhem_augment_stats.json    SKIPPED_FETCH         (3 rows: 16.11.1, 16.12.1, 16.13.1)
   scenarios.json               RESTAMPED             (2 rows: 16.11.1, 16.12.1)
   wiki_ability_stats.json      CARRY_UNVERIFIABLE    (2 rows: 16.12.1, 16.13.1)
   wiki_stats.json              CARRY_UNVERIFIABLE    (2 rows: 16.12.1, 16.13.1)
   ```

   Nine of the 11 are already written as prose in sections 1.2, 1.3 and 1.4 and can be
   transcribed rather than researched. Revision 1 priced this as "a written note on every
   non-HEALTHY row" over "4 dirs x ~19 feeds", which an auditor reasonably read as up to 67
   retroactive prose fields. The reduction to 11 comes from three things, all schema
   decisions rather than estimate revisions: the `BASELINE` exemption (19 rows), the machine
   note absorbing the per-row obligation, and `(feed, class)` keying (24 rows -> 11 strings).
   Extending the lock to the live dir would add exactly one pair
   (`cdragon_spell_stats.json` / `CARRY_UNVERIFIABLE`).
3. `tests/test_ds_feed_lock.py` (6.1).
4. The 1-line `ci.yml` edit (3.6) and the 1-line `FROZEN_FIXTURES` edit (3.7).
5. `core/build_planner/champ_kit_data.py` patch-guard (~6 lines). **Measured
   output-neutral today**: the sidecar's declared patch already equals its directory at
   16.14.1 (`{'patch': '16.14.1', 'patch_segment': '16.14'}`), so the new guard cannot change
   any current build-planner result. It only becomes live on a future copy-forward, which is
   the point.
6. The nine doc-sync riders from 2.7, the ADR from 2.5, and the
   `DECISION_cdragon_cross_reference.md` status flip.

**Verification set - stated explicitly instead of as a tier label.** Revision 1 said "Tier-1
by R5" while spanning 8 files across 6 trees, and titled a section "Lock schema" while
`CLAUDE.md:85` lists `schema` as a Tier-2 trigger. Ruling:
`CLAUDE.md:85`'s trigger list (`schema / engine / scorer / item-effect / ENGINE_VERSION`) is a
DS-ENGINE list whose prescribed remedy is the dual suite plus a `:8893` restart plus a Share
mirror sync, and `CLAUDE.md:151` pairs `schema` with `engine version bumps` and `item-effect
additions`. `feed_lock.json` is a tools-layer artifact schema with no engine consumer, no
scorer, no `ENGINE_VERSION` and no Share presence, so it does not trigger Tier-2. It is also
not a bare Tier-1, since `CLAUDE.md:84` scopes that to one module. Run exactly:

```
py_compile  tools/ds_feed_lock.py  core/build_planner/champ_kit_data.py
pytest      tests/test_ds_feed_lock.py  tests/test_ds_fixture_policy.py
pytest      the build_planner module's own tests   (champ_kit_data.py is the one Phase-1
                                                    edit that can alter engine output)
python      tools/ds_share_sync.py --check
pytest      the ci.yml:136 hygiene trio            (the slice adds .md and .json)
```

No `ENGINE_VERSION` bump, no `:8893` restart, no dual suite.
Cost: one session.

**GATE (all four must be observed, not assumed):**

- **(a) The guard must be proven to run PER PUSH, and the proof must be runnable locally.**
  Revision 1's "push and observe the check job go red" is not a check with an unambiguous
  local pass/fail. Split:
  - **(a1) STATIC, in-test.** `tests/test_ds_feed_lock.py` parses
    `.github/workflows/ci.yml`, locates the job named `check`, and asserts the literal
    `tests/test_ds_feed_lock.py` appears in one of that job's `run:` blocks. Deterministic,
    and it tests the property gate (a) actually cares about (per-push versus nightly-only).
    Precedent exists in-tree: `tests/test_bare_py_ban.py` already parses `ci.yml` (`:26`
    comment: "ci.yml multi-file pytest lines are legitimate").
  - **(a2) LOCAL MUTATION PROOF.** Hand-mutate one locked `body_md5`, run the exact command
    copied out of the check job's `run:` block, observe **exit 1**; revert, observe **exit 0**.
    Record both exit codes in the commit message.
  - **(a3) OPTIONAL.** The real push. Not required once (a1) and (a2) pass, and it costs a
    deliberate red run on main.
- **(b)** Hide a `*.json` from the walk and confirm the coverage assertion fails - no
  exit-0-having-compared-nothing.
- **(c) Assert SETS and a RATIO, never bytes.** Confirm
  `test_walk_excludes_non_feed_semver_dirs` and `test_walk_is_not_recursive` both pass. The
  first asserts the walked dir-name set equals
  `['16.10.1','16.11.1','16.12.1','16.13.1']` and that no walked path contains
  `laning_scenarios` or `build_orders`; the second asserts
  `shallow_bytes < 0.25 * recursive_bytes` (measured 11.4% on 2026-07-19). **No absolute byte
  figure is pinned anywhere in this spec's gates.** Revision 1's exact-size gate was
  unsatisfiable on two independent counts: its unit was ambiguous (MiB quoted, MB measured),
  and the CRLF finding in 1.1 means the same walk measures 57.69 MiB on Legion and 55.82 MiB
  in a Linux CI checkout, a 3.4% gap that grows with line count and that no literal or
  tolerance band can straddle. For orientation only, never asserted: lock scope 67 files /
  45.7 MiB, walk scope 87 files / 57.7 MiB on Legion, both hashing in under 1 s.
- **(d)** `python tools/ds_share_sync.py --check` green, confirming root-level placement is
  Share-neutral (3.2). Because test 7 is scoped to frozen pairs (6.1), no Phase-1 remediation
  touches the mirrored `16.14.1` dir, so this gate runs once and the slice needs no Share
  re-sync. **The live dir's `enchanter_items.json` stamp remains wrong and is reported by
  `--report`, not asserted** - it gets fixed at the next patch refresh, where a Share sync
  happens anyway as part of the refresh ritual. This is listed as a deferred item in section 8.

### 4.2 PHASE 2 - value corroboration. The only thing that catches instance 1.

Gated on Phase 1 landing green. Cost ~1 session, Tier-2 (touches `agents/daemon_slayer/`):
full dual suite + Share mirror in the same commit. No `ENGINE_VERSION` bump - default output
is byte-identical.

Population, counted by `^    "\d+":` entries across `agents/daemon_slayer/_item_*.py` and
`_rune_*.py`: 278 total, of which `_item_ability_haste.py` holds 220 already wholesale-covered
by `tests/test_item_ability_haste_ddragon_sync.py`. **58 uncovered values across 14 modules:**

```
_item_bonus_hp_amp 2   _item_general_dr 2   _item_health_stack 2
_item_lowhp_magic_crit 2   _item_mana_health 6   _item_omnivamp 2
_item_resist_grants 8   _item_revive 2   _item_spell_shield_overrides 5
_item_survival_window 4   _item_tenacity 17
_rune_health_grants 2   _rune_hsp_amp 1   _rune_resist_grants 3
```

**ANNOTATION versus REMEDIATION - the split that dissolves revision 1's self-contradiction.**
Revision 1 fixed the population at 58 with `_item_tenacity`'s 17 inside it, and simultaneously
asked in Section 9 whether those 17 belong. Two different activities were sharing one word:

- **ANNOTATION** - attaching a `Src` to each of the 58. All 58 are annotated in Phase 2,
  tenacity included. The population line stands unchanged.
- **REMEDIATION** - fixing values whose rendered literal does not match the feed. Unbounded,
  and this is what the question was actually about.

Under the value-rendered-template design below, **annotating IS verifying**, so the 17
tenacity values get re-checked for free rather than needing a separate re-parse project.
Sizing rule an agent applies without asking: **if `_item_tenacity` produces more than 3 render
failures, spin the REMEDIATION of that module into its own slice and land Phase 2 with those
17 rows marked `SINGLE_SOURCE` pending; the annotation still ships in Phase 2.**

Each of the 14 modules gains three module-level containers, **parallel dicts, not a wrapped
value type**. The registries are read on hot paths inside per-item loops, so wrapping forces
`.value` unwrapping across `ehp.py` and `hybrid.py` and converts a documentation feature into
an engine change.

**DESIGN CORRECTION - one `_SOURCES` dict cannot hold five kinds.** Three of revision 1's five
kinds are structurally incompatible with the two-directional key parity it called
load-bearing. `EXCLUDED` asserts an id is ABSENT from the value dict, i.e. a `_SOURCES` key
with no value key. `JUDGEMENT`'s own exemplar, `_ASSUMED_PROCS_BY_LEVEL` at
`agents/daemon_slayer/_item_health_stack.py:106`, is a module-level `tuple[float, ...]` of
cumulative proc counts indexed by champion level - **it carries no item id at all**, so it can
never be a key in a parity-locked dict under any spelling, and it is not one of the 58 (the
counting regex cannot see it). Three containers:

1. **`_SOURCES: dict[str, Src]`** - key set IDENTICAL to the value dict, both directions,
   **ZERO exemptions**. Holds only `DERIVED` / `INHERITED` / `SINGLE_SOURCE`.
2. **`_EXCLUDED: dict[str, str]`** - id -> reason. Asserted DISJOINT from the value dict.
3. **`_JUDGEMENT: dict[str, str]`** - CONSTANT NAME -> reason, e.g.
   `{'_ASSUMED_PROCS_BY_LEVEL': 'operator-tuned proc curve; no upstream states a proc
   count'}`. Asserted only for non-emptiness and that the name resolves via `getattr`. Never
   key-parity-checked against any value dict.

This is chosen over a key-parity exemption set because an exemption set is a permanent hole in
exactly the assertion 6.2 test 2 calls load-bearing, and it grows with every future `EXCLUDED`
id. The split keeps test 2 at full strength AND makes test 5 a clean one-liner, so both get
stronger rather than trading off. All five kind NAMES stay in the vocabulary; `EXCLUDED` and
`JUDGEMENT` are expressed by container membership rather than by `Src.kind`.

**The `Src` record:**

```python
@dataclass(frozen=True, slots=True)
class Src:
    kind: str                             # DERIVED | INHERITED | SINGLE_SOURCE
    feed: str | None = None               # 'items.json' | 'items_meraki.json'
    literal_template: str | None = None   # contains exactly one '{v}'
    value_path: str = ''                  # '' = the value itself; '0'/'1' = tuple index;
                                          # attribute name for dataclass values
    render: str = 'unit_pct'              # unit_pct | num_pct | num
    base_id: str | None = None            # INHERITED only
    note: str = ''                        # prose, never asserted
```

Per-kind required-field contract, asserted by the checker:
- `DERIVED` - `feed='items.json'`, `literal_template` set, `base_id` None.
- `INHERITED` - `base_id` set AND present in the same module's value dict; `feed` and
  `literal_template` None. This is what 6.2 test 4 (`223084 == 3084`) reads; revision 1's
  3-field signature had no field to hold it.
- `SINGLE_SOURCE` - `feed='items_meraki.json'`, `literal_template` set.

`value_path` is required because the registries are NOT uniformly `dict[str, float]`:
`_item_resist_grants` values are `ItemResistEntry` dataclasses and `_item_omnivamp` /
`_item_general_dr` values are tuples, so a bare `{v}` cannot address the number. Measured
value shapes: `_item_tenacity` `('1111','30.0')` percent-as-number, `_item_resist_grants`
`('6665','ItemResistEntry(')` dataclass, `_item_survival_window` `('3157','2.5')` plain number,
`_item_omnivamp` `('4633','(0.10')` tuple, `_item_general_dr` `('3869','(0.35')` tuple.

**DESIGN CORRECTION - the Phase-2 GATE could not fire as revision 1 designed it.** This is the
structural hole, not a wording problem. `corroborating_literal` was a hand-authored constant
that the checker compares to the FEED and never to the PINNED VALUE. Reconstruct the pre-R137
`0.08` Heartsteel pin, leave the literal alone, and the checker reads GREEN: DDragon says 10%,
the hand-copied literal says 10%, substring present, pin never consulted. So
`test_heartsteel_pre_r137_pin_is_rejected` - the spec's own held-out validation and its stated
GATE - was unreachable, and Phase 2 as written would have shipped without catching its
founding defect.

**Corrected: RENDER the literal FROM the pinned value.** The checker computes

```
literal = literal_template.format(v=RENDER[render](select(value, value_path)))
```

and asserts `literal` is a substring of the NORMALIZED feed record. Value and literal then
cannot drift apart by construction. The "exact substring, no regex over marketing prose"
constraint survives intact - the match is still an exact substring, merely rendered from the
pin rather than copied beside it. `RENDER` is a closed 3-entry enum:
`unit_pct` (0.10 -> `'10%'`), `num_pct` (30.0 -> `'30%'`), `num` (2.5 -> `'2.5'`).

Proven by mutation against `data/daemon_slayer/16.14.1/items.json`, template
`'grants {v} of the damage as max Health'`:

```
pin 0.10 -> 'grants 10% of the damage as max Health'  present=True
pin 0.08 -> 'grants 8% of the damage as max Health'   present=False
pin 0.12 -> 'grants 12% of the damage as max Health'  present=False
```

Reproduced on two more ids: Warmog 3083 `'equal to {v} of your Item Health'` (0.12 True /
0.10 False), and Awe 3119 against the FROZEN Meraki feed `'equal to {v} bonus mana'`
(0.15 True / 0.08 False).

**DESIGN CORRECTION - "EXACT substring" is unimplementable against the RAW records, and both
of revision 1's worked examples prove it.** It quoted DDragon 3084 as
`grants 10% of the damage as max Health` and Meraki 3119 as
`Grants bonus health equal to 15% bonus mana.`. Neither is a substring of the record it cites:

```
raw DDragon 3084:  ...and grants <scaleHealth>10%</scaleHealth> of the damage as
                   <scaleHealth>max Health.</scaleHealth>
raw Meraki  3119:  "effects": "Grants {{as|'''bonus''' health}} equal to
                   {{as|15% '''bonus''' mana}}."
```

Both quoted strings are RENDERED forms read off a viewer. As written, 6.2 test 3 fails on day
one for every row, as a broken checker rather than an intended RED.

**Feed normalization (exact) - part of the checker, pinned by its own test:**

- **DDragon** - take `record['description']`, apply `re.sub(r'<[^>]*>', '', d)`, then
  `re.sub(r'\s+', ' ', d).strip()`.
- **Meraki** - for each entry in `record['passives']`, take `['effects']`, apply
  `re.sub(r'\{\{[a-z]+\|([^}|]*)(\|[^}]*)?\}\}', r'\1', e)`, then `.replace("'''", '')`, then
  whitespace-collapse; join as `'Name: text'` with `' | '`.

**Implementer warning, carry it into the docstring:** tag-stripping deliberately concatenates
across removed tags (`'900 Health100% Base Health Regen'`). Do NOT "fix" that by inserting
spaces - every template in this spec was verified against this exact pipeline and inserting
spaces breaks them.

Reword rate is affordable, measured across the five vendored dirs: of the 35 scheme item ids,
only 3 had ANY DDragon description text change (3084, 4645, 223091) and only 1 had a changed
percent-set - the real Heartsteel 8 -> 10. Roughly 0.25 findings per patch.

**Three `Src` kinds, each with a distinct machine action:**

- **`DERIVED`** - the rendered literal is present in DDragon `items.json` at `current.txt`'s
  dir. Asserted. Fails CI.
- **`INHERITED`** - a mode-mirror of a base id. Asserts `mirror == base`. Patch-independent,
  self-checking, needs no upstream. The most rot-proof rule in the spec, and it is the ONLY
  possible kind for the Arena mirrors, which are absent from Meraki entirely (probed: 223084,
  443083, 223119, 323119 all `in_meraki=False`).
- **`SINGLE_SOURCE`** - only the frozen Meraki feed carries it. **Split into two questions
  that revision 1 conflated under one non-blocking label.** The FRESHNESS question (this
  value's only witness is a dead feed) stays counted and never blocking, as intended. The
  TRANSCRIPTION question (does the pinned number match what that feed says) is **BLOCKING**,
  because the feed is vendored and frozen, so the assertion is perfectly deterministic and can
  only fail if someone edits the pin or the vendored bytes. This matters because instance 1's
  stated mechanism is a human transcribing a number out of JSON, and the transcription check
  is the only part of Phase 2 that guards that mechanism for Meraki-witnessed values.

`EXCLUDED` and `JUDGEMENT` remain as container membership, per the three-container split.

**Day-one finding, verified, and the reason this is not paperwork.** Probing
`data/daemon_slayer/16.14.1/items.json`: normalized DDragon percentages for the six Awe ids
are 3119 `[]`, 3121 `['80%']`, 223119 `[]`, 223121 `[]`, 323119 `[]`, 323121 `['80%']` - no id
yields 15%, and 3121's only percentage is the Empowered Shield 80%. The `0.15` pinned for all
six Awe ids in `_item_mana_health.py` is witnessed ONLY by `items_meraki.json`
(`"Awe", "effects": "Grants bonus health equal to 15% bonus mana."`), the frozen feed, cited
at `_item_mana_health.py:30` to the 16.13.1 dir. That is the Heartsteel risk shape sitting in
the tree right now with no guard naming it. Phase 2 classifies it `SINGLE_SOURCE`, asserts its
transcription against the vendored bytes, and counts its freshness. It does NOT change the
value.

**GATE - a two-exit-code observation, not an impression.** Reconstruct the pre-R137 `0.08`
Heartsteel pin, run the checker, assert **exit 1** AND that the failure message names id
`3084`; restore `0.10`, assert **exit 0**. Both exit codes go in the commit message alongside
the `SINGLE_SOURCE` count. Use LEDGER item 953's own technique - mutation-test the checker
rather than trusting a green run. That item records, verbatim at `docs/LEDGER.md:68`:
"`Share/README.md` sat 72 minors stale at 1.149.0 while `--check` read green" and "A guard
that has never been shown to go red is not a guard." (A revision-1 auditor reported this
citation as unverifiable; it grepped the spec's paraphrase "72 stale" rather than the LEDGER's
"72 minors stale". **The citation is sound and must not be "corrected".**)

### 4.3 PHASE 3 - citation vintage ratchet, DRIVEN BY THE LOCK

`tests/test_source_citation_patch.py`, modeled on the already-passing
`tests/test_ddragon_path_version_drift.py` which bans versioned paths in live JS and was
simply never extended to Python.

**DESIGN CORRECTION - the rule shape was structurally wrong, not merely undecided.** Revision
1 framed Phase 3 as a choice between a provenance-keyword heuristic and a hand-maintained
allowlist, and made neither. **Both branches are the wrong mechanism**, because both try to
infer from PROSE whether a line is a provenance citation, when the answer is already computed
elsewhere in this same spec. Phase 1 builds `feed_lock.json`, which contains `body_md5` per
`(dir, feed)`. **That artifact IS the severity oracle.**

The keyword branch is additionally proven to miss its own targets: revision 1 flags
`_item_bonus_hp_amp.py:39`, whose enclosing block opens `Mechanic:` at `:38` and matches no
listed keyword; same for `_item_mana_health.py:30` (block opens `Mechanic:` at `:29`); and
`_item_resist_grants.py:67`'s `confirmed` wraps across `:68-69` so a line-based match misses
it. Sibling sites DO match (`_item_omnivamp.py:24` "Source magnitude:",
`_item_bonus_hp_amp.py:57` "Registered ids"), so the keyword rule is not uniformly wrong - it
is unreliable, which is worse for a ratchet. Measured coverage: 6 of 9.

**The rule, computed:**

> A citation of `data/daemon_slayer/<P>/<feed>` is **ACTIONABLE** iff the canonical body at
> `<P>` differs from the canonical body at `current.txt`'s dir, and **INERT** otherwise.
> A citation naming a dir that is neither in the lock nor the live dir is ACTIONABLE
> (unresolvable provenance).

Implementation notes an agent applies without further design:
- The live dir is NOT in the lock (3.0), so the checker computes the live body hash at call
  time with the 1.1 instrument. This makes Phase 3 a genuine consumer of Phase 1's OUTPUT,
  which is a real phase dependency revision 1 did not have (it gated Phase 3 only on Phase 2's
  COUNT).
- The path regex must tolerate a line wrap between the dir and the filename; three in-tree
  citations wrap (`_item_revive.py:28`, `_item_resist_grants.py:67`, and one sibling).

**Measured over the full 26-site census: 6 ACTIONABLE, 20 INERT.**

```
ACTIONABLE  6   items.json sites          (uniq=5 - the body genuinely moves)
INERT       7   items_meraki.json         (73446cf8 x5)
INERT      12   champion_abilities.json   (96da30d8 x5)
INERT       1   champions.json            (4975bcd2 at both 16.13.1 and 16.14.1)
```

This clears the RM-81 bar (6 of 75) with a **computed** rather than asserted split, and it
resolves revision 1's largest uncovered class for free: `champion_abilities.json` spans 12
production sites across 5 patches (`ability_hps.py:375` at 16.11.1, `ability_hps.py:430` at
16.12.1, `cc_conditional.py:648` at 16.10.1, `kit_conversion.py:21` at 16.14.1,
`_passive_ally_grant_overrides.py:250` at 16.12.1, `_passive_as_overrides.py:28` and `:79` at
16.12.1, `_passive_damage_overrides.py:885` at 16.14.1, `_passive_health_overrides.py:30` at
16.13.1, `_per_spell_cc.py:284`, `:618` and `:700` at 16.10.1) and revision 1's two rules gave
it no verdict at all. It is materially INERT by measurement - a citation naming ANY dir returns
identical bytes - so it takes the vintage-marker rule, not the bump rule. Better still, its
vintage is machine-derivable: the feed carries `meraki_content_patch = '25.15'` as its own
field, so the required marker is "FROZEN at Meraki content patch 25.15", the identical marker
already in-tree at `_effects_data.py:762`. Mechanical for all 12 sites.

**Three rules, no either/or:**

1. **ACTIONABLE citations must name `current.txt`'s patch.** Fires today on the 6
   `items.json` sites: `_item_bonus_hp_amp.py:58`, `_item_general_dr.py:51`,
   `_item_mana_health.py:46`, `_item_omnivamp.py:31`, `_item_resist_grants.py:67`,
   `_item_revive.py:28`.
2. **INERT citations may name any patch but the enclosing docstring must carry the
   frozen-vintage marker.** Covers `items_meraki.json`, `champion_abilities.json` and
   `champions.json` uniformly. Target format exists in-tree at `_effects_data.py:762` and
   `_item_health_stack.py:20`.
3. **Dated history is never flagged.** Kept as an explicit narrow belt rather than left to
   emerge from the data, because today's INERT verdict for `champion_abilities.json` is a
   property of today's bytes: the day that feed moves, every dated-history line citing it
   becomes ACTIONABLE and would be wrongly flagged.

**The dated-history exemption is generated, keyed by tuple, and asserted closed.**
`tools/ds_feed_lock.py --write-citation-baseline` emits
`data/daemon_slayer/citation_baseline.json` containing
`(file_path, cited_patch, cited_feed)` tuples - **never line numbers**, so it survives line
drift. Today it holds exactly three entries: `ability_hps.py` / 16.11.1 /
`champion_abilities.json`, `ability_hps.py` / 16.12.1 / `champion_abilities.json`, and
`cc_conditional.py` / 16.10.1 / `champion_abilities.json`. The test asserts (a) every entry
still resolves to at least one matching line in that file, so a stale exemption fails loudly,
and (b) no NEW citation appears outside the baseline, matching the `precommit_gate` net-new
convention the spec already cites. This makes 6.3 test 3 a data assertion rather than a
heuristic, and it makes the ratchet auditable in the PR diff.

**Free rider, worth taking here:** `tools/ds_share_sync.py:62` is `_PATCH = "16.14.1"`, a
hardcoded literal in the one guard CI runs by name (`ci.yml:121-127`), whose own docstring has
already drifted to a different patch. Assert it equals `current.txt`. Same invariant, genuine
catch.

**GATE - bound to a number, because revision 1's "if the `SINGLE_SOURCE` count is small" is
unfalsifiable.** Build Phase 3 only if the Phase 2 `SINGLE_SOURCE` count is **greater than 3
OR at least one `SINGLE_SOURCE` id is rung-3-live**. Otherwise resolve those values by hand at
the next seam flip. The rung-3-live disjunct is not hypothetical: `_item_tenacity.py`'s 17
values are already live via `score_by='cc_blended'` (5.2 rung 3).

### 4.4 PHASE 1b - `data/meta_build/ddragon/`. Scoped and priced, not hand-waved.

Revision 1 excluded every non-`daemon_slayer` feed on the rationale "They have no directory to
contradict, so a dir-vs-dir invariant structurally cannot reach them". **That rationale is
factually false for one tree and must be replaced, not reworded.**
`data/meta_build/ddragon/{16.11.1,16.12.1,16.13.1,16.14.1}/` has exactly the
directory-name-as-provenance shape, holds 5 git-tracked files each, and is cited by PRODUCTION
at four different patches: `agents/daemon_slayer/rune_procs.py:10` and `:254` (16.11.1),
`enemy_runes.py:22`, `_item_ability_haste.py:37` and `core/build_order.py:90` (16.12.1),
`_rune_health_grants.py:24` and `hybrid.py:73` (16.14.1). It carries real runtime loaders
(`core/rune_wpa.py:82`, `core/summoner_spell_wpa.py:66`,
`agents/agent4_coach_mentor/analyzer.py:67`).

It is excluded from Phase 1 for a DIFFERENT and true reason: separate owner
(`tools/ddragon_mirror_refresh.py`, not `daemon_slayer_extract.py`), separate refresh cadence,
and a uniform kind - it is a pure DDragon mirror where every file is version-pinned, so it has
none of the mixed-origin classification problem that motivates the registry.

Logged as PHASE 1b with a stated trigger and a measured price: `tools/ds_feed_lock.py --tree
meta_build`, **20 rows, +34,626,308 bytes = 33.02 MiB of permanent retention obligation**
under accepted risk 5, walk code byte-identical to Phase 1's. **Trigger: Phase 1 green.** See
Section 9 Q3.

### 4.5 PHASE 4 - historical backfill. DEFERRED. Argue against it now.

DDragon retains 495 versions back to 2013 (~3.0 MB/patch, so ~15 MB for all five vendored
patches) and CDragon retains 228 numeric dirs back to 7.1. The capability is real and is not
at risk of expiring, so the option costs nothing to hold.

**Trigger:** a specific value trace bottoms out at 16.10.1 without resolving, i.e. it needs a
patch older than the oldest vendored dir. Do not pre-build. A bulk per-value cross-patch
materialization is exactly the large-artifact-that-reads-as-work failure.

---

## 5. NOISE CONTROL

RM-81 measured 75 drifted champions, 6 that move any ranked order, 2 that touch a top-5 item,
and 0 that change a recommended core build. A design that surfaces every diff at equal
severity reproduces that ratio.

### 5.1 The primary mechanism is structural: the artifact has no findings list

Phase 1 emits no per-value report. **The lock is exactly 67 rows** (16.10.1 holds 10 feeds,
the other three hold 19 each - not the "4 dirs x ~19" = 76 revision 1 arithmetic implied), and
the git diff of `feed_lock.json` at each refresh IS the report; in the normal case it is empty
because the lock covers frozen dirs only. `body_md5`, `carried_from`, `run_len`,
`fetch_evidence`, `class` and `note` are all computed, never authored. **The only human
writing is 11 `(feed, class)` rationales, authored once**, nine of which are already prose in
sections 1.2 / 1.3 / 1.4.

### 5.2 The actionable-vs-inert ladder, applied to values (Phase 2+)

Three rungs, all measured, all offline.

**Rung 1 - route reachability. The premise is corrected; the output is unchanged.**

Revision 1 asserted "`dps.py` and `ehp.py` import no ability module". **Grep falsifies that,
and the failure direction matters.** `dps.py` DOES import `.ability_dps` (function-level at
`:813` and `:1180-1181`). Because `apply_passive_damage` defaults TRUE on the production path
(`core/daemon_slayer_client.py:992` and `:1686`, `server.py:1239`), a reader who checked the
import claim, found it false, and concluded "the carry scorer does read ability data live"
would have wrongly deleted the whole rung. The premise was unsafe-side.

The correct invariant is one level lower - reachability of the VENDORED FEED, not of a module:

> A scorer is ability-feed-blind iff it neither constructs nor receives an
> `AbilitiesSnapshot`. Mechanical check: `grep -c 'AbilitiesSnapshot\|abilities_snapshot'
> <module>` is 0 AND every `compute_ability_dps` hit is a comment.

`dps.py` passes: `AbilitiesSnapshot`=0, `abilities_snapshot`=0, and all three
`compute_ability_dps` hits are comments (`:116`, `:327`, `:1171`). What it actually imports is
`rank_at_level` (`ability_dps.py:323`, pure rank arithmetic) and `_evaluate_block`
(`ability_dps.py:381`, a pure evaluator) - **neither takes a snapshot** - and it feeds them a
SYNTHETIC `DamageBlock` built from the HAND-AUTHORED `_passive_damage_overrides` registry
(whose docstring says "Why HAND-AUTHORED, not parsed"), never a feed record. Only
`compute_ability_dps` (`ability_dps.py:929`) takes a snapshot.

Per-module reachability table, which revision 1 omitted entirely:

| module | reads the vendored ability feed? |
|---|---|
| `dps.py` | NO - synthetic block, pure functions |
| `ehp.py` | NO - 0/0/0 |
| `hybrid.py` | **YES** - `from .ability_dps import compute_ability_dps` at `:43` (MODULE level), called at `:110` and `:199` |
| `burst.py` | YES |
| `onhit_dps.py` | YES - imports at `:19` |
| `hps.py` | YES, indirectly - `ability_hps_total` at `hps.py:359`, fed by `ability_hps.py:132` |

Adding `hybrid.py` is not a wording slip: bruiser is the second-largest stale cohort at 16
champions, and its absence from a section titled "route reachability" was a real hole.

Output, unchanged and independently reproduced: loading
`data/daemon_slayer/16.14.1/ability_staleness.json` (75 stale champions) and mapping each
through `core.build_order_precompute.archetype_for` gives mage 25, bruiser 16, carry 15, tank
10, assassin 5, onhit 2, enchanter 2. **carry 15 + tank 10 = 25 structurally unreachable**,
matching the `ROADMAP.md` `RM-81 data currency` row verbatim, i.e. 33.3% of champion-side
noise removed with certainty. Revision 1's "0.007s" microbenchmark is dropped - it is
dominated by module import cost and asserts nothing.

**Rung 2 - build membership. Demoted to a LABEL, and the unit is named.**

Item ids present in the committed `build_orders_{sr,aram,arena}.json`, read from
**`data/daemon_slayer/<current.txt>/`, resolved at call time, never a literal and never a
committed id list.** The checker prints the source dir and the id count beside every verdict.

Revision 1's "1557 cells" did not reproduce for an auditor who walked item-id slots and got
9342. **Both numbers are correct and count different things; the word "cell" was never
defined.** Definitions, now stated:

- **cell** = one `(mode, champion, variant)` build list. `3 modes x 173 champions x 3
  variants {ad_heavy, ap_heavy, balanced}` = **1557**.
- **item-id slot** = one of the 6 ids in a cell. `1557 x 6` = **9342**.
- Rung 2 tests membership in the DISTINCT-ID UNION only: **105 ids at 16.14.1, 111 at
  16.13.1**.

**That id set MOVES, which is why this rung is not CI-blocking.** Measured per-commit over the
live dir: `21db5626`=112, `dddbbdfa`=112, `e1b42e89`=105 (8 added, 15 removed in a single
commit), `6f7f957a`=105, `91664dbf`=105, `cde08721`=105. A pinned id list would have been
wrong within 3 days. A CI-blocking gate keyed to it would flip a value's severity - and
therefore CI status - on an unrelated engine bump, which is exactly the "reds on ordinary
work" failure mode Phase 1's scope decision exists to avoid.

Retrospectively validated on the only ground truth available: Heartsteel 3084/223084 are both
present (ACTIONABLE, and the one confirmed real defect), while `_item_mana_health`'s six Awe
ids are all absent (INERT).

**Rung 3 - seam reachability. THE PANEL GOT THIS WRONG AND THE CORRECTION IS UNSAFE-SIDE.**

Three of four proposals assert "every hand-seeded item registry is behind a default-OFF seam,
so a wrong value is latent". **That is false.** Verified at `agents/daemon_slayer/ehp.py:2765-2767`:

```python
apply_tenacity = (
    apply_build_tenacity if apply_build_tenacity is not None
    else (score_by == "cc_blended")
)
```

`_item_tenacity.py` holds **17 of the 58** - the largest registry in the scheme - and goes live
with no operator flip whenever `rank_items_by_ehp(score_by="cc_blended")` runs. Compounding:
`_item_tenacity.py:19-20` records the values as parse-seeded from 16.11.1 descriptions
("Values are the NOMINAL flat passive tenacity from each item's 16.11.1 description
(parse-verified, not hand-typed)") and `:31-33` prescribes a re-run on each patch bump
("Regeneration on a patch bump: re-run the description scan that seeded this") that
demonstrably did not happen for 16.12 / 16.13 / 16.14.

**Rule: derive the seam default by reading the resolution site in `ehp.py` / `hybrid.py`,
never by docstring grep.** The docstring-grep method is what produced the wrong answer.

### 5.3 Severity rule

**CI-BLOCKING only for a value that is rung-3-live.** Rung 2 is a severity LABEL reported in
the one-line summary, never blocking, for the id-set-instability reason measured above. Rung 1
removes champion-side noise before anything is reported. The checker prints the rung-2 source
dir and id count beside every verdict so a reviewer sees which population the label was taken
against.

**Honest limit, stated so it is not mistaken for a proof.** Rung 2 covers 105 ids while a
single archetype's rank pool is roughly 111 items. Build membership answers the core-build
question only; an item absent from every build can still move a ranked order. The inert bucket
is **unvalidated, not proven inert**, and Zhonya's Hourglass - a real top-5 mage item - is
build-inert. Say this in the checker's own output rather than letting a green read as a
clearance. (Note the numeric coincidence: the ~111-item rank pool figure and 16.13.1's
111-id build union are unrelated quantities that happen to collide. Do not conflate them.)

### 5.4 Noise sources designed out, each traceable to a measurement

1. **Live-dir churn** - the lock covers frozen dirs only. Removes all 4 measured
   canonical-body reds (4.1).
2. **Permanent false positive on hand-curated files** - `origin: authored` is exempt from
   stamp-equals-dir and gets body-moved-implies-stamp-moved instead. A dir-equality rule would
   flag `enchanter_items.json` on every run forever, which is the fastest way to get a guard
   ignored.
3. **Legitimate no-change** - `pinning: pinned` + identical body + inherited fetch evidence =
   `STATIC_CONFIRMED`, not a finding, unless the stamp also disagrees (tier A1). Verified to
   kill the false positive on `champions.json@16.14.1`, which revision 1's ladder did NOT
   (3.5).
4. **Formatting churn** - canonicalized JSON, so the `wiki_stats.json` 10,048-byte indent flip
   is invisible. The same canonicalization is what makes `cde08721` correctly read as inert
   (4.1).
5. **Machine churn** - no byte or whole-file-digest column, so the Legion/CI CRLF divergence
   cannot manufacture 67 phantom findings (1.1).
6. **Evidence gaps are named, not silently exonerated or blocked** - `CARRY_UNVERIFIABLE` is
   counted-only until the four sidecar extractors emit a timestamp (Section 9 Q1).
7. **Migration cost** - Phase 3 ships as a generated baseline ratchet, matching the
   `precommit_gate` net-new convention, over a census of 26 sites of which 6 are actionable.

**One deliberate REJECTION:** no max-age or staleness threshold on the Meraki vintage. Meraki
is dead, so any threshold fires forever, and a permanently red guard is a silenced guard. The
vintage is a label at the point of reading, not an alarm.

---

## 6. TEST PLAN - RED-first

Every test below must be observed FAILING before the fix, against the stated setup. Each names
the scope (3.0) it iterates.

### 6.1 `tests/test_ds_feed_lock.py` (Phase 1)

| # | Test | Scope | RED-first setup |
|---|---|---|---|
| 1 | `test_every_frozen_feed_has_a_lock_row` | LOCK | Delete one row from `feed_lock.json`. |
| 2 | `test_locked_body_hashes_recompute` | LOCK | Hand-mutate one `body_md5`. Also covers deletion of a locked dir. |
| 3 | `test_every_feed_has_a_registry_entry` | REGISTRY | Add an unregistered `*.json` to **ANY semver dir including the live one**. Revision 1 said "a frozen dir", which structurally could never see `ability_staleness.json` - the exact feed that arrived mid-cycle and would have needed catching. |
| 4a | `test_non_exempt_rows_carry_a_machine_note` | LOCK | Blank a generated `note`. Guards the generator; auto-satisfied by `--write`. |
| 4b | `test_every_non_exempt_pair_has_a_registry_rationale` | LOCK | Delete one `(feed, class)` rationale. Asserts a non-empty string **>= 40 chars** (blocks "n/a" and "see above") for each of the 11 pairs. This is the real human gate and it fires when a NEW class appears for a feed at a future refresh. |
| 5 | `test_walk_excludes_non_feed_semver_dirs` | LOCK | Assert the walked dir-name set equals the frozen set, that `laning_scenarios` and `build_orders` are absent by name, and that **no registry or lock key contains a path separator** (3.1). |
| 6 | **`test_live_dir_has_no_patch_stamp_mismatch`** | LIVE | **INSTANCE 2.** Assert no live-dir row classifies `PATCH_STAMP_MISMATCH`. **GREEN today** - verified over all 20 live feeds. RED-first: restore `data/daemon_slayer/16.13.1/cdragon_ability_ratios.json` (payload `"16.11.1"`, body `bb1fd9e2`) into the live dir and confirm failure. This is the generalized form of `abilities.py:448`. **Assert the CLASS, not a raw `declared_patch == patch_dir` comparison.** The raw form - which is what revision 1 specified - reds day-one on `cherry_augments` and `mayhem_augment_stats` (both carry `rc_patch = "16.10.1"` in the 16.14.1 dir) whose only remediation is a live network re-fetch that Phase 1 explicitly excludes. That is a permanently-red guard, which 5.4 rejects. The ladder already ranks those two as `SKIPPED_FETCH`, and test 8 surfaces them as a counted standing question. |
| 7 | **`test_authored_body_change_bumps_stamp`** | LOCK, adjacent FROZEN pairs only | **INSTANCE 3.** For `origin == authored`, body moved vs the previous dir implies the stamp moved. **Fails on today's tree at the 16.12.1 -> 16.13.1 boundary**: `enchanter_items.json` body `3b82292c` -> `c6f74cae` (item count 9 -> 10) with `_meta.patch` frozen at `16.9.1`. Remediation: bump `_meta.patch` to `"16.13.1"` in `data/daemon_slayer/16.13.1/enchanter_items.json`. That is HONEST (the file was genuinely curated in the 16.13.1 era by commit `b97abc1f`, 2026-07-10), SHARE-NEUTRAL (`ds_share_sync.py:62` pins `_PATCH = "16.14.1"` and `:256-260` rglobs only that dir; `Share/src/data/daemon_slayer/` holds only `16.14.1` and `current.txt`), LOCK-NEUTRAL (`_meta.patch` is a stripped stamp, so `body_md5` is unchanged), and FIXTURE-POLICY-NEUTRAL (3.7). **Revision 1 scoped this to the 16.13.1/16.14.1 pair, whose remediation edits a mirrored file and reds the per-push "DS Share package in sync" step the spec promises stays green.** |
| 8 | **`test_skipped_fetch_set_is_exactly_the_two_never_refetched_feeds`** | LOCK + LIVE | **The two unnamed instances (1.4).** Assert `fetch_evidence == 'identical'` implies `class == 'SKIPPED_FETCH'`, and that the `SKIPPED_FETCH` FEED set is exactly `{cherry_augments.json, mayhem_augment_stats.json}`. **Hardcodes no timestamp literal** - the two files do not share one (1.4), and revision 1's quoted literal is wrong for mayhem. Stays silent on `items_meraki.json` (five distinct `fetched_at`). Fully mechanical, 100% actionable rate on today's data, and it reds if a third feed ever joins. |
| 9 | `test_lock_covers_every_frozen_dir_on_disk` | LOCK | **META-GUARD, mandatory.** Assert the lock's dir set equals the on-disk frozen semver set minus `RETIRED_FIXTURES`, and that the row count is non-zero. Without this, a future "why hash four dirs" narrowing leaves tests 1-8 iterating an empty set and CI stays green with the cross-patch capability gone. LEDGER item 957: RC-GeminiAudit "exited 0 having written no review AND no log line" for 28 nights while every probe read the task as Ready. |
| 10 | `test_tool_default_tracks_current_txt` | LIVE | **META-GUARD.** Copy of the assertion in `tests/test_item_ability_haste_ddragon_sync.py`, which exists because `ops/audit/item_ah_drift_check.py` hardcoded `16.12.1` and false-reported IN SYNC, hiding the Eclipse 226692 drift for a full patch. |
| 11 | `test_feed_lock_runs_in_the_per_push_check_job` | n/a | **GATE (a1).** Parse `.github/workflows/ci.yml`, find the job named `check`, assert `tests/test_ds_feed_lock.py` appears in one of its `run:` blocks. RED-first: remove the pytest argument from `ci.yml:140-144`. Precedent: `tests/test_bare_py_ban.py` already parses `ci.yml`. |
| 12 | `test_root_feed_set_is_pinned` | n/a | Assert the on-disk `*.json` set directly under `data/daemon_slayer/` equals `root_feeds`, excluding the untracked `user_builds.json` (3.1). RED-first: drop a new `*.json` at the root. |
| 13 | `test_registry_source_urls_agree_with_manifest` | LIVE | For the 5 feeds `manifest.json`'s `outputs` block names plus the 2 that carry their own URL in the payload, assert the registry's `source_url` matches (3.3). RED-first: alter one registry URL. |
| 14 | `test_walk_is_not_recursive` | LOCK | **GATE (c).** Assert `shallow_bytes < 0.25 * recursive_semver_bytes` (measured 0.1141). RED-first: swap `iterdir()` for `rglob()`, taking the ratio to 1.000. |
| 15 | `test_authored_edit_with_stamp_bump_is_clean` | LOCK | **Belt for the unexercised `AUTHORED_EDITED`.** Edit any value in `data/daemon_slayer/16.14.1/enchanter_items.json` AND bump `_meta.patch` to `16.14.1`; assert the class moves from `STAMP_UNMAINTAINED` to `AUTHORED_EDITED`. Doubles as the acceptance test for the instance-3 remediation, proving the fix lands in a clean, note-exempt class rather than merely silencing a rule. |
| 16 | `test_derived_copy_forward_with_correct_stamp_is_caught` | LOCK | **Belt for the unexercised `DERIVED_NOT_REGENERATED`.** Copy `data/daemon_slayer/16.13.1/build_orders_sr.json` into 16.14.1 with `version` rewritten to `16.14.1`; assert `DERIVED_NOT_REGENERATED`. That is exactly the copy-forward-with-a-correct-stamp shape no other rule catches, and it is the belt for the case `cdragon_ratio_drift` would have been had whoever copied it forward also flipped the stamp. |
| 17 | `test_every_row_classifies` | LOCK + LIVE | Assert no row carries a null or fallback class over either scope (67 and 87 rows). RED-first: delete any one ladder tier. This is the assertion that would have caught revision 1's 21% fall-through. |

The module docstring MUST record (a) why the check is content-addressed and not a
payload-patch compare, citing the wiki `sed`-flip ritual (1.3), and (b) that
`tools/daemon_slayer_abilities_extract.py:729-735` is prior art for the wall-clock argument
(section 3). Without (a) a later simplification reverts the design; without (b) the next
reader re-derives the relationship between the two guards.

### 6.2 `tests/test_value_corroboration.py` (Phase 2)

1. **`test_heartsteel_pre_r137_pin_is_rejected`** - **INSTANCE 1, held-out validation.**
   Reconstruct the pre-R137 `0.08` pin from git, run the checker against
   `data/daemon_slayer/16.14.1/items.json`, and assert **non-zero exit** with a message naming
   id `3084`; restore `0.10` and assert **exit 0**. Pass/fail criterion is the measured
   mutation table in 4.2 (`0.10` present=True, `0.08` present=False, `0.12` present=False).
   This is the only retrospective proof available that the mechanism catches its founding
   defect, and it is reachable ONLY because the literal is rendered from the pin.
2. `test_sources_key_parity` - `_SOURCES` and the value dict have identical key sets, both
   directions. **Load-bearing, and no exemption set is permitted; if one is ever needed the
   design has failed.** If this is `xfail`ed or skipped, the scheme is decorative.
3. `test_derived_rendered_literals_present_in_ddragon` - every `DERIVED` row's RENDERED literal
   is an exact substring of that id's NORMALIZED `items.json` record at `current.txt`.
4. `test_inherited_mirrors_match_base` - e.g. `223084 == 3084`, reading `Src.base_id`.
   Patch-independent.
5. `test_excluded_ids_stay_absent` - `set(_EXCLUDED) & set(value_dict) == set()`.
6. `test_single_source_count_is_reported` - asserts the summary line exists and names the
   count; does not assert the value.
7. `test_single_source_rendered_literals_present_in_vendored_meraki` - the BLOCKING
   transcription half of the freshness/transcription split (4.2). Deterministic against the
   frozen vendored bytes; verified on Awe 3119 (`0.15` True / `0.08` False).
8. `test_feed_normalization_pipelines_are_pinned` - assert both regex pipelines produce the
   two worked strings in 4.2 from the raw records, so a later "cleanup" that inserts spaces
   into the tag-strip fails loudly.
9. `test_judgement_names_resolve` - every `_JUDGEMENT` key resolves via `getattr` on its
   module. Covers `_ASSUMED_PROCS_BY_LEVEL`, which carries no id and is outside both the 58
   and key parity.

### 6.3 `tests/test_source_citation_patch.py` (Phase 3)

1. **`test_actionable_citations_name_current_patch`** - **INSTANCE 4.** RED-first on today's
   tree at the 6 measured ACTIONABLE `items.json` sites (4.3).
2. `test_inert_feed_citations_carry_vintage_marker` - covers `items_meraki.json`,
   `champion_abilities.json` and `champions.json` uniformly, since all three are INERT by
   measurement rather than by allowlist.
3. `test_dated_history_is_not_flagged` - assert `citation_baseline.json` holds exactly the
   three tuple entries in 4.3, that each still resolves to a matching line, and that no
   dated-history line is flagged.
4. `test_no_new_citation_outside_the_baseline` - the net-new ratchet.
5. `test_ds_share_sync_patch_tracks_current_txt` - the free rider,
   `tools/ds_share_sync.py:62`.

---

## 7. WHAT THIS DELIBERATELY DOES NOT DO

### 7.1 DO NOT IMPUTE - and the mechanism is absence, not a zero pin

**Correction to three panel proposals.** They specify a `BLOCKED` class asserting the pinned
value stays `0.0` for Font of Life 8463 and Guardian 8465. **That is impossible.** Probed:
`grep -rn '"8463"\|"8465"' agents/ core/ --include=*.py` excluding tests returns **zero
production dict keys**. The registries are allowlists - `_rune_resist_grants.py:51-52` says
verbatim "Only three ids are SEEDED. This registry is a deliberate ALLOWLIST, not a tree-wide
sweep" - so **absence encodes zero**.

The correct and already-shipped guard is behavioral:
`agents/daemon_slayer/tests/test_rune_health_seam_r136.py:200-202` computes
`off = _ehp(health=False, hsp=False, runes=["8463"])` and
`on = _ehp(health=True, hsp=True, runes=["8463"])` and asserts equality of `physical_ehp` - an
assertion on engine output, strictly stronger than dict-absence because it composes across
registries. Do NOT replace it.

Revision 1 diagnosed the `EXCLUDED`-versus-key-parity contradiction and then kept both,
calling `EXCLUDED` "a redundant belt". **A redundant belt does not get to weaken the primary
assertion.** Resolved in 4.2 by splitting containers: `_EXCLUDED` lives outside `_SOURCES`, so
key parity keeps zero exemptions and the disjointness assertion becomes a one-liner. Both
tests get stronger. If the behavioral test and the container assertion ever conflict, the
behavioral test wins.

Nothing in this spec seeds a value. Where a value is unresolvable, the only permitted actions
are (a) resolve it from a real upstream and cite the patch that changed it, or (b) classify it
`SINGLE_SOURCE` / `EXCLUDED` and count it. There is no spelling for "I guessed".

One live lead, explicitly NOT actioned here: the recon's wiki probe found Font of Life's heal
resolved to a dated numeric entry (V14.10, "10 to 50", 20s cooldown), meaning the unresolved
template var is a CDragon/DDragon export gap rather than an absence of upstream truth. But
that entry's `{{rd|10 to 50|10*0.7 to 50*0.7|pp=true}}` carries an uninterpreted 0.7 factor
and an unresolved self-vs-ally split. **Resolving it is a separate adjudication and must never
be shortcut into an imputed number.**

### 7.2 Meraki backfill is impossible for this range - with a corrected premise

The brief states "Meraki's `latest` endpoint is mutable with no versioned history". Per 2.6,
adopt the endpoint-mutable / content-frozen distinction rather than declaring both halves
wrong: Meraki DOES publish a dated daily archive at `.../resources/old/en-US/` (380 item
snapshots, 2024-01-01 to 2026-02-11), so "no versioned history" is wrong; and the `latest`
URL is genuinely unversioned (mutable in the reproducibility sense) while its CONTENT is
frozen (five fetches over 64 days, byte-identical body).

**The conclusion survives on different and stronger evidence:** the archive's final snapshot
(2026-02-11) predates the earliest vendored fetch (16.10.1, 2026-05-13) by three months, and
versioned item paths 404. So the five vendored dirs remain the only Meraki history for
16.10.1..16.14.1, and they are irreplaceable. The honest statement is "Meraki's content is
FROZEN, roughly since Feb 2026", which correctly implies demotion rather than a re-fetch
cadence.

### 7.3 Not built, with reasons

- **No generalized payload-patch gate over all feeds.** It cannot cover `items_meraki.json` or
  `arena_augments.json` (measured `stamp_field: null` for both, 3.3), it passes all three
  1.3 feeds, and it false-positives forever on `enchanter_items.json`. It survives here only
  as the narrow, precedence-ordered tier-A1 rule (3.5).
- **No extension of `tools/upstream_drift_check.py`.** Structurally the wrong shape (section 3).
- **No promotion of the Meraki content-freshness guard.** Evaluated in section 3 and kept as
  cited prior art. It is log-only, extract-time, champion-side and compares against a
  hardcoded constant rather than across dirs.
- **No new scheduled task.** The RM-81 watchdog calls itself daily in its own docstring while
  the live task passes only `--bridge-note`, not `--staleness-recent`. The existing schedule
  slot is already declining to run the guard it has; a second unrun artifact is the defining
  failure to avoid.
- **No SQLite index.** `.gitignore` recursively ignores `**/*.db` / `**/*.sqlite*` and
  `git ls-files | grep -c '\.db$'` returns 0. A gitignored index cannot be reviewed in the PR
  that changes it and does not exist on a fresh checkout - the exact opposite of what
  Constraint 1 needs.
- **No blanket cross-feed prose diff over 706 items.** Measured: of 229 items present in both
  feeds at 16.14.1 with any percentage, 203 have disagreeing percent-sets under a coarse
  comparator. Because Meraki's content is frozen at 25.15, DDragon/Meraki disagreement is the
  EXPECTED state and every finding resolves identically. Phase 2 is scoped to the 58
  hand-seeded ids only, where a human already transcribed a number.
- **No re-fetch of `cherry_augments` / `mayhem_augment_stats` in this spec.** Genuinely the
  cheapest real data win - but only `cherry_augments` is CommunityDragon-sourced;
  `mayhem_augment_stats` comes from `data.v2.iesdev.com` and its retention is UNVERIFIED
  (1.4). Test 8 surfaces both as a standing dated question rather than a silent one, at zero
  cost, and Phase 1 stays offline. Per 7.1 the guard annotates; it does not impute.
- **No content coverage of the six loose root feeds.** They are patch-independent so no
  dir-vs-dir class applies, and content-locking them would need a max-age or a
  body-hash-with-no-comparand, i.e. the different design deferred below. They get a pinned
  NAME-SET plus test 12 instead (3.1), which closes the silent-escape hole at zero cost.
- **No coverage of `data/meta_build/sr_champion_builds.json`, `rune_recommendations_sr.json`
  or `data/external/101qq`.** These are the stalest artifacts in the repo - the first two are
  stamped `16.8.1`, BELOW the oldest vendored dir, and the 101qq feeds carry no provenance
  field at all. **These genuinely have no directory to contradict**, so a dir-vs-dir invariant
  structurally cannot reach them. They need a declared max-age, which is a different design.
  Naming it as a separate later spec is more honest than stretching this one to cover it badly.
- **`data/meta_build/ddragon/` is NOT excluded on that reason** - it has exactly such
  directories and is cited by production at four patches. It is deferred to Phase 1b on a
  different, true reason (4.4). Revision 1 excluded it on the false reason, which would have
  sent the next session to re-derive the same finding.
- **Provenance is not correctness.** Phase 1 would not have caught Heartsteel; only Phase 2
  would. Phase 1's job is that the reader of a value sees which patch its feed actually came
  from.

---

## 8. ACCEPTED RISKS

1. **Rung 2 cannot see rank-order movement.** Build membership covers 105 ids against
   ~111-item rank pools, so "inert" means "not in a committed core build", not "cannot move a
   ranking". ACCEPTED because the alternative is a full roster regen per value, and the
   checker states the limitation in its own output (5.3). Additionally mitigated in revision 2
   by demoting rung 2 to a non-blocking label, so a wrong inert verdict now costs a missing
   label rather than a wrong CI clearance.

2. **A wrong `origin` or `pinning` classification silently exempts a feed.** The registry
   forces classification (test 3) but cannot force a correct one, and at least one value is a
   bug rather than a fact (`daemon_slayer_wiki_stats_extract.py:143` hardcodes `/latest/`
   where its sibling `daemon_slayer_cdragon_spell_extract.py:107` pins by `{patch}`). ACCEPTED,
   mitigated three ways: the source URL sits beside each row so the classification is
   checkable by eye, test 13 machine-checks 7 of the 20 URLs against a second source, and the
   two-axis split means a wrong `pinning` can no longer silently remove a feed from the
   ladder's domain (only `STATIC_CONFIRMED` reads it).

3. **The live dir is only weakly covered.** Tests 6, 8, 10 and 13 are mechanical and cannot
   false-positive, but the full body-hash lock deliberately stops at N-1. ACCEPTED knowingly:
   a lock over the live dir reds 4 times in 3 days on ordinary work and trains the bypass
   reflex in week one (4.1). A guard that is routinely bypassed is worth less than a narrower
   guard that is not.

4. **Phase 2's exact-substring assertion reds on a Riot reword with no value change.**
   Measured at roughly 0.25 findings/patch over the five vendored dirs, and the correct
   response (a human re-reads the coefficient) is the intended behavior. ACCEPTED. If the rate
   proves higher than measured, downgrade the affected id to `SINGLE_SOURCE` rather than
   loosening the match into a regex.

5. **The lock creates a retention obligation.** Frozen dirs are ~12 MiB each and test 2 makes
   deletion fail. Twenty refreshes is roughly +240 MiB. ACCEPTED, mitigated by the
   `RETIRED_FIXTURES` tombstone path (3.7) existing BEFORE the first prune is needed, not
   after it fails CI. Phase 1b would add a further 33.02 MiB and deserves its own risk line if
   accepted (Section 9 Q3).

6. **A guard that reds noisily acquires `continue-on-error`.** `ci.yml:150-152` already
   carries `mypy gradual typing` with `continue-on-error: true` - a live in-file precedent for
   neutering rather than fixing. ACCEPTED as a real vector; the mitigation is that the
   frozen-dir scope means steady-state reds are near zero. If `test_ds_feed_lock.py` ever
   acquires that flag or a `skip`, the design has failed and should be deleted rather than
   left as decoration.

7. **`FROZEN_FIXTURES` is a hand-maintained tuple that nobody bumps at 16.15.1.** ACCEPTED
   with a partial mitigation: test 9 asserts lock coverage against the on-disk set, so a new
   frozen dir that nobody locked fails loudly even if the fixture tuple was not extended.

8. **Phase 1 does not resolve whether the frozen-body feeds' content moves any ranking.** The
   `FROZEN_UPSTREAM` / `CARRY_UNVERIFIABLE` table is a provenance finding, not a defect list.
   ACCEPTED and stated: do not treat `champion_abilities` / `wiki_stats` / `wiki_ability_stats`
   as defects until run through 5.2's ladder.

9. **The live dir's `enchanter_items.json` stamp stays wrong through Phase 1.** It reads
   `16.9.1` at 16.14.1 and is `--report`-only, deliberately, so the slice stays Share-neutral
   (4.1 gate (d)). ACCEPTED and explicitly deferred to the next patch refresh, where a Share
   sync happens anyway as part of the refresh ritual. The mirror
   (`Share/src/data/daemon_slayer/16.14.1/enchanter_items.json`) reproduces the defect until
   then, which is visible to external reviewers.

10. **`carried_from` and `run_len` are well-defined only while no feed's body reverts.**
    Measured today at 0 of 20 non-contiguous feeds. ACCEPTED with a hard mitigation: the tool
    RAISES on a detected revert rather than guessing a run origin. A silent guess here would
    corrupt both `carried_from` and the `FROZEN_UPSTREAM` verdict at once.

---

## 9. OPEN QUESTIONS FOR THE OPERATOR

Only genuine decisions. Everything resolvable was resolved above, and **every question below
carries a recommended default, so an unattended agent never blocks.** Revision 1's Q3
(re-cost Option C before minting the ADR) is resolved in 2.5 and removed: a conditional
rejection ADR needs no pre-requisite.

**Q1. Add a `fetched_at` to the four sidecar extractors that write none, inside Phase 1, or
defer?** The four are `tools/daemon_slayer_cdragon_ratio_extract.py`,
`tools/daemon_slayer_cdragon_spell_extract.py`, `tools/daemon_slayer_wiki_ability_extract.py`
and `tools/daemon_slayer_wiki_stats_extract.py`. They are the ENTIRE `CARRY_UNVERIFIABLE`
population (4 of 67 frozen rows, 7 of 87 over all five dirs), and that class exists only
because the artifact carries no evidence either way. Two of them (`wiki_stats`,
`wiki_ability_stats`) are the documented sed-flip copy-forward targets in memory
`reference_patch_refresh_workflow`, so this is precisely where the evidence matters most.

> **RECOMMENDED DEFAULT: do it in Phase 1.** Four one-line additions to an output dict. It
> does not change any existing body hash because the new key is inside the 1.1 wall-clock
> strip set, and at 16.15.1 it converts four permanently-unverifiable rows into decidable
> verdicts. Deferring costs nothing today but keeps the class permanently unresolvable, which
> is the shape 5.4 warns turns into a silenced guard.

**Q2. Is `CARRY_UNVERIFIABLE` CI-blocking, or counted-only?** It is an evidence gap, not a
proven defect, and today it lands on exactly 4 frozen rows.

> **RECOMMENDED DEFAULT: counted-only**, reported in the one-line summary, and promoted to
> blocking only after the four extractors emit a timestamp - at which point the class should
> go empty and any future member is a real finding. Making it blocking now reds the build for
> a condition nobody can remediate except by Q1's change.

**Q3. Extend the lock to `data/meta_build/ddragon/` (Phase 1b, 4.4)?** A genuine scope and
retention call, not a design gap. The tree has exactly the shape this spec exists to guard and
is cited by production at four patches, but it doubles the retention commitment (+33.02 MiB).

> **RECOMMENDED DEFAULT: yes, but as a separate commit gated on Phase 1 landing green, NOT
> folded into Phase 1.** It deserves its own accepted-risk line. If declined, 7.3's corrected
> rationale must still ship, because revision 1's stated reason for excluding it is factually
> false and would send the next session to re-derive the finding.

**Q4. Re-fetch `cherry_augments.json` now, and separately, is `mayhem_augment_stats.json`
still reachable?** Revision 1 asked these as one question on the assumption both are
CommunityDragon-sourced. Measured: only cherry is (1.4). So "the cheapest real data win" is
confidently true for one feed and unproven for the other.

> **RECOMMENDED DEFAULT: split, and do neither inside Phase 1.** Test 8 as re-specified turns
> both into a standing dated question at zero cost, and Phase 1 is explicitly a no-network
> slice. The finding does not decay by waiting - each file's `fetched_at` is byte-identical
> across all five dirs. When actioned: re-fetch `cherry_augments.json` first (one live
> CommunityDragon probe, low risk, 554 augments frozen since 2026-05-18), and hold
> `mayhem_augment_stats` until someone confirms the iesdev endpoint is still live and still
> returns 16.14-era data. If the operator overrides toward doing it now, it belongs in the
> SAME commit as test 8 so the test is not merged already-red.

**Q5. Fund the `_item_tenacity` REMEDIATION slice now, or let Phase 2 measure it first?** The
scope contradiction is resolved in 4.2 (annotation covers all 58 including tenacity; only
remediation is separable), so this is a funding call. The exposure is real: 17 of 58, the
largest registry, rung-3-live via `ehp.py:2765-2767` with no operator flip, and a prescribed
per-patch re-run at `_item_tenacity.py:31-33` that did not happen for three patches.

> **RECOMMENDED DEFAULT: do NOT fund it up front.** Land Phase 2 annotating all 58, let the
> rendered-literal check report how many of the 17 actually fail, and spin a remediation slice
> only if that count exceeds 3 (the sizing rule in 4.2). The failure count is currently
> unknown and is cheap to measure as a side effect of work already scheduled. Funding a
> doubling of Phase 2 against an unmeasured count is the same mistake 2.2 refuses for Option C.

**Q6. May a `SINGLE_SOURCE` value ship behind a seam flip?** Phase 2 counts freshness but
never blocks on it; the transcription half IS blocking (4.2).

> **RECOMMENDED DEFAULT: yes, keep freshness non-blocking. Revisit only if a second
> transcription defect ships.** One asymmetry the operator should weigh: the day-one
> `SINGLE_SOURCE` instance (the `0.15` Awe coefficient across six ids, witnessed only by the
> frozen Meraki feed) is build-INERT under rung 2, so a blocking rule would NOT have caught
> the one defect that actually shipped (Heartsteel 3084, which IS build-present). That argues
> for keeping it non-blocking until a second real instance exists.

---

## CHANGE LOG

**Revision 2 - 2026-07-19.** Revision 1 was marked "READY TO IMPLEMENT - no further design
work required" and then failed a three-lens completeness audit: all three independent auditors
returned NEEDS_WORK, producing **43 gaps and 16 unactionable sections**. Four themed agents
re-measured every failing claim against disk, and this integration re-verified the two
headline numbers on which those agents disagreed. Every gap is resolved; nothing is deferred
to "the implementer should decide".

**Structural corrections (design was wrong, not merely under-specified):**

1. **The `kind` enum was two axes crushed into one.** Replaced with `origin` +
   `pinning`, with the ladder branching on `origin` first. This is the single change that
   makes the taxonomy total; patching `derived` into the old ladder would have left the same
   defect for the next kind added. A third `pinning` value (`content_hash`) was added because
   `scenarios.json`'s upstream is a Next.js chunk with a build-hash filename, which the
   4-value enum could not express.
2. **Rule 3 `COPIED_FORWARD` was unsound.** It compared raw `fetched_at` values, and 10 of the
   20 feeds carry none, so `null == null` made it vacuously true for half the inventory and,
   ranked above rules 4/5/6, swallowed them. Replaced by computed `fetch_evidence` plus
   `SKIPPED_FETCH` / `CARRY_UNVERIFIABLE`, with manifest-inherited evidence for the three
   feeds `manifest.json`'s `outputs` block names.
3. **The 7-rule ladder was not total.** 14 of 67 frozen rows (21%) fell through and 6 more
   landed in designed-out classes. Rebuilt as 13 classes on 2 axes plus an explicit
   `BASELINE`, **measured at 0 fall-through over both 67 frozen rows and 87 five-dir rows**,
   with all six required day-one verdicts preserved and the `champions.json` false positive
   actually killed for the first time.
4. **Section 1.3's `RESTAMPED` class was unreachable for two of the three feeds it was
   invented for, and wrong for the third.** Membership corrected; the section's conclusion
   (content-addressed lock, not a stamp compare) survives and is strengthened.
5. **The stamp slot was three semantic axes**, one in a foreign version namespace. Split into
   `stamp_field` (dir-comparable) and `content_vintage_field` (recorded, never compared); the
   2-segment forms are dropped entirely because selecting one makes the highest-precedence
   rule fire forever on three feeds.
6. **The note obligation was keyed to the wrong thing and sized against the wrong
   denominator.** Split into a machine-generated per-row `note` and a human `(feed, class)`
   `rationale`: **24 non-exempt rows collapsing to 11 authored strings**, nine of which are
   already prose in this document.
7. **One scope word did three jobs.** Split into REGISTRY (20 feeds) / LOCK (67 rows over 19
   feeds) / LIVE-ASSERTION (20 feeds), which is the only way `ability_staleness.json` is
   expressible at all.
8. **The Phase-2 GATE could not fire.** `corroborating_literal` was a hand-authored constant
   never compared to the pin, so the founding-defect test read GREEN on the reconstructed
   `0.08`. Literals are now RENDERED from the pinned value, proven by mutation on three ids.
9. **"EXACT substring" was unimplementable** against the raw records - both of revision 1's
   worked examples are rendered forms, so the test would have failed on day one for every row
   as a broken checker. Two normalization pipelines are now specified and pinned by a test.
10. **One `_SOURCES` dict could not hold five kinds.** Split into three containers, which
    makes key parity exemption-free AND the disjointness test a one-liner. The `JUDGEMENT`
    exemplar carries no item id at all, a collision no auditor named.
11. **Phase 3's rule shape was wrong**, not undecided: both offered branches infer from prose
    what `feed_lock.json` already computes. Phase 3 is now a consumer of Phase 1's output -
    **6 ACTIONABLE of 26 citations, computed** - which also gives a verdict to the 12-site
    `champion_abilities.json` class revision 1 left unruled.
12. **Test 7's remediation falsified the spec's own Share-neutrality claim.** Rescoped to
    frozen pairs, where it still fires day-one on instance 3 and touches nothing mirrored.
13. **Test 6 as written would have red day-one with no in-phase remediation** (found during
    integration): the raw `declared_patch == patch_dir` form fires on `cherry_augments` and
    `mayhem_augment_stats`, whose only fix is a network re-fetch Phase 1 excludes. Rescoped to
    assert the CLASS.
14. **Gate (c)'s byte assertion was unsatisfiable on this repo**, independently of its
    MB/MiB mislabel: `core.autocrlf=true` with `.gitattributes:28` covering `*.py` only means
    the same walk measures 57.69 MiB on Legion and 55.82 MiB in CI. Replaced by set equality
    plus a 0.25 ratio bound, and `feed_lock.json` is forbidden from carrying any size or
    whole-file-digest column.

**Measurement corrections:**

- The section 1.1 strip set gained `_meraki_content_patch` and `content_patch`. **A themed
  agent claimed this was provably a no-op; measured, it moves two published hashes**
  (`ability_staleness.json` and `manifest.json` at four dirs). The matrix in 1.1 is the
  corrected one.
- **GAP 42 adjudicated by re-measurement.** Two auditors reported the live-dir churn as
  "5 of 5"; both counted files TOUCHED. Measured with the canonical instrument, `cde08721`
  moves ZERO bodies and `91664dbf` moves one, not three. Revision 1's "4 of 5" and its named
  file list were correct.
- `cherry_augments` and `mayhem_augment_stats` do NOT share a `fetched_at` literal, and only
  cherry is CommunityDragon-sourced. Both errors are fixed and test 8 now hardcodes no
  timestamp.
- Rung 1's premise was falsified by grep in the UNSAFE direction; replaced with a
  feed-reachability invariant plus a per-module table, and `hybrid.py` added. The 25-champion
  output is unchanged.
- Rung 2's "1557 cells" reproduced once "cell" was defined; both 1557 and 9342 are correct and
  count different things. The id set moved 112 -> 105 in three days, so rung 2 is demoted to a
  non-blocking label and recomputed at call time.
- Instance 4's census was undercounted: 9 tabled, 26 measured, 13 in scope for Phase 3.
- The "~11 patches" correction list was undercounted: 4 named, 5 measured.
- The doc-sync rider list was undercounted: 2 named, 9 measured.
- Line citations corrected: `_item_tenacity.py:22-24` -> `:19-20`, `:36-38` -> `:31-33`;
  `_rune_resist_grants.py:50-51` -> `:51-52`;
  `daemon_slayer_wiki_ability_extract.py:199-201` -> `:200-202`; `ci.yml:64` -> `:66`;
  `daemon_slayer_extract.py:57` -> `:624-628`. Revision 1's own proposed correction of
  `abilities.py:622` to `:679` was WRONG (`:679` is a different flag) and is now `:676`.
- **LEDGER 953 is REFUTED as a citation failure.** The auditor grepped the paraphrase "72
  stale" rather than the LEDGER's "72 minors stale". The citation is sound and must not be
  "corrected".
- Line citations into LIVING docs (`ROADMAP.md`, `docs/OPERATIONS.md`, `docs/LEDGER.md`) are
  replaced by stable label anchors throughout. Revision 1 criticized ROADMAP for stale line
  numbers and then cited `ROADMAP.md:231` three times; that cite went stale DURING the audit,
  and Phase 1 deliverable 6 edits that very row.

**Gaps resolved that no themed agent owned** (resolved by direct measurement in this pass):
the shipped Meraki content-freshness guard omitted from the coverage map (evaluated, kept as
cited prior art, verified `log.warning`-only and absent from CI); the endpoint-mutable /
content-frozen distinction the repo already carries and revision 1 would have deleted; the
five-site "~11 patches" list; the nine-site doc-sync rider list including the CI-checked
`Share/docs/03_DATA_AND_SOURCES.md`; the `CLAUDE.md:7` ADR count, which minting ADR-013 makes
CORRECT and which must therefore NOT be bumped; and the missing `docs/LEDGER.md` deliverable.

**Status downgraded** from "READY TO IMPLEMENT - no further design work required" (which
contradicted a four-question operator gate where only one question carried a recommendation)
to a qualified status, with a recommended default on every remaining question so an unattended
agent never blocks and the operator retains a real veto.
