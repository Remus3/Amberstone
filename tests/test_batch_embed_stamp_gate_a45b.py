"""A45b (s146) sibling sweep: the batch launchers that START the app on
python-embed\\pythonw.exe use it only when tools/build_python_embed.py
stamped it.

The dev checkout carries a hand-made python-embed (Python 3.11.9 from April,
no EMBED_STAMP.json, half the lock missing). `start.bat` and
`scripts/restart_clean.bat` (what `tools/dev_cli.py start-clean` runs)
preferred it to the PATH pythonw.exe on the bare existence of
pythonw.exe, so a checkout launch ran main.py on that stale runtime. A built
bundle always carries the stamp (tools/build_portable.py refuses an embed
`verify_embed_dir` rejects; tools/run_packaged_smoke.py requires the stamp),
so the gate changes nothing there. An unstamped embed now gets a printed
line and the PATH pythonw.exe (Option A), never a silent pick.

The key-check pickers (`RC_KEY_EMBED` in start.bat, scripts/restart.bat,
scripts/start_debug.bat) are out of scope: they run only the stdlib
core/anthropic_key.py, which the 3.11 runtime runs correctly.

RM-1229 (s146 A45b follow-up): a stamp alone was not enough. Both bats took
the embed when EMBED_STAMP.json merely EXISTED, so a stamped but stale embed
(built from another requirements.txt, the 3.11.9 runtime that stopped the
first cutover attempt) still ran from the bat launchers while the A45b
launcher (`embedFitness` in rc-shell/src/launcher.js) refuses it as
`stale-lock`. The bats now take the embed only when the stamp's
`requirements_sha256` is the SHA-256 of this tree's requirements.txt (the
same predicate: missing stamp, unreadable / hash-less stamp, missing lock and
a stale lock are all refused, named and skipped; hex case is ignored).

Each case runs the file's REAL launch block under cmd.exe with `start ""`
swapped for an echo, in a tmp tree - nothing is launched.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
LAUNCHERS = ("start.bat", "scripts/restart_clean.bat")

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe batch semantics")


def _lines(rel: str) -> list[str]:
    return (REPO / rel).read_text(encoding="ascii").splitlines()


def _launch_block(rel: str) -> list[str]:
    """From the `set "EMBED_OK="` reset that opens the gate (else the first
    `if` that tests EMBED_PYW) to the `)` closing the launch's if / else."""
    lines = _lines(rel)
    stripped = [ln.strip() for ln in lines]
    first_if = next(i for i, ln in enumerate(stripped)
                    if ln.lower().startswith("if ") and "EMBED_PYW" in ln)
    resets = [i for i in range(first_if) if stripped[i].lower() == 'set "embed_ok="']
    start = resets[-1] if resets else first_if
    first_start = next(i for i in range(start, len(stripped))
                       if stripped[i].lower().startswith('start ""'))
    end = next(i for i in range(first_start, len(stripped)) if stripped[i] == ")")
    return lines[start:end + 1]


LOCK = b"example-pkg==1.0.0 \\\n    --hash=sha256:" + b"0" * 64 + b"\n"
LOCK_SHA = hashlib.sha256(LOCK).hexdigest()
OTHER_SHA = hashlib.sha256(b"another lock\n").hexdigest()


def _stamp_text(sha, cpython_sha: str = OTHER_SHA) -> str:
    """The stamp the way tools/build_python_embed.py writes it (pinned by
    test_the_stamp_writer_keeps_the_layout_the_bats_match)."""
    stamp = {"tool": "tools/build_python_embed.py", "cpython": {"sha256": cpython_sha}}
    if sha is not None:
        stamp["requirements_sha256"] = sha
    return json.dumps(stamp, indent=2, sort_keys=True) + "\n"


def _run(tmp_path: Path, rel: str, *, embed: bool, stamp, lock: bool = True,
         root_name: str = "", env: dict | None = None) -> str:
    """stamp: False (no file), True (matches the lock), a hex string (that
    requirements_sha256), None (a stamp with no requirements_sha256) or
    bytes (written as is)."""
    root = tmp_path / root_name if root_name else tmp_path
    root.mkdir(exist_ok=True)
    if lock:
        (root / "requirements.txt").write_bytes(LOCK)
    emb = root / "python-embed"
    if embed:
        emb.mkdir()
        (emb / "pythonw.exe").write_bytes(b"")
        if stamp is not False:
            if isinstance(stamp, bytes):
                body = stamp
            else:
                body = _stamp_text(LOCK_SHA if stamp is True else stamp).encode("ascii")
            (emb / "EMBED_STAMP.json").write_bytes(body)
    set_embed = [ln for ln in _lines(rel) if ln.strip().lower().startswith("set embed_pyw=")]
    assert len(set_embed) == 1, (rel, set_embed)
    block = [ln.replace('start ""', "echo LAUNCH") for ln in _launch_block(rel)]
    head = ["@echo off", "setlocal", f'set "RC_ROOT={root}"', set_embed[0]]
    bat = root / "launch_block_harness.bat"
    bat.write_bytes(("\r\n".join(head + block) + "\r\n").encode("ascii"))
    cmd = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cmd.exe"
    run_env = {k: v for k, v in os.environ.items()
               if k.upper() not in ("EMBED_OK", "EMBED_WHY", "EMBED_WANT")}
    run_env.update(env or {})
    res = subprocess.run([str(cmd), "/d", "/c", str(bat)], capture_output=True, text=True,
                         cwd=str(root), timeout=30, env=run_env)
    assert res.returncode == 0, res.stderr
    return res.stdout


def _launches(out: str) -> list[str]:
    return [ln.strip() for ln in out.splitlines() if ln.strip().startswith("LAUNCH")]


@pytest.mark.parametrize("rel", LAUNCHERS)
def test_an_unstamped_embed_is_not_launched_and_says_why(tmp_path, rel):
    out = _run(tmp_path, rel, embed=True, stamp=False)
    launches = _launches(out)
    assert len(launches) == 1, out
    assert "python-embed" not in launches[0], f"{rel} launched the unstamped runtime: {out}"
    assert launches[0].split()[1].lower() == "pythonw.exe", out
    assert "EMBED_STAMP.json" in out, f"{rel} switched interpreters silently: {out}"


@pytest.mark.parametrize("rel", LAUNCHERS)
def test_a_stamped_embed_is_launched(tmp_path, rel):
    out = _run(tmp_path, rel, embed=True, stamp=True)
    launches = _launches(out)
    assert len(launches) == 1 and "python-embed\\pythonw.exe" in launches[0], out
    assert "EMBED_STAMP.json" not in out, out


@pytest.mark.parametrize("rel", LAUNCHERS)
def test_no_embed_is_plain_option_a(tmp_path, rel):
    out = _run(tmp_path, rel, embed=False, stamp=False)
    launches = _launches(out)
    assert len(launches) == 1 and launches[0].split()[1].lower() == "pythonw.exe", out
    assert "EMBED_STAMP.json" not in out, out


def _refused(out: str, rel: str) -> None:
    launches = _launches(out)
    assert len(launches) == 1, out
    assert "python-embed" not in launches[0], f"{rel} launched an unfit runtime: {out}"
    assert launches[0].split()[1].lower() == "pythonw.exe", out
    assert "requirements.txt" in out, f"{rel} switched interpreters silently: {out}"


@pytest.mark.parametrize("rel", LAUNCHERS)
def test_a_stamp_from_another_lock_is_not_launched_and_says_why(tmp_path, rel):
    """RM-1229: the A45b launcher's `stale-lock`."""
    _refused(_run(tmp_path, rel, embed=True, stamp=OTHER_SHA), rel)


@pytest.mark.parametrize("rel", LAUNCHERS)
def test_the_locks_hash_under_another_key_is_not_a_match(tmp_path, rel):
    """Only `requirements_sha256` counts: the lock's hash written as the
    cpython archive's `sha256` must not satisfy the check."""
    body = _stamp_text(OTHER_SHA, cpython_sha=LOCK_SHA).encode("ascii")
    _refused(_run(tmp_path, rel, embed=True, stamp=body), rel)


@pytest.mark.parametrize("rel", LAUNCHERS)
@pytest.mark.parametrize("stamp", [None, b"{}", b"not json", b"", "abc", LOCK_SHA + "0"],
                         ids=["no-hash-key", "empty-object", "not-json", "empty-file",
                              "short-hash", "long-hash"])
def test_a_stamp_without_this_locks_hash_is_not_launched(tmp_path, rel, stamp):
    """RM-1229: the launcher's `bad-stamp` - no readable requirements_sha256."""
    _refused(_run(tmp_path, rel, embed=True, stamp=stamp), rel)


@pytest.mark.parametrize("rel", LAUNCHERS)
def test_no_lock_to_check_against_is_not_launched(tmp_path, rel):
    """RM-1229: the launcher's `no-lock`."""
    _refused(_run(tmp_path, rel, embed=True, stamp=True, lock=False), rel)


@pytest.mark.parametrize("rel", LAUNCHERS)
def test_an_inherited_gate_variable_does_not_launch_a_stale_embed(tmp_path, rel):
    """The gate resets EMBED_OK / EMBED_WHY / EMBED_WANT before it runs, so a
    caller's environment cannot pre-approve a stale embed or pre-fill the
    hash it is compared with."""
    inherited = {"EMBED_OK": "1", "EMBED_WANT": OTHER_SHA, "EMBED_WHY": ""}
    assert any(ln.strip().lower() == 'set "embed_ok="' for ln in _launch_block(rel)), rel
    _refused(_run(tmp_path, rel, embed=True, stamp=OTHER_SHA, env=inherited), rel)


@pytest.mark.parametrize("rel", LAUNCHERS)
def test_an_inherited_reason_does_not_refuse_a_fit_embed(tmp_path, rel):
    """The EMBED_WHY reset: a caller's leftover reason must not skip a fit
    embed (second RM-1229 verifier nit)."""
    out = _run(tmp_path, rel, embed=True, stamp=True, env={"EMBED_WHY": "leftover"})
    launches = _launches(out)
    assert len(launches) == 1 and "python-embed\\pythonw.exe" in launches[0], out
    assert "leftover" not in out, out


@pytest.mark.parametrize("rel", LAUNCHERS)
def test_a_matching_stamp_in_upper_case_hex_is_launched(tmp_path, rel):
    """The launcher compares `want.toLowerCase()`; the bats ignore case too."""
    out = _run(tmp_path, rel, embed=True, stamp=LOCK_SHA.upper())
    launches = _launches(out)
    assert len(launches) == 1 and "python-embed\\pythonw.exe" in launches[0], out


@pytest.mark.parametrize("rel", LAUNCHERS)
@pytest.mark.parametrize("fit", [True, False], ids=["fit", "stale"])
def test_a_root_with_spaces_and_parentheses_is_checked_the_same(tmp_path, rel, fit):
    """The dev checkout's own folder name has a space; a parenthesis is the
    usual way a cmd for /f clause breaks."""
    out = _run(tmp_path, rel, embed=True, stamp=True if fit else OTHER_SHA,
               root_name="Riot C (x)")
    launches = _launches(out)
    assert len(launches) == 1, out
    if fit:
        assert "python-embed\\pythonw.exe" in launches[0], out
    else:
        _refused(out, rel)


def test_the_stamp_writer_keeps_the_layout_the_bats_match():
    """The bats match the literal `"requirements_sha256": "<hex>"` that
    json.dumps(indent=2) writes, so the writer's layout is part of the
    contract: a compact separator would refuse every built embed."""
    src = (REPO / "tools" / "build_python_embed.py").read_text(encoding="utf-8")
    assert '"requirements_sha256": sha256_file(requirements)' in src
    assert "json.dumps(stamp, indent=2, sort_keys=True)" in src
    assert '"requirements_sha256": "' in _stamp_text(LOCK_SHA)
    for rel in LAUNCHERS:
        text = (REPO / rel).read_text(encoding="ascii")
        assert 'requirements_sha256\\": \\"' in text, rel
