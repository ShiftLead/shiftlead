"""A finished design lets go of its derived claim (design §4.8, TD-1567's build TD-1725): a derived claim with no PR
on an open `design-first` entry that some entry names in `Part of:`, and whose `Blocked by:` carries no
`decision (paul)`, is neither written nor kept — at the home's own derive, a node's sent derived reports, and the
home's retire pass over every record, local or a node's."""

from datetime import UTC, datetime

from conftest import park_ticks

from sessionorc import queue as queue_mod
from sessionorc import reports
from sessionorc.models import ProgressEntry, Session

DONE = {"id": "TD-50", "kind": "design-first", "blocked_by": [], "parts_open": ["TD-60"], "parts_archived": []}
ARCHIVED_PARTS = {"id": "TD-51", "kind": "design-first", "blocked_by": ["TD-9"], "parts_open": [],
                  "parts_archived": ["TD-61"]}  # fmt: skip
GATED = {"id": "TD-52", "kind": "design-first", "blocked_by": ["decision (paul)"], "parts_open": ["TD-62"]}
NO_PARTS = {"id": "TD-53", "kind": "design-first", "blocked_by": [], "parts_open": [], "parts_archived": []}
BUILD = {"id": "TD-54", "kind": "build", "blocked_by": [], "parts_open": ["TD-64"]}
ENTRIES = [DONE, ARCHIVED_PARTS, GATED, NO_PARTS, BUILD]


def _repos(root) -> dict:
    return {str(root): {"name": "repo", "root": str(root), "ledger": {"entries": [dict(e) for e in ENTRIES]}}}


def _claim(ref: str, **kw) -> ProgressEntry:
    return ProgressEntry(**{"ref": ref, "source": "derived", "branch": f"{ref.lower().replace('-', '')}-x", **kw})


def test_design_done_reads_the_kind_a_part_and_the_persons_gate_alone():
    assert queue_mod.design_done(DONE) and queue_mod.design_done(ARCHIVED_PARTS)  # an archived part keeps it done
    assert not queue_mod.design_done(GATED)  # its Go not given
    assert not queue_mod.design_done(NO_PARTS) and not queue_mod.design_done(BUILD)
    assert not queue_mod.design_done({**GATED, "blocked_by": ["decision (Paul)"]})  # `decided_by`'s compare
    assert queue_mod.design_done({**DONE, "owner": "paul"})  # never an Owner


def test_finished_designs_maps_a_record_as_the_queue_does_and_leaves_one_it_cannot(tmp_path):
    designs = queue_mod.finished_designs(_repos(tmp_path))
    rec = Session(id="a", name="a", kind="agent", adapter="claude-code", dir=str(tmp_path), repo=str(tmp_path))
    assert designs(rec) == {"TD-50", "TD-51"}
    elsewhere = Session(id="b", name="b", kind="agent", adapter="claude-code", dir="/x", repo=str(tmp_path / "other"))
    assert designs(elsewhere) == frozenset()  # no root of its: left as it is
    no_reading = queue_mod.finished_designs({str(tmp_path): {"name": "repo", "root": str(tmp_path)}})
    assert no_reading(rec) == frozenset()  # a repo with no ledger reading retires nothing


async def test_the_homes_derive_writes_no_finished_designs_claim_and_retires_one_already_held(
    agent, tmp_path, monkeypatch
):
    """The checked-out branch's claim is not written either, and what stands stands: a declared claim on a designed
    entry, a claim with a PR, a design still gated by `decision (paul)`, one with no part."""
    await park_ticks(agent)
    agent._repos.update(_repos(tmp_path))
    s = Session(id="ao-x-d", name="d", kind="interactive", adapter="claude-code", dir=str(tmp_path), repo=str(tmp_path))
    s.git = {"branch": "td50-x"}
    s.progress = [
        _claim("TD-51"),  # already on the record, from before its last build archived
        ProgressEntry(ref="TD-50", source="declared"),  # the session's own word
        _claim("TD-50", pr=7),  # a PR the by-number re-check still watches — out of reach (on another ref below)
    ]
    s.progress[2].ref = "TD-54"
    agent.sessions[s.id] = s
    monkeypatch.setattr(reports, "holds_directory", lambda _s: {s.id})
    derived = [_claim("TD-50"), _claim("TD-51"), _claim("TD-52"), _claim("TD-53")]
    monkeypatch.setattr(reports, "derive", lambda *a: (list(derived), [], []))
    try:
        agent._designs_retired_at = datetime.min.replace(tzinfo=UTC)
        await agent._derive_reports_inner(datetime.now(UTC))
        got = {(e.ref, e.source) for e in s.progress}
        assert got == {("TD-50", "declared"), ("TD-54", "derived"), ("TD-52", "derived"), ("TD-53", "derived")}
    finally:
        agent.sessions.pop(s.id)


async def test_a_derived_claim_on_a_finished_design_is_dropped_from_a_new_start_on_its_branch(
    agent, tmp_path, monkeypatch
):
    """A Start session on a designed top entry (§4.5 screen 12 *A designed top entry is the exception*): its `td-<n>`
    branch derives no claim, so the record holds nothing, and Open session finds it by its name, not a claim."""
    await park_ticks(agent)
    agent._repos.update(_repos(tmp_path))
    s = Session(id="ao-x-td-50", name="td-50", kind="interactive", adapter="claude-code", dir=str(tmp_path),
                repo=str(tmp_path))  # fmt: skip
    s.git = {"branch": "td-50"}
    agent.sessions[s.id] = s
    monkeypatch.setattr(reports, "holds_directory", lambda _s: {s.id})
    monkeypatch.setattr(reports, "derive", lambda *a: ([_claim("TD-50", branch="td-50")], [], []))
    try:
        await agent._derive_reports_inner(datetime.now(UTC))
        assert s.progress == [] and s.name == "td-50"
    finally:
        agent.sessions.pop(s.id)


async def test_the_home_filters_a_nodes_sent_claim_and_its_pass_retires_one_a_node_record_holds(agent, tmp_path):
    from test_link import record

    await park_ticks(agent)
    agent._repos.update(_repos(tmp_path))
    held = [_claim("TD-50").to_dict(), _claim("TD-52").to_dict()]
    agent._take_records(
        "laptop",
        [
            record(repo=str(tmp_path), progress=held),
            record("ao-x-far", repo="/nowhere/registered", progress=held),  # a path matching no root
            record("ao-x-shut", repo=str(tmp_path), state="closed", progress=held),  # the derive pass skips it
        ],
        whole=True,
    )
    far, shut = agent.remote["laptop"]["ao-x-far"], agent.remote["laptop"]["ao-x-shut"]
    agent._designs_retired_at = datetime.min.replace(tzinfo=UTC)
    agent._retire_finished_designs(datetime.now(UTC), queue_mod.finished_designs(agent._repos))
    near = agent.remote["laptop"]["ao-x-w"]
    assert [e.ref for e in near.progress] == ["TD-52"]
    assert [e.ref for e in far.progress] == ["TD-50", "TD-52"] and [e.ref for e in shut.progress] == ["TD-50", "TD-52"]
    # the clock: a second pass inside DERIVE_EVERY reads nothing
    near.progress.append(_claim("TD-51"))
    agent._retire_finished_designs(datetime.now(UTC), queue_mod.finished_designs(agent._repos))
    assert [e.ref for e in near.progress] == ["TD-52", "TD-51"]
    # what the node sends is filtered as the home's own derive is
    got = await agent._take_derived(
        "laptop",
        {"id": "ao-x-w", "progress": [_claim("TD-50").to_dict(), _claim("TD-53").to_dict()], "retire": []},
    )
    assert got == {"changed": True} and [e.ref for e in near.progress] == ["TD-52", "TD-51", "TD-53"]
