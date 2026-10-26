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
                the same private-first writer as the tokens, rather than by
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
open it, and every check is made on an object this process holds open):
  1. BASE. On the first secret that needs creating, ops/runtime/first_run/
     (gitignored) is created private if missing, then restricted on every
     run (inheritance removed, one inheritable ACE for this user, owner set
     to this user), then PINNED - opened with backup semantics, its reparse
     point not followed, and a share mode WITHOUT FILE_SHARE_DELETE, so no
     one can rename or delete it (or, measured, any ancestor of it) while
     held - and VERIFIED through that handle (`verify_held`: GetSecurityInfo
     on the handle; owner = this user's SID, a protected DACL, every ACE an
     explicit allow for that SID - nothing inherited, no other principal).
  2. RUN FOLDER. A fresh, randomly named run-<pid>-<random>/ is created
     PRIVATE FROM BIRTH (CreateDirectoryW with the security descriptor
     "O:<SID>D:P(A;OICI;FA;;;<SID>)"), pinned the same way, its identity
     recorded (volume serial + file index), verified through the handle and
     checked empty. A stale or shared folder is never reused. If any step of
     1 or 2 fails, NOTHING is written and every secret still to create reads
     `error` (name-only log line).
  3. FILE. Each scratch file is created EXCLUSIVELY and PRIVATE FROM BIRTH
     (CreateFileW CREATE_NEW, share mode 0, descriptor
     "O:<SID>D:P(A;;FA;;;<SID>)"; POSIX mode 0600 dir_fd-relative) and kept
     open. Before a byte is written: the name must still be the open file
     (os.stat vs os.fstat), the file's parent must BE the pinned run folder
     (its final path's parent opened and compared by volume serial + file
     index), and its owner + DACL must read back private THROUGH the open
     handle - else nothing is written for that secret. Only then is the
     secret written through that SAME handle and fsynced.
  4. PUBLISH with os.link, which fails if the name exists, so a concurrent
     writer's secret is kept (the ensure_key precedent, :117); the published
     name must then be the very file that was written (identity compare),
     else it is removed and the secret reads `error`. Fail closed where the
     volume cannot hard-link (FAT / exFAT, another volume:
     `_links_unsupported`): nothing is ever created in place under the
     target folder's inherited ACL. Nothing here replaces an existing file.
  5. The run folder is deleted through its own handle at the end of the run
     and both pins are released.
POSIX does the same with descriptors: base and run folder are held as
O_DIRECTORY | O_NOFOLLOW fds, and every scratch create / stat / link / unlink
is dir_fd-relative to the held run folder (O_NOFOLLOW on the file), so a
renamed or swapped path cannot redirect it.

ACL: Windows = `icacls <path> /inheritance:r /grant:r *<SID>:(F)` (`(OI)(CI)`
for a folder) then `/setowner *<SID>`, the current process token's user SID
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
import stat
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
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)

# POSIX: every scratch operation is relative to the held run-folder fd.
_POSIX_DIR_FD_OK = os.name != "nt" and {
    os.open, os.mkdir, os.stat, os.unlink, os.rmdir, os.link} <= os.supports_dir_fd

# The ONLY link failures that mean "this volume cannot hard-link here"; they
# fail the secret CLOSED (nothing is ever created in place). Windows:
# ERROR_INVALID_FUNCTION (FAT / exFAT), ERROR_NOT_SAME_DEVICE,
# ERROR_NOT_SUPPORTED. POSIX: EPERM (vfat refuses link), EXDEV, EOPNOTSUPP /
# ENOTSUP, ENOSYS. Any other link error is reported as a write failure.
_NO_LINK_WINERRORS = frozenset({1, 17, 50})
_NO_LINK_ERRNOS = frozenset(e for e in (
    errno.EPERM, errno.EXDEV, getattr(errno, "EOPNOTSUPP", None),
    getattr(errno, "ENOTSUP", None), errno.ENOSYS) if e is not None)

# Win32 constants (winnt.h, accctrl.h, fileapi.h, minwinbase.h, sddl.h).
_SE_FILE_OBJECT = 1
_OWNER_SECURITY_INFORMATION = 0x1
_DACL_SECURITY_INFORMATION = 0x4
_SE_DACL_PROTECTED = 0x1000
_ACCESS_ALLOWED_ACE_TYPE = 0
_INHERITED_ACE = 0x10
_ACL_SIZE_INFORMATION = 2
_TOKEN_QUERY = 0x0008
_TOKEN_USER = 1
_DELETE = 0x00010000
_READ_CONTROL = 0x00020000
_FILE_READ_ATTRIBUTES = 0x0080
_FILE_SHARE_READ = 0x1
_FILE_SHARE_WRITE = 0x2
_FILE_SHARE_DELETE = 0x4
_OPEN_EXISTING = 3
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_ATTRIBUTE_DIRECTORY = 0x10
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_FILE_DISPOSITION_INFO = 4
_SDDL_REVISION_1 = 1
_GENERIC_WRITE = 0x40000000
_CREATE_NEW = 1
_FILE_ATTRIBUTE_NORMAL = 0x80
# Held pins share read / write but NEVER delete: a rename or delete of the
# folder (or, measured, of an ancestor) fails while the pin is open.
_PIN_SHARE = _FILE_SHARE_READ | _FILE_SHARE_WRITE

ACL_FAILED = ("the scratch file did not read back private to the current user; "
              "secret not written")
SCRATCH_FAILED = ("no scratch folder private to the current user could be made, "
                  "pinned and verified; secret not written")
MOVED = ("the scratch file is not inside the pinned private folder; "
         "secret not written")
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


# ------------------------------------------------------------ Win32


class _Api:
    """ctypes, wintypes and PRIVATE WinDLL handles with explicit prototypes,
    never the shared ctypes.windll (service_host.py `_kernel32` gives the
    reason)."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes as w
        vp, ptr = ctypes.c_void_p, ctypes.POINTER
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        for fn, args, res in (
            (advapi.OpenProcessToken, (w.HANDLE, w.DWORD, ptr(w.HANDLE)), w.BOOL),
            (advapi.GetTokenInformation, (w.HANDLE, ctypes.c_int, vp, w.DWORD, ptr(w.DWORD)), w.BOOL),
            (advapi.ConvertSidToStringSidW, (vp, ptr(vp)), w.BOOL),
            (advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW,
             (w.LPCWSTR, w.DWORD, ptr(vp), vp), w.BOOL),
            (advapi.GetSecurityInfo,
             (w.HANDLE, ctypes.c_int, w.DWORD, ptr(vp), ptr(vp), ptr(vp), ptr(vp), ptr(vp)), w.DWORD),
            (advapi.GetSecurityDescriptorControl, (vp, ptr(w.WORD), ptr(w.DWORD)), w.BOOL),
            (advapi.GetAclInformation, (vp, vp, w.DWORD, ctypes.c_int), w.BOOL),
            (advapi.GetAce, (vp, w.DWORD, ptr(vp)), w.BOOL),
            (k32.GetCurrentProcess, (), w.HANDLE),
            (k32.CloseHandle, (w.HANDLE,), w.BOOL),
            (k32.LocalFree, (vp,), vp),
            (k32.CreateFileW, (w.LPCWSTR, w.DWORD, w.DWORD, vp, w.DWORD, w.DWORD, w.HANDLE), w.HANDLE),
            (k32.CreateDirectoryW, (w.LPCWSTR, vp), w.BOOL),
            (k32.GetFileInformationByHandle, (w.HANDLE, vp), w.BOOL),
            (k32.GetFinalPathNameByHandleW, (w.HANDLE, w.LPWSTR, w.DWORD, w.DWORD), w.DWORD),
            (k32.SetFileInformationByHandle, (w.HANDLE, ctypes.c_int, vp, w.DWORD), w.BOOL),
        ):
            fn.argtypes = args
            fn.restype = res

        class FileInfo(ctypes.Structure):     # BY_HANDLE_FILE_INFORMATION
            _fields_ = [("attributes", w.DWORD), ("created", w.DWORD * 2),
                        ("accessed", w.DWORD * 2), ("written", w.DWORD * 2),
                        ("volume", w.DWORD), ("size_high", w.DWORD), ("size_low", w.DWORD),
                        ("links", w.DWORD), ("index_high", w.DWORD), ("index_low", w.DWORD)]

        class SecurityAttributes(ctypes.Structure):
            _fields_ = [("length", w.DWORD), ("descriptor", vp), ("inherit", w.BOOL)]

        self.ctypes, self.w, self.advapi, self.k32 = ctypes, w, advapi, k32
        self.FileInfo, self.SecurityAttributes = FileInfo, SecurityAttributes
        self.invalid = ctypes.c_void_p(-1).value

    def ok(self, handle: Any) -> bool:
        return bool(handle) and handle != self.invalid


_API: Optional[_Api] = None


def _api() -> _Api:
    global _API
    if _API is None:
        _API = _Api()
    return _API


def _sid_string(api: _Api, psid: Any) -> Optional[str]:
    out = api.ctypes.c_void_p()
    if not psid or not api.advapi.ConvertSidToStringSidW(psid, api.ctypes.byref(out)):
        return None
    try:
        return api.ctypes.wstring_at(out.value)
    finally:
        api.k32.LocalFree(out)


def current_user_sid() -> Optional[str]:
    """The string SID of this process token's user, or None off Windows or
    on any failure."""
    if os.name != "nt":
        return None
    try:
        api = _api()
        ct, w = api.ctypes, api.w
        token = w.HANDLE()
        if not api.advapi.OpenProcessToken(api.k32.GetCurrentProcess(), _TOKEN_QUERY,
                                           ct.byref(token)):
            return None
        try:
            need = w.DWORD(0)
            api.advapi.GetTokenInformation(token, _TOKEN_USER, None, 0, ct.byref(need))
            if not need.value:
                return None
            buf = ct.create_string_buffer(need.value)
            if not api.advapi.GetTokenInformation(token, _TOKEN_USER, buf, need, ct.byref(need)):
                return None
            sid = _sid_string(api, ct.cast(buf, ct.POINTER(ct.c_void_p))[0])
        finally:
            api.k32.CloseHandle(token)
    except (OSError, AttributeError, ValueError):
        return None
    return sid if _SID_RE.match(sid or "") else None


AceInfo = Tuple[int, int, Optional[str]]     # (AceType, AceFlags, SID or None)


def _read_descriptor(api: _Api, owner: Any, dacl: Any,
                     sd: Any) -> Optional[Tuple[Optional[str], bool, List[AceInfo]]]:
    """(owner SID, DACL protected?, ACEs) from a GetSecurityInfo result, or
    None when any part cannot be read (incl. a NULL DACL, which grants
    everyone everything)."""
    ct, w = api.ctypes, api.w
    if not dacl.value:
        return None
    control, revision = w.WORD(), w.DWORD()
    if not api.advapi.GetSecurityDescriptorControl(sd, ct.byref(control), ct.byref(revision)):
        return None
    info = (w.DWORD * 3)()         # ACL_SIZE_INFORMATION: AceCount first
    if not api.advapi.GetAclInformation(dacl, info, ct.sizeof(info), _ACL_SIZE_INFORMATION):
        return None
    aces: List[AceInfo] = []
    for index in range(info[0]):
        ace = ct.c_void_p()
        if not api.advapi.GetAce(dacl, index, ct.byref(ace)) or not ace.value:
            return None
        ace_type, ace_flags = ct.string_at(ace.value, 2)   # ACE_HEADER
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


def _win_open(path: Any, access: int, share: int) -> Optional[int]:
    """CreateFileW with backup semantics (folders open too) and the reparse
    point itself opened, never followed. None on failure."""
    api = _api()
    handle = api.k32.CreateFileW(str(path), access, share, None, _OPEN_EXISTING,
                                 _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
                                 None)
    return handle if api.ok(handle) else None


def _win_close(handle: Optional[int]) -> None:
    if handle:
        _api().k32.CloseHandle(handle)


def _win_info(handle: int) -> Optional[Tuple[int, Tuple[int, int]]]:
    """(attributes, (volume serial, file index)) of an open handle."""
    api = _api()
    info = api.FileInfo()
    if not api.k32.GetFileInformationByHandle(handle, api.ctypes.byref(info)):
        return None
    return info.attributes, (info.volume, (info.index_high << 32) | info.index_low)


def _win_final_path(handle: int) -> Optional[str]:
    api = _api()
    size = 1024
    for _ in range(2):
        buf = api.ctypes.create_unicode_buffer(size)
        n = api.k32.GetFinalPathNameByHandleW(handle, buf, size, 0)
        if n == 0:
            return None
        if n < size:
            return buf.value
        size = n + 1
    return None


def _win_handle_private(handle: int, sid: str) -> bool:
    """Owner + DACL read THROUGH the handle (GetSecurityInfo), never by path."""
    api = _api()
    ct = api.ctypes
    owner, dacl, sd = ct.c_void_p(), ct.c_void_p(), ct.c_void_p()
    rc = api.advapi.GetSecurityInfo(
        handle, _SE_FILE_OBJECT, _OWNER_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION,
        ct.byref(owner), None, ct.byref(dacl), None, ct.byref(sd))
    if rc != 0 or not sd.value:
        return False
    try:
        read = _read_descriptor(api, owner, dacl, sd)
    finally:
        api.k32.LocalFree(sd)
    return read is not None and _is_private_descriptor(*read, sid)


def _win_create_private_dir(path: Path, sid: str) -> int:
    """CreateDirectoryW with the private descriptor from birth: owner = this
    user, protected DACL, one inheritable full-control ACE for this user.
    Returns 0 on success, else the Win32 error code."""
    api = _api()
    ct = api.ctypes
    psd = ct.c_void_p()
    sddl = f"O:{sid}D:P(A;OICI;FA;;;{sid})"
    if not api.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, _SDDL_REVISION_1, ct.byref(psd), None):
        return ct.get_last_error() or 1
    try:
        attrs = api.SecurityAttributes(ct.sizeof(api.SecurityAttributes), psd, False)
        if api.k32.CreateDirectoryW(str(path), ct.byref(attrs)):
            return 0
        return ct.get_last_error() or 1
    finally:
        api.k32.LocalFree(psd)


def _win_delete_by_handle(handle: Optional[int]) -> bool:
    """Mark the (empty) folder behind `handle` for deletion: it goes when
    the handle closes, wherever it is - never a path lookup."""
    if not handle:
        return False
    api = _api()
    flag = api.ctypes.c_ubyte(1)            # FILE_DISPOSITION_INFO.DeleteFile
    return bool(api.k32.SetFileInformationByHandle(handle, _FILE_DISPOSITION_INFO,
                                                   api.ctypes.byref(flag), 1))


# ------------------------------------------------------------ ACL


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
    # /setowner too: an elevated admin token's default owner is the
    # Administrators group, and a private object is owned by this user.
    steps = [["/inheritance:r", "/grant:r", grant], ["/setowner", who]]
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


# ------------------------------------------------------------ held folders


class HeldDir:
    """A folder pinned for the whole run. Windows: a CreateFileW handle
    (backup semantics, reparse point not followed, share mode without
    FILE_SHARE_DELETE) - it cannot be renamed or deleted by anyone while
    held. POSIX: an O_DIRECTORY | O_NOFOLLOW fd that every scratch operation
    is relative to. `identity` = (volume serial, file index) / (st_dev,
    st_ino)."""

    def __init__(self, path: Path, name: str, *, handle: Optional[int] = None,
                 fd: Optional[int] = None, identity: Tuple[int, int] = (0, 0)) -> None:
        self.path = Path(path)
        self.name = name
        self.handle = handle
        self.fd = fd
        self.identity = identity

    def close(self) -> None:
        handle, self.handle = self.handle, None
        _win_close(handle)
        fd, self.fd = self.fd, None
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


def hold_dir(path: Path, *, parent: Optional[HeldDir] = None,
             delete: bool = False) -> Optional[HeldDir]:
    """Pin the folder at `path` (relative to `parent`'s fd on POSIX). None
    when it cannot be opened or is not a plain folder (a reparse point or
    symlink is refused)."""
    path = Path(path)
    if os.name == "nt":
        access = _READ_CONTROL | _FILE_READ_ATTRIBUTES | (_DELETE if delete else 0)
        handle = _win_open(path, access, _PIN_SHARE)
        if handle is None:
            return None
        info = _win_info(handle)
        if info is None or not info[0] & _FILE_ATTRIBUTE_DIRECTORY \
                or info[0] & _FILE_ATTRIBUTE_REPARSE_POINT:
            _win_close(handle)
            return None
        return HeldDir(path, path.name, handle=handle, identity=info[1])
    flags = os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW | _O_CLOEXEC
    try:
        if parent is not None:
            fd = os.open(path.name, flags, dir_fd=parent.fd)
        else:
            fd = os.open(str(path), flags)
    except OSError:
        return None
    st = os.fstat(fd)
    if not stat.S_ISDIR(st.st_mode):
        os.close(fd)
        return None
    return HeldDir(path, path.name, fd=fd, identity=(st.st_dev, st.st_ino))


def verify_held(held: HeldDir, *, sid: Optional[str] = None) -> bool:
    """Private-to-this-user, read THROUGH the pin: Windows GetSecurityInfo on
    the handle (owner = this SID, protected DACL, only explicit allows for
    this SID); POSIX fstat (owner = this uid, no group / other bits)."""
    if os.name != "nt":
        if held.fd is None:
            return False
        st = os.fstat(held.fd)
        return st.st_uid == os.getuid() and not st.st_mode & 0o077
    sid = sid or current_user_sid()
    if not sid or not held.handle:
        return False
    try:
        return _win_handle_private(held.handle, sid)
    except (OSError, AttributeError, ValueError):
        return False


def verify_private(path: Path, *, sid: Optional[str] = None) -> bool:
    """verify_held for a path, through a short-lived handle (files or
    folders). False - never an exception - on any doubt."""
    path = Path(path)
    if os.name != "nt":
        try:
            st = os.stat(path, follow_symlinks=False)
        except OSError:
            return False
        return st.st_uid == os.getuid() and not st.st_mode & 0o077
    sid = sid or current_user_sid()
    if not sid:
        return False
    try:
        handle = _win_open(path, _READ_CONTROL,
                           _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE)
        if handle is None:
            return False
        try:
            return _win_handle_private(handle, sid)
        finally:
            _win_close(handle)
    except (OSError, AttributeError, ValueError):
        return False


def _make_private_dir(path: Path, sid: Optional[str], parent: Optional[HeldDir]) -> None:
    """Create `path` private from birth; raises OSError on failure
    (FileExistsError when the name is taken)."""
    if os.name == "nt":
        err = _win_create_private_dir(path, sid) if sid else 1
        if err == 183:                                      # ERROR_ALREADY_EXISTS
            raise FileExistsError(errno.EEXIST, "exists", str(path))
        if err:
            raise OSError(errno.EACCES, f"CreateDirectoryW failed ({err})", str(path))
        return
    if parent is not None:
        os.mkdir(path.name, 0o700, dir_fd=parent.fd)
    else:
        os.mkdir(path, 0o700)


def _after_scratch_verified(scratch: "ScratchFolder") -> None:
    """Test seam: runs once the run folder is pinned and verified, before
    any scratch file exists. Production does nothing here."""


class ScratchFolder:
    """The pinned, verified-private base and a FRESH run folder for one
    provisioning run, made on the first secret that needs them (a tree whose
    secrets all exist gets neither) and released by close()."""

    def __init__(self, base: Path, restrict: Callable[[Path], bool],
                 verify: Callable[[HeldDir], bool]) -> None:
        self.base = Path(base)
        self.restrict = restrict
        self.verify = verify
        self.base_dir: Optional[HeldDir] = None
        self.run: Optional[HeldDir] = None
        self.error: Optional[str] = None

    @property
    def path(self) -> Optional[Path]:
        return self.run.path if self.run is not None else None

    def get(self) -> Optional[HeldDir]:
        """The pinned private run folder, or None (self.error says why) -
        then nothing may be written for any secret this run."""
        if self.run is not None or self.error is not None:
            return self.run
        try:
            if not self._open():
                self._fail(SCRATCH_FAILED)
        except OSError as exc:
            self._fail(f"{SCRATCH_FAILED} ({type(exc).__name__})")
        return self.run

    def _open(self) -> bool:
        if os.name != "nt" and not _POSIX_DIR_FD_OK:
            return False
        sid = current_user_sid() if os.name == "nt" else None
        if os.name == "nt" and not sid:
            return False
        self.base.parent.mkdir(parents=True, exist_ok=True)
        try:
            _make_private_dir(self.base, sid, None)
        except FileExistsError:
            pass
        if not self.restrict(self.base):                    # every run, even if it existed
            return False
        self.base_dir = hold_dir(self.base)
        if self.base_dir is None or not self.verify(self.base_dir):
            return False
        path = self.base / f"run-{os.getpid()}-{secrets.token_hex(8)}"
        _make_private_dir(path, sid, self.base_dir)
        self.run = hold_dir(path, parent=self.base_dir, delete=True)
        if self.run is None or not self.verify(self.run) or self._listing():
            return False
        _after_scratch_verified(self)
        return True

    def _listing(self) -> List[str]:
        if os.name != "nt" and os.listdir in os.supports_fd:
            return os.listdir(self.run.fd)
        return os.listdir(self.run.path)

    def _fail(self, message: str) -> None:
        self.error = message
        self.close()

    def _release_pins(self) -> None:
        """Close the pins WITHOUT removing anything (tests use it to model
        an attacker who got past them). The recorded identities stay, so
        Windows still has its parent-identity check; POSIX, whose safety is
        the held dir_fd, then refuses every scratch operation."""
        for held in (self.run, self.base_dir):
            if held is not None:
                held.close()

    def close(self) -> None:
        run, self.run = self.run, None
        if run is not None:
            if os.name == "nt":
                _win_delete_by_handle(run.handle)
            elif run.fd is not None and self.base_dir is not None and self.base_dir.fd is not None:
                try:
                    st = os.stat(run.name, dir_fd=self.base_dir.fd, follow_symlinks=False)
                    if (st.st_dev, st.st_ino) == run.identity:
                        os.rmdir(run.name, dir_fd=self.base_dir.fd)
                except OSError:
                    pass
            run.close()
        base, self.base_dir = self.base_dir, None
        if base is not None:
            base.close()


# ------------------------------------------------------------ create


def _links_unsupported(exc: OSError) -> bool:
    """True only for "this volume cannot hard-link these two names"."""
    winerror = getattr(exc, "winerror", None)
    if winerror is not None:
        return winerror in _NO_LINK_WINERRORS
    return exc.errno in _NO_LINK_ERRNOS


def _scratch_name(path: Path) -> str:
    return f"{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"


def _win_create_private_file(tmp: Path) -> int:
    """CreateFileW(CREATE_NEW) with the private descriptor from birth (owner
    = this user, protected DACL, one explicit full-control ACE for this
    user) and share mode 0, as an fd. FileExistsError if the name exists."""
    import msvcrt
    sid = current_user_sid()
    if not sid:
        raise OSError(errno.EACCES, "no user SID", str(tmp))
    api = _api()
    ct = api.ctypes
    psd = ct.c_void_p()
    if not api.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            f"O:{sid}D:P(A;;FA;;;{sid})", _SDDL_REVISION_1, ct.byref(psd), None):
        raise OSError(errno.EACCES, "security descriptor", str(tmp))
    try:
        attrs = api.SecurityAttributes(ct.sizeof(api.SecurityAttributes), psd, False)
        handle = api.k32.CreateFileW(str(tmp), _GENERIC_WRITE | _READ_CONTROL, 0,
                                     ct.byref(attrs), _CREATE_NEW, _FILE_ATTRIBUTE_NORMAL,
                                     None)
        err = ct.get_last_error()
    finally:
        api.k32.LocalFree(psd)
    if not api.ok(handle):
        if err in (80, 183):                     # ERROR_FILE_EXISTS / ALREADY_EXISTS
            raise FileExistsError(errno.EEXIST, "exists", str(tmp))
        raise OSError(errno.EACCES, f"CreateFileW failed ({err})", str(tmp))
    try:
        return msvcrt.open_osfhandle(handle, 0)
    except OSError:
        _win_close(handle)
        raise


def _open_new(tmp: Path, scratch: HeldDir) -> int:
    """Exclusive create of an EMPTY scratch file that is private FROM BIRTH
    (FileExistsError if the name is taken). Windows: CreateFileW with the
    private descriptor; POSIX: mode 0600, relative to the held run-folder
    fd, never following a symlink. Returns the creating handle as an fd;
    the secret is later written through THIS handle, never a reopen."""
    if os.name == "nt":
        return _win_create_private_file(tmp)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | _O_NOFOLLOW | _O_CLOEXEC
    return os.open(tmp.name, flags, 0o600, dir_fd=scratch.fd)


def _write_secret(fd: int, data: bytes) -> None:
    """Write `data` through the creating handle and fsync."""
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view):]
    os.fsync(fd)


def _identity_of_name(tmp: Path, scratch: HeldDir) -> Optional[Tuple[int, int]]:
    try:
        if os.name == "nt":
            st = os.stat(tmp, follow_symlinks=False)
        else:
            st = os.stat(tmp.name, dir_fd=scratch.fd, follow_symlinks=False)
    except OSError:
        return None
    return st.st_dev, st.st_ino


def _win_parent_identity(fd: int) -> Optional[Tuple[int, int]]:
    """Identity of the folder that ACTUALLY holds the open file: its final
    path (from the file handle), parent opened with backup semantics."""
    import msvcrt
    final = _win_final_path(msvcrt.get_osfhandle(fd))
    if not final or "\\" not in final:
        return None
    parent = _win_open(final.rsplit("\\", 1)[0], _FILE_READ_ATTRIBUTES,
                       _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE)
    if parent is None:
        return None
    try:
        info = _win_info(parent)
    finally:
        _win_close(parent)
    return info[1] if info is not None else None


def _inside_held(fd: int, tmp: Path, scratch: HeldDir) -> bool:
    """The open file is the one at the scratch name AND sits in the pinned
    run folder."""
    st = os.fstat(fd)
    if _identity_of_name(tmp, scratch) != (st.st_dev, st.st_ino):
        return False
    if os.name == "nt":
        return _win_parent_identity(fd) == scratch.identity
    return True        # created dir_fd-relative to the pinned folder


def _unlink_scratch(tmp: Path, scratch: HeldDir) -> None:
    try:
        if os.name == "nt":
            os.unlink(tmp)
        elif scratch.fd is not None:
            os.unlink(tmp.name, dir_fd=scratch.fd)
    except OSError:
        pass


def _link_into_place(tmp: Path, path: Path, scratch: HeldDir) -> None:
    if os.name == "nt":
        os.link(tmp, path)
    else:
        os.link(tmp.name, str(path), src_dir_fd=scratch.fd)


def _held_file(fd: int, tmp: Path) -> HeldDir:
    """A non-owning view of an open scratch file for `verify` (never closed
    through this object; the creator closes the fd)."""
    if os.name == "nt":
        import msvcrt
        return HeldDir(tmp, tmp.name, handle=msvcrt.get_osfhandle(fd))
    return HeldDir(tmp, tmp.name, fd=fd)


def create_secret_file(path: Path, value: str, *, scratch: HeldDir,
                       verify: Optional[Callable[[HeldDir], bool]] = None) -> str:
    """Create `path` holding `value` + LF when it does not exist, staging in
    the pinned, verified-private `scratch` run folder.

    The order is the security property (module docstring "Writes" 3-4).
    Returns "created"; "exists" (the name already existed or another writer
    won - its file is kept); "moved" (the scratch file or the published
    name is not the file this run wrote - nothing kept); "acl_failed" (the
    open scratch file did not read back private - nothing written);
    "no_links" (this volume cannot hard-link into place - nothing
    published)."""
    path = Path(path)
    if not valid_token(value):
        raise ValueError("refusing to write a token that is not printable ASCII")
    if path.exists():
        return "exists"
    if os.name != "nt" and scratch.fd is None:
        # POSIX safety rests on dir_fd-relative calls; with no held fd they
        # would resolve against the CWD instead. Refuse.
        return "moved"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (value + "\n").encode("ascii")
    tmp = scratch.path / _scratch_name(path)
    try:
        fd = _open_new(tmp, scratch)               # private from birth
        try:
            if not _inside_held(fd, tmp, scratch):
                return "moved"                     # nothing written
            if os.name != "nt":
                os.fchmod(fd, 0o600)               # through the fd, never the name
            if not (verify or verify_held)(_held_file(fd, tmp)):
                return "acl_failed"                # read back THROUGH the open handle
            _write_secret(fd, data)
            st = os.fstat(fd)
            written = (st.st_dev, st.st_ino)
        finally:
            os.close(fd)
        try:
            _link_into_place(tmp, path, scratch)
        except FileExistsError:
            return "exists"
        except OSError as exc:
            if _links_unsupported(exc):
                return "no_links"                  # fail closed, never created in place
            raise
        try:
            published = os.stat(path, follow_symlinks=False)
        except OSError:
            published = None
        if published is None or (published.st_dev, published.st_ino) != written:
            try:
                os.unlink(path)                    # the name we just linked is not ours
            except OSError:
                pass
            return "moved"
        return "created"
    finally:
        _unlink_scratch(tmp, scratch)


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
        state = create_secret_file(path, secrets.token_hex(nbytes), scratch=folder,
                                   verify=scratch.verify)
    except OSError as exc:
        return SecretResult(name, path, "error", detail=f"write failed: {type(exc).__name__}")
    if state == "created":
        return SecretResult(name, path, "created", acl=True)
    if state == "acl_failed":
        return SecretResult(name, path, "error", acl=False, detail=ACL_FAILED)
    if state == "moved":
        return SecretResult(name, path, "error", detail=MOVED)
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
              verify: Optional[Callable[[HeldDir], bool]] = None) -> ProvisionReport:
    """Create every missing per-install secret under `root`; idempotent.

    `environ` is the services' environment (default os.environ). The report's
    `env` holds RC_DASH_TOKEN only when `dash_token_gate` is true AND the
    stored dash token is valid; otherwise it is empty and the services'
    environment is left exactly as the profile made it. `restrict` /
    `verify` default to restrict_to_current_user / verify_held."""
    root = Path(root)
    environ = os.environ if environ is None else environ
    scratch = ScratchFolder(root.joinpath(*SCRATCH_REL),
                            restrict or restrict_to_current_user,
                            verify or verify_held)
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
