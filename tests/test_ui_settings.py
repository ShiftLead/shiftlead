"""The Settings page (design §4.5 screen 8, §4.5a *Settings page*; TD-148): the one page that writes a
setting — through the host agent's `set_settings`, never the file — and draws every other configured
value with the file it lives in."""

import html.parser
import json
import pathlib
import re
import shutil
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from conftest import scratch_dir
from fastapi.testclient import TestClient

from shiftlead import profiles as profiles_mod
from shiftlead.ui import settings_page as setmod

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui"
NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


@pytest.fixture
def client(subprocess_agent):
    from shiftlead.ui.app import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.mark.unit
def test_a_reserve_field_takes_what_ao_gate_takes():
    assert setmod.parse_reserve_text("30") == 30
    assert setmod.parse_reserve_text(" 10/day ") == {"per_day": 10}
    assert setmod.parse_reserve_text("") is None and setmod.parse_reserve_text(None) is None
    with pytest.raises(ValueError, match="whole percent"):
        setmod.parse_reserve_text("thirty")
    assert setmod.reserve_text({"per_day": 10}) == "10/day" and setmod.reserve_text(30) == "30"
    assert setmod.reserve_text(None) == ""


@pytest.mark.unit
def test_usage_cards_are_one_per_account_and_draw_each_reported_window():
    """A card per account (§4.5a *Settings page: Usage*, TD-1610): the home's `profiles.yml`'s and each the
    `gate` reply's accounts name, its badge the profiles on it; a row per window its reading reports, with the
    account's reserve as the field takes it and the line it makes today; an account with no reading draws its
    reserves' labels and says they are not checked; a metered account's card carries the home's three
    windows, each an amount with the account's spend beside it; one whose profiles disagree on billing takes
    no reserve; a node's account draws a card from the reply alone."""
    profiles = {
        "grind": profiles_mod.Profile(name="grind", account="paul"),
        "paul": profiles_mod.Profile(name="paul", account="paul"),
        "cold": profiles_mod.Profile(name="cold", account="other"),
        "api": profiles_mod.Profile(name="api", account="key", billing="metered", prices={"input": 3, "output": 15}),
        "sa": profiles_mod.Profile(name="sa", account="split"),
        "sb": profiles_mod.Profile(name="sb", account="split", billing="metered"),
    }
    resets = (NOW + timedelta(days=3, hours=19)).isoformat()
    usage = {
        "grind": {"tool": "claude-code", "account": "paul", "windows": [
            {"label": "5h", "pct": 41, "resets": NOW.isoformat()}, {"label": "week", "pct": 58, "resets": resets}]},
        "paul": {"tool": "claude-code", "account": "paul", "windows": [{"label": "5h", "pct": 41}]},
        "api": {"tool": "claude-code", "account": "key", "windows": [
            {"label": "day", "pct": 64, "resets": resets, "spent": {"total": 9, "cost": 3.2}},
            {"label": "week", "pct": None, "resets": resets, "spent": {"total": 1_200_000, "cost": 9.8}}]},
    }  # fmt: skip
    accounts = {
        "claude-code:paul": {"profiles": ["grind", "paul"], "billing": "subscription",
            "reserves": {"5h": 30, "week": {"per_day": 10}}, "windows": [
            {"label": "5h", "line": 70, "reserve": 30, "resets": None, "next": None},
            {"label": "week", "line": 60, "reserve": {"per_day": 10}, "resets": resets, "next": None}]},
        "claude-code:other": {"profiles": ["cold"], "billing": "subscription", "reserves": {"5h": 20}, "windows": []},
        "claude-code:key": {"profiles": ["api"], "billing": "metered",
            "amounts": {"day": "$5", "week": "2M tok"}, "windows": []},
        "claude-code:split": {"profiles": ["sa", "sb"], "billing": "mixed",
            "billings": {"sa": "subscription", "sb": "metered"}},
        "claude-code:nodeacct": {"profiles": ["np"], "billing": "subscription", "reserves": {}, "windows": []},
    }  # fmt: skip
    cards = {c["account"]: c for c in setmod.usage_cards(profiles, accounts, usage, NOW)}
    assert list(cards) == sorted(accounts)
    paul = cards["claude-code:paul"]
    assert paul["profiles"] == ["grind", "paul"] and paul["badge"] == "grind, paul · claude-code"
    assert [(r["label"], r["value"], r["line"]) for r in paul["rows"]] == [
        ("5h", "30", "→ line 70%"),
        ("week", "10/day", "→ line 60% · 4 days left"),
    ]
    assert paul["rows"][1]["resets"] == resets and not paul["unchecked"]
    cold = cards["claude-code:other"]
    assert cold["rows"] == [{"label": "5h", "value": "20", "line": "no reading yet", "resets": "", "pct": None}]
    assert cold["unchecked"]
    api = cards["claude-code:key"]
    assert api["metered"] and "metered · $3 in / $15 out per M" in api["badge"]
    at = datetime.fromisoformat(resets).astimezone().strftime("%H:%M")
    assert [(r["label"], r["value"], r["line"]) for r in api["rows"]] == [
        ("day", "$5", f"spent $3.20 · 64% · resets {at}"),
        ("week", "2M tok", f"spent 1.2M tok · resets {at}"),
        ("month", "", "no reading yet"),
    ]
    split = cards["claude-code:split"]
    assert split["mixed"] == "sa subscription, sb metered" and split["rows"] == []
    node = cards["claude-code:nodeacct"]
    assert node["profiles"] == ["np"] and node["rows"] == [] and node["unchecked"]
    # with no `gate` reply (an older host agent), the file's accounts still draw, with empty fields
    bare = {c["account"]: c for c in setmod.usage_cards(profiles, None, usage, NOW)}
    assert [r["value"] for r in bare["claude-code:paul"]["rows"]] == ["", ""] and bare["claude-code:split"]["mixed"]
    assert setmod.parse_reserve_text(" $5 ") == "$5" and setmod.parse_reserve_text("20M tok") == "20M tok"


@pytest.mark.unit
def test_a_reserve_on_a_window_the_reading_lacks_is_a_not_reported_row_the_save_clears():
    """An account whose reading reports only `week` but whose `usage_gate:` still holds `5h` (TD-1680): the 5h
    row says the window is not reported, not *no reading yet*, holds no field, and the card's Save sends it as a
    clear beside the fields; an account with no reading keeps *no reading yet*."""
    profiles = {"grind": profiles_mod.Profile(name="grind", account="paul")}
    usage = {"grind": {"tool": "claude-code", "account": "paul", "windows": [{"label": "week", "pct": 58}]}}
    accounts = {
        "claude-code:paul": {"profiles": ["grind"], "billing": "subscription", "reserves": {"5h": 5, "week": 10},
            "windows": [{"label": "week", "line": 90, "reserve": 10, "resets": None, "next": None}]},
    }  # fmt: skip
    (card,) = setmod.usage_cards(profiles, accounts, usage, NOW)
    week, stale = card["rows"]
    assert (week["label"], week["value"], week.get("stale")) == ("week", "10", None)
    assert stale == {
        "label": "5h",
        "value": "5",
        "line": "not reported: claude-code:paul reports week",
        "resets": "",
        "pct": None,
        "stale": True,
    }
    assert not card["unchecked"]
    (cold,) = setmod.usage_cards(profiles, accounts, {}, NOW)
    assert [(r["label"], r["line"], r.get("stale")) for r in cold["rows"]] == [
        ("5h", "no reading yet", None),
        ("week", "no reading yet", None),
    ]
    # the row has no field; the card's Save sends it as a clear, and can be pressed as drawn to send it
    html = (UI / "templates" / "settings.html").read_text()
    assert re.search(r'{% if w.stale %}\s*{#-[^#]*-#}\s*<div class="setrow setstale" data-label="{{ w.label }}">', html)
    stale_row = html.split('class="setrow setstale"', 1)[1].split("</div>", 1)[0]
    assert "<input" not in stale_row  # the Save's clear is run, not read: the next test (TD-1683)


# a DOM just big enough for `AO.settings` over the rendered page: elements parsed from the page's own HTML,
# `querySelector(All)` on descendant selectors of tag, #id, .class and [attr] / [attr='v'] parts
CARD_PROBE = """
const fs = require("fs");
const noop = () => {};
const tree = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const part = (c) => {
  const m = { tag: (c.match(/^[a-z]+/) || [""])[0], id: (c.match(/#([\\w-]+)/) || [])[1],
    cls: [...c.matchAll(/\\.([\\w-]+)/g)].map((x) => x[1]),
    attrs: [...c.matchAll(/\\[([\\w-]+)(?:=['"]?([^'"\\]]*)['"]?)?\\]/g)].map((x) => [x[1], x[2]]) };
  return (e) => (!m.tag || e.tagName.toLowerCase() === m.tag) && (!m.id || e.attrs.id === m.id)
    && m.cls.every((k) => e.cls.includes(k))
    && m.attrs.every(([k, v]) => k in e.attrs && (v === undefined || e.attrs[k] === v));
};
const matches = (e, sel) => {
  const parts = sel.trim().split(/\\s+/).map(part);
  if (!parts.at(-1)(e)) return false;
  let i = parts.length - 2;
  for (let up = e.parentElement; up && i >= 0; up = up.parentElement) if (parts[i](up)) i--;
  return i < 0;
};
const all = (root) => root.children.flatMap((c) => [c, ...all(c)]);
const make = (n, parent) => {
  const e = { tagName: n.tag.toUpperCase(), attrs: n.attrs, cls: (n.attrs.class || "").split(/\\s+/).filter(Boolean),
    parentElement: parent, children: [], textContent: n.text || "", hidden: "hidden" in n.attrs,
    disabled: "disabled" in n.attrs, on: {}, style: {} };
  e.dataset = Object.fromEntries(Object.entries(n.attrs).filter(([k]) => k.startsWith("data-"))
    .map(([k, v]) => [k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase()), v]));
  if ("name" in n.attrs) e.name = n.attrs.name;
  if (e.tagName === "INPUT") {
    e.type = n.attrs.type || "text"; e.value = n.attrs.value || ""; e.defaultValue = e.value;
  }
  if (e.tagName === "BUTTON") e.type = n.attrs.type || "submit";
  e.classList = { contains: (k) => e.cls.includes(k), add: (k) => e.cls.includes(k) || e.cls.push(k),
    remove: (k) => { e.cls = e.cls.filter((x) => x !== k); },
    toggle: (k, on) => (on ? e.classList.add(k) : e.classList.remove(k)) };
  e.addEventListener = (t, f) => { (e.on[t] = e.on[t] || []).push(f); };
  e.setAttribute = (k, v) => { e.attrs[k] = String(v); }; e.getAttribute = (k) => (k in e.attrs ? e.attrs[k] : null);
  e.removeAttribute = (k) => { delete e.attrs[k]; }; e.hasAttribute = (k) => k in e.attrs;
  e.append = e.appendChild = e.replaceChildren = e.prepend = e.before = e.after = e.remove = noop;
  e.querySelectorAll = (sel) => all(e).filter((x) => sel.split(",").some((s) => matches(x, s)));
  e.querySelector = (sel) => e.querySelectorAll(sel)[0] || null;
  e.closest = (sel) => { for (let x = e; x; x = x.parentElement) if (matches(x, sel)) return x; return null; };
  e.children = n.children.map((c) => make(c, e));
  if (e.tagName === "SELECT") {
    e.options = all(e).filter((x) => x.tagName === "OPTION");
    e.options.forEach((o) => { o.value = o.attrs.value ?? o.textContent; o.selected = "selected" in o.attrs; });
    e.value = (e.options.find((o) => o.selected) || e.options[0] || { value: "" }).value;
  }
  if (e.tagName === "TEXTAREA") { e.value = e.textContent; e.defaultValue = e.value; }
  if (e.tagName === "INPUT") e.checked = "checked" in n.attrs;
  if (e.tagName === "FORM") {
    e.elements = all(e).filter((x) => ["INPUT", "SELECT", "TEXTAREA", "BUTTON"].includes(x.tagName));
    e.elements.forEach((x) => { if (x.name && !(x.name in e.elements)) e.elements[x.name] = x; });
  }
  return e;
};
const page = make(tree, null);
const document = { documentElement: page, body: page, addEventListener: noop,
  createElement: () => make({ tag: "div", attrs: {}, children: [] }, null),
  querySelector: (s) => (matches(page, s) ? page : page.querySelector(s)),
  querySelectorAll: (s) => page.querySelectorAll(s), getElementById: (id) => page.querySelector(`#${id}`) };
global.window = { addEventListener: noop, navigator: { userAgent: "" } }; global.document = document;
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/settings", protocol: "http:", host: "x", reload: noop };
const sent = [];
global.fetch = (url, init) => {
  sent.push({ url, body: JSON.parse(init.body) });
  return Promise.resolve({ ok: true, json: async () => ({ ok: true }) });
};
eval(fs.readFileSync(process.argv[2], "utf8"));
window.AO.toast = noop;
window.AO.settings();
const form = page.querySelector("form.setcard[data-section='usage']"), save = form.querySelector(".setsave");
const drawn = save.disabled;
// the press: the browser's submit of the card, which the page's one listener takes
page.on.submit.forEach((h) => h({ target: save, preventDefault: noop }));
setImmediate(() => console.log(JSON.stringify({ disabled: drawn, sent })));
"""


class _Tree(html.parser.HTMLParser):
    """The page's HTML as nested `{tag, attrs, children, text}`, for the probe's DOM."""

    VOID = {"input", "br", "img", "meta", "link", "hr"}

    def __init__(self):
        super().__init__()
        self.root = {"tag": "root", "attrs": {}, "children": []}
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "attrs": {k: v or "" for k, v in attrs}, "children": [], "text": ""}
        self.stack[-1]["children"].append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):  # `<x/>` opens nothing, so it closes nothing
        node = {"tag": tag, "attrs": {k: v or "" for k, v in attrs}, "children": [], "text": ""}
        self.stack[-1]["children"].append(node)

    def handle_endtag(self, tag):
        while len(self.stack) > 1 and self.stack.pop()["tag"] != tag:
            pass

    def handle_data(self, data):
        if len(self.stack) > 1:
            self.stack[-1]["text"] += data


@pytest.mark.unit
def test_the_usage_cards_save_sends_a_stale_rows_clear_as_drawn():
    """TD-1683 (#3481, TD-1680): the card as `settings.html` draws it for an account reporting only `week` with a
    `5h` reserve left, run through `AO.settings` under node: Save is pressable on the untouched card, and its press
    POSTs `/api/settings/usage` with the stale row's window as a clear beside the field's value."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the card's Save is JavaScript, and nothing else runs it")
    from jinja2 import ChainableUndefined

    from shiftlead.ui.app import templates

    profiles = {"grind": profiles_mod.Profile(name="grind", account="paul")}
    usage = {"grind": {"tool": "claude-code", "account": "paul", "windows": [{"label": "week", "pct": 58}]}}
    accounts = {
        "claude-code:paul": {"profiles": ["grind"], "billing": "subscription", "reserves": {"5h": 5, "week": 10},
            "windows": [{"label": "week", "line": 90, "reserve": 10, "resets": None, "next": None}]},
    }  # fmt: skip
    cards = setmod.usage_cards(profiles, accounts, usage, NOW)
    # the page's own template, every value but the cards left empty: the usage card is the one pressed
    page = templates.env.overlay(undefined=ChainableUndefined).get_template("settings.html").render(usage_cards=cards)
    start = page.index('<div class="page inboxpage setpage" id="setpage"')
    tree = _Tree()
    tree.feed(page[start:])
    d = scratch_dir()
    (d / "card.json").write_text(json.dumps(tree.root["children"][0]))
    (d / "card_probe.js").write_text(CARD_PROBE)
    out = subprocess.run(
        [node, str(d / "card_probe.js"), str(UI / "static" / "app.js"), str(d / "card.json")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert got["disabled"] is False  # pressable as drawn: the stale reserve is what it saves
    assert got["sent"] == [
        {"url": "/api/settings/usage", "body": {"account": "claude-code:paul", "reserves": {"5h": "", "week": "10"}}}
    ]


@pytest.mark.unit
def test_a_usage_cards_rows_say_how_old_the_reading_is():
    """design §4.5a *Settings page: Usage*, *The reading's age* (TD-230, TD-233 slice 1): beside each
    window's reading, its age and source as the chip's hover gives them; past three hours, or past
    the window's reset, *unknown since …* with the number it was."""
    profiles = {"grind": profiles_mod.Profile(name="grind", account="paul")}
    later = (NOW + timedelta(days=2)).isoformat()

    def rows(fetched: str, resets: str = later) -> list[dict]:
        usage = {"grind": {"fetched": fetched, "windows": [{"label": "week", "pct": 58, "resets": resets}]}}
        return setmod.usage_cards(profiles, {}, usage, NOW)[0]["rows"]

    assert rows((NOW - timedelta(minutes=7)).isoformat())[0]["age"] == "58% · read 7m ago, asked of the endpoint"
    was = NOW - timedelta(hours=4)
    assert rows(was.isoformat())[0]["age"] == (
        f"unknown since {was.astimezone():%H:%M} (was 58%), asked of the endpoint"
    )
    gone = NOW - timedelta(minutes=30)
    got = rows(NOW.isoformat(), gone.isoformat())[0]["age"]
    assert got == f"unknown since its reset at {gone.astimezone():%H:%M} (was 58%)"
    assert rows("x")[0]["age"] == ""  # no time on the reading: nothing said


@pytest.mark.unit
def test_the_line_text_is_ao_gates():
    row = {"line": 60, "reserve": {"per_day": 10}, "resets": (NOW + timedelta(days=1)).isoformat(), "next": None}
    assert setmod.line_text(row, NOW) == "→ line 60% · 1 day left"
    assert setmod.line_text({"line": None}, NOW) == "no line — the window reports no reset"
    assert setmod.line_text(None, NOW) == "no line"
    assert setmod.line_text({"line": 95, "pct": 99, "unknown": "reset"}, NOW).startswith("unknown since its reset")
    # past `usage.max_age` (TD-233): the projection the gate reads, or why there is none
    pr = {"line": 95, "pct": 96.0, "reserve": 5, "projected": {"from": 88, "rate": 1.3, "age": 21600}}
    assert setmod.line_text(pr, NOW) == "→ line 95% · projected 96%"
    assert setmod.line_text({"line": 95, "pct": 88, "reserve": 5, "unknown": "rate"}, NOW).endswith(
        "no rate to project by"
    )


def test_trust_a_reading_for_writes_usage_max_age(client, subprocess_agent):
    """§4.5a *Settings page: Usage* **trust a reading for** (TD-233): drawn at the hour until set,
    written through `set_settings {usage}`, refused in place out of its bounds, empty clearing it."""
    from sessionorc.client import call_sync

    try:
        assert 'id="setmaxage"' in (page := client.get("/settings").text) and 'name="max_age" value="1h"' in page
        assert client.post("/api/settings/max_age", json={"max_age": "off"}).json()["ok"]
        assert call_sync("settings")["usage"] == {"max_age": "off"}
        page = client.get("/settings").text
        assert 'name="max_age" value="off"' in page and "never project" in page
        bad = client.post("/api/settings/max_age", json={"max_age": "2m"})
        assert bad.status_code == 400 and "from 5m to 7d" in bad.json()["detail"]
    finally:
        assert client.post("/api/settings/max_age", json={"max_age": ""}).json()["ok"]
    assert call_sync("settings")["usage"] == {"max_age": "1h"}


@pytest.mark.unit
def test_read_only_cards_mark_what_the_file_leaves_to_its_default(tmp_path):
    from sessionorc import hosts

    local = hosts.Host(name="kmaster", vscode_host="kmaster", volatile=True)
    card = setmod.host_card({"name": "kmaster", "volatile": True}, local, "kmaster", {"cm": {"container": True}})
    by = {r["key"]: r for r in card["rows"]}
    assert not by["name"]["default"] and by["volatile"]["value"] == "True" and not by["volatile"]["default"]
    assert by["vscode_host"]["default"] and by["runs_keep_days"]["default"] and by["home"]["default"]
    assert by["nodes"]["value"] == "cm (container)"
    (tmp_path / "hosts.yml").write_text("local: {name: kmaster, volatile: true}\nhome: kmaster\n")
    assert setmod.local_entry(tmp_path / "hosts.yml") == {"name": "kmaster", "volatile": True}
    assert setmod.local_entry(tmp_path / "missing.yml") == {}
    prof = setmod.profile_cards({"grind": profiles_mod.Profile(name="grind", account="paul")}, "grind")[0]
    pby = {r["key"]: r for r in prof["rows"]}
    assert prof["default"] and pby["adapter"]["default"] and not pby["account"]["default"]


@pytest.mark.unit
def test_a_repo_card_draws_the_switch_only_where_the_file_carries_promote(tmp_path):
    with_block, without = tmp_path / "a", tmp_path / "b"
    with_block.mkdir(), without.mkdir()
    (with_block / ".shiftlead.yml").write_text("promote:\n  run: make install\n  check: make which\n")
    cards = setmod.repo_cards([str(with_block), str(without)], {"a": {"promote": {"auto": True}}})
    a, b = cards
    assert a["promote"] and a["auto"] and {"promote.run", "promote.check"} <= {r["key"] for r in a["rows"]}
    assert not b["promote"] and not b["exists"] and not b["auto"]
    # **pull** on every card, block or not: on when absent, the home's reading beside it (§6 *Pull*)
    assert a["pull"] and b["pull"] and a["pull_reading"] == b["pull_reading"] == ""
    pulls = {"a": {"outcome": "waiting", "occupant": "main"}, "b": {"outcome": "off"}}
    a, b = setmod.repo_cards([str(with_block), str(without)], {"b": {"pull": False}}, pulls)
    assert a["pull"] and a["pull_reading"] == "waiting: main is mid-turn"
    assert not b["pull"] and b["pull_reading"] == "off"
    # **sync** on every card: on when absent, the repo's last verdict from the repo facts (§6 *Sync*)
    assert a["sync"] and a["sync_reading"] == ""  # no reading of the repo: nothing said
    readings = {str(with_block): {"prs": {"open": []}}, str(without): {"sync": {"3": {"verdict": "merged"}}}}
    a, b = setmod.repo_cards([str(with_block), str(without)], {"b": {"sync": {"auto": False}}}, None, readings)
    assert a["sync"] and a["sync_reading"] == "no sync PR"
    assert not b["sync"] and b["sync_reading"] == "off"


@pytest.mark.unit
def test_the_pull_reading_in_the_designs_words():
    at = (NOW - timedelta(minutes=4)).isoformat()
    assert setmod.pull_reading({"outcome": "pulled", "at": at, "commits": 3}, NOW) == "last pulled 4m ago · 3 commits"
    assert setmod.pull_reading({"outcome": "pulled", "at": at, "commits": 1}, NOW) == "last pulled 4m ago · 1 commit"
    assert setmod.pull_reading({"outcome": "current"}) == "current"
    assert setmod.pull_reading({"outcome": "refused", "why": "on topic"}) == "refused: on topic"
    assert setmod.pull_reading({"outcome": "waiting", "occupant": None}).startswith("waiting: a session here")
    assert setmod.pull_reading(None) == ""


@pytest.mark.unit
def test_the_sync_reading_in_the_designs_words():
    """§4.5a *Settings page: Repos*: the newest verdict by its `at`; *no sync PR* only when the PR
    reading holds none open; an open one with no verdict yet, and a reading that failed, say nothing."""
    at = (NOW - timedelta(minutes=4)).isoformat()
    old = (NOW - timedelta(hours=2)).isoformat()

    def read(sync, *open_):
        return {"sync": sync, "prs": {"open": list(open_)}}

    assert setmod.sync_reading(read({"9": {"verdict": "merged", "at": at}}), True, NOW) == "merged #9 4m ago"
    assert setmod.sync_reading(read({"9": {"verdict": "merged"}}), True, NOW) == "merged #9"  # no `at`: no age
    sync = {"9": {"verdict": "merged", "at": old}, "12": {"verdict": "refused", "why": "forked", "at": at}}
    assert setmod.sync_reading(read(sync), True, NOW) == "#12 refused: forked"
    assert setmod.sync_reading(read({"4": {"verdict": "gate", "why": "ci: red", "at": at}}), True) == "#4 gate: ci: red"
    assert (
        setmod.sync_reading(read({"4": {"verdict": "error", "why": "gh down", "at": at}}), True) == "#4 error: gh down"
    )
    pr = {"number": 4, "sync": True}
    assert setmod.sync_reading(read({"4": {"verdict": "", "tries": 1, "at": at}}, pr), True) == ""  # a retry
    assert setmod.sync_reading(read({"4": {"verdict": "off", "at": at}}, pr), True) == ""  # *off* is no verdict
    assert setmod.sync_reading(read({}, pr), True) == ""  # open, waiting on its checks
    assert setmod.sync_reading(read({}, {"number": 5, "sync": False}), True) == "no sync PR"
    assert setmod.sync_reading({"prs": {"error": "gh down"}}, True) == ""  # an outage is never zero PRs
    assert setmod.sync_reading(None, True) == ""
    assert setmod.sync_reading(read(sync), False) == "off"


@pytest.mark.unit
def test_the_line_preview_is_the_gates_arithmetic():
    """`AO.reserveLine` draws a new line before the press lands (§4.5a *Usage*): the same arithmetic
    as `sessionorc.settings.line`, run as itself under node."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the rule is JavaScript, and nothing else runs it")
    from test_ui_menu import PROBE

    probe = scratch_dir() / "set_probe.js"
    now = int(NOW.timestamp() * 1000)
    resets = (NOW + timedelta(days=3, hours=19)).isoformat()
    head = PROBE[: PROBE.index("const P =")]  # the page's stubs and the eval, without the menu's own probe
    probe.write_text(
        head
        + f"""
const r = (t, at) => window.AO.reserveLine(t, at, {now});
const a = (t) => window.AO.amountSays(t);
console.log(JSON.stringify({{flat: r("30"), day: r("10/day", "{resets}"), none: r(""), bad: r("x"),
  big: r("120"), noreset: r("10/day", ""), usd: a("$5"), tok: a("20M tok"), pct: a("30"), clear: a("")}}));
"""
    )
    out = subprocess.run([node, str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert got["flat"] == {"line": 70, "says": "→ line 70%"}
    assert got["day"] == {"line": 60, "says": "→ line 60% · 4 days left"}
    assert got["none"]["line"] is None and "error" in got["bad"] and "error" in got["big"]
    assert got["noreset"]["says"] == "no line — the window reports no reset"
    assert got["usd"] == {"says": "→ amount $5"} and got["tok"] == {"says": "→ amount 20M tok"}
    assert "not a percent" in got["pct"]["error"] and got["clear"] == {"says": "no amount"}


def test_the_page_draws_every_section_and_the_tab(client, subprocess_agent):
    r = client.get("/settings")
    assert r.status_code == 200
    for sec in ("sec-usage", "sec-teams", "sec-repos", "sec-you", "sec-hosts", "sec-profiles", "sec-org"):
        assert f'id="{sec}"' in r.text
    assert 'id="settingstab"' in r.text and "Reset this browser" in r.text
    assert "settings.yml" in r.text and str(subprocess_agent.home / "hosts.yml") in r.text
    # the tab is on every page, last after Inbox
    org = client.get("/").text
    assert org.index('id="personinbox"') < org.index('id="settingstab"')


@pytest.fixture
def grind_profile(subprocess_agent):
    """A `grind` profile in the agent's `profiles.yml`, so its reserve has an account to be kept under
    (§6 *A reserve is the account's*, TD-1581: `claude-code:paul`); removed after, the agent being shared."""
    from sessionorc import paths

    f = paths.home() / "profiles.yml"
    f.write_text("profiles:\n  grind: {account: paul}\n")
    try:
        yield
    finally:
        f.unlink(missing_ok=True)


def test_a_save_writes_settings_yml_through_set_settings(client, subprocess_agent, grind_profile):
    """Each section's write goes through `set_settings` (§5): a reserve in `ao gate`'s forms, the
    promote switch, the person's editor and terminal — the refusals in the same words, and a team the
    org does not define refused, naming the defined ones."""
    from sessionorc.client import call_sync

    try:
        # an account's card posts its account (TD-1610)
        body = {"account": "claude-code:paul", "reserves": {"5h": "30", "week": "10/day"}}
        ok = client.post("/api/settings/usage", json=body)
        assert ok.status_code == 200 and ok.json()["ok"]
        got = call_sync("settings")["usage_accounts"]["claude-code:paul"]
        assert got["reserves"] == {"5h": 30, "week": {"per_day": 10}}
        page = client.get("/settings").text
        assert 'data-account="claude-code:paul"' in page and "grind · claude-code" in page
        # a page loaded before TD-1610 posts a profile, resolved to its account
        ok = client.post("/api/settings/usage", json={"profile": "grind", "reserves": {"5h": "20"}})
        assert ok.json()["ok"] and call_sync("settings")["usage_accounts"]["claude-code:paul"]["reserves"]["5h"] == 20
        bad = client.post("/api/settings/usage", json={"profile": "grind", "reserves": {"5h": "lots"}})
        assert bad.status_code == 400 and "whole percent" in bad.json()["detail"]
        assert client.post("/api/settings/usage", json={"profile": "grind", "reserves": {"5h": "", "week": ""}}).json()[
            "ok"
        ]

        assert client.post("/api/settings/repos", json={"repo": "shiftlead", "auto": True}).json()["ok"]
        assert call_sync("settings")["repos"]["shiftlead"] == {"promote": {"auto": True}}
        assert client.post("/api/settings/repos", json={"repo": "shiftlead", "auto": "yes"}).status_code == 400
        assert client.post("/api/settings/repos", json={"repo": "shiftlead", "pull": False}).json()["ok"]
        assert call_sync("settings")["repos"]["shiftlead"] == {"promote": {"auto": True}, "pull": False}
        assert client.post("/api/settings/repos", json={"repo": "shiftlead", "pull": "no"}).status_code == 400
        both = {"repo": "shiftlead", "auto": True, "pull": True}  # one switch per press: never half-applied
        assert client.post("/api/settings/repos", json=both).status_code == 400
        assert client.post("/api/settings/repos", json={"repo": "shiftlead", "sync": False}).json()["ok"]
        assert call_sync("settings")["repos"]["shiftlead"]["sync"] == {"auto": False}
        assert client.post("/api/settings/repos", json={"repo": "shiftlead", "sync": "off"}).status_code == 400
        both = {"repo": "shiftlead", "pull": True, "sync": True}
        assert client.post("/api/settings/repos", json=both).status_code == 400

        got = client.post("/api/settings/you", json={"open_in": "none", "terminal": {"size": 15, "face": "Fira Code"}})
        assert got.json()["ok"]
        person = call_sync("settings")["person"]
        assert person == {"open_in": "none", "terminal": {"size": 15, "face": "Fira Code"}}
        assert 'name="copy_on_select" checked' in client.get("/settings").text  # on by default
        page = client.get("/settings").text
        assert 'data-term-size="15"' in page and 'data-term-face="Fira Code"' in page
        refused = client.post("/api/settings/you", json={"open_in": {"label": "x", "url": "javascript://alert(1)"}})
        assert refused.status_code == 400 and "refused" in refused.json()["detail"]
        assert client.post("/api/settings/you", json={"terminal": {"copy_on_select": False}}).json()["ok"]
        assert 'name="copy_on_select">' in client.get("/settings").text  # drawn off, as Focus's toggle is
        assert client.post("/api/settings/you", json={"terminal": {"colour": "red"}}).status_code == 400

        # **board items shown** (§4.5a, TD-220 slice 4): drawn at next:10 until set, written, refused out of range
        page = client.get("/settings").text
        assert (
            'name="board_show" value="next" checked' in page and 'name="board_next"' in page and "due this week" in page
        )
        assert client.post("/api/settings/you", json={"inbox": {"board_show": "14d"}}).json()["ok"]
        assert call_sync("settings")["person"]["inbox"] == {"board_show": "14d"}
        page = client.get("/settings").text
        assert 'name="board_show" value="days" checked' in page and "due within 14 days" in page
        for bad in ("next:0", "next:51", "0d", "soon"):
            assert client.post("/api/settings/you", json={"inbox": {"board_show": bad}}).status_code == 400, bad
        assert client.post("/api/settings/you", json={"inbox": {"colour": "red"}}).status_code == 400
        assert call_sync("settings")["person"]["inbox"] == {"board_show": "14d"}

        # **attachment bound** (§4.5 screen 8, TD-478): the default beside an empty field, written, refused
        # out of 1M–4G in the RPC's words, and an empty Save (`max: null`) back to the default
        page = client.get("/settings").text
        assert 'name="attach_max" value="" placeholder="256M"' in page and "256M by default" in page
        assert client.post("/api/settings/you", json={"attach": {"max": "1G"}}).json()["ok"]
        assert call_sync("settings")["person"]["attach"] == {"max": "1G"}
        assert 'name="attach_max" value="1G"' in client.get("/settings").text
        bad = client.post("/api/settings/you", json={"attach": {"max": "9G"}})
        assert bad.status_code == 400 and "1M to 4G" in bad.json()["detail"]
        assert client.post("/api/settings/you", json={"attach": {"colour": "red"}}).status_code == 400
        assert client.post("/api/settings/you", json={"attach": {"max": None}}).json()["ok"]
        assert "attach" not in call_sync("settings")["person"]

        # **composer** (§4.5a *Focus composer* **the bar**, TD-500): folded until picked, written, refused in words
        assert '<option value="folded" selected>folded</option>' in client.get("/settings").text
        assert client.post("/api/settings/you", json={"composer": "open"}).json()["ok"]
        assert call_sync("settings")["person"]["composer"] == "open"
        assert '<option value="open" selected>always open</option>' in client.get("/settings").text
        bad = client.post("/api/settings/you", json={"composer": "sideways"})
        assert bad.status_code == 400 and "composer is folded or open, not 'sideways'" in bad.json()["detail"]
        assert call_sync("settings")["person"]["composer"] == "open"

        nope = client.post("/api/settings/teams", json={"team": "nobody", "reserve": "10"})
        assert nope.status_code == 400 and "the org defines" in nope.json()["detail"]
    finally:
        call_sync(
            "set_settings",
            person={"open_in": None, "terminal": None, "inbox": None, "attach": None, "composer": None},
            repos={"shiftlead": None},
        )


def test_the_you_card_draws_and_saves_the_file_link_and_a_templates_file(client, subprocess_agent):
    """§4.5a *Settings page: You, file link* (TD-536, built by TD-537): the switch on and one second until
    set, under the editor pick and absent under `none`; written through `set_settings`, the wait refused
    outside 0–4 in its words, the wait input drawn disabled with the switch off; a template's **file** saved
    and a refused one named. The form's own script — what Save posts, the toggles — is `test_ui_settings_you.py`'s."""
    from sessionorc.client import call_sync

    try:
        page = client.get("/settings").text
        assert 'id="setfilelink"' in page and 'class="setfilelink"' in page
        assert 'name="folder_first" title="Has a file link open' in page and re.search(
            r'name="folder_first" title="[^"]*" checked>', page
        )
        assert 'name="wait" type="number" min="0" max="4" step="0.5" value="1">' in page
        assert 'name="file" value=""' in page and "the file link's own form; empty, url with the file's path" in page
        got = client.post("/api/settings/you", json={"file_link": {"folder_first": False, "wait": 2.5}})
        assert got.json()["ok"]
        assert call_sync("settings")["person"]["file_link"] == {"folder_first": False, "wait": 2.5}
        page = client.get("/settings").text
        assert re.search(r'name="folder_first" title="[^"]*">', page)  # drawn unticked
        assert 'value="2.5" disabled>' in page
        bad = client.post("/api/settings/you", json={"file_link": {"wait": 5}})
        assert bad.status_code == 400 and "0 to 4" in bad.json()["detail"]
        assert client.post("/api/settings/you", json={"file_link": {"colour": 1}}).status_code == 400
        # merged field by field (TD-545): a save of the wait alone leaves the switch off, a field set to None
        # clears that field alone
        call_sync("set_settings", person={"file_link": None})
        assert client.post("/api/settings/you", json={"file_link": {"folder_first": False}}).json()["ok"]
        assert client.post("/api/settings/you", json={"file_link": {"wait": 3}}).json()["ok"]
        assert call_sync("settings")["person"]["file_link"] == {"folder_first": False, "wait": 3}
        assert client.post("/api/settings/you", json={"file_link": {"wait": None}}).json()["ok"]
        assert call_sync("settings")["person"]["file_link"] == {"folder_first": False}
        tpl = {"label": "Zed", "url": "zed://ssh/{remote}{path}", "file": "zed://f/{remote}{path}:{line}"}
        assert client.post("/api/settings/you", json={"open_in": tpl}).json()["ok"]
        assert call_sync("settings")["person"]["open_in"] == tpl
        assert 'name="file" value="zed://f/{remote}{path}:{line}"' in client.get("/settings").text
        refused = client.post("/api/settings/you", json={"open_in": {**tpl, "file": "javascript://x{path}"}})
        assert refused.status_code == 400 and "refused" in refused.json()["detail"]
        assert client.post("/api/settings/you", json={"open_in": "none"}).json()["ok"]
        assert 'class="setfilelink hidden"' in client.get("/settings").text
    finally:
        call_sync("set_settings", person={"open_in": None, "file_link": None})


def test_a_team_card_sets_the_stop_time_and_priority(client, subprocess_agent):
    from sessionorc.client import call_sync

    org = subprocess_agent.home / "org.yml"
    org.write_text(
        f"projects:\n  sp:\n    repos:\n      sp: {{kmaster: {subprocess_agent.home}}}\n"
        "teams:\n  sett-team:\n    repo: sp\n    manager: {role: manager}\n"
        "    members: [{role: grinder, count: 2}]\n"
    )
    try:
        page = client.get("/settings").text
        assert 'data-team="sett-team"' in page and "not built — TD-133" not in page
        assert "grinder ×2" in page  # the Org section draws the definition, read-only
        assert client.post("/api/settings/teams", json={"team": "sett-team", "until": "+2h", "reserve": "10"}).json()[
            "ok"
        ]
        t = call_sync("settings")["teams"]["sett-team"]
        assert t["reserve"] == 10 and t["until"].endswith("Z") and not t["passed"]
        assert re.search(r"\+10 on the profile", client.get("/settings").text)
        bad = client.post("/api/settings/teams", json={"team": "sett-team", "until": "soon"})
        assert bad.status_code == 400 and "not a time" in bad.json()["detail"]
        assert client.post("/api/settings/teams", json={"team": "sett-team", "until": None, "reserve": "0"}).json()[
            "ok"
        ]
        assert "sett-team" not in (call_sync("settings")["teams"] or {})
        # **when work appears** (§4.5a, §6 rule 8, TD-227 slice 3): *start the team* is the default while the
        # key is absent (TD-457, TD-466), the pick is written as `on_work`, and anything else is refused
        page = client.get("/settings").text
        assert 'name="on_work" data-was="start"' in page and "start the team (default)" in page
        assert client.post("/api/settings/teams", json={"team": "sett-team", "on_work": "start"}).json()["ok"]
        assert call_sync("settings")["teams"]["sett-team"] == {"on_work": "start"}
        page = client.get("/settings").text
        assert 'data-was="start"' in page and '<option value="start" selected>' in page
        assert "start the team (default)" not in page and "the home starts it" in page
        # the note says all three choices, the picked one first (TD-286)
        note = re.search(r'<span class="note setonwork">([^<]*)</span>', page)[1]
        assert note.startswith("wound down — start the team: the home starts it · ask me: an Inbox row")
        assert note.endswith("do nothing: it waits for Start or its schedule")
        # the definition's file at the card's head, not a foot under Save (TD-286)
        card = page[page.index('data-team="sett-team"') :]
        card = card[: card.index("</form>")]
        assert card.index('defined in <span class="mono">org.yml</span>') < card.index("stop time")
        assert "setfoot" not in card
        bad = client.post("/api/settings/teams", json={"team": "sett-team", "on_work": "maybe"})
        assert bad.status_code == 400 and "ask, start or off" in bad.json()["detail"]
        assert call_sync("settings")["teams"]["sett-team"] == {"on_work": "start"}
    finally:
        org.unlink()
        call_sync("set_settings", teams={"sett-team": None})


def test_every_card_saves_only_a_change_and_cancels_back(client, subprocess_agent):
    """design §4.5a *Settings page* **Save** / **Cancel** (TD-286): every card with fields draws Save
    disabled and Cancel hidden until a field moves, and says the file its values live in; the page's
    script settles them from the form's drawn state and puts the defaults back on Cancel."""
    page = client.get("/settings").text
    forms = re.findall(r'<form class="card pad setcard".*?</form>', page, re.S)
    forms = [f for f in forms if "<input" in f]  # a usage card with no window reported has no field
    assert len(forms) >= 2  # trust a reading for, and You, at the least
    for f in forms:
        assert '<button class="btn sm primary setsave" type="submit" disabled>Save</button>' in f
        assert '<button class="btn sm ghost setcancel" type="button" hidden>Cancel</button>' in f
        assert 'saved to <span class="mono">settings.yml</span>' in f
    js = (UI / "static" / "app.js").read_text()
    assert "f.reset();" in js and "f.dataset.drawn = state(f); settle(f);" in js


def test_a_team_card_draws_balance_and_writes_its_lines_whole(client, subprocess_agent):
    """**balance** (§4.5a *Settings page: Teams*, §6 *Balance*, TD-239 slice 4): off, the key is absent
    and the fields are disabled; a Save writes the lines whole; a field left out is a line not drawn;
    a switch on with no line is refused in place; off removes the key."""
    from sessionorc.client import call_sync

    org = subprocess_agent.home / "org.yml"
    org.write_text(
        f"projects:\n  sp:\n    repos:\n      sp: {{kmaster: {subprocess_agent.home}}}\n"
        "teams:\n  bal-team:\n    repo: sp\n    manager: {role: manager}\n"
        "    members: [{role: grinder, count: 2}]\n"
    )
    post = lambda body: client.post("/api/settings/teams", json={"team": "bal-team", **body})  # noqa: E731
    try:
        page = client.get("/settings").text
        assert 'class="setrow setbalance" data-was="null"' in page
        assert re.search(r'name="balance_prs" value=""[^>]* disabled', page)
        assert "the techlead's queue past its bound</label>" in page  # the seat by its role (TD-428 slice 7)
        assert "no live member: a team with none is not read" in page and "open PRs: could not look (no line)" in page
        assert post({"balance": {"prs": "8", "oldest": "2d", "review": True}}).json()["ok"]
        assert call_sync("settings")["teams"]["bal-team"] == {"balance": {"prs": 8, "oldest": "2d", "review": True}}
        page = client.get("/settings").text
        assert 'data-was="{&#34;prs&#34;:8,&#34;oldest&#34;:&#34;2d&#34;,&#34;review&#34;:true}"' in page
        assert 'name="balance_prs" value="8"' in page and "open PRs: could not look (line 8)" in page
        assert not re.search(r'name="balance_prs"[^>]* disabled', page)
        # an empty field and an unticked box are lines not drawn
        assert post({"balance": {"prs": 3, "oldest": "", "review": False}}).json()["ok"]
        assert call_sync("settings")["teams"]["bal-team"] == {"balance": {"prs": 3}}
        refused = (
            ({}, "at least one line"),
            ({"prs": 0}, "1 or more"),
            ({"prs": "²"}, "balance.prs"),
            ({"prs": "many"}, "balance.prs"),
            ({"oldest": "soon"}, "12h or 2d"),
        )
        for bad, said in refused:
            got = post({"balance": bad})
            assert got.status_code == 400 and said in got.json()["detail"], got.json()
        assert post({"balance": "on"}).status_code == 400
        assert call_sync("settings")["teams"]["bal-team"] == {"balance": {"prs": 3}}
        assert post({"balance": None}).json()["ok"]
        assert "bal-team" not in (call_sync("settings")["teams"] or {})
    finally:
        org.unlink()
        call_sync("set_settings", teams={"bal-team": None})


def test_a_team_card_draws_the_schedule_and_writes_it_whole(client, subprocess_agent):
    """**schedule** (§4.5a *Settings page: Teams*, §6 *Schedule*, TD-1346): off, the key is absent, the
    picks disabled and *no schedule* beside them; a Save writes the rule whole as `ao schedule` does,
    the card then draws it switched on with the *starts* line; a refusal is the RPC's words; off removes it."""
    from sessionorc.client import call_sync

    org = subprocess_agent.home / "org.yml"
    org.write_text(
        f"projects:\n  sp:\n    repos:\n      sp: {{kmaster: {subprocess_agent.home}}}\n"
        "teams:\n  sch-team:\n    repo: sp\n    manager: {role: manager}\n"
        "    members: [{role: grinder, count: 2}]\n"
    )
    post = lambda body: client.post("/api/settings/teams", json={"team": "sch-team", **body})  # noqa: E731
    rule = {"start": "reset", "profile": "grind", "window": "week"}
    try:
        page = client.get("/settings").text
        card = page[page.index('data-team="sch-team"') :]
        card = card[: card.index("</form>")]
        assert (
            'class="setrow setschedule" data-was="null"' in card
            and '<span class="note setstarts">no schedule</span>' in card
        )
        assert re.search(r'name="schedule_on"(?![^>]* checked)', card) and re.search(
            r'name="schedule_profile"[^>]* disabled', card
        )
        assert post({"schedule": rule}).json()["ok"]
        assert call_sync("settings")["teams"]["sch-team"]["schedule"] == rule
        page = client.get("/settings").text
        card = page[page.index('data-team="sch-team"') :]
        card = card[: card.index("</form>")]
        assert (
            'data-was="{&#34;start&#34;:&#34;reset&#34;,&#34;profile&#34;:&#34;grind&#34;,&#34;window&#34;:&#34;week&#34;}"'
            in card
        )
        assert re.search(r'name="schedule_on" checked', card) and "starts at the reset · no reading yet" in card
        assert '<option value="grind" selected>grind (not reported)</option>' in card  # no such profile here
        assert 'name="schedule_window" value="week"' in card  # its label in the text field
        for bad, said in (({**rule, "window": ""}, "window is needed"), ({**rule, "start": "noon"}, "schedule.start")):
            got = post({"schedule": bad})
            assert got.status_code == 400 and said in got.json()["detail"], got.json()
        assert post({"schedule": "on"}).status_code == 400
        assert call_sync("settings")["teams"]["sch-team"]["schedule"] == rule
        assert post({"schedule": None}).json()["ok"]
        assert "sch-team" not in (call_sync("settings")["teams"] or {})
    finally:
        org.unlink()
        call_sync("set_settings", teams={"sch-team": None})


def test_the_settings_page_hands_profiles_yml_to_the_schedule_card(client, subprocess_agent, monkeypatch):
    """The page's wiring (§4.5a *Settings page: Teams*, TD-1346, TD-1351): `profiles.yml` read first, its
    names handed to the `settings` read, whose `labels` reach the schedule card — the window pick lists the
    default profile's labels, a metered profile is a disabled option. The agent here holds no reading, so
    the read answers the labels a reading would, for the names it is given and only when given them."""
    from shiftlead.ui import app as ui

    home = subprocess_agent.home
    (home / "profiles.yml").write_text(
        f"default: grind\nprofiles:\n  grind: {{}}\n  api: {{billing: metered, config_dir: {home / 'api-claude'}}}\n"
    )
    (home / "org.yml").write_text(
        f"projects:\n  sp:\n    repos:\n      sp: {{kmaster: {home}}}\n"
        "teams:\n  sch-team:\n    repo: sp\n    manager: {role: manager}\n"
    )
    real, asked = ui.LocalClient.call, []

    async def call(self, method, **kw):
        got = await real(self, method, **kw)
        if method == "settings" and "profiles" in kw:
            asked.append(kw["profiles"])
            got = {**got, "labels": {p: {"grind": ["5h", "week"]}.get(p, []) for p in kw["profiles"]}}
        return got

    monkeypatch.setattr(ui.LocalClient, "call", call)
    try:
        page = client.get("/settings").text
        assert sorted(asked[-1]) == ["api", "grind"]
        card = page[page.index('data-team="sch-team"') :]
        card = card[: card.index("</form>")]
        assert re.search(r'<option value="grind" selected>grind</option>', card)
        assert re.search(r'<option value="api" disabled title="[^"]+">api</option>', card)
        assert re.search(
            r'name="schedule_window" disabled><option value="5h" selected>5h</option>'
            r'<option value="week">week</option>',
            card,
        ), card
    finally:
        (home / "org.yml").unlink()
        (home / "profiles.yml").unlink()


def test_a_malformed_profiles_yml_is_a_note_on_the_settings_page(client, subprocess_agent):
    """`settings_profiles` (§4.5 *Page loads*, TD-1346, TD-1351): a `profiles.yml` that does not load is
    named on the page, never a 500."""
    bad = subprocess_agent.home / "profiles.yml"
    bad.write_text("default: nobody\nprofiles:\n  grind: {}\n")
    try:
        got = client.get("/settings")
        assert got.status_code == 200
        assert re.search(r'<div class="note warn">profiles\.yml: default [^<]*nobody', got.text), got.text[:2000]
    finally:
        bad.unlink()


def test_schedule_card_offers_the_profiles_and_their_windows():
    """`schedule_card` (TD-1346): every profile offered, a metered one disabled with the reason; the window
    pick is the `labels` the read answered, a text field where none; off, the picks hold the default and its
    first label; a standing rule's profile or label no longer reported is its own option, marked; a standing
    metered rule keeps its own label in a fixed option; every profile metered, the switch cannot turn on."""
    import types

    sub, met = types.SimpleNamespace(billing="subscription"), types.SimpleNamespace(billing="metered")
    profiles = {"grind": sub, "api": met, "fresh": sub}
    labels = {"grind": ["5h", "week"], "fresh": [], "api": ["month"]}
    off = setmod.schedule_card("t", None, profiles, "grind", labels)
    assert off["on"] is False and off["can"] and off["was"] == "null" and off["starts"] == "no schedule"
    assert (off["profile"], off["window"]) == ("grind", "5h")
    assert [(o["name"], o["disabled"]) for o in off["options"]] == [("grind", False), ("api", True), ("fresh", False)]
    assert off["options"][1]["title"] == setmod.SCHEDULE_METERED
    assert json.loads(off["labels"]) == {"grind": ["5h", "week"], "fresh": []}  # never a metered profile's
    assert setmod.schedule_card("t", None, profiles, "api", labels)["profile"] == "grind"  # the default metered
    fresh = setmod.schedule_card(
        "t", {"start": "reset", "profile": "fresh", "window": "week"}, profiles, "grind", labels
    )
    assert fresh["windows"] == [] and fresh["note"] == "no reading of fresh yet — the label is not checked"
    assert fresh["was"] == '{"start":"reset","profile":"fresh","window":"week"}'
    accented = setmod.schedule_card(
        "t", {"start": "reset", "profile": "fresh", "window": "semäne"}, profiles, "", labels
    )
    assert accented["was"] == '{"start":"reset","profile":"fresh","window":"semäne"}'  # as JSON.stringify writes it
    gone = setmod.schedule_card("t", {"start": "reset", "profile": "old", "window": "week"}, profiles, "grind", labels)
    assert gone["options"][-1] == {"name": "old", "disabled": False, "title": "", "mark": " (not reported)"}
    assert gone["profile"] == "old" and gone["windows"] == [] and gone["note"] == ""
    lost = setmod.schedule_card("t", {"start": "reset", "profile": "grind", "window": "day"}, profiles, "grind", labels)
    assert lost["windows"][-1] == {"label": "day", "mark": " (not reported)"} and lost["window"] == "day"
    metered = setmod.schedule_card(
        "t", {"start": "reset", "profile": "api", "window": "spend"}, profiles, "grind", labels
    )
    assert metered["fixed"] and metered["windows"] == [{"label": "spend", "mark": ""}] and metered["profile"] == "api"
    none = setmod.schedule_card("t", None, {"api": met}, "api", labels)
    assert not none["can"] and none["why"] == setmod.SCHEDULE_METERED
    assert setmod.schedule_card("t", None, profiles, "grind", "junk")["windows"] == []  # a malformed read: no labels


@pytest.mark.unit
def test_the_schedule_rows_window_pick_and_save_body():
    """`AO.scheduleWindowPick` and `AO.scheduleBody` (TD-1346), run as themselves under node: a profile
    pick keeps the label the new profile reports, else its first, and a profile with none is a text field
    with its note; the body carries the rule only when it moved from the drawn one, so an unmoved Save of a
    *(not reported)* rule writes nothing, and off is `null`."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the rule is JavaScript, and nothing else runs it")
    from test_ui_menu import PROBE

    probe = scratch_dir() / "sched_probe.js"
    head = PROBE[: PROBE.index("const P =")]
    probe.write_text(
        head
        + """
const W = window.AO.scheduleWindowPick, B = window.AO.scheduleBody;
const held = {grind: ["5h", "week"], other: ["week", "month"], fresh: []};
const was = '{"start":"reset","profile":"old","window":"day"}';
console.log(JSON.stringify({keep: W(held, "other", "week"), first: W(held, "other", "5h"),
  none: W(held, "fresh", "week"), unknown: W(held, "old", "day"), unmoved: B(was, true, "old", "day"),
  moved: B(was, true, "grind", "week"), off: B(was, false, "old", "day"), offnone: B("null", false, "grind", "5h"),
  trimmed: B("null", true, "grind", " week ")}));
"""
    )
    out = subprocess.run([node, str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert got["keep"] == {"labels": ["week", "month"], "value": "week"}
    assert got["first"] == {"labels": ["week", "month"], "value": "week"}
    assert got["none"] == {
        "labels": None,
        "value": "week",
        "note": "no reading of fresh yet — the label is not checked",
    }
    assert got["unknown"]["labels"] is None and got["unknown"]["value"] == "day"
    assert got["unmoved"] == {} and got["offnone"] == {}
    assert got["moved"] == {"schedule": {"start": "reset", "profile": "grind", "window": "week"}}
    assert got["off"] == {"schedule": None}
    assert got["trimmed"] == {"schedule": {"start": "reset", "profile": "grind", "window": "week"}}
    # Cancel after a profile pick: the form's `reset` puts the drawn window control back, which `reset()` cannot
    js = (UI / "static" / "app.js").read_text()
    assert "slot.dataset.drawn = slot.innerHTML;" in js
    assert 'f.addEventListener("reset", () => { slot.innerHTML = slot.dataset.drawn;' in js


def test_balance_card_reads_the_numbers_and_the_mark():
    """The card's own reading (`balance_card`): the form's `was`, the three lines against the repo's
    numbers, and the mark while one stands."""
    now = datetime.now(UTC)
    fleet = [{"id": "g", "team": "t", "state": "idle", "repo": "/r"}]
    open_ = [{"number": n, "created": (now - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")} for n in (1, 2, 3)]
    mark = {"since": "", "repo": "/r", "crossed": [{"line": "prs", "value": 3, "limit": 2}]}
    repos = {"/r": {"prs": {"open": open_}, "balance": {"t": mark}}}
    card = setmod.balance_card("t", {"prs": 2, "review": False}, fleet, repos)
    assert card["on"] and card["was"] == '{"prs":2}' and card["prs"] == "2" and not card["review"]
    assert card["live"] and card["now"][0] == "open PRs: 3 (line 2) — over"
    assert card["now"][1].startswith("oldest PR: 5h") and card["now"][1].endswith("(no line)")
    assert card["mark"] == "over its line: 3 open PRs, line 2"
    off = setmod.balance_card("t", None, fleet, repos)
    assert not off["on"] and off["was"] == "null" and off["mark"] == "" and off["now"][0] == "open PRs: 3 (no line)"
    assert setmod.team_cards({"t": object()}, {"t": {"balance": {"prs": 2}}}, sessions=fleet, repos=repos)[0][
        "balance"
    ]["mark"]
    # a mark with no repo: only the home's `host` read carries it (TD-330)
    bare = {"/r": {"prs": {"open": open_}}}
    assert setmod.balance_card("t", {"prs": 2}, fleet, bare)["mark"] == ""
    host = {"balance": {"t": {**mark, "repo": ""}}}
    assert setmod.balance_card("t", {"prs": 2}, fleet, bare, host)["mark"] == "over its line: 3 open PRs, line 2"
    assert setmod.team_cards({"t": object()}, {"t": {"balance": {"prs": 2}}}, sessions=fleet, repos=bare, host=host)[0][
        "balance"
    ]["mark"]


def test_every_page_draws_the_usage_chip(client, subprocess_agent, monkeypatch):
    """design §4.5a *Sessions top bar* **usage** chip (TD-287): the top bar is one bar, so Settings and the
    other pages draw the account's chip as the Org does, read by one helper."""
    from shiftlead.ui import app as appmod

    reading = {"paul": {"windows": [{"label": "week", "pct": 42, "resets": None}], "fetched": "x", "profiles": []}}

    async def chip(call, sessions=None, **reads):
        return reading

    monkeypatch.setattr(appmod, "chip_usage", chip)
    for path in ("/settings", "/help", "/inbox", "/new"):
        page = client.get(path).text
        assert 'data-account="paul"' in page and "week 42%" in page, path


@pytest.mark.unit
def test_the_chip_reading_fails_quietly():
    """A host agent that cannot answer gives no chip, never a page that fails; one without `gate`
    still gives the reading."""
    import asyncio

    from shiftlead.ui.app import chip_usage

    async def down(method, **kw):
        raise RuntimeError("down")

    async def no_gate(method, **kw):
        if method == "gate":
            raise RuntimeError("unknown method")
        return [] if method == "list" else {}

    assert asyncio.run(chip_usage(down)) == {}
    assert asyncio.run(chip_usage(no_gate)) == {}


@pytest.mark.unit
def test_a_hidden_button_is_not_drawn_whatever_its_class_sets():
    """TD-296 #2: Settings' **Cancel** carries `hidden` until a field changes, but `.btn` sets
    `display: inline-flex`, which beats the UA's `[hidden] { display: none }`, so it showed always
    and pushed Save to its own line on a narrow card. `.btn[hidden]` puts it back."""
    css = (pathlib.Path(__file__).parents[1] / "src/shiftlead/ui/static/app.css").read_text()
    assert ".btn[hidden] { display: none; }" in css
    html = (pathlib.Path(__file__).parents[1] / "src/shiftlead/ui/templates/settings.html").read_text()
    assert 'class="btn sm ghost setcancel" type="button" hidden' in html


@pytest.mark.unit
def test_the_telegram_card_reads_the_setting_and_the_last_send():
    """**You**: **Telegram** (§4.5a, §4.10; TD-319 slice 3): the switch, the secrets' name and the link as
    `notify.telegram` keeps them, and the later of the home's last send and last failure in its words."""
    off = setmod.telegram(None, None, NOW)
    assert off["on"] is False and off["secrets"] == "" and off["link"] == "" and off["last"] == ""
    assert "a blocked outcome" in off["told"] and "no text a session wrote is sent" in off["when"]
    tg = {"telegram": {"on": True, "secrets": "samscrape/prd", "link": "http://kmaster:8765"}}
    at = (NOW - timedelta(minutes=3)).isoformat()
    got = setmod.telegram(tg, {"last_ok": at}, NOW)
    assert (got["on"], got["secrets"], got["link"]) == (True, "samscrape/prd", "http://kmaster:8765")
    assert got["last"].startswith("last sent ") and not got["last_failed"]
    later = (NOW - timedelta(minutes=1)).isoformat()
    bad = setmod.telegram(tg, {"last_ok": at, "last_error": {"at": later, "reason": "doppler: not logged in"}}, NOW)
    assert (
        bad["last_failed"] and bad["last"].startswith("last send failed ") and "doppler: not logged in" in bad["last"]
    )
    # a send after the failure is the line again
    assert not setmod.telegram(tg, {"last_ok": later, "last_error": {"at": at, "reason": "x"}}, NOW)["last_failed"]


@pytest.mark.unit
def test_the_telegram_links_placeholder_is_the_route_else_localhost():
    """TD-648 (§4.5b *The setting*): an empty link sends `reach.url`, so the placeholder shows it; with no
    route it is the plain port a browser on the home reaches — never `http://<host>:8765`, which a
    loopback plain port refuses."""
    assert setmod.telegram(None, None, NOW)["link_placeholder"] == ""
    got = setmod.telegram(None, None, NOW, reach={"route": "tailscale", "url": "https://home.tail1.ts.net"})
    assert got["link_placeholder"] == "https://home.tail1.ts.net"
    page = pathlib.Path(setmod.__file__).parent / "templates" / "settings.html"
    assert "placeholder=\"{{ telegram.link_placeholder or 'http://localhost:8765' }}\"" in page.read_text()


def test_the_telegram_card_saves_through_set_settings_and_sends_a_test(client, subprocess_agent):
    """**Save** writes `notify.telegram` through `set_settings` — an empty field cleared, `on` with no
    secrets refused in the RPC's words — and **Send a test** is `notify_test`'s answer, refused while no
    secrets are saved (§4.10; TD-319 slice 3)."""
    from sessionorc.client import call_sync

    try:
        page = client.get("/settings").text
        assert 'id="settelegram"' in page and 'name="tg_on" ' in page and "Send a test" in page
        assert 'name="tg_on" title="Has the home send you one Telegram message' in page
        no = client.post("/api/settings/notify", json={"telegram": {"on": True, "secrets": "", "link": ""}})
        assert no.status_code == 400 and "secrets" in no.json()["detail"]
        test = client.post("/api/settings/notify_test", json={})
        assert test.status_code == 400 and "secrets is not set" in test.json()["detail"]
        body = {"telegram": {"on": False, "secrets": "look/dev", "link": "http://127.0.0.1:1/"}}
        assert client.post("/api/settings/notify", json=body).json()["ok"]
        assert call_sync("settings")["notify"] == {
            "telegram": {"on": False, "secrets": "look/dev", "link": "http://127.0.0.1:1"}
        }
        page = client.get("/settings").text
        assert 'name="tg_secrets" value="look/dev"' in page and 'name="tg_on" title=' in page
        assert client.post("/api/settings/notify", json={"telegram": {"link": ""}}).json()["ok"]
        assert call_sync("settings")["notify"] == {"telegram": {"on": False, "secrets": "look/dev"}}
        bad = client.post("/api/settings/notify", json={"telegram": {"link": "ftp://x"}})
        assert bad.status_code == 400 and "http://" in bad.json()["detail"]
        assert client.post("/api/settings/notify", json={"telegram": {"token": "x"}}).status_code == 400
    finally:
        call_sync("set_settings", notify={"telegram": None})


@pytest.mark.unit
def test_a_telegram_rows_key_is_the_inboxs_row():
    """`/inbox?row=<key>` (§4.10, TD-319 slice 3): the home's key, `<session>|<kind>` or `work:<team>`, is
    the page's `data-msg` — `<session>:<kind>`, `work:<team>` as it is — by `AO.rowOfKey`, run under node."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the rule is JavaScript, and nothing else runs it")
    from test_ui_menu import PROBE

    probe = scratch_dir() / "row_probe.js"
    head = PROBE[: PROBE.index("const P =")]
    probe.write_text(
        head
        + """
const k = (x) => window.AO.rowOfKey(x);
console.log(JSON.stringify([k("ao-x-1|permission"), k("ao-x-1|alarm"), k("work:ao-grind"), k(""), k(null)]));
"""
    )
    out = subprocess.run([node, str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert got == ["ao-x-1:permission", "ao-x-1:alarm", "work:ao-grind", "", ""]


def test_a_malformed_permissions_rule_is_named_where_the_page_shows_settings_yml(client, subprocess_agent):
    """§4.9b *The person's written rules* (TD-641): a `permissions:` value the host refuses — read
    through the agent's `settings` read, never the file — is named on the settings.yml card as
    ignored; a well-formed one is not named."""
    f = subprocess_agent.home / "settings.yml"
    was = f.read_text() if f.exists() else None
    try:
        f.write_text('permissions:\n  grinder: {allow: ["Bash(ls:*)", 7], deny: "rm"}\n')
        page = client.get("/settings").text
        bad = re.findall(r'<div class="note warn permbad">([^<]*)</div>', page)
        assert len(bad) == 2 and all("— ignored: no prompt is answered by it" in b for b in bad)
        assert any("permissions.grinder.allow" in b for b in bad) and any("permissions.grinder.deny" in b for b in bad)
        assert "Bash(ls" not in " ".join(bad)  # the good rule beside them is not named
        f.write_text('permissions:\n  grinder: {allow: ["Bash(ls:*)"]}\n')
        assert "permbad" not in client.get("/settings").text.split('id="sec-settingsfile"')[1]
    finally:  # the module's agent outlives this test: its file is put back
        f.write_text(was) if was is not None else f.unlink(missing_ok=True)


@pytest.mark.unit
def test_the_ledger_row_says_the_resolved_ledger_and_whether_the_file_set_it(tmp_path):
    """§4.4 *Either layout*, TD-1146: the row shows the ledger as found — *docs/ledger (directory)* for a v2
    checkout, the file for a v1 one — marked default while `.shiftlead.yml` sets no `ledger:`."""
    v1, v2 = tmp_path / "v1", tmp_path / "v2"
    v1.mkdir()
    (v2 / "docs" / "ledger").mkdir(parents=True)
    a, b = ({r["key"]: r for r in c["rows"]}["ledger"] for c in setmod.repo_cards([str(v1), str(v2)], {}))
    assert a == {"key": "ledger", "value": "docs/technical_debt.md", "default": True}
    assert b == {"key": "ledger", "value": "docs/ledger (directory)", "default": True}
    (v1 / ".shiftlead.yml").write_text("ledger: docs/technical_debt.md\n")
    (a,) = ({r["key"]: r for r in c["rows"]}["ledger"] for c in setmod.repo_cards([str(v1)], {}))
    assert a == {"key": "ledger", "value": "docs/technical_debt.md", "default": False}
