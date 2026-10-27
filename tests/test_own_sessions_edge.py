"""The edge between the person's own sessions (design §4.10 *between the person's own sessions*, TD-1042,
TD-1069): two records the person started by hand mail each other in any kind, whatever their team,
project, role, `controllers` or state. The record says so in `by_person`, derived once by the create and
never passed; a record before the field resolves it from being interactive, not supervised and with no
controllers; on a node's record it is the home's, set on its copy from the forwarded create's reply."""

from __future__ import annotations

import pytest
from conftest import park_ticks

from sessionorc import mail
from sessionorc.client import AgentError, LocalClient
from sessionorc.models import Session

GRAPH = r"nor between two sessions the person started by hand"
KINDS = ("note", "ask", "steer", "reply")


def _rec(rid: str, **kw) -> Session:
    base = dict(id=rid, name=rid, kind="interactive", adapter="claude-code", dir=f"/tmp/{rid}", by_person=True)
    return Session(**{**base, **kw})


@pytest.mark.unit
def test_two_of_the_persons_own_records_pass_in_every_kind_and_each_near_miss_does_not():
    records = {
        "a": _rec("a", team="alpha", project="A"),
        "b": _rec("b", team="beta", project="B", controllers=["mgr"]),  # a person's session in a team
        "x": _rec("x", team="gamma", project="C", state="exited"),
        "sh": _rec("sh", adapter="shell"),  # the person's own shell
        "mgr": _rec("mgr", unattended=True, by_person=False, team="beta"),
        "w": _rec("w", by_person=False, controllers=["mgr"]),  # a worker's start without --unattended
        "u": _rec("u", unattended=True),  # later put in `ao mode unattended`
        "seat": _rec("seat", seat={"trigger": "team"}),
        "qs": _rec("qs", seat={"trigger": "asks"}),
    }
    for kind in KINDS:
        for sender, target in (("a", "b"), ("b", "a"), ("a", "x"), ("sh", "a")):
            assert mail.message_edge(records, sender, target, kind=kind) == "own", (kind, sender, target)
            assert mail.message_gate(records, sender, target, kind=kind) is None
        for far in ("w", "u", "seat", "qs"):
            assert mail.message_edge(records, "a", far, kind=kind) != "own", (kind, far)
            assert mail.message_edge(records, far, "a", kind=kind) != "own", (kind, far)
    # an ask to a question seat keeps the seat's edge, and its one open question per sender
    assert mail.message_edge(records, "a", "qs", kind="ask") == "question seat"
    assert mail.message_gate(records, "a", "w", kind="note") is not None
    # an ask carrying a pr or cites is a team's: it passes no own edge
    assert mail.message_edge(records, "a", "b", kind="ask", carries=True) is None
    refused = mail.message_gate(records, "a", "b", kind="ask", carries=True)
    assert refused is not None and GRAPH.replace(r"\.", ".") in refused


@pytest.mark.unit
def test_a_record_before_the_field_resolves_it_from_its_controllers():
    assert mail.by_person(_rec("old", by_person=None))
    assert not mail.by_person(_rec("old", by_person=None, controllers=["ao-lead"]))
    assert not mail.by_person(_rec("old", by_person=None, unattended=True))
    # a lead `ao team start` made before the field: supervised, with no controllers, is no end
    assert not mail.by_person(_rec("lead", by_person=None, supervised=True))
    # an explicit false stays false, whatever the controllers say
    assert not mail.by_person(_rec("w", by_person=False))
    records = {"a": _rec("a"), "old": _rec("old", by_person=None, team="t")}
    assert mail.message_edge(records, "a", "old", kind="note") == "own"
    assert Session.from_dict({k: v for k, v in _rec("o").to_dict().items() if k != "by_person"}).by_person is None


@pytest.mark.integration
async def test_each_start_writes_the_field_as_the_create_derives_it(agent, hookstub, tmp_path, monkeypatch):
    await park_ticks(agent)
    made: dict[str, str] = {}

    async def mk(client, n: str, **kw) -> dict:
        (tmp_path / n).mkdir(exist_ok=True)
        got = await client.call("create", name=n, dir=str(tmp_path / n), adapter="hookstub", **kw)
        made[n] = got["id"]
        return got

    async with LocalClient() as person:
        a = await mk(person, "a", team="alpha", project="A")
        b = await mk(person, "b", team="beta", project="B")
        assert a["by_person"] is True and b["by_person"] is True
        assert (await mk(person, "sup", supervised=True, capabilities=["control"]))["by_person"] is False
        assert (await mk(person, "seat", seat={"trigger": "team"}))["by_person"] is False
        # **Open shell here** on a team member: the badge, no controllers, the person's
        (tmp_path / "sh").mkdir()
        sh = await person.call("create", name="sh", dir=str(tmp_path / "sh"), adapter="shell", team="beta")
        made["sh"] = sh["id"]
        assert sh["by_person"] is True
        # from the person's own shell: the person
        async with LocalClient(caller=sh["id"]) as shell:
            assert (await mk(shell, "fromsh"))["by_person"] is True
        # a session's start, a by_person param on it dropped with a warning
        async with LocalClient(caller=made["sup"]) as lead:
            assert (await mk(lead, "child", by_person=True))["by_person"] is False
            (tmp_path / "subsh").mkdir()
            subsh = await lead.call("create", name="subsh", dir=str(tmp_path / "subsh"), adapter="shell")
            made["subsh"] = subsh["id"]
            assert subsh["by_person"] is False
        # the tick's restarts, fills and replays: in-process, no caller, every one supervised
        (tmp_path / "fill").mkdir()
        rec = await agent.rpc_create(name="fill", dir=str(tmp_path / "fill"), adapter="hookstub", supervised=True)
        made["fill"] = rec["id"]
        assert rec["by_person"] is False
        # a scheduled start is supervised and unattended: no end whatever happens
        later = await mk(person, "later", unattended=True, start_at="2099-01-01T00:00:00Z")
        assert later["by_person"] is False
        assert agent.sessions[later["id"]].by_person is False  # stored, not only resolved in the view

        # the person's resume of a supervised record stays supervised, so it writes false
        await person.call("hook", session=made["sup"], adapter_id="cc-sup")
        await person.call("kill", id=made["sup"])
        again = await person.call("create", name="sup", dir=str(tmp_path / "sup"), adapter="hookstub", resume="cc-sup")
        assert again["supervised"] is True and again["by_person"] is False

        # the two of the person's own, of different teams and projects, mail each other in every kind
        async with LocalClient(caller=made["a"]) as ca, LocalClient(caller=made["b"]) as cb:
            await ca.call("msg", to=made["b"], text="fyi", kind="note")
            q = (await ca.call("msg", to=made["b"], text="which?", kind="ask"))["entry"]
            await cb.call("msg", text="that one", kind="reply", reply_to=q["id"])
            await cb.call("msg", to=made["a"], text="I will", kind="steer", default="go")
            # a session a session started is no end, nor the person's session once put unattended
            with pytest.raises(AgentError, match=GRAPH):
                await ca.call("msg", to=made["child"], text="hi", kind="note")
            agent.sessions[made["b"]].unattended = True
            with pytest.raises(AgentError, match=GRAPH):
                await ca.call("msg", to=made["b"], text="still?", kind="note")
            agent.sessions[made["b"]].unattended = False
            # with b's team's manager in its controllers (§4.9 *A person in the team*), and b exited
            agent.sessions[made["b"]].controllers = [made["sup"]]
            await ca.call("msg", to=made["b"], text="with a manager", kind="note")
            await person.call("kill", id=made["b"])
            await ca.call("msg", to=made["b"], text="exited", kind="note")
            # an ask carrying a pr is a team's
            with pytest.raises(AgentError, match=GRAPH):
                await ca.call("msg", to=made["b"], text="read #1?", kind="ask", pr=1)
            # every pair and depth bound holds
            monkeypatch.setattr(mail, "PAIR_BOUND", 0)
            with pytest.raises(AgentError, match="replying to nothing"):
                await ca.call("msg", to=made["b"], text="bounded", kind="note")
            monkeypatch.setattr(mail, "PAIR_BOUND", None)
            monkeypatch.setattr(mail, "MAILBOX_DEPTH", 1)
            with pytest.raises(AgentError, match="unread entries"):
                await ca.call("msg", to=made["b"], text="full", kind="note")
        # the person's own shell sends on the edge
        monkeypatch.setattr(mail, "MAILBOX_DEPTH", None)
        async with LocalClient(caller=sh["id"]) as shell:
            await shell.call("msg", to=made["a"], text="from the shell", kind="note")
        assert agent.sessions[made["a"]].inbox[-1].text == "from the shell"
        for sid in made.values():
            if agent.sessions.get(sid) is not None and agent.sessions[sid].pane:
                await person.call("kill", id=sid)


@pytest.mark.integration
async def test_a_node_writes_none_and_the_home_sets_its_copy_from_the_forwarded_creates_reply(agent, tmp_path):
    await park_ticks(agent)
    agent.mode, agent.home = "node", "kmaster"
    try:
        (tmp_path / "n").mkdir()
        got = await agent.rpc_create(name="n", dir=str(tmp_path / "n"), adapter="shell")
        assert agent.sessions[got["id"]].by_person is None  # the home's to write
        await agent.rpc_kill(id=got["id"])
        (tmp_path / "s").mkdir()
        later = await agent.rpc_create(
            name="s", dir=str(tmp_path / "s"), adapter="shell", unattended=True, start_at="2099-01-01T00:00:00Z"
        )
        assert agent.sessions[later["id"]].by_person is None  # a scheduled record's too
    finally:
        agent.mode, agent.home = "home", agent.host

    class Node:
        def __init__(self):
            self.acts, self.reply = [], {}

        async def request(self, method, timeout=None, **params):
            self.acts.append(params)
            return self.reply

        async def notify(self, method, **params):
            pass

        def close(self, why="closed"):
            pass

    node = Node()
    agent._link_muxes["laptop"] = node
    agent.links["laptop"] = {"up": True, "since": "t", "why": "linked"}
    lead = "ao-lead"
    agent.sessions[lead] = Session(
        id=lead, name=lead, kind="interactive", adapter="shell", dir="/tmp", unattended=True, capabilities=["control"]
    )

    def written(rid: str, **kw) -> dict:
        r = Session(id=rid, name=rid, kind="interactive", adapter="claude-code", dir=f"/x/{rid}", host="laptop", **kw)
        return r.to_dict()

    async def create(rid: str, caller, *, record: dict, **params) -> Session:
        node.reply = {"record": record, "result": {"id": rid, "host": "laptop"}}
        req = {"name": rid, "dir": f"/x/{rid}", "host": "laptop", "adapter": "claude-code", **params}
        got = await agent._dispatch({"id": 1, "method": "create", "params": req, "caller": caller})
        assert "error" not in got, got
        assert "by_person" not in node.acts[-1]["params"]  # never a param of the forwarded create
        return agent.remote["laptop"][rid]

    try:
        # a report landing before the reply: absent, the resolver covering the gap
        agent._take_records("laptop", [written("ao-p")], whole=False)
        assert agent.remote["laptop"]["ao-p"].by_person is None and mail.by_person(agent.remote["laptop"]["ao-p"])
        assert (await create("ao-p", None, record=written("ao-p"))).by_person is True
        # the home's value, never the node's: a session's forwarded create writes false
        assert (await create("ao-s", lead, record=written("ao-s", by_person=True))).by_person is False
        # supervised and seat as the reply carries the written record, the seat sent where it carries none
        assert (await create("ao-v", None, record=written("ao-v", supervised=True))).by_person is False
        assert (await create("ao-t", None, record=written("ao-t"), seat={"trigger": "team"})).by_person is False
        # and a node's report keeps it: home-owned
        agent._take_records("laptop", [written("ao-p", by_person=False)], whole=False)
        assert agent.remote["laptop"]["ao-p"].by_person is True
        # a node's record reads the same on the gate, addressed `id@host`
        mine = Session(id="ao-mine", name="mine", kind="interactive", adapter="claude-code", dir="/m", by_person=True)
        agent.sessions[mine.id] = mine
        assert mail.message_edge(agent._graph(), mine.id, "ao-p@laptop", kind="steer") == "own"
        assert mail.message_edge(agent._graph(), mine.id, "ao-s@laptop", kind="note") is None
    finally:
        del agent._link_muxes["laptop"]
