"""The seat ledger (design §4.4 *Spend per seat*, §4.3 *Spend per turn*, §5 `spend.weights`; TD-818,
built by TD-830): every profile's turns weighed and charged to a record and a reference, kept in
`seat_spend.json`, and read by `seats` per seat, per role and per finished entry — while the account
ledger, the gate and the chip read nothing of it."""

import re
from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks

from sessionorc import seats, settings
from sessionorc import spend as spend_mod
from sessionorc.client import AgentError, LocalClient
from sessionorc.models import ProgressEntry, Session

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)  # a Saturday
W = seats.WEIGHTS


def _at(minutes_ago: float = 0) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")


def _t(uid, offset, source="t1", conv="c1", cwd="", model="claude-sonnet-4-6", inp=1_000_000, at=None, **kw):
    return {
        "at": at or _at(), "id": uid, "source": source, "offset": offset, "response": f"r-{uid}",
        "model": model, "input": inp, "output": 0, "cache_read": 0, "cache_write": 0, "cost": None,
        "conversation": conv, "cwd": cwd, "subagent": False,
    } | kw  # fmt: skip


def _rec(sid, name="w", dir="/nowhere", conv=None, team="t", role="grinder", repo="r", state="idle", **kw):
    s = Session(id=sid, name=name, kind="interactive", adapter="hookstub", dir=dir, repo=repo, adapter_id=conv, **kw)
    s.team, s.role, s.state = team, role, state
    return s


def _take(ledger, turns, records, prices=None, backfill=False, cursors=None):
    ends = cursors if cursors is not None else {t["source"]: t["offset"] + 1 for t in turns}
    return seats.take(ledger, "h", {"turns": turns, "cursors": ends}, records, prices, W, NOW, backfill)


def _row(ledger, rid, day="2026-10-17"):
    return ledger["days"][day][rid]


def _fig(row):
    return round(sum(m["figure"] for m in row["models"].values()), 6)


def test_the_weights_match_the_longest_prefix_and_an_unmatched_model_is_unweighed():
    assert seats.weight_for("claude-opus-4-8", W) is W["claude-opus-4"]
    assert seats.weight_for("claude-opus-5-5", W) is W["claude-opus-5-5"]
    assert seats.weight_for("claude-opus-5-1", W) is W["claude-opus-5"]
    assert seats.weight_for("claude-fable-5-1", W) is W["claude-fable"]
    assert seats.weight_for("gpt-9", W) is None and seats.weight_for("", W) is None
    tokens = {"input": 1_000_000, "output": 0, "cache_read": 2_000_000, "cache_write": 0}
    assert seats.figure_of({"model": "claude-opus-4-8"}, tokens, None, W) == (pytest.approx(6.0), False)
    assert seats.figure_of({"model": "m", "cost": 2.5}, tokens, None, W) == (2.5, True)  # the tool's own price
    assert seats.figure_of({"model": "m"}, tokens, {"input": 3.0}, W) == (pytest.approx(9.0), True)  # a bill
    assert seats.figure_of({"model": "m"}, tokens, {}, W) == (None, False)  # metered with no prices, no weight
    ledger: dict = {}
    _take(ledger, [_t("u1", 0, model="gpt-9"), _t("u2", 1, model="<synthetic>")], [_rec("a", conv="c1")])
    m = _row(ledger, "a")["models"]
    assert list(m) == ["gpt-9"] and (m["gpt-9"]["turns"], m["gpt-9"]["unweighed"], m["gpt-9"]["figure"]) == (1, 1, 0)
    assert m["gpt-9"]["input"] == 1_000_000  # kept in tokens


def test_a_turn_is_charged_by_conversation_then_cwd_then_outside(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "src" / "deep").mkdir(parents=True)
    by_conv = _rec("a", name="a", dir=str(tmp_path / "elsewhere"), conv="c1")
    by_dir = _rec("b", name="b", dir=str(repo))
    deeper = _rec("c", name="c", dir=str(repo / "src"))
    ledger: dict = {}
    turns = [
        _t("u1", 0, source="t1", conv="c1", cwd=str(repo)),  # its conversation names a, wherever it ran
        _t("u2", 0, source="t2", conv="c2", cwd=str(repo / "src" / "deep")),  # the deepest dir above the cwd
        _t("u3", 0, source="t3", conv="c3", cwd=str(repo)),  # the repo's own dir
        _t("u4", 0, source="t4", conv="c4", cwd=str(tmp_path)),  # above every dir: outside shiftlead
    ]
    _take(ledger, turns, [by_conv, by_dir, deeper])
    day = ledger["days"]["2026-10-17"]
    assert {rid: row["models"]["claude-sonnet-4-6"]["turns"] for rid, row in day.items()} == {
        "a": 1, "b": 1, "c": 1, seats.OUTSIDE: 1,
    }  # fmt: skip
    assert day[seats.OUTSIDE]["name"] == seats.OUTSIDE
    cursors = ledger["hosts"]["h"]["cursors"]
    assert (cursors["t1"]["owner"], cursors["t2"]["owner"], cursors["t4"]["owner"]) == ("a", "c", seats.OUTSIDE)
    assert cursors["t2"]["root"] == str(repo)
    # the owner is kept on the cursor: a later turn of t2 is c's though c's dir moved away
    deeper.dir = "/gone"
    _take(ledger, [_t("u5", 1, source="t2", conv="c2", cwd=str(repo))], [by_conv, by_dir, deeper])
    assert _row(ledger, "c")["models"]["claude-sonnet-4-6"]["turns"] == 2


def test_a_forgotten_seats_worktree_present_or_removed_is_not_charged_to_the_anchor(tmp_path):
    checkout = tmp_path / "shiftlead"
    (checkout / ".git").mkdir(parents=True)
    wt = checkout / ".claude" / "worktrees" / "grinder-x"
    wt.mkdir(parents=True)
    (wt / ".git").write_text("gitdir: ../../.git/worktrees/grinder-x\n")
    anchor = _rec("anchor", name="ao", dir=str(checkout))
    ledger: dict = {}
    # the worktree's seat was forgotten: no record names its conversation or its dir
    _take(ledger, [_t("u1", 0, source="t1", conv="gone1", cwd=str(wt))], [anchor])
    # a removed worktree: its cwd is no directory, so no record by cwd
    _take(ledger, [_t("u2", 0, source="t2", conv="gone2", cwd=str(checkout / ".claude" / "worktrees" / "y"))], [anchor])
    day = ledger["days"]["2026-10-17"]
    assert set(day) == {seats.OUTSIDE} and _row(ledger, seats.OUTSIDE)["models"]["claude-sonnet-4-6"]["turns"] == 2
    assert ledger["hosts"]["h"]["cursors"]["t2"]["root"] == seats.ROOT_GONE
    # the anchor's own turn, in a subdirectory of the checkout, is the anchor's
    (checkout / "docs").mkdir()
    _take(ledger, [_t("u3", 0, source="t3", conv="new", cwd=str(checkout / "docs"))], [anchor])
    assert _row(ledger, "anchor")["models"]["claude-sonnet-4-6"]["turns"] == 1


def test_an_adopted_session_and_a_subagent_are_their_records_the_subagent_marked():
    adopted = _rec("adopt", name="paul-claude", conv="c9", team="", role="")  # the tick adopted it: a record
    ledger: dict = {}
    _take(ledger, [_t("u1", 0, conv="c9"), _t("u2", 0, source="sub", conv="c9", subagent=True)], [adopted])
    m = _row(ledger, "adopt")["models"]["claude-sonnet-4-6"]
    assert (m["turns"], m["subagent"]) == (2, 1)


def test_a_turn_goes_to_the_reference_doing_names_else_the_newest_claim_else_between():
    r = _rec("a", conv="c1")
    assert seats.current_ref(r) == seats.BETWEEN
    r.progress = [
        ProgressEntry(ref="TD-81", at="2026-10-17T10:00:00Z"),
        ProgressEntry(ref="TD-818", at="2026-10-17T09:00:00Z"),
        ProgressEntry(ref="TD-7", status="done", at="2026-10-17T11:00:00Z"),
    ]
    assert seats.current_ref(r) == "TD-81"  # no doing: the newest claim
    r.doing = {"text": "writing the design of td-818 while TD-81 waits", "at": _at()}
    assert seats.current_ref(r) == "TD-818"  # both named as whole tokens: the longest
    r.doing = {"text": "TD-8180 is another entry", "at": _at()}
    assert seats.current_ref(r) == "TD-81"  # not a whole token
    r.doing = {"text": "TD-7 again", "at": _at()}
    assert seats.current_ref(r) == "TD-81"  # a reference no longer claimed is not charged
    r.doing, r.state = {"text": "on TD-818", "at": _at()}, "exited"
    assert seats.current_ref(r) == "TD-81"  # an exited record's doing is not read
    ledger: dict = {}
    r.state = "idle"
    _take(ledger, [_t("u1", 0)], [r])
    assert _row(ledger, "a")["refs"] == {"TD-818": {"figure": pytest.approx(3.0), "turns": 1}}


def test_a_rewritten_transcript_is_not_counted_twice_and_a_quiet_read_moves_nothing():
    r = _rec("a", conv="c1")
    ledger: dict = {}
    first = [_t("u1", 0, at=_at(3)), _t("u2", 100, at=_at(2))]
    assert _take(ledger, first, [r], cursors={"t1": 200})
    assert not _take(ledger, [], [r], cursors={"t1": 200})  # nothing new: nothing moved
    # a compaction rewrote the file shorter: read from 0, the two already ledgered come back
    again = [_t("u1", 0, at=_at(3)), _t("u2", 50, at=_at(2)), _t("u3", 80, at=_at(1))]
    assert _take(ledger, again, [r], cursors={"t1": 120})
    assert _row(ledger, "a")["models"]["claude-sonnet-4-6"]["turns"] == 3


def test_the_backfill_charges_the_fortnight_to_between_and_drops_older_turns():
    r = _rec("a", conv="c1")
    r.progress = [ProgressEntry(ref="TD-1", at="2026-10-17T10:00:00Z")]
    ledger: dict = {}
    turns = [_t("u0", 0, at=_at(60 * 24 * 20)), _t("u1", 1, at=_at(60 * 24 * 3)), _t("u2", 2, at=_at(1))]
    _take(ledger, turns, [r], backfill=True)
    assert "2026-09-27" not in ledger["days"]  # twenty days ago: dropped
    assert _row(ledger, "a", "2026-10-14")["refs"] == {seats.BETWEEN: {"figure": pytest.approx(3.0), "turns": 1}}
    assert _row(ledger, "a")["refs"] == {seats.BETWEEN: {"figure": pytest.approx(3.0), "turns": 1}}


def test_a_forgotten_owner_kept_on_a_cursor_reads_outside():
    r = _rec("a", conv="c1")
    ledger: dict = {}
    _take(ledger, [_t("u1", 0)], [r])
    _take(ledger, [_t("u2", 1)], [])  # its record was forgotten since
    assert _row(ledger, seats.OUTSIDE)["models"]["claude-sonnet-4-6"]["turns"] == 1
    assert _row(ledger, "a")["models"]["claude-sonnet-4-6"]["turns"] == 1  # a written row never moves


def test_a_row_keeps_its_figure_past_200k_and_300k_context():
    ledger: dict = {}
    turns = [
        _t("u1", 0, inp=0, cache_read=250_000, model="claude-opus-4-8"),
        _t("u2", 1, inp=10_000, cache_read=300_000, model="claude-opus-4-8"),
        _t("u3", 2, inp=1_000, model="claude-opus-4-8"),
    ]
    _take(ledger, turns, [_rec("a", conv="c1")])
    m = _row(ledger, "a")["models"]["claude-opus-4-8"]
    assert m["past_200k"] == pytest.approx(0.125 + 0.2) and m["past_300k"] == pytest.approx(0.2)


def test_the_reading_merges_a_seats_runs_shares_its_team_and_sums_a_finished_entry():
    w1 = _rec("w1", name="grinder-1", conv="c1")
    w1.progress = [ProgressEntry(ref="TD-5", at="2026-10-17T09:00:00Z")]
    w2 = _rec("w2", name="grinder-1", conv="c2")  # the same seat restarted
    w2.progress = [ProgressEntry(ref="TD-5", at="2026-10-17T10:00:00Z")]
    lead = _rec("tl", name="techlead", conv="c3", role="techlead")
    lead.progress = [ProgressEntry(ref="TD-5", at="2026-10-17T10:00:00Z")]
    other = _rec("x", name="grinder-1", conv="c4", team="other")
    other.progress = [ProgressEntry(ref="TD-5", at="2026-10-17T10:00:00Z")]
    ledger: dict = {"began": "2026-10-10T00:00:00Z"}
    seats.see_claims(ledger, [w1, w2, lead, other], "2026-10-17T09:00:00Z")
    _take(ledger, [_t("u1", 0, source="a", conv="c1"), _t("u2", 0, source="b", conv="c2")], [w1, w2, lead, other])
    _take(ledger, [_t("u3", 0, source="c", conv="c3"), _t("u4", 0, source="d", conv="c4")], [w1, w2, lead, other])
    seats.done(ledger, "r", "TD-5", None, "2026-10-17T11:00:00Z")
    got = seats.reading(ledger, "day", NOW, team="t", weights=W)
    assert [(s["seat"], s["records"], s["figure"], s["share"]) for s in got["seats"]] == [
        ("grinder-1", ["w1", "w2"], 6.0, pytest.approx(0.6667, abs=1e-4)),
        ("techlead", ["tl"], 3.0, pytest.approx(0.3333, abs=1e-4)),
    ]
    assert got["unit"] == "≈$" and got["as_of"] == "2026-10-17" and got["outside"]["figure"] == 0
    (entry,) = got["entries"]
    assert (entry["ref"], entry["figure"], entry["turns"], entry["partial"]) == ("TD-5", 12.0, 4, False)
    assert entry["by_role"] == {"grinder": 9.0, "techlead": 3.0}  # every record's rows, another team's included
    assert got["finished"] == {"grinder": {"entries": 1, "sum": 12.0, "median": 12.0}}
    assert set(got["roles"]) == {"grinder", "techlead"}
    by_record = seats.reading(ledger, "day", NOW, by="record", weights=W)
    assert sorted(s["records"][0] for s in by_record["seats"]) == ["tl", "w1", "w2", "x"]
    week = seats.reading(ledger, "week", NOW, weights=W)
    assert (week["at"], week["until"], week["begins"]) == ("2026-10-12", "2026-10-17", "2026-10-17")
    with pytest.raises(ValueError, match="day, week or month"):
        seats.reading(ledger, "year", NOW)


def test_each_seat_reads_its_own_finished_entries_and_its_tokens_by_kind():
    def row(name, refs, inp, out):
        r = _day(sum(refs.values()) + 1.0, name=name, input=inp, output=out, cache_read=7, cache_write=3)
        return r | {"refs": {k: {"figure": v, "turns": 1} for k, v in refs.items()}}

    ledger = _ledger(
        d2026_10_17={
            "a1": row("grinder-1", {"TD-1": 4.0, "TD-2": 6.0}, 100, 10),
            "a2": row("grinder-1", {"TD-3": 2.0}, 50, 5),  # the same seat restarted
            "b1": row("grinder-2", {"TD-2": 1.0, "TD-4": 9.0}, 200, 20),  # TD-4 is not finished
        }
    )
    ledger["refs"] = {
        f"r TD-{n}": {"first_claimed": "2026-10-17T01:00:00Z", "done_at": "2026-10-17T09:00:00Z"} for n in (1, 2, 3)
    }
    got = seats.reading(ledger, "day", NOW, team="t", weights=W)
    one, two = sorted(got["seats"], key=lambda s: s["seat"])
    assert one["finished"] == {"entries": 3, "sum": 12.0, "median": 4.0, "refs": ["TD-2", "TD-1", "TD-3"]}
    assert two["finished"] == {"entries": 1, "sum": 1.0, "median": 1.0, "refs": ["TD-2"]}
    assert one["tokens"] == {"input": 150, "output": 15, "cache_read": 14, "cache_write": 6}
    assert two["tokens"] == {"input": 200, "output": 20, "cache_read": 7, "cache_write": 3}
    by_record = {s["records"][0]: s for s in seats.reading(ledger, "day", NOW, by="record", weights=W)["seats"]}
    assert by_record["a1"]["finished"]["refs"] == ["TD-2", "TD-1"] and by_record["a2"]["finished"]["entries"] == 1
    assert by_record["a2"]["tokens"]["input"] == 50
    top = {s["seat"]: s for s in seats.reading(ledger, "day", NOW, by="record", weights=W)["top"]}
    assert top["grinder-1"]["finished"]["entries"] == 3 and top["grinder-1"]["tokens"]["input"] == 150
    quiet = _ledger(d2026_10_17={"a1": _day(1.0)})
    assert seats.reading(quiet, "day", NOW, weights=W)["seats"][0]["finished"] == {
        "entries": 0, "sum": 0.0, "median": 0.0, "refs": []
    }  # fmt: skip


def test_an_entry_claimed_before_the_ledger_began_reads_partial():
    ledger: dict = {"began": "2026-10-17T08:00:00Z"}
    seats.done(ledger, "r", "TD-9", "2026-10-15T08:00:00Z", "2026-10-17T11:00:00Z")
    (entry,) = seats.reading(ledger, "day", NOW, weights=W)["entries"]
    assert entry["partial"] and entry["first_claimed"] == "2026-10-15T08:00:00Z"
    seats.done(ledger, "r", "TD-9", "2026-10-16T08:00:00Z", "2026-10-17T11:30:00Z")
    assert ledger["refs"]["r TD-9"]["first_claimed"] == "2026-10-15T08:00:00Z"  # the first sight stands


def test_a_prune_drops_old_rows_cursors_and_finished_references_and_keeps_an_open_one():
    today = NOW.date()
    old = (today - spend_mod.KEEP - timedelta(days=1)).isoformat()
    recent = (today - timedelta(days=3)).isoformat()
    ledger = {
        "days": {old: {}, recent: {}},
        "hosts": {"kmaster": {"cursors": {"/t/a.jsonl": {"seen": f"{old}T09:00:00Z"}, "/t/b.jsonl": {"seen": recent}}}},
        "refs": {
            "r TD-1": {"first_claimed": f"{old}T09:00:00Z", "done_at": f"{old}T10:00:00Z"},
            "r TD-2": {"first_claimed": f"{old}T09:00:00Z", "done_at": f"{recent}T10:00:00Z"},
            "r TD-3": {"first_claimed": f"{old}T09:00:00Z"},  # still open: its claim is no reason to forget it
        },
    }
    seats.prune(ledger, today)
    assert list(ledger["days"]) == [recent] and list(ledger["hosts"]["kmaster"]["cursors"]) == ["/t/b.jsonl"]
    assert list(ledger["refs"]) == ["r TD-2", "r TD-3"]


def test_the_weights_setting_replaces_a_key_whole_and_refuses_a_bad_price():
    assert settings.weights({}) == seats.WEIGHTS
    doc = {"spend": {"weights": {"as_of": "2026-11-01", "claude-opus": {"input": 3}, "bad": {"input": -1}}}}
    got = settings.weights(doc)
    assert got["claude-opus"] == {"input": 3.0} and got["as_of"] == "2026-11-01" and "bad" not in got
    assert got["claude-sonnet"] == seats.WEIGHTS["claude-sonnet"]
    tokens = {"input": 0, "output": 1_000_000, "cache_read": 0, "cache_write": 0}
    assert seats.figure_of({"model": "claude-opus-4-8"}, tokens, None, got) == (25.0, False)  # its own key
    assert seats.figure_of({"model": "claude-opus-x"}, tokens, None, got) == (3.0, False)  # output at input
    for bad, words in (
        ({"weights": {"m": {"input": "x"}}}, "per million"),
        ({"weights": {"m": {"tokens": 1}}}, "not a token kind"),
        ({"weights": ["m"]}, "a mapping"),
        ({"weight": {}}, "unknown key"),
    ):
        with pytest.raises(ValueError, match=words):
            settings.parse_spend(bad)


async def test_a_subscription_profiles_turns_reach_the_seat_ledger_and_nothing_the_gate_reads(
    agent, hookstub, tmp_path, monkeypatch
):
    """The pass end to end on the home: the first pass backfills, a subscription profile is read
    (never the account ledger's, never a `pct`), a quiet pass writes nothing, `seats` reads the
    seat, a claim made and done inside one pass has a `first_claimed`, and `set_settings` takes the
    weights."""
    await park_ticks(agent)
    hookstub.billing, hookstub.accounts = {}, {}
    hookstub.spend_turns = [_t("old", 0, source="t1", conv="cv", at=_at(60 * 24 * 30))]
    async with LocalClient() as person:
        w = await person.call("create", name="w", dir=str(tmp_path), adapter="hookstub", profile="sub")
        agent.sessions[w["id"]].adapter_id = "cv"
        await person.call("progress", id=w["id"], status="claimed", ref="TD-202")
        await agent._refresh_seats_inner()  # the backfill: a month-old turn is dropped
        assert agent._seats.get("days", {}) == {} and agent._seats["hosts"][agent.host]["cursors"]["t1"]["offset"] == 1
        assert agent._seats["hosts"][agent.host]["seeded"] == ["sub"]
        # a claim already held when the ledger began reads partial once done, its earlier spend unseen
        assert (
            agent._seats["refs"][f"{agent.sessions[w['id']].repo or ''} TD-202"]["first_claimed"]
            <= agent._seats["began"]
        )
        await person.call("progress", id=w["id"], status="done", ref="TD-202")
        # a profile first live later is backfilled too: its month-old turn is dropped, not charged
        (tmp_path / "v").mkdir()
        v = await person.call("create", name="v", dir=str(tmp_path / "v"), adapter="hookstub", profile="sub2")
        hookstub.spend_turns.append(_t("old2", 0, source="t9", conv="cv2", at=_at(60 * 24 * 30)))
        agent.sessions[v["id"]].adapter_id = "cv2"
        await agent._refresh_seats_inner()
        assert agent._seats.get("days", {}) == {} and agent._seats["hosts"][agent.host]["seeded"] == ["sub", "sub2"]
        await person.call("kill", id=v["id"])
        await person.call("remove", id=v["id"])
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        hookstub.spend_turns.append(_t("u1", 1, source="t1", conv="cv", at=now))
        await person.call("progress", id=w["id"], status="claimed", ref="TD-303")
        await agent._refresh_seats_inner()
        rid = w["id"]
        day = next(iter(agent._seats["days"].values()))
        assert day[rid]["refs"] == {"TD-303": {"figure": pytest.approx(3.0), "turns": 1}}
        on_disk = seats.SeatStore().load()
        assert next(iter(on_disk["days"].values()))[rid]["name"] == "w"
        assert spend_mod.SpendStore().load() == {} and "sub" not in agent._usage  # nothing the gate or chip reads
        saved: list = []
        monkeypatch.setattr(agent.seat_store, "save", lambda ledger: saved.append(ledger))
        await agent._refresh_seats_inner()
        assert saved == []  # a quiet pass writes nothing
        # a claim made and done inside one pass: first_claimed from the claim's own at
        await person.call("progress", id=w["id"], status="claimed", ref="TD-404")
        await person.call("progress", id=w["id"], status="done", ref="TD-404")
        meta = agent._seats["refs"][f"{agent.sessions[rid].repo or ''} TD-404"]
        assert meta["first_claimed"] <= meta["done_at"]
        got = await person.call("seats", window="week")
        assert [(s["seat"], s["figure"]) for s in got["seats"]] == [("w", 3.0)]
        assert [(e["ref"], e["partial"]) for e in got["entries"]] == [("TD-202", True), ("TD-404", False)]
        assert got["unknown"] == {}
        # a ledger file that cannot be written never fails a report
        monkeypatch.setattr(agent.seat_store, "save", lambda ledger: (_ for _ in ()).throw(OSError("full")))
        await person.call("progress", id=w["id"], status="claimed", ref="TD-505")
        assert await person.call("progress", id=w["id"], status="done", ref="TD-505")
        with pytest.raises(AgentError, match="day, week or month"):
            await person.call("seats", window="year")
        assert (await person.call("seats", window="month", at=None))["window"] == "month"  # the RPC takes `at`
        with pytest.raises(AgentError, match="starts on the 1st"):
            await person.call("seats", window="month", at="2026-10-02")
        out = await person.call("set_settings", spend={"weights": {"claude-sonnet": {"input": 1}}})
        assert out["spend"]["weights"]["claude-sonnet"] == {"input": 1.0}
        with pytest.raises(AgentError, match="not a token kind"):
            await person.call("set_settings", spend={"weights": {"claude-sonnet": {"tok": 1}}})
        assert (await person.call("settings"))["spend"]["weights"]["claude-sonnet"] == {"input": 1.0}
        await person.call("set_settings", spend={})
        assert "spend" not in settings.load()
        await person.call("kill", id=w["id"])
        await person.call("remove", id=w["id"])


async def test_a_profiles_last_session_ended_is_read_once_more_and_then_dropped(agent, hookstub, tmp_path, monkeypatch):
    """TD-965 (§4.4 *Spend per seat*, *What is read*): a session that ends with turns past the cursor,
    the last live one on its profile, has them charged to its record by the next pass; the pass after
    reads that profile no more."""
    await park_ticks(agent)
    hookstub.billing, hookstub.accounts, hookstub.spend_turns = {}, {}, []
    asked: list = []
    spend = type(hookstub).spend
    monkeypatch.setattr(
        type(hookstub), "spend", lambda self, prof, cursors=None: asked.append(prof) or spend(self, prof, cursors)
    )
    async with LocalClient() as person:
        w = await person.call("create", name="w", dir=str(tmp_path), adapter="hookstub", profile="sub")
        rid = w["id"]
        agent.sessions[rid].adapter_id = "cv"
        await agent._refresh_seats_inner()  # the backfill: nothing yet
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        hookstub.spend_turns = [_t("u1", 0, source="t1", conv="cv", at=now)]
        await person.call("kill", id=rid)
        assert agent.sessions[rid].state in ("exited", "closed") and not agent._usage_live()
        asked.clear()
        await agent._refresh_seats_inner()  # its last minute, though nothing else runs on "sub"
        assert asked == ["sub"]
        day = next(iter(agent._seats["days"].values()))
        assert day[rid]["models"]["claude-sonnet-4-6"]["turns"] == 1
        asked.clear()
        await agent._refresh_seats_inner()
        assert asked == []  # read once more, then dropped
        await person.call("remove", id=rid)


async def test_the_home_charges_a_nodes_seat_turns_once_and_its_seeding_charges_nothing(agent):
    """`seat_spend` at the home (TD-833): a read answers the cursors and whether the profile is
    seeded; the seeding takes a new transcript's end and charges nothing; a turn is owned among the
    node's records by the roots the node read, and a resent batch — a lost reply — is not charged
    twice. The home's own records never own a node's turn."""
    from test_link import record

    await park_ticks(agent)
    agent._take_records(
        "laptop", [record(rid="ao-x-n", name="n", dir="/srv/w/n", team="t", role="grinder")], whole=True
    )
    agent.sessions["ao-x-mine"] = _rec("ao-x-mine", dir="/srv/w/n/src")  # deeper, and the home's: never the node's
    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    got = await agent._take_seat_spend("laptop", {"profile": "sub", "prices": None, "turns": [], "cursors": {}})
    assert got == {"cursors": {}, "seeded": False}
    old = _t("u0", 0, conv="", cwd="/srv/w/n/src", at=now)
    got = await agent._take_seat_spend(
        "laptop", {"profile": "sub", "prices": None, "turns": [old], "cursors": {"t1": 1}}
    )
    assert got == {"cursors": {"t1": 1}, "seeded": True} and agent._seats.get("days", {}) == {}
    new = _t("u1", 1, conv="", cwd="/srv/w/n/src", at=now)
    call = {"profile": "sub", "prices": None, "turns": [new], "cursors": {"t1": 2}, "roots": {"/srv/w/n/src": "/srv/w"}}
    assert (await agent._take_seat_spend("laptop", call))["cursors"] == {"t1": 2}
    await agent._take_seat_spend("laptop", call)  # the reply was lost: the node sends it again
    rows = next(iter(agent._seats["days"].values()))
    assert set(rows) == {"ao-x-n"} and rows["ao-x-n"]["models"]["claude-sonnet-4-6"]["turns"] == 1
    assert rows["ao-x-n"]["role"] == "grinder" and rows["ao-x-n"]["metered"] is False
    # a transcript whose `cwd` the node sent no root for matches no record by `cwd`: outside shiftlead
    other = _t("u2", 0, source="t2", conv="", cwd="/srv/w/n/src", at=now)
    await agent._take_seat_spend("laptop", {"profile": "sub", "prices": None, "turns": [other], "cursors": {"t2": 1}})
    assert set(next(iter(agent._seats["days"].values()))) == {"ao-x-n", seats.OUTSIDE}
    with pytest.raises(Exception, match="names a profile"):
        await agent._take_seat_spend("laptop", {"turns": [], "cursors": {}})


# -- over time and across teams (§4.4 *Over time and across teams*, TD-859) ---------------------------


def _day(figure, turns=1, metered=False, name="w", team="t", role="grinder", repo="r", model="m", **m):
    return {
        "name": name, "team": team, "role": role, "repo": repo, "metered": metered, "refs": {},
        "models": {model: {"input": 1000, "output": 0, "cache_read": 0, "cache_write": 0, "turns": turns,
                           "figure": figure, "past_200k": 0.0, "past_300k": 0.0} | m},
    }  # fmt: skip


def _ledger(**days):
    """`{day: {rid: row}}`, a day written `d2026_10_17`."""
    return {"days": {k[1:].replace("_", "-"): v for k, v in days.items()}}


def test_a_month_and_a_week_sum_their_days_and_a_week_starts_on_monday():
    ledger = _ledger(
        d2026_09_30={"a": _day(1.0)},
        d2026_10_11={"a": _day(2.0)},  # a Sunday: last week's
        d2026_10_12={"a": _day(4.0)},  # this week's Monday
        d2026_10_17={"a": _day(8.0)},
    )
    figure = {w: seats.reading(ledger, w, NOW, weights=W)["whole"]["figure"] for w in seats.WINDOWS}
    assert figure == {"day": 8.0, "week": 12.0, "month": 14.0}
    assert seats.reading(ledger, "month", NOW, weights=W)["at"] == "2026-10-01"


def test_at_picks_a_past_period_and_a_bad_future_or_pre_begins_at_is_refused():
    ledger = _ledger(d2026_09_30={"a": _day(1.0)}, d2026_10_05={"a": _day(2.0)}, d2026_10_17={"a": _day(8.0)})
    past = seats.reading(ledger, "week", NOW, at="2026-10-05", weights=W)
    assert (past["at"], past["until"], past["current"], past["whole"]["figure"]) == (
        "2026-10-05",
        "2026-10-11",
        False,
        2.0,
    )
    assert "resets" not in past and "resets" in seats.reading(ledger, "week", NOW, weights=W)
    assert seats.reading(ledger, "month", NOW, at="2026-09-01", weights=W)["whole"]["figure"] == 1.0
    assert seats.reading(ledger, "week", NOW, at="2026-09-28", weights=W)["whole"]["figure"] == 1.0  # holds begins
    assert seats.reading(ledger, "day", NOW, at="2026-10-17", weights=W)["current"]  # the current reads as no at
    for window, at, words in (
        ("week", "2026-10-06", "starts on a Monday"),
        ("month", "2026-10-02", "starts on the 1st"),
        ("day", "17/10/2026", "YYYY-MM-DD"),
        ("day", "20261017", "YYYY-MM-DD"),
        ("week", "2026-10-19", "after the current week"),
        ("week", "2026-09-21", "before the seat ledger begins (2026-09-30)"),
        ("day", "2026-09-29", "before the seat ledger begins"),
    ):
        with pytest.raises(ValueError, match=re.escape(words)):
            seats.reading(ledger, window, NOW, at=at, weights=W)
    with pytest.raises(ValueError, match="holds no turns"):
        seats.reading({}, "day", NOW, at="2026-10-16", weights=W)
    assert "begins" not in seats.reading({}, "day", NOW, weights=W)


def test_the_series_has_its_buckets_by_team_or_by_role_and_a_partial_bucket():
    ledger = _ledger(
        d2026_10_14={"a": _day(1.0), "b": _day(2.0, team="u"), "i": _day(4.0, team="", role="")},
        d2026_10_17={"a": _day(8.0), "c": _day(16.0, name="lead", role="techlead"), "outside": _day(32.0, team="")},
    )
    for window, n, last in (("day", 30, "2026-10-17"), ("week", 12, "2026-10-12"), ("month", 13, "2026-10-01")):
        got = seats.reading(ledger, window, NOW, weights=W)["series"]
        assert len(got) == n and got[-1]["at"] == last
    week = seats.reading(ledger, "week", NOW, weights=W)["series"]
    assert week[0]["at"] == "2026-07-27" and week[-1]["partial"]  # begins is a Wednesday
    assert {k: v["figure"] for k, v in week[-1]["by"].items()} == {
        "outside": 32.0, "t": 25.0, "interactive": 4.0, "u": 2.0
    }  # fmt: skip
    assert week[-1]["figure"] == 63.0 and not any(b.get("partial") for b in week[:-1])
    days = seats.reading(ledger, "day", NOW, weights=W)["series"]
    assert not any(b.get("partial") for b in days) and days[-4]["figure"] == 7.0
    by_role = seats.reading(ledger, "week", NOW, team="t", weights=W)["series"][-1]["by"]
    assert {k: v["figure"] for k, v in by_role.items()} == {"techlead": 16.0, "grinder": 9.0}
    other = seats.reading(ledger, "week", NOW, team="interactive", weights=W)["series"][-1]["by"]
    assert list(other) == ["other"]  # a record with no role

    # a ledger that begins on a bucket's first day leaves that bucket whole: a Monday its week, the 1st its month
    def partial(begins: str, window: str) -> list[str]:
        got = seats.reading({"days": {begins: {"a": _day(1.0)}}}, window, NOW, weights=W)["series"]
        return [b["at"] for b in got if b.get("partial")]

    assert partial("2026-10-12", "week") == [] and partial("2026-10-12", "month") == ["2026-10-01"]
    assert partial("2026-10-01", "month") == [] and partial("2026-10-01", "week") == ["2026-09-28"]
    old = _ledger(d2025_10_20={"a": _day(1.0)}, d2026_10_17={"a": _day(1.0)})
    from_at = seats.reading(old, "week", NOW, at="2025-10-20", weights=W)["series"]
    assert (from_at[0]["at"], from_at[-1]["at"], from_at[0]["figure"]) == ("2025-10-20", "2026-01-05", 1.0)


def test_teams_carry_the_previous_period_to_date_the_week_and_month_and_the_top_seat():
    ledger = _ledger(
        d2026_09_30={"a": _day(100.0)},
        d2026_10_05={"a": _day(1.0)},  # last Monday
        d2026_10_10={"a": _day(2.0)},  # last Saturday: the sixth day, inside to date
        d2026_10_11={"a": _day(4.0), "z": _day(64.0, team="gone")},  # last Sunday: outside it
        d2026_10_12={"a": _day(8.0), "b": _day(12.0, name="w2")},
        d2026_10_17={"a": _day(16.0), "outside": _day(48.0, team="")},
    )
    got = seats.reading(ledger, "week", NOW, weights=W)
    rows = {r["team"]: r for r in got["teams"]}
    assert [r["team"] for r in got["teams"]] == ["t", "outside"]  # `gone` spent only after last week's to date
    t = rows["t"]
    assert (t["figure"], t["previous"], t["week"], t["month"]) == (
        36.0, {"figure": 7.0, "unit": "≈$", "to_date": 3.0}, 36.0, 43.0
    )  # fmt: skip
    assert t["most"] == {"seat": "w", "share": pytest.approx(0.6667, abs=1e-4)} and t["turns"] == 3
    assert t["share"] + rows["outside"]["share"] == pytest.approx(1.0) and t["share"] == pytest.approx(0.4286, abs=1e-4)
    month = {r["team"]: r for r in seats.reading(ledger, "month", NOW, weights=W)["teams"]}
    assert set(month) == {"t", "gone", "outside"} and month["t"]["previous"] == {
        "figure": 100.0,
        "unit": "≈$",
        "to_date": 0.0,
    }  # Sept 1-17
    past = seats.reading(ledger, "week", NOW, at="2026-10-05", weights=W)["teams"]
    assert past[0]["team"] == "gone" and past[1]["previous"] == {"figure": 100.0, "unit": "≈$", "to_date": 100.0}
    today = seats.reading(ledger, "day", NOW, weights=W)["teams"][0]
    assert today["previous"] == {"figure": 0.0, "unit": "≈$"}  # the current day: the whole alone
    (one,) = seats.reading(ledger, "week", NOW, team="gone", weights=W)["teams"]
    assert one["team"] == "gone" and one["figure"] == 0.0 and "top" not in seats.reading(ledger, "week", NOW, team="t")


def test_the_shares_on_all_sum_to_the_whole_and_top_ranks_every_seat_across_teams():
    ledger = _ledger(
        d2026_10_17={
            "a": _day(10.0, name="g1"), "b": _day(30.0, name="g2", team="u"),
            "c": _day(20.0, name="me", team="", role="lead"),
            "outside": _day(40.0, team=""),
        }
    )  # fmt: skip
    got = seats.reading(ledger, "day", NOW, weights=W)
    assert got["whole"]["figure"] == 100.0
    assert sum(r["share"] for r in got["teams"]) == pytest.approx(1.0)
    assert [(s["seat"], s["team"], s["role"], s["share"]) for s in got["top"]] == [
        ("g2", "u", "grinder", 0.3), ("me", "interactive", "lead", 0.2), ("g1", "t", "grinder", 0.1)
    ]  # fmt: skip
    assert got["outside"]["share"] == 0.4
    by_record = seats.reading(ledger, "day", NOW, by="record", weights=W)
    assert [s["records"] for s in by_record["seats"]] == [["b"], ["c"], ["a"]]
    assert by_record["top"] == got["top"]  # `top` reads seats under `by: record` too


def test_a_mixed_sum_prints_approx_and_an_unweighed_part_stays_out_of_it():
    ledger = _ledger(
        d2026_10_17={
            "a": _day(10.0, metered=True), "b": _day(10.0, name="w2", metered=True),
            "c": _day(0.0, name="w3", team="u", model="mystery", turns=2, unweighed=2),
        }
    )  # fmt: skip
    got = seats.reading(ledger, "day", NOW, weights=W)
    rows = {r["team"]: r for r in got["teams"]}
    assert (rows["t"]["unit"], rows["u"]["unit"], got["unit"]) == ("$", "≈$", "≈$")
    assert got["whole"]["figure"] == 20.0 and got["whole"]["unweighed_tokens"] == 1000
    assert rows["t"]["share"] == 1.0 and rows["u"]["share"] == 0.0
    assert seats.reading(ledger, "day", NOW, team="t", weights=W)["unit"] == "$"


def test_a_record_in_no_team_reads_as_an_interactive_seat_by_name_and_repo_with_its_role():
    mine = _rec("p1", name="ao-paul", conv="c1", team="", role="")
    there = _rec("p2", name="ao-paul", conv="c2", team="", role="designer", repo="other")
    again = _rec("p3", name="ao-paul", conv="c3", team="", role="")  # the same seat, a later run
    ledger: dict = {}
    recs = [mine, there, again]
    _take(
        ledger, [_t("u1", 0, source="a"), _t("u2", 0, source="b", conv="c2"), _t("u3", 0, source="c", conv="c3")], recs
    )
    got = seats.reading(ledger, "day", NOW, weights=W)
    assert sorted((s["seat"], s["repo"], s["team"], s["role"], s["records"]) for s in got["seats"]) == [
        ("ao-paul", "other", "interactive", "designer", ["p2"]),
        ("ao-paul", "r", "interactive", "other", ["p1", "p3"]),
    ]
    (row,) = seats.reading(ledger, "day", NOW, team="interactive", weights=W)["teams"]
    assert row["team"] == "interactive" and row["turns"] == 3


def test_every_row_carries_its_tokens_by_kind_summed_once_from_its_seats():
    """§4.4 *Tokens beside every figure* (TD-929): the team, role, repo, whole and series rows carry `tokens` by
    kind beside their figure, each the sum of its seats'; a seat on two models sums them once; no reply shares
    another's dict."""
    two = {"models": {"m": {"input": 100, "output": 10, "cache_read": 1000, "cache_write": 5, "turns": 1,
                            "figure": 1.0}, "n": {"input": 50, "output": 5, "cache_read": 500, "cache_write": 0,
                                                  "turns": 1, "figure": 2.0}}}  # fmt: skip
    ledger = _ledger(
        d2026_10_17={
            "a": _day(1.0, name="g1") | two,
            "b": _day(4.0, name="d1", role="designer", output=20, cache_read=7, cache_write=3),
        }
    )
    got = seats.reading(ledger, "day", NOW, weights=W)
    g1, d1 = sorted(got["seats"], key=lambda s: s["seat"], reverse=True)
    assert g1["tokens"] == {"input": 150, "output": 15, "cache_read": 1500, "cache_write": 5}  # once, not twice
    assert d1["tokens"] == {"input": 1000, "output": 20, "cache_read": 7, "cache_write": 3}
    both = {"input": 1150, "output": 35, "cache_read": 1507, "cache_write": 8}
    assert got["whole"]["tokens"] == got["teams"][0]["tokens"] == got["repos"]["r"]["tokens"] == both
    assert got["roles"]["grinder"]["tokens"] == g1["tokens"] and got["roles"]["designer"]["tokens"] == d1["tokens"]
    assert got["outside"]["tokens"] == dict.fromkeys(seats.KINDS, 0)
    assert "tokens" not in got["teams"][0]["previous"]  # the previous period, week and month: figures alone
    bucket = got["series"][-1]
    assert bucket["tokens"] == both and bucket["by"]["t"]["tokens"] == both
    got["whole"]["tokens"]["input"] = 0
    assert got["teams"][0]["tokens"]["input"] == 1150 and g1["tokens"] is not got["top"][0]["tokens"]
