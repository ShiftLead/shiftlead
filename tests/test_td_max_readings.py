"""td-max's held extras in the readings (design §4.9 *Scaling with the work*, *An extra*; TD-1545 slice 5): the
wound-down and finished readings pass over a held extra as over a seat and count a live worker extra as a
member; rule 8's finished-alone never names one; a question to a closed extra waits for its fill as a seat's
does, never expired; and a Resume of an extra keeps its `scale` as a seat's keeps its `seat`."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from conftest import park_ticks
from test_mail import _mk

from sessionorc import paths, work
from sessionorc.client import LocalClient
from sessionorc.models import Session

EXTRA = {"line": "g"}
SAID = {"at": "2026-11-11T05:00:00Z", "why": "nothing pickable"}


def _rec(name: str, state: str, **kw) -> Session:
    return Session(
        id=f"ao-{name}", name=name, kind="agent", adapter="shell", dir="/x", state=state, unattended=True, **kw
    )


@pytest.mark.unit
def test_a_held_extra_is_passed_over_as_a_seat_is():
    assert work.held_extra({"scale": EXTRA, "state": "closed"}) and work.held_extra({"scale": EXTRA, "state": "exited"})
    assert not work.held_extra({"scale": EXTRA, "state": "idle"}) and not work.held_extra({"state": "closed"})
    kept = _rec("g-1", "closed", out_of_work=SAID)
    never = _rec("g-4", "closed", scale=EXTRA)  # held, never filled: it declared nothing
    assert work.team_wound_down([kept, never]) == SAID["at"], "a held extra keeps no team from reading wound down"
    assert work.wound_down([{"name": "g-1", "out_of_work": SAID}, {"name": "g-4", "scale": EXTRA, "state": "closed"}])
    # one declared on an older run and closed held: its old word is no part of the reading
    old = _rec("g-5", "closed", scale=EXTRA, out_of_work={"at": "2026-11-12T00:00:00Z"})
    assert work.team_wound_down([kept, old]) == SAID["at"]


@pytest.mark.unit
def test_finished_counts_a_live_worker_extra_and_passes_over_a_held_one():
    idle = {"name": "g-1", "state": "idle", "unattended": True, "out_of_work": SAID}
    held = {"name": "g-4", "state": "closed", "unattended": True, "scale": EXTRA, "restart_wanted": {"at": "x"}}
    got = work.finished([idle, held])
    assert got is not None and got["why"] == [] and got["restart"] is False, "a held extra blocks nothing"
    live = {"name": "g-5", "state": "idle", "unattended": True, "scale": EXTRA}
    assert work.finished([idle, live])["why"] == ["g-5 idle, not declared"], "a live worker extra is a member"


@pytest.mark.unit
def test_finished_alone_never_names_an_extra():
    up = _rec("g-1", "idle")
    member = _rec("g-2", "closed", out_of_work=SAID)
    extra = _rec("g-4", "closed", out_of_work=SAID, scale=EXTRA)
    assert [r.name for r in work.finished_alone([up, member, extra])] == ["g-2"]


@pytest.mark.integration
async def test_a_question_to_a_closed_extra_waits_for_its_fill(agent, tmp_path):
    async with LocalClient() as person:
        mk = _mk(person, tmp_path)
        lead, w = await mk("lead", unattended=True), await mk("w", unattended=True, scale=EXTRA)
        await person.call("set_controllers", id=w, add=[lead])
        async with LocalClient(caller=lead) as ld:
            ask = (await ld.call("msg", to=w, text="status?", kind="ask"))["entry"]
        await person.call("close", id=w)
        await agent._sweep_mail(datetime.now(UTC))
        mail = (await person.call("get", id=lead))["mail"]
        assert mail["expired"] == [] and mail["addressee_exited"] == [ask["id"]], "an extra held is an empty seat"
        await person.call("kill", id=lead)


@pytest.mark.integration
async def test_a_resume_of_an_extra_keeps_its_scale(agent, hookstub, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        old = await person.call(
            "create", name="g-4", dir=str(tmp_path), adapter="hookstub", unattended=True, supervised=True, scale=EXTRA
        )
        await person.call("hook", session=old["id"], adapter_id="cc-extra")
        await person.call("kill", id=old["id"])
        new = await person.call("create", name="g-4", dir=str(tmp_path), adapter="hookstub", resume="cc-extra")
        assert new["id"] == old["id"] and new["scale"] == EXTRA
        assert json.loads((paths.launch_dir() / f"{new['id']}.json").read_text())["scale"] == EXTRA
        given = await person.call("get", id=new["id"])
        assert given["scale"] == EXTRA
        await person.call("kill", id=new["id"])


class _Node:
    """A node's link that takes a Resume's create and answers with the replica it made: the node's own
    `rpc_create` carried the extra's `scale` from the record it replaced, though the params name none."""

    def __init__(self, record: dict):
        self.record, self.acts = record, []

    async def request(self, method, timeout=None, **params):
        self.acts.append((params["rpc"], params["params"]))
        return {"record": self.record}


async def test_a_nodes_replica_of_a_resumed_extra_keeps_its_scale_in_the_homes_launch_record(agent):
    """TD-1586: the home writes a node session's launch record (§6), from the params and what the node
    made of them; a Resume names no `scale`, so the replica's carried mark goes in, or a replay would
    bring the extra back a plain member (#3281, design §4.9 *An extra*)."""
    from test_link import record

    await park_ticks(agent)
    agent._link_muxes["laptop"] = node = _Node(record(name="g-4", supervised=True, unattended=True, scale=EXTRA))
    try:
        await agent._route_act("create", {"name": "g-4", "dir": "/tmp/x", "resume": "cc-extra"}, None, "laptop")
        assert "scale" not in node.acts[-1][1], "the Resume sent no scale: the node carried it"
        assert agent.remote["laptop"]["ao-x-w"].scale == EXTRA
        made = json.loads((paths.launch_dir() / "ao-x-w@laptop.json").read_text())
        assert made["scale"] == EXTRA, "the launch record carries the replica's scale"
    finally:
        del agent._link_muxes["laptop"]
