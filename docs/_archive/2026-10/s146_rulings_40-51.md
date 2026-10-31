# Session 146 rulings: operator asks 40, 41, 42, 43, 44, 48 and 51 (self-adjudicated)

2026-10-31, session 146. Channel code RC.

Authority: the operator answered in chat, session 146: rulings 40-44, 48 and 51 from the
hand-off's operator-ask batch -> "self-adjudicate". Each ruling below was taken by a distinct
adjudicator sub-agent (FLEET-COMMON item 1) and is recorded as decision, alternatives, why and
reversal. Precedent for the form: LEDGER 1984 (ASKS 31) and 1986 (RM-1222 ruling C).

Floors this record does NOT lift: the halt boundary (any write, delete or lock outside the repo
root; any push whose diff can leak; any public publish), the frozen-file gate, the CLAUDE.md
third-party licence gate, MAIN-owned acts, and acts that need money, a legal identity, an account
login or a physical action. Where an ask needs one of those, the ruling says who keeps it.

Nothing else in the tree was changed by this record. LEDGER, ROADMAP, BACKLOG, CLAUDE.md and the
hand-off are the merger's and /done's to update; each ruling names its follow-up.

Ask text: `docs/handoff-archive/RC-2026-10-31.txt` block 2 (asks 40-44 and 48 at its lines
332-339 and 349); ask 51 and the RM-962 body: `BACKLOG.md` "Session 144 lane filings (research
lane)" (RM-962 at line 96-100).

Recall gate: `python tools/perseus_recall.py` was run for each topic (M10 licence payload;
signing and release; RM-189 / ADR-006; websockets; RM-962 wiki Terms). No settled or ledger hit
reads CLOSED or REFUTED for any of the seven questions.


## Ruling 40 - M10 licence payload: the two LGPL ffmpeg DLLs and certifi (MPL-2.0)

Question: "Licence ruling: the two LGPL ffmpeg DLLs (Electron ffmpeg.dll; the opencv videoio
DLL, stripped by default) and certifi (MPL-2.0) - ship, strip or replace?"

Ruling id for the notices generator: `M10-S146-R40`.

Decision, per item:

- opencv `cv2/opencv_videoio_ffmpeg*.dll` (LGPL-2.1): STRIP, mandatory. It stays OUT of the
  generator's `RULINGS`, so a bundle that ever carries it again fails
  `tools/build_third_party_notices.py` (fail closed).
- Electron runtime `ffmpeg.dll` (LGPL-2.1) and `LICENSES.chromium.html`: SHIP, unmodified and
  dynamically loaded, on these conditions:
  - C1. The Electron dist's `LICENSE` and `LICENSES.chromium.html` ship verbatim beside the
    executable (the generator already reads both).
  - C2. The generated THIRD_PARTY_NOTICES names ffmpeg as LGPL-2.1 and carries the full
    LGPL-2.1 text.
  - C3. Any release that carries the DLL also offers its corresponding source FROM THE SAME
    PLACE: the source of that exact ffmpeg build (Chromium's ffmpeg at the revision the shipped
    Electron's Chromium pins) is attached to the same GitHub Release. A link to an upstream host
    alone does not meet LGPL-2.1 section 4. The notices also name the Electron and Chromium
    versions and point to the upstream Chromium source for the MPL-covered parts inside the
    Electron runtime (MPL-2.0 section 3.2 asks only for "reasonable means").
  - C4. The DLL is never swapped for a modified or proprietary-codec build. A modified build
    changes the obligations and needs a new ruling.
  - C5. LGPL-2.1 section 6 asks that the work using the library permit modification and
    reverse engineering. RC's own code is Apache-2.0 and Electron is MIT, so this is already met.
- certifi (MPL-2.0): REPLACE, then drop. RC's one use (`lib/http/client.py:88-101`, the
  `_SSL_CONTEXT` built from `certifi.where()`) moves to truststore, which is MIT, is already in
  the shipped closure as httpx2's dependency (`pip show httpx2`: Requires truststore) and gives
  the OS verifier the SDK traffic already uses. Then certifi leaves `requirements.in:24` and the
  hashed lock. It stays OUT of `RULINGS` until the replacement lands, so a bundle built before
  then fails the generator. That matters only at a release, and none is ruled (ruling 42).
  Fallback: if the replacement is measured infeasible (for example, truststore cannot verify on
  the embedded 3.14 runtime), certifi ships unmodified with its MPL-2.0 text under
  `M10-S146-R40`, recorded with that measurement.

Measured s146:

- `electron.exe` in the main checkout's `rc-shell/node_modules/electron/dist` (electron 45.0.0)
  names `ffmpeg.dll` in its DELAY-import table. The PE import directories were read in Python:
  59 imported modules, `ffmpeg.dll` the only ffmpeg entry, delay-loaded. Stripping it would be
  an unsupported build that fails the first time media is decoded, for example the dashboard's
  recording `<video>` (PACKAGING_PLAN V3). Every Electron `ffmpeg.dll` is a build of the same
  LGPL library, so replacing it gains nothing.
- certifi is a DIRECT pin only. `requirements.txt:17-20` reads "certifi==2026.10.23 ... # via -r
  requirements.in". Its "anthropic / httpx2" lines just above belong to anyio, not to certifi.
  `.github/ci/requirements-docs-guards.in:52` records that anthropic 1.11.0 does not pull
  certifi in (httpx2 + truststore). The only tracked importer is `lib/http/client.py:99`.
  `tools/build_python_embed.py` already has the `include_certifi` switch, and
  `tests/test_build_portable_bundle_pkg.py:798-808` exercises it.
- The opencv strip is the default: `tools/build_python_embed.py:138`
  (`strip_opencv_ffmpeg: bool = True`). PACKAGING_PLAN M10 records that RC never calls
  `VideoCapture` / `VideoWriter`.

Licence gate: this does not breach the CLAUDE.md DO-NOT-VENDOR line. That line binds lifting
third-party source INTO the git tree, and nothing copyleft enters it: `node_modules/`,
site-packages, `python-embed/` and `dist/` are build output and gitignored. This ruling governs
the payload of a build artifact. It authorises NO distribution: publishing stays with ruling 42
and the halt boundary.

Alternatives considered:

- Strip all three. Rejected: Electron needs `ffmpeg.dll` for media, as above.
- Ship all three, opencv's DLL included. Rejected: the DLL is unused, and shipping it widens the
  LGPL surface for nothing.
- Ship certifi as-is now. MPL-2.0 permits it (section 3.3, Larger Work), but it was not chosen
  as the default because a permissive replacement is already in the closure. It stays as the
  recorded fallback.

Why: this removes every copyleft item that is not structurally required. It keeps the one that
is required (Electron's ffmpeg) under LGPL-2.1's own conditions for unmodified,
dynamically loaded use. And it keeps the notices generator failing closed on anything this
ruling does not name.

Reverses if: the Electron or certifi licence changes; Electron ships without a separate
`ffmpeg.dll` or links it statically; RC modifies either; RC starts calling cv2 video I/O (then
the opencv DLL needs its own ruling); the truststore replacement is measured infeasible (then
the certifi fallback above applies); or a rights holder or counsel says otherwise.

Follow-up:

- (a) Tier-1, about 15 min. In `tools/build_third_party_notices.py:66-70`, record
  `RULINGS = {"electron-runtime:ffmpeg.dll": "M10-S146-R40", "electron-runtime:chromium-credits":
  "M10-S146-R40"}`, with no opencv glob and no certifi entry, and update the docstring at
  `:20-25` and the comment at `:66-69`. Add a test in `tests/test_third_party_notices_pkg.py`
  asserting that `RULINGS` covers exactly those two ids (the component ids are as used at
  `:348-349`). In `docs/PACKAGING_PLAN.md`, mark M10 (`:126-145`), the operator-gated line
  (`:622-623`) and section 6 (`:864`) "ruled s146, M10-S146-R40".
- (b) Tier-1 deps, about 45 min, a queue slice and not small. Do the certifi -> truststore
  replacement in `lib/http/client.py:88-101` and the comment at `:590`. Keep verification on
  (CERT_REQUIRED plus hostname) and the RM-752 TLS 1.2 floor. Add truststore as a direct pin and
  drop certifi from `requirements.in`, regenerate the hashed lock with the header's uv command,
  and flip `include_certifi` to False by default in `tools/build_python_embed.py`.
- (c) C3, the source attachment, goes on the release checklist (ruling 42).


## Ruling 41 - Code-signing certificate, or ship unsigned (S4)

Question: "Code-signing certificate for the packaged app, or ship unsigned (S4)?"

Decision: SHIP UNSIGNED for now (ruling id `S4-S146-R41`). No certificate is bought and no
signing service is enrolled. The build is documented as unsigned, as `docs/PACKAGING_PLAN.md`
S4 (`:166-169`) already provides. S4 is RE-DECIDED by the operator before any build goes to
anyone else (rulings 42 and 44). Until then, every published asset's SHA-256 goes in the
release notes and the SmartScreen warning is documented. Buying or enrolling a signing identity
stays with the operator: it is a payment plus an identity check of the publisher.

Alternatives considered:

- Buy an OV certificate now. Rejected: it costs money, needs the operator's identity, and has no
  recipient today.
- Buy an EV certificate. Rejected: the same, plus a hardware token, which is a physical act.
- Enrol a cloud signing service. Rejected for now: it needs the operator's identity validation
  and a recurring cost.
- Self-sign. Rejected: worse than unsigned. SmartScreen still warns, and users would have to
  trust a new root, which is a security anti-pattern.

Why:

- The operator's own box needs no signature. PACKAGING_PLAN section 6 (`:855`): "Running the
  packaged build on the operator's own box needs none of these."
- Update integrity today is the sha512 in `latest.yml` over HTTPS (S4).
- The choice is reversible: signing can be added at any release. Adding it later is not
  expected to strand unsigned installs, because an unsigned build's update config names no
  publisher to check. Re-verify this against the electron-updater version in the lock when S4
  lands.

Binding when a certificate is added: WA12 (`docs/PACKAGING_PLAN.md:798-801`) lands in the same
change. That is the signing exclusion that keeps electron-builder from re-signing the PSF-signed
`python.exe` / `pythonw.exe` and the site-packages `.exe` files.

Reverses if: the operator buys or enrols a signing identity; the app goes to users beyond the
operator; a Windows or SmartScreen change blocks unsigned installs; or an antivirus vendor flags
the unsigned installer.

Follow-up: Tier-0, about 5 min. `docs/PACKAGING_PLAN.md` S4 (`:166-169`), the operator-gated line
(`:624`) and section 6 (`:865`) read "ruled s146: unsigned (S4-S146-R41); re-decide before
distribution; WA12 binds the certificate change".


## Ruling 42 - First packaged-app GitHub Release

Question: "OK to publish the first packaged-app GitHub Release (PKG-6 / PKG-7 landed s142;
PKG-6b waits on PKG-6c; WA9 first)?"

Decision: NO, NOT NOW. Publishing is deferred until every blocker below is closed and read back.
Even then, the publish itself is a fresh, attended operator go. A public release is bytes leaving
the tree, and a downloaded binary cannot be recalled (halt boundary). This ruling does not give
that go in advance.

Blockers, measured s146 from the tracked docs:

- WA9 is undecided (`docs/PACKAGING_PLAN.md:673-678`). An NSIS oneClick upgrade is expected to
  replace the install dir, losing `ops/runtime` secrets, logs, `data/` runtime files and any
  PKG-2 backend update. This is unmeasured. Release 1 fixes the upgrade path for every later
  release, so WA9 is decided and fixed BEFORE release 1, or the first update wipes state.
- The PKG-6c residue is open: M2 LOW, LOW 1 and LOW 2 (LEDGER 1945; hand-off). WA14 (`:694-701`)
  and WA17 (`:760`) are open. PKG-6b waits on PKG-6c.
- ASKS 45 (a), the attended Explorer launch, has not been done: the PKG-6 visual check plus the
  electron 45 shell check. The PKG-6 GPU error_code=18 seen in the agent environment is
  undecided.
- The distribution gates (`docs/PACKAGING_PLAN.md` section 6, `:853-867`) all apply. A Release on
  a PUBLIC repo is giving the build to anyone:
  - the ADR-006 reopen (ruling 44);
  - the RM-189 gates (ruling 43);
  - the M10 notices shipped (ruling 40, follow-ups (a) and (b), plus C3, the ffmpeg source
    attached to the same Release);
  - S4 re-decided (ruling 41);
  - the N8 asset provenance audit of everything in the bundle (not recorded as done).

Alternatives considered:

- Publish now. Rejected: it fails section 6 and WA9.
- Publish a GitHub DRAFT release to test the feed. Rejected for now: it is still an out-of-tree
  upload, and nothing needs it.
- Use the in-tree route for the operator's own use. This is what runs today and needs no
  release: build locally and update the backend from a local folder (`ops/launcher/updater.py`
  `LocalSource`, `--source local:<dir>`).

Why: the first release sets the upgrade contract for every install. Its prerequisites are
measured open, and the act is public and irreversible in effect.

Reverses if: every blocker above is closed and read back (the publish is then re-asked as ONE
attended act), or the operator orders a release directly.

Follow-up: Tier-0, about 10 min. Add a "First Release checklist" to the "Operator-gated" block in
`docs/PACKAGING_PLAN.md` (`:620-630`) naming the blockers above, including C3 from ruling 40 and
the B4-f interim from ruling 43. WA9 itself is a design-and-measure slice: seed a user-data
backend root and pass `--rc-root`. That is over 30 min and is not listed as small.


## Ruling 43 - RM-189 public-release gates

Question: "RM-189 public-release gates: Riot dev-portal registration, public site + ToS + Privacy
Policy, the B4-f live-advice ruling."

Decision: ALL THREE GATES STAND as hard prerequisites for any build that goes to anyone other
than the operator. None is waived. Each stays with its owner, and B4-f gets one interim in-tree
default:

- Riot Developer Portal registration and the production key stay with the operator. They need
  the operator's account login, and the production-key review is ASKS 32. The ROADMAP RM-189 row
  (`ROADMAP.md:143`) records them as operator-only.
- The public site, Terms of Service and Privacy Policy stay with the operator. Publishing a site
  is an out-of-tree public act. A ToS and a Privacy Policy are legal undertakings by the
  publisher, who controls Riot-API data on identifiable players (NOTICE, "Riot API / Match-V5"),
  and an adjudicator cannot give them. Drafting in-tree happens only on an operator order.
- B4-f ("are build/shop recommendations in or out during a live game?") is Riot DevRel's to
  answer (`docs/OVERLAY_B4_DESIGN.md:162-167`, `:284`, `:294`). Raising it is outreach, which is
  the operator's, together with B8 and B9.
  - INTERIM: until DevRel answers IN, any build that goes to anyone else treats build and shop
    recommendations as OUT during a live game. They are withheld through the existing B4
    live-game predicate, the way TFT engine recommendations already are (`dashboard/routes_tft.py`
    `_live_game_now`, used by `build_engine_recommend`; BACKLOG RM-893 note).
  - The operator's own box keeps today's behaviour. The 2026-08-12 B4 design left it
    deliberately, noting that every approved competitor ships one (`OVERLAY_B4_DESIGN.md:162-167`).
  - The interim binds at distribution time only, so it is a release-checklist item (ruling 42),
    not a code change now.

Alternatives considered:

- Waive the gates for a "preview" release. Rejected: the production-key requirement is Riot's,
  and a shared build on the personal key breaks ADR-006.
- Build the site, ToS and Privacy Policy now. Rejected: these are the operator's legal acts, and
  there is no recipient yet.
- Remove live build recommendations everywhere now. Rejected: it deletes a core feature over an
  open question.

Why: every gate depends on a party other than RC (Riot, or the operator as publisher). The only
in-tree lever is the conservative interim default, and it costs nothing until distribution.

Reverses if: DevRel answers B4-f (IN lifts the interim; OUT applies it to every build, the
operator's included); the operator publishes the site, ToS and Privacy Policy and the production
key is approved; or Riot's third-party policy changes.

Follow-up: Tier-0, about 5 min, for the merger. Note the B4-f interim in the ROADMAP RM-189 row
and in `docs/OVERLAY_B4_DESIGN.md` section 8, item 1. The hand-off already says to move closed
ROADMAP rows to `docs/ROADMAP_HISTORY.md` before the next ROADMAP edit (the 90 percent line).


## Ruling 44 - Reopen ADR-006 before any build goes to anyone else?

Question: "Reopen ADR-006 (personal Riot key) before any build goes to anyone else?"

Decision: YES. The reopen is MANDATORY before the first build reaches anyone other than the
operator. ADR-006 says so itself (`docs/adr/ADR-006-riot-api-key-policy.md:35`: "If a future
requirement ever needs to redistribute RC ... this ADR must be reopened"), and the reopen is a
hard prerequisite of ruling 42. NOT NOW: no build is going to anyone (ruling 42), and the
reopen's deciding input, the production key (ASKS 32 / RM-189), is still in Riot review.
Reopening today would decide on an unknown.

Interim, already true and read back s146:

- A packaged payload never carries a Riot key. `tools/build_portable.py:123-127`
  (`_SECRET_NAME_RES`, `^api-key-.*\.txt$`) excludes `API-Key-Riot.txt` and
  `API-Key-Riot-TFT.txt`; the guard is `tests/test_build_portable_bundle_pkg.py:296-304`; see
  also `docs/PACKAGING_PLAN.md:363-368`.
- The Riot client soft-fails without a key (ADR-006 `:33`).

The reopened ADR starts from the always-legal shape:

- A shared build ships NO Riot key, and its Riot-API features degrade.
- A production key (RM-189) is the only route to full features for other users.
- A user-supplied personal key is NOT adopted by this ruling. Whether an app may ask its users
  for their own personal keys is Riot's call; raise it with B4-f.

Alternatives considered:

- Reopen now. Rejected: it would decide before the production-key outcome.
- Never reopen and ship with the personal key. Rejected: ADR-006 `:29` says "no
  redistribution", and Riot's personal-key terms say the same.
- Default to a user-supplied key. Rejected pending Riot's answer.

Why: the ADR's load-bearing assumption is a single user. The safety that matters today (no key
in any payload) is already enforced and guarded, so the reopen can wait for its real input.

Reverses if: a build is about to reach anyone else (reopen first); the production key is
approved or refused (reopen with the answer); or Riot changes its key tiers or terms.

Follow-up: optional, Tier-1, about 5 min. Add `"API-Key-Riot-TFT.txt"` to the parametrized list
in `tests/test_build_portable_bundle_pkg.py:296-300`. The regex already covers it; no test names
it.


## Ruling 48 - Live Python websockets 17.2 -> 17.3

Question: "OK to update the live Python websockets 17.2 -> 17.3 (writes outside the repo)?"

Decision: YES. Update the live interpreter's websockets to the locked 17.3: this one package and
this one version only.

Measured s146:

- The canonical interpreter (CPython 3.14.4) reports websockets 17.2. `pip show` lists no
  Requires and no Required-by.
- The hashed lock pins 17.3 (`requirements.in:31`, `requirements.txt:589`) since `e7175c3c3`
  (LEDGER 1921). CI and the packaged `python-embed`, both built from the lock, therefore run
  17.3, while the dev box runs 17.2: every local suite tests a version nothing ships.
- Tracked importers: `agents/agent2_backend/ws_server.py`, `core/lcu_events.py`,
  `core/obs_frame_source.py`, `core/obs_publisher.py`, `core/obs_recorder.py`.

Halt boundary: the install writes outside the repo root, into the interpreter's site-packages.
This ruling does NOT lift the boundary. The operator's own chat answer to ASKS 48
("self-adjudicate", s146) answers that ping for this one act, as the s145 answer did for ASKS 31
(LEDGER 1984). If the main session reads that answer as not covering the out-of-tree write, the
act stays with the operator; the merit decision stands either way. The interpreter is
user-wide, so another tree on this machine could import websockets. A patch release with no
dependents is the narrowest such change.

Conditions for the act:

1. No live game: `/api/state` shows no live mode.
2. Take a pre-install freeze to gitignored `ops/runtime/pip_freeze_before_websockets_17_3.txt`,
   following the D2 precedent (`pip_freeze_before_anthropic_1_11_0.txt`, LEDGER).
3. Install with hashes and no dependencies: build a one-package requirements file from the
   lock's `websockets==17.3` block (in the session scratchpad), then run
   `python -m pip install --require-hashes --no-deps -r <that file>`.
4. Read back `websockets.__version__ == "17.3"`.
5. Restart RC through `restart_trigger.txt`, plus every running host that imports websockets
   (`core/lcu_events.py` users, the agent2 ws_server). Read back `ops/runtime/health.json`:
   new pid, `alive`, `last_reload_ok`.
6. Run the touched test files that exercise the websockets paths (Tier-1, not a whole suite).
7. Reversal: `pip install websockets==17.2`, as named in the freeze.

Alternatives considered:

- Keep 17.2. Rejected: dev, CI and the shipped build stay out of step.
- Move RC to a venv. Rejected: it touches every launcher path and scheduled task, which is far
  past the ask.
- Install the whole lock. Rejected: a wider blast radius than asked.

Why: it aligns the dev box with what CI tests and what ships, at the smallest possible
out-of-tree change, and it can be undone with a recorded rollback.

Reverses if: 17.3 is measured breaking a websockets-backed path (roll back from the freeze), or
the lock moves again (then re-ask for the new pin).

Follow-up: the act itself, about 10 min, attended, run by the main session's executor under the
conditions above. It is out-of-tree, not an in-tree edit.


## Ruling 51 - RM-962: the wiki host's Terms of Use

Question: "RM-962 wiki Terms ruling". RC's tracked wiki fetchers make automated requests that the
wiki host's Terms of Use prohibit without prior consent, on paths its `robots.txt` disallows.
Ruling 51 also gates the RM-787 + RM-954 sidecar re-extract and the RM-955 live `--full` re-run.

Decision: NO AUTOMATED WIKI ACCESS (ruling id `RM962-S146-R51`). This takes RM-962 route (b),
"retire automated wiki reads", with route (c)'s NOTICE line written as the record. Route (a), a
consent request to the host, stays with the operator: it is outreach to a third party, and it is
the only reversal. DO-NOT-FETCH:

- The ONE wiki ability sidecar re-extract (RM-787 + RM-954 backfill) does not run against the
  wiki host.
- The RM-955 live `--full` staleness re-run does not run against the wiki host either.

Both move from "waits on RM-962" to "blocked by ruling 51; reopens only on recorded consent".

The CLAUDE.md licence gate, applied strictly:

- The host's Terms (Weird Gloop Terms of Use, "Updated on 31 January 2025", read 2026-10-27,
  quoted at `BACKLOG.md:97`) list as misuse "Attempting to use our Sites in an automated fashion
  without prior consent".
- `robots.txt` disallows `/*api.php`, `/*?action=` and `/en-us/Special:`, the exact paths the
  five fetchers request.
- Page prose is CC BY-SA 3.0, which a PUBLIC Apache-2.0 repo cannot absorb.

Terms that do not clearly permit the use mean DO-NOT-VENDOR and do-not-fetch.

Always-legal path:

1. The served sources RC already credits: Riot Data Dragon (`NOTICE:26`) and CommunityDragon
   (`NOTICE:30`). The Settled Meraki line already makes live DDragon prose win and lets
   CommunityDragon per-patch data break ties.
2. Re-implementation from observed behaviour: the DS cited-value pattern, where a human reads one
   page in a browser and cites one number. That is not automated use (`BACKLOG.md:95`,
   "Allowed").
3. A fetch-free correction of data already in the tree.

What stays: wiki-derived NUMBERS already committed, because game stats are facts and the prose is
not kept (`BACKLOG.md:100` DO-NOT-REDO: "Do not file a licence question on the numbers"). The
numbers-only fixture `tests/fixtures/game_data_replay/` (`NOTICE:62-65`) also stays. No purge and
no history rewrite, consistent with the Settled RM-846 line.

Measured s146:

- No scheduled automated wiki read is live. The live `RC-UpstreamDriftCheck` task runs
  `upstream_drift_check.py --bridge-note` only (read with Get-ScheduledTask). The tracked
  installer passes `--bridge-note --spec-watch` (`ops/install_RC_UpstreamDriftCheck.ps1:25`), and
  spec_watch reads DDragon only (`tools/spec_watch.py:50`).
- A DORMANT sixth arm exists. `tools/upstream_drift_check.py --staleness-recent` (`:589-615`,
  flag `:660-663`, call `:757-765`) imports `ds_wiki_staleness_check`, and would make the wiki
  reads unattended if the flag were ever added to the task. The refusal below covers it.
- The other tracked mentions of the wiki host under `agents/`, `core/` and `dashboard/` are
  citation comments; none of those files makes an HTTP call (grep for urlopen, requests,
  http.client, lib.http and fetch).

Alternatives considered:

- (a) Ask for consent now. Not rejected, but not the adjudicator's to do. It is the operator's
  outreach act, and it stays open as the reversal.
- (c) Keep the fetchers and record the risk. Rejected: it knowingly breaches the Terms, and the
  licence gate forbids proceeding on terms that do not clearly permit the use.
- Run the one re-extract "just once". Rejected: one automated run without consent is still
  automated use without consent.

Why: the Terms are explicit, the operator-read and served-source routes keep the DS pipeline
working, and nothing already committed has to move.

Reverses if: Weird Gloop grants RC consent, recorded with date and scope in
`docs/OVERLAY_COMPLIANCE_PLAN.md` (the re-extract and the RM-955 re-run then proceed within that
scope); the host's Terms change to permit identified, low-rate automated reads (re-read only to
check the date, per `BACKLOG.md:100`); or the host publishes an API usage policy that permits
them.

Follow-up:

- (a) Tier-0, about 15 min. Meets RM-962 acceptance parts 1 and 2.
  - NOTICE's wiki entry (`NOTICE:58-60`) gains the Terms line: `weirdgloop.org/terms`, the
    clause, the read date 2026-10-27 and "RC makes no automated requests (ruling 51, s146)".
  - `docs/OVERLAY_COMPLIANCE_PLAN.md` gains a row naming the five fetchers, the dormant
    `--staleness-recent` arm and route (b).
  - Check: `git grep -n "weirdgloop.org/terms" -- NOTICE` returns one line.
- (b) Tier-1, about 40 min, a queue slice and slightly over small. This refines RM-962 (b)'s
  acceptance from delete to refuse, which is reversible and keeps the RM-600 / RM-787 parsers
  and their tests.
  - Add a fail-closed fetch refusal at every wiki request path: `lib/game_data/sources.py` (the
    `wiki` Source `:216-221`, `_WIKI_MODULE` `:31`), `tools/daemon_slayer_wiki_ability_extract.py`
    (`WIKI_API`), `tools/daemon_slayer_wiki_stats_extract.py`, `tools/ds_wiki_staleness_check.py`
    (and so `upstream_drift_check --staleness-recent`) and `tools/ds_windup_offset_compare.py:31`.
    Each refuses before any socket opens unless a consent record exists. Parsers fed
    operator-supplied text keep working.
  - Add a test that patches the network layer and asserts zero requests.
- (c) Re-file the RM-787 backfill as a measure-first queue row. Check whether the param-less
  `abilities/Kled & Skaarl/*` records in the committed
  `data/daemon_slayer/16.21.1/wiki_ability_stats.json` can be corrected offline, with no fetch,
  using the fixed extractor's rule. If they can, it is a Tier-2 data change (dual suite, ENGINE
  bump only if a table moves, DS `:8860` restart), not small work.


## Side observation (not a ruling)

The main checkout's `rc-shell/node_modules/electron` reads 45.0.0 (its `package.json` and
`dist/version`, read s146). The hand-off's ASKS 45 (b) line says it "still" reads 44.5.1.
Re-check ASKS 45 (b) before re-asking it.
