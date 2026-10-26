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
                (ops/rc_transactional_deploy.py:80 DEFAULT_KEY_PATH, :94
                _read_key, :133 verify_request), in ensure_key's exact format
                (`secrets.token_hex(32)` + LF, ASCII, :115). Written HERE, by
                the same restricted-first writer as the tokens, rather than by
                running the worker's `--init-key`: ensure_key publishes the
                key under ops/runtime/'s inherited ACL before anyone can
                tighten it (:114-117), and closing that window from outside
                would mean re-ACLing the whole shared ops/runtime/ tree.
                Format parity is pinned by a test against the real ensure_key
                / sign_request / verify_request. It is a symmetric key that
                never leaves the machine (the launcher's updater, PKG-2, signs
                with it and the worker verifies with it), so there is no
                public / private split to make.

Writes, in this order (no secret byte ever sits where another principal can
open it):
  1. on the first secret that needs creating, a FRESH randomly named folder
     ops/runtime/first_run/run-<pid>-<random>/ (gitignored) is made with a
     plain mkdir, restricted (inheritance removed, one inheritable ACE for
     this user, owner set to this user), then VERIFIED by reading the
     security descriptor back (`verify_private`: owner = this user's SID, a
     protected DACL, every ACE an explicit allow for that SID - nothing
     inherited, no other principal). A stale or shared folder is never
     reused. If the mkdir, the restriction or the verify fails, NOTHING is
     written and every secret still to create reads `error` (name-only
     log line). One folder per run, removed (with its scratch files) at the
     end of the run;
  2. inside it, each scratch file is created EXCLUSIVELY and stays open; its
     ACL is made explicit (protected, this user only) while it is empty -
     a failed restriction deletes it and writes nothing for that secret;
  3. the secret is written through that SAME creating handle (never a
     reopen by name) and fsynced;
  4. publish with os.link, which fails if the name exists, so a concurrent
     writer's secret is kept (the ensure_key precedent, :117). Fail closed
     where the volume cannot hard-link (FAT / exFAT, the scratch on another
     volume: `_links_unsupported`): that secret reads `error`, and nothing
     is ever created in place under the target folder's inherited ACL.
     Nothing here ever replaces an existing file.

ACL: Windows = `icacls <path> /inheritance:r /grant:r *<SID>:(F)` (`(OI)(CI)`
plus `/setowner *<SID>` for a folder), the current process token's user SID
(USERDOMAIN\\USERNAME as a fallback), run windowless (CREATE_NO_WINDOW) with
a timeout; POSIX = mode 0600 (0700 for a folder), verified as owner = this
uid and no group / other bits. A volume without ACL or hard-link support
therefore gets no secret: set RC_VISION_TOKEN for the services instead.

Logging: report lines name the secret, its root-relative path and its state,
never a value. Stdlib only - it runs under the host's `-I` interpreter.
"""
from __future__ import annotations

import errno
import os
import re
import secrets
import subprocess
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
SCRATCH_REL = ("ops", "runtime", "first_run")              # gitignored (.gitignore:197)

VISION_TOKEN_BYTES = 16      # 32 hex chars, core/vision_token.py:15
DASH_TOKEN_BYTES = 32        # 64 hex chars
DEPLOY_KEY_BYTES = 32        # 64 hex chars, ops/rc_transactional_deploy.py:115
DEPLOY_KEY_MIN_CHARS = 32    # ops/rc_transactional_deploy.py:103

ICACLS_TIMEOUT_S = 30.0

_SID_RE = re.compile(r"^S-1(-\d+)+$")
_ACCOUNT_RE = re.compile(r"^[^\x00-\x1f\"*:<>?|/]{1,256}$")
_O_BINARY = getattr(os, "O_BINARY", 0)
_O_NOINHERIT = getattr(os, "O_NOINHERIT", 0)

# "This volume cannot hard-link here" - the ONLY link failures that may take
# the exclusive-create path. Windows: ERROR_INVALID_FUNCTION (FAT / exFAT),
# ERROR_NOT_SAME_DEVICE, ERROR_NOT_SUPPORTED. POSIX: EPERM (vfat refuses
# link), EXDEV, EOPNOTSUPP / ENOTSUP, ENOSYS. Anything else is an error.
_NO_LINK_WINERRORS = frozenset({1, 17, 50})
_NO_LINK_ERRNOS = frozenset(e for e in (
    errno.EPERM, errno.EXDEV, getattr(errno, "EOPNOTSUPP", None),
    getattr(errno, "ENOTSUP", None), errno.ENOSYS) if e is not None)

# Win32 security-descriptor constants (winnt.h / accctrl.h).
_SE_FILE_OBJECT = 1
_OWNER_SECURITY_INFORMATION = 0x1
_DACL_SECURITY_INFORMATION = 0x4
_SE_DACL_PROTECTED = 0x1000
_ACCESS_ALLOWED_ACE_TYPE = 0
_INHERITED_ACE = 0x10
_ACL_SIZE_INFORMATION = 2
_TOKEN_QUERY = 0x0008
_TOKEN_USER = 1

ACL_FAILED = "acl could not be restricted to the current user; secret not written"
SCRATCH_FAILED = ("no scratch folder private to the current user could be made "
                  "and verified; secret not written")
NO_LINKS = ("no hard link from the private scratch folder to the target on this volume; "
            "secret not written (fail closed)")


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


def _win_api() -> Tuple[Any, Any, Any, Any]:
    """(ctypes, wintypes, advapi32, kernel32) with explicit prototypes on
    PRIVATE WinDLL handles, never the shared ctypes.windll (service_host.py
    `_kernel32` gives the reason)."""
    import ctypes
    from ctypes import wintypes
    vp, ptr = ctypes.c_void_p, ctypes.POINTER
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi.OpenProcessToken.argtypes = (wintypes.HANDLE, wintypes.DWORD, ptr(wintypes.HANDLE))
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.GetTokenInformation.argtypes = (wintypes.HANDLE, ctypes.c_int, vp,
                                           wintypes.DWORD, ptr(wintypes.DWORD))
    advapi.GetTokenInformation.restype = wintypes.BOOL
    advapi.ConvertSidToStringSidW.argtypes = (vp, ptr(vp))
    advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
    advapi.GetNamedSecurityInfoW.argtypes = (wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD,
                                             ptr(vp), ptr(vp), ptr(vp), ptr(vp), ptr(vp))
    advapi.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi.GetSecurityDescriptorControl.argtypes = (vp, ptr(wintypes.WORD), ptr(wintypes.DWORD))
    advapi.GetSecurityDescriptorControl.restype = wintypes.BOOL
    advapi.GetAclInformation.argtypes = (vp, vp, wintypes.DWORD, ctypes.c_int)
    advapi.GetAclInformation.restype = wintypes.BOOL
    advapi.GetAce.argtypes = (vp, wintypes.DWORD, ptr(vp))
    advapi.GetAce.restype = wintypes.BOOL
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    k32.LocalFree.argtypes = (vp,)
    k32.LocalFree.restype = vp
    return ctypes, wintypes, advapi, k32


def _sid_string(api: Tuple[Any, Any, Any, Any], psid: Any) -> Optional[str]:
    ctypes, _wintypes, advapi, k32 = api
    out = ctypes.c_void_p()
    if not psid or not advapi.ConvertSidToStringSidW(psid, ctypes.byref(out)):
        return None
    try:
        return ctypes.wstring_at(out.value)
    finally:
        k32.LocalFree(out)


def current_user_sid() -> Optional[str]:
    """The string SID of this process token's user, or None off Windows or
    on any failure."""
    if os.name != "nt":
        return None
    try:
        api = _win_api()
        ctypes, wintypes, advapi, k32 = api
        token = wintypes.HANDLE()
        if not advapi.OpenProcessToken(k32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)):
            return None
        try:
            need = wintypes.DWORD(0)
            advapi.GetTokenInformation(token, _TOKEN_USER, None, 0, ctypes.byref(need))
            if not need.value:
                return None
            buf = ctypes.create_string_buffer(need.value)
            if not advapi.GetTokenInformation(token, _TOKEN_USER, buf, need, ctypes.byref(need)):
                return None
            sid = _sid_string(api, ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0])
        finally:
            k32.CloseHandle(token)
    except (OSError, AttributeError, ValueError):
        return None
    return sid if _SID_RE.match(sid or "") else None


AceInfo = Tuple[int, int, Optional[str]]     # (AceType, AceFlags, SID or None)


def _read_descriptor(api: Tuple[Any, Any, Any, Any], owner: Any, dacl: Any,
                     sd: Any) -> Optional[Tuple[Optional[str], bool, List[AceInfo]]]:
    """(owner SID, DACL protected?, ACEs) from a GetNamedSecurityInfoW
    result, or None when any part cannot be read (incl. a NULL DACL, which
    grants everyone everything)."""
    ctypes, wintypes, advapi, _k32 = api
    if not dacl.value:
        return None
    control, revision = wintypes.WORD(), wintypes.DWORD()
    if not advapi.GetSecurityDescriptorControl(sd, ctypes.byref(control), ctypes.byref(revision)):
        return None
    info = (wintypes.DWORD * 3)()         # ACL_SIZE_INFORMATION: AceCount first
    if not advapi.GetAclInformation(dacl, info, ctypes.sizeof(info), _ACL_SIZE_INFORMATION):
        return None
    aces: List[AceInfo] = []
    for index in range(info[0]):
        ace = ctypes.c_void_p()
        if not advapi.GetAce(dacl, index, ctypes.byref(ace)) or not ace.value:
            return None
        ace_type, ace_flags = ctypes.string_at(ace.value, 2)   # ACE_HEADER
        # ACCESS_ALLOWED_ACE: 4-byte header + 4-byte mask, then the SID.
        ace_sid = _sid_string(api, ace.value + 8) if ace_type == _ACCESS_ALLOWED_ACE_TYPE else None
        aces.append((ace_type, ace_flags, ace_sid))
    return (_sid_string(api, owner.value), bool(control.value & _SE_DACL_PROTECTED), aces)


def _is_private_descriptor(owner_sid: Optional[str], protected: bool,
                           aces: List[AceInfo], sid: str) -> bool:
    """The private-to-this-user rule, separate from the Win32 reads: owner
    is this user, the DACL is protected (inherits nothing), and it has at
    least one ACE, every one an explicit allow for exactly this SID."""
    return (owner_sid == sid and protected and bool(aces)
            and all(_ace_is_private(t, f, s, sid) for t, f, s in aces))


def _ace_is_private(ace_type: int, ace_flags: int, ace_sid: Optional[str], sid: str) -> bool:
    """One ACE of a private DACL: an explicit (not inherited) allow for
    exactly this user's SID. A deny or any other principal fails it too."""
    return (ace_type == _ACCESS_ALLOWED_ACE_TYPE and not ace_flags & _INHERITED_ACE
            and ace_sid == sid)


def verify_private(path: Path, *, sid: Optional[str] = None) -> bool:
    """Read the security descriptor BACK and say whether `path` is private
    to the current user. Windows: owner = this user's SID, a protected DACL
    (nothing inherited), at least one ACE and every ACE an explicit allow
    for that SID - no other principal. POSIX: owner = this uid and no group /
    other mode bits. False - never an exception - on any doubt."""
    path = Path(path)
    if os.name != "nt":
        try:
            st = os.stat(path)
        except OSError:
            return False
        return st.st_uid == os.getuid() and not st.st_mode & 0o077
    sid = sid or current_user_sid()
    if not sid:
        return False
    try:
        api = _win_api()
        ctypes, _wintypes, advapi, k32 = api
        owner, dacl, sd = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        rc = advapi.GetNamedSecurityInfoW(
            str(path), _SE_FILE_OBJECT, _OWNER_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION,
            ctypes.byref(owner), None, ctypes.byref(dacl), None, ctypes.byref(sd))
        if rc != 0 or not sd.value:
            return False
        try:
            read = _read_descriptor(api, owner, dacl, sd)
        finally:
            k32.LocalFree(sd)
        return read is not None and _is_private_descriptor(*read, sid)
    except (OSError, AttributeError, ValueError):
        return False


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
    """Leave only the current user on `path`'s ACL (a folder also hands that
    single ACE to everything created in it later). True on success, False -
    never an exception - when it could not be done."""
    path = Path(path)
    folder = path.is_dir()
    win = (os.name == "nt") if windows is None else windows
    if not win:
        try:
            os.chmod(path, 0o700 if folder else 0o600)
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
    grant = f"{who}:(OI)(CI)(F)" if folder else f"{who}:(F)"
    steps = [["/inheritance:r", "/grant:r", grant]]
    if folder:
        # An elevated admin token's default owner is the Administrators
        # group; the private scratch folder is owned by this user instead.
        steps.append(["/setowner", who])
    for step in steps:
        argv = [_icacls(), str(path)] + step
        try:
            done = run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW,
                       timeout=ICACLS_TIMEOUT_S, check=False)
        except (OSError, subprocess.SubprocessError):
            return False
        if getattr(done, "returncode", 1) != 0:
            return False
    return True


# ------------------------------------------------------------ create


def _links_unsupported(exc: OSError) -> bool:
    """True only for "this volume cannot hard-link these two names"."""
    winerror = getattr(exc, "winerror", None)
    if winerror is not None:
        return winerror in _NO_LINK_WINERRORS
    return exc.errno in _NO_LINK_ERRNOS


def _scratch(path: Path, scratch_dir: Path) -> Path:
    return scratch_dir / f"{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"


def _open_new(path: Path) -> int:
    """Exclusive create of an EMPTY file (FileExistsError if the name is
    taken), mode 0600 where the OS honours it. Returns the creating handle;
    the secret is later written through THIS handle, never a reopen."""
    return os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY | _O_BINARY | _O_NOINHERIT,
                   0o600)


def _write_secret(fd: int, data: bytes) -> None:
    """Write `data` through the creating handle and fsync."""
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view):]
    os.fsync(fd)


def _unlink(path: Path) -> None:
    try:
        Path(path).unlink()
    except OSError:
        pass


def _remove_scratch_dir(path: Path) -> None:
    """Remove a per-run scratch folder and any scratch file left in it (a
    temp folder of this run only - nothing irreplaceable)."""
    try:
        for child in Path(path).iterdir():
            _unlink(child)
        Path(path).rmdir()
    except OSError:
        pass


class ScratchFolder:
    """One FRESH, randomly named, verified-private folder per provisioning
    run under SCRATCH_REL, made on the first secret that needs one (so a
    tree whose secrets all exist never gets one) and removed by close()."""

    def __init__(self, base: Path, restrict: Callable[[Path], bool],
                 verify: Callable[[Path], bool]) -> None:
        self.base = Path(base)
        self.restrict = restrict
        self.verify = verify
        self.path: Optional[Path] = None
        self.error: Optional[str] = None

    def get(self) -> Optional[Path]:
        """The private folder, or None (self.error says why) - then nothing
        may be written for any secret this run."""
        if self.path is not None or self.error is not None:
            return self.path
        try:
            self.base.mkdir(parents=True, exist_ok=True)
            path = self.base / f"run-{os.getpid()}-{secrets.token_hex(8)}"
            # A plain mkdir on Windows: Python 3.13+ turns mode 0o700 into
            # extra EXPLICIT ACEs (SYSTEM, Administrators) that /inheritance:r
            # would keep. POSIX gets 0700 from the start.
            if os.name == "nt":
                os.mkdir(path)
            else:
                os.mkdir(path, 0o700)
        except OSError as exc:
            self.error = f"{SCRATCH_FAILED} ({type(exc).__name__})"
            return None
        if not (self.restrict(path) and self.verify(path)):
            _remove_scratch_dir(path)
            self.error = SCRATCH_FAILED
            return None
        self.path = path
        return path

    def close(self) -> None:
        if self.path is not None:
            _remove_scratch_dir(self.path)
            self.path = None


def create_secret_file(path: Path, value: str, *, restrict: Callable[[Path], bool],
                       scratch_dir: Path) -> str:
    """Create `path` holding `value` + LF when it does not exist, staging in
    `scratch_dir` (a verified-private ScratchFolder).

    The order is the security property (module docstring "Writes"): the
    scratch file is created exclusively and kept open, made explicit-private
    while EMPTY, and only then is the secret written through that same
    handle; a failed restriction writes nothing.

    Returns "created"; "exists" (the name already existed or another writer
    won - its file is kept); "acl_failed" (nothing written); "no_links"
    (this volume cannot hard-link into place - nothing published)."""
    path = Path(path)
    if not valid_token(value):
        raise ValueError("refusing to write a token that is not printable ASCII")
    if path.exists():
        return "exists"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (value + "\n").encode("ascii")
    tmp = _scratch(path, Path(scratch_dir))
    try:
        fd = _open_new(tmp)
        try:
            if not restrict(tmp):
                return "acl_failed"                # fail closed: no secret byte written
            _write_secret(fd, data)
        finally:
            os.close(fd)
        try:
            os.link(tmp, path)
        except FileExistsError:
            return "exists"
        except OSError as exc:
            if _links_unsupported(exc):
                return "no_links"                  # fail closed, never created in place
            raise
        return "created"
    finally:
        _unlink(tmp)


def _new_secret(name: str, path: Path, nbytes: int, scratch: ScratchFolder,
                valid: Callable[[Path], bool]) -> SecretResult:
    if path.exists():
        if valid(path):
            return SecretResult(name, path, "present")
        return SecretResult(name, path, "invalid",
                            detail="existing file is not a valid secret; left as is")
    folder = scratch.get()
    if folder is None:
        return SecretResult(name, path, "error", acl=False, detail=scratch.error)
    try:
        state = create_secret_file(path, secrets.token_hex(nbytes), restrict=scratch.restrict,
                                   scratch_dir=folder)
    except OSError as exc:
        return SecretResult(name, path, "error", detail=f"write failed: {type(exc).__name__}")
    if state == "created":
        return SecretResult(name, path, "created", acl=True)
    if state == "acl_failed":
        return SecretResult(name, path, "error", acl=False, detail=ACL_FAILED)
    if state == "no_links":
        return SecretResult(name, path, "error", detail=NO_LINKS)
    return SecretResult(name, path, "present" if valid(path) else "invalid")


def _is_token(path: Path) -> bool:
    return read_token(path) is not None


# ------------------------------------------------------------ secrets


def provision_vision_token(root: Path, environ: Mapping[str, str], *,
                           scratch: ScratchFolder) -> SecretResult:
    path = Path(root).joinpath(*VISION_TOKEN_REL)
    env = _env_get(environ, VISION_TOKEN_ENV)
    if env and env.strip():
        return SecretResult("vision_token", path, "env",
                            detail=f"{VISION_TOKEN_ENV} is set; the reader uses it first")
    return _new_secret("vision_token", path, VISION_TOKEN_BYTES, scratch, _is_token)


def provision_dash_token(root: Path, *, scratch: ScratchFolder) -> SecretResult:
    return _new_secret("dash_token", Path(root).joinpath(*DASH_TOKEN_REL), DASH_TOKEN_BYTES,
                       scratch, _is_token)


def provision_deploy_key(root: Path, *, scratch: ScratchFolder) -> SecretResult:
    return _new_secret("deploy_key", Path(root).joinpath(*DEPLOY_KEY_REL), DEPLOY_KEY_BYTES,
                       scratch, _valid_deploy_key)


def provision(root: Path, *, dash_token_gate: bool = False,
              environ: Optional[Mapping[str, str]] = None,
              restrict: Optional[Callable[[Path], bool]] = None,
              verify: Optional[Callable[[Path], bool]] = None) -> ProvisionReport:
    """Create every missing per-install secret under `root`; idempotent.

    `environ` is the services' environment (default os.environ). The report's
    `env` holds RC_DASH_TOKEN only when `dash_token_gate` is true AND the
    stored dash token is valid; otherwise it is empty and the services'
    environment is left exactly as the profile made it. `restrict` /
    `verify` default to restrict_to_current_user / verify_private."""
    root = Path(root)
    environ = os.environ if environ is None else environ
    scratch = ScratchFolder(root.joinpath(*SCRATCH_REL),
                            restrict or restrict_to_current_user,
                            verify or verify_private)
    try:
        results = (
            provision_vision_token(root, environ, scratch=scratch),
            provision_dash_token(root, scratch=scratch),
            provision_deploy_key(root, scratch=scratch),
        )
    finally:
        scratch.close()
    env: Dict[str, str] = {}
    if dash_token_gate:
        token = read_token(root.joinpath(*DASH_TOKEN_REL))
        if token:
            env[DASH_TOKEN_ENV] = token
    return ProvisionReport(results, env, bool(dash_token_gate))
