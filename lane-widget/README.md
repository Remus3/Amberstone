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

- `<root>/ops/loop/control/lanes/0.lock`, `1.lock` and `2.lock` - the lane
  slots (FLEET-KIT v6, `fleet_lanes.LANE_CAP_MAX = 3`). A repo runs up to three
  lanes at once, one lock per lane INDEX; the lane NAME is a field inside the
  lock, never the filename, so any roster lane can sit at any index. The three
  are read by NAME every fast tick - the `lanes` directory is never listed.
- `<root>/ops/loop/control/progress/lane-<i>.json` - read ONLY for a lane
  whose lock is live (FLEET-KIT v7, FLEET-COMMON item 13 d), one named file per
  live lane, never for a free or stale one. Its `checklist` field is that lane
  fire's REMAINING tasks, in order.
- `<root>/ops/loop/control/RUNNING.lock` - the controller lock.
- A **non-recursive listing** of `<root>/ops/loop/reports` for the log
  heartbeat. Only filenames and mtimes are used; the logs are legitimately
  mixed UTF-8 / UTF-16LE and are never decoded.
- `<root>/ops/loop/control/inbox_status.json` - that tree's inbox responder
  status (schema 1), read once per slow tick and never written. It feeds the
  row's `Sync:` line, e.g. `Sync: Appending Ledger [35m/42m][25/120]`. An
  absent, unparseable or stale file (older than 2x the tree's tick) renders
  `Sync: no signal [<age>]`, never the numbers it still carries.
- The account proxy's **state file**, if the gitignored roster's optional
  `accounts` key names one: ONE stat (its mtime is the freshness signal) plus
  ONE read per slow tick, never written. It feeds the ACCOUNTS strip.
- One **machine-wide process snapshot**, taken once per slow tick and reused
  for every repository, to count the descendants of each live lock pid.

Once per slow tick, machine-wide (not per repository), for the GOVERNOR strip:

- `%ProgramData%\lw-loop\slots\0.lock`, `1.lock`, `2.lock` - the three shared
  governor slots, read by NAME (plus one stat of a slot whose bytes do not
  parse, which `fleet_lanes` judges by mtime). The slot root is never listed.
- ONE **non-recursive listing** of its sibling `%ProgramData%\lw-loop\queue`
  and one read per `*.ticket` in it (at most 32) - the fair-queue waiters.
- No `ProgramData` in the environment means no reads and no strip.

## The ALL tab

One row per repository, in the fixed order the roster's `order` field gives,
including a repository with no live lane or no checkout on this host. Each row
is the display name, a state word, ONE line per lane index and ONE `Sync:`
line:

```
queue (lane 0) 12m
  [ ] C2: Run the suite (builder running, ~4m)
  [ ] C3: Commit the adoption
  +2 more
Lane 1: free
Lane 2: STALE (reclaimable)
```

A LIVE lane shows its NAME (from the lock payload), its index and age, then
its remaining checklist items from `progress/lane-<i>.json`, one short line
each, capped at 3 and then `+N more`. With no progress file or no `checklist`
field it reads `<name> (lane i) <age> - no checklist`; when the file's
`updated` is older than 2x its `eta_s` (an undatable stamp or a missing
`eta_s` counts as older; `eta_s` 0 gets a 30 s floor) it reads
`- checklist STALE` and NO items - a stale list is never shown as live. A free
lane shows `free`, a dead or pid-reused lock `STALE (reclaimable)`. The
controller lock folds into lane 0 only when every lane is free
(`Lane 0: controller 15m`). The per-repo tabs keep one card per lane index plus
the controller card. Display names and order come from the optional `roster`
key of the gitignored roster file (see the tracked example).

Under the ACCOUNTS strip sits ONE **GOVERNOR strip** (`src/governor.js`) for
the whole machine: `Governor 2/3 - RC, CS - queue 1` - slots held out of three,
the repos holding them in slot order, and the live queue depth, with
`- N stale` (alarm-styled) when a slot is reclaimable. Slot liveness mirrors
`fleet_lanes`: pid or executor child alive and not a start-time stranger,
never past twice the stale window. A slot's `repo` field may be a checkout
PATH (RC's controller passes its root); it is mapped to its roster code, and
anything that is neither a roster root nor a bare code renders as `?` - a path
never reaches the screen.

Above the rows sits ONE **ACCOUNTS strip** (`src/accounts.js`): one line per
proxy account, labelled by ROLE from the roster's `accounts.roles`, never by
email or uuid:

```
Headless     5h 23% (resets 2h10m)   7d 7% (resets 3d4h)   allowed
Interactive  no data - not signed in to the proxy
```

Percent is round(fraction x 100); resets read m under 120m, then h with m,
then d+h. A status other than `allowed` is alarm-styled. A state file older
than 2x the probe interval, absent or unparseable renders
`Accounts: no signal [<age>]`. Identifiers are used only to match an entry to
its role and are dropped before the model leaves `src/accounts.js`.

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

- A **listing** of the governor slot root, or any slot beyond `0..2.lock`. The
  slots are read by name for the GOVERNOR strip only; they are held just for
  the moment around each executor call and carry no lane field, so they are
  never used to identify a lane - the lane locks do that.
- A **listing** of `ops/loop/control/lanes` or `ops/loop/control/progress`.
  Both are read by exact filename only.
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
"<repo>\rc-shell\node_modules\electron\dist\electron.exe" "<repo>\lane-widget"
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
