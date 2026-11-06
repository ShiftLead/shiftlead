"""Every mode change is stamped and logged (design §4.5 *A taken-over member*, §4.5a the Session card's
*mode* row, §4.4a; TD-1439, a build of TD-1434)."""

from datetime import UTC, datetime, timedelta

import pytest
from test_link import Acts, at_home, home, node_agent, until  # noqa: F401 — `home` is a fixture

from sessionorc.client import LocalClient
from shiftlead.ui.cards import mode_line


def _d(tmp_path, name: str) -> str:
    """One agent session per directory (§9 invariant 2): each of a test's sessions gets its own."""
    d = tmp_path / name
    d.mkdir(exist_ok=True)
    return str(d)


async def test_a_flip_stamps_all_three_and_logs_it_and_a_same_mode_call_stamps_nothing(agent, tmp_path, caplog):
    async with LocalClient() as person:
        s = await person.call("create", name="m", dir=_d(tmp_path, "m"), adapter="agentshell", unattended=True)
        sid = s["id"]
        # a start names nobody: its `created`, `start`, no `mode_by`
        assert (s["mode_at"], s["mode_by"], s["mode_via"]) == (s["created"], None, "start")
        with caplog.at_level("INFO", logger="shiftlead.agent"):
            v = await person.call("set_mode", id=sid, unattended=False, via="focus")
        assert v["mode_by"] == "person" and v["mode_via"] == "focus" and v["mode_at"] >= s["created"]
        assert f"{sid}: mode interactive by person via focus" in caplog.text
        stamped = v["mode_at"]
        # the same mode again writes nothing: the stamp names the last real change
        caplog.clear()
        with caplog.at_level("INFO", logger="shiftlead.agent"):
            again = await person.call("set_mode", id=sid, unattended=False, via="cli")
        assert (again["mode_at"], again["mode_via"]) == (stamped, "focus")
        assert "mode interactive" not in caplog.text
        # an unknown `via` is dropped to none; `ao mode`'s own word is kept
        assert (await person.call("set_mode", id=sid, unattended=True, via="telegram"))["mode_via"] is None
        assert (await person.call("set_mode", id=sid, unattended=False, via="cli"))["mode_via"] == "cli"
        await person.call("kill", id=sid)


async def test_a_session_callers_id_lands_in_mode_by(agent, tmp_path):
    async with LocalClient() as person:
        lead = await person.call("create", name="lead", dir=_d(tmp_path, "lead"), adapter="agentshell", argv=["bash"])
        await person.call("set_grants", id=lead["id"], add=["control"])
        async with LocalClient(caller=lead["id"]) as as_lead:
            w = await as_lead.call("create", name="w", dir=_d(tmp_path, "w"), adapter="agentshell", unattended=True)
            v = await as_lead.call("set_mode", id=w["id"], unattended=False, via="card")
        assert (v["mode_by"], v["mode_via"]) == (lead["id"], "card")
        for x in (w, lead):
            await person.call("kill", id=x["id"])


async def test_the_persons_own_shell_stamps_person(agent, tmp_path):
    async with LocalClient() as person:
        sh = await person.call("create", name="sh", dir=_d(tmp_path, "sh"), adapter="shell")
        w = await person.call("create", name="w", dir=_d(tmp_path, "w"), adapter="agentshell", unattended=True)
        async with LocalClient(caller=sh["id"]) as as_shell:
            v = await as_shell.call("set_mode", id=w["id"], unattended=False, via="cli")
        assert (v["mode_by"], v["mode_via"]) == ("person", "cli")
        for x in (w, sh):
            await person.call("kill", id=x["id"])


async def test_a_scheduled_record_is_stamped_at_its_writing(agent, tmp_path):
    later = (datetime.now(UTC) + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    async with LocalClient() as person:
        s = await person.call(
            "create", name="later", dir=_d(tmp_path, "later"), adapter="agentshell", unattended=True, start_at=later
        )
        assert s["state"] == "scheduled"
        assert (s["mode_at"], s["mode_by"], s["mode_via"]) == (s["created"], None, "start")
        await person.call("kill", id=s["id"])  # a scheduled record's kill is its Cancel


async def test_a_node_members_flip_stamps_the_homes_copy_and_forwards_no_via(home, hookstub, tmp_path, monkeypatch):  # noqa: F811
    async with node_agent(tmp_path, monkeypatch, home.dial_command()) as node:
        acts = Acts(node, monkeypatch)
        async with LocalClient() as c:
            w = await c.call("create", name="w", dir=_d(tmp_path, "w"), adapter=hookstub.name, unattended=True)
        address = f"{w['id']}@laptop"
        await until(home, address, lambda v: v is not None and v["state"] != "unreachable")
        async with LocalClient(sock=home.dir / "agent.sock") as person:
            lead = await person.call(
                "create", name="lead", dir=_d(tmp_path, "lead"), adapter="agentshell", argv=["bash"]
            )
            await person.call("set_grants", id=lead["id"], add=["control"])
            await person.call("set_controllers", id=address, add=[lead["id"]])
            async with LocalClient(sock=home.dir / "agent.sock", caller=lead["id"]) as as_lead:
                v = await as_lead.call("set_mode", id=address, unattended=False, via="focus")
            assert acts.taken[-1]["rpc"] == "set_mode" and "via" not in acts.taken[-1]["params"]
            # the home's copy names the lead in the home's form; the node's own record carries no stamp
            assert (v["mode_by"], v["mode_via"]) == (lead["id"], "focus") and v["mode_at"]
            assert node.sessions[w["id"]].mode_by is None and node.sessions[w["id"]].mode_via is None
            got = await at_home(home, address)
            assert (got["mode_by"], got["mode_via"]) == (lead["id"], "focus")
            # a person's flip from the home names the person
            v = await person.call("set_mode", id=address, unattended=True, via="cli")
            assert (v["mode_by"], v["mode_via"]) == ("person", "cli")
            # a node member created through the home reads *from its start* on the home's copy
            n = await person.call(
                "create", name="w2", dir=_d(tmp_path, "w2"), adapter=hookstub.name, unattended=False, host="laptop"
            )
            assert (n["mode_by"], n["mode_via"]) == (None, "start") and n["mode_at"] == n["created"]
            for x in (n["id"], address, lead["id"]):
                await person.call("kill", id=x)


@pytest.mark.parametrize(
    ("rec", "want"),
    [
        (
            {"unattended": False, "mode_at": "2026-11-06T05:41:00Z", "mode_by": "person", "mode_via": "focus"},
            r"interactive since (\w{3} )?\d\d:\d\d · by you from Focus",
        ),
        (
            {"unattended": True, "mode_at": "2026-11-06T05:41:00Z", "mode_via": "start"},
            r"unattended since (\w{3} )?\d\d:\d\d · from its start",
        ),
        (
            {"unattended": False, "mode_at": "2026-11-06T05:41:00Z", "mode_by": "ao-x-lead", "mode_via": "card"},
            r"interactive since (\w{3} )?\d\d:\d\d · by lead from its card",
        ),
        (
            {"unattended": False, "mode_at": "2026-11-06T05:41:00Z", "mode_by": "ao-x-gone", "mode_via": "inbox"},
            r"interactive since (\w{3} )?\d\d:\d\d · by ao-x-gone from the Inbox",
        ),
        (
            {"unattended": True, "mode_at": "2026-11-06T05:41:00Z", "mode_by": "person", "mode_via": "cli"},
            r"unattended since (\w{3} )?\d\d:\d\d · by you by `ao mode`",
        ),
        (
            {"unattended": False, "mode_at": "2026-11-06T05:41:00Z", "mode_by": "person"},
            r"interactive since (\w{3} )?\d\d:\d\d · by you",
        ),
        ({"unattended": True}, r"unattended since before this was recorded"),
        ({"unattended": False, "agent": False, "mode_at": "2026-11-06T05:41:00Z"}, r"interactive"),
    ],
)
def test_the_session_cards_mode_row_draws_each_wording(rec, want):
    import re

    assert re.fullmatch(want, mode_line(rec, {"ao-x-lead": {"name": "lead"}}))
