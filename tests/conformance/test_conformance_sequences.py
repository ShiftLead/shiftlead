"""The offline suite's sequence form (design §4.3 *The conformance suite*, *The third adapter*): a captured hook
fixture read in order through the adapter's hook and the host agent's apply, the record carried between the
payloads and asserted after each — what one payload alone cannot show, a prompt ended by a later event among it.
The manifest's `sequences` lists each file and the record after each of its lines (`state`, the open `pending`'s
kind, `subagents`); the record's `adapter_id` and `transcript` stay the main session's throughout."""

from __future__ import annotations

import json

import pytest
from _harness import HARNESSES, agent_adapters, fixture, manifest

from sessionorc import adapters
from sessionorc.models import Session

pytestmark = pytest.mark.integration

AGENTS = agent_adapters()


def _record(s: Session) -> dict:
    return {"state": s.state, "pending": s.pending.kind if s.pending else None, "subagents": s.subagents}


@pytest.mark.parametrize("name", AGENTS)
async def test_each_sequence_carries_the_record_through_its_payloads(name, agent, tmp_path):
    sequences = manifest(name).get("sequences") or []
    if not sequences:
        pytest.skip(f"{name} ships no sequence fixture")
    harness = HARNESSES[name]
    adapters.load_all()
    for seq in sequences:
        payloads = [json.loads(x) for x in fixture(name, seq["file"]).read_text(encoding="utf-8").splitlines() if x]
        assert len(payloads) == len(seq["records"]), f"{seq['file']}: {len(payloads)} payloads"
        s = Session(id=f"ao-seq-{name}", name="seq", kind="agent", dir=str(tmp_path), adapter=name, state="starting")
        agent.sessions[s.id] = s
        main: dict[str, str] = {}
        for i, (payload, want) in enumerate(zip(payloads, seq["records"], strict=True)):
            params = harness.hook_params(payload, at_composer=seq.get("at_composer", True))
            if params is not None:
                agent._apply_event(s.id, dict(params))
            main = main or {k: getattr(s, k) for k in ("adapter_id", "transcript") if getattr(s, k)}
            got = _record(agent.sessions[s.id])
            assert got == want, f"{seq['file']} line {i + 1} ({payload.get('hook_event_name')}): {got}, want {want}"
            assert {k: getattr(s, k) for k in main} == main, f"{seq['file']} line {i + 1}: the record re-pointed"
        del agent.sessions[s.id]
