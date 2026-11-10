"""gated_g601_shell_fresh.py - the G6-01 precondition as one read-only command.

G6-01 (GATE 6) reads "rc-shell Electron MAIN relaunch - PREREQUISITE for every
`[OVERLAY-*]` batch": the renderer half auto-reloads (ADR-008) but the Electron
MAIN process keeps the `rc-shell/src` code it started with. Since the
2026-10-31 launcher cutover any app start relaunches MAIN, so the row is a
recurring PRECONDITION, not a closable check. This tool answers it for the
shell running right now:

1. ``main``: the Electron MAIN process(es) - an ``electron.exe`` or packaged
   ``Amberstone Shell.exe`` whose command line carries no ``--type=`` (the
   renderer, GPU and utility children all do). Read from ``Win32_Process``
   through powershell.exe CIM, CREATE_NO_WINDOW.
2. ``source``: the newest bound on the code MAIN would load - the later of the
   newest commit touching ``rc-shell/src`` (committer time) and the newest
   on-disk mtime of a file under ``rc-shell/src``. The mtime half exists because
   a lane commit's committer time can predate the merge that wrote its bytes
   into the checkout; a stray touch can only make a fresh shell read STALE,
   which fails closed.

Verdicts (``grade``): PASS iff exactly one MAIN, it is a CHECKOUT launch of
``<repo>/rc-shell`` (``node_modules/electron/dist/electron.exe``) named
``--profile dev`` on its argv, and it was created AFTER the source bound.
NO_SHELL / PROFILE_UNNAMED / UNKNOWN are INCOMPLETE; MULTIPLE_MAIN / PACKAGED /
WRONG_CHECKOUT / STALE are FAIL. PACKAGED fails on purpose: a packaged shell
loads the app it was built from, so its start time says nothing about
``rc-shell/src``. PROFILE_UNNAMED is not a fail because ``RC_LAUNCHER_PROFILE``
can name the profile (rc-shell/src/launcher.js ``resolveProfile``) and another
process's environment is not read here; ``rc-shell/launch_overlay.bat`` names
none and starts no service.

Run it against the checkout the shell was launched from (the MAIN checkout,
``--repo``); run from a lane worktree it reports WRONG_CHECKOUT.

READ-ONLY: no file, registry or process write, no signal, no network, no
capture. It never ticks a row: PASS is the precondition every overlay row
states, not evidence that anything rendered.

USAGE
    python tools/gated_g601_shell_fresh.py [--repo <checkout>] [--json]

Exit 0 PASS, 1 INCOMPLETE, 2 FAIL.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent

SRC_REL = "rc-shell/src"
DEV_EXE_REL = ("rc-shell", "node_modules", "electron", "dist", "electron.exe")
CHECKOUT_IMAGE = "electron.exe"
PACKAGED_IMAGE = "Amberstone Shell.exe"
IMAGES = (CHECKOUT_IMAGE, PACKAGED_IMAGE)

# JavaScript String.prototype.trim()'s whitespace set (WhiteSpace + LineTerminator),
# so a value Python would strip but launcher.js keeps is never read as "dev".
_JS_WS = ("\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006"
          "\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff")

PASS = "PASS"
INCOMPLETE_VERDICTS = ("NO_SHELL", "PROFILE_UNNAMED", "UNKNOWN")
FAIL_VERDICTS = ("MULTIPLE_MAIN", "PACKAGED", "WRONG_CHECKOUT", "STALE")

_PS_QUERY = (
    "$f = \"Name='electron.exe' or Name='Amberstone Shell.exe'\"; "
    "@(Get-CimInstance Win32_Process -Filter $f | ForEach-Object { "
    "[pscustomobject]@{pid=$_.ProcessId; ppid=$_.ParentProcessId; name=$_.Name; "
    "created=$_.CreationDate.ToUniversalTime().ToString('o'); "
    "exe=$_.ExecutablePath; cmd=$_.CommandLine} }) | ConvertTo-Json -Compress"
)


def _flags() -> int:
    """CREATE_NO_WINDOW on Windows; any other platform refuses creationflags."""
    return 0x08000000 if sys.platform == "win32" else 0


def _parse_ts(text) -> datetime | None:
    """An aware UTC datetime from an ISO string, or None."""
    if not isinstance(text, str) or not text.strip():
        return None
    s = text.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # Win32 CIM 'o' format carries 7 fractional digits; fromisoformat takes 6.
    head, dot, tail = s.partition(".")
    if dot:
        frac = ""
        rest = ""
        for i, ch in enumerate(tail):
            if not ch.isdigit():
                rest = tail[i:]
                break
            frac += ch
        s = head + "." + frac[:6] + rest
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc)


def list_shell_processes(run=subprocess.run) -> list[dict] | None:
    """Every electron.exe / packaged-shell process, or None when the query fails."""
    try:
        proc = run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _PS_QUERY],
                   capture_output=True, text=True, timeout=60, creationflags=_flags())
    except (OSError, subprocess.SubprocessError):
        return None
    if getattr(proc, "returncode", 1) != 0:
        return None
    out = (proc.stdout or "").strip()
    if not out:
        return []
    try:
        data = json.loads(out)
    except ValueError:
        return None
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return None
    return [row for row in data if isinstance(row, dict)]


def split_cmdline(cmd: str) -> list[str]:
    """argv from a Windows command line, by shell32 CommandLineToArgvW rules.

    Whitespace splits outside quotes; 2n backslashes before a quote give n
    backslashes and toggle quoting, 2n+1 give n and a literal quote; other
    backslashes are literal; a doubled quote inside quotes is a literal quote
    that also ends the quoted run (shell32's rule, not the MSVC 2008 CRT's).
    A whitespace split would cut a quoted argument such as ``"--profile dev"``
    in two and invent a profile the shell never saw.
    """
    args: list[str] = []
    cur: list[str] = []
    inq = False
    have = False
    i, n = 0, len(cmd)
    while i < n:
        c = cmd[i]
        if c == "\\":
            j = i
            while j < n and cmd[j] == "\\":
                j += 1
            nb = j - i
            have = True
            if j < n and cmd[j] == '"':
                cur.append("\\" * (nb // 2))
                if nb % 2:
                    cur.append('"')
                    i = j + 1
                else:
                    i = j
                continue
            cur.append("\\" * nb)
            i = j
            continue
        if c == '"':
            have = True
            if inq and i + 1 < n and cmd[i + 1] == '"':
                # shell32: a doubled quote inside quotes is a literal quote AND
                # ends the quoted run (the MSVC 2008 CRT would stay quoted).
                cur.append('"')
                inq = False
                i += 2
                continue
            inq = not inq
            i += 1
            continue
        if c in " \t" and not inq:
            if have:
                args.append("".join(cur))
                cur = []
                have = False
            i += 1
            continue
        cur.append(c)
        have = True
        i += 1
    if have:
        args.append("".join(cur))
    return args


def is_main(row: dict) -> bool:
    """True for an Electron MAIN process: a shell image with no --type= switch."""
    name = str(row.get("name") or "")
    if name.lower() not in {i.lower() for i in IMAGES}:
        return False
    cmd = row.get("cmd")
    if not isinstance(cmd, str):
        return False
    return not any(tok.startswith("--type=") for tok in split_cmdline(cmd))


def argv_profile(cmd: str) -> str | None:
    """The --profile value on a command line, or None.

    A line-for-line port of rc-shell/src/launcher.js ``argValue`` over the
    Windows argv: the LAST occurrence wins; a separate value that is missing,
    blank or starts with "--" is no value (and is not consumed); ``--profile=``
    takes the trimmed remainder, empty meaning no value.
    """
    toks = split_cmdline(cmd)
    found = None
    i = 0
    while i < len(toks):
        tok = toks[i]
        if tok == "--profile":
            nxt = toks[i + 1] if i + 1 < len(toks) else None
            ok = nxt is not None and nxt.strip(_JS_WS) and not nxt.startswith("--")
            found = nxt.strip(_JS_WS) if ok else None
            if found is not None:
                i += 1
        elif tok.startswith("--profile="):
            found = tok[len("--profile="):].strip(_JS_WS) or None
        i += 1
    return found


def _norm(p) -> str:
    return str(p).replace("\\", "/").rstrip("/").lower()


def source_bound(repo: Path, run=subprocess.run) -> dict:
    """The newest commit and newest on-disk mtime under rc-shell/src."""
    out = {"commit": None, "commit_time": None, "mtime_file": None, "mtime": None,
           "bound": None, "error": None}
    try:
        proc = run(["git", "-C", str(repo), "log", "-1", "--format=%H %cI", "--", SRC_REL],
                   capture_output=True, text=True, timeout=60, creationflags=_flags())
        files = run(["git", "-C", str(repo), "ls-files", "-co", "--exclude-standard", "--", SRC_REL],
                    capture_output=True, text=True, timeout=60, creationflags=_flags())
    except (OSError, subprocess.SubprocessError) as exc:
        out["error"] = f"git: {type(exc).__name__}"
        return out
    if proc.returncode != 0 or files.returncode != 0:
        out["error"] = "git exit non-zero"
        return out
    parts = (proc.stdout or "").split()
    if len(parts) == 2:
        out["commit"] = parts[0][:12]
        ct = _parse_ts(parts[1])
        out["commit_time"] = ct.isoformat() if ct else None
    newest = None
    for rel in (files.stdout or "").splitlines():
        rel = rel.strip()
        if not rel:
            continue
        try:
            mt = (repo / rel).stat().st_mtime
        except OSError:
            continue
        if newest is None or mt > newest[0]:
            newest = (mt, rel)
    if newest is not None:
        out["mtime_file"] = newest[1]
        out["mtime"] = datetime.fromtimestamp(newest[0], tz=timezone.utc).isoformat()
    stamps = [t for t in (_parse_ts(out["commit_time"]), _parse_ts(out["mtime"])) if t]
    if not stamps:
        out["error"] = out["error"] or "no commit and no file under rc-shell/src"
        return out
    out["bound"] = max(stamps).isoformat()
    return out


def grade(mains: list[dict] | None, src: dict, repo: Path) -> dict:
    """The verdict for G6-01, with the reason. Pure; no I/O."""
    if mains is None:
        return {"verdict": "UNKNOWN", "reason": "process query failed"}
    if not mains:
        return {"verdict": "NO_SHELL", "reason": "no Electron MAIN process is running"}
    if len(mains) > 1:
        return {"verdict": "MULTIPLE_MAIN",
                "reason": f"{len(mains)} MAIN processes; which one draws the overlay is ambiguous"}
    row = mains[0]
    if str(row.get("name") or "").lower() == PACKAGED_IMAGE.lower():
        return {"verdict": "PACKAGED",
                "reason": "a packaged shell loads its build, not rc-shell/src; start time proves nothing"}
    exe = row.get("exe")
    if not isinstance(exe, str) or not exe.strip():
        return {"verdict": "UNKNOWN", "reason": "MAIN executable path unreadable (access denied?)"}
    want = _norm(Path(repo, *DEV_EXE_REL))
    if _norm(exe) != want:
        return {"verdict": "WRONG_CHECKOUT",
                "reason": "MAIN is not this checkout's rc-shell electron.exe; re-run with --repo"}
    prof = argv_profile(str(row.get("cmd") or ""))
    if prof != "dev":
        if prof is None:
            return {"verdict": "PROFILE_UNNAMED",
                    "reason": "no --profile on argv; RC_LAUNCHER_PROFILE may name it, "
                              "read ops/runtime/launcher_status.json"}
        return {"verdict": "WRONG_CHECKOUT", "reason": f"--profile {prof} is not the dev checkout launch"}
    created = _parse_ts(row.get("created"))
    bound = _parse_ts(src.get("bound"))
    if created is None or bound is None:
        return {"verdict": "UNKNOWN",
                "reason": "process start or source bound unreadable: " + str(src.get("error"))}
    if created <= bound:
        return {"verdict": "STALE",
                "reason": f"MAIN started {created.isoformat()} at or before the source bound "
                          f"{bound.isoformat()}; relaunch the app"}
    return {"verdict": PASS, "reason": f"MAIN started {created.isoformat()} after {bound.isoformat()}"}


def exit_code(verdict: str) -> int:
    if verdict == PASS:
        return 0
    if verdict in FAIL_VERDICTS:
        return 2
    return 1


def collect(repo: Path, run=subprocess.run) -> dict:
    rows = list_shell_processes(run=run)
    mains = None if rows is None else [r for r in rows if is_main(r)]
    src = source_bound(repo, run=run)
    result = grade(mains, src, repo)
    return {
        "row": "G6-01",
        "repo_is_tool_checkout": _norm(repo) == _norm(_REPO),
        "main": [{"pid": r.get("pid"), "name": r.get("name"), "created": r.get("created"),
                  "profile": argv_profile(str(r.get("cmd") or ""))} for r in (mains or [])],
        "children": 0 if rows is None else len(rows) - len(mains or []),
        "source": src,
        "verdict": result["verdict"],
        "reason": result["reason"],
        "measured_at": datetime.now(timezone.utc).isoformat(),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=str(_REPO), help="checkout the shell was launched from")
    parser.add_argument("--json", action="store_true", help="print the full result as JSON")
    args = parser.parse_args(argv)
    res = collect(Path(args.repo).resolve())
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        src = res["source"]
        print(f"G6-01 {res['verdict']}: {res['reason']}")
        print(f"  source bound {src.get('bound')} (commit {src.get('commit')} {src.get('commit_time')};"
              f" newest mtime {src.get('mtime_file')} {src.get('mtime')})")
        for m in res["main"]:
            print(f"  MAIN pid {m['pid']} {m['name']} created {m['created']} profile {m['profile']}")
    return exit_code(res["verdict"])


if __name__ == "__main__":
    sys.exit(main())
