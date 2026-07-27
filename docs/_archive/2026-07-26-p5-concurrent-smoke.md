# P5 concurrent-run smoke log (2026-07-26)

- RC cycle 1: tree clean at start and the smoke log was absent, so this cycle created it; no concurrent-write contention seen on the RC repo (head e0f4d546)
- RC cycle 2: tree clean at start with cycle 1's commit already on main, log read back intact, so the append-only pattern survived the concurrent run without contention (head 4f3ee42c)
