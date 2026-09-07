# DECISION - Riot patch-note backfill as an ability-data source

Status: DECIDED - do not build. Recommendation is to extend the wiki extractor instead.
Date: 2026-07-18
Spike artifacts: throwaway PoC in session scratchpad (NOT added to the repo, by design).

---

## Question

Can RC parse Riot's official patch-note pages, as far back as they are reachable, to
reconstruct champion/item data that Riot publishes nowhere else in machine-readable form?

Motivation: RC's ability data flows wiki -> meraki-analytics/lolstaticdata -> Meraki CDN -> RC,
and the two middle hops are dead. The Meraki CDN `latest` endpoint is frozen at content
patch 25.15 while live play is well ahead of it, so 75 of 171 champions carry drifted
base-damage or cooldown values (RM-81), and 2 champions are missing entirely (RM-79).

---

## What the spike proved

All numbers below were observed this session against the live site, not estimated.

### 1. Reachability and URL shape

Patch pages are directly reachable and server-rendered (no JS needed for the change content).
Probed patch labels spread across 7 years:

| Patch | HTTP | Working slug | h3.change-title (DOM) | Row markup era |
|---|---|---|---|---|
| 26-14 | 200 | `league-of-legends-patch-26-14-notes` | 13 | modern `ul/li` |
| 26-1  | 200 | `patch-26-1-notes` | 34 | modern `ul/li` |
| 25-15 | 200 | `patch-25-15-notes` | 13 | modern `ul/li` |
| 14-10 | 200 | `patch-14-10-notes` | 90 | modern `ul/li` |
| 13-1  | 200 | `patch-13-1-notes` | 22 | modern `ul/li` |
| 12-10 | 200 | `patch-12-10-notes` | 12 | legacy `div.attribute-change` |
| 11-1  | 200 | `patch-11-1-notes` | 21 | legacy `div.attribute-change` |
| 10-1  | 200 | `patch-10-1-notes` | 21 | legacy `div.attribute-change` |
| 9-1   | 200 | `patch-9-1-notes` | 16 | legacy `div.attribute-change` |
| 8-1   | 404 | (both forms tried) | - | - |
| 7-1   | 404 | (both forms tried) | - | - |
| 6-1   | 404 | (both forms tried) | - | - |

**Floor is patch 9.1 (January 2019).** Everything at or before 8.1 is gone from this host.
So the reachable window is roughly 7.5 years, which is more than the concept needs.

`h3.change-title` does hold across the entire reachable range. That part of the premise
survived the spike intact.

### 2. Observed parse FAILURES (the part that matters)

Three things broke. All three are recorded here because they change the cost estimate.

**(a) Raw regex counts are contaminated by CSS.** The token `change-title` appears inside
the page's inlined stylesheet, not only in the body. A naive
`re.findall(r'class="[^"]*change-title', html)` over patch 26-14 returns 13 - which happened
to look plausible - but on other pages the CSS rules inflate the count outright. Any real
implementation must build a DOM, strip `<style>` and `<script>`, then XPath. This invalidated
my own first-pass counts mid-spike.

**(b) The row markup changed. There are two incompatible eras.** My first parser, written
against modern markup, extracted **zero rows** from patch 9.1 despite correctly finding all
16 champion headings. Observed structures:

- Legacy (9.1 through ~12.10): fully structured and machine-friendly.
  `div.attribute-change > span.attribute + span.attribute-before + span.change-indicator + span.attribute-after`.
  Patch 9.1 carries 73 such rows; patch 12.10 carries 315.
- Modern (~13.1 through 26.14): unstructured text.
  `ul > li > strong` with the before and after joined by a U+21D2 arrow inside a single
  text node. Zero `attribute-change` elements exist on these pages.

A backfill therefore needs two extractors plus an era-detection heuristic. Ironically the
*older* pages are the easier ones to parse.

**(c) Slug derivation is not formulaic.** Within a single season the prefix changes:
26.1 through 26.3 answer on `patch-26-N-notes`, while 26.4 through 26.14 answer only on
`league-of-legends-patch-26-N-notes`. Separately, `25-1` and `25-01` both 404 under both
prefixes even though `25-15` is fine. Any implementation needs probe-with-fallback per
patch, not a format string.

Confirming the brief's warning: the patch-schedule page is JS-rendered and cannot be scraped
for the patch list. I derived the list by probing instead. Note that RC's own
`data/meta_build/ddragon/_index.json` is **not** a usable substitute: it covers only
`16.11.1, 16.12.1, 16.13.1, 16.14.1` with `latest_pulled = 16.14.1`. Four patches, all recent.
It cannot seed a historical chain.

### 3. Full parse of one modern page (patch 26.14)

After fixing (a) and (b), the modern parse is clean. Patch 26.14 yielded 14 change blocks and
31 rows:

- 18 rows cleanly numeric (`Attack Damage Growth: 2 => 2.5`)
- 9 rows mixed (numbers plus prose or ratios, e.g.
  `True Damage: 150 / 250 / 350 (+ 25 / 30 / 35% of target's missing health) => 125 / 200 / 275 (...)`)
- 4 rows pure prose with no extractable value

Ability-slot attribution is recoverable, which was better than expected: each row sits under an
`h4.change-detail-title`, and where that heading is an ability it carries a DDragon spell icon
whose filename is the slot key (`MordekaiserE.png`, `AzirW.png`, `LockeQ.png`). 17 of 31 rows
were slot-attributable by icon; the remaining 14 are base-stats or passive rows whose `h4` text
still names the section (`Base Stats`, `Passive - Absolution`). So slot attribution is ~100%
via section text.

Bonus observation: the pages embed the DDragon version in their image URLs
(patch 26.14 embeds `16.13.1`), so a page can self-identify its data version.

The mangled case worth naming: the **Azir** block on 26.14 produced 0 numeric rows. All four of
its rows are prose about rune and item interactions filed under `W - Arise!`
(`On-Hit? More Like On-Destroy: Scorch, Liandry's Torment, ... now deal 100% of their damage
on-hit instead of 50%`). A champion can appear in a patch and contribute nothing loadable.

### 4. How much of a kit does a patch note actually pin down?

Measured against what RC's Meraki baseline holds for the same champions
(cooldown, cost, and each damage block counted as one field):

| Champion (26.14) | Fields pinned by the note | Fields RC holds | Coverage |
|---|---|---|---|
| Azir | 0 | 17 | 0.0% |
| Corki | 2 | 17 | 11.8% |
| Garen | 1 | 11 | 9.1% |
| Jayce | 2 | 25 | 8.0% |
| Mordekaiser | 2 | 9 | 22.2% |
| Nami | 1 | 17 | 5.9% |
| Senna | 3 | 16 | 18.8% |
| Seraphine | 1 | 17 | 5.9% |
| Yunara | 1 | 23 | 4.3% |
| **TOTAL** | **13** | **152** | **8.6%** |

**A patch note pins down roughly 9 percent of a touched champion's kit, and 0 percent of an
untouched champion's kit.** This is the arithmetic consequence of "changes only" and it is not
improvable by better parsing.

### 5. The anchor question - can the delta chain be anchored?

This was the load-bearing question. Answer: **anchorable for RM-81, not anchorable for RM-79.**

RC's baseline is `data/daemon_slayer/<patch>/champion_abilities.json`, sourced from the Meraki
CDN, self-labelled `meraki_content_patch: 25.15`, covering 171 champions and 927 forms. I
independently confirmed the freeze: the CDN `latest` champions.json returns
`last-modified: Fri, 01 Aug 2025 08:37:37 GMT`.

Enumerating the real chain by probing every candidate slug: 2025 ends at 25.24 (25.25+ are 404),
and 2026 runs 26.1 through 26.14 (26.15+ are 404). So the replay is:

```
25.16 .. 25.24   =  9 patches
26.1  .. 26.14   = 14 patches
                 -----------
                   23 patch pages to replay onto the 25.15 anchor
```

Note: `ROADMAP.md` describes the Meraki freeze as "~11 patches back". The enumerated chain is
**23**. That discrepancy should be corrected in the ROADMAP independently of this decision.

Aggregate over all 23 chain patches, parsed:

- 517 change blocks, 220 distinct named subjects (champions, items, runes)
- 1565 rows total: **647 numeric (41%), 501 mixed (32%), 417 pure prose (27%)**
- **558 distinct row labels, of which 460 (82%) occur exactly once**

For RM-79 specifically, the two kit-less champions were tracked across the whole chain:

- **Locke** appears in **1 of 23** patches (26.14 only), contributing 4 rows touching Q and W only.
- **Zaahen** appears in **5 of 23** patches, touching Passive/Q/W/E and **never R**.

Neither has a baseline in Meraki, and no patch note in the window publishes a full kit. Deltas
against a nonexistent anchor are unusable. **Patch-note backfill cannot solve RM-79.**

### 6. What the wiki does instead (the decisive comparison)

Queried the live wiki with RC's own proven access path
(`tools/daemon_slayer_wiki_ability_extract.WIKI_API`, `action=query&prop=revisions`):

- `Template:Data Locke/*` returns **12 ability template pages** (I/Q/W/E/R aliases plus named
  and multi-form pages). `Template:Data Zaahen/*` likewise returns **12**.
- `Template:Data Locke/Ritual Nails` contains `{{#vardefine:b1|50}}` (rank 1) and
  `{{#vardefine:b2|82}}` (rank 5).

Compare that against what the 26.14 patch note said about the same ability:

```
patch note 26.14 : Nail Damage: 50 / 60 / 70 / 80 / 90  =>  50 / 58 / 66 / 74 / 82
wiki, right now  : b1 = 50, b2 = 82
```

The wiki already holds the post-patch absolute values, for the exact champion the patch-note
path cannot anchor. The patch note gives a delta with no baseline; the wiki gives the answer.

This is not theoretical for RC. `tools/ds_wiki_staleness_check.py` (shipped `dddbbdfa`) already
fetched **754 wiki pages across 171 champions in one run** and produced
`data/daemon_slayer/16.14.1/ability_staleness.json` containing 75 stale champions with correct
live values, e.g. `Ahri Q base:Damage Per Pass meraki [40,140] vs wiki [35,135]`. The wiki side
of that comparison is already right. `parse_leveling_bases()` is doing the work today; it just
writes a diff report instead of writing the data back.

---

## PROS of the patch-note backfill

- Genuinely reachable back to January 2019, server-rendered, no auth, no JS, stable enough
  that a 2019 page still parses.
- The change rows carry exact before -> after pairs, so a parsed row is unambiguous about the
  transition, which the wiki does not state as such.
- Slot attribution is clean via the DDragon spell-icon filename in the section heading.
- Pages self-identify their DDragon version.
- It is the only source that captures Riot's stated *intent* and the prose context blocks,
  which the wiki flattens away. If RC ever wants "why did this change" narrative for coaching,
  this is where it lives.
- Legacy-era pages (2019-2022) are more structured than modern ones, so a historical crawl
  would degrade gracefully rather than fall off a cliff.
- It covers items and runes in the same pass, not only champions.

## CONS

- **Changes only. ~8.6% of a touched kit, 0% of an untouched kit.** Structural, unfixable.
- **Cannot solve RM-79 at all.** Locke has no anchor, and appears in 1 of 23 patches with 2 of
  5 slots touched.
- **59% of rows are not cleanly loadable** (32% mixed, 27% pure prose). An entire champion block
  can yield zero numeric rows (Azir, 26.14).
- **The label-to-engine-field mapping is the real cost, and it is unbounded.** 558 distinct
  labels over 23 patches, 82% of them appearing exactly once. Labels are free text written by
  designers, are ambiguous without their section (`damage` occurs 81 times), and drift by patch.
  Every new patch introduces new one-off labels that need human adjudication forever. This is a
  permanent tax, not a one-time build.
- **Two parser eras plus per-patch slug probing** - three sources of silent breakage, and the
  breakage mode is under-extraction, which fails quietly rather than loudly.
- **Compounding error.** Replaying 23 deltas means one mis-parsed or missed row corrupts the
  value for every subsequent patch, with no independent check. There is no way to detect drift
  except by comparing against... the wiki.
- Riot can restyle patch notes at any time; there is no contract and no versioning.
- Every value it produces is a value the wiki already states absolutely.

---

## Effort estimate

**Patch-note backfill (to actually fix RM-81):**

| Work | Estimate |
|---|---|
| Two-era DOM parser plus era detection | ~1 session |
| Per-patch slug resolver with fallback probing | ~0.3 session |
| Label -> engine-field mapping for 558 labels | **~4-6 sessions, and never finished** |
| Delta replay engine, conflict handling, reconciliation vs baseline | ~2 sessions |
| Tests, Share mirror, ENGINE bump, live verify | ~1 session |
| **Build total** | **~8-10 sessions** |
| Ongoing per-patch maintenance | permanent, every patch, forever |

And after all that it reaches ~41% of rows cleanly, ~8.6% of a kit per patch, and still does not
fix RM-79.

**Extending the wiki extractor (the alternative):**

| Work | Estimate |
|---|---|
| Extend `parse_leveling_bases()` from endpoint pairs to full rank arrays | ~0.5 session |
| Emit into the `champion_abilities.json` shape the engine already consumes | ~1 session |
| Add Locke and Zaahen (pages already exist, 12 templates each) - fixes RM-79 | ~0.5 session |
| Tests, Share mirror, ENGINE bump, live verify | ~1 session |
| **Build total** | **~3 sessions** |
| Ongoing maintenance | the existing daily watchdog already runs it |

---

## How it compares to extending the wiki extractor

Honest answer: **the wiki path dominates this outright.** Not narrowly - on every axis that
matters.

| | Patch notes | Wiki extractor |
|---|---|---|
| States absolute current values | No, deltas only | Yes |
| Kit coverage per fetch | ~8.6% of touched champs | 100% of all champs |
| Fixes RM-81 (stale values) | Partially, via 23-patch replay | Yes, directly |
| Fixes RM-79 (Locke, Zaahen) | **No - no anchor exists** | **Yes - 12 template pages each, live** |
| Machine-readable contract | None, free-text labels | Yes, `{{#vardefine}}` params |
| Mapping table needed | 558 labels, 82% singletons, grows forever | Existing param names |
| Error mode | Silent compounding across 23 replays | Per-page, self-correcting on refetch |
| Already working in RC | No | **Yes - 754 pages / 171 champs, shipped `dddbbdfa`** |
| Build cost | ~8-10 sessions | ~3 sessions |

The clinching point is that Meraki's `champions.json` is *itself generated from the LoL wiki* by
`meraki-analytics/lolstaticdata`. RC talking to the wiki directly is not a workaround; it is
removing two dead intermediaries and talking to the actual upstream. The patch-note path, by
contrast, is a third-hand reconstruction of data the upstream states plainly.

There is also a subtler point that removes the last patch-note advantage. The apparent unique
selling point is history - "what was Ahri Q at 25.20?". But MediaWiki exposes full page revision
history through the same API RC already uses (`prop=revisions` with `rvstart`/`rvend`). So even
historical per-patch reconstruction is better served by walking wiki revisions than by replaying
patch-note deltas, and it comes back as absolute values rather than diffs.

---

## Recommendation

**Do not build the patch-note backfill. Extend the wiki extractor to write ability data back
into `champion_abilities.json`, and close RM-79 and RM-81 that way.**

The spike answered the feasibility question as "yes, technically" and the value question as
"no, and the alternative is strictly better and 3x cheaper". The single most persuasive artifact
is that the wiki already holds `b1=50 / b2=82` for Locke - the champion the patch-note path
provably cannot anchor - while `ds_wiki_staleness_check.py` is already fetching those pages
daily and throwing the values away into a diff report.

The cheapest next move is not a new scraper. It is to stop discarding what the staleness checker
already reads.

## What would change the recommendation

- **The wiki goes dark or hostile.** `wiki.gg` already returns 401 (memory
  `reference_lol_wiki_access`). If `wiki.leagueoflegends.com` follows, patch notes become the
  only remaining human-readable source and this doc should be reopened immediately. That is the
  main reason to keep this document rather than delete it.
- **RC wants Riot's stated design intent as coaching content** (the prose context blocks:
  "Morde has lost a fair amount of power ever since the Riftmaker bugfix in 26.10..."). The wiki
  does not carry that. This would be a *different, additive* feature with a different
  justification, not a data-integrity fix, and it would not need the delta-replay machinery at
  all - just block text keyed by champion and patch. That is a much smaller build (~1 session)
  and is the only version of this idea worth revisiting.
- **A champion appears in patch notes but never on the wiki.** Did not occur for Locke or
  Zaahen, but if a future release lands that way, patch notes become the only source for that
  champion.
- **Riot ships a real machine-readable patch-delta feed.** Would moot the scraping question.

## Open questions for the operator

1. Approve the wiki-extractor extension as the RM-79 + RM-81 fix? It is the "operator decision,
   not yet taken" already flagged in `ROADMAP.md`.
2. Do you want the patch-note *prose* (design intent) as a coaching surface, separately? It is
   cheap on its own and is the only genuinely unique thing patch notes hold.
3. `ROADMAP.md` says the Meraki freeze is "~11 patches back"; the enumerated chain is 23. Fix
   the ROADMAP line?
4. Should the wiki extractor write into `champion_abilities.json` directly, or into a sidecar
   that overlays it? A sidecar keeps the Meraki provenance tag honest and is reversible; direct
   write is simpler. This affects the metric-provenance tagging convention.

## Flagged - not verified in this spike

- `meraki-analytics/lolstaticdata` last push date (2025-11-12) was taken from the task brief and
  not checked. The CDN freeze itself **was** verified live (`last-modified: 2025-08-01`).
- Patch reachability was **sampled**, not exhaustive. Patches between 9.1 and 26.14 that were
  not probed may have their own slug or markup quirks. The 23-patch chain 25.16-26.14 **was**
  enumerated exhaustively.
- No end-to-end delta replay was attempted. The 8.6% kit-coverage figure is measured; the claim
  that replay error compounds is reasoned, not demonstrated.
- Locke's launch patch was not identified. Locke appears only in 26.14 within the 25.15-26.14
  window, so the launch predates the window or its launch block is not a `patch-change-block`.
- Item and rune coverage was counted but not evaluated for engine-field mappability. The
  conclusion here is argued on champion data.
