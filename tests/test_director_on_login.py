"""TD-2068, design §4.9e *The launch on a login*, §4.9d *How each one runs*: after the cut-over the director takes its
`model:` and ordered `logins:` from `org.yml`'s `director:`. The home writes them on the director's held record as its
`seat_model` and `login_list` (the host agent reads no `org.yml`), and rule 3's fill launches it on the first usable
login of that list offering the model, passing over a login that leaves its prompts on."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import yaml
from conftest import park_ticks

from sessionorc import paths, teamstore
from sessionorc.adapters import LaunchSpec
from sessionorc.agent_common import RpcError, _on_login
from sessionorc.client import LocalClient
from sessionorc.models import Session
from shiftlead import org as orgmod
from shiftlead import stage_seats, teamrun, teams

LOGINS = """logins:
  hookstub:first: {folder: /c/first, account: acct-1}
  hookstub:second: {folder: /c/second, account: acct-2}
accounts: {}
forgotten: {}
"""
SETTINGS = "cut_over: 2026-12-01\n"
ORDER = ["hookstub:first", "hookstub:second"]


def _row(account: str, models: list[str], **kw) -> dict:
    return {"state": "signed_in", "account": account, "pin": None, "models": models, "at_reserve": False, **kw}


@pytest.fixture
def launched(hookstub, monkeypatch):
    seen: list[dict] = []

    def launch(*, profile, resume, prompt, unattended, cwd, name="", **kw):
        seen.append({"profile": profile, **kw})
        return LaunchSpec(argv=["bash", "--norc"])

    monkeypatch.setattr(hookstub, "launch", launch)
    return seen


@pytest.fixture
def rows(agent, monkeypatch):
    held: dict[str, dict] = {}
    monkeypatch.setattr(agent, "rpc_tools", AsyncMock(return_value={"tools": []}))
    monkeypatch.setattr(agent, "rpc_gate", AsyncMock(return_value={"accounts": {}}))
    monkeypatch.setattr(teamstore, "login_rows", lambda *a, **kw: held)
    return held


async def _held_director(agent, tmp_path, **on_list) -> str:
    """The director's record as the home writes it after the cut-over: held, with its model and list and no login."""
    await park_ticks(agent)
    (paths.home() / "logins.yml").write_text(LOGINS)
    (paths.home() / "settings.yml").write_text(SETTINGS)
    agent._read_cut_over()
    (tmp_path / "director").mkdir(exist_ok=True)
    async with LocalClient() as person:
        sid = (
            await person.call(
                "create",
                name="director",
                dir=str(tmp_path / "director"),
                adapter="hookstub",
                unattended=True,
                supervised=True,
                held=True,
                prompt="the director's brief",
                seat={"trigger": "prompt"},
                **({"seat_model": "opus", "login_list": ORDER} | on_list),
            )
        )["id"]
    agent.sessions[sid].seat_due = {"at": datetime.now(UTC).isoformat(), "by": "prompt"}
    return sid


async def _fill(agent, sid: str) -> None:
    await agent._fill(agent.sessions[sid], datetime.now(UTC), list(agent.sessions.values()))


@pytest.mark.integration
async def test_the_held_record_keeps_its_model_and_list_with_no_login(agent, tmp_path, launched, rows):
    s = agent.sessions[await _held_director(agent, tmp_path)]
    assert (s.login, s.seat_model, s.login_list) == (None, "opus", ORDER) and not launched


@pytest.mark.integration
async def test_the_director_is_filled_on_its_lists_first_usable_login(agent, tmp_path, launched, rows):
    rows.update({"hookstub:first": _row("acct-1", ["opus"]), "hookstub:second": _row("acct-2", ["opus"])})
    sid = await _held_director(agent, tmp_path)
    await _fill(agent, sid)
    new = agent.sessions[sid]
    assert (new.login, new.account, new.seat_model, new.login_list) == ("hookstub:first", "acct-1", "opus", ORDER)
    assert launched[-1] == {"profile": "first", "model": "opus"}


@pytest.mark.integration
async def test_the_director_passes_over_a_login_that_leaves_its_prompts_on(agent, tmp_path, launched, rows):
    rows.update({"hookstub:first": _row("acct-1", ["opus"], asks=True), "hookstub:second": _row("acct-2", ["opus"])})
    sid = await _held_director(agent, tmp_path)
    await _fill(agent, sid)
    assert agent.sessions[sid].login == "hookstub:second"


@pytest.mark.integration
@pytest.mark.parametrize(
    ("first", "second", "word"),
    [
        (_row("acct-1", ["opus"], asks=True), _row("acct-2", ["opus"], asks=True), "no login usable"),
        (_row("acct-1", ["sonnet"]), _row("acct-2", ["haiku"]), "cannot run"),
    ],
    ids=["every-login-asks", "none-offers"],
)
async def test_no_login_fit_for_it_fills_nothing_and_says_why(agent, tmp_path, launched, rows, first, second, word):
    rows.update({"hookstub:first": first, "hookstub:second": second})
    sid = await _held_director(agent, tmp_path)
    old = agent.sessions[sid]
    await _fill(agent, sid)
    assert agent.sessions[sid] is old and not launched and agent.unfillable[sid] == word


@pytest.mark.unit
def test_a_seat_model_and_list_with_no_login_are_a_held_records_alone(tmp_path):
    with pytest.raises(RpcError, match="ride a launch on a login"):
        _on_login(None, "hookstub", "", "opus", ORDER, tmp_path)
    with pytest.raises(RpcError, match="names its seat_model and its login_list"):
        _on_login(None, "hookstub", "", "opus", None, tmp_path, held=True)
    got = _on_login(None, "hookstub", "", "opus", ORDER, tmp_path, held=True)
    assert got == {"login": None, "account": None, "profile": "", "login_list": ORDER}
    assert _on_login(None, "hookstub", "", None, None, tmp_path, held=True) is None


def _org(tmp_path: Path, monkeypatch, director: dict) -> orgmod.Org:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("SHIFTLEAD_HOME", str(home))
    monkeypatch.setattr(teams, "DIRECTOR_DIR", str(tmp_path / "director"))
    (home / "org.yml").write_text(yaml.safe_dump({"director": director}))
    return orgmod.load()


@pytest.mark.unit
def test_org_yml_reads_a_directors_model_and_logins(tmp_path, monkeypatch):
    d = _org(tmp_path, monkeypatch, {"model": "opus", "logins": ORDER}).director
    assert d is not None and (d.model, d.logins, d.profile) == ("opus", ORDER, None)
    with pytest.raises(ValueError, match="logins' keys in order"):
        _org(tmp_path, monkeypatch, {"model": "opus", "logins": "hookstub:first"})


@pytest.mark.unit
def test_after_the_cut_over_the_director_is_written_on_its_model_and_list(tmp_path, monkeypatch):
    monkeypatch.setattr(teamstore, "first_shape_off", lambda: True)
    p = teams.director_create(_org(tmp_path, monkeypatch, {"model": "opus", "logins": ORDER}))
    assert p is not None
    assert (p["adapter"], p["profile"], p["seat_model"], p["login_list"]) == ("hookstub", "", "opus", ORDER)
    assert p["held"] and p["seat"] == {"trigger": "prompt"} and "login" not in p


@pytest.mark.unit
@pytest.mark.parametrize(
    ("director", "match"),
    [
        ({"profile": "grind", "model": "opus", "logins": ORDER}, "profiles went at the switch-over"),
        ({"logins": ORDER}, "names no model or no logins"),
        ({"model": "opus"}, "names no model or no logins"),
        ({"model": "opus", "logins": ["first"]}, "is not <tool>:<name>"),
    ],
)
def test_after_the_cut_over_a_director_with_no_model_or_list_is_refused(tmp_path, monkeypatch, director, match):
    monkeypatch.setattr(teamstore, "first_shape_off", lambda: True)
    with pytest.raises(teams.TeamError, match=match):
        teams.director_create(_org(tmp_path, monkeypatch, director))


@pytest.mark.unit
def test_before_the_cut_over_the_director_carries_no_model_or_list(tmp_path, monkeypatch):
    monkeypatch.setattr(teamstore, "first_shape_off", lambda: False)
    p = teams.director_create(_org(tmp_path, monkeypatch, {"model": "opus", "logins": ORDER}))
    assert p is not None and "seat_model" not in p and "login_list" not in p


class _Home:
    def __init__(self, *records):
        self.records, self.calls = list(records), []

    def __call__(self, method, **params):
        self.calls.append((method, params))
        if method == "list":
            return list(self.records)
        if method == "create":
            return {"id": "ao-director"}
        raise AssertionError(method)


def _stale(state: str = "closed", **kw) -> dict:
    return {"id": "ao-director", "name": "director", "state": state, "seat": {"trigger": "prompt"}, **kw}


@pytest.mark.unit
@pytest.mark.parametrize(
    "record",
    [_stale(profile="grind"), _stale(seat_model="sonnet", login_list=ORDER), _stale(seat_model="opus", login_list=[])],
    ids=["before-the-cut-over", "another-model", "another-list"],
)
def test_an_ended_director_record_on_another_model_or_list_is_written_again_its_mail_kept(
    tmp_path, monkeypatch, record
):
    monkeypatch.setattr(teamstore, "first_shape_off", lambda: True)
    org = _org(tmp_path, monkeypatch, {"model": "opus", "logins": ORDER})
    home = _Home(record)
    assert stage_seats.write_director(home, org) == ["director: written again on the org's model and logins"]
    (method, params) = home.calls[-1]
    assert method == "create" and params["keep_mail"] is True
    assert (params["seat_model"], params["login_list"]) == ("opus", ORDER)


@pytest.mark.unit
def test_a_director_record_on_the_keys_model_and_list_is_left_and_a_live_one_waits(tmp_path, monkeypatch):
    monkeypatch.setattr(teamstore, "first_shape_off", lambda: True)
    org = _org(tmp_path, monkeypatch, {"model": "opus", "logins": ORDER})
    home = _Home(_stale(seat_model="opus", login_list=ORDER))
    assert stage_seats.write_director(home, org) == [] and not any(m == "create" for m, _ in home.calls)
    live = _Home(_stale("working", seat_model="sonnet", login_list=ORDER))
    assert stage_seats.write_director(live, org) == [] and not any(m == "create" for m, _ in live.calls)
    assert teamrun.is_director(live.records[0]), "kept until its session ends"


def _director_session(**kw):
    base = {"id": "ao-director", "name": "director", "kind": "interactive", "adapter": "hookstub", "dir": "/d"}
    return Session(**{**base, "seat": {"trigger": "prompt"}, **kw})


@pytest.mark.unit
def test_the_pass_graph_on_another_model_writes_the_director_again_and_on_the_keys_asks_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(teamstore, "first_shape_off", lambda: True)
    org = _org(tmp_path, monkeypatch, {"model": "opus", "logins": ORDER})
    old = _director_session(state="closed", seat_model="sonnet", login_list=ORDER)
    home = _Home(_stale(seat_model="sonnet", login_list=ORDER))
    assert stage_seats.write_director(home, org, {old.id: old}) == [
        "director: written again on the org's model and logins"
    ]
    assert home.calls[-1][0] == "create"
    current = _director_session(state="closed", seat_model="opus", login_list=ORDER)
    untouched = _Home(_stale(seat_model="opus", login_list=ORDER))
    assert stage_seats.write_director(untouched, org, {current.id: current}) == []
    assert untouched.calls == [], "a graph that reads as the key wants asks nothing of the home"


@pytest.mark.unit
def test_an_unrelated_ended_record_beside_a_live_director_on_an_old_model_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(teamstore, "first_shape_off", lambda: True)
    org = _org(tmp_path, monkeypatch, {"model": "opus", "logins": ORDER})
    other = {"id": "ao-w", "name": "w", "state": "exited", "seat": None}
    home = _Home(other, _stale("working", seat_model="sonnet", login_list=ORDER))
    assert stage_seats.write_director(home, org) == []
    assert not any(m == "create" for m, _ in home.calls)


@pytest.mark.unit
def test_before_the_cut_over_an_ended_director_with_no_model_or_list_is_not_written_again(tmp_path, monkeypatch):
    monkeypatch.setattr(teamstore, "first_shape_off", lambda: False)
    org = _org(tmp_path, monkeypatch, {"model": "opus", "logins": ORDER})
    home = _Home(_stale(profile="grind"))
    assert stage_seats.write_director(home, org) == []
    assert not any(m == "create" for m, _ in home.calls)
