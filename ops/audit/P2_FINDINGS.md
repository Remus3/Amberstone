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

## P2 W1 app-set (cycle 10, item 404) - app/ game_reader/ modes/ lcu/ coach_integration/ lib/ vision_server/ modules/

Slices A (app+game_reader+modes+vision_server+modules) / B (lcu+coach_integration+lib).
FIX-NOW landed in the merge d61330b9; DEFER below. No frozen-file edits this cycle
(all app/* + lcu_client.py findings were DEFER/INFO; FIX-NOW touched non-frozen files only).

### MED
- vision_server/_frame.py:205: _frames_by_source dict keyed by uploader-supplied
  source string, never evicted; each slot holds up to a ~7MB b64 frame. Fixed
  deployment uses 2-3 sources, but a token-authed client cycling source names grows
  memory unbounded. Bound + LRU is a design change.

### LOW
- game_reader/poller.py:41: hardcoded RELAY_TOKEN literal as ImportError fallback;
  except only catches ImportError (NOT the RuntimeError core.vision_token raises when
  unconfigured) so the literal is partly dead. Part of the known 13-file legacy-token
  fanout (operator-gated). vision_server/_config.py is CLEAN (no literal, fails loud).
- vision_server/_relay.py:68: _lcu_cmd_queue appends per dashboard command, drained
  only by the LCU agent polling /lcu-cmd-pending; if the agent is down it grows
  unbounded (results dict IS capped at 100). User-rare commands.
- vision_server/_http.py:206: do_PUT writes moon_monitor.html via bare write_bytes
  (GET /monitor could read a partial file). Dev/diagnostic surface, manual PUT.
- vision_server/_http.py:194 + app/_remediation.py:59: {"error": str(e)} raw-exception
  bodies on the internal localhost :8889 / DevRuntime ops surfaces (not coach UI /
  dashboard panel) - consistent with RC internal-API style.
- modules/cache_engine.py:17: phase_bucket(t) has no None guard (hp/mana/obj_window
  buckets do); make_cache_key passes game_time_s default 0, but an explicit None
  would TypeError. game_time_s rarely None.

### INFO (P3-prune material - DO NOT prune in P2, record-only per charter)
- gamepc / 2-PC / RC-LiveClientRelay docstring + comment references:
  game_reader/poller.py:8, vision_server/_frame.py:14, vision_server/_relay.py:13,
  modes/shared_vision.py:21,44. P3 PRUNE SWEEP target.
- game_reader/poller.py:137: relay read path returns _process_game(relay_raw) with
  NO try/except, unlike the direct path (183-187). The NaN root-cause fix (slice A)
  covers the known crash; full parity wrap deferred (changes is_in_game control flow).

---

## P2-W2 DS engine half-wave 1 (cycle 11, item 405)

Slices A (dps/ability_dps/burst/hybrid/objdamage/dps_sweep/beam/missile) /
B (threatrange/waveclear/mobility/extendedduel/zonecontrol/self_shred/antitank/
allyamp/sustain) / C (ehp/hps/ability_hps/_per_spell_cc/cc_conditional/cc_output/
cc_pressure/cc_pairing) / F (server/engine/data_loader/_registries/cli/__init__/
__main__/stats/scaling/rank/abilities). 36 files / ~23.1k LOC. FIX-NOW landed in
the merge; 47 new tests (tests/test_p2w2_ds_{a,b,c,f}.py 15/16/10/6). No frozen-file
edits (no agents/daemon_slayer file is on the frozen list). DEFER below.

### LOW
- agents/daemon_slayer/server.py:1375 (_route_antitank): the live /anti-tank route
  calls compute_antitank(champion, mode=mode) and never passes stats=, so the entire
  P3.2 AP/AD build-aware scaling path (ap_ratio/ad_ratio seeds on 7 rows) is exercised
  only by tests, never on the running dashboard. Slice-B hardening protects it for
  future wiring; the feature itself is inert on the live surface. Wire a resolved
  ResolvedStats in, or document as test-only/future.
- agents/daemon_slayer/cc_conditional.py:526 (ConditionalCcEntry.__post_init__):
  validates durations_s for negativity (d < 0) but not finiteness; a NaN duration
  passes (NaN < 0 is False) and would serialize to a bare NaN token via cc_output
  round(). Source is the REQUIRED hand-authored cc_conditional_registry.json
  (fail-loud, 0 non-finite today) not the scraped extract, so out of strict need.
  Add an isfinite check in __post_init__.
- agents/daemon_slayer/server.py:1786 (_read_json_body): self.rfile.read(length) is
  unbounded vs _drain_request_body's 65536-chunk loop; a bogus huge Content-Length on
  a valid route allocates that buffer. Localhost-only trusted single-user bind = low
  risk. Read in bounded chunks with a max-body cap.
- agents/daemon_slayer/beam.py:344 (_seed_has_boots): re-scans snapshot.items per beam
  per depth inside the expansion loop; hoist a per-beam bool alongside (items,dps,gold).
  Efficiency only.
- agents/daemon_slayer/data_loader.py:435 (arena_augment): the one-line
  `... or ... if str(key).isdigit() else ...` ternary is correct (AST-confirmed int(key)
  only on the digit branch) but hard to read; expand to explicit if/elif. Behavior is
  value-pinned by tests - pure-churn rewrite, left as-is.
- agents/daemon_slayer/objdamage.py:743: best_value = -1.0 sentinel - a literal
  0.0-magnitude entry would beat -1.0, but top_kind is gated on total > 0.0 and every
  champ has a positive BASE row, so currently benign. Init 0.0 + skip zero-value entries.

### INFO
- agents/daemon_slayer/server.py:281/304 (_DISPATCH_REVMAP_CACHE keyed by id(snap)):
  module-level dict would grow if many distinct snapshots existed; the server holds
  exactly one snapshot for process life, so bounded in practice. Store the revmap on
  the snapshot or use a single-entry cache.
- ASCII: 0 banned-set hits (em/en dash, smart quotes) across all 36 files. Pre-existing
  non-banned glyphs survive in comments/docstrings/format_table console output repo-wide
  (-> arrow U+2192, x U+00D7, box-draw U+2500, alpha/beta) - NOT in the s244 swept set;
  converting here would be inconsistent drift, deferred to any future cosmetic sweep.

## P2-W2 DS engine half-wave 2 (cycle 12, item 406)

Slices D effects-data (3 files) / E passive-overrides (12) / G remaining-mechanics (17)
/ H Phase3 supervisor set (5). 8 FIX-NOW landed (see LEDGER item 406); below are the
record-only DEFER + INFO findings. Recurring DEFER class this wave = int(non-finite)
OverflowError and NaN-passthrough at accessor chokepoints that are NOT reachable via the
live consumer (the live paths int-validate / clamp before the accessor). Recorded for a
future defense-in-depth sweep; not fixed to avoid manufacturing changes with no live repro.

### LOW
- agents/daemon_slayer/_passive_*_overrides.py int(level) raises on non-finite level
  (_passive_survival_window_overrides.py:325, _passive_resist_overrides.py:647,
  _passive_mitigation_overrides.py:251, _passive_revive_overrides.py:269,
  _champion_cc_mitigation_overrides.py:194, _champion_spell_shield_overrides.py:226,
  _passive_ally_grant_overrides.py:257). NaN level -> ValueError, inf -> OverflowError.
  NOT reachable via compute_ehp (clamp_level int-validates first); defense-in-depth only.
- agents/daemon_slayer/spike_markers.py:148-156 (_clamp_level): int(inf) OverflowError
  not caught by except (TypeError, ValueError). Live route routes_spike_markers._parse_int
  uses int(str)->ValueError->default, so only a direct programmatic level=inf trips it.
- agents/daemon_slayer/rune_procs.py:60-69 (_clamp_level): same narrow-except gap reached
  via _lerp_by_level; upstream consumers (fight_report/burst/combo) pass ints, not reachable.
- agents/daemon_slayer/geometry.py:243-245 / 350-351 (spell_cone_angle / spell_cast_radius):
  a NaN datum passes the `<= 0` guard (nan<=0 is False) and returns NaN. Unreachable +
  unconsumed (item-336..342 forward-marker accessors nothing consumes / never serialized).
- agents/daemon_slayer/geometry.py:158 (aoe_multiplier): int(targets_hit=inf) OverflowError;
  internal callers pass 1-5, never inf.
- agents/_supervisor_http.py:48 do_GET / :96 do_POST: no top-level try/except around handler
  dispatch; an unexpected raise before headers drops the connection (most handlers self-guard
  now, so low impact). A single outer guard would harden uniformly.
- agents/_supervisor_http.py:150 (_handle_input et al): self.server.supervisor accessed with
  no None-guard; AttributeError raises raw if start_web_server(supervisor=None) is ever used
  (currently always constructed with a real supervisor).
- agents/supervisor.py:693 (_on_mode_transition): asyncio.get_event_loop() is deprecation-
  pathed on 3.14 with no running loop; guarded by .is_running() so benign - modernize to
  get_running_loop() in a try.
- dashboard/routes_ds_statcheck.py:342 / routes_ds_sweep.py:349,376 (cross-file, dashboard/):
  json.dumps default allow_nan=True fleet-wide on DS routes. Slice-D/E/G guards stop the
  effects/override/fight-report sources; an allow_nan=False (or finite-sanitizer) at the DS
  route serializers would belt-and-suspenders against any future non-finite source - the same
  hardening slice H applied to the supervisor _send_json this wave.

### INFO
- _effects_data.py: 547 entries, zero duplicate dict keys, zero key!=item_id mismatches
  (AST + runtime verified). Docstring header "16.9.1" vs many "Meraki 16.10.1" per-entry
  values is benign doc-drift (current.txt is source of truth) - docs-sync, not a code defect.
- E: all 12 override registries are canonical-DDragon-id keyed (zero dead display-name keys
  - MonkeyKing/KSante/Renata/JarvanIV/XinZhao/TahmKench/DrMundo all canonical), zero duplicate
  keys, no shared-mutable returns (accessors return fresh float/tuple/frozen dataclass), and
  every entry resolves finite across the roster x ranks -1..6 / levels 1..18.
- G: augment_formula_eval.py is a pure dict-dispatch interpreter (NO eval/ast/compile/exec),
  division-free, all float() casts guarded - no formula-injection or div-by-zero surface.
  mana_sim inf mana_pool is the documented "no finite-mana gate" sentinel (pinned by
  test_mana_sim.py:115); matchup 0-HP div guarded (matchup.py:260-261); scenario_matrix NaN
  cells are internal-only, never serialized; _item_ability_haste.effective_cooldown floors the
  denominator at 0.01.
- H: agents._WebServer is ThreadingTCPServer (daemon_threads=True) - the cycle-7 S7 single-
  threaded-serialization class does NOT apply. spawn_ephemeral_llm already has
  subprocess.run(timeout=...) and prune_task_logs() still wired (not regressed). _minimap_bbox.py
  is fully hardened (int-coercion rejects inf/nan strings, arity + r>l/b>t ordering + [0,10000]
  clamp; no division/NaN math) - CLEAN, no change.

## P2-W3 web surface (cycle 13, item 407) - DEFER

Dominant FIX-NOW class this wave = XSS: data-controlled strings (LCU/remote player
names, LLM coach text, OCR text, DDragon/engine names) interpolated raw into innerHTML.
18 JS files hardened in-slice. The DEFER tail below is MED/LOW/INFO.

### MED
- web/js/ws_client.js (whole file): unreferenced Phase-3 WS stub - no <script>/import loads
  it and its DOM ids were removed (main.js:411); if ever loaded the IIFE would throw at L14.
  Whole-file removal is a P1/P3 STRUCTURAL prune, not an in-slice JS edit.
- web/js/panels/build_insights.js:82-106: rune/spell `icon` URL embedded raw inside an inline
  `onerror="this.src='...'"` JS string-literal attribute. Element-content + title are escaped
  (FIX-NOW done); the onerror sink needs a structural rewrite to the fixed-kind fallback pattern
  used by historical_pgr - larger than a pixel-neutral escape.
- web/css/panels/last_match.css (40+ sites) + home.css (7 sites): CSS custom properties
  referenced but NEVER defined repo-wide (`--ok --accent --grade-s/a/b/c/d/f --surface-2 --warn`
  with literal fallbacks render the fallback; `--label --clock` have NO fallback -> inherited
  color). Latent-correctness gap; every fix is pixel-altering -> 5-phase UI-audit ritual, not a
  code-audit slice.
- web/css/panels/header.css (35 `!important`) + champ_select_view dead-but-test-pinned selectors:
  the !important are all documented cascade battles (static-pill / view-router visibility); the
  "retired-per-comment" csv-pb-* selectors are PINNED by test_csv_typography_v21_floor.py +
  test_personal_record_dom.py, so deletion needs coordinated test edits. Both DEFER.
- web/css/panels/next.css:1 (162x U+2500 box-drawing in header comment): the repo treats U+2500
  as an OPERATOR-GATED sweep (tests/test_u2500_hygiene.py - explicitly NOT folded into em/en-dash
  hygiene); fix via tools/strip_u2500.py + _ASSERTED_CLEAN, not a freelance per-slice edit.

### LOW
- main.js:3719 `_encodeTip` escapes only `"` (not <>&) - tip body is server numerics, low risk;
  widening touches a shared helper. _mcOverallHtml/_mcAveragedHtml interpolate DB-computed
  numerics/enums into innerHTML (not free-text).
- main.js (~15 fetch sites) + several panels: command POSTs + low-churn GETs lack
  `cache: "no-store"`; benign (not output-preserving to change).
- web/js/panels/right_now.js renderStats: ~90 `setv` rows re-applied every tick with no sig
  guard - idempotent (textContent, no innerHTML wipe) so wasteful-not-buggy; UI/efficiency pass.
- web/js/panels/map_state.js:107,576: two module-scope 1s setInterval tickers run regardless of
  active view (only document.hidden-gated), unlike active_match's dataset.view gate. Fixed count,
  no leak; efficiency-only.
- web/js/panels/last_match.js:593-622 `_setEnrichedBuild` + `_setDsPicks`: unreferenced dead code
  since the s219 v3 BUILD-section removal; harmless, removal is a refactor.
- last_match.js:173 augment `icon_url` into img `src=` unescaped (server patch-snapshot source,
  same trust as ITEMS); historical_pgr raw Match-V5 numerics into innerHTML (typed, low risk).
- web/js JS-E/F: SVG-coord sig keyed `parentEl.id || "_default"` - two id-less mounts could share
  a sig (all live mounts carry unique ids); draft_elo escaping is defense-only (numeric ids).
- 5+ panels (replay_events/post_game_phases/pgr_winprob/pgr_loadout/pgr_lane_compare) each
  redefine a local `_escHtml`/`_esc`; could import the new shared helpers.escHtml (DRY, out of slice).
- web/css: stub.css is a vestigial orphan stylesheet (zero <link>/route/import repo-wide) - DEFER
  removal per charter quarantine policy + note. ds_statcheck.css undefined-token cluster
  (--signal-strong/--signal-mute/--accent/--border-1/--surface-2/--fs-2xs resolve to literals);
  repeated `.ds-*` card-chrome literals would need a NEW token (out of literal->existing-var scope).

### INFO
- Repo-wide rendered UI glyphs (arrows, middot, box-drawing in comments, U+00B7/U+2192/U+25CF
  etc.) are established display glyphs across 10+ panels + comment-only decoration; NONE are the
  enforced em/en-dash or smart-quote bans (verified zero across all 106 web files). The dedicated
  P3 tree-wide encoding/smart-quote retro-sweep owns these, not a per-slice freelance churn.
- dedup_fetch.js clone contract (master gets unread Response, waiters .clone()) is the standard
  pattern; no confirmed live bug. items_index resolver negative-caches null correctly (not poison).
- The JS view-panel + supervisor-flagged "high-risk" sinks were already SAFE: active_match /
  last_match / dev / bridge_pending / screen_read render dynamic strings via createElement +
  textContent/.title (immune to HTML parse) or a pre-existing local _escHtml; cc_pairing /
  callouts / pgr_winprob / cd_ledger / ds_matchup already escaped every interpolation.

## W4 operational tooling - tools/ half-wave 1 (cycle 14, item 409)

### MED
- tools/rc_facts.py:40 + tools/calibrate_vision.py:25 (+ doc wrap-gamepc.md:19) hardcode the
  fleet relay bearer token `8e8f131e...` as a source literal (sent Authorization: Bearer).
  Localhost/tailnet-bound, not a Riot/Anthropic secret, but belongs in config not source -
  cross-file, operator-gated. Same literal pervasive across ~12-18 files (bridge_mcp/cli too).
- tools/package_portable.py:81 + build_installer.py:72 + run_packaged_smoke.py:88 spawn the
  build-chain child (build_portable/package_portable) with NO subprocess timeout - a wedged
  child build hangs the packaging chain / CI indefinitely (the bootstrap subprocesses in the
  same files DO have timeouts; only the build-chain spawns lack them).
- tools/scheduled_boot_verify.py:104 _write() does a direct write_text (not tmp+replace) - a
  crash mid-write leaves a torn boot-verify jsonl; :34 _OUT_DIR.mkdir() runs at import (raises
  on import, not in main(), if LOCALAPPDATA unwritable).
- tools/bridge_watcher.py:162 _atomic_write_json could pass allow_nan=False to harden the
  health/pending dumps, but the write path only catches OSError (not the ValueError that
  allow_nan=False raises) - needs ValueError handling FIRST or it crashes the poll loop. The
  parse-chokepoint fix (bridge_watcher_actions cost guard, applied) already blocks the only
  remote vector; this is defense-in-depth.

### LOW
- tools/bridge_mcp_server.py:213-223 _norm_source/_norm_target not URL-encoded before f-string
  interpolation into the bridge GET querystring (a source containing & could append params).
  Localhost-only MCP, args from a local agent. Add urllib.parse.quote.
- tools/daemon_slayer_extract.py:112 + daemon_slayer_abilities_extract.py:286 write
  ensure_ascii=False (unlike the 4 newer sidecar extractors) - intentional for legit non-ASCII
  DDragon/Meraki prose, but a non-ASCII char lands in committed data JSON.
- tools/champion_loadout_autogen.py:415 atomic_write_loadouts writes ensure_ascii=False while
  every sibling writer uses True - could let a non-ASCII glyph into curated JSON (harmless today).
- tools/validate_loadouts.py:28 + champion_loadout_invariants.py:112,139 validate-silently-passes
  on empty input (empty champion_loadouts.json / empty items.json catalog validates as OK).
- tools/champion_loadout_validate_meta.py:146 MULTIPLE_BOOTS dedup unreachable when first boot
  is not at index 1 (spent item-200 migration; live data passes; superseded by Cleaner._reseat_boots).
- tools/ds_cc_conditional_to_json.py:84 + ds_execute_prefilter.py:25 + ds_cond_pair_prefilter.py:21
  + ds_cond_inspect.py:12 bare open() no encoding=, unclosed - dev one-shot scanners, fail-loud,
  never imported by runtime.
- tools/daemon_slayer_build_orders_generate.py:98 + daemon_slayer_pickban_targets_generate.py:102
  + ds_share_sync.py:11,115 stale _FALLBACK_PATCH / docstring 16.11.1 vs live 16.12.1 (harmless;
  only guards a missing current.txt on fresh checkout).
- tools/ds_matchdb_mcp_server.py:167 hardcoded fallback bearer token (documented localhost-only
  "override in prod"; server binds 127.0.0.1).
- tools/gemini_audit.ps1:56 + gemini_ask.ps1:27 native gemini CLI calls have retry/backoff
  bounding attempts but no hard wall-clock cap - a hung CLI stalls the scheduled run.
  [PARTIAL-RESOLVED item 438 (commit 63486e8a, cycle 41): both wrappers' retry LOOP is now
  bounded by a shared $deadline=(Get-Date).AddSeconds($MaxWaitSec) (ask 120 / audit 180) +
  the Start-Sleep is skipped past the deadline; and gemini_ask.ps1's separate Write-Error-
  under-EAP=Stop exit-code masking (the 2026-06-07 incident class) was ported to the sibling
  Fail() helper. Guard tests/test_gemini_wrapper_robustness.py. STILL DEFERRED: a single
  in-flight `& gemini` call's internal 429-backoff is not killable without Start-Job/Wait-Job
  process-kill (MED-risk PS5.1); ops/loop/loop_controller.py:93 gemini() has the same
  no-loop-cap class (already returns "" gracefully, loop STOPped, lower urgency).]
- tools/usage-mcp-server.js:105,119 echoes JSON.stringify(API error body) on non-200 - the
  Anthropic error envelope does NOT contain the key (no secret leak); NaN path already fail-soft.
- The test_bare_py_ban.py guard regex (_BARE_PY) has a GAP: it does not match the `& py (...)`
  call-operator form nor `& py "$var\tools\..."` (quoted-variable, no drive-letter) - two .ps1
  files (bridge_setup, headless_run) slipped through despite the live defect. TIGHTEN the pattern.

### INFO (W4)
- tools/*.cmd packaging wrappers + the 4 strip_* tools (strip_smart_quotes/strip_em_dashes/
  strip_u2500/repair_mojibake) audited CLEAN: canonical-interpreter pin, atomic tmp+replace,
  self-excluded walk, banned glyphs built via chr()/\xNN so they stay 7-bit ASCII. regen_rc_cert.ps1
  cert handling sound (ErrorActionPreference Stop, no key exposure, leaf-only). truth_gate/
  precommit_gate/text_first_guard fail-closed/fail-open correctly by design.
- The 12 ds_*_build.py scorers + the EXHAUSTED block/form/max_priority prefilters are sound
  retain-for-patch-re-extract tooling (CLAUDE.md Settled) - NOT prune candidates.
- *-rootca-on-gamepc.cmd (3 cert installers) carry LOW non-ASCII arrows (U+2192) + are Game-PC
  P3-prune candidates. tools/*.md skill/plan docs (BRIDGE_WATCHER_PLAN, LAUNCH_STRATEGY,
  PYTHON_BUNDLING_STRATEGY stale wrapper-order, headless-upgrade gamepc ref) -> P8 doc rewrite.
- P3-prune feed (verdict slices F + I): ARCHIVE 9 dated one-shots (hotfix_sr_adc_loadouts_item167
  + hotfix_kaisa_aram_ashe_sr_item263 + regen_ranged_marksman_item213 are HAZARD-if-rerun
  unconditional clobbers - archiving neutralizes; + hotfix_sibling_item269/arena_mage_item273/
  thin_aram_item275/item276/zaahen_item277 + migrate_carry_summoners) + champion_loadout
  _backfill_item208_carry + _sweep_item_s8 + migrate_abilities_* (3). gamepc_*: 3 LIVE-on-Legion
  RENAME (lcu_agent/liveclient_relay/hotkey_listener -> legion_*, Tier-2: 3 tasks + ~8 test
  imports) + 5 DEAD ARCHIVE (screen_agent/phase_watcher/mcp_server/bridge_daemon/
  phase_watcher_install) + keybind_listener DELETE + Game-PC doc/boot bundle KEEP-historical
  pending operator decommission. KEEP-live: replay_matchup/pickban_validate, recover_match_via_match_v5,
  probe_101qq, compare_101qq, match_monitor, backfill_match_ingest_misattribution.

## W4 half-wave 2 (cycle 15, item 410) - scripts/ops/rc-shell/tft/root/spec

### MED (W4-hw2)
- scripts/retrofill_match_metrics.py:127-196 every derived metric (kda_ratio/kp_pct/share_pct/
  td_pct) computed by division but recorder.record() called WITHOUT provenance= -> all default
  source_truth despite feedback_metric_provenance_tagging (math-derived rows must be inferred_*).
  Large blast radius (rubric weighting) -> behavior change, deferred.
- scripts/merge_refresh_builds.py:79,110,153 direct write_text() to {aram,sr,arena}_champion_builds.json
  (engine-read build files) - should be tmp+replace like patch_champion.save_builds. One-shot s33
  merge, not a polled hot path.
- riot-commander.spec hiddenimports omits ~47 dashboard route modules (dynamic imports) - a packaged
  PyInstaller build would crash on first route load. SHIPPED 5669d682: replaced the stale 7-of-54
  hand-list with a build-time glob of dashboard/routes_*.py (self-maintaining, file-existence-guaranteed;
  54 modules now declared). (.svg EXE icon FIXED in-slice.)

### LOW (W4-hw2)
- ops/rc_file_bridge.py:349,355 _tail_file/_grep_file read any absolute path the request names, no
  project_root confinement (local trusted IPC, bounded). :210,218 PID write non-atomic + inline
  __import__('json').
- ops/loop/loop_controller.py:97 gemini PowerShell builds -p '{inst}' with ''-escaping; inst is a
  hardcoded literal + infile is a controlled const - not a live injection vector (note-only).
- scripts/retrofill_match_metrics.py:103-112 same SELECT * run twice (description + fetchone) - one
  redundant DB round-trip per match.
- scripts/prune_synthetic_matches.py:142-144 dry-run stdout "would drop N" vs summary dropped:0 mismatch.
- scripts/data_pipeline.py:73-82 tmp-suffix can collide across concurrent writers; :61-70 .replace()
  no retry-with-backoff on transient WinError 5 (one-shot pipeline, low risk).
- scripts/fetch_cdragon_pbe.py:22,63 + fetch_external_tft_meta + download_aram_icons raw fetch body
  write_text() to cache BEFORE validating expected shape - a 200-with-garbage caches a bad file.
- tft/placement_aggregator.py:88,114 json.dump pct math lacks allow_nan=False (total>=1 structurally
  when a cell exists -> NaN impossible; defensive only).
- rc-shell/src/main.js:650 JSON.parse accumulates unbounded response body (bounded by 1500ms timeout
  + localhost-trusted origin). :111-143 persistWindowState origin-field cosmetic inconsistency.
- ASCII-in-output (NOT hard-banned dashes/quotes; coordinated pass): scripts audit_ddragon_items /
  audit_api_surface / download_aram_icons / build_spell_cast_rates (x lands in spell_cast_rates.json
  note) / build_champion_benchmarks / extract_* use arrows/box-draw/x/check/middot in prints+docstrings;
  ops/* decorative U+2500 box-draw + U+2192 arrows + U+00A7 section-sign (phase3 docstrings); tft
  SYSTEM_PROMPT strings carry pre-existing mojibake (->/bullet/>=/quote/star) baked into prompt text;
  tft_ocr_reader comment banners. The 2 mojibake in rc_state_validator:180 + rc_self_monitor:411
  (corrupted <=/>=) FIXED in-slice.

### INFO (W4-hw2)
- bare-py guard (test_bare_py_ban.py) has a SECOND distinct gap (beyond cycle-14 `& py (`): bare
  `python <script>` (the word) is NOT caught - regex keys on `py(\.exe)?\s+` and `python` has `thon`
  after. Widening to `python` would false-positive the many intentional `python tools/dev_cli.py` doc
  lines (LAUNCH_STRATEGY.md) - a policy change outside slice authority. run_deploy_test.bat bare-python
  FIXED in-slice; launch_new_system.bat:35,39 bare pythonw (legacy chain, sibling-consistent) DEFER.
- ops/launch_new_system.bat:44 latent bug: run_self_healing_watchdog.ps1 --ConfigPath (double-dash)
  binds as positional under -File -> Test-Path fails -> exit 1. Legacy chain only (live boots via
  rc_bootstrap.py). Should be -ConfigPath. P3-prune bucket.
- ops/RC-DaemonSlayer.xml has NO WorkingDirectory - CORRECT by design (start_daemon_slayer.py:20
  self-chdir's _PROJECT_ROOT since the task hands over C:\Windows\System32).
- rc-shell/ Electron security posture PASS: contextIsolation on / nodeIntegration off / sandbox on
  both windows; preload empty; cert-trust exact-host-only (never global); injection escaping proven
  (JSON.stringify + normPanelSet). 145/145 node tests. Slice already hardened, 0 FIX-NOW.
- gamepc/2-PC refs (P3-prune feed, note-only): scripts/{discover_champion_codes,probe_missing_codes,
  team_planner_sync}.py hardcode 192.168.8.237 LCU base (should be 127.0.0.1/RC_GAME_HOST post-1PC);
  ops/phase3_setup/phase3_summary SMB 192.168.8.237 + game_pc topology; ops/phase3_install +
  install_RC_LegionBridgeDaemon gamepc comments; tft_vision_reader/tft_ocr_reader Game-PC frame
  comments (accurate post-1PC relay-path notes, not stale wiring).

## W5 test corpus tests/ (cycle 16, 6 disjoint slices A-F; audit + sweep, no product/DS edit)

Lighter test-corpus lens (data-fragile asserts / stale pins / dead-skip-xfail rot / asyncio.run
polluter / ASCII / non-hermetic writes). Outcome: the corpus is mature + clean. ZERO product bugs
surfaced, so ZERO new tests added (unlike W1-W4 which added regression tests per product fix). The
ONLY FIX-NOW class was non-ASCII glyph cleanup in comments/docstrings/dividers (47 test files swept
to ASCII: U+2192 arrow -> ->, U+2500 box-draw -> -, U+2194 -> <->, U+00D7 -> x, U+2248 -> ~,
U+2265 -> >=, U+2212 -> -, U+00A7 -> section, U+ACE4 Korean -> \\uace4 source-escape). This is the
test-corpus arm of the coordinated ASCII-in-output pass already logged under W4-hw2 (prints/docstrings
in scripts/ops/tft + the production wire arrow below still pending a P3 production-side slice). NO
em-dash/en-dash/smart-quote was found anywhere (those were already swept) - all hits were decorative
or load-bearing non-banned glyphs that strip_em_dashes.py deliberately left; charter auth 6 (full
encoding retro-sweep) is the operator grant the test_u2500_hygiene.py SCOPE NOTE asks for.

### MED (production-side, own slice - NOT a test-corpus fix)
- coaches/aram_coach.py item_build wire convention uses a LITERAL U+2192 separator
  ("Boots -> Item" built/split on the raw arrow; documented "Arrow separator in item_build is U+2192
  per coach prompt convention"). PROVEN load-bearing: converting the 11 arrows in
  tests/phase2_smoke/test_aram_coach_item_class_peers.py (slice D) broke 8 tests -> reverted to
  pristine. This is a real production non-ASCII data convention; ASCII-ifying it touches the coach +
  the Haiku coach-prompt format + every peer test = a coordinated production slice (fold into a P3/P4
  ASCII-output pass, NOT this test-corpus wave). test file left with its 11 arrows by design.

### INFO (W5)
- tests/phase7_polish/test_wakeup_prune.py retains exactly 3 U+2705 (white-check) bytes after the
  decorative sweep - they are LOAD-BEARING PIN fixture data ("# U+2705 RESOLVED ..." lines that
  test_session_re_does_not_match_pin / test_leading_pin_folds_into_header assert SESSION_RE rejects).
  Intentionally NOT swept; the file's decorative U+2500 dividers + 2 U+2192 WERE swept.
- Slice A initially read the ASCII lens narrowly (em/en-dash + smart-quote only) and deferred its 6
  decorative-glyph files as INFO; supervisor swept them post-merge (ops/audit/p2w5_sweep_sliceA.py)
  for corpus consistency, leaving the 2 load-bearing files above as the ONLY remaining non-ASCII in
  tests/. Net: decorative non-ASCII is now ZERO across the corpus except those 2 justified files.
- Several files carry INTENTIONAL data-fragile asserts kept by design (NOT findings):
  test_daemon_slayer_resolver_hp.py pins long-stable item HP literals as a deliberate DDragon-rebalance
  drift detector; test_item_wpa.py documents "Do NOT pin exact numbers"; champion-roster conformance
  guards assert == 172 (live champ count, bumps with a new champ). All correct as-is.

## W5 test corpus agents/daemon_slayer/tests (cycle 17, 6 disjoint slices A-F; audit + sweep, no product/DS edit)

Same lighter test-corpus lens as W5 half 1. 222 files / 86705 LOC. Outcome matches half 1: the DS
test corpus is mature + clean. ZERO product bugs surfaced -> ZERO new tests. The ONLY FIX-NOW class
was non-ASCII glyph cleanup in comments/docstrings/dividers: 39 files swept to ASCII (U+2500 box-draw
-> -, U+2192 arrow -> ->, U+00D7 -> x, U+2248 -> ~, U+2265 -> >=, U+2260 -> !=, U+2212 -> -, U+00B1
-> +/-, U+00B7 middot -> * (multiply context), U+221E -> inf, U+03B1 -> alpha, U+03B2 -> beta,
U+21D2 -> =>, U+226B -> >>). em-dash/en-dash/smart-quote count was ZERO at wave start (already swept)
- all hits were decorative or load-bearing NON-banned glyphs strip_em_dashes.py deliberately left;
charter auth 6 (full encoding retro-sweep) + auth 7 is the grant. Every edited file is a balanced
in-line ASCII swap (git numstat net 0 lines/file); no logic/assertion/count change. Post-sweep fresh
census = exactly 1 remaining non-ASCII file (the load-bearing DEFER below); 0 banned glyphs.

### MED (production-side, own slice - NOT a test-corpus fix)
- agents/daemon_slayer/tests/test_effects_expansion.py:3892 retains 1x U+2192 inside
  re.search("effective target armor [\\d.]+\\s*->\\s*([\\d.]+)", n): the DS engine (agents/daemon_slayer/
  dps.py) EMITS a literal U+2192 in its "effective target armor X -> Y" note strings, and this regex
  matches that live output. PROVEN load-bearing by slice A (converting it makes eff_armor() return None
  -> assertIsNotNone(eff_lvl1) fails in the Lvl/Pen tests). dps.py is the production source. This is the
  DS-engine analog of the W5-half-1 aram-coach item_build arrow - same MED DEFER: fold into a coordinated
  P3/P4 production-side ASCII-output slice (change dps.py's emitted arrow + this regex together), NOT a
  test-only pass. An in-file comment (3889-3891) already documents the load-bearing reason.

### INFO (W5 half 2)
- Pervasive historical ENGINE_VERSION narrative in docstrings + method names (e.g.
  test_engine_version_at_1_41_0 / "pins 1.41.0" / "wave-6 ship state (1.37.0)") across many files while
  the actual ASSERTION correctly pins live 1.120.0 (or uses a drift-tolerant assertGreaterEqual floor).
  Correct asserts, stale PROSE only - the established repo orchestrator-bump convention, not a defect.
  A P8 docs-sweep job, NOT a test-corpus fix (and out of the no-history-rewrite + ASCII-mandate scope).
- INTENTIONAL drift-detector pins kept by design (NOT findings): == 172/171 roster-conformance, == 150/
  725/258 coverage-count guards, FROZEN {16.10.1, 16.11.1} DataSnapshot fixture pins, item-HP literals.
- skip/xfail census = all legit, no rot: conditional skips (DS-server-unavailable guards, data-conditional
  skipTest, _require_live_sidecar) + 1 strict xfail (test_wireable_sims_p1l3.py:901, a deliberate Phase-1
  lifesteal/spellvamp sustain contract-gap flagged for the engine owner).
- 0 asyncio.run polluters; 0 non-hermetic writes (every .write_text targets tmp_path/TemporaryDirectory;
  real data/ paths are read-only sources). Corpus is correctly hermetic.
