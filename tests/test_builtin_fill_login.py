"""TD-2068, design §4.9d *The login a seat starts on*, §4.9e *The launch on a login*: after the cut-over, rule 3's fill
of a built-in seat's record on the home's own host is launched on the first usable login of the list of the built-in
set its repo uses that offers the seat's model, and the record holds the login, its account, the seat's model and the
set's list; with no login usable, or none offering the model, nothing is filled and `unfillable` says why. Before the
cut-over a fill is as it was."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from conftest import park_ticks

from sessionorc import paths, teamstore
from sessionorc.adapters import LaunchSpec
from sessionorc.agent_common import RpcError
from sessionorc.client import LocalClient

pytestmark = pytest.mark.integration

LOGINS = """logins:
  hookstub:first: {folder: /c/first, account: acct-1}
  hookstub:second: {folder: /c/second, account: acct-2}
accounts: {}
forgotten: {}
"""
SETTINGS = """cut_over: 2026-12-01
builtins:
  default:
    models: {tech-lead: opus, sweeper: haiku}
    logins: [hookstub:first, hookstub:second]
"""


SEATS = {
    "techlead": {"trigger": "asks"},
    "sweeper": {"trigger": "swept", "by": "settings"},
    "prompts": {"trigger": "prompt"},
}


def _row(account: str, models: list[str], **kw) -> dict:
    return {"state": "signed_in", "account": account, "pin": None, "models": models, "at_reserve": False, **kw}


@pytest.fixture
def launched(hookstub, monkeypatch):
    """The stub adapter's launch, recording what each was handed."""
    seen: list[dict] = []

    def launch(*, profile, resume, prompt, unattended, cwd, name="", **kw):
        seen.append({"profile": profile, **kw})
        return LaunchSpec(argv=["bash", "--norc"])

    monkeypatch.setattr(hookstub, "launch", launch)
    return seen


@pytest.fixture
def rows(agent, monkeypatch):
    """The login rows the fill's pick reads, as the test sets them; no tool is read and no account is asked."""
    held: dict[str, dict] = {}
    monkeypatch.setattr(agent, "rpc_tools", AsyncMock(return_value={"tools": []}))
    monkeypatch.setattr(agent, "rpc_gate", AsyncMock(return_value={"accounts": {}}))
    monkeypatch.setattr(teamstore, "login_rows", lambda *a, **kw: held)
    return held


async def _held_seat(
    agent, tmp_path, builtin: str = "techlead", settings: str = SETTINGS, *, adapter: str = "hookstub", **launch
) -> str:
    """A built-in seat's record as the home writes it, held, before any login: then the marker, and the seat due.
    `adapter` and `launch` (a `profile`) are its last launch's, which a fill replays."""
    await park_ticks(agent)
    (paths.home() / "logins.yml").write_text(LOGINS)
    (tmp_path / "repo").mkdir(exist_ok=True)
    async with LocalClient() as person:
        sid = (
            await person.call(
                "create",
                name=f"{builtin}-t",
                dir=str(tmp_path / "repo"),
                adapter=adapter,
                **launch,
                unattended=True,
                supervised=True,
                held=True,
                prompt="the seat's brief",
                seat=SEATS[builtin],
                builtin=builtin,
                **({"team": "t"} if builtin == "techlead" else {}),
            )
        )["id"]
    (paths.home() / "settings.yml").write_text(settings)
    agent._read_cut_over()
    agent.sessions[sid].seat_due = {"at": datetime.now(UTC).isoformat(), "by": "asks"}
    return sid


async def _fill(agent, sid: str) -> None:
    s = agent.sessions[sid]
    await agent._fill(s, datetime.now(UTC), list(agent.sessions.values()))


@pytest.mark.parametrize(("builtin", "model"), [("techlead", "opus"), ("sweeper", "haiku"), ("prompts", "sonnet")])
async def test_a_built_in_seat_is_filled_on_its_sets_first_usable_login(
    agent, tmp_path, launched, rows, builtin, model
):
    rows.update({"hookstub:first": _row("acct-1", [model]), "hookstub:second": _row("acct-2", [model])})
    sid = await _held_seat(agent, tmp_path, builtin)
    old = agent.sessions[sid]
    await _fill(agent, sid)
    new = agent.sessions[sid]
    assert new is not old, "the seat was filled"
    assert (new.login, new.account, new.seat_model, new.login_list) == (
        "hookstub:first",
        "acct-1",
        model,
        ["hookstub:first", "hookstub:second"],
    )
    assert launched[-1] == {"profile": "first", "model": model}, "launched on the login's folder and the set's model"
    assert new.builtin == builtin and sid not in agent.unfillable


async def test_a_login_at_its_reserve_is_passed_over_for_the_next(agent, tmp_path, launched, rows):
    rows.update(
        {"hookstub:first": _row("acct-1", ["opus"], at_reserve=True), "hookstub:second": _row("acct-2", ["opus"])}
    )
    sid = await _held_seat(agent, tmp_path)
    await _fill(agent, sid)
    assert agent.sessions[sid].login == "hookstub:second"
    assert launched[-1] == {"profile": "second", "model": "opus"}


@pytest.mark.parametrize(
    ("first", "second", "word"),
    [
        (_row("acct-1", ["opus"], state="limited"), _row("acct-1", ["opus"]), "no login usable"),
        (_row("acct-1", ["sonnet"]), _row("acct-2", ["haiku"]), "cannot run"),
    ],
    ids=["waits", "none-offers"],
)
async def test_no_usable_login_fills_nothing_and_says_why(agent, tmp_path, launched, rows, first, second, word):
    """A login unusable now is a wait under the usage gate; a list with no login offering the model cannot run it
    (§4.9d). Either way nothing is launched, and `unfillable` carries the word a question's routing reads."""
    rows.update({"hookstub:first": first, "hookstub:second": second})
    sid = await _held_seat(agent, tmp_path)
    old = agent.sessions[sid]
    await _fill(agent, sid)
    assert agent.sessions[sid] is old and not launched
    assert agent.unfillable[sid] == word
    assert not old.restarts, "a fill not made is no failed restart"


async def test_before_the_cut_over_a_fill_reads_no_set(agent, tmp_path, launched, rows):
    sid = await _held_seat(agent, tmp_path, settings=SETTINGS.replace("cut_over: 2026-12-01\n", ""))
    await _fill(agent, sid)
    new = agent.sessions[sid]
    assert new.login is None and new.seat_model is None
    assert launched[-1] == {"profile": ""}, "launched as before: no login, no model"


async def test_its_last_runs_gated_profile_does_not_keep_it_off_the_next_login(
    agent, tmp_path, launched, rows, monkeypatch
):
    """The fill's pick passes over a gated login to the next (§4.9d): the profile its last run was read under, over
    its usage line, is no refusal of rule 3 for a built-in seat after the cut-over (review of #4717)."""
    rows.update(
        {"hookstub:first": _row("acct-1", ["opus"], at_reserve=True), "hookstub:second": _row("acct-2", ["opus"])}
    )
    sid = await _held_seat(agent, tmp_path)
    monkeypatch.setattr(agent, "_profile_gated", lambda *a, **kw: True)
    assert agent._unfillable_word(agent.sessions[sid], datetime.now(UTC)) is None
    await _fill(agent, sid)
    assert agent.sessions[sid].login == "hookstub:second"


async def test_an_ended_seat_not_due_says_it_cannot_run_before_a_question_comes(
    agent, tmp_path, launched, rows, monkeypatch
):
    """Rule 3's pass reads an ended built-in seat's login due or not, so a question is routed around a seat its set
    cannot run from the first (§4.9b *A seat that cannot answer is routed around*, review of #4717)."""
    rows.update({"hookstub:first": _row("acct-1", ["sonnet"]), "hookstub:second": _row("acct-2", ["sonnet"])})
    sid = await _held_seat(agent, tmp_path)
    s = agent.sessions[sid]
    monkeypatch.setattr(agent, "_builtin_hold", lambda *a, **kw: None)
    monkeypatch.setattr(agent, "_seat_due", lambda *a, **kw: None)
    s.seat_due = None
    await agent._seat_pass(s, datetime.now(UTC), list(agent.sessions.values()))
    assert agent.unfillable[sid] == "cannot run" and not launched


def test_a_login_asks_where_its_unattended_args_lack_the_tools_skip(hookstub, monkeypatch):
    """§4.9d *How each one runs*, §4.3 `skip_args`: a login's `unattended_args` given without the tool's skip leave its
    prompts on; none given, the launch passes its own; a tool naming no skip, or with no adapter here, is unread."""
    monkeypatch.setattr(hookstub, "skip_args", ["--skip"], raising=False)
    assert teamstore.asks("hookstub", ["--other"]) is True
    assert teamstore.asks("hookstub", ["--skip", "--other"]) is False
    assert teamstore.asks("hookstub", None) is False and teamstore.asks("hookstub", []) is False
    assert teamstore.asks("no-such-tool", ["--other"]) is False
    monkeypatch.setattr(hookstub, "skip_args", None, raising=False)
    assert teamstore.asks("hookstub", ["--other"]) is False


def test_a_two_word_skip_asks_where_the_args_hold_only_one_of_its_words(hookstub, monkeypatch):
    """TD-2257: a tool whose skip is two words (Gemini's `--approval-mode yolo`) asks where a login's
    `unattended_args` hold one word and not the other: the login leaves its prompts on (§4.9d)."""
    monkeypatch.setattr(hookstub, "skip_args", ["--approval-mode", "yolo"], raising=False)
    assert teamstore.asks("hookstub", ["--approval-mode", "default"]) is True
    assert teamstore.asks("hookstub", ["yolo"]) is True
    assert teamstore.asks("hookstub", ["--approval-mode", "yolo", "--other"]) is False


def test_login_rows_read_asks_from_a_logins_settings(hookstub, monkeypatch):
    monkeypatch.setattr(hookstub, "skip_args", ["--skip"], raising=False)
    read = {
        "tools": [
            {
                "adapter": "hookstub",
                "accounts": [],
                "logins": [
                    {"name": "first", "state": "signed_in", "settings": {"unattended_args": ["--other"]}},
                    {"name": "second", "state": "signed_in", "settings": {"unattended_args": None}},
                ],
            }
        ]
    }
    got = teamstore.login_rows(read, {})
    assert (got["hookstub:first"]["asks"], got["hookstub:second"]["asks"]) == (True, False)


def test_an_unasked_pick_passes_over_a_login_that_asks_and_waits_where_all_do():
    rows = {"a:x": _row("acct-1", ["sonnet"], asks=True), "a:y": _row("acct-2", ["sonnet"])}
    assert teamstore.pick(["a:x", "a:y"], "sonnet", rows)["login"] == "a:x", "a team's pick reads no asks"
    assert teamstore.pick(["a:x", "a:y"], "sonnet", rows, unasked=True)["login"] == "a:y"
    rows["a:y"]["asks"] = True
    got = teamstore.pick(["a:x", "a:y"], "sonnet", rows, unasked=True)
    assert got["state"] == "waits" and "leaves its prompts on" in got["why"]


@pytest.mark.parametrize(
    ("builtin", "model", "login"), [("prompts", "sonnet", "second"), ("techlead", "opus", "first")]
)
async def test_only_the_prompts_seat_skips_a_login_that_leaves_its_prompts_on(
    agent, tmp_path, launched, rows, builtin, model, login
):
    """The prompts seat answers permission prompts for the person, so nothing above it would answer its own (§4.9d
    *How each one runs*): its fill passes over a login whose `unattended_args` leave them on. A tech lead's does not."""
    rows.update({"hookstub:first": _row("acct-1", [model], asks=True), "hookstub:second": _row("acct-2", [model])})
    sid = await _held_seat(agent, tmp_path, builtin)
    await _fill(agent, sid)
    assert agent.sessions[sid].login == f"hookstub:{login}"


async def test_a_prompts_seat_whose_every_login_asks_is_not_filled(agent, tmp_path, launched, rows):
    rows.update(
        {
            "hookstub:first": _row("acct-1", ["sonnet"], asks=True),
            "hookstub:second": _row("acct-2", ["sonnet"], asks=True),
        }
    )
    sid = await _held_seat(agent, tmp_path, "prompts")
    old = agent.sessions[sid]
    await _fill(agent, sid)
    assert agent.sessions[sid] is old and not launched
    assert agent.unfillable[sid] == "no login usable"


async def test_a_fill_reads_the_real_logins_and_passes_over_one_at_its_reserve(agent, tmp_path, launched, monkeypatch):
    """TD-2251: the pick's rows come from the home's own `tools` and `gate` replies (`teamstore.login_rows` left
    real), so a first login whose account is over its reserve is passed over and the seat fills on the second."""
    families = {"families": ["opus"]}
    card = {
        "adapter": "hookstub",
        "accounts": [{"key": "acct-1", "models": families}, {"key": "acct-2", "models": families}],
        "logins": [
            {"name": "first", "state": "signed_in", "account": "acct-1"},
            {"name": "second", "state": "signed_in", "account": "acct-2"},
        ],
    }
    over = {"label": "week", "pct": 90, "reserve": 20, "resets": "2099-01-01T00:00:00Z"}
    monkeypatch.setattr(agent, "rpc_tools", AsyncMock(return_value={"tools": [card]}))
    monkeypatch.setattr(agent, "rpc_gate", AsyncMock(return_value={"accounts": {"acct-1": {"windows": [over]}}}))
    agent._usage, agent._usage_acct = {}, {}
    sid = await _held_seat(agent, tmp_path)
    await _fill(agent, sid)
    new = agent.sessions[sid]
    assert (new.login, new.account) == ("hookstub:second", "acct-2"), "the login at its reserve is passed over"
    assert launched[-1] == {"profile": "second", "model": "opus"} and sid not in agent.unfillable


async def test_a_directors_record_with_no_model_or_list_is_not_filled_after_the_cut_over(
    agent, tmp_path, launched, rows
):
    """TD-2254, TD-2068 slice 8: the director's record has no `builtin`, and rule 3 still reaches it after the cut-over
    (`_rules_reach`). Its fill picks from its own `seat_model` and `login_list` (§4.9e *The launch on a login*), so a
    record carrying neither is not launched as before: nothing is filled and it *cannot run*."""
    rows.update({"hookstub:first": _row("acct-1", ["sonnet"]), "hookstub:second": _row("acct-2", ["sonnet"])})
    await park_ticks(agent)
    (paths.home() / "logins.yml").write_text(LOGINS)
    (tmp_path / "repo").mkdir(exist_ok=True)
    async with LocalClient() as person:
        sid = (
            await person.call(
                "create",
                name="director-t",
                dir=str(tmp_path / "repo"),
                adapter="hookstub",
                unattended=True,
                supervised=True,
                held=True,
                prompt="the director's brief",
                seat={"trigger": "prompt"},
            )
        )["id"]
    (paths.home() / "settings.yml").write_text(SETTINGS)
    agent._read_cut_over()
    old = agent.sessions[sid]
    assert not old.builtin and agent._rules_reach(old), "rule 3 reaches the director's record after the cut-over"
    old.seat_due = {"at": datetime.now(UTC).isoformat(), "by": "prompt"}
    await _fill(agent, sid)
    new = agent.sessions[sid]
    assert new is old and not launched, "nothing is launched as before"
    assert agent.unfillable[sid] == "cannot run"


async def test_a_built_in_seat_on_a_node_sends_its_sets_list_as_names(agent, tmp_path, launched, rows):
    """TD-2068 (§4.9d *Where a seat's session launches*, §4.9e *A team on a node*): a built-in seat's fill on a node
    sends the set's list as names and the seat's model with no login, whatever the home's own logins could run, and
    the node's own launch picks; the home reads none of that node's logins."""
    rows.update({"hookstub:first": _row("acct-1", ["opus"]), "hookstub:second": _row("acct-2", ["opus"])})
    sid = await _held_seat(agent, tmp_path)
    s = agent.sessions[sid]
    assert (await agent._builtin_login(s))["login"] == "hookstub:first", "on the home's own host it picks a login"
    s.host = "a-node"
    assert agent._on_set_login(s)
    assert await agent._builtin_login(s) == {
        "profile": "",
        "seat_model": "opus",
        "login_list": ["hookstub:first", "hookstub:second"],
    }
    rows.clear()  # the home's own logins are not read for a node
    assert (await agent._builtin_login(s))["seat_model"] == "opus" and sid not in agent.unfillable


async def test_a_node_mark_holds_the_seats_fill_on_that_node_alone(agent, tmp_path, launched, rows):
    """The home's mark that a node found no login of the set's list offering the seat's model (`builtins_node_cannot`)
    makes the seat *cannot run* there with nothing sent, while the list and the model are the ones it names; a mark
    for another node, another model or another list holds nothing."""
    sid = await _held_seat(agent, tmp_path)
    s = agent.sessions[sid]
    s.host = "a-node"
    order = ["hookstub:first", "hookstub:second"]
    for mark, held in (
        ({"other-node": {"model": "opus", "logins": order}}, False),
        ({"a-node": {"model": "sonnet", "logins": order}}, False),
        ({"a-node": {"model": "opus", "logins": ["hookstub:first"]}}, False),
        ({"a-node": {"model": "opus", "logins": order}}, True),
    ):
        agent.unfillable.pop(sid, None)
        agent._host_rec["builtins"] = {"default": {"node_cannot_run": {"tech-lead": mark}}}
        got = await agent._builtin_login(s)
        assert (got is None) is held, mark
        assert (agent.unfillable.get(sid) == "cannot run") is held, mark


def _on_a_node(agent, monkeypatch, sid: str, refused: str | None, **launch) -> list[dict]:
    """The seat's record moved to a node, its launch record read as the node's (with `launch` added), and the node's
    `create` refused with `refused`'s words (or answered); returns what each `create` the home routed there was
    handed."""
    s = agent.sessions[sid]
    s.host = "a-node"
    sent: list[dict] = []

    async def route(method, params, _caller, host):
        sent.append({"method": method, **params})
        if refused:
            raise RpcError(refused)
        return {"id": f"{sid}@{host}"}

    monkeypatch.setattr(agent, "_read_launch", lambda _address: {"name": s.name, "adapter": "hookstub", **launch})
    monkeypatch.setattr(agent, "_route_act", route)
    return sent


@pytest.mark.parametrize(
    ("words", "word", "marked"),
    [
        (f"{teamstore.NO_LOGIN_USABLE}: every login of the list is at its reserve", "no login usable", False),
        (f"{teamstore.NO_LOGIN_OFFERS} opus", "cannot run", True),
    ],
)
async def test_a_nodes_list_refusal_is_no_fill_and_counts_nothing(
    agent, tmp_path, launched, rows, monkeypatch, words, word, marked
):
    """§4.9d *How each one runs*: a node that refuses a fill for its list, before anything is made, has made no fill:
    no `restarts` entry, no fill ceiling spent, and the seat unfillable with the node's words; *no login offers* also
    marks the set *cannot run* the seat on that node, so the next fill sends nothing there."""
    sid = await _held_seat(agent, tmp_path)
    sent = _on_a_node(agent, monkeypatch, sid, words)
    before = list(agent.sessions[sid].restarts)
    await _fill(agent, sid)
    s = agent.sessions[sid]
    assert sent and sent[0]["seat_model"] == "opus" and not sent[0].get("login"), "the list went as names"
    assert sent[0]["login_list"] == ["hookstub:first", "hookstub:second"] and sent[0]["host"] == "a-node"
    assert s.restarts == before, "no fill was made, so none is counted"
    assert agent.unfillable[sid] == word
    marks = ((agent._host_rec.get("builtins") or {}).get("default") or {}).get("node_cannot_run") or {}
    assert bool(marks.get("tech-lead", {}).get("a-node")) is marked
    agent.unfillable.pop(sid, None)
    await _fill(agent, sid)
    assert len(sent) == (1 if marked else 2), "a marked node is sent nothing; a wait is asked again"


async def test_any_other_failed_create_on_a_node_is_a_counted_failed_fill(agent, tmp_path, launched, rows, monkeypatch):
    sid = await _held_seat(agent, tmp_path)
    _on_a_node(agent, monkeypatch, sid, "the node's disk is full")
    await _fill(agent, sid)
    last = agent.sessions[sid].restarts[-1]
    assert last["why"] == "fill" and "disk is full" in last["error"]


async def test_a_directors_fill_on_a_node_sends_its_own_list_and_marks_no_set(
    agent, tmp_path, launched, rows, monkeypatch
):
    """The director's fill on a node sends its own record's `seat_model` and `login_list`; its *no login offers* is
    *cannot run* with no set marked, since the director has none."""
    sid = await _held_seat(agent, tmp_path, "prompts")
    s = agent.sessions[sid]
    s.builtin, s.seat_model, s.login_list = None, "sonnet", ["hookstub:second"]
    sent = _on_a_node(agent, monkeypatch, sid, f"{teamstore.NO_LOGIN_OFFERS} sonnet")
    await _fill(agent, sid)
    assert (sent[0]["seat_model"], sent[0]["login_list"]) == ("sonnet", ["hookstub:second"])
    assert agent.unfillable[sid] == "cannot run" and not agent._host_rec.get("builtins")


@pytest.mark.parametrize(("why", "word"), [("fill", "fill ceiling"), ("crash", "restart ceiling")])
async def test_an_ended_seat_at_its_ceiling_keeps_the_ceilings_word(
    agent, tmp_path, launched, rows, monkeypatch, why, word
):
    """TD-2254: rule 3's pass reads an ended, not due seat's login only where its own ceiling does not refuse it, so a
    seat at its fill or restart ceiling whose set also cannot run it keeps the ceiling's word in `unfillable`."""
    rows.update({"hookstub:first": _row("acct-1", ["sonnet"]), "hookstub:second": _row("acct-2", ["sonnet"])})
    sid = await _held_seat(agent, tmp_path)
    s = agent.sessions[sid]
    monkeypatch.setattr(agent, "_builtin_hold", lambda *a, **kw: None)
    monkeypatch.setattr(agent, "_seat_due", lambda *a, **kw: None)
    s.seat_due = None
    s.restart_ceiling = {"at": datetime.now(UTC).isoformat(), "count": 6, "why": why}
    await agent._seat_pass(s, datetime.now(UTC), list(agent.sessions.values()))
    assert agent.unfillable[sid] == word and not launched


@pytest.mark.parametrize(
    ("adapter", "launch"),
    [("shell", {}), ("hookstub", {"profile": "oldprof"})],
    ids=["another-tool", "an-older-profile"],
)
async def test_a_seat_whose_last_launch_is_not_the_logins_is_filled_on_it(
    agent, tmp_path, launched, rows, adapter, launch
):
    """A fill replays the record's last launch, and a launch on a login refuses an adapter or a profile not the
    login's (§4.9e *The launch on a login*): the fill's own arguments put the login's tool and its profile in their
    place (TD-2252)."""
    (paths.home() / "profiles.yml").write_text("profiles:\n  oldprof: {adapter: hookstub}\n")
    rows.update({"hookstub:first": _row("acct-1", ["opus"]), "hookstub:second": _row("acct-2", ["opus"])})
    sid = await _held_seat(agent, tmp_path, adapter=adapter, **launch)
    old = agent.sessions[sid]
    assert (old.adapter, old.profile or "") == (adapter, launch.get("profile", ""))
    await _fill(agent, sid)
    new = agent.sessions[sid]
    assert new is not old and not any(e.get("error") for e in new.restarts), "the fill was made"
    assert (new.login, new.adapter, new.profile) == ("hookstub:first", "hookstub", "first")
    assert launched[-1] == {"profile": "first", "model": "opus"}


async def test_a_seat_filled_on_one_login_is_filled_on_the_next_once_it_is_at_its_reserve(
    agent, tmp_path, launched, rows
):
    """A fill on a login writes the login's name as the record's profile, so the next fill's replay names it: on
    another login that is no profile of its own, and the fill puts the next login's in its place (TD-2252)."""
    rows.update({"hookstub:first": _row("acct-1", ["opus"]), "hookstub:second": _row("acct-2", ["opus"])})
    sid = await _held_seat(agent, tmp_path)
    await _fill(agent, sid)
    first = agent.sessions[sid]
    assert (first.login, first.profile) == ("hookstub:first", "first")
    async with LocalClient() as person:
        await person.call("kill", id=sid)
    rows["hookstub:first"]["at_reserve"] = True
    agent.sessions[sid].seat_due = {"at": datetime.now(UTC).isoformat(), "by": "asks"}
    await _fill(agent, sid)
    second = agent.sessions[sid]
    assert second is not first and not any(e.get("error") for e in second.restarts), "the second fill was made"
    assert (second.login, second.account, second.adapter, second.profile) == (
        "hookstub:second",
        "acct-2",
        "hookstub",
        "second",
    )
    assert launched[-1] == {"profile": "second", "model": "opus"}


async def test_a_seat_is_filled_from_the_set_its_repo_picked(agent, tmp_path, launched, rows):
    """§4.9d *The login a seat starts on*: a built-in seat starts on a login of the set its repo uses, read by the
    repo's name, not the `default` set's, with that set's model and list (TD-2253)."""
    settings = SETTINGS + (
        "  night:\n    models: {tech-lead: sonnet}\n    logins: [hookstub:second]\nrepos:\n  repo: {builtins: night}\n"
    )
    rows.update(
        {"hookstub:first": _row("acct-1", ["opus", "sonnet"]), "hookstub:second": _row("acct-2", ["opus", "sonnet"])}
    )
    sid = await _held_seat(agent, tmp_path, settings=settings)
    agent.sessions[sid].repo = str(tmp_path / "repo")
    await _fill(agent, sid)
    new = agent.sessions[sid]
    assert new.login == "hookstub:second", "the repo's set, not default's"
    assert (new.seat_model, new.login_list) == ("sonnet", ["hookstub:second"])
    assert launched[-1] == {"profile": "second", "model": "sonnet"}


async def test_a_seat_neither_built_in_nor_the_director_is_filled_as_before(agent, tmp_path, launched, rows):
    """TD-2254, TD-2068 slice 8: after the cut-over only a built-in seat's record and the director's pick a login
    (`_on_set_login`); a manager on call's record (a `team` seat, no `builtin`) is launched as before."""
    rows.update({"hookstub:first": _row("acct-1", ["opus"]), "hookstub:second": _row("acct-2", ["opus"])})
    sid = await _held_seat(agent, tmp_path)
    s = agent.sessions[sid]
    s.builtin, s.seat = None, {"trigger": "team"}
    assert agent._first_shape_off and not agent._on_set_login(s)
    assert await agent._builtin_login(s) == {}


NODE_LAUNCH = {"profile": "", "seat_model": "opus", "login_list": ["hookstub:first", "hookstub:second"]}


@pytest.mark.parametrize("why", ["crash", "lost-brief"])
@pytest.mark.parametrize(
    ("words", "word", "marked"),
    [
        (f"{teamstore.NO_LOGIN_USABLE}: every login of the list is at its reserve", "no login usable", False),
        (f"{teamstore.NO_LOGIN_OFFERS} opus", "cannot run", True),
    ],
)
async def test_a_nodes_list_refusal_of_a_replay_is_no_restart(
    agent, tmp_path, launched, rows, monkeypatch, why, words, word, marked
):
    """§4.9d *How each one runs*: rule 1's crash and lost-brief replays of a built-in seat on a node send its launch
    record's list as names, and the node's refusal of that list counts toward no restart ceiling; *no login offers*
    marks the set, and the mark holds the next replay with nothing sent."""
    sid = await _held_seat(agent, tmp_path)
    sent = _on_a_node(agent, monkeypatch, sid, words, **NODE_LAUNCH)
    s = agent.sessions[sid]
    before = list(s.restarts)
    await agent._replay(s, why, keep_mail=True)
    assert sent and (sent[0]["seat_model"], sent[0]["login_list"]) == ("opus", NODE_LAUNCH["login_list"])
    assert not sent[0].get("login") and s.restarts == before, "nothing was made, so no restart is counted"
    assert agent.unfillable[sid] == word
    await agent._replay(s, why, keep_mail=True)
    assert len(sent) == (1 if marked else 2), "a marked node is sent nothing; a wait is asked again"
    assert s.restarts == before


async def test_a_replay_on_a_node_of_a_record_no_built_in_seats_counts_the_refusal(
    agent, tmp_path, launched, rows, monkeypatch
):
    """A team's stage session on a node (slice 11's launch) is no built-in seat: its replay refused for the list is a
    failed restart that counts, as before."""
    sid = await _held_seat(agent, tmp_path)
    s = agent.sessions[sid]
    s.builtin, s.seat = None, None
    _on_a_node(agent, monkeypatch, sid, f"{teamstore.NO_LOGIN_OFFERS} opus", **NODE_LAUNCH)
    await agent._replay(s, "crash", keep_mail=True)
    assert s.restarts[-1]["why"] == "crash" and teamstore.NO_LOGIN_OFFERS in s.restarts[-1]["error"]
    assert not agent._host_rec.get("builtins")
