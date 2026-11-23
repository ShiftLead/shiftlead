"""`ao team show`'s read (design §4.9d *Controls and verbs*, TD-2060): the login rows from the host's reads, and the
reply the page draws from, for a team before the cut-over, on this host and on a node."""

from __future__ import annotations

from datetime import UTC, datetime

from sessionorc import teamstore as ts
from shiftlead import team_show

NOW = datetime(2026, 11, 23, 12, tzinfo=UTC)
FLOW = {
    "format": 3,
    "name": "build",
    "stages": [
        {"name": "Build", "does": "build", "model": "opus", "takes": "any", "work-pushed": "Check"},
        {"name": "Check", "does": "review", "model": "fable", "ship": "merge", "changes-wanted": "Build"},
    ],
    "audits": [{"name": "Docs", "model": "sonnet", "every": "6 hours", "brief": "docs"}],
}
HEAD = {"word": "running", "sessions": 2, "by": None}


def _doc(**team):
    entry = {"repo": "shiftlead", "host": "home", "flow": "build", "logins": ["claude:a", "claude:b"], **team}
    return {"cut_over": "2026-12-01", "teams": {"t": entry}}


def _row(models, state="signed_in", account="acct", **more):
    return {"state": state, "account": account, "models": list(models), **more}


def _read(state="signed_in"):
    account = {"key": "acct", "models": {"families": ["opus", "fable"]}}
    login = {"name": "a", "label": "Mine", "account": "acct", "state": state, "pin": None}
    return {"tools": [{"adapter": "claude", "accounts": [account], "logins": [login]}]}


def test_login_rows_carry_the_accounts_models_and_state():
    got = ts.login_rows(_read(), {}, now=NOW)
    assert got == {
        "claude:a": {
            "label": "Mine",
            "state": "signed_in",
            "account": "acct",
            "pin": None,
            "models": ["opus", "fable"],
            "at_reserve": False,
        }
    }


def test_the_teams_reserve_is_added_to_the_line():
    window = {"label": "week", "pct": 75, "reserve": 20, "resets": "2026-11-27T00:00:00Z"}
    gate = {"acct": {"windows": [window]}}
    assert ts.login_rows(_read(), gate, 0, NOW)["claude:a"]["at_reserve"] is False
    assert ts.login_rows(_read(), gate, 10, NOW)["claude:a"]["at_reserve"] is True


def test_a_window_the_gate_has_no_number_for_is_not_at_the_reserve():
    window = {"label": "week", "pct": 99, "reserve": 20, "resets": "2026-11-20T00:00:00Z"}
    assert ts.login_rows(_read(), {"acct": {"windows": [window]}}, 0, NOW)["claude:a"]["at_reserve"] is False


def test_a_metered_account_is_at_its_reserve_once_its_amount_is_spent():
    row = {"label": "month", "reserve": 50, "metered": True, "pct": 100, "resets": "2026-12-01T00:00:00Z"}
    assert ts.login_rows(_read(), {"acct": {"windows": [row]}}, 0, NOW)["claude:a"]["at_reserve"] is True


def test_a_teams_reserve_lowers_a_metered_line_and_a_past_reset_is_no_number():
    row = {"label": "month", "reserve": 50, "metered": True, "pct": 95, "resets": "2026-12-01T00:00:00Z"}
    assert ts.login_rows(_read(), {"acct": {"windows": [row]}}, 0, NOW)["claude:a"]["at_reserve"] is False
    assert ts.login_rows(_read(), {"acct": {"windows": [row]}}, 10, NOW)["claude:a"]["at_reserve"] is True
    ended = {**row, "pct": 100, "resets": "2026-11-20T00:00:00Z"}
    assert ts.login_rows(_read(), {"acct": {"windows": [ended]}}, 0, NOW)["claude:a"]["at_reserve"] is False


def test_a_mixed_account_is_read_by_the_rows_of_the_logins_billing():
    spent = {"label": "month", "reserve": 50, "metered": True, "pct": 100, "resets": "2026-12-01T00:00:00Z"}
    gate = {"acct": {"billing": "mixed", "windows": [spent]}}
    assert ts.login_rows(_read(), gate, 0, NOW)["claude:a"]["at_reserve"] is False
    read = _read()
    read["tools"][0]["logins"][0]["settings"] = {"billing": "metered"}
    assert ts.login_rows(read, gate, 0, NOW)["claude:a"]["at_reserve"] is True


def test_a_broken_copy_of_the_flow_costs_the_flow_and_never_the_read(tmp_path, monkeypatch):
    class Store:
        def __init__(self, root):
            pass

        def flow(self, team):
            return "a: ["

        def entries(self):
            return {}

    (tmp_path / "shiftlead").mkdir()
    monkeypatch.setattr(team_show, "StageStore", Store)
    monkeypatch.setattr(team_show.flow_save, "listing", lambda roots: {"flows": []})
    got = team_show.call(team="t", doc=_doc(), rows={}, head=HEAD, here="home", roots=[tmp_path / "shiftlead"])
    assert "could not be read" in got["unread"] and got["flow"]["read"] is False and got["cannot_run"] is None


def test_stages_that_are_not_a_list_read_as_none():
    got = team_show.view("t", _doc(), {}, HEAD, "home", {"stages": 5, "audits": 5}, ())
    assert got["flow"]["stages"] == [] and got["audits"] == []


def test_a_team_not_switched_says_after_the_switch_over():
    got = team_show.view("t", {"teams": {"t": {"until": "2026-12-01"}}}, {}, HEAD, "home", None, ())
    assert not got["switched"] and got["note"] == ts.BEFORE and got["flow"] is None and got["logins"] == []
    assert got["settings"] == {"until": "2026-12-01"} and got["head"]["sessions"] == 2


def test_the_show_names_each_stages_login_number_and_entries():
    rows = {"claude:a": _row(["opus"], state="limited"), "claude:b": _row(["opus", "fable", "sonnet"], account="b")}
    records = [
        {"id": "TD-2", "flow": "build", "stage": "check", "holder": None, "waits": "person"},
        {"id": "TD-1", "flow": "build", "stage": "build", "holder": "x"},
        {"id": "TD-3", "flow": "build", "stage": "build", "closed_at": "2026-11-01T00:00:00Z"},
        {"id": "TD-4", "flow": "other", "stage": "build"},
    ]
    doc = _doc(at_once={"build": 2, "gone": 1}, most=4, label="Grind")
    got = team_show.view("t", doc, rows, HEAD, "home", FLOW, records)
    build, check = got["flow"]["stages"]
    assert build["now"]["login"] == "claude:b" and build["at_once"] == 2
    assert [e["id"] for e in build["entries"]] == ["TD-1"]
    assert check["entries"][0]["waits"] == "person"
    assert got["flow"]["no_such_stage"] == {"gone": 1}
    assert got["audits"][0]["now"]["login"] == "claude:b"
    assert got["head"]["most"] == 4 and got["label"] == "Grind" and got["builtins"] == "default"
    assert [lg["why"] for lg in got["logins"]] == ["limited", None] and got["cannot_run"] is None


def test_a_model_no_login_offers_is_cannot_run_and_a_login_off_the_flow_says_so():
    rows = {"claude:a": _row(["opus"]), "claude:b": _row(["haiku"], account="b")}
    got = team_show.view("t", _doc(), rows, HEAD, "home", FLOW, ())
    assert got["cannot_run"] == "t cannot run build: no login in its list offers fable"
    assert [lg["runs_nothing"] for lg in got["logins"]] == [False, True]


def test_a_model_offered_only_by_unusable_logins_waits():
    rows = {"claude:a": _row(["opus", "fable", "sonnet"], state="limited"), "claude:b": _row([], account="b")}
    got = team_show.view("t", _doc(), rows, HEAD, "home", FLOW, ())
    assert got["cannot_run"] is None and got["flow"]["stages"][0]["now"]["state"] == "waits"


def test_a_team_on_a_node_makes_no_check_of_its_logins():
    got = team_show.view("t", _doc(host="node1"), {}, HEAD, "home", FLOW, ())
    assert got["cannot_run"] is None and got["note"] == team_show.NODE_NOTE
    assert got["logins"][0] == {"login": "claude:a", "tool": None, "name": "a", "state": "not_read"}
    assert got["flow"]["stages"][0]["now"]["state"] == "not_read"
