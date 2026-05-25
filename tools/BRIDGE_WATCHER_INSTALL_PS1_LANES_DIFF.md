# bridge_watcher_install.ps1 -EnableLanes parameter prep work

Item 189 Slice A (item 188 Slice G carry (j)) - the prep work owed before
`docs/AUTO_ACTION_LANES_GATE_PROBE.md` step (1) Game-PC enablement recipe
becomes invocable cleanly.

The recipe wants:

    .\bridge_watcher_install.ps1 -Node gamepc -EnableLanes read

But `tools/bridge_watcher_install.ps1:200` currently hardcodes the launch
args WITHOUT `--enable-auto-action-lanes`. This doc captures the exact
~5 LOC diff to thread the flag through. The file is FROZEN per CLAUDE.md
"Frozen files" hard rule, so the diff is staged here for operator review +
explicit grant before landing.

## Scope

NOT a behavior flip. Default `-EnableLanes ""` -> argument string is empty
-> `--enable-auto-action-lanes` is not appended -> daemon runs with
`enabled_lanes={}` -> auto-action stays OFF. Existing installs are
byte-identical post-patch.

Only when the operator explicitly passes `-EnableLanes read` (or
`-EnableLanes read,ops` after gate clearance) does the flag reach the
daemon's argparse at `tools/bridge_watcher.py:1083`.

## Phase 3 gate reminder

Per `docs/AUTO_ACTION_LANES_GATE_PROBE.md` verdict (item 188 Slice G):
the auto-action lanes ENABLE decision is DEFERRED until the bridge action
history accumulates N>=50 samples at >=95% success rate. Current state is
N=2 / 100% / 22 days zero cadence. This diff is PREP only - it does not
flip the gate.

## Diff (apply manually via Edit tool under explicit operator grant)

### Edit 1 of 2 - param block (file lines 24-33)

Old (lines 24-33):

    param(
        [ValidateSet("gamepc", "peer")]
        [string]$Node = "",
        [string]$InstallDir = "",
        [string]$BridgeUrl = "",
        [string]$LegionAgentBase = "https://legion-rc:8888/agent",
        [switch]$InstallHook,
        [switch]$DryRun,
        [switch]$Force
    )

New (lines 24-34, adds 1 line):

    param(
        [ValidateSet("gamepc", "peer")]
        [string]$Node = "",
        [string]$InstallDir = "",
        [string]$BridgeUrl = "",
        [string]$LegionAgentBase = "https://legion-rc:8888/agent",
        [ValidatePattern("^$|^(read|ops|read,ops|ops,read)$")]
        [string]$EnableLanes = "",
        [switch]$InstallHook,
        [switch]$DryRun,
        [switch]$Force
    )

The `ValidatePattern` ASCII regex restricts input to empty / read / ops /
either ordering of read,ops. This catches typos at parse time rather than
silently passing junk through to the daemon argparse.

### Edit 2 of 2 - task XML Arguments string (file lines 197-201)

Old (lines 197-201):

      <Actions Context="Author">
        <Exec>
          <Command>"$Pythonw"</Command>
          <Arguments>"$WatcherPath" --node $Node --bridge-url $BridgeUrl --data-dir "$InstallDir" --log-dir "$InstallDir\logs" --poll 15</Arguments>
        </Exec>

New (lines 197-202, adds 1 line + extends the Arguments line):

      <Actions Context="Author">
        <Exec>
          <Command>"$Pythonw"</Command>
          $(if ($EnableLanes) { "<Arguments>`"$WatcherPath`" --node $Node --bridge-url $BridgeUrl --data-dir `"$InstallDir`" --log-dir `"$InstallDir\logs`" --poll 15 --enable-auto-action-lanes $EnableLanes</Arguments>" } else { "<Arguments>`"$WatcherPath`" --node $Node --bridge-url $BridgeUrl --data-dir `"$InstallDir`" --log-dir `"$InstallDir\logs`" --poll 15</Arguments>" })
        </Exec>

The here-string interpolates conditionally so default-empty `-EnableLanes`
produces the byte-identical Arguments line; only an explicit non-empty
value triggers the extended form. The backtick-escaped double-quotes
inside the conditional keep the embedded XML quotes intact when PowerShell
evaluates the expression inside the here-string.

## Combined diff line count

- Edit 1: +2 lines (ValidatePattern attribute + EnableLanes declaration)
- Edit 2: +1 line (the conditional wraps existing Arguments line into
  an if/else that produces either the old or extended form)

Net: 3 new content lines + ~2 reformat lines = ~5 LOC as stated in
item 188 Slice G carry (j).

## Verification plan after operator applies the diff

1. `Test-Path tools/bridge_watcher_install.ps1` still true.
2. `pwsh -NoProfile -Command "& { . tools/bridge_watcher_install.ps1 -DryRun -Node gamepc -EnableLanes read }"`
   should print the dry-run line `[dry-run] would: schtasks /Create ...`
   without erroring on the new parameter.
3. `pwsh -NoProfile -Command "& { . tools/bridge_watcher_install.ps1 -DryRun -Node gamepc -EnableLanes garbage }"`
   should fail parameter validation with the ValidatePattern error.
4. Run `py -m pytest tests/test_bridge_watcher_install_lanes_diff.py -v`
   - the drift guard reads BOTH this doc + the live install.ps1 + the
   live bridge_watcher.py argparse to confirm the prep work is consistent.
5. After the diff lands + Phase 3 gate clears, dispatch step (1) from
   `docs/AUTO_ACTION_LANES_GATE_PROBE.md` to re-register the Game-PC
   scheduled task via the bridge.

## Rollback

If the diff causes Windows PowerShell 5.1 parser regression on Game-PC or
Peer, revert by re-writing the two edit hunks to their old form. The
operator's existing `RC-BridgeWatcher-<Node>` scheduled tasks are
unaffected (the diff only changes future re-installs; running daemons
continue from their already-registered Arguments string).

## Cross-reference

- Carry source: CLAUDE.md item 188 paragraph (j) "NEW carry:
  `tools/bridge_watcher_install.ps1` -EnableLanes param (~5 LOC) prep
  work owed before Slice G recipe invocation."
- Live recipe: `docs/AUTO_ACTION_LANES_GATE_PROBE.md` step (1) Game-PC
  enablement.
- Flag consumer: `tools/bridge_watcher.py:1083` argparse +
  `tools/bridge_watcher.py:1148` populates `enabled_lanes: set`.
- Frozen-file list: CLAUDE.md "Hard rules" -> "Frozen files".
