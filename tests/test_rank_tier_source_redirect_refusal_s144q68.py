"""RM-1441 (census miss, second site) - the live rank-tier aggregate fetch
refuses a request to, or a redirect INTO, the League wiki host (ruling 51,
``RM962-S146-R51``; RM-1254 closed the same shape on the three wiki tools and
``lib/http/client.py``, RM-1440 on ``tools/upstream_drift_check.py``, the
first RM-1441 site on ``core/synergy_external_source.py``).

``core/rank_tier_source.py`` ``_http_get_json`` fetched the operator-configured
aggregate endpoint with ``urllib.request.urlopen``, whose default opener
follows a 3xx, so an endpoint answering 302 to the wiki host (or an endpoint
that simply IS a wiki url) opened a wiki socket with no consent record. The
host is built at runtime from ``config/rank_tier_source.json``, which is why
cycle 113's literal-host census did not see this site.

The origin is a real local HTTP server on 127.0.0.1, so urllib's own redirect
machinery runs. ``socket.create_connection`` is patched (this thread only) to
RECORD and refuse any connect to a wiki host and pass every other connect
through, so a refusal is proven by ZERO recorded wiki connects, not by an
exception alone. With a consent record the same redirect IS followed (one
recorded wiki connect), so the refusal is conditional, and a redirect to a
non-wiki target still resolves. ``fetch_rows`` stays fail-soft (None) and
negative-caches the refusal. The module's no-credential-in-a-message contract
(defect F of tests/test_rank_tier_live_budget.py) holds for the refusal too:
no api key in the message, and no __cause__ / __context__ behind it.
"""
from __future__ import annotations

import datetime as _dt
import http.server
import json
import socket
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import rank_tier_source as RTS  # noqa: E402
from lib import wiki_consent  # noqa: E402
from tests._module_view import this_thread_only  # noqa: E402

# The genuine seam, captured at import, in case another file in the same
# worker replaced RTS._http_get_json; each test installs it explicitly.
_REAL_HTTP_GET_JSON = RTS._http_get_json

_DUMMY_KEY = "dummy-not-a-real-key"
WIKI_TARGETS = {
    "vanity": "http://wiki.leagueoflegends.com/en-us/Module:ChampionData/data?action=raw",
    "wikigg": "https://leagueoflegends.wiki.gg/api.php?action=query",
    "fandom": "http://leagueoflegends.fandom.com/wiki/Ahri",
}
_ROW = {"role": "all", "bracket": "early", "metric": "cs", "avg": 150.0}
OK_BODY = json.dumps({"data": [_ROW]}).encode("ascii")


class _NetworkTouched(OSError):
    """Raised by the patched connect after it records a wiki connect."""


def _make_handler(hits: list[str]):
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib handler name
            path = urlsplit(self.path).path
            hits.append(path)
            if path.startswith("/to-wiki/"):
                self._redirect(WIKI_TARGETS[path.rsplit("/", 1)[1]])
            elif path.startswith("/hop/"):
                self._redirect("/to-wiki/" + path.rsplit("/", 1)[1])
            elif path == "/to-local":
                self._redirect("/ok")
            elif path == "/ok":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(OK_BODY)))
                self.end_headers()
                self.wfile.write(OK_BODY)
            else:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

        def _redirect(self, location: str) -> None:
            self.send_response(302)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):  # silence the stdlib access log
            pass

    return _Handler


@pytest.fixture
def origin():
    """(base url, request-path log) of a local origin; stopped and joined at teardown."""
    hits: list[str] = []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(hits))
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05},
                         name="s144q68-rank-tier-origin", daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}", hits
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=10)


@pytest.fixture
def net(monkeypatch, tmp_path):
    """Record-and-refuse wiki connects; the real seam; empty caches; consent path in an empty dir."""
    calls: list[str] = []
    real = socket.create_connection

    def _connect(address, *a, **k):
        host = str(address[0])
        if wiki_consent.is_wiki_url(f"http://{host}/"):
            calls.append(f"connect {host}:{address[1]}")
            raise _NetworkTouched(f"wiki connect: {host}")
        return real(address, *a, **k)

    monkeypatch.setattr(socket, "create_connection", this_thread_only(_connect, real))
    for name in ("http_proxy", "https_proxy", "all_proxy",
                 "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("no_proxy", "*")
    monkeypatch.setattr(RTS, "_http_get_json", _REAL_HTTP_GET_JSON)
    consent_dir = tmp_path / "consent"
    consent_dir.mkdir()
    monkeypatch.setattr(wiki_consent, "CONSENT_PATH", consent_dir / "wiki_fetch_consent.json")
    RTS._reset_cache_for_tests()
    yield calls
    RTS._reset_cache_for_tests()


def _grant() -> None:
    rec = {"ruling": wiki_consent.RULING_ID, "granted": _dt.date.today().isoformat(),
           "scope": "identified low-rate reads of Module:ChampionData (test)"}
    wiki_consent.CONSENT_PATH.write_text(json.dumps(rec), encoding="utf-8", newline="\n")


def _write_config(tmp_path, monkeypatch, endpoint: str) -> None:
    p = tmp_path / "rank_tier_source.json"
    p.write_text(json.dumps({"endpoint": endpoint, "tier_param": "tier", "enabled": True}),
                 encoding="utf-8", newline="\n")
    monkeypatch.setattr(RTS, "_CONFIG_PATH", p)


def _refused(exc) -> bool:
    cls = getattr(RTS, "RankTierSourceRefused", None)
    return cls is not None and isinstance(exc, cls)


@pytest.mark.parametrize("target", sorted(WIKI_TARGETS))
def test_redirect_into_the_wiki_is_refused_before_any_wiki_socket(net, origin, target):
    base, _hits = origin
    with pytest.raises(RTS.RankTierSourceError) as ei:
        RTS._http_get_json(f"{base}/to-wiki/{target}", timeout_s=10)
    assert net == []
    assert _refused(ei.value)


def test_a_two_hop_redirect_into_the_wiki_is_refused(net, origin):
    base, hits = origin
    with pytest.raises(RTS.RankTierSourceError) as ei:
        RTS._http_get_json(f"{base}/hop/vanity", timeout_s=10)
    assert net == []
    assert _refused(ei.value)
    assert hits == ["/hop/vanity", "/to-wiki/vanity"]


def test_a_direct_wiki_endpoint_is_refused_before_any_socket(net, origin):
    _base, hits = origin
    with pytest.raises(RTS.RankTierSourceError) as ei:
        RTS._http_get_json(WIKI_TARGETS["vanity"], timeout_s=10)
    assert net == [] and hits == []
    assert _refused(ei.value)


def test_the_refusal_message_carries_no_credential_and_no_chain(net, origin):
    """Defect F of tests/test_rank_tier_live_budget.py, for the new raise: the
    credentialed fetch url never reaches the message, the message still names
    the endpoint, and nothing hangs off __cause__ / __context__."""
    base, _hits = origin
    url = RTS._build_url(f"{base}/to-wiki/vanity?api_key={_DUMMY_KEY}", "tier", "iron", "SR")
    with pytest.raises(RTS.RankTierSourceError) as ei:
        RTS._http_get_json(url, timeout_s=10)
    assert net == []
    assert _refused(ei.value)
    text = str(ei.value)
    assert _DUMMY_KEY not in text and "api_key" not in text and url not in text, text
    assert "127.0.0.1" in text, f"redacted past usefulness: {text!r}"
    assert ei.value.__cause__ is None and ei.value.__context__ is None


def test_with_consent_the_redirect_is_followed(net, origin):
    base, _hits = origin
    _grant()
    with pytest.raises(RTS.RankTierSourceError) as ei:
        RTS._http_get_json(f"{base}/to-wiki/vanity", timeout_s=10)
    # The consented redirect reaches the wiki host once; the patched connect
    # refuses it, so it fails as an ordinary transport error, not a refusal.
    assert net and all(c.startswith("connect wiki.leagueoflegends.com:") for c in net)
    assert len(net) == 1
    assert not _refused(ei.value)


def test_a_redirect_to_a_non_wiki_target_still_resolves(net, origin):
    base, _hits = origin
    assert RTS._http_get_json(f"{base}/to-local", timeout_s=10)["data"] == [_ROW]
    assert net == []


def test_fetch_rows_stays_fail_soft_and_negative_caches_a_refusal(
        net, origin, tmp_path, monkeypatch):
    """None, zero wiki sockets, ONE origin request, and the refusal is
    negative-cached like any other failure."""
    base, hits = origin
    _write_config(tmp_path, monkeypatch, f"{base}/to-wiki/vanity")
    assert RTS.fetch_rows("iron", "SR") is None
    assert net == []
    assert hits == ["/to-wiki/vanity"]
    assert RTS.fetch_rows("iron", "SR") is None
    assert hits == ["/to-wiki/vanity"], "the refusal was not negative-cached"


def test_fetch_rows_stays_fail_soft_on_a_direct_wiki_endpoint(
        net, origin, tmp_path, monkeypatch):
    _base, hits = origin
    _write_config(tmp_path, monkeypatch, WIKI_TARGETS["wikigg"])
    assert RTS.fetch_rows("gold", "ARAM") is None
    assert net == [] and hits == []


def test_fetch_rows_still_reads_a_non_wiki_redirect(net, origin, tmp_path, monkeypatch):
    base, _hits = origin
    _write_config(tmp_path, monkeypatch, f"{base}/to-local")
    assert RTS.fetch_rows("iron", "SR") == [_ROW]
    assert net == []
