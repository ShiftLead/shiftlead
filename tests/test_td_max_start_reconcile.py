"""Rule 8's and a schedule's start first drop the held extras the merged `max` no longer holds (design §6 rule 14,
§4.9 *Scaling with the work*; TD-1545): read from `settings.yml` and the records alone, since the home reads no
definition. A missing extra is never written here — it waits for the person's next Start or Apply — and one with
unread mail is kept."""

from __future__ import annotations

from datetime import UTC, datetime

from conftest import park_ticks
from test_work_start import _rec, _Replays, _settled

from sessionorc import settings as settings_mod
from sessionorc.models import SYSTEM, MailEntry


def _held(name: str, line: str, **kw):
    return _rec(name, scale={"line": line}, out_of_work=None, **kw)


def _team(agent):
    mail = _held("grinder-ao-7", "grinder-ao")
    mail.inbox.append(MailEntry(id="m-1", from_=SYSTEM, to=[mail.id], at="2026-11-11T08:00:00Z", kind="note", text="x"))
    return [
        _rec("manager-ao", lane=["TD-900"]),
        _rec("grinder-ao-1", controllers=["ao-t-manager-ao"]),
        _held("grinder-ao-5", "grinder-ao"),  # within the ceiling of 5: kept
        _held("grinder-ao-6", "grinder-ao"),  # past it: removed
        mail,  # past it, with unread mail: kept, its mail waiting for a fill
        _held("techlead-ao-2", "techlead-ao"),  # its seat stored at 0: removed
        _held("fc-ao-2", "fc-ao"),  # no key: its default, which only the definition reads — kept
    ]


def _removes(agent, monkeypatch) -> list[str]:
    gone: list[str] = []

    async def remove(id, caller=None):
        gone.append(id)

    monkeypatch.setattr(agent, "rpc_remove", remove)
    return gone


async def test_rule_8s_start_removes_the_held_extras_past_the_max_and_writes_none(agent, tmp_path, monkeypatch):
    await park_ticks(agent)
    settings_mod.save({"teams": {"g": {"on_work": "start", "max": {"grinder-ao": 5, "techlead-ao": 0}}}})
    replays = _Replays()
    monkeypatch.setattr(agent, "_replay", replays)
    gone = _removes(agent, monkeypatch)
    later = await _settled(agent, tmp_path, *_team(agent))
    await agent._work_marks(later)
    assert sorted(gone) == ["ao-t-grinder-ao-6", "ao-t-techlead-ao-2"]
    assert sorted(c[0] for c in replays.calls) == ["grinder-ao-1", "manager-ao"]  # an extra is never replayed


async def test_a_schedules_start_removes_them_too(agent, tmp_path, monkeypatch):
    await park_ticks(agent)
    settings_mod.save({"teams": {"g": {"max": {"grinder-ao": 5, "techlead-ao": 0}}}})
    monkeypatch.setattr(agent, "_replay", _Replays())
    gone = _removes(agent, monkeypatch)
    recs = _team(agent)
    await _settled(agent, tmp_path, *recs)
    assert await agent._schedule_start("g", recs, datetime.now(UTC), "2026-11-11T10:00:00Z") == "started"
    assert sorted(gone) == ["ao-t-grinder-ao-6", "ao-t-techlead-ao-2"]


async def test_off_reads_every_held_extra_as_surplus_and_no_key_none(agent, tmp_path):
    await park_ticks(agent)
    recs = _team(agent)
    for r in recs:
        r.host = agent.host
    settings_mod.save({"teams": {"g": {"max": "off"}}})
    assert sorted(r.name for r in agent._extras_past("g", recs)) == [
        "fc-ao-2", "grinder-ao-5", "grinder-ao-6", "grinder-ao-7", "techlead-ao-2",
    ]  # fmt: skip
    settings_mod.save({"teams": {"g": {"on_work": "start"}}})
    assert agent._extras_past("g", recs) == []
    # a live extra, another host's and a superseded one are never read as held surplus here
    settings_mod.save({"teams": {"g": {"max": "off"}}})
    live, node, gone = _held("grinder-ao-8", "grinder-ao"), _held("grinder-ao-9", "grinder-ao"), _held("x-2", "x")
    live.state, live.host, node.host, gone.host, gone.superseded_by = "idle", agent.host, "laptop", agent.host, "y"
    assert agent._extras_past("g", [live, node, gone]) == []


async def test_a_reading_that_raises_never_stops_the_start(agent, tmp_path, monkeypatch):
    """Review of #3369: the settings read is outside each removal's own guard, so it is guarded on its own."""
    await park_ticks(agent)
    monkeypatch.setattr(agent, "_replay", _Replays())

    def boom(*a):
        raise ValueError("bad settings")

    monkeypatch.setattr(agent, "_extras_past", boom)
    recs = _team(agent)
    await _settled(agent, tmp_path, *recs)
    assert await agent._schedule_start("g", recs, datetime.now(UTC), "2026-11-11T10:00:00Z") == "started"
