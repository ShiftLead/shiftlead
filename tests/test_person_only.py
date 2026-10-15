"""The person-only gate (design §4.8 *A person's own act is a named RPC, and the gate is one list*,
TD-317): `mail.PERSON_ONLY` and the RPCs that begin with `agent_common.person_only` are held to each
other in both directions, so a new person's act is one name added and cannot be forgotten."""

from __future__ import annotations

import ast
import asyncio
import inspect
import textwrap

import pytest

from sessionorc import mail
from sessionorc.agent import HostAgent
from sessionorc.agent_common import RpcError, person_only
from sessionorc.models import Session

# what each RPC's first statement may call to make the check: the check, or one of the two
# helpers that make it and keep what else each does (the entry lookup, *runs at the home*)
CHECKS = {"agent_common.person_only", "self._person_entry", "self._promote_person"}


def _first_call(fn) -> str | None:
    """The dotted name the RPC's first statement (past its docstring) calls, or None."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    body = tree.body[0].body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    st = body[0] if body else None
    value = st.value if isinstance(st, (ast.Expr, ast.Assign)) else None
    if isinstance(value, ast.Await):
        value = value.value
    return ast.unparse(value.func) if isinstance(value, ast.Call) else None


def _rpcs() -> dict[str, object]:
    return {
        name[len("rpc_") :]: fn
        for name, fn in inspect.getmembers(HostAgent, inspect.isfunction)
        if name.startswith("rpc_")
    }


def test_every_name_in_the_list_is_an_rpc_that_refuses_a_session_before_reading_its_parameters():
    """Every name is an `rpc_` method, and called by a session with every other parameter left
    `None` it is refused in the one shape — so nothing it reads is reached first. The agent is
    never constructed: a check that touched `self` before refusing would fail here too."""
    rpcs = _rpcs()
    assert len(mail.PERSON_ONLY) == 32
    assert set(rpcs) >= mail.PERSON_ONLY, sorted(mail.PERSON_ONLY - set(rpcs))
    bare = HostAgent.__new__(HostAgent)
    bare.sessions = {}  # the one thing the check reads: a caller this host does not hold is a session
    bare.remote = {}
    for name in sorted(mail.PERSON_ONLY):
        fn = rpcs[name]
        params = [p for p in inspect.signature(fn).parameters if p not in ("self", "caller")]
        with pytest.raises(RpcError) as e:
            call = getattr(bare, f"rpc_{name}")(**dict.fromkeys(params), caller="ao-repo-worker")
            if inspect.iscoroutine(call):
                asyncio.run(call)
        msg = str(e.value)
        assert msg.startswith("ao-repo-worker cannot "), (name, msg)
        assert ": a person's own act, refused to every session but the person's own shell (design §" in msg, (
            name,
            msg,
        )


def test_every_rpc_that_makes_the_check_is_in_the_list():
    """Read from the source: an RPC whose first statement is the check, or one of its two helpers,
    is in `PERSON_ONLY` — and every name in the list begins that way."""
    gated = {name for name, fn in _rpcs().items() if _first_call(fn) in CHECKS}
    assert gated == mail.PERSON_ONLY, {
        "checked, not listed": gated - mail.PERSON_ONLY,
        "listed, not checked": mail.PERSON_ONLY - gated,
    }


def test_the_lists_neighbours_keep_their_own_rules():
    """§4.8 *What is not in the list*: an RPC a person or a grant holder may call, the acting RPCs,
    and the RPCs with one person's branch keep their own checks."""
    assert not mail.PERSON_ONLY & {"host_files", "inbox", "msg", "decide", "wait"}
    assert not mail.PERSON_ONLY & mail.ACTING_RPCS


def test_a_person_passes_the_check():
    assert person_only(None, "restart a session", "§6 rule 2", {}) is None
    with pytest.raises(RpcError, match=r"^0 cannot restart a session: a person's own act"):
        person_only(0, "restart a session", "§6 rule 2", {})  # any caller present is a session (§4.8a)
    with pytest.raises(RpcError, match=r"^\['x'\] cannot restart"):
        person_only(["x"], "restart a session", "§6 rule 2", {"x": _shell("x")})  # never looked up


# ── the person's own shell is the person (§4.8, TD-580) ──────────────────────────────────────────


def _shell(sid: str, **over) -> Session:
    """A shell the person opened: Open shell here, + New ▾ Shell, `ao shell` outside a pane."""
    return Session(**{"id": sid, "name": sid, "kind": "interactive", "dir": "/", "adapter": "shell", **over})


NOT_THE_PERSONS = {
    "an agent session": {"adapter": "claude-code"},
    "an unattended shell": {"unattended": True},
    "a controlled shell": {"controllers": ["ao-repo-lead"]},
    "a role's shell": {"role": "grinder"},
    "a team's shell": {"team": "ao-grind"},
}


def test_person_shell_is_a_shell_interactive_with_no_role_team_or_controller():
    assert mail.person_shell(_shell("s"))
    assert not mail.person_shell(None)
    for what, over in NOT_THE_PERSONS.items():
        assert not mail.person_shell(_shell("s", **over)), what


def test_the_persons_shell_passes_every_act_in_the_list_and_nothing_else_does():
    """The one exception, held against the whole list: called from a person's shell each RPC gets
    past the check (whatever it fails on next, it is not the refusal); called from an agent session,
    an unattended, controlled, role's or team's shell, or a caller the host does not hold, each is
    refused in the new words."""
    rpcs = _rpcs()
    callers = {"ao-sh": _shell("ao-sh")} | {
        f"ao-{i}": _shell(f"ao-{i}", **o) for i, o in enumerate(NOT_THE_PERSONS.values())
    }
    bare = HostAgent.__new__(HostAgent)
    bare.sessions = callers
    bare.remote = {}
    for name in sorted(mail.PERSON_ONLY):
        params = [p for p in inspect.signature(rpcs[name]).parameters if p not in ("self", "caller")]

        def call(caller, name=name, params=params):
            out = getattr(bare, f"rpc_{name}")(**dict.fromkeys(params), caller=caller)
            if inspect.iscoroutine(out):
                asyncio.run(out)

        try:
            call("ao-sh")
        except Exception as e:  # noqa: BLE001 — the bare agent fails on whatever it reads next
            assert "a person's own act" not in str(e), (name, str(e))
        for sid in [*callers.keys() - {"ao-sh"}, "ao-gone"]:
            with pytest.raises(RpcError, match="refused to every session but the person's own shell") as e:
                call(sid)
            assert str(e.value).startswith(f"{sid} cannot "), (name, sid)


def test_the_right_is_the_records_state_at_the_call():
    """Never kept: a controller added, `ao mode` to unattended, or a role, and the next call is refused."""
    s = _shell("ao-sh")
    records = {"ao-sh": s}
    assert person_only("ao-sh", "change the settings", "§5", records) is None
    s.controllers = ["ao-repo-lead"]
    with pytest.raises(RpcError, match="but the person's own shell"):
        person_only("ao-sh", "change the settings", "§5", records)
    s.controllers, s.unattended = [], True
    with pytest.raises(RpcError):
        person_only("ao-sh", "change the settings", "§5", records)


def test_a_nodes_shell_is_read_from_the_homes_copy_of_its_record():
    """§4.4a: a node forwards a home edit (`promote`, the settings) with its caller as `id@node`; the
    home reads the record from the one graph, so a person's shell on a node passes there too."""
    home = HostAgent.__new__(HostAgent)
    home.sessions, home.remote = {}, {"laptop": {"ao-sh": _shell("ao-sh")}}
    assert person_only("ao-sh@laptop", "run promote", "§6 *Promote*", home._graph()) is None
    home.remote["laptop"]["ao-sh"].controllers = ["ao-lead"]
    with pytest.raises(RpcError, match="^ao-sh@laptop cannot run promote"):
        person_only("ao-sh@laptop", "run promote", "§6 *Promote*", home._graph())
