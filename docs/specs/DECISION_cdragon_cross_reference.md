# DECISION: CommunityDragon / CDTB as a champion-ability cross-reference source

Status: PROPOSED - awaiting operator decision
Author: research session 2026-07-18
Scope: decision document only. No code was changed. No extractor was re-run.

---

## Question

Should RC adopt CommunityDragon / CDTB (or grow the existing
`tools/daemon_slayer_cdragon_ratio_extract.py`) as a CROSS-REFERENCE source for
champion ability data - given that RC's real provenance is
`wiki -> meraki-analytics/lolstaticdata -> Meraki CDN -> RC` and the two middle
hops are dead?

---

## Ground truth as verified

Everything in this section was probed this session. Claims I could not verify are
listed in "Unverified" at the end of the section and again in Open Questions.

### GT-1. The briefing's central premise is WRONG: the CDragon cutover already shipped

The task framing states `prefer_cdragon_ratios` is a default-OFF, operator-gated
flag. It is not. It is **default `True` and live in the main engine load path.**

- `agents/daemon_slayer/abilities.py:622` - `prefer_cdragon_ratios: bool = True,`
- `agents/daemon_slayer/abilities.py:661` - docstring: "default True / ON since
  item 320 / ENGINE 1.119.0 cutover"
- `agents/daemon_slayer/abilities.py:536` - "the default since the item 320 cutover"
- `Share/src/agents/daemon_slayer/abilities.py:622` - Share mirror is identical
- git: `1f172fcc feat(ds): item 320 - prefer_cdragon_ratios default-ON cutover +
  resolver float-snap (ENGINE 1.118.0 -> 1.119.0)`
- `agents/daemon_slayer/data_loader.py:477` calls
  `AbilitiesSnapshot.load(patch=self.patch, data_root=self.data_root)` with **no**
  `prefer_cdragon_ratios` argument, so it takes the `True` default. This is the
  engine's real load path, not a test seam.

CDragon is therefore not a prospective cross-reference. It is **already a primary
source that overrides Meraki ratios in production.**

**Three stale "default OFF" statements are propagating this error**, including one
in a file shipped in the most recent commit:

- `agents/daemon_slayer/abilities.py:82` - "(item: prefer-CDragon re-source, default OFF)"
- `agents/daemon_slayer/abilities.py:700` - "opt-in, default OFF"
- `tools/ds_wiki_staleness_check.py:22` - "does not touch the default-off
  `prefer_cdragon_ratios` cutover"

`abilities.py` contradicts itself: line 82 and line 700 say OFF, line 622 and line
661 say ON. The code is the truth; the comments are stale.

### GT-2. The live CDragon sidecar is pinned at 16.11 and was copied forward, not re-extracted

`data/daemon_slayer/current.txt` = `16.14.1`.

SHA-256 (first 8) of the committed sidecars per patch directory:

| File | 16.11.1 | 16.12.1 | 16.13.1 | 16.14.1 | internal patch |
|---|---|---|---|---|---|
| `cdragon_ability_ratios.json` | f48ba6fa | f48ba6fa | f48ba6fa | f48ba6fa | **16.11.1** |
| `cdragon_ratio_drift.json` | e2c4d924 | e2c4d924 | e2c4d924 | e2c4d924 | **16.11.1** |
| `cdragon_spell_stats.json` | 5403f39e | 5403f39e | 6aa44416 | 1dbce06e | 16.14.1 |

The ratio sidecar and its drift report are **byte-identical across four patch
directories**. They were carried forward verbatim by the patch-refresh commits
(`0b870f71`, `c022498f`, `21db5626`) and have not been re-extracted since
16.11.1. The sibling `cdragon_spell_stats.json` IS re-extracted per patch, so the
patch-refresh ritual regenerates one CDragon artifact and not the other.

The loader does not catch this. `agents/daemon_slayer/abilities.py:417-440`
resolves the sidecar by directory path only:

```
path = root / patch / _CDRAGON_RATIO_SIDECAR      # abilities.py:430
```

It never reads the payload's own `patch` field. Copying a stale file into a new
patch directory silently re-arms it as authoritative.

**Net effect, live today: the DS engine prefers 16.11-extracted CDragon ratios
over the Meraki snapshot, three patches after they were extracted, with no guard.**

### GT-3. The drift report is ratio-only and cannot see base or cooldown - CONFIRMED

`data/daemon_slayer/16.14.1/cdragon_ratio_drift.json`, 1046 rows:

- Field distribution: `ap_pct` 660, `total_ad_pct` 324, `caster_max_hp_pct` 55,
  `bonus_ad_pct` 7.
- **Zero `base` rows. Zero `cooldown` rows.** Verified by direct scan, not by
  reading the docstring that asserts it.
- Summary: `n_blocks_compared` 698, `n_changed` 319, `n_only_cdragon` 348,
  `n_fallback` 577, `n_meraki_only` 235, `n_champs` 170.
- Kind distribution: `match` 379, `only_cdragon` 348, `changed` 319.

The operator's statement ("drift is RATIO-only and pinned at 16.11.1 while live is
16.14.1") is correct on both counts.

`base` is absent from the drift comparison because `build_drift`
(`tools/daemon_slayer_cdragon_ratio_extract.py:889-986`) iterates `_RATIO_FIELDS`
only (`:912`), and `_RATIO_FIELDS` (`:191-197`) excludes `base` even though the
resolver emits it. Cooldown is absent because the extractor never reads it at all.

### GT-4. What the extractor actually extracts

`tools/daemon_slayer_cdragon_ratio_extract.py`:

- Source: `https://raw.communitydragon.org/{patch}/game/data/characters/{slug}/{slug}.bin.json`,
  two-segment patch (`16.11`, not `16.11.1`) - `:123-126`, `:145-149`.
- Core resolver `resolve_calc_block` (`:528`) walks
  `mSpell.mSpellCalculations.<Calc>.mFormulaParts` and maps part types to six
  emitted fields: `base`, `ap_pct`, `total_ad_pct`, `bonus_ad_pct`,
  `caster_max_hp_pct`, `target_max_hp_pct` (`:191-197`).
- Deliberately conservative. Any level-interpolation, breakpoint, buff-counter,
  conditional, cross-ref, or unknown stat enum forces the WHOLE block to
  `resolution="fallback"` with no partial emission (`:209-218`, `:606-607`).
  Three explosion / sanity guards follow (`:609-626`).
- Slot order from `CharacterRecords/Root.spellNames`; the passive is not in that
  list so **no P-slot data is emitted at all** (`:697-722`).
- Yield at 16.11: **838 mechanical / 577 fallback blocks** across 171 champions,
  0 fetch errors. That is a **40.8 percent fallback rate** - two in five damage
  blocks fall back to Meraki.
- Champion enumeration: `_load_champion_ids` (`:735-745`) reads
  `champion_abilities.json` and returns its keys. **The CDragon extractor's roster
  is therefore capped by the frozen Meraki file.** This matters for RM-79 - see GT-6.

`cdragon_spell_stats.json` (the sibling, fresh at 16.14.1) carries a genuinely
different payload: `_with_geometry` 619, `_with_missile` 416, `_with_cc_tags` 186,
`_with_ammo` 24. None of that is available from the wiki as structured numbers.

### GT-5. Meraki is not slow. It is frozen, and the freeze is asymmetric

- `champion_abilities.json` carries `meraki_content_patch: 25.15` under
  `fetched_at: 2026-07-16`, `count: 171`.
- Meraki CDN `champions.json`: Last-Modified **2025-08-01**, pinned content patch
  **15.15**, roughly 24 patches behind live 16.14.
- Meraki CDN `items.json`: Last-Modified 2026-02-11, patch 16.3.
- There are no versioned CDN paths. `/resources/15.15/...` and
  `/resources/16.14/...` both 404. Only `latest/` exists, and for champions
  `latest` IS 15.15 data.
- `meraki-analytics/lolstaticdata`: last push **2025-11-12**, pure Python, no game
  install required. Not archived. README, verbatim: the wiki is used "because it
  is the only accurate source of champion data".

So the generator is dormant but alive; the CDN artifact RC consumes is frozen.
There is no version of "wait for Meraki" that is a plan.

### GT-6. RM-79 is NOT blocked upstream. RC's own extractor filters Locke and Zaahen out

This is the most consequential finding of the session and it inverts the standing
ROADMAP framing.

Verified live against `wiki.leagueoflegends.com` on 2026-07-18:

`Module:ChampionData/data` (392,361 bytes) contains full skill arrays for both:

- `apiname = Locke` - skill_i `Silver Stake`, skill_q `Ritual Nails`,
  skill_w `Soul Ignition`, skill_e `Ashen Pursuit`, skill_r `Purgatory`
- `apiname = Zaahen` - skill_i `Cultivation of War` / `Determination`,
  skill_q `The Darkin Glaive` / `The Darkin Glaive 2`, skill_w `Dreaded Return`,
  skill_e `Aureate Rush`, skill_r `Grim Deliverance`

The `Template:Data` pages exist and carry the parameters RC already parses:

| Page | bytes | has `leveling` | has `cooldown` |
|---|---|---|---|
| `Template:Data Locke/Purgatory` | 4923 | yes | yes |
| `Template:Data Locke/Ritual Nails` | 4093 | yes | yes |
| `Template:Data Locke/Soul Ignition` | 3093 | yes | yes |
| `Template:Data Locke/Silver Stake` | 965 | no | no |
| `Template:Data Zaahen/The Darkin Glaive` | 4726 | yes | yes |
| `Template:Data Zaahen/Grim Deliverance` | 3727 | yes | yes |
| `Template:Data Zaahen/Dreaded Return` | 2323 | yes | yes |

Yet both are absent from `data/daemon_slayer/16.14.1/wiki_ability_stats.json`
(0 entries each). The reason is RC's own code:

- `tools/daemon_slayer_wiki_ability_extract.py:506` - `keep = _load_champion_apinames(patch)`
- `tools/daemon_slayer_wiki_ability_extract.py:197-211` - `_load_champion_apinames`
  reads `champion_abilities.json` and returns its 171 keys
- `tools/daemon_slayer_wiki_ability_extract.py:275-285` - the title builder skips
  any apiname not in `keep`

**RC fetches the wiki, then throws Locke and Zaahen away because the dead Meraki
hop does not list them.** RM-79's ability-data half is not blocked upstream. It is
blocked by a roster filter RC controls.

Note the same trap applies to Option A: `daemon_slayer_cdragon_ratio_extract.py:735-745`
enumerates champions from the same Meraki file, so **a CDragon ratio re-extract
does not fix RM-79 either** without the identical de-capping change.

### GT-7. The wiki path is already built and already at full-roster scale

- `data/daemon_slayer/16.14.1/wiki_ability_stats.json`: **1046 abilities**,
  `_missing_pages` 12 (all form-variants like `Viktor/Glorious Evolution 3`),
  0 errors, `_with_cc_flags` 753, `_with_static` 55, `_with_recharge` 20.
- Fetch cost: batched MediaWiki `action=query`, up to 50 titles per request,
  roughly 22 requests for the full roster
  (`tools/daemon_slayer_wiki_ability_extract.py:41-52`).
- `data/daemon_slayer/16.14.1/ability_staleness.json`, generated
  `2026-07-18T11:59:22Z`: 171 champions checked, 754 pages fetched,
  **75 stale champions / 123 findings**. Example row: Ahri Q
  `base:Damage Per Pass` Meraki `[40.0, 140.0]` vs wiki `[35.0, 135.0]`.
- `parse_leveling_bases()` (`tools/ds_wiki_staleness_check.py:177-195`) already
  extracts the per-label base endpoints out of `{{st|...}}` blocks by cutting at
  the first `{{as|` scaling wrapper.

The wiki extractor is not a greenfield build. It is a working full-roster
pipeline that currently discards most of what it parses.

### GT-8. CommunityDragon and CDTB, externally verified

- CDragon serves `game/data/characters/<slug>/<slug>.bin.json` - confirmed HTTP
  200. Two-segment patch dirs only: `/16.11/` returns 200, `/16.14.1/` returns 404.
- **Newest patch directory served: `16.14`** (mtime 2026-07-15). `/latest/` is
  byte-identical to `/16.14/`. `/pbe/` is a separate tree.
- Cadence is automated. Every 16.x tree landed on a Wednesday between 05:50 and
  06:48 UTC. Live heartbeat `status.live.txt` = `2026-07-18T12:00:02Z done`.
  `CommunityDragon/Data` pushed "Update hashes" commits on 2026-07-18, 07-16 and
  07-15. Lag after a patch is hours, not days.
- CDTB (`github.com/CommunityDragon/CDTB`): Python, `pip3 install cdtb`,
  **no local game install required** - it pulls from Riot's CDN via `-s cdn`.
  Needs hash lists via `cdtb fetch-hashes`. Last commit 2026-07-16. 149 stars,
  not archived, created 2017.
- CDragon carries, per direct sampling at 16.14: per-rank arrays (7 slots
  including a rank-0 pad), `cooldownTime` arrays (15/15 champions sampled),
  missile speed, hitbox geometry (`mMissileWidth`, `mLineWidth`, `castRadius`),
  and machine-readable `mSpellTags` such as `Trait_ImmobilizingCCSpell`.
- CDragon's real limitations: **cast time is sparse and inconsistent** (entirely
  absent for ezreal, lux, leesin; partial elsewhere - Aatrox has it on W/E/R but
  not on Q); **CC durations are untyped**, surviving only as free-text DataValue
  names like `QKnockupDuration`, so consumers must string-match per champion; and
  **153 to 451 unresolved hash keys per champion file** (`{0e1136d1}` style),
  including some `__type` values.
- What CDragon can never carry: human-authored interaction rulings (spell-shield
  behavior, on-hit vs on-attack application, interrupt windows), prose for unusual
  mechanics, and community-tested values. That is editorial judgment, not data.

### Unverified

- Whether flipping `prefer_cdragon_ratios` to `False` changes DS outputs, and for
  how many champions. **I did not run the suite or diff engine outputs.** The
  16.11 override is confirmed live and confirmed stale; its magnitude is unmeasured.
- Whether Locke/Zaahen `leveling` blocks parse cleanly through
  `parse_leveling_bases()`. I confirmed the parameters exist; I did not run the parser.
- CDTB's release-manifest / rman handling. The README section retrieved did not
  cover it.
- A search summary mentioned a planned CDragon CDN deprecation "to allow for
  versioning of the endpoints". This could not be confirmed on the site. Treat as
  low confidence, but it is a real tail risk worth a periodic recheck.

---

## Option A: CDragon as the cross-reference (refresh and grow the existing extractor)

Re-extract `cdragon_ability_ratios.json` at 16.14, wire the re-extract into the
patch-refresh ritual, and extend `build_drift` to cover `base` (and add cooldown
extraction) so the drift report can see RM-81-class evidence.

**PROS**

- The extractor exists, is tested, and its conservative fallback discipline is
  already tuned through two correction rounds (items 317 and 320).
- CDragon is genuinely fresh: 16.14 is available today, automated, hours of lag.
  This is the strongest freshness story of any source RC touches.
- Game-client-derived. It fails independently of the wiki - it cannot be
  vandalized, cannot lag on an editor's availability, and cannot carry an
  editorial mistake.
- It uniquely carries missile speed, hitbox geometry and spell tags. RC already
  consumes these via `cdragon_spell_stats.json`, and that artifact is already
  kept fresh.
- CDTB is a real, maintained, install-free escape hatch if `raw.communitydragon.org`
  ever changes shape.

**CONS**

- **It does not fix RM-79.** `_load_champion_ids` (`:735-745`) enumerates from the
  frozen Meraki file, so Locke and Zaahen are structurally invisible to it.
- **It does not fix RM-81 as currently shaped.** The 40.8 percent fallback rate
  means two in five blocks yield nothing, and P-slot passives are never emitted.
- Extending drift to `base` is not free. `base` is an absolute magnitude, so the
  comparison hits exactly the tooltip-aggregate-vs-per-instance mis-pairing that
  produced the MissFortune R 17.7x undercount (R127, guard at
  `abilities.py:456-457`). Ratios are dimensionless and forgiving; bases are not.
- Cooldowns are not extracted at all today. That is net-new resolver work against
  the hash-opaque bin format.
- The correctness burden is demonstrably high. This resolver has needed an
  off-by-one fix, a float-snap, three explosion guards, a semantic re-pairing
  rewrite, and a per-champion exclusion set. Each patch is a chance for a new
  bin-shape surprise.

**Cost: ~1 session** for a refresh plus patch-refresh wiring.
**~2 to 3 sessions** to extend drift to `base` and add cooldown extraction safely,
because base comparison needs its own pairing-safety work.

---

## Option B: Extend RC's own wiki extractor

Drop the Meraki-derived roster cap, and promote `parse_leveling_bases()` from a
staleness detector into a real damage-block producer feeding the engine.

**PROS**

- **It is the true upstream.** Meraki's own README says the wiki is "the only
  accurate source of champion data", and Meraki's generator is the pure-Python
  `pull_champions_wiki.py`. Going wiki-direct removes two dead hops rather than
  routing around them.
- **It fixes RM-79 at the root, and the fix is small.** Proven this session:
  `Template:Data Locke/*` and `Template:Data Zaahen/*` exist with `leveling` and
  `cooldown` parameters. The only thing stopping RC is
  `daemon_slayer_wiki_ability_extract.py:506`.
- **It fixes RM-81 at the root.** The detector already finds 75 stale champions
  and 123 findings. Today those findings are a report; extending the path makes
  them a correction.
- It covers `base` and `cooldown` - precisely the two fields the CDragon drift
  report structurally cannot see (GT-3).
- Full roster coverage already proven: 1046 abilities, 12 missing pages, 0 errors.
- Cheap at runtime: roughly 22 batched requests. Access is already solved -
  correct host, non-browser User-Agent, batching discipline all documented and
  working.
- It covers P-slot passives, which CDragon's `spellNames` path structurally cannot.
- No new third-party code is executed. RC keeps its own parser.

**CONS**

- Human-authored. It can be wrong, vandalized, or lag a patch. Nothing about the
  wiki is machine-guaranteed.
- Wikitext is a moving parse target. This session's own history proves it: the
  `#vardefine` gap (`{{ap|{{#var:b1}} to {{#var:b3}}}}`) silently parsed to
  nothing and hid a real Garen R nerf until `resolve_wiki_vars()` recovered 4
  champions and 14 findings.
- The current parser is deliberately conservative and under-reports: labels that
  do not match a Meraki `attribute` verbatim are skipped. Promoting it to an
  authority means confronting every label it currently declines to match.
- Meraki's typed `damage_blocks` schema is real value that the wiki does not
  hand over. Reproducing `attribute_kind` classification (damage / heal / shield /
  slow / duration) from free text is the hard part of this option, and it is the
  part that made lolstaticdata a 20-file project rather than a script.
- Single upstream. If the wiki is wrong, RC is wrong, with nothing to disagree with it.

**Cost: ~2 to 3 sessions.** Roughly: (1) de-cap the roster and prove Locke/Zaahen
parse; (2) promote leveling blocks to typed damage blocks behind a default-OFF
flag; (3) reconcile against Meraki on the 96 non-stale champions as a correctness
gate before any flip.

---

## Option C: Both - wiki as numeric authority, CDragon demoted to alarm

Do Option B, and keep CDragon as a **cross-check that never overrides**. Concretely:
the wiki becomes the source for bases, ratios and cooldowns; CDragon keeps its
existing uncontested role for geometry / missile / tags via
`cdragon_spell_stats.json`; and the ratio sidecar stops feeding the engine and
starts feeding a disagreement report.

**PROS**

- **The two sources fail independently, which is the entire argument for a
  cross-reference.** The wiki is human-authored and fails through editor lag,
  vandalism and parse drift. CDragon is client-derived and fails through bin-shape
  changes and hash opacity. A number both agree on is very likely right; a number
  they disagree on is exactly what a human should look at.
- **Demoting the override collapses the maintenance cost.** This is the key point.
  Almost all of CDragon's historical pain - the off-by-one, the semantic
  re-pairing rewrite, the MissFortune exclusion set - is the cost of being
  *authoritative*. A mis-paired block in an alarm-only role produces a spurious
  alarm, which is cheap. The same mis-pairing in an overriding role produced a
  17.7x DPS undercount, which is expensive. The 40.8 percent fallback rate also
  stops being a coverage problem and becomes "the 59 percent it does resolve is
  free verification".
- RC keeps every asset it has already paid for. Nothing is deleted.
- It resolves the live defect in GT-2 as a side effect: the stale sidecar stops
  being authoritative the moment it stops overriding.

**CONS**

- Two upstreams to keep alive across every patch refresh, two parse-trap surfaces,
  two things that can break on a Tuesday.
- Alarm fatigue is a real failure mode. There are already 319 `changed` rows and
  348 `only_cdragon` rows at 16.11. Without a triage rule most of that is noise,
  and a report nobody reads is worse than no report because it looks like coverage.
- Highest total cost of the four options.

**Cost: Option B (~2 to 3 sessions) plus ~1 session** to demote the override,
regenerate at 16.14, and define a triage threshold. Call it **~3 to 4 sessions.**

---

## Option D: Do nothing

**PROS**

- Zero cost. The engine is stable and the DS sweep is mid-flight at 89/173.
- RM-81 is already tooled: the detector, the runtime guard
  (`core.daemon_slayer_client.champion_ability_data_is_current()`) and the daily
  watchdog all shipped and are green.

**CONS**

- **This is not a neutral option, and that is the finding that should decide this.**
  "Do nothing" means continuing to ship 16.11-extracted CDragon ratios as
  authoritative over Meraki, with no patch guard, while three separate comments in
  the codebase state the flag is off. Nobody currently believes this is happening.
- 75 of 171 champions carry drifted base or cooldown values, including 39 of the 86
  already-adjudicated sweep verdicts. Every further sweep verdict is adjudicated
  against data known to be wrong for 44 percent of the roster.
- RM-79 stays "blocked upstream pending Meraki" when GT-6 proves it is not blocked
  and the upstream is not coming.
- The gap widens monotonically. Meraki's champion CDN has not moved since
  2025-08-01.

**Cost: 0 sessions now.** The cost is paid later and it compounds.

---

## Recommendation

**Take Option C, sequenced Option B first - but ship the GT-2 integrity fix before
any of it, as a separate P0.**

### P0, before the A/B/C/D choice is even relevant

The live engine prefers ability ratios extracted from patch 16.11 while running
16.14, because the sidecar was copied forward through three patch refreshes and
`_load_cdragon_ratio_sidecar` (`abilities.py:417-440`) validates only the
directory, never the payload's own `patch` field. Pick one of:

1. Add a patch guard to `_load_cdragon_ratio_sidecar`: if `doc["patch"]` does not
   match the requested patch, return `{}` and log loudly. Fail-soft to Meraki,
   which is what the docstring already promises. This is the honest fix - it makes
   the stale-copy failure mode impossible rather than merely fixed-once.
2. Re-extract at 16.14 and add the re-extract to the patch-refresh ritual next to
   the `cdragon_spell_stats.json` step that already exists.

Do both. (1) is the guard, (2) is the data. Then correct the three stale
"default OFF" comments at `abilities.py:82`, `abilities.py:700`, and
`ds_wiki_staleness_check.py:22`.

This is a Tier-2 change (engine data path) and needs the full dual suite plus the
Share mirror. Note that (1) and (2) have opposite short-term effects on engine
output - the guard falls back to Meraki, the re-extract moves to 16.14 CDragon -
so land them together and diff once, deliberately.

### Then: the question as asked

**Does a CDragon cross-reference still earn its keep once the wiki path is on the
table? Yes - but only in the demoted, alarm-only role, and for a much smaller job
than it currently holds.**

The reasoning, in order:

1. **The wiki wins on every axis that RM-79 and RM-81 actually turn on.** It is
   the true upstream. It carries `base` and `cooldown`, which CDragon's drift
   report structurally cannot see (GT-3). It covers P-slot passives, which
   CDragon's `spellNames` path cannot (GT-4). It reaches Locke and Zaahen -
   though so does CDragon, once RC stops capping it: **CDragon is blocked ONLY by
   the same RC-controlled roster cap** (GT-6), and the character bins for both
   exist (`locke` 57068 bytes / `zaahen` 55748 bytes, HTTP 200 on 2026-07-25 at
   the exact URL `daemon_slayer_cdragon_ratio_extract.py` already requests). An
   earlier draft of this line said CDragon "cannot" reach them; that was wrong and
   contradicted GT-6 above. It is already running at full roster scale (GT-7).
   Option A still cannot close the `base` / `cooldown` gap; that half is not a
   close call.

2. **But CDragon is not therefore worthless, and the independent-failure argument
   is genuinely strong.** The wiki's failure modes are human - editor lag,
   vandalism, and the `#vardefine` class of silent parse drift that this repo has
   already been bitten by once. Those are exactly the failures a client-derived
   source cannot share. Going wiki-only means RC's damage model has a single
   human-authored point of failure and no way to notice.

3. **The maintenance-cost objection is real but it is an argument about the ROLE,
   not about the source.** Every expensive CDragon incident in RC's history - the
   off-by-one, the re-pairing rewrite, the MissFortune exclusion - was the cost of
   letting it *override*. Alarm-only, a mis-pairing costs one spurious row in a
   report. Overriding, the same mis-pairing cost a 17.7x DPS undercount that had
   to be found and guarded per champion. Demotion is what makes the second
   upstream affordable, and it is why "two upstreams is too expensive" does not
   survive contact with the demoted design.

4. **Demotion is also strictly safer than the status quo**, independent of
   everything above. The engine currently takes a 40.8-percent-fallback,
   three-patch-stale, P-slot-blind source as authoritative over its own snapshot.

So: wiki becomes the numeric authority for bases, ratios and cooldowns. CDragon
keeps the geometry / missile-speed / spell-tag role it already holds
uncontested and already keeps fresh. The ratio sidecar stops feeding the engine
and starts feeding a disagreement alarm, with a triage threshold defined up front
so the 319-changed-row noise floor does not become fake coverage.

**Do not adopt CDTB.** It is healthy, install-free and maintained, but it solves
a problem RC does not have. RC needs parsed ability numbers, and
`raw.communitydragon.org` already serves those over plain HTTP with stdlib
`urllib`. CDTB is WAD extraction and hash management - the right tool only if
CDragon's served JSON disappears. Log it as the documented fallback (this matters
slightly more given the unconfirmed CDN-versioning rumor in Unverified) and
revisit only if `raw.communitydragon.org` breaks.

### Sequencing

| Step | Work | Sessions |
|---|---|---|
| P0 | Sidecar patch guard + 16.14 re-extract + fix 3 stale comments | 0.5 |
| B1 | De-cap the wiki roster filter; prove Locke + Zaahen parse - **SHIPPED 2026-07-25** | 0.5 to 1 |
| B2 | Promote `leveling` to typed damage blocks, default-OFF flag | 1 to 1.5 |
| B3 | Reconcile against Meraki on the 96 non-stale champions as the flip gate | 0.5 |
| C1 | Demote the ratio sidecar to alarm-only; define the triage threshold | 1 |

**Total ~3.5 to 4.5 sessions**, with real value banked at P0 and again at B1.

#### B1 status (A-26 / RM-95b, shipped 2026-07-25)

All four sidecar extractors now take a DEFAULT-OFF `--full-roster` opt-in that
sources the champion keyspace from `champions.json` (173) instead of
`champion_abilities.json` (171). OFF, the champion list is byte-identical to the
pre-change code on all four (proven by importing the HEAD modules alongside the
new ones and diffing; the wiki-ability `extract()` payload compares 1119 bytes
to 1119 bytes). ON, all four reach 173 and gain exactly `['Locke','Zaahen']`.

**Size the deliverable honestly: B1 buys CC / geometry / cooldown / cast-time
for these two, NOT the damage the scorers need.** Measured 2026-07-25:

- `wiki_ability_stats.json` (1046 abilities) carries **no `leveling` key and no
  damage block for any champion** - the entire field census is cast_time_raw 714,
  cooldown_raw 672, spellshield 667, effect_radius_raw 407, speed_raw 311,
  cdstart_raw 266, parry 215, width_raw 204, grounded 165, knockdown 135,
  callforhelp 105, static 55, silence 54, angle_raw 48, collision_radius_raw 30,
  recharge_raw 20, recharge_ranks 19, terraingrace 17, tether_radius_raw 17,
  ontargetcdstatic_raw 15, inner_radius_raw 14, ontargetcd_raw 1.
  `Ahri/Charm` = `{cast_time_raw, cooldown_raw, speed_raw, spellshield,
  width_raw}`; `Ahri/Essence Theft` = `{}`.
- DDragon cannot supply the damage either: for Locke, Zaahen AND Ahri at 16.14.1,
  `spells[0].vars == []` and `effectBurn == [None,'0','0','0']`, with unresolved
  `{{ missiledamage }}` / `{{ totaldamage }}` tooltip placeholders.

So `POST /rank-assassin` `baseline_burst` for Locke stays **0.0** after B1.
Closing that is **B2** (promote the wiki `leveling` blocks to typed damage
blocks), which is still open.

---

## What would change the recommendation

- **If the wiki's `leveling` blocks do not parse cleanly into typed damage blocks
  for a meaningful fraction of the roster**, B2 is the whole cost of this plan and
  it inflates fast. Gate on B1: if de-capping plus a Locke/Zaahen parse spike is
  not clean in half a session, stop and re-cost before committing to B2.
- **If Meraki ships a 16.x refresh**, the urgency collapses. RC's schema is already
  built for it. This plan becomes a nice-to-have rather than a correction. (Last
  push 2025-11-12; the CDN champions artifact has not moved since 2025-08-01. Do
  not plan around this.)
- **If `raw.communitydragon.org` changes shape or the CDN-versioning rumor turns
  real**, C1 gets more expensive and CDTB becomes the fallback rather than a
  logged note. Recheck at the next patch refresh.
- **If measurement shows the 16.11 override is currently changing few or no
  champion scores**, the P0 urgency drops from "live data defect" to "latent
  hazard" - but the guard is still correct and still cheap, so P0 should ship
  regardless.
- **If the operator's real priority is finishing the 89/173 DS sweep rather than
  data currency**, then P0 alone is the right scope and B/C wait. But note the
  interaction: 39 of the 86 already-adjudicated verdicts were adjudicated against
  data now known to be stale, so sweep verdicts banked before this lands may need
  re-checking. That argues for doing at least P0 and B1 before the sweep goes much
  further.

---

## Open questions for the operator

1. **Was the item-320 default-ON cutover intended to remain on?** Three comments
   say the flag is off, including one shipped in the latest commit. Either the
   comments are stale (most likely) or the cutover outran its intended gate. This
   changes whether P0 is a guard-plus-refresh or a revert.
2. **P0 tie-break:** if the guard and the 16.14 re-extract disagree on a champion's
   ratios, which wins for this patch - fall back to Meraki, or take fresh CDragon?
3. **Is the DS sweep allowed to keep banking verdicts against known-stale data**
   while B lands, or should the sweep pause at 89/173?
4. **Alarm triage threshold for C1:** what delta on a ratio is worth a human look?
   Without a threshold, 319 changed rows is noise wearing the costume of coverage.
5. **Does RM-79 get re-opened?** The ROADMAP records it as "BLOCKED UPSTREAM
   pending Meraki" and task chip `task_020c8e44` tracks that framing. GT-6 shows
   it is blocked by RC's own roster filter instead. The chip's premise is stale.
6. **Scope confirmation:** promoting the wiki to the numeric authority for damage
   bases is a larger change than the "cross-reference" framing this question
   started from. Worth an explicit yes before B2.
