# Rename sweep: Riot Commander -> Amberstone

Status: **TIER 0 EXECUTED 2026-08-11** (except the two operator-gated items
below). Tiers 1-3 not started. Name LOCKED by the operator:
**Amberstone** (product) + **Daemon Slayer** (engine, internal, unchanged).

Why this exists: the product name "Riot Commander" uses Riot's trademark, and
Riot's third-party developer policy forbids their trademarks in a project name,
website, advertising or domain without a written licence. **This rename BLOCKS
the Riot 3rd-party application, which in turn blocks the Overlay Platform M submission.**
See `docs/OVERLAY_COMPLIANCE_PLAN.md` N1.

---

## 0. THE TRAP THAT WOULD RUIN THIS SWEEP

**Measured on tracked files, 2026-08-11:**

| Pattern | Hits | Files |
|---|---|---|
| any case-insensitive `riot` | **4163** | 957 |
| `Riot Commander` | 653 | 258 |
| `riot-commander` | 205 | 72 |
| `RiotCommander` | 69 | 35 |
| `riot_commander` | 19 | 15 |

**About 77 percent of every "Riot" in this repo is NOMINATIVE** - it names Riot
Games the company, the Riot API, the Riot Live Client, Riot's developer policy.
Those references are legitimate, required, and **must survive**.

A blind `sed s/Riot/Amberstone/` would:

- rewrite `Riot Games` -> `Amberstone Games` (false attribution),
- break `Riot API` / `Riot Live Client` (wrong technical facts),
- and destroy the **legally required disclaimer**, which must literally read
  "... isn't endorsed by **Riot Games** ...".

So the sweep is pattern-scoped to the four PRODUCT-NAME forms above, never to
the bare token `Riot`. Every hit is reviewed, because product-name and
nominative uses sit in the same sentences constantly.

---

## 1. Tier 0 - BLOCKING and public-facing (do first, small, surgical)

| Target | Current | Action | Risk |
|---|---|---|---|
| GitHub repo | `Remus3/riot-commander` | rename to `Remus3/amberstone` | GitHub redirects the old URL, BUT see the updater row - they must move together |
| `rc-shell/electron-builder.yml:35-36` | `publish: owner Remus3 / repo riot-commander` | update in lockstep with the repo rename | **auto-update breaks for existing installs if these drift** |
| `rc-shell/electron-builder.yml:16` | `appId: com.riotcommander.rc-shell` | `com.amberstone.shell` | **BREAKING INSTALL IDENTITY.** Windows treats a new appId as a DIFFERENT application: existing installs will not upgrade, they will co-install alongside. Needs a migration decision before it is touched. |
| `rc-shell/electron-builder.yml:17` | `productName: Riot Commander Shell` | `Amberstone Shell` | installer + Start Menu + window title |
| `rc-shell/package.json:4` | description opens "Riot Commander Electron companion shell" | reword | cosmetic |
| Scheduled task | bare `RiotCommander` | rename or delete - it is ALREADY broken (races RC-Supervisor for `:8888` and loses, LastTaskResult=1, filed 2026-08-08c) | operator territory (system settings) |
| `docs/HEXCORE.html`, `docs/HEXCORE_offline.html` | Hextech / Hexcore naming | **RE-SCOPED OUT of Tier 0 - my "low risk" estimate was wrong when measured.** See section 1b. | was low, is not |
| Dashboard `<title>` + any UI-visible product string | "Riot Commander" | "Amberstone" | low, but needs the UI-fixture ritual if the page changes visually |
| **Disclaimer (ADD, does not exist today)** | - | "Amberstone isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties." Must be readily visible. | required by policy |

## 1a. What landed (2026-08-11)

- `rc-shell/electron-builder.yml`: `appId` -> `com.amberstone.shell`
  (operator-approved breaking change), `productName` -> `Amberstone Shell`.
- `rc-shell/package.json`: `description` and `author` -> Amberstone.
- `web/index.html`: `<title>` -> `Amberstone - Phase 3`.
- `README.md`: H1 -> `# Amberstone`; the non-endorsement disclaimer now reads
  "Amberstone is not endorsed by Riot Games ...".
- `tests/test_rename_amberstone_guard.py`: the section-5 guards, written RED
  first (8 failing), now 8 passed / 16 subtests.
- `tests/test_web_ascii_sweep.py`: `_LIVE_HALF_DIGEST` re-pinned for the
  `<title>` change, after confirming the superseded value reproduces byte for
  byte in a clean HEAD worktree.

## 1a-bis. Slug re-cased (2026-09-06)

Operator request: the GitHub repo is `Remus3/Amberstone`, not `Remus3/amberstone`.
The Tier-0 table above records the 2026-08-11 plan verbatim and is left as-is;
this note is the current truth. GitHub repo lookup is case-insensitive and the
old-casing URL still resolves, so nothing broke - but the same lockstep rule
applied anyway: `rc-shell/electron-builder.yml` `publish.repo`, the two README
CI badge URLs, `tools/ci_watchdog.py` `REPO`, and the HEXCORE repo lines all
moved in the same commit. `gh repo rename` rewrote `origin` in the shared
config, so all six lane worktrees follow automatically.

**STILL OPERATOR-GATED, and they must move together:**

1. `gh repo rename` on `Remus3/riot-commander` -> `amberstone`.
2. `rc-shell/electron-builder.yml` `publish.repo`, plus the two README CI badge
   URLs.

Both are deliberately left pointing at the old slug: electron-updater reads its
feed from `publish.repo`, so changing it before the repo rename lands would
break auto-update for any packaged install. The guard exempts exactly these two
shapes (`_GITHUB_URL_RE`, `_PUBLISH_SLUG_RE`) and carries a test that goes RED
once they are gone, so the exemption cannot outlive the thing it exempts.

## 1a-frozen. Frozen-file edits, OPERATOR-APPROVED 2026-08-11

Tier 1 touched four files on the CLAUDE.md frozen list. **The operator reviewed
the diff and approved keeping them.** 8 lines total, every one a user-visible
product-name string - which is precisely what the rename exists to change, so
leaving them would have kept the trademark in `--help` output and the log
banner:

| File | Lines | What |
|---|---|---|
| `main.py` | 3 | module docstring, `argparse` prog, startup log banner |
| `core/log_setup.py` | 2 | module docstring, logging-started banner |
| `core/game_snapshot.py` | 1 | docstring (`Authoritative mode container for ...`) |
| `ops/rc_dev_runtime.py` | 2 | docstrings |

No behaviour changed in any of them. `RIOT_COMMANDER_DEBUG` inside those same
files was deliberately SKIPPED by the sweep and is untouched.

This is the SECOND frozen-file approval this session; the first was
`core/game_snapshot.py` for the B7 forbidden-mode gate, which was functional.

## 1b. HEXCORE - re-scoped, my Tier-0 estimate was wrong

I filed the two `docs/HEXCORE*.html` files as a low-risk Tier-0 rename. Measured,
they are not: `HEXCORE` is referenced by `ops/loop/config.gate.json`,
`ops/loop/director_prompt.md`, `tests/test_hexcore_offline_dust.py` and
`tools/drift_guard.py`, plus the historical docs - and the pages carry ~50
internal `hexcore` identifiers each. That is a mini-sweep with a drift guard and
a loop config in it, not a two-file rename, so it is pulled out of Tier 0 into
its own item rather than half-done here.

Note the nominative trap applies to "Hextech" too, and harder: **Hextech Gunblade
and Hextech Rocketbelt are real League items the engine must model by name.** The
exposure is the two pages' OWN naming, not the token.

## 2. Tier 1 - repo and docs identity (bulk, non-breaking)

653 `Riot Commander` hits across 258 files: `.md` prose, docstrings, comments,
`README.md`, the `CLAUDE.md` header, `docs/**`.

Approach: generate a candidate list per file, review each hit in context, apply.
Do NOT batch-apply unreviewed - the nominative adjacency problem above.

Historical artifacts are a deliberate CARVE-OUT: `docs/LEDGER.md`,
`docs/history_notes.md`, `docs/ROADMAP_HISTORY.md` and `docs/_archive/**` are
append-only records of what was true at the time. Renaming inside them rewrites
history, which this repo forbids. Add a single dated note at the top of each
instead.

## 3. Tier 2 - filesystem and infrastructure (highest mechanical risk, do LAST)

The repo directory itself, `C:\Riot Commander`:

- 31 tracked files carry a `C:/Riot Commander` literal.
- **The real number is higher** - `.claude/settings.json`, `.mcp.json`, the
  Perseus vault wiring and the hooks are all GITIGNORED and invisible to
  `git grep`. Every one is an absolute path.
- All 24 `RC-*` scheduled tasks carry absolute action paths.
- `ops/runtime/health.json`, the `logs/` path, `restart.bat`, the git hooks
  (`core.hooksPath` is LOCAL config), and the Claude Code workspace-trust key in
  `~/.claude.json` - which is keyed per path STRING, so a directory rename
  silently drops trust and headless runs start discarding `permissions.allow`.
- Cert CN / SAN - regenerate via `tools/regen_rc_cert.ps1`.
- Tailscale MagicDNS `legion-rc` - a node rename.

**Recommendation: DEFER, possibly indefinitely.** The directory name is not
public. It carries the trademark but no outsider ever sees it, so it buys no
compliance while risking every absolute path in the system at once. If it is
done, it is its own session with a rollback plan, not a tail on the rename.

## 4. Tier 3 - the "RC" abbreviation (RECOMMENDATION: DO NOT)

24 scheduled tasks, `rc-shell`, `RC_GAME_HOST`, `RC_ORIGIN`, `RC2`,
`ops/runtime/`, health keys, and hundreds of identifiers across the tree.

**"RC" does not expose the trademark.** The policy bars Riot's marks; the
initials are not one. Renaming this is an enormous-blast-radius change for zero
compliance value, and it would touch frozen files.

The ONE exception: anywhere public-facing text EXPANDS "RC" to "Riot Commander",
that expansion is a Tier 1 hit and gets fixed.

## 5. Verification - the guard that stops both failure modes

Write this BEFORE the sweep, TDD:

1. **Under-fire guard:** zero occurrences of `Riot Commander`, `riot-commander`,
   `RiotCommander`, `riot_commander` outside the historical carve-out set.
2. **Over-fire guard, the one that matters:** assert nominative references
   SURVIVE - `Riot Games`, `Riot API`, `Riot Live Client` must still be present,
   and the disclaimer string must contain the literal words "Riot Games".
   A sweep that scores 100 percent on guard 1 by deleting guard 2's subjects has
   failed, and this is exactly what a blind find-replace does.
3. `python tools/drift_guard.py`, the full dual suite, and
   `tools/ds_share_sync.py --check`.

## 6. Suggested order

1. Operator decides the **appId migration** question (Tier 0) - it is the only
   irreversible-for-users step.
2. Write the guards (section 5).
3. Tier 0, all of it, one commit.
4. Tier 1 bulk prose, reviewed, one commit.
5. Re-run guards + suites + Share check.
6. Riot Developer Portal registration under the new name (operator).
7. Tier 2 only if and when it is worth a dedicated session.
