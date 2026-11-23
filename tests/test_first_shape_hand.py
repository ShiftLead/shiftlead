"""After the switch-over's marker the Add entry form, an `act` line's Doer and `ao td add` hand to a built-in tech
lead read from the records, never a first-shape team (design §4.9d *How each one runs*, §4.9e, TD-2076)."""

from __future__ import annotations

import pytest
from test_cli_teams import _td_world
from test_cli_teams import world as cli_world  # noqa: F401 — a fixture
from test_hand_route import roots  # noqa: F401 — a fixture

from shiftlead import cli, teams
from shiftlead.ui import app as ui
from shiftlead.ui.repo import entry_hand

pytestmark = pytest.mark.unit


def _seat(root, team: str = "web", **kw) -> dict:
    rec = {"id": f"ao-{team}-techlead", "name": "techlead", "team": team, "repo": str(root), "builtin": "techlead"}
    return rec | kw


def _mark(tmp_path) -> None:
    (tmp_path / "home" / "settings.yml").write_text("cut_over: 2026-12-01\n")


def test_servicing_reads_only_a_current_built_in_tech_lead_in_the_declared_order(tmp_path):
    root = str(tmp_path.resolve())
    records = [
        _seat(root, "b"),
        _seat(root, "a"),
        _seat(root, "old", superseded_by="x"),
        _seat(root, "first", builtin=None),
        _seat(root, "sweep", builtin="sweeper"),
        _seat(tmp_path / "other", "else"),
    ]
    assert [t["team"] for t in teams.builtin_servicing(records, root, ["b"])] == ["b", "a"]


def test_the_form_hands_to_the_built_in_seat_where_no_definition_is_read(tmp_path):
    (row,) = teams.builtin_servicing([_seat(tmp_path.resolve())], str(tmp_path.resolve()))
    got = entry_hand([row], {row["seat"]: {"state": "closed"}})
    assert got["to"] == "ao-web-techlead" and not got["why"]


def test_a_doer_resolves_to_a_built_in_seat_after_the_marker_and_a_definition_before(roots, tmp_path):  # noqa: F811
    org, _ = ui.org_here()
    board, other = str(roots["samscrape"].resolve()), roots["other"].resolve()
    records = [_seat(other, "web")]
    assert ui.doer_target(org, board, "team oth", "kmaster", None, records)["team"] == "oth"
    assert ui.doer_target(org, board, "team web", "kmaster", None, records) is None
    _mark(tmp_path)
    assert ui.doer_target(org, board, "team oth", "kmaster", None, records) is None  # the first shape's is not read
    got = ui.doer_target(org, board, "team web", "kmaster", None, records)
    assert got["team"] == "web" and got["root"] == str(other) and got["teams"][0]["seat"] == "ao-web-techlead"
    assert ui.doer_target(org, board, "other", "kmaster", None, records)["teams"][0]["team"] == "web"
    assert ui.doer_target(org, board, "other", "kmaster", None, []) is None


def test_td_add_sends_no_first_shape_teams_after_the_marker(cli_world, capsys, monkeypatch):  # noqa: F811
    tmp_path, _handed = _td_world(cli_world, monkeypatch)
    _mark(tmp_path)
    sent: list[dict] = []

    def fake(method, **params):
        assert method == "entry_add", method
        sent.append(params)
        return {"id": "m-1", "to": "ao-web-techlead", "repo": "shiftlead", "type": "debt"}

    monkeypatch.setattr(cli, "call_sync", fake)
    monkeypatch.delenv("SHIFTLEAD_SESSION", raising=False)
    assert cli.main(["td", "add", "--repo", "shiftlead", "a", "word"]) == 0
    assert len(sent) == 1 and "teams" not in sent[0]
    assert "handed to ao-web-techlead" in capsys.readouterr().out
