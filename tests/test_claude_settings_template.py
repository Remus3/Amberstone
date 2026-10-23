"""The tracked Claude Code settings template and the settings rules it carries
(MAIN FIX 2026-10-21 1254 items 4, 5, 7, 8, 16, 19, 20, 21, 22 and section 3;
MAIN FIX 2026-10-21 1300 inert keys; C1b-3 S5).

The live project `.claude/settings.json` and `.claude/settings.local.json` are
gitignored per-host files, so the hook wiring could not be reproduced from git
(item 7). `ops/claude_settings.example.json` is the tracked, host-free copy:
RC hook lines run `"$CLAUDE_PROJECT_DIR/tools/<hook>.py"` under ONE documented
interpreter (`$LOCALAPPDATA/Programs/Python/Python314/`, the canonical
interpreter of docs/OPERATIONS.md); the fleet-kit lines stay in the exact form
CLAUDE.md prescribes (kit v11 ruling R3 / kit v12), which is why item 16 is
DECLINED rather than fixed here.

The last two tests read the live gitignored files when they exist (skip in a
fresh clone, a worktree or CI) and hold them to the same no-inert-key rule.

RM-782 (hooks fail visibly): every hook line is run end to end in a POSIX
shell with a BROKEN interpreter path, and the outcome is pinned per line. An
RC line on an event that reads additionalContext carries one shell tail
(`_fallback`) that turns an interpreter that never started (exit 126 / 127,
any code outside the hook's own 0-2) into ONE additionalContext line, and
passes the hook's own exit codes through untouched (2 still blocks).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "ops" / "claude_settings.example.json"
OPERATIONS = ROOT / "docs" / "OPERATIONS.md"
CLAUDE_MD = ROOT / "CLAUDE.md"

#: Not settings keys at the top level (MAIN 1300 section 2).
INERT_TOP = {"bypassPermissions", "dangerouslySkipPermissions", "defaultMode"}
#: The keys the settings schema allows under "permissions"; everything else
#: there (skipDangerousModePermissionPrompt, autoUpdates, ...) is inert.
PERMISSION_KEYS = {"allow", "ask", "deny", "additionalDirectories",
                   "defaultMode", "disableBypassPermissionsMode"}
#: Account-level or operator-pending keys an RC template never carries
#: (items 21 and 22).
NEVER_IN_TEMPLATE = {"remoteControlAtStartup", "effortLevel", "modelSettings"}
TEMPLATE_TOP = {"$schema", "env", "hooks", "permissions"}

INTERP = '"$LOCALAPPDATA/Programs/Python/Python314/'
_RC_LINE = re.compile(
    r'^"\$LOCALAPPDATA/Programs/Python/Python314/pythonw?\.exe" '
    r'"\$CLAUDE_PROJECT_DIR/(tools|ops/fleet_kit)/[A-Za-z0-9_]+\.py"( .*)?$'
)
_SCRIPT = re.compile(r'\$CLAUDE_PROJECT_DIR/([A-Za-z0-9_./-]+\.py)')
_EDIT_TOOLS = "Edit|Write|MultiEdit|NotebookEdit"


def _template() -> dict:
    return json.loads(TEMPLATE.read_text(encoding="ascii"))


def _entries(blob: dict):
    """(event, matcher, command) for every hook command in a settings blob."""
    for event, groups in (blob.get("hooks") or {}).items():
        for group in groups:
            for hook in group.get("hooks", []):
                yield event, group.get("matcher"), hook.get("command", "")


def _all_keys(node) -> set[str]:
    keys: set[str] = set()
    if isinstance(node, dict):
        for k, v in node.items():
            keys.add(k)
            keys |= _all_keys(v)
    elif isinstance(node, list):
        for v in node:
            keys |= _all_keys(v)
    return keys


def _r3_kit_lines() -> set[str]:
    """The kit hook commands CLAUDE.md quotes verbatim (ruling R3 form)."""
    text = CLAUDE_MD.read_text(encoding="utf-8")
    return set(re.findall(
        r'`(python "\$CLAUDE_PROJECT_DIR/ops/fleet_kit/[^`]+)`', text))


# --------------------------------------------------------------- the template

def test_template_is_valid_json_ascii_lf():
    raw = TEMPLATE.read_bytes()
    assert raw, "template is empty"
    assert all(b < 128 for b in raw), "template must be 7-bit ASCII"
    assert b"\r" not in raw, "template must be LF only"
    assert raw.endswith(b"\n")
    assert isinstance(_template(), dict)


def test_template_top_level_shape():
    blob = _template()
    assert set(blob) <= TEMPLATE_TOP, sorted(set(blob) - TEMPLATE_TOP)
    assert blob.get("hooks"), "template must carry the hook wiring"


def test_template_carries_no_inert_or_account_keys():
    blob = _template()
    assert not (set(blob) & INERT_TOP)
    assert set(blob.get("permissions", {})) <= PERMISSION_KEYS
    assert not (_all_keys(blob) & NEVER_IN_TEMPLATE)


def test_precommit_gate_matcher_is_bash_or_powershell():
    # Item 4: `Bash(git commit:*)` is permission-rule syntax and never matched,
    # so Bash-tool commits were ungated. The gate filters commits itself.
    hits = [(m, c) for _, m, c in _entries(_template())
            if "tools/precommit_gate.py" in c]
    assert len(hits) == 1, hits
    assert hits[0][0] == "Bash|PowerShell"


def test_no_matcher_uses_permission_rule_syntax():
    for event, matcher, _ in _entries(_template()):
        if matcher is None:
            continue
        assert not re.search(r"[A-Za-z]\(", matcher), (event, matcher)
        re.compile(matcher)


def test_post_tool_use_covers_every_edit_tool():
    # Item 5: `Edit|Write` missed MultiEdit and NotebookEdit.
    matchers = {m for e, m, c in _entries(_template())
                if e == "PostToolUse"
                and ("pytest_guard.py" in c or "edit_lint_check.py" in c)}
    assert matchers == {_EDIT_TOOLS}


def test_rc_hook_lines_use_project_dir_and_one_interpreter():
    # Item 7: no absolute interpreter or repo path; one interpreter.
    kit = _r3_kit_lines()
    rc_lines = [c for _, _, c in _entries(_template()) if c not in kit]
    assert rc_lines
    for cmd in rc_lines:
        assert _RC_LINE.match(cmd), cmd
        assert cmd.startswith(INTERP), cmd


def test_kit_lines_stay_in_the_claude_md_r3_form():
    # Item 16 DECLINED: CLAUDE.md prescribes these exact commands.
    kit = _r3_kit_lines()
    assert len(kit) >= 3, kit
    commands = {c for _, _, c in _entries(_template())}
    assert kit <= commands, sorted(kit - commands)
    bare = {c for c in commands if c.startswith("python ")}
    assert bare <= kit, sorted(bare - kit)


def test_every_wired_script_exists():
    for _, _, cmd in _entries(_template()):
        rels = _SCRIPT.findall(cmd)
        assert rels, cmd
        for rel in rels:
            assert (ROOT / rel).is_file(), rel


def test_template_has_no_machine_path():
    text = TEMPLATE.read_text(encoding="ascii")
    # One letter, not preceded by another (so the https: of "$schema" passes).
    assert not re.search(r"(?<![A-Za-z])[A-Za-z]:[\\/]", text), "drive-rooted path"
    assert "Users" not in text
    assert "perseus" not in text.lower(), "Perseus wiring is machine-only (item 19)"


# ------------------------------------- RM-782: a hook that did not run says so

#: Events whose hook stdout Claude Code reads as hookSpecificOutput.
#: additionalContext. Stop is left out on purpose: a Stop context line keeps
#: the session going (tools/stop_claim_gate.py docstring, measured), so a
#: broken interpreter would re-enter on every Stop, and FLEET-COMMON item 15
#: says never block on Stop.
CONTEXT_EVENTS = {"PreToolUse", "PostToolUse", "SessionStart", "UserPromptSubmit"}

#: Measured with a broken interpreter path (2026-10-23, Git Bash and POSIX
#: sh): (exit code, stdout) of every hook line this tail does NOT cover.
#: Kit lines: item 16 DECLINED - the kit owns that `|| true` form (CLAUDE.md
#: ruling R3 / kit v12) and its silence is the known cost docs/OPERATIONS.md
#: records; a change ships only as a kit version. Reverses if: MAIN ships one.
#: The Stop claim gate exits 127 (a non-blocking "Stop hook error" row, never
#: a context line, see CONTEXT_EVENTS); fleet_done's stop-hook keeps the kit
#: contract "silent, never additionalContext or systemMessage".
UNCOVERED_OUTCOME = {
    ("PreToolUse", "ops/fleet_kit/fleet_subagent_first.py"): (0, ""),
    ("PreToolUse", "ops/fleet_kit/fleet_claims.py"): (0, ""),
    ("SubagentStop", "ops/fleet_kit/fleet_claims.py"): (0, ""),
    ("Stop", "tools/stop_claim_gate.py"): (127, ""),
    ("Stop", "ops/fleet_kit/fleet_done.py"): (0, ""),
}


def _fallback(event: str, script: str) -> str:
    """The exact shell tail every RC hook line on a CONTEXT_EVENTS event ends
    in. Exit codes 0-2 are the hook's own (allow / non-blocking error /
    block) and pass through; anything else means the interpreter never ran
    the hook, and the tail prints ONE additionalContext line and exits 0."""
    ctx = (f"RC hook {script} did not run (exit %s, not one of its own codes "
           "0-2): check the interpreter path in .claude/settings.json")
    line = json.dumps({"hookSpecificOutput": {"hookEventName": event,
                                              "additionalContext": ctx}},
                      separators=(",", ":"))
    return " || { r=$?; [ $r -le 2 ] && exit $r; printf '" + line + "\\n' $r; }"


def _covered(event: str, cmd: str) -> bool:
    return event in CONTEXT_EVENTS and cmd.startswith(INTERP)


def _posix_sh() -> str | None:
    """The POSIX shell Claude Code runs hook commands in. On Windows that is
    Git Bash (CLAUDE_CODE_GIT_BASH_PATH, else the sh.exe of the git on PATH),
    NEVER System32's bash.exe, which is WSL."""
    if os.name != "nt":
        return shutil.which("sh")
    override = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH", "").strip()
    if override and Path(override).is_file():
        return override
    git = shutil.which("git")
    if not git:
        return None
    for parent in list(Path(git).resolve().parents)[:3]:
        for rel in ("bin/sh.exe", "usr/bin/sh.exe"):
            if (parent / rel).is_file():
                return str(parent / rel)
    return None


def _run_line(cmd: str, env_over: dict, stdin: str = "{}") -> subprocess.CompletedProcess:
    sh = _posix_sh()
    if sh is None:
        pytest.skip("no POSIX shell (Git Bash on Windows) to run a hook line in")
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(ROOT).replace("\\", "/")
    env.update(env_over)
    return subprocess.run([sh, "-c", cmd], input=stdin, env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=60)


def _context_line(proc: subprocess.CompletedProcess, event: str) -> str:
    lines = proc.stdout.splitlines()
    assert lines, (proc.returncode, proc.stderr)
    hso = json.loads(lines[-1])["hookSpecificOutput"]
    assert hso["hookEventName"] == event
    ctx = hso["additionalContext"]
    assert ctx.isascii() and "\x1b" not in ctx and "\n" not in ctx
    return ctx


def _line_ids():
    return [f"{i}-{e}-{Path(_SCRIPT.findall(c)[0]).stem}"
            for i, (e, _, c) in enumerate(_entries(_template()))]


def test_every_rc_context_line_ends_in_the_fallback_tail():
    covered = [(e, c) for e, _, c in _entries(_template()) if _covered(e, c)]
    assert len(covered) >= 6, covered
    for event, cmd in covered:
        script = _SCRIPT.findall(cmd)[0]
        assert cmd.endswith(_fallback(event, script)), (event, cmd)
        assert cmd.count(" || ") == 1, cmd


def test_every_uncovered_line_is_a_named_kit_or_stop_line():
    seen = {(e, _SCRIPT.findall(c)[0]) for e, _, c in _entries(_template())
            if not _covered(e, c)}
    assert seen == set(UNCOVERED_OUTCOME), sorted(seen ^ set(UNCOVERED_OUTCOME))
    for event, _, cmd in _entries(_template()):
        if not _covered(event, cmd):
            assert "hookSpecificOutput" not in cmd, (event, cmd)


@pytest.mark.parametrize("event,cmd", [(e, c) for e, _, c in _entries(_template())],
                         ids=_line_ids())
def test_each_hook_line_with_a_broken_interpreter(event, cmd, tmp_path):
    """The acceptance measurement: the line as wired, its interpreter gone
    ($LOCALAPPDATA for RC lines, `python` off PATH for the kit lines)."""
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    proc = _run_line(cmd, {"LOCALAPPDATA": str(tmp_path / "no-python"),
                           "PATH": str(empty)})
    script = _SCRIPT.findall(cmd)[0]
    if not _covered(event, cmd):
        assert (proc.returncode, proc.stdout) == UNCOVERED_OUTCOME[(event, script)], \
            proc.stderr
        return
    assert proc.returncode == 0, proc.stderr
    assert len(proc.stdout.splitlines()) == 1, proc.stdout
    ctx = _context_line(proc, event)
    assert f"RC hook {script} did not run (exit 127" in ctx, ctx


def _working(cmd: str, script: Path) -> str:
    """The same line with a working interpreter and `script` in place of the
    hook, so only the template's own tail is under test."""
    head = re.match(r'^"[^"]+" "[^"]+"', cmd)
    assert head, cmd
    py = sys.executable.replace("\\", "/")
    return f'"{py}" "{script.as_posix()}"' + cmd[head.end():]


@pytest.mark.parametrize("code", [0, 1, 2, 3, 120])
def test_the_tail_passes_the_hooks_own_exit_codes_through(code, tmp_path):
    probe = tmp_path / "probe.py"
    probe.write_text("import os, sys\nsys.stdout.write('own line\\n')\n"
                     "sys.exit(int(os.environ['PROBE_EXIT']))\n", encoding="ascii")
    event, cmd = next((e, c) for e, _, c in _entries(_template())
                      if "tools/precommit_gate.py" in c)
    proc = _run_line(_working(cmd, probe), {"PROBE_EXIT": str(code)})
    if code <= 2:
        # 2 is a PreToolUse BLOCK: the tail must never turn it into an allow.
        assert (proc.returncode, proc.stdout) == (code, "own line\n"), proc.stderr
        return
    assert proc.returncode == 0, proc.stderr
    assert f"(exit {code}," in _context_line(proc, event)


def test_working_guards_are_unchanged_by_the_tail(tmp_path):
    lines = {_SCRIPT.findall(c)[0]: c for _, _, c in _entries(_template())}

    def real(rel: str) -> str:
        return _working(lines[rel], ROOT / rel)

    quiet = _run_line(real("tools/precommit_gate.py"), {},
                      json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}}))
    assert (quiet.returncode, quiet.stdout) == (0, ""), quiet.stderr
    deny = _run_line(real("tools/text_first_guard.py"),
                     {"TEXT_FIRST_FLAG": str(tmp_path / "no-such-flag")},
                     json.dumps({"tool_name": "mcp__Windows-MCP__Scrape"}))
    assert deny.returncode == 0, deny.stderr
    out = json.loads(deny.stdout.splitlines()[-1])["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"


# ------------------------------------------------------------ docs and hooks

def _operations_section() -> str:
    text = OPERATIONS.read_text(encoding="utf-8")
    start = text.index("## Claude settings and hooks")
    end = text.find("\n## ", start + 1)
    return text[start:end if end != -1 else len(text)]


@pytest.mark.parametrize("needle", [
    "ops/claude_settings.example.json",
    "$LOCALAPPDATA/Programs/Python/Python314/",
    "Bash|PowerShell",
    "Edit|Write|MultiEdit|NotebookEdit",
    "permissions.defaultMode",
    "ruling R3",
    "Perseus",
    "effortLevel",
    "modelSettings",
    "remoteControlAtStartup",
    "~/.fleet/headless_route.json",
    "machine-only",
    "RM-782",
])
def test_operations_documents_the_settings_rules(needle):
    assert needle in _operations_section()


def test_caveman_default_docstring_says_per_repo():
    # Item 20: it is a per-repo SessionStart hook, not machine-wide.
    head = (ROOT / "tools" / "caveman_default.py").read_text(encoding="utf-8")
    doc = head.split('"""')[1]
    assert "per-repo SessionStart hook" in doc
    assert "every Legion" not in doc


# ------------------------------------------------- live gitignored settings
#
# Only the MAIN checkout's copies are held to the rule. A linked worktree
# (`.git` is a file there) carries whatever snapshot of settings.local.json the
# harness copied in when it was created; it is not the operator's live file and
# goes away with the worktree, so it is skipped rather than reddened.

def _live(name: str) -> Path:
    if (ROOT / ".git").is_file():
        pytest.skip("linked worktree: its .claude/ copy is a creation-time "
                    "snapshot; the main checkout's file is the live one")
    path = ROOT / ".claude" / name
    if not path.is_file():
        pytest.skip(f".claude/{name} is gitignored and absent in this checkout")
    return path


@pytest.mark.parametrize("name", ["settings.json", "settings.local.json"])
def test_live_settings_have_no_inert_permission_keys(name):
    path = _live(name)
    blob = json.loads(path.read_text(encoding="utf-8"))
    assert not (set(blob) & INERT_TOP), sorted(set(blob) & INERT_TOP)
    extra = set(blob.get("permissions", {})) - PERMISSION_KEYS
    assert not extra, sorted(extra)


def test_live_settings_matchers_are_not_permission_rules():
    blob = json.loads(_live("settings.json").read_text(encoding="utf-8"))
    bad = [(e, m) for e, m, _ in _entries(blob)
           if m and re.search(r"[A-Za-z]\(", m)]
    assert bad == []
