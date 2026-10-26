"""PKG-2 backend updater: live updates for an installed backend, verified first.

docs/PACKAGING_PLAN.md section 3.4 (release channel) and M8. The launcher
(PKG-6) calls this module; it never runs at boot and registers nothing: it
acts only when the running app asks it to.

API (each step is separate so the shell can show progress and defer):

    check(source, channel, current_version)  -> newest newer Release | None
    stage(root, source, release, ...)        -> StagedUpdate   (verified)
    verify_staged(root, version)             -> StagedUpdate   (re-verified)
    plan_apply(root, staged)                 -> ApplyPlan      (what + restart)
    apply(root, version, ...)                -> ApplyResult    (signed request)
    finish(root)                             -> FinishResult   (collect result)
    rollback(root, ...)                      -> ApplyResult    (redeploy backup)
    recover(root)                            -> dict  (app down after an update)
    classify_paths(paths)                    -> RestartPlan    ("needs restart?")
    game_live(root)                          -> reason | None
    app_health(root)                         -> {alive, run_id, age_s}

Sources: LocalSource(dir) reads backend-<ver>.json + backend-<ver>.zip from a
folder (a PKG-4 build output, or the operator's local channel); GitHubSource
reads the same two assets from a GitHub Release through an injectable
`fetch(url, max_bytes)` (default https_get), so tests never touch a network.
Channels mirror the shell (rc-shell/src/update_channel.js): `stable` rides
full releases only, `dev` also rides prereleases; drafts are never offered.

INTEGRITY MODEL (fail closed at every step; any violation refuses the WHOLE
update and leaves nothing staged):
  1. Optional pin: the caller may pin the manifest's sha256 (pin_sha256).
     Without one the manifest is trusted as far as its transport (a local
     folder, or HTTPS from the repo's own Release - the shell's
     electron-updater trust model, PACKAGING_PLAN S4: no code signing yet).
  2. Manifest schema check (parse_manifest): schema 1, kind, semver version,
     channel, archive {name, sha256, size}, files [{path, sha256, size}],
     optional min_shell_version; case-insensitive duplicates refused.
  3. Every path passes check_payload_path: a relative POSIX path under an
     allow-listed top-level entry, never runtime state (ops/runtime, logs,
     backups, keys, local host config, coaching data, jsonl / log files),
     never a per-install secret (token files, .env, certs / tls dirs,
     pem / key / pfx / p12), never dev-only trees (tests, docs, ops/loop,
     ops/fleet_kit, .git), no drive, root, `..`, reserved device name, 8.3
     short-name segment (`~1`) or Windows-illegal character. Deny wins over
     allow. Then the INSTALL's own shipped .gitignore files decide with
     `git check-ignore` semantics (IgnoreRules): an ignored path is
     per-install or runtime state and refuses the update; an install that
     ships no .gitignore refuses every update.
  4. The archive's size and sha256 match the manifest BEFORE it is opened.
  5. Archive members equal the manifest file set exactly; symlinks, special
     files, encrypted members and size mismatches are refused; every file is
     hashed while it is written and must match.
  6. Staging is atomic: extract into ops/runtime/staging/.partial-*, then one
     directory rename to ops/runtime/staging/<ver>; a failed stage removes
     its partial and keeps any previous staging untouched.
  7. apply() re-verifies the staging (verify_staged: a file changed, added or
     removed after staging = dirty = refused), re-checks the ignore list,
     refuses any path that RESOLVES elsewhere (live_alias: an 8.3 short
     name, junction or symlink), and refuses to overwrite a live file no
     installed release owns - with no ownership baseline at all it may only
     create files that do not exist yet. Then it writes a deploy request
     SIGNED with the per-install key (HMAC-SHA256 over the canonical JSON,
     byte-compatible with ops/rc_transactional_deploy.py `_canonical` /
     `sign_request` / `verify_request`; key ops/runtime/deploy_request.key).
     No key = refused (the host's first-run provisioning creates it with
     `ensure_key`). The signed body carries a unique request_id, a validity
     window (issued_at .. expires_at, REQUEST_TTL_S) and the sha256 of every
     staged file.
  8. The worker verifies the signature, the window, and claims the id once
     in its used-id ledger (a replay is refused), checks every staged file
     against its signed sha256 before anything is touched, and copies from
     the very bytes it hashed (copy_verified), so a staged file swapped
     after signing never deploys; then backup + compile + heartbeat +
     rollback as before. finish() records the result; rollback()
     re-deploys the worker's backup, each file checked against the sha256
     recorded before the update, and moves files the update CREATED into
     ops/runtime/launcher/quarantine/ (moved, never deleted).

LIVE GAME: apply() and rollback() raise GameLiveError while a game is live,
before any write. The frozen supervisor does NOT defer deploys itself: it
starts one whenever the app is healthy (ops/rc_supervisor.py:1421), so the
deferral lives here. Signals mirrored from RC (stdlib only; tests pin the
mirrors against the source): a running game process (core/hot_reload.py:170
GAME_PROCESS_NAMES, the same scan hot_reload's own deferral uses at
core/hot_reload.py:608), or a FRESH ops/runtime/health.json carrying any of
core/live_game_gate.py:31 LIVE_GAME_FLAGS. A failed process scan defers
(an update can wait; a mid-game restart cannot be undone).

RESTART CLASSIFIER (classify_path / classify_paths). Per changed file, an
effect on the main app process (main.py) plus the out-of-process services
whose own code changed; the plan level is the worst of them:
  none        web/ assets: ADR-008 reloads every open page through the asset
              hash (dashboard/_static.py:36 asset_fileset, polled via
              /api/ui-version); docs, tests and licences are not loaded.
  hot_reload  a .py core/hot_reload.py watches (its _should_watch,
              core/hot_reload.py:249 over _WATCH_DIRS :158, _SKIP_DIRS :118,
              frozen set :94): the watcher started by web_dashboard.py:60
              writes restart_trigger.txt itself when a module main.py LOADED
              changes (core/hot_reload.py:582 tick), held while a game is live
              (:608). The watcher only fires on an mtime newer than it knew
              (core/hot_reload.py:590); the worker's copy_verified writes a
              fresh file (no copystat), so every deployed file carries the
              deploy time. If the watcher is halted (ops/runtime/hot_reload_halt.txt,
              core/hot_reload.py:692) or not watching (ops/runtime/
              hot_reload.json, :693), hot_reload escalates to restart.
  restart     frozen core (never watched), a .py outside the watch dirs
              (coaches/, modes/, lcu/, app/, ...), data / config, and a
              dependency change: a SUPERVISED restart of main.py. The request
              sets force_restart; the worker then drops a `restart` request
              (ops/rc_transactional_deploy.py:631) that the supervisor handles
              at ops/rc_supervisor.py:1302 (restart_app, :1010). The same
              loop also honours restart_trigger.txt (ops/rc_supervisor.py:1663).
  relaunch    code of a process the supervisor's restart never reaches:
              restart_app restarts main.py only (ops/rc_supervisor.py:1010).
              `services` names what must restart: supervisor (its script, its
              config, and the modules it imports at ops/rc_supervisor.py:1490
              - :1492), lcu_agent / liveclient_relay / hotkey_listener /
              phase3_supervisor (ops/launcher/services.json), vision (:8889,
              vision_server/ + moon_vision_server.py, respawned by
              dashboard/_vision_watchdog.py), ds (:8860), app (the service
              host itself, or a dependency change: every Python process) and
              shell (rc-shell/, electron-updater on quit). PKG-6 restarts
              those services when no game is live.
  stale_check is set when a shared .py changed: out-of-process services may
  import it too (vision imports core/), so the host's import-chain staleness
  check (PACKAGING_PLAN 3.4) must run for them.

Not here: the linked-checkout channel. A root with .git is a dev checkout;
its edits reach RC through git + core/hot_reload.py + ADR-008, so stage(),
apply() and rollback() refuse it (classify_paths still answers for it).

Stdlib only: it runs under the launcher's `-I` interpreter with no RC module
on sys.path (same contract as ops/launcher/service_host.py).
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
DEFAULT_ROOT = HERE.parent.parent

SCHEMA = 1
KIND = "amberstone-backend"
CHANNELS = ("stable", "dev")
LEVELS = ("none", "hot_reload", "restart", "relaunch")
APP_EFFECTS = ("none", "hot_reload", "restart")
INSTALLED_MANIFEST = "backend-manifest.json"   # shipped at the bundle root (PKG-4)

# The release feed. Must equal rc-shell/electron-builder.yml `publish`
# (a test pins it), or the backend and the shell would read different feeds.
DEFAULT_GITHUB_OWNER = "Remus3"
DEFAULT_GITHUB_REPO = "Amberstone"
GITHUB_API = "https://api.github.com"
GITHUB_HOSTS = frozenset({"api.github.com", "github.com",
                          "objects.githubusercontent.com",
                          "release-assets.githubusercontent.com"})

MAX_MANIFEST_BYTES = 8 << 20
MAX_ARCHIVE_BYTES = 1 << 30
MAX_FILE_BYTES = 256 << 20
MAX_TOTAL_BYTES = 2 << 30
MAX_FILES = 50000
MAX_PATH_CHARS = 240
CHUNK = 1 << 20
HEALTH_FRESH_S = 30.0      # an older health.json is no evidence of a game
HEALTH_TIMEOUT_S = 30.0    # the worker's post-copy heartbeat wait
# Signed validity window of a deploy request. The worker refuses a request
# outside it and caps any window at its MAX_TTL_S (3600 s); the supervisor
# starts a queued deploy only once the app is healthy (ops/rc_supervisor.py
# :1421), so an expired request fails `auth` and the launcher re-applies.
REQUEST_TTL_S = 1800.0
# A request that vanished with no result: the supervisor removes the
# .deploying file even when it kills a worker at 120 s
# (ops/rc_supervisor.py:1462, :1475), so after this long it is reported lost.
LOST_AFTER_S = 600.0

_VERSION = (r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
            r"(?:-[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)?")
VERSION_RE = re.compile(rf"^{_VERSION}$")
MANIFEST_NAME_RE = re.compile(rf"^backend-({_VERSION})\.json$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_SLUG_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")

# ---- mirrors of RC constants (stdlib-only module: no import of core/).
# tests/test_launcher_updater.py pins each one against its source.

# core/hot_reload.py:94 _FROZEN_PATHS
FROZEN_PATHS = frozenset({
    "main.py", "core/log_setup.py", "core/moon_proxy.py", "lcu/lcu_client.py",
    "core/game_snapshot.py", "ops/rc_dev_runtime.py", "ops/rc_supervisor.py",
    "app/__init__.py", "app/_loop.py", "app/_health_monitor.py",
    "app/_remediation.py", "app/_state_authority.py",
    "app/_overlay_manager.py", "app/_game_lifecycle.py",
})
# core/hot_reload.py:158 _WATCH_DIRS ("" = repo-root files only)
HOT_RELOAD_WATCH_DIRS = ("agents", "core", "dashboard", "ops", "tools", "")
# core/hot_reload.py:118 _SKIP_DIRS
HOT_RELOAD_SKIP_DIRS = (".git", "__pycache__", "logs", "docs/_archive", "data",
                        "web", "node_modules", "ops/runtime", ".claude",
                        "moon_sync_inbox", "tests", "ops/loop/control")
# core/hot_reload.py:170 GAME_PROCESS_NAMES
GAME_PROCESS_NAMES = frozenset({"league of legends.exe",
                                "tftclient-win64-shipping.exe"})
# core/live_game_gate.py:31 LIVE_GAME_FLAGS
LIVE_GAME_FLAGS = ("has_game", "aram_mode", "arena_mode", "tft_mode",
                   "brawl_mode")

# ---- payload allow-list (state never travels in a payload, PACKAGING_PLAN 3.4)

PAYLOAD_DIRS = frozenset({
    "agents", "app", "assets", "coach_integration", "coaches", "config",
    "core", "dashboard", "data", "game_reader", "lcu", "lib", "LICENSES",
    "modes", "modules", "ops", "tft", "tools", "vision_server", "web",
})
PAYLOAD_ROOT_FILES = frozenset({
    "main.py", "web_dashboard.py", "moon_vision_server.py",
    "champion_profiles.py", "composition_advisor.py", "item_advisor.py",
    "overlay.py", "performance_tracker.py", "role_profiles.py",
    "requirements.txt", "LICENSE", "NOTICE",
})
# Deny wins over allow. Every per-install secret and runtime path is named
# here explicitly (they are also gitignored; the shipped .gitignore is the
# second, wider net - IgnoreRules below).
DENY_PREFIXES = ("ops/runtime/", "ops/backups/", "ops/loop/", "ops/fleet_kit/",
                 "ops/tls/", "data/recordings/", "data/spend/", "data/tft/",
                 "data/tft_matches/", "data/game_data/")
DENY_PATHS = frozenset({
    # per-install bearer tokens (.gitignore: config/vision_token.txt,
    # config/mission_control_token.txt, tools/mcp_token.txt; core/vision_token
    # also reads tools/vision_token.txt)
    "config/vision_token.txt", "config/mission_control_token.txt",
    "tools/mcp_token.txt", "tools/vision_token.txt",
    # per-host config (CLAUDE.md: never in a tracked file)
    "ops/local_hosts.json", "ops/moon_sync_repos.json", "ops/local_paths.json",
    "ops/install_startup.bat", "restart_trigger.txt",
})
DENY_SEGMENTS = frozenset({".git", ".claude", "tests", "__pycache__",
                           "node_modules", "moon_sync_inbox", "tls", "certs", "cert"})
# `.gitignore` / `.gitattributes` / `.gitmodules` never travel: a payload
# `.gitignore` (`!*`) would re-include every ignored path for the NEXT
# update's IgnoreRules check, so the rules only ever come from the installed
# bundle. `.gitkeep` placeholders are plain files and still travel.
_DENY_NAME_RE = re.compile(
    r"(^\.git(ignore|attributes|modules)$)"
    r"|(^api-key.*\.txt$)|(^\.env(\..*)?$)|((^|[._-])token\.txt$)"
    r"|(\.(pem|key|pfx|p12|jks|crt|salt|pyc|pyo|jsonl|log|tmp|partial|deploying)$)"
    r"|(_coaching_data\.json$)", re.I)
# An 8.3 short-name segment (`FLEET_~1`) can alias a denied directory on a
# volume that generates short names; no tracked path has one.
_SHORT_NAME_RE = re.compile(r"~[0-9]")
_RESERVED = frozenset({"con", "prn", "aux", "nul", "conin$", "conout$"}
                      | {f"com{i}" for i in range(1, 10)}
                      | {f"lpt{i}" for i in range(1, 10)})
_BAD_CHARS = frozenset('\\:*?"<>|')

# ---- restart classifier tables

ALL_SERVICE_NAMES = ("app", "shell", "supervisor", "lcu_agent",
                     "liveclient_relay", "hotkey_listener", "phase3_supervisor",
                     "vision", "ds")
_SERVICE_FILES = {
    # the supervisor process: its script, its config (the launcher derives
    # the per-install config from it, service_host.py:433) and the modules
    # it imports (ops/rc_supervisor.py:1490-1492)
    "ops/rc_supervisor.py": "supervisor",
    "ops/rc_config.json": "supervisor",
    "ops/rc_incident_log.py": "supervisor",
    "ops/rc_state_validator.py": "supervisor",
    "ops/rc_self_monitor.py": "supervisor",
    "tools/lcu_agent.py": "lcu_agent",
    "tools/liveclient_relay.py": "liveclient_relay",
    "tools/hotkey_listener.py": "hotkey_listener",
    "agents/supervisor.py": "phase3_supervisor",
    "moon_vision_server.py": "vision",
    "requirements.txt": "app",
    "requirements.in": "app",
}
_SERVICE_PREFIXES = (
    ("ops/launcher/", "app"),
    ("vision_server/", "vision"),
    ("agents/daemon_slayer/", "ds"),
    ("data/daemon_slayer/", "ds"),
    ("rc-shell/", "shell"),
)
_SERVICE_PATTERNS = (
    (re.compile(r"^agents/_supervisor_[^/]+\.py$"), "phase3_supervisor"),
    (re.compile(r"^agents/agent[0-9]+_[^/]+/"), "phase3_supervisor"),
)
# Code main.py never imports (grep 2026-10-26: vision_server is imported
# only by moon_vision_server.py; nothing imports moon_vision_server,
# ops.launcher or ops/rc_supervisor.py, the supervisor's own script).
_MAIN_NEVER_PREFIXES = ("ops/launcher/", "vision_server/", "rc-shell/")
_MAIN_NEVER_FILES = frozenset({"ops/rc_supervisor.py", "moon_vision_server.py"})
_NOT_RUNTIME_DIRS = frozenset({"docs", ".github", ".githooks", "LICENSES"})

MECHANISMS = {
    "none": "no restart: web assets reload open pages through the ADR-008 "
            "asset hash; everything else changed is not loaded at runtime",
    "hot_reload": "core/hot_reload.py restarts main.py when a module it loaded "
                  "changes (restart_trigger.txt, held while a game is live)",
    "restart": "supervised main.py restart: the deploy request sets "
               "force_restart and the supervisor handles the restart request",
    "relaunch": "the named services must be restarted by the service host "
                "(or the app relaunched) when no game is live; the "
                "supervisor's restart reaches main.py only",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ errors


class UpdateError(Exception):
    """Base of every refusal. `code` is stable; match on it, never the text."""
    code = "update"


class ManifestError(UpdateError):
    code = "manifest"


class PayloadPathError(UpdateError):
    code = "path"


class IntegrityError(UpdateError):
    code = "integrity"


class GameLiveError(UpdateError):
    code = "game_live"


class DeployKeyError(UpdateError):
    code = "auth"


class StateError(UpdateError):
    code = "state"


class SourceError(UpdateError):
    code = "source"


# ------------------------------------------------------------- file helpers


def _replace_with_retry(src: Path, dst: Path) -> None:
    # A reader holding the target open makes os.replace raise WinError 5
    # until it closes (ops/rc_supervisor.py:69 measured the same race).
    delays = (0.01, 0.025, 0.05, 0.1, 0.2, 0.4)
    for i in range(len(delays) + 1):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i >= len(delays):
                raise
            time.sleep(delays[i])


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    """Scratch file ending in .tmp (never matched by the supervisor's
    `*.json` request glob, ops/rc_supervisor.py:1424), fsync, os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        _replace_with_retry(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _write_json(path: Path, data: Any) -> None:
    _write_bytes_atomic(path, json.dumps(data, indent=2, sort_keys=True,
                                         ensure_ascii=True).encode("ascii"))


def _read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _hash_file(path: Path) -> Tuple[str, int]:
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(CHUNK)
            if not chunk:
                break
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n


def _live_path(root: Path, rel: str) -> Path:
    return root.joinpath(*rel.split("/"))


# ------------------------------------------------------------ install root


def runtime_dir(root: Path) -> Path:
    return Path(root) / "ops" / "runtime"


def staging_root(root: Path) -> Path:
    return runtime_dir(root) / "staging"


def launcher_state_dir(root: Path) -> Path:
    return runtime_dir(root) / "launcher"


def installed_record_path(root: Path) -> Path:
    return launcher_state_dir(root) / "backend_installed.json"


def state_path(root: Path) -> Path:
    return launcher_state_dir(root) / "update_state.json"


def deploy_key_path(root: Path) -> Path:
    # The worker derives the same path from its own location
    # (ops/rc_transactional_deploy.py:80) - never from the request.
    return runtime_dir(root) / "deploy_request.key"


def _install_root(root: Path) -> Path:
    r = Path(root).resolve()
    if (r / ".git").exists():
        raise StateError(
            "the backend root is a linked git checkout: it updates through git, "
            "core/hot_reload.py and ADR-008, never the release channel")
    return r


# ---------------------------------------------------------------- versions


def version_key(version: Any) -> Tuple[Any, ...]:
    """Semver precedence key: a release sorts after its prereleases; numeric
    prerelease identifiers compare as numbers and before alphanumeric ones."""
    if not isinstance(version, str) or not VERSION_RE.match(version):
        raise ManifestError(f"not a version: {version!r}")
    core, _, pre = version.partition("-")
    nums = tuple(int(x) for x in core.split("."))
    if not pre:
        return (nums, 1, ())
    parts = tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split("."))
    return (nums, 0, parts)


# ------------------------------------------------------------- path policy


def check_payload_path(rel: Any) -> str:
    """Return `rel` when it may travel in a backend payload, else raise
    PayloadPathError. Exact-case allow-list; case-insensitive deny-list."""
    if not isinstance(rel, str):
        raise PayloadPathError("payload path must be a string")
    if not rel or len(rel) > MAX_PATH_CHARS:
        raise PayloadPathError(f"payload path empty or longer than {MAX_PATH_CHARS}")
    for ch in rel:
        if not 0x20 <= ord(ch) <= 0x7e or ch in _BAD_CHARS:
            raise PayloadPathError(f"forbidden character in payload path {rel!r}")
    if rel.startswith("/"):
        raise PayloadPathError(f"payload path is not relative: {rel!r}")
    segs = rel.split("/")
    for seg in segs:
        if seg in ("", ".", ".."):
            raise PayloadPathError(f"empty, '.' or '..' segment in {rel!r}")
        if seg != seg.strip(" ") or seg.endswith("."):
            raise PayloadPathError(f"segment with an edge space or a trailing dot in {rel!r}")
        if seg.split(".")[0].casefold() in _RESERVED:
            raise PayloadPathError(f"reserved device name in {rel!r}")
        if _SHORT_NAME_RE.search(seg):
            raise PayloadPathError(f"8.3 short-name segment in {rel!r}")
    folded = rel.casefold()
    if any(s in DENY_SEGMENTS for s in folded.split("/")):
        raise PayloadPathError(f"dev-only or generated tree in {rel!r}")
    if folded in DENY_PATHS or any(folded.startswith(p) for p in DENY_PREFIXES):
        raise PayloadPathError(f"runtime state or host config never travels: {rel!r}")
    if _DENY_NAME_RE.search(segs[-1]):
        raise PayloadPathError(f"secret, generated or runtime file name: {rel!r}")
    if len(segs) == 1:
        if rel not in PAYLOAD_ROOT_FILES:
            raise PayloadPathError(f"root file not on the payload allow-list: {rel!r}")
    elif segs[0] not in PAYLOAD_DIRS:
        raise PayloadPathError(f"top-level entry not on the payload allow-list: {rel!r}")
    return rel


# ------------------------------------------------------------ ignore rules


@dataclass(frozen=True)
class _IgnoreRule:
    regex: Any
    negate: bool
    dir_only: bool


def _glob_to_regex(pat: str) -> str:
    """gitignore glob -> regex body: `*` / `?` / `[...]` never cross `/`;
    a leading or inner `**/` matches zero or more directories, a trailing
    `/**` everything inside."""
    out: List[str] = []
    i, n = 0, len(pat)
    while i < n:
        if pat.startswith("**/", i) and (i == 0 or pat[i - 1] == "/"):
            out.append("(?:.*/)?")
            i += 3
            continue
        if pat.startswith("/**", i) and i + 3 == n:
            out.append("/.*")
            i += 3
            continue
        c = pat[i]
        if c == "*":
            while i < n and pat[i] == "*":
                i += 1
            out.append("[^/]*")
            continue
        if c == "?":
            out.append("[^/]")
        elif c == "[":
            j = i + 1
            if j < n and pat[j] in "!^":
                j += 1
            if j < n and pat[j] == "]":
                j += 1
            j = pat.find("]", j)
            if j == -1:
                out.append(re.escape(c))
            else:
                body = pat[i + 1:j]
                if body[:1] in ("!", "^"):
                    body = "^" + body[1:]
                out.append("[" + body.replace("\\", "\\\\") + "]")
                i = j + 1
                continue
        elif c == "\\" and i + 1 < n:
            out.append(re.escape(pat[i + 1]))
            i += 2
            continue
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


def _parse_ignore(text: str) -> List[_IgnoreRule]:
    rules: List[_IgnoreRule] = []
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if not line or line.startswith("#"):
            continue
        while line.endswith(" ") and not line.endswith("\\ "):
            line = line[:-1]
        negate = line.startswith("!")
        if negate:
            line = line[1:]
        elif line.startswith(("\\!", "\\#")):
            line = line[1:]
        dir_only = line.endswith("/")
        line = line.rstrip("/")
        if not line:
            continue
        anchored = "/" in line
        body = _glob_to_regex(line.lstrip("/"))
        # Windows git runs core.ignorecase=true: fold case, and a wider match
        # only ever denies more.
        rx = re.compile(("^" if anchored else "^(?:.*/)?") + body + "$", re.I | re.S)
        rules.append(_IgnoreRule(rx, negate, dir_only))
    return rules


class IgnoreRules:
    """`git check-ignore` semantics over the install's shipped .gitignore
    files (the root one plus any nested ones), read from the INSTALLED tree,
    never from a payload - and no payload can ever write one there, since
    check_payload_path denies every .gitignore / .gitattributes /
    .gitmodules path, so the rules are the installed bundle's own. The
    last matching pattern wins, a deeper .gitignore
    outranks a shallower one, and nothing inside an ignored directory can be
    re-included. A path it reports is per-install or runtime state."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._sets: Dict[str, List[_IgnoreRule]] = {}
        self._dirs: Dict[str, bool] = {}

    @classmethod
    def for_install(cls, root: Path) -> "IgnoreRules":
        top = Path(root) / ".gitignore"
        if not top.is_file() or top.is_symlink():
            raise StateError("the install ships no .gitignore at its root, so runtime and "
                             "per-install paths cannot be told apart - refusing (fail closed)")
        return cls(root)

    def _rules(self, base: str) -> List[_IgnoreRule]:
        got = self._sets.get(base)
        if got is None:
            path = _live_path(self.root, base + "/.gitignore") if base else self.root / ".gitignore"
            got = []
            if path.is_file() and not path.is_symlink():
                try:
                    got = _parse_ignore(path.read_text(encoding="utf-8", errors="replace"))
                except OSError as exc:
                    raise StateError(f"ignore list unreadable: {base or '.'}/.gitignore "
                                     f"({type(exc).__name__})") from None
            self._sets[base] = got
        return got

    def _match(self, rel: str, is_dir: bool) -> bool:
        parts = rel.split("/")
        hit = False
        for depth in range(len(parts)):
            sub = "/".join(parts[depth:])
            for rule in self._rules("/".join(parts[:depth])):
                if (not rule.dir_only or is_dir) and rule.regex.match(sub):
                    hit = not rule.negate
        return hit

    def ignored(self, rel: str) -> bool:
        parts = rel.split("/")
        for i in range(1, len(parts)):
            d = "/".join(parts[:i])
            if d not in self._dirs:
                self._dirs[d] = self._match(d, True)
            if self._dirs[d]:
                return True
        return self._match(rel, False)


def _check_not_ignored(rules: IgnoreRules, paths: Iterable[str]) -> None:
    for rel in paths:
        if rules.ignored(rel):
            raise PayloadPathError(
                f"{rel!r} is ignored by the install's .gitignore (per-install or runtime "
                "state never travels); refusing the whole update")


def live_alias(root: Path, rel: str) -> Optional[str]:
    """None when root/rel lands on itself (case aside). Otherwise the path,
    relative to root, that it REALLY lands on: Path.resolve() expands 8.3
    short names of existing components (GetFinalPathNameByHandleW, the
    GetLongPathNameW equivalent) and follows junctions and symlinks, so
    `ops/FLEET_~1/x` reports ops/fleet_kit/x."""
    resolved = _live_path(root, rel).resolve()
    try:
        inside = resolved.relative_to(root)
    except ValueError:
        return "<outside the install root>"
    real = "/".join(inside.parts)
    return None if real.casefold() == rel.casefold() else real


# ---------------------------------------------------------------- manifest


@dataclass(frozen=True)
class FileEntry:
    path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class Manifest:
    version: str
    channel: str
    files: Tuple[FileEntry, ...]
    archive_name: Optional[str] = None
    archive_sha256: Optional[str] = None
    archive_size: Optional[int] = None
    min_shell_version: Optional[str] = None

    def file_map(self) -> Dict[str, FileEntry]:
        return {f.path: f for f in self.files}


def _size(value: Any, where: str, cap: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= cap:
        raise ManifestError(f"{where}: size must be an integer 0-{cap}")
    return value


def _sha(value: Any, where: str) -> str:
    if not isinstance(value, str) or not _SHA_RE.match(value):
        raise ManifestError(f"{where}: sha256 must be 64 lower-case hex characters")
    return value


def parse_manifest(doc: Any, *, require_archive: bool = True) -> Manifest:
    """Schema-check a manifest document. `require_archive=False` reads the
    install's own backend-manifest.json, which describes files only."""
    if not isinstance(doc, dict):
        raise ManifestError("manifest must be a JSON object")
    schema = doc.get("schema")
    if type(schema) is not int or schema != SCHEMA:
        raise ManifestError(f"unsupported manifest schema {schema!r}; expected {SCHEMA}")
    if doc.get("kind") != KIND:
        raise ManifestError(f"manifest kind must be {KIND!r}")
    version = doc.get("version")
    version_key(version)
    channel = doc.get("channel")
    if channel not in CHANNELS:
        raise ManifestError(f"manifest channel must be one of {CHANNELS}")
    min_shell = doc.get("min_shell_version")
    if min_shell is not None:
        version_key(min_shell)
    archive = doc.get("archive")
    a_name = a_sha = a_size = None
    if archive is None:
        if require_archive:
            raise ManifestError("manifest has no archive")
    else:
        if not isinstance(archive, dict):
            raise ManifestError("archive must be an object")
        a_name = archive.get("name")
        if a_name != f"backend-{version}.zip":
            raise ManifestError(f"archive name must be backend-{version}.zip")
        a_sha = _sha(archive.get("sha256"), "archive")
        a_size = _size(archive.get("size"), "archive", MAX_ARCHIVE_BYTES)
    raw_files = doc.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise ManifestError("files must be a non-empty list")
    if len(raw_files) > MAX_FILES:
        raise ManifestError(f"more than {MAX_FILES} files")
    files: List[FileEntry] = []
    seen: set = set()
    dirs: set = set()
    total = 0
    for i, raw in enumerate(raw_files):
        if not isinstance(raw, dict):
            raise ManifestError(f"files[{i}] must be an object")
        path = check_payload_path(raw.get("path"))
        sha = _sha(raw.get("sha256"), f"files[{i}]")
        size = _size(raw.get("size"), f"files[{i}]", MAX_FILE_BYTES)
        key = path.casefold()
        if key in seen:
            raise ManifestError(f"duplicate path (case-insensitive): {path!r}")
        seen.add(key)
        parts = key.split("/")
        dirs.update("/".join(parts[:n]) for n in range(1, len(parts)))
        total += size
        files.append(FileEntry(path, sha, size))
    if total > MAX_TOTAL_BYTES:
        raise ManifestError(f"payload larger than {MAX_TOTAL_BYTES} bytes")
    if seen & dirs:
        raise ManifestError("a file path is also a directory of another file")
    return Manifest(version=version, channel=channel, files=tuple(files),
                    archive_name=a_name, archive_sha256=a_sha, archive_size=a_size,
                    min_shell_version=min_shell)


def parse_manifest_bytes(data: bytes, *, require_archive: bool = True) -> Manifest:
    try:
        doc = json.loads(data.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ManifestError(f"manifest is not ASCII JSON: {type(exc).__name__}") from None
    return parse_manifest(doc, require_archive=require_archive)


# ----------------------------------------------------------------- sources


@dataclass(frozen=True)
class Release:
    version: str
    prerelease: bool
    manifest: str
    archive: str
    origin: str = ""
    urls: Tuple[Tuple[str, str], ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {"version": self.version, "prerelease": self.prerelease,
                "manifest": self.manifest, "archive": self.archive,
                "origin": self.origin}


class Source:
    origin = ""

    def releases(self) -> List[Release]:
        raise NotImplementedError

    def read(self, release: Release, name: str, max_bytes: int) -> bytes:
        raise NotImplementedError

    def release(self, version: str) -> Release:
        for rel in self.releases():
            if rel.version == version:
                return rel
        raise SourceError(f"no release {version} in {self.origin}")


class LocalSource(Source):
    """A folder of backend-<ver>.json + backend-<ver>.zip pairs (a PKG-4 build
    output or the operator's local channel). A version with a prerelease tag
    rides the dev channel only."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.origin = f"local:{self.directory}"

    def releases(self) -> List[Release]:
        if not self.directory.is_dir():
            raise SourceError(f"local release folder not found: {self.directory}")
        out = []
        for p in self.directory.iterdir():
            m = MANIFEST_NAME_RE.match(p.name)
            if not m or not p.is_file():
                continue
            ver = m.group(1)
            if (self.directory / f"backend-{ver}.zip").is_file():
                out.append(Release(ver, "-" in ver, p.name, f"backend-{ver}.zip",
                                   origin=self.origin))
        return sorted(out, key=lambda r: version_key(r.version))

    def read(self, release: Release, name: str, max_bytes: int) -> bytes:
        if name not in (release.manifest, release.archive):
            raise SourceError(f"{name!r} is not an asset of release {release.version}")
        path = self.directory / name
        try:
            with open(path, "rb") as fh:
                data = fh.read(max_bytes + 1)
        except OSError as exc:
            raise SourceError(f"cannot read {name}: {exc}") from None
        if len(data) > max_bytes:
            raise SourceError(f"{name} is larger than {max_bytes} bytes")
        return data


class _HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise urllib.error.HTTPError(newurl, code, "refused a non-https redirect",
                                         headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def https_get(url: str, *, max_bytes: int, timeout: float = 30.0) -> bytes:
    """GET over HTTPS only (redirects too), capped at `max_bytes`. The scheme
    is refused before any connection is made."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise SourceError(f"refused a non-https URL: {parts.scheme or '?'}://")
    opener = urllib.request.build_opener(_HttpsOnlyRedirect())
    req = urllib.request.Request(url, headers={
        "User-Agent": "Amberstone-updater",
        "Accept": "application/vnd.github+json, application/octet-stream"})
    try:
        with opener.open(req, timeout=timeout) as resp:
            data = resp.read(max_bytes + 1)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise SourceError(f"fetch failed: {type(exc).__name__}: {exc}") from None
    if len(data) > max_bytes:
        raise SourceError(f"response larger than {max_bytes} bytes")
    return data


class GitHubSource(Source):
    """GitHub Releases of owner/repo. Each release offers the backend as two
    assets, backend-<ver>.json + backend-<ver>.zip; drafts are skipped and a
    GitHub prerelease rides the dev channel only."""

    def __init__(self, owner: str = DEFAULT_GITHUB_OWNER,
                 repo: str = DEFAULT_GITHUB_REPO, *,
                 fetch: Optional[Callable[[str, int], bytes]] = None,
                 api_base: str = GITHUB_API, per_page: int = 30) -> None:
        if not _SLUG_RE.match(owner or "") or not _SLUG_RE.match(repo or ""):
            raise SourceError("bad GitHub owner / repo")
        self.owner, self.repo = owner, repo
        self.api_base = api_base.rstrip("/")
        self.per_page = int(per_page)
        self._fetch = fetch or (lambda url, max_bytes: https_get(url, max_bytes=max_bytes))
        self.origin = f"github:{owner}/{repo}"

    def releases(self) -> List[Release]:
        url = f"{self.api_base}/repos/{self.owner}/{self.repo}/releases?per_page={self.per_page}"
        _check_github_url(url)
        try:
            doc = json.loads(self._fetch(url, MAX_MANIFEST_BYTES).decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise SourceError(f"release list is not JSON: {type(exc).__name__}") from None
        if not isinstance(doc, list):
            raise SourceError("release list is not a JSON array")
        found: Dict[str, Release] = {}
        for rel in doc:
            if not isinstance(rel, dict) or rel.get("draft"):
                continue
            assets = {}
            for a in rel.get("assets") or []:
                if isinstance(a, dict) and isinstance(a.get("name"), str) \
                        and isinstance(a.get("browser_download_url"), str):
                    assets[a["name"]] = a["browser_download_url"]
            for name in sorted(assets):
                m = MANIFEST_NAME_RE.match(name)
                zname = f"backend-{m.group(1)}.zip" if m else ""
                if not m or zname not in assets or m.group(1) in found:
                    continue
                found[m.group(1)] = Release(
                    m.group(1), bool(rel.get("prerelease")), name, zname,
                    origin=self.origin, urls=((name, assets[name]), (zname, assets[zname])))
        return sorted(found.values(), key=lambda r: version_key(r.version))

    def read(self, release: Release, name: str, max_bytes: int) -> bytes:
        url = dict(release.urls).get(name)
        if not url:
            raise SourceError(f"{name!r} is not an asset of release {release.version}")
        _check_github_url(url)
        return self._fetch(url, max_bytes)


def _check_github_url(url: str) -> None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "").lower() not in GITHUB_HOSTS:
        raise SourceError(f"refused a release URL outside GitHub over HTTPS: "
                          f"{parts.scheme}://{parts.hostname}")


def check(source: Source, *, channel: str = "stable",
          current_version: Optional[str] = None) -> Optional[Release]:
    """The newest release on `channel` strictly newer than current_version
    (any release when the current version is unknown), or None."""
    if channel not in CHANNELS:
        raise UpdateError(f"unknown channel {channel!r}; expected one of {CHANNELS}")
    floor = version_key(current_version) if current_version else None
    best: Optional[Release] = None
    for rel in source.releases():
        if rel.prerelease and channel != "dev":
            continue
        key = version_key(rel.version)
        if floor is not None and key <= floor:
            continue
        if best is None or key > version_key(best.version):
            best = rel
    return best


# ------------------------------------------------------------ install state


def _read_record_file(root: Path) -> Optional[Dict[str, Any]]:
    try:
        doc = _read_json(installed_record_path(root))
    except (OSError, ValueError):
        return None
    if isinstance(doc, dict) and isinstance(doc.get("files"), dict) and "version" in doc:
        return doc
    return None


def read_installed(root: Path) -> Optional[Dict[str, Any]]:
    """What is installed: the record finish() keeps, else the bundle's
    shipped backend-manifest.json, else None (version unknown)."""
    rec = _read_record_file(Path(root))
    if rec is not None:
        return rec
    try:
        shipped = parse_manifest_bytes(
            (Path(root) / INSTALLED_MANIFEST).read_bytes(), require_archive=False)
    except (OSError, UpdateError):
        return None
    return {"schema": SCHEMA, "version": shipped.version, "manifest_sha256": None,
            "files": {f.path: f.sha256 for f in shipped.files}, "source": "shipped",
            "previous": None, "pre_hashes": {}, "created": [], "backup_root": None}


def installed_version(root: Path) -> Optional[str]:
    rec = read_installed(root)
    return rec.get("version") if rec else None


def read_state(root: Path) -> Dict[str, Any]:
    try:
        doc = _read_json(state_path(root))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _write_state(root: Path, state: Dict[str, Any]) -> None:
    _write_json(state_path(root), dict(state, schema=SCHEMA, updated=utc_now()))


def hot_reload_watching(root: Path) -> bool:
    """Is core/hot_reload.py watching? Its status file (core/hot_reload.py:693)
    says `watching`, and its halt file (:692) is absent. Unknown = no."""
    rt = runtime_dir(root)
    if (rt / "hot_reload_halt.txt").exists():
        return False
    try:
        doc = _read_json(rt / "hot_reload.json")
    except (OSError, ValueError):
        return False
    return isinstance(doc, dict) and doc.get("watching") is True


# ------------------------------------------------------------ live game


_TH32 = None


def _toolhelp():
    global _TH32
    if _TH32 is None:
        import ctypes
        from ctypes import wintypes

        class _Entry(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", ctypes.c_size_t),
                        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD),
                        ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                        ("szExeFile", ctypes.c_wchar * 260)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
        k32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_Entry))
        k32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_Entry))
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        _TH32 = (k32, _Entry)
    return _TH32


def running_process_names() -> frozenset:
    """Lower-case image names of every running process (Windows Toolhelp32,
    stdlib ctypes). Elsewhere: empty, so the health signal alone decides."""
    if sys.platform != "win32":
        return frozenset()
    import ctypes
    k32, entry_t = _toolhelp()
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)   # TH32CS_SNAPPROCESS
    if not snap or snap == ctypes.c_void_p(-1).value:
        raise OSError(f"CreateToolhelp32Snapshot failed ({ctypes.get_last_error()})")
    names = set()
    try:
        entry = entry_t()
        entry.dwSize = ctypes.sizeof(entry_t)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            names.add(entry.szExeFile.lower())
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return frozenset(names)


def game_live(root: Path, *, process_names: Optional[Callable[[], Iterable[str]]] = None,
              now: Optional[float] = None) -> Optional[str]:
    """A reason string while a League / TFT game is loading or running, else
    None. Process signal first (core/hot_reload.py:170), then a fresh
    health.json flag (core/live_game_gate.py:31). Fail closed: a failed
    process scan, and a FRESH health.json that cannot be read or parsed (a
    torn write, a lock), are reported as reasons so the caller defers. Only
    a missing or stale health.json is no evidence (RC is not running)."""
    try:
        names = {str(n).lower() for n in (process_names or running_process_names)()}
    except Exception as exc:   # noqa: BLE001 - any probe failure defers
        return f"game check failed: {type(exc).__name__}: {exc}"[:200]
    hits = sorted(names & GAME_PROCESS_NAMES)
    if hits:
        return f"process {hits[0]}"
    health = runtime_dir(root) / "health.json"
    try:
        age = (time.time() if now is None else now) - health.stat().st_mtime
    except FileNotFoundError:
        return None
    except OSError as exc:
        return f"health unreadable ({type(exc).__name__}); deferring"
    if age > HEALTH_FRESH_S:
        return None
    try:
        doc = _read_json(health)
    except (OSError, ValueError) as exc:
        return f"health unreadable ({type(exc).__name__}); deferring"
    if not isinstance(doc, dict):
        return "health unreadable (not a JSON object); deferring"
    for flag in LIVE_GAME_FLAGS:
        if doc.get(flag):
            return f"health {flag}"
    return None


def _check_game(root: Path, game_check: Optional[Callable[[], Optional[str]]]) -> None:
    probe = game_check if game_check is not None else (lambda: game_live(root))
    try:
        reason = probe()
    except Exception as exc:   # noqa: BLE001
        reason = f"game check failed: {type(exc).__name__}"
    if reason:
        raise GameLiveError(f"deferred while a game is live ({reason}); retry after it")


# --------------------------------------------------------- classifier


@dataclass(frozen=True)
class PathClass:
    path: str
    app: str                     # none | hot_reload | restart (main.py)
    services: Tuple[str, ...]    # out-of-process services to restart
    why: str


@dataclass(frozen=True)
class RestartPlan:
    level: str
    app: str
    services: Tuple[str, ...]
    stale_check: bool
    escalated: bool
    mechanism: str
    reasons: Tuple[PathClass, ...] = field(default=())

    @property
    def needs_restart(self) -> bool:
        return self.level != "none"

    def to_dict(self) -> Dict[str, Any]:
        return {"level": self.level, "app": self.app, "services": list(self.services),
                "stale_check": self.stale_check, "escalated": self.escalated,
                "needs_restart": self.needs_restart, "mechanism": self.mechanism,
                "reasons": [{"path": c.path, "app": c.app, "services": list(c.services),
                             "why": c.why} for c in self.reasons]}


def _hr_skipped(dirs: Sequence[str]) -> bool:
    singles = {s for s in HOT_RELOAD_SKIP_DIRS if "/" not in s}
    if singles.intersection(dirs):
        return True
    for run in (tuple(s.split("/")) for s in HOT_RELOAD_SKIP_DIRS if "/" in s):
        for i in range(len(dirs) - len(run) + 1):
            if tuple(dirs[i:i + len(run)]) == run:
                return True
    return False


def hot_reload_watches(rel: str) -> bool:
    """Mirror of core/hot_reload.py:249 _should_watch."""
    r = rel.replace("\\", "/")
    if _hr_skipped(r.split("/")[:-1]) or r in FROZEN_PATHS or not r.endswith(".py"):
        return False
    return any(r == wd or r.startswith(wd + "/") or (wd == "" and "/" not in r)
               for wd in HOT_RELOAD_WATCH_DIRS)


def main_never_imports(rel: str) -> bool:
    r = rel.replace("\\", "/")
    return r in _MAIN_NEVER_FILES or r.startswith(_MAIN_NEVER_PREFIXES)


def _services_for(r: str) -> Tuple[str, ...]:
    out = set()
    if r in _SERVICE_FILES:
        out.add(_SERVICE_FILES[r])
    out.update(name for prefix, name in _SERVICE_PREFIXES if r.startswith(prefix))
    out.update(name for rx, name in _SERVICE_PATTERNS if rx.match(r))
    return tuple(sorted(out))


def _not_runtime(r: str) -> bool:
    segs = r.split("/")
    if segs[0] in _NOT_RUNTIME_DIRS or "tests" in segs[:-1]:
        return True
    return len(segs) == 1 and (r.endswith(".md") or r in ("LICENSE", "NOTICE"))


def classify_path(rel: str) -> PathClass:
    """Effect of one changed backend file. See the module docstring."""
    r = str(rel).replace("\\", "/")
    services = _services_for(r)
    if _not_runtime(r):
        return PathClass(r, "none", (), "not loaded at runtime (docs, tests, licences)")
    if main_never_imports(r):
        return PathClass(r, "none", services,
                         "main.py never imports it; only its own process loads it")
    if r.startswith("web/") and not r.endswith(".py"):
        return PathClass(r, "none", services,
                         "web asset: ADR-008 reloads open pages, served fresh otherwise")
    if r.endswith(".py"):
        if r in FROZEN_PATHS:
            return PathClass(r, "restart", services,
                             "frozen core: core/hot_reload.py never watches it")
        if hot_reload_watches(r):
            return PathClass(r, "hot_reload", services,
                             "core/hot_reload.py restarts main.py if it loaded this module")
        return PathClass(r, "restart", services,
                         "outside core/hot_reload.py's watch dirs")
    if r in ("requirements.txt", "requirements.in"):
        return PathClass(r, "restart", services,
                         "dependency set: every Python process must restart")
    return PathClass(r, "restart", services, "data / config read at startup")


def classify_paths(paths: Iterable[str], *, hot_reload_active: bool = True) -> RestartPlan:
    """The needs-restart answer for a set of changed files: the worst main
    app effect, the union of services, and the overall level."""
    classes = tuple(classify_path(p) for p in paths)
    app = "none"
    for c in classes:
        if APP_EFFECTS.index(c.app) > APP_EFFECTS.index(app):
            app = c.app
    escalated = app == "hot_reload" and not hot_reload_active
    if escalated:
        app = "restart"
    services = tuple(sorted({s for c in classes for s in c.services}))
    level = "relaunch" if services else app
    stale = any(c.path.endswith(".py") and c.app in ("hot_reload", "restart")
                for c in classes)
    return RestartPlan(level=level, app=app, services=services, stale_check=stale,
                       escalated=escalated, mechanism=MECHANISMS[level], reasons=classes)


# ------------------------------------------------------------- staging


@dataclass(frozen=True)
class StagedUpdate:
    version: str
    directory: Path
    manifest: Manifest
    manifest_sha256: str

    @property
    def payload(self) -> Path:
        return self.directory / "payload"


def _check_shell(manifest: Manifest, shell_version: Optional[str]) -> None:
    need = manifest.min_shell_version
    if need is None:
        return
    if shell_version is None:
        raise ManifestError(f"release needs shell >= {need} and the shell version is unknown")
    if version_key(shell_version) < version_key(need):
        raise ManifestError(f"release needs shell >= {need}; this shell is {shell_version}")


def _extract(blob: bytes, manifest: Manifest, dest: Path) -> None:
    want = manifest.file_map()
    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise IntegrityError(f"archive unreadable: {type(exc).__name__}") from None
    seen: set = set()
    try:
        with zf:
            for info in zf.infolist():
                name = info.filename
                mode = (info.external_attr >> 16) & 0o170000
                if name.endswith("/"):
                    if mode not in (0, 0o040000):
                        raise IntegrityError(f"special directory entry {name!r}")
                    continue
                if info.flag_bits & 0x1:
                    raise IntegrityError(f"encrypted archive member {name!r}")
                if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise IntegrityError(f"unsupported compression for {name!r}")
                if mode not in (0, 0o100000):
                    raise IntegrityError(f"{name!r} is not a regular file (symlink or special)")
                entry = want.get(name)
                if entry is None:
                    raise IntegrityError(f"archive member not in the manifest: {name!r}")
                if name in seen:
                    raise IntegrityError(f"duplicate archive member {name!r}")
                seen.add(name)
                if info.file_size != entry.size:
                    raise IntegrityError(f"{name}: size differs from the manifest")
                target = dest.joinpath(*name.split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                h = hashlib.sha256()
                n = 0
                with zf.open(info) as src, open(target, "xb") as out:
                    while True:
                        chunk = src.read(CHUNK)
                        if not chunk:
                            break
                        n += len(chunk)
                        if n > entry.size:
                            raise IntegrityError(f"{name}: longer than the manifest says")
                        h.update(chunk)
                        out.write(chunk)
                    out.flush()
                    os.fsync(out.fileno())
                if n != entry.size or not hmac.compare_digest(h.hexdigest(), entry.sha256):
                    raise IntegrityError(f"{name}: sha256 does not match the manifest")
    except (zipfile.BadZipFile, EOFError, zipfile.LargeZipFile) as exc:
        raise IntegrityError(f"archive corrupt: {type(exc).__name__}: {exc}") from None
    missing = sorted(set(want) - seen)
    if missing:
        raise IntegrityError(f"{len(missing)} manifest file(s) missing from the archive, "
                             f"first {missing[0]!r}")


def _swap_into_place(partial: Path, final: Path) -> None:
    old = None
    if final.exists():
        old = final.with_name(f".old-{final.name}-{secrets.token_hex(4)}")
        _replace_with_retry(final, old)
    try:
        _replace_with_retry(partial, final)
    except BaseException:
        if old is not None:
            _replace_with_retry(old, final)
        raise
    if old is not None:
        shutil.rmtree(old, ignore_errors=True)


def stage(root: Path, source: Source, release: Release, *, channel: str = "stable",
          pin_sha256: Optional[str] = None,
          shell_version: Optional[str] = None) -> StagedUpdate:
    """Fetch, verify and atomically stage `release` under
    ops/runtime/staging/<ver>/ (payload/, manifest.json, staged.json)."""
    root = _install_root(root)
    if channel not in CHANNELS:
        raise UpdateError(f"unknown channel {channel!r}")
    if read_state(root).get("pending"):
        # The worker may be copying out of a staging dir right now; a restage
        # would swap it underneath that copy.
        raise StateError("an update operation is pending; call finish() first")
    ignore = IgnoreRules.for_install(root)
    version_key(release.version)
    if release.manifest != f"backend-{release.version}.json" \
            or release.archive != f"backend-{release.version}.zip":
        raise ManifestError("release asset names do not match its version")
    raw = source.read(release, release.manifest, MAX_MANIFEST_BYTES)
    msha = hashlib.sha256(raw).hexdigest()
    if pin_sha256 is not None and not hmac.compare_digest(msha, str(pin_sha256).lower()):
        raise IntegrityError("manifest does not match the pinned sha256")
    manifest = parse_manifest_bytes(raw)
    if manifest.version != release.version:
        raise ManifestError(f"manifest says {manifest.version}, release says {release.version}")
    if manifest.channel == "dev" and channel != "dev":
        raise ManifestError("a dev-channel release cannot be staged on the stable channel")
    _check_shell(manifest, shell_version)
    _check_not_ignored(ignore, (f.path for f in manifest.files))
    blob = source.read(release, release.archive, MAX_ARCHIVE_BYTES)
    if len(blob) != manifest.archive_size:
        raise IntegrityError("archive size differs from the manifest")
    if not hmac.compare_digest(hashlib.sha256(blob).hexdigest(), manifest.archive_sha256 or ""):
        raise IntegrityError("archive sha256 does not match the manifest")
    sroot = staging_root(root)
    sroot.mkdir(parents=True, exist_ok=True)
    partial = sroot / f".partial-{release.version}-{os.getpid()}-{secrets.token_hex(4)}"
    partial.mkdir()
    final = sroot / release.version
    try:
        _extract(blob, manifest, partial / "payload")
        _write_bytes_atomic(partial / "manifest.json", raw)
        _write_json(partial / "staged.json", {
            "schema": SCHEMA, "version": release.version, "manifest_sha256": msha,
            "pinned": pin_sha256 is not None, "origin": release.origin,
            "staged_at": utc_now()})
        _swap_into_place(partial, final)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    return StagedUpdate(release.version, final, manifest, msha)


def _walk_payload(payload: Path) -> Dict[str, Path]:
    isjunction = getattr(os.path, "isjunction", lambda _p: False)
    found: Dict[str, Path] = {}
    stack = [(payload, "")]
    while stack:
        d, rel = stack.pop()
        with os.scandir(d) as it:
            for e in it:
                r = f"{rel}{e.name}"
                if e.is_symlink() or isjunction(e.path):
                    raise IntegrityError(f"link in the staging: {r!r}")
                if e.is_dir(follow_symlinks=False):
                    # The worker's py_compile writes __pycache__ next to each
                    # staged .py (ops/rc_transactional_deploy.py:359); it is
                    # never part of the payload and never copied to live.
                    if e.name != "__pycache__":
                        stack.append((Path(e.path), r + "/"))
                elif e.is_file(follow_symlinks=False):
                    found[r] = Path(e.path)
                else:
                    raise IntegrityError(f"special file in the staging: {r!r}")
    return found


def verify_staged(root: Path, version: str) -> StagedUpdate:
    """Re-verify a staging dir byte for byte against its own manifest, whose
    sha256 must still be the one recorded at stage time. Dirty = refused."""
    root = _install_root(root)
    if not isinstance(version, str) or not VERSION_RE.match(version):
        raise PayloadPathError(f"not a version: {version!r}")
    d = staging_root(root) / version
    if not d.is_dir():
        raise StateError(f"nothing staged for {version}")
    try:
        raw = (d / "manifest.json").read_bytes()
        meta = _read_json(d / "staged.json")
    except (OSError, ValueError) as exc:
        raise IntegrityError(f"staging metadata unreadable: {type(exc).__name__}") from None
    msha = hashlib.sha256(raw).hexdigest()
    if not isinstance(meta, dict) or meta.get("manifest_sha256") != msha:
        raise IntegrityError("the staged manifest changed after staging")
    manifest = parse_manifest_bytes(raw)
    if manifest.version != version:
        raise IntegrityError("the staged manifest names another version")
    try:
        found = _walk_payload(d / "payload")
    except OSError as exc:
        raise IntegrityError(f"staging unreadable: {exc}") from None
    want = manifest.file_map()
    extra = sorted(set(found) - set(want))
    missing = sorted(set(want) - set(found))
    if extra or missing:
        raise IntegrityError(f"staging differs from its manifest: {len(extra)} extra, "
                             f"{len(missing)} missing")
    for rel, entry in want.items():
        sha, size = _hash_file(found[rel])
        if size != entry.size or not hmac.compare_digest(sha, entry.sha256):
            raise IntegrityError(f"staged file changed after staging: {rel!r}")
    return StagedUpdate(version, d, manifest, msha)


# ---------------------------------------------------------------- apply


@dataclass(frozen=True)
class ApplyPlan:
    version: Optional[str]
    changed: Tuple[str, ...]          # deployed (new or different bytes)
    created: Tuple[str, ...]          # subset of changed: not present live
    unchanged: Tuple[str, ...]
    pre_hashes: Tuple[Tuple[str, str], ...]   # live sha256 before the update
    modified_locally: Tuple[str, ...]  # live differs from the installed record
    orphaned: Tuple[str, ...]          # owned before, absent from the release
    removed: Tuple[str, ...]           # rollback: created files to quarantine
    restart: RestartPlan

    def to_dict(self) -> Dict[str, Any]:
        return {"version": self.version, "changed": list(self.changed),
                "created": list(self.created), "unchanged": len(self.unchanged),
                "pre_hashes": dict(self.pre_hashes),
                "modified_locally": list(self.modified_locally),
                "orphaned": list(self.orphaned), "removed": list(self.removed),
                "restart": self.restart.to_dict()}


@dataclass(frozen=True)
class ApplyResult:
    status: str                    # requested | noop | done
    request_id: Optional[str]
    request_path: Optional[Path]
    plan: ApplyPlan

    def to_dict(self) -> Dict[str, Any]:
        return {"status": self.status, "request_id": self.request_id,
                "request_path": str(self.request_path) if self.request_path else None,
                "plan": self.plan.to_dict()}


@dataclass(frozen=True)
class FinishResult:
    status: str                    # none | pending | ok | failed | lost
    kind: Optional[str] = None     # apply | rollback
    version: Optional[str] = None
    restart: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    run_id_before: Optional[str] = None   # main.py's run_id when requested

    def to_dict(self) -> Dict[str, Any]:
        return {"status": self.status, "kind": self.kind, "version": self.version,
                "restart": self.restart, "result": self.result,
                "run_id_before": self.run_id_before}


def plan_apply(root: Path, staged: StagedUpdate, *,
               hot_reload_active: Optional[bool] = None) -> ApplyPlan:
    """Which files the update changes, which it creates, and the restart it
    needs. Fail closed throughout: a path the install's .gitignore ignores,
    a path that resolves somewhere else (8.3 short name, junction, symlink),
    and an existing live file no installed release owns - or ANY existing
    file when there is no ownership baseline at all - refuse the update."""
    root = Path(root).resolve()
    _check_not_ignored(IgnoreRules.for_install(root), (f.path for f in staged.manifest.files))
    installed = read_installed(root)
    owned = installed.get("files") if installed else None
    changed, created, unchanged, modified = [], [], [], []
    pre: Dict[str, str] = {}
    for entry in staged.manifest.files:
        live = _live_path(root, entry.path)
        alias = live_alias(root, entry.path)
        if alias is not None:
            # Every allow / deny decision was made on the requested name; a
            # different landing path voids all of them.
            raise PayloadPathError(f"{entry.path!r} resolves to {alias!r} (8.3 short name, "
                                   "junction or symlink); refusing the whole update")
        if os.path.islink(live) or (live.exists() and not live.is_file()):
            raise PayloadPathError(f"live path is not a regular file: {entry.path!r}")
        if live.is_file():
            sha, _ = _hash_file(live)
            if sha == entry.sha256:
                unchanged.append(entry.path)
                continue
            if owned is None:
                raise PayloadPathError(
                    f"{entry.path!r} exists in the install and there is no ownership "
                    f"baseline (no installed record, no shipped {INSTALLED_MANIFEST}): only "
                    "new files may be created; refusing the whole update")
            if entry.path not in owned:
                raise PayloadPathError(
                    f"{entry.path!r} exists in the install but no installed release owns it "
                    "(user or runtime state); refusing the whole update")
            pre[entry.path] = sha
            if owned is not None and owned.get(entry.path) not in (None, sha):
                modified.append(entry.path)
        else:
            created.append(entry.path)
        changed.append(entry.path)
    active = hot_reload_watching(root) if hot_reload_active is None else hot_reload_active
    orphaned = sorted(set(owned or {}) - set(staged.manifest.file_map()))
    return ApplyPlan(version=staged.version, changed=tuple(changed), created=tuple(created),
                     unchanged=tuple(unchanged), pre_hashes=tuple(sorted(pre.items())),
                     modified_locally=tuple(modified), orphaned=tuple(orphaned), removed=(),
                     restart=classify_paths(changed, hot_reload_active=active))


def _read_deploy_key(path: Path) -> bytes:
    """Same rules as ops/rc_transactional_deploy.py:94 `_read_key`."""
    try:
        key = Path(path).read_text(encoding="ascii").strip()
    except FileNotFoundError:
        raise DeployKeyError("no deploy key provisioned - refusing (fail closed)") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise DeployKeyError(f"deploy key unreadable: {type(exc).__name__}") from None
    if len(key) < 32:
        raise DeployKeyError("deploy key too short (need >= 32 hex chars)")
    return key.encode("ascii")


def sign_request(req: Dict[str, Any], key: bytes) -> Dict[str, Any]:
    """HMAC-SHA256 over the canonical JSON, byte-compatible with
    ops/rc_transactional_deploy.py:88 `_canonical` + :125 `sign_request`."""
    body = {k: v for k, v in req.items() if k != "signature"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True).encode("ascii")
    return dict(body, signature=hmac.new(key, canonical, hashlib.sha256).hexdigest())


def _window() -> Dict[str, float]:
    """The signed validity window the worker enforces
    (ops/rc_transactional_deploy.py check_freshness). Real wall clock, never
    an injected one: the worker compares it with its own."""
    issued = time.time()
    return {"issued_at": issued, "expires_at": issued + REQUEST_TTL_S}


def _request_id(kind: str, version: Any, now: Callable[[], float]) -> str:
    ver = version if isinstance(version, str) and VERSION_RE.match(version) else "none"
    return f"launcher-{kind}-{ver}-{int(now() * 1000)}-{secrets.token_hex(3)}"


def _submit(root: Path, state: Dict[str, Any], pending: Dict[str, Any],
            req: Dict[str, Any], key: bytes) -> Path:
    """Record the pending op, then drop the signed request where the frozen
    supervisor polls (ops/rc_supervisor.py:714 deploy_requests/, :1424)."""
    path = runtime_dir(root) / "deploy_requests" / f"{req['request_id']}.json"
    state = dict(state, pending=pending)
    _write_state(root, state)
    try:
        _write_json(path, sign_request(req, key))
    except BaseException:
        _write_state(root, dict(state, pending=None))
        raise
    return path


def apply(root: Path, version: str, *,
          game_check: Optional[Callable[[], Optional[str]]] = None,
          key_path: Optional[Path] = None, hot_reload_active: Optional[bool] = None,
          now: Callable[[], float] = time.time) -> ApplyResult:
    """Re-verify the staged `version` and hand it to the supervisor's
    transactional deploy as a signed request. Deferred (GameLiveError)
    while a game is live; nothing is written then."""
    root = _install_root(root)
    state = read_state(root)
    if state.get("pending"):
        raise StateError("an update operation is pending; call finish() first")
    staged = verify_staged(root, version)
    plan = plan_apply(root, staged, hot_reload_active=hot_reload_active)
    if not plan.changed:
        # Nothing to deploy, but the record and state are still writes: the
        # game check comes first on this path too.
        _check_game(root, game_check)
        _record_installed(root, version, staged.manifest_sha256,
                          {f.path: f.sha256 for f in staged.manifest.files},
                          request_id=None, backup_root=None, pre_hashes={}, created=[])
        _write_state(root, dict(state, pending=None, last={
            "kind": "apply", "version": version, "status": "noop", "at": utc_now()}))
        return ApplyResult("noop", None, None, plan)
    key = _read_deploy_key(key_path or deploy_key_path(root))
    _check_game(root, game_check)
    shas = staged.manifest.file_map()
    request_id = _request_id("update", version, now)
    req = {
        "request_id": request_id,
        "project_root": str(root),
        "staging_root": str(staged.payload),
        "files": [{"live": rel, "staged": rel, "sha256": shas[rel].sha256}
                  for rel in plan.changed],
        "force_restart": plan.restart.app == "restart",
        "health_timeout_seconds": HEALTH_TIMEOUT_S,
        "requested_by": "ops/launcher/updater.py",
        "requested_at": utc_now(),
        **_window(),
        "update": {"kind": "apply", "version": version,
                   "manifest_sha256": staged.manifest_sha256,
                   "level": plan.restart.level, "services": list(plan.restart.services)},
    }
    pending = {"kind": "apply", "request_id": request_id, "version": version,
               "manifest_sha256": staged.manifest_sha256, "requested_at": now(),
               "files": {f.path: f.sha256 for f in staged.manifest.files},
               "pre_hashes": dict(plan.pre_hashes), "created": list(plan.created),
               "restart": plan.restart.to_dict(),
               "run_id_before": app_health(root)["run_id"]}
    path = _submit(root, state, pending, req, key)
    return ApplyResult("requested", request_id, path, plan)


def _record_installed(root: Path, version: Optional[str], manifest_sha: Optional[str],
                      files: Dict[str, str], *, request_id: Optional[str],
                      backup_root: Optional[str], pre_hashes: Dict[str, str],
                      created: List[str]) -> None:
    prior = read_installed(root)
    previous = None
    if prior is not None:
        previous = {"version": prior.get("version"), "files": prior.get("files") or {},
                    "manifest_sha256": prior.get("manifest_sha256")}
    _write_json(installed_record_path(root), {
        "schema": SCHEMA, "version": version, "manifest_sha256": manifest_sha,
        "files": files, "applied_at": utc_now(), "request_id": request_id,
        "backup_root": backup_root, "pre_hashes": pre_hashes, "created": created,
        "previous": previous})


def _quarantine(root: Path, rec: Dict[str, Any], now: Callable[[], float]) -> Dict[str, list]:
    """Move (never delete) the files an update created, when they still hold
    the bytes the update wrote. Changed since = not ours: left in place.
    The record is state on disk, so nothing it says becomes a path unchecked:
    the folder label is the version only when it is a version, and every
    destination is proven to sit inside the install root."""
    root = Path(root).resolve()
    ver = rec.get("version")
    label = ver if isinstance(ver, str) and VERSION_RE.match(ver) else "unversioned"
    qdir = (launcher_state_dir(root) / "quarantine" /
            f"{label}-{int(now())}-{secrets.token_hex(3)}").resolve()
    if root not in qdir.parents:
        raise PayloadPathError("the quarantine folder would leave the install root")
    files = rec.get("files") or {}
    moved, kept = [], []
    for rel in rec.get("created") or []:
        check_payload_path(rel)
        live = _live_path(root, rel)
        if not live.is_file():
            continue
        if live_alias(root, rel) is not None or _hash_file(live)[0] != files.get(rel):
            kept.append(rel)
            continue
        dst = _live_path(qdir, rel).resolve()
        if qdir not in dst.parents:
            raise PayloadPathError(f"quarantine destination escapes its folder: {rel!r}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        _replace_with_retry(live, dst)
        moved.append(rel)
    return {"moved": moved, "kept": kept}


def _restore_previous(root: Path, rec: Dict[str, Any]) -> None:
    prev = rec.get("previous") or {}
    _write_json(installed_record_path(root), {
        "schema": SCHEMA, "version": prev.get("version"),
        "manifest_sha256": prev.get("manifest_sha256"), "files": prev.get("files") or {},
        "applied_at": utc_now(), "request_id": None, "backup_root": None,
        "pre_hashes": {}, "created": [], "previous": None,
        "rolled_back_from": rec.get("version")})


def finish(root: Path, *, now: Callable[[], float] = time.time) -> FinishResult:
    """Collect the supervisor's result for the pending operation (its
    deploy_results/<stem>.json, ops/rc_supervisor.py:1449) and record it."""
    root = _install_root(root)
    state = read_state(root)
    pending = state.get("pending")
    if not isinstance(pending, dict):
        return FinishResult("none")
    rid = str(pending.get("request_id"))
    kind, version = pending.get("kind"), pending.get("version")
    restart = pending.get("restart")
    before = pending.get("run_id_before")
    rt = runtime_dir(root)
    result_path = rt / "deploy_results" / f"{rid}.json"
    if not result_path.is_file():
        queued = any((rt / "deploy_requests" / f"{rid}{ext}").exists()
                     for ext in (".json", ".deploying"))
        if queued or now() - float(pending.get("requested_at") or 0) < LOST_AFTER_S:
            return FinishResult("pending", kind, version, restart, None, before)
        # Lost: the supervisor removed the request with no result - e.g. it
        # killed the worker at 120 s, possibly mid-copy. Live may be mixed.
        _write_state(root, dict(state, pending=None, last={
            "kind": kind, "version": version, "status": "lost", "request_id": rid,
            "at": utc_now()}))
        return FinishResult("lost", kind, version, restart, None, before)
    try:
        result = _read_json(result_path)
    except (OSError, ValueError):
        return FinishResult("pending", kind, version, restart, None, before)   # torn read
    result = result if isinstance(result, dict) else {}
    summary = {"phase": result.get("phase"), "rollback": result.get("rollback"),
               "error": str(result.get("error"))[:240] if result.get("error") else None}
    if result.get("ok") is True:
        status = "ok"
        if kind == "rollback":
            rec = _read_record_file(root) or {}
            summary["quarantine"] = _quarantine(root, rec, now)
            _restore_previous(root, rec)
        else:
            _record_installed(root, version, pending.get("manifest_sha256"),
                              pending.get("files") or {}, request_id=rid,
                              backup_root=result.get("backup_root"),
                              pre_hashes=pending.get("pre_hashes") or {},
                              created=list(pending.get("created") or []))
    else:
        status = "failed"
    _write_state(root, dict(state, pending=None, last=dict(
        summary, kind=kind, version=version, status=status, request_id=rid, at=utc_now())))
    return FinishResult(status, kind, version, restart, summary, before)


def _verified_backup(root: Path, rec: Dict[str, Any]) -> Path:
    """The worker's backup of the files the last update overwrote, proven
    to hold the bytes recorded before that update. The worker writes it to
    ops/backups/<stamp>-<id> (ops/rc_transactional_deploy.py:557); a path
    anywhere else is refused."""
    backups = (root / "ops" / "backups").resolve()
    raw = rec.get("backup_root")
    broot = Path(raw).resolve() if isinstance(raw, str) and raw else None
    if broot is None or broot == backups or backups not in broot.parents:
        raise PayloadPathError("the recorded backup is not under ops/backups")
    for rel, sha in sorted((rec.get("pre_hashes") or {}).items()):
        check_payload_path(rel)
        src = _live_path(broot, rel)
        if not src.is_file() or src.is_symlink():
            raise IntegrityError(f"backup file missing: {rel!r}")
        if not hmac.compare_digest(_hash_file(src)[0], str(sha)):
            raise IntegrityError(f"backup file changed since the update: {rel!r}")
    return broot


def app_health(root: Path, *, now: Optional[float] = None) -> Dict[str, Any]:
    """main.py's heartbeat (ops/runtime/health.json): `alive` only when the
    file is fresh and says alive. PKG-6 compares `run_id` across an update."""
    path = runtime_dir(root) / "health.json"
    try:
        age = (time.time() if now is None else now) - path.stat().st_mtime
        doc = _read_json(path)
    except (OSError, ValueError):
        return {"alive": False, "run_id": None, "age_s": None}
    doc = doc if isinstance(doc, dict) else {}
    return {"alive": bool(age <= HEALTH_FRESH_S and doc.get("alive")),
            "run_id": str(doc.get("run_id") or "") or None, "age_s": round(age, 1)}


def recover(root: Path, *, now: Callable[[], float] = time.time) -> Dict[str, Any]:
    """The app does not come back healthy after an update. rollback() cannot
    help then: the supervisor starts a deploy only while the app is healthy
    (ops/rc_supervisor.py:1421). Its OWN rollback request needs no healthy
    app (ops/rc_supervisor.py:1306 -> _do_rollback :1327: stop the app,
    restore the NEWEST ops/backups dir, start the app), so this writes, in
    the supervisor's sorted processing order (:1281), a circuit-breaker reset
    (:1315; a tripped breaker refuses start_app, :920) and then that
    rollback - or a restart when the update overwrote nothing. Refused when
    a later backup exists (the supervisor would restore that one instead) or
    when the backup's bytes changed. Not game-gated: the app is already
    down. Files the update created are quarantined; the record steps back."""
    root = _install_root(root)
    state = read_state(root)
    if state.get("pending"):
        raise StateError("an update operation is pending; call finish() first")
    rec = _read_record_file(root)
    if not rec or not isinstance(rec.get("previous"), dict):
        raise StateError("no recovery point: no update has been applied")
    kinds = ["reset_circuit_breaker"]
    if rec.get("pre_hashes"):
        broot = _verified_backup(root, rec)
        newest = sorted((d for d in broot.parent.iterdir() if d.is_dir()), reverse=True)[0]
        if newest.resolve() != broot:
            raise StateError("a later backup exists; the supervisor's rollback would restore "
                             "it instead of this update's")
        kinds.append("rollback")
    else:
        kinds.append("restart")
    moved = _quarantine(root, rec, now)
    stamp = int(now() * 1000)
    written = []
    for i, kind in enumerate(kinds, 1):
        path = runtime_dir(root) / "supervisor_requests" / \
            f"launcher-recover-{stamp}-{i}-{kind}.json"
        _write_json(path, {"type": kind, "reason": f"launcher-recover:{rec.get('version')}",
                           "requested_by": "ops/launcher/updater.py",
                           "requested_at": utc_now()})
        written.append(str(path))
    _restore_previous(root, rec)
    _write_state(root, dict(state, pending=None, last={
        "kind": "recover", "version": rec.get("version"), "status": "requested",
        "requests": written, "quarantine": moved, "at": utc_now()}))
    return {"status": "requested", "requests": written, "quarantine": moved,
            "to_version": rec["previous"].get("version")}


def rollback(root: Path, *, game_check: Optional[Callable[[], Optional[str]]] = None,
             key_path: Optional[Path] = None, hot_reload_active: Optional[bool] = None,
             now: Callable[[], float] = time.time) -> ApplyResult:
    """Undo the last applied update: re-deploy the worker's backup of every
    file it overwrote (each checked against the sha256 recorded before the
    update) and, once that lands, quarantine the files it created. One level
    only. Deferred while a game is live."""
    root = _install_root(root)
    state = read_state(root)
    if state.get("pending"):
        raise StateError("an update operation is pending; call finish() first")
    rec = _read_record_file(root)
    if not rec or not isinstance(rec.get("previous"), dict):
        raise StateError("no rollback point: no update has been applied")
    pre = rec.get("pre_hashes") or {}
    created = [check_payload_path(r) for r in rec.get("created") or []]
    broot = _verified_backup(root, rec) if pre else None
    files = [{"live": rel, "staged": rel, "sha256": sha} for rel, sha in sorted(pre.items())]
    active = hot_reload_watching(root) if hot_reload_active is None else hot_reload_active
    restart = classify_paths(sorted(pre) + created, hot_reload_active=active)
    prev_version = rec["previous"].get("version")
    plan = ApplyPlan(version=prev_version, changed=tuple(sorted(pre)), created=(),
                     unchanged=(), pre_hashes=(), modified_locally=(), orphaned=(),
                     removed=tuple(created), restart=restart)
    if not files:
        _check_game(root, game_check)
        moved = _quarantine(root, rec, now)
        _restore_previous(root, rec)
        _write_state(root, dict(state, pending=None, last={
            "kind": "rollback", "version": rec.get("version"), "status": "done",
            "quarantine": moved, "at": utc_now()}))
        return ApplyResult("done", None, None, plan)
    key = _read_deploy_key(key_path or deploy_key_path(root))
    _check_game(root, game_check)
    request_id = _request_id("rollback", rec.get("version"), now)
    req = {
        "request_id": request_id,
        "project_root": str(root),
        "staging_root": str(broot),
        "files": files,
        "force_restart": restart.app == "restart",
        "health_timeout_seconds": HEALTH_TIMEOUT_S,
        "requested_by": "ops/launcher/updater.py",
        "requested_at": utc_now(),
        **_window(),
        "update": {"kind": "rollback", "version": rec.get("version"),
                   "to_version": prev_version, "level": restart.level,
                   "services": list(restart.services)},
    }
    pending = {"kind": "rollback", "request_id": request_id, "version": rec.get("version"),
               "to_version": prev_version, "requested_at": now(),
               "restart": restart.to_dict(),
               "run_id_before": app_health(root)["run_id"]}
    path = _submit(root, state, pending, req, key)
    return ApplyResult("requested", request_id, path, plan)


# ------------------------------------------------------------------- CLI


def _source(spec: str) -> Source:
    if spec.startswith("local:"):
        return LocalSource(Path(spec[len("local:"):]))
    if spec == "github":
        return GitHubSource()
    if spec.startswith("github:") and spec.count("/") == 1:
        owner, repo = spec[len("github:"):].split("/")
        return GitHubSource(owner, repo)
    raise UpdateError("source must be local:<dir>, github or github:<owner>/<repo>")


def _run(args: argparse.Namespace) -> Dict[str, Any]:
    root = Path(args.root)
    if args.cmd == "classify":
        return {"ok": True, "restart": classify_paths(args.paths).to_dict()}
    if args.cmd == "status":
        return {"ok": True, "installed": installed_version(root), "state": read_state(root)}
    if args.cmd == "check":
        current = installed_version(root)
        rel = check(_source(args.source), channel=args.channel, current_version=current)
        return {"ok": True, "current": current, "available": rel.to_dict() if rel else None}
    if args.cmd == "stage":
        src = _source(args.source)
        staged = stage(root, src, src.release(args.version), channel=args.channel,
                       pin_sha256=args.pin, shell_version=args.shell_version)
        return {"ok": True, "version": staged.version,
                "manifest_sha256": staged.manifest_sha256}
    if args.cmd == "apply":
        return dict(apply(root, args.version).to_dict(), ok=True)
    if args.cmd == "finish":
        return dict(finish(root).to_dict(), ok=True)
    if args.cmd == "recover":
        return dict(recover(root), ok=True)
    return dict(rollback(root).to_dict(), ok=True)


def main(argv: Optional[List[str]] = None) -> int:
    """One JSON line on stdout. Exit 0 ok, 1 refused (`code` names why),
    3 deferred because a game is live."""
    ap = argparse.ArgumentParser(prog="updater",
                                 description="Amberstone backend updater (PKG-2).")
    ap.add_argument("--root", default=str(DEFAULT_ROOT), help="backend root")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "stage"):
        p = sub.add_parser(name)
        p.add_argument("--source", required=True,
                       help="local:<dir>, github or github:<owner>/<repo>")
        p.add_argument("--channel", choices=CHANNELS, default="stable")
        if name == "stage":
            p.add_argument("--version", required=True)
            p.add_argument("--pin", default=None, help="expected manifest sha256")
            p.add_argument("--shell-version", default=None)
    sub.add_parser("apply").add_argument("--version", required=True)
    sub.add_parser("finish")
    sub.add_parser("rollback")
    sub.add_parser("recover")
    sub.add_parser("status")
    sub.add_parser("classify").add_argument("paths", nargs="*")
    args = ap.parse_args(argv)
    try:
        out, code = _run(args), 0
    except GameLiveError as exc:
        out, code = {"ok": False, "code": exc.code, "error": str(exc)}, 3
    except UpdateError as exc:
        out, code = {"ok": False, "code": exc.code, "error": str(exc)}, 1
    print(json.dumps(out, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
