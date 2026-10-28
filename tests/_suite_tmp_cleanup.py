"""RM-828 (d): remove a suite's import-time temp dir when its process is done.

`tests/conftest.py` (`rc-suite-logs-*`) and the agent3 suite conftest
(`rc-agent3-agent-logs-*`) `mkdtemp` at IMPORT, before any fixture exists, so
`tmp_path_factory` retention never sees them; nothing removed them, and
%TEMP% held 1271 `rc-suite-logs-*` dirs on 2026-10-27.

`remove_dir(path)` is called from each conftest's `pytest_unconfigure` (an
xdist worker runs it too: its `pytest_cmdline_main` ends in
`_ensure_unconfigure`), and `remove_dir_at_exit(path)` registers the same call
with `atexit` as the backstop for a process that imports the conftest without
running a pytest session. It is idempotent, so running both is safe.

Windows refuses to delete an open file, and the redirected import-time log
handlers stay open until `logging.shutdown`, whose own atexit hook runs AFTER
ours (atexit is LIFO and `logging` registers at its import). So every handler
writing inside the dir is closed and detached first - detached as well,
because a closed `FileHandler` in append mode reopens on its next emit - and
"every" includes a live handler that no logger holds (RM-1027).
Errors are ignored: a child process can still hold a file, and a leftover
temp dir is not worth failing a finished session for.
"""
from __future__ import annotations

import atexit
import logging
import shutil
from pathlib import Path


def _is_under(filename, root: Path) -> bool:
    try:
        return Path(filename).resolve().is_relative_to(root)
    except (OSError, TypeError, ValueError):
        return False


def _live_handlers(loggers) -> list:
    """Every handler on a logger, plus every live handler NO logger holds.

    RM-1027: an import-time `logging.basicConfig(handlers=[...])` is a no-op
    when root already has a handler (pytest's capture handler, during a test),
    so the FileHandler built for it is never attached. scripts/data_pipeline.py
    and tools/lcu_agent.py keep theirs in a module global, so it stays open on
    its redirected log here. `logging._handlerList` is the weakref registry
    `logging.shutdown` itself closes from; it is private, hence the getattr.
    """
    found = {}
    for lg in loggers:
        for handler in list(lg.handlers):
            found.setdefault(id(handler), handler)
    for ref in list(getattr(logging, "_handlerList", ())):
        handler = ref() if callable(ref) else None
        if handler is not None:
            found.setdefault(id(handler), handler)
    return list(found.values())


def _close_handlers_under(root: Path) -> None:
    loggers = [logging.getLogger()]
    loggers += [lg for lg in list(logging.Logger.manager.loggerDict.values())
                if isinstance(lg, logging.Logger)]
    for handler in _live_handlers(loggers):
        if _is_under(getattr(handler, "baseFilename", None), root):
            for lg in loggers:
                lg.removeHandler(handler)
            try:
                handler.close()
            except Exception:  # noqa: BLE001 - best effort at teardown
                pass


def remove_dir(path) -> None:
    root = Path(path)
    try:
        root = root.resolve()
    except OSError:
        return
    if not root.is_dir():
        return
    _close_handlers_under(root)
    shutil.rmtree(root, ignore_errors=True)


def remove_dir_at_exit(path) -> None:
    atexit.register(remove_dir, Path(path))
