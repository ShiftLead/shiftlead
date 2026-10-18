"""TD-219 slices 3 and 4, design §4.9 *Add an entry to the ledger* and §4.5a **Add entry…** / **Open a
session**: one form from the Repo page and the team card, and the session way out of it — an
interactive session in a new worktree `entry-<n>`, with the role the team's `entries:` names for the
Type, at the prompt; its composer text comes back to the page and nothing is typed into the pane."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


def world(tmp_path, *, team: bool = True, entries: dict | None = None, seat: bool = True):
    home = tmp_path / "home"
    home.mkdir()
    repo = tmp_path / "samscrape"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    roster = tmp_path / "repos.txt"
    roster.write_text(f"{repo}\n")
    (home / "hosts.yml").write_text(f"local:\n  name: kmaster\n  local: true\n  repos_registry: {roster}\n")
    doc: dict = {"projects": {"sam": {"repos": {"samscrape": {"kmaster": str(repo)}}}}, "roles": {"designer": {}}}
    if team:
        t = {"repo": "samscrape", "manager": {"name": "manager-sam"}}
        if seat:
            t["techlead"] = {"name": "techlead-sam"}
        t["members"] = [{"role": "grinder"}]
        if entries:
            t["entries"] = entries
        doc["teams"] = {"sam-grind": t}
    (home / "org.yml").write_text(yaml.safe_dump(doc))
    return repo


def fake(fleet, taken=(), created=None, handed=None, checks=None):
    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            if method == "name_check":
                if checks and kw["name"] in checks:
                    return checks[kw["name"]]
                return {"verdict": "live" if kw["name"] in taken else "free"}
            if method == "entry_add":
                handed.append(kw)
                seat = kw["teams"][0]["seat"]
                return {"id": "m-1", "to": seat, "team": kw["teams"][0]["team"], "read_when": "fills this seat"}
            if method == "create":
                created.append(kw)
                return {"id": f"ao-samscrape-{kw['name']}", "name": kw["name"], "state": "starting"}
            return {"list": fleet, "repos": {}, "doing_log": {}, "usage": {}, "host": {"name": "kmaster"}}.get(
                method, {}
            )

    return Fake


def client(monkeypatch, tmp_path, Fake):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    from shiftlead.ui import app as ui

    monkeypatch.setattr(ui, "LocalClient", Fake)
    return TestClient(ui.create_app())


def test_open_a_session_starts_the_types_role_interactive_in_a_new_worktree_with_no_prompt(tmp_path, monkeypatch):
    repo = world(tmp_path, entries={"feature": "designer"})
    created: list[dict] = []
    manager = {"id": "ao-samscrape-manager-sam", "name": "manager-sam", "state": "idle", "team": "sam-grind"}
    c = client(monkeypatch, tmp_path, fake([manager], taken={"entry-1"}, created=created))
    # the line under the button, as the Type changes: the first free number, the role entries: names
    got = c.get("/api/entry/plan", params={"repo": "samscrape", "type": "feature"}).json()
    assert (got["team"], got["role"], got["name"]) == ("sam-grind", "designer", "entry-2")
    assert got["line"] == "an interactive designer session, entry-2, in a new worktree"
    assert c.get("/api/entry/plan", params={"repo": "samscrape", "type": "debt"}).json()["role"] == "techlead"
    # the press: interactive, in worktree entry-2, the role, the team's badge, its live manager, no prompt
    words = "The Inbox lists a board item only once it is due."
    r = c.post("/api/entry/session", json={"repo": "samscrape", "type": "feature", "words": words})
    assert r.status_code == 200, r.text
    (kw,) = created
    assert (kw["name"], kw["worktree"], kw["dir"], kw["repo"]) == (
        "entry-2",
        "entry-2",
        str(repo.resolve()),
        str(repo.resolve()),
    )
    assert kw["unattended"] is False and kw["prompt"] == "" and kw["role"] == "designer" and kw["team"] == "sam-grind"
    assert kw["controllers"] == ["ao-samscrape-manager-sam"]
    assert kw["context_bound"] is None  # a person's own session takes no default bound (§4.8, TD-249)
    # entry.md's lines, filled, are the session's start context (§4.3, TD-283 part 2): the create carries them
    assert kw["start_context"].startswith(
        "The person asked for a new entry in the ledger of samscrape: docs/technical_debt.md, with Type feature"
    )
    assert "Their first message is their words for it." in kw["start_context"] and words not in kw["start_context"]
    # …and the composer holds the person's words and nothing else
    assert r.json()["text"] == words and r.json()["id"] == "ao-samscrape-entry-2"


def test_a_repo_no_team_services_starts_plain_with_no_badge(tmp_path, monkeypatch):
    world(tmp_path, team=False)
    created: list[dict] = []
    c = client(monkeypatch, tmp_path, fake([], created=created))
    got = c.get("/api/entry/plan", params={"repo": "samscrape", "type": "debt"}).json()
    assert got["role"] == "plain" and got["team"] == "" and got["line"].endswith("no team services this repo")
    r = c.post("/api/entry/session", json={"repo": "samscrape", "type": "debt", "words": ""})
    (kw,) = created
    assert kw["role"] == "plain" and kw["team"] == "" and kw["controllers"] == [] and kw["unattended"] is False
    # with **What** empty the composer is empty, and the session is told the same
    from shiftlead import repoconfig

    assert r.json()["text"] == ""
    assert kw["start_context"] == repoconfig.entry_text("samscrape", "debt", "medium", "docs/technical_debt.md")


def test_a_bad_type_or_an_unknown_repo_is_refused_and_nothing_starts(tmp_path, monkeypatch):
    world(tmp_path)
    created: list[dict] = []
    c = client(monkeypatch, tmp_path, fake([], created=created))
    assert c.get("/api/entry/plan", params={"repo": "samscrape", "type": "bug"}).status_code == 400
    assert c.post("/api/entry/session", json={"repo": "nope", "type": "debt"}).status_code == 404
    assert created == []


def test_the_button_is_drawn_on_the_repo_page_and_the_form_in_every_page(tmp_path, monkeypatch):
    repo = world(tmp_path)
    root = str(repo)
    reading = {"name": "samscrape", "root": root, "ledger": {"path": "docs/technical_debt.md", "entries": []}}

    class Fake(fake([])):
        async def call(self, method, **kw):
            if method == "repos":
                return {root: reading}
            return await super().call(method, **kw)

    c = client(monkeypatch, tmp_path, Fake)
    html = c.get("/repo/samscrape").text
    assert 'data-addentry="samscrape"' in html and 'id="entrydlg"' in html
    assert 'id="entryhand"' in html and "Hand to the techlead" in html  # slice 4


def test_hand_to_the_techlead_sends_the_words_to_the_repos_first_seat_and_names_the_message(tmp_path, monkeypatch):
    """§4.5a Add entry form → **Hand to the techlead** (TD-219 slice 4): the plan says who takes it and
    when it is read — a seat nobody fills reads *fills this seat* — and the press hands `entry_add` the
    repo's checkout, the Type, the words and the servicing teams with their seats; the toast names
    the seat and the message and links its page."""
    repo = world(tmp_path)
    handed: list[dict] = []
    c = client(monkeypatch, tmp_path, fake([], handed=handed))
    hand = c.get("/api/entry/plan", params={"repo": "samscrape", "type": "debt"}).json()["hand"]
    assert (hand["team"], hand["name"], hand["why"]) == ("sam-grind", "techlead-sam", "")
    assert hand["to"].endswith("techlead-sam")
    assert hand["line"] == "fills this seat: a session starts on the next tick and reads it first"
    r = c.post("/api/entry/hand", json={"repo": "samscrape", "type": "feature", "words": "a board line is hidden"})
    assert r.status_code == 200, r.text
    (kw,) = handed
    assert (kw["repo"], kw["type"], kw["text"]) == (str(repo.resolve()), "feature", "a board line is hidden")
    assert kw["teams"] == [{"team": "sam-grind", "seat": hand["to"]}]
    got = r.json()
    assert got["text"] == "handed to techlead-sam · m-1" and got["href"] == "/inbox/m-1"


def test_a_live_seat_says_its_own_sentence(tmp_path, monkeypatch):
    """The sentence under the button is the seat's record's own when one is live (the agent's
    `refill`, an ask's sentence with no bound), not the one for a seat nobody fills."""
    world(tmp_path)
    from shiftlead import org as orgmod
    from shiftlead import teams

    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    org = orgmod.load(tmp_path / "home" / "org.yml")
    t = org.teams["sam-grind"]
    sid = teams.seat_id(org, t, "kmaster", "kmaster")
    live = {"id": sid, "name": "techlead-sam", "state": "working", "read_when": {"refill": "read when its turn ends"}}
    c = client(monkeypatch, tmp_path, fake([live]))
    assert c.get("/api/entry/plan", params={"repo": "samscrape", "type": "debt"}).json()["hand"]["line"] == (
        "read when its turn ends"
    )


@pytest.mark.parametrize(("team", "seat", "why"), [(True, False, "this team has no techlead seat"),
                                                   (False, True, "no team services this repo")])  # fmt: skip
def test_hand_is_disabled_with_its_reason(tmp_path, monkeypatch, team, seat, why):
    """With no techlead seat, or no team at all, the plan carries the reason the button is disabled,
    in the design's words, and names no seat to hand to."""
    world(tmp_path, team=team, seat=seat)
    c = client(monkeypatch, tmp_path, fake([]))
    hand = c.get("/api/entry/plan", params={"repo": "samscrape", "type": "debt"}).json()["hand"]
    assert hand["why"] == why and hand["to"] == ""


def test_a_seat_with_no_checkout_is_not_read_as_no_seat():
    """From the review of slice 4: `teams.seat_id` answers "" both for a team with no techlead and
    for a seat whose home has no checkout on its host, and `entry_add` refuses both — but the reason
    under the button says which, so the person knows whether to add a seat or a checkout."""
    from datetime import UTC, datetime

    from shiftlead.ui.repo import entry_hand

    now = datetime(2026, 9, 29, tzinfo=UTC)
    none = entry_hand([{"team": "t", "seat": "", "name": "", "techlead": ""}], {}, now)
    assert none["why"] == "this team has no techlead seat" and none["to"] == ""
    bare = entry_hand([{"team": "t", "seat": "", "name": "", "techlead": "techlead-sam"}], {}, now)
    assert bare["why"] == "techlead-sam: the techlead seat has no checkout on its host" and bare["to"] == ""


@pytest.mark.unit
def test_focus_draws_told_at_start_folded_escaped_and_only_on_a_record_holding_one(tmp_path, monkeypatch):
    """§4.5a Focus side panel **Told at start** (TD-283 part 2): a fold, closed, above Session, its
    heading the start context's length in lines, the text escaped with nothing in it a control — and
    no card at all on a record without one."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    from shiftlead.ui.app import templates, view

    base = {
        "id": "ao-x-entry-1", "name": "entry-1", "kind": "interactive", "adapter": "claude-code",
        "dir": str(tmp_path), "state": "idle", "since": "2026-10-04T07:00:00Z", "confidence": "hook",
        "pane": True, "tail": [], "created": "2026-10-04T07:00:00Z",
    }  # fmt: skip

    def page(**rec):
        v = view({**base, **rec})
        return templates.get_template("focus.html").render(
            s={**v, "grants_all": [], "ready": []}, host="h", active="Org", popped=False
        )

    told = "The person asked for a new entry.\n\n- **Read** <b>first</b>\n- [the site](https://example.com) `code`"
    html = page(start_context=told)
    card = re.search(r'<details class="card pad side" data-side="told" id="toldcard">(.*?)</details>', html, re.S)
    assert card, "drawn closed: no `open` on it"
    assert ">Told at start<" in card[1] and ">3 lines<" in card[1]  # blank lines are not counted
    # the closed markdown subset (bold, code), every other character escaped, and no link: nothing pressable
    assert "<strong>Read</strong>" in card[1] and "<code>code</code>" in card[1]
    assert "&lt;b&gt;first&lt;/b&gt;" in card[1] and "<a " not in card[1] and "<button" not in card[1]
    assert "[the site](https://example.com)" in card[1]
    assert html.index('data-side="told"') < html.index('data-side="session"')  # above Session
    assert 'data-side="told"' not in page() and 'data-side="told"' not in page(start_context=None)
    assert ">1 line<" in page(start_context="one")


def test_under_a_flow_a_feature_opens_its_design_stage(tmp_path, monkeypatch):
    """§4.9c item 4 (TD-309 slice 3b): with no `entries:` written, a team running `td` opens a
    feature with the design stage's role — the line under the button says designer — and a debt
    with the techlead."""
    world(tmp_path)
    doc = yaml.safe_load((tmp_path / "home" / "org.yml").read_text())
    doc["teams"]["sam-grind"]["flows"] = ["td"]
    (tmp_path / "home" / "org.yml").write_text(yaml.safe_dump(doc))
    c = client(monkeypatch, tmp_path, fake([]))
    got = c.get("/api/entry/plan", params={"repo": "samscrape", "type": "feature"}).json()
    assert got["role"] == "designer" and "an interactive designer session" in got["line"]
    assert c.get("/api/entry/plan", params={"repo": "samscrape", "type": "debt"}).json()["role"] == "techlead"


def test_each_way_out_hands_on_the_forms_draft_and_none_without_one(tmp_path, monkeypatch):
    """§4.5a *Add entry form: Attach / drop / paste* (TD-630, built by TD-633): where the form attached
    files, **Open a session** hands `draft` to the create and **Hand to the techlead** to `entry_add`,
    each of which claims the folder at the press (§4.4 *The Add entry form's draft*); a form that
    attached nothing hands none, and a draft that is not a string is refused before either is asked."""
    world(tmp_path)
    created: list[dict] = []
    handed: list[dict] = []
    c = client(monkeypatch, tmp_path, fake([], created=created, handed=handed))
    body = {"repo": "samscrape", "type": "debt", "words": "see /h/attachments/draft-0a1b2c3d/shot.png"}
    assert c.post("/api/entry/session", json={**body, "draft": "draft-0a1b2c3d"}).status_code == 200
    assert c.post("/api/entry/hand", json={**body, "draft": "draft-0a1b2c3d"}).status_code == 200
    assert created[0]["draft"] == "draft-0a1b2c3d" and handed[0]["draft"] == "draft-0a1b2c3d"
    assert c.post("/api/entry/session", json={**body, "draft": ""}).status_code == 200
    assert c.post("/api/entry/hand", json=body).status_code == 200
    assert "draft" not in created[1] and "draft" not in handed[1]
    r = c.post("/api/entry/hand", json={**body, "draft": 7})
    assert r.status_code == 400 and "draft is the token" in r.json()["detail"] and len(handed) == 2


def test_attach_is_refused_in_place_where_the_team_runs_on_a_node(tmp_path, monkeypatch):
    """§4.5a *Add entry form: Attach / drop / paste* (TD-630): the plan says why **Attach** refuses —
    a repo whose servicing team runs on a node, in the words a node session's composer gets — and
    nothing where the team runs here; the form draws Attach, its picker, its ✕ and the hint under **What**."""
    world(tmp_path)
    c = client(monkeypatch, tmp_path, fake([]))
    assert c.get("/api/entry/plan", params={"repo": "samscrape"}).json()["attach"] == ""
    org = tmp_path / "home" / "org.yml"
    doc = yaml.safe_load(org.read_text())
    doc["teams"]["sam-grind"]["host"] = "node1"
    org.write_text(yaml.safe_dump(doc))
    got = c.get("/api/entry/plan", params={"repo": "samscrape"}).json()
    assert got["attach"] == "sam-grind runs on node1: this call does not cross the link"
    from shiftlead.ui import app as ui

    html = (Path(ui.__file__).parent / "templates" / "base.html").read_text()
    form = html[html.index('<dialog id="entrydlg"') : html.index("</dialog>", html.index('<dialog id="entrydlg"'))]
    what = form.index('id="entrywhat"')
    assert what < form.index('id="entryattach"') < form.index('name="entrytype"')
    assert '<input type="file" id="entryattachfile" multiple hidden>' in form
    assert 'id="entryattachcancel"' in form and "drop a file on the box" in form


def test_the_forms_what_is_tall_and_a_hidden_warning_draws_nothing():
    """TD-668: **What** is the tall textarea (the mockup's 132 px, not `.input`'s 34), and a `.warn`
    carrying `hidden` is hidden — `.warn` sets `display`, which beats the UA's `[hidden]`, so the
    form's error note drew as an empty orange box."""
    from shiftlead.ui import app as ui

    root = Path(ui.__file__).parent
    html = (root / "templates" / "base.html").read_text()
    assert '<textarea class="input tall" id="entrywhat" rows="6">' in html
    assert '<p class="note warn" id="entryerr" hidden></p>' in html
    css = (root / "static" / "app.css").read_text()
    assert ".warn[hidden] { display: none; }" in css
    assert "#entrywhat.tall { height: 132px; }" in css


# -- the **Name** box (§4.5a *Add entry form: Name*, TD-675 designed, TD-677 built) -------------------------


def git(repo, *args):
    who = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]  # CI has no git identity
    subprocess.run(["git", "-C", str(repo), *who, *args], check=True, capture_output=True)


def test_a_free_typed_name_starts_the_session_its_worktree_and_its_branch_under_it(tmp_path, monkeypatch):
    world(tmp_path)
    created: list[dict] = []
    c = client(monkeypatch, tmp_path, fake([], created=created))
    # the box's prefill: the default, which the plan answers beside the name the press would take
    got = c.get("/api/entry/plan", params={"repo": "samscrape", "type": "debt"}).json()
    assert (got["name"], got["default"], got["name_why"]) == ("entry-1", "entry-1", "")
    got = c.get("/api/entry/plan", params={"repo": "samscrape", "type": "debt", "name": "inbox-counts"}).json()
    assert (got["name"], got["default"], got["name_why"]) == ("inbox-counts", "entry-1", "")
    assert got["line"] == "an interactive techlead session, inbox-counts, in a new worktree"
    r = c.post("/api/entry/session", json={"repo": "samscrape", "type": "debt", "words": "", "name": "inbox-counts"})
    assert r.status_code == 200, r.text
    (kw,) = created
    assert (kw["name"], kw["worktree"]) == ("inbox-counts", "inbox-counts")


def test_an_emptied_box_takes_the_default(tmp_path, monkeypatch):
    world(tmp_path)
    created: list[dict] = []
    c = client(monkeypatch, tmp_path, fake([], created=created))
    got = c.get("/api/entry/plan", params={"repo": "samscrape", "type": "debt", "name": ""}).json()
    assert (got["name"], got["name_why"]) == ("entry-1", "")
    assert c.post("/api/entry/session", json={"repo": "samscrape", "type": "debt", "name": ""}).status_code == 200
    assert created[0]["name"] == "entry-1"


SLUG_WHY = "lowercase letters and digits, with single - between them: the name is the session's, its worktree's"
SLUG_WHY += " and its branch's"  # §4.5a's words, written out rather than imported


@pytest.mark.parametrize(
    "name, why",
    [
        ("Entry-2", SLUG_WHY),
        ("my entry", SLUG_WHY),
        ("entry-", SLUG_WHY),
        ("a--b", SLUG_WHY),
        ("x" * 33, SLUG_WHY),
        ("held", "held is running — switch to it, or pick another name"),
        ("gone", "gone names an exited session — pick another name"),
        ("alarm", "alarm was suspended by a person"),
        ("tree", "a worktree named tree exists — pick another name"),
        ("twig", "a branch named twig exists — the session would start on it; pick another name"),
    ],
)
def test_a_name_that_is_not_free_is_refused_in_the_boxs_words_at_the_check_and_at_the_press(
    tmp_path, monkeypatch, name, why
):
    repo = world(tmp_path)
    git(repo, "commit", "-q", "--allow-empty", "-m", "root")
    git(repo, "branch", "twig")
    (repo / ".claude" / "worktrees" / "tree").mkdir(parents=True)
    checks = {
        "held": {"verdict": "live", "message": "held is running — switch to it, or pick another name"},
        "gone": {"verdict": "supersede", "message": "replaces the exited gone — run log kept"},
        "alarm": {"verdict": "suspended", "message": "alarm was suspended by a person at … — no session may take it"},
    }
    created: list[dict] = []
    c = client(monkeypatch, tmp_path, fake([], created=created, checks=checks))
    got = c.get("/api/entry/plan", params={"repo": "samscrape", "type": "debt", "name": name}).json()
    assert got["name_why"].startswith(why) and got["default"] == "entry-1"
    r = c.post("/api/entry/session", json={"repo": "samscrape", "type": "debt", "name": name})
    assert r.status_code == 409 and r.json()["detail"].startswith(why)
    assert created == []  # refused, never replaced by another name


def test_the_defaults_loop_skips_a_number_whose_branch_or_worktree_or_holder_is_there(tmp_path, monkeypatch):
    repo = world(tmp_path)
    git(repo, "commit", "-q", "--allow-empty", "-m", "root")
    git(repo, "branch", "entry-1")  # a leftover local branch: ensure_worktree would check it out
    (repo / ".claude" / "worktrees" / "entry-2").mkdir(parents=True)
    checks = {"entry-3": {"verdict": "supersede", "message": "replaces the exited entry-3 — run log kept"}}
    c = client(monkeypatch, tmp_path, fake([], checks=checks))
    got = c.get("/api/entry/plan", params={"repo": "samscrape", "type": "debt"}).json()
    assert (got["name"], got["default"]) == ("entry-4", "entry-4")


def test_the_form_draws_the_name_box_beside_open_a_session_and_sends_what_it_holds():
    """The template's box and the page's three rules for it: untouched it follows the default, a
    typed name rides on every read (so a changed Type keeps it), and an emptied one sends nothing."""
    from shiftlead.ui import app as ui

    root = Path(ui.__file__).parent
    html = (root / "templates" / "base.html").read_text()
    go = html.index('id="entrygo"')
    assert go < html.index('id="entryname" maxlength="32"') < html.index('id="entryline"')
    js = (root / "static" / "app.js").read_text()
    assert 'const typed = () => (named && nameBox.value.trim() ? nameBox.value : "");' in js
    assert "if (!named) nameBox.value = v.default" in js and 'nameBox.placeholder = v.default || "";' in js
    assert re.search(r"/api/entry/plan\?repo=.*\$\{q\}", js) and "name: typed() })" in js
    assert '$("#entrygo").disabled = !!v.name_why;' in js


def test_the_form_draws_priority_beside_type_with_medium_selected_and_both_ways_send_the_pick(tmp_path, monkeypatch):
    """§4.5a **Add entry…** (TD-851, built by TD-855): **Priority** — High · Medium · Low — beside Type, drawn
    as Type is with *Medium* selected and set again at each opening; **Hand to the techlead** carries the pick
    to `entry_add` as `entry.priority`, and **Open a session** names it in its start context."""
    from shiftlead import repoconfig
    from shiftlead.ui import app as ui

    root = Path(ui.__file__).parent
    html = (root / "templates" / "base.html").read_text()
    pick = html[html.index('aria-label="Priority"') : html.index("</div>", html.index('aria-label="Priority"'))]
    assert html.index('aria-label="Type"') < html.index('aria-label="Priority"') < html.index('id="entryhand"')
    assert re.findall(r'name="entrypriority" value="(\w+)"( checked)?', pick) == [
        ("high", ""),
        ("medium", " checked"),
        ("low", ""),
    ]
    js = (root / "static" / "app.js").read_text()
    assert 'dlg.querySelector("input[name=entrypriority][value=medium]").checked = true;' in js
    assert js.count("type: type(), priority: priority(),") == 2  # the hand and the session
    world(tmp_path)
    handed: list[dict] = []
    created: list[dict] = []
    c = client(monkeypatch, tmp_path, fake([], handed=handed, created=created))
    r = c.post("/api/entry/hand", json={"repo": "samscrape", "type": "debt", "priority": "low", "words": "w"})
    assert r.status_code == 200, r.text
    assert c.post("/api/entry/hand", json={"repo": "samscrape", "type": "debt", "words": "w"}).status_code == 200
    assert [kw["priority"] for kw in handed] == ["low", ""]  # absent: the host agent's *medium*
    r = c.post("/api/entry/session", json={"repo": "samscrape", "type": "debt", "priority": "High", "words": ""})
    assert r.status_code == 200, r.text
    (kw,) = created
    assert kw["start_context"] == repoconfig.entry_text("samscrape", "debt", "high", "docs/technical_debt.md")
    assert "with Type debt and Priority high" in kw["start_context"]
    bad = c.post("/api/entry/session", json={"repo": "samscrape", "type": "debt", "priority": "urgent"})
    assert bad.status_code == 400 and "not 'urgent'" in bad.json()["detail"] and len(created) == 1
