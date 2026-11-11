#!/usr/bin/env python3
"""The cache capture (design §4.3 *The conformance suite*, *The cache capture, live, by hand*; TD-1551, TD-1664).

Two commands, standard library only:

- `serve --port N --out DIR [--upstream URL]`: a logging pass-through a tool's base URL is pointed at (Claude
  Code's `ANTHROPIC_BASE_URL=http://127.0.0.1:N`). It forwards each request to the upstream (default
  `https://api.anthropic.com`), streams the response back as it comes (an SSE stream included), passing its
  `content-encoding` through untouched, and writes each request body and each response body, decoded, to DIR as
  `NNNN-request.json` and `NNNN-response.txt` — never a header, so no key reaches the files.
- `show FILE…`: each request's layout — the tool count, each system and message block with its length and cache
  marker — and the first request's cache figures from its response (the `NNNN-response.txt` beside it). It reads
  the shape from a small provider table (`--provider`, Anthropic's the first row); for a provider with no row it
  prints the top-level block sizes and the raw `usage` alone.
"""

from __future__ import annotations

import argparse
import gzip
import http.client
import http.server
import json
import re
import sys
import threading
import urllib.error
import urllib.request
import zlib
from pathlib import Path
from typing import Any

UPSTREAM = "https://api.anthropic.com"
CHUNK = 8192
# hop-by-hop headers (RFC 9110 §7.6.1) and the ones the forward recomputes: never passed on either way
HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}

# Where each provider keeps what `show` reads. A row: the request's tool list, its system text, its messages, a
# block's cache marker, and the usage's input, cache-read and cache-write fields.
PROVIDERS: dict[str, dict[str, str]] = {
    "anthropic": {
        "tools": "tools",
        "system": "system",
        "messages": "messages",
        "marker": "cache_control",
        "input": "input_tokens",
        "read": "cache_read_input_tokens",
        "write": "cache_creation_input_tokens",
    },
}


def decode(body: bytes, encoding: str | None) -> bytes:
    """A body as its `content-encoding` names it, decoded where the standard library can (gzip, deflate); any other
    encoding is kept as it came."""
    enc = (encoding or "").strip().lower()
    try:
        if enc in ("gzip", "x-gzip"):
            return gzip.decompress(body)
        if enc == "deflate":
            try:
                return zlib.decompress(body)
            except zlib.error:
                return zlib.decompress(body, -zlib.MAX_WBITS)  # raw deflate, as some servers send it
    except (OSError, EOFError, zlib.error):
        return body
    return body


class Recorder:
    """Numbers each exchange and writes its two bodies under `out`."""

    def __init__(self, out: Path) -> None:
        self.out = out
        self.out.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._n = 0

    def next(self) -> int:
        with self._lock:
            self._n += 1
            return self._n

    def write(self, n: int, kind: str, body: bytes) -> Path:
        path = self.out / (f"{n:04d}-request.json" if kind == "request" else f"{n:04d}-response.txt")
        path.write_bytes(body)
        return path


def make_handler(upstream: str, rec: Recorder) -> type[http.server.BaseHTTPRequestHandler]:
    base = upstream.rstrip("/")

    class Handler(http.server.BaseHTTPRequestHandler):
        # HTTP/1.0 to the client: the connection closes after each response, so a stream needs no framing of ours
        protocol_version = "HTTP/1.0"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 — the base class's name
            sys.stderr.write(f"cache_capture: {self.command} {self.path} {format % args}\n")

        def _forward(self) -> None:
            n = rec.next()
            length = int(self.headers.get("content-length") or 0)
            body = self.rfile.read(length) if length else b""
            rec.write(n, "request", decode(body, self.headers.get("content-encoding")))
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
            req = urllib.request.Request(base + self.path, data=body or None, headers=headers, method=self.command)
            try:
                resp = urllib.request.urlopen(req, timeout=600)  # noqa: S310 — the URL is the person's --upstream
            except urllib.error.HTTPError as e:
                resp = e  # an error status is still the upstream's answer: passed on as it came
            except (urllib.error.URLError, OSError) as e:
                self.send_error(502, f"upstream: {e}")
                return
            with resp:
                self.send_response(resp.status)
                for k, v in resp.headers.items():
                    if k.lower() not in HOP and k.lower() not in ("server", "date"):  # send_response wrote its own
                        self.send_header(k, v)
                self.end_headers()
                got = bytearray()
                try:
                    while True:
                        chunk = resp.read1(CHUNK) if hasattr(resp, "read1") else resp.read(CHUNK)
                        if not chunk:
                            break
                        got += chunk
                        try:
                            self.wfile.write(chunk)
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError):
                            break  # the client went away; what came is still recorded
                except (OSError, http.client.HTTPException) as e:  # the upstream broke mid-stream
                    sys.stderr.write(f"cache_capture: upstream broke after {len(got)} bytes: {e!r}\n")
                finally:
                    rec.write(n, "response", decode(bytes(got), resp.headers.get("content-encoding")))

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _forward

    return Handler


def serve(port: int, out: Path, upstream: str = UPSTREAM, host: str = "127.0.0.1") -> http.server.ThreadingHTTPServer:
    """The proxy, bound but not yet serving (`serve_forever` it): the caller owns its life."""
    return http.server.ThreadingHTTPServer((host, port), make_handler(upstream, Recorder(out)))


# ---------------------------------------------------------------------------------------------------- show


def usage_of(text: str) -> dict[str, Any] | None:
    """The response's `usage`: a JSON body's own, or a streamed one's `message_start` usage updated by each
    `message_delta`'s (the last figures win). None where neither is found."""
    try:
        doc = json.loads(text)
    except ValueError:
        doc = None
    if isinstance(doc, dict):
        u = doc.get("usage")
        return u if isinstance(u, dict) else None
    usage: dict[str, Any] | None = None
    for line in text.splitlines():
        m = re.match(r"data:\s?(.*)", line)
        if not m:
            continue
        try:
            ev = json.loads(m.group(1))
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        u = ev.get("message", {}).get("usage") if ev.get("type") == "message_start" else ev.get("usage")
        if isinstance(u, dict):
            usage = {**(usage or {}), **{k: v for k, v in u.items() if v is not None}}
    return usage


def _size(block: Any) -> int:
    if isinstance(block, str):
        return len(block)
    if isinstance(block, dict):
        for k in ("text", "content", "input"):
            if k in block:
                return _size(block[k])
    if isinstance(block, list):
        return sum(_size(b) for b in block)
    return len(json.dumps(block, ensure_ascii=False))


def _blocks(value: Any) -> list[Any]:
    if isinstance(value, str):
        return [value]
    return list(value) if isinstance(value, list) else []


def layout(req: dict[str, Any], row: dict[str, str] | None) -> list[str]:
    """One request's layout as lines: with a provider row, the tool count and each system and message block with
    its length and cache marker; without one, each top-level key's size."""
    if row is None:
        return [f"  {k}: {len(json.dumps(v, ensure_ascii=False))} chars" for k, v in req.items()]
    mark = row["marker"]
    lines = [f"  tools: {len(req.get(row['tools']) or [])}"]
    for i, b in enumerate(_blocks(req.get(row["system"]))):
        cut = " [cache]" if isinstance(b, dict) and b.get(mark) else ""
        lines.append(f"  system[{i}]: {_size(b)} chars{cut}")
    for i, msg in enumerate(req.get(row["messages"]) or []):
        role = msg.get("role", "?") if isinstance(msg, dict) else "?"
        content = msg.get("content") if isinstance(msg, dict) else msg
        for j, b in enumerate(_blocks(content)):
            kind = b.get("type", "block") if isinstance(b, dict) else "text"
            cut = " [cache]" if isinstance(b, dict) and b.get(mark) else ""
            lines.append(f"  messages[{i}] {role} [{j}] {kind}: {_size(b)} chars{cut}")
    return lines


def show(files: list[Path], provider: str = "anthropic") -> str:
    """The layouts of `files` (request files; a response file among them is passed over) and the first request's
    cache figures, as text."""
    row = PROVIDERS.get(provider)
    reqs = sorted(f for f in files if not f.name.endswith("-response.txt"))
    out: list[str] = []
    if row is None:
        out.append(f"provider {provider!r} has no row: block sizes and the raw usage only")
    for f in reqs:
        try:
            req = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            out.append(f"{f}: not a JSON request ({e})")
            continue
        out.append(f"{f}:")
        out.extend(layout(req if isinstance(req, dict) else {"body": req}, row))
    if reqs and reqs[0].name.endswith("-request.json"):
        first = reqs[0]
        resp = first.with_name(first.name.replace("-request.json", "-response.txt"))
        usage = usage_of(resp.read_text(encoding="utf-8")) if resp.exists() else None
        if usage is None:
            out.append(f"first request's usage: none found ({resp.name})")
        elif row is None:
            out.append(f"first request's usage: {json.dumps(usage, sort_keys=True)}")
        else:
            out.append(
                "first request's cache: "
                f"read {usage.get(row['read'], 0)}, write {usage.get(row['write'], 0)}, "
                f"uncached input {usage.get(row['input'], 0)}"
            )
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cache_capture.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="the logging pass-through a tool's base URL is pointed at")
    s.add_argument("--port", type=int, required=True)
    s.add_argument("--out", type=Path, required=True, help="where each request and response body is written")
    s.add_argument("--upstream", default=UPSTREAM, help=f"the provider's API (default {UPSTREAM})")
    w = sub.add_parser("show", help="each request's layout and the first request's cache figures")
    w.add_argument("files", nargs="+", type=Path)
    w.add_argument("--provider", default="anthropic", help=f"a row of the table: {', '.join(PROVIDERS)}")
    args = ap.parse_args(argv)
    if args.cmd == "show":
        print(show(args.files, args.provider))
        return 0
    srv = serve(args.port, args.out, args.upstream)
    print(f"cache_capture: http://127.0.0.1:{srv.server_address[1]} → {args.upstream}, bodies in {args.out}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
