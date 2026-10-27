"""CI that never started is the person's (design §4.4 *Its spell*, §4.5a *Inbox row: CI not starting*,
§4.10 *Told on Telegram*; TD-687 slice 1): the home's spells, stepped once per successful reading;
`ci_rerun`, the row's **Re-run**, a person's own act served at the home; the run-status reads that keep a
spell standing while a re-run is pending; and the Telegram line, told once per spell. No `gh` is run: the
two `reports` calls are stubbed."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks

from sessionorc import notify, reports, workorders
from sessionorc import settings as settings_mod
from sessionorc.agent_common import RpcError
from sessionorc.store import HostStore

BILLING = "The job was not started because recent account payments have failed"
NR = {"reason": BILLING, "kind": "billing", "runs": [11, 12]}


def _z(t: datetime) -> str:
    return t.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _pr(n: int, owner: str = "ContractMatch", repo: str = "samscrape", runs=(11, 12)) -> dict:
    return {
        "number": n,
        "checks": "not_run",
        "not_run": {**NR, "runs": list(runs)},
        "url": f"https://github.com/{owner}/{repo}/pull/{n}",
    }


def _repos(*prs: dict, error: bool = False) -> dict:
    reading = {"remote": "git@github.com:ContractMatch/samscrape.git", "prs": {"open": list(prs)}}
    if error:
        reading["prs"]["error"] = "gh: rate limited"
    return {"/r/samscrape": reading}


# -- the step, pure ----------------------------------------------------------------------------------


def test_a_spell_begins_keeps_its_since_and_ends_after_two_clear_readings():
    g = workorders.ci_not_run(_repos(_pr(1097), _pr(1099)), {})
    one = workorders.ci_spells({}, g, set(), "T0")
    assert one["contractmatch"]["since"] == "T0" and one["contractmatch"]["clear"] == 0
    assert [i["pr"] for i in one["contractmatch"]["row"]["items"]] == [1097, 1099]
    # grouped again later: the same spell, its since kept
    two = workorders.ci_spells(one, g, set(), "T1")
    assert two["contractmatch"]["since"] == "T0"
    # one clear reading counts, a grouping again resets, two in a row end it
    three = workorders.ci_spells(two, {}, set(), "T2")
    assert three["contractmatch"]["clear"] == 1 and three["contractmatch"]["row"] == two["contractmatch"]["row"]
    four = workorders.ci_spells(three, g, set(), "T3")
    assert four["contractmatch"]["clear"] == 0 and four["contractmatch"]["since"] == "T0"
    five = workorders.ci_spells(workorders.ci_spells(four, {}, set(), "T4"), {}, set(), "T5")
    assert five == {}
    assert one["contractmatch"]["clear"] == 0, "never mutated"


def test_a_failed_reading_counts_for_nothing_and_a_pending_rerun_resets_the_count():
    g = workorders.ci_not_run(_repos(_pr(1097)), {})
    spells = workorders.ci_spells({}, g, set(), "T0")
    failed = workorders.ci_failed_owners(_repos(error=True))
    assert failed == {"contractmatch"}
    assert (
        workorders.ci_failed_owners({"/r/lab": {"remote": "git@gitlab.com:x/lab.git", "prs": {"error": "x"}}}) == set()
    )
    # a failed reading: nothing grouped, nothing counted
    assert workorders.ci_spells(spells, {}, failed, "T1") == spells
    once = workorders.ci_spells(spells, {}, set(), "T1")
    assert once["contractmatch"]["clear"] == 1
    # a re-run's run still pending: the count goes back to 0 and the spell stands
    pending = {
        k: {**v, "rerun": {"at": "T1", "runs": [{"root": "/r/samscrape", "run": 11, "pending": True}]}}
        for k, v in once.items()
    }
    for _ in range(3):
        pending = workorders.ci_spells(pending, {}, set(), "T2")
        assert pending["contractmatch"]["clear"] == 0
    done = {
        k: {**v, "rerun": {**v["rerun"], "runs": [{**v["rerun"]["runs"][0], "pending": False}]}}
        for k, v in pending.items()
    }
    assert workorders.ci_spells(workorders.ci_spells(done, {}, set(), "T3"), {}, set(), "T4") == {}


def test_the_rerun_names_every_run_once_with_its_root():
    g = workorders.ci_not_run(_repos(_pr(1097), _pr(1099, runs=(12, 13))), {
        "samscrape": {"root": "/r/samscrape", "main": "m" * 40, "checks_not_run": {**NR, "runs": [14]},
                      "origin": "https://github.com/ContractMatch/samscrape"},
    })  # fmt: skip
    spell = workorders.ci_spells({}, g, set(), "T0")["contractmatch"]
    assert workorders.ci_rerun_runs(spell) == [("/r/samscrape", r) for r in (11, 12, 13, 14)]


def test_the_host_record_keeps_the_spells(tmp_path):
    store = HostStore(tmp_path / "host.json")
    store.save({"teams": {}, "ci_spells": {"contractmatch": {"owner": "ContractMatch", "since": "T0", "clear": 0}}})
    assert store.load()["ci_spells"]["contractmatch"]["since"] == "T0"
    store.save({"teams": {}, "ci_spells": {"x": "not a spell"}})
    assert "ci_spells" not in store.load()


def test_the_told_line_is_the_owner_and_the_count():
    assert (
        notify.ci_line("ContractMatch", 3) == "shiftlead · GitHub Actions does not start in ContractMatch · 3 waiting"
    )


# -- at the home -------------------------------------------------------------------------------------


@pytest.fixture
async def agent(agent):
    """The tick parked (TD-1087): the loop's own `_ci_spells_step` ran beside the test's, and under load
    one wrote `_host_rec` between two of its reads (`KeyError: 'ci_spells'`)."""
    await park_ticks(agent)
    return agent


@pytest.fixture
def statuses(monkeypatch):
    """`reports.run_status` answering from a map, None (unreadable) for a run not in it."""
    got: dict[int, str | None] = {}
    monkeypatch.setattr(reports, "run_status", lambda root, run, timeout=30.0: got.get(run))
    return got


@pytest.fixture
def reruns(monkeypatch):
    """`reports.run_rerun` recorded, refusing the runs named in `refuse`."""
    calls: list[tuple[str, int]] = []
    refuse: set[int] = set()

    def run(root, run, timeout=30.0):
        calls.append((root, run))
        return "HTTP 403: Resource not accessible" if run in refuse else None

    monkeypatch.setattr(reports, "run_rerun", run)
    return calls, refuse


@pytest.mark.integration
async def test_rerun_is_the_persons_runs_each_run_and_keeps_the_spell_standing(agent, statuses, reruns):
    calls, refuse = reruns
    agent._repos = _repos(_pr(1097), _pr(1099, runs=(12, 13)))
    await agent._ci_spells_step()
    assert (await agent.rpc_host())["ci_spells"]["contractmatch"]["owner"] == "ContractMatch"
    with pytest.raises(RpcError, match=r"^ao-x-w cannot re-run an account's CI: a person's own act"):
        await agent.rpc_ci_rerun("ContractMatch", caller="ao-x-w")
    with pytest.raises(RpcError, match="no \\*CI not starting\\* row for 'nobody'"):
        await agent.rpc_ci_rerun("nobody")
    refuse.add(13)
    got = await agent.rpc_ci_rerun("contractmatch")
    assert got == {"owner": "ContractMatch", "asked": 3, "refused": 1, "why": "HTTP 403: Resource not accessible"}
    assert sorted(calls) == [("/r/samscrape", 11), ("/r/samscrape", 12), ("/r/samscrape", 13)]
    rerun = agent._host_rec["ci_spells"]["contractmatch"]["rerun"]
    assert (rerun["asked"], rerun["refused"]) == (3, 1)
    assert [r["run"] for r in rerun["runs"]] == [11, 12] and all(r["pending"] for r in rerun["runs"])
    assert json.loads(agent.host_store.path.read_text())["ci_spells"]["contractmatch"]["rerun"] == rerun
    # the PRs read pending now (nothing grouped): while a run is queued, or unreadable, the spell stands
    agent._repos = _repos()
    statuses.update({11: "queued"})
    for _ in range(3):
        await agent._ci_spells_step()
        assert agent._host_rec["ci_spells"]["contractmatch"]["clear"] == 0
    # both read completed: two clear readings end the spell, and the record says so
    statuses.update({11: "completed", 12: "completed"})
    await agent._ci_spells_step()
    assert agent._host_rec["ci_spells"]["contractmatch"]["clear"] == 1
    await agent._ci_spells_step()
    assert "ci_spells" not in agent._host_rec and (await agent.rpc_host())["ci_spells"] == {}


@pytest.mark.integration
async def test_rerun_is_served_at_the_home_alone(agent):
    agent.mode = "node"
    try:
        with pytest.raises(RpcError, match="ci_rerun runs at the home"):
            await agent.rpc_ci_rerun("ContractMatch")
    finally:
        agent.mode = "home"


# -- told on Telegram, once per spell ----------------------------------------------------------------


@pytest.fixture
def sent(agent, monkeypatch):
    got: list[tuple[str, str]] = []

    async def record(secrets: str, text: str) -> str | None:
        got.append((secrets, text))
        return None

    monkeypatch.setattr(agent, "_notify_run", record)
    settings_mod.save({"notify": {"telegram": {"on": True, "secrets": "samscrape/prd", "link": "http://kmaster:8765"}}})
    return got


async def _pass(agent, now: datetime) -> None:
    agent._notify_pass(now)
    for _ in range(20):  # the send is a detached task
        if not agent._bg:
            break
        await asyncio.sleep(0.01)


def _spell(agent, since: datetime, n: int = 2) -> None:
    items = [{"repo": "samscrape", "root": "/r/samscrape", "pr": i, "url": "", "runs": [i]} for i in range(n)]
    agent._host_rec["ci_spells"] = {
        "contractmatch": {"owner": "ContractMatch", "since": _z(since), "clear": 0, "row": {"items": items}}
    }


@pytest.mark.integration
async def test_a_spell_is_told_once_and_not_again_inside_it(agent, sent, statuses):
    t0 = datetime.now(UTC)
    _spell(agent, t0)
    await _pass(agent, t0 + timedelta(seconds=30))
    assert sent == [], "inside the hold"
    await _pass(agent, t0 + timedelta(seconds=61))
    assert sent == [
        (
            "samscrape/prd",
            "shiftlead · GitHub Actions does not start in ContractMatch · 2 waiting\n"
            "http://kmaster:8765/inbox?row=ci_not_run%3Acontractmatch",
        )
    ]
    # a new push reads pending for one reading and then `not_run` again: the same spell, not told again
    agent._repos = _repos()
    await agent._ci_spells_step()
    assert agent._host_rec["ci_spells"]["contractmatch"]["clear"] == 1
    await _pass(agent, t0 + timedelta(seconds=90))
    agent._repos = _repos(_pr(1097))
    await agent._ci_spells_step()
    assert agent._host_rec["ci_spells"]["contractmatch"]["since"] == _z(t0)
    await _pass(agent, t0 + timedelta(seconds=120))
    assert len(sent) == 1
    # the spell ends: its key leaves the told list; a later spell is a new row, told again
    agent._repos = _repos()
    await agent._ci_spells_step()
    await agent._ci_spells_step()
    await _pass(agent, t0 + timedelta(seconds=150))
    assert "ci_not_run:contractmatch" not in agent.attention_store.notified
    t1 = t0 + timedelta(minutes=10)
    _spell(agent, t1, n=1)
    await _pass(agent, t1 + timedelta(seconds=61))
    assert sent[1][1].split("\n")[0] == "shiftlead · GitHub Actions does not start in ContractMatch · 1 waiting"


@pytest.mark.integration
async def test_a_snoozed_row_is_not_told_and_a_snooze_that_runs_out_inside_the_spell_tells_nothing(agent, sent):
    t0 = datetime.now(UTC)
    _spell(agent, t0)
    until = _z(t0 + timedelta(minutes=2))
    got = await agent.rpc_attention_snooze("ci_not_run:contractmatch", "ci_not_run", until)
    assert got["row"] == "ci_not_run:contractmatch|ci_not_run"
    await _pass(agent, t0 + timedelta(seconds=61))
    assert sent == [], "snoozed: the person has seen it"
    await _pass(agent, t0 + timedelta(minutes=3))
    await _pass(agent, t0 + timedelta(minutes=8))
    assert sent == [], "the snooze ran out inside the spell: not told again"
    with pytest.raises(RpcError, match="cannot snooze"):
        await agent.rpc_attention_snooze("ci_not_run:contractmatch", "ci_not_run", until, caller="ao-x-w")


@pytest.mark.integration
async def test_a_press_during_a_steps_run_reads_is_kept(agent, monkeypatch, reruns):
    """The press waits for the step in hand and is never overwritten by it (the review of slice 1)."""
    import time

    agent._repos = _repos(_pr(1097))
    await agent._ci_spells_step()
    spell = agent._host_rec["ci_spells"]["contractmatch"]
    agent._host_rec["ci_spells"]["contractmatch"] = {
        **spell,
        "rerun": {"at": "T0", "runs": [{"root": "/r/samscrape", "run": 9, "pending": True}], "asked": 1, "refused": 0},
    }
    monkeypatch.setattr(reports, "run_status", lambda root, run, timeout=30.0: time.sleep(0.3) or "queued")
    step = asyncio.create_task(agent._ci_spells_step())
    await asyncio.sleep(0.05)  # the step is inside its run reads
    got = await agent.rpc_ci_rerun("ContractMatch")
    await step
    assert got["asked"] == 2
    rerun = agent._host_rec["ci_spells"]["contractmatch"]["rerun"]
    assert [r["run"] for r in rerun["runs"]] == [11, 12] and rerun["asked"] == 2


@pytest.mark.integration
async def test_a_snooze_with_telegram_off_is_seen_all_the_same(agent):
    t0 = datetime.now(UTC)
    _spell(agent, t0)
    await agent.rpc_attention_snooze("ci_not_run:contractmatch", "ci_not_run", _z(t0 + timedelta(minutes=2)))
    await _pass(agent, t0 + timedelta(seconds=10))
    assert "ci_not_run:contractmatch" in agent.attention_store.notified
