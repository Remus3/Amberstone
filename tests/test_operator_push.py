"""Y-45 / RM-568 (external reference K): the phone-push notifier.

core/operator_push.NtfyNotifier publishes to a self-hosted ntfy server over
the tailnet. Everything here runs against a FAKE server: a stdlib
http.server bound to 127.0.0.1 inside the test. No real server, topic or
token is ever contacted or created.

TWO DIFFERENT LOOPBACK FACTS, kept apart on purpose:
* the SERVER url may be loopback (the fake server here; in production the
  ntfy service also runs on Legion itself), and is never refused for it;
* a click / attach / action URL INSIDE the message is opened on the PHONE,
  where loopback means the phone itself - so those are refused, and must
  name a tailnet host.
"""
from __future__ import annotations

import ast
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from core import operator_notify as on
from core import operator_push as op

TOKEN = "tk_synthetic_test_token_0123456789"  # synthetic, never a real token
TOPIC = "rc-test-topic-synthetic"
SIBLING = "zqxwvsibling"  # synthetic needle, armed via RC_MOON_SYNC_REPOS
TAILNET_LINK = "https://rc-host.example-tailnet.ts.net/dashboard"


class _Fake:
    """A tiny ntfy-shaped server: records requests, answers as told."""

    def __init__(self):
        self.requests: list[dict] = []
        self.status = 200
        self.reply = b'{"id":"abc123","event":"message"}'
        self.poll_lines: list[dict] = []
        self.redirect_to: str | None = None
        fake = self

        class H(BaseHTTPRequestHandler):
            def _record(self, body: bytes):
                fake.requests.append({
                    "method": self.command, "path": self.path,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body": body,
                })

            def do_POST(self):  # noqa: N802
                n = int(self.headers.get("Content-Length") or 0)
                self._record(self.rfile.read(n))
                if fake.redirect_to:
                    self.send_response(302)
                    self.send_header("Location", fake.redirect_to)
                    self.end_headers()
                    return
                self.send_response(fake.status)
                self.send_header("Content-Type", "application/json")
                body = fake.reply
                if fake.status >= 400:
                    # A hostile/odd server echoing the credential back.
                    body = ("bad auth " + self.headers.get("Authorization", "")).encode()
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802
                self._record(b"")
                body = "".join(json.dumps(x) + "\n" for x in fake.poll_lines).encode()
                self.send_response(fake.status)
                self.send_header("Content-Type", "application/x-ndjson")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):  # keep test output clean
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def fake():
    f = _Fake()
    yield f
    f.close()


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    # Deterministic sweep: ARMED on one synthetic needle, in CI and locally.
    monkeypatch.setenv("RC_MOON_SYNC_REPOS", str(tmp_path / "fakeroot" / SIBLING))
    monkeypatch.delenv("RC_MOON_SYNC_NARROWED_NAMES", raising=False)
    monkeypatch.setenv("RC_TEST_PUSH_TOKEN", TOKEN)
    monkeypatch.setenv(op.CONFIG_ENV, str(tmp_path / "absent.json"))
    monkeypatch.setenv(on.JSONL_ENV, str(tmp_path / "floor.jsonl"))


def _unhold(monkeypatch):
    monkeypatch.delenv(on.HOLD_ENV, raising=False)


def _cfg(fake, **over):
    cfg = {
        "enabled": True,
        "server": fake.url,
        "topic": TOPIC,
        "token": {"env": "RC_TEST_PUSH_TOKEN"},
        "timeout_s": 3,
    }
    cfg.update(over)
    return cfg


def _push(fake, **over):
    return op.NtfyNotifier(_cfg(fake, **over))


def _n(title="Live flip ready", body="drain ready", link=None, **kw):
    return on.Notification(title, body, kw.get("priority", "default"), link,
                           tuple(kw.get("tags", ())))


# ---------------------------------------------------------------- publish


def test_publishes_json_body_shape(fake, monkeypatch):
    _unhold(monkeypatch)
    ok, detail = _push(fake).notify(
        _n(link=TAILNET_LINK, priority="high", tags=("lcu-push",)))
    assert ok, detail
    assert len(fake.requests) == 1
    req = fake.requests[0]
    assert req["method"] == "POST"
    assert req["path"] == "/"  # JSON publish goes to the server root
    assert req["headers"]["content-type"].startswith("application/json")
    assert req["headers"]["authorization"] == f"Bearer {TOKEN}"
    payload = json.loads(req["body"].decode("utf-8"))
    assert payload == {
        "topic": TOPIC, "title": "Live flip ready", "message": "drain ready",
        "priority": 4, "tags": ["lcu-push"], "click": TAILNET_LINK,
    }
    assert "abc123" in detail


def test_non_latin_title_is_in_the_json_body_not_a_header(fake, monkeypatch):
    _unhold(monkeypatch)
    title = "Flip \u5b8c\u6210 \u0414\u0430 \u2603"
    ok, detail = _push(fake).notify(_n(title=title, body="\u00e9t\u00e9 \u4e2d"))
    assert ok, detail
    req = fake.requests[0]
    assert json.loads(req["body"].decode("utf-8"))["title"] == title
    # Nothing message-derived travels as a (latin-1) header.
    for k, v in req["headers"].items():
        v.encode("latin-1")
        assert "Flip" not in v, k
    assert "title" not in req["headers"] and "x-title" not in req["headers"]


def test_priority_map_covers_every_rc_priority():
    assert [op.NTFY_PRIORITY[p] for p in on.PRIORITIES] == [1, 2, 3, 4, 5]


# ---------------------------------------------------------------- links


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8888/x", "https://127.9.9.9/", "http://localhost/",
    "http://LOCALHOST.:8888/", "http://app.localhost/", "http://[::1]:8888/",
    "http://[::ffff:127.0.0.1]/", "http://127.1/", "http://2130706433/",
    "http://0.0.0.0:8888/",
])
def test_loopback_links_are_refused(url):
    reason = op.link_refusal(url)
    assert reason and "loopback" in reason


@pytest.mark.parametrize("url", [
    "http://192.0.2.230:8888/", "http://100.64.0.1:8888/",
    "https://example.com/", "file:///C:/x", "javascript:alert(1)", "https:///nohost",
])
def test_non_tailnet_links_are_refused(url):
    assert op.link_refusal(url)


def test_tailnet_link_passes_and_suffix_can_be_narrowed():
    assert op.link_refusal(TAILNET_LINK) is None
    assert op.link_refusal(TAILNET_LINK, ".other.ts.net")
    assert op.link_refusal(TAILNET_LINK, "example-tailnet.ts.net") is None


def test_loopback_click_refuses_whole_message_and_sends_nothing(fake, monkeypatch):
    _unhold(monkeypatch)
    ok, detail = _push(fake).notify(_n(link="http://127.0.0.1:8888/"))
    assert not ok and "loopback" in detail
    assert fake.requests == []


def test_attach_and_action_urls_are_checked_too(fake):
    p = _push(fake)
    payload, why = p.build_payload(_n(), attach="http://localhost/a.png")
    assert payload is None and "attach" in why and "loopback" in why
    payload, why = p.build_payload(
        _n(), actions=[{"action": "view", "label": "Open", "url": "http://[::1]/"}])
    assert payload is None and "action" in why
    payload, why = p.build_payload(
        _n(), attach=TAILNET_LINK + "/a.png",
        actions=[{"action": "view", "label": "Open", "url": TAILNET_LINK}])
    assert why == "" and payload["attach"].endswith("a.png")
    assert payload["actions"][0]["url"] == TAILNET_LINK


def test_loopback_server_url_is_not_refused(fake, monkeypatch):
    """The distinction: the SERVER may be loopback; only message links may not."""
    _unhold(monkeypatch)
    assert fake.url.startswith("http://127.0.0.1:")
    ok, detail = _push(fake).notify(_n())
    assert ok, detail


# ---------------------------------------------------------------- secrets


def test_token_never_in_repr_detail_or_logs(fake, monkeypatch, caplog, capsys, tmp_path):
    _unhold(monkeypatch)
    caplog.set_level(logging.DEBUG)
    p = _push(fake)
    text = [repr(p), str(p)]
    text.append(p.notify(_n())[1])
    fake.status = 401  # server echoes the Authorization header in its body
    text.append(p.notify(_n())[1])
    chain = on.FirstThatWorks([p, on.JsonlNotifier(tmp_path / "f.jsonl", use_win32=False)])
    text.append(chain.notify(_n())[1])
    text.append(str(p.poll()))
    fake.close()  # connection refused path
    text.append(p.notify(_n())[1])
    out = capsys.readouterr()
    text += [out.out, out.err, caplog.text, (tmp_path / "f.jsonl").read_text()]
    blob = "\n".join(text)
    assert TOKEN not in blob
    assert TOPIC not in blob  # the topic is a capability too
    assert "401" in blob  # positive control: the failure was reported


def test_token_must_be_a_reference_never_a_literal(fake, monkeypatch):
    _unhold(monkeypatch)
    ok, detail = _push(fake, token=TOKEN).notify(_n())
    assert not ok and "reference" in detail
    assert TOKEN not in detail and fake.requests == []


def test_token_file_reference(fake, monkeypatch, tmp_path):
    _unhold(monkeypatch)
    f = tmp_path / "push_token.txt"
    f.write_text("\n" + TOKEN + "\n", encoding="ascii")
    ok, detail = _push(fake, token={"file": str(f)}).notify(_n())
    assert ok, detail
    assert fake.requests[0]["headers"]["authorization"] == f"Bearer {TOKEN}"


def test_unset_token_env_names_the_ref_and_sends_nothing(fake, monkeypatch):
    _unhold(monkeypatch)
    monkeypatch.delenv("RC_TEST_PUSH_TOKEN")
    ok, detail = _push(fake).notify(_n())
    assert not ok and "env:RC_TEST_PUSH_TOKEN" in detail
    assert fake.requests == []


def test_no_secret_reaches_argv():
    """Publishing is in-process urllib: no subprocess anywhere in the module."""
    tree = ast.parse(Path(op.__file__).read_text(encoding="ascii"))
    imported = {a.name.split(".")[0] for node in ast.walk(tree)
                if isinstance(node, (ast.Import, ast.ImportFrom))
                for a in (node.names if isinstance(node, ast.Import)
                          else [ast.alias(node.module or "")])}
    assert imported, "positive control: the walk found imports"
    assert "subprocess" not in imported and "sys" not in imported
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not attrs & {"system", "popen", "spawnv", "argv", "startfile"}


@pytest.mark.parametrize("server", [
    "https://ntfy.example.com", "http://192.0.2.230:8080", "ftp://legion.x.ts.net",
])
def test_public_or_lan_server_is_refused(server, monkeypatch, fake):
    _unhold(monkeypatch)
    p = op.NtfyNotifier({"enabled": True, "server": server, "topic": TOPIC,
                         "token": {"env": "RC_TEST_PUSH_TOKEN"}})
    ok, detail = p.notify(_n())
    assert not ok and "server" in detail and server not in detail


def test_tailnet_servers_are_allowed():
    assert op.server_refusal("https://rc-host.example-tailnet.ts.net:8443") is None
    assert op.server_refusal("http://100.64.0.1:8080") is None
    assert op.server_refusal("http://127.0.0.1:8080") is None


# ---------------------------------------------------------------- hold / off


def test_hold_sends_nothing(fake, monkeypatch):
    monkeypatch.setenv(on.HOLD_ENV, "1")
    p = _push(fake)
    ok, detail = p.notify(_n())
    assert not ok and detail.startswith("held")
    ok, items, pdetail = p.poll()
    assert not ok and items == [] and pdetail.startswith("held")
    assert fake.requests == []


def test_default_off_when_unconfigured(monkeypatch, tmp_path):
    # autouse fixture points the config at an absent file
    assert op.NtfyNotifier.from_config() is None
    assert [m.name for m in on.default_chain().notifiers] == ["toast", "jsonl"]


def test_default_off_when_config_present_but_not_enabled(fake, monkeypatch, tmp_path):
    cfgp = tmp_path / "push.json"
    cfgp.write_text(json.dumps(_cfg(fake, enabled=False)), encoding="ascii")
    monkeypatch.setenv(op.CONFIG_ENV, str(cfgp))
    assert op.NtfyNotifier.from_config() is None
    cfgp.write_text("{not json", encoding="ascii")
    assert op.NtfyNotifier.from_config() is None


def test_enabled_config_puts_push_first_in_default_chain(fake, monkeypatch, tmp_path):
    cfgp = tmp_path / "push.json"
    cfgp.write_text(json.dumps(_cfg(fake, tailnet_suffix=".example-tailnet.ts.net")),
                    encoding="ascii")
    monkeypatch.setenv(op.CONFIG_ENV, str(cfgp))
    assert [m.name for m in on.default_chain().notifiers] == ["ntfy", "toast", "jsonl"]


@pytest.mark.parametrize("suffix", [
    None, "", ".ts.net", "ts.net", "TS.NET.", "<your-tailnet>.ts.net", ".com",
])
def test_generic_or_placeholder_suffix_refuses_to_arm(fake, monkeypatch, tmp_path,
                                                      caplog, suffix):
    caplog.set_level(logging.INFO, logger=op.__name__)
    cfg = _cfg(fake)
    if suffix is None:
        cfg.pop("tailnet_suffix", None)
    else:
        cfg["tailnet_suffix"] = suffix
    cfgp = tmp_path / "push.json"
    cfgp.write_text(json.dumps(cfg), encoding="ascii")
    monkeypatch.setenv(op.CONFIG_ENV, str(cfgp))
    assert op.NtfyNotifier.from_config() is None
    assert "tailnet_suffix" in caplog.text  # the reason is logged
    assert TOKEN not in caplog.text and TOPIC not in caplog.text
    # positive control: the operator's own tailnet arms
    cfg["tailnet_suffix"] = ".example-tailnet.ts.net"
    cfgp.write_text(json.dumps(cfg), encoding="ascii")
    assert op.NtfyNotifier.from_config() is not None


def test_example_config_is_disabled_and_holds_only_references():
    ex = json.loads((Path(op.__file__).resolve().parents[1]
                     / "config" / "push_notify.example.json").read_text(encoding="ascii"))
    assert ex["enabled"] is False
    assert set(ex["token"]) <= {"env", "file"}
    # the suffix is a placeholder the operator must replace: it cannot arm as-is
    assert op.suffix_refusal(ex["tailnet_suffix"])


def test_real_config_is_gitignored():
    gi = (Path(op.__file__).resolve().parents[1] / ".gitignore").read_text(encoding="utf-8")
    assert "config/push_notify.json" in gi.splitlines()


# ---------------------------------------------------------------- fall-through


def test_failure_falls_through_to_floor(fake, monkeypatch, tmp_path):
    _unhold(monkeypatch)
    fake.status = 500
    floor = tmp_path / "floor2.jsonl"
    chain = on.FirstThatWorks([_push(fake), on.JsonlNotifier(floor, use_win32=False)])
    ok, detail = chain.notify(_n())
    assert ok
    assert detail.startswith("ntfy: ") and "500" in detail and "jsonl: appended" in detail
    assert json.loads(floor.read_text().splitlines()[0])["title"] == "Live flip ready"


def test_unreachable_server_falls_through_fast(monkeypatch, tmp_path):
    _unhold(monkeypatch)
    f = _Fake()
    url = f.url
    f.close()
    floor = tmp_path / "floor3.jsonl"
    p = op.NtfyNotifier({"enabled": True, "server": url, "topic": TOPIC,
                         "token": {"env": "RC_TEST_PUSH_TOKEN"}, "timeout_s": 2})
    ok, detail = on.FirstThatWorks([p, on.JsonlNotifier(floor, use_win32=False)]).notify(_n())
    assert ok and "ntfy: " in detail and floor.exists()


def test_redirect_is_not_followed(fake, monkeypatch):
    """A 30x must not carry the bearer token to another URL."""
    _unhold(monkeypatch)
    fake.redirect_to = fake.url + "/elsewhere"
    ok, detail = _push(fake).notify(_n())
    assert not ok and "302" in detail
    assert [r["path"] for r in fake.requests] == ["/"]


def test_timeout_is_short_and_capped(fake):
    assert _push(fake, timeout_s=999).timeout_s <= op.MAX_TIMEOUT_S <= 10
    assert _push(fake, timeout_s="junk").timeout_s == op.DEFAULT_TIMEOUT_S


# ---------------------------------------------------------------- sweep


def test_sibling_name_in_body_is_refused_before_leaving(fake, monkeypatch):
    _unhold(monkeypatch)
    ok, detail = _push(fake).notify(_n(body=f"merged from {SIBLING} today"))
    assert not ok and "sweep" in detail
    assert SIBLING not in detail  # the report never spells the needle
    assert fake.requests == []


def test_sibling_name_in_title_tag_or_link_is_refused(fake, monkeypatch):
    _unhold(monkeypatch)
    p = _push(fake)
    assert not p.notify(_n(title=SIBLING.upper()))[0]
    assert not p.notify(_n(tags=(SIBLING,)))[0]
    assert not p.notify(_n(link=TAILNET_LINK + "/" + SIBLING))[0]
    assert fake.requests == []


def test_structural_drive_path_is_refused(fake, monkeypatch):
    _unhold(monkeypatch)
    # Built at run time (same technique as tests/test_sibling_name_sweep.py
    # `_D`): spelled out, the synthetic drive path makes the pre-push
    # structural arm halt on this test file itself.
    unknown = "D:" + "/Unknownproj/notes"
    ok, detail = _push(fake).notify(_n(body="see " + unknown))
    assert not ok and "sweep" in detail and fake.requests == []


@pytest.mark.parametrize("field,value", [
    ("body", "ping someone.else@example.org about it"),
    ("body", "log at C:\\Users\\Administrator\\notes.txt"),  # allowlisted root
    ("body", "log at C:/Riot Commander/logs/x.log"),  # allowlisted root, fwd slash
    ("body", "share \\\\nas01\\drop\\file.txt"),
    ("title", "see /home/someone/x"),
    ("body", "see /Users/someone/x"),
    ("tags", "~/secrets"),
])
def test_email_or_path_is_refused_before_leaving(fake, monkeypatch, field, value):
    _unhold(monkeypatch)
    kw = {"title": "t", "body": "b"}
    if field == "tags":
        n = _n(tags=(value,))
    else:
        kw[field] = value
        n = _n(**kw)
    ok, detail = _push(fake).notify(n)
    assert not ok and "privacy sweep" in detail, detail
    assert value not in detail
    assert fake.requests == []


def test_privacy_sweep_spares_tailnet_urls_and_plain_text(fake, monkeypatch):
    """Positive control: an https:// tailnet link is not read as a drive path."""
    _unhold(monkeypatch)
    ok, detail = _push(fake).notify(_n(body="ratio 3:2 at 10:30", link=TAILNET_LINK))
    assert ok, detail


def test_sweep_fails_closed_when_it_cannot_arm(fake, monkeypatch, tmp_path):
    _unhold(monkeypatch)
    monkeypatch.delenv("RC_MOON_SYNC_REPOS")
    p = op.NtfyNotifier(_cfg(fake), sweep_root=tmp_path)  # no config there
    ok, detail = p.notify(_n())
    assert not ok and "DEGRADED" in detail and fake.requests == []


# ---------------------------------------------------------------- poll


def test_poll_reads_back_messages(fake, monkeypatch):
    _unhold(monkeypatch)
    fake.poll_lines = [
        {"id": "a1", "time": 1, "event": "open"},
        {"id": "m1", "time": 2, "event": "message", "title": "t", "message": "b",
         "priority": 4, "tags": ["x"]},
    ]
    ok, items, detail = _push(fake).poll(since_hours=36)
    assert ok, detail
    assert [i["id"] for i in items] == ["m1"]
    req = fake.requests[0]
    assert req["method"] == "GET"
    assert req["path"] == f"/{TOPIC}/json?poll=1&since=36h"
    assert req["headers"]["authorization"] == f"Bearer {TOKEN}"


def test_days_to_since():
    assert op.since_hours_from_days(2) == "48h"
    assert op.since_hours_from_days(0.5) == "12h"
    assert op.since_hours_from_days(-3) == "1h"


def test_poll_never_raises(fake, monkeypatch):
    _unhold(monkeypatch)
    fake.close()
    ok, items, detail = _push(fake).poll()
    assert not ok and items == [] and detail


# ---------------------------------------------------------------- fleet kit


def test_fleet_deliver_adapter_shape(fake, monkeypatch):
    _unhold(monkeypatch)
    deliver = op.fleet_deliver(_push(fake))
    answer = deliver(["id-1", "id-2"])
    assert answer["delivered"] is True and isinstance(answer["detail"], str)
    fake.status = 500
    answer = deliver(["id-3"])
    assert answer["delivered"] is False
