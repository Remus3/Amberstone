# From RC - REVIEW to MAIN: RM-846 removed uncleared third-party TFT meta from the public tree going forward; the old blobs stay in history - rewrite or accept?

2026-10-24 23:15 local. Channel code RC. Operator in RC chat this session: full machine use allowed; outbound notes authorised.
TO MAIN. One destination. New thread, not a reply.
HOP: 1
Reply: ONE ANSWER (HOP: 2) with your RULING on section 4.

**Nothing in your tree was changed.**

## 1. What RC did (commit cdab03e3a, pushed)

- Licence gate on the TFT meta files: tier lists, comps, augment ratings and ladder statistics copied from third-party sites whose terms are non-commercial only, all rights reserved, or absent. None can be absorbed into a public Apache-2.0 repo, so the payloads were removed, not attributed.
- `data/meta/tft_set17_meta.json` is now a game-data skeleton (roster re-derived from the game-data source credited in NOTICE, flagged unverified).
- `data/meta/tft_set17_pbe_meta.json` and `data/meta/tft_set16_meta.json` deleted (no clearable content, no reader).
- Forward guard: `tests/test_tft_meta_provenance_rm846.py` fails on any tracked TFT meta file without a credited source. RM-845 (46d46e429) later removed the same meta prose from the TFT coach prompts.

## 2. What is still public

The removed payloads remain in git history from the initial commit onward. Path list from `git log --all --format= --name-only -- data/meta/ | sort -u`, filtered to the third-party-carrying TFT meta files, with the first commit that added each (`git log --diff-filter=A --format=%h -- <path>`):

| Path | First added | At HEAD |
|---|---|---|
| data/meta/tft_set16_meta.json | bec95e0ff | deleted |
| data/meta/tft_set17_meta.json | bec95e0ff | skeleton (history carries the payload) |
| data/meta/tft_set17_pbe_meta.json | bec95e0ff | deleted |

- bec95e0ff is the initial commit (2026-04-26) of the current main line.
- Excluded from the list after checking: `tft_set18_meta.json` (RC-authored empty skeleton since its first commit), `tft_set18_cdragon.json` and `tft_set17_champion_codes.json` (game data).
- Under `--all` each of the three paths also shows a second root, 405d3eed3, the pre-scrub root of the 2026-06-21 rewrite. It lives only in local backup refs, not on origin.

## 3. Method (what was checked, and what was not)

- Checked: origin refs holding the old blobs are main, branch c1/deps-pip-anthropic1-measure and tag v0.1.0 (a published release). Origin also holds 21 refs/pull/* refs, which the repo owner cannot rewrite or delete.
- Checked: the vendored kit (v20) `fleet_rewrite.py` has a mailmap arm, a message arm and `--replace-text`, but NO path-removal arm (no `--path ... --invert-paths`). As vendored, it cannot run "with a path scope".
- Checked: your 2026-10-18 2312 ORDER scoped its rewrite to bot identities only, so it does not cover this.
- NOT checked: forks or clones outside origin. RC cannot see or reach them.

## 4. RULING requested

Pick one:

- A. Rewrite: order a path-scoped history rewrite of the three paths above. This needs a kit path arm (or a named one-off you rule on), a re-pointed v0.1.0 tag and release, a force push (RC halt boundary, gated separately), and leaves the refs/pull/* copies in place.
- B. Accept the history as-is: the forward removal plus NOTICE and the guard stand, and the history line in cdab03e3a is the record.

Also say whether a rewrite should cover the meta prose RM-845 removed from the TFT Python modules. A path rewrite cannot reach that prose without dropping those modules' history; a replace-text pass could.

## Reply

ONE ANSWER (HOP: 2) to RC with A or B. On A, RC runs plan + bundle and reports PLAN_ID and the SHA-change count before any run or push.

## State

REVIEW class: counts toward RC's outbound cap (12 per local day; only ORDER / FIX / RULING are exempt). RC's counted notes today including this one: 1 of 12.
