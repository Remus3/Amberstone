"""One operator-notify path (Y-02, external reference K).

Every notifier returns ``(ok, detail)`` and NEVER raises. A jsonl file is the
floor. ``FirstThatWorks`` tries notifiers in order, stops at the first that
reports ok, and joins every attempt's detail so a failure is never silent.

RC_NOTIFY_HOLD=1 (tests/conftest.py sets it) makes every notifier that would
reach a person - the desktop toast today, a phone push later - send nothing
and return ``(False, "held: ...")``. The file floor is not held: it reaches
nobody, and RC_NOTIFY_JSONL redirects it (conftest points it at a tmp dir).

WHY THIS EXISTS. Three watchers carried copy-pasted ``_toast`` functions that
interpolated title/body straight into toast XML. A ``&`` or ``<`` made LoadXml
throw, a bare except swallowed it, and the toast silently never showed. Here
the XML is escaped, the PowerShell exit code is read back, and a failed toast
falls through to the jsonl floor.

EXTENDING. A new sink (a network push, a fleet sink) subclasses ``Notifier``,
implements ``_send`` and is inserted as a chain entry. Set ``holdable = True``
if it reaches a person or leaves the box: the base class then enforces the
HOLD before ``_send`` runs. Put any credential in an attribute whose name
contains token / secret / password / key: ``repr`` masks it.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

_ROOT = Path(__file__).resolve().parents[1]

HOLD_ENV = "RC_NOTIFY_HOLD"
JSONL_ENV = "RC_NOTIFY_JSONL"
DEFAULT_JSONL = _ROOT / "ops" / "runtime" / "operator_notify.jsonl"

# The AppUserModelID two of the three replaced watchers used (lcu_push_watcher,
# live_flip_watcher). claude_quota_watch used the Windows Terminal AppId and
# passes it explicitly, so no watcher's toast attribution changes here.
DEFAULT_APP_ID = (
    "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}"
    "\\WindowsPowerShell\\v1.0\\powershell.exe"
)
WINDOWS_TERMINAL_APP_ID = "Microsoft.WindowsTerminal_8wekyb3d8bbwe!App"

# Every spawn here runs under pythonw-hosted scheduled tasks: without this
# flag the powershell child gets a fresh console and flashes. Never
# DETACHED_PROCESS - powershell then exits at once, silently, rc=0.
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

PRIORITIES = ("min", "low", "default", "high", "urgent")

# Keeps the -EncodedCommand line well under the 32767-char Win32 limit.
_MAX_TITLE = 200
_MAX_BODY = 2000

# XML 1.0 forbids these even when escaped; LoadXml rejects them.
_XML_ILLEGAL = re.compile(
    "[" + "".join(f"\\x{c:02x}" for c in range(0x20) if c not in (9, 10, 13))
    + "\\ud800-\\udfff" + "\\uFFFE" + "\\uFFFF" + "]"
)
_SECRET_ATTR = re.compile(r"token|secret|password|passwd|key", re.IGNORECASE)


@dataclass(frozen=True)
class Notification:
    title: str
    body: str
    priority: str = "default"
    link: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)


def is_held(environ=None) -> bool:
    env = os.environ if environ is None else environ
    return str(env.get(HOLD_ENV, "")).strip().lower() in ("1", "true", "yes", "on")


def _clean(text: object, limit: int) -> str:
    s = _XML_ILLEGAL.sub("", str(text if text is not None else ""))
    return s if len(s) <= limit else s[: limit - 3] + "..."


def build_toast_xml(title: str, body: str, link: str | None = None) -> str:
    """ToastGeneric XML with title/body/link escaped (the measured defect)."""
    attrs = ""
    if link:
        attrs = f' activationType="protocol" launch={quoteattr(_clean(link, 1000))}'
    return (
        f"<toast{attrs}><visual><binding template=\"ToastGeneric\">"
        f"<text>{escape(_clean(title, _MAX_TITLE))}</text>"
        f"<text>{escape(_clean(body, _MAX_BODY))}</text>"
        f"</binding></visual></toast>"
    )


class Notifier:
    """Base: ``notify`` is the never-raising, HOLD-enforcing entry point."""

    name = "notifier"
    holdable = False  # True = reaches a person or leaves the box

    def notify(self, n: Notification) -> tuple[bool, str]:
        try:
            if self.holdable and is_held():
                return False, f"held: {HOLD_ENV}=1, {self.name} sent nothing"
            ok, detail = self._send(n)
            return bool(ok), str(detail)
        except BaseException as exc:  # noqa: BLE001 - contract: never raises
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            return False, f"{type(exc).__name__}: {exc}"

    def _send(self, n: Notification) -> tuple[bool, str]:
        raise NotImplementedError

    def __repr__(self) -> str:
        parts = []
        for k, v in sorted(vars(self).items()):
            shown = "***" if _SECRET_ATTR.search(k) and v else repr(v)
            parts.append(f"{k.lstrip('_')}={shown}")
        return f"{type(self).__name__}({', '.join(parts)})"


class WinToastNotifier(Notifier):
    """One WinRT toast through one hidden powershell.exe. Reads the exit code
    back, so a rejected payload is (False, detail), never a silent pass."""

    name = "toast"
    holdable = True

    def __init__(self, app_id: str = DEFAULT_APP_ID, timeout_s: float = 20.0):
        self.app_id = app_id
        self.timeout_s = timeout_s

    def script(self, n: Notification) -> str:
        xml = build_toast_xml(n.title, n.body, n.link)
        b64 = base64.b64encode(xml.encode("utf-8")).decode("ascii")
        app = self.app_id.replace("'", "''")
        return (
            "$ErrorActionPreference='Stop'\n"
            "try {\n"
            "[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]|Out-Null\n"
            "[Windows.UI.Notifications.ToastNotification,Windows.UI.Notifications,ContentType=WindowsRuntime]|Out-Null\n"
            "[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime]|Out-Null\n"
            f"$t=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{b64}'))\n"
            "$x=New-Object Windows.Data.Xml.Dom.XmlDocument\n"
            "$x.LoadXml($t)\n"
            "$n=New-Object Windows.UI.Notifications.ToastNotification $x\n"
            f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{app}').Show($n)\n"
            "'shown'\n"
            "} catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }\n"
        )

    def _send(self, n: Notification) -> tuple[bool, str]:
        if sys.platform != "win32":
            return False, "not windows"
        enc = base64.b64encode(self.script(n).encode("utf-16-le")).decode("ascii")
        try:
            r = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                 "-EncodedCommand", enc],
                capture_output=True, text=True, timeout=self.timeout_s,
                creationflags=CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"spawn failed: {type(exc).__name__}: {exc}"
        err = (r.stderr or "").strip().replace("\n", " ")[:300]
        if r.returncode == 0 and "shown" in (r.stdout or ""):
            return True, "shown"
        return False, f"rc={r.returncode} {err}".strip()


def _win32_append(path: Path, data: bytes) -> None:
    """Append via CreateFileW(FILE_APPEND_DATA) - every WriteFile lands at EOF,
    atomically per call, even with concurrent writers. Shares read/write/delete
    so a reader or a rotation never blocks us (and we never block them)."""
    import ctypes  # noqa: PLC0415 - Windows-only
    from ctypes import wintypes  # noqa: PLC0415

    FILE_APPEND_DATA = 0x0004
    SHARE_ALL = 0x1 | 0x2 | 0x4
    OPEN_ALWAYS = 4
    FILE_ATTRIBUTE_NORMAL = 0x80
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create = k32.CreateFileW
    create.restype = wintypes.HANDLE
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                       wintypes.HANDLE]
    write = k32.WriteFile
    write.restype = wintypes.BOOL
    write.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD,
                      ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    close = k32.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    h = create(str(path), FILE_APPEND_DATA, SHARE_ALL, None, OPEN_ALWAYS,
               FILE_ATTRIBUTE_NORMAL, None)
    if not h or h == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), f"CreateFileW failed: {path}")
    try:
        written = wintypes.DWORD(0)
        if not write(h, data, len(data), ctypes.byref(written), None):
            raise OSError(ctypes.get_last_error(), f"WriteFile failed: {path}")
        if written.value != len(data):
            raise OSError(f"short write {written.value}/{len(data)}: {path}")
    finally:
        close(h)


def _portable_append(path: Path, data: bytes) -> None:
    """CI / non-Windows fallback: one os.write on an append-mode fd."""
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND
                 | getattr(os, "O_BINARY", 0), 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


class JsonlNotifier(Notifier):
    """The floor: one JSON row per notification. Reaches nobody, so not held."""

    name = "jsonl"
    holdable = False

    def __init__(self, path: str | os.PathLike | None = None,
                 use_win32: bool | None = None):
        if path is None:
            env = os.environ.get(JSONL_ENV)
            path = env if env else DEFAULT_JSONL
        self.path = Path(path)
        self.use_win32 = (sys.platform == "win32") if use_win32 is None else use_win32

    def _send(self, n: Notification) -> tuple[bool, str]:
        row = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "title": n.title, "body": n.body, "priority": n.priority,
            "link": n.link, "tags": list(n.tags), "pid": os.getpid(),
        }
        data = (json.dumps(row, ensure_ascii=True) + "\n").encode("ascii")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            (_win32_append if self.use_win32 else _portable_append)(self.path, data)
        except OSError as exc:
            return False, f"write failed: {exc}"
        return True, f"appended {self.path.name}"


class FirstThatWorks(Notifier):
    """Try each notifier in order; stop at the first ok; join every detail."""

    name = "chain"
    holdable = False  # each member enforces its own HOLD

    def __init__(self, notifiers: Iterable[Notifier]):
        self.notifiers: list[Notifier] = list(notifiers)

    def _send(self, n: Notification) -> tuple[bool, str]:
        details: list[str] = []
        for member in self.notifiers:
            label = getattr(member, "name", type(member).__name__)
            try:
                ok, detail = member.notify(n)
            except BaseException as exc:  # noqa: BLE001 - a member broke its contract
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                ok, detail = False, f"{type(exc).__name__}: {exc}"
            details.append(f"{label}: {detail}")
            if ok:
                return True, "; ".join(details)
        return False, "; ".join(details) if details else "no notifiers configured"


def default_chain(app_id: str = DEFAULT_APP_ID) -> FirstThatWorks:
    """Desktop toast first, jsonl floor last. Later sinks insert before the floor."""
    return FirstThatWorks([WinToastNotifier(app_id=app_id), JsonlNotifier()])


def notify(title: str, body: str, priority: str = "default",
           link: str | None = None, tags: Sequence[str] = (), *,
           notifier: Notifier | None = None,
           app_id: str = DEFAULT_APP_ID) -> tuple[bool, str]:
    """The one operator-notify entry point. Never raises."""
    try:
        pr = priority if priority in PRIORITIES else "default"
        n = Notification(str(title), str(body), pr, link,
                         tuple(str(t) for t in (tags or ())))
        target = notifier if notifier is not None else default_chain(app_id)
        ok, detail = target.notify(n)
        return bool(ok), str(detail)
    except BaseException as exc:  # noqa: BLE001 - contract: never raises
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        return False, f"{type(exc).__name__}: {exc}"
