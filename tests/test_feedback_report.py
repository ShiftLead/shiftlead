"""`ao feedback report` and its `--build` read (design §4.7 *Feedback*, *Reports from other installs*, TD-1794):
the shared rules, the scrub's three passes and the cut, the build read from real clones, the Markdown file, the
publish check (the pinned agent-cadence's own, where it is on PATH) and the verb's exits."""

from __future__ import annotations

import fnmatch
import json
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote

import pytest

from shiftlead import cli
from shiftlead import feedback_report as fr

ROOT = Path(__file__).resolve().parents[1]
UUID = "123e4567-e89b-12d3-a456-426614174000"


def names(*pairs: tuple[str, str]) -> fr.Names:
    return fr.Names.of(pairs)


def s(text: str, *pairs: tuple[str, str], keep: tuple[str, ...] = ()) -> str:
    return fr.scrub(text, names(*pairs), keep)


def finding(what: str = "a thing", fix: str = "a fix", **kw) -> dict:
    return {"area": "shiftlead", "what": what, "fix": fix, "count": 1, "recurs": None} | kw


def findings(new=None, known=None, **kw) -> dict:
    return {"days": 7, "seats": 2, "noise": 0.25, "names": [], "new": new or [], "known": known or []} | kw


BUILD = {"checkout": str(ROOT), "commit": "abcdef0123456789abcdef0123456789abcdef01", "build_day": "2026-11-13",
         "local": False}  # fmt: skip


def write(tmp_path: Path, data: dict) -> str:
    p = tmp_path / "findings.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


def run_report(tmp_path, data, *, pairs=(), check=(0, [])):
    return fr.report(
        write(tmp_path, data),
        str(tmp_path / "feedback-issue.md"),
        build=lambda: BUILD,
        names=lambda listed: names(*pairs, *((n, "seat") for n in listed)),  # the file's names, as gather_names
        check=lambda c, o: check,
    )


def block(text: str) -> dict:
    assert fr.MARKER in text
    body = text.split(fr.MARKER, 1)[1].split("```json\n", 1)[1].split("\n```", 1)[0]
    return json.loads(body)


# ── the fields ────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "change, why",
    [
        ({"days": True}, "days: bad type"),
        ({"days": 3.0}, "days: bad type"),
        ({"days": 0}, "days: not allowed"),
        ({"days": 367}, "days: not allowed"),
        ({"seats": 1000}, "seats: not allowed"),
        ({"noise": True}, "noise: bad type"),
        ({"noise": 1.5}, "noise: not allowed"),
        ({"noise": "0.5"}, "noise: bad type"),
        ({"noise": 10**400}, "noise: not allowed"),
        ({"new": [finding(count=True)]}, "new[0].count: bad type"),
        ({"new": [finding(count=0)]}, "new[0].count: not allowed"),
        ({"new": [finding(area="acme")]}, "new[0].area: not allowed"),
        ({"new": [finding(what=3)]}, "new[0].what: bad type"),
        ({"new": [finding(recurs="TD-x")]}, "new[0].recurs: not allowed"),
        ({"new": "x"}, "new: bad type"),
        ({"known": [{"repo": "shiftlead", "id": "12", "count": 1}]}, "known[0].id: not allowed"),
        ({"known": [{"repo": "acme", "id": "TD-1", "count": 1}]}, "known[0].repo: not allowed"),
        ({"names": "x"}, "names: bad type"),
    ],
)
def test_a_field_that_breaks_a_rule_is_refused_naming_the_field(change, why):
    with pytest.raises(fr.Refused, match=f"^{fr.re.escape(why)}$"):
        fr.validate(findings(new=[finding()]) | change)


def test_no_findings_and_too_many_are_refused():
    with pytest.raises(fr.Refused, match="nothing to report"):
        fr.validate(findings())
    many = findings(new=[finding()] * 30, known=[{"repo": "shiftlead", "id": "TD-1", "count": 1}] * 11)
    with pytest.raises(fr.Refused, match="at most 40"):
        fr.validate(many)
    assert len(fr.validate(findings(new=[finding()] * 40))["new"]) == 40


def test_a_count_over_999_is_capped_noise_rounded_and_other_keys_dropped():
    got = fr.validate(findings(new=[finding(count=1200, extra="x")], noise=0.336, other=1))
    assert got["new"][0]["count"] == 999
    assert "extra" not in got["new"][0] and "other" not in got
    assert got["noise"] == 0.34


# ── normalize ─────────────────────────────────────────────────────────────────────────────────


def test_normalize_spaces_drops_controls_and_defuses_links():
    assert fr.normalize("a|b\nc\td") == "a|b c d"
    assert fr.normalize("run `ao` and ｀x｀") == "run 'ao' and 'x'"
    assert fr.normalize("[a](x) and ［b］（y）") == "[a] (x) and [b] (y)"
    assert fr.normalize("a‮b​c­") == "abc"  # a bidi mark, a zero-width space, a soft hyphen


def test_a_tab_between_two_words_is_a_space_so_a_name_after_it_still_matches():
    assert s("x\tacme y", ("acme", "repo")) == "x <repo> y"


# ── pass 1: URLs, emails, addresses ──────────────────────────────────────────────────────────


def test_a_shiftlead_url_is_kept_whole_after_a_colon_and_holding_td_12():
    url = "https://github.com/ShiftLead/shiftlead/blob/main/docs/ledger/TD-12.md"
    assert s(f"see:{url}") == f"see:{url}"
    assert s(f"see {url}?x=1") == "see <url>"
    assert s(f"see {url}#frag") == "see <url>"


@pytest.mark.parametrize(
    "text", ["HTTPS://x.example/a", "ssh://h/p", "git@github.com:acme/private.git", "file:///etc/x", "(git://h/x)"]
)
def test_other_urls_and_the_scp_form_are_url(text):
    assert "<url>" in s(text) and "example" not in s(text) and "acme" not in s(text)


def test_an_email_whose_domain_is_a_known_name_is_email():
    assert s("mail jdoe@acme.example now", ("acme", "repo")) == "mail <email> now"


def test_addresses_are_host():
    assert s("at 10.0.0.5 and [::1] then") == "at <host> and <host> then"


# ── pass 2: names ────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text, want",
    [
        ("acme-td12 fails", "<repo>-td12 fails"),
        ("acme_cli and get_acme_token", "<repo>_cli and get_<repo>_token"),
        ("ao-acme-lead-2", "ao-<repo>-lead-2"),
        ("ACME is down", "<repo> is down"),
        ("ac​me and ａｃｍｅ", "<repo> and <repo>"),
    ],
)
def test_a_name_is_a_whole_word_whose_edges_are_any_non_alphanumeric(text, want):
    assert s(text, ("acme", "repo")) == want


def test_a_names_parts_match_across_any_separator():
    assert s("acme_billing broke", ("acme-billing", "repo")) == "<repo> broke"
    assert s("acme.billing broke", ("acme billing", "repo")) == "<repo> broke"


def test_sharp_s_in_a_name_matches_and_the_text_around_it_is_unchanged():
    assert s("Größe Straße hier", ("straße", "team")) == "Größe <team> hier"
    assert s("die STRASSE", ("Straße", "team")) == "die <team>"


def test_a_longer_name_wins_and_a_string_from_two_sources_takes_the_first_kind():
    assert s("acme-billing and acme", ("acme", "team"), ("acme-billing", "seat")) == "<seat> and <team>"
    assert s("acme here", ("acme", "team"), ("acme", "repo")) == "<repo> here"


@pytest.mark.parametrize("word", ["shiftlead", "url", "seat", "lead", "claude", "home", "main", "grinder"])
def test_a_fixed_list_word_is_never_replaced_whatever_is_named_so(word):
    assert s(f"the {word} is fine", (word, "team"), (word, "seat"), (word, "profile")) == f"the {word} is fine"


def test_a_placeholder_already_there_stays_whole():
    assert s("<seat> broke", ("seat", "seat")) == "<seat> broke"
    assert s("<seat>s and <path>", ("acme", "repo")) == "<seat>s and <path>"


def test_a_name_under_three_characters_is_skipped():
    assert s("ab cd", ("ab", "seat")) == "ab cd"


# The names an install's records, org, repos, host and person give (`name_pairs`).
STATUS = [
    {
        "id": "ao-acme-worker-1",
        "name": "wrk",
        "profile": "work-max",
        "worktree": "wt-gizmo",
        "project": "projx",
        "team": "zebras",
        "role": "auditor",
        "repo": "/x/acme",
        "dir": "/x/acme/.claude/worktrees/wt-gizmo",
        "host": "boxen",
        "state": "closed",
    },
    {"id": "ao-y", "name": "y", "role": "quokka", "repo": "/srv/shiftlead", "dir": "/srv/shiftlead/docs"},
]
ORG = {
    "teams": [{"name": "zebras", "repo": "acme", "project": "projx", "host": "farhost"}],
    "roles": [{"name": "boss"}],
}
REPOS = [{"name": "acme", "root": "/x/acme"}, {"name": "shiftlead", "root": "/srv/sl-clone"}]


def install_names() -> fr.Names:
    pairs = fr.name_pairs(
        STATUS,
        ORG,
        REPOS,
        ["ao-closed-one"],
        hostname="box.corp.example.com",
        user=["kim", "Jane Doe", "Jane", "Doe", "jdoe@corp.example", "jdoe"],
    )
    return fr.Names.of(pairs)


@pytest.mark.parametrize(
    "text, want",
    [
        ("acme is slow", "<repo> is slow"),  # a record's repo, no acme registered needed
        ("zebras and projx", "<team> and <project>"),
        ("wrk and ao-acme-worker-1", "<seat> and <seat>"),
        ("ao-closed-one quit", "<seat> quit"),  # `names` from the file
        ("work-max ran", "<profile> ran"),
        ("wt-gizmo is stale", "<path> is stale"),
        ("quokka and boss", "<role> and <role>"),  # non-package roles; auditor is the package's
        ("auditor read it", "auditor read it"),
        ("boxen and farhost", "<host> and <host>"),  # a record's host not in the org, and the org's
        ("box.corp.example.com and box", "<host> and <host>"),
        ("Jane wrote, Doe read, jdoe and kim", "<user> wrote, <user> read, <user> and <user>"),
        ("sl-clone checkout", "<path> checkout"),
        ("docs/x is fine", "docs/x is fine"),  # a dir ending in docs is a checkout's folder
    ],
)
def test_each_name_source_is_replaced_by_its_placeholder(text, want):
    assert fr.scrub(text, install_names()) == want


def test_a_dir_ending_in_docs_leaves_docs_alone_but_its_whole_path_is_path():
    assert fr.scrub("see /srv/shiftlead/docs now", install_names()) == "see <path> now"


def test_user_names_reads_user_and_git_skipping_what_is_unset():
    def run(_cwd, *args):
        value = {"user.name": "Jane Q Doe", "user.email": ""}[args[-1]]
        return subprocess.CompletedProcess(args, 0 if value else 1, value + "\n", "")

    assert fr.user_names({"USER": "kim"}, run) == ["kim", "Jane Q Doe", "Jane", "Q", "Doe"]
    assert fr.user_names({}, lambda *_a: subprocess.CompletedProcess([], 1, "", "")) == []

    # user.email set: the address, then its part before `@`, the mailbox name a scrub must also find (TD-1812)
    def run_mail(_cwd, *args):
        value = {"user.name": "Jane Q Doe", "user.email": "jane.doe@example.com"}[args[-1]]
        return subprocess.CompletedProcess(args, 0, value + "\n", "")

    assert fr.user_names({"USER": "kim"}, run_mail) == [
        "kim", "Jane Q Doe", "Jane", "Q", "Doe", "jane.doe@example.com", "jane.doe"
    ]  # fmt: skip


def test_a_failing_ao_is_refused():
    def ao(args):
        if args == ["org"]:
            raise fr.Refused("ao org --json failed: down")
        return []

    with pytest.raises(fr.Refused, match="ao org"):
        fr.gather_names([], ao, env={})


# ── pass 3: patterns ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text, want",
    [
        ("a>/etc/x", "a><path>"),
        ("x|/etc/x", "x|<path>"),
        ("in $HOME/x and ${HOME}/y and ~/z", "in <path> and <path> and <path>"),
        ("acme/src/x.py", "acme/src/x.py"),  # a relative path passes, by design
        ("<repo>/src/x.py", "<repo>/src/x.py"),
        ("/home/<user>/src/<repo>/x.py", "<path>"),
        (f"id {UUID} and m-0123456789ab", "id <id> and <id>"),
        ("tok " + "a" * 40, "tok <secret>"),
        ("see TD-9 and #12", "see <ref> and <ref>"),
        ("see agent-cadence#TD-243", "see agent-cadence#TD-243"),
        ("see acme#TD-3", "see <ref>"),
        ("see acme#12 and shiftlead#3767", "see acme<ref> and shiftlead#3767"),
        ("run /ao", "run <path>"),
    ],
)
def test_patterns(text, want):
    assert fr.shared(text) == want


def test_a_bare_td_id_is_kept_when_it_is_the_recurs_or_a_known_id():
    assert fr.shared("TD-9 and TD-10", ["TD-9"]) == "TD-9 and <ref>"


def test_a_root_with_a_path_after_it_is_one_path():
    assert fr.scrub("open /x/acme/src/x.py now", install_names()) == "open <path> now"


# ── the cut ──────────────────────────────────────────────────────────────────────────────────


def test_the_cut_is_300_and_backs_up_before_a_placeholder_or_kept_url():
    assert len(fr.shared("xy " * 150)) == 300
    assert fr.shared("x " * 148 + "TD-77") == "x " * 148  # `<ref>` would end at 301
    url = "https://github.com/ShiftLead/shiftlead/pull/1"
    assert fr.shared("y " * 140 + url) == "y " * 140


@pytest.mark.parametrize(
    "text",
    [
        "acme/src/x.py",
        "x " * 140 + "https://github.com/ShiftLead/shiftlead/pull/12345",
        "<seat> on <host> saw <path>; agent-cadence#TD-243 and TD-4",
        "mail <email> at <url>",
    ],
)
def test_the_intakes_passes_over_the_reports_output_change_nothing(text):
    once = fr.scrub(text, install_names(), ["TD-4"])
    assert fr.shared(once, ["TD-4"]) == once


# ── the report ───────────────────────────────────────────────────────────────────────────────


def test_the_report_has_the_title_table_marker_and_one_block_of_the_same_strings(tmp_path):
    data = findings(
        new=[finding("acme | broke `x`", "do ］（this）", count=1200, recurs="TD-5"), finding("TD-5 again", "")],
        known=[{"repo": "agent-cadence", "id": "TD-9", "count": 3}],
        names=["ao-secret-seat"],
    )
    data["new"][1]["what"] += " ao-secret-seat"
    got = run_report(tmp_path, data, pairs=(("acme", "repo"),))
    text = Path(got["out"]).read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0] == "feedback report: abcdef0 · 3 findings"
    b = block(text)
    assert b["v"] == 1 and b["commit"] == BUILD["commit"] and b["build_day"] == "2026-11-13"
    assert set(b) == {"v", "commit", "build_day", "days", "seats", "noise", "new", "known"}
    assert b["new"][0] == {"area": "shiftlead", "what": "<repo> | broke 'x'", "fix": "do ] (this)", "count": 999,
                           "recurs": "TD-5"}  # fmt: skip
    assert b["new"][1]["what"] == "<ref> again <seat>"  # TD-5 is the other finding's recurs, not this one's
    assert "ao-secret-seat" not in text  # names never in the output
    row = next(line for line in lines if "recurs TD-5" in line)
    assert row == "| shiftlead | `<repo> \\| broke 'x'` | `do ] (this)` | 999 | recurs TD-5 |"
    known = next(line for line in lines if "seen on" in line)
    assert known == "| agent-cadence | – | – | 3 | seen on TD-9 |"
    assert b["known"] == [{"repo": "agent-cadence", "id": "TD-9", "count": 3}]
    assert "\\u" not in text


def test_forty_plain_findings_of_300_characters_fit(tmp_path):
    data = findings(new=[finding("w" * 300, "f" * 300)] * 40)
    got = run_report(tmp_path, data)
    assert len(Path(got["out"]).read_text(encoding="utf-8")) <= fr.BODY_MAX


@pytest.mark.parametrize("char", ['"', "\\", "|"])
def test_forty_findings_of_quotes_backslashes_or_bars_are_over_the_bound(tmp_path, char):
    out = tmp_path / "feedback-issue.md"
    out.write_text("old", encoding="utf-8")
    with pytest.raises(fr.Refused, match="^report over 65536 characters$"):
        run_report(tmp_path, findings(new=[finding(char * 300, char * 300)] * 40))
    assert not out.exists()


def test_a_refused_file_and_a_failed_name_source_write_nothing(tmp_path):
    out = tmp_path / "feedback-issue.md"
    with pytest.raises(fr.Refused, match="nothing to report"):
        run_report(tmp_path, findings())
    assert not out.exists()

    def down(_names):
        raise fr.Refused("ao status --json failed: down")

    with pytest.raises(fr.Refused, match="ao status"):
        fr.report(write(tmp_path, findings(new=[finding()])), str(out), build=lambda: BUILD, names=down)
    assert not out.exists()


def test_a_flagged_check_keeps_the_report_and_its_lines(tmp_path):
    got = run_report(tmp_path, findings(new=[finding()]), check=(1, ["x:3: a name (acme)"]))
    assert got["check"] == {"exit": 1, "lines": ["x:3: a name (acme)"]}
    assert Path(got["out"]).exists()


# ── the publish check ────────────────────────────────────────────────────────────────────────


def accepted(finding_text: str) -> bool:
    return any(fnmatch.fnmatchcase(finding_text, line.split(" ", 1)[1]) for line in fr.accept_lines())


def test_the_accept_lines_take_the_three_and_the_fixed_words_whole_in_any_case():
    assert accepted("a repo on this machine's roster (shiftlead)")
    assert accepted("a name your publish-names lists (ShiftLead)")
    assert accepted("this machine's short name (shiftlead)")  # a host named shiftlead-1
    assert accepted("this machine's short name (home)")  # a host named home-pc
    assert accepted("a repo on this machine's roster (Ledgerboard)")
    assert not accepted("a name your publish-names lists (shiftlead-acme)")
    assert not accepted("this machine's name (shiftlead-1)")
    assert not accepted("an email address (a@b.co)")


def test_the_check_runs_with_the_accept_file_and_removes_it(tmp_path):
    out = str(tmp_path / "r.md")
    seen = {}

    def run(cmd, **_kw):
        seen["cmd"] = cmd
        seen["accept"] = Path(cmd[cmd.index("--accept") + 1]).read_text(encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 1, f"{out}:4: a name (acme)\nnote: x\n2 lines to look at\n", "")

    assert fr.publish_check("/c", out, run) == (1, [f"{out}:4: a name (acme)"])
    assert seen["cmd"][:5] == ["agent-cadence", "-C", "/c", "run", "cadence_layer.py"]
    assert seen["cmd"][-1] == out and "* * ([Ss][Hh][Ii][Ff][Tt][Ll][Ee][Aa][Dd])" in seen["accept"]
    assert not Path(out + ".accept").exists()

    def missing(cmd, **_kw):
        raise FileNotFoundError("agent-cadence")

    with pytest.raises(fr.Refused, match="no agent-cadence"):
        fr.publish_check("/c", out, missing)
    with pytest.raises(fr.Refused, match="exit 2"):
        fr.publish_check("/c", out, lambda cmd, **_kw: subprocess.CompletedProcess(cmd, 2, "", "bad\n"))


needs_cadence = pytest.mark.skipif(shutil.which("agent-cadence") is None, reason="agent-cadence is not on PATH")


@needs_cadence
def test_the_pinned_check_accepts_a_registered_shiftlead_and_flags_a_publish_name(tmp_path, monkeypatch):
    reg = tmp_path / "reg"
    reg.mkdir()
    (tmp_path / "shiftlead").mkdir()
    (reg / "repos.txt").write_text(f"{tmp_path / 'shiftlead'}\n", encoding="utf-8")
    (reg / "cadence.toml").write_text('publish-names = ["shiftlead-acme", "Zorblax"]\n', encoding="utf-8")
    monkeypatch.setenv("AGENT_CADENCE_REG_DIR", str(reg))
    data = findings(new=[finding("shiftlead and ledgerboard are fine")])
    out = str(tmp_path / "ok.md")
    got = fr.report(write(tmp_path, data), out, build=lambda: BUILD, names=lambda _n: names())
    assert got["check"] == {"exit": 0, "lines": []}
    data = findings(new=[finding("shiftlead-acme is private")])
    got = fr.report(write(tmp_path, data), out, build=lambda: BUILD, names=lambda _n: names())
    assert got["check"]["exit"] == 1
    flagged = "a name your publish-names lists (shiftlead-acme)"
    assert got["check"]["lines"] == [f"{out}:5: {flagged}", f"{out}:20: {flagged}"]  # the row and the block
    assert Path(out).exists() and not Path(out + ".accept").exists()


# ── the build ────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url, up",
    [
        ("https://github.com/ShiftLead/shiftlead", True),
        ("https://github.com/shiftlead/ShiftLead.git/", True),
        ("https://u:t@github.com/ShiftLead/shiftlead.git", True),
        ("ssh://git@ssh.github.com:443/ShiftLead/shiftlead.git", True),
        ("git@github.com:ShiftLead/shiftlead.git", True),
        ("https://www.github.com/ShiftLead/shiftlead", True),
        ("https://git.corp.example/ShiftLead/shiftlead", False),
        ("https://github.com/someone/shiftlead", False),
        ("/srv/mirror/shiftlead.git", False),
    ],
)
def test_the_upstream_is_compared_as_host_and_owner_name(url, up):
    assert fr.is_upstream(url) is up


def git(cwd: Path, *args: str) -> str:
    env = os.environ | {
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com", "GIT_COMMITTER_DATE": "2026-11-01T12:00:00Z",
    }  # fmt: skip
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True, env=env).stdout


def clone(tmp_path: Path, name: str = "my clone") -> tuple[Path, str]:
    d = tmp_path / name
    d.mkdir()
    git(d, "init", "-q", "-b", "main")
    git(d, "commit", "-q", "--allow-empty", "-m", "public")
    return d, git(d, "rev-parse", "HEAD").strip()


def direct(d: Path) -> str:
    return json.dumps({"url": "file://" + quote(str(d)), "dir_info": {}})


def test_build_reads_head_where_it_is_public_from_a_percent_encoded_path(tmp_path):
    d, public = clone(tmp_path)
    git(d, "remote", "add", "upstream", "https://github.com/ShiftLead/shiftlead.git")
    git(d, "update-ref", "refs/remotes/upstream/main", public)
    assert "%20" in direct(d)
    got = fr.read_build(direct(d))
    assert got == {"checkout": str(d), "commit": public, "build_day": "2026-11-01", "local": False}


def test_build_on_a_patched_clone_gives_the_merge_base_and_local(tmp_path):
    d, public = clone(tmp_path)
    git(d, "remote", "add", "origin", "https://github.com/ShiftLead/shiftlead")
    git(d, "update-ref", "refs/remotes/origin/main", public)
    git(d, "commit", "-q", "--allow-empty", "-m", "mine")
    got = fr.read_build(direct(d))
    assert got["commit"] == public and got["local"] is True


def test_build_reads_the_upstream_remote_not_a_forks_origin(tmp_path):
    d, public = clone(tmp_path)
    git(d, "commit", "-q", "--allow-empty", "-m", "private")
    private = git(d, "rev-parse", "HEAD").strip()
    git(d, "remote", "add", "origin", "https://github.com/someone/shiftlead")
    git(d, "update-ref", "refs/remotes/origin/main", private)
    git(d, "remote", "add", "upstream", "git@github.com:ShiftLead/shiftlead.git")
    git(d, "update-ref", "refs/remotes/upstream/main", public)
    got = fr.read_build(direct(d))
    assert got["commit"] == public and got["local"] is True


def test_build_refuses_no_upstream_no_main_and_no_checkout(tmp_path):
    d, _ = clone(tmp_path)
    git(d, "remote", "add", "origin", "https://github.com/someone/shiftlead")
    with pytest.raises(fr.Refused, match="git remote add upstream https://github.com/ShiftLead/shiftlead"):
        fr.read_build(direct(d))
    git(d, "remote", "add", "upstream", "https://github.com/ShiftLead/shiftlead")
    with pytest.raises(fr.Refused, match="no main under upstream"):
        fr.read_build(direct(d))
    # a broken or shallow history: `merge-base --is-ancestor` exits 128, never read as *local* (TD-1813)
    git(d, "update-ref", "refs/remotes/upstream/main", git(d, "rev-parse", "HEAD").strip())

    def broken(cwd, *args):
        if args[:2] == ("merge-base", "--is-ancestor"):
            return subprocess.CompletedProcess(args, 128, "", "fatal: bad object\n")
        return fr.git(cwd, *args)

    assert fr.read_build(direct(d))["local"] is False  # the real git reads it: the stub alone refuses
    with pytest.raises(fr.Refused, match="merge-base --is-ancestor HEAD refs/remotes/upstream/main"):
        fr.read_build(direct(d), broken)
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(fr.Refused, match="no git checkout"):
        fr.read_build(direct(plain))
    with pytest.raises(fr.Refused, match="no checkout"):
        fr.read_build(None)
    with pytest.raises(fr.Refused, match="no checkout"):
        fr.read_build(json.dumps({"url": "https://example.com/x.whl"}))


# ── the verb ─────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def stubbed(monkeypatch):
    state = {"check": (0, [])}
    monkeypatch.setattr(fr, "read_build", lambda _raw, run=None: BUILD)
    monkeypatch.setattr(fr, "gather_names", lambda n, ao=None, env=None: names(("acme", "repo")))
    monkeypatch.setattr(fr, "publish_check", lambda c, o, run=None: state["check"])
    return state


def test_the_verbs_json_on_exit_0_1_and_2(tmp_path, stubbed, capsys):
    f = write(tmp_path, findings(new=[finding("acme broke")]))
    out = tmp_path / "feedback-issue.md"
    assert cli.main(["feedback", "report", "--findings", f, "--out", str(out), "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got == {"out": str(out), "commit": BUILD["commit"], "build_day": "2026-11-13", "local": False,
                   "check": {"exit": 0, "lines": []}}  # fmt: skip
    stubbed["check"] = (1, [f"{out}:5: a name (acme)"])
    assert cli.main(["feedback", "report", "--findings", f, "--out", str(out), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["check"]["exit"] == 1 and out.exists()
    bad = write(tmp_path, findings(new=[finding(count=True)]))
    assert cli.main(["feedback", "report", "--findings", bad, "--out", str(out), "--json"]) == 2
    assert json.loads(capsys.readouterr().out) == {"error": "new[0].count: bad type"}
    assert not out.exists()


def test_build_takes_neither_findings_nor_out(tmp_path, stubbed, capsys):
    assert cli.main(["feedback", "report", "--build", "--out", "x.md", "--json"]) == 2
    assert "--build takes neither" in json.loads(capsys.readouterr().out)["error"]
    assert cli.main(["feedback", "report", "--build", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == BUILD
    assert cli.main(["feedback", "report", "--out", "x.md"]) == 2
