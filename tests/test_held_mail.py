"""TD-1440 slice 2, design §4.5 *A taken-over member*, §4.5a *Inbox row: held · mail waiting*: a member the
person took over and left idle, with mail its doorbell has not rung for half an hour, raises a counted row
with Hand back, Open and Snooze. The view carries the reading (`unread_unrung`, `oldest_unread_at`,
`held_mail_at`), computed at the home for a held member alone; the row is derived from it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sessionorc.models import MailEntry, Session

NOW = datetime.now(UTC).replace(microsecond=0)


def _iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


def _mail(mid: str, to: list[str], ago: timedelta, **kw) -> MailEntry:
    return MailEntry(id=mid, from_="ao-x-w", to=to, at=_iso(NOW - ago), kind=kw.pop("kind", "ask"), text="?", **kw)


def _held(agent, **kw) -> Session:
    base = dict(
        id="ao-x-tl", name="techlead-ao-1", kind="interactive", adapter="claude-code", dir="/tmp/x", state="idle",
        unattended=False, supervised=True, team="t", host=agent.host, by_person=False,
        mode_at=_iso(NOW - timedelta(hours=2)), mode_by="person", mode_via="focus",
    )  # fmt: skip
    s = Session(**{**base, **kw})
    agent.sessions[s.id] = s
    return s


def _reading(agent, s: Session) -> tuple:
    v = agent._view(s)
    return v["unread_unrung"], v["oldest_unread_at"], v["held_mail_at"]


async def test_the_view_counts_a_held_members_unrung_mail_addressed_to_it(agent):
    s = _held(agent)
    s.inbox = [
        _mail("m-1", [s.id], timedelta(minutes=50)),
        _mail("m-2", [f"{s.id}@{agent.host}"], timedelta(minutes=40), kind="note"),
        _mail("m-3", ["ao-x-other"], timedelta(minutes=45)),  # a copy: not addressed to it
        _mail("m-4", [s.id], timedelta(minutes=55), read_at=_iso(NOW)),  # read
        _mail("m-5", [s.id], timedelta(minutes=30), closed_reason="lapsed", kind="steer"),  # closed, still unread
    ]
    oldest = _iso(NOW - timedelta(minutes=50))
    # the clock is the later of the oldest and the take-over
    assert _reading(agent, s) == (3, oldest, oldest)
    s.mode_at = _iso(NOW - timedelta(minutes=10))
    assert _reading(agent, s) == (3, oldest, s.mode_at), "mail older than the hold waits from the take-over"
    s.mode_at = None
    assert _reading(agent, s) == (3, oldest, oldest), "no stamp: the oldest alone"


async def test_mail_rung_before_the_hold_is_decided_and_does_not_count(agent):
    s = _held(agent)
    s.inbox = [_mail("m-1", [s.id], timedelta(hours=3)), _mail("m-2", [s.id], timedelta(minutes=40))]
    s.mail_decided = {"id": "m-1", "at": s.inbox[0].at}
    assert _reading(agent, s) == (1, s.inbox[1].at, s.inbox[1].at)
    s.mail_decided = {"id": "m-2", "at": s.inbox[1].at}
    assert _reading(agent, s) == (None, None, None), "nothing undecided: no reading"


@pytest.mark.parametrize(
    "kw",
    [
        {"team": None},  # not a member
        {"by_person": True},  # the person's own session in a team
        {"unattended": True, "kind": "agent"},  # not held: its mail wakes it
        {"state": "closed"},
        {"state": "exited"},
        {"adapter": "shell"},  # a record with no agent
    ],
)
async def test_no_reading_on_any_other_record(agent, kw):
    s = _held(agent, **kw)
    s.inbox = [_mail("m-1", [s.id], timedelta(hours=1))]
    assert _reading(agent, s) == (None, None, None), kw


async def test_a_controller_alone_makes_a_member(agent):
    s = _held(agent, team=None, controllers=["ao-x-m"])
    s.inbox = [_mail("m-1", [s.id], timedelta(hours=1))]
    assert _reading(agent, s)[0] == 1


async def test_a_node_holds_no_inbox_and_reads_none(agent, monkeypatch):
    s = _held(agent)
    s.inbox = [_mail("m-1", [s.id], timedelta(hours=1))]
    monkeypatch.setattr(agent, "mode", "node")
    assert _reading(agent, s) == (None, None, None)


async def test_a_node_members_reading_is_the_homes_copy(agent):
    s = _held(agent, host="laptop")
    s.inbox = [_mail("m-1", ["ao-x-tl@laptop"], timedelta(hours=1)), _mail("m-2", ["ao-x-tl"], timedelta(hours=1))]
    agent.remote.setdefault("laptop", {})[s.id] = s
    del agent.sessions[s.id]
    # a bare address in the home's store names the home's session, not the node's
    assert _reading(agent, s)[0] == 1


async def test_a_held_records_wake_decision_leaves_its_watermark(agent):
    """The row rests on it: nothing is decided while the record is held, so `mail_decided` stands still."""
    s = _held(agent)
    s.inbox = [_mail("m-1", [s.id], timedelta(hours=1))]
    assert agent._decide_wake(s, member_change=False) is None
    assert s.mail_decided is None and s.wakes == []


# -- the row ----------------------------------------------------------------------------------------


def _v(**kw) -> dict:
    base = {
        "id": "ao-x-tl", "name": "techlead-ao-1", "state": "idle", "unattended": False, "team": "t",
        "agent": True, "by_person": False, "mode_at": _iso(NOW - timedelta(hours=2)), "mode_by": "person",
        "mode_via": "focus", "unread_unrung": 5, "oldest_unread_at": _iso(NOW - timedelta(minutes=50)),
        "held_mail_at": _iso(NOW - timedelta(minutes=50)),
    }  # fmt: skip
    return {**base, **kw}


def test_the_row_draws_at_thirty_minutes_and_not_before():
    from shiftlead.ui.cards import _clock
    from shiftlead.ui.inbox import held_mail_mark

    at, words = held_mail_mark(_v(), {}, NOW)
    assert at == _v()["held_mail_at"]
    two, fifty = _clock(_v()["mode_at"]), _clock(_v()["oldest_unread_at"])
    assert words == (
        f"techlead-ao-1 · held by you since {two} from Focus · 5 unread since {fifty} — "
        "its mail does not wake it while you hold it"
    )
    assert held_mail_mark(_v(held_mail_at=_iso(NOW - timedelta(minutes=29))), {}, NOW) is None
    assert held_mail_mark(_v(held_mail_at=_iso(NOW - timedelta(minutes=30))), {}, NOW) is not None


def test_the_rows_stamp_words():
    from shiftlead.ui.cards import _clock
    from shiftlead.ui.inbox import held_mail_mark

    two = _clock(_v()["mode_at"])
    assert "· held since before this was recorded ·" in held_mail_mark(_v(mode_at=None), {}, NOW)[1]
    assert f"· held since {two} from its start ·" in held_mail_mark(_v(mode_by=None, mode_via="start"), {}, NOW)[1]
    got = held_mail_mark(_v(mode_by="ao-x-m", mode_via="cli"), {"ao-x-m": "manager-ao"}, NOW)[1]
    assert f"· held by manager-ao since {two} by `ao mode` ·" in got


@pytest.mark.parametrize(
    "kw",
    [
        {"state": "working"},
        {"state": "stalled"},
        {"unattended": True},
        {"team": None},
        {"by_person": True},
        {"unread_unrung": None},
        {"unread_unrung": 0},
        {"agent": False},
    ],
)
def test_no_row_otherwise(kw):
    from shiftlead.ui.inbox import held_mail_mark

    assert held_mail_mark(_v(**kw), {}, NOW) is None, kw


def test_the_row_is_a_counted_state_row_with_hand_back_open_and_snooze():
    from shiftlead.ui.inbox import inbox_sections, state_rows

    rows = state_rows([_v()])
    row = next(r for r in rows if r["row"] == "held_mail")
    assert row["id"] == "ao-x-tl:held_mail" and row["subject"].startswith("held · mail waiting")
    out = inbox_sections([], now=NOW, states=rows)
    assert [r["id"] for r in out["needs"]] == [row["id"]], "under Needs you, counted"
    out = inbox_sections(
        [], now=NOW, states=rows, attention_snoozed={"ao-x-tl|held_mail": _iso(NOW + timedelta(hours=1))}
    )
    assert [r["row"] for r in out["snoozed"]] == ["held_mail"] and not out["needs"]


def test_the_row_template_draws_hand_back_open_and_snooze(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    from shiftlead.ui.app import templates
    from shiftlead.ui.inbox import state_rows

    row = next(r for r in state_rows([_v()]) if r["row"] == "held_mail")
    html = templates.get_template("inbox_row.html").module.state(row, "needs")
    assert 'data-act="mode" data-via="inbox" data-id="ao-x-tl" data-unattended="0"' in str(html)
    assert "Hand back</button>" in str(html) and "data-confirm" not in str(html).split("Hand back</button>")[0][-400:]
    assert 'href="/focus/ao-x-tl"' in str(html) and 'data-row="held_mail"' in str(html)


def test_the_rows_kind_is_not_merged_without_its_reads():
    """Snooze's kind is `held_mail`, never `held`, which is *merged without its read*'s."""
    from shiftlead.ui.inbox import STATE_SUBJECTS

    assert STATE_SUBJECTS["held_mail"] == "held · mail waiting" and "held" not in STATE_SUBJECTS


async def test_snooze_takes_the_kind_held_mail(agent):
    from sessionorc.agent_common import RpcError

    s = _held(agent)
    await agent.rpc_attention_snooze(id=s.id, kind="held_mail", until=_iso(NOW + timedelta(hours=1)))
    with pytest.raises(RpcError, match="held_mail"):
        await agent.rpc_attention_snooze(id="x", kind="nope", until="1h")
