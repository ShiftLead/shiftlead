"""TD-1372, design §4.4 *Who lifts the person's gate*: a `decision (paul)` gate is lifted by the person's own
session through the pinned agent-cadence's `ledger.py set … --by <person>` (ledgerboard's target design §1.1,
§3.1, agent-cadence TD-218), which refuses every other session by `agent_sessions.person_session_refusal()`
reading four fields of each record in `ao status --json` — `by_person`, `unattended`, `seat`, `controllers`.
Those fields are ShiftLead's half of the contract: this runs the pinned checker over the records the home
serves, so a renamed or dropped field fails here rather than turning every lift into a refusal (it fails
closed) or every session into a person's."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from types import SimpleNamespace

import pytest
from conftest import park_ticks, pinned_script

from sessionorc.client import LocalClient


def _checker():
    spec = importlib.util.spec_from_file_location("ac_agent_sessions", pinned_script("agent_sessions.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.integration
async def test_the_pinned_lift_check_passes_the_persons_own_session_alone(agent, hookstub, tmp_path, monkeypatch):
    acs = _checker()
    await park_ticks(agent)
    made: dict[str, str] = {}

    async def mk(client, n: str, **kw) -> None:
        (tmp_path / n).mkdir(exist_ok=True)
        made[n] = (await client.call("create", name=n, dir=str(tmp_path / n), adapter="hookstub", **kw))["id"]

    async with LocalClient() as person:
        await mk(person, "own", team="alpha")  # the person's own, in a team
        await mk(person, "lead", supervised=True, capabilities=["control"])
        await mk(person, "seat", seat={"trigger": "team"})
        await mk(person, "later", unattended=True, start_at="2099-01-01T00:00:00Z")
        async with LocalClient(caller=made["lead"]) as lead:
            await mk(lead, "worker", unattended=True)
        listing = await person.call("list")  # what `ao status --json` prints

    def ao(argv, **_kw):
        assert argv == ["ao", "status", "--json"]
        return subprocess.CompletedProcess(argv, 0, json.dumps(listing), "")

    # the checker's own name for the module alone: `subprocess.run` itself is the fixture's tmux too
    monkeypatch.setattr(acs, "subprocess", SimpleNamespace(run=ao, TimeoutExpired=subprocess.TimeoutExpired))
    why = {n: acs.person_session_refusal({"SHIFTLEAD_SESSION": rid}) for n, rid in made.items()}
    assert why.pop("own") is None, "the person's own session lifts"
    for n, w in why.items():
        assert w and "only a person's own session lifts a person's gate" in w, (n, w)
    assert "has controllers" in why["worker"] and "unattended" in why["worker"]
    assert "holds a seat" in why["seat"]
    # no ShiftLead session at all is the person's own terminal; an id the home does not list fails closed
    assert acs.person_session_refusal({}) is None
    assert "does not list" in acs.person_session_refusal({"SHIFTLEAD_SESSION": "ao-gone"})
