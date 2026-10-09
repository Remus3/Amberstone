# Skip-construct audit - 2026-07-27

Full per-instance disposition of every skip construct in the RC-owned test
set: `tests/`, `agents/daemon_slayer/tests/`, `agents/agent3_testing/suite/`.
Excluded by scope: `python-embed/` (vendored setuptools/distutils),
`docs/_archive/`, `Share/**` (generated mirror), and
`ops/loop/executor.py` + `tests/test_loop_executor.py` (owned by a sibling
agent this cycle).

## The rule applied

A test may skip ONLY when a CAPABILITY is absent from the environment: an OS
feature, a third-party binary or library, a network endpoint, or machine-local
gitignored state. If the THING UNDER TEST is missing, the test must FAIL. A
skip there is a guard that silently degrades into always-passing.

The mechanical discriminator is `git ls-files --error-unmatch <path>`: a
condition that gates on a TRACKED file, a tracked registry key, or an import
of one of our own modules can only be true when the code or the committed data
is broken. That is a DEFECT.

## Summary

| Verdict | Count |
|---|---|
| CAPABILITY-OK | 75 |
| GITIGNORED-DATA-OK | 27 |
| DEFECT-FIXED | 51 |
| FUTURE | 2 |
| **TOTAL** | **155** |

Population: 153 raw regex hits at HEAD `1f66700d`, minus 10
false positives (docstring prose, a `BurstSkipTests` class name, and the
`assertRaises(unittest.SkipTest)` meta-assertions in `test_build_order_precompute.py`
and `test_drift_guard.py` - those are guards ABOUT skips, not skip sites),
giving 143 real constructs, plus 12 `pytest.importorskip`
sites = **155** dispositions.

Line numbers are PRE-FIX positions at HEAD `1f66700d`. DEFECT-FIXED rows no
longer exist at those lines.

## Measured baseline (the TDD 'demonstrate' step)

Before any edit, both suites were run with `-rs`:

- DS `agents/daemon_slayer/tests/`: 10052 passed, **1 skipped**, 5585 subtests.
  The single skip was `test_ehp_shield_phase15.py:449` - `Aatrox has
  aramDamageTaken == 1.0; pick a different sample`. Aatrox's aramDamageTaken IS
  exactly 1.0 in the shipped snapshot, so that test had NEVER asserted anything.
- RC `tests/`: 13476 passed, 145 skipped, 1 pre-existing failure
  (`test_vision_merge_augment_rehome_b01b.py::test_real_fusion_shadow_corpus_invariants`,
  `assert narrowed > 0` over the machine-local `data/fusion_shadow.jsonl` corpus -
  unrelated to this audit and already a hard failure, which is the desired state).

The other DEFECT rows did not fire locally precisely BECAUSE their tracked data
is present - that is the point: they are latent always-pass guards that would
only trigger at the moment the thing they protect broke.

## Per-instance table

| File | Line | Construct | Gates on | Tracked? | Verdict | Reason |
|---|---|---|---|---|---|---|
| `agents/agent3_testing/suite/test_file_task_api.py` | 29 | pytest.skip | agent3 supervisor on :8890 | n/a (network) | CAPABILITY-OK | local supervisor liveness |
| `agents/agent3_testing/suite/test_round14.py` | 36 | pytest.skip | agent3 supervisor on :8890 | n/a (network) | CAPABILITY-OK | local supervisor liveness |
| `agents/daemon_slayer/tests/test_ability_resolution_p1l20.py` | 598 | self.skipTest | Akali emitting both R and R2 casts | YES (combo/block registries) | DEFECT-FIXED | MEASURED tokens E/Q/Q2/R/R2 at level 16; now two assertIn |
| `agents/daemon_slayer/tests/test_block_index_overrides.py` | 4374 | raise | live DS engine on 127.0.0.1:8893 | n/a (network) | CAPABILITY-OK | engine liveness is an external capability; absent engine != broken code |
| `agents/daemon_slayer/tests/test_burst_off_axis_rm41.py` | 227 | raise | live DS engine on 127.0.0.1:8893 | n/a (network) | CAPABILITY-OK | engine liveness is an external capability; absent engine != broken code |
| `agents/daemon_slayer/tests/test_cc_conditional_wave20.py` | 431 | self.skipTest | import of agents.daemon_slayer.cc_pressure | YES (our own module) | DEFECT-FIXED | import failure = broken consumer; try/except removed |
| `agents/daemon_slayer/tests/test_cdragon_ratio_matcher.py` | 49 | pytest.skip | data/daemon_slayer/current.txt | YES (in BOTH trees) | DEFECT-FIXED | tracked pointer; now a plain assert |
| `agents/daemon_slayer/tests/test_cdragon_ratio_matcher.py` | 52 | pytest.skip | cdragon_ability_ratios.json for the current patch | YES (vendored in BOTH trees) | DEFECT-FIXED | pointer-ahead-of-extract is the drift under test; now a plain assert |
| `agents/daemon_slayer/tests/test_cdragon_surplus_ad_a29.py` | 115 | pytest.skip | data/daemon_slayer/current.txt | YES (in BOTH trees) | DEFECT-FIXED | tracked pointer; now a plain assert |
| `agents/daemon_slayer/tests/test_cdragon_surplus_ad_a29.py` | 118 | pytest.skip | cdragon_ability_ratios.json for the current patch | YES (vendored in BOTH trees) | DEFECT-FIXED | pointer-ahead-of-extract is the drift under test; now a plain assert |
| `agents/daemon_slayer/tests/test_changelog_tracks_engine_version.py` | 65 | unittest.skipIf | running from inside the Share mirror tree | n/a (tree shape) | CAPABILITY-OK | keys on the mirror PATH not on file absence, so a deleted CHANGELOG still fails in the main tree |
| `agents/daemon_slayer/tests/test_combo_overrides.py` | 307 | raise | live DS engine on 127.0.0.1:8893 | n/a (network) | CAPABILITY-OK | engine liveness is an external capability; absent engine != broken code |
| `agents/daemon_slayer/tests/test_conditional_block_index_s228.py` | 563 | raise | live DS engine on 127.0.0.1:8893 | n/a (network) | CAPABILITY-OK | engine liveness is an external capability; absent engine != broken code |
| `agents/daemon_slayer/tests/test_cooldown_inheritance.py` | 275 | raise | live DS engine on 127.0.0.1:8893 | n/a (network) | CAPABILITY-OK | engine liveness is an external capability; absent engine != broken code |
| `agents/daemon_slayer/tests/test_ehp.py` | 233 | self.skipTest | aramDamageTaken in [0.5,1.0) | YES (DS snapshot) | DEFECT-FIXED | MEASURED 50 champions; now assertIsNotNone |
| `agents/daemon_slayer/tests/test_ehp.py` | 251 | self.skipTest | aramDamageTaken in (1.0,1.5] | YES (DS snapshot) | DEFECT-FIXED | MEASURED 52 champions; now assertIsNotNone |
| `agents/daemon_slayer/tests/test_ehp.py` | 404 | self.skipTest | non-unit aramDamageTaken | YES (DS snapshot) | DEFECT-FIXED | MEASURED 102 champions; now assertIsNotNone |
| `agents/daemon_slayer/tests/test_ehp_family_seams_reach_the_client_rm115.py` | 88 | raise | live DS engine on 127.0.0.1:8893 | n/a (network) | CAPABILITY-OK | engine liveness is an external capability; absent engine != broken code |
| `agents/daemon_slayer/tests/test_ehp_shield_phase15.py` | 458 | self.skipTest | Aatrox aramDamageTaken != 1.0 | YES (DS snapshot) | DEFECT-FIXED | VACUOUS: Aatrox is exactly 1.0, so this ALWAYS skipped - the only skip in the DS suite. Now selects a non-unit champion and asserts |
| `agents/daemon_slayer/tests/test_form_index_overrides.py` | 330 | raise | live DS engine on 127.0.0.1:8893 | n/a (network) | CAPABILITY-OK | engine liveness is an external capability; absent engine != broken code |
| `agents/daemon_slayer/tests/test_lightshield_strike_burst.py` | 424 | raise | live DS engine on 127.0.0.1:8893 | n/a (network) | CAPABILITY-OK | engine liveness is an external capability; absent engine != broken code |
| `agents/daemon_slayer/tests/test_max_priority_overrides.py` | 360 | raise | live DS engine on 127.0.0.1:8893 | n/a (network) | CAPABILITY-OK | engine liveness is an external capability; absent engine != broken code |
| `agents/daemon_slayer/tests/test_on_hit_per_aa.py` | 181 | raise | live DS engine on 127.0.0.1:8893 | n/a (network) | CAPABILITY-OK | engine liveness is an external capability; absent engine != broken code |
| `agents/daemon_slayer/tests/test_pen_pct_catalog_r160.py` | 226 | self.skipTest | both catalog layouts present | YES in the main repo; Share omits data/meta | DEFECT-FIXED | not flipped blind: now skips on the Share mirror PATH and asserts in the main tree |
| `agents/daemon_slayer/tests/test_r144_mirror_slice_e.py` | 79 | raise | data/meta_build/ddragon/<patch>/item.json | YES (not mirrored to Share) | DEFECT-FIXED | tracked for every patch current.txt names; now a plain assert |
| `agents/daemon_slayer/tests/test_rank_assassin_runes.py` | 38 | raise | Zed/Talon/Qiyana resolving a burst ranking | YES (roster + registry) | DEFECT-FIXED | MEASURED all 3 return 5 rows; now AssertionError |
| `agents/daemon_slayer/tests/test_rm115_tail_seams_reach_the_client.py` | 117 | raise | live DS engine on 127.0.0.1:8893 | n/a (network) | CAPABILITY-OK | engine liveness is an external capability; absent engine != broken code |
| `agents/daemon_slayer/tests/test_rune_hsp_amp_r136.py` | 158 | self.skipTest | vendored runesReforged.json snapshots | YES in the main repo; Share omits meta_build | DEFECT-FIXED | not flipped blind: new _require_rune_files skips on the Share PATH, asserts in the main tree |
| `agents/daemon_slayer/tests/test_rune_hsp_amp_r136.py` | 184 | self.skipTest | vendored runesReforged.json snapshots | YES in the main repo; Share omits meta_build | DEFECT-FIXED | same helper as above |
| `agents/daemon_slayer/tests/test_rune_offense_saturation_r158.py` | 88 | raise | a vendored runesReforged.json snapshot | YES in the main repo; Share omits meta_build | DEFECT-FIXED | not flipped blind: new _require_feed_path skips on the Share PATH, asserts in the main tree |
| `agents/daemon_slayer/tests/test_rune_offense_saturation_r158.py` | 97 | raise | a vendored runesReforged.json snapshot | YES in the main repo; Share omits meta_build | DEFECT-FIXED | same helper as above |
| `agents/daemon_slayer/tests/test_spellblade_burst.py` | 480 | raise | live DS engine on 127.0.0.1:8893 | n/a (network) | CAPABILITY-OK | engine liveness is an external capability; absent engine != broken code |
| `agents/daemon_slayer/tests/test_sum_of_blocks.py` | 431 | raise | live DS engine on 127.0.0.1:8893 | n/a (network) | CAPABILITY-OK | engine liveness is an external capability; absent engine != broken code |
| `agents/daemon_slayer/tests/test_wireable_sims_p1l3.py` | 249 | self.skipTest | Stormrazor 3097 in ITEM_EFFECTS | YES (python registry) | DEFECT-FIXED | MEASURED present; now assertIsNotNone |
| `agents/daemon_slayer/tests/test_wireable_sims_p1l3.py` | 254 | self.skipTest | Stormrazor constant-damage periodic | YES (python registry) | DEFECT-FIXED | MEASURED 1 periodic; now assertIsNotNone |
| `agents/daemon_slayer/tests/test_wireable_sims_p1l3.py` | 387 | self.skipTest | a curated heal-throughput enchanter item | YES (curated formulas) | DEFECT-FIXED | MEASURED 3 items; now assertIsNotNone |
| `agents/daemon_slayer/tests/test_wireable_sims_p1l3.py` | 723 | self.skipTest | a bonus_ap_stacked item | YES (python registry) | DEFECT-FIXED | MEASURED 2 items; now assertIsNotNone |
| `tests/phase8_smoke/test_sr_draft_profile_engine.py` | 269 | self.skipTest | live DS engine on 127.0.0.1:8893 | n/a (network) | CAPABILITY-OK | engine liveness is an external capability; absent engine != broken code |
| `tests/snapshot_panels/test_xss_escaping.py` | 49 | pytest.skip | `node` on PATH | n/a (third-party binary) | CAPABILITY-OK | JS helper needs a node runtime; not shipped by the repo |
| `tests/snapshot_regressions/test_app_authority.py` | 189 | self.skipTest | ally_details in the _RICH_SR_STATE fixture | YES (in-module literal) | DEFECT-FIXED | fixture shape fixed at author time; now assertTrue |
| `tests/snapshot_regressions/test_app_authority.py` | 202 | self.skipTest | enemy_details in the _RICH_SR_STATE fixture | YES (in-module literal) | DEFECT-FIXED | fixture shape fixed at author time; now assertTrue |
| `tests/test_build_order_alias_dedupe_w3.py` | 305 | raise | live DS engine on 127.0.0.1:8893 | n/a (network) | CAPABILITY-OK | engine liveness is an external capability; absent engine != broken code |
| `tests/test_build_order_boots.py` | 357 | self.skipTest | data/daemon_slayer/16.12.1/items.json | YES | DEFECT-FIXED | reason said 'clean checkout' but the file is committed; now assertTrue |
| `tests/test_build_order_content_freshness.py` | 169 | mark.skipif | RC_BUILD_ORDER_FULL_REGEN | n/a (env opt-in) | CAPABILITY-OK | slow full-roster regen guard, nightly/on-demand not per-commit |
| `tests/test_build_order_precompute.py` | 84 | raise | a GENERATED build-order table | no (regenerated artifact) | CAPABILITY-OK | mid-regen checkout has none; RC_REQUIRE_BUILD_ORDER_TABLES=1 escalates it to a failure |
| `tests/test_build_order_precompute.py` | 131 | raise | git-lfs content fetched into the checkout | pointer tracked, content not | CAPABILITY-OK | LFS fetch is a separate CI concern (~190MB); deliberately skips even when the table flag is armed |
| `tests/test_build_order_variants.py` | 255 | self.skipTest | import of core.daemon_slayer_client | YES (our own module) | DEFECT-FIXED | import failure = broken code; guard removed, ImportError propagates |
| `tests/test_build_order_variants.py` | 257 | self.skipTest | live DS engine on 127.0.0.1:8893 | n/a (network) | CAPABILITY-OK | engine liveness is an external capability; absent engine != broken code |
| `tests/test_build_orders_family_a_guard.py` | 391 | pytest.skip | live DS engine on 127.0.0.1:8893 | n/a (network) | CAPABILITY-OK | engine liveness is an external capability; absent engine != broken code |
| `tests/test_build_orders_family_a_guard.py` | 422 | mark.skipif | RC_BUILD_ORDER_LIVE_PARITY + :8893 | n/a (env opt-in + network) | CAPABILITY-OK | slow live dock-parity lane, nightly/on-demand not per-commit |
| `tests/test_build_orders_family_a_guard.py` | 472 | mark.skipif | RC_BUILD_ORDER_LIVE_PARITY + :8893 | n/a (env opt-in + network) | CAPABILITY-OK | slow live dock-parity lane, nightly/on-demand not per-commit |
| `tests/test_champ_select_ban_provenance_dom.py` | 113 | unittest.skipUnless | `node` on PATH | n/a (third-party binary) | CAPABILITY-OK | JS helper needs a node runtime; not shipped by the repo |
| `tests/test_champ_select_pick_placeholder_provenance.py` | 117 | unittest.skipUnless | `node` on PATH | n/a (third-party binary) | CAPABILITY-OK | JS helper needs a node runtime; not shipped by the repo |
| `tests/test_champ_select_rune_follows_build.py` | 140 | unittest.skipUnless | `node` on PATH | n/a (third-party binary) | CAPABILITY-OK | JS helper needs a node runtime; not shipped by the repo |
| `tests/test_coach_choices_trigger_render.py` | 28 | pytest.skip | `node` on PATH | n/a (third-party binary) | CAPABILITY-OK | JS helper needs a node runtime; not shipped by the repo |
| `tests/test_cross_mode_ds_p1l6.py` | 231 | self.skipTest | a champion with non-unit aram_modifiers | YES (DS snapshot) | DEFECT-FIXED | MEASURED 101 dealt / 102 taken; now self.fail |
| `tests/test_csv_push_swap_wipe.py` | 104 | unittest.skipUnless | `node` on PATH | n/a (third-party binary) | CAPABILITY-OK | JS helper needs a node runtime; not shipped by the repo |
| `tests/test_csv_push_toggles_phase5.py` | 147 | unittest.skipUnless | `node` on PATH | n/a (third-party binary) | CAPABILITY-OK | JS helper needs a node runtime; not shipped by the repo |
| `tests/test_dashboard_condense_rc2.py` | 73 | unittest.skipUnless | `node` on PATH | n/a (third-party binary) | CAPABILITY-OK | JS helper needs a node runtime; not shipped by the repo |
| `tests/test_dashboard_condense_rc2.py` | 186 | unittest.skipUnless | `node` on PATH | n/a (third-party binary) | CAPABILITY-OK | JS helper needs a node runtime; not shipped by the repo |
| `tests/test_ddragon_mirror_prune.py` | 63 | mark.skipif | sys.platform == win32 | n/a (OS feature) | CAPABILITY-OK | Windows junction / reparse-point semantics |
| `tests/test_ddragon_mirror_prune.py` | 77 | pytest.skip | symlink create privilege | n/a (OS privilege) | CAPABILITY-OK | unprivileged Windows accounts cannot create symlinks |
| `tests/test_drift_guard.py` | 95 | raise | git core.hooksPath (LOCAL config) | no (local git config, never cloned) | CAPABILITY-OK | fresh clone genuinely has no hooks; RC_REQUIRE_HOOK_GATE=1 escalates it to a failure |
| `tests/test_ds_ability_data_status_rm95.py` | 190 | pytest.skip | _live_patch() == '16.14.1' | YES (current.txt says 16.14.1) | FUTURE | decidable TODAY, but it is a deliberate patch pin - a patch bump would turn CI red on a finding that legitimately needs re-measuring, which is the brittle-against-a-future-re-extract case. Needs a re-pin policy, not a blind flip |
| `tests/test_ds_calibration_agreement.py` | 359 | pytest.skip | agents/daemon_slayer/ dir | YES | DEFECT-FIXED | tracked package; now a plain assert |
| `tests/test_ds_client_conversion_seam_plumb_w2.py` | 400 | unittest.skipUnless | live DS engine on 127.0.0.1:8893 | n/a (network) | CAPABILITY-OK | engine liveness is an external capability; absent engine != broken code |
| `tests/test_ds_pick_consumption_p1l11.py` | 372 | unittest.skipUnless | `node` on PATH | n/a (third-party binary) | CAPABILITY-OK | JS helper needs a node runtime; not shipped by the repo |
| `tests/test_ds_share_ingest_sync.py` | 46 | self.skipTest | dist/daemon_slayer_bundle.json | NO (gitignored) | GITIGNORED-DATA-OK | built bundle, absent on a clean checkout |
| `tests/test_git_hook_gate_e2e.py` | 127 | unittest.skipUnless | `git` on PATH | n/a (third-party binary) | CAPABILITY-OK | end-to-end hook test shells out to git |
| `tests/test_git_hook_gate_e2e.py` | 142 | unittest.skipUnless | `git` on PATH | n/a (third-party binary) | CAPABILITY-OK | end-to-end hook test shells out to git |
| `tests/test_hexcore_offline_dust.py` | 218 | pytest.skip | `node` on PATH | n/a (third-party binary) | CAPABILITY-OK | JS helper needs a node runtime; not shipped by the repo |
| `tests/test_hotkey_lowlevel_decoder.py` | 27 | pytest.skip | sys.platform == win32 | n/a (OS feature) | CAPABILITY-OK | Win32-only hotkey listener |
| `tests/test_hotkey_panel_cycle_signal.py` | 25 | pytest.skip | sys.platform == win32 | n/a (OS feature) | CAPABILITY-OK | Win32-only hotkey listener |
| `tests/test_idempotent_stream_gate.py` | 31 | pytest.skip | `node` on PATH | n/a (third-party binary) | CAPABILITY-OK | JS helper needs a node runtime; not shipped by the repo |
| `tests/test_item_wpa.py` | 105 | self.skipTest | load_legendary_ids() returning {} | YES data/daemon_slayer/*/items.json | DEFECT-FIXED | empty catalog = broken loader; now assertTrue |
| `tests/test_item_wpa.py` | 122 | self.skipTest | BF Sword classified as legendary | YES (same catalog) | DEFECT-FIXED | decidable data shape; now assertNotIn |
| `tests/test_item_wpa.py` | 226 | self.skipTest | IE / Lord Dominik's in the catalog | YES (same catalog) | DEFECT-FIXED | decidable data shape; now two assertIn |
| `tests/test_item_wpa.py` | 299 | unittest.skipUnless | data/rewind_history.db | NO (gitignored) | GITIGNORED-DATA-OK | machine-local match corpus; CI is a clean checkout |
| `tests/test_json_authored_glyph_hygiene.py` | 108 | pytest.skip | data/daemon_slayer/spell_cast_rates.json | YES | DEFECT-FIXED | tracked artifact; now a plain assert |
| `tests/test_json_authored_glyph_hygiene.py` | 121 | pytest.skip | scripts/build_spell_cast_rates.py | YES | DEFECT-FIXED | tracked generator; now a plain assert |
| `tests/test_json_authored_glyph_hygiene.py` | 133 | pytest.skip | cast-rate source AND its Share mirror | YES (both committed) | DEFECT-FIXED | a missing half IS the mirror drift under test; now two asserts |
| `tests/test_live_benchmark_band_robustness.py` | 136 | pytest.skip | canonical_champion_id resolving 4 multiword names | YES (champion data) | DEFECT-FIXED | MEASURED all 4 resolve; a mismatch IS the item-447 bug; now a plain assert |
| `tests/test_lobby_invite_resolution.py` | 226 | unittest.skipUnless | RC_LIVE_LOBBY + a live League lobby | n/a (live client) | CAPABILITY-OK | live-LCU integration, deliberately opt-in |
| `tests/test_loop_concurrency.py` | 52 | pytest.skip | sibling Sibling-A tree at C:/Sibling-A | n/a (external repo) | CAPABILITY-OK | cross-repo byte-identity check; SHARED_SHA256 digests untouched by this audit |
| `tests/test_loop_concurrency.py` | 272 | mark.skipif | sys.platform == win32 | n/a (OS feature) | CAPABILITY-OK | Windows named-mutex semantics |
| `tests/test_loop_concurrency.py` | 423 | pytest.skip | sibling Sibling-A tree at C:/Sibling-A | n/a (external repo) | CAPABILITY-OK | cross-repo byte-identity check; SHARED_SHA256 digests untouched by this audit |
| `tests/test_minimap_blob_detect_precision.py` | 85 | pytest.skip | SR minimap corpus frames | NO (gitignored) | GITIGNORED-DATA-OK | live-grab capture corpus, primary checkout only |
| `tests/test_minimap_blob_detect_precision.py` | 102 | pytest.skip | SR minimap corpus frames | NO (gitignored) | GITIGNORED-DATA-OK | live-grab capture corpus, primary checkout only |
| `tests/test_minimap_identity.py` | 35 | mark.skipif | opencv-python installed | n/a (third-party lib) | CAPABILITY-OK | cv2 is an optional dependency |
| `tests/test_obs_frame_source.py` | 326 | pytest.skip | numpy installed | n/a (third-party lib) | CAPABILITY-OK | optional dependency |
| `tests/test_obs_frame_source.py` | 342 | pytest.skip | numpy installed | n/a (third-party lib) | CAPABILITY-OK | optional dependency |
| `tests/test_obs_frame_source.py` | 348 | pytest.skip | PIL installed | n/a (third-party lib) | CAPABILITY-OK | optional dependency |
| `tests/test_obs_frame_source.py` | 368 | pytest.skip | numpy installed | n/a (third-party lib) | CAPABILITY-OK | optional dependency |
| `tests/test_overlay_idle_rc2.py` | 58 | unittest.skipUnless | `node` on PATH | n/a (third-party binary) | CAPABILITY-OK | JS helper needs a node runtime; not shipped by the repo |
| `tests/test_overlay_idle_rc2.py` | 147 | unittest.skipUnless | `node` on PATH | n/a (third-party binary) | CAPABILITY-OK | JS helper needs a node runtime; not shipped by the repo |
| `tests/test_overlay_priority_rc2.py` | 57 | unittest.skipUnless | `node` on PATH | n/a (third-party binary) | CAPABILITY-OK | JS helper needs a node runtime; not shipped by the repo |
| `tests/test_overlay_pulse_flip_rc2.py` | 91 | unittest.skipUnless | `node` on PATH | n/a (third-party binary) | CAPABILITY-OK | JS helper needs a node runtime; not shipped by the repo |
| `tests/test_overlay_pulse_flip_rc2.py` | 150 | unittest.skipUnless | `node` on PATH | n/a (third-party binary) | CAPABILITY-OK | JS helper needs a node runtime; not shipped by the repo |
| `tests/test_overlay_settings_rc2.py` | 94 | unittest.skipUnless | `node` on PATH | n/a (third-party binary) | CAPABILITY-OK | JS helper needs a node runtime; not shipped by the repo |
| `tests/test_p2w1_core_c.py` | 173 | self.skipTest | data/daemon_slayer/current.txt | YES | DEFECT-FIXED | class docstring itself called these 'the tracked data files'; now assertTrue |
| `tests/test_p2w1_core_c.py` | 176 | self.skipTest | patch-current items.json | YES | DEFECT-FIXED | pointer-ahead-of-bundle is the pin drift under test; now assertTrue |
| `tests/test_p2w1_core_c.py` | 181 | self.skipTest | meta_build/ddragon/_index.json | YES | DEFECT-FIXED | tracked marker; now assertTrue |
| `tests/test_p2w1_core_c.py` | 186 | self.skipTest | latest_pulled runesReforged bundle | YES | DEFECT-FIXED | latest_pulled=16.14.1 and that bundle is committed; now assertTrue |
| `tests/test_p2w1_core_c.py` | 193 | self.skipTest | meta_build/ddragon/_index.json | YES | DEFECT-FIXED | tracked marker; now assertTrue |
| `tests/test_p2w1_core_c.py` | 198 | self.skipTest | latest_pulled summoner bundle | YES | DEFECT-FIXED | latest_pulled=16.14.1 and that bundle is committed; now assertTrue |
| `tests/test_pengu_plugin_skeleton.py` | 22 | mark.skipif | a pengu/ stub at the repo root | NO (relocated to docs/_archive/2026-07-07-pengu-stub) | FUTURE | the thing under test is GONE, so by the principle it should fail - but the relocation was deliberate and converting means permanently red CI. Needs the operator's open BACKLOG question answered (does the stub return, or does this module get deleted?) |
| `tests/test_personal_build_wr.py` | 164 | self.skipTest | data/rewind_history.db | NO (gitignored) | GITIGNORED-DATA-OK | machine-local match corpus; CI is a clean checkout |
| `tests/test_playstyle_labels.py` | 248 | pytest.skip | data/rewind_history.db | NO (gitignored) | GITIGNORED-DATA-OK | machine-local match corpus; CI is a clean checkout |
| `tests/test_pro_match_index.py` | 29 | pytest.skip | pro roster .xlsx | NO (gitignored) | GITIGNORED-DATA-OK | machine-local spreadsheet |
| `tests/test_pro_match_index.py` | 36 | pytest.skip | data/rewind_history.db | NO (gitignored) | GITIGNORED-DATA-OK | machine-local match corpus; CI is a clean checkout |
| `tests/test_pro_match_index.py` | 65 | pytest.skip | data/rewind_history.db | NO (gitignored) | GITIGNORED-DATA-OK | machine-local match corpus; CI is a clean checkout |
| `tests/test_rc2_p73_quarantine.py` | 73 | pytest.skip | _archive/2026-06-20-rc2-p73/ | NO (gitignored, 0 tracked files under _archive/) | GITIGNORED-DATA-OK | local-only quarantine hygiene guard |
| `tests/test_rofl_stats_backfill.py` | 47 | mark.skipif | .rofl sidecar archive + rewind db | NO (gitignored) | GITIGNORED-DATA-OK | machine-local replay archive |
| `tests/test_rofl_stats_backfill.py` | 184 | pytest.skip | an archived .rofl for the match | NO (gitignored) | GITIGNORED-DATA-OK | machine-local replay archive |
| `tests/test_routes_bench_role_bracket.py` | 221 | self.skipTest | data/rewind_history.db | NO (gitignored) | GITIGNORED-DATA-OK | machine-local match corpus; CI is a clean checkout |
| `tests/test_routes_champ_benchmarks.py` | 235 | self.skipTest | data/champion_benchmarks.json | NO (untracked) | GITIGNORED-DATA-OK | generated benchmark artifact |
| `tests/test_rune_wpa.py` | 326 | self.skipTest | load_rune_names() returning {} | YES data/meta_build/ddragon/*/runesReforged.json | DEFECT-FIXED | empty catalog = broken loader; now assertTrue |
| `tests/test_rune_wpa.py` | 335 | self.skipTest | Electrocute name resolution | YES (same catalog) | DEFECT-FIXED | decidable; now assertEqual |
| `tests/test_rune_wpa.py` | 348 | unittest.skipUnless | data/rewind_history.db | NO (gitignored) | GITIGNORED-DATA-OK | machine-local match corpus; CI is a clean checkout |
| `tests/test_session_hygiene.py` | 394 | pytest.skip | data/rewind_history.db | NO (gitignored) | GITIGNORED-DATA-OK | machine-local match corpus; CI is a clean checkout |
| `tests/test_set_augment_intent_handler.py` | 258 | unittest.skipUnless | RC_LIVE_ARENA + a live Arena augment phase | n/a (live client) | CAPABILITY-OK | live-LCU integration, deliberately opt-in |
| `tests/test_silent_except_arena_augment_cache.py` | 70 | mark.skipif | data/daemon_slayer/*/arena_augments.json | YES (5 patch dirs committed) | DEFECT-FIXED | module-wide skipif retired 3 cache tests; replaced by a meta-test assertion |
| `tests/test_skill_wpa.py` | 248 | self.skipTest | data/rewind_history.db | NO (gitignored) | GITIGNORED-DATA-OK | machine-local match corpus; CI is a clean checkout |
| `tests/test_smoothed_rates_101qq.py` | 89 | self.skipTest | len(top_duos_for_bot('Smolder')) >= 2 | YES (static seed committed) | DEFECT-FIXED | MEASURED 10; now assertGreaterEqual |
| `tests/test_smoothed_rates_101qq.py` | 119 | self.skipTest | len(top_duos_for_sup('Brand')) >= 2 | YES (static seed committed) | DEFECT-FIXED | MEASURED 10; now assertGreaterEqual |
| `tests/test_smoothed_rates_101qq.py` | 151 | self.skipTest | len(top_solo_picks('bot')) >= 2 | YES (static seed committed) | DEFECT-FIXED | MEASURED 20; now assertGreaterEqual |
| `tests/test_stats_panel_kp_live.py` | 107 | unittest.skipUnless | `node` on PATH | n/a (third-party binary) | CAPABILITY-OK | JS helper needs a node runtime; not shipped by the repo |
| `tests/test_status_helper_rc2.py` | 54 | unittest.skipUnless | `node` on PATH | n/a (third-party binary) | CAPABILITY-OK | JS helper needs a node runtime; not shipped by the repo |
| `tests/test_summspell_wpa.py` | 319 | self.skipTest | load_spell_names() returning {} | YES data/meta_build/ddragon/*/summoner.json | DEFECT-FIXED | empty catalog = broken loader; now assertTrue |
| `tests/test_summspell_wpa.py` | 328 | self.skipTest | Flash name resolution | YES (same catalog) | DEFECT-FIXED | decidable; now assertEqual |
| `tests/test_summspell_wpa.py` | 343 | unittest.skipUnless | data/rewind_history.db | NO (gitignored) | GITIGNORED-DATA-OK | machine-local match corpus; CI is a clean checkout |
| `tests/test_u2500_candidate_sweep.py` | 89 | pytest.skip | _archive/2026-05-01-audit/** source file | NO (0 tracked files under _archive/) | GITIGNORED-DATA-OK | decommissioned quarantine tree, absent by design |
| `tests/test_u2500_candidate_sweep.py` | 100 | pytest.skip | _archive/2026-05-01-audit/** source file | NO (0 tracked files under _archive/) | GITIGNORED-DATA-OK | decommissioned quarantine tree, absent by design |
| `tests/test_u2500_candidate_sweep.py` | 111 | pytest.skip | _archive/2026-05-01-audit/** source file | NO (0 tracked files under _archive/) | GITIGNORED-DATA-OK | decommissioned quarantine tree, absent by design |
| `tests/test_u2500_candidate_sweep.py` | 122 | pytest.skip | _archive/2026-05-01-audit/** source file | NO (0 tracked files under _archive/) | GITIGNORED-DATA-OK | decommissioned quarantine tree, absent by design |
| `tests/test_u2500_candidate_sweep.py` | 133 | pytest.skip | _archive/2026-05-01-audit/** source file | NO (0 tracked files under _archive/) | GITIGNORED-DATA-OK | decommissioned quarantine tree, absent by design |
| `tests/test_u2500_candidate_sweep.py` | 144 | pytest.skip | _archive/2026-05-01-audit/** source file | NO (0 tracked files under _archive/) | GITIGNORED-DATA-OK | decommissioned quarantine tree, absent by design |
| `tests/test_u2500_candidate_sweep.py` | 155 | pytest.skip | _archive/2026-05-01-audit/** source file | NO (0 tracked files under _archive/) | GITIGNORED-DATA-OK | decommissioned quarantine tree, absent by design |
| `tests/test_u2500_candidate_sweep.py` | 166 | pytest.skip | web/legacy_index.html | YES | DEFECT-FIXED | reason claimed gitignored/decommissioned but it is tracked + present; now a plain assert |
| `tests/test_u2500_candidate_sweep.py` | 177 | pytest.skip | ops/rc_config.json | YES | DEFECT-FIXED | reason claimed gitignored/decommissioned but it is tracked + present; now a plain assert |
| `tests/test_vision_atlas_precompute.py` | 134 | pytest.skip | vtm.list_ids('items') | YES data/icons/items/ (36 files) | DEFECT-FIXED | cv2 above is the real gate; now a plain assert |
| `tests/test_vision_merge_augment_rehome_b01b.py` | 256 | pytest.skip | data/fusion_shadow.jsonl | NO (untracked) | GITIGNORED-DATA-OK | machine-local shadow ledger |
| `tests/test_vision_profile_2560_ocr_boxes.py` | 43 | pytest.skip | 2560x1440 HUD profiles | NO (gitignored) | GITIGNORED-DATA-OK | per-machine vision calibration state |
| `tests/test_minimap_blob_detect.py` | 6 | importorskip | `numpy` installed | n/a (third-party lib) | CAPABILITY-OK | optional dependency, absent in a minimal env |
| `tests/test_minimap_blob_detect_hold.py` | 13 | importorskip | `numpy` installed | n/a (third-party lib) | CAPABILITY-OK | optional dependency, absent in a minimal env |
| `tests/test_minimap_blob_detect_precision.py` | 30 | importorskip | `numpy` installed | n/a (third-party lib) | CAPABILITY-OK | optional dependency, absent in a minimal env |
| `tests/test_minimap_blob_detect_precision.py` | 31 | importorskip | `PIL.Image` installed | n/a (third-party lib) | CAPABILITY-OK | optional dependency, absent in a minimal env |
| `tests/test_minimap_identity.py` | 20 | importorskip | `numpy` installed | n/a (third-party lib) | CAPABILITY-OK | optional dependency, absent in a minimal env |
| `tests/test_minimap_native_grab.py` | 13 | importorskip | `numpy` installed | n/a (third-party lib) | CAPABILITY-OK | optional dependency, absent in a minimal env |
| `tests/test_minimap_native_grab.py` | 97 | importorskip | `PIL.ImageGrab` installed | n/a (third-party lib) | CAPABILITY-OK | optional dependency, absent in a minimal env |
| `tests/test_vision_atlas_precompute.py` | 131 | importorskip | `cv2` installed | n/a (third-party lib) | CAPABILITY-OK | optional dependency, absent in a minimal env |
| `tests/test_vision_atlas_precompute.py` | 141 | importorskip | `cv2` installed | n/a (third-party lib) | CAPABILITY-OK | optional dependency, absent in a minimal env |
| `tests/test_vision_atlas_precompute.py` | 159 | importorskip | `cv2` installed | n/a (third-party lib) | CAPABILITY-OK | optional dependency, absent in a minimal env |
| `tests/test_vision_atlas_validate.py` | 27 | importorskip | `cv2` installed | n/a (third-party lib) | CAPABILITY-OK | optional dependency, absent in a minimal env |
| `tests/test_vision_template_match_r96.py` | 19 | importorskip | `cv2` installed | n/a (third-party lib) | CAPABILITY-OK | optional dependency, absent in a minimal env |

## FUTURE rows (deliberately NOT flipped)

Both are decidable against tracked state TODAY, so a naive reading calls them
defects. Neither conversion is clean-checkout-safe as a mechanical flip:

1. `tests/test_ds_ability_data_status_rm95.py:190` - `_live_patch() != "16.14.1"`.
   `current.txt` says 16.14.1, so the skip is dead code right now. But the test
   is named `..._at_1614` and pins an RM-95 finding to that specific snapshot.
   Converting means the next patch bump turns CI red on a finding that
   legitimately has to be re-measured. That is exactly the
   brittle-against-a-future-patch-re-extract case the audit brief carves out.
   The right fix is a re-pin policy (assert the pin matches current.txt AND
   force a conscious re-measure on bump), which is a separate decision.

2. `tests/test_pengu_plugin_skeleton.py:22` - `not PENGU.is_dir()`. The `pengu/`
   stub was relocated to `docs/_archive/2026-07-07-pengu-stub/`, so the module
   currently skips all 6 of its tests. By the principle the thing under test is
   GONE and this should fail - but the relocation was deliberate, and the file's
   own comment carries an open BACKLOG question (was the archival intended, or
   should the stub return to `pengu/`?). Converting = permanently red CI;
   deleting the module is a scope call. Needs the operator to answer the
   BACKLOG question.

## Cross-tree note (why three fixes are not plain asserts)

`agents/daemon_slayer/tests/**` is mirrored verbatim into `Share/src/`, and the
Share handoff deliberately does NOT vendor `data/meta` or `data/meta_build`.
Three converted sites read exactly those trees, so a plain assert would have
been green in the main repo and red inside Share:

- `test_pen_pct_catalog_r160.py` (both catalog layouts)
- `test_rune_hsp_amp_r136.py` (vendored runesReforged snapshots)
- `test_rune_offense_saturation_r158.py` (newest runesReforged snapshot)

Each now discriminates on the mirror PATH (`_IS_SHARE_MIRROR`) and asserts in
the main tree, following the existing
`test_changelog_tracks_engine_version.py` precedent. That precedent's own
comment states the reason: keying on the file's ABSENCE would let a genuinely
deleted file silently skip in the main tree, which is the failure the guard
exists to catch. `test_r144_mirror_slice_e.py` reads the same tree but is NOT
mirrored, so it took a plain assert.

`data/daemon_slayer/current.txt` and `cdragon_ability_ratios.json` ARE vendored
into both trees, so the two CDragon helpers took plain asserts.

One extra trap, caught by
`test_no_mirrored_module_hard_depends_on_an_unshipped_path` during this work:
that guard statically scans mirrored test modules for root-anchored path joins
and forgives only the ones consumed by a tolerant method (`.glob` / `.exists` /
`.is_dir` / ...). The pre-existing
`(_REPO_ROOT / "data" / "meta_build" / "ddragon").glob(...)` lookups were
therefore invisible to it - but building the SAME join again purely to format an
assertion message is a HARD reference, and it turned the guard red. Both new
failure messages now name the directory as a plain string literal. Anyone
converting a skip in a mirrored DS test must not interpolate a repo path into
the failure text.

After the conversions, `tools/ds_share_sync.py` was re-run so the 10 mirrored DS
test files plus `Share/MANIFEST.md` land in the same commit as their sources.
The Share tree's own suite was then run from `Share/src` to confirm the
`_IS_SHARE_MIRROR` branches skip there with a precise reason instead of failing.

## Not touched

`tests/test_loop_concurrency.py` carries the `SHARED_SHA256` cross-repo
byte-identity pins. Its two Sibling-A skips and its win32 skip are
CAPABILITY-OK and were left exactly as-is; no digest was read, regenerated, or
modified.

## Regression guard (R203, same day)

The audit above fixed 51 instances and shipped no machine guard, so instance
#52 could land unnoticed. `tests/test_skip_condition_hygiene.py` closes that:
an AST scanner over every module under `tests/**` and
`agents/daemon_slayer/tests/**` that resolves each skip condition and FAILS
when the condition gates on a git-TRACKED artifact.

Two predecessor lessons shaped it, both from
`tests/test_no_console_flash_scheduled_tools.py` before `80bb813f`:

- The universe is GLOBBED (`rglob`, 1236 modules), never a hand-written list.
  A hand list is how that guard went green over the exact class it existed to
  catch.
- Classification is `ast.parse` with scope chains, name bindings and
  cross-module resolution - never substring grep. A grep for a literal is
  satisfied by a module that passes the value to nothing.

Corpus at landing: 107 skip sites, 106 CAPABILITY, 1 allowlisted FUTURE row.

**The guard found instance #52 on its first real run.**
`tests/test_routes_champ_benchmarks.py:235` skipped when
`data/coach_reference/champion_benchmarks.json` was absent. The disposition
table above recorded it as gating on an untracked `data/champion_benchmarks.json`;
the code gates on the `coach_reference/` path, which IS tracked - and the
module docstring already said so ("it is checked in, not gitignored"). That
skip had never been able to fire. Converted to a hard assert in the same slice.

`_ALLOWLIST` holds exactly one entry, the RM-95 patch-pin FUTURE row. Entries
are scoped to the EXACT tracked artifact set they excuse, not to the module, so
a new skip in an allowlisted module still fails. Three anti-rot tests assert
every entry still exists on disk, still flags, and still excuses only what it
claims.

### Known limits (measured, live exposure zero)

- An `and`-joined compound gate (`not TRACKED.exists() and sys.platform == ...`)
  classifies CAPABILITY because a capability signal wins regardless of the
  boolean operator. Such a gate can never fire. Three real sites rely on the
  masking rule and all three are legitimately capability-gated.
- `import sys as _s` / `from sys import platform` resolve UNRESOLVED, which the
  guard treats as failure. Fails loud, not silent.

An aliased-module hole was found by the verifier and closed before landing:
`import pytest as _p` + `_p.skip(...)` was invisible to the scanner because
`pytest.skip` is matched on the full dotted chain (a bare `.skip` tail would
collect unrelated calls). `_canonical_call` now rewrites the alias head.
Pinned by `aliased_pytest_bare_skip_on_tracked_path`; with the rewrite
suppressed the site scans to zero findings.

---

## RM-119 class B2 - the DS live-route gates (2026-08-06, CLOSED)

The rows in the table above marked "live DS engine on 127.0.0.1:8893" are the
B2 class. (The port literal in those rows is stale - DS moved to `:8860` at
RM-129, item 1146. The rows are a dated snapshot and are left as written.)

B2 was filed as "19 DS live-route sites". Re-derived rather than inherited:
the true pre-slice census is **20 skip control points across 18 modules**.

**Verdict: all 20 are class A - a legitimate capability gate. None is dead.**

- All 34 live paths (31 `_POST_ROUTES` plus `/health`, `/snapshot`,
  `/modifier-summary`) were probed read-only at ENGINE 1.275.0 - audit CLOSED
  2026-08-06, so this is a dated measurement and not a currency claim; the live
  engine has moved on since - at patch 16.15.1. Every one answered. The single non-200
  was `/v2/matchup` returning 400 for a field the probe body did not supply,
  which still proves dispatch.
- No workflow starts the engine. A case-insensitive grep of the whole
  `.github/` tree for `8860`, for `start_daemon_slayer`, and for any
  daemon-slayer serve/start/launch verb returns nothing.

The masking B2 named is real, but it is not in the skip CONDITION - it is that
nothing ever declared the engine REQUIRED. Fixed with a third instance of the
idiom this audit already established twice:

| Flag | Set by | Documented in |
|---|---|---|
| `RC_REQUIRE_HOOK_GATE` | CI (`ci.yml`) | this doc, `docs/ORCHESTRATION_PLAN.md` |
| `RC_REQUIRE_BUILD_ORDER_TABLES` | CI (`ci.yml`) | this doc, `docs/ORCHESTRATION_PLAN.md` |
| `RC_REQUIRE_DS_ENGINE` | **nothing - operator only** | this doc, `docs/OPERATIONS.md` |

That third row is the load-bearing difference and is deliberate: no GitHub
runner has a Daemon Slayer, so there is no CI job to set it in. It is a
Legion / operator knob. `docs/OPERATIONS.md` carries the command.

Seven modules route through the shared gate
`tests/test_ds_live_route_gate.require_live_engine` - the five in `tests/`,
plus the two RM-115 seam modules in the DS tree, which are named in
`tools/ds_share_sync._HOST_DEPENDENT_TESTS` and so are not mirrored into
`Share/src` at all. The remaining eleven DS-tree gates are stdlib-only and ARE
mirrored behind a hard CI gate, so they stay put and are covered class-wide by
`LiveRouteSurfaceTests`, which under the flag probes the whole route surface
and asserts `/health` matches the checkout's `ENGINE_VERSION`.

`tests/test_skip_condition_hygiene.py` now recognises `require_live_engine` as
a skip construct. Without that it lost sight of six of the seven adopted sites
(7 visible sites across those modules before, 1 after) - a refactor can shrink
a guard's population as effectively as a hand-kept list can.
