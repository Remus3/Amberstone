# Capture 101.qq.com hero-rank-double payload (operator recipe)

Item 187 Slice G follow-up; ROADMAP L132. Tencent CN-official duo-synergy /
counter data. **Updated 2026-06-02 (item 277) - three premises in the
original recipe were verified WRONG against live probes from Legion; see
"Verified reality" below before capturing.**

## CAPTURED + characterized (2026-06-02, item 277) - RESOLVED

Operator captured the live URL; the payload was pulled + run through the probe
from Legion. The hero-rank-double page uses the **faas** variant:

```
https://faas-6831.native.qq.com/faas/6831/1371/getRankDouble
  ?championid=&date=<YYYYMMDD>&tier=200
  &lane1=<lane>&lane2=<lane>&pagesize=200&pageindex=0
```

- `lane1`/`lane2` are LANE STRINGS (top / jungle / mid / bottom / support),
  NOT role codes. `championid=` empty -> all champions for that lane pair.
- Verified reachable from Legion (`code:0 success`), 200 rows per lane pair;
  top/jungle, mid/jungle, mid/support, bottom/support all return 200.
- Row schema (list of pair records):
  `{championid1, championid2, doublewinrate, iwinrate1, iwinrate2,
    itemp1 (pick%), irank, lane1, lane2}` - `doublewinrate` is the duo synergy
  signal, `itemp1` the pick rate, `irank` the synergy rank.
- `championid1/2` are DDragon NUMERIC KEYS 1:1 (498=Xayah, 497=Rakan) -
  probe matched 59/59, unmatched 0, NO id translation needed. The
  `101qq_id_map.json` scaffold is therefore just a DDragon key->name map.
- Cross-checks cleanly to `data/rewind_history.db` (Xayah/Rakan resolved both
  sides).

The raw payload is gitignored (`data/external/qq_double_*.json`) - it is
third-party Tencent winrate data, NOT committed (redistributable; see the
pre-release name-scrub prereq). Re-pull on demand with the curl above + a
`Referer: https://101.qq.com/` header.

### Wiring - RESOLVED (item 277): option (b) LIVE dependency SHIPPED

The operator chose the live dependency. NEW `core/synergy_external_source.py`
`fetch_rows(lane1, lane2, tier)` does the on-demand getRankDouble fetch (6h
in-memory TTL, tries recent dates, fail-soft -> None). It feeds the EXISTING
item-199 duo-synergy lane: `core/smoothed_rates_101qq._load_once` now pulls
live rows FIRST and falls back to the committed static May-25 seed when the
CN endpoint is unreachable (`source()` reports `live`|`static`). The
`/api/duo-synergy` route + champ-select bot/sup grid are UNCHANGED (same
schema). Kill switch: `RC_DUO_SYNERGY_LIVE=0` forces static. The raw payload
is never written to disk (gitignored); only the committed static seed
persists. Re-pull is automatic at champ-select.

Not chosen: (a) one-shot snapshot seed; (c) documented-only.

## Verified reality (live-probed from Legion 2026-06-02)

1. **NOT geo-fenced.** From Legion: `101.qq.com` -> HTTP 200, `game.gtimg.cn`
   -> HTTP 200, and `game.gtimg.cn/images/lol/act/img/js/heroList/hero_list.js`
   -> HTTP 200. The "must capture on Game-PC / Legion-side fetch will fail"
   note was stale. **Capture from Legion's own Chrome** (or fetch the static
   gtimg files directly with curl).
2. **The duo data is NOT a static gtimg JSON.** It is a DYNAMIC param'd API.
   The static gtimg `act/img/js/` tree is only REFERENCE data (champions /
   items / runes / augments), not the rank-double payload.
3. **Real endpoints** (from `https://101.qq.com/js/api.js`):
   - `https://mlol.qt.qq.com/go/mlol_webapis/odp_proxy/get1700_rank_double`
     `?date=<YYYYMMDD>&championid=<id>&role1=<r>&role2=<r>&pagesize=<n>`
     `&pageindex=<n>&item=<sortfield>&order=<dir>&ts=<ms>`
   - `https://faas-6831.native.qq.com/faas/6831/1371/getRankDouble<params>`
   Both respond from Legion (no geo-fence) but reject missing/bad params with
   `{"code":603,"message":"..."}`.

### Param contract for get1700_rank_double (partially reverse-engineered)

Sequential validation; verified ACCEPTED: `date` (YYYYMMDD), `championid`,
`role1`, `role2`, `pagesize`, `pageindex`, `ts`. The two values that still
need the live capture are the `item` (sort field) + `order` (direction) ENUMS
- every guessed value returned `"item is wrong"` / `"order is wrong"`, so the
exact tokens come from the page's sort UI. That is the ONE thing the capture
below resolves.

## Recipe (now a ~1-minute Legion-Chrome task)

1. Open Chrome on Legion. Navigate to:
   `https://101.qq.com/#/hero-rank-double?tier=200`
2. `F12` -> **Network** tab -> **Fetch/XHR** filter.
3. Hard-refresh (`Ctrl + Shift + R`), pick a champion + the two lane roles,
   and click a sort column (so the real `item`/`order` values fire).
4. Find the request to `get1700_rank_double` (or `getRankDouble`).
5. Right-click -> **Copy** -> **Copy link address** (the full param'd URL),
   and **Save as** / **Copy response** to a local JSON file.

## Hand it to the probe script

```
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" tools/probe_101qq_hero_rank_double.py \
  --url "<the get1700_rank_double URL you copied>" \
  --json "C:\path\to\rank-double.json" \
  --cross-check-rewind
```

Prints (no network): URL-structure analysis, JSON schema summary, DDragon
cross-reference, one sample pair vs `data/rewind_history.db`. For the
canonical id-map:

```
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" tools/compare_101qq_vs_ddragon.py \
  --json "C:\path\to\rank-double.json" \
  --out data/external/101qq_id_map.json
```

Hand-correct unmatched keys in `data/external/101qq_hero_id_map.json`
(overlaid LAST, your corrections win).

## Operator decision BEFORE wiring (item 277 flag)

This is a LIVE param'd CN API, not a one-shot static seed - wiring it into the
`core/smoothed_rates.py` pick/ban-synergy lane means a standing external
dependency on a Tencent endpoint (params + a daily `dtstatdate`), plus the
redistributable-scrape concerns the competitor-teardown already flagged
(`docs/_archive/COMPETITOR_LIFT_2026-06-02.md`). Decide whether to (a) one-shot snapshot
a tier-200 sweep into a static `data/external/` seed (cleaner, ages out), or
(b) take the live dependency. Capture one URL first either way - the probe
characterizes the schema offline before any wiring.

## Safety notes

- Do NOT run during an active match (champ-select-safe only).
- The probe + compare scripts are stdlib-only + ASCII-clean (no new deps).
