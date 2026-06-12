# P2 per-file audit - DEFER findings ledger (append-only, newest wave first)

Findings that did NOT meet the FIX-NOW bar (risky/wide/operator-gated). Each carries
file:line, class, severity, evidence. Re-triage when its wave's follow-up slice runs,
or fold into P3/P6 as marked. FIX-NOW work is in git history, not here.

## W1 core/ (cycle 7, slices A-G, merge 6273d655)

### MED
- 13 files outside core (web_dashboard.py:44, game_reader/poller.py:41, tools/*.py x11):
  legacy vision-token literal scattered; same class as the liveclient_cache.py:117
  FIX-NOW removal. Fanout candidate when those slices run (W1d/W4). [class: stale-pin]
- core/riot_api_cache.py:117: cache_immutable has no prune path; live db 94.7 MB and
  growing. Retention policy = design decision. [class: retention-less growth]
- core/game_snapshot.py:90 vs core/queue_modes.py:40: URF/ARURF/OFA -> MODE_BRAWL
  in-game but queues 900/1020/1400/1900 -> "sr" pre-game; brawl backend retired (s214).
  Cross-layer mode divergence, wide blast radius. [class: correctness]
- core/lessons_revert.py:263-284: ack claims auto_reverted=True even when git revert
  failed (no rev_ok on wire, no revert --abort cleanup on conflict). Wire semantics
  change. [class: correctness]
- core/cost_tracker.py: daily ledger cross-process read-modify-write + shared .tmp
  name (RC main + vision server) can lose a telemetry write; needs file lock or
  single-writer. MED-LOW. [class: concurrency]
- core/smoothed_rates_101qq.py:194: TTL expiry with live enabled + endpoint dead
  blocks request path up to ~18s (3 dates x 6s timeout, no negative-result cache).
  MED-LOW. [class: latency]
- core/{hz_choice,hz_build,det_coach,ds_coach}_shadow.py: all 4 shadow JSONLs
  append-only, no rotation (~1 rec/30s in-game). Trimming risks destroying
  do-not-flip-blind validation data - operator retention decision. LOW-MED.
  [class: retention-less growth]
- core/bridge_monitor.py:104-105: state() hardcodes configured/remote_url_set True
  (never consults bridge.is_configured) - misleading ops JSON. LOW-MED.
  [class: correctness]

### LOW
- core/daemon_slayer_client.py:861: _champ_attackrange_index lockless lazy global +
  process-lifetime stale after patch refresh.
- core/liveclient_cache.py:199: stop() nulls _thread after failed 3s join; later
  start() could spawn duplicate poller (test-only path).
- core/match_metrics.py:393: module-level Recorder() creates DB at import time.
- core/riot_api.py:92: malformed-key path re-logs WARNING per call (missing-file
  path has a once-flag).
- core/replay_history.py:347: match_detail returns cached dict by reference.
- core/prompt_sanitize.py:84 + core/coach_choices.py:71: truncation overshoot
  (cap returns len+2/+3 over stated max); fixing changes live prompt/UI bytes.
- core/decision_detector.py:875: _prev_game_time written outside _heartbeat_lock.
- core/coach_trace.py:95: trim gates on 1 MiB then keeps 200 lines; can reach
  ~2.5 MB with max-size records. Bounded.
- core/{build_order_precompute.py:123, laning_scenario_precompute.py:120,
  pickban_targets.py:50}: scattered _FALLBACK_PATCH="16.11.1" literals (drifted vs
  16.12.1; near-unreachable while current.txt tracked). Fix = central const,
  cross-slice. [class: version-literal fallback]
- core/ds_calibration.py:19,50: ds_calibration.jsonl appends ~1 row/30s tick, no
  rotation; policy needs Stage-5 join consumer decision.
- core/laning_verdicts.py:174-197: _next_build_item re-reads build_orders +
  items_index JSON every coaching tick (siblings mtime-cache).
- core/draft_elo_db.py:148: pair_winrate double-counts mirror matches.
- core/post_game_score.py:726: int(r[0]) raises on NULL team_id (CLI-only path).
- core/aftergame_summary.py:82,109: corrupt-DB raises vs docstring "returns {}"
  (CLI-only callers today).
- core/aftergame_summary.py:403,323,340: non-ASCII glyphs in rendered UI strings
  (check/warn/middot/multiply) - operator-gated (visible output). [fold into P3]
- core/augment_recommender.py:211-236: _lcu_row_count LIKE full-scan per
  augment-tick as cache key (documented design).
- core/aram_comp_verdict.py:98-113: _index_loaded=True set before population
  (fail-soft one-tick partial read).
- core/archetype_picks.py:121-234: ddragon_champions.json parsed 3x for 3 caches.
- core/vision_tracker.py:285-297: riotIdPlusTagLine is not a Live Client field
  (None-safe; championName fallback covers).
- core/metrics_cache.py:226 + core/log_retention.py:188 (+obs_publisher stop):
  Task.cancel() cross-thread when spawned on AppLoop - shutdown-only.
- core/lessons_receiver.py:39 / lessons_ack_watcher.py:39: loopback bridge pinned
  to tailnet hostname legion-rc; Tailscale outage breaks local pulls.
- lessons_sent/received.jsonl retention-less growth (tiny volume) +
  lessons_ack_watcher.py:56 limit=500 no-pagination ack-miss window.
- core/lessons_confidence.py:145-155: O(n^2) _received_bucket (n tiny).
- tests/test_synergy_external_source.py:46: tearDown never restores
  S._http_get_json (cross-test pollution). [W5 test-corpus item]

### INFO (no action expected)
- core/ds_antitank_hint.py:5: "never raises" overstated; both live consumers wrap.
- core/build_order.py:91: _BOOTS_IDS authored 16.10.1; all 8 ids probed alive in
  16.12.1 - no drift.
- core/laning_scenario_precompute.py:449: band-constant recomputed per leaf
  (offline, engine-bound).
- core/bridge.py:171 secret_len exposure; feature_policy unlocked cache;
  bridge_monitor _last_seen_ts unlocked write.
- data/spend unbounded daily files: consciously covered by
  scripts/db_size_monitor.py 50MB threshold.
