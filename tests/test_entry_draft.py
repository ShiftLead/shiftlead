"""The Add entry form's draft (design §4.4 *The Add entry form's draft*, §4.6 *Run-log retention*,
TD-630, built by TD-633 slice 1): `attach` with `draft` writes the form's files before any session
exists, under `attachments/<draft>/`; a way out claims the folder by its `claimed.json` — *Open a
session* through `create`, *Hand to the techlead* through `entry_add` — and the hourly sweep reads
that claim alone."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import pathlib
from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks

from sessionorc import agent_common, paths
from sessionorc.client import AgentError, LocalClient


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _age(path: pathlib.Path, seconds: float) -> None:
    t = datetime.now(UTC).timestamp() - seconds
    os.utime(path, (t, t))


def _draft(token: str, files: dict[str, float], claim: dict | None = None) -> pathlib.Path:
    """`attachments/<token>/` with each file aged by its seconds, the folder aged as its oldest."""
    folder = paths.attachments_dir() / token
    folder.mkdir(parents=True)
    for name, secs in files.items():
        (folder / name).write_bytes(b"x")
        _age(folder / name, secs)
    if claim is not None:
        (folder / paths.DRAFT_CLAIM).write_text(json.dumps(claim))
        _age(folder / paths.DRAFT_CLAIM, max(files.values(), default=0))
    _age(folder, max(files.values(), default=0))
    return folder


@pytest.mark.integration
async def test_a_forms_first_file_mints_a_draft_and_its_later_files_share_it(agent, tmp_path):
    """`draft: ""` mints `draft-<8 hex>` and answers it with the path; a later file names it and lands
    beside the first, in pieces as a session's do; a session's id beside a draft, a token that is not
    one, a draft this host does not hold, and a later piece with no token are refused in words."""
    async with LocalClient() as c:
        first = await c.call("attach", draft="", name="Screen Shot.png", data=_b64(b"png"))
        token = first["draft"]
        assert paths.DRAFT.fullmatch(token)
        where = paths.attachments_dir() / token
        assert pathlib.Path(first["path"]) == where / "Screen_Shot.png" and first["bytes"] == 3
        again = await c.call("attach", draft=token, name="notes.txt", data=_b64(b"words"))
        assert again["draft"] == token and pathlib.Path(again["path"]) == where / "notes.txt"
        body = bytes(range(256)) * 8
        up = await c.call("attach", draft=token, name="deck.pdf", data=_b64(body[:1024]), total=len(body))
        assert up["draft"] == token and "upload" in up
        done = await c.call(
            "attach", draft=token, name="deck.pdf", data=_b64(body[1024:]), upload=up["upload"], offset=1024
        )
        assert pathlib.Path(done["path"]).read_bytes() == body and done["draft"] == token
        posed = await c.call("attach", draft=token, name="claimed.json", data=_b64(b"{}"))
        assert pathlib.Path(posed["path"]).name == "attached-claimed.json", "the claim's name is never a file's"
        assert not (where / paths.DRAFT_CLAIM).exists()
        other = (await c.call("attach", draft="", name="x.txt", data=_b64(b"x")))["draft"]
        assert other != token, "each form's first file mints its own"
        with pytest.raises(AgentError, match="a session's id or a draft, not both"):
            await c.call("attach", id="ao-x", draft=token, name="x", data=_b64(b"x"))
        with pytest.raises(AgentError, match="is not a draft"):
            await c.call("attach", draft="../ao-x", name="x", data=_b64(b"x"))
        with pytest.raises(AgentError, match="no draft draft-00000000 on this host"):
            await c.call("attach", draft="draft-00000000", name="x", data=_b64(b"x"))
        with pytest.raises(AgentError, match="a later piece names its draft"):
            await c.call("attach", draft="", name="x", data=_b64(b"x"), upload="0" * 16, offset=1)


@pytest.mark.integration
async def test_open_a_session_claims_the_draft_for_the_new_session(agent, tmp_path):
    """*Open a session* hands `draft` to the create: once the session exists its id is the claim's
    `by`, and the files stay where the person's words name them; a claimed draft takes no more files,
    and a create naming one is refused before anything is made."""
    await park_ticks(agent)
    async with LocalClient() as c:
        token = (await c.call("attach", draft="", name="shot.png", data=_b64(b"png")))["draft"]
        folder = paths.attachments_dir() / token
        s = await c.call("create", name="entry-1", dir=str(tmp_path), adapter="shell", draft=token)
        claim = json.loads((folder / paths.DRAFT_CLAIM).read_text())
        assert claim["by"] == s["id"] and datetime.fromisoformat(claim["at"])
        assert (folder / "shot.png").read_bytes() == b"png", "neither way out moves a file"
        with pytest.raises(AgentError, match=f"draft {token} is already claimed"):
            await c.call("attach", draft=token, name="late.png", data=_b64(b"x"))
        (tmp_path / "b").mkdir()
        with pytest.raises(AgentError, match=f"create: draft {token} is already claimed"):
            await c.call("create", name="entry-2", dir=str(tmp_path / "b"), adapter="shell", draft=token)
        assert not any(r.name == "entry-2" for r in agent.sessions.values())
        with pytest.raises(AgentError, match="not beside start_at or held"):
            await c.call(
                "create", name="entry-3", dir=str(tmp_path), adapter="shell", unattended=True,
                start_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat(), draft="draft-0000000a",
            )  # fmt: skip
        await c.call("kill", id=s["id"])


@pytest.mark.integration
async def test_hand_to_the_techlead_claims_the_draft_for_the_ask(agent, tmp_path):
    """*Hand to the techlead* hands `draft` to `entry_add`: the claim's `by` is `hand:<the ask's id>`,
    and the envelope carries `draft` beside `entry`; a draft already claimed is refused before any
    ask is sent."""
    repo = tmp_path / "shiftlead"
    repo.mkdir()
    home = paths.home()
    (home / "repos.txt").write_text(f"{repo}\n")
    (home / "hosts.yml").write_text(f"local:\n  repos_registry: {home / 'repos.txt'}\n")
    await park_ticks(agent)
    async with LocalClient() as c:
        seat = (
            await c.call(
                "create",
                name="tl",
                dir=str(tmp_path),
                adapter="agentshell",
                argv=["bash", "--norc", "--noprofile"],
                unattended=True,
                supervised=True,
                prompt="the seat's brief",
                seat={"trigger": "asks"},
            )  # fmt: skip
        )["id"]
        token = (await c.call("attach", draft="", name="shot.png", data=_b64(b"png")))["draft"]
        teams = [{"team": "ao-grind", "seat": seat}]
        got = await c.call("entry_add", repo="shiftlead", type="debt", text="see the shot", teams=teams, draft=token)
        claim = json.loads((paths.attachments_dir() / token / paths.DRAFT_CLAIM).read_text())
        assert claim["by"] == f"hand:{got['id']}"
        e = next(e for e in agent.sessions[got["to"]].inbox if e.id == got["id"])
        assert e.draft == token and e.entry == {"repo": "shiftlead", "type": "debt"}
        before = len(agent.sessions[got["to"]].inbox)
        with pytest.raises(AgentError, match="already claimed"):
            await c.call("entry_add", repo="shiftlead", type="debt", text="again", teams=teams, draft=token)
        assert len(agent.sessions[got["to"]].inbox) == before, "refused before the send"
        plain = await c.call("entry_add", repo="shiftlead", type="debt", text="no files", teams=teams)
        assert next(e for e in agent.sessions[got["to"]].inbox if e.id == plain["id"]).draft is None
        await c.call("kill", id=seat)


@pytest.mark.integration
@pytest.mark.parametrize("keep", [7, 0])
async def test_the_sweep_reads_a_drafts_claim(agent, tmp_path, keep):
    """Unclaimed: removed an hour after its last write whatever `runs_keep_days`, a younger one kept.
    Claimed by a hand: removed `keep` days after the claim, kept under `0`. Claimed by a session:
    kept while the session is live, then its files go by age as the session's own folder's do, the
    folder going with its claim once nothing else is left. A claim that cannot be read is kept."""
    (paths.home() / "hosts.yml").write_text(f"local:\n  runs_keep_days: {keep}\n")
    now = datetime.now(UTC)
    old, day = 2 * paths.ATTACH_PART_IDLE_S, 86400
    abandoned = _draft("draft-0000000a", {"shot.png": old})
    writing = _draft("draft-0000000b", {"shot.png": old, "new.png": 60})
    hand_old = _draft(
        "draft-0000000c", {"a.png": 9 * day}, {"by": "hand:m-1", "at": (now - timedelta(days=8)).isoformat()}
    )
    hand_young = _draft("draft-0000000d", {"a.png": 9 * day}, {"by": "hand:m-2", "at": now.isoformat()})
    live = _draft("draft-0000000e", {"a.png": 30 * day}, {"by": "ao-live-1", "at": now.isoformat()})
    ended = _draft("draft-0000000f", {"a.png": 30 * day}, {"by": "ao-ended-2", "at": now.isoformat()})
    ended_young = _draft("draft-00000010", {"a.png": 30 * day, "b.png": day}, {"by": "ao-ended-3", "at": ""})
    garbled = _draft("draft-00000011", {"a.png": old})
    (garbled / paths.DRAFT_CLAIM).write_text("{not json")
    await asyncio.to_thread(agent._prune_runs, now, set(), {"ao-live-1"})
    assert not abandoned.exists(), "an abandoned form leaves nothing past the hour"
    assert writing.exists() and garbled.exists() and live.exists() and hand_young.exists()
    if keep:
        assert not hand_old.exists() and not ended.exists()
        assert not (ended_young / "a.png").exists() and (ended_young / "b.png").exists()
        assert (ended_young / paths.DRAFT_CLAIM).exists(), "the claim stays while a file does"
    else:
        assert hand_old.exists() and ended.exists() and (ended_young / "a.png").exists()
    await asyncio.to_thread(agent._prune_runs, now, set())  # no live reading: a session's draft is kept
    assert live.exists()


@pytest.mark.unit
def test_a_draft_token_is_its_folder_name_and_nothing_else(tmp_path, monkeypatch):
    """The one gate every call passes (`agent_common.draft_folder`): a path, a session's id or a
    symlinked folder is never a draft."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    paths.attachments_dir().mkdir(parents=True)
    (tmp_path / "elsewhere").mkdir()
    (paths.attachments_dir() / "draft-0000abcd").symlink_to(tmp_path / "elsewhere")
    for bad in ("draft-0000abcd", "ao-x", "draft-0000ABCD", "draft-0000abcd/..", ""):
        with pytest.raises(agent_common.RpcError):
            agent_common.draft_folder(bad, "attach")


@pytest.mark.unit
def test_a_second_claim_is_refused_and_the_first_stands(tmp_path, monkeypatch):
    """A double press, or the draft handed to both ways out: the claim is linked into place, so the
    second is refused and the first claimant keeps the files; no temporary is left behind."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    folder = _draft("draft-0000beef", {"a.png": 0})
    now = datetime.now(UTC)
    agent_common.claim_draft(folder, "ao-first-1", now)
    with pytest.raises(agent_common.RpcError, match="already claimed"):
        agent_common.claim_draft(folder, "hand:m-2", now)
    assert agent_common.read_draft_claim(folder)["by"] == "ao-first-1"
    assert sorted(f.name for f in folder.iterdir()) == ["a.png", paths.DRAFT_CLAIM]
