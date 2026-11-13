"""A seat's life end to end, in CI, with no model (design §4.3 *The conformance suite*, TD-1647): for every
registered agent adapter, a launch, the brief typed, an ask delivered and read, an `ao` command run, the reply
landing, the seat closing — the adapter built with `binary` set to a wrapper that runs the stub CLI
(`stub_cli.py`), which replays the adapter's own captured hook payloads, on the in-process host agent of the
suite's private tmux socket and scratch home. What the stub cannot show — whether the real tool, given these
arguments, prompts — is the seat smoke's (TD-1648)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from _harness import HARNESSES, agent_adapters, manifest
from conftest import wait_for

from sessionorc import adapters, paths
from sessionorc.client import LocalClient

AGENTS = agent_adapters()
STUB = Path(__file__).resolve().parent / "stub_cli.py"
BRIEF = "Stub brief: answer each ask in your inbox with its last word."
# the fact-checker brief's road (TD-1582): the stub's own read standing in for the model's, then the reply
SCRIPT = "ao inbox --json\nao reply {id} '{text}'\n"


def _profiles(name: str, tmp: Path) -> None:
    """Three profiles of the adapter: `skip` (the default), `other` (`all`, one other unattended argument) and
    `none` (`all`, declaring no unattended arguments, so the adapter's default is dropped)."""
    tool = "" if name == "claude-code" else f"adapter: {name}, "
    cfg = tmp / "cfg"
    (paths.home()).mkdir(parents=True, exist_ok=True)
    (paths.home() / "profiles.yml").write_text(
        "default: skip\nprofiles:\n"
        f"  skip: {{{tool}account: t, config_dir: {cfg}}}\n"
        f"  other: {{{tool}account: t, config_dir: {cfg}, permission_prompts: all, unattended_args: [--stub-other]}}\n"
        f"  none: {{{tool}account: t, config_dir: {cfg}, permission_prompts: all}}\n",
        encoding="utf-8",
    )


def _stubbed(name: str, tmp: Path, monkeypatch: pytest.MonkeyPatch, key: str) -> Path:
    """Register the adapter built with `binary` set to a wrapper that runs the stub; the launch's own folder,
    where the stub's script, `launch.json` and `events.log` live."""
    out = tmp / f"stub-{key}"
    out.mkdir()
    (out / "script").write_text(SCRIPT, encoding="utf-8")
    wrapper = out / "tool"
    pythonpath = os.pathsep.join(p for p in sys.path if p)
    wrapper.write_text(
        "#!/bin/sh\n"
        f"PATH={shlex.quote(os.environ['PATH'])} PYTHONPATH={shlex.quote(pythonpath)} "
        f"exec {shlex.quote(sys.executable)} {shlex.quote(str(STUB))} {name} "
        f'{shlex.quote(str(out / "script"))} -- "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    monkeypatch.setitem(adapters._REGISTRY, name, type(adapters.get(name))(binary=str(wrapper)))
    return out


def _launch(out: Path) -> dict:
    return json.loads((out / "launch.json").read_text(encoding="utf-8"))


def _events(out: Path) -> list[str]:
    f = out / "events.log"
    return f.read_text(encoding="utf-8").splitlines() if f.exists() else []


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)  # a probe, no signal sent
    except ProcessLookupError:
        return False
    return True


def _has_skip(argv: list[str], flags: tuple[str, ...]) -> bool:
    joined = f" {' '.join(argv)} "
    return any(f" {f} " in joined for f in flags)


async def _start(c: LocalClient, name: str, tmp: Path, profile: str, out: Path) -> dict:
    cwd = tmp / f"seat-{out.name}"
    cwd.mkdir()
    s = await c.call(
        "create",
        name=f"life-{profile}",
        dir=str(cwd),
        adapter=name,
        profile=profile,
        unattended=True,
        prompt=BRIEF,
        seat={"trigger": "asks"},
    )
    assert await wait_for(lambda: (out / "launch.json").exists(), timeout=20.0), f"{name}: the stub never started"
    return s


async def _close(c: LocalClient, sid: str, out: Path) -> dict:
    pid = _launch(out)["pid"]
    await c.call("close", id=sid)
    assert await wait_for(lambda: not _alive(pid), timeout=20.0), f"the stub {pid} outlived the close"
    return await c.call("get", id=sid)


@pytest.mark.parametrize("name", AGENTS)
def test_each_agent_adapter_names_a_life(name):
    """An adapter with no `life` fails the suite, never skips it; its turn waits on nobody."""
    life = manifest(name).get("life")
    assert life, f"{name}'s manifest names no `life` (design §4.3 *A seat's life end to end*)"
    hooks = next(h for h in manifest(name)["hooks"] if h["file"] == "captured/hooks.jsonl")
    for i in life["turn"]:
        assert hooks["reads"][i]["state"] != "needs-you", f"{name}: turn payload {i} waits on the person"
    assert hooks["reads"][life["start"]]["state"] == "idle"
    assert hooks["reads"][life["turn"][-1]]["state"] == "idle"
    assert any(p["file"] == life["composer"] and p.get("composer") == "" for p in manifest(name)["panes"])


@pytest.mark.parametrize("name", AGENTS)
async def test_a_seats_life_on_the_stub(name, agent, tmp_path, monkeypatch):
    harness = HARNESSES[name]
    harness.stub_setup(tmp_path, monkeypatch)
    _profiles(name, tmp_path)
    skip = harness.skip_flags
    asking = list(getattr(adapters.get(name), "asking_args", ()) or ())
    async with LocalClient() as c:
        # the launches under `all`: no skip flag, the profile's other argument kept, the asking arguments added
        for profile in ("other", "none"):
            out = _stubbed(name, tmp_path, monkeypatch, profile)
            s = await _start(c, name, tmp_path, profile, out)
            argv = _launch(out)["argv"]
            assert not _has_skip(argv, skip), f"{profile}: a skip flag under `all`: {argv}"
            assert ("--stub-other" in argv) == (profile == "other"), argv
            # the seat's launch read its tool's version through the adapter's own method (§4.3, TD-1726)
            assert agent.sessions[s["id"]].tool_version == f"0.0.0 (stub {name})"
            assert all(a in argv for a in asking), f"{profile}: {asking} missing from {argv}"
            await _close(c, s["id"], out)

        # the life, under `skip`
        out = _stubbed(name, tmp_path, monkeypatch, "skip")
        seen: list[str] = []
        s = await _start(c, name, tmp_path, "skip", out)
        sid = s["id"]

        async def watch() -> None:
            while True:
                state = agent.sessions[sid].state  # read in process: the client is the case's
                if not seen or seen[-1] != state:
                    seen.append(state)
                await asyncio.sleep(0.05)

        watcher = asyncio.create_task(watch())
        try:
            launch = _launch(out)
            argv, env = launch["argv"], launch["env"]
            assert _has_skip(argv, skip), f"no skip flag under `skip`: {argv}"
            assert env["SHIFTLEAD_SESSION"] == sid and env["SHIFTLEAD_HOME"] == str(paths.home())
            got_id, _field = harness.session_id(argv, env)
            assert got_id and got_id == (await c.call("get", id=sid))["adapter_id"]
            # the layer the launch names names the suite's own hook (`stub_setup` put it first on `PATH`)
            assert shutil.which(shlex.split(launch["hook"])[0]) == str(tmp_path / "suite-bin" / "shiftlead-hook")

            # the brief typed at the first hook-confirmed idle plays the first turn
            assert await wait_for(lambda: "turn 1 done" in _events(out), timeout=30.0), _events(out)

            nonce = "n" + secrets.token_hex(6)
            env_ask = {k: v for k, v in os.environ.items() if k not in ("SHIFTLEAD_SESSION", "TMUX", "TMUX_PANE")}
            cp = await asyncio.to_thread(
                subprocess.run,
                ["ao", "--json", "msg", "--kind", "ask", sid, f"What is the nonce? Reply with it: {nonce}"],
                capture_output=True,
                text=True,
                env=env_ask,
                timeout=60,
            )
            assert cp.returncode == 0, cp.stderr
            ask = json.JSONDecoder().raw_decode(cp.stdout[cp.stdout.index("{") :])[0]["entry"]["id"]

            async def replied() -> bool:
                box = await c.call("inbox")
                return any(e.get("kind") == "reply" and nonce in (e.get("text") or "") for e in box["entries"])

            assert await wait_for(replied, timeout=60.0), (_events(out), seen)
            box = await c.call("inbox")
            (reply,) = [e for e in box["entries"] if e.get("kind") == "reply" and nonce in (e.get("text") or "")]
            assert reply.get("thread") == ask or reply.get("reply_to") == ask, reply
            assert await wait_for(lambda: "turn 2 done" in _events(out), timeout=20.0), _events(out)
            assert await wait_for(lambda: seen[-1:] == ["idle"], timeout=10.0), seen
        finally:
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher

        assert "needs-you" not in seen, seen
        start = seen.index("idle")
        turns = [x for x in seen[start:] if x in ("idle", "working")]
        assert turns[:5] == ["idle", "working", "idle", "working", "idle"], seen

        record = await _close(c, sid, out)
        assert record["state"] == "closed", record["state"]
        end = manifest(name)["life"]["end"]
        assert await wait_for(lambda: any(x.startswith("exit on signal") for x in _events(out)), timeout=10.0), (
            "\n".join(_events(out))
        )
        assert ("end played" in _events(out)) == (end is not None), _events(out)
