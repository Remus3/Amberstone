# Capture 101.qq.com hero-rank-double payload (operator recipe)

One-shot Game-PC step. Item 187 Slice G follow-up; ROADMAP L132. Tencent
CN-official duo-synergy/counter data lives on the `game.gtimg.cn` CDN
but the exact URL path resists blind probing; this recipe captures it
live in champ-select-safe Chrome (never in-game).

## What you are capturing

The Tencent SPA at `https://101.qq.com/#/hero-rank-double?tier=200`
fetches static JSON from `game.gtimg.cn/images/lol/act/...` containing
per-champion-pair winrate / counter / synergy data. We need:

1. The resolved URL (so we can re-fetch on demand later).
2. The JSON payload (so we can analyze its schema offline).

## Recipe

1. Open Chrome on Game-PC. Navigate to:
   `https://101.qq.com/#/hero-rank-double?tier=200`
2. Press `F12` to open DevTools. Click the **Network** tab.
3. Click the **XHR** filter (also called **Fetch/XHR** in newer Chrome).
4. Hard-refresh the page: `Ctrl + Shift + R`.
5. In the Network list, scan for a request whose URL contains BOTH
   `game.gtimg.cn/images/lol/` AND the substring `hero-rank-double`.
   Common shapes seen on similar Tencent endpoints:
   - `https://game.gtimg.cn/images/lol/act/img/js/hero-rank-double-tier200.js`
   - `https://game.gtimg.cn/images/lol/act/data/heroRankDouble/tier200.json`
6. Right-click the matching request -> **Save as** (or **Copy response**
   to clipboard, then paste into a new file). Save it as something like
   `C:\Users\you\Downloads\hero-rank-double-tier200.json`.
7. Copy the full request URL from the Headers tab.

## Hand it to the probe script

Once you have the URL + the local JSON file, run:

```
py tools/probe_101qq_hero_rank_double.py \
  --url "<the URL you copied>" \
  --json "C:\path\to\hero-rank-double-tier200.json" \
  --cross-check-rewind
```

The script prints (no network calls):

- URL structure analysis (is it patch-versioned? tier-stratified? region-coded?)
- JSON schema summary (top-level keys, champion-keying convention)
- DDragon cross-reference (how many keys match RC's champion set)
- One sample champion pair vs `data/rewind_history.db` (operator eyeballs alignment)

For the canonical id-map output (used by the live consumer), also run:

```
py tools/compare_101qq_vs_ddragon.py \
  --json "C:\path\to\hero-rank-double-tier200.json" \
  --out data/external/101qq_id_map.json
```

## Submit findings via the bridge

Once the script outputs look clean, post the captured URL + a short
summary (JSON shape + id-map size + unmatched-key sample) via the
RC<->Game-PC bridge so Legion can wire the static seed into the
`core/smoothed_rates.py` pick/ban-synergy lane (consumer (b) in the
shared-primitive design).

## Hand-correct mismatches without re-capturing

If `compare_101qq_vs_ddragon.py` reports unmatched keys (e.g. Tencent
spells `MissFortune` as `niuren` or uses a code RC does not recognize),
create `data/external/101qq_hero_id_map.json` with the corrections:

```json
{
  "niuren": "MissFortune",
  "ezreal_cn_code": "Ezreal"
}
```

Re-run `compare_101qq_vs_ddragon.py`; the override is overlaid LAST so
your hand-corrections always win.

## Safety notes

- Do NOT run this recipe during an active match. Tencent's SPA is
  channel-safe in champ-select; in-game it can affect the screen-agent
  cadence on Game-PC.
- Do NOT attempt to fetch the URL from Legion. The CDN is geo-fenced;
  Legion-side fetch will fail. The capture must happen on Game-PC.
- The probe + compare scripts are stdlib-only and ASCII-clean (per
  CLAUDE.md hard rule). No new dependencies are added.
