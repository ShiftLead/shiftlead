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


async def _held_seat(agent, tmp_path, builtin: str = "techlead", settings: str = SETTINGS) -> str:
    """A built-in seat's record as the home writes it, held, before any login: then the marker, and the seat due."""
    await park_ticks(agent)
    (paths.home() / "logins.yml").write_text(LOGINS)
    (tmp_path / "repo").mkdir(exist_ok=True)
    async with LocalClient() as person:
        sid = (
            await person.call(
                "create",
                name=f"{builtin}-t",
                dir=str(tmp_path / "repo"),
                adapter="hookstub",
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


async def test_the_directors_record_is_filled_as_before_after_the_cut_over(agent, tmp_path, launched, rows):
    """TD-2254: only a built-in seat's record picks its login (`_on_set_login`). The director's record has no `builtin`
    and rule 3 still reaches it after the cut-over (`_rules_reach`), so its fill is launched as before: no login, no
    model, no `unfillable` word."""
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
    assert new is not old, "the director's record was filled"
    assert new.login is None and new.seat_model is None and sid not in agent.unfillable
    assert launched[-1] == {"profile": ""}, "launched as before: no login, no model"


async def test_a_built_in_seat_on_a_node_picks_no_login(agent, tmp_path, launched, rows):
    """TD-2254: a built-in seat's record on a node is launched as before until the node half (§4.9e): its fill reads
    no set, even where the home's own logins could run it."""
    rows.update({"hookstub:first": _row("acct-1", ["opus"]), "hookstub:second": _row("acct-2", ["opus"])})
    sid = await _held_seat(agent, tmp_path)
    s = agent.sessions[sid]
    assert await agent._builtin_login(s) != {}, "on the home's own host it picks a login"
    s.host = "a-node"
    assert not agent._on_set_login(s)
    assert await agent._builtin_login(s) == {}, "on a node the fill is as before"


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
