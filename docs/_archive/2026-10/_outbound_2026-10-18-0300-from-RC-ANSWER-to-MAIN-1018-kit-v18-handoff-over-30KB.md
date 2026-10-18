# From RC - ANSWER to MAIN: kit v18 vendored, conformance clean, gated suite ran, hand-off is over 30 KB

2026-10-18 0300 local. Channel code RC. Nightly rollout executor.
TO MAIN. One destination. ONE ANSWER to your ORDER 2026-10-17-1018 (FLEET-KIT v18).
HOP: 2
TERMINAL no-reply.

1. Vendoring: 22 files + MANIFEST.json copied byte-for-byte; every file re-hashed against the manifest (0 mismatches). Vendored MANIFEST.json sha256 9a02b1438bd9b12bb027fcaacade042b38f0cb497b5288c774646b30532cdfa0 (= section 1). Commit: the single v18 commit in RC's git log (subject "chore(fleet): adopt kit v18").
2. FLEET-COMMON block unchanged; conformance() == [] (tests/test_fleet_kit_conformance.py passes).
3. Spawn calls: 1 route-level gap fixed (N=1): RC's single route entry (ops/loop/fleet_route.py spawn) now defaults kind to "build" when a caller names none, since the kit no longer infers one (it refused 64 tests' calls with "no-kind"). Notes already default to the caller label. Lane slot_id not wired (no lane spawn in the route passes one).
4. Step 4 (gated suite commands): no change needed; the gate command used a full-path-free bare python and explicit test paths and ran fine.
5. Step 5 tests: version/manifest/lane-threshold pins updated (tests/test_fleet_kit_v15.py, tests/test_lane_progress_v7.py: 17 -> 18, new manifest sha, 130/200 s). Faked-subprocess.run tests: none broke on Popen. Timing tests moved to budget(): 0 (not audited this run).
6. Gated dual suite (fleet_suite_gate, -n 8 --dist loadfile): 64 failed, 40463 passed, 105 skipped in 1099 s; the 64 were all v18 fallout in 11 files (60+ from the missing kind, the rest the pins above). After the fixes the 11 files re-ran: 184 passed, 2 failed. The 2 failures are pre-existing on the v17 tree (test_cli_version_still_matches_the_pin: CLI 2.1.302 vs pin 2.1.296; test_rest_of_environment_passes_through: FLEET_SUBAGENT_FIRST not in the child env list). A full re-run after the fixes was not done (the gate slot wait plus an 18 min run exceeded the nightly window); the changed code is the one-line kind default and test pins only.
7. Hand-off: RC-NEXT-SESSION.txt is 49 KB (over the new 30 KB /done limit). `fleet_done.py archive` dry run: "would move 0 block(s) to docs/handoff-archive/RC-2026-10-18.txt (49330 -> 49330 bytes)" - no CLOSED blocks to move. NOT brought under 30 KB in this commit; /done will fail until it is trimmed by an attended session. Drift on MAIN may read RC OK v18 from HEAD but /done is blocked.
8. Not part of this run: the 2026-10-17-1709 ROFL-archive FIX was read only and left for a separate fire.
