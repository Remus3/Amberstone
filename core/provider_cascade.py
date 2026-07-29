# arch: multi-source provider cascade with provenance stamping | section=core | frozen=no
"""Ordered multi-source resolution with provenance stamping.

RC already has this shape by hand in several places: try a live source, fall
back to a static seed, expose a kill switch. The duo-synergy lane is exactly
that (live rows first, a dated static seed behind it). Every ad-hoc copy
re-decides the same four questions:

  - which source is tried first, and in what order do the rest follow
  - what counts as a failure worth cascading past
  - does an EMPTY answer count as an answer
  - how does the consumer learn which source actually served it

They do not all answer those the same way, which is how a panel ends up
showing seed data that looks live. This module answers them once.

The provenance stamp is the load-bearing part. RC's standing rule is that a
displayed metric carries where it came from, so the serving provider id is
attached to every result instead of being inferred.

Re-implemented (not vendored) from a reviewed MIT plugin's provider registry,
including its one genuinely good idea: within a provider, REQUIRED sub-sources
raise so the cascade moves on, while OPTIONAL sub-sources degrade to a default
so one nice-to-have outage does not discard an otherwise good answer. See
``optional`` at the bottom.

Deliberately NOT included: any aggregator scraping. This is the resolution
primitive only. What gets registered as a provider is a separate decision with
its own policy weight.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Provider:
    """One named source. ``call`` takes keyword args and returns a value."""

    id: str
    label: str
    call: Callable[..., Any]


@dataclass
class CascadeResult:
    """A resolved value plus how it was obtained."""

    value: Any
    source: str
    fell_back: bool = False
    attempted: list[tuple[str, str]] = field(default_factory=list)


class AllProvidersFailed(RuntimeError):
    """Every provider failed. Carries the first error as ``__cause__``."""

    def __init__(self, attempted: list[tuple[str, str]]):
        self.attempted = attempted
        tried = ", ".join(pid for pid, _ in attempted) or "none"
        super().__init__(f"all providers failed (tried: {tried})")


def _is_empty(value: Any) -> bool:
    """Absent, not merely falsey. 0 and False are legitimate values."""
    if value is None:
        return True
    if isinstance(value, (str, bytes, list, tuple, dict, set, frozenset)):
        return len(value) == 0
    return False


class ProviderCascade:
    """Resolve through providers in order, stamping the winner."""

    def __init__(
        self,
        providers: Sequence[Provider],
        order: Sequence[str] | None = None,
        accept_empty: bool = False,
    ) -> None:
        self._providers = {p.id: p for p in providers}
        self._order = list(order) if order else [p.id for p in providers]
        self._accept_empty = accept_empty

    def _resolution_order(self, selected: str | None) -> list[str]:
        """Selected first, then the declared order with it removed."""
        rest = [pid for pid in self._order if pid != selected]
        if selected and selected in self._providers:
            return [selected, *rest]
        return rest

    def resolve(self, selected: str | None = None, **kwargs: Any) -> CascadeResult:
        """First provider to answer wins. Raises AllProvidersFailed if none do."""
        attempted: list[tuple[str, str]] = []
        first_error: BaseException | None = None

        for index, provider_id in enumerate(self._resolution_order(selected)):
            provider = self._providers.get(provider_id)
            if provider is None:
                continue
            try:
                value = provider.call(**kwargs)
            except Exception as exc:  # noqa: BLE001 - any fault cascades
                attempted.append((provider_id, f"{type(exc).__name__}: {exc}"))
                if first_error is None:
                    first_error = exc
                _log.info("provider %s failed: %s", provider_id, exc)
                continue

            if not self._accept_empty and _is_empty(value):
                attempted.append((provider_id, "empty result"))
                continue

            if index > 0:
                _log.info("provider fallback: served by %s", provider_id)
            # Stamp in place, but never overwrite a source the provider set
            # itself - an inner cascade's attribution is more specific.
            if isinstance(value, dict):
                value.setdefault("source", provider_id)
            return CascadeResult(
                value=value,
                source=provider_id,
                fell_back=index > 0,
                attempted=attempted,
            )

        error = AllProvidersFailed(attempted)
        if first_error is not None:
            raise error from first_error
        raise error

    def resolve_or_none(self, selected: str | None = None, **kwargs: Any):
        """``resolve`` for callers that would rather have None than an except."""
        try:
            return self.resolve(selected=selected, **kwargs)
        except AllProvidersFailed:
            return None


def optional(call: Callable[[], Any], default: Any = None) -> Any:
    """Run a nice-to-have sub-source, degrading to ``default`` on any fault.

    Use inside a provider for data that improves an answer but must not
    discard it. Required sub-sources should be called directly so their
    failure propagates and the cascade moves to the next provider.
    """
    try:
        return call()
    except Exception:  # noqa: BLE001 - optional by contract
        _log.debug("optional sub-source failed; using default")
        return default
