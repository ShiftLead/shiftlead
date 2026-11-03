"""Told on the home-screen app too, the home's store (design §4.10 *On and off, per device*, *Where the
subscriptions live*; TD-1304 slice 1): `push.json`, the checks a subscription meets, `push_subscribe` and
`push_unsubscribe` as a person's own at the home, the `host` read's `push` view, and `notify.push` in
`set_settings`. Nothing here sends."""

import base64
import os

import pytest

from sessionorc import mail, modes
from sessionorc import push as push_mod
from sessionorc import settings as settings_mod
from sessionorc.client import AgentError, LocalClient

pytestmark = pytest.mark.integration


def b64(raw: bytes, pad: bool = False) -> str:
    s = base64.urlsafe_b64encode(raw).decode()
    return s if pad else s.rstrip("=")


PUBLIC = b64(b"\x04" + b"k" * 64)
KEYS = {"p256dh": b64(b"\x04" + b"p" * 64), "auth": b64(b"a" * 16)}
EP = "https://fcm.googleapis.com/fcm/send/abc123"


def _ready(key: str = push_mod.KEY) -> None:
    push_mod.save({"key": key, "public_key": PUBLIC, "devices": []})


def test_the_checks_name_the_field():
    assert push_mod.check(EP, KEYS) == (EP, KEYS)
    for ep, field in (("http://push.example/x", "https"), ("https://127.0.0.1/x", "loopback"),
                      ("https://localhost/x", "loopback"), ("https://10.1.2.3/x", "private"),
                      ("https://192.168.0.9/x", "private"), ("https://169.254.1.1/x", "link-local"),
                      ("https://[::1]/x", "loopback"), ("", "endpoint"), ("https://127.1/x", "internal"),
                      ("https://2130706433/x", "internal"), ("https://0x7f.0.0.1/x", "internal"),
                      ("https://017700000001/x", "internal"), ("https://0/x", "internal"),
                      ("https://0.0.0.0/x", "internal"), ("https://[::]/x", "internal"),
                      ("https://localhost./x", "internal"), ("https://127.0.0.1./x", "internal"),
                      ("https://100.64.0.1/x", "internal"), ("https://224.0.0.1/x", "internal"),
                      ("https://[::ffff:127.0.0.1]/x", "internal"), ("https://intranet/x", "internal"),
                      ("https://foo.local/x", "internal"), ("https://metadata.google.internal/x", "internal"),
                      ("https://push.example.com:abc/x", "endpoint")):  # fmt: skip
        with pytest.raises(ValueError, match=field):
            push_mod.check(ep, KEYS)
    with pytest.raises(ValueError, match=r"keys.p256dh: 64 bytes, not 65"):
        push_mod.check(EP, {**KEYS, "p256dh": b64(b"x" * 64)})
    with pytest.raises(ValueError, match=r"keys.auth: 12 bytes, not 16"):
        push_mod.check(EP, {**KEYS, "auth": b64(b"x" * 12)})
    with pytest.raises(ValueError, match="keys.auth: not a base64url"):
        push_mod.check(EP, {**KEYS, "auth": "!!"})
    with pytest.raises(ValueError, match="keys.auth: not a base64url"):
        push_mod.check(EP, {**KEYS, "auth": KEYS["auth"].replace("Y", "+")})  # standard base64, not url-safe
    assert push_mod.check("https://8.8.8.8:443/x", KEYS)[0] == "https://8.8.8.8:443/x"  # a global literal passes
    assert push_mod.device_id(EP) == __import__("hashlib").sha256(EP.encode()).hexdigest()[:16]
    assert push_mod.same_key(PUBLIC, b64(b"\x04" + b"k" * 64, pad=True)), "compared as decoded bytes"


async def test_subscribe_lists_a_device_and_the_host_read_hides_its_endpoint_and_keys(agent):
    async with LocalClient() as person:
        with pytest.raises(AgentError, match="reading the key"):
            await person.call("push_subscribe", endpoint=EP, keys=KEYS, label="iPhone · Safari", key=PUBLIC)
        _ready(push_mod.NO_KEY)
        with pytest.raises(AgentError, match="no key"):
            await person.call("push_subscribe", endpoint=EP, keys=KEYS, label="iPhone · Safari", key=PUBLIC)
        _ready()
        with pytest.raises(AgentError, match="key: the subscription was made with a key"):
            await person.call("push_subscribe", endpoint=EP, keys=KEYS, label="x", key=b64(b"\x04" + b"z" * 64))
        with pytest.raises(AgentError, match="endpoint: must be https"):
            await person.call("push_subscribe", endpoint="http://p.example/1", keys=KEYS, label="x", key=PUBLIC)
        got = await person.call("push_subscribe", endpoint=EP, keys=KEYS, label="iPhone · Safari", key=PUBLIC)
        assert got == {"id": push_mod.device_id(EP)}
        p = push_mod.path()
        assert os.stat(p).st_mode & 0o777 == 0o600
        doc = push_mod.load()
        (d,) = doc["devices"]
        assert d["endpoint"] == EP and d["keys"] == KEYS and d["label"] == "iPhone · Safari" and d["since"]
        view = (await agent.rpc_host())["push"]
        assert view["key"] == "key" and view["public_key"] == PUBLIC
        assert view["devices"] == [{"id": got["id"], "label": "iPhone · Safari", "since": d["since"],
                                    "last_ok": None, "last_error": None}]  # fmt: skip
        assert EP not in str(view) and KEYS["auth"] not in str(view)
        # the same endpoint again is the same device; `replaces` swaps one's endpoint and keys, keeping its label
        await person.call("push_subscribe", endpoint=EP, keys=KEYS, label="other", key=PUBLIC)
        assert [x["label"] for x in push_mod.load()["devices"]] == ["iPhone · Safari"]
        ep2, keys2 = EP + "-rotated", {**KEYS, "auth": b64(b"b" * 16)}
        new = await person.call("push_subscribe", endpoint=ep2, keys=keys2, label="ignored", key=PUBLIC,
                                replaces=got["id"])  # fmt: skip
        (d2,) = push_mod.load()["devices"]
        assert new["id"] == push_mod.device_id(ep2) == d2["id"]
        assert (d2["endpoint"], d2["keys"], d2["label"], d2["since"]) == (ep2, keys2, "iPhone · Safari", d["since"])
        # a refused `replaces` leaves the old device listed; one naming an id no longer listed adds the device
        with pytest.raises(AgentError, match="auth"):
            await person.call("push_subscribe", endpoint=EP, keys={**KEYS, "auth": "x"}, label="y", key=PUBLIC,
                              replaces=new["id"])  # fmt: skip
        assert [x["id"] for x in push_mod.load()["devices"]] == [new["id"]]
        await person.call("push_subscribe", endpoint=EP, keys=KEYS, label="Linux · Firefox", key=PUBLIC,
                          replaces="0000000000000000")  # fmt: skip
        assert len(push_mod.load()["devices"]) == 2
        assert await person.call("push_unsubscribe", id=new["id"]) == {"removed": True}
        assert await person.call("push_unsubscribe", id=new["id"]) == {"removed": False}
        assert [x["label"] for x in push_mod.load()["devices"]] == ["Linux · Firefox"]


async def test_the_two_rpcs_are_a_persons_own_and_the_homes(agent, tmp_path):
    assert {"push_subscribe", "push_unsubscribe"} <= mail.PERSON_ONLY
    assert not {"push_subscribe", "push_unsubscribe"} & modes.HOME_EDITS  # a tap opens the home's own origin
    _ready()
    async with LocalClient() as person:
        sid = (await person.call("create", name="w", dir=str(tmp_path), adapter="shell", role="worker",
                                 argv=["bash", "--norc", "--noprofile"]))["id"]  # fmt: skip
        try:
            async with LocalClient(caller=sid) as itself:
                for rpc, kw in (("push_subscribe", {"endpoint": EP, "keys": KEYS, "label": "x", "key": PUBLIC}),
                                ("push_unsubscribe", {"id": "x"})):  # fmt: skip
                    with pytest.raises(AgentError, match="a person's own"):
                        await itself.call(rpc, **kw)
        finally:
            await person.call("kill", id=sid)
            await person.call("remove", id=sid)
        agent.mode = "node"
        try:
            with pytest.raises(AgentError, match="this host is a node"):
                await person.call("push_unsubscribe", id="x")
            assert "push" not in await agent.rpc_host()
        finally:
            agent.mode = "home"
    assert push_mod.load()["devices"] == []


def test_the_setting_takes_a_switch_a_pick_and_a_doppler_name():
    assert settings_mod.parse_push({"on": False, "telegram": "fallback", "secrets": " p/c "}) == {
        "on": False, "telegram": "fallback", "secrets": "p/c"}  # fmt: skip
    for bad in ({"on": "no"}, {"telegram": "always"}, {"secrets": "VAPID_PRIVATE_KEY=x"}, {"devices": []}):
        with pytest.raises(ValueError):
            settings_mod.parse_push(bad)
    # absent, on, both, and Telegram's secrets for sending; Make key writes only to push's own
    doc = {"notify": {"telegram": {"secrets": "t/prd"}}}
    assert settings_mod.push(doc) == {"on": True, "telegram": "both", "secrets": "t/prd", "own_secrets": None}
    doc["notify"]["push"] = {"secrets": "p/prd", "telegram": "nope"}
    assert settings_mod.notify(doc)["push"] == {"secrets": "p/prd"}  # a bad hand edit dropped field by field
    assert settings_mod.push(doc)["secrets"] == settings_mod.push(doc)["own_secrets"] == "p/prd"


async def test_set_settings_writes_notify_push_and_names_a_bad_field(agent):
    async with LocalClient() as person:
        out = await person.call("set_settings", notify={"push": {"on": False, "telegram": "fallback"}})
        assert out["notify"] == {"push": {"on": False, "telegram": "fallback"}}
        out = await person.call("set_settings", notify={"telegram": {"secrets": "t/prd"}, "push": {"on": None}})
        assert out["notify"] == {"telegram": {"secrets": "t/prd"}, "push": {"telegram": "fallback"}}
        with pytest.raises(AgentError, match="push.telegram is both or fallback"):
            await person.call("set_settings", notify={"push": {"telegram": "always"}})
        with pytest.raises(AgentError, match=r"notify.push: unknown key devices"):
            await person.call("set_settings", notify={"push": {"devices": []}})
        await person.call("set_settings", notify={"push": None})
        assert settings_mod.load()["notify"] == {"telegram": {"secrets": "t/prd"}}


def test_subscribe_and_load_keep_what_the_store_says(tmp_path):
    """TD-1309: a known endpoint's new keys are stored; `replaces` onto an endpoint already listed leaves
    one device; a label is capped at 80; a hand-written `push.json` drops a device without an endpoint and
    passes on no non-string key."""
    doc = {"key": push_mod.KEY, "public_key": PUBLIC, "devices": []}
    first = push_mod.subscribe(doc, EP, KEYS, "x" * 81, PUBLIC, "2026-11-02T00:00:00Z")
    assert doc["devices"][0]["label"] == "x" * 80
    fresh = {"p256dh": b64(b"\x04" + b"q" * 64), "auth": b64(b"b" * 16)}
    assert push_mod.subscribe(doc, EP, fresh, "", PUBLIC, "2026-11-02T00:01:00Z") == first
    assert [d["keys"] for d in doc["devices"]] == [fresh], "the same endpoint's new keys are stored"
    other = "https://fcm.googleapis.com/fcm/send/other"
    second = push_mod.subscribe(doc, other, KEYS, "phone", PUBLIC, "2026-11-02T00:02:00Z")
    # the first device moves onto the endpoint the second already holds: one device remains under that id
    assert push_mod.subscribe(doc, other, KEYS, "", PUBLIC, "2026-11-02T00:03:00Z", replaces=first) == second
    assert [d["id"] for d in doc["devices"]] == [second]
    assert doc["devices"][0]["label"] == "x" * 80, "the replaced device's label is kept"

    where = tmp_path / "push.json"
    where.write_text(
        __import__("json").dumps(
            {
                "key": 7,
                "public_key": "",
                "last_line": "sent",
                "devices": [{"id": "a", "endpoint": EP}, {"id": "b"}, {"endpoint": EP}, "c"],
            }
        )
    )
    got = push_mod.load(where)
    assert got == {"devices": [{"id": "a", "endpoint": EP}], "last_line": "sent"}
