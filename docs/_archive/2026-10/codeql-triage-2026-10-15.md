# CodeQL triage, 2026-10-15 (PUBREPO order item 1g)

Every code-scanning alert that was open on 2026-10-15 (54: 43 high, 11 medium),
triaged high first. FIXED rows name the commit that removes the flagged flow.
PATHS-IGNORE closes on the next analysis because `docs/_archive/**` is no longer
analysed (`.github/codeql/codeql-config.yml`). DISMISS rows carry the written
reason posted with the dismissal. Line numbers are as of the analysis on
2026-10-15 and may have moved since.

| Severity | FIXED | PATHS-IGNORE | DISMISS | Total |
|---|---|---|---|---|
| high | 20 | 1 | 22 | 43 |
| medium | 11 | 0 | 0 | 11 |

| # | Severity | Rule | Location | Verdict | Reason | Note |
|---|---|---|---|---|---|---|
| 5 | high | `js/xss` | `docs/_archive/2026-05-18-dead-dashboard-js/web-js-dashboard.js:1716` | PATHS-IGNORE 4c3d4da04 | - | archived dead dashboard copy, never served; docs/_archive/** paths-ignore via .github/codeql/codeql-config.yml (only 2 js files there, no py) |
| 6 | high | `js/xss` | `web/js/panels/augment_reco.js:114` | FIXED f3caad1cf | - | score / n_own now _esc()d; DOM byte-identical for numeric payloads |
| 7 | high | `js/xss` | `web/js/panels/coach_choices.js:223` | FIXED f3caad1cf | - | _bandDots escapes the LLM confidence band; low/mid/high byte-identical |
| 8 | high | `js/xss` | `web/js/panels/champ_select.js:958` | FIXED f3caad1cf | - | _csvArenaPaneHtml escapes names, augment fields, round tier; ui_mock arena byte-identical |
| 9 | high | `js/xss` | `web/js/panels/champ_select.js:971` | FIXED f3caad1cf | - | _csvBenchHtml escapes bench id + name; all 173 champions byte-identical |
| 10 | high | `js/xss` | `web/js/panels/champ_select.js:3636` | FIXED f3caad1cf | - | _csvRenderEnemiesArena escapes team label + champion name; ui_mock arena byte-identical |
| 11 | high | `js/xss-through-dom` | `web/js/main.js:7552` | FIXED e5dcd6b58 | - | tooltip rebuilt by lib/helpers.renderTooltipHtml allowlist, no innerHTML; 7120/7120 tooltips DOM-identical to innerHTML; see 44a4a3708 |
| 12 | high | `js/incomplete-multi-character-sanitization` | `web/js/lib/lol_descriptions.js:54` | FIXED cf5ef3eba | - | real bypass (<b onmouseover> kept): fixpoint strip, bare b/i/br, stray < escaped; title-row fix-up 44a4a3708 (items 3901-3903) |
| 13 | high | `js/incomplete-multi-character-sanitization` | `web/js/lib/items_index.js:214` | FIXED cf5ef3eba | - | parseItemTooltip strips via lib/helpers.stripTags (fixpoint); 706 DDragon items deep-equal |
| 14 | high | `js/incomplete-multi-character-sanitization` | `web/js/panels/build_insights.js:69` | FIXED cf5ef3eba | - | _stripHtml -> lib/helpers.htmlToText (fixpoint stripTags); output _esc()d into title= |
| 15 | high | `js/incomplete-multi-character-sanitization` | `web/js/main.js:2654` | FIXED cf5ef3eba | - | _stripHtml -> lib/helpers.htmlToText (fixpoint stripTags); output assigned to .title |
| 16 | high | `js/incomplete-multi-character-sanitization` | `web/legacy_index.html:2951` | FIXED 9c14e6aed | - | page still served (?ui=legacy + index fallback); dedupe key now strips to a fixpoint; key is compared only, never rendered |
| 17 | high | `js/double-escaping` | `web/js/panels/build_insights.js:69` | FIXED cf5ef3eba | - | _stripHtml delegates to lib/helpers.htmlToText: &amp; decoded last; 787 DDragon texts unchanged |
| 18 | high | `js/double-escaping` | `web/js/main.js:2654` | FIXED cf5ef3eba | - | _stripHtml delegates to lib/helpers.htmlToText: &amp; decoded last; 787 DDragon texts unchanged |
| 19 | medium | `js/incomplete-html-attribute-sanitization` | `web/js/panels/champ_benchmarks.js:99` | FIXED 74276583a | - | _esc delegates to lib/helpers.escHtml (escapes quotes); DOM-identical on fixtures |
| 20 | medium | `js/incomplete-html-attribute-sanitization` | `web/js/panels/duration_winrate.js:115` | FIXED 74276583a | - | _esc delegates to lib/helpers.escHtml (escapes quotes); DOM-identical on fixtures + 207 champion strings |
| 21 | medium | `js/incomplete-html-attribute-sanitization` | `web/js/panels/duration_winrate.js:120` | FIXED 74276583a | - | same _esc fix as alert 20 (value= attribute of the champion filter) |
| 22 | medium | `js/incomplete-html-attribute-sanitization` | `web/js/panels/op_score.js:134` | FIXED 74276583a | - | _esc delegates to lib/helpers.escHtml; op_score._html over ui_mock byte-identical |
| 23 | medium | `js/incomplete-html-attribute-sanitization` | `web/js/panels/patch_impact.js:91` | FIXED 74276583a | - | _esc delegates to lib/helpers.escHtml; chip title cannot break out (test pinned) |
| 24 | medium | `js/incomplete-html-attribute-sanitization` | `web/js/panels/patch_impact.js:100` | FIXED 74276583a | - | _esc delegates to lib/helpers.escHtml; patchImpactHtml DOM-identical |
| 25 | medium | `js/incomplete-html-attribute-sanitization` | `web/js/panels/perf_curve.js:122` | FIXED 74276583a | - | _esc delegates to lib/helpers.escHtml; perf_curve._html over ui_mock byte-identical |
| 26 | medium | `js/incomplete-html-attribute-sanitization` | `web/js/panels/playstyle_labels.js:64` | FIXED 74276583a | - | _esc delegates to lib/helpers.escHtml; playstyleLabelsHtml DOM-identical |
| 27 | medium | `js/incomplete-html-attribute-sanitization` | `web/js/panels/session_hygiene.js:108` | FIXED 74276583a | - | _esc delegates to lib/helpers.escHtml; sessionHygieneHtml over ui_mock byte-identical |
| 28 | high | `js/incomplete-sanitization` | `web/js/lib/champion_tags.js:31` | FIXED 9c14e6aed | - | variant keys use global /'/g, / /g like the server's str.replace; every DDragon lookup unchanged |
| 29 | high | `js/incomplete-sanitization` | `web/js/lib/champion_tags.js:33` | FIXED 9c14e6aed | - | same fix as alert 28 |
| 30 | high | `js/disabling-certificate-validation` | `rc-shell/src/main.js:1145` | DISMISS | won't fix | pollState GETs /api/state only from the configured RC origin (default 127.0.0.1:8888, mkcert self-signed); no credentials sent; reads mode_key to pick the overlay surface |
| 31 | high | `py/path-injection` | `coaches/_adaptation_common.py:59` | DISMISS | false positive | mode allow-listed (coaches/_adaptation_common.py:46, return None unless in lib/modes.PHASE3_MODES) before base / f'{mode}.db' at :58. |
| 32 | high | `py/path-injection` | `vision_server/_http.py:218` | DISMISS | false positive | Confined: NUL refused (vision_server/_http.py:213), root=SYNC_DIR.resolve() (:217), candidate resolve() (:218), relative_to(root) (:219) else 404; tests/test_vision_server_http_hardening.py. |
| 33 | high | `py/path-injection` | `vision_server/_http.py:223` | DISMISS | false positive | Confined: NUL refused (vision_server/_http.py:213), root=SYNC_DIR.resolve() (:217), candidate resolve() (:218), relative_to(root) (:219) else 404; tests/test_vision_server_http_hardening.py. |
| 34 | high | `py/path-injection` | `vision_server/_http.py:224` | DISMISS | false positive | Confined: NUL refused (vision_server/_http.py:213), root=SYNC_DIR.resolve() (:217), candidate resolve() (:218), relative_to(root) (:219) else 404; tests/test_vision_server_http_hardening.py. |
| 35 | high | `py/path-injection` | `vision_server/_http.py:286` | DISMISS | false positive | PUT target is SYNC_DIR / Path(seg).name (vision_server/_http.py:281,:285): one component; '', '.', '..' are dirs so write_bytes fails (500). Auth-gated, loopback bind. |
| 36 | high | `py/path-injection` | `agents/agent4_coach_mentor/analyzer.py:323` | DISMISS | false positive | mode allow-listed (agents/agent4_coach_mentor/analyzer.py:316, raise unless in lib/modes.PHASE3_MODES from tracked resolved_decisions.json) before DB_DIR / f'{mode}.db'. |
| 37 | high | `py/insecure-temporary-file` | `tests/test_precommit_gate_message_file.py:46` | FIXED 49458d52b | - | tempfile.mktemp -> mkstemp (fd closed, write inside try, finally unlinks). Adjudicator Q4: fix in tree, no paths-ignore. |
| 38 | high | `py/polynomial-redos` | `agents/agent7_context/input_parser.py:154` | FIXED ff233e115 | - | Cubic (agent0 + 1600 spaces + x\ny = 5.8 s). Equivalent linear form; differential fuzz 6764800 comparisons, 0 differences. |
| 39 | high | `py/polynomial-redos` | `agents/agent7_context/input_parser.py:192` | FIXED ff233e115 | - | Cubic (note + 1600 spaces + x\ny = 7.3 s). Equivalent linear form; differential fuzz 6764800 comparisons, 0 differences. |
| 40 | high | `py/clear-text-storage-sensitive-data` | `scripts/rewind_catchup.py:443` | DISMISS | false positive | State JSON holds puuid/riot_id account ids and run-status literals (scripts/rewind_catchup.py:865-874, :468-472); no API key or password ever enters it. |
| 42 | high | `py/clear-text-storage-sensitive-data` | `tests/test_vision_server_http_hardening.py:112` | DISMISS | used in tests | Planted fake SECRET ("SUPERSECRET-not-a-real-key") proves /sync/get/ refuses path traversal; written beside SYNC_DIR, removed in cleanup. Adjudicator Q4. |
| 43 | high | `py/clear-text-storage-sensitive-data` | `tests/test_vision_server_http_hardening.py:129` | DISMISS | used in tests | Same planted fake SECRET, in a temp dir, proves /sync/get/ refuses an absolute-path injection; removed in cleanup. Adjudicator Q4. |
| 44 | high | `py/clear-text-logging-sensitive-data` | `lib/http/client.py:507` | DISMISS | false positive | Logged value is the hostname only: urlparse(url).hostname, normalized (lib/http/client.py:567, :150); a hostname excludes userinfo/path/query, so no credential reaches the log. |
| 45 | high | `py/clear-text-logging-sensitive-data` | `lib/http/client.py:520` | DISMISS | false positive | Logged value is the hostname only: urlparse(url).hostname, normalized (lib/http/client.py:567, :150); a hostname excludes userinfo/path/query, so no credential reaches the log. |
| 46 | high | `py/clear-text-logging-sensitive-data` | `lib/http/client.py:525` | DISMISS | false positive | Logged value is the hostname only: urlparse(url).hostname, normalized (lib/http/client.py:567, :150); a hostname excludes userinfo/path/query, so no credential reaches the log. |
| 47 | high | `py/clear-text-logging-sensitive-data` | `scripts/rewind_catchup.py:483` | DISMISS | false positive | Logged outcome is a fixed status literal (RUN_* at scripts/rewind_catchup.py:137-140, e.g. "no_api_key"); the Riot key itself is never logged or stored. |
| 48 | medium | `py/bind-socket-all-network-interfaces` | `agents/_supervisor_common.py:466` | FIXED 49458d52b | - | Only 0.0.0.0 source was the probe in agents/agent3_testing/suite/test_quality_pass.py, now 127.0.0.1. Production BIND_HOST is loopback unless RC_PHASE3_BIND_HOST (RM-231). |
| 49 | high | `py/weak-sensitive-data-hashing` | `core/obs_publisher.py:482` | DISMISS | won't fix | obs-websocket 5.x Identify auth mandates base64(sha256(password+salt)) then sha256(secret+challenge); any other hash fails the handshake. Nothing persisted. |
| 50 | high | `py/weak-sensitive-data-hashing` | `core/riot_api.py:149` | DISMISS | won't fix | Truncated SHA-256 of a high-entropy Riot API key used as a cache-key fingerprint, not password storage; persisted account:v1 cache keys (core/riot_api.py:733) depend on it. |
| 51 | high | `py/weak-sensitive-data-hashing` | `tests/test_p2w1_core_f.py:207` | DISMISS | used in tests | Recomputes the obs-websocket 5.x SHA-256 auth response to assert core/obs_publisher.py sends the protocol-mandated value. Adjudicator Q4 (verified). |
| 53 | medium | `py/http-response-splitting` | `dashboard/_handler.py:388` | FIXED 815a6c602 | - | Obs-folded Origin kept CR/LF and passed the loopback gate; _cors_allowed_origin now refuses any non-printable or whitespace char. Not RM-745 (server.py redirect). |
| 54 | high | `py/redos` | `tools/stop_claim_gate.py:418` | FIXED b1a1d336f | - | Exponential (40 x ' -c' = 56 s). _GIT_OPTIONS: same language and first match; fuzz vs HEAD file 42744580 comparisons, 0 differences. Also fixes _GIT_LEAD. |
| 55 | high | `py/redos` | `tools/stop_claim_gate.py:418` | FIXED b1a1d336f | - | Exponential ('-- -' x 24 = 3.4 s; --x words split two ways). Same _GIT_OPTIONS rewrite; 0 differences in 42744580 comparisons. |
| 58 | high | `py/incomplete-url-substring-sanitization` | `tests/test_atlas_fonts.py:151` | DISMISS | false positive | Asserts the font name-table licence text (IDs 13+14) names the OFL; nothing is fetched or trusted by URL - a licence check, not URL sanitization. Adjudicator Q4. |
| 59 | high | `py/insecure-protocol` | `tests/test_mc_server_tls_accept_rm739.py:97` | DISMISS | used in tests | Test-only TLS client (verification off on purpose) probing a loopback test server's accept loop; protocol floor is irrelevant. Adjudicator Q4. Alt: minimum_version=TLSv1_2. |
| 60 | high | `py/insecure-protocol` | `tests/test_mc_server_tls_accept_rm739.py:220` | DISMISS | used in tests | Test-only TLS client (verified, test CA) against a loopback test server; Python already floors at TLS 1.2. Adjudicator Q4. Alt: minimum_version=TLSv1_2. |
| 61 | high | `py/insecure-protocol` | `tests/test_dashboard_tls_accept_rm742.py:149` | DISMISS | used in tests | Test-only TLS client (verification off on purpose) probing a loopback test server's accept loop; protocol floor is irrelevant. Adjudicator Q4. Alt: minimum_version=TLSv1_2. |
| 62 | high | `py/insecure-protocol` | `tests/test_dashboard_tls_accept_rm742.py:375` | DISMISS | used in tests | Test-only TLS client (verified, test CA) against a loopback test server; Python already floors at TLS 1.2. Adjudicator Q4. Alt: minimum_version=TLSv1_2. |
