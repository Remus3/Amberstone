"""
core/data_store.py — Thread-safe shared data bus for Riot Commander.

All modules read/write game state through this singleton instead of
passing dicts around or reading JSON files directly.

Usage:
    from core.data_store import store
    store.set("game_state", {...})
    state = store.get("game_state")
    store.subscribe("game_state", my_callback)   # called on change
"""

import threading
import logging
from typing import Any, Callable, Optional

_log = logging.getLogger("rc.data_store")


class DataStore:
    """Thread-safe key-value store with change-notification callbacks."""

    def __init__(self):
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {}
        self._subscribers: dict[str, list[Callable]] = {}

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any, notify: bool = True):
        with self._lock:
            old = self._data.get(key)
            self._data[key] = value
        if notify and value != old:
            self._notify(key, value)

    def update(self, mapping: dict, notify: bool = True):
        """Batch-set multiple keys."""
        changed = []
        with self._lock:
            for k, v in mapping.items():
                old = self._data.get(k)
                self._data[k] = v
                if v != old:
                    changed.append((k, v))
        if notify:
            for k, v in changed:
                self._notify(k, v)

    def subscribe(self, key: str, callback: Callable):
        """Register a callback(value) to fire when key changes."""
        with self._lock:
            self._subscribers.setdefault(key, []).append(callback)

    def snapshot(self) -> dict:
        """Return a shallow copy of all data."""
        with self._lock:
            return dict(self._data)

    def _notify(self, key: str, value: Any):
        with self._lock:
            cbs = list(self._subscribers.get(key, []))
        for cb in cbs:
            try:
                cb(value)
            except Exception as exc:
                _log.warning("DataStore callback error for '%s': %s", key, exc)


# Module-level singleton — import this
store = DataStore()
