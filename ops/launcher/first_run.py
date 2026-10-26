"""PKG-1b first-run provisioning: per-install secrets for a fresh install.

docs/PACKAGING_PLAN.md section 3.2: on launch the service host "provisions
per-install secrets on first run (dashboard token, deploy key via
ops/rc_transactional_deploy.py:108 ensure_key)". A fresh bundle carries none
of them, and one is fatal: core/vision_token.py raises at IMPORT when neither
RC_VISION_TOKEN nor config/vision_token.txt exists (core/vision_token.py:103,
reached from the module-level resolve at :136), so `import app` dies before
RC starts. ops/launcher/service_host.py calls `provision` in OWNED mode only,
once, before it spawns any service. Attach and blocked modes never call it.

Secrets (each created only when absent; an existing file is NEVER rewritten,
re-ACLed or validated into a rewrite - a bad one is reported, not replaced):

  vision_token  config/vision_token.txt - the reader's file
                (core/vision_token.py:69 `_CONFIG_PATH`; first line, stripped,
                :97; printable ASCII 0x21-0x7E only, :83). Value
                `secrets.token_hex(16)`, the rotation recipe at
                core/vision_token.py:15. The relay agents read the same file
                first (tools/lcu_agent.py:126, tools/liveclient_relay.py:83).
                Skipped when RC_VISION_TOKEN is set non-blank in the services'
                environment: the reader takes the env var first (:92-94).
  dash_token    ops/runtime/dash_token.txt - the per-install dashboard token
                (PACKAGING_PLAN 3.6). `secrets.token_hex(32)`, one line. It is
                STORED on every install but exported as RC_DASH_TOKEN (the
                gate at dashboard/_handler.py:654 and
                dashboard/routes_recordings.py:189) only when the profile sets
                `dash_token_gate: true` in services.json. Default OFF: a set
                token 401s the plain-browser control callers that send no
                X-RC-Token (PACKAGING_PLAN "Verifier findings" V3) until PKG-6
                injects the header and PKG-5 handles those callers.
                ops/runtime/ is gitignored and outside both the bundle and the
                update payload allow-list (PACKAGING_PLAN 3.4, PKG-4).
  deploy_key    ops/runtime/deploy_request.key - the per-machine HMAC key the
                deploy worker verifies signed requests with
                (ops/rc_transactional_deploy.py:80 DEFAULT_KEY_PATH, :133
                verify_request). Created by the worker's OWN `--init-key`
                (:693, which calls ensure_key at :699 -> :108): the key format
                and its create-if-absent race guard (:114-121) keep one owner,
                and this module still imports nothing from the RC tree. It is
                a symmetric key that never leaves the machine: the launcher's
                updater (PKG-2) signs with it and the worker verifies with it,
                both local, so there is no public / private split to make.

Writes: a per-writer scratch file under the gitignored ops/runtime/first_run/
(flushed + fsynced), the ACL restricted ON THE SCRATCH FILE, then published
under the real name with os.link, which
fails if the name exists - so a concurrent writer's secret is never
replaced (the ensure_key precedent, ops/rc_transactional_deploy.py:117).
Where hard links are unsupported (FAT / exFAT) it falls back to os.replace
after re-checking the name. A reader never sees a torn file either way.

ACL: Windows = `icacls <file> /inheritance:r /grant:r *<SID>:(F)` (the
current process token's user SID; USERDOMAIN\\USERNAME as a fallback), run
windowless (CREATE_NO_WINDOW) with a timeout; POSIX = mode 0600. A failure is
reported and not fatal: the file then keeps the ACL inherited from its folder
(a per-user install folder), and the host logs "acl not restricted".

Logging: report lines name the secret, its root-relative path and its state,
never a value. Stdlib only - it runs under the host's `-I` interpreter.
"""
from __future__ import annotations

import os
import re
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, NamedTuple, Optional, Tuple

# Same per-OS guard as ops/launcher/service_host.py:108: a non-zero
# creationflags raises on POSIX, and CI runs on ubuntu.
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

VISION_TOKEN_REL = ("config", "vision_token.txt")          # core/vision_token.py:69
VISION_TOKEN_ENV = "RC_VISION_TOKEN"                       # core/vision_token.py:92
DASH_TOKEN_REL = ("ops", "runtime", "dash_token.txt")
DASH_TOKEN_ENV = "RC_DASH_TOKEN"                           # dashboard/_handler.py:654
DEPLOY_KEY_REL = ("ops", "runtime", "deploy_request.key")  # ops/rc_transactional_deploy.py:80
DEPLOY_WORKER_REL = ("ops", "rc_transactional_deploy.py")
SCRATCH_REL = ("ops", "runtime", "first_run")              # gitignored (.gitignore:197)

VISION_TOKEN_BYTES = 16      # 32 hex chars, core/vision_token.py:15
DASH_TOKEN_BYTES = 32        # 64 hex chars
DEPLOY_KEY_MIN_CHARS = 32    # ops/rc_transactional_deploy.py:103

INIT_KEY_TIMEOUT_S = 60.0
ICACLS_TIMEOUT_S = 30.0

_SID_RE = re.compile(r"^S-1(-\d+)+$")
_ACCOUNT_RE = re.compile(r"^[^\x00-\x1f\"*:<>?|/]{1,256}$")


class SecretResult(NamedTuple):
    name: str
    path: Path
    state: str                      # created | present | env | invalid | error
    acl: Optional[bool] = None      # True restricted, False failed, None untouched
    detail: Optional[str] = None    # never a secret value


class ProvisionReport(NamedTuple):
    results: Tuple[SecretResult, ...]
    env: Dict[str, str]             # overrides for the services' environment
    gate: bool = False              # the profile's dash_token_gate

    def lines(self, root: Path) -> List[str]:
        """One log line per secret (+ the gate), names and paths only."""
        out = []
        for res in self.results:
            line = f"first run: {res.name} {res.state} ({_rel(res.path, root)})"
            if res.acl is True:
                line += ", acl restricted to the current user"
            elif res.acl is False:
                line += ", acl not restricted (inherited from its folder)"
            if res.detail:
                line += f": {res.detail}"
            out.append(line)
        if DASH_TOKEN_ENV in self.env:
            out.append(f"first run: dash token gate on, {DASH_TOKEN_ENV} exported to the services")
        elif self.gate:
            out.append("first run: dash token gate on but no valid dash token, "
                       "control endpoints stay ungated")
        return out


def _rel(path: Path, root: Path) -> str:
    try:
        return Path(path).relative_to(Path(root)).as_posix()
    except ValueError:
        return Path(path).name


# ------------------------------------------------------------ token text


def valid_token(text: str) -> bool:
    """Legal as a header value: non-empty, printable ASCII 0x21-0x7E only
    (core/vision_token.py:83 `_checked`)."""
    return bool(text) and all(0x21 <= ord(c) <= 0x7E for c in text)


def read_token(path: Path) -> Optional[str]:
    """The first line, stripped, when it is a valid token; else None. The
    reader's own rule (core/vision_token.py:97). Never raises."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    if not lines:
        return None
    tok = lines[0].strip()
    return tok if valid_token(tok) else None


def _valid_deploy_key(path: Path) -> bool:
    """ops/rc_transactional_deploy.py:94 `_read_key`: ASCII, stripped, at
    least 32 chars."""
    try:
        key = Path(path).read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        return False
    return len(key) >= DEPLOY_KEY_MIN_CHARS


def _env_get(environ: Mapping[str, str], key: str) -> Optional[str]:
    if key in environ:
        return environ[key]
    if os.name == "nt":
        for k, v in environ.items():
            if k.upper() == key.upper():
                return v
    return None


# ------------------------------------------------------------ ACL


def current_user_sid() -> Optional[str]:
    """The string SID of this process token's user, or None off Windows or
    on any failure. Private WinDLL handles, never the shared ctypes.windll
    (service_host.py `_kernel32` gives the reason)."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        advapi.OpenProcessToken.argtypes = (wintypes.HANDLE, wintypes.DWORD,
                                            ctypes.POINTER(wintypes.HANDLE))
        advapi.OpenProcessToken.restype = wintypes.BOOL
        advapi.GetTokenInformation.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                               wintypes.DWORD, ctypes.POINTER(wintypes.DWORD))
        advapi.GetTokenInformation.restype = wintypes.BOOL
        advapi.ConvertSidToStringSidW.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
        advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        k32.LocalFree.argtypes = (ctypes.c_void_p,)
        k32.LocalFree.restype = ctypes.c_void_p
        token = wintypes.HANDLE()
        if not advapi.OpenProcessToken(k32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
            return None
        try:
            need = wintypes.DWORD(0)
            advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(need))  # TokenUser
            if not need.value:
                return None
            buf = ctypes.create_string_buffer(need.value)
            if not advapi.GetTokenInformation(token, 1, buf, need, ctypes.byref(need)):
                return None
            psid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
            out = ctypes.c_void_p()
            if not advapi.ConvertSidToStringSidW(psid, ctypes.byref(out)):
                return None
            try:
                sid = ctypes.wstring_at(out.value)
            finally:
                k32.LocalFree(out)
        finally:
            k32.CloseHandle(token)
    except (OSError, AttributeError, ValueError):
        return None
    return sid if _SID_RE.match(sid or "") else None


def _icacls() -> str:
    # The System32 binary by absolute path, so a PATH entry cannot stand in
    # for it; the bare name only when SystemRoot is missing.
    system_root = os.environ.get("SystemRoot") or os.environ.get("SYSTEMROOT")
    if system_root:
        exe = Path(system_root) / "System32" / "icacls.exe"
        if exe.is_file():
            return str(exe)
    return "icacls"


def _account_name() -> Optional[str]:
    user = os.environ.get("USERNAME")
    if not user:
        return None
    domain = os.environ.get("USERDOMAIN")
    name = f"{domain}\\{user}" if domain else user
    return name if _ACCOUNT_RE.match(name.replace("\\", "")) else None


def restrict_to_current_user(path: Path, *, run: Callable[..., Any] = subprocess.run,
                             windows: Optional[bool] = None,
                             sid: Optional[str] = None) -> bool:
    """Leave only the current user on `path`'s ACL. True on success, False
    (never an exception) when it could not be done."""
    path = Path(path)
    win = (os.name == "nt") if windows is None else windows
    if not win:
        try:
            os.chmod(path, 0o600)
            return True
        except OSError:
            return False
    if sid is None:
        sid = current_user_sid()
        who = f"*{sid}" if sid else _account_name()
    else:
        who = f"*{sid}" if _SID_RE.match(sid) else None
    if not who:
        return False
    argv = [_icacls(), str(path), "/inheritance:r", "/grant:r", f"{who}:(F)"]
    try:
        done = run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW,
                   timeout=ICACLS_TIMEOUT_S, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return getattr(done, "returncode", 1) == 0


# ------------------------------------------------------------ create


def _scratch(path: Path, scratch_dir: Path) -> Path:
    return scratch_dir / f"{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"


def create_secret_file(path: Path, value: str, *,
                       restrict: Callable[[Path], bool],
                       scratch_dir: Optional[Path] = None) -> Tuple[bool, Optional[bool]]:
    """Create `path` holding `value` + LF when it does not exist.

    The scratch file lives in `scratch_dir` (default: beside `path`). The
    provisioner passes SCRATCH_REL under the gitignored ops/runtime/, so a
    write killed midway can never leave a secret-bearing scratch file in
    config/, where only config/vision_token.txt itself is ignored
    (.gitignore:60). Same volume, so the link / replace still works.

    Returns (created, acl): created is False when the name already existed
    or another writer won the race (its file is kept); acl is the result of
    `restrict` on the new file, None when nothing was created."""
    path = Path(path)
    if not valid_token(value):
        raise ValueError("refusing to write a token that is not printable ASCII")
    if path.exists():
        return False, None
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch_dir = Path(scratch_dir) if scratch_dir is not None else path.parent
    scratch_dir.mkdir(parents=True, exist_ok=True)
    tmp = _scratch(path, scratch_dir)
    try:
        with open(tmp, "x", encoding="ascii", newline="\n") as fh:
            fh.write(value + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        acl = bool(restrict(tmp))
        try:
            os.link(tmp, path)
        except FileExistsError:
            return False, None
        except OSError:
            # No hard links on this volume: replace, after one more look.
            if path.exists():
                return False, None
            os.replace(tmp, path)
        return True, acl
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def _token_secret(name: str, path: Path, nbytes: int,
                  restrict: Callable[[Path], bool], scratch_dir: Path) -> SecretResult:
    if path.exists():
        if read_token(path):
            return SecretResult(name, path, "present")
        return SecretResult(name, path, "invalid",
                            detail="existing file is not a printable-ASCII token; left as is")
    try:
        created, acl = create_secret_file(path, secrets.token_hex(nbytes), restrict=restrict,
                                          scratch_dir=scratch_dir)
    except OSError as exc:
        return SecretResult(name, path, "error", detail=f"write failed: {type(exc).__name__}")
    if created:
        return SecretResult(name, path, "created", acl=acl)
    ok = read_token(path) is not None
    return SecretResult(name, path, "present" if ok else "invalid")


# ------------------------------------------------------------ secrets


def provision_vision_token(root: Path, environ: Mapping[str, str], *,
                           restrict: Callable[[Path], bool]) -> SecretResult:
    path = Path(root).joinpath(*VISION_TOKEN_REL)
    env = _env_get(environ, VISION_TOKEN_ENV)
    if env and env.strip():
        return SecretResult("vision_token", path, "env",
                            detail=f"{VISION_TOKEN_ENV} is set; the reader uses it first")
    return _token_secret("vision_token", path, VISION_TOKEN_BYTES, restrict,
                         Path(root).joinpath(*SCRATCH_REL))


def provision_dash_token(root: Path, *, restrict: Callable[[Path], bool]) -> SecretResult:
    path = Path(root).joinpath(*DASH_TOKEN_REL)
    return _token_secret("dash_token", path, DASH_TOKEN_BYTES, restrict,
                         Path(root).joinpath(*SCRATCH_REL))


def provision_deploy_key(root: Path, *, restrict: Callable[[Path], bool],
                         run: Callable[..., Any] = subprocess.run,
                         python: Optional[str] = None) -> SecretResult:
    root = Path(root)
    path = root.joinpath(*DEPLOY_KEY_REL)
    if path.exists():
        if _valid_deploy_key(path):
            return SecretResult("deploy_key", path, "present")
        return SecretResult("deploy_key", path, "invalid",
                            detail="existing key is unreadable or too short; left as is")
    worker = root.joinpath(*DEPLOY_WORKER_REL)
    if not worker.is_file():
        return SecretResult("deploy_key", path, "error",
                            detail=f"{'/'.join(DEPLOY_WORKER_REL)} missing, no key created")
    argv = [python or sys.executable, "-I", str(worker), "--init-key"]
    try:
        done = run(argv, cwd=str(root), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW,
                   timeout=INIT_KEY_TIMEOUT_S, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return SecretResult("deploy_key", path, "error",
                            detail=f"--init-key did not run: {type(exc).__name__}")
    code = getattr(done, "returncode", 1)
    if code != 0 or not path.is_file():
        return SecretResult("deploy_key", path, "error",
                            detail=f"--init-key exit {code}, no key file")
    # ensure_key wrote it with the folder's inherited ACL; tighten it now.
    return SecretResult("deploy_key", path, "created", acl=bool(restrict(path)))


def provision(root: Path, *, dash_token_gate: bool = False,
              environ: Optional[Mapping[str, str]] = None,
              restrict: Optional[Callable[[Path], bool]] = None,
              run: Optional[Callable[..., Any]] = None,
              python: Optional[str] = None) -> ProvisionReport:
    """Create every missing per-install secret under `root`; idempotent.

    `environ` is the services' environment (default os.environ). The report's
    `env` holds RC_DASH_TOKEN only when `dash_token_gate` is true AND the
    stored dash token is valid; otherwise it is empty and the services'
    environment is left exactly as the profile made it."""
    root = Path(root)
    environ = os.environ if environ is None else environ
    restrict = restrict or restrict_to_current_user
    run = run or subprocess.run
    results = (
        provision_vision_token(root, environ, restrict=restrict),
        provision_dash_token(root, restrict=restrict),
        provision_deploy_key(root, restrict=restrict, run=run, python=python),
    )
    env: Dict[str, str] = {}
    if dash_token_gate:
        token = read_token(root.joinpath(*DASH_TOKEN_REL))
        if token:
            env[DASH_TOKEN_ENV] = token
    return ProvisionReport(results, env, bool(dash_token_gate))
