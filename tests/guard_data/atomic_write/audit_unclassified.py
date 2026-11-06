"""`_AUDIT_UNCLASSIFIED` of the atomic-write guard: only shrinks."""
# RM-258 residual (s144): ops/audit/ was exempted wholesale as the row's
# "one-shot generator tree". It is IN scope now; the modules below are the
# ones that still hand-roll a rename or a destination-derived scratch name
# (measured 2026-11-05: 11 modules offended, 11 renames + 10 scratch names, of 38;
# the other 27, ds_cross_eval included, were clean; RM-1713 converted the two
# ds_perm_swarm table builders, build_aram_archetype_override and
# build_marksman_offclass_exempt; RM-1714 converted dsp10_pass2_verify,
# rf4_verify and p2w5_sweep_sliceA). Each is a one-shot audit
# script: no importer outside ops/audit/ and tests (the two cited from
# core/archetype_picks.py and agents/daemon_slayer/rank.py are named in
# comments only), no scheduled task, no poller reading what it writes (the one
# reader, tools/live_flip_watcher.py, loads live_flip_eyeball.json once at
# start and exits when it is absent). An
# entry leaves by converting onto core.polled_json; the set only shrinks, a new
# ops/audit/ writer starts guarded, and an entry that stops offending fails
# test_ops_audit_baseline_is_exact until it is dropped.
ROWS = {
    "ops/audit/ds_perm_swarm/live_flip_eyeball.py",
    "ops/audit/ds_perm_swarm/run_consolidate.py",
    "ops/audit/ds_perm_swarm/run_harness.py",
    "ops/audit/lolmath_ds_sweep/g7_comp_harness.py",
    "ops/audit/p0_inventory.py",
    "ops/audit/p3c24_b1b_sweep.py",
}
