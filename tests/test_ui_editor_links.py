"""A file button is a file link (design §4.6 *A file button is a file link*, §4.5a rows *Repo page: Open
ledger*, *Settings page: Open file*, *Focus header: ‹› VS Code*, *Transcript*; TD-688, built by TD-689):
every control that opens one file in the person's editor is drawn by the `file_link` macro from
`editor_file_link` — the editor's file form with `:1`, the checkout holding the file opened first, one
launch for a file outside every checkout — so no file button can fall back to the folder form."""

from __future__ import annotations

import html as htmllib
import pathlib
import re

import pytest
from fastapi.testclient import TestClient
from test_ui_repo_page import client as repo_client
from test_ui_repo_page import fake, reading

from sessionorc import hosts

TEMPLATES = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui" / "templates"
FILE_TEXTS = ("Open file", "Open ledger", "Open board")
TAG = re.compile(r"<(a|button)\b([^>]*)>(.*?)</\1>", re.S)

# the person's `open_in` forms the pages are rendered under: (local, a template or None)
FORMS = {
    "local": (True, None),
    "ssh-remote": (False, None),
    "template": (False, {"label": "Zed", "url": "zed://ssh/{remote}{path}", "file": "zed://ssh/{remote}{path}:{line}"}),
}


def _host(monkeypatch, tmp_path, local: bool, roots: list[str]) -> None:
    reg = tmp_path / "repos.txt"
    reg.write_text("".join(f"{r}\n" for r in roots))
    h = hosts.Host(name="kmaster", vscode_host="kmaster", local=local, repos_registry=reg, repos_import=None)
    monkeypatch.setattr(hosts, "local_host", lambda: h)


def _form(monkeypatch, tpl: dict | None) -> None:
    from shiftlead.ui import uiconf

    if tpl:
        monkeypatch.setattr(uiconf, "open_in", lambda: uiconf.OpenIn(kind="template", **tpl))


def _links(page: str, text: str) -> list[str]:
    """Every `<a>` on a page whose text ends with `text`, its opening tag."""
    return [m.group(0).split(">")[0] for m in TAG.finditer(page) if htmllib.unescape(m.group(3)).strip().endswith(text)]


def _attr(tag: str, name: str) -> str | None:
    m = re.search(rf'\b{name}="([^"]*)"', tag)
    return htmllib.unescape(m.group(1)) if m else None


@pytest.mark.unit
def test_every_file_button_in_the_templates_is_drawn_by_file_link():
    """No template writes a file button's tag itself: every **Open file**, **Open ledger** and **Open
    board**, the Focus header's `#ftranscript_editor` and the Transcript page's **VS Code** is a
    `file_link` call; the Session card's folder button `#feditor` is not."""
    seen = {t: 0 for t in FILE_TEXTS}
    for f in sorted(TEMPLATES.glob("*.html")):
        src = f.read_text(encoding="utf-8")
        for m in TAG.finditer(src):
            inner = re.sub(r"\{#.*?#\}", "", m.group(3), flags=re.S).strip()
            assert not any(inner.endswith(t) for t in FILE_TEXTS), f"{f.name}: {m.group(0)[:160]}"
            assert 'id="ftranscript_editor"' not in m.group(2), f"{f.name}: the transcript button is a file_link"
            if m.group(1) == "a" and 'id="feditor"' in m.group(2):
                assert "data-file-link" not in m.group(2), f"{f.name}: #feditor is the folder button"
        for t in FILE_TEXTS:
            seen[t] += len(re.findall(rf"""file_link\([^)]*['"](‹› )?{t}['"]""", src))
    assert all(seen.values()), seen
    assert re.search(r"file_link\([^)]*\"ftranscript_editor\"", (TEMPLATES / "focus.html").read_text())
    assert re.search(r"file_link\(editor,", (TEMPLATES / "transcript.html").read_text())
    assert "data-file-link" in (TEMPLATES / "file_link.html").read_text()


@pytest.mark.unit
@pytest.mark.parametrize("form", FORMS)
def test_open_ledger_is_the_file_form_at_line_1_with_the_checkout_first(form, tmp_path, monkeypatch):
    root = str(tmp_path / "samscrape")
    local, tpl = FORMS[form]
    _host(monkeypatch, tmp_path, local, [root])
    _form(monkeypatch, tpl)
    page = repo_client(monkeypatch, tmp_path, fake({root: reading(root)}, [])).get("/repo/samscrape").text
    (a,) = _links(page, "Open ledger")
    ledger = f"{root}/docs/technical_debt.md"
    assert "data-file-link" in a and 'class="editor btn sm ghost"' in a
    url, folder = _attr(a, "href"), _attr(a, "data-folder")
    if form == "local":
        assert url == f"vscode://file{ledger}:1" and folder == f"vscode://file{root}?windowId=_blank"
    elif form == "ssh-remote":
        assert url == f"vscode://vscode-remote/ssh-remote+kmaster{ledger}:1"
        assert folder == f"vscode://vscode-remote/ssh-remote+kmaster{root}?windowId=_blank"
    else:
        assert url == f"zed://ssh/kmaster{ledger}:1" and folder == f"zed://ssh/kmaster{root}"
    assert _attr(a, "data-wait") == "1"


@pytest.mark.unit
def test_open_ledger_is_one_launch_with_the_folder_first_off(tmp_path, monkeypatch):
    from shiftlead.ui import uiconf

    root = str(tmp_path / "samscrape")
    _host(monkeypatch, tmp_path, True, [root])
    monkeypatch.setattr(uiconf, "file_link", lambda: {"folder_first": False, "wait": 1})
    page = repo_client(monkeypatch, tmp_path, fake({root: reading(root)}, [])).get("/repo/samscrape").text
    (a,) = _links(page, "Open ledger")
    assert _attr(a, "href").endswith("technical_debt.md:1") and "data-folder" not in a


@pytest.mark.unit
def test_a_file_outside_every_checkout_is_one_launch_and_none_draws_no_button(tmp_path, monkeypatch):
    """`~/.shiftlead/hosts.yml` lies in no checkout: the file form alone. Under `open_in: none`, nothing."""
    from shiftlead.ui import common, uiconf

    root = tmp_path / "r"
    (root / "docs").mkdir(parents=True)
    _host(monkeypatch, tmp_path, False, [str(root)])
    home = tmp_path / "home" / "hosts.yml"
    got = common.editor_file_link(str(home))
    assert got == {
        "label": "VS Code",
        "url": f"vscode://vscode-remote/ssh-remote+kmaster{home}:1",
        "folder": None,
        "wait": 1,
    }
    inside = common.editor_file_link(str(root / ".shiftlead.yml"))
    assert inside["folder"] == f"vscode://vscode-remote/ssh-remote+kmaster{root}?windowId=_blank"
    assert common.editor_file_link(str(root / ".shiftlead.yml"), folder=False)["folder"] is None  # the transcript's
    assert common.editor_file_link(str(root / "a b.md"), line=7)["url"].endswith("/r/a%20b.md:7")
    assert common.checkout_of(str(tmp_path / "rr" / "x")) == ""  # a sibling with the same prefix is not inside
    _host(monkeypatch, tmp_path, False, [str(root), str(root / "inner")])
    assert common.checkout_of(str(root / "inner" / "a.md")) == str(root / "inner")  # the inner of two nested
    monkeypatch.setattr(uiconf, "open_in", lambda: uiconf.OpenIn(kind="none"))
    assert common.editor_file_link(str(home)) is None


@pytest.mark.unit
def test_a_container_s_reach_takes_the_file_in_its_folder_s_place():
    from shiftlead.ui import uiconf

    reach = "vscode://vscode-remote/attached-container+abc123/work/r?windowId=_blank"
    got = uiconf.editor_file_link("/work/r/notes.md", local=False, remote="n1", reach=reach, folder_url=reach)
    assert got["url"] == "vscode://vscode-remote/attached-container+abc123/work/r/notes.md:1" and got["folder"] == reach


@pytest.fixture
def settings_client(subprocess_agent):
    from shiftlead.ui.app import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.mark.parametrize("form", FORMS)
def test_the_settings_page_s_open_file_is_a_file_link(form, settings_client, subprocess_agent, tmp_path, monkeypatch):
    """Every **Open file** on the Settings page: the file form with `:1`; a repo's `.shiftlead.yml`
    opens its checkout first, the home's `hosts.yml` is one launch."""
    root = tmp_path / "r"
    root.mkdir()
    (root / ".shiftlead.yml").write_text("ledger: docs/technical_debt.md\n")
    local, tpl = FORMS[form]
    _host(monkeypatch, tmp_path, local, [str(root)])
    _form(monkeypatch, tpl)
    page = settings_client.get("/settings").text
    tags = _links(page, "Open file")
    assert tags and all("data-file-link" in a for a in tags)
    by = {_attr(a, "href"): a for a in tags}
    hosts_yml = str(subprocess_agent.home / "hosts.yml")
    yml = str(root / ".shiftlead.yml")
    pre = {
        "local": "vscode://file",
        "ssh-remote": "vscode://vscode-remote/ssh-remote+kmaster",
        "template": "zed://ssh/kmaster",
    }[form]
    assert "data-folder" not in by[f"{pre}{hosts_yml}:1"]
    assert _attr(by[f"{pre}{yml}:1"], "data-folder").startswith(f"{pre}{root}")


@pytest.mark.unit
def test_open_ledger_on_a_v2_directory_is_the_folder_form_titled_open_ledger_folder(tmp_path, monkeypatch):
    """§4.5a *Repo page: Open ledger* (TD-1146): a v2 ledger (§4.4 *Either layout*) is a directory, so the
    button is the editor's folder form, with no line and no folder before it, and reads *Open ledger folder*."""
    root = tmp_path / "samscrape"
    (root / "docs" / "ledger").mkdir(parents=True)
    _host(monkeypatch, tmp_path, False, [str(root)])
    r = reading(str(root))
    r["ledger"]["path"] = "docs/ledger"
    page = repo_client(monkeypatch, tmp_path, fake({str(root): r}, [])).get("/repo/samscrape").text
    assert not _links(page, "Open ledger")
    (a,) = _links(page, "Open ledger folder")
    assert "data-file-link" in a and "data-folder" not in a
    assert _attr(a, "href") == f"vscode://vscode-remote/ssh-remote+kmaster{root}/docs/ledger?windowId=_blank"
    assert _attr(a, "title") == "open the ledger's folder in VS Code"
