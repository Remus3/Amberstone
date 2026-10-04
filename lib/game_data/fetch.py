"""Fetch step of the game-data pipeline (P1-4): raw bodies, cached on disk.

``fetch(patch, client=..., cache_dir=...)`` resolves the patch against the
official version feed, then pulls every source's bodies for that patch through
ONE in-process client. Bodies are cached under
``cache_dir/<patch>/<source>/<sha256(url)[:16]>.body`` so a re-run skips work
already done; only the version feed is re-read, because it decides which patch
is current.

Era rule: a source that cannot serve an old patch's tables (not
era-addressable) is EXCLUDED when the requested patch is not the newest one,
and the exclusion is recorded - an old-ruleset query never mixes in today's
numbers.

A required source that cannot be fetched or parsed fails the whole fetch with
``MissingSourceError``; nothing is built from a partial set.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from lib.game_data.sources import DDRAGON_VERSIONS_URL, SOURCES, Source, SourceParseError, parse_versions
from lib.http.client import HttpClient

USER_AGENT_NOTE = "Amberstone game-data pipeline (one request per source per patch)"


class MissingSourceError(RuntimeError):
    """A required source could not be fetched or parsed."""


@dataclass
class Fetched:
    version: str
    latest: str
    parsed: dict[str, dict] = field(default_factory=dict)
    excluded: dict[str, str] = field(default_factory=dict)
    cache_hits: int = 0
    fetched: int = 0


def live_client() -> HttpClient:
    """The pipeline's network client: the shared HttpClient (blocklist, per-host
    rate gate of 1 request/second, circuit breaker) with environment proxies
    ignored, so no local proxy can rewrite an upstream response."""
    return HttpClient(trust_env_proxy=False)


def _cache_path(cache_dir: Path, version: str, source_id: str, url: str) -> Path:
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return cache_dir / version / source_id / f"{key}.body"


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _get(client: Any, url: str) -> bytes:
    resp = client.get(url)
    status = getattr(resp, "status", 200)
    if status != 200:
        raise MissingSourceError(f"HTTP {status} for {url}")
    return resp.body


def fetch(
    patch: Optional[str],
    *,
    client: Any = None,
    cache_dir: Path,
    sources: Iterable[Source] = SOURCES,
) -> Fetched:
    client = client if client is not None else live_client()
    cache_dir = Path(cache_dir)
    try:
        versions = parse_versions(_get(client, DDRAGON_VERSIONS_URL))
    except Exception as exc:  # noqa: BLE001 - every failure here is "no version feed"
        raise MissingSourceError(f"version feed: {exc}") from exc
    latest = versions[0]
    version = patch or latest
    if version not in versions:
        raise MissingSourceError(f"version feed: unknown patch {version!r}")
    out = Fetched(version=version, latest=latest)
    for src in sources:
        if version != latest and not src.era_addressable:
            out.excluded[src.id] = f"not era-addressable; requested {version}, source serves only {latest}"
            continue
        bodies: dict[str, bytes] = {}
        fresh: dict[Path, bytes] = {}
        for name, url in src.urls(version).items():
            path = _cache_path(cache_dir, version, src.id, url)
            if path.is_file():
                bodies[name] = path.read_bytes()
                out.cache_hits += 1
                continue
            try:
                body = _get(client, url)
            except MissingSourceError as exc:
                raise MissingSourceError(f"{src.id}: {exc}") from exc
            except Exception as exc:  # noqa: BLE001 - any transport failure fails the source
                raise MissingSourceError(f"{src.id}: fetch failed for {url}: {exc}") from exc
            out.fetched += 1
            bodies[name] = body
            fresh[path] = body
        try:
            out.parsed[src.id] = src.parse(bodies)
        except SourceParseError as exc:
            raise MissingSourceError(f"{src.id}: {exc}") from exc
        # Cache only what parsed: a bad body must be re-fetched, not replayed.
        for path, body in fresh.items():
            _atomic_write_bytes(path, body)
    return out
