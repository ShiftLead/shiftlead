"""A question the work settled closes itself (design §4.10, TD-1469, TD-1453's third build): on the home's tick an
open `ask` or `steer` to the person closes `merged` when the PR it carries merged in its repo, or `settled` when the
entry its `about` names was archived after it was asked, `settled_by` the closing PR; a question passed up on a
thread takes the `pr` (and the empty stamp's `repo`) of the ask it closes; the FYI, the Sent fold and `ao inbox
--sent` word it *settled — #164 merged* or *settled — TD-221 archived (#164)*, *(no PR)*."""

import argparse
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sessionorc import held, mail
from sessionorc.client import LocalClient
from sessionorc.models import PERSON, MailEntry

pytestmark = pytest.mark.integration


def _registry(tmp_path, *repos) -> None:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / "repos.txt").write_text("".join(f"{r}\n" for r in repos))
    (home / "hosts.yml").write_text(f"local:\n  repos_registry: {home / 'repos.txt'}\n")


async def _mk(person, d: Path, name: str, **kw) -> str:
    d.mkdir(parents=True, exist_ok=True)
    kw.setdefault("unattended", True)
    got = await person.call("create", name=name, dir=str(d), adapter="agentshell", argv=["bash", "--norc"], **kw)
    return got["id"]


def _reading(*, merged=(), closed=(), completed=(), entries=()) -> dict:
    prs = [{"number": n, "state": "merged"} for n in merged] + [{"number": n, "state": "closed"} for n in closed]
    return {"prs": {"open": [], "recent": prs}, "completed": list(completed), "ledger": {"entries": list(entries)}}


def _copies(agent, mid):
    out = [e for e in agent.person_inbox if e.id == mid]
    for s in agent.sessions.values():
        out += [e for e in [*s.inbox, *s.outbox] if e.id == mid]
    return out


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# -- the decision, read from the repo's facts alone ----------------------------------------------------------------


def _q(**kw) -> MailEntry:
    base = {"id": "m-1", "from_": "w", "to": [PERSON], "at": "2026-11-06T12:00:00Z", "kind": "ask", "text": "?"}
    return MailEntry(**{**base, **kw})


def test_a_merged_pr_settles_and_a_closed_or_unread_one_does_not():
    assert mail.work_settles(_q(pr=164), _reading(merged=[164]), []) == ("merged", 164)
    assert mail.work_settles(_q(pr=164), _reading(closed=[164]), []) is None, "closed unmerged settles nothing"
    assert mail.work_settles(_q(pr=164), _reading(), []) is None, "in neither list: the person's"
    assert mail.work_settles(_q(pr=164), None, []) is None, "no reading of its repo: nothing"
    steer = _q(kind="steer", about="#164")
    assert mail.work_settles(steer, _reading(merged=[164]), []) == ("merged", 164), "a steer by its `about` alone"
    assert mail.work_settles(_q(kind="steer", pr=164), _reading(merged=[164]), []) is None, "only an ask carries pr"


def test_an_archive_after_the_question_settles_it_and_one_before_does_not():
    after = {"id": "TD-221", "closed": "2026-11-06T13:00:00+00:00", "pr": 164}
    assert mail.work_settles(_q(about="TD-221"), _reading(completed=[after]), []) == ("settled", 164)
    before = {**after, "closed": "2026-11-06T11:00:00+00:00"}
    assert mail.work_settles(_q(about="TD-221"), _reading(completed=[before]), []) is None
    push = {**after, "pr": None}
    assert mail.work_settles(_q(about="TD-221"), _reading(completed=[push]), []) == ("settled", None)
    reopened = _reading(completed=[after], entries=[{"id": "TD-221"}])
    assert mail.work_settles(_q(about="TD-221"), reopened, []) is None, "open again: nothing settled"
    both = _reading(merged=[164], completed=[after])
    assert mail.work_settles(_q(pr=164, about="TD-221"), both, []) == ("merged", 164), "merged first where both apply"


def test_with_no_closing_commit_the_resolved_day_on_the_local_calendar_decides():
    local = datetime.now().astimezone().tzinfo
    day = datetime(2026, 11, 6, tzinfo=local)
    arch = [{"id": "TD-221", "fields": {"resolved": "2026-11-06 — #164"}}]
    same = _q(about="TD-221", at=_iso(day.replace(hour=12)))
    assert mail.work_settles(same, _reading(), arch) is None, "the Resolved day itself settles nothing"
    early = _q(about="TD-221", at=_iso(day.replace(hour=0, minute=5)))
    assert mail.work_settles(early, _reading(), arch) is None, "00:05 local on the Resolved day: nothing"
    eve = _q(about="TD-221", at=_iso(day.replace(hour=23, minute=55) - timedelta(days=1)))
    assert mail.work_settles(eve, _reading(), arch) == ("settled", None), "the day before is settled"


def test_the_words_the_fyi_the_sent_fold_and_the_cli_read():
    assert mail.settled_words(_q(pr=164, closed_reason="merged")) == "settled — #164 merged"
    assert mail.settled_words({"kind": "steer", "about": "#164", "closed_reason": "merged"}) == "settled — #164 merged"
    got = _q(about="TD-221", closed_reason="settled", settled_by=164)
    assert mail.settled_words(got) == "settled — TD-221 archived (#164)"
    assert mail.settled_words(_q(about="TD-221", closed_reason="settled")) == "settled — TD-221 archived (no PR)"
    assert mail.settled_words(_q(closed_reason="replied")) is None


def test_the_sent_fold_and_the_focus_inbox_word_it_as_the_fyi_does():
    js = (Path(__file__).parents[1] / "src/shiftlead/ui/static/app.js").read_text()
    assert 'r === "merged" || r === "settled" ? AO.settledWords(e)' in js, "the Sent fold (§4.5a)"
    assert 'e.closed_reason === "merged" || e.closed_reason === "settled" ? esc(AO.settledWords(e))' in js
    node = shutil.which("node")
    if node is None:
        return
    start = js.index("AO.settledWords = function")
    body = js[start : js.index("\n  };\n", start) + 5]
    script = (
        "const AO = {};\n" + body + "\n"
        'console.log(AO.settledWords({kind: "ask", pr: 164, closed_reason: "merged"}));\n'
        'console.log(AO.settledWords({kind: "ask", about: "TD-221", closed_reason: "settled", settled_by: 164}));\n'
        'console.log(AO.settledWords({kind: "ask", about: "TD-221", closed_reason: "settled"}));\n'
    )
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30, check=True).stdout
    assert out.splitlines() == [
        "settled — #164 merged",
        "settled — TD-221 archived (#164)",
        "settled — TD-221 archived (no PR)",
    ]


def test_ao_inbox_sent_prints_the_words(monkeypatch, capsys):
    from shiftlead import cli

    entries = [
        {"id": "m-1", "kind": "ask", "to": [PERSON], "at": "x", "text": "merge?", "pr": 164, "closed_reason": "merged"},
        {"id": "m-2", "kind": "ask", "to": [PERSON], "at": "x", "text": "?", "about": "TD-221"},
    ]
    entries[1]["closed_reason"] = "settled"
    monkeypatch.setattr(cli, "call_sync", lambda *a, **k: {"id": "w", "entries": entries})
    cli._sent(argparse.Namespace(unread=False, json=False))
    out = capsys.readouterr().out
    assert "· settled — #164 merged" in out and "· settled — TD-221 archived (no PR)" in out


def test_the_inbox_row_draws_the_words():
    from shiftlead.ui.common import templates

    macro = templates.env.get_template("inbox_row.html").module.state_line
    row = {"closed_reason": "settled", "about": "TD-221", "settled_by": 164, "kind": "ask"}
    assert str(macro(row)).strip() == "settled — TD-221 archived (#164)"
    assert str(macro({"closed_reason": "merged", "pr": 164, "kind": "ask"})).strip() == "settled — #164 merged"


# -- the tick's pass -----------------------------------------------------------------------------------------------


async def test_a_merged_pr_closes_its_ask_on_the_tick_and_a_closed_one_does_not(agent, tmp_path):
    alpha = tmp_path / "alpha"
    alpha.mkdir()
    _registry(tmp_path, alpha)
    async with LocalClient() as person:
        w = await _mk(person, alpha / ".claude" / "worktrees" / "g", "g")
        async with LocalClient(caller=w) as c:
            a = (await c.call("msg", to="person", text="merge #164?", kind="ask", about="TD-9"))["entry"]["id"]
            b = (await c.call("msg", to="person", text="merge #165?", kind="ask", about="TD-8"))["entry"]["id"]
        agent._mark(a, pr=164)
        agent._mark(b, pr=165)
        agent._repos = {str(alpha): _reading(merged=[164], closed=[165])}
        await agent._settle_by_work()
        assert all(e.closed_reason == "merged" and e.closed_at and not e.open for e in _copies(agent, a))
        assert len(_copies(agent, a)) >= 2, "the person's copy and the sender's outbox"
        assert all(e.open for e in _copies(agent, b)), "closed unmerged settles nothing"
        assert not any(e.owes for e in _copies(agent, a)), "nobody answered: nothing owed"
        notes = [e for e in agent.sessions[w].inbox if e.from_ == "system"]
        assert notes == [], "nobody is told"
        first = next(e for e in agent.person_inbox if e.id == a).closed_at
        await agent._settle_by_work()
        assert next(e for e in agent.person_inbox if e.id == a).closed_at == first, "closed once"
        async with LocalClient(caller=w) as c:  # a new ask about a PR already merged: not refused, closed next tick
            late = (await c.call("msg", to="person", text="merge #164 now?", kind="ask", about="#164"))["entry"]["id"]
        assert all(e.open for e in _copies(agent, late))
        await agent._settle_by_work()
        assert [e.closed_reason for e in agent.person_inbox if e.id == late] == ["merged"]
        # a closed `merged` entry is pruned by retention from its `closed_at`
        got = next(e for e in agent.person_inbox if e.id == a)
        got.read_at = got.closed_at = _iso(datetime.now(UTC) - timedelta(days=30))
        await agent._sweep_mail(datetime.now(UTC))
        assert a not in [e.id for e in agent.person_inbox]
        await person.call("kill", id=w)


async def test_an_ask_about_another_repos_pr_is_not_closed_by_this_repos_merge(agent, tmp_path):
    alpha = tmp_path / "alpha"
    alpha.mkdir()
    _registry(tmp_path, alpha)
    async with LocalClient() as person:
        w = await _mk(person, alpha / ".claude" / "worktrees" / "g", "g")
        async with LocalClient(caller=w) as c:
            mid = (await c.call("msg", to="person", text="merge?", kind="ask", about="TD-9"))["entry"]["id"]
        agent._mark(mid, pr=2996, repo="agent-cadence")
        agent._repos = {str(alpha): _reading(merged=[2996])}
        await agent._settle_by_work()
        assert all(e.open for e in _copies(agent, mid))
        await person.call("kill", id=w)


async def test_a_steer_closed_merged_applies_no_default(agent, tmp_path):
    alpha = tmp_path / "alpha"
    alpha.mkdir()
    _registry(tmp_path, alpha)
    async with LocalClient() as person:
        w = await _mk(person, alpha / ".claude" / "worktrees" / "g", "g")
        async with LocalClient(caller=w) as c:
            st = await c.call("msg", to="person", text="squash?", kind="steer", default="squash", about="#164")
        mid = st["entry"]["id"]
        agent._repos = {str(alpha): _reading(merged=[164])}
        await agent._sweep_mail(datetime.now(UTC) + timedelta(days=2))  # past its bound: the pass runs first
        assert all(e.closed_reason == "merged" for e in _copies(agent, mid))
        assert [e for e in agent.sessions[w].inbox if e.from_ == "system"] == [], "no lapse note, no default"
        await person.call("kill", id=w)


async def test_an_orphaned_ask_settles_by_its_archive_and_one_asked_after_stays_open(agent, tmp_path):
    alpha = tmp_path / "alpha"
    alpha.mkdir()
    _registry(tmp_path, alpha)
    async with LocalClient() as person:
        w = await _mk(person, alpha / ".claude" / "worktrees" / "g", "g")
        async with LocalClient(caller=w) as c:
            a = (await c.call("msg", to="person", text="reopen TD-221?", kind="ask", about="TD-221"))["entry"]
            b = await c.call("msg", to="person", text="split TD-222?", kind="steer", default="no", about="TD-222")
        b = b["entry"]
        for mid in (a["id"], b["id"]):
            agent._mark(mid, repo=None)  # sent before the stamp: the orphan stamp's path is what names its repo
        await person.call("kill", id=w)
        await person.call("close", id=w)
        held_now = next(e for e in agent.person_inbox if e.id == a["id"])
        assert held_now.open and held_now.orphaned, "an asker's going alone closes nothing that names a reference"
        at = datetime.fromisoformat(a["at"].replace("Z", "+00:00"))
        agent._repos = {
            str(alpha): _reading(
                completed=[
                    {"id": "TD-221", "closed": (at + timedelta(minutes=5)).isoformat(), "pr": 164},
                    {"id": "TD-222", "closed": (at - timedelta(minutes=5)).isoformat(), "pr": 165},
                ]
            )
        }
        await agent._settle_by_work()
        got = next(e for e in agent.person_inbox if e.id == a["id"])
        assert (got.closed_reason, got.settled_by) == ("settled", 164)
        assert next(e for e in agent.person_inbox if e.id == b["id"]).open, "archived before it was asked"
        # a closed `settled` entry is pruned by retention from its `closed_at`
        got.read_at = got.closed_at = _iso(datetime.now(UTC) - timedelta(days=30))
        await agent._sweep_mail(datetime.now(UTC))
        assert a["id"] not in [e.id for e in agent.person_inbox]


async def test_the_unstamped_order_a_live_askers_record_and_neither(agent, tmp_path):
    alpha = tmp_path / "alpha"
    alpha.mkdir()
    _registry(tmp_path, alpha)
    async with LocalClient() as person:
        w = await _mk(person, alpha / ".claude" / "worktrees" / "g", "g")
        loose = await _mk(person, tmp_path / "loose", "loose")
        async with LocalClient(caller=w) as c:
            a = (await c.call("msg", to="person", text="merge?", kind="ask", about="TD-9"))["entry"]["id"]
        async with LocalClient(caller=loose) as c:
            b = (await c.call("msg", to="person", text="merge?", kind="ask", about="TD-9"))["entry"]["id"]
        for mid in (a, b):
            agent._mark(mid, pr=164, repo=None)
        agent._repos = {str(alpha): _reading(merged=[164])}
        await agent._settle_by_work()
        assert all(e.closed_reason == "merged" for e in _copies(agent, a)), "a live asker's record resolves"
        assert all(e.open for e in _copies(agent, b)), "neither: it stays the person's"
        for sid in (w, loose):
            await person.call("kill", id=sid)


async def test_a_question_passed_up_on_a_thread_carries_the_asks_pr_and_repo(agent, tmp_path):
    alpha = tmp_path / "alpha"
    alpha.mkdir()
    _registry(tmp_path, alpha)
    async with LocalClient() as person:
        w = await _mk(person, alpha / ".claude" / "worktrees" / "g", "g", team="t")
        tl = await _mk(person, tmp_path / "tl", "tl", team="t", seat={"trigger": "asks"})
        loose = await _mk(person, tmp_path / "loose", "loose", team="t")
        async with LocalClient(caller=w) as wc, LocalClient(caller=loose) as lc:
            q = (await wc.call("msg", to=tl, text="read #164?", kind="ask"))["entry"]
            q2 = (await lc.call("msg", to=tl, text="read #170?", kind="ask"))["entry"]
            agent._mark(q["id"], pr=164)
            agent._mark(q2["id"], pr=170, repo="alpha")
            agent.sessions[w].review = {"reader": "techlead", "held": ["src/**"]}
            assert held.read_by(agent.sessions[w], 164) is None
            up = await wc.call("msg", to="person", text="read #164? tl did not answer", kind="ask", thread=q["id"])
            up = up["entry"]
            up2 = (await lc.call("msg", to="person", text="read #170?", kind="ask", thread=q2["id"]))["entry"]
        mine = next(e for e in agent.person_inbox if e.id == up["id"])
        assert mine.pr == 164 and mine.repo == "alpha", "a stamped one keeps its own repo"
        theirs = next(e for e in agent.person_inbox if e.id == up2["id"])
        assert theirs.pr == 170 and theirs.repo == "alpha", "an empty stamp takes the closed ask's repo"
        # the copy makes the person's reply the PR's read, and `held.asks` keeps the author's earlier ask
        await person.call("msg", to=w, kind="reply", reply_to=up["id"], text="merge it")
        assert held.read_by(agent.sessions[w], 164) == PERSON
        asks = held.asks(agent._graph(), agent.person_inbox, {str(alpha): {}})
        assert asks[str(alpha)]["164"]["to"] != PERSON, "the author's earlier ask to the seat is the one kept"
        agent._repos = {str(alpha): _reading(merged=[170])}
        await agent._settle_by_work()
        assert all(e.closed_reason == "merged" for e in _copies(agent, up2["id"]))
        for sid in (w, tl, loose):
            await person.call("kill", id=sid)


async def test_the_settle_names_by_team_by_graph_address_and_keeps_two_hosts_paths_apart(agent, tmp_path, monkeypatch):
    """TD-1561 (§4.10 *A question the work settled closes itself*, §4.5 screen 6): a pre-stamp item whose sender is
    gone is named by its team's one repo; a node's sender is found by its graph address and named by the node's
    roster; a home record and a node record at one path are named apart, by `(host, root)`."""
    from sessionorc.models import Session

    alpha, beta = tmp_path / "alpha", tmp_path / "beta"
    alpha.mkdir(), beta.mkdir()
    _registry(tmp_path, alpha)  # the home registers alpha; the node registers beta

    async def roster(host):
        return [str(beta)] if host == "node" else []

    monkeypatch.setattr(agent, "_host_roster", roster)
    async with LocalClient() as person:
        w = await _mk(person, alpha / ".claude" / "worktrees" / "g", "g")
        y = await _mk(person, beta, "y")  # the home's record at beta, a path the home does not register
        agent.sessions[w].team = "t"
        async with LocalClient(caller=w) as c:
            ids = [(await c.call("msg", to="person", text=f"merge {i}?", kind="ask"))["entry"]["id"] for i in range(4)]
        team, remote, home_y, gone = ids
        node_z = Session(id="z", name="z", kind="interactive", adapter="shell", dir=str(beta), host="node")
        agent.remote["node"] = {"z": node_z}
        try:
            agent._mark(team, pr=164, repo=None, from_="ghost", team="t")
            agent._mark(remote, pr=165, repo=None, from_="z@node")
            agent._mark(home_y, pr=165, repo=None, from_=y)
            agent._mark(gone, pr=164, repo=None, from_="ghost", team="u")
            agent._repos = {str(alpha): _reading(merged=[164]), str(beta): _reading(merged=[165])}
            await agent._settle_by_work()
            closed = {e.id: e.closed_reason for e in agent.person_inbox if e.id in ids}
            assert closed[team] == "merged", "its team's one repo"
            assert closed[remote] == "merged", "a node's sender by its graph address, named by the node's roster"
            assert closed[home_y] is None, "the home's record at the same path: the home registers none there"
            assert closed[gone] is None, "no stamp, no record, a team naming none: the person's"
        finally:
            agent.remote.pop("node", None)
            for sid in (w, y):
                await person.call("kill", id=sid)
