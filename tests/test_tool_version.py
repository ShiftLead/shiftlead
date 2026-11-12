"""TD-1726 (TD-1650's first build), design §4.3 *An upgraded seat tool asks for the smoke*: a seat's launch reads its
tool's version through the adapter's optional `tool_version(env)` — `--version`'s first stdout line, bounded by
`VERSION_TIMEOUT`, only when it holds a digit — and writes it on the record as the node-owned `tool_version`; an
interactive or plain launch, a worker line's extra and an `argv` override read nothing, and a missing method or a
None writes none. The seat smoke reads through the same method itself and prints *version unknown* where it can't."""

from __future__ import annotations

import importlib.util
import os
import stat
import time
from pathlib import Path

import pytest

from sessionorc import adapters
from sessionorc.adapters import read_version
from sessionorc.client import LocalClient
from sessionorc.models import NODE_OWNED, Session, apply_node
from shiftlead.adapters.claude_code import ClaudeCodeAdapter
from shiftlead.adapters.gemini import GeminiAdapter

ROOT = Path(__file__).resolve().parent.parent


def _tool(bin_dir: Path, name: str, body: str) -> Path:
    """A fake tool on a PATH of its own: a shell script whose body answers `--version`."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    p = bin_dir / name
    p.write_text(f"#!/bin/sh\n{body}\n")
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return p


def _env(bin_dir: Path) -> dict[str, str]:
    return {"PATH": f"{bin_dir}{os.pathsep}/usr/bin:/bin", "HOME": str(bin_dir)}


# ---- the read ----


@pytest.mark.unit
@pytest.mark.parametrize(
    ("body", "want"),
    [
        ('echo "2.1.37 (Claude Code)"; echo "a second line"', "2.1.37 (Claude Code)"),
        ('echo "  0.66.0  "', "0.66.0"),
        ('echo "Welcome to the tool"', None),  # a banner is no version
        ('echo "1.0.0" >&2', None),  # stderr is never read
        ('echo "1.0.0"; exit 3', None),  # a non-zero exit
        ("true", None),  # no line at all
    ],
    ids=["version", "stripped", "banner", "stderr", "nonzero", "silent"],
)
def test_the_read_is_the_first_stdout_line_holding_a_digit_and_none_else(tmp_path, body, want):
    _tool(tmp_path / "bin", "claude", body)
    assert read_version("claude", _env(tmp_path / "bin")) == want


@pytest.mark.unit
def test_a_bare_name_the_envs_path_cannot_find_reads_none_and_a_hang_stops_at_the_bound(tmp_path, monkeypatch):
    assert read_version("claude", _env(tmp_path / "empty")) is None
    assert read_version(str(tmp_path / "no-such"), {}) is None
    monkeypatch.setattr(adapters, "VERSION_TIMEOUT", 0.5)
    _tool(tmp_path / "bin", "claude", "sleep 30; echo 1.0")
    t0 = time.monotonic()
    assert read_version("claude", _env(tmp_path / "bin")) is None
    assert time.monotonic() - t0 < 10


@pytest.mark.unit
def test_the_bound_is_ten_seconds_one_constant():
    assert adapters.VERSION_TIMEOUT == 10


@pytest.mark.unit
@pytest.mark.parametrize("make", [lambda: ClaudeCodeAdapter(binary="claude"), lambda: GeminiAdapter(binary="gemini")])
def test_claude_code_and_gemini_read_their_binary_in_the_env_given(tmp_path, make):
    ad = make()
    _tool(tmp_path / "bin", ad.binary, 'echo "9.8.7"')
    assert ad.tool_version(_env(tmp_path / "bin")) == "9.8.7"
    assert ad.tool_version(_env(tmp_path / "empty")) is None
    assert "tool_version" not in getattr(ad, "implements", frozenset()), "looked up with getattr, never declared"


# ---- the record ----


@pytest.mark.unit
def test_the_field_is_node_owned_and_a_nodes_report_carries_it_to_the_home():
    assert "tool_version" in NODE_OWNED
    home = Session(id="a", name="a", kind="interactive", adapter="claude-code", dir="/")
    assert Session.from_dict(home.to_dict()).tool_version is None, "no read, no field"
    assert apply_node(home, {**home.to_dict(), "tool_version": "2.1.37"}).tool_version == "2.1.37"
    assert Session.from_dict(home.to_dict()).tool_version == "2.1.37", "and it is kept"


@pytest.fixture
def versioned(hookstub, monkeypatch):
    """The stub adapter with a `tool_version` that records each env it was given and answers `answer[0]`."""
    seen: list[dict[str, str]] = []
    answer: list = ["3.4.5 (stub)"]

    def tool_version(env):
        seen.append(dict(env))
        if isinstance(answer[0], Exception):
            raise answer[0]
        return answer[0]

    monkeypatch.setattr(hookstub, "tool_version", tool_version, raising=False)
    return seen, answer


def _params(tmp_path: Path, name: str, **kw) -> dict:
    (tmp_path / name).mkdir(exist_ok=True)
    return {"name": name, "dir": str(tmp_path / name), "adapter": "hookstub", "unattended": True,
            "supervised": True, **kw}  # fmt: skip


async def test_a_seats_launch_writes_its_tools_version_read_once_in_the_launchs_env(agent, tmp_path, versioned):
    seen, _ = versioned
    async with LocalClient() as person:
        sid = (await person.call("create", **_params(tmp_path, "audit", seat={"trigger": "every", "after": "6h"})))[
            "id"
        ]
    assert agent.sessions[sid].tool_version == "3.4.5 (stub)"
    assert len(seen) == 1 and seen[0].get("PATH") == os.environ.get("PATH"), "the host agent's env, read once"


async def test_a_seats_extra_reads_and_a_worker_lines_extra_and_a_plain_launch_read_nothing(agent, tmp_path, versioned):
    seen, _ = versioned
    async with LocalClient() as person:
        extra = await person.call(
            "create", **_params(tmp_path, "audit-2", seat={"trigger": "every", "after": "6h"}, scale={"line": "audit"})
        )
        line = await person.call("create", **_params(tmp_path, "g-2", scale={"line": "g"}))
        plain = await person.call("create", **_params(tmp_path, "w", unattended=False, supervised=False))
    assert agent.sessions[extra["id"]].tool_version == "3.4.5 (stub)"
    assert agent.sessions[line["id"]].tool_version is None
    assert agent.sessions[plain["id"]].tool_version is None
    assert len(seen) == 1, "the seat's extra alone read"


async def test_an_argv_override_reads_nothing(agent, tmp_path, versioned):
    seen, _ = versioned
    async with LocalClient() as person:
        sid = (
            await person.call(
                "create", **_params(tmp_path, "audit", seat={"trigger": "every", "after": "6h"}, argv=["bash"])
            )
        )["id"]
    assert agent.sessions[sid].tool_version is None and seen == []


@pytest.mark.parametrize("got", [None, "", RuntimeError("the read broke")], ids=["none", "empty", "raised"])
async def test_a_read_that_says_nothing_writes_none_and_the_launch_goes_on(agent, tmp_path, versioned, got):
    _, answer = versioned
    answer[0] = got
    async with LocalClient() as person:
        sid = (await person.call("create", **_params(tmp_path, "audit", seat={"trigger": "every", "after": "6h"})))[
            "id"
        ]
    assert agent.sessions[sid].tool_version is None
    assert agent.sessions[sid].state not in ("exited", "closed")


async def test_an_adapter_without_the_method_writes_none(agent, tmp_path, hookstub):
    assert not hasattr(hookstub, "tool_version")
    async with LocalClient() as person:
        sid = (await person.call("create", **_params(tmp_path, "audit", seat={"trigger": "every", "after": "6h"})))[
            "id"
        ]
    assert agent.sessions[sid].tool_version is None


async def test_a_held_seat_reads_nothing_until_its_own_launch(agent, tmp_path, versioned):
    seen, _ = versioned
    params = _params(tmp_path, "audit", seat={"trigger": "every", "after": "6h"}, team="t")
    async with LocalClient() as person:
        held = (await person.call("create", **params, held=True))["id"]
        assert agent.sessions[held].tool_version is None and seen == [], "a held create makes no pane, reads nothing"
        sid = (await person.call("create", **params))["id"]  # its later start runs `create`, as the tick's replay does
    assert agent.sessions[sid].tool_version == "3.4.5 (stub)" and len(seen) == 1


# ---- the seat smoke ----


def _conformance():
    spec = importlib.util.spec_from_file_location("conformance_tool_version", ROOT / "scripts" / "conformance.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.unit
def test_the_smoke_reads_through_the_adapters_method_in_its_own_env(tmp_path, monkeypatch):
    cw = _conformance()
    ad = ClaudeCodeAdapter(binary="claude")
    _tool(tmp_path / "bin", "claude", 'echo "2.1.37 (Claude Code)"')
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}/usr/bin:/bin")
    assert cw.smoke_version(ad) == "2.1.37 (Claude Code)"
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert cw.smoke_version(ad) == "version unknown"
    assert cw.smoke_version(object()) == "version unknown", "an adapter without the method"
    seat_run = (ROOT / "scripts" / "seat_run.py").read_text()
    assert "def tool_version" not in seat_run, "seat_run's own read is gone: the method replaces it"
