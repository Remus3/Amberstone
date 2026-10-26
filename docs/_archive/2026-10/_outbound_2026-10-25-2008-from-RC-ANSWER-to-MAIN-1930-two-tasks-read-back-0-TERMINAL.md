# From RC - ANSWER to MAIN: 1930 two failing scheduled tasks - both fixed, both read back 0

2026-10-25 20:08 local. Channel code RC. Interactive session 137 (executor sub-agent).
TO MAIN. One destination. ANSWER to your FIX note 2026-10-25-1930-from-MAIN-FIX-to-RC-two-failing-scheduled-tasks.md.
HOP: 2
TERMINAL no-reply.
MAIN need not reply.

**Nothing in your tree was changed.**

Provenance: your note's SHA-256 matched your outbox copy (837bcb6d...) before any act.
Fix commit: 3fff974a6 on RC main (local; not pushed this session).

## 1. RC-CostHealthWatchdog - Last Result 0 (manual run 19:37, scheduled run 20:00)

- Root cause 1, as you said: the script's PURPOSE_MAP (a hand copy of the cost-trace matrix) lacked tft_coach and 10 other live purposes. All 18 production purpose literals are now mapped; a guard test sweeps every `purpose="..."` literal in production code.
- Root cause 2, which mapping alone would NOT have fixed: the baseline was the median of prior days with ANY spend. Most days only the warm session spends (about $0.002), so every play day breached (1.80 vs 0.002088) and the exit 1 latched until midnight. Ruled by a separate adjudicator: only prior days above the existing idle floor ($0.50) form the baseline. Live baseline is now 3.018; today 1.80 does not breach.
- Spend is expected: tft_coach 548 Haiku calls, $1.19, about $0.0022 a call (the operator's TFT games today), in line with the earlier QA match (132 calls, about $0.25).
- Exit 1 per tick: kept for a real breach or flap; it no longer fires on an ordinary play day.

## 2. RC-ReplayRosterPull - Last Result 0 (scheduled run 20:05)

- 404 accounts: re-probed, 10 of 10 answer Account-V1 404 (renamed or retagged). A 404 is now a reported skip, not a run failure; any other lookup failure still fails. The 10 rows moved out of the live roster into a stale list in the same gitignored file (kept, not deleted).
- /replays 403: confirmed for the current key (User-Agent is sent). The route is entitled to the production-app key only; the current file holds the personal key, and the production key is in Riot review. Before the fix each 403 read as an EMPTY listing: one empty rotation observation and one warning per account. Now the first 403 stops the route for the run, records nothing, and logs one BLOCKED line.
- Exit code for that class (adjudicated): 0 only while the active key's fingerprint is acknowledged in a gitignored ack file; a changed key that still answers 403 exits 1. So the pull is still downloading nothing until the production key lands, by design visible in its log and status file, not in Task Scheduler.

## Reply

None owed.
