"""`_RUNTIME_TOOLS` of the atomic-write guard."""
# Long-running separate-process agents that live under tools/ (RM-258 names
# both), plus each tools/ watcher converted onto core.polled_json since, so
# the conversion stays pinned: never an extractor, never unclassified.
ROWS = {
    "tools/lcu_agent.py",
    "tools/hotkey_listener.py",
    # RC-CostHealthWatchdog, every 15 min; each run reads back the state file
    # the last run wrote.
    "tools/cost_health_watchdog.py",
    # RC-CIWatchdog: the run-id sentinel and the 2-strike attempt counters
    # are read back on every poll, and a torn read parses as 0.
    "tools/ci_watchdog.py",
    # The progress watcher's own state file is its first-sight baseline;
    # a torn read re-baselines every task and drops a pending alert.
    "tools/progress_watch.py",
    # The spec / patch watch state is the only record of what was already
    # posted; a torn read re-baselines (drops a change) or reposts one.
    "tools/spec_watch.py",
    # One-shot per DS batch, but --record rewrites the live patch's
    # manifest.json in place, which the running DS process reads
    # (agents/daemon_slayer/data_loader.py), and --ack the tracked
    # high-water file.
    "tools/ds_feed_watch.py",
    # The session counter in the hand-off (read by the SessionStart hook)
    # and the headless progress fallback (read by the lane widget and the
    # board): a torn read loses the counter or a checklist row.
    "tools/session_checklist.py",
    # The inbox responder's answered record, read back on every
    # RC-InboxResponder tick: a torn read fails closed and the responder
    # answers nothing until a human repairs the file.
    "tools/inbox_responder.py",
    # The SessionStart / UserPromptSubmit hook (and an import of the
    # long-lived inbox poller and responder runner): the per-session
    # reported record is read back on every fire, and a torn read fails
    # open and re-prints the inbox block.
    "tools/rc_facts.py",
    # The RC-InboxResponder runner, fired every tick: its state records are
    # read back on the next fire, and its bounce and reply land in a
    # sibling's polled inbox under a hidden per-writer `_<file>.<pid>.<hex>.tmp`.
    "tools/inbox_responder_runner.py",
    # The LCU WAMP phase watcher (a long-running loop, installed as an
    # at-logon task by tools/phase_watcher_install.ps1): one JSON sidecar per
    # captured phase event under data/event_captures/, which
    # core/data_retention.py prunes; a failed write used to leave a torn
    # sidecar or a stray destination-derived .tmp.
    "tools/phase_watcher.py",
    # RC-MoonSyncPoller (at logon, a long-running loop) plus its --ping
    # UserPromptSubmit hook: status.md and findings.json are read by
    # --status and /api/moon-sync-status while the poller rewrites them,
    # and poller_seen.json is read back on every poll.
    "tools/moon_sync_poller.py",
    # RC-UpstreamDriftCheck (a daily scheduled task): the sentinel is read
    # back on every run, and the drift alerts are read by tools/rc_facts.py
    # at session start while the task may be rewriting them (RM-514).
    "tools/upstream_drift_check.py",
    # The Claude Stop hook, fired on every main-session and sub-agent Stop:
    # its report and seen set are read back by the next Stop (the seen set
    # decides what is surfaced again), and parallel sub-agents of one session
    # can stop in the same instant, so a shared `<dest>.tmp` could interleave.
    "tools/stop_claim_gate.py",
    # RC-DDragonMirrorRefresh (a daily scheduled task): assets are fetched
    # on a thread pool into web/data/ddragon/<patch>/, which the dashboard
    # serves while the task writes it, and _index.json / the manifest are
    # read back on the next run.
    "tools/ddragon_mirror_refresh.py",
    # RC-RoflDedupe (a daily scheduled task, `--apply`): relinks replays in
    # the archive RC-RoflArchive writes every 15 minutes and replay readers
    # open, so the swap meets a held target.
    "tools/rofl_dedupe.py",
    # tools/timeline_ingest.py: a detached, hours-long Match-V5 ingest whose
    # <corpus>/timelines/ directory the 15-minute RC-ReplayChainWatch task
    # counts and tools/mine_event_patterns.py reads while it runs.
    "tools/timeline_ingest.py",
    # tools/replay_roster_pull.py: the hourly RC-ReplayRosterPull task, which
    # rewrites ops/runtime/replay_roster_status.json unattended every run.
    "tools/replay_roster_pull.py",
    # tools/ladder_role_scout.py: a background bulk ingest (~50 Riot calls a
    # minute) that RC-ReplayChainWatch treats as a busy ingest; its
    # data/ladder_role_mains.json is tools/timeline_ingest.py's ladder input.
    "tools/ladder_role_scout.py",
}
