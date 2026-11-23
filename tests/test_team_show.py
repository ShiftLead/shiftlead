"""`ao team show`'s read (design §4.9d *Controls and verbs*, TD-2060): the login rows from the host's reads, and the
reply the page draws from, for a team before the cut-over, on this host and on a node."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import yaml

from sessionorc import teamstore as ts
from sessionorc.agent_settings import SettingsMixin
from shiftlead import flow3, team_show

NOW = datetime(2026, 11, 23, 12, tzinfo=UTC)
_TWO_HOURS_AGO = "2026-11-23T10:00:00Z"
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


def _projected(row_windows, reading_windows, billing="subscription"):
    host = SimpleNamespace(_usage={}, _usage_acct={"acct": {"windows": reading_windows, "fetched": _TWO_HOURS_AGO}})
    accounts = {"acct": {"billing": billing, "profiles": ["a"], "windows": row_windows}}
    return SettingsMixin._projected(host, accounts, {}, NOW)["acct"]["windows"]


def test_a_stale_metered_reading_does_not_age_out_of_its_spent_amount():
    spent = {"label": "month", "reserve": 50, "metered": True, "pct": 100, "resets": "2026-12-01T00:00:00Z"}
    rows = _projected([spent], [{"label": "month", "pct": 100, "resets": "2026-12-01T00:00:00Z"}], "metered")
    assert rows == [spent]
    gate = {"acct": {"billing": "metered", "windows": rows}}
    assert ts.login_rows(_read(), gate, 0, NOW)["claude:a"]["at_reserve"] is True


def test_a_subscription_window_lays_nothing_on_a_metered_row_of_the_same_label():
    spent = {"label": "month", "reserve": 50, "metered": True, "pct": 100, "resets": "2026-12-01T00:00:00Z"}
    plan = {"label": "month", "reserve": 10, "pct": 20, "resets": "2026-12-01T00:00:00Z"}
    reading = [{"label": "month", "pct": 20, "resets": "2026-12-01T00:00:00Z"}]
    metered, subscription = _projected([spent, plan], reading, "mixed")
    assert metered == spent
    assert subscription["unknown"] == "rate"


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
        {"id": "TD-2", "team": "t", "flow": "build", "stage": "check", "holder": None, "waits": "person"},
        {"id": "TD-1", "team": "t", "flow": "build", "stage": "build", "holder": "x"},
        {"id": "TD-3", "team": "t", "flow": "build", "stage": "build", "closed_at": "2026-11-01T00:00:00Z"},
        {"id": "TD-4", "team": "other", "flow": "other", "stage": "build"},
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


def test_two_teams_of_one_repo_on_one_flow_each_list_only_their_own_entries():
    entry = {"repo": "shiftlead", "host": "home", "flow": "build", "logins": ["claude:a"]}
    doc = {"cut_over": "2026-12-01", "teams": {"t": dict(entry), "u": dict(entry)}}
    records = [
        {"id": "TD-1", "team": "t", "flow": "build", "stage": "build"},
        {"id": "TD-2", "team": "u", "flow": "build", "stage": "build"},
    ]
    for team, tid in (("t", "TD-1"), ("u", "TD-2")):
        build = team_show.view(team, doc, {}, HEAD, "home", FLOW, records)["flow"]["stages"][0]
        assert [e["id"] for e in build["entries"]] == [tid]


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


def test_a_login_on_the_account_of_an_unusable_login_above_it_is_passed_over():
    rows = {
        "claude:a": {"state": "signed_in", "account": "acct", "models": ["opus"], "at_reserve": True},
        "claude:b": {"state": "signed_in", "account": "acct", "models": ["opus"]},
        "claude:c": {"state": "signed_in", "account": "other", "models": ["opus"]},
    }
    order = list(rows)
    assert ts.reasons(order, rows) == {
        "claude:a": "at its reserve",
        "claude:b": "shares an account with an unusable login above it",
        "claude:c": None,
    }
    assert ts.pick(order, "opus", rows)["login"] == "claude:c"
    shown = team_show.view("t", _doc(logins=order), rows, HEAD, "home", FLOW, ())["logins"]
    assert [x["why"] for x in shown][1] == "shares an account with an unusable login above it"


def _keys(lines):
    return [(x["head"], x["stops"], x["end"]) for x in lines]


def test_the_route_map_draws_each_built_in_flow_by_the_rule():
    read = {n: yaml.safe_load((flow3.PACKAGE_DIR / n / "flow.yml").read_text())["stages"] for n in flow3.BUILTIN}
    assert _keys(flow3.route_lines(read["build"])) == [("Every entry", ["build"], "merged")]
    assert _keys(flow3.route_lines(read["build-review"])) == [("Every entry", ["build", "review"], "merged")]
    assert _keys(flow3.route_lines(read["design-wise"])) == [
        ("Entries that need a design first", ["design", "first-read", "second-read", "fact-check"], "merged"),
        ("Entries ready to build", ["build", "review", "protected-read"], "merged"),
    ]


def test_a_stage_on_no_line_a_loop_and_the_person_end_a_line_as_the_rule_says():
    stages = [
        {"name": "Build", "does": "build", "takes": "any", "work-pushed": "Check"},
        {"name": "Check", "does": "review", "ship": {"to": "person"}},
        {"name": "Spare", "does": "build", "work-pushed": "merge"},
        {"name": "Loop", "does": "build", "takes": "other", "work-pushed": "Back"},
        {"name": "Back", "does": "review", "ship": "Loop"},
    ]
    got = flow3.route_lines(stages)
    assert _keys(got) == [
        ("Every entry", ["build", "check"], "you"),
        ("Entries ready to build", ["loop", "back"], "back"),
        (flow3.ROUTE_OTHER, ["spare"], None),
    ]
    assert got[1]["back_to"] == "loop" and got[2]["other"] is True


def test_a_record_the_flow_cannot_place_is_drawn_as_such():
    records = [
        {"id": "TD-1", "team": "t", "stage": "build", "asked": {"at": _TWO_HOURS_AGO}, "waits": "person"},
        {"id": "TD-2", "team": "t", "stage": "gone", "waits": "person", "asked": {"at": _TWO_HOURS_AGO}},
        {"id": "TD-3", "team": "t", "stage": "gone", "holder": "x"},
        {"id": "TD-4", "team": "t", "stage": "gone", "closed_at": _TWO_HOURS_AGO},
    ]
    flow = team_show.view("t", _doc(), {}, HEAD, "home", FLOW, records)["flow"]
    assert flow["stages"][0]["entries"][0]["asked_at"] == _TWO_HOURS_AGO
    assert [e["id"] for e in flow["gone"]] == ["TD-2"] and [e["id"] for e in flow["unplaced"]] == ["TD-3"]
    unread = team_show.view("t", _doc(), {}, HEAD, "home", None, records)["flow"]
    assert unread["gone"] == [] and [e["id"] for e in unread["unplaced"]] == ["TD-1", "TD-2", "TD-3"]
