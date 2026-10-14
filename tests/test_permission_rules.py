"""The person's `permissions:` rules (design §4.9b *The director seat answers permission prompts for
the person*, TD-641): the settings reader, Claude Code's rule syntax, the always-the-person check,
the profile's `permission_prompts`, and the host agent answering at the hook."""

import asyncio
from pathlib import Path

import pytest
from conftest import wait_state

from sessionorc import paths, permits
from sessionorc import settings as settings_mod
from sessionorc.client import AgentError, LocalClient
from shiftlead import profiles
from shiftlead.adapters.claude_code import ClaudeCodeAdapter
from shiftlead.adapters.claude_code import rules as rules_mod

# -- the reader ---------------------------------------------------------------------------------


def test_the_reader_keeps_rules_and_names_what_is_malformed():
    doc = {
        "permissions": {
            "grinder": {"allow": ["Bash(pdm run test:*)", " Edit(src/**) ", "", 3], "deny": ["Bash(rm -rf:*)"]},
            "manager": "allow everything",
            "techlead": {"allow": "Bash(ls)", "always": ["x"]},
        }
    }
    rules, bad = settings_mod.permissions(doc)
    assert rules == {"grinder": {"allow": ["Bash(pdm run test:*)", "Edit(src/**)"], "deny": ["Bash(rm -rf:*)"]}}
    assert len(bad) == 5 and any("manager" in b for b in bad) and any("unknown key always" in b for b in bad)
    assert settings_mod.permissions({}) == ({}, [])
    assert settings_mod.permissions({"permissions": ["x"]})[1]


# -- the adapter's syntax -------------------------------------------------------------------------


def test_bash_rules_prefix_exact_and_compound(tmp_path):
    m = rules_mod.matches
    assert m("Bash(pdm run test:*)", "Bash", {"command": "pdm run test -q"})
    assert m("Bash(pdm run test:*)", "Bash", {"command": "pdm run test"})
    assert not m("Bash(pdm run test:*)", "Bash", {"command": "pdm run tests"})
    assert m("Bash(git status)", "Bash", {"command": "git status"})
    assert not m("Bash(git status)", "Bash", {"command": "git status -s"})
    assert m("Bash", "Bash", {"command": "anything"})
    assert not m("Bash(pdm run test:*)", "Edit", {"command": "pdm run test"})
    # an allow covers every part of a compound command, or none of it; a nested command never
    assert not m("Bash(pdm run test:*)", "Bash", {"command": "pdm run test && rm -rf /"})
    assert not m("Bash(echo:*)", "Bash", {"command": "echo $(rm -rf x)"})
    assert m("Bash(pdm run test:*)", "Bash", {"command": "pdm run test 2>&1"})
    # a deny matches when any part does
    assert m("Bash(rm -rf:*)", "Bash", {"command": "cd x && rm -rf y"}, deny=True)
    assert not m("Bash(rm -rf:*)", "Bash", {"command": "cd x && rm -rf y"})
    for dodge in ("sudo rm -rf y", "FOO=1 rm -rf y", "/bin/rm -rf y", "env A=b nohup rm -rf y"):
        assert m("Bash(rm -rf:*)", "Bash", {"command": dodge}, deny=True), dodge
        assert not m("Bash(rm -rf:*)", "Bash", {"command": dodge}), dodge


def test_path_web_and_mcp_rules(tmp_path):
    m = rules_mod.matches
    assert m("Edit(src/**)", "Edit", {"file_path": str(tmp_path / "src" / "a" / "b.py")}, cwd=tmp_path)
    assert not m("Edit(src/**)", "Edit", {"file_path": str(tmp_path / "docs" / "x.md")}, cwd=tmp_path)
    assert not m("Edit(src/**)", "Edit", {"file_path": "/etc/passwd"}, cwd=tmp_path)
    assert m("Read(*.md)", "Read", {"file_path": str(tmp_path / "docs" / "x.md")}, cwd=tmp_path)
    assert m("WebFetch(domain:github.com)", "WebFetch", {"url": "https://github.com/x"})
    assert not m("WebFetch(domain:github.com)", "WebFetch", {"url": "https://evilgithub.com/x"})
    assert not m("WebFetch(domain:github.com)", "WebFetch", {"url": "https://api.github.com/x"})  # the host exactly
    assert not m("WebFetch(domain:github.com)", "WebFetch", {"url": "https://evil.com\\@github.com/"})
    assert not m("WebFetch(domain:github.com)", "WebFetch", {"url": "https://u@github.com/"})
    assert not m("WebFetch(domain:github.com)", "WebFetch", {"url": "ftp://github.com/"})
    assert m("mcp__docs__*", "mcp__docs__read", {}) and not m("mcp__docs__*", "mcp__other__read", {})
    assert m("Edit(src/**)", "MultiEdit", {"file_path": "x"}, cwd=None) is False
    assert m("mcp__docs", "mcp__docs__read", {})
    assert not m("mcp__docs", "mcp__other__read", {})
    assert not m("Task(anything)", "Task", {"prompt": "anything"})  # a specifier it does not read: no match
    assert not m("AskUserQuestion", "AskUserQuestion", {})  # a question is never a rule's


def test_a_malformed_rule_is_named():
    assert rules_mod.problem("Bash(pdm run test:*)") is None
    assert rules_mod.problem("Bash") is None
    assert rules_mod.problem("Bash(") and rules_mod.problem("Bash()") and rules_mod.problem("rm -rf")
    assert rules_mod.problem("mcp__docs__*") is None and rules_mod.problem("Ba*sh")


# -- what always reaches the person ------------------------------------------------------------


def test_always_the_person(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    wt = repo / ".claude" / "worktrees" / "w"
    wt.mkdir(parents=True)

    def atp(*strings: str) -> str | None:
        return permits.always_the_person(list(strings), str(wt), str(repo))

    # the member's own
    assert atp("pdm run test 2>/dev/null") is None
    assert atp(f"cat {wt}/src/a.py", "cat src/a.py", "cd src && ls") is None
    assert atp("git log https://github.com/x/y") is None
    assert atp(f"ls {repo}/docs") is None  # the checkout is the member's too
    assert atp("for f in a b; do echo $f; done") is None
    # the home's, a unit, outside
    assert atp("cat ~/.shiftlead/settings.yml")
    assert atp("cat $HOME/.claude/settings.json") and atp("cat ${HOME}/.claude/x")
    assert atp(str(tmp_path / "home" / "x"))
    assert atp("systemctl --user restart shiftlead-agent") and atp("cat x.service")
    assert atp("cat /etc/hosts")
    assert atp("cat ../../../../elsewhere/x")
    # the review's holes: a climb mid-command, a bare home, a glued flag, a scheme, a variable
    assert atp("cd .. && cd .. && cd .. && cd .. && cat .claude/x")
    assert atp("cat $PWD/../../../../.claude/x")
    assert atp("cd ~ && cat .shiftlead/x") and atp("ls ~") and atp("cat ~root/x") and atp("cd")
    assert atp("curl -o/etc/x http://x") and atp("tar -xf/etc/x") and atp("echo x >/etc/x")
    assert atp("curl file:///etc/passwd")
    assert atp("cat $XDG_CONFIG_HOME/x")
    assert atp("echo hi>~/.claude/x") and atp("cat x>>/etc/y")
    assert atp("FOO=~/.claude cmd") and atp("dd if=/etc/x of=y")
    assert atp("bash -c 'cat ~/.claude/x'") and atp("eval 'cat /etc/x'")
    assert atp("cat ./.claude/hooks/x")
    assert atp("echo 'a b' > out.txt") is None
    # another member's worktree, the git directory, a permission setting
    (repo / ".claude" / "worktrees" / "other").mkdir()
    assert atp(f"cat {repo}/.claude/worktrees/other/x")
    assert atp(f"cat {repo}/.git/hooks/pre-push") and atp("cat .claude/settings.json")
    # a path that cannot be read is the person's, never a crash
    assert atp("cat /tmp/a\x00b")


def test_the_adapter_names_what_a_prompt_touches():
    ps = rules_mod.prompt_strings
    assert ps("Bash", {"command": "ls", "description": "list /etc"}) == ["ls"]
    # a file's content is never read as paths: `a / b` or a shebang holds nothing
    assert ps("Edit", {"file_path": "/w/a.py", "old_string": "x", "new_string": "y = a / b"}) == ["/w/a.py"]
    assert ps("Write", {"file_path": "/w/a.py", "content": "#!/usr/bin/env python"}) == ["/w/a.py"]
    assert ps("Glob", {"pattern": "/etc/**", "path": "/w"}) == ["/w", "/etc/**"]
    assert ps("WebFetch", {"url": "https://x"}) == []
    assert ps("Task", {"prompt": "x"}) is None


# -- the profile's permission_prompts --------------------------------------------------------------


def test_permission_prompts_ask_launches_without_the_skip_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "profiles.yml").write_text(
        "default: grind\nprofiles:\n"
        "  grind: {account: grind, config_dir: /tmp/cc-grind}\n"
        "  watched: {account: grind, config_dir: /tmp/cc-grind, permission_prompts: ask}\n"
        "  extra: {account: grind, config_dir: /tmp/cc-grind, permission_prompts: ask,\n"
        "          unattended_args: [--dangerously-skip-permissions, --verbose]}\n"
    )
    ad = ClaudeCodeAdapter(binary="claude")

    def argv(profile: str, unattended: bool = True) -> list[str]:
        return ad.launch(profile=profile, resume=None, prompt=None, unattended=unattended, cwd=tmp_path).argv

    assert "--dangerously-skip-permissions" in argv("grind")  # skip, the default
    assert "--dangerously-skip-permissions" not in argv("watched")
    assert "--dangerously-skip-permissions" not in argv("extra") and "--verbose" in argv("extra")
    assert "--dangerously-skip-permissions" not in argv("grind", unattended=False)
    (tmp_path / "home" / "profiles.yml").write_text("profiles:\n  p: {permission_prompts: sometimes}\n")
    with pytest.raises(ValueError, match="ask or skip"):
        profiles.load()


# -- the host agent at the hook ----------------------------------------------------------------------


class _RuleStub:
    """The hook-fed stub with a rule matcher: a rule matches when it is the tool's name, or
    `Tool(<the command>)` exactly."""

    name = "rulestub"
    state_source = "hook"

    def launch(self, *, profile, resume, prompt, unattended, cwd, name=""):
        from sessionorc.adapters import LaunchSpec

        return LaunchSpec(argv=["bash", "--norc"])

    def classify(self, pane, tail):
        return None

    def rule_matches(self, rule, tool, tool_input, *, cwd=None, deny=False):
        return rule == tool or rule == f"{tool}({(tool_input or {}).get('command', '')})"

    def rule_problem(self, rule):
        return None if rule.endswith(")") or rule.isalpha() else f"{rule!r} is no rule"


@pytest.fixture
def rulestub(monkeypatch):
    from sessionorc import adapters

    adapters.load_all()
    stub = _RuleStub()
    monkeypatch.setitem(adapters._REGISTRY, stub.name, stub)
    return stub


def _rules(text: str) -> None:
    (paths.home() / "settings.yml").write_text(text)


async def _hook(sid: str, tool: str | None, command: str, tu: str, wait: float = 5) -> dict | None:
    extra = {"tool": tool, "input": {"command": command}} if tool else {}
    async with LocalClient() as h:
        return await h.call(
            "hook",
            session=sid,
            kind="permission",
            text=f"{tool}: {command}",
            tool_use_id=tu,
            wait_seconds=wait,
            **extra,
        )


@pytest.mark.integration
async def test_a_rule_answers_an_unattended_prompt_and_tells_the_person(agent, rulestub, tmp_path):
    _rules(
        "permissions:\n  grinder:\n    allow: ['Bash(pdm run test)', 'Bash(rm -rf x)', 'Bash(cat ~/.shiftlead/x)']\n"
        "    deny: ['Bash(rm -rf x)', 'Bash(cat ~/.claude/y)', 'Bash(']\n"
    )
    async with LocalClient() as c:
        w = (await c.call("create", name="w", dir=str(tmp_path), adapter="rulestub", unattended=True, role="grinder"))[
            "id"
        ]
        assert await _hook(w, "Bash", "pdm run test", "tu1") == {
            "behavior": "allow",
            "reason": "rule: Bash(pdm run test)",
        }
        fyi = [e for e in agent.person_inbox if e.answered]
        assert len(fyi) == 1 and fyi[0].answered == {
            "question": "Bash: pdm run test",
            "asker": w,
            "answerer": "rules",
            "source": "settings.yml permissions: grinder allow Bash(pdm run test)",
        }
        assert (await c.call("get", id=w))["state"] != "needs-you"
        # an Overrule of a rule's answer is refused: the rule is the person's to change
        with pytest.raises(AgentError, match="settings.yml's permissions"):
            await c.call("msg", reply_to=fyi[0].id, kind="reply", text="no")
        # a deny wins over an allow
        assert await _hook(w, "Bash", "rm -rf x", "tu2") == {"behavior": "deny", "reason": "rule: Bash(rm -rf x)"}
        # a deny of a prompt that always reaches the person stands
        assert (await _hook(w, "Bash", "cat ~/.claude/y", "tu3"))["behavior"] == "deny"
        assert len([e for e in agent.person_inbox if e.answered]) == 3
        # an allow of one is not made: the prompt waits for the person
        task = asyncio.create_task(_hook(w, "Bash", "cat ~/.shiftlead/x", "tu4"))
        st = await wait_state(c, w, "needs-you")
        assert st["pending"]["tool_use_id"] == "tu4"
        await c.call("decide", id=w, tool_use_id="tu4", behavior="deny", reason="mine")
        assert await task == {"behavior": "deny", "reason": "mine"}
        # a question (no tool) is never matched
        task = asyncio.create_task(_hook(w, None, "pdm run test", "tu5"))
        await wait_state(c, w, "needs-you")
        await c.call("decide", id=w, tool_use_id="tu5", behavior="allow")
        await task
        # the settings read names the malformed rule and keeps the rest
        got = (await c.call("settings"))["permissions"]
        assert got["rules"]["grinder"]["deny"] == ["Bash(rm -rf x)", "Bash(cat ~/.claude/y)"]
        assert any("Bash(" in b for b in got["malformed"])
        assert len([e for e in agent.person_inbox if e.answered]) == 3


@pytest.mark.integration
async def test_no_rule_answers_an_interactive_prompt_or_another_role(agent, rulestub, tmp_path):
    _rules("permissions:\n  grinder: {allow: ['Bash'], deny: ['Bash(ls)']}\n")  # neither reaches them
    async with LocalClient() as c:
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        (tmp_path / "n").mkdir()
        mine = (await c.call("create", name="i", dir=str(tmp_path / "a"), adapter="rulestub", role="grinder"))["id"]
        other = (
            await c.call(
                "create", name="o", dir=str(tmp_path / "b"), adapter="rulestub", unattended=True, role="manager"
            )
        )["id"]
        for sid, tu in ((mine, "i1"), (other, "o1")):
            task = asyncio.create_task(_hook(sid, "Bash", "ls", tu))
            await wait_state(c, sid, "needs-you")
            await c.call("decide", id=sid, tool_use_id=tu, behavior="allow")
            assert await task == {"behavior": "allow", "reason": None}
        # no rules at all: everything as today
        _rules("")
        none = (
            await c.call(
                "create", name="n", dir=str(tmp_path / "n"), adapter="rulestub", unattended=True, role="grinder"
            )
        )["id"]
        task = asyncio.create_task(_hook(none, "Bash", "ls", "n1"))
        await wait_state(c, none, "needs-you")
        await c.call("decide", id=none, tool_use_id="n1", behavior="allow")
        await task
        assert not [e for e in agent.person_inbox if e.answered]


def test_the_host_reads_no_tool_name():
    """The core names no tool (design §4.3): the rule step reads `tool` and `input` as given."""
    src = (Path(permits.__file__).parent / "agent_hook.py").read_text()
    assert "Bash" not in src and "AskUserQuestion" not in src


@pytest.mark.integration
async def test_a_node_answers_by_rule_only_once_the_home_has_filed_the_fyi(agent, rulestub, tmp_path, monkeypatch):
    """The hook is the node's and the rules its replica of the home's, but the *Answered for you* FYI
    is mail, whose one writer is the home (§9 invariant 15): a node answers by rule only while its
    link is up, and only once the home has filed the FYI (`answered_by_rule`). With no link, or a
    filing refused, the prompt waits for the person; the node's own person inbox is never written."""
    from sessionorc import link

    _rules("permissions:\n  grinder: {allow: ['Bash'], deny: ['Bash(ls)']}\n")
    asked: list[dict] = []
    refuse = False

    class Mux:
        async def request(self, method, timeout=None, **params):
            if refuse:
                raise link.LinkError("answered_by_rule names no record of kmaster")
            asked.append({"method": method, **params})
            return {"filed": True}

        async def notify(self, method, **params):  # the node's own reports go the same road
            pass

    async with LocalClient() as c:
        w = (await c.call("create", name="w", dir=str(tmp_path), adapter="rulestub", unattended=True, role="grinder"))[
            "id"
        ]
        monkeypatch.setattr(agent, "mode", "node")
        monkeypatch.setattr(agent, "_home_mux", Mux())
        monkeypatch.setattr(agent, "_snapshot_sent", True)
        assert await _hook(w, "Bash", "pdm run test", "n1") == {"behavior": "allow", "reason": "rule: Bash"}
        assert await _hook(w, "Bash", "ls", "n2") == {"behavior": "deny", "reason": "rule: Bash(ls)"}
        assert asked == [
            {
                "method": "answered_by_rule",
                "id": w,
                "prompt": "Bash: pdm run test",
                "behavior": "allow",
                "rule": "Bash",
            },
            {"method": "answered_by_rule", "id": w, "prompt": "Bash: ls", "behavior": "deny", "rule": "Bash(ls)"},
        ]

        # a filing refused, a link not past its snapshot, a link that is down: the person answers
        refuse = True
        for tu, setup in (("n3", None), ("n4", ("_snapshot_sent", False)), ("n5", ("_home_mux", None))):
            if setup:
                monkeypatch.setattr(agent, *setup)
            task = asyncio.create_task(_hook(w, "Bash", "pdm run test", tu))
            st = await wait_state(c, w, "needs-you")
            assert st["pending"]["tool_use_id"] == tu
            monkeypatch.setattr(agent, "mode", "home")  # the person's answer, as the home relays it
            await c.call("decide", id=w, tool_use_id=tu, behavior="allow")
            assert await task == {"behavior": "allow", "reason": None}
            monkeypatch.setattr(agent, "mode", "node")
        monkeypatch.setattr(agent, "mode", "home")
        assert not [e for e in agent.person_inbox if e.answered]


async def test_the_home_files_a_nodes_answer_by_rule(agent):
    """At the home, `answered_by_rule` from a node files the *Answered for you* FYI as the home's own
    rule step does, the asker the node's record by its address; a record of another host, or no
    answer, is refused, so the node's prompt waits for the person."""
    from sessionorc import link
    from sessionorc.models import Session

    rec = Session(
        id="ao-x-w", name="w", kind="worker", adapter="hookstub", dir="/tmp/x", host="laptop", role="grinder"
    ).to_dict()
    agent._take_records("laptop", [rec], whole=True)
    params = {"id": "ao-x-w", "prompt": "Bash: pdm run test", "behavior": "allow", "rule": "Bash(pdm run test)"}
    assert await agent._take_answered_by_rule("laptop", params) == {"filed": True}
    fyi = [e for e in agent.person_inbox if e.answered]
    assert len(fyi) == 1 and fyi[0].answered == {
        "question": "Bash: pdm run test",
        "asker": "ao-x-w@laptop",
        "answerer": "rules",
        "source": "settings.yml permissions: grinder allow Bash(pdm run test)",
    }
    for bad in ({**params, "id": "ao-x-nope"}, {**params, "behavior": "maybe"}, {**params, "rule": ""}):
        with pytest.raises(link.LinkError):
            await agent._take_answered_by_rule("laptop", bad)
    with pytest.raises(link.LinkError):
        await agent._take_answered_by_rule("desk", params)
    assert len([e for e in agent.person_inbox if e.answered]) == 1
