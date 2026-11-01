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

# what each RPC's first statement may call to make the check: the check, or one of the helpers
# that make it and keep what else each does (the entry lookup, *runs at the home*, and `entry_add`'s
# session call for another repo, TD-995)
CHECKS = {"agent_common.person_only", "self._person_entry", "self._promote_person", "self._entry_session"}

# the refusal's words: today's for every name, and for `mail.PERSON_SESSION`'s the carve-out's (TD-1117)
OLD = ": a person's own act, refused to every session but the person's own shell (design §"
NEW = OLD.replace(" (design", " and a session the person started by hand (design")
# and `thread`'s, which passes an own end whatever its controllers (§4.8 *`thread` passes an own end*, TD-1066)
THREAD = OLD.replace(" (design", " and an own end of the person's (design")

# what the bare call supplies beyond `None`: a road, without which `ledger_decide` sets no `session_ok`
SUPPLY = {"ledger_decide": {"road": "done"}}


def _refusal(name: str) -> str:
    return NEW if name in mail.PERSON_SESSION else THREAD if name == "thread" else OLD


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
    assert len(mail.PERSON_ONLY) == 33
    assert set(rpcs) >= mail.PERSON_ONLY, sorted(mail.PERSON_ONLY - set(rpcs))
    bare = HostAgent.__new__(HostAgent)
    bare.sessions = {}  # the one thing the check reads: a caller this host does not hold is a session
    bare.remote = {}
    for name in sorted(mail.PERSON_ONLY):
        fn = rpcs[name]
        params = [p for p in inspect.signature(fn).parameters if p not in ("self", "caller")]
        with pytest.raises(RpcError) as e:
            call = getattr(bare, f"rpc_{name}")(**dict.fromkeys(params) | SUPPLY.get(name, {}), caller="ao-repo-worker")
            if inspect.iscoroutine(call):
                asyncio.run(call)
        msg = str(e.value)
        assert msg.startswith("ao-repo-worker cannot "), (name, msg)
        assert _refusal(name) in msg, (name, msg)


def test_the_person_session_subset_is_in_the_list_and_its_rpcs_alone_set_session_ok():
    """§4.8 *A person's session passes one of them* (TD-1117, TD-1297): the subset is one name of the list,
    and the check passes `session_ok` in exactly that RPC's first statement — read from the source."""
    assert {"ledger_decide"} == mail.PERSON_SESSION and mail.PERSON_SESSION <= mail.PERSON_ONLY
    rpcs = _rpcs()
    for name in sorted(mail.PERSON_ONLY):
        src = textwrap.dedent(inspect.getsource(rpcs[name]))
        assert ("session_ok=" in src) == (name in mail.PERSON_SESSION), name
        assert ("own_end_ok=" in src) == (name == "thread"), name


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
    "a team's shell with a role": {"team": "ao-grind", "role": "grinder"},
    "a team's shell with a controller": {"team": "ao-grind", "controllers": ["ao-repo-lead"]},
}

# of those, the person's sessions (`mail.person_session`, TD-1117): started by hand, interactive, no
# controller and no seat, a role not ending it — they pass `PERSON_SESSION`'s two names
PERSONS_SESSIONS = {"an agent session", "a role's shell", "a team's shell with a role"}

# an own end with a controller (§4.8 *`thread` passes an own end*, TD-1066): the person's session started
# from a Queue card, the live manager its controller — `by_person` written by the create is what tells it
# from the controlled shells above, which carry no such field; it passes `thread` alone
OWN_ENDS = {
    "a Queue-started session": {"adapter": "claude-code", "controllers": ["ao-repo-manager"], "by_person": True},
}

# and sessions refused every name: an unattended agent, and an interactive one holding a seat
NEVER = {
    "an unattended agent session": {"adapter": "claude-code", "unattended": True},
    "a seat's interactive session": {"adapter": "claude-code", "seat": {"trigger": "ask"}},
}


def test_person_shell_is_a_shell_interactive_with_no_role_or_controller():
    assert mail.person_shell(_shell("s"))
    # a team badge does not end it (TD-821): Open shell here on a team member gives it the member's
    assert mail.person_shell(_shell("s", team="ao-grind", project="shiftlead"))
    assert not mail.person_shell(None)
    for what, over in NOT_THE_PERSONS.items():
        assert not mail.person_shell(_shell("s", **over)), what


def test_the_persons_shell_passes_every_act_in_the_list_and_nothing_else_does():
    """The one exception, held against the whole list: called from a person's shell each RPC gets
    past the check (whatever it fails on next, it is not the refusal); called from an unattended,
    controlled or seat-holding session, or a caller the host does not hold, each is refused in its
    words. The third class (TD-1117): a person's session — an interactive agent session, a role's shell,
    with no controller — passes each name in `PERSON_SESSION` and is refused every other name. And `thread`
    (TD-1066) passes every own end, a Queue-started session with the manager its controller among them, while
    the controlled shells written before `by_person` stay refused."""
    rpcs = _rpcs()
    shells = {"ao-sh": _shell("ao-sh"), "ao-tsh": _shell("ao-tsh", team="ao-grind")}
    others = {
        f"ao-{i}": (what, _shell(f"ao-{i}", **o))
        for i, (what, o) in enumerate((NOT_THE_PERSONS | OWN_ENDS | NEVER).items())
    }
    sessions = {sid for sid, (what, _) in others.items() if what in PERSONS_SESSIONS}
    assert len(sessions) == len(PERSONS_SESSIONS)
    own_ends = sessions | {sid for sid, (what, _) in others.items() if what in OWN_ENDS}
    bare = HostAgent.__new__(HostAgent)
    bare.sessions = shells | {sid: r for sid, (_, r) in others.items()}
    bare.remote = {}
    for name in sorted(mail.PERSON_ONLY):
        params = [p for p in inspect.signature(rpcs[name]).parameters if p not in ("self", "caller")]

        def call(caller, name=name, params=params):
            out = getattr(bare, f"rpc_{name}")(**dict.fromkeys(params) | SUPPLY.get(name, {}), caller=caller)
            if inspect.iscoroutine(out):
                asyncio.run(out)

        passing = {*shells, *(sessions if name in mail.PERSON_SESSION else ()), *(own_ends if name == "thread" else ())}
        for own in sorted(passing):
            try:
                call(own)
            except Exception as e:  # noqa: BLE001 — the bare agent fails on whatever it reads next
                assert "a person's own act" not in str(e), (name, own, str(e))
        for sid in [*sorted(others.keys() - passing), "ao-gone"]:
            with pytest.raises(RpcError) as e:
                call(sid)
            assert str(e.value).startswith(f"{sid} cannot ") and _refusal(name) in str(e.value), (name, sid)


def test_a_person_session_answers_no_ledger_entry_without_a_road():
    """`ledger_decide` with no road is the answer to a question put to the person (§4.8): a person's
    session is refused it, and a non-string road is coerced inside the check, refused and never raised."""
    bare = HostAgent.__new__(HostAgent)
    bare.sessions = {"ao-me": _shell("ao-me", adapter="claude-code")}
    bare.remote = {}
    for road in ("", None, 0):
        with pytest.raises(RpcError, match=r"^ao-me cannot answer a ledger entry: .* own shell \(design"):
            asyncio.run(bare.rpc_ledger_decide(repo="r", id="TD-1", road=road, caller="ao-me"))
    bare._repos = {}
    with pytest.raises(RpcError, match="r is not a repo this home reads"):  # past the check: a road it reads
        asyncio.run(bare.rpc_ledger_decide(repo="r", id="TD-1", road=5, caller="ao-me"))


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
