# ruff: noqa: E501 — the fixture rows read as one line each
"""TD-608 slice 2, design §4.5 screen 11 item 3 *Recently completed*, §4.5a *team card: Repo facet*,
§4.7 `ao repo`: the window's closed entries with the PR that closed each and who opened it, the
facet's *closed* block a link there with the titles on hover, and `ao repo`'s *completed this week*."""

from __future__ import annotations

import html as htmllib
import json
from datetime import UTC, datetime, timedelta

import pytest
from test_ui_repo_page import _iso, client, fake, reading, rec

pytestmark = pytest.mark.unit

NOW = datetime.now(UTC)


def closed(i: int, hours: float, pr: int | None = 900, **kw) -> dict:
    return {"id": f"TD-{i}", "title": f"closed {i}", "closed": _iso(NOW - timedelta(hours=hours)), "pr": pr,
            "author": "eye", "branch": "", "url": f"https://x/{pr}" if pr else "", **kw}  # fmt: skip


def section(html: str, w: str) -> str:
    sec = html[html.index('id="completed"') : html.index('id="waiting"')]
    return sec[sec.index(f'data-wv="{w}"') :].split('class="wv"')[0]


def test_recently_completed_lists_the_windows_closed_entries_with_their_pr_and_author(tmp_path, monkeypatch):
    root = str(tmp_path / "samscrape")
    r = reading(root)
    r["completed"] = [
        closed(401, 2, 1290, branch="td401"),  # a session's branch: its Focus
        closed(402, 30, 1291),  # the login: no record holds the branch
        closed(403, 50, None),  # a direct push: no PR
        closed(404, 24 * 10, 1293),  # this month, not this week
    ]
    fleet = [rec("tdgrind-1", root, git={"branch": "td401"})]
    html = client(monkeypatch, tmp_path, fake({root: r}, fleet)).get("/repo/samscrape?win=month").text
    # after Technical debt, before Waiting on you (§4.5 screen 11)
    assert html.index('id="debt"') < html.index('id="completed"') < html.index('id="waiting"')
    day, week, month = section(html, "day"), section(html, "week"), section(html, "month")
    assert "1 today" in day and "TD-401" in day and "TD-402" not in day
    assert "3 this week" in week and "TD-404" not in week and "4 this month" in month
    # newest first; the PR a link; the author a session's Focus, else the login; *no PR* names nobody
    assert week.index("TD-401") < week.index("TD-402") < week.index("TD-403")
    assert '<a class="mono" href="https://x/1290" target="_blank" rel="noopener">#1290</a>' in week
    assert '<a class="mono" href="/focus/tdgrind-1">tdgrind-1</a>' in week
    row402 = week[week.index("TD-402") :].split("</div>")[0]
    assert '<span class="mono meta">eye</span>' in row402
    row403 = week[week.index("TD-403") :].split("</div>")[0]
    assert '<span class="meta">no PR</span>' in row403 and "eye" not in row403
    # the page's one picker shows one window: day first, the others hidden until picked
    assert 'data-wv="day">' in html and 'data-wv="week" hidden' in html


def test_a_pr_the_month_reading_lacks_links_the_remote_and_an_empty_window_says_so(tmp_path, monkeypatch):
    root = str(tmp_path / "samscrape")
    r = reading(root)
    r["completed"] = [closed(410, 40, 1300, url="", author="")]
    html = client(monkeypatch, tmp_path, fake({root: r}, [])).get("/repo/samscrape?win=week").text
    assert 'href="https://github.com/eye/samscrape/pull/1300"' in section(html, "week")
    assert "nothing closed today" in section(html, "day")


def test_recently_completed_folds_past_eight_rows(tmp_path, monkeypatch):
    root = str(tmp_path / "samscrape")
    r = reading(root)
    r["completed"] = [closed(500 + n, 1 + n) for n in range(11)]
    c = client(monkeypatch, tmp_path, fake({root: r}, []))
    week = section(c.get("/repo/samscrape?win=week").text, "week")
    # the rows past the fold are not sent (§4.5 *Page loads*, TD-882): the button reads them on its press
    assert week.count('data-list="completed-week"') == 8 and "folded" not in week
    assert 'data-unfold="completed-week" data-unsent>+3 more</button>' in week
    week = section(c.get("/repo/samscrape?part=1&win=week&open=completed-week").text, "week")
    assert week.count('class="rrow folded" data-list="completed-week"') == 3
    assert 'data-unfold="completed-week">+3 more</button>' in week


def test_the_page_sends_the_window_picked_and_the_narrower_ones_alone(tmp_path, monkeypatch):
    """TD-882, §4.5 *Page loads* (*only what is shown*): at load the day's rows alone, a wider window's
    count still on its heading and its rows read by `part=1&win=`, which carries every narrower window too."""
    root = str(tmp_path / "samscrape")
    r = reading(root)
    r["completed"] = [closed(601, 2), closed(602, 30), closed(603, 24 * 10)]
    c = client(monkeypatch, tmp_path, fake({root: r}, []))
    html = c.get("/repo/samscrape").text
    assert 'id="completed" data-loaded="day"' in html
    day, week, month = section(html, "day"), section(html, "week"), section(html, "month")
    assert "TD-601" in day and "2 this week" in week and "3 this month" in month
    assert "TD-602" not in html and "TD-603" not in html
    assert "reading this week…" in week and "nothing closed" not in week
    part = c.get("/repo/samscrape?part=1&win=month").text
    assert 'data-loaded="month"' in part and "TD-601" in section(part, "day")
    assert "TD-602" in section(part, "week") and "TD-603" in section(part, "month")
    # an unknown window reads as the day
    assert 'data-loaded="day"' in c.get("/repo/samscrape?part=1&win=year").text


def test_the_facets_closed_block_links_to_recently_completed_with_the_titles_on_hover(tmp_path, monkeypatch):
    root = str(tmp_path / "samscrape")
    r = reading(root)
    r["ledger"]["windows"] = {w: {"opened": 1, "closed": 12} for w in ("day", "week", "month")}
    r["completed"] = [closed(600 + n, 1 + n) for n in range(12)]
    fleet = [rec("tdgrind-1", root)]
    html = client(monkeypatch, tmp_path, fake({root: r}, fleet)).get("/repo/samscrape").text
    tsum = html[html.index('class="rline') : html.index('id="prs"')]  # the facet is on the repo's line (TD-740)
    a = tsum[tsum.index('href="/repo/samscrape?win=week#completed"') :].split(">")[0]
    title = htmllib.unescape(a.split('title="')[1].split('"')[0]).split("\n")
    assert title[0] == "TD-600 closed 600" and len(title) == 11 and title[-1] == "… and 2 more"
    assert 'href="/repo/samscrape?win=day#completed"' in tsum and 'href="/repo/samscrape?win=month#completed"' in tsum


def test_ao_repo_says_how_many_closed_this_week_and_its_json_carries_completed(tmp_path, monkeypatch, capsys):
    from shiftlead import cli

    root = tmp_path / "r"
    root.mkdir()
    done = [closed(700, 3), closed(701, 24 * 3), closed(702, 24 * 9)]
    repos = {
        str(root): {"name": "r", "root": str(root), "prs": {"open": []}, "ledger": {"entries": []}, "completed": done}
    }
    monkeypatch.setattr(
        cli, "call_sync", lambda rpc, **kw: {"repos": repos, "list": [], "doing_log": {}, "queue": {}, "inbox": {}}[rpc]
    )
    monkeypatch.setattr(cli, "_main_checkout", lambda cwd: str(root.resolve()))
    assert cli.main(["repo"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[1] == "  completed this week: 2"  # under the first line
    assert cli.main(["--json", "repo"]) == 0
    (got,) = json.loads(capsys.readouterr().out)
    assert [c["id"] for c in got["completed"]] == ["TD-700", "TD-701", "TD-702"]
