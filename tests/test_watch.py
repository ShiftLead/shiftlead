"""The watch's one run (design §4.10 *When the home itself is down: the watch*, TD-497), driven by a
fake socket (answering or silent), a fake `systemctl` and a fake clock through `watch.json`."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta

import pytest

from shiftlead import watch

T0 = datetime(2026, 10, 9, 11, 31, tzinfo=UTC)
EVERY = watch.WATCH_EVERY


@pytest.fixture
def home(tmp_path):
    return tmp_path / "home"


def drive(home, runs, secrets="samscrape/prd"):
    """Each run `(minutes after T0, answered, started)`; the lines each run sent, in order."""
    sent: list[list[str]] = []
    for minutes, answered, started in runs:
        got: list[str] = []
        watch.run_once(
            home=home,
            now=T0 + timedelta(minutes=minutes),
            answered=answered,
            started=started,
            host="kmaster",
            secrets=secrets,
            send=lambda line, s, log, got=got: got.append(line),
        )
        sent.append(got)
    return sent


def hhmm(minutes):
    return (T0 + timedelta(minutes=minutes)).astimezone().strftime("%H:%M")


def test_silence_is_told_at_ten_minutes_and_its_recovery_once(home):
    sent = drive(home, [(0, True, False), (5, False, False), (10, False, False), (15, False, False)])
    assert sent[:3] == [[], [], []], "five minutes silent is not yet an outage"
    assert sent[3] == [f"shiftlead · the host agent on kmaster has not answered since {hhmm(5)}"]
    state = json.loads((home / "watch.json").read_text())
    assert state["told"] == ["silent"] and state["silent_since"] == (T0 + timedelta(minutes=5)).isoformat()
    later = drive(home, [(20, False, False), (265, False, False), (270, True, False), (275, True, False)])
    assert later[:2] == [[], []], "one message an outage"
    assert later[2] == ["shiftlead · the host agent on kmaster answers again (silent 4h25m)"]
    assert later[3] == [], "one message a recovery"
    assert json.loads((home / "watch.json").read_text())["told"] == []


def test_a_stopped_manager_is_started_told_and_its_recovery_told(home):
    sent = drive(home, [(0, False, True), (5, True, False)])
    assert sent[0] == [
        f"shiftlead · kmaster's user manager was stopped; started again at {hhmm(0)}, sessions kept running"
    ]
    assert sent[1] == ["shiftlead · the host agent on kmaster answers again (silent 5 min)"]
    state = json.loads((home / "watch.json").read_text())
    assert state == {"silent_since": None, "manager_started_at": None, "told": [], "last_run": state["last_run"]}


def test_a_manager_started_and_answering_in_one_run_is_one_line(home):
    assert drive(home, [(0, True, True), (5, True, False)]) == [[watch.manager_line("kmaster", T0)], []]


def test_a_started_manager_then_ten_minutes_silent_is_both_lines_once(home):
    sent = drive(home, [(0, False, True), (5, False, False), (10, False, False), (15, False, False)])
    assert [len(s) for s in sent] == [1, 0, 1, 0]
    assert sent[2] == [watch.silent_line("kmaster", T0)]


def test_nothing_is_sent_with_the_switch_off_and_the_state_still_kept(home):
    sent = drive(home, [(0, False, True), (10, False, False), (15, True, False)], secrets=None)
    assert sent == [[], [], []]
    assert not (home / "watch.log").exists()
    assert json.loads((home / "watch.json").read_text())["told"] == []


def test_a_failed_send_is_logged_and_not_retried(home, monkeypatch):
    class Failed:
        returncode, stdout, stderr = 1, "", "Doppler Error: you must be logged in\n"

    calls = []
    monkeypatch.setattr(watch.subprocess, "run", lambda argv, **kw: calls.append((argv, kw["input"])) or Failed())
    for minutes in (0, 10, 15, 20):
        watch.run_once(
            home=home, now=T0 + timedelta(minutes=minutes), answered=False, started=False, host="kmaster", secrets="a/b"
        )
    assert len(calls) == 1, "the silent line once, and the failure not retried"
    argv, line = calls[0]
    assert argv[:6] == ["doppler", "run", "--project", "a", "--config", "b"] and argv[-2:] == [
        "-m",
        "sessionorc.notify",
    ]
    assert line.startswith("shiftlead · the host agent on kmaster has not answered")
    assert (home / "watch.log").read_text().endswith("send failed: Doppler Error: you must be logged in\n")


def test_a_broken_state_file_starts_afresh(home):
    home.mkdir()
    (home / "watch.json").write_text("{not json")
    assert drive(home, [(0, False, False)]) == [[]]
    assert json.loads((home / "watch.json").read_text())["silent_since"] == T0.isoformat()


def test_a_state_file_that_is_not_a_mapping_starts_afresh(home):
    home.mkdir()
    (home / "watch.json").write_text("[1, 2]")
    assert drive(home, [(0, False, False)]) == [[]]
    assert json.loads((home / "watch.json").read_text())["silent_since"] == T0.isoformat()


def test_a_sent_line_is_logged_and_a_child_that_cannot_run_is_a_log_line(monkeypatch):
    class Sent:
        returncode, stdout, stderr = 0, "", ""

    logged: list[str] = []
    monkeypatch.setattr(watch.subprocess, "run", lambda argv, **kw: Sent())
    watch.tell("shiftlead · a line", "a/b", logged.append)
    assert logged == ["told: shiftlead · a line"]
    for err in (FileNotFoundError("doppler"), subprocess.TimeoutExpired("doppler", 10)):

        def fail(argv, err=err, **kw):
            raise err

        monkeypatch.setattr(watch.subprocess, "run", fail)
        logged.clear()
        watch.tell("shiftlead · a line", "a/b", logged.append)
        assert logged == [f"send failed: {type(err).__name__}"]


def test_main_wires_the_switch_the_host_and_the_home(monkeypatch, tmp_path):
    """The run the system timer makes: the manager it started told, through the child with the
    switch's secrets, in the host's name, and the state kept under the home."""
    from sessionorc import hosts, settings

    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "ao"))
    monkeypatch.setattr(watch, "manager_started", lambda: True)
    monkeypatch.setattr(watch, "ask", lambda: False)
    monkeypatch.setattr(settings, "telegram", lambda doc: {"secrets": "a/b", "link": ""})
    monkeypatch.setattr(hosts, "local_host", lambda: hosts.Host(name="kmaster", vscode_host="kmaster"))

    class Sent:
        returncode, stdout, stderr = 0, "", ""

    sent = []
    monkeypatch.setattr(watch.subprocess, "run", lambda argv, **kw: sent.append((argv, kw["input"])) or Sent())
    assert watch.main() == 0
    assert len(sent) == 1
    argv, line = sent[0]
    assert argv[:6] == ["doppler", "run", "--project", "a", "--config", "b"]
    assert line.startswith("shiftlead · kmaster's user manager was stopped; started again at ")
    state = json.loads((tmp_path / "ao" / "watch.json").read_text())
    assert state["told"] == ["manager"] and state["manager_started_at"]
    assert (tmp_path / "ao" / "watch.log").read_text().endswith(f"told: {line}\n")


def fake_systemctl(entered, began):
    def run(argv):
        assert argv[:2] == ["systemctl", "show"] and argv[-1] == "--value"
        return {"user@1000.service": entered, watch.SERVICE: began}[argv[2]] + "\n"

    return run


def test_the_manager_start_is_read_from_systemd_s_monotonic_stamps():
    """Started by this run: the manager became active after the watch service began, just now."""
    assert watch.manager_started(fake_systemctl("500000000", "499000000"), uid=1000, mono_now=510.0)
    assert not watch.manager_started(fake_systemctl("100000000", "499000000"), uid=1000, mono_now=510.0), (
        "a manager running since before the run"
    )
    assert not watch.manager_started(fake_systemctl("500000000", "499000000"), uid=1000, mono_now=900.0), (
        "a run by hand long after the timer's last activation claims no start"
    )
    assert not watch.manager_started(fake_systemctl("0", "499000000"), uid=1000, mono_now=510.0)
    assert not watch.manager_started(fake_systemctl("", ""), uid=1000, mono_now=510.0), "no systemd"


def test_ask_is_one_bounded_never_gated_read(monkeypatch):
    from sessionorc import client

    asked = []
    monkeypatch.setattr(client, "call_sync", lambda method, **kw: asked.append((method, kw)) or "pong")
    assert watch.ask() is True
    assert asked == [("ping", {"_timeout": watch.ASK_SECONDS})]

    def down(method, **kw):
        raise client.AgentUnavailable("host agent not reachable")

    monkeypatch.setattr(client, "call_sync", down)
    assert watch.ask() is False


def test_the_spans_read_as_a_person_says_them():
    assert watch._span(timedelta(minutes=260)) == "4h20m"
    assert watch._span(timedelta(minutes=15)) == "15 min"
    assert watch.WATCH_SILENCE == 2 * EVERY


def test_a_switch_turned_on_mid_outage_tells_the_outage_before_its_recovery(home):
    drive(home, [(0, False, False), (10, False, False)], secrets=None)
    assert drive(home, [(15, False, False), (20, True, False)]) == [
        [watch.silent_line("kmaster", T0)],
        ["shiftlead · the host agent on kmaster answers again (silent 20 min)"],
    ]


# -- push (design §4.10 *Told on the home-screen app too*, TD-1304) ------------------------------------------

DEV = {"id": "a" * 16, "endpoint": "https://push.example.com/s/secret-capability", "keys": {"p256dh": "x", "auth": "y"}}


def push_ch(telegram="both", key="key", devices=(DEV,)):
    return {"secrets": "p/c", "telegram": telegram, "devices": list(devices), "key": key, "sub": "https://x.ts.net"}


def run_push(home, *, secrets="t/c", push=None, took=True, link=""):
    """One run whose silence is told (the manager started): what each channel was handed."""
    tg: list[str] = []
    pushed: list[str] = []

    def push_send(line, ch, log):
        pushed.append(line)
        return took

    watch.run_once(
        home=home,
        now=T0,
        answered=False,
        started=True,
        host="kmaster",
        secrets=secrets,
        link=link,
        push=push,
        send=lambda text, s, log: tg.append(text),
        push_send=push_send,
    )
    return tg, pushed


def test_push_alone_tells_with_telegram_off(home):
    tg, pushed = run_push(home, secrets=None, push=push_ch())
    assert tg == [] and len(pushed) == 1 and pushed[0].startswith("shiftlead · kmaster's user manager")
    assert json.loads((home / "watch.json").read_text())["told"] == ["manager"]


def test_both_sends_on_both_channels_and_telegram_links_the_inbox(home):
    tg, pushed = run_push(home, push=push_ch("both"), link="https://x.ts.net")
    assert len(pushed) == 1 and len(tg) == 1
    assert tg[0] == f"{pushed[0]}\nhttps://x.ts.net/inbox"


def test_fallback_sends_telegram_only_when_no_push_service_took_the_line(home, tmp_path):
    tg, pushed = run_push(home, push=push_ch("fallback"), took=True)
    assert len(pushed) == 1 and tg == []
    tg, pushed = run_push(tmp_path / "other", push=push_ch("fallback"), took=False)
    assert len(pushed) == 1 and tg == pushed


@pytest.mark.parametrize("key", ["no key", "unreadable: bad PEM", None])
def test_a_paused_key_runs_no_child_and_falls_to_telegram(home, tmp_path, key):
    tg, pushed = run_push(home, push=push_ch("fallback", key=key))
    assert pushed == [] and len(tg) == 1
    assert "push not sent: push is paused: " in (home / "watch.log").read_text()
    tg, pushed = run_push(tmp_path / "off", secrets=None, push=push_ch("fallback", key=key))
    assert pushed == [] and tg == []


def test_the_push_channel_is_the_tick_s_reading():
    pcfg = {"on": True, "telegram": "fallback", "secrets": "p/c"}
    pdoc = {"devices": [DEV], "key": "key"}
    ch = watch.push_channel(pcfg, pdoc, "https://x.ts.net")
    assert ch == {
        "secrets": "p/c",
        "telegram": "fallback",
        "devices": [DEV],
        "key": "key",
        "public_key": None,
        "sub": "https://x.ts.net",
    }
    assert watch.push_channel(pcfg, pdoc, "http://10.0.0.2:8000")["sub"] == "https://github.com/ShiftLead/shiftlead"
    assert watch.push_channel({**pcfg, "on": False}, pdoc, "") is None
    assert watch.push_channel(pcfg, {"devices": []}, "") is None
    assert watch.push_channel({**pcfg, "secrets": None}, pdoc, "") is None


def fake_child(rc, *lines, err=""):
    calls = []

    def child(argv, stdin, bound):
        calls.append((argv, json.loads(stdin), bound))
        return rc, "".join(json.dumps(x) + "\n" for x in lines), err

    return child, calls


def test_push_tell_sends_the_line_to_every_device_tagged_watch():
    other = {**DEV, "id": "b" * 16, "endpoint": "https://push.example.com/s/other"}
    child, calls = fake_child(
        0,
        {"key": "key", "public_key": "P"},
        {"device": "a" * 16, "i": 0, "status": 201},
        {"device": "b" * 16, "i": 0, "status": 410},
    )
    logged: list[str] = []
    assert watch.push_tell("shiftlead · a line", push_ch(devices=(DEV, other)), logged.append, child=child) is True
    argv, job, bound = calls[0]
    assert argv[:6] == ["doppler", "run", "--project", "p", "--config", "c"] and argv[-1] == "--push"
    assert job["payloads"] == [{"body": "a line", "path": "/inbox", "tag": "watch"}]
    assert job["sub"] == "https://x.ts.net" and [d["id"] for d in job["devices"]] == ["a" * 16, "b" * 16]
    assert logged == [
        f"push failed on device {'b' * 16}: the push service answered 410",
        "pushed to 1 of 2 devices: shiftlead · a line",
    ]
    assert not any("push.example.com" in x for x in logged), "an endpoint is a capability: never in a log line"


def test_push_tell_a_paused_reading_a_failed_child_and_a_timeout_take_nothing():
    logged: list[str] = []
    child, _ = fake_child(0, {"key": "no key"})
    assert watch.push_tell("shiftlead · x", push_ch(), logged.append, child=child) is False
    assert logged == ["push not sent: push is paused: no key"]
    logged.clear()
    child, _ = fake_child(1, err="Doppler Error: you must be logged in\n")
    assert watch.push_tell("shiftlead · x", push_ch(), logged.append, child=child) is False
    assert logged == [f"push failed on device {'a' * 16}: Doppler Error: you must be logged in"]
    logged.clear()
    child, _ = fake_child(None, {"key": "key", "public_key": "P"})
    assert watch.push_tell("shiftlead · x", push_ch(), logged.append, child=child) is False
    assert logged == [f"push failed on device {'a' * 16}: no answer in 50 s"]


def test_the_child_s_bound_ends_its_whole_group_and_keeps_what_it_printed():
    rc, out, _ = watch._child(["sh", "-c", "echo said; sleep 30"], "", 1.0)
    assert rc is None and out == "said\n"
    assert watch._child(["sh", "-c", "cat; exit 3"], "in", 5.0) == (3, "in", "")


def test_main_tells_by_push_from_push_json_and_never_writes_it(monkeypatch, tmp_path):
    from sessionorc import hosts, settings
    from sessionorc import push as push_mod

    home = tmp_path / "ao"
    monkeypatch.setenv("SHIFTLEAD_HOME", str(home))
    home.mkdir()
    pj = home / "push.json"
    pj.write_text(json.dumps({"key": "key", "public_key": "P", "devices": [DEV]}))
    before = (pj.read_bytes(), pj.stat().st_mtime_ns)
    monkeypatch.setattr(watch, "manager_started", lambda: True)
    monkeypatch.setattr(watch, "ask", lambda: False)
    monkeypatch.setattr(settings, "load", lambda: {"notify": {"push": {"secrets": "p/c"}}})
    monkeypatch.setattr(hosts, "local_host", lambda: hosts.Host(name="kmaster", vscode_host="kmaster"))
    assert push_mod.path() == pj
    got = []
    monkeypatch.setattr(watch, "push_tell", lambda line, ch, log: got.append((line, ch)) or True)
    sent = []
    monkeypatch.setattr(watch.subprocess, "run", lambda argv, **kw: sent.append(argv))
    assert watch.main() == 0
    assert sent == [], "Telegram is off"
    assert len(got) == 1 and got[0][1]["devices"] == [DEV] and got[0][1]["key"] == "key"
    assert (pj.read_bytes(), pj.stat().st_mtime_ns) == before


def test_push_tell_sends_nothing_under_a_key_the_home_has_not_read_and_finds_the_reading_by_its_field():
    logged: list[str] = []
    child, _ = fake_child(0, {"key": "key", "public_key": "NEW"}, {"device": "a" * 16, "i": 0, "status": 201})
    ch = {**push_ch(), "public_key": "T0xE"}
    assert watch.push_tell("shiftlead · x", ch, logged.append, child=child) is False
    assert logged == ["push not sent: the key changed since the home last read it"]
    logged.clear()
    child, _ = fake_child(
        0, {"stray": 1}, {"key": "key", "public_key": "T0xE"}, {"device": "a" * 16, "i": 0, "status": 201}
    )
    assert watch.push_tell("shiftlead · x", ch, logged.append, child=child) is True
    assert logged == ["pushed to 1 of 1 devices: shiftlead · x"]
