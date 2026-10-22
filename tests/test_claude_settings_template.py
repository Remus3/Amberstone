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
"""
from __future__ import annotations

import json
import re
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
