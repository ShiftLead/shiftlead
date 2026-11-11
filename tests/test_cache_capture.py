"""`scripts/cache_capture.py` (design §4.3 *The cache capture, live, by hand*, TD-1664): the logging pass-through
against a local stub upstream, and the reader over a fixture request with a JSON and an SSE response."""

from __future__ import annotations

import gzip
import http.server
import importlib.util
import json
import threading
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "cache_capture.py"


def _load():
    spec = importlib.util.spec_from_file_location("cache_capture", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


cc = _load()

JSON_BODY = {
    "id": "msg_1",
    "usage": {"input_tokens": 12, "cache_read_input_tokens": 29451, "cache_creation_input_tokens": 0},
}
SSE_BODY = (
    'event: message_start\ndata: {"type":"message_start","message":{"id":"msg_2","usage":'
    '{"input_tokens":5,"cache_read_input_tokens":0,"cache_creation_input_tokens":27500}}}\n\n'
    'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"text":"hi"}}\n\n'
    'event: message_delta\ndata: {"type":"message_delta","usage":{"output_tokens":7}}\n\n'
)
SECRET = "sk-ant-not-a-real-key"


class Upstream(http.server.BaseHTTPRequestHandler):
    """The stub provider: `/json` a JSON body, `/sse` an event stream, `/gz` the JSON gzip-encoded; each records the
    request it got so the test can read what the proxy forwarded."""

    seen: list[dict] = []

    def log_message(self, *a):  # quiet
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("content-length") or 0))
        Upstream.seen.append({"path": self.path, "body": body, "key": self.headers.get("x-api-key")})
        if self.path == "/v1/sse":
            data, ctype, enc = SSE_BODY.encode(), "text/event-stream", None
        elif self.path == "/v1/gz":
            data, ctype, enc = gzip.compress(json.dumps(JSON_BODY).encode()), "application/json", "gzip"
        else:
            data, ctype, enc = json.dumps(JSON_BODY).encode(), "application/json", None
        self.send_response(200)
        self.send_header("content-type", ctype)
        if enc:
            self.send_header("content-encoding", enc)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def proxy(tmp_path):
    Upstream.seen = []
    up = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    out = tmp_path / "cap"
    srv = cc.serve(0, out, f"http://127.0.0.1:{up.server_address[1]}")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", out
    srv.shutdown()
    srv.server_close()
    up.shutdown()
    up.server_close()


def _post(url: str, body: dict) -> tuple[bytes, dict]:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"x-api-key": SECRET, "content-type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 — a local stub
        return r.read(), dict(r.headers)


def test_the_proxy_passes_each_response_through_and_writes_the_decoded_bodies_and_no_header(proxy):
    base, out = proxy
    request = {"model": "m", "system": [{"type": "text", "text": "x"}], "messages": []}
    got_json, _ = _post(base + "/v1/json", request)
    got_sse, h_sse = _post(base + "/v1/sse", request)
    got_gz, h_gz = _post(base + "/v1/gz", request)
    # the client gets the upstream's bytes as they were: the gzip still encoded, its header passed on
    assert json.loads(got_json) == JSON_BODY
    assert got_sse.decode() == SSE_BODY and h_sse["content-type"] == "text/event-stream"
    assert h_gz.get("content-encoding") == "gzip" and json.loads(gzip.decompress(got_gz)) == JSON_BODY
    # the upstream got the request, the key included (the proxy forwards headers, it only never writes them)
    assert [s["path"] for s in Upstream.seen] == ["/v1/json", "/v1/sse", "/v1/gz"]
    assert all(s["key"] == SECRET and json.loads(s["body"]) == request for s in Upstream.seen)
    names = sorted(p.name for p in out.iterdir())
    assert names == [f"{n:04d}-{k}" for n in (1, 2, 3) for k in ("request.json", "response.txt")]
    assert json.loads((out / "0001-request.json").read_text()) == request
    assert (out / "0002-response.txt").read_text() == SSE_BODY
    assert json.loads((out / "0003-response.txt").read_text()) == JSON_BODY  # decoded
    for p in out.iterdir():
        text = p.read_text()
        assert SECRET not in text and "x-api-key" not in text.lower() and "content-type" not in text.lower()


FIXTURE_REQUEST = {
    "model": "claude-opus-5-5",
    "tools": [{"name": "Bash"}, {"name": "Read"}, {"name": "Edit"}],
    "system": [
        {"type": "text", "text": "You are Claude Code.", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "x" * 120, "cache_control": {"type": "ephemeral", "ttl": "1h"}},
    ],
    "messages": [
        {"role": "user", "content": [{"type": "text", "text": "y" * 40}, {"type": "text", "text": "hello"}]},
        {
            "role": "user",
            "content": "plain",
        },
    ],
}


@pytest.mark.parametrize("response", [json.dumps(JSON_BODY), SSE_BODY], ids=["json", "sse"])
def test_show_prints_the_layout_and_the_first_requests_cache_figures(tmp_path, response):
    (tmp_path / "0001-request.json").write_text(json.dumps(FIXTURE_REQUEST))
    (tmp_path / "0001-response.txt").write_text(response)
    (tmp_path / "0002-request.json").write_text(json.dumps({**FIXTURE_REQUEST, "tools": []}))
    text = cc.show(sorted(tmp_path.iterdir()))
    lines = text.splitlines()
    first = lines[: lines.index(f"{tmp_path / '0002-request.json'}:")]
    assert first == [
        f"{tmp_path / '0001-request.json'}:",
        "  tools: 3",
        "  system[0]: 20 chars [cache]",
        "  system[1]: 120 chars [cache]",
        "  messages[0] user [0] text: 40 chars",
        "  messages[0] user [1] text: 5 chars",
        "  messages[1] user [0] text: 5 chars",
    ]
    assert "  tools: 0" in lines
    want = (
        "read 29451, write 0, uncached input 12"
        if response.startswith("{")
        else "read 0, write 27500, uncached input 5"
    )
    assert lines[-1] == f"first request's cache: {want}"


def test_show_for_a_provider_with_no_row_prints_block_sizes_and_the_raw_usage(tmp_path):
    (tmp_path / "0001-request.json").write_text(json.dumps({"contents": ["abc"], "model": "g"}))
    (tmp_path / "0001-response.txt").write_text(json.dumps({"usage": {"promptTokenCount": 9}}))
    text = cc.show([tmp_path / "0001-request.json"], provider="gemini")
    assert text.splitlines() == [
        "provider 'gemini' has no row: block sizes and the raw usage only",
        f"{tmp_path / '0001-request.json'}:",
        "  contents: 7 chars",
        "  model: 3 chars",
        'first request\'s usage: {"promptTokenCount": 9}',
    ]


def test_usage_of_merges_a_streams_message_delta_over_its_message_start():
    assert cc.usage_of(SSE_BODY) == {
        "input_tokens": 5,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 27500,
        "output_tokens": 7,
    }
    assert cc.usage_of("not json, no events") is None
    # a null in a later event never overwrites a figure an earlier one gave
    nulled = SSE_BODY + 'data: {"type":"message_delta","usage":{"cache_creation_input_tokens":null}}\n\n'
    assert cc.usage_of(nulled)["cache_creation_input_tokens"] == 27500
