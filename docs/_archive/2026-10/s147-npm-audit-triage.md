# rc-shell npm audit triage, 2026-10-31 (session 147, hand-off items NA7 + s146-b)

Measured with `npm audit --json` in rc-shell at HEAD f9e6a7c25 (lock last changed
in 537b72710; npm 11.12.1, node 24.15.0): 15 moderate, 0 low / high / critical. Every finding traces to ONE
advisory, GHSA-g3hv-75wg-m249 (CVE-2026-118764, CWE-405, minimatch globParts
amplification DoS; vulnerable < 11.0.1, first patched 11.0.1, published
2026-10-30). The other 14 are transitive "depends on vulnerable versions" rows.

All 15 are DEV-ONLY: every node carries `dev: true` in the lock and sits under the
electron-builder packaging toolchain (devDependency). The one runtime dependency,
electron-updater, is not in any chain, so none of this ships in the packaged app.
The DoS needs an attacker-controlled glob pattern; electron-builder's patterns
come from our own electron-builder.yml.

In-range fix check (scratch copy of package.json + package-lock.json, never the
live rc-shell node_modules): `npm audit fix --package-lock-only --ignore-scripts`
rewrote the lock (electron-builder family 26.18.0 -> 26.18.1, builder-util
26.16.0 -> 26.18.1, node-abi, tslib, @peculiar/*) and the re-audit still read 15
moderate. No lock-only in-range bump resolves any finding, so no lock change is
committed. That churn is unrelated to the advisory (26.18.1 is on dist-tag v26,
not latest) and stays with the normal Dependabot version-update cadence.

npm's only offered fix for 10 of the 15 is electron-builder 20.23.1: a six-major
DOWNGRADE that predates Electron 45 support. Rejected. The other 5 rows npm marks
`fixAvailable: true` resolved to nothing in the measured lock-only run.

Upstream state on 2026-10-31: minimatch has no backport to the 3.x / 5.x / 9.x /
10.x lines (11.0.0 - 11.0.3 published 2026-10-27/28 only). Even the newest majors
of the chain stay below 11: @electron/asar 4.3.1 (^10.0.1), dir-compare 5.0.0
(^3.0.5), filelist 2.0.2 (^10.2.1), app-builder-lib 26.18.1 (^10.2.5, pins asar
3.4.1 and universal 2.0.3 exactly). Only glob 14.0.3 moved (^11.0.2).

## Dependabot alert 144 decision: DECLINE (no change applied)

- alert 144: minimatch, manifest rc-shell/package-lock.json, transitive, scope development, severity medium, range < 11.0.1, patched 11.0.1; no open Dependabot PR (gh pr list --author app/dependabot: empty).
- why decline: the patched 11.0.1 fits none of the six parent ranges (^3.0.4, ^3.0.5, ^3.1.1, ^5.0.1, ^9.0.3, ^10.2.5), so the only routes are a forced cross-major `overrides` (3.x callers such as @electron/asar call `require("minimatch").default` via __importDefault; the 10.2.6 and 11.0.3 CommonJS builds have no default export (measured), so forcing 11 onto the 3.x callers breaks @electron/asar, dir-compare, glob 7) or the electron-builder 20.23.1 downgrade. Both rejected for a dev-only, non-shipped, non-attacker-reachable DoS.
- dependabot.yml: NOT widened. There is no bot PR to decline, version updates never target transitive minimatch, and an ignore entry would also suppress the security-update PR wanted once upstream moves.
- remote acts NOT taken (session constraint): no alert dismissal. If dismissed later, the reason is tolerable_risk: dev-only build toolchain, no in-range patch.
- Reverses if: app-builder-lib (electron-builder) ships a release whose minimatch, @electron/asar, @electron/universal, dir-compare and filelist chains all resolve to minimatch >= 11.0.1, or minimatch backports the fix to 3.x / 5.x / 9.x / 10.x. Then re-run `npm audit` and apply as a lock-only bump.

## The 15 findings (package locked-version: via-chain -> classification)

- minimatch 3.1.5 x3, 5.1.9, 9.0.9, 10.2.6: ROOT advisory GHSA-g3hv-75wg-m249 -> dev-only; needs a major bump (11.x), no in-range fix.
- @electron/asar 3.4.1: via glob, minimatch ^3.0.4 -> dev-only; needs a major bump (pinned exactly by app-builder-lib; asar 4.3.1 still on minimatch 10).
- @electron/universal 2.0.3: via @electron/asar, dir-compare, minimatch ^9.0.3 -> dev-only; needs a major bump (pinned exactly by app-builder-lib).
- app-builder-lib 26.18.0: via @electron/asar, @electron/universal, dmg-builder, ejs, electron-builder-squirrel-windows, minimatch ^10.2.5 -> dev-only; no fix available (26.18.1 measured still vulnerable).
- dir-compare 4.2.0: via minimatch ^3.0.5 -> dev-only; no fix available (5.0.0 still minimatch ^3.0.5).
- dmg-builder 26.18.0: via app-builder-lib -> dev-only; no fix available (follows app-builder-lib).
- ejs 3.1.10: via jake -> dev-only; needs a major bump (app-builder-lib asks ^3.1.8; ejs latest 7.0.2).
- electron-builder 26.18.0 (direct devDependency): via app-builder-lib, dmg-builder -> dev-only; no fix available (npm offers only the 20.23.1 major downgrade).
- electron-builder-squirrel-windows 26.18.0: via app-builder-lib, electron-winstaller -> dev-only; no fix available (npm fixAvailable true, measured lock-only fix 15 -> 15).
- electron-winstaller 5.4.0: via @electron/asar, temp -> dev-only; no fix available (pinned exactly by squirrel-windows; 5.4.4 keeps asar ^3.2.1 and temp ^0.9.0).
- filelist 1.0.6: via minimatch ^5.0.1 -> dev-only; needs a major bump (jake asks ^1.0.4; filelist 2.0.2 still minimatch 10).
- glob 7.2.3: via minimatch ^3.1.1 -> dev-only; needs a major bump (glob 14 is the first on minimatch 11; parents ask ^7.1.3 / ^7.1.6).
- jake 10.9.4: via filelist -> dev-only; needs a major bump (ejs asks ^10.8.5).
- rimraf 2.6.3: via glob -> dev-only; needs a major bump (temp asks ~2.6.2).
- temp 0.9.4: via rimraf -> dev-only; no fix available (0.9.4 is temp's latest release).

Count before: 15 moderate. Count after: 15 moderate (no lock change committed).
