# Skins and chromas (s156 S4)

Status: data layer + read-only route shipped; UI not built (see ROADMAP row text in the s156 report).

## What a coaching dashboard gains

- Champ-select: show the selected skin name (and chroma, when the LCU reports one) next to the pick.
- Home hero: use the splash of the skin the player actually selected instead of the default splash.
- Pool panel: skin count per champion ("Ahri, 104 skins") as a cheap familiarity / ownership hint.

None of this changes coaching numbers; it is presentation only.

## Sources and refresh

- DDragon `champion_detail/<Champ>.json` `skins[]` (`id`, `num`, `name`, `chromas` flag). Local, gitignored mirror under `data/meta_build/ddragon/<patch>/`, refreshed by `tools/ddragon_mirror_refresh.py` with each patch. `core/skins.skins_for(champion)`.
- CommunityDragon `skins.json` (chroma lists). Optional, fetched at runtime by `core.skins.refresh_cdragon_cache()` into gitignored `data/cache/cdragon_skins.json`; only `id -> {name, chromas[{id, name}]}` is kept, art paths are dropped. Atomic write, 15 s timeout, https only, returns False on any failure. `core/skins.chromas_for(skin_id)`.
- LCU champ-select session (`myTeam[].selectedSkinId`) or skin-carousel list. `core/skins.selected_skin_from_lcu(payload)`.

Missing data degrades to empty lists / None; nothing raises on data problems.

## Route

`GET /api/skins?champion=<Slug>[&skin=<id>]` (`dashboard/routes_skins.py`): always 200, `{champion, count, skins[], chromas[]}`. Names and numeric ids only.

## Licence note

Skin names, ids and chroma lists are Riot data used under Riot's developer terms (see `NOTICE`). Splash and chroma art is fetched at runtime from Riot / CommunityDragon CDNs for display and is NEVER committed: the repo is public Apache-2.0 and Riot art is not ours to relicense. Tests use small synthetic fixtures only.
