"""RM-258 + RM-261 - no runtime module may hand-roll an atomic write.

RM-258: roughly 45 runtime writers finished a tmp+rename with a BARE replace
(no WinError 5 retry), and the repo carried three separate hardened
implementations with nothing forcing a writer onto one of them - so every new
polled writer started bare by default. RM-261: ~96 modules built their scratch
file from the DESTINATION alone (`<dest>.tmp`), the shared-scratch collision
RM-254 fixed inside core/polled_json.

The two rows are the same population of writers, so one guard covers both
spellings of the rename and every destination-derived scratch name:

  Rule R (rename):  `os.replace(a, b)` and the one-positional-argument
                    `x.replace(y)` (Path.replace - the spelling CLAUDE.md's
                    own atomic-write rule prescribes, and the one a plain
                    `grep os.replace` misses).
  Rule S (scratch): `.with_suffix(...)` / `.with_name(...)` / `str + ...` /
                    an f-string whose literal tail ends in `.tmp` with no
                    per-writer component (getpid / token / uuid) in it.

Either fires ONLY inside a SANCTIONED implementation, listed below with the
reason it may not import core.polled_json. Everything else routes through
core.polled_json.atomic_write_json / _text / _bytes. A row is keyed on the
enclosing function, never a line number: its bare name, or its dotted
qualname (`HostLog.write`) when the bare name is too generic to key a file on.
There is no directory or package sanction on purpose - it would let every new
writer in that tree start bare, the RM-258 failure itself.

SCOPE: every tracked .py via tests/_repo_walk (ADR-015) EXCEPT the one-shot
generator trees the rows themselves allowlist (`scripts/`, `ops/audit/`,
`Share/`, `lib/`), plus `tests/`, `docs/`, `oss/` (the extracted package IS
an implementation and is drift-pinned to core/polled_json by
tests/test_oss_win32_atomic_io_drift.py) and `ops/fleet_kit/` (vendored
byte-for-byte; a local edit fails its MANIFEST). tools/ is in scope except
the row's own `tools/*extract*` allowlist, tools/tests/ and the named
`_TOOLS_UNCLASSIFIED` baseline, which only shrinks. The two separate-process
agents under tools/ that RM-258 names are long-running ONLOGON tasks, not
generators, and they and the tools/ watchers converted since stay pinned in
`_RUNTIME_TOOLS`.
"""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, iter_repo_files, relative_posix, self_check

_EXCLUDED_PREFIXES = (
    "tests/",
    "docs/",
    "oss/",
    "scripts/",
    "ops/audit/",
    "ops/fleet_kit/",
    "Share/",
    "lib/",
)

# Long-running separate-process agents that live under tools/ (RM-258 names
# both), plus each tools/ watcher converted onto core.polled_json since, so
# the conversion stays pinned: never an extractor, never unclassified.
_RUNTIME_TOOLS = frozenset({
    "tools/lcu_agent.py",
    "tools/hotkey_listener.py",
    # RC-CostHealthWatchdog, every 15 min; --remediate rewrites
    # config/coach_settings.json, which the running app reads.
    "tools/cost_health_watchdog.py",
    # RC-CIWatchdog: the run-id sentinel and the 2-strike attempt counters
    # are read back on every poll, and a torn read parses as 0.
    "tools/ci_watchdog.py",
    # The progress watcher's own state file is its first-sight baseline;
    # a torn read re-baselines every task and drops a pending alert.
    "tools/progress_watch.py",
    # The spec / patch watch state is the only record of what was already
    # posted; a torn read re-baselines (drops a change) or reposts one.
    "tools/spec_watch.py",
    # One-shot per DS batch, but --record rewrites the live patch's
    # manifest.json in place, which the running DS process reads
    # (agents/daemon_slayer/data_loader.py), and --ack the tracked
    # high-water file.
    "tools/ds_feed_watch.py",
    # The session counter in the hand-off (read by the SessionStart hook)
    # and the headless progress fallback (read by the lane widget and the
    # board): a torn read loses the counter or a checklist row.
    "tools/session_checklist.py",
    # The inbox responder's answered record, read back on every
    # RC-InboxResponder tick: a torn read fails closed and the responder
    # answers nothing until a human repairs the file.
    "tools/inbox_responder.py",
    # The SessionStart / UserPromptSubmit hook (and an import of the
    # long-lived inbox poller and responder runner): the per-session
    # reported record is read back on every fire, and a torn read fails
    # open and re-prints the inbox block.
    "tools/rc_facts.py",
    # The RC-InboxResponder runner, fired every tick: its state records are
    # read back on the next fire, and its bounce and reply land in a
    # sibling's polled inbox under a hidden per-writer `_<file>.<pid>.<hex>.tmp`.
    "tools/inbox_responder_runner.py",
    # The LCU WAMP phase watcher (a long-running loop, installed as an
    # at-logon task by tools/phase_watcher_install.ps1): one JSON sidecar per
    # captured phase event under data/event_captures/, which
    # core/data_retention.py prunes; a failed write used to leave a torn
    # sidecar or a stray destination-derived .tmp.
    "tools/phase_watcher.py",
    # RC-MoonSyncPoller (at logon, a long-running loop) plus its --ping
    # UserPromptSubmit hook: status.md and findings.json are read by
    # --status and /api/moon-sync-status while the poller rewrites them,
    # and poller_seen.json is read back on every poll.
    "tools/moon_sync_poller.py",
    # RC-UpstreamDriftCheck (a daily scheduled task): the sentinel is read
    # back on every run, and the drift alerts are read by tools/rc_facts.py
    # at session start while the task may be rewriting them (RM-514).
    "tools/upstream_drift_check.py",
    # The Claude Stop hook, fired on every main-session and sub-agent Stop:
    # its report and seen set are read back by the next Stop (the seen set
    # decides what is surfaced again), and parallel sub-agents of one session
    # can stop in the same instant, so a shared `<dest>.tmp` could interleave.
    "tools/stop_claim_gate.py",
})

# RM-258 residual (s144): tools/ is IN scope by default. Out of scope are the
# one-shot extractors the row itself allowlists (`tools/*extract*`), tools/
# test code, and the files below - every tools/ module that offended when the
# blanket tools/ exemption was narrowed (measured 2026-10-27: 100 renames + 82
# scratch names across 77 files, 6 of them extractors). Each entry is
# UNCLASSIFIED, not proven one-shot: it leaves this set by converting onto
# core.polled_json (then it joins _RUNTIME_TOOLS if it is long-running) or by
# a named one-shot proof (no scheduled task, no poller, no reader racing it).
# The set only shrinks: a new tools/ writer starts guarded, and an entry that
# stops offending fails test_tools_baseline_is_exact until it is dropped.
_TOOLS_UNCLASSIFIED = frozenset({
    "tools/ascii_escape_py.py",
    "tools/build_portable.py",
    "tools/build_python_embed.py",
    "tools/build_third_party_notices.py",
    "tools/champion_loadout_autogen.py",
    "tools/champion_loadout_cleanup_pollution_item213.py",
    "tools/champion_loadout_collapse_to_paths.py",
    "tools/champion_loadout_sweep_item_s8.py",
    "tools/champion_loadout_validate_meta.py",
    "tools/compare_101qq_vs_ddragon.py",
    "tools/console_flash_attribute.py",
    "tools/daemon_slayer_build_orders_generate.py",
    "tools/daemon_slayer_pickban_targets_generate.py",
    "tools/ddragon_mirror_refresh.py",
    "tools/ds_cross_eval/probe_champion.py",
    "tools/ds_cross_eval/run_all.py",
    "tools/ds_parity_map.py",
    "tools/ds_parity_run.py",
    "tools/ds_patch_diff.py",
    "tools/gen_archmap.py",
    "tools/gen_state_schema.py",
    "tools/hotfix_kaisa_aram_ashe_sr_item263.py",
    "tools/hotfix_ranged_only_melee_loadouts.py",
    "tools/hotfix_sibling_pollution_item269.py",
    "tools/hotfix_thin_aram_adc_item275.py",
    "tools/hotfix_thin_aram_pollution_item276.py",
    "tools/hotfix_zaahen_loadout_item277.py",
    "tools/hz_mismatch_diagnose.py",
    "tools/hz_shadow_arena_contamination.py",
    "tools/ladder_role_scout.py",
    "tools/laning_verdict_information_probe.py",
    "tools/package_portable.py",
    "tools/regen_ranged_marksman_builds_item213.py",
    "tools/repair_mojibake.py",
    "tools/repin_subagent_cli.py",
    "tools/replay_build_order_validate.py",
    "tools/replay_laning_verdict_validate.py",
    "tools/replay_matchup_validate.py",
    "tools/replay_pickban_validate.py",
    "tools/replay_roster_pull.py",
    "tools/rewrite_sha_citations.py",
    "tools/rofl_dedupe.py",
    "tools/sanitize_agent6_reports.py",
    "tools/shadow_archive_split.py",
    "tools/slot_bucket_audit.py",
    "tools/strip_em_dashes.py",
    "tools/strip_smart_quotes.py",
    "tools/strip_u2500.py",
    "tools/tft_cv_accuracy.py",
    "tools/timeline_ingest.py",
    "tools/vision_atlas_validate.py",
    "tools/web_ascii_sweep.py",
})


def _is_tools_extractor(rel: str) -> bool:
    return rel.startswith("tools/") and "extract" in rel.rsplit("/", 1)[-1]

# (relpath, enclosing function or its dotted qualname) -> why this
# implementation may not import core.polled_json. Each must itself use a
# per-writer scratch name, a bounded WinError 5 retry and fsync (asserted for
# the ops trio in tests/test_ops_atomic_writers_rm261.py and for the launcher
# below).
SANCTIONED = {
    ("core/polled_json.py", "_replace_with_retry"):
        "the canonical implementation every other writer routes through",
    ("ops/rc_supervisor.py", "_replace_with_retry"):
        "FROZEN watchdog: stdlib-only by design so a broken app package "
        "cannot take the process that restarts it down with it",
    ("ops/rc_dev_runtime.py", "_atomic_write_json"):
        "FROZEN runtime host: stdlib-only heartbeat writer with its own "
        "measured retry budget (tests/test_rc_dev_runtime_atomic_write_retry.py)",
    ("ops/rc_transactional_deploy.py", "_replace_with_retry"):
        "deploy transaction runs while the app tree is being swapped, so it "
        "must not import from the tree it is replacing",
    ("tools/phase_watcher.py", "_replace_with_retry"):
        "RC-PhaseWatcher is served standalone to its agent directory with no "
        "repo above it (tools/phase_watcher_install.ps1), so it cannot import "
        "core/ - the same constraint tests/test_tls_floor_rm752.py pins for "
        "its TLS floor. Its write_sidecar meets the three requirements, "
        "asserted by test_phase_watcher_writer_meets_the_sanction_contract "
        "below: a <name>.<pid>.<token>.tmp scratch, flush + fsync before the "
        "rename, a bounded PermissionError (WinError 5) retry, and the "
        "scratch removed when the rename fails for good",
    ("tools/moon_sync_poller.py", "_replace_with_retry"):
        "RC-MoonSyncPoller is the only process watching the cross-repo "
        "channel, so nothing from core/ may join its import path (an "
        "import-time fault there would kill every poller restart; its own "
        "comment above _replace_with_retry), and its --ping hook must run in "
        "a copy without RC's modules (MAIN 1254 #17). Its _atomic_write meets "
        "the three requirements, asserted by "
        "test_moon_sync_poller_writer_meets_the_sanction_contract below: a "
        "<name>.<pid>.<token>.tmp scratch, flush + fsync before the rename, a "
        "bounded PermissionError (WinError 5) retry, and the scratch removed "
        "when the rename fails for good",
    ("tools/stop_claim_gate.py", "_replace_with_retry"):
        "the Claude Stop hook is PORTABLE and stdlib-only on purpose: a copy "
        "runs at any depth in another tree with no RC package above it (MAIN "
        "1254 #9, tests/test_stop_claim_gate_portable_main1254.py), so it "
        "cannot import core/. Its _atomic_write (the report, the history "
        "roll and the seen set) meets the three requirements, asserted by "
        "test_stop_claim_gate_writer_meets_the_sanction_contract below: a "
        "<name>.<pid>.<token>.tmp scratch, flush + fsync before the rename, a "
        "bounded PermissionError (WinError 5) retry, and the scratch removed "
        "when the rename fails for good. prune_seen's move of a stale seen "
        "file into pruned/ (a rename of an existing file, no payload) goes "
        "through the same helper",
    ("core/log_rotation.py", "try_rotate"):
        "log ROTATION, not an atomic write (RM-718 a), checked against the "
        "three requirements above. Per-writer scratch: yes - "
        "<name>.rotating/.dropping.<pid>.<token>, and orphans from a crash are "
        "recovered, never overwritten. WinError 5 retry: deliberately none in "
        "the call - the refusal here is not a reader's millisecond poll but "
        "another process holding the log open for its lifetime (measured "
        "2026-10-25 as WinError 32, a sharing violation, RM-864 c), so an "
        "in-call retry only stalls the logging call that triggered the "
        "rollover; the bounded retry is one level up (the handler re-attempts "
        "after _RETRY_AFTER_S, the one-shot writer on its next run), and a "
        "refusal rolls the applied renames back, best effort and no-clobber (a "
        "refused roll-back rename leaves its file one slot higher or under a "
        "scratch name recover_orphans() preserves). fsync: nothing to "
        "flush - it only renames existing files, it writes no payload. It "
        "may not use core.polled_json because those helpers write a payload "
        "to a destination; there is no payload here",
    ("ops/launcher/service_host.py", "_replace_with_retry"):
        "PKG-1 launcher service host: stdlib-only and run under `python -I` "
        "with no RC module on sys.path, because it starts and stops the "
        "backend core.polled_json belongs to (docs/PACKAGING_PLAN.md 3.1). "
        "Its atomic_write_json meets the three requirements, asserted by "
        "test_launcher_writer_meets_the_sanction_contract below: a "
        "<dest>.<pid>.<token>.tmp scratch, flush + fsync before the rename, "
        "a bounded PermissionError (WinError 5) retry, and the scratch "
        "removed when the rename fails for good",
    ("ops/launcher/service_host.py", "HostLog.write"):
        "log ROTATION, not an atomic write (the core/log_rotation.py "
        "try_rotate class), in the same stdlib-only launcher, checked against "
        "the three requirements. fsync: nothing to flush - the rename moves "
        "an existing file and writes no payload. WinError 5 retry: none in "
        "the call - a refused rename (a reader holding the log or its `.1` "
        "open) is swallowed, the line still appended, and the next write "
        "re-checks the size and re-attempts, so the retry is one level up "
        "and the log outgrows LOG_MAX_BYTES only while that holder stays. "
        "Per-writer scratch: none - the target is the fixed `.1` slot. The "
        "host is single-writer under HostLock except main()'s two pre-lock "
        "lines (bad manifest, lock refused), so a second launch crossing the "
        "size threshold in the same instant as the live host can replace "
        "`.1` with a one-line file: one lost older generation, never torn "
        "bytes (residual reported for the PKG-1b slice)",
    ("ops/launcher/updater.py", "_replace_with_retry"):
        "PKG-2 backend updater: stdlib-only and run under `python -I` with no "
        "RC module on sys.path, because it replaces the backend tree "
        "core.polled_json belongs to (docs/PACKAGING_PLAN.md 3.4) - the same "
        "reason as the ops/rc_transactional_deploy.py row. Its _write_json / "
        "_write_bytes_atomic meet the three requirements, asserted by "
        "test_launcher_writer_meets_the_sanction_contract below: a "
        "<dest>.<pid>.<token>.tmp scratch, flush + fsync before the rename, "
        "a bounded PermissionError (WinError 5) retry, and the scratch "
        "removed when the rename fails for good. The same helper also moves "
        "the updater's own staging and quarantine entries (renames of whole "
        "existing files and directories inside ops/runtime/, no payload)",
}

_PER_WRITER_HINTS = ("getpid", "token", "uuid", "pid")


def _in_scope(rel: str) -> bool:
    if rel in _RUNTIME_TOOLS:
        return True
    if rel.startswith("tools/"):
        return not (rel.startswith("tools/tests/") or _is_tools_extractor(rel)
                    or rel in _TOOLS_UNCLASSIFIED)
    return not rel.startswith(_EXCLUDED_PREFIXES)


def _runtime_files() -> list[tuple[str, Path]]:
    out = []
    for p in iter_repo_files(REPO_ROOT, ("*.py",)):
        rel = relative_posix(p)
        if _in_scope(rel):
            out.append((rel, p))
    return out


def _enclosing_functions(tree: ast.AST) -> dict[int, tuple[str, str]]:
    """node id -> (innermost enclosing function name, its dotted qualname).

    The qualname joins every enclosing class and function (`HostLog.write`),
    so a SANCTIONED row can name one method without exempting every
    same-named function in the file."""
    owner: dict[int, tuple[str, str]] = {}

    def visit(node: ast.AST, fn: str, qual: str, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            name, q, inner = fn, qual, scope
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = child.name
                q = scope + child.name
                inner = q + "."
            elif isinstance(child, ast.ClassDef):
                inner = scope + child.name + "."
            owner[id(child)] = (name, q)
            visit(child, name, q, inner)

    visit(tree, "<module>", "<module>", "")
    return owner


def _str_tail(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr) and node.values:
        last = node.values[-1]
        if isinstance(last, ast.Constant) and isinstance(last.value, str):
            return last.value
    return None


def _mentions_per_writer(node: ast.AST, src: str) -> bool:
    seg = (ast.get_source_segment(src, node) or "").lower()
    return any(h in seg for h in _PER_WRITER_HINTS)


def _is_rename(node: ast.Call) -> bool:
    f = node.func
    if not isinstance(f, ast.Attribute) or f.attr != "replace":
        return False
    if isinstance(f.value, ast.Name) and f.value.id == "os":
        return True
    # Path.replace(target): exactly one positional arg, no keywords. str.replace
    # always takes two, datetime.replace is keyword-only in practice.
    return (len(node.args) == 1 and not node.keywords
            and not isinstance(f.value, ast.Constant))


def _is_dest_derived_scratch(node: ast.AST, src: str) -> bool:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr in ("with_suffix", "with_name") and node.args:
        tail = _str_tail(node.args[0])
        if tail is None and isinstance(node.args[0], ast.BinOp):
            tail = _str_tail(node.args[0].right)
        return bool(tail and tail.endswith(".tmp")) and not _mentions_per_writer(node, src)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        tail = _str_tail(node.right)
        return bool(tail and tail.endswith(".tmp")) and not _mentions_per_writer(node, src)
    if isinstance(node, ast.JoinedStr):
        tail = _str_tail(node)
        return bool(tail and tail.endswith(".tmp")) and not _mentions_per_writer(node, src)
    return False


def scan(files=None, sanctioned=None) -> tuple[list[str], list[str]]:
    """Return (rename offenders, scratch-name offenders) as 'path:line fn'."""
    sanctioned = SANCTIONED if sanctioned is None else sanctioned
    renames: list[str] = []
    scratch: list[str] = []
    for rel, path in (files if files is not None else _runtime_files()):
        src = path.read_bytes().decode("utf-8")
        tree = ast.parse(src)
        owner = _enclosing_functions(tree)
        for node in ast.walk(tree):
            fn, qual = owner.get(id(node), ("<module>", "<module>"))
            if (rel, fn) in sanctioned or (rel, qual) in sanctioned:
                continue
            if isinstance(node, ast.Call) and _is_rename(node):
                renames.append(f"{rel}:{node.lineno} {fn}")
            elif _is_dest_derived_scratch(node, src):
                scratch.append(f"{rel}:{getattr(node, 'lineno', 0)} {fn}")
    # A with_suffix(x + ".tmp") matches as the call AND as its BinOp argument;
    # report each site once.
    return sorted(set(renames)), sorted(set(scratch))


@pytest.fixture(scope="module")
def offenders():
    self_check()
    files = _runtime_files()
    # Empty is never clean: the scope must still reach the writers this guard
    # exists for.
    rels = {r for r, _ in files}
    for anchor in ("coach_integration/_coach.py", "tools/lcu_agent.py",
                   "ops/rc_supervisor.py", "core/polled_json.py"):
        assert anchor in rels, f"guard scope lost {anchor}"
    return scan(files)


def test_rm258_no_runtime_module_hand_rolls_the_rename(offenders):
    renames, _ = offenders
    assert renames == [], (
        "bare tmp->rename outside a sanctioned implementation - route it "
        "through core.polled_json.atomic_write_json/_text/_bytes:\n  "
        + "\n  ".join(renames)
    )


def test_rm261_no_runtime_module_derives_its_scratch_name_from_the_destination(offenders):
    _, scratch = offenders
    assert scratch == [], (
        "destination-derived scratch name (shared by every writer of that "
        "file) - use core.polled_json, or a per-writer pid+token name:\n  "
        + "\n  ".join(scratch)
    )


def test_every_sanctioned_entry_still_exists():
    """A stale allowlist entry silently widens nothing today but hides a
    rename the day a function of that name reappears; keep it exact."""
    for rel, fn in SANCTIONED:
        tree = ast.parse((REPO_ROOT / rel).read_bytes().decode("utf-8"))
        owner = _enclosing_functions(tree)
        # Each def node owns itself, so this is every function's bare name
        # and dotted qualname.
        names = {v for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 for v in owner[id(n)]}
        assert fn in names, f"SANCTIONED entry {rel}:{fn} no longer exists"


@pytest.mark.parametrize("snippet, rename, scratch", [
    ("import os\ndef f(t, p):\n    os.replace(t, p)\n", 1, 0),
    ("def f(t, p):\n    t.replace(p)\n", 1, 0),
    ("def f(s):\n    return s.replace('a', 'b')\n", 0, 0),
    ("def f(p):\n    return p.with_suffix(p.suffix + '.tmp')\n", 0, 1),
    ("def f(p):\n    return p.with_suffix('.json.tmp')\n", 0, 1),
    ("def f(p):\n    return str(p) + '.tmp'\n", 0, 1),
    ("import os\ndef f(p):\n    return p.with_name(f'{p.name}.{os.getpid()}.tmp')\n", 0, 0),
])
def test_detector_positive_and_negative_controls(tmp_path, snippet, rename, scratch):
    f = tmp_path / "m.py"
    f.write_bytes(snippet.encode())
    r, s = scan([("core/m.py", f)])
    assert (len(r), len(s)) == (rename, scratch), (r, s)


def test_a_qualname_row_exempts_one_method_not_every_same_named_function(tmp_path):
    f = tmp_path / "m.py"
    f.write_bytes(b"import os\n"
                  b"class Log:\n"
                  b"    def write(self, a, b):\n"
                  b"        os.replace(a, b)\n"
                  b"def write(a, b):\n"
                  b"    os.replace(a, b)\n")
    r, _ = scan([("core/m.py", f)], sanctioned={("core/m.py", "Log.write"): "x"})
    assert r == ["core/m.py:6 write"]


def _launcher_writer(module: str):
    """(module, its atomic JSON writer) for each sanctioned launcher writer."""
    import importlib
    mod = importlib.import_module(f"ops.launcher.{module}")
    write = {"service_host": "atomic_write_json", "updater": "_write_json"}[module]
    return mod, getattr(mod, write)


def test_every_launcher_rename_row_has_a_contract_case():
    """A new ops/launcher _replace_with_retry row must join the contract test
    below, or the sanction rests on its reason string alone."""
    rows = {rel for rel, fn in SANCTIONED
            if rel.startswith("ops/launcher/") and fn == "_replace_with_retry"}
    assert rows == {f"ops/launcher/{m}.py" for m in _LAUNCHER_WRITERS}


_LAUNCHER_WRITERS = ("service_host", "updater")


@pytest.mark.parametrize("module", _LAUNCHER_WRITERS)
def test_launcher_writer_meets_the_sanction_contract(tmp_path, monkeypatch, module):
    """The ops/launcher rows are sanctioned on the three requirements, so
    they are asserted on the code, not on the reason string: a per-writer
    scratch name, fsync before the rename, a bounded WinError 5 retry and no
    scratch left behind when the rename fails for good."""
    sh, write = _launcher_writer(module)

    real_replace, real_fsync = os.replace, os.fsync
    events: list[str] = []
    scratch: list[str] = []

    def rec_replace(src, dst):
        events.append("replace")
        scratch.append(Path(src).name)
        return real_replace(src, dst)

    def rec_fsync(fd):
        events.append("fsync")
        return real_fsync(fd)

    monkeypatch.setattr(sh.os, "replace", rec_replace)
    monkeypatch.setattr(sh.os, "fsync", rec_fsync)
    monkeypatch.setattr(sh.time, "sleep", lambda _s: None)
    dest = tmp_path / "launcher_status.json"
    write(dest, {"n": 1})
    write(dest, {"n": 2})
    assert events == ["fsync", "replace", "fsync", "replace"]
    assert scratch[0] != scratch[1], scratch
    for name in scratch:
        assert name.startswith("launcher_status.json.") and name.endswith(".tmp")
        assert f".{os.getpid()}." in name, name

    refusals = [3]

    def flaky(src, dst):
        if refusals[0]:
            refusals[0] -= 1
            raise PermissionError(13, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(sh.os, "replace", flaky)
    write(dest, {"n": 3})
    assert json.loads(dest.read_text(encoding="ascii")) == {"n": 3}

    calls = [0]

    def refused(src, dst):
        calls[0] += 1
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(sh.os, "replace", refused)
    with pytest.raises(PermissionError):
        write(dest, {"n": 4})
    assert 1 < calls[0] <= 20, calls[0]
    assert [p.name for p in tmp_path.iterdir()] == ["launcher_status.json"]
    assert json.loads(dest.read_text(encoding="ascii")) == {"n": 3}


def _load_phase_watcher():
    """tools/phase_watcher.py under a private name (it is a script, not a
    package module, and its deployed copy has no repo above it)."""
    import importlib.util
    import sys
    alias = "_phase_watcher_rm258"
    spec = importlib.util.spec_from_file_location(
        alias, REPO_ROOT / "tools" / "phase_watcher.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(alias, None)
    return mod


def test_phase_watcher_writer_meets_the_sanction_contract(tmp_path, monkeypatch):
    """tools/phase_watcher.py is served to a standalone agent directory with
    no repo above it (tools/phase_watcher_install.ps1), so it cannot import core.polled_json (the RM-752 pin in
    tests/test_tls_floor_rm752.py); its sidecar writer is sanctioned on the
    three requirements instead, asserted here on the code: a per-writer
    scratch name, fsync before the rename, a bounded WinError 5 retry, the
    scratch removed when the rename fails for good - and LF bytes on disk."""
    pw = _load_phase_watcher()
    real_replace, real_fsync = os.replace, os.fsync
    events: list[str] = []
    scratch: list[str] = []

    def rec_replace(src, dst):
        events.append("replace")
        scratch.append(Path(src).name)
        return real_replace(src, dst)

    def rec_fsync(fd):
        events.append("fsync")
        return real_fsync(fd)

    monkeypatch.setattr(pw.os, "replace", rec_replace)
    monkeypatch.setattr(pw.os, "fsync", rec_fsync)
    monkeypatch.setattr(pw.time, "sleep", lambda _s: None)
    meta = {"topic": "gameflow_phase", "sub_phase": "ChampSelect",
            "queue_id": 420, "captured_at": "2026-05-27T21:15:00Z"}
    dest = pw.write_sidecar(tmp_path, meta, [{"monitor": "game"}])
    assert pw.write_sidecar(tmp_path, meta, [{"monitor": "game"}]) == dest
    assert events == ["fsync", "replace", "fsync", "replace"]
    assert scratch[0] != scratch[1], scratch
    for name in scratch:
        assert name.startswith(dest.name + ".") and name.endswith(".tmp")
        assert f".{os.getpid()}." in name, name
    raw = dest.read_bytes()
    assert b"\r\n" not in raw and b"\n" in raw
    assert json.loads(raw)["frames"] == [{"monitor": "game"}]

    refusals = [3]

    def flaky(src, dst):
        if refusals[0]:
            refusals[0] -= 1
            raise PermissionError(13, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(pw.os, "replace", flaky)
    pw.write_sidecar(tmp_path, dict(meta, queue_id=450), [])
    assert json.loads((tmp_path / dest.name.replace("_420_", "_450_"))
                      .read_bytes())["queue_id"] == 450

    calls = [0]

    def refused(src, dst):
        calls[0] += 1
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(pw.os, "replace", refused)
    with pytest.raises(PermissionError):
        pw.write_sidecar(tmp_path, dict(meta, queue_id=1700), [])
    assert 1 < calls[0] <= 20, calls[0]
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        [dest.name, dest.name.replace("_420_", "_450_")])


def test_moon_sync_poller_writer_meets_the_sanction_contract(tmp_path, monkeypatch):
    """tools/moon_sync_poller.py keeps core/ off its import path on purpose,
    so its one writer (status.md, findings.json, poller_seen.json and the
    --ping stamp all go through _atomic_write) is sanctioned on the three
    requirements, asserted here on the code: a per-writer scratch name, fsync
    before the rename, a bounded WinError 5 retry, the scratch removed when
    the rename fails for good - and LF bytes on disk."""
    from tools import moon_sync_poller as msp
    real_replace, real_fsync = os.replace, os.fsync
    events: list[str] = []
    scratch: list[str] = []

    def rec_replace(src, dst):
        events.append("replace")
        scratch.append(Path(src).name)
        return real_replace(src, dst)

    def rec_fsync(fd):
        events.append("fsync")
        return real_fsync(fd)

    monkeypatch.setattr(msp.os, "replace", rec_replace)
    monkeypatch.setattr(msp.os, "fsync", rec_fsync)
    monkeypatch.setattr(msp.time, "sleep", lambda _s: None)
    dest = tmp_path / "status.md"
    msp._atomic_write(dest, "# a\n- b\n")
    msp._atomic_write(dest, "# a\n- c\n")
    assert events == ["fsync", "replace", "fsync", "replace"]
    assert scratch[0] != scratch[1], scratch
    for name in scratch:
        assert name.startswith("status.md.") and name.endswith(".tmp"), name
        assert f".{os.getpid()}." in name, name
    assert dest.read_bytes() == b"# a\n- c\n"

    refusals = [3]

    def flaky(src, dst):
        if refusals[0]:
            refusals[0] -= 1
            raise PermissionError(13, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(msp.os, "replace", flaky)
    msp._atomic_write(dest, "# a\n- d\n")
    assert dest.read_bytes() == b"# a\n- d\n"

    calls = [0]

    def refused(src, dst):
        calls[0] += 1
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(msp.os, "replace", refused)
    with pytest.raises(PermissionError):
        msp._atomic_write(dest, "# a\n- e\n")
    assert 1 < calls[0] <= 20, calls[0]
    assert [p.name for p in tmp_path.iterdir()] == ["status.md"]
    assert dest.read_bytes() == b"# a\n- d\n"


def test_stop_claim_gate_writer_meets_the_sanction_contract(tmp_path, monkeypatch):
    """tools/stop_claim_gate.py is a portable stdlib-only Stop hook, so its
    one writer (the report, the history roll and the seen set all go through
    _atomic_write) is sanctioned on the three requirements, asserted here on
    the code: a per-writer scratch name, fsync before the rename, a bounded
    WinError 5 retry, the scratch removed when the rename fails for good -
    and LF bytes on disk. The three callers keep their failure contracts:
    write_report raises (RM-796 reports it), the history and the seen set
    swallow (bookkeeping never breaks the gate)."""
    from tools import stop_claim_gate as gate
    real_replace, real_fsync = os.replace, os.fsync
    events: list[str] = []
    scratch: list[str] = []

    def rec_replace(src, dst):
        events.append("replace")
        scratch.append(Path(src).name)
        return real_replace(src, dst)

    def rec_fsync(fd):
        events.append("fsync")
        return real_fsync(fd)

    monkeypatch.setattr(gate.os, "replace", rec_replace)
    monkeypatch.setattr(gate.os, "fsync", rec_fsync)
    monkeypatch.setattr(gate.time, "sleep", lambda _s: None)
    dest = tmp_path / "stop_claim_gate_last.json"
    gate.write_report({"n": 1}, dest)
    gate.write_report({"n": 2}, dest)
    assert events == ["fsync", "replace", "fsync", "replace"]
    assert scratch[0] != scratch[1], scratch
    for name in scratch:
        assert name.startswith(dest.name + ".") and name.endswith(".tmp"), name
        assert f".{os.getpid()}." in name, name
    raw = dest.read_bytes()
    assert b"\r\n" not in raw and b"\n" in raw
    assert json.loads(raw) == {"n": 2}

    history = tmp_path / "history.jsonl"
    for i in range(4):
        gate.append_history({"session_id": f"s{i}"}, history, cap=2)
    rows = history.read_bytes().split(b"\n")
    assert b"\r" not in history.read_bytes()
    assert [json.loads(r)["session_id"] for r in rows if r] == ["s2", "s3"]

    refusals = [3]

    def flaky(src, dst):
        if refusals[0]:
            refusals[0] -= 1
            raise PermissionError(13, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(gate.os, "replace", flaky)
    gate.write_report({"n": 3}, dest)
    assert json.loads(dest.read_bytes()) == {"n": 3}

    calls = [0]

    def refused(src, dst):
        calls[0] += 1
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(gate.os, "replace", refused)
    with pytest.raises(PermissionError):
        gate.write_report({"n": 4}, dest)
    assert 1 < calls[0] <= 20, calls[0]
    gate.append_history({"session_id": "s4"}, history, cap=2)
    seen = tmp_path / "seen" / "s.json"
    gate.save_seen(seen, "s", {"k"})
    assert not seen.exists()
    assert list(seen.parent.iterdir()) == []
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        [dest.name, history.name, "seen"])
    assert json.loads(dest.read_bytes()) == {"n": 3}


def test_scope_keeps_runtime_tools_and_drops_generators():
    assert _in_scope("tools/lcu_agent.py")
    assert _in_scope("tools/hotkey_listener.py")
    assert _in_scope("tools/cost_health_watchdog.py")
    assert _in_scope("tools/ci_watchdog.py")
    assert _in_scope("tools/progress_watch.py")
    assert _in_scope("tools/spec_watch.py")
    assert _in_scope("tools/ds_feed_watch.py")
    assert _in_scope("tools/session_checklist.py")
    assert _in_scope("tools/inbox_responder.py")
    assert _in_scope("tools/rc_facts.py")
    assert _in_scope("tools/inbox_responder_runner.py")
    assert _in_scope("tools/phase_watcher.py")
    assert _in_scope("tools/moon_sync_poller.py")
    assert _in_scope("tools/upstream_drift_check.py")
    assert _in_scope("tools/stop_claim_gate.py")
    assert not _in_scope("tools/daemon_slayer_extract.py")
    assert not _in_scope("ops/fleet_kit/fleet_headless.py")
    assert _in_scope("coach_integration/_coach.py")


def test_a_new_tools_writer_starts_in_scope():
    """The RM-258 residual: a tools/ module is guarded unless it is an
    extractor, tools/ test code or a named unclassified entry - a new writer
    no longer starts bare under a directory-wide exemption."""
    assert _in_scope("tools/a_new_polled_writer.py")
    assert _in_scope("tools/ds_cross_eval/a_new_writer.py")
    assert not _in_scope("tools/daemon_slayer_cdragon_ratio_extract.py")
    assert not _in_scope("tools/tests/test_cdragon_ratio_extract.py")
    assert not _in_scope("tools/web_ascii_sweep.py")


def test_tools_baseline_is_exact():
    """Every unclassified entry is a tracked tools/ module that still
    offends, is not an extractor and is not a converted watcher - so a
    conversion has to shrink the set, and the set never hides a clean file."""
    tracked = {relative_posix(p) for p in iter_repo_files(REPO_ROOT, ("*.py",))}
    assert not _TOOLS_UNCLASSIFIED & _RUNTIME_TOOLS
    stale = []
    for rel in sorted(_TOOLS_UNCLASSIFIED):
        assert rel in tracked, f"unclassified entry {rel} is not tracked"
        assert not _is_tools_extractor(rel), rel
        renames, scratch = scan([(rel, REPO_ROOT / rel)])
        if not renames and not scratch:
            stale.append(rel)
    assert stale == [], (
        "these no longer hand-roll an atomic write - drop them from "
        "_TOOLS_UNCLASSIFIED (add a long-running one to _RUNTIME_TOOLS):\n  "
        + "\n  ".join(stale))
