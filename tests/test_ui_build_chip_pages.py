"""TD-549: design §4.5a top bar **build** chip (TD-539) is on every page. `base.html` draws an empty,
hidden span when a page's context holds no `build_chip`, so a handler that forgets the key still has
`id="buildchip"`: each page here is read with `chip_build` answering a chip no other code writes, and
the walk over the templates says no page that extends `base.html` was left out."""

from __future__ import annotations

import pathlib
import re

import pytest
from test_ui import client  # noqa: F401 — the fixture, by name
from test_ui_entry import client as entry_client
from test_ui_entry import fake, world
from test_ui_inbox import send, sender_session

from shiftlead.ui import app as uiapp

UI = pathlib.Path(__file__).resolve().parents[1] / "src" / "shiftlead" / "ui"
CHIP = {"text": "live 10-10 15:41 · main +7", "title": "td549", "cls": "behind", "at": "", "rest": ""}
DRAWN = '<span class="mono behind" id="buildchip" title="td549">live 10-10 15:41 · main +7</span>'

# each template that extends base.html, and the page that renders it
PAGES = {
    "org.html": "/",
    "inbox.html": "/inbox",
    "inbox_entry.html": "/inbox/{mid}",
    "focus.html": "/focus/{sid}",
    "transcript.html": "/transcript/{sid}",
    "new.html": "/new",
    "help.html": "/help",
    "settings.html": "/settings",
    "repo.html": "/repo/samscrape",
}


def _chip(monkeypatch):
    async def chip(call, info=None):
        return CHIP

    monkeypatch.setattr(uiapp, "chip_build", chip)


@pytest.mark.unit
def test_the_list_names_every_template_that_extends_base():
    extends = {
        p.name for p in (UI / "templates").glob("*.html") if re.search(r'{%\s*extends "base.html"', p.read_text())
    }
    assert extends == set(PAGES)


@pytest.mark.integration
def test_every_page_on_the_host_agent_draws_the_chip_its_handler_read(client, tmp_path, monkeypatch):  # noqa: F811
    _chip(monkeypatch)
    sid = sender_session(client, tmp_path, name="chip")
    mid = send(sid, text="merge #9?", kind="ask")["id"]
    try:
        for template, path in PAGES.items():
            if template == "repo.html":
                continue  # a registered repo: the next test
            got = client.get(path.format(sid=sid, mid=mid))
            assert got.status_code == 200, path
            assert DRAWN in got.text, path
    finally:
        client.post(f"/api/sessions/{sid}/kill")


@pytest.mark.unit
def test_the_repo_page_draws_the_chip_its_handler_read(tmp_path, monkeypatch):
    repo = world(tmp_path)
    root = str(repo)
    reading = {"name": "samscrape", "root": root, "ledger": {"path": "docs/technical_debt.md", "entries": []}}

    class Fake(fake([])):
        async def call(self, method, **kw):
            if method == "repos":
                return {root: reading}
            return await super().call(method, **kw)

    _chip(monkeypatch)
    got = entry_client(monkeypatch, tmp_path, Fake).get(PAGES["repo.html"])
    assert got.status_code == 200 and DRAWN in got.text
