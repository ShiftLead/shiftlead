"""td-max's extras as records (design §4.9 *Scaling with the work*, *An extra*; TD-1545 slice 3): `create` takes
`scale: {line}`, writes an extra held as it writes a seat's record, keeps the mark on the record and in the launch
record, and rule 8 never replays a record carrying it."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from conftest import park_ticks, wait_for
from test_anchor_retired import _shell
from test_person_restart import _member, _state

from sessionorc import agent_common, models, paths
from sessionorc.client import AgentError, LocalClient


@pytest.mark.unit
def test_the_mark_is_a_line_name_alone():
    assert agent_common._scale(None) is None
    assert agent_common._scale({"line": " grinder-ao "}) == {"line": "grinder-ao"}
    for bad in ({}, {"line": ""}, {"line": 3}, {"line": "g", "last": "x"}, "grinder-ao", ["grinder-ao"]):
        with pytest.raises(agent_common.RpcError, match="scale is"):
            agent_common._scale(bad)
    assert "scale" in agent_common.LAUNCH_KEYS
    assert "scale" in models.HOME_OWNED


@pytest.mark.integration
async def test_a_held_create_writes_an_extra_closed_with_its_mark_on_the_record_and_launch(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        with pytest.raises(AgentError, match="held writes a seat's or an extra's record alone"):
            await person.call("create", **_shell(tmp_path, "g-4", held=True, scale={"line": "g"}, unattended=False))
        with pytest.raises(AgentError, match="scale is"):
            await person.call("create", **_shell(tmp_path, "g-4", held=True, scale={"line": ""}))
        sid = (await person.call("create", **_shell(tmp_path, "g-4", held=True, scale={"line": " g "})))["id"]
        rec = agent.sessions[sid]
        assert rec.state == "closed" and rec.closer == {"by": "start", "why": "held"}
        assert rec.scale == {"line": "g"} and rec.seat is None
        assert sid not in {p.session for p in agent.tmux.list_panes()}, "no pane"
        launch = json.loads((paths.launch_dir() / f"{agent._address(rec)}.json").read_text())
        assert launch.get("scale") == {"line": "g"}, "every replay carries the mark"
        # a live create keeps it too, as a fill from the launch record does
        live = (await person.call("create", **_shell(tmp_path, "g-5", scale={"line": "g"})))["id"]
        assert agent.sessions[live].scale == {"line": "g"}
        await person.call("kill", id=live)


@pytest.mark.integration
async def test_rule_8_never_replays_an_extra(agent, composerstubs, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        kept = await _member(agent, person, tmp_path, name="kept", team="g")
        extra = await _member(agent, person, tmp_path, name="kept-4", team="g", scale={"line": "kept"})
        for sid in (kept, extra):
            await person.call("kill", id=sid)
            assert await wait_for(lambda sid=sid: _state(agent, sid, "exited"), timeout=5)
    got = [r.id for r in agent._work_replays(list(agent.sessions.values()), datetime.now(UTC))]
    assert got == [kept], "an extra is filled at the work by rules 3 and 14, never replayed by a start"
