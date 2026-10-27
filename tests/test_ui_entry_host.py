"""TD-1092, design §4.9 *Add an entry to the ledger* item 2 (*It runs on the team's host*) and §4.5a
*Add entry form: Open a session* / *Name*: where `place:` or a team's `host:` puts the repo's team on
another host, **Open a session** starts there — the team's checkout on that host, every name test read
there (the routed name check, `host_worktrees` once per plan, the branch test the home's own for a
container node and `host_branch` on a machine node), a machine node's role, reader and ledger read
through `host_files` — and a host that does not answer, or a team with no checkout there, disables the
session way with its reason while **Hand to the techlead** still answers."""

from __future__ import annotations

import subprocess

import pytest
import yaml
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit

NODE_DIR = "/srv/node/samscrape"
NODE_FILES = {
    ".shiftlead.yml": "ledger: docs/node-ledger.md\n",
}


def world(tmp_path, *, container=False, node_path=True, team_extra=None, repo_team=False):
    """A home `kmaster` registering `samscrape`, and its team `sam-grind` on `node1` — a container
    node (its checkout the home's own directory) or a machine node (`/srv/node/samscrape`)."""
    home = tmp_path / "home"
    home.mkdir()
    repo = tmp_path / "samscrape"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    roster = tmp_path / "repos.txt"
    roster.write_text(f"{repo}\n")
    node = f"    container: {{devcontainer: {repo}}}\n" if container else "    {}\n"
    (home / "hosts.yml").write_text(
        f"local:\n  name: kmaster\n  local: true\n  repos_registry: {roster}\nnodes:\n  node1:\n{node}"
    )
    there = str(repo) if container else NODE_DIR
    paths = {"kmaster": str(repo), **({"node1": there} if node_path else {})}
    doc: dict = {"projects": {"sam": {"repos": {"samscrape": paths}}}}
    team = {"repo": "samscrape", "manager": {"name": "manager-sam"}, "techlead": {"name": "techlead-sam"}}
    team["members"] = [{"role": "grinder"}]
    team.update(team_extra or {})
    if repo_team:  # the repo's own definition, which the org file's `place:` lands on node1
        mine = {k: v for k, v in team.items() if k != "repo"}  # a repo's team works its own repo, unsaid
        (repo / ".shiftlead.yml").write_text(yaml.safe_dump({"teams": {"sam-grind": mine}}))
        doc["place"] = {"sam-grind": "node1"}
    else:
        doc["teams"] = {"sam-grind": {**team, "host": "node1"}}
    (home / "org.yml").write_text(yaml.safe_dump(doc))
    return repo


def fake(*, calls, created=None, handed=None, held=(), worktrees=(), branches=(), silent=(), branch_unknown=False):
    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            from sessionorc.client import AgentError

            calls.append((method, kw))
            if kw.get("host") == "node1" and method in silent:
                raise AgentError("node1 did not answer: the link dropped")
            if method == "name_check":
                if kw["name"] in held:
                    return {"verdict": "suspended", "message": f"{kw['name']} was suspended by a person"}
                return {"verdict": "free"}
            if method == "host_worktrees":
                return {"host": "node1", "repo": kw["repo"], "worktrees": [
                    {"name": w, "path": f"{kw['repo']}/.claude/worktrees/{w}", "occupied": True} for w in worktrees
                ]}  # fmt: skip
            if method == "host_branch":
                exists = None if branch_unknown else kw["name"] in branches
                return {"host": "node1", "dir": kw["dir"], "name": kw["name"], "exists": exists}
            if method == "host_dir":
                return {"host": "node1", "dir": kw["dir"], "exists": True, "root": NODE_DIR}
            if method == "host_files":
                assert kw["dir"] == NODE_DIR
                return {"host": "node1", "dir": kw["dir"], "files": {p: NODE_FILES.get(p) for p in kw["paths"]}}
            if method == "entry_add":
                handed.append(kw)
                return {"id": "m-1", "to": kw["teams"][0]["seat"], "read_when": "fills this seat"}
            if method == "create":
                created.append(kw)
                return {"id": f"ao-samscrape-{kw['name']}@node1", "name": kw["name"], "state": "starting"}
            return {"list": [], "repos": {}, "doing_log": {}, "usage": {}, "host": {"name": "kmaster"}}.get(method, {})

    return Fake


def client(monkeypatch, tmp_path, Fake):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    from shiftlead.ui import app as ui

    monkeypatch.setattr(ui, "LocalClient", Fake)
    return TestClient(ui.create_app())


def plan(c, **q):
    return c.get("/api/entry/plan", params={"repo": "samscrape", "type": "debt", **q}).json()


def test_a_container_nodes_team_plans_and_creates_on_its_host(tmp_path, monkeypatch):
    """(a) a container node: the host, the org file's path for it, the line *…on node1*, and the press
    routed there; the name tests routed, the branch the home's own read of the shared directory."""
    repo = world(tmp_path, container=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                    "--allow-empty", "-m", "r"], check=True)  # fmt: skip
    subprocess.run(["git", "-C", str(repo), "branch", "entry-1"], check=True)
    calls, created = [], []
    c = client(monkeypatch, tmp_path, fake(calls=calls, created=created))
    got = plan(c)
    assert (got["host"], got["dir"], got["why"]) == ("node1", str(repo), "")
    assert got["default"] == "entry-2", "the home's own branch test skips entry-1 in the shared checkout"
    assert got["line"] == "an interactive techlead session, entry-2, in a new worktree on node1"
    assert not any(m == "host_branch" for m, _ in calls), "a container node's branch is read here"
    checks = [kw for m, kw in calls if m == "name_check"]
    assert checks and all(kw["host"] == "node1" and kw["repo"] == str(repo) for kw in checks)
    r = c.post("/api/entry/session", json={"repo": "samscrape", "type": "debt", "words": "w"})
    assert r.status_code == 200, r.text
    (kw,) = created
    assert (kw["host"], kw["dir"], kw["repo"], kw["worktree"]) == ("node1", str(repo), str(repo), "entry-2")
    assert kw["team"] == "sam-grind" and kw["project"] == "sam"


def test_a_machine_nodes_team_reads_its_role_reader_and_ledger_there(tmp_path, monkeypatch):
    """(a) a machine node's org-file path; (c) its ledger and role read through `host_files`, and an
    existing branch there refused in the Name row's words, the plan and the press alike."""
    world(tmp_path, team_extra={"entries": {"debt": "designer"}})
    calls, created, readers = [], [], []
    from shiftlead.ui import app as ui

    real = ui.team_reader

    def reader(team, directory, cfg=None, role=None):
        readers.append(cfg)
        return real(team, directory, cfg, role)

    monkeypatch.setattr(ui, "team_reader", reader)
    c = client(monkeypatch, tmp_path, fake(calls=calls, created=created, branches={"entry-1", "twig"}))
    got = plan(c)
    want = ("node1", NODE_DIR, "docs/node-ledger.md", "designer")
    assert (got["host"], got["dir"], got["ledger"], got["role"]) == want
    assert got["default"] == "entry-2", "entry-1's branch on the node is skipped"
    assert [kw["name"] for m, kw in calls if m == "host_branch"] == ["entry-1", "entry-2"]
    why = "a branch named twig exists — the session would start on it; pick another name"
    assert plan(c, name="twig")["name_why"] == why
    r = c.post("/api/entry/session", json={"repo": "samscrape", "type": "debt", "name": "twig"})
    assert (r.status_code, r.json()["detail"]) == (409, why)
    r = c.post("/api/entry/session", json={"repo": "samscrape", "type": "debt", "words": ""})
    assert r.status_code == 200, r.text
    (kw,) = created
    assert (kw["host"], kw["dir"], kw["role"], kw["ledger"]) == ("node1", NODE_DIR, "designer", "docs/node-ledger.md")
    assert "docs/node-ledger.md" in kw["start_context"]
    assert any(m == "host_files" for m, _ in calls), "the ledger was read on the node"
    (cfg,) = readers
    assert cfg is not None and cfg.ledger == "docs/node-ledger.md", "the reader is given the node's config"


def test_a_repos_team_placed_on_a_node_takes_the_path_that_hosts_registry_gives(tmp_path, monkeypatch):
    """(a) a repo's team `place:` lands on node1 with no org-file path: the node's registry gives it."""
    world(tmp_path, node_path=False, repo_team=True)
    from shiftlead.ui import common

    monkeypatch.setattr(common, "repos_of", lambda host: [NODE_DIR] if host == "node1" else [])
    calls = []
    got = plan(client(monkeypatch, tmp_path, fake(calls=calls)))
    assert (got["host"], got["dir"], got["team"], got["why"]) == ("node1", NODE_DIR, "sam-grind", "")


def test_a_held_name_on_the_node_is_refused_in_the_name_checks_words(tmp_path, monkeypatch):
    """(b) a typed `entry-1` held by a suspended session in the node's checkout: the routed check's words."""
    world(tmp_path)
    calls = []
    got = plan(client(monkeypatch, tmp_path, fake(calls=calls, held={"entry-1"})), name="entry-1")
    assert got["name_why"] == "entry-1 was suspended by a person" and got["default"] == "entry-2"
    assert ("name_check", {"dir": NODE_DIR, "name": "entry-1", "repo": NODE_DIR, "host": "node1"}) in calls


@pytest.mark.parametrize("silent", ["host_worktrees", "name_check", "host_branch", "host_dir"])
def test_a_node_that_does_not_answer_disables_the_session_way_and_hand_still_answers(tmp_path, monkeypatch, silent):
    """(d) whichever read met the silent host: *node1 did not answer*, no default, the press refused,
    and `entry_add` (the mail way) still handed."""
    world(tmp_path)
    calls, created, handed = [], [], []
    c = client(monkeypatch, tmp_path, fake(calls=calls, created=created, handed=handed, silent={silent}))
    got = plan(c)
    assert got["why"].startswith("node1 did not answer") and got["name_why"] == got["why"]
    assert got["default"] == ""
    r = c.post("/api/entry/session", json={"repo": "samscrape", "type": "debt"})
    assert r.status_code == 409 and r.json()["detail"].startswith("node1 did not answer") and created == []
    r = c.post("/api/entry/hand", json={"repo": "samscrape", "type": "debt", "words": "an entry"})
    assert r.status_code == 200, r.text
    assert handed and handed[0]["teams"][0]["team"] == "sam-grind"


def test_a_branch_the_node_cannot_tell_disables_the_session_way(tmp_path, monkeypatch):
    world(tmp_path)
    got = plan(client(monkeypatch, tmp_path, fake(calls=[], branch_unknown=True)))
    assert got["why"] == "node1 did not say whether entry-1 is free" and got["default"] == ""


def test_a_team_with_no_checkout_on_its_host_is_refused_in_the_starts_words(tmp_path, monkeypatch):
    """(d) an org-file team with no path on its host: `_checkout`'s sentence; a repo's team whose
    landing cannot be told: `org.unlanded`'s — neither creating on the home's path."""
    world(tmp_path, node_path=False)
    calls, created = [], []
    c = client(monkeypatch, tmp_path, fake(calls=calls, created=created))
    got = plan(c)
    assert got["why"].startswith("Open a session: repo 'samscrape' has no checkout on node1")
    assert c.post("/api/entry/session", json={"repo": "samscrape", "type": "debt"}).status_code == 409
    assert created == [] and not any(m == "host_worktrees" for m, _ in calls)

    tmp2 = tmp_path / "two"
    tmp2.mkdir()
    world(tmp2, node_path=False, repo_team=True)
    from shiftlead.ui import common

    def unread(host):
        raise OSError("the link dropped")

    monkeypatch.setattr(common, "repos_of", unread)
    got = plan(client(monkeypatch, tmp2, fake(calls=[])))
    assert got["why"].startswith("team sam-grind: `place:` puts it on node1, whose registry could not be read")


def test_a_plan_on_a_node_lists_its_worktrees_once(tmp_path, monkeypatch):
    """(f) three live entries on the node: one `host_worktrees`, and no name check for a listed one."""
    world(tmp_path)
    calls = []
    got = plan(client(monkeypatch, tmp_path, fake(calls=calls, worktrees=("entry-1", "entry-2", "entry-3"))))
    assert got["default"] == "entry-4"
    assert [m for m, _ in calls].count("host_worktrees") == 1
    assert [kw["name"] for m, kw in calls if m == "name_check"] == ["entry-4"]


def test_a_typed_name_the_nodes_worktrees_list_is_refused_in_the_name_rows_words(tmp_path, monkeypatch):
    """TD-1123: a typed name, unlike the default search's candidates, reaches the listed-worktree test."""
    world(tmp_path)
    got = plan(client(monkeypatch, tmp_path, fake(calls=[], worktrees=("entry-1",))), name="entry-1")
    assert got["name_why"] == "a worktree named entry-1 exists — pick another name" and got["default"] == "entry-2"


def test_a_typed_name_that_is_not_a_slug_is_refused_on_the_node(tmp_path, monkeypatch):
    from shiftlead.ui.repo import ENTRY_SLUG_WHY

    world(tmp_path)
    got = plan(client(monkeypatch, tmp_path, fake(calls=[])), name="Bad Name")
    assert got["name_why"] == ENTRY_SLUG_WHY and got["why"] == ""


def test_a_node_that_stops_answering_between_the_plan_and_the_press_creates_nothing(tmp_path, monkeypatch):
    """TD-1123: the press's plan reads the node, then its reader's read over the link (the press's
    alone) meets a silent node: 409 in the host's words, nothing created."""
    world(tmp_path, team_extra={"entries": {"debt": "designer"}})
    calls, created = [], []
    from shiftlead.ui import app as ui

    def dropped(team, directory, cfg=None, role=None):
        assert cfg is not None, "the node's config, read across the link"
        raise OSError("the link dropped")

    monkeypatch.setattr(ui, "team_reader", dropped)
    c = client(monkeypatch, tmp_path, fake(calls=calls, created=created))
    assert plan(c)["why"] == ""
    r = c.post("/api/entry/session", json={"repo": "samscrape", "type": "debt", "words": "w"})
    assert (r.status_code, r.json()["detail"]) == (409, "node1 did not answer: the link dropped")
    assert created == []
