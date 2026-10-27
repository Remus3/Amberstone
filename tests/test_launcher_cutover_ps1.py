"""PKG-7: the ONLOGON-to-launcher cutover script (docs/PACKAGING_PLAN.md
section 5) - tools/launcher_cutover.ps1.

Running the script for real is an OPERATOR step (elevated; hand-off ASKS 45).
Nothing here performs a real run. What is pinned:

* Static (pure Python, runs on every host incl. the Linux CI): ASCII + LF;
  a dry run is the DEFAULT (only an explicit `-Apply` changes anything, and
  `-WhatIf` beats `-Apply`); every mutating command sits inside an
  `Invoke-Change -Do { ... }` block - the one gate that does nothing in a dry
  run and refuses without elevation - or inside a helper only such blocks
  call; the target list is exactly the section-5 list (unregister, never
  disable; no kill, no task start / stop); the XML backup is written and
  read back before the first unregister; `-Rollback` re-imports the XML
  after a sha256 check.
* Windows PowerShell 5.1 (skipped by name where that binary is absent): the
  script parses with zero errors under the 5.1 parser, never pwsh; and the
  DEFAULT dry run - cutover and rollback - executed against FAKE task
  cmdlets (every mutator a tripwire that throws) prints its plan, calls no
  mutator and writes no file. Those runs never pass `-Apply`, so even a fake
  that failed to shadow its cmdlet would leave the dry-run gate in force.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "launcher_cutover.ps1"
PLAN = ROOT / "docs" / "PACKAGING_PLAN.md"
PS51 = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
NO_WINDOW = 0x08000000

CORE = ("RC-Supervisor", "RC-LCUAgent", "RC-LiveClientRelay", "RC-HotkeyListener",
        "RC-Phase3-Supervisor", "RC-DaemonSlayer", "RC-DSKeepalive")
OPTIONAL = ("RC-LiveFlipWatcher",)

# Commands that change the machine. Each may appear only inside an
# Invoke-Change -Do block (or a helper only such blocks call).
GATED = (
    "Unregister-ScheduledTask", "Register-ScheduledTask",
    "New-Item", "Set-Content", "Add-Content", "Out-File", "Move-Item",
    "Copy-Item", "Remove-Item", "Rename-Item", "Set-ItemProperty",
    "New-ItemProperty", "Remove-ItemProperty", "Tee-Object",
    "WriteAllText", "WriteAllBytes", "WriteAllLines", "AppendAllText",
    "CreateDirectory",
)
# Never anywhere: section 5 / S9 unregister-never-disable, the no-kill rule,
# no task start / stop, and no module-qualified call that would bypass a
# test fake.
BANNED = (
    "Disable-ScheduledTask", "Enable-ScheduledTask", "Set-ScheduledTask",
    "Start-ScheduledTask", "Stop-ScheduledTask", "Stop-Process",
    "Start-Process", "taskkill", "schtasks", "Invoke-Expression", "iex",
    "ScheduledTasks\\", "Remove-Variable",
)


# --------------------------------------------------------------------------- #
# A small PowerShell lexer: comments removed, string bodies blanked, so a
# message string never reads as code and a brace inside a string never moves
# the brace depth.
# --------------------------------------------------------------------------- #
def _lex(text: str) -> tuple[str, str]:
    """(code_blank, code_keep): comments become spaces in both; string bodies
    become spaces in code_blank and stay in code_keep. Offsets match."""
    blank, keep = [], []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if text.startswith("<#", i):
            j = text.find("#>", i + 2)
            j = n if j < 0 else j + 2
            chunk = re.sub(r"[^\n]", " ", text[i:j])
            blank.append(chunk)
            keep.append(chunk)
            i = j
        elif c == "#":
            j = text.find("\n", i)
            j = n if j < 0 else j
            blank.append(" " * (j - i))
            keep.append(" " * (j - i))
            i = j
        elif c in "'\"":
            j = i + 1
            while j < n:
                if c == '"' and text[j] == "`":
                    j += 2
                    continue
                if text[j] == c:
                    if j + 1 < n and text[j + 1] == c:
                        j += 2
                        continue
                    break
                j += 1
            j = min(j + 1, n)
            body = text[i:j]
            blank.append(c + re.sub(r"[^\n]", " ", body[1:-1]) + body[-1:])
            keep.append(body)
            i = j
        else:
            blank.append(c)
            keep.append(c)
            i += 1
    return "".join(blank), "".join(keep)


def _match_brace(code: str, open_at: int) -> int:
    depth = 0
    for k in range(open_at, len(code)):
        if code[k] == "{":
            depth += 1
        elif code[k] == "}":
            depth -= 1
            if depth == 0:
                return k
    raise AssertionError(f"unbalanced brace at {open_at}")


def _functions(code: str) -> dict[str, tuple[int, int]]:
    out = {}
    for m in re.finditer(r"(?im)^\s*function\s+([A-Za-z][\w-]*)\s*\{", code):
        open_at = m.end() - 1
        out[m.group(1)] = (m.start(), _match_brace(code, open_at))
    return out


def _gate_spans(code: str) -> list[tuple[int, int]]:
    spans = []
    for m in re.finditer(r"(?i)(?<![\w-])Invoke-Change\b", code):
        line_start = code.rfind("\n", 0, m.start()) + 1
        if re.match(r"(?i)\s*function\s", code[line_start:m.start() + 1]):
            continue
        do = re.compile(r"(?i)-Do\s*\{").search(code, m.end())
        assert do, f"Invoke-Change at {m.start()} has no -Do block"
        nl = code.find("\n", m.end())
        assert do.start() < (nl if nl >= 0 else len(code)), \
            "write `Invoke-Change ... -Do {` on one line"
        spans.append((do.end() - 1, _match_brace(code, do.end() - 1)))
    return spans


def _word(name: str) -> re.Pattern:
    return re.compile(r"(?i)(?<![\w-])" + re.escape(name) + r"(?![\w-])")


@pytest.fixture(scope="module")
def src() -> str:
    assert SCRIPT.is_file(), f"{SCRIPT} is missing"
    return SCRIPT.read_bytes().decode("ascii")


@pytest.fixture(scope="module")
def lexed(src) -> tuple[str, str]:
    return _lex(src)


# --------------------------------------------------------------------------- #
# Static
# --------------------------------------------------------------------------- #
def test_script_is_ascii_and_lf():
    raw = SCRIPT.read_bytes()
    assert all(b < 128 for b in raw), "tools/launcher_cutover.ps1 is not 7-bit ASCII"
    assert b"\r" not in raw, "tools/launcher_cutover.ps1 carries CR bytes"


def test_the_lexer_blanks_strings_and_comments():
    # Negative control for every static test below: a mutator named only in a
    # comment or a string is not code; one in code is.
    blank, keep = _lex("# Remove-Item x\n$a = 'Remove-Item {'\nRemove-Item y\n")
    assert len(_word("Remove-Item").findall(blank)) == 1
    assert "{" not in blank
    assert "'Remove-Item {'" in keep


def test_dry_run_is_the_default_and_whatif_beats_apply(lexed):
    blank, keep = lexed
    param = re.search(r"(?is)\bparam\s*\((.*?)\)\s*\n\s*\n", keep)
    assert param, "no param block"
    block = param.group(1)
    assert re.search(r"(?i)\[switch\]\s*\$Apply\b", block)
    assert re.search(r"(?i)\[switch\]\s*\$Rollback\b", block)
    assert not re.search(r"(?i)\$Apply\s*=", block), "-Apply must not default on"
    assert re.search(r"(?i)SupportsShouldProcess\s*=\s*\$true", keep), "-WhatIf must be accepted"
    dry = re.findall(r"(?im)^\s*\$script:DryRun\s*=\s*(.+)$", keep)
    assert dry == ["(-not $Apply) -or [bool]$WhatIfPreference"], dry
    assert not re.search(r"(?i)\$Apply\s*=", blank), "-Apply is never assigned"
    assert not re.search(r"(?i)\$script:DryRun\s*=", blank[blank.find("$script:DryRun =") + 1:]), \
        "DryRun is assigned once"


def test_the_gate_does_nothing_in_a_dry_run_and_refuses_unelevated(lexed):
    blank, keep = lexed
    funcs = _functions(blank)
    assert "Invoke-Change" in funcs
    start, end = funcs["Invoke-Change"]
    body = keep[start:end]
    dry_at = body.find("if ($script:DryRun)")
    elev_at = body.find("if (-not $script:Elevated)")
    run_at = body.find("& $Do")
    assert 0 <= dry_at < elev_at < run_at, "dry-run check, then elevation, then the change"
    assert "throw" in body[elev_at:run_at]
    assert body[dry_at:elev_at].count("return") >= 1


def test_every_mutation_sits_behind_the_gate(lexed):
    blank, _ = lexed
    spans = _gate_spans(blank)
    assert len(spans) >= 4, "cutover writes, manifest, unregister and re-register each gate"
    funcs = _functions(blank)

    def inside(pos: int) -> bool:
        return any(a < pos < b for a, b in spans)

    # A helper with an UNGATED mutation in its body may only be CALLED from
    # inside a gate span (to a fixpoint: a caller of such a helper outside a
    # span is itself such a helper, up to the top level, which fails).
    mutating = set()
    changed = True
    while changed:
        changed = False
        for name, (fa, fb) in funcs.items():
            if name in mutating or name == "Invoke-Change":
                continue
            for word in (*GATED, *mutating):
                hits = [m.start() for m in _word(word).finditer(blank, fa, fb)
                        if not (word == name and m.start() == fa)]
                if any(not inside(p) for p in hits if p > fa):
                    mutating.add(name)
                    changed = True
                    break
    assert "Write-AtomicFile" in mutating, "the file writer must be a gated helper"
    bad = []
    for name in (*GATED, *mutating):
        for m in _word(name).finditer(blank):
            owner = next((f for f, (fa, fb) in funcs.items() if fa <= m.start() <= fb), None)
            if owner is not None and owner in mutating:
                continue  # the helper's own body; its call sites are checked
            if owner == "Invoke-Change":
                bad.append(f"{name} inside the gate function itself")
            elif not inside(m.start()):
                line = blank.count("\n", 0, m.start()) + 1
                bad.append(f"line {line}: {name} outside an Invoke-Change -Do block")
    assert bad == []


def test_no_banned_command_and_no_file_redirection(lexed):
    blank, _ = lexed
    for name in BANNED:
        hits = _word(name).findall(blank) if not name.endswith("\\") else \
            [1] * blank.count(name)
        assert not hits, f"{name} appears in code"
    # `>` / `>>` redirection writes a file outside the gate; only 2>&1 style
    # stream merges are allowed (PowerShell compares with -gt, never `>`).
    for m in re.finditer(r">", blank):
        assert re.match(r"[*\d]?>&[12]", blank[max(0, m.start() - 1):m.start() + 3]), \
            f"redirection at line {blank.count(chr(10), 0, m.start()) + 1}"


def _list_literal(keep: str, var: str) -> list[str]:
    m = re.search(r"(?is)\$" + var + r"\s*=\s*@\((.*?)\)", keep)
    assert m, f"no ${var} list"
    return re.findall(r"'([^']+)'", m.group(1))


def test_targets_are_exactly_the_section5_list(lexed):
    blank, keep = lexed
    assert tuple(_list_literal(keep, "CoreTasks")) == CORE
    assert tuple(_list_literal(keep, "OptionalTasks")) == OPTIONAL
    assert re.search(r"(?i)\[switch\]\s*\$IncludeLiveFlipWatcher\b", keep)
    # No other task name anywhere in code or strings: nothing else can be
    # unregistered or re-registered by name.
    names = set(re.findall(r"RC-[A-Za-z0-9-]+", keep))
    assert names == set(CORE) | set(OPTIONAL), names - set(CORE) - set(OPTIONAL)
    assert "RiotCommander" not in keep, "the bare task is the operator's separate call"


def test_the_list_matches_packaging_plan_section_5():
    text = PLAN.read_text(encoding="utf-8")
    sec = text[text.index("## 5. ONLOGON-to-launcher cutover"):text.index("## 6.")]
    step2 = sec[sec.index("2. Stage 1"):sec.index("3. Stage 2")]
    named = re.findall(r"`(RC-[A-Za-z0-9-]+)`", step2)
    assert set(named) == set(CORE) | set(OPTIONAL), named
    assert "tools/launcher_cutover.ps1" in sec


def test_backup_is_written_and_read_back_before_the_first_unregister(lexed):
    blank, keep = lexed
    funcs = _functions(blank)
    assert "Invoke-Cutover" in funcs and "Invoke-Rollback" in funcs
    fa, fb = funcs["Invoke-Cutover"]
    body = keep[fa:fb]
    export_at = body.find("Export-ScheduledTask")
    write_at = body.find("Write-AtomicFile")
    manifest_at = body.find("manifest.json")
    verify_at = body.find("Test-BackupReadBack")
    unreg_at = body.find("Unregister-ScheduledTask")
    assert 0 <= export_at < write_at < verify_at < unreg_at, \
        (export_at, write_at, verify_at, unreg_at)
    assert 0 <= manifest_at < unreg_at
    # A failed read-back returns before any unregister.
    between = body[verify_at:unreg_at]
    assert re.search(r"(?i)return\s+1", between), "a bad backup must stop the run"
    # Unregister appears only in the cutover, re-register only in the rollback.
    assert len(_word("Unregister-ScheduledTask").findall(blank)) == 1
    assert len(_word("Register-ScheduledTask").findall(blank)) == 1
    ra, rb = funcs["Invoke-Rollback"]
    assert _word("Register-ScheduledTask").search(blank[ra:rb])
    assert _word("Unregister-ScheduledTask").search(blank[fa:fb])


def test_rollback_reimports_the_xml_after_a_sha256_check(lexed):
    blank, keep = lexed
    funcs = _functions(blank)
    ra, rb = funcs["Invoke-Rollback"]
    body = keep[ra:rb]
    sha_at = body.find("Get-Sha256Hex")
    reg_at = body.find("Register-ScheduledTask")
    assert 0 <= sha_at < reg_at
    assert re.search(r"(?i)Register-ScheduledTask\s+-Xml\s+\$", body)
    # An already-registered task is never overwritten.
    assert "-Force" not in body[reg_at:body.find("\n", reg_at)]


def test_apply_refuses_without_elevation_before_any_change(src, lexed):
    blank, keep = lexed
    main_at = src.find("# ---- main")
    assert main_at > 0, "the script needs a `# ---- main` marker"
    main = keep[main_at:]
    refuse = main.find("if (-not $script:DryRun -and -not $script:Elevated)")
    first_call = min(i for i in (main.find("Invoke-Cutover"), main.find("Invoke-Rollback"))
                     if i >= 0)
    assert 0 <= refuse < first_call
    assert re.search(r"(?i)exit\s+2", main[refuse:first_call])


def test_backups_default_under_gitignored_runtime(lexed):
    _, keep = lexed
    assert "'ops\\runtime\\launcher_cutover'" in keep
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "ops/runtime/launcher_cutover/cutover-x/manifest.json"],
        cwd=ROOT, capture_output=True)
    assert ignored.returncode == 0, "the backup folder must be gitignored"


def test_no_machine_paths_or_names(src):
    assert not re.search(r"(?i)\b[A-Z]:\\", src), "no drive-rooted path in the script"
    assert "Users\\" not in src


def test_bundle_never_ships_the_cutover_script():
    from tools import build_portable as bp
    reason = bp.exclusion_reason("tools/launcher_cutover.ps1")
    assert reason == bp.R_TASKS


# --------------------------------------------------------------------------- #
# Windows PowerShell 5.1
# --------------------------------------------------------------------------- #
def _ps51(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    if not PS51.is_file():
        pytest.skip("Windows PowerShell 5.1 not available on this host")
    return subprocess.run([str(PS51), "-NoProfile", "-NonInteractive", *args],
                          capture_output=True, text=True, timeout=timeout,
                          creationflags=NO_WINDOW if os.name == "nt" else 0)


def test_parses_under_windows_powershell_51():
    command = (
        "$e = $null; "
        f"[void][System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}', "
        "[ref]$null, [ref]$e); Write-Output ('ERRORS=' + $e.Count)"
    )
    proc = _ps51(["-Command", command])
    assert "ERRORS=0" in proc.stdout, f"{proc.stdout}\n{proc.stderr}"


_MUTATORS_TO_TRIP = (
    "Unregister-ScheduledTask", "Register-ScheduledTask", "Disable-ScheduledTask",
    "Enable-ScheduledTask", "Set-ScheduledTask", "Start-ScheduledTask",
    "Stop-ScheduledTask", "Stop-Process", "Start-Process", "New-Item", "Set-Content",
    "Add-Content", "Out-File", "Move-Item", "Copy-Item", "Remove-Item", "Rename-Item",
)

_HARNESS = r"""
$ErrorActionPreference = 'Stop'
# Hard floor under the fakes: the real ScheduledTasks / NetTCPIP modules can
# never load in this process, so even a broken dry-run gate plus a fake that
# failed to shadow its cmdlet reaches "command not found", never a real task.
Import-Module Microsoft.PowerShell.Management, Microsoft.PowerShell.Utility
$PSModuleAutoLoadingPreference = 'None'
if (Get-Module ScheduledTasks) { throw 'MUTATION ScheduledTasks module loaded' }
# No @() here: PS 5.1 ConvertFrom-Json emits a JSON array as ONE object, so
# @() would wrap it and every lookup would match the whole list.
$global:FakeTasks = Get-Content -Raw -LiteralPath $env:PKG7_FAKE_TASKS | ConvertFrom-Json
function global:Get-ScheduledTask {
    [CmdletBinding()] param([string]$TaskName, [string]$TaskPath)
    @($global:FakeTasks | Where-Object {
        $_.TaskName -eq $TaskName -and (-not $TaskPath -or $_.TaskPath -eq $TaskPath) })
}
function global:Export-ScheduledTask {
    [CmdletBinding()] param([string]$TaskName, [string]$TaskPath)
    $t = @($global:FakeTasks | Where-Object { $_.TaskName -eq $TaskName })[0]
    '<?xml version="1.0" encoding="UTF-16"?><Task version="1.2" ' +
    'xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"><Principals>' +
    '<Principal id="Author"><LogonType>' + $t.Principal.LogonType +
    '</LogonType></Principal></Principals></Task>'
}
function global:Get-NetTCPConnection {
    [CmdletBinding()] param($LocalPort, $State)
    @()
}
foreach ($m in $env:PKG7_TRIP.Split(',')) {
    Set-Item -LiteralPath ("function:global:" + $m) `
        -Value ([scriptblock]::Create("throw 'MUTATION " + $m + "'"))
}
$splat = @{}
foreach ($p in ($env:PKG7_ARGS | ConvertFrom-Json).psobject.Properties) { $splat[$p.Name] = $p.Value }
& $env:PKG7_SCRIPT @splat
$code = $LASTEXITCODE
if (Get-Module ScheduledTasks) { throw 'MUTATION ScheduledTasks module loaded' }
exit $code
"""


def test_the_harness_floor_blocks_the_real_task_module():
    # Positive control for the floor in _HARNESS, probed with a READ cmdlet
    # only: with autoload off, the real Get-ScheduledTask does not resolve.
    command = (
        "Import-Module Microsoft.PowerShell.Management, Microsoft.PowerShell.Utility; "
        "$PSModuleAutoLoadingPreference = 'None'; "
        "try { [void](Get-ScheduledTask -TaskName 'pkg7-floor-probe' -ErrorAction Stop); "
        "'FLOOR=open' } catch { 'FLOOR=' + $_.FullyQualifiedErrorId }"
    )
    proc = _ps51(["-Command", command])
    assert "FLOOR=CommandNotFoundException" in proc.stdout, f"{proc.stdout}\n{proc.stderr}"


def _fake_task(name: str, state: str = "Ready", logon: str = "Interactive") -> dict:
    return {"TaskName": name, "TaskPath": "\\", "State": state,
            "Principal": {"LogonType": logon, "RunLevel": "Highest", "UserId": "op"}}


def _run_dry(tmp_path: Path, tasks: list[dict], args: dict) -> subprocess.CompletedProcess:
    if not PS51.is_file():
        pytest.skip("Windows PowerShell 5.1 not available on this host")
    fake = tmp_path / "fake_tasks.json"
    fake.write_text(json.dumps(tasks), encoding="ascii")
    harness = tmp_path / "harness.ps1"
    harness.write_text(_HARNESS, encoding="ascii")
    lowered = {k.lower() for k in args}
    assert not lowered & {"apply", "confirm"}, "these tests only ever run the default dry run"
    env = dict(os.environ, PKG7_FAKE_TASKS=str(fake), PKG7_SCRIPT=str(SCRIPT),
               PKG7_TRIP=",".join(_MUTATORS_TO_TRIP), PKG7_ARGS=json.dumps(args))
    return subprocess.run(
        [str(PS51), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(harness)],
        capture_output=True, text=True, timeout=180, env=env,
        creationflags=NO_WINDOW if os.name == "nt" else 0)


def test_default_dry_run_plans_every_present_task_and_changes_nothing(tmp_path):
    backups = tmp_path / "backups"
    tasks = [_fake_task(n, "Running") for n in CORE if n != "RC-DSKeepalive"]
    tasks.append(_fake_task("RC-LiveFlipWatcher"))
    proc = _run_dry(tmp_path, tasks, {"BackupRoot": str(backups)})
    out = proc.stdout + proc.stderr
    assert "MUTATION" not in out, out
    assert proc.returncode == 0, out
    assert "DRY RUN" in out
    for name in CORE:
        if name == "RC-DSKeepalive":
            assert re.search(r"RC-DSKeepalive\s*:\s*not registered", out), out
        else:
            assert f"would unregister {name}" in out, (name, out)
            assert f"would write {name}.xml" in out, (name, out)
    assert "would unregister RC-LiveFlipWatcher" not in out, "opt-in only"
    assert not backups.exists(), "a dry run creates no backup folder"


def test_dry_run_with_the_opt_in_adds_only_live_flip_watcher(tmp_path):
    backups = tmp_path / "backups"
    tasks = [_fake_task(n) for n in (*CORE, *OPTIONAL)]
    proc = _run_dry(tmp_path, tasks, {"BackupRoot": str(backups), "IncludeLiveFlipWatcher": True})
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0 and "MUTATION" not in out, out
    for name in (*CORE, *OPTIONAL):
        assert f"would unregister {name}" in out, (name, out)
    assert not backups.exists()


def test_dry_run_with_nothing_registered_reports_nothing_to_do(tmp_path):
    proc = _run_dry(tmp_path, [], {"BackupRoot": str(tmp_path / "b")})
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0 and "MUTATION" not in out, out
    assert "nothing to unregister" in out
    assert "would unregister" not in out


def _backup(root: Path, entries: list[tuple[str, str]], tamper: str = "") -> Path:
    folder = root / "cutover-20261026-000000"
    folder.mkdir(parents=True)
    tasks = []
    for name, logon in entries:
        xml = ('<?xml version="1.0" encoding="UTF-16"?><Task version="1.2" '
               'xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"><Principals>'
               f'<Principal id="Author"><LogonType>{logon}</LogonType></Principal>'
               '</Principals></Task>')
        data = b"\xff\xfe" + xml.encode("utf-16-le")
        (folder / f"{name}.xml").write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        if name == tamper:
            digest = "0" * 64
        tasks.append({"name": name, "path": "\\", "state": "Ready", "logon_type": logon,
                      "run_level": "Highest", "file": f"{name}.xml", "sha256": digest,
                      "bytes": len(data)})
    (folder / "manifest.json").write_text(
        json.dumps({"schema": 1, "tool": "tools/launcher_cutover.ps1",
                    "created": "2026-10-26T00:00:00Z", "tasks": tasks}), encoding="ascii")
    return folder


def test_rollback_dry_run_plans_the_reimport_and_changes_nothing(tmp_path):
    root = tmp_path / "backups"
    folder = _backup(root, [("RC-Supervisor", "InteractiveToken"),
                            ("RC-LCUAgent", "S4U"), ("RC-DaemonSlayer", "")])
    before = sorted((p.name, p.stat().st_size) for p in folder.iterdir())
    present = [_fake_task("RC-LCUAgent")]  # already back: left alone
    proc = _run_dry(tmp_path, present, {"Rollback": True, "BackupRoot": str(root)})
    out = proc.stdout + proc.stderr
    assert "MUTATION" not in out, out
    assert proc.returncode == 0, out
    assert "DRY RUN" in out
    assert "would re-register RC-Supervisor" in out
    assert "would re-register RC-DaemonSlayer" in out
    assert re.search(r"RC-LCUAgent\s*:\s*already registered", out), out
    assert "would re-register RC-LCUAgent" not in out
    assert sorted((p.name, p.stat().st_size) for p in folder.iterdir()) == before


def test_rollback_dry_run_refuses_a_tampered_or_password_backup(tmp_path):
    root = tmp_path / "backups"
    _backup(root, [("RC-Supervisor", "InteractiveToken"), ("RC-HotkeyListener", "Password")],
            tamper="RC-Supervisor")
    proc = _run_dry(tmp_path, [], {"Rollback": True, "BackupRoot": str(root)})
    out = proc.stdout + proc.stderr
    assert "MUTATION" not in out, out
    assert proc.returncode == 1, out
    assert re.search(r"RC-Supervisor\s*:\s*sha256 mismatch", out), out
    assert re.search(r"RC-HotkeyListener\s*:\s*needs its account password", out), out
    assert "would re-register" not in out


def test_rollback_with_no_backup_refuses(tmp_path):
    proc = _run_dry(tmp_path, [], {"Rollback": True, "BackupRoot": str(tmp_path / "none")})
    out = proc.stdout + proc.stderr
    assert proc.returncode == 2 and "MUTATION" not in out, out
    assert "no backup" in out
