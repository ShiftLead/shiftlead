"""The title's verdict in the tick (design §4.2 *A title the tool writes its state into*, §4.3 *Two gaps*,
TD-785 slice 3): read once a hook has reached the record and past one tick since the last hook, compared
with the hook-confirmed state, `✋`'s text written by the state it replaces, equal states no event (the
stall check still runs), never held for its screen; `ao explain` shows the title as its evidence."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import wait_for

from sessionorc import adapters, agent_common, agent_tick
from sessionorc.client import LocalClient
from sessionorc.models import Pending, Session, now_iso
from sessionorc.screen import Match, painted_text
from sessionorc.tmux import PaneInfo
from shiftlead import cli
from shiftlead.adapters.gemini import GeminiAdapter

pytestmark = pytest.mark.integration

PAD = " " * 40
READY, WORKING, QUIET, ACTION = (
    f"{g}  {w} (t1){PAD}" for g, w in (("◇", "Ready"), ("✦", "Working…"), ("⏲", "Working…"), ("✋", "Action Required"))
)


@pytest.fixture
def gem(monkeypatch):
    adapters.load_all()
    ad = GeminiAdapter(binary="gemini")
    monkeypatch.setitem(adapters._REGISTRY, ad.name, ad)
    return ad


def _rec(tmp_path, state="working", confidence="hook", hooked=True, pending=None) -> Session:
    s = Session(id="ao-x-g", name="g", kind="agent", dir=str(tmp_path), adapter="gemini", state=state)
    s.confidence = confidence
    s.pending = pending
    s.hook_seen_at = now_iso() if hooked else None
    return s


def _look(agent, s: Session, title: str, hook_age: float | None = 60.0) -> Session:
    now = datetime.now(UTC)
    if hook_age is None:
        agent._last_hook.pop(s.id, None)
    else:
        agent._last_hook[s.id] = now - timedelta(seconds=hook_age)
    agent._observe(s, PaneInfo(s.id, 0, "node", 1, dead=False, dead_status=None, title=title), [], now)
    return s


def test_the_adapter_explains_its_title_and_not_its_screen():
    ad = GeminiAdapter(binary="gemini")
    m = ad.explain(["◇  Ready"], title=ACTION)
    assert m.state == "needs-you" and m.pending.kind == "question" and m.pending.text == ""
    assert m.rule == "title ✋" and m.evidence == [ACTION.strip()]
    assert ad.explain([], title=QUIET).state == "working" and ad.explain([], title=READY).pending is None
    assert ad.explain(["✦  Working…"], title="kmaster: ~/src") is None and ad.explain([]) is None


async def test_the_title_replaces_a_hook_state_older_than_a_tick(agent, gem, tmp_path):
    s = _rec(tmp_path, hooked=False)
    assert _look(agent, s, READY).state == "working"  # no hook has reached it: the title is its screen
    s.hook_seen_at = now_iso()
    assert _look(agent, s, READY, hook_age=0.0).state == "working"  # a hook within the tick wins
    agent._hook_state[s.id] = ("idle", None, "hook")  # what a screen verdict kept: the title drops it
    assert _look(agent, s, READY).state == "idle"  # a cancelled or failed turn ends
    assert s.confidence == "title" and s.pending is None and s.id not in agent._hook_state
    assert s.told  # the tool's own word: every hook-confirmed rule takes it
    assert _look(agent, s, WORKING).state == "working" and s.confidence == "title"  # a slash command's call
    assert _look(agent, s, READY, hook_age=None).state == "idle"  # no hook since a restart: none to outrank


async def test_action_required_is_written_by_the_state_it_replaces(agent, gem, tmp_path):
    s = _look(agent, _rec(tmp_path, state="working"), ACTION)
    assert s.state == "needs-you" and s.pending.kind == "question" and s.pending.text == agent_tick.TITLE_SHELL_WAITS
    s = _look(agent, _rec(tmp_path, state="idle"), ACTION)
    assert s.pending.text == agent_tick.TITLE_CONFIRMATION
    # under a Notification's permission the `✋` is that confirmation: its pending stands
    perm = Pending(kind="permission", text="Allow execution: rm -rf build")
    s = _look(agent, _rec(tmp_path, state="needs-you", pending=perm), ACTION)
    assert s.pending == perm and s.confidence == "hook"
    # answered in the terminal, no hook says so until AfterTool: the title's `✦` ends it
    s = _look(agent, s, WORKING)
    assert s.state == "working" and s.pending is None and s.confidence == "title"
    # a title's own `working` is hook-confirmed: `✋` over it is the shell waiting
    s = _look(agent, s, ACTION)
    assert s.state == "needs-you" and s.pending.text == agent_tick.TITLE_SHELL_WAITS


async def test_explains_reason_is_the_ticks_own_rule(agent, gem, tmp_path):
    ad = GeminiAdapter(binary="gemini")
    now = datetime.now(UTC)
    agent._last_hook["ao-x-g"] = now - timedelta(seconds=60)

    def why(s, title):
        return agent._title_reading(s, ad.explain([], title=title), now)

    assert why(_rec(tmp_path), "kmaster: ~") == (None, "the title says no state")
    assert "not read yet" in why(_rec(tmp_path, hooked=False), READY)[1]
    assert "stands" in why(_rec(tmp_path, state="exited"), READY)[1]
    assert "no event" in why(_rec(tmp_path), WORKING)[1]
    assert "does not end a stall" in why(_rec(tmp_path, state="stalled?", confidence="tick"), WORKING)[1]
    assert "not compared" in why(_rec(tmp_path, state="idle", confidence="tick"), WORKING)[1]
    assert "taken as the tool's own word" in why(_rec(tmp_path, state="idle", confidence="scraped"), READY)[1]
    m, reason = why(_rec(tmp_path), READY)
    assert m.state == "idle" and "confidence: title" in reason
    agent._last_hook["ao-x-g"] = now
    assert "within a tick" in why(_rec(tmp_path), READY)[1]


async def test_the_ticks_own_readings_stand_but_a_stall_ends_when_the_tool_moves_on(agent, gem, tmp_path):
    for st in ("exited", "closed"):
        for conf in ("tick", "hook"):  # the tool's own SessionEnd is a hook's `exited`: it stands too
            s = _look(agent, _rec(tmp_path, state=st, confidence=conf), READY)
            assert s.state == st and s.confidence == conf
    s = _rec(tmp_path, state="stalled?", confidence="tick")
    assert _look(agent, s, WORKING).state == "stalled?"  # still working: no event
    assert _look(agent, s, QUIET).state == "stalled?"
    assert _look(agent, s, READY).state == "idle" and s.confidence == "title"
    s = _look(agent, _rec(tmp_path, state="stalled?", confidence="tick"), ACTION)
    assert s.state == "needs-you" and s.pending.text == agent_tick.TITLE_SHELL_WAITS
    # a scraped state with no rule's screen up is the fallback: the title is compared with it (TD-944)
    assert _look(agent, _rec(tmp_path, state="idle", confidence="scraped"), WORKING).state == "working"


async def test_an_equal_verdict_falls_through_to_the_stall_check(agent, gem, tmp_path):
    s = _rec(tmp_path, state="working")
    log = tmp_path / "run.log"
    log.write_text("x")
    old = time.time() - 3600
    os.utime(log, (old, old))
    s.run_log = str(log)
    assert _look(agent, s, WORKING).state == "stalled?" and s.confidence == "tick"


async def test_a_title_adapters_bare_tail_answer_is_its_screen_rule(agent, gem, tmp_path, monkeypatch):
    # A title adapter's `explain` asked without a title answers from its manifest (§4.3 *The limit dialog
    # is read off the screen*, TD-944): that verdict takes the screen road; a title that says nothing and
    # a tail no rule matches leave the record as it stands (TD-844)
    title_explain = gem.explain

    def explain(tail, title=None):
        if title is None and tail == ["Allow?"]:  # the screen rule's call: the tail alone
            return Match(rule="tail", state="needs-you", evidence=tail, pending=Pending(kind="question", text="?"))
        return title_explain(tail, title=title)

    monkeypatch.setattr(gem, "explain", explain)
    s = _rec(tmp_path, state="working")
    s.tail = ["Allow?"]
    agent._last_hook[s.id] = datetime.now(UTC) - timedelta(seconds=60)
    assert agent._screen_verdict(s, gem, datetime.now(UTC)).rule == "tail"
    assert _look(agent, _rec(tmp_path, state="working"), "kmaster: ~/src").state == "working"
    s = _look(agent, _rec(tmp_path, state="working"), "kmaster: ~/src")
    assert s.confidence == "hook" and s.pending is None


async def test_a_title_set_in_the_pane_reaches_the_record_and_explain(agent, hookstub, tmp_path, monkeypatch):
    """The whole path: a pane's own title (OSC 2) through the tick's pane list to the record, and `ao
    explain` showing the title as the verdict's evidence."""
    ad = GeminiAdapter(binary="gemini")
    monkeypatch.setattr(type(hookstub), "state_in_title", True, raising=False)
    monkeypatch.setattr(type(hookstub), "explain", lambda self, tail, title="": ad.explain(tail, title=title))
    async with LocalClient() as c:
        s = await c.call("create", name="ttl", dir=str(tmp_path), adapter="hookstub")
        await c.call("hook", session=s["id"], state="idle")
        agent.tmux.send_prompt(s["id"], r"printf '\033]2;✋  Action Required (ttl)\033\\'")

        async def reads(state, confidence):
            x = await c.call("get", id=s["id"])
            return x["state"] == state and x["confidence"] == confidence

        assert await wait_for(lambda: reads("needs-you", "title"))
        x = await c.call("get", id=s["id"])
        assert x["pending"] == {
            "kind": "question",
            "text": agent_tick.TITLE_CONFIRMATION,
            "deadline": None,
            "tool_use_id": None,
        }
        ex = await c.call("explain", id=s["id"])
        assert ex["title"].startswith("✋  Action Required") and ex["match"]["rule"] == "title ✋"
        assert "no event" in ex["reason"]  # the record already reads what the title says
        await c.call("kill", id=s["id"])


def test_explain_file_takes_a_title(gem, tmp_path, capsys):
    screen = tmp_path / "pane.txt"
    screen.write_text(" > Type your message or @path/to/file\n")
    assert cli.main(["--json", "explain", "--file", str(screen), "-a", "gemini", "--title", ACTION]) == 0
    x = json.loads(capsys.readouterr().out)
    assert x["title"] == ACTION and x["match"]["state"] == "needs-you" and x["match"]["rule"] == "title ✋"
    assert cli.main(["explain", "--file", str(screen), "-a", "gemini"]) == 0
    out = capsys.readouterr().out
    assert "title: \n" in out and "no screen rule matched" in out


# ── the limit dialog (design §4.3 *The limit dialog is read off the screen*, TD-944 slice 1) ─────

BOX = (
    (Path(__file__).parent / "conformance" / "fixtures" / "gemini" / "captured" / "panes" / "6-a-doorbell.txt")
    .read_text(encoding="utf-8")
    .splitlines()
)


def test_the_limit_box_reads_limited_over_the_titles_working():
    """The manifest is asked first, on the raw pane's painted text: its verdict stands over `✦`, modal."""
    ad = GeminiAdapter(binary="gemini")
    m = ad.explain(BOX, title=WORKING)
    assert (m.rule, m.state, m.modal) == ("gemini-usage-limit", "limited", True)
    assert m.pending == Pending(kind="limit", text="Gemini's usage limit reached — answer its dialog in the terminal")
    assert m.to_dict()["modal"] is True and ad.explain(BOX).state == "limited"  # with no title, the manifest alone
    painted = [painted_text(r) for r in BOX]
    on_stop = [r.replace("● 1. Keep trying", "  1. Keep trying").replace("  2. Stop", "● 2. Stop") for r in painted]
    assert on_stop != painted and ad.explain(on_stop, title=WORKING).rule == "gemini-usage-limit"
    # the title's own verdict is not modal; prose quoting the dialog outside a box matches nothing
    assert ad.explain([], title=WORKING).modal is False
    # core tells a title verdict from a rule's by the Match's `title`, never by the rule id (§4.3)
    assert ad.explain([], title=WORKING).title is True and m.title is False
    prose = ["✦ The tool says: Usage limit reached for gemini-3.8-flash.", "  2. Stop"]
    assert ad.explain(prose, title=WORKING).rule == "title ✦"


def _box(agent, s: Session, title: str, hook_age: float | None = 60.0, tail: list[str] = BOX) -> Session:
    now = datetime.now(UTC)
    if hook_age is None:
        agent._last_hook.pop(s.id, None)
    else:
        agent._last_hook[s.id] = now - timedelta(seconds=hook_age)
    agent._observe(s, PaneInfo(s.id, 0, "node", 1, dead=False, dead_status=None, title=title), tail, now)
    return s


LIMIT = Pending(kind="limit", text="Gemini's usage limit reached — answer its dialog in the terminal")


async def test_the_box_takes_the_screen_road_and_the_title_takes_over_once_it_goes(agent, gem, tmp_path):
    """TD-944 slice 2: the box over `✦` reads `limited` (`scraped`) and keeps the `working` it replaced;
    gone, the kept state comes back on the next tick and the title's verdict on the one after."""
    s = _box(agent, _rec(tmp_path, state="working"), WORKING)
    assert (s.state, s.confidence, s.pending) == ("limited", "scraped", LIMIT)
    assert agent._hook_state[s.id] == ("working", None, "hook")
    assert _box(agent, s, WORKING).state == "limited"  # the title is never compared while the box is up
    assert _look(agent, s, READY).state == "working" and s.confidence == "hook"  # *Stop*: what it replaced
    assert _look(agent, s, READY).state == "idle" and s.confidence == "title"
    # a hook two minutes old does not keep a cleared box's `limited` (the stall window would, for 20)
    s = _box(agent, _rec(tmp_path, state="working"), WORKING, hook_age=120.0)
    assert _look(agent, s, WORKING, hook_age=120.0).state == "working" and s.confidence == "hook"
    # a hook within the tick still outranks the box
    s = _box(agent, _rec(tmp_path, state="working"), WORKING, hook_age=0.0)
    assert (s.state, s.confidence) == ("working", "hook")


async def test_the_box_over_a_titles_state_restores_it_as_the_titles(agent, gem, tmp_path):
    s = _box(agent, _rec(tmp_path, state="idle", confidence="title"), READY)
    assert (s.state, s.confidence) == ("limited", "scraped")  # a told state is replaced either way
    assert _look(agent, s, READY).state == "idle" and s.confidence == "title"
    assert _look(agent, s, WORKING).state == "working" and s.confidence == "title"  # compared with it


async def test_the_box_over_the_polls_limited_keeps_the_polls_reading(agent, gem, tmp_path):
    cap = Pending(kind="limit", text="weekly limit — resets Fri 09:00")
    s = _box(agent, _rec(tmp_path, state="limited", pending=cap), WORKING)
    assert (s.state, s.confidence, s.pending) == ("limited", "hook", cap) and s.id not in agent._hook_state


async def test_the_usage_poll_never_lifts_the_boxs_limited(agent, gem, tmp_path):
    """A poll with no reading (an API-key home) lifted every kind-`limit` record; a modal rule's stands
    while its box is up, and once the box is gone a lift goes back to what the verdict replaced."""
    s = _box(agent, _rec(tmp_path, state="working"), WORKING)
    agent._usage_limits([s], set())
    assert (s.state, s.confidence, s.pending) == ("limited", "scraped", LIMIT)
    assert agent_common.limit_is_modal(s, gem) and not agent_common.limit_is_modal(None, gem)
    s.tail = []  # the box gone between two ticks: the poll's lift restores the kept `working`
    assert not agent_common.limit_is_modal(s, gem)
    agent._usage_limits([s], set())
    assert (s.state, s.confidence) == ("working", "hook") and s.id not in agent._hook_state
    # nothing kept (a host-agent restart): the no-saved fallback, the title's to overrule
    s = _box(agent, _rec(tmp_path, state="working"), WORKING)
    agent._hook_state.pop(s.id)
    s.tail = []
    agent._usage_limits([s], set())
    assert (s.state, s.confidence) == ("idle", "scraped")
    assert _look(agent, s, WORKING).state == "working" and s.confidence == "title"


async def test_the_no_saved_fallback_is_the_titles_to_overrule(agent, gem, tmp_path):
    """A `scraped` `idle` with nothing kept and no box up is compared as a told state: an equal verdict is
    taken as the tool's own word, `since` and `rev` unchanged."""
    s = _rec(tmp_path, state="idle", confidence="scraped")
    since, rev = s.since, s.rev
    assert _look(agent, s, READY).state == "idle" and s.confidence == "title"
    assert (s.since, s.rev) == (since, rev)
    s = _look(agent, _rec(tmp_path, state="idle", confidence="scraped"), WORKING)
    assert (s.state, s.confidence) == ("working", "title")


async def test_explain_on_a_live_record_at_the_box_gives_the_rules_reason(agent, hookstub, tmp_path, monkeypatch):
    ad = GeminiAdapter(binary="gemini")
    monkeypatch.setattr(type(hookstub), "state_in_title", True, raising=False)
    monkeypatch.setattr(type(hookstub), "explain", lambda self, tail, title="": ad.explain(tail, title=title))
    fixture = Path(__file__).parent / "conformance" / "fixtures" / "gemini" / "captured" / "panes" / "6-a-doorbell.txt"
    async with LocalClient() as c:
        s = await c.call("create", name="box", dir=str(tmp_path), adapter="hookstub", unattended=True)
        await c.call("hook", session=s["id"], state="working")
        agent.tmux.send_prompt(s["id"], f"clear; cat {fixture}")

        async def limited():
            return (await c.call("get", id=s["id"]))["state"] == "limited"

        assert await wait_for(limited)
        x = await c.call("get", id=s["id"])
        assert x["confidence"] == "scraped" and x["pending"]["kind"] == "limit"
        ex = await c.call("explain", id=s["id"])
        assert ex["match"]["rule"] == "gemini-usage-limit" and ex["match"]["modal"] is True
        assert ex["reason"] == "rule gemini-usage-limit matched, applied as scraped; held for its screen"
        # a hook within a tick outranks the rule; the poll's limited at `hook` is kept (TD-954)
        agent._last_hook[s["id"]] = datetime.now(UTC)
        ex = await c.call("explain", id=s["id"])
        assert ex["reason"] == "rule gemini-usage-limit matched, but a hook reported within a tick — the hook state wins"
        del agent._last_hook[s["id"]]
        rec = agent._get(s["id"])
        rec.confidence = "hook"
        ex = await c.call("explain", id=s["id"])
        assert ex["reason"] == "rule gemini-usage-limit matched, but the usage poll's limited stands — its reading kept"
        rec.confidence = "scraped"
        # a send lands and waits with no reset to name (§4.10), and the card's composer says so
        no_reset = "lands and waits: the tool's usage-limit dialog is up; it is read once that is answered"
        got = await c.call("msg", to=s["id"], kind="note", text="when you can")
        assert got["read_when"][s["id"]].startswith(no_reset)
        view = next(v for v in await c.call("list") if v["id"] == s["id"])
        assert view["read_when"]["note"].startswith(no_reset)
        assert view["read_when"]["refill"].startswith(no_reset)  # the Reply composer's line on a handed thread
        # an entry handed to a seat at the box: its reply's sentence names no reset either (TD-955)
        repo = tmp_path / "shiftlead"
        repo.mkdir()
        home = tmp_path / "home"
        home.mkdir(exist_ok=True)
        (home / "repos.txt").write_text(f"{repo}\n")
        (home / "hosts.yml").write_text(f"local:\n  repos_registry: {home / 'repos.txt'}\n")
        teams = [{"team": "ao-grind", "seat": s["id"]}]
        handed = await c.call("entry_add", repo="shiftlead", type="debt", text="the parser drops a line", teams=teams)
        assert handed["to"] == s["id"] and handed["read_when"].startswith(no_reset)
        await c.call("kill", id=s["id"])
