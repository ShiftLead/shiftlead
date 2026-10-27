"""The question-seat edge (design §4.10 *to a question seat, from anywhere in the org*, TD-995, TD-1000
slice 1): an `ask` from any session to a record whose seat's trigger is `asks`, one open per sender
per seat counted along the sender's `superseded_by` chain, and that seat's `reply` back to its asker."""

from datetime import UTC, datetime

import pytest
from conftest import park_ticks

from sessionorc import agent_mail, mail, models
from sessionorc.agent_common import RpcError
from sessionorc.client import AgentError, LocalClient
from sessionorc.models import MailEntry

pytestmark = pytest.mark.integration

GRAPH = r"nor an ask to a question seat.*design §4\.10"


def _mk(person, tmp_path):
    async def mk(n: str, **kw):
        d = tmp_path / n
        d.mkdir(exist_ok=True)
        kw.setdefault("unattended", True)
        return (await person.call("create", name=n, dir=str(d), adapter="agentshell", argv=["bash", "--norc"], **kw))[
            "id"
        ]

    return mk


def _ask_in(rec: models.Session, mid: str) -> MailEntry:
    return next(e for e in rec.inbox if e.id == mid)


async def test_an_ask_reaches_another_projects_question_seat_once_at_a_time_and_its_reply_comes_back(agent, tmp_path):
    async with LocalClient() as person:
        mk = _mk(person, tmp_path)
        seat = await mk("seat", team="beta", project="B", seat={"trigger": "asks", "tags": True})
        asker = await mk("asker", team="alpha", project="A")
        mgr = await mk("mgr", team="gamma", project="C", seat={"trigger": "team"})
        assert mail.message_edge(agent.sessions, asker, seat, kind="ask") == "question seat"
        async with LocalClient(caller=asker) as a, LocalClient(caller=seat) as s:
            first = (await a.call("msg", to=seat, text="may samscrape take an entry?", kind="ask"))["entry"]
            # one open question per sender per seat, the refusal naming the first
            with pytest.raises(AgentError, match=rf"{first['id']} is still open"):
                await a.call("msg", to=seat, text="and another?", kind="ask")
            # an ask and nothing else: a note and a steer are the unrelated projects' still
            with pytest.raises(AgentError, match=GRAPH):
                await a.call("msg", to=seat, text="fyi", kind="note")
            with pytest.raises(AgentError, match=GRAPH):
                await a.call("msg", to=seat, text="I will", kind="steer", default="go")
            # a seat whose trigger is not `asks` is no question seat
            with pytest.raises(AgentError, match=GRAPH):
                await a.call("msg", to=mgr, text="q?", kind="ask")
            # an ask citing `sends` is not this edge's: the `msg` RPC reads `cites` as the gate's `carries`
            with pytest.raises(AgentError, match=GRAPH):
                await a.call("msg", to=seat, text="which?", kind="ask", cites=["s-1"])
        # an ask passing an earlier edge (the seat's own team) has no open-question limit
        mate = await mk("mate", team="beta", project="B")
        async with LocalClient(caller=mate) as m:
            await m.call("msg", to=seat, text="one?", kind="ask")
            await m.call("msg", to=seat, text="two?", kind="ask")
        async with LocalClient(caller=asker) as a, LocalClient(caller=seat) as s:
            # the seat's reply lands on the asker's thread, and frees the sender
            reply = (await s.call("msg", text="yes", kind="reply", reply_to=first["id"]))["entry"]
            assert reply["to"] == [asker] and reply["root"] == first["id"]
            second = (await a.call("msg", to=seat, text="a second question", kind="ask"))["entry"]
            # a lapsed ask frees the sender, and the seat's late reply still lands on its thread
            _ask_in(agent.sessions[seat], second["id"]).closed_reason = "expired"
            third = (await a.call("msg", to=seat, text="a third", kind="ask"))["entry"]
            late = (await s.call("msg", text="late, but yes", kind="reply", reply_to=second["id"]))["entry"]
            assert late["to"] == [asker] and late["root"] == second["id"]
            # the seat's reply goes to its asker, never to a session that did not ask
            with pytest.raises(AgentError, match=GRAPH):
                await s.call("msg", to=mgr, text="yes", kind="reply", reply_to=third["id"])
        # a seat's reply to an entry that is no ask is no question-seat reply
        note = await person.call("msg", to=seat, text="from the person", kind="note")
        agent.sessions[seat].inbox[-1].from_ = asker  # as if the asker's note had come another way
        async with LocalClient(caller=seat) as s:
            with pytest.raises(AgentError, match=GRAPH):
                await s.call("msg", text="re", kind="reply", reply_to=note["entry"]["id"])
        # a reply from a record whose seat is not `asks` is refused, an ask in its inbox notwithstanding
        await person.call("msg", to=mgr, text="q?", kind="ask")
        held = agent.sessions[mgr].inbox[-1]
        held.from_ = asker
        async with LocalClient(caller=mgr) as m:
            with pytest.raises(AgentError, match=GRAPH):
                await m.call("msg", text="answer", kind="reply", reply_to=held.id)
        for sid in (seat, asker, mgr, mate):
            await person.call("kill", id=sid)


async def test_a_resumed_asker_is_the_one_that_asked_and_a_filled_seat_still_holds_its_question(agent, tmp_path):
    async with LocalClient() as person:
        mk = _mk(person, tmp_path)
        seat = await mk("seat", team="beta", project="B", seat={"trigger": "asks"})
        asker, resumed = await mk("asker", team="alpha", project="A"), await mk("asker2", team="alpha", project="A")
        async with LocalClient(caller=asker) as a:
            first = (await a.call("msg", to=seat, text="q?", kind="ask"))["entry"]
        old = agent.sessions[asker]
        old.state, old.superseded_by = "closed", resumed
        async with LocalClient(caller=resumed) as r:
            with pytest.raises(AgentError, match=rf"{first['id']} is still open"):
                await r.call("msg", to=seat, text="q again?", kind="ask")
        # the seat's reply to the old record's ask reaches the record continuing it
        async with LocalClient(caller=seat) as s:
            got = await s.call("msg", text="yes", kind="reply", reply_to=first["id"], to=asker)
            assert got["entry"]["to"] == [resumed] and got["forwarded"] == {asker: resumed}
        # a seat filled anew (its mail moved to the new record) still holds the open question
        async with LocalClient(caller=resumed) as r:
            q = (await r.call("msg", to=seat, text="next?", kind="ask"))["entry"]
        filled = await mk("seat2", team="beta", project="B", seat={"trigger": "asks"})
        was = agent.sessions[seat]
        agent.sessions[filled].inbox, was.inbox = was.inbox, []
        was.state, was.superseded_by = "closed", filled
        async with LocalClient(caller=resumed) as r:
            with pytest.raises(AgentError, match=rf"{q['id']} is still open"):
                await r.call("msg", to=seat, text="again?", kind="ask")
        for sid in (seat, filled, asker, resumed):
            await person.call("kill", id=sid)


def test_an_ask_carrying_a_pr_or_cites_passes_no_question_seat():
    seat = models.Session(id="s", name="s", kind="claude", adapter="claude-code", dir="/b", team="beta", project="B")
    seat.seat = {"trigger": "asks"}
    asker = models.Session(id="a", name="a", kind="claude", adapter="claude-code", dir="/a", team="alpha", project="A")
    records = {"s": seat, "a": asker}
    assert mail.message_gate(records, "a", "s", kind="ask") is None
    assert "question seat" in mail.message_gate(records, "a", "s", kind="ask", carries=True)


async def test_a_node_askers_chain_is_read_as_the_home_keys_it(agent):
    """Both chain walks re-address a node record's `superseded_by` as `id@host` (`_from_host`): a node
    sender resumed with its predecessor's ask open is refused, and the seat's reply to that ask reaches
    the resumed node record."""
    seat = models.Session(id="ao-seat", name="seat", kind="claude", adapter="claude-code", dir="/b", team="beta")
    seat.seat, seat.project = {"trigger": "asks"}, "B"
    old = models.Session(id="ao-n", name="n", kind="claude", adapter="claude-code", dir="/a", host="laptop")
    new = models.Session(id="ao-n2", name="n2", kind="claude", adapter="claude-code", dir="/a", host="laptop")
    old.project = new.project = "A"
    old.state, old.superseded_by = "closed", "ao-n2"  # as the node stores it: bare
    agent.sessions[seat.id] = seat
    agent.remote["laptop"] = {old.id: old, new.id: new}
    try:
        open_ask = MailEntry(
            id="m-1", from_="ao-n@laptop", to=[seat.id], at="2026-10-25T00:00:00Z", kind="ask", text="q"
        )
        seat.inbox.append(open_ask)
        g = agent._graph()
        assert mail.chain(g, "ao-n@laptop", agent._successor) == ["ao-n@laptop", "ao-n2@laptop"]
        refused = mail.message_gate(g, "ao-n2@laptop", seat.id, kind="ask", successor=agent._successor)
        assert refused and "m-1 is still open" in refused
        assert (
            mail.message_gate(g, seat.id, "ao-n2@laptop", kind="reply", replied=open_ask, successor=agent._successor)
            is None
        )
        # read raw, the node's chain stops at the bare id and the reply would be refused
        assert mail.message_gate(g, seat.id, "ao-n2@laptop", kind="reply", replied=open_ask) is not None
        # `follow` reads the node's chain the same way: mail to the closed record reaches its successor
        async with LocalClient() as person:
            got = await person.call("msg", to="ao-n@laptop", text="still there?")
        assert got["forwarded"] == {"ao-n@laptop": "ao-n2@laptop"} and new.inbox[-1].text == "still there?"
    finally:
        del agent.sessions[seat.id]
        del agent.remote["laptop"]


async def test_a_team_or_a_repo_addresses_its_question_seat(agent, tmp_path, monkeypatch):
    """`msg`'s `team=` / `repo=` (design §4.10 *A team or a repo as the address*, TD-1000 slice 2): resolved
    at the home from the records, the kind an `ask` unless given, every refusal in the design's words."""
    async with LocalClient() as person:
        mk = _mk(person, tmp_path)
        old = await mk("seat-old", team="beta", project="B", seat={"trigger": "asks", "tags": True})
        seat = await mk("seat", team="beta", project="B", seat={"trigger": "asks", "tags": True})
        asker = await mk("asker", team="alpha", project="A")
        member = await mk("member", team="delta", project="D")
        agent.sessions[old].state, agent.sessions[old].superseded_by = "closed", seat
        agent.sessions[seat].state = "exited"  # on call: the ask fills it
        agent.sessions[seat].repo = agent.sessions[old].repo = "/src/samscrape"
        node = models.Session(id="ao-cm", name="cm-techlead", kind="claude", adapter="claude-code", dir="/w")
        node.team, node.project, node.repo, node.host = "cm", "C", "/home/u/contractmatch", "laptop"
        node.seat, node.state = {"trigger": "asks", "tags": True}, "idle"
        agent.remote["laptop"] = {node.id: node}
        try:
            async with LocalClient(caller=asker) as a:
                got = await a.call("msg", team="beta", text="may samscrape take an entry?")
                assert got["entry"]["kind"] == "ask" and got["delivered"] == [seat]
                assert "fills this seat" in got["read_when"][seat]
                got = await a.call("msg", repo="contractmatch", text="and contractmatch?")
                assert got["delivered"] == ["ao-cm@laptop"]
                with pytest.raises(AgentError, match="no addressee beside it"):
                    await a.call("msg", to=[member], team="beta", text="q?")
                with pytest.raises(AgentError, match="--team or --repo, not both"):
                    await a.call("msg", team="beta", repo="samscrape", text="q?")
                with pytest.raises(
                    AgentError, match=r"no team nosuch has a seat record: the teams with one are beta, cm"
                ):
                    await a.call("msg", team="nosuch", text="q?")
                # a team whose seat was superseded has no seat record, not *no question seat*
                with pytest.raises(AgentError, match=r"no team beta-old has a seat record"):
                    agent.sessions[old].team = "beta-old"
                    await a.call("msg", team="beta-old", text="q?")
                agent.sessions[old].team = "beta"
                with pytest.raises(AgentError, match=r"delta has no question seat — ask the person"):
                    await a.call("msg", team="delta", text="q?")
                # a node whose registry is not read is named, never waited on
                with pytest.raises(
                    AgentError, match=r"no registered repo nosuch: the registries list .*not read: laptop"
                ):
                    await a.call("msg", repo="nosuch", text="q?")
                # a repo a registry lists but no seat serves
                monkeypatch.setattr(
                    agent_mail.hosts, "local_host", lambda: type("H", (), {"repos": lambda self: ["/r/guardians"]})()
                )
                with pytest.raises(AgentError, match=r"guardians has no question seat"):
                    await a.call("msg", repo="guardians", text="q?")
                # a repo two teams serve is refused naming them
                agent.sessions[member].seat, agent.sessions[member].repo = {"trigger": "asks"}, "/x/samscrape"
                with pytest.raises(AgentError, match=r"samscrape is served by beta, delta: name one with --team"):
                    await a.call("msg", repo="samscrape", text="q?")
                # a team's two question seats resolve to its techlead seat, and none such is refused
                second = await mk("second", team="delta", project="D", seat={"trigger": "asks"})
                with pytest.raises(AgentError, match=r"delta has 2 question seats and no techlead seat"):
                    await a.call("msg", team="delta", text="q?")
                agent.sessions[second].seat = {"trigger": "asks", "tags": True}
                got = await a.call("msg", team="delta", text="to the techlead?")
                assert got["delivered"] == [second]
        finally:
            del agent.remote["laptop"]
        for sid in (old, seat, asker, member, second):
            await person.call("kill", id=sid)


async def test_a_session_asks_another_repos_seat_for_a_ledger_entry(agent, tmp_path):
    """`entry_add` from a session (design §4.7 *Entries*, §4.10 *An entry handed to a seat*, TD-1000 slice 3):
    for another repo, the session's own `ask` to its question seat carrying `entry`, not `handed`, with no
    bound, through the gate's open-question limit; for its own repo, or with a draft, refused in words."""
    async with LocalClient() as person:
        mk = _mk(person, tmp_path)
        seat = await mk("seat", team="ss-grind", project="S", seat={"trigger": "asks", "tags": True})
        asker = await mk("asker", team="cm-grind", project="C")
        agent.sessions[seat].repo, agent.sessions[asker].repo = "/src/samscrape", "/src/contractmatch"
        mine = await mk("mine", team="cm-grind", project="C", seat={"trigger": "asks", "tags": True})
        agent.sessions[mine].repo = "/src/contractmatch"
        async with LocalClient(caller=asker) as a, LocalClient(caller=seat) as s:
            got = await a.call("entry_add", repo="samscrape", type="debt", text="parse the new feed", priority="high")
            assert (got["to"], got["repo"], got["team"], got["priority"]) == (seat, "samscrape", "ss-grind", "high")
            held = _ask_in(agent.sessions[seat], got["id"])
            assert held.kind == "ask" and held.from_ == asker and not held.handed and held.bound is None
            assert held.entry == {"repo": "samscrape", "type": "debt", "team": "", "priority": "high"}
            assert agent.sessions[seat].asks_waiting(home=agent.host) == 1
            # one open question to the seat: a second request is refused naming the first
            with pytest.raises(AgentError, match=rf"{got['id']} is still open"):
                await a.call("entry_add", repo="samscrape", type="debt", text="and another")
            # its own repo is written on its branch; a draft is the person's form's
            with pytest.raises(
                AgentError, match=r"cannot add an entry to the ledger this way .*on its branch.*ao finding"
            ):
                await a.call("entry_add", repo="contractmatch", type="debt", text="mine")
            # served by no seat, its own repo is still its branch's (a trailing slash is the same path)
            own_seat = agent.sessions[mine]
            own_seat.repo = "/src/contractmatch/"
            with pytest.raises(AgentError, match=r"cannot add an entry to the ledger this way"):
                await a.call("entry_add", repo="contractmatch", type="debt", text="mine")
            own_seat.seat = None
            with pytest.raises(AgentError, match=r"cannot add an entry to the ledger this way"):
                await a.call("entry_add", repo="contractmatch", type="debt", text="mine")
            with pytest.raises(AgentError, match=r"a draft folder is the person's form's"):
                await a.call("entry_add", repo="samscrape", type="debt", text="w", draft="draft-0123abcd")
            with pytest.raises(AgentError, match=r"a person's own act"):
                await a.call("entry_add", type="debt", text="no repo")
            # the seat's reply closes it, after its PR merged
            await s.call("msg", text="merged #12 as TD-40", kind="reply", reply_to=got["id"])
            assert not held.open and agent.sessions[seat].asks_waiting(home=agent.host) == 0
        # a same-named repo whose seat is on another host is another repo
        node = models.Session(id="ao-cm", name="cm-techlead", kind="claude", adapter="claude-code", dir="/w")
        node.team, node.project, node.repo, node.host = "cm-node", "N", "/src/contractmatch", "laptop"
        node.seat, node.state = {"trigger": "asks", "tags": True}, "idle"
        agent.remote["laptop"] = {node.id: node}
        try:
            async with LocalClient(caller=asker) as a:
                got = await a.call("entry_add", repo="contractmatch", team="cm-node", type="feature", text="w")
                assert got["to"] == "ao-cm@laptop" and got["team"] == "cm-node"
                with pytest.raises(
                    AgentError, match=r"ops has no seat record on samscrape: the teams with one are ss-grind"
                ):
                    await a.call("entry_add", repo="samscrape", team="ops", type="debt", text="w")
        finally:
            del agent.remote["laptop"]
        for sid in (seat, asker, mine):
            await person.call("kill", id=sid)


async def test_a_closed_seat_is_the_address_and_the_ask_fills_it(agent, tmp_path):
    """TD-1128, design §4.10 *A team or a repo as the address*: rule 3 leaves an empty seat `closed`
    (§4.10 *A seat is the exception*), so `--repo` and `--team` resolve to it while its team runs, and
    when nobody of the team is live — the `ask` waits pending, and rule 3 fills the seat for it."""
    await park_ticks(agent)
    async with LocalClient() as person:
        mk = _mk(person, tmp_path)
        seat = await mk(
            "dc-techlead", team="dc-grind", project="D", seat={"trigger": "asks", "tags": True},
            supervised=True, prompt="the seat's brief",
        )  # fmt: skip
        grinder = await mk("dc-grinder", team="dc-grind", project="D")
        asker = await mk("cm-session", team="cm-grind", project="C")
        agent.sessions[seat].repo, agent.sessions[grinder].repo = "/src/dev-cadence", "/src/dev-cadence"
        agent.sessions[asker].repo = "/src/contractmatch"
        await person.call("close", id=seat)  # rule 3's close between questions
        rec = agent.sessions[seat]
        assert rec.state == "closed"
        assert (await agent._question_seat(team="dc-grind")) is rec, "the team runs, its seat closed"
        # a closed seat rule 3 never fills is no address: an ask to it would wait on nothing
        for field, value in (("sit_out", {"at": "t"}), ("closed_for", {"why": "sit_out"}), ("suspended", {"at": "t"})):
            setattr(rec, field, value)
            with pytest.raises(RpcError, match=r"dc-grind has no question seat"):
                await agent._question_seat(team="dc-grind")
            setattr(rec, field, None)
        rec.supervised = False
        with pytest.raises(RpcError, match=r"dc-grind has no question seat"):
            await agent._question_seat(team="dc-grind")
        rec.supervised = True
        async with LocalClient(caller=asker) as a:
            got = await a.call("entry_add", repo="dev-cadence", type="debt", text="the address refuses a closed seat")
        assert got["to"] == seat and _ask_in(rec, got["id"]).open
        # nobody of the team live (stopped): the address still resolves, and the ask still fills it
        await person.call("kill", id=grinder)
        agent.sessions[grinder].state = "closed"
        assert (await agent._question_seat(repo="dev-cadence")) is rec
        await agent._keep_running(datetime.now(UTC))
        new = agent.sessions[seat]
        assert new is not rec and [r["why"] for r in new.restarts][-1:] == ["fill"], "the ask filled the seat"
        assert _ask_in(new, got["id"]).open, "and the filled seat holds the question"
        for sid in (seat, grinder, asker):
            await person.call("kill", id=sid)


def test_a_teams_question_seat_is_live_then_on_call_then_closed():
    def rec(n: str, state: str, tags: bool = True) -> models.Session:
        s = models.Session(id=f"ao-{n}", name=n, kind="claude", adapter="claude-code", dir="/w", state=state)
        s.seat = {"trigger": "asks", **({"tags": True} if tags else {})}
        return s

    live, on_call, closed = rec("a", "idle"), rec("b", "exited"), rec("c", "closed")
    one = agent_mail.MailMixin._one_seat
    assert one("t", [closed, on_call, live]) is live
    assert one("t", [closed, on_call]) is on_call
    assert one("t", [closed]) is closed
    assert one("t", [closed, rec("d", "idle", tags=False)]) is closed, "the techlead seat wins among two"
