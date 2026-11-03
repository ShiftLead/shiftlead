"""The Settings page's **Push** card and `/sw.js` (design §4.5a **You**: **Push**, §4.10 *Told on the home-screen
app too*; TD-1305): the card's server half as `settings_page.push_card` draws it, its routes against a scratch
agent, and the browser half — the page's checks and the service worker — run under node with stubbed APIs."""

import json
import pathlib
import shutil
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from conftest import scratch_dir
from fastapi.testclient import TestClient

from sessionorc import push as push_mod
from shiftlead.ui import settings_page as setmod

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui"
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
PUB = "BP" + "A" * 85  # a P-256 public key's length in base64url; the home compares it as bytes
SUB_KEYS = {"p256dh": "B" + "A" * 86, "auth": "A" * 22}


@pytest.fixture
def client(subprocess_agent):
    from shiftlead.ui.app import create_app

    with TestClient(create_app()) as c:
        yield c


def _node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the rule is JavaScript, and nothing else runs it")
    return node


def _run(node, script: str, *args: str):
    probe = scratch_dir() / f"push_probe_{abs(hash(script))}.js"
    probe.write_text(script)
    out = subprocess.run([node, str(probe), *args], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


# -- the server half ---------------------------------------------------------------------------------------


@pytest.mark.unit
def test_the_switchs_line_is_the_keys_reading_in_the_designs_order():
    """§4.5a **Push**: *set secrets first* while neither config is set (no **Make key**), then *reading the
    key…*, *make the key first* with **Make key**, *the key could not be read: <why>*, and no line on *key* —
    the only reading that hands the page a public key to subscribe with."""
    tg = {"telegram": {"secrets": "samscrape/prd"}}
    none = setmod.push_card(None, {"key": "no key"}, NOW)
    assert (none["block"], none["make"]) == ("set secrets first", False)
    assert setmod.push_card(tg, {}, NOW)["block"] == "reading the key…"
    made = setmod.push_card(tg, {"key": "no key"}, NOW)
    assert (made["block"], made["make"], made["secrets"], made["tg_secrets"]) == (
        "make the key first",
        True,
        "",
        "samscrape/prd",
    )
    bad = setmod.push_card(tg, {"key": "unreadable: doppler: not logged in", "public_key": PUB}, NOW)
    assert bad["block"] == "the key could not be read: doppler: not logged in" and bad["public_key"] == ""
    ok = setmod.push_card({"push": {"secrets": "look/dev"}}, {"key": "key", "public_key": PUB}, NOW)
    assert (ok["block"], ok["public_key"], ok["make"]) == ("", PUB, False)


@pytest.mark.unit
def test_the_cards_settings_read_their_defaults():
    """**on all devices** is on when absent, **with Telegram** *both* when absent or unreadable, and the https
    address is offered only when the route is one."""
    got = setmod.push_card(None, None, NOW, reach={"url": "http://kmaster:8765"})
    assert (got["on"], got["telegram"], got["tg_on"], got["https"]) == (True, "both", False, "")
    n = {"push": {"on": False, "telegram": "fallback"}, "telegram": {"on": True}}
    got = setmod.push_card(n, None, NOW, reach={"url": "https://home.tail1.ts.net"})
    assert (got["on"], got["telegram"], got["tg_on"], got["https"]) == (
        False,
        "fallback",
        True,
        "https://home.tail1.ts.net",
    )
    assert setmod.push_card({"push": {"telegram": "never"}}, None, NOW)["telegram"] == "both"


@pytest.mark.unit
def test_each_devices_line_and_the_paused_line():
    """A device's line: its label, *since <date>*, *last told 14:02* or *last failed 14:02: <status>* — the later
    of the two — with the date in front once a day old; *push is paused: <reading>* while the key is gone with
    devices listed, and a `last_line` that says the same is not drawn twice."""
    at = (NOW - timedelta(minutes=5)).isoformat()
    later = (NOW - timedelta(minutes=1)).isoformat()
    old = (NOW - timedelta(days=3)).isoformat()
    devices = [
        {"id": "a" * 16, "label": "iPhone · Safari", "since": old, "last_ok": at},
        {"id": "b" * 16, "label": "", "since": old, "last_ok": at, "last_error": {"at": later, "reason": "410"}},
        {"id": "c" * 16, "since": old, "last_ok": old},
        {"label": "no id: not drawn"},
    ]
    got = setmod.push_card(None, {"key": "key", "public_key": PUB, "devices": devices}, NOW)
    lines = [(d["label"], d["last"].split(" ")[:2], d["failed"]) for d in got["devices"]]
    assert lines == [
        ("iPhone · Safari", ["last", "told"], False),
        ("a device", ["last", "failed"], True),
        ("a device", ["last", "told"], False),
    ]
    assert got["devices"][1]["last"].endswith(": 410")
    assert ":" in got["devices"][0]["last"] and len(got["devices"][0]["last"]) == len("last told 14:02")
    assert len(got["devices"][2]["last"]) > len("last told 14:02")  # a day old: the date in front
    assert all(d["since"] for d in got["devices"]) and got["paused"] == ""
    gone = {"key": "no key", "devices": devices, "last_line": "push is paused: no key"}
    paused = setmod.push_card({"push": {"secrets": "look/dev"}}, gone, NOW)
    assert paused["paused"] == "push is paused: no key" and paused["last_line"] == ""
    changed = {"key": "key", "public_key": PUB, "last_line": push_mod.KEY_CHANGED}
    assert setmod.push_card(None, changed, NOW)["last_line"] == push_mod.KEY_CHANGED


@pytest.mark.unit
def test_on_a_node_the_card_is_one_line_pointing_at_the_home():
    """The card is the home's: on a node it says *turn this on from <home>'s page* and nothing else."""
    from jinja2 import Environment, FileSystemLoader

    page = (UI / "templates" / "settings.html").read_text()
    part = page[page.index("{% if push.node %}") : page.index('<div class="card pad setcard" id="setbrowser">')]
    env = Environment(loader=FileSystemLoader(str(UI / "templates")), autoescape=True)
    node = env.from_string(part).render(push=setmod.push_card(None, None, NOW, node=True, home="kmaster"))
    assert "turn this on from kmaster’s page" in node and "setpushme" not in node and "Make key" not in node


def test_the_worker_is_served_at_the_root_and_never_cached(client):
    """`/sw.js` (§4.10 *The service worker*): at the root, so its scope is the app; `no-cache`, so a new worker
    is taken on the next load; JavaScript, which a browser requires of a worker."""
    got = client.get("/sw.js")
    assert got.status_code == 200 and got.headers["cache-control"] == "no-cache"
    assert got.headers["content-type"].startswith("text/javascript") and "pushsubscriptionchange" in got.text
    assert 'addEventListener("fetch"' not in got.text and "caches." not in got.text


def test_the_card_saves_and_its_switch_lands_through_the_home(client, subprocess_agent):
    """**Save** writes `notify.push` through `set_settings`, an empty secrets cleared and a bad value refused in
    the RPC's words; the switch's `push_subscribe` lists the device the card then draws, a subscription made
    under another key refused; **Remove** is `push_unsubscribe`; **Send a test to this device** is
    `notify_test {channel: push, device}`."""
    from sessionorc.client import call_sync

    f = subprocess_agent.home / "push.json"
    try:
        page = client.get("/settings").text
        assert (
            'id="setpush"' in page and 'data-block="set secrets first"' in page and "Send a test to this device" in page
        )
        assert client.post("/api/settings/push", json={"token": "x"}).status_code == 400
        bad = client.post("/api/settings/push", json={"telegram": "never"})
        assert bad.status_code == 400 and "both or fallback" in bad.json()["detail"]
        body = {"on": False, "telegram": "fallback", "secrets": "look/dev"}
        assert client.post("/api/settings/push", json=body).json()["ok"]
        assert call_sync("settings")["notify"]["push"] == body
        page = client.get("/settings").text
        assert 'name="push_secrets" value="look/dev"' in page and '<option value="fallback" selected>' in page
        assert client.post("/api/settings/push", json={"secrets": ""}).json()["ok"]
        assert "secrets" not in call_sync("settings")["notify"]["push"]

        push_mod.save({"key": "key", "public_key": PUB, "devices": []}, f)
        ep = "https://fcm.googleapis.com/fcm/send/abc"
        sub = {"endpoint": ep, "keys": SUB_KEYS, "label": "Linux · Firefox"}
        other = client.post("/api/settings/push_subscribe", json={**sub, "key": "BQ" + "A" * 85})
        assert other.status_code == 400 and "a key this home does not hold" in other.json()["detail"]
        got = client.post("/api/settings/push_subscribe", json={**sub, "key": PUB}).json()
        assert got["id"] == push_mod.device_id(ep)
        page = client.get("/settings").text
        assert f'data-id="{got["id"]}" data-label="Linux · Firefox"' in page and f'data-key="{PUB}"' in page
        assert client.post("/api/settings/push", json={"secrets": "look/dev"}).json()["ok"]
        test = client.post("/api/settings/notify_test", json={"channel": "push", "device": "f" * 16})
        # push's own refusals, never Telegram's: the device not listed, or the key being read again after the save
        assert test.status_code == 400 and (
            "no device 'ffffffffffffffff' is listed" in (why := test.json()["detail"]) or "reading the key" in why
        )
        assert client.post("/api/settings/push", json={"secrets": ""}).json()["ok"]
        removed = client.post("/api/settings/push_unsubscribe", json={"id": got["id"]}).json()
        assert removed["removed"] is True and push_mod.load(f)["devices"] == []
        made = client.post("/api/settings/push_key", json={})
        assert made.status_code == 400 and "notify.push.secrets" in made.json()["detail"]
    finally:
        call_sync("set_settings", notify={"push": None})
        f.unlink(missing_ok=True)


# -- the browser half, under node --------------------------------------------------------------------------

PAGE = """
const fs = require("fs");
const noop = () => {};
const el = () => ({ dataset: {}, style: {}, addEventListener: noop, appendChild: noop,
  classList: { toggle: noop, add: noop, remove: noop, contains: () => false },
  querySelector: () => null, querySelectorAll: () => [] });
global.window = {}; global.document = { documentElement: el(), body: el(), querySelector: () => null,
  querySelectorAll: () => [], addEventListener: noop, createElement: el };
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const P = window.AO.push;
const IPHONE = (v) => "Mozilla/5.0 (iPhone; CPU iPhone OS " + v + " like Mac OS X) AppleWebKit/605.1.15"
  + " (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";
const LINUX = "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0";
const w = (o) => {
  const nav = { userAgent: o.ua || LINUX, platform: "Linux", maxTouchPoints: 0, standalone: o.standalone };
  if (o.sw !== false) nav.serviceWorker = {};
  const win = { isSecureContext: o.secure !== false, navigator: nav, matchMedia: () => ({ matches: !!o.standalone }) };
  if (o.push !== false) { win.PushManager = function () {}; win.Notification = { permission: o.perm || "default" }; }
  return win;
};
const line = (b) => b && (b.href ? b.text + b.href : b.text);
(async () => {
  console.log(JSON.stringify({
    http_routed: line(P.browserBlock(w({ secure: false }), "https://home.ts.net")),
    http: line(P.browserBlock(w({ secure: false }), "")),
    old_ios: line(P.browserBlock(w({ ua: IPHONE("16_3") }), "")),
    safari_tab: line(P.browserBlock(w({ ua: IPHONE("17_1") }), "")),
    home_screen: line(P.browserBlock(w({ ua: IPHONE("17_1"), standalone: true }), "")),
    no_push: line(P.browserBlock(w({ push: false }), "")),
    denied: line(P.browserBlock(w({ perm: "denied" }), "")),
    fine: line(P.browserBlock(w({}), "")),
    id: await P.deviceId("https://fcm.googleapis.com/fcm/send/abc"),
    labels: [P.labelOf(IPHONE("17_1")), P.labelOf(LINUX), P.labelOf("curl/8")],
    round: P.b64url(P.fromB64url("BPAq-_80")),
  }));
})();
"""


@pytest.mark.unit
def test_the_pages_checks_tell_each_case_before_any_browser_call():
    """§4.5a **Push**'s disabled cases the browser tells, in order — not a secure context (with the https
    address as a link where the route has one), iOS below 16.4, an iPhone's Safari tab, a browser without
    push, notifications blocked — each read from `window` alone; and the device id the page works out is the
    home's (`push.device_id`)."""
    got = _run(_node(), PAGE, str(UI / "static" / "app.js"))
    assert got["http_routed"] == "needs the https address — open https://home.ts.net"
    assert got["http"] == "needs HTTPS: ao connect tailscale"
    assert got["old_ios"] == "needs iOS 16.4 or later"
    assert got["safari_tab"].startswith("add shiftlead to the home screen first (Share → Add to Home Screen)")
    assert got["home_screen"] is None and got["fine"] is None
    assert got["no_push"] == "this browser cannot take push"
    assert got["denied"] == "notifications are blocked for this site in the browser’s settings"
    assert got["id"] == push_mod.device_id("https://fcm.googleapis.com/fcm/send/abc")
    assert got["labels"] == ["iPhone · Safari", "Linux · Firefox", "a device"]
    assert got["round"] == "BPAq-_80"


WORKER = """
const fs = require("fs");
const on = {}, shown = [], posted = [], wins = [], opened = [];
const sub = (endpoint) => ({ endpoint, toJSON: () => ({ endpoint, keys: { p256dh: "p", auth: "a" } }) });
global.self = {
  location: { href: "https://home.ts.net/sw.js?k=BPAq", origin: "https://home.ts.net" },
  navigator: { userAgent: "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0" },
  addEventListener: (k, f) => { on[k] = f; },
  registration: {
    showNotification: async (title, o) => { shown.push({ title, ...o }); },
    pushManager: { subscribe: async (o) => sub("https://fcm.googleapis.com/new") },
  },
  clients: { matchAll: async () => wins, openWindow: async (u) => { opened.push(u); } },
};
global.fetch = async (u, o) => { posted.push([u, JSON.parse(o.body)]); return { ok: true }; };
eval(fs.readFileSync(process.argv[2], "utf8"));
const fire = async (k, ev) => { let p; ev.waitUntil = (x) => { p = x; }; on[k](ev); await p; };
const data = (v) => ({ json: () => (typeof v === "string" ? JSON.parse(v) : v) });
(async () => {
  await fire("push", { data: data({ body: "grinder-ao-2 asks: which key?", path: "/inbox?row=x", tag: "ao-x|ask" }) });
  await fire("push", { data: null });
  await fire("push", { data: data("not json") });
  await fire("push", { data: data({ body: "no tag", path: "/inbox" }) });
  await fire("push", { data: data({ body: "b", path: "https://evil.example/", tag: "t" }) });
  await fire("push", { data: data({ body: "b", path: "//evil.example/", tag: "t" }) });
  await fire("push", { data: data({ body: "b", path: "/\\\\evil.example/", tag: "t" }) });
  await fire("push", { data: data({ body: "b", path: "/\\t/evil.example/", tag: "t" }) });
  await fire("push", { data: data({ body: "b", path: "/\\n/evil.example/", tag: "t" }) });
  const click = (path) => ({ notification: { close: () => {}, data: { path } } });
  await fire("notificationclick", click("/inbox?row=x"));
  const nav = [];
  wins.push({ url: "https://other.example/", focus: async () => nav.push("wrong"), navigate: async () => {} });
  wins.push({ url: "https://home.ts.net/settings", focus: async () => nav.push("focus"),
    navigate: async (u) => nav.push(u) });
  await fire("notificationclick", click("/inbox?row=y"));
  const F = "https://fcm.googleapis.com/";
  await fire("pushsubscriptionchange", { oldSubscription: sub(F + "old"), newSubscription: null });
  await fire("pushsubscriptionchange", { oldSubscription: null, newSubscription: sub(F + "n2") });
  console.log(JSON.stringify({ shown, opened, nav, posted, old: await self.__ao.deviceId(F + "old") }));
})();
"""


@pytest.mark.unit
def test_the_worker_draws_every_push_opens_its_row_and_subscribes_again():
    """§4.10 *The service worker*: a push is always drawn — absent, not JSON or missing a field, as *something
    needs you* at `/inbox` under the tag `more`, and never a path off the app; a tap focuses an open window of
    the app and navigates it, or opens one; `pushsubscriptionchange` subscribes again with its key and posts
    `push_subscribe`, naming the old device in `replaces` when the browser still says which it was."""
    got = _run(_node(), WORKER, str(UI / "static" / "sw.js"))
    first = got["shown"][0]
    assert (first["title"], first["body"], first["tag"], first["data"]) == (
        "shiftlead",
        "grinder-ao-2 asks: which key?",
        "ao-x|ask",
        {"path": "/inbox?row=x"},
    )
    assert first["icon"].endswith("192.png") and (UI / "static" / first["icon"].removeprefix("/static/")).is_file()
    fallback = [(s["body"], s["tag"], s["data"]["path"]) for s in got["shown"][1:4]]
    assert fallback == [("something needs you", "more", "/inbox")] * 3
    assert [s["data"]["path"] for s in got["shown"][4:9]] == ["/inbox"] * 5  # never a page off the app
    assert got["opened"] == ["https://home.ts.net/inbox?row=x"]
    assert got["nav"] == ["focus", "https://home.ts.net/inbox?row=y"]
    (u1, b1), (u2, b2) = got["posted"]
    assert u1 == u2 == "/api/settings/push_subscribe"
    assert (
        b1["endpoint"] == "https://fcm.googleapis.com/new" and b1["key"] == "BPAq" and b1["label"] == "Linux · Firefox"
    )
    assert b1["replaces"] == got["old"] == push_mod.device_id("https://fcm.googleapis.com/old")
    assert b2["endpoint"] == "https://fcm.googleapis.com/n2" and "replaces" not in b2


CARD = """
const fs = require("fs");
const noop = () => {};
const log = [];
const store = {};
const node = (extra) => {
  const on = {};
  return Object.assign({ dataset: {}, hidden: false, disabled: false, checked: false, textContent: "",
    classList: { toggle: noop, add: noop, remove: noop, contains: () => false }, append: noop,
    addEventListener: (k, f) => { on[k] = f; }, fire: (k, e) => on[k](e || {}),
    querySelector: () => null, querySelectorAll: () => [] }, extra || {});
};
const ENDPOINT = "https://fcm.googleapis.com/fcm/send/mine";
let sub = { endpoint: ENDPOINT, unsubscribe: async () => { log.push("browser unsubscribe"); return true; } };
const parts = { ".setpushme": node(), ".setpushwhy": node({ textContent: "checking this browser…" }),
  ".setpushtest": node(), ".setpushsaid": node(), ".setpushtgline": node() };
const row = (id) => { const r = node({ dataset: { id, label: "Linux · Firefox", since: "Nov 1" } });
  const t = node(), rm = node(); r.querySelector = (s) => (s === ".setpushthis" ? t : rm); return r; };
global.window = {}; global.document = { documentElement: node(), body: node(), querySelector: () => null,
  querySelectorAll: () => [], addEventListener: noop, createElement: node };
global.localStorage = { getItem: () => null, setItem: noop };
global.sessionStorage = { getItem: (k) => store[k] || null, setItem: (k, v) => { store[k] = v; },
  removeItem: (k) => { delete store[k]; } };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/settings", protocol: "http:", host: "x", reload: () => log.push("reload") };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
Object.assign(window, { isSecureContext: true, PushManager: noop, Notification: { permission: "granted" },
  navigator: { userAgent: "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0",
    serviceWorker: {} } });
Object.defineProperty(globalThis, "navigator", { value: { serviceWorker: { getRegistration: async () =>
  ({ pushManager: { getSubscription: async () => sub } }) } }, configurable: true });
const tick = () => new Promise((r) => setImmediate(r));
(async () => {
  const mine = await window.AO.push.deviceId(ENDPOINT);
  const rows = [row(mine), row("0000000000000000")];
  const form = node({ dataset: { key: "BPAq", block: "", https: "" },
    elements: { push_tg: node({ value: "both", dataset: {} }), push_secrets: { defaultValue: "look/dev" } },
    querySelector: (s) => parts[s] || null,
    querySelectorAll: (s) => (s === ".setpushdev" ? rows : []) });
  let fail = false;
  const post = async (verb, body) => { log.push("post " + verb + " " + JSON.stringify(body));
    if (fail) throw new Error("the home did not answer"); return {}; };
  store["ao.pushsaid"] = "the key is made";
  window.AO.pushCard(form, post, () => false, noop);
  const said0 = parts[".setpushsaid"].textContent, kept0 = store["ao.pushsaid"] || null;
  for (let i = 0; i < 5; i++) await tick();
  const me = parts[".setpushme"];
  const drawn = { checked: me.checked, disabled: me.disabled, test_hidden: parts[".setpushtest"].hidden };
  fail = true; me.checked = false; me.fire("change");
  for (let i = 0; i < 8; i++) await tick();
  const failed = { log: log.slice(), said: parts[".setpushsaid"].textContent };
  log.length = 0; fail = false; me.checked = false; me.fire("change");
  for (let i = 0; i < 8; i++) await tick();
  const kept = store["ao.pushsaid"] || null;
  console.log(JSON.stringify({ said0, kept0, drawn, failed, off: log.slice(), kept, mine }));
})();
"""


@pytest.mark.unit
def test_the_card_turns_off_at_the_home_first_and_says_its_result_after_the_reload():
    """`AO.pushCard` under a stub DOM: a line kept for the reload is said once on the page drawn next; this
    browser's listed subscription reads the switch on, with **Send a test**; off posts `push_unsubscribe` before
    the browser drops its subscription, so a failed post leaves both standing and says why; a landed press keeps
    its words for the reload (§4.5a **Push**: **Make key** *prints its result in words*)."""
    got = _run(_node(), CARD, str(UI / "static" / "app.js"))
    assert got["said0"] == "the key is made" and got["kept0"] is None
    assert got["drawn"] == {"checked": True, "disabled": False, "test_hidden": False}
    assert got["failed"]["log"] == [f'post push_unsubscribe {{"id":"{got["mine"]}"}}']  # the browser kept its own
    assert got["failed"]["said"] == "the home did not answer"
    assert got["off"] == [f'post push_unsubscribe {{"id":"{got["mine"]}"}}', "browser unsubscribe", "reload"]
    assert got["kept"] == "off"
