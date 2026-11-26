"""§4.4a *Settings, replicated* (TD-1870): the home sends one settings push at a time, its read of the file and its
sends together, so a dial's push that read the file before a `set_settings` write never lands after the write's own
frame and puts the old file back on the node."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from sessionorc import agent_remote
from sessionorc.agent_remote import RemoteMixin


async def test_a_push_read_before_a_write_never_lands_after_the_writes_own(monkeypatch):
    file = {"doc": {"reserves": 30}}
    first_read = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def read_then_hold():
        nonlocal calls
        calls += 1
        doc = dict(file["doc"])
        if calls == 1:  # the dial's push: it reads the old file, then is slow to send it
            first_read.set()
            await release.wait()
        return doc

    async def to_thread(fn, *a, **kw):
        return await read_then_hold()

    monkeypatch.setattr(agent_remote.asyncio, "to_thread", to_thread)
    sent: list[dict] = []

    class Mux:
        async def notify(self, method, **params):
            sent.append(params["doc"])

    home = SimpleNamespace(mode="home", _link_muxes={"laptop": Mux()}, _settings_push_lock=asyncio.Lock())
    dial = asyncio.ensure_future(RemoteMixin._push_settings(home, "laptop"))
    await first_read.wait()
    file["doc"] = {"reserves": 40}  # the person's write, and its own push
    write = asyncio.ensure_future(RemoteMixin._push_settings(home))
    await asyncio.sleep(0.05)
    release.set()
    await asyncio.gather(dial, write)
    assert sent == [{"reserves": 30}, {"reserves": 40}], sent  # the last frame is the newest file


async def test_a_node_saves_the_pushes_in_the_order_they_came(monkeypatch):
    """The node's half (TD-1870, #4793's precheck): the link serves each frame in a task of its own and the node saves
    the file in a thread, so a slow save of the dial's older file could land after the write's newer one and leave the
    replica without the write until the next dial. The node now saves one frame at a time, in the order they came."""
    from sessionorc import agent_link
    from sessionorc.agent_link import LinkMixin

    saved: list[dict] = []
    first_started = asyncio.Event()
    release = asyncio.Event()

    async def to_thread(fn, doc, *a, **kw):
        if doc == {"reserves": 30}:  # the dial's frame: its save is slow
            first_started.set()
            await release.wait()
        saved.append(doc)

    monkeypatch.setattr(agent_link.asyncio, "to_thread", to_thread)
    node = SimpleNamespace(mode="node", _settings_take_lock=asyncio.Lock())
    dial = asyncio.ensure_future(LinkMixin._take_settings(node, {"reserves": 30}))
    write = asyncio.ensure_future(LinkMixin._take_settings(node, {"reserves": 40}))
    await first_started.wait()
    await asyncio.sleep(0.05)  # the write's frame would have saved by now, were it not held behind the dial's
    release.set()
    await asyncio.gather(dial, write)
    assert saved == [{"reserves": 30}, {"reserves": 40}], saved  # the replica ends on the newest file
