"""TD-880 (design §4.5 *Page loads*, *Compressed* and *Cached*): a page, a `part=1` fragment and a static
file go gzipped to a browser that takes it, with `Vary: Accept-Encoding`, and plain to one that does not;
the compression runs on a worker thread, never on the loop; a static file carrying its `?v=` hash is kept
a year, immutable, and one without it is revalidated; the event stream is a websocket and passes by."""

from __future__ import annotations

import asyncio
import gzip
import threading

from fastapi.testclient import TestClient
from test_ui_shape import fake

GZ = {"Accept-Encoding": "gzip"}


def client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    from shiftlead.ui import app as ui

    monkeypatch.setattr(ui, "LocalClient", fake([]))
    return TestClient(ui.create_app())


def raw(c: TestClient, url: str, headers: dict[str, str]) -> tuple[dict[str, str], bytes]:
    """The response's headers and its body as sent, not decoded."""
    with c.stream("GET", url, headers=headers) as r:
        assert r.status_code == 200, url
        return dict(r.headers), b"".join(r.iter_raw())


def test_a_page_and_a_fragment_go_gzipped_to_a_browser_that_takes_it_and_plain_otherwise(tmp_path, monkeypatch):
    c = client(monkeypatch, tmp_path)
    for url in ("/spend?view=shape", "/spend?view=shape&team=ao-grind&window=week&part=1"):
        h, body = raw(c, url, GZ)
        assert h["content-encoding"] == "gzip" and h["vary"] == "Accept-Encoding"
        page = gzip.decompress(body)
        assert int(h["content-length"]) == len(body) < len(page) and b"shteam" in page
        for no in ({"Accept-Encoding": "identity"}, {"Accept-Encoding": "gzip;q=0"}):
            h, plain = raw(c, url, no)
            assert "content-encoding" not in h and h["vary"] == "Accept-Encoding" and b"shteam" in plain


def test_a_body_under_a_kilobyte_and_an_encoded_one_are_sent_as_they_are(tmp_path, monkeypatch):
    from shiftlead.ui import app as ui

    c = client(monkeypatch, tmp_path)
    app = c.app
    app.add_api_route("/tiny", lambda: ui.Response(b"x" * (ui.GZIP_MIN - 1), media_type="text/plain"))
    big = gzip.compress(b"y" * 5000)
    app.add_api_route("/pre", lambda: ui.json_answer(big, True))
    h, body = raw(c, "/tiny", GZ)
    assert "content-encoding" not in h and body == b"x" * (ui.GZIP_MIN - 1)
    h, body = raw(c, "/pre", GZ)
    assert h["content-encoding"] == "gzip" and body == big  # not compressed twice


def test_the_compression_runs_on_a_worker_thread(tmp_path, monkeypatch):
    from shiftlead.ui import app as ui

    threads: list[threading.Thread] = []
    real = ui.gzip.compress

    def compress(data, *a, **k):
        threads.append(threading.current_thread())
        return real(data, *a, **k)

    loops: list[threading.Thread] = []
    c = client(monkeypatch, tmp_path)

    async def on_loop():
        loops.append(threading.current_thread())
        return ui.Response(b"z" * 4096)

    c.app.add_api_route("/aloop", on_loop)
    monkeypatch.setattr(ui.gzip, "compress", compress)
    h, _ = raw(c, "/aloop", GZ)
    assert h["content-encoding"] == "gzip" and len(threads) == 1 and threads[0] is not loops[-1]


def test_a_hashed_static_file_is_kept_a_year_and_a_bare_one_revalidated(tmp_path, monkeypatch):
    from shiftlead.ui.common import static_url

    c = client(monkeypatch, tmp_path)
    url = static_url("app.js")
    assert "?v=" in url
    h, body = raw(c, url, GZ)
    assert h["cache-control"] == "public, max-age=31536000, immutable"
    assert h["content-encoding"] == "gzip" and len(gzip.decompress(body)) > len(body)
    h, _ = raw(c, "/static/app.js", {"Accept-Encoding": "identity"})
    assert h["cache-control"] == "no-cache" and h["etag"] and "content-encoding" not in h
    font = "/static/vendor/fonts/jetbrains-mono-latin-400-normal.woff2"
    fh, _ = raw(c, font, GZ)
    assert "content-encoding" not in fh  # a woff2 is compressed already
    r = c.get("/static/app.js", headers={"If-None-Match": h["etag"]})
    assert r.status_code == 304 and r.headers["cache-control"] == "no-cache"


def test_the_event_stream_is_not_compressed(tmp_path, monkeypatch):
    """The pushed stream is a websocket: `_Gzip` hands any scope that is not http straight on."""
    from shiftlead.ui import app as ui

    seen: list[str] = []

    async def inner(scope, receive, send):
        seen.append(scope["type"])
        await send({"type": "websocket.accept"})

    sent: list[dict] = []

    async def send(m):
        sent.append(m)

    asyncio.run(ui._Gzip(inner)({"type": "websocket", "headers": [(b"accept-encoding", b"gzip")]}, None, send))
    assert seen == ["websocket"] and sent == [{"type": "websocket.accept"}]


def test_a_pathsend_goes_after_its_start_as_it_was():
    """A server with the `pathsend` extension gets a `FileResponse`'s start before its pathsend, never
    the pathsend alone (the held start is let go first)."""
    from shiftlead.ui import app as ui

    start = {"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/javascript")]}

    async def inner(scope, receive, send):
        await send(start)
        await send({"type": "http.response.pathsend", "path": "/x.js"})

    sent: list[dict] = []

    async def send(m):
        sent.append(m)

    scope = {"type": "http", "method": "GET", "path": "/", "headers": [(b"accept-encoding", b"gzip")]}
    asyncio.run(ui._Gzip(inner)(scope, None, send))
    assert [m["type"] for m in sent] == ["http.response.start", "http.response.pathsend"] and sent[0] is start


def test_a_ranged_request_a_non_200_and_an_encoded_body_over_a_kilobyte_go_as_they_are(tmp_path, monkeypatch):
    """TD-885: each guard of `_Gzip`'s start under a body big enough to be compressed — a `Range`
    request (a partial body gzipped is corrupt), a 404 and a 206, and a body already gzipped that is
    not compressed again."""
    import os

    from shiftlead.ui import app as ui

    c = client(monkeypatch, tmp_path)
    big = b"x" * 5000
    c.app.add_api_route("/big", lambda: ui.Response(big, media_type="text/plain"))
    c.app.add_api_route("/gone", lambda: ui.Response(big, status_code=404, media_type="text/plain"))
    c.app.add_api_route("/part", lambda: ui.Response(big, status_code=206, media_type="text/plain"))
    packed = gzip.compress(os.urandom(4096))
    assert len(packed) >= ui.GZIP_MIN
    c.app.add_api_route(
        "/enc", lambda: ui.Response(packed, media_type="text/plain", headers={"Content-Encoding": "gzip"})
    )
    h, body = raw(c, "/big", GZ)
    assert h["content-encoding"] == "gzip"  # the same body unranged is compressed
    h, body = raw(c, "/big", GZ | {"Range": "bytes=0-99"})
    assert "content-encoding" not in h and body == big
    for url, status in (("/gone", 404), ("/part", 206)):
        with c.stream("GET", url, headers=GZ) as r:
            assert r.status_code == status and "content-encoding" not in r.headers
            assert b"".join(r.iter_raw()) == big
    h, body = raw(c, "/enc", GZ)
    assert h["content-encoding"] == "gzip" and body == packed  # not compressed twice


def test_a_body_sent_in_chunks_is_compressed_whole(tmp_path, monkeypatch):
    """TD-885: a streamed body is held until its last chunk and compressed once, not per chunk."""
    from fastapi.responses import StreamingResponse

    c = client(monkeypatch, tmp_path)

    def chunks():
        yield b"a" * 3000
        yield b"b" * 3000

    c.app.add_api_route("/chunks", lambda: StreamingResponse(chunks(), media_type="text/plain"))
    h, body = raw(c, "/chunks", GZ)
    assert h["content-encoding"] == "gzip" and gzip.decompress(body) == b"a" * 3000 + b"b" * 3000


def test_an_empty_v_is_no_hash(tmp_path, monkeypatch):
    """TD-885: `?v=` with nothing after it marks no file immutable (`parse_qsl` drops a blank value, so
    `_Static` never sees the pair)."""
    c = client(monkeypatch, tmp_path)
    h, _ = raw(c, "/static/app.js?v=", GZ)
    assert h["cache-control"] == "no-cache"
