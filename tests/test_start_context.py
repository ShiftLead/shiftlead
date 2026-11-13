"""TD-283 part (2) slice 1, design §4.3 `start_context`: text a session holds from its start that is
no prompt. `create` hands it to an adapter that says it can carry one, refuses it in words for one
that cannot, counts it under the argument limit as it counts a prompt, and keeps it on the record and
the launch record — and a resume that gives none carries the conversation's own."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _stubs import HookFedStub

from sessionorc import adapters, mail, paths
from sessionorc.adapters import LaunchSpec
from sessionorc.client import AgentError, LocalClient


class ContextStub(HookFedStub):
    """A hook-fed adapter that carries a start context, and remembers what each launch was handed."""

    name = "ctxstub"
    start_context = True

    def __init__(self):
        self.launches: list[dict] = []

    def launch(self, *, profile, resume, prompt, unattended, cwd, name="", start_context=None):
        self.launches.append({"resume": resume, "prompt": prompt, "start_context": start_context})
        return LaunchSpec(argv=["bash", "--norc"], adapter_id=resume)  # a resume keeps its id, as Claude Code's does


@pytest.fixture
def ctxstub(monkeypatch):
    adapters.load_all()
    stub = ContextStub()
    monkeypatch.setitem(adapters._REGISTRY, stub.name, stub)
    return stub


async def test_the_start_context_reaches_the_launch_the_record_and_every_resume(agent, ctxstub, tmp_path):
    lines = "You are drafting a ledger entry.\nThe ledger is docs/technical_debt.md."
    async with LocalClient() as c:
        s = await c.call("create", name="entry-1", dir=str(tmp_path), adapter="ctxstub", start_context=lines)
        assert s["start_context"] == lines
        handed = mail.start_context_file_text(lines)  # the home's preface heads it (§4.1, TD-347)
        assert handed.startswith(mail.BRIEF_PREFACE + "\n\n") and handed.endswith(lines)
        assert ctxstub.launches[-1] == {"resume": None, "prompt": None, "start_context": handed}  # no turn for it
        await c.call("hook", session=s["id"], adapter_id="cc-1")
        await c.call("kill", id=s["id"])
        # the one-press Resume sends no start context: the conversation's own is handed again
        again = await c.call("create", name="entry-1", dir=str(tmp_path), adapter="ctxstub", resume="cc-1")
        assert again["start_context"] == lines and ctxstub.launches[-1]["start_context"] == handed
        await c.call("kill", id=again["id"])
        # …under another name too: it is the conversation's, not the name's
        other = await c.call("create", name="moved", dir=str(tmp_path), adapter="ctxstub", resume="cc-1")
        assert other["start_context"] == lines and ctxstub.launches[-1]["start_context"] == handed
        await c.call("kill", id=other["id"])
        # a fresh start under the name holds nothing it was not given: the record none, the file the preface
        fresh = await c.call("create", name="entry-1", dir=str(tmp_path), adapter="ctxstub")
        assert fresh["start_context"] is None and ctxstub.launches[-1]["start_context"] == mail.BRIEF_PREFACE
        await c.call("kill", id=fresh["id"])
        # a blank one is none
        blank = await c.call("create", name="b", dir=str(tmp_path), adapter="ctxstub", start_context="  \n")
        assert blank["start_context"] is None
        await c.call("kill", id=blank["id"])


async def test_an_adapter_without_the_flag_is_refused_in_words_and_nothing_is_folded(agent, hookstub, tmp_path):
    async with LocalClient() as c:
        for adapter in ("shell", "hookstub"):
            with pytest.raises(AgentError, match="cannot carry a start context") as refused:
                await c.call("create", name="x", dir=str(tmp_path), adapter=adapter, start_context="told")
            assert "design §4.3" in str(refused.value)
        assert all(v["name"] != "x" for v in await c.call("list"))


async def test_a_start_context_no_process_can_take_is_refused_before_anything(agent, ctxstub, tmp_path):
    from sessionorc.tmux import ARG_LIMIT

    async with LocalClient() as c:
        with pytest.raises(AgentError, match="the start context is .* past what a process can be started with"):
            await c.call("create", name="huge", dir=str(tmp_path), adapter="ctxstub", start_context="x" * ARG_LIMIT)
        assert ctxstub.launches == [] and all(v["name"] != "huge" for v in await c.call("list"))


async def test_the_launch_record_keeps_it_so_a_restart_launches_with_it(agent, ctxstub, tmp_path):
    async with LocalClient() as c:
        s = await c.call(
            "create", name="kept", dir=str(tmp_path), adapter="ctxstub", supervised=True, start_context="told"
        )
        rec = json.loads((paths.launch_dir() / f"{s['id']}.json").read_text())
        assert rec["start_context"] == "told"
        await c.call("hook", session=s["id"], adapter_id="cc-2")
        await c.call("kill", id=s["id"])
        # a resume that gives none writes the launch record with the conversation's own
        again = await c.call("create", name="kept", dir=str(tmp_path), adapter="ctxstub", resume="cc-2")
        rec = json.loads((paths.launch_dir() / f"{again['id']}.json").read_text())
        assert rec["start_context"] == "told"
        await c.call("kill", id=again["id"])


async def test_the_context_file_goes_with_the_last_record_holding_the_conversation(agent, ctxstub, tmp_path):
    # design §4.1 *No prose in the argv* (TD-339): removed when the record is forgotten, but never from
    # under another record of the same conversation, whose Resume would hand it again
    async with LocalClient() as c:
        a = await c.call("create", name="a", dir=str(tmp_path), adapter="ctxstub", resume="cc-9", start_context="t")
        await c.call("kill", id=a["id"])
        b = await c.call("create", name="b", dir=str(tmp_path), adapter="ctxstub", resume="cc-9")
        told = paths.context_file("cc-9")
        told.parent.mkdir(parents=True, exist_ok=True)
        told.write_text("t")
        await c.call("remove", id=a["id"])
        assert told.is_file()  # `b` still holds the conversation
        await c.call("kill", id=b["id"])
        await c.call("remove", id=b["id"])
        assert not told.exists()
        # a create under a held name replaces its record in place, never forgetting it: the old
        # conversation's file goes there (review of PR #1147)
        old = await c.call("create", name="c", dir=str(tmp_path), adapter="ctxstub", resume="cc-7", start_context="t")
        paths.context_file("cc-7").write_text("t")
        await c.call("kill", id=old["id"])
        new = await c.call("create", name="c", dir=str(tmp_path), adapter="ctxstub", resume="cc-8", start_context="u")
        assert new["id"] == old["id"] and not paths.context_file("cc-7").exists()


@pytest.mark.unit
def test_claude_code_carries_it_as_the_system_prompts_tail(tmp_path, monkeypatch):
    from shiftlead.adapters.claude_code import AT_COMPOSER_ENV, ClaudeCodeAdapter

    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "profiles.yml").write_text("default: p\nprofiles:\n  p: {account: p}\n")
    ad = ClaudeCodeAdapter(binary="claude")
    assert ad.start_context is True
    spec = ad.launch(profile="", resume=None, prompt=None, unattended=False, cwd=tmp_path, start_context="told")
    # by file, never as prose in the argv (design §4.1 *No prose in the argv*, TD-339)
    told = Path(spec.argv[spec.argv.index("--append-system-prompt-file") + 1])
    assert told == tmp_path / "home" / "launch" / f"{spec.adapter_id}.context.md"
    assert told.read_text() == "told" and told.stat().st_mode & 0o777 == 0o600
    assert "told" not in spec.argv and "--append-system-prompt" not in spec.argv
    assert spec.env[AT_COMPOSER_ENV] == "1"  # still at the composer: no turn runs for it
    resumed = ad.launch(profile="", resume="abc", prompt="-go", unattended=False, cwd=tmp_path, start_context="again")
    path = Path(resumed.argv[resumed.argv.index("--append-system-prompt-file") + 1])
    assert path.name == "abc.context.md" and path.read_text() == "again"
    assert resumed.first_prompt == "-go" and "-go" not in resumed.argv  # typed at the composer
    with pytest.raises(ValueError, match="cannot name a file"):
        ad.launch(profile="", resume="../x", prompt=None, unattended=False, cwd=tmp_path, start_context="told")
    bare = ad.launch(profile="", resume=None, prompt=None, unattended=False, cwd=tmp_path)
    assert "--append-system-prompt-file" not in bare.argv and bare.first_prompt is None
    assert Path(spec.argv[spec.argv.index("--settings") + 1]).is_file()


# --- TD-1669: a member's brief in the system prompt (design §4.3 *The shared text goes in the system prompt*)

BRIEF = "You are a grinder.\nPick the highest-ranked entry."
MADE = {"template": "grinder.md"}  # a role's brief: what `prompt_from` says it was made from


class SystemStub(ContextStub):
    """A start context that is the tool's system prompt, written to the conversation's file as Claude Code's
    `launch` writes it, and kept as it stands on `keep_context`."""

    name = "sysstub"
    start_context_system = True

    def __init__(self):
        super().__init__()
        self.n = 0

    def launch(self, *, profile, resume, prompt, unattended, cwd, name="", start_context=None, keep_context=False):
        self.n += 1
        conversation = resume or f"sys-{self.n}"
        self.launches.append(
            {"resume": resume, "prompt": prompt, "start_context": start_context, "keep_context": keep_context}
        )
        if start_context:
            from shiftlead.adapters.claude_code import write_context_file

            write_context_file(conversation, start_context)
        return LaunchSpec(argv=["bash", "--norc"], adapter_id=conversation, first_prompt=prompt)


@pytest.fixture
def sysstub(monkeypatch):
    adapters.load_all()
    stub = SystemStub()
    monkeypatch.setitem(adapters._REGISTRY, stub.name, stub)
    return stub


def _launch_record(sid: str) -> dict:
    return json.loads((paths.launch_dir() / f"{sid}.json").read_text())


async def test_a_members_brief_moves_and_the_records_keep_the_callers_own(agent, sysstub, tmp_path):
    for d in ("b", "c"):
        (tmp_path / d).mkdir()
    async with LocalClient() as c:
        s = await c.call(
            "create", name="g1", dir=str(tmp_path), adapter="sysstub", supervised=True, prompt=BRIEF, prompt_from=MADE
        )
        handed = sysstub.launches[-1]
        assert handed["prompt"] == mail.BRIEF_MOVED_LINE
        assert handed["start_context"] == mail.start_context_file_text(BRIEF)
        assert paths.context_file(s["adapter_id"]).read_text() == mail.start_context_file_text(BRIEF)
        rec = agent.sessions[s["id"]]
        assert rec.start_context is None and rec.first_prompt == mail.BRIEF_MOVED_LINE
        launch = _launch_record(s["id"])
        assert launch["prompt"] == BRIEF and launch["prompt_from"] == MADE and "start_context" not in launch
        # Focus reads it from the file, in the get's copy alone; the list's views carry none
        assert (await c.call("get", id=s["id"]))["start_context"] == BRIEF
        assert next(v for v in await c.call("list") if v["id"] == s["id"]).get("start_context") is None
        assert agent.sessions[s["id"]].start_context is None
        # a second member of the line, another name, the same brief: the same file text
        kw = {"adapter": "sysstub", "prompt_from": MADE}
        t = await c.call("create", name="g2", dir=str(tmp_path / "b"), prompt=BRIEF, **kw)
        assert paths.context_file(t["adapter_id"]).read_text() == paths.context_file(s["adapter_id"]).read_text()
        # a member whose own lane makes its own brief: another text
        other = BRIEF + "\nYour lane: TD-7."
        u = await c.call("create", name="g3", dir=str(tmp_path / "c"), prompt=other, **kw)
        assert paths.context_file(u["adapter_id"]).read_text() == mail.start_context_file_text(other)


async def test_a_seat_fills_line_stays_typed(agent, sysstub, tmp_path):
    from sessionorc.agent_tick import FILLED_FOR

    filled = f"{FILLED_FOR}m-1 — a question"
    async with LocalClient() as c:
        s = await c.call(
            "create", name="seat", dir=str(tmp_path), adapter="sysstub", supervised=True,
            prompt=f"{BRIEF}\n\n{filled}", prompt_from=MADE,
        )  # fmt: skip
        assert sysstub.launches[-1]["prompt"] == f"{mail.BRIEF_MOVED_LINE}\n\n{filled}"
        assert sysstub.launches[-1]["start_context"] == mail.start_context_file_text(BRIEF)
        assert _launch_record(s["id"])["prompt"] == f"{BRIEF}\n\n{filled}"
        assert mail.first_prompt_lead(agent.sessions[s["id"]].first_prompt) == (mail.BRIEF_MOVED_LINE, filled)


@pytest.mark.parametrize(
    "given",
    [
        {"prompt": BRIEF},  # no role's brief: a person's own prompt
        {"prompt": BRIEF, "prompt_from": MADE, "argv": ["bash", "--norc"]},  # an argv replaces the adapter's
        {"prompt": BRIEF, "prompt_from": MADE, "start_context": "the Add entry template"},  # both: as given
    ],
)
async def test_no_move_where_the_create_is_not_a_members_brief(agent, sysstub, tmp_path, given):
    async with LocalClient() as c:
        await c.call("create", name="x", dir=str(tmp_path), adapter="sysstub", **given)
        handed = sysstub.launches[-1]
        assert handed["prompt"] == BRIEF
        assert handed["start_context"] == mail.start_context_file_text(given.get("start_context"))


async def test_no_move_on_an_adapter_whose_start_context_is_not_its_system_prompt(agent, ctxstub, tmp_path):
    async with LocalClient() as c:
        await c.call("create", name="x", dir=str(tmp_path), adapter="ctxstub", prompt=BRIEF, prompt_from=MADE)
        assert ctxstub.launches[-1] == {"resume": None, "prompt": BRIEF, "start_context": mail.BRIEF_PREFACE}


async def test_a_resume_keeps_the_conversations_file_and_its_launch_record(agent, sysstub, tmp_path):
    async with LocalClient() as c:
        s = await c.call(
            "create", name="g", dir=str(tmp_path), adapter="sysstub", supervised=True, prompt=BRIEF, prompt_from=MADE
        )
        conv = s["adapter_id"]
        told = paths.context_file(conv).read_bytes()
        for _ in range(2):
            await c.call("kill", id=s["id"])
            s = await c.call("create", name="g", dir=str(tmp_path), adapter="sysstub", resume=conv, prompt="go on")
            handed = sysstub.launches[-1]
            assert handed["keep_context"] is True and handed["start_context"] is None and handed["prompt"] == "go on"
            assert paths.context_file(conv).read_bytes() == told
            launch = _launch_record(s["id"])  # the brief kept for a later replay, never the resume's own prompt
            assert launch["prompt"] == BRIEF and launch["prompt_from"] == MADE
        # the file gone: the brief is written again from the launch record, never the preface alone
        await c.call("kill", id=s["id"])
        paths.context_file(conv).unlink()
        s = await c.call("create", name="g", dir=str(tmp_path), adapter="sysstub", resume=conv)
        assert sysstub.launches[-1]["start_context"] == mail.start_context_file_text(BRIEF)
        assert paths.context_file(conv).read_bytes() == told


async def test_a_resume_with_neither_file_nor_launch_record_writes_the_preface(agent, sysstub, tmp_path):
    async with LocalClient() as c:
        s = await c.call("create", name="h", dir=str(tmp_path), adapter="sysstub", resume="lost-1")
        assert sysstub.launches[-1]["start_context"] == mail.BRIEF_PREFACE
        assert sysstub.launches[-1]["keep_context"] is False
        assert (await c.call("get", id=s["id"])).get("start_context") is None  # nothing after the preface: no row
