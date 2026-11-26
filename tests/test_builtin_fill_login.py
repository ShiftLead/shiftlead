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
                seat={"trigger": "asks"} if builtin == "techlead" else {"trigger": "swept", "by": "settings"},
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


@pytest.mark.parametrize(("builtin", "model"), [("techlead", "opus"), ("sweeper", "haiku")])
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
