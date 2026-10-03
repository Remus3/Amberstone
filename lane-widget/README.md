# lane-widget

A small, frameless, always-on-top Electron panel that shows which headless
lane / worker runs are live right now, across every repository in the local
participant roster - RC included.

It is a **strictly read-only observer**. It opens files for reading and it
never writes, locks, unlinks or reaps anything under `ops/loop/control` in any
repository, including RC's own. There is no reclaim button, no kill button, and
no code path that mutates another repo's state.

## What it reads

Per repository in the roster, a bounded and explicitly named set of paths - no
recursion, no directory walk, no `rglob`:

- `<root>/ops/loop/control/lanes/0.lock` - the single lane slot. There is at
  most one lane per repo, and the lane NAME is a field inside that one lock
  rather than a per-lane filename.
- `<root>/ops/loop/control/RUNNING.lock` - the controller lock.
- A **non-recursive listing** of `<root>/ops/loop/reports` for the log
  heartbeat. Only filenames and mtimes are used; the logs are legitimately
  mixed UTF-8 / UTF-16LE and are never decoded.
- `<root>/ops/loop/control/inbox_status.json` - that tree's inbox responder
  status (schema 1), read once per slow tick and never written. It feeds the
  row's `Sync:` line, e.g. `Sync: Appending Ledger [35m/42m][25/120]`. An
  absent, unparseable or stale file (older than 2x the tree's tick) renders
  `Sync: no signal [<age>]`, never the numbers it still carries.
- One **machine-wide process snapshot**, taken once per slow tick and reused
  for every repository, to count the descendants of each live lock pid.

## The ALL tab

One row per repository, in the fixed order the roster's `order` field gives,
including a repository with no live lane or no checkout on this host. Each row
is the display name, a state word, ONE combined `Lane:` line (lane and
controller together - `Lane: <name> 12m`, `Lane: free`,
`Lane: STALE (reclaimable)`) and ONE `Sync:` line. The per-repo tabs keep the
lane / controller cards. Display names and order come from the optional
`roster` key of the gitignored roster file (see the tracked example).

Liveness is decided by a **pid probe plus a start-time stranger guard**, never
by file existence. A lock file whose pid is dead renders as stale
(RECLAIMABLE), and a lock whose pid has been reused by an unrelated process
renders as stale too. This is the single most important correctness property
in the widget: RC carries stale lock files with dead pids as a normal
condition, and anything that trusted file existence would render phantom
running lanes.

The roster itself comes from the per-host, gitignored `ops/moon_sync_repos.json`
(schema in the tracked `ops/moon_sync_repos.example.json`), or from the
`RC_MOON_SYNC_REPOS` environment override. Repositories are labelled by their
short participant CODE, or by a display name set in that same gitignored file -
never by a directory name. A missing or corrupt
roster file is the correct fresh-clone answer and yields RC alone, not an error.

## What it deliberately does NOT read

- `C:\ProgramData\lw-loop\slots` - **not an inventory.** It is held only for the
  moment around each executor call and its payload carries no lane field, so it
  is empty in normal operation and could not identify a lane even when it is
  not.
- **Named mutexes** - they carry no lane identity and cannot be enumerated at
  all on Windows.
- **Log contents.** Only mtimes are stat'ed. There is no log tailing in v1, and
  adding one would walk straight into the mixed-encoding trap above.

## Running it

Tests - Node's builtin runner, zero npm dependencies, no `npm install` needed:

```
cd lane-widget
npm test
```

The app, on RC's already-vendored Electron binary (no second Electron install):

```
"C:\Riot Commander\rc-shell\node_modules\electron\dist\electron.exe" "C:\Riot Commander\lane-widget"
```

It holds its own single-instance lock, so a second launch focuses the existing
window instead of opening another one. Closing the window sends it to the tray;
only tray Exit quits.

## Desktop shortcut

`tools/install_lane_widget_shortcut.ps1` creates, refreshes or removes a
"Lane Monitor" shortcut on the Desktop. It supports `-DryRun` (echo exactly
what it would write, touch nothing) and `-Uninstall` (remove it, silent when
already absent), and it pre-flight-refuses rather than producing a shortcut
that cannot launch.

**That script is operator-run, never session-run.** It writes outside the
repository root, which is a standing halt-and-ping point here, so a Claude
session authors it and stops.
