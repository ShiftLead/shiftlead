"""Told on the home-screen app too, the sending half (design §4.10 *Told on the home-screen app too*, *The key*,
*The key's reading*; TD-1304 slice 2): the pass with either channel on, *both* and *fallback*, the child's
`--push`, `--public` and `--key` modes, the derived-key check, the key's background reading, a paused key,
404/410 drops, `push_key` and `notify_test {channel: push, device}`. The home's child is replaced by a fake
that answers as the real one does; the child itself is driven with its post replaced: no test sends anything."""

import asyncio
import base64
import json
import os
import sys
from datetime import UTC, datetime, timedelta

import pytest

from sessionorc import mail, modes, notify
from sessionorc import push as push_mod
from sessionorc import settings as settings_mod
from sessionorc.client import AgentError, LocalClient
from sessionorc.models import Pending, Session

pytestmark = pytest.mark.integration


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


PUBLIC = b64(b"\x04" + b"k" * 64)
OTHER = b64(b"\x04" + b"o" * 64)
KEYS = {"p256dh": b64(b"\x04" + b"p" * 64), "auth": b64(b"a" * 16)}
EP1, EP2 = "https://fcm.googleapis.com/fcm/send/one", "https://web.push.apple.com/two"


def _z(t: datetime) -> str:
    return t.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _devices(*eps: str) -> list[dict]:
    return [{"id": push_mod.device_id(ep), "endpoint": ep, "keys": KEYS, "label": f"phone {n}", "since": "x",
             "last_ok": None, "last_error": None} for n, ep in enumerate(eps)]  # fmt: skip


def _store(*eps: str, key: str | None = push_mod.KEY, public: str = PUBLIC) -> None:
    doc: dict = {"public_key": public, "devices": _devices(*eps)}
    if key is not None:
        doc["key"] = key
    push_mod.save(doc)


def _settings(telegram: bool = False, pick: str = "both", on: bool = True) -> None:
    n: dict = {"push": {"on": on, "telegram": pick, "secrets": "home/push"}}
    if telegram:
        n["telegram"] = {"on": True, "secrets": "home/tg", "link": "http://kmaster:8765"}
    settings_mod.save({"notify": n})


class Child:
    """The push child as the home sees it: its reading first, then one status a device and payload."""

    def __init__(self) -> None:
        self.public: str | None = PUBLIC  # None: the config holds no key
        self.status: dict[str, object] = {}  # endpoint → status; absent, 201
        self.fail: str | None = None  # the child failed before a line (Doppler not logged in)
        self.calls: list[tuple[str, tuple, object]] = []

    async def __call__(self, secrets, mode, stdin=""):
        self.calls.append((secrets, tuple(mode), json.loads(stdin) if stdin else None))
        if self.fail:
            return [], self.fail, False
        first = {"key": "key", "public_key": self.public} if self.public else {"key": "no key"}
        if mode[0] != "--push" or not self.public:
            return [first], None, False
        job = json.loads(stdin)
        out = [first] + [{"device": d["id"], "i": i, "status": self.status.get(d["endpoint"], 201)}
                         for d in job["devices"] for i in range(len(job["payloads"]))]  # fmt: skip
        return out, None, False

    def pushes(self) -> list[dict]:
        return [c[2] for c in self.calls if c[1] == ("--push",)]


@pytest.fixture
def child(agent, monkeypatch):
    got = Child()
    monkeypatch.setattr(agent, "_push_run", got)
    return got


@pytest.fixture
def sent(agent, monkeypatch):
    """Every Telegram send, as `(secrets, text)`."""
    got: list[tuple[str, str]] = []

    async def record(secrets: str, text: str) -> str | None:
        got.append((secrets, text))
        return None

    monkeypatch.setattr(agent, "_notify_run", record)
    return got


def _session(agent, tmp_path, n: int, t0: datetime) -> Session:
    s = Session(id=f"ao-x-w{n}", name=f"grinder-x-{n}", kind="agent", adapter="agentshell", dir=str(tmp_path),
                team="x-grind", state="needs-you", since=_z(t0),
                pending=Pending(kind="question", text="q"))  # fmt: skip
    agent.sessions[s.id] = s
    return s


async def _settle(agent) -> None:
    for _ in range(50):
        if not agent._bg:
            return
        await asyncio.sleep(0.01)


async def _pass(agent, now: datetime) -> None:
    agent._note_attention(now)
    agent._notify_pass(now)
    await _settle(agent)


# -- the pass --------------------------------------------------------------------------------------


async def test_a_row_is_told_once_to_every_device_with_telegram_off_and_a_410_drops_one(agent, tmp_path, child, sent):
    _settings()
    _store(EP1, EP2)
    child.status[EP2] = 410
    t0 = datetime.now(UTC)
    s = _session(agent, tmp_path, 1, t0)
    try:
        await _pass(agent, t0 + timedelta(seconds=61))
        (job,) = child.pushes()
        assert {d["id"] for d in job["devices"]} == {push_mod.device_id(EP1), push_mod.device_id(EP2)}
        (p,) = job["payloads"]
        assert p == {"body": "grinder-x-1 (x-grind) needs you: question", "path": "/inbox?row=ao-x-w1%7Cquestion",
                     "tag": "ao-x-w1|question"}  # fmt: skip
        assert job["sub"] == notify.PUSH_SUB, "no https reach.url: the project's own address"
        assert sent == [], "Telegram is off"
        doc = push_mod.load()
        assert [d["endpoint"] for d in doc["devices"]] == [EP1], "the 410 one is dropped"
        assert doc["devices"][0]["last_ok"] and doc["last_line"].startswith("a device was removed: its subscription")
        await _pass(agent, t0 + timedelta(seconds=90))
        assert len(child.pushes()) == 1, "told once"
        view = (await agent.rpc_host())["push"]
        assert "endpoint" not in json.dumps(view) and view["devices"][0]["last_ok"]
    finally:
        agent.sessions.pop(s.id, None)


async def test_both_sends_on_both_channels(agent, tmp_path, child, sent):
    _settings(telegram=True, pick="both")
    _store(EP1)
    t0 = datetime.now(UTC)
    s = _session(agent, tmp_path, 1, t0)
    try:
        await _pass(agent, t0 + timedelta(seconds=61))
        assert len(child.pushes()) == 1
        assert [x[0] for x in sent] == ["home/tg"] and "/inbox?row=" in sent[0][1]
        assert child.calls[-1][0] == "home/push"
    finally:
        agent.sessions.pop(s.id, None)


async def test_fallback_sends_telegram_only_for_the_rows_no_device_took(agent, tmp_path, child, sent, monkeypatch):
    _settings(telegram=True, pick="fallback")
    _store(EP1)
    t0 = datetime.now(UTC)
    s1, s2 = _session(agent, tmp_path, 1, t0), _session(agent, tmp_path, 2, t0)

    async def half(secrets, mode, stdin=""):  # the device takes the first row and refuses the second
        lines, why, t = await Child.__call__(child, secrets, mode, stdin)
        return [lines[0]] + [{**ln, "status": 201 if ln["i"] == 0 else 500} for ln in lines[1:]], why, t

    monkeypatch.setattr(agent, "_push_run", half)
    try:
        await _pass(agent, t0 + timedelta(seconds=61))
        assert len(child.pushes()[0]["payloads"]) == 2
        assert len(sent) == 1 and "grinder-x-2" in sent[0][1], "Telegram carries the row no device took"
        (d,) = push_mod.load()["devices"]
        assert d["last_error"]["reason"] == "the push service answered 500"
    finally:
        for s in (s1, s2):
            agent.sessions.pop(s.id, None)


async def test_fallback_with_push_off_or_no_device_sends_telegram(agent, tmp_path, child, sent):
    _settings(telegram=True, pick="fallback", on=False)
    _store(EP1)
    t0 = datetime.now(UTC)
    s = _session(agent, tmp_path, 1, t0)
    try:
        await _pass(agent, t0 + timedelta(seconds=61))
        assert child.pushes() == [] and len(sent) == 1
    finally:
        agent.sessions.pop(s.id, None)


async def test_a_paused_key_keeps_the_devices_tells_nothing_and_resumes(agent, tmp_path, child, sent):
    _settings(telegram=True, pick="fallback")
    _store(EP1, key=push_mod.NO_KEY)
    child.public = None
    t0 = datetime.now(UTC)
    s = _session(agent, tmp_path, 1, t0)
    try:
        await _pass(agent, t0 + timedelta(seconds=61))
        assert child.pushes() == [], "no child runs while paused"
        assert len(sent) == 1, "under fallback, a paused push's row goes to Telegram"
        doc = push_mod.load()
        assert doc["last_line"] == "push is paused: no key" and len(doc["devices"]) == 1
        # the key put back: the next background read (ten minutes on) resumes it, devices kept
        child.public = PUBLIC
        agent._push_read_at = datetime.now(UTC) - timedelta(minutes=11)
        await _pass(agent, datetime.now(UTC))
        doc = push_mod.load()
        assert doc["key"] == "key" and "last_line" not in doc and len(doc["devices"]) == 1
    finally:
        agent.sessions.pop(s.id, None)


async def test_a_changed_key_drops_every_device_and_discards_the_send(agent, tmp_path, child, sent):
    _settings()
    _store(EP1, EP2)
    child.public = OTHER
    t0 = datetime.now(UTC)
    s = _session(agent, tmp_path, 1, t0)
    try:
        await _pass(agent, t0 + timedelta(seconds=61))
        doc = push_mod.load()
        assert doc["devices"] == [] and doc["public_key"] == OTHER
        assert doc["last_line"] == "the key changed: turn this on again on each device"
    finally:
        agent.sessions.pop(s.id, None)


async def test_a_failed_send_child_writes_the_reading(agent, tmp_path, child, sent):
    _settings()
    _store(EP1)
    child.fail = "Doppler Error: you must be logged in"
    t0 = datetime.now(UTC)
    s = _session(agent, tmp_path, 1, t0)
    try:
        await _pass(agent, t0 + timedelta(seconds=61))
        doc = push_mod.load()
        assert doc["key"] == "unreadable: Doppler Error: you must be logged in"
        assert doc["last_line"].startswith("push is paused: unreadable") and len(doc["devices"]) == 1
    finally:
        agent.sessions.pop(s.id, None)


# -- the key's reading -----------------------------------------------------------------------------


async def test_a_key_already_in_the_config_is_read_in_the_background_before_any_send(agent, child):
    _settings()
    assert push_mod.load().get("key") is None
    now = datetime.now(UTC)
    await _pass(agent, now)
    assert [c[1] for c in child.calls] == [("--public",)]
    assert push_mod.load()["key"] == "key" and push_mod.load()["public_key"] == PUBLIC


async def test_a_failed_reading_is_retried_no_sooner_than_ten_minutes(agent, child):
    _settings()
    child.fail = "Doppler Error: config not found"
    now = datetime.now(UTC)
    await _pass(agent, now)
    assert push_mod.load()["key"] == "unreadable: Doppler Error: config not found"
    await _pass(agent, now + timedelta(minutes=9))
    assert len(child.calls) == 1
    await _pass(agent, now + timedelta(minutes=10))
    assert len(child.calls) == 2


async def test_no_secrets_no_reading_and_a_save_that_moves_secrets_reads_afresh(agent, child):
    settings_mod.save({})
    await _pass(agent, datetime.now(UTC))
    assert child.calls == [] and "key" not in push_mod.load()
    _store(EP1)
    async with LocalClient() as person:
        await person.call("set_settings", notify={"push": {"secrets": "other/cfg"}})
    assert "key" not in push_mod.load(), "the kept reading was of another config"
    await _pass(agent, datetime.now(UTC))
    assert child.calls[-1][:2] == ("other/cfg", ("--public",))


# -- push_key and the test -------------------------------------------------------------------------


async def test_push_key_writes_only_to_its_own_config_and_keeps_a_refusals_reading(agent, child, monkeypatch):
    settings_mod.save({"notify": {"telegram": {"on": True, "secrets": "home/tg"}}})
    async with LocalClient() as person:
        with pytest.raises(AgentError, match="set notify.push.secrets — the key is written only there"):
            await person.call("push_key")
        _settings()

        async def refused(secrets, mode, stdin=""):
            child.calls.append((secrets, tuple(mode), None))
            return [{"key": "key", "public_key": PUBLIC}], "a key is there: replacing it would end …", False

        monkeypatch.setattr(agent, "_push_run", refused)
        with pytest.raises(AgentError, match="a key is there"):
            await person.call("push_key")
        assert child.calls[-1] == ("home/push", ("--key", "home/push"), None)
        assert push_mod.load()["key"] == "key", "the refusal's reading is kept"

        async def doppler_says_no(secrets, mode, stdin=""):
            return [], "Doppler refused the write: you do not have write access", False

        monkeypatch.setattr(agent, "_push_run", doppler_says_no)
        with pytest.raises(AgentError, match="Doppler refused the write"):
            await person.call("push_key")
        monkeypatch.setattr(agent, "_push_run", child)
        push_mod.save({"key": push_mod.NO_KEY, "devices": []})
        got = await person.call("push_key")
        assert got["public_key"] == PUBLIC and push_mod.load()["key"] == "key"
        # devices listed under a deleted key cannot be reached with the new one: dropped, and said
        _store(EP1, key=push_mod.NO_KEY, public=OTHER)
        await person.call("push_key")
        doc = push_mod.load()
        assert doc["devices"] == [] and doc["last_line"] == push_mod.KEY_CHANGED


async def test_a_child_that_fails_after_its_reading_says_why_and_a_push_begun_before_a_save_is_discarded(
    agent, child, monkeypatch
):
    _settings()
    _store(EP1)

    async def no_pywebpush(secrets, mode, stdin=""):
        return [{"key": "key", "public_key": PUBLIC}], "pywebpush: not installed", False

    monkeypatch.setattr(agent, "_push_run", no_pywebpush)
    taken, statuses, _ = await agent._push_send("home/push", [{"body": "x", "path": "/inbox", "tag": "t"}])
    assert taken == set() and push_mod.load()["devices"][0]["last_error"]["reason"] == "pywebpush: not installed"

    async def slow(secrets, mode, stdin=""):
        agent._push_secrets_moved()  # a Save moved `secrets` while the child ran
        return [{"key": "key", "public_key": OTHER}], None, False

    _store(EP1)
    monkeypatch.setattr(agent, "_push_run", slow)
    _, _, why = await agent._push_send("home/push", [{"body": "x", "path": "/inbox", "tag": "t"}])
    assert why and len(push_mod.load()["devices"]) == 1, "the old config's key never drops the devices"


async def test_the_push_test_reaches_one_device_and_is_refused_while_paused(agent, child):
    _settings()
    _store(EP1, EP2)
    dev = push_mod.device_id(EP1)
    async with LocalClient() as person:
        got = await person.call("notify_test", channel="push", device=dev)
        assert got["sent"] and got["result"].startswith("delivered to phone 0 ")
        (job,) = child.pushes()
        assert [d["id"] for d in job["devices"]] == [dev]
        assert job["payloads"] == [{"body": f"a test from {agent.home or agent.host}", "path": "/inbox",
                                    "tag": "test"}]  # fmt: skip
        child.status[EP1] = 410
        got = await person.call("notify_test", channel="push", device=dev)
        assert got["result"] == "the push service answered 410 — this device's subscription ended"
        assert [d["endpoint"] for d in push_mod.load()["devices"]] == [EP2]
        _store(EP1, key=push_mod.NO_KEY)
        with pytest.raises(AgentError, match="push is paused: no key"):
            await person.call("notify_test", channel="push", device=dev)
        _store(EP1, key=None)
        with pytest.raises(AgentError, match="reading the key — try again shortly"):
            await person.call("notify_test", channel="push", device=dev)


async def test_push_key_is_a_persons_own_and_the_homes(agent, tmp_path, child):
    assert "push_key" in mail.PERSON_ONLY and "push_key" not in modes.HOME_EDITS
    assert "notify_test" in modes.HOME_EDITS
    _settings()
    async with LocalClient() as person:
        sid = (await person.call("create", name="w", dir=str(tmp_path), adapter="shell", role="worker",
                                 argv=["bash", "--norc", "--noprofile"]))["id"]  # fmt: skip
        try:
            async with LocalClient(caller=sid) as itself:
                with pytest.raises(AgentError, match="a person's own"):
                    await itself.call("push_key")
        finally:
            await person.call("kill", id=sid)
            await person.call("remove", id=sid)
        agent.mode = "node"
        try:
            with pytest.raises(AgentError, match="this host is a node"):
                await person.call("push_key")
        finally:
            agent.mode = "home"
    assert child.calls == []


# -- the child -------------------------------------------------------------------------------------


def _pair() -> tuple[str, str, str]:
    """A P-256 key as the base64url raw scalar, as a PEM, and its public half."""
    ec = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ec")
    from cryptography.hazmat.primitives import serialization

    key = ec.generate_private_key(ec.SECP256R1())
    raw = b64(key.private_numbers().private_value.to_bytes(32, "big"))
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()  # fmt: skip
    return raw, pem, notify.public_key(key)


def test_the_child_reads_a_raw_scalar_or_a_pem_and_says_no_key(monkeypatch, capsys):
    raw, pem, public = _pair()
    for text in (raw, pem):
        monkeypatch.setenv("VAPID_PRIVATE_KEY", text)
        monkeypatch.setattr(sys, "argv", ["notify", "--public"])
        assert notify.main() == 0
        out = capsys.readouterr().out
        assert json.loads(out) == {"key": "key", "public_key": public}
        assert raw not in out and "PRIVATE" not in out
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "not a key")
    assert notify.reading()[0]["key"].startswith("unreadable: VAPID_PRIVATE_KEY is neither")
    monkeypatch.delenv("VAPID_PRIVATE_KEY")
    assert notify.reading()[0] == {"key": "no key"}


def test_the_child_pushes_each_payload_to_each_device_and_prints_no_secret(monkeypatch, capsys):
    pytest.importorskip("pywebpush")
    raw, _, public = _pair()
    monkeypatch.setenv("VAPID_PRIVATE_KEY", raw)
    posts = []

    def post(device, data, key, sub):
        posts.append((device["id"], json.loads(data)["tag"], sub))
        return 410 if device["id"] == "b" else 201

    monkeypatch.setattr(notify, "_post", post)
    job = {"sub": "https://home.example.ts.net", "payloads": [{"body": "x", "path": "/inbox", "tag": "t1"},
           {"body": "y", "path": "/inbox", "tag": "t2"}],
           "devices": [{"id": "a", "endpoint": EP1, "keys": KEYS},
                       {"id": "b", "endpoint": EP2, "keys": KEYS}]}  # fmt: skip
    assert notify.push_main(json.dumps(job)) == 0
    out = capsys.readouterr().out
    lines = [json.loads(x) for x in out.splitlines()]
    assert lines[0] == {"key": "key", "public_key": public}
    assert sorted((x["device"], x["i"], x["status"]) for x in lines[1:]) == [
        ("a", 0, 201), ("a", 1, 201), ("b", 0, 410), ("b", 1, 410)]  # fmt: skip
    assert len(posts) == 4 and {p[2] for p in posts} == {"https://home.example.ts.net"}
    assert raw not in out and EP1 not in out and EP2 not in out


def test_the_child_refuses_an_endpoint_that_resolves_inward(monkeypatch):
    pytest.importorskip("pywebpush")
    import socket

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("10.0.0.5", 443))])
    raw, _, _ = _pair()
    key = notify.private_key(raw)
    got = notify._post({"id": "a", "endpoint": EP1, "keys": KEYS}, "{}", key, notify.PUSH_SUB)
    assert got == "the push service's name resolves to a private address"
    assert push_mod.words(401) == "the push service refused the key's sender (401)"


def _burst(devices: int) -> dict:
    payloads = [{"body": f"row {n}", "path": "/inbox", "tag": f"t{n}"} for n in range(notify.BURST)]
    payloads.append({"body": notify.MORE, "path": "/inbox", "tag": "more"})  # a full burst: BURST, then *and more*
    return {"payloads": payloads, "devices": [{"id": f"d{n}", "endpoint": EP1, "keys": KEYS} for n in range(devices)]}


def test_a_full_burst_to_three_devices_ends_inside_the_bound_with_every_status(monkeypatch, capsys):
    """TD-1322: 7 payloads × 3 devices posted at once, not in waves of 8, so posts that each take a request's
    whole time end together; and a post still running at the deadline is printed *no answer* and left behind,
    the child ending at once with every line printed."""
    import time

    pytest.importorskip("pywebpush")
    raw, _, _ = _pair()
    monkeypatch.setenv("VAPID_PRIVATE_KEY", raw)
    monkeypatch.setattr(notify, "PUSH_SECONDS", 3.0)
    monkeypatch.setattr(notify, "_post", lambda d, data, key, sub: time.sleep(1.0) or 201)
    started = time.monotonic()
    assert notify.push_main(json.dumps(_burst(3))) == 0
    assert time.monotonic() - started < 2.5  # three waves of 8 would take 3 s
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines()[1:]]
    assert sorted((x["device"], x["i"]) for x in lines) == [(f"d{d}", i) for d in range(3) for i in range(7)]
    assert {x["status"] for x in lines} == {201}

    left = []
    monkeypatch.setattr(notify, "PUSH_SECONDS", 0.5)
    monkeypatch.setattr(notify, "_abandon", lambda: left.append(True))
    hang = lambda d, data, key, sub: time.sleep(3.0 if d["id"] == "d1" else 0.0) or 201  # noqa: E731
    monkeypatch.setattr(notify, "_post", hang)
    started = time.monotonic()
    assert notify.push_main(json.dumps(_burst(3))) == 0
    assert time.monotonic() - started < 2.0 and left == [True]
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines()[1:]]
    assert len(lines) == 21
    assert {x["status"] for x in lines if x["device"] == "d1"} == {push_mod.NO_ANSWER}
    assert {x["status"] for x in lines if x["device"] != "d1"} == {201}


def test_an_address_that_does_not_read_ends_only_its_own_post(monkeypatch, capsys):
    """TD-1322: `getaddrinfo` answering an address `ipaddress` cannot parse is that device's status, in words;
    the other devices' posts are printed as they answer."""
    import socket

    pytest.importorskip("pywebpush")
    raw, _, _ = _pair()
    monkeypatch.setenv("VAPID_PRIVATE_KEY", raw)
    real = notify._post

    def post(d, data, key, sub):
        return real(d, data, key, sub) if d["id"] == "bad" else 201

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("not-an-address", 443))])
    monkeypatch.setattr(notify, "_post", post)
    devices = [{"id": "bad", "endpoint": EP1, "keys": KEYS}, {"id": "ok", "endpoint": EP2, "keys": KEYS}]
    job = {"payloads": [{"body": "x", "path": "/inbox", "tag": "t"}], "devices": devices}
    assert notify.push_main(json.dumps(job)) == 0
    lines = {x["device"]: x["status"] for x in map(json.loads, capsys.readouterr().out.splitlines()[1:])}
    assert lines == {"bad": "the push service's name resolves to an address that does not read", "ok": 201}


def test_make_key_refuses_over_a_key_and_words_a_doppler_refusal(monkeypatch, capsys, tmp_path):
    raw, _, public = _pair()
    monkeypatch.setenv("VAPID_PRIVATE_KEY", raw)
    assert notify.key_main("home/push") == 2
    got = capsys.readouterr()
    assert json.loads(got.out) == {"key": "key", "public_key": public} and "a key is there" in got.err
    monkeypatch.delenv("VAPID_PRIVATE_KEY")
    doppler = tmp_path / "doppler"
    doppler.write_text("#!/bin/sh\ncat > /dev/null\necho 'Doppler Error: you do not have write access' >&2\nexit 1\n")
    doppler.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    assert notify.key_main("home/push") == 1
    got = capsys.readouterr()
    assert got.out == "" and got.err.strip() == "Doppler refused the write: Doppler Error: you do not have write access"
    # a write Doppler takes: the private half went on its stdin alone, the public half printed
    kept = tmp_path / "kept"
    doppler.write_text(f'#!/bin/sh\necho "$@" > {kept}.args\ncat > {kept}\n')
    assert notify.key_main("home/push") == 0
    out = json.loads(capsys.readouterr().out)
    written = kept.read_text()
    assert out["key"] == "key" and notify.public_key(notify.private_key(written)) == out["public_key"]
    assert written not in json.dumps(out)
    assert (tmp_path / "kept.args").read_text().split() == [
        "secrets", "set", "VAPID_PRIVATE_KEY", "--project", "home", "--config", "push", "--silent"]  # fmt: skip


async def test_the_real_run_streams_the_lines_and_keeps_them_past_a_timeout(agent, monkeypatch, tmp_path):
    """`_push_run` against a stand-in Doppler: each JSON line kept, and on a timeout those already printed."""
    doppler = tmp_path / "doppler"
    doppler.write_text('#!/bin/sh\ncat > /dev/null\necho \'{"key": "no key"}\'\nsleep 30 &\nwait\n')
    doppler.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    monkeypatch.setattr(notify, "CHILD_SECONDS", 0.3)
    monkeypatch.setattr(notify, "REQUEST_SECONDS", 0.2)
    lines, why, timed_out = await type(agent)._push_run(agent, "p/c", ("--public",))
    assert lines == [{"key": "no key"}] and timed_out and why == "no answer in 0.5 s"
    monkeypatch.setenv("PATH", "/nonexistent")
    assert (await type(agent)._push_run(agent, "p/c", ("--public",)))[1] == "doppler: not installed"
