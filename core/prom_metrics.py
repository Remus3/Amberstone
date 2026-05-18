# arch: zero-dep Counter/Gauge/Histogram | section=core | frozen=no
"""
core/prom_metrics.py - hand-rolled Prometheus exposition (T3 #12).

Zero-dep instrumentation pass. Exposes a `/metrics` endpoint emitting
Prometheus text format 0.0.4 so anything Prom-compatible can scrape RC's
runtime stats. Adding the actual scraper + Grafana stack is a separate
task; this module only produces the exposition body.

Three primitives:

    Counter   - monotonic. `.inc(amount=1.0, **labels)`.
    Gauge     - arbitrary value. `.set(value, **labels)`.
    Histogram - observation distribution. `.observe(value, **labels)`.
                Bucket counts are stored cumulatively, so render is just
                a per-bucket emit (no re-summation).

Each metric registers itself on construction; `render_all()` walks the
registry to produce the full text body. Concurrency is serialized by a
single module-level lock - the hot path is one dict lookup + one
arithmetic op per emit.

Labels are passed as kwargs to `inc/set/observe`. Label names are fixed
at construction; missing labels at emit raise ValueError so a typo
fails fast in dev rather than silently dropping samples.
"""
from __future__ import annotations

import threading
from typing import Iterable, List, Tuple

_REGISTRY: List["_Metric"] = []
_LOCK = threading.Lock()


def _escape_label(value: str) -> str:
    """Per spec: escape backslash, double-quote, and newline."""
    return (str(value)
            .replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n"))


def _format_labels(labelnames: Tuple[str, ...],
                   labelvalues: Tuple[str, ...]) -> str:
    if not labelnames:
        return ""
    parts = [f'{n}="{_escape_label(v)}"'
             for n, v in zip(labelnames, labelvalues)]
    return "{" + ",".join(parts) + "}"


def _format_value(v: float) -> str:
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return repr(v)


def _format_bucket_le(le: float) -> str:
    if le == float("inf"):
        return "+Inf"
    return repr(le)


class _Metric:
    _kind = "untyped"

    def __init__(self, name: str, help_text: str,
                 labelnames: Iterable[str] = ()) -> None:
        self.name = name
        self.help_text = help_text
        self.labelnames = tuple(labelnames)
        with _LOCK:
            _REGISTRY.append(self)

    def _labelvalues(self, labels: dict) -> Tuple[str, ...]:
        if not self.labelnames:
            if labels:
                raise ValueError(f"{self.name} has no labels but got {labels!r}")
            return ()
        try:
            return tuple(str(labels[n]) for n in self.labelnames)
        except KeyError as exc:
            raise ValueError(
                f"{self.name} missing label {exc.args[0]!r}; "
                f"expected {self.labelnames!r}"
            ) from None

    def render(self) -> List[str]:
        raise NotImplementedError


class Counter(_Metric):
    _kind = "counter"

    def __init__(self, name: str, help_text: str,
                 labelnames: Iterable[str] = ()) -> None:
        super().__init__(name, help_text, labelnames)
        self._values: dict = {}

    def inc(self, amount: float = 1.0, **labels) -> None:
        if amount < 0:
            return
        lv = self._labelvalues(labels)
        with _LOCK:
            self._values[lv] = self._values.get(lv, 0.0) + amount

    def render(self) -> List[str]:
        out = [f"# HELP {self.name} {self.help_text}",
               f"# TYPE {self.name} counter"]
        with _LOCK:
            items = sorted(self._values.items())
        if not items and not self.labelnames:
            out.append(f"{self.name} 0")
            return out
        for lv, v in items:
            out.append(f"{self.name}{_format_labels(self.labelnames, lv)} "
                       f"{_format_value(v)}")
        return out


class Gauge(_Metric):
    _kind = "gauge"

    def __init__(self, name: str, help_text: str,
                 labelnames: Iterable[str] = ()) -> None:
        super().__init__(name, help_text, labelnames)
        self._values: dict = {}

    def set(self, value: float, **labels) -> None:
        lv = self._labelvalues(labels)
        with _LOCK:
            self._values[lv] = float(value)

    def render(self) -> List[str]:
        out = [f"# HELP {self.name} {self.help_text}",
               f"# TYPE {self.name} gauge"]
        with _LOCK:
            items = sorted(self._values.items())
        for lv, v in items:
            out.append(f"{self.name}{_format_labels(self.labelnames, lv)} "
                       f"{_format_value(v)}")
        return out


# Default histogram buckets calibrated for Anthropic API call latency
# (seconds). Sub-100ms is local cache, sub-1s is fast-path Haiku, multi-
# second is Sonnet/vision, 30s+ is degraded.
DEFAULT_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0)


class Histogram(_Metric):
    _kind = "histogram"

    def __init__(self, name: str, help_text: str,
                 buckets: Iterable[float] = DEFAULT_BUCKETS,
                 labelnames: Iterable[str] = ()) -> None:
        super().__init__(name, help_text, labelnames)
        self.buckets = tuple(sorted(set(float(b) for b in buckets)))
        # labelvalues -> [bucket_counts (cumulative), sum, count]
        self._values: dict = {}

    def observe(self, value: float, **labels) -> None:
        lv = self._labelvalues(labels)
        v = float(value)
        with _LOCK:
            entry = self._values.get(lv)
            if entry is None:
                entry = [[0] * len(self.buckets), 0.0, 0]
                self._values[lv] = entry
            counts = entry[0]
            for i, le in enumerate(self.buckets):
                if v <= le:
                    counts[i] += 1
            entry[1] += v
            entry[2] += 1

    def render(self) -> List[str]:
        out = [f"# HELP {self.name} {self.help_text}",
               f"# TYPE {self.name} histogram"]
        with _LOCK:
            items = sorted((lv, (list(c), s, n))
                           for lv, (c, s, n) in self._values.items())
        for lv, (counts, total, n) in items:
            base = list(zip(self.labelnames, lv))
            for i, le in enumerate(self.buckets):
                bl = base + [("le", _format_bucket_le(le))]
                lstr = "{" + ",".join(
                    f'{k}="{_escape_label(v)}"' for k, v in bl) + "}"
                out.append(f"{self.name}_bucket{lstr} {counts[i]}")
            bl = base + [("le", "+Inf")]
            lstr = "{" + ",".join(
                f'{k}="{_escape_label(v)}"' for k, v in bl) + "}"
            out.append(f"{self.name}_bucket{lstr} {n}")
            blstr = _format_labels(self.labelnames, lv)
            out.append(f"{self.name}_sum{blstr} {repr(total)}")
            out.append(f"{self.name}_count{blstr} {n}")
        return out


def render_all() -> str:
    """Return the full text-format exposition of every registered metric."""
    with _LOCK:
        metrics = list(_REGISTRY)
    lines: List[str] = []
    for m in metrics:
        lines.extend(m.render())
    lines.append("")
    return "\n".join(lines)

# Phase 6: cross-cutting bridge metrics. Co-located in this module so any
# bridge-touching code (`tools/bridge_cli.py`, `core/bridge.py`,
# `core/bridge_monitor.py`, future watcher refactors) can record without
# each module re-declaring its own counters.
#
# Per-process counters reset across CLI invocations - these accumulate
# usefully only inside long-running processes (the dashboard, the watcher
# daemon, anything that imports `core.bridge.send`). For one-shot
# `py tools/bridge_cli.py task ...` invocations the counts are emitted
# but die with the process. That's by design - no shared state file to
# coordinate across processes, no metrics daemon.
class BridgeMetrics:
    """Namespace of bridge-related Prometheus metrics."""

    posts_total = Counter(
        "rc_bridge_posts_total",
        "Successful POSTs to a bridge endpoint, by envelope kind and target.",
        labelnames=("kind", "target"),
    )
    fetches_total = Counter(
        "rc_bridge_fetches_total",
        "GET fetches against the bridge, by outcome "
        "(success / error / empty / self_only).",
        labelnames=("status",),
    )
    pulls_total = Counter(
        "rc_bridge_pulls_total",
        "Pull-tasks polls, by target and outcome (found / empty).",
        labelnames=("target", "status"),
    )
    pull_pending = Gauge(
        "rc_bridge_pull_pending",
        "Pending un-answered tasks for this machine on the last poll.",
        labelnames=("target",),
    )

