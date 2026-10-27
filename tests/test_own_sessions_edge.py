"""The edge between the person's own sessions (design §4.10 *between the person's own sessions*, TD-1042,
TD-1069, widened by TD-1116): a record the person started by hand, with no controllers, mails any record in
any kind, whatever its team, project, role or state, and a `reply` comes back along it; one with a
controller reaches another own end alone. What lands reads `[person-session]`. The record says so in
`by_person`, derived once by the create and never passed; a record before the field resolves it from being
interactive, not supervised and with no controllers; on a node's record it is the home's, set on its copy
from the forwarded create's reply."""

from __future__ import annotations

import pytest
from conftest import park_ticks

from sessionorc import mail
from sessionorc.client import AgentError, LocalClient
from sessionorc.models import MailEntry, Session

GRAPH = r"nor from a session the person started by hand, or a reply to one"
NO_INBOX = r"a question needs an inbox to answer into"
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
        # with no controllers, to any record: a worker, an unattended member, a seat holder
        for far in ("w", "u", "seat", "mgr"):
            assert mail.message_edge(records, "a", far, kind=kind) == "own", (kind, far)
            # none of them is an own end, so nothing goes back but a reply (below)
            assert mail.message_edge(records, far, "a", kind=kind) != "own", (kind, far)
        # b names a controller: it keeps the first reach, to another own end alone
        for far in ("w", "u", "seat"):
            assert mail.message_edge(records, "b", far, kind=kind) is None, (kind, far)
    assert mail.message_edge(records, "a", "qs", kind="note") == "own"
    # an ask to a question seat keeps the seat's edge, and its one open question per sender
    assert mail.message_edge(records, "a", "qs", kind="ask") == "question seat"
    assert mail.message_gate(records, "a", "w", kind="note") is None
    assert mail.message_gate(records, "b", "w", kind="note") is not None
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
            # a session a session started is no end, but a reaches it (TD-1116), and its reply comes back
            asked = (await ca.call("msg", to=made["child"], text="hold that", kind="steer", default="hold"))["entry"]
            async with LocalClient(caller=made["child"]) as cc:
                got = await cc.call("inbox")
                mark = {e["id"]: e["from_role"] for e in got["entries"]}
                assert mark[asked["id"]] == "person-session"
                # and the wake's mail header, where an unattended member first weighs the text
                rec = agent.sessions[made["child"]]
                landed = next(e for e in rec.inbox if e.id == asked["id"])
                assert agent._header(rec, landed)["from_role"] == "person-session"
                await cc.call("msg", text="held", kind="reply", reply_to=asked["id"])
                # its own note to a passes no edge
                with pytest.raises(AgentError, match=GRAPH):
                    await cc.call("msg", to=made["a"], text="unprompted", kind="note")
            # the person's session once put unattended is no sender
            agent.sessions[made["b"]].unattended = True
            async with LocalClient(caller=made["b"]) as cb2:
                with pytest.raises(AgentError, match=GRAPH):
                    await cb2.call("msg", to=made["child"], text="still?", kind="note")
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
            # …a note alone: nothing could answer into it (TD-1116), to a member or another own end
            for target in (made["a"], made["child"]):
                with pytest.raises(AgentError, match=NO_INBOX):
                    await shell.call("msg", to=target, text="which?", kind="steer", default="this")
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
        # a session's forwarded start is no end: reached as any record is, it sends nothing back on the edge
        assert mail.message_edge(agent._graph(), mine.id, "ao-s@laptop", kind="note") == "own"
        assert mail.message_edge(agent._graph(), "ao-s@laptop", mine.id, kind="note") is None
    finally:
        del agent._link_muxes["laptop"]


def _entry(eid: str, sender: str, kind: str = "note") -> MailEntry:
    return MailEntry(id=eid, from_=sender, to=["x"], at="2026-10-27T00:00:00Z", kind=kind, text="t")


@pytest.mark.unit
def test_a_member_replies_back_along_the_edge_and_nothing_else_goes_back():
    records = {
        "a": _rec("a"),  # the person's session, no controllers
        "a2": _rec("a2"),
        "b": _rec("b", controllers=["mgr"]),  # the person's session in a team
        "mgr": _rec("mgr", unattended=True, by_person=False),
        "w": _rec("w", unattended=True, by_person=False, team="grind", controllers=["mgr"]),
        "u": _rec("u", unattended=True),  # once the person's, now unattended
    }
    records["a"].superseded_by = "a2"
    for kind in ("note", "ask", "steer"):
        got = _entry("m-1", "a", kind)
        # the member's reply on that thread, back to the sender and to its successor
        for back in ("a", "a2"):
            assert mail.message_edge(records, "w", back, kind="reply", replied=got) == "own", (kind, back)
            assert mail.message_gate(records, "w", back, kind="reply", replied=got) is None
    # the member's unprompted note, ask or steer to it passes no edge
    for kind in ("note", "ask", "steer"):
        assert mail.message_gate(records, "w", "a", kind=kind) is not None
    # a reply to an entry whose sender's record is gone passes no own edge
    assert mail.message_edge(records, "w", "a", kind="reply", replied=_entry("m-2", "gone")) is None
    # a reply to an own end with a controller is refused, unless the replier is an own end too
    from_b = _entry("m-3", "b")
    assert mail.message_gate(records, "w", "b", kind="reply", replied=from_b) is not None
    assert mail.message_edge(records, "a", "b", kind="reply", replied=from_b) == "own"
    # a sender later put in `ao mode unattended` passes no own edge, and reads `other`
    assert mail.message_edge(records, "u", "w", kind="note") is None
    assert mail.message_edge(records, "w", "u", kind="reply", replied=_entry("m-4", "u")) is None
    assert mail.from_role(records, "w", "u") == "other"
    # an own end with a controller reaches another own end, landing `other`, and no member
    assert mail.message_edge(records, "b", "a", kind="note") == "own"
    assert mail.from_role(records, "a", "b") == "other"
    assert mail.message_edge(records, "b", "w", kind="note") is None


@pytest.mark.unit
def test_from_role_reads_person_session_live_and_controller_first():
    records = {
        "a": _rec("a"),
        "w": _rec("w", unattended=True, by_person=False, controllers=["mgr"]),
        "w2": _rec("w2", unattended=True, by_person=False, controllers=["a"]),
        "sh": _rec("sh", adapter="shell"),
    }
    assert mail.from_role(records, "w", "a") == "person-session"
    assert mail.from_role(records, "w", "sh") == "person-session"  # a shell's note reads it too
    assert mail.from_role(records, "w2", "a") == "controller"
    records["a"].unattended = True  # since put unattended: its earlier mail reads `other` from then on
    assert mail.from_role(records, "w", "a") == "other"
    records["a"].unattended, records["a"].controllers = False, ["mgr"]  # since put under a lead
    assert mail.from_role(records, "w", "a") == "other"


@pytest.mark.unit
def test_the_persons_shell_sends_a_note_alone_on_the_edge():
    records = {
        "sh": _rec("sh", adapter="shell", team="grind"),  # **Open shell here** on a member: its badge
        "a": _rec("a"),
        "w": _rec("w", unattended=True, by_person=False, controllers=["mgr"]),
        "mate": _rec("mate", unattended=True, by_person=False, team="grind", controllers=["mgr"]),
        "qs": _rec("qs", unattended=True, by_person=False, seat={"trigger": "asks"}),
    }
    for target in ("w", "a"):
        assert mail.message_gate(records, "sh", target, kind="note", agentless=True) is None
        for kind in ("ask", "steer"):
            refused = mail.message_gate(records, "sh", target, kind=kind, agentless=True)
            assert refused is not None and NO_INBOX in refused, (target, kind)
    # an edge before or after `own` keeps its rule
    assert mail.message_edge(records, "sh", "qs", kind="ask") == "question seat"
    assert mail.message_gate(records, "sh", "qs", kind="ask", agentless=True) is None
    assert mail.message_edge(records, "sh", "mate", kind="ask") == "team"
    assert mail.message_gate(records, "sh", "mate", kind="ask", agentless=True) is None
    # a session the person started sends every kind
    for kind in ("ask", "steer"):
        assert mail.message_gate(records, "a", "w", kind=kind) is None


@pytest.mark.unit
def test_an_ask_to_a_question_seat_is_the_seats_and_a_pr_ask_is_a_teams():
    records = {
        "a": _rec("a"),
        "qs": _rec("qs", unattended=True, by_person=False, seat={"trigger": "asks"}),
        "w": _rec("w", unattended=True, by_person=False, controllers=["mgr"]),
    }
    assert mail.message_edge(records, "a", "qs", kind="ask") == "question seat"
    records["qs"].inbox.append(_entry("m-open", "a", "ask"))
    refused = mail.message_gate(records, "a", "qs", kind="ask")
    assert refused is not None and "m-open" in refused
    # a note and a steer to the seat holder pass as own
    for kind in ("note", "steer"):
        assert mail.message_gate(records, "a", "qs", kind=kind) is None
        assert mail.message_edge(records, "a", "qs", kind=kind) == "own"
    assert mail.message_gate(records, "a", "w", kind="ask", carries=True) is not None
