# P2 per-file audit - DEFER findings ledger (append-only, newest wave first)

Findings that did NOT meet the FIX-NOW bar (risky/wide/operator-gated). Each carries
file:line, class, severity, evidence. Re-triage when its wave's follow-up slice runs,
or fold into P3/P6 as marked. FIX-NOW work is in git history, not here.

## W1 coaches/ (cycle 9, slices A-B - mode coaches+base / adaptation+builders; merge 6350c6d1)

### MED
- coaches/__init__.py:66: load_coach/unload_all have ZERO callers repo-wide -
  app/_game_lifecycle.py:86-132 (frozen) imports coach modules directly via its
  own mode table. Whole dynamic-loader path incl _MODE_MAP/_PREFIX_MAP/_is_tft_pbe
  is dead; the TFT-PBE toggle only works through this dead path - confirm intent
  before removal. P3 prune decision. [class: dead code]
- coaches/experimental_builder.py:118: no lock around load-modify-save
  (record_result vs adapt threads can lose history); _save lacks the WinError-5
  retry sr_user_builds has. Chooser retired item 213; performance_tracker wraps
  caller in try/except. [class: thread-safety]

### LOW
- coaches/aram_coach.py:466: _overlay.get('ai_bar')/'coach_bar' branches dead -
  self._overlay always {} since tkinter-free. P3 prune. [class: vestige]
- coaches/_base_coach.py:191: module-level fetch_game_data() (direct :2999
  reader) zero callers - all coaches use the liveclient_cache instance method.
  P3 prune. [class: dead code]
- coaches/brawl_coach.py:513: writes 'immediate' from a parse key absent from
  all three brawl output key sets (prompts retired Immediate) - always empty.
  [class: vestigial field]
- coaches/arena_coach.py:589: comment claims PlayerN placeholder names skipped
  'by length' but the list-comp implements no filter; harmless, misleading.
  [class: comment drift]
- coaches/aram_coach.py:873: items_display re-parsed from rendered prompt text
  (user.split('Items:')) instead of state['items']; breaks silently if template
  wording changes. [class: fragile coupling]
- coaches/adaptation_hint_temporal.py:61: 'with sqlite3.connect()' commits but
  never closes across temporal/session/champion/aggregates; CPython refcount
  mitigates; byte-pinned cross-file pattern. [class: sqlite-conn-leak]
- coaches/adaptation_hint_champion.py:79: float(row['avg_rating']) TypeError if
  NULL (schema nullable, analyzer always writes) breaks 'never raises' contract;
  also adaptation_hint_aggregates.py:52. [class: null-crash]
- coaches/sr_draft_profile.py:279: engine HTTP body/str(exc) into envelope
  notes; no live UI consumer today (route retired item 186) - scrub before any
  future UI wiring. [class: raw-error-leak]
- coaches/adaptation_hint_cli.py:40: --since '-5h' accepted, yields future
  timestamp / silently empty results. [class: input-validation]
- coaches/loadout_resolver.py:397: norm_pairs list rebuilt per _resolve_item_ids
  call. [class: efficiency]
- coaches/champ_pool_recommender.py:176: int() of champ_kda.json entries
  uncaught if file corrupt (self-built file). [class: input-validation]
- coaches/sr_user_builds.py:113: update() patch can blank label; add()
  validates, update() does not. [class: validation-asymmetry]
- coaches/experimental_builder.py:312: per-champion history list grows unbounded
  on disk (prompt uses last 6 only). [class: retention-less growth]

## W1 dashboard/ (cycle 8, slices A-D - spine/state/pickban/DS; merge a5d266b3)

### MED
- dashboard/routes_duo_synergy.py:309: first cache-miss after start/6h TTL can
  block ~18s (3 dates x 6s timeout, core/synergy_external_source.py:39+144)
  while holding smoothed_rates_101qq._CACHE_LOCK:193, serializing all consumers;
  failure IS negative-cached 6h (static fallback stamps _LOADED_AT:296). Fix =
  background refresh; core files were out of slice. Overlaps the cycle 7
  smoothed_rates_101qq:194 MED-LOW entry - same root. [class: latency]
- dashboard/routes_ds_combo.py:101 (+ 13 siblings): all 14 slice-D TTL caches
  (combo/profile/sweep/knobs/relscore/matchup/statcheck/spike_markers/
  spike_curve x2/cc_blended/cc_conditional/cc_pairing/peel/cooldown) never evict
  expired keys - overwrite-only; unbounded over uptime or query fuzz. Needs a
  shared eviction helper (cross-cutting). Slice C bounded its 4; slice E bounded
  ward_heat. [class: retention-less growth]

### LOW
- dashboard/routes_diag.py:151+111 and dashboard/routes_bridge.py:45+101:
  unbounded str(exc) in 500 JSON bodies (peers truncate [:200]); diagnostics
  panel surface. Bound + log raw. [class: raw-error-leak]
- dashboard/_writers.py:28: atomic_write_json lacks the WinError-5 retry its
  siblings have (routes_health_peer/_bridge_cadence/_bridge_pending_actions);
  coaching_data.json / force_scan.json flake window
  (reference_os_replace_winerror5). [class: atomic-write]
- dashboard/routes_lobby_aux.py:98: _save_top8 os.replace same missing-retry
  class. [class: atomic-write]
- dashboard/routes_state.py:214: _serve_health_all probes :8889 + :8893
  sequentially (timeout=2 each); hung ports stretch /api/health/all to ~4s+.
  [class: latency]
- dashboard/_deterministic_coaching.py:162: _CACHE/_LAST_GOOD mutated by handler
  threads + background refresh without a lock; _evict_if_full min() can hit
  dict-changed-size; callers fail-soft one tick. [class: concurrency]
- dashboard/_champ_select_deterministic.py:97: keystone id map caches {}
  permanently if ddragon_runes.json unreadable at first call; no retry until
  restart. [class: resilience]
- dashboard/routes_team_context.py:330: _WORKER assigned under _LOCK but
  t.start() outside; microsecond double-spawn window doubles the Riot fan-out
  spend. Move start() inside the lock. [class: concurrency]
- dashboard/routes_team_context.py:436: GET serializes the live cache dict
  outside _LOCK while the fan-out mutates entries in place; safe only because
  _skeleton_entry pre-creates every key (no resize). Fragile invariant -
  deep-copy under lock. [class: concurrency]
- dashboard/routes_lobby_aux.py:320: _read_live_mastery self-HTTPS GETs
  /api/state (full state build) per /api/mains poll; read the snapshot
  in-process. [class: latency]
- dashboard/routes_ban_suggestions.py:135: icon slug derived by sanitizing
  display name; breaks for display!=slug champs (Wukong->MonkeyKing, Nunu &
  Willump->Nunu, Renata Glasc->Renata) if ever added to global_top_bans.json -
  current list verified unaffected. [class: latent-data-bug]
- dashboard/routes_sr_draft.py:169: notes[] in the 200 response carries raw
  enqueue exception text (localhost urllib errors); author short reasons.
  [class: raw-error-leak]
- dashboard/routes_dictionary.py:78+189: re-parses ddragon_champions.json per
  request (browser max-age=86400 mitigates); mtime-keyed memo.
  [class: efficiency]
- dashboard/routes_ds_knobs.py:302 (+ profile:406, relscore:227, statcheck,
  damage_mix:90): mode free-string unvalidated - cache-key pollution only;
  engines treat unknown mode as SR identity. [class: param-validation]
- dashboard/routes_spike_curve.py:109: _ARCHETYPE_BUILDS hardcoded item ids
  duplicated in routes_ds_sweep.py:113 "kept in lockstep" manually; comment pins
  16.10.1 vs live 16.12.1. [class: stale-pin]

### INFO (no action expected)
- dashboard/server.py:144: served redirect <title> uses escaped U+2192 arrow
  (source stays 7-bit ASCII); P3 visible-output sweep candidate.
  dashboard/server.py:123 hardcodes 192.168.8.230 fallback for the best-effort
  garbage-traffic redirect.
- dashboard/_dispatch.py:60+154: route-table lazy builds race harmlessly
  (idempotent, last-writer-wins).
- dashboard/routes_bridge_pending_actions.py:81: accept/defer RMW races the
  watcher's _add_to_pending writer; documented last-writer-wins.
- dashboard/_liveclient.py:91: one malformed allPlayers entry degrades whole
  summary to {} by design (fail-soft, never 500).
- dashboard/_cs_retention.py:58 / routes_coach_choice.py:28 /
  routes_state.py:443: unlocked module state with benign worst cases
  (passthrough tick / duplicate append-only store / one extra log line).
- dashboard/routes_state.py:110: _serve_state 500s on build failure instead of
  serving the <1s-stale cache while SSE degrades to {} - divergent but both safe.
- dashboard/routes_pickban.py:51 + routes_personal_vs.py:53: _REWIND_DB is
  CWD-relative while lobby_aux:64 anchors on __file__; correct under supervisor
  CWD only.
- dashboard/routes_ban_suggest.py:187: worst case ~450 sequential sqlite queries
  per cache-miss (30 candidates x 15); local ro db keeps it tolerable.
- dashboard/routes_personal_vs.py:61: _CACHE lockless unlike siblings; probed
  8 threads x 3000 ops = 0 errors (GIL); harmonize someday.
- dashboard/routes_ds_profile.py:243: _axis_maxima cold hit = 172 champs x 8
  scorers in first request (documented intentional).
- dashboard/routes_ds_combo.py:448: outer-500 str(exc)[:200] bodies are the
  documented repo-wide pattern; changing is wide.
- dashboard/routes_ds_combo.py:191: cache key preserves item order (permutations
  duplicate entries). routes_ds_sweep.py:33 docstring clamp drift
  ([step,1000] vs code [100,1000]). routes_ds_statcheck.py:268
  unknown-champion 200 keeps bounded engine detail (deliberate).

## W1 dashboard/ (cycle 8, slice E - postgame/WPA/builders)

### LOW
- dashboard/routes_last_match.py:206-211: _ensure_retry_thread TOCTOU on
  _INGEST_RETRY_THREAD_STARTED (check-then-set outside the lock); two concurrent
  first-ingests can start duplicate drain threads. Benign (queue drained under
  lock, just doubled cadence) + no deterministic failing test possible; fix =
  flip the flag under _INGEST_RETRY_LOCK. [class: concurrency]
- dashboard/routes_{post_game_wpa:71,item_wpa:68,rune_wpa:56,skill_wpa:56,
  summspell_wpa:58,post_game_rubric:59,replay_events:82}: module TTL caches are
  unlocked dicts; eviction's sorted(_CACHE.items()) can raise RuntimeError if a
  sibling handler thread mutates mid-iteration -> spurious one-off 500 (caught by
  wrapper). ward_heat already locks; consistency pass = shared lock helper,
  cross-file. [class: concurrency]
- dashboard/builders.py:269-274: _build_diagnostics tails the day log via full
  read_text + splitlines per request; a full day's log can be tens of MB. Fix =
  bounded seek-from-end tail. [class: efficiency]
- dashboard/builders_home.py:186-193 + dashboard/builders.py:249-267: per-request
  live HTTP probes (vision :8889 timeout=1; Live Client :2999 timeout=2) inside
  home-summary/diagnostics builders add up to 1-3s latency per poll while those
  services are down; no negative-result cache. [class: latency]
- dashboard/builders_last_match.py:448-451: /api/last-match has no response
  cache; every poll re-parses the 50-120KB raw_data blob + full LCU enrichment +
  timeline fold. Mild CPU; frontend polls this endpoint. [class: efficiency]
- dashboard/routes_last_match.py:172: ingest UPDATE uses a per-call write conn
  (default busy timeout) while performance_tracker + the retry drain thread also
  write match_history.db; contention timeout-mitigated, not serialized
  (reference_sqlite_wal_windows_writes). [class: concurrency]
- dashboard/_context.py:21-28: comment claims ThreadingHTTPServer "recycles
  worker threads" - stdlib ThreadingMixIn spawns one thread per connection (no
  pool), so the per-thread conn cache amortizes nothing across requests today.
  Cache still correct; rationale doc misleading. [class: docs]
- Non-ASCII glyphs in authored comments/UI strings across slice files
  (box-drawing headers builders.py:26 / routes_history.py:77 /
  routes_loadout.py:386; math glyphs builders.py:28,80 /
  builders_lcu_enrich.py:205; UI-rendered middot/arrow builders.py:145,247 /
  builders_home.py:183 / builders_last_match.py:91,124,166). Same class cycle 7
  deferred - operator-gated visible-output sweep. [fold into P3]
  [class: ascii-hygiene]

### INFO (no action expected)
- dashboard/routes_summspell_wpa.py:120-125: 200 ok=false (not 503) when rewind
  db missing is a DOCUMENTED deliberate deviation from siblings (clean-checkout
  empty-state rendering); leave as-is.
- dashboard/routes_history.py:84: prefix("/api/history") also matches
  /api/history-* (legacy startswith port); harmless under first-match-wins.
- dashboard/builders.py:49: LIMIT interpolation is int()-coerced (no injection);
  noted for future editors.
- Slice files carry NO stale 16.x version pins (the cycle 7 core/ WPA-trio
  class); routes delegate catalog resolution to core modules fixed in cycle 7.

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
