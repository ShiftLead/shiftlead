"""`scripts/cache_capture.py` (design §4.3 *The cache capture, live, by hand*, TD-1664): the logging pass-through
against a local stub upstream, and the reader over a fixture request with a JSON and an SSE response."""

from __future__ import annotations

import gzip
import http.server
import importlib.util
import json
import shutil
import socket
import struct
import subprocess
import threading
import time
import urllib.error
import urllib.request
import zlib
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
LIMITED = {"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}}


class Upstream(http.server.BaseHTTPRequestHandler):
    """The stub provider: `/json` a JSON body, `/sse` an event stream, `/gz` the JSON gzip-encoded; each records the
    request it got so the test can read what the proxy forwarded."""

    seen: list[dict] = []

    def log_message(self, *a):  # quiet
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("content-length") or 0))
        Upstream.seen.append({"path": self.path, "body": body, "key": self.headers.get("x-api-key")})
        raw = json.dumps(JSON_BODY).encode()
        status, extra = 200, {}
        if self.path == "/v1/sse":
            data, ctype, enc = SSE_BODY.encode(), "text/event-stream", None
        elif self.path == "/v1/gz":
            data, ctype, enc = gzip.compress(raw), "application/json", "gzip"
        elif self.path == "/v1/deflate":
            data, ctype, enc = zlib.compress(raw), "application/json", "deflate"
        elif self.path == "/v1/rawdeflate":
            c = zlib.compressobj(wbits=-zlib.MAX_WBITS)
            data, ctype, enc = c.compress(raw) + c.flush(), "application/json", "deflate"
        elif self.path == "/v1/429":
            data, ctype, enc = json.dumps(LIMITED).encode(), "application/json", None
            status, extra = 429, {"retry-after": "7"}
        elif self.path == "/v1/slow":
            self._slow()
            return
        else:
            data, ctype, enc = raw, "application/json", None
        self.send_response(status)
        for k, v in extra.items():
            self.send_header(k, v)
        self.send_header("content-type", ctype)
        if enc:
            self.send_header("content-encoding", enc)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _slow(self):
        """An event stream that keeps coming, a chunk every 50 ms for up to 10 s: long enough for a client to go."""
        self.protocol_version = "HTTP/1.0"
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        try:
            for i in range(200):
                self.wfile.write(f"data: {i}\n\n".encode())
                self.wfile.flush()
                time.sleep(0.05)
        except OSError:
            pass


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


def test_a_gzip_encoded_request_is_recorded_decoded_and_forwarded_as_it_came(proxy):
    base, out = proxy
    request = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
    gz = gzip.compress(json.dumps(request).encode())
    req = urllib.request.Request(
        base + "/v1/json", data=gz, headers={"content-type": "application/json", "content-encoding": "gzip"}
    )
    with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 — a local stub
        r.read()
    assert Upstream.seen[0]["body"] == gz  # the upstream got the bytes the client sent
    assert json.loads((out / "0001-request.json").read_text()) == request  # the file holds them decoded


def test_an_upstream_error_status_reaches_the_client_as_it_came_and_its_body_is_recorded(proxy):
    base, out = proxy
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(base + "/v1/429", {"model": "m"})
    assert e.value.code == 429
    assert e.value.headers.get("retry-after") == "7"
    assert json.loads(e.value.read()) == LIMITED
    assert json.loads((out / "0001-response.txt").read_text()) == LIMITED


def test_an_upstream_that_does_not_answer_is_a_502(tmp_path):
    with socket.socket() as s:  # a port that was free a moment ago and is closed now
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = cc.serve(0, tmp_path / "cap", f"http://127.0.0.1:{port}")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with pytest.raises(urllib.error.HTTPError) as e:
            _post(f"http://127.0.0.1:{srv.server_address[1]}/v1/json", {"model": "m"})
        assert e.value.code == 502
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.parametrize("path", ["/v1/deflate", "/v1/rawdeflate"], ids=["zlib", "raw"])
def test_a_deflate_response_is_passed_through_and_recorded_decoded(proxy, path):
    base, out = proxy
    got, headers = _post(base + path, {"model": "m"})
    assert headers.get("content-encoding") == "deflate"
    assert got != json.dumps(JSON_BODY).encode()  # the client gets it still encoded
    assert json.loads((out / "0001-response.txt").read_text()) == JSON_BODY


def test_the_client_response_carries_one_date_and_one_server_header(proxy):
    base, _ = proxy
    req = urllib.request.Request(base + "/v1/json", data=b"{}", headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 — a local stub
        r.read()
        assert len(r.headers.get_all("Date") or []) == 1
        assert len(r.headers.get_all("Server") or []) == 1


def test_a_client_that_goes_away_mid_stream_ends_the_forward_quietly_and_what_came_is_recorded(proxy, capsys):
    base, out = proxy
    host, port = base.removeprefix("http://").split(":")
    c = socket.create_connection((host, int(port)), timeout=10)
    c.sendall(b"POST /v1/slow HTTP/1.0\r\ncontent-length: 2\r\n\r\n{}")
    assert b"data: 0" in c.recv(4096) or b"data: 0" in c.recv(4096)
    c.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))  # close with a reset
    c.close()
    resp = out / "0001-response.txt"
    deadline = time.monotonic() + 10
    while not (resp.exists() and resp.stat().st_size) and time.monotonic() < deadline:  # written, not just made
        time.sleep(0.05)
    assert resp.read_text().startswith("data: 0\n\n")
    assert "data: 199" not in resp.read_text()  # the forward stopped when the client went
    # a client gone is not the upstream breaking: nothing says it did
    assert "upstream broke" not in capsys.readouterr().err


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


ZSTD = shutil.which("zstd")


@pytest.mark.skipif(ZSTD is None, reason="no zstd binary")
def test_a_zstd_encoded_request_is_recorded_decoded_by_the_binary_and_forwarded_as_it_came(proxy):
    base, out = proxy
    request = {"model": "grok-4.7", "input": [{"role": "user", "content": "hi"}]}
    zst = subprocess.run([ZSTD, "-cq"], input=json.dumps(request).encode(), capture_output=True, check=True).stdout
    req = urllib.request.Request(
        base + "/v1/json", data=zst, headers={"content-type": "application/json", "content-encoding": "zstd"}
    )
    with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 — a local stub
        r.read()
    assert Upstream.seen[0]["body"] == zst  # the upstream got the bytes the client sent
    assert json.loads((out / "0001-request.json").read_text()) == request  # the file holds them decoded


def test_a_zstd_body_with_no_binary_is_kept_raw_and_stderr_says_so(monkeypatch, capsys):
    monkeypatch.setattr(cc.shutil, "which", lambda name: None)
    assert cc.decode(b"\x28\xb5\x2f\xfdnot-really", "zstd") == b"\x28\xb5\x2f\xfdnot-really"
    assert "no zstd binary on PATH" in capsys.readouterr().err


@pytest.mark.skipif(ZSTD is None, reason="no zstd binary")
def test_a_body_the_binary_cannot_decode_is_kept_raw_and_stderr_says_why(capsys):
    assert cc.decode(b"not zstd at all", "zstd") == b"not zstd at all"
    assert "zstd exited" in capsys.readouterr().err


RESPONSES_REQUEST = {
    "model": "grok-4.7",
    "stream": True,
    "store": False,
    "prompt_cache_key": "sess-1234",
    "tools": [{"type": "function", "name": n} for n in ("bash", "read", "send_feedback")],
    "input": [
        {"role": "system", "content": "s" * 70},
        {"role": "user", "content": [{"type": "input_text", "text": "env " * 5}, {"type": "input_text", "text": "go"}]},
        {"type": "function_call", "name": "bash", "arguments": '{"cmd":"ls"}', "call_id": "c1"},
        {"type": "function_call_output", "call_id": "c1", "output": "a b"},
    ],
}
RESPONSES_SSE = (
    'event: response.created\ndata: {"type":"response.created","response":{"id":"r1","usage":null}}\n\n'
    'event: response.output_text.delta\ndata: {"type":"response.output_text.delta","delta":"hi"}\n\n'
    'event: response.completed\ndata: {"type":"response.completed","response":{"id":"r1","usage":'
    '{"input_tokens":23800,"input_tokens_details":{"cached_tokens":1664},"output_tokens":9}}}\n\n'
)


@pytest.mark.parametrize(
    "response",
    [RESPONSES_SSE, json.dumps({"usage": {"input_tokens": 23800, "input_tokens_details": {"cached_tokens": 1664}}})],
    ids=["sse", "json"],
)
def test_show_reads_a_responses_request_its_cache_key_blocks_and_cached_tokens(tmp_path, response):
    (tmp_path / "0001-request.json").write_text(json.dumps(RESPONSES_REQUEST))
    (tmp_path / "0001-response.txt").write_text(response)
    text = cc.show([tmp_path / "0001-request.json"], provider="responses")
    assert text.splitlines() == [
        f"{tmp_path / '0001-request.json'}:",
        "  tools: 3",
        "  prompt_cache_key: sess-1234",
        "  system[0]: 70 chars",
        "  messages[0] user [0] input_text: 20 chars",
        "  messages[0] user [1] input_text: 2 chars",
        "  messages[1] ? [0] function_call: 91 chars",  # an item with no content: its whole JSON
        "  messages[2] ? [0] function_call_output: 66 chars",
        "first request's cache: read 1664, input (the read included) 23800",
    ]


def test_show_measures_a_null_content_item_whole_and_reads_a_string_input_as_one_message(tmp_path):
    reasoning = {"type": "reasoning", "content": None, "summary": []}
    (tmp_path / "0001-request.json").write_text(json.dumps({"tools": [], "input": [reasoning]}))
    (tmp_path / "0002-request.json").write_text(json.dumps({"tools": [], "input": "hello"}))
    lines = cc.show(sorted(tmp_path.iterdir()), provider="responses").splitlines()
    assert f"  messages[0] ? [0] reasoning: {len(json.dumps(reasoning))} chars" in lines
    assert lines[-2] == "  messages[0] user [0] text: 5 chars"  # the last is the first request's usage line
