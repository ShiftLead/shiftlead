"""`ao feedback intake` (design §4.7 *Feedback*, *The intake, in file mode*, TD-1795): the saved list read, a
report's block parsed into its fixed fields by the report's own rules, the shared scrub and the cut, each refusal
a fixed reason naming at most a field, the build day derived from shiftlead's own clone, and the verb's exits."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from shiftlead import cli
from shiftlead import feedback_intake as fi
from shiftlead import feedback_report as fr

SHA = "abcdef0123456789abcdef0123456789abcdef01"


def finding(what: str = "a thing", fix: str = "a fix", **kw) -> dict:
    return {"area": "shiftlead", "what": what, "fix": fix, "count": 1, "recurs": None} | kw


def block(**kw) -> dict:
    return {"v": 1, "commit": None, "build_day": "2026-01-01", "days": 7, "seats": 2, "noise": 0.25,
            "new": [finding()], "known": []} | kw  # fmt: skip


def body(data, *, text: str | None = None) -> str:
    """An issue form's body: `### Report`, a blank line, the pasted Markdown, its marker and block."""
    inner = text if text is not None else json.dumps(data, ensure_ascii=False, indent=1)
    return f"### Report\n\n| area | what |\n|---|---|\n\n{fr.MARKER}\n\n```json\n{inner}\n```\n"


def issue(number: int, b, *, title: str = "feedback report: abcdef0 · 1 findings", **kw) -> dict:
    return {"number": number, "title": title, "body": b, "author": {"login": "someone", "name": "Their Own Words"},
            "createdAt": "2026-11-10T09:00:00Z"} | kw  # fmt: skip


def save(tmp_path: Path, issues) -> str:
    p = tmp_path / "reports.json"
    p.write_text(json.dumps(issues), encoding="utf-8")
    return str(p)


def run(tmp_path, issues, read=(), root=None):
    return fi.intake(save(tmp_path, issues), root or tmp_path / "no-checkout", read)


_BODY = object()


def one(tmp_path, data=None, *, raw=_BODY, read=True) -> dict:
    b = body(data) if raw is _BODY else raw
    got = run(tmp_path, [issue(7, b)], read=[7] if read else ())
    return got


# ── the clone ────────────────────────────────────────────────────────────────────────────────


def g(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def clone(tmp_path) -> dict:
    """A clone whose `origin/main` holds commit `a` (day 2026-03-04); `b` (2026-05-06) is off it, and a branch
    named like `a`'s short id points at `b`."""
    root = tmp_path / "clone"
    root.mkdir()
    g(root, "init", "-q", "-b", "main")
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}

    def commit(msg: str, day: str) -> str:
        e = env | {"GIT_AUTHOR_DATE": f"{day}T12:00:00Z", "GIT_COMMITTER_DATE": f"{day}T12:00:00Z"}
        subprocess.run(["git", "-C", str(root), "commit", "-q", "--allow-empty", "-m", msg], check=True, env={
            **__import__("os").environ, **e})  # fmt: skip
        return g(root, "rev-parse", "HEAD")

    a = commit("a", "2026-03-04")
    g(root, "update-ref", "refs/remotes/origin/main", a)
    b = commit("b", "2026-05-06")
    g(root, "branch", a[:7], b)  # a hex-named branch, never read as the commit
    return {"root": root, "a": a, "b": b}


def test_the_build_day_is_derived_from_the_clone(clone, tmp_path):
    root, a, b = clone["root"], clone["a"], clone["b"]
    assert fi.build_day(a, root) == "2026-03-04"
    assert fi.build_day(a[:7], root) == "2026-03-04"  # the commit, not the branch of that name
    assert fi.build_day(b, root) is None  # off origin/main
    assert fi.build_day(None, root) is None
    assert fi.build_day("0000000", root) is None  # no such object
    assert fi.build_day(a, tmp_path / "nowhere") is None  # no checkout
    reports = run(tmp_path, [issue(1, body(block(commit=a[:7], build_day="1999-01-01")))], root=root)["reports"]
    assert reports[0]["build_day"] == "2026-03-04" and reports[0]["commit"] == a[:7]  # the report's own day dropped


def test_an_ambiguous_short_commit_is_build_unknown(tmp_path):
    def fake(root, *args):
        out = "abcdef01\nabcdef02\n" if args[0] == "rev-parse" else "commit"
        return subprocess.CompletedProcess(args, 0, out, "")

    assert fi.build_day("abcdef0", tmp_path, run=fake) is None

    def failing(root, *args):
        if args[0] == "merge-base":
            return subprocess.CompletedProcess(args, 128, "", "fatal")
        return subprocess.CompletedProcess(
            args, 0, {"rev-parse": "f" * 40, "cat-file": "commit"}.get(args[0], "2026-01-02"), ""
        )

    assert fi.build_day("fffffff", tmp_path, run=failing) is None  # a git call that fails
    tree = lambda root, *args: subprocess.CompletedProcess(args, 0, "f" * 40 if args[0] == "rev-parse" else "tree", "")  # noqa: E731
    assert fi.build_day("fffffff", tmp_path, run=tree) is None  # an object that is no commit


# ── the round trip ───────────────────────────────────────────────────────────────────────────


def test_a_report_the_report_verb_wrote_parses_back(tmp_path):
    data = {"days": 7, "seats": 2, "noise": 0.25, "names": [],
            "new": [finding("the Queue froze at /home/x/y with see TD-12", "refresh it", recurs="TD-12", count=3)],
            "known": [{"repo": "agent-cadence", "id": "TD-40", "count": 2}]}  # fmt: skip
    (tmp_path / "f.json").write_text(json.dumps(data), encoding="utf-8")
    build = {"checkout": str(tmp_path), "commit": SHA, "build_day": "2026-11-13", "local": False}
    out = tmp_path / "feedback-issue.md"
    fr.report(str(tmp_path / "f.json"), str(out), build=lambda: build, names=lambda n: fr.Names.of([]),
              check=lambda c, o: (0, []))  # fmt: skip
    text = out.read_text(encoding="utf-8")
    title, pasted = text.split("\n", 1)
    got = run(tmp_path, [issue(5, "### Report\n\n" + pasted, title=title)], read=[5])
    (r,) = got["reports"]
    written = json.loads(text.split("```json\n", 1)[1].split("\n```", 1)[0])
    assert r["new"] == written["new"] and r["known"] == written["known"] and r["commit"] == SHA
    assert r["cut"] == {"findings": 0, "counts": 0, "text": 0} and not got["refused"]


def test_the_intakes_pass_is_the_reports_on_one_string(tmp_path):
    text = "see https://evil.example/x and mail a@b.co, `rm` ‮at ~/secret/x, TD-99 and [l](http://e) " + "z" * 40
    expect = fr.scrub(text, fr.Names(None, {}), [])
    (r,) = one(tmp_path, block(new=[finding(text, text)]))["reports"]
    assert r["new"][0]["what"] == expect == r["new"][0]["fix"]
    assert "evil" not in expect and "‮" not in expect and "`" not in expect and "](" not in expect


# ── the cut ──────────────────────────────────────────────────────────────────────────────────


def test_a_report_is_cut_to_40_findings_and_a_count_to_999(tmp_path):
    new = [finding(f"n{i}", count=5000 if i == 0 else 999) for i in range(30)]
    known = [{"repo": "shiftlead", "id": f"TD-{i}", "count": 1} for i in range(30)]
    (r,) = one(tmp_path, block(new=new, known=known))["reports"]
    assert len(r["new"]) == 30 and len(r["known"]) == 10 and r["known"][-1]["id"] == "TD-9"
    assert r["new"][0]["count"] == 999
    assert r["cut"] == {"findings": 20, "counts": 1, "text": 0}  # a count of exactly 999 was never capped
    summary = run(tmp_path, [issue(7, body(block(new=new, known=known)))])["reports"][0]
    assert summary["findings"] == 40 and "new" not in summary


def test_a_long_sentence_is_cut_and_counted(tmp_path):
    (r,) = one(tmp_path, block(new=[finding("w " * 400)]))["reports"]
    assert len(r["new"][0]["what"]) <= fr.CUT and r["cut"]["text"] == 1


# ── the refusals ─────────────────────────────────────────────────────────────────────────────

SECRET = "SECRET-VALUE-zz9"


@pytest.mark.parametrize(
    "change, why",
    [
        ({"v": 2}, "unknown v"),
        ({"v": SECRET}, "unknown v"),
        ({"v": True}, "unknown v"),
        ({"commit": SECRET}, "commit: not allowed"),
        ({"commit": "abcdef"}, "commit: not allowed"),
        ({"commit": "a" * 41}, "commit: not allowed"),
        ({"commit": 1234567}, "commit: bad type"),
        ({"days": SECRET}, "days: bad type"),
        ({"days": 400}, "days: not allowed"),
        ({"seats": 0}, "seats: not allowed"),
        ({"noise": SECRET}, "noise: bad type"),
        ({"noise": 2}, "noise: not allowed"),
        ({"new": SECRET}, "new: bad type"),
        ({"new": [SECRET]}, "new: bad type"),
        ({"known": {"x": SECRET}}, "known: bad type"),
        ({"new": [finding(what=[SECRET])]}, "what: bad type"),
        ({"new": [finding(fix=7)]}, "fix: bad type"),
        ({"new": [finding(area=SECRET)]}, "area: not allowed"),
        ({"new": [finding(count=SECRET)]}, "count: bad type"),
        ({"new": [finding(count=0)]}, "count: not allowed"),
        ({"new": [finding(recurs=SECRET)]}, "recurs: not allowed"),
        ({"known": [{"repo": SECRET, "id": "TD-1", "count": 1}]}, "repo: not allowed"),
        ({"known": [{"repo": "shiftlead", "id": SECRET, "count": 1}]}, "id: not allowed"),
    ],
)
def test_each_refusal_is_a_fixed_reason_and_never_the_value(tmp_path, change, why):
    got = one(tmp_path, block(**change))
    assert got["reports"] == [] and got["refused"] == [
        {"number": 7, "login": "someone", "created_at": "2026-11-10T09:00:00Z", "why": why}
    ]
    assert SECRET not in json.dumps(got)


@pytest.mark.parametrize(
    "raw, why",
    [
        (None, "no marker"),
        ("", "no marker"),
        ("```json\n{}\n```", "no marker"),
        (f"{fr.MARKER}\nno block", "block does not parse"),
        (f"{fr.MARKER}\n```json\n{{{SECRET}\n```", "block does not parse"),
        (f"{fr.MARKER}\n```json\n[1]\n```", "block does not parse"),
        (f"{fr.MARKER}\n```json\n" + "[" * 100000 + "\n```", "block does not parse"),
    ],
)
def test_a_body_with_no_marker_or_no_block(tmp_path, raw, why):
    got = one(tmp_path, raw=raw)
    assert got["refused"][0]["why"] == why and SECRET not in json.dumps(got)


def test_the_first_block_after_the_marker_is_read(tmp_path):
    early = "```json\n" + json.dumps(block(v=9)) + "\n```\n"
    raw = early + body(block()) + "```json\n" + json.dumps(block(v=9)) + "\n```\n"
    assert one(tmp_path, raw=raw)["reports"][0]["new"][0]["what"] == "a thing"


def test_other_keys_are_dropped_unread(tmp_path):
    data = block(evidence=[SECRET], extra="x" * 10_000, new=[finding(evidence=SECRET, why=SECRET)])
    data["known"] = [{"repo": "ledgerboard", "id": "TD-3", "count": 2, "note": SECRET}]
    got = one(tmp_path, data)
    assert SECRET not in json.dumps(got) and "xxxx" not in json.dumps(got)
    (r,) = got["reports"]
    assert set(r["new"][0]) == {"area", "what", "fix", "count", "recurs"} and set(r["known"][0]) == {
        "repo",
        "id",
        "count",
    }
    assert set(r) == {"number", "login", "created_at", "commit", "build_day", "days", "seats", "noise", "new",
                      "known", "cut"}  # fmt: skip


# ── the list ─────────────────────────────────────────────────────────────────────────────────


def test_the_summary_oldest_first_titles_and_who(tmp_path):
    issues = [
        issue(9, body(block(new=[finding("nine")]))),
        issue(3, body(block()), author=None, createdAt="yesterday"),
        issue(4, body(block()), title="Feedback report: not ours"),
        issue(5, body(block()), title="a bug"),
        issue(6, None),
    ]
    got = run(tmp_path, issues)
    assert [r["number"] for r in got["reports"]] == [3, 9] and not got["limit_reached"]
    first = got["reports"][0]
    assert first["login"] is None and first["created_at"] is None and first["build_day"] is None
    nothing_cut = {"findings": 0, "counts": 0, "text": 0}
    assert first == {"number": 3, "login": None, "created_at": None, "commit": None, "build_day": None, "days": 7,
                     "seats": 2, "noise": 0.25, "findings": 1, "cut": nothing_cut}  # fmt: skip
    assert got["refused"] == [
        {"number": 6, "login": "someone", "created_at": "2026-11-10T09:00:00Z", "why": "no marker"}
    ]
    text = json.dumps(got)
    assert "nine" not in text and "a thing" not in text and "Their Own Words" not in text  # no sentence, no name


def test_read_names_its_reports_alone(tmp_path):
    issues = [issue(1, body(block(new=[finding("report-uno")]))), issue(2, body(block(new=[finding("two")]))),
              issue(3, body(block(v=5))), issue(4, body(block()), title="a bug")]  # fmt: skip
    got = run(tmp_path, issues, read=[2, 3, 4, 8])
    assert [r["number"] for r in got["reports"]] == [2] and "report-uno" not in json.dumps(got)
    assert got["reports"][0]["new"][0]["what"] == "two" and "findings" not in got["reports"][0]
    assert got["refused"] == [
        {"number": 3, "login": "someone", "created_at": "2026-11-10T09:00:00Z", "why": "unknown v"},
        {"number": 4, "login": None, "created_at": None, "why": "not a report"},
        {"number": 8, "login": None, "created_at": None, "why": "not a report"},
    ]


def test_a_list_of_100_says_more_wait(tmp_path):
    issues = [issue(i, body(block())) for i in range(100)]
    assert run(tmp_path, issues)["limit_reached"] is True


# ── the verb ─────────────────────────────────────────────────────────────────────────────────


def test_the_verbs_exits(tmp_path, capsys):
    f = save(tmp_path, [issue(1, body(block(new=[finding("café ✓")])))])
    root = str(tmp_path)
    assert cli.main(["feedback", "intake", "--issues", f, "--root", root, "--read", "1", "--json"]) == 0
    out = capsys.readouterr().out
    assert "café ✓" in out and "\\u" not in out  # no \u escapes
    assert json.loads(out)["reports"][0]["new"][0]["what"] == "café ✓"
    assert cli.main(["feedback", "intake", "--issues", f, "--root", root, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["reports"][0]["findings"] == 1
    six = ["--read", *map(str, range(1, 7))]
    assert cli.main(["feedback", "intake", "--issues", f, "--root", root, *six, "--json"]) == 2
    assert "at most 5" in json.loads(capsys.readouterr().out)["error"]
    missing = str(tmp_path / "missing.json")
    assert cli.main(["feedback", "intake", "--issues", missing, "--root", root, "--json"]) == 2
    assert "cannot be read" in json.loads(capsys.readouterr().out)["error"]
    for bad in ('{"number": 1}', "not json", '[{"title": "x"}]', '[{"number": true}]'):
        (tmp_path / "bad.json").write_text(bad, encoding="utf-8")
        assert cli.main(["feedback", "intake", "--issues", str(tmp_path / "bad.json"), "--root", root, "--json"]) == 2
        assert "not gh's list" in json.loads(capsys.readouterr().out)["error"]
