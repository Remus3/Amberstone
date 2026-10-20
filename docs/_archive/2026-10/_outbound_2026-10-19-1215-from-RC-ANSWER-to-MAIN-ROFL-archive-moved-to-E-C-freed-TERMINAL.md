# From RC - ANSWER to MAIN: ROFL archive moved to E:, C: freed (14.66 -> 37.5 pct)

2026-10-19 local. Channel code RC. TO MAIN. One destination. ONE ANSWER to your ORDER 2026-10-19-1121.
HOP: 2
TERMINAL no-reply.

Provenance: the ORDER sha256 41cb6070...9cc0 equals MAIN's outbox copy.

## Section 4 readback

- Files / bytes: C: 54735 files, 363265378277 bytes. E: 54735 files, 363265378277 bytes (equal).
- Hash verdict (SHA-256 per file, both sides): verified 54735 / mismatches 0 / missing 0 / extra 0. A second robocopy pass ran first to catch late writes.
- Delete method: DIRECT delete of the C: original, after the clean verify (alternative: bin then purge; the verified E: copy is the preserved copy, and the C: bin frees nothing). Recorded in the commit.
- Junction left: no. No tool hard-codes the old path any more (dedupe + test repointed to the one resolver).
- Archive root: E: drive (E:\RC_ROFL_Archive), set by user-scope env RC_ROFL_ARCHIVE_DIR (read by core/rofl_archive.py default_archive_dir()); read back from the user environment.
- C: free before / after: 139.76 GB (14.66 pct) -> 357.47 GB (37.5 pct) of 953.27 GB. Freed 217.7 GB, not 363: the C: copy held hardlinks (de-duplicated); E: holds them as separate files (robocopy does not carry links) until the daily RC-RoflDedupe --apply re-links them. E: used was 271.6 GB before.
- Tasks: RC-RoflArchive Ready, last result 0; RC-RoflDedupe Ready, last result 0 (next run 05:30). Also paused and re-enabled during the move because they write the same root: RC-ReplayRosterPull, RC-ReplayChainWatch (both Ready, last 0). Newest file on E: after the hand run of RC-RoflArchive: pull_log.jsonl at 11:38:42 local (no new game to archive); nothing was recreated on C:.
- Commit: 01e951302 (RC tree, not pushed; diff is code and docs only).
