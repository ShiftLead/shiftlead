#!/usr/bin/env python3
# SYNCED FILE — canonical copy: ShiftLead/dev-cadence files/scripts/forge.py
# Edit it there and re-run sync.sh; an edit made in a consumer repo is overwritten (sync.sh --verify detects one).
"""The forge adapter (TD-103, the decision in TD-097): every question the PR tooling asks a
forge goes through here, in one neutral shape, so a second forge is one more backend and
never a branch in each caller.

Callers: check_cadence.py (the rows), nudge_user_attention.py (the open-PR line, the settings
line, the remote tier), adopt_repo_settings.sh and sync-all.sh (through the CLI below). No
other script runs the forge's CLI (`gh`, `glab`): a new question is an operation here first.

Which forge (cadence.md §9.18, the `forge` key): `auto` (the default) reads origin's host —
github.com is GitHub, gitlab.com or a host whose first label is `gitlab` is GitLab (TD-104),
anything else is a forge the cadence cannot read yet, never GitHub by default; `github` says
a host under another name (GitHub Enterprise) is GitHub, `gitlab` the same for GitLab;
`none` says there is no PR API at all (TD-105): check_cadence.py --since reads the review
line from each commit's body (NoForge), and every other caller says "no forge" once. An origin that names no host (a local path, file://) is read with the
GitHub backend, as before TD-103: `gh` then answers or fails on its own.

Every operation raises ForgeUnreadable(reason) when it cannot ask — no CLI, not
authenticated, offline, an unsupported forge — and a caller turns that into "cannot see",
never into an empty answer (cadence.md §7). The backend shells out to the forge's own CLI
and never holds a credential: `gh` for GitHub, `glab` for GitLab (whose facts were read
from a real project with glab 1.123.0 — docs/plans/2026-10-12-forge-adapter.md, *GitLab, as
read*).

    forge.py check                     exit 0 when the forge here can be read (its CLI present
                                       and authenticated), else the reason, exit 2
    forge.py pr-for-branch BRANCH      "<STATE> <url>" of BRANCH's PR (STATE as the forge says it);
                                       the CLI's own error and exit code when it has none
    forge.py create-pr --title T --body B
                                       open a PR from the current branch; prints its url
    forge.py has-cli [SLUG]            exit 0 when the forge's CLI is installed, else the reason, exit 2
    forge.py origin-slug               the SLUG of the repo in the current directory, from origin
    forge.py wanted SLUG [--no-auto-delete]
                                       one "name=value" line per merge setting the cadence wants
    forge.py repo-settings SLUG        the same lines with the repo's values (null: unreadable)
    forge.py patch-settings SLUG name=value…
                                       write those settings

SLUG is `owner/repo` (github.com) or `host/owner/repo` (`host/group/sub/repo` on GitLab), and
picks the forge itself; the other commands read the forge of the repo in the current
directory. A value with a newline or a quote in it (GitLab's squash template) is printed as
a JSON string, on both sides of the comparison, and patch-settings reads it back.

Stdlib only.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlencode

KNOWN = ("auto", "github", "gitlab", "none")
NOT_FOUND = -4   # a remote-tier probe's rc for "the forge says there is no such file"


class ForgeUnreadable(Exception):
    pass


def setting(root: "Path | str | None") -> str:
    """The `forge` key for the repo at root (default "auto"). An unreadable settings file
    still lets CADENCE_FORGE count, then falls back to auto — the classifier below is
    loud about any host it does not know, so auto never reads a stranger as GitHub."""
    try:
        here = str(Path(__file__).resolve().parent)
        if here not in sys.path:
            sys.path.insert(0, here)
        import cadence_config as C
        top = C.repo_root(str(root or "."))
        raw, _ = C.resolve("forge", C.sources(top))
    except Exception:  # noqa: BLE001 — no helper, or an unreadable file
        raw = os.environ.get("CADENCE_FORGE", "").strip() or "auto"
    return str(raw).strip().lower() or "auto"


def _origin(root: Path) -> tuple[str | None, str]:
    """(host, path) of origin's URL; host None when origin names none (no origin, a local
    path, file://)."""
    try:
        r = subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"],
                           check=False, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None, ""
    raw = r.stdout.strip() if r.returncode == 0 else ""
    # The host is read from the URL's own shape, not through a normalizer, so any scheme
    # (ssh://, git://, HTTPS://) and any user (deploy@host:a/b) names its forge.
    m = re.fullmatch(r"([A-Za-z][A-Za-z0-9+.-]*)://(?:[^@/]*@)?([^/:]*)(?::\d*)?(/.*)?", raw)
    if m:
        if m.group(1).lower() == "file":
            return None, ""
        host, path = m.group(2).lower(), m.group(3) or ""
    else:
        # scp-like user@host:path; a bare owner/repo (a legacy *lock* form) or a local path
        # has no host — it would read as github.com through the lock normalizer, so never here
        m = re.fullmatch(r"[^/@:]+@([^/:]+):(.*)", raw)
        if not m:
            return None, ""
        host, path = m.group(1).lower(), m.group(2)
    return (host or None), path


def _slug(path: str, deep: bool = False) -> str | None:
    """owner/repo from origin's path; deep allows GitLab's group/sub/repo."""
    slug = re.sub(r"\.git$", "", path.strip("/")).lower()
    return slug if re.fullmatch(r"[^/]+(/[^/]+)+" if deep else r"[^/]+/[^/]+", slug) else None


def is_gitlab_host(host: str) -> bool:
    """`auto`'s GitLab: gitlab.com, or a host whose first label is gitlab (gitlab.corp.example)."""
    return host == "gitlab.com" or host.split(".", 1)[0] == "gitlab"


def origin_forge(root: Path) -> tuple[str, str | None]:
    """Classify a repo's origin once (TD-098, moved here by TD-103): ("github", "owner/repo")
    for GitHub; ("gitlab", "host/group/repo") for GitLab (TD-104; None in place of the slug
    when origin names no project to ask about); ("other", host) for a forge the cadence
    cannot read yet (Gitea, a GitHub Enterprise host not named by `forge = "github"`), or
    ("other", "none") for `forge = "none"` (TD-105); ("none", None) for no origin, or one that
    names no host (a local path, a bare file:// clone: what every test fixture uses) — there
    the caller behaves as before. A detector told "other" says it could not look, never stays
    quiet: an empty answer must mean nothing there (cadence.md §7)."""
    want = setting(root)
    host, path = _origin(Path(root))
    if want == "none":
        return "other", "none"
    if want not in KNOWN:
        return "other", f"!{want}"
    if want == "gitlab" or (want == "auto" and host and is_gitlab_host(host)):
        slug = _slug(path, deep=True) if host else None
        return "gitlab", f"{host}/{slug}" if slug else None
    if not host:
        return ("github", None) if want == "github" else ("none", None)
    if host == "github.com" or want == "github":
        slug = _slug(path)
        if host == "github.com":
            return ("github", slug) if slug else ("none", None)
        return "github", slug
    return "other", host


def forge_unread_line(host: str) -> str:
    """The one wording every detector uses for an origin it cannot read (TD-098)."""
    if host.startswith("!"):
        return (f"PRs not checked: the forge setting {host[1:]!r} is not one of "
                f"{', '.join(KNOWN)} (docs/cadence.toml or CADENCE_FORGE)")
    if host == "none":
        return ('no forge (forge = "none" in docs/cadence.toml): PR checks read the commit log only '
                "— check_cadence.py --since reads each commit's cadence-review: line (TD-105)")
    return f"PRs not checked: origin is {host}, which the cadence cannot read yet (TD-097)"


GITLAB_NO_PROJECT = ('PRs not checked: the forge is GitLab, but origin names no project to ask '
                     "about (forge = \"gitlab\" needs an origin like gitlab.example/group/repo)")


def backend(root: "Path | str | None" = None, **kw) -> "GitHub | GitLab":
    """The backend for the repo at root (default: the current directory's). Raises
    ForgeUnreadable with the "PRs not checked" line for a forge with no backend."""
    kind, host = origin_forge(Path(root or "."))
    if kind == "other":
        raise ForgeUnreadable(forge_unread_line(host or "?"))
    if kind == "gitlab":
        if not host:
            raise ForgeUnreadable(GITLAB_NO_PROJECT)
        return GitLab(slug=host, **kw)
    return GitHub(slug=host, **kw)


class NoForge:
    """`forge = "none"` (TD-105): a repo with no PR API, such as a bare repo over ssh. There
    are no PRs, so the §4.9 review line goes in the squash commit's body, and
    check_cadence.py --since reads every commit on the default branch from git (its direct
    audit). Only what that needs is here: a PR question raises ForgeUnreadable with the
    "no forge" line, and the other callers never get this backend (backend() raises the same
    line for them)."""

    name = "none"
    cli = "git"
    subject_re = re.compile(r"(?!)")   # no PR marks a subject: every commit is read

    @staticmethod
    def missing() -> None:
        return None

    @staticmethod
    def merged_since(when: str, limit: int) -> list[dict]:
        return []

    @staticmethod
    def pr(n) -> dict:
        raise ForgeUnreadable(forge_unread_line("none"))

    @staticmethod
    def prs_for_branch(branch: str, limit: int = 5) -> list[dict]:
        raise ForgeUnreadable(forge_unread_line("none"))


# --- GitHub -----------------------------------------------------------------------------


# The fields check_cadence.py's rows read, in gh's names (the neutral record below maps them).
PR_FIELDS = (
    "number,url,state,title,body,baseRefName,headRefName,headRefOid,mergedAt,mergeCommit,files,updatedAt"
)
# What every gh-driven caller's env adds: a call from a hook or a sweep must never prompt.
_QUIET = {"GH_PROMPT_DISABLED": "1"}


class _CLI:
    """What every backend shares: the one place its CLI runs, under the remote tier's budget,
    and the errors turned into ForgeUnreadable."""

    cli = ""

    def __init__(self, slug: str | None = None, cwd: "Path | str | None" = None,
                 spent: dict | None = None, per_call: float = 60.0, total: float | None = None):
        self.slug, self.cwd = slug, cwd
        # The remote tier's budget (nudge_user_attention.py): elapsed time is booked into
        # spent["t"]; a call past `total` is not made, and spent["hit"] says so.
        self.spent, self.per_call, self.total = spent, per_call, total

    # -- the one place the CLI runs --------------------------------------------------------

    def call(self, args: list[str], timeout: float | None = None,
             env: dict | None = None) -> tuple[int, str, str]:
        """(rc, stdout, stderr) of one CLI call; rc -1 timeout, -2 budget exhausted (not
        attempted), -3 the CLI not installed."""
        cap = timeout if timeout is not None else self.per_call
        if self.spent is not None and self.total is not None:
            remaining = self.total - self.spent["t"]
            if remaining <= 0:
                self.spent["hit"] = True
                return -2, "", "remote-tier budget exhausted"
            cap = min(cap, remaining)   # the budget may truncate below the per-call cap
        t0 = time.monotonic()
        try:
            r = subprocess.run([self.cli, *args], cwd=self.cwd, check=False, capture_output=True,
                               text=True, timeout=cap,
                               env=None if env is None else {**os.environ, **env})
            return r.returncode, r.stdout, r.stderr
        except FileNotFoundError:
            return -3, "", f"{self.cli} not installed"
        except subprocess.TimeoutExpired:
            return -1, "", f"timeout after {cap:g}s" if self.spent is not None else f"{self.cli} timed out"
        finally:
            if self.spent is not None:
                self.spent["t"] += time.monotonic() - t0

    def _run(self, args: list[str], timeout: float | None = None, env: dict | None = None) -> str:
        rc, out, err = self.call(args, timeout, env)
        if rc == 0:
            return out
        if rc == -3:
            raise ForgeUnreadable(err)
        msg = (err or out).strip()
        raise ForgeUnreadable(msg.splitlines()[-1] if msg else f"{self.cli} failed")

    def _json(self, args: list[str]):
        try:
            return json.loads(self._run(args))
        except ValueError as e:
            raise ForgeUnreadable(f"{self.cli} gave unparseable JSON ({e})") from None

    def _lines(self, args: list[str]) -> list[dict]:
        try:
            return [json.loads(ln) for ln in self._run(args).splitlines() if ln.strip()]
        except ValueError as e:
            raise ForgeUnreadable(f"{self.cli} gave unparseable JSON ({e})") from None

    def auth_scope(self) -> list[str]:
        return []

    def missing(self) -> str | None:
        """Why the CLI cannot be run at all, or None."""
        from shutil import which
        return None if which(self.cli) else f"{self.cli} is not installed"

    def check(self) -> str | None:
        """Why this forge cannot be asked at all (no CLI, not authenticated), or None."""
        gone = self.missing()
        if gone:
            return gone
        rc, _, _ = self.call(["auth", "status", *self.auth_scope()], timeout=30)
        return None if rc == 0 else f"{self.cli} is not authenticated ({self.cli} auth login)"


class GitHub(_CLI):
    """Today's `gh` calls, moved (TD-103) — the argv of each is what the caller ran before,
    so the suites' `gh` shims answer them unchanged."""

    name = "github"
    cli = "gh"
    # A squash's subject ends "(#N)"; a merge commit's starts "Merge pull request #N".
    # The §4.6 audit's fallback when the merged list is unreadable; the list is the source.
    subject_re = re.compile(r"\(#\d+\)$|^Merge pull request #\d+ ")
    # cadence.md §4's merge settings, in the API's names: the settings line and
    # adopt_repo_settings.sh both read this one copy.
    settings_wanted = {"allow_squash_merge": True, "allow_merge_commit": False,
                       "allow_rebase_merge": False, "delete_branch_on_merge": True}
    auto_delete = "delete_branch_on_merge"

    @staticmethod
    def ref(n) -> str:
        return f"#{n}"

    @staticmethod
    def retarget_hint(n, base: str) -> str:
        return f"`gh pr edit {n} --base {base}`"

    @staticmethod
    def landed_pr_hint(branch: str) -> str:
        return f"gh pr list --head {branch} --state merged"

    # -- PRs ---------------------------------------------------------------------------------

    @classmethod
    def record(cls, p: dict) -> dict:
        """gh's PR JSON as the neutral record (only the fields gh was asked for are filled)."""
        n = p.get("number")
        return {
            "number": n,
            "ref": cls.ref(n),
            "url": p.get("url"),
            "state": str(p.get("state") or "").lower(),   # open | merged | closed
            "title": p.get("title"),
            "body": p.get("body"),
            "base": p.get("baseRefName"),
            "head": p.get("headRefName"),
            "head_sha": p.get("headRefOid"),
            "merged_at": p.get("mergedAt"),
            "merge_sha": (p.get("mergeCommit") or {}).get("oid"),
            "files": [f.get("path") for f in p.get("files") or []],
            "updated_at": p.get("updatedAt"),
        }

    def pr(self, n) -> dict:
        return self.record(self._json(["pr", "view", str(n), "--json", PR_FIELDS]))

    def prs_for_branch(self, branch: str, limit: int = 5) -> list[dict]:
        prs = self._json(["pr", "list", "--head", branch, "--state", "all", "--limit", str(limit),
                          "--json", "number,state"])
        return [self.record(p) for p in prs]

    def merged_since(self, when: str, limit: int) -> list[dict]:
        prs = self._json(["pr", "list", "--state", "merged", "--search", f"merged:>={when}",
                          "--limit", str(limit), "--json", "number,mergeCommit"])
        return [self.record(p) for p in prs]

    def open_prs(self, limit: int, timeout: float) -> list[dict]:
        """Open PRs, oldest first (so a limit can never drop the stalest), each with
        created_at, draft and its comments as {trusted, body} — trusted when the author has
        a say in the repo."""
        # oldest first, so the limit can never drop the stalest PR — the one TD-052 is for
        prs = json.loads(self._run(["pr", "list", "--state", "open", "--limit", str(limit),
                                    "--search", "sort:created-asc",
                                    "--json", "number,title,createdAt,isDraft,comments"],
                                   timeout=timeout, env=_QUIET) or "[]")
        out = []
        for p in prs:
            rec = self.record(p)
            rec["created_at"] = p.get("createdAt")
            rec["draft"] = bool(p.get("isDraft"))
            rec["comments"] = [
                {"trusted": c.get("authorAssociation") in ("OWNER", "MEMBER", "COLLABORATOR"),
                 "body": c.get("body")}
                for c in p.get("comments") or []]
            out.append(rec)
        return out

    def comments(self, n) -> list[dict]:
        """[{author, created_at, updated_at, body}], oldest first as the forge lists them."""
        raw = self._json(["api", "--paginate", f"repos/{{owner}}/{{repo}}/issues/{n}/comments"])
        return [{"author": (c.get("user") or {}).get("login"), "created_at": c.get("created_at"),
                 "updated_at": c.get("updated_at"), "body": c.get("body")} for c in raw]

    def commit_parents(self, sha: str) -> int:
        return len(self._json(["api", f"repos/{{owner}}/{{repo}}/commits/{sha}"]).get("parents", []))

    # -- CI ----------------------------------------------------------------------------------

    def check_runs(self, sha: str) -> list[dict]:
        """[{name, status, conclusion}] for every check run on sha."""
        # object-shaped endpoint: --paginate walks the pages, --jq flattens each page's runs to one object per line
        return self._lines(["api", "--paginate",
                            f"repos/{{owner}}/{{repo}}/commits/{sha}/check-runs?per_page=100",
                            "--jq", ".check_runs[]"])

    def ci_runs_registered(self, sha: str) -> list[dict]:
        """[{status, conclusion}] of the workflow runs registered for sha — a run may exist
        before its check runs do (TD-079)."""
        return self._lines(["api", f"repos/{{owner}}/{{repo}}/actions/runs?head_sha={sha}&per_page=20",
                            "--jq", ".workflow_runs[] | {status, conclusion}"])

    def ci_active_workflows(self) -> int:
        return int(self._run(["api", "repos/{owner}/{repo}/actions/workflows", "--jq",
                              '[.workflows[] | select(.state == "active")] | length']).strip() or 0)

    # -- settings ----------------------------------------------------------------------------

    def repo_settings(self, slug: str) -> tuple[int, str, str]:
        """(rc, the repo's JSON, stderr) — the settings line reads the fields it wants."""
        return self.call(["api", f"repos/{slug}"])

    def settings_lines(self, slug: str) -> str:
        """One "name=value" line per wanted setting, as the API gives it (null unreadable)."""
        jq = ",\n".join(f'        "{k}=\\(.{k})"' for k in self.settings_wanted)
        return self._run(["api", f"repos/{slug}", "--jq", "\n" + jq])

    def patch_settings(self, slug: str, pairs: list[str]) -> None:
        args = ["api", "-X", "PATCH", f"repos/{slug}"]
        for p in pairs:
            args += ["-F", p]
        self._run(args)

    # -- the remote tier (budgeted; each returns (rc, out, err) as the tier reads it) --------

    def whoami(self) -> tuple[int, str, str]:
        return self.call(["api", "user", "--jq", ".login"])

    def owners(self) -> tuple[int, str, str]:
        return self.call(["api", "user/orgs", "--jq", ".[].login"])

    def list_repos(self, owner: str, limit: int) -> tuple[int, str, str]:
        """JSON [{name, archived}] on rc 0."""
        rc, out, err = self.call(["repo", "list", owner, "--json", "nameWithOwner,isArchived",
                                  "--limit", str(limit)])
        if rc == 0:
            try:
                out = json.dumps([{"name": r["nameWithOwner"], "archived": bool(r.get("isArchived"))}
                                  for r in json.loads(out)])
            except (ValueError, KeyError, TypeError):
                pass   # the caller reports it unparseable
        return rc, out, err

    def read_file(self, repo: str, path: str) -> tuple[int, str, str]:
        """The file's text on rc 0; rc NOT_FOUND when the forge says there is none."""
        rc, out, err = self.call(["api", f"repos/{repo}/contents/{path}",
                                  "-H", "Accept: application/vnd.github.raw"])
        return (NOT_FOUND if rc > 0 and "HTTP 404" in err else rc), out, err


# --- GitLab -----------------------------------------------------------------------------


# The squash template the cadence wants (cadence.md §4.2, read 2026-10-13): the subject ends
# "(!N)", the body carries every commit's message, trailers included. `%{co_authored_by}`
# would name the commits' authors, not their Co-Authored-By: lines, so it is not used.
GITLAB_SQUASH_TEMPLATE = "%{title} (%{local_reference})\n\n%{all_commits}"
# A pipeline's status, as a check run's (status, conclusion).
_PIPELINE = {"success": ("completed", "success"), "failed": ("completed", "failure"),
             "canceled": ("completed", "cancelled"), "skipped": ("completed", "skipped"),
             "manual": ("completed", "action_required")}


class GitLab(_CLI):
    """`glab` against GitLab (TD-104), built on what a real project returned (glab 1.123.0,
    gitlab.com, 2026-10-13: the plan's *GitLab, as read*). Every call is `glab api` against
    the REST endpoints with the project named outright (`projects/<group%2Frepo>`, on
    `--hostname`), never glab's cwd placeholders, so a call answers for the repo the slug
    names wherever it runs."""

    name = "gitlab"
    cli = "glab"
    # The cadence's template marks a squash "(!N)"; a merge_method=merge project's merge
    # commit is "Merge branch '…' into '…'", which a local merge also writes, so it is not
    # matched here — it is in the merged list whenever the forge can be read.
    subject_re = re.compile(r"\(!\d+\)$")
    settings_wanted = {"merge_method": "ff", "squash_option": "always",
                       "remove_source_branch_after_merge": True,
                       "squash_commit_template": GITLAB_SQUASH_TEMPLATE}
    auto_delete = "remove_source_branch_after_merge"
    not_squash_hint = (" — a merge_method = merge project lands a merge commit around the squash; "
                       "the cadence wants merge_method ff with squash_option always "
                       "(scripts/adopt_repo_settings.sh)")

    def __init__(self, slug: str | None = None, **kw):
        super().__init__(slug=slug, **kw)
        host, _, path = (slug or "").partition("/")
        self.host, self.path = host or "gitlab.com", path
        self.project = f"projects/{quote(path, safe='')}"

    @staticmethod
    def ref(n) -> str:
        return f"!{n}"

    @staticmethod
    def retarget_hint(n, base: str) -> str:
        return f"`glab mr update {n} --target-branch {base}`"

    @staticmethod
    def landed_pr_hint(branch: str) -> str:
        return f"glab mr list --source-branch {branch} --merged"

    def auth_scope(self) -> list[str]:
        return ["--hostname", self.host]

    def _api(self, endpoint: str, *extra: str) -> list[str]:
        return ["api", "--hostname", self.host, endpoint, *extra]

    def _get(self, endpoint: str, paginate: bool = False):
        if not paginate:
            return self._json(self._api(endpoint))
        try:
            return _pages(self._run(self._api(endpoint, "--paginate")))
        except ValueError as e:
            raise ForgeUnreadable(f"{self.cli} gave unparseable JSON ({e})") from None

    # -- MRs ---------------------------------------------------------------------------------

    @classmethod
    def record(cls, m: dict) -> dict:
        """GitLab's MR JSON as the neutral record. Under ff + always-squash the landed commit
        is squash_commit_sha and merge_commit_sha is empty ("" from one MR, null in a list)."""
        n = m.get("iid")
        state = str(m.get("state") or "")
        return {
            "number": n,
            "ref": cls.ref(n),
            "url": m.get("web_url"),
            "state": {"opened": "open", "locked": "open"}.get(state, state),  # merged | closed
            "title": m.get("title"),
            "body": m.get("description"),
            "base": m.get("target_branch"),
            "head": m.get("source_branch"),
            "head_sha": m.get("sha"),
            "merged_at": m.get("merged_at"),
            "merge_sha": m.get("merge_commit_sha") or m.get("squash_commit_sha") or None,
            "files": [],
            "updated_at": m.get("updated_at"),
            "created_at": m.get("created_at"),
            "draft": bool(m.get("draft")),
        }

    def pr(self, n) -> dict:
        rec = self.record(self._get(f"{self.project}/merge_requests/{int(n)}"))
        diffs = self._get(f"{self.project}/merge_requests/{int(n)}/diffs?per_page=100", paginate=True)
        rec["files"] = [d.get("new_path") for d in diffs or []]
        return rec

    def prs_for_branch(self, branch: str, limit: int = 5) -> list[dict]:
        q = urlencode({"source_branch": branch, "state": "all", "order_by": "created_at",
                       "sort": "desc", "per_page": limit})
        return [self.record(m) for m in self._get(f"{self.project}/merge_requests?{q}")]

    def merged_since(self, when: str, limit: int) -> list[dict]:
        """The MRs merged at or after `when`. The API filters on updated_after (a merge updates
        the MR, so nothing merged in the window is missed); merged_at is filtered here."""
        q = urlencode({"state": "merged", "updated_after": when, "order_by": "updated_at",
                       "sort": "desc", "per_page": 100})
        cut = _ts(when)
        got = [self.record(m) for m in self._get(f"{self.project}/merge_requests?{q}", paginate=True)]
        return [r for r in got if cut is None or (_ts(r["merged_at"]) or cut) >= cut][:limit]

    def pr_for_branch_line(self, branch: str) -> tuple[int, str, str]:
        """sync-all.sh's answer: "<STATE> <url>" of the branch's newest MR, or gh's own words
        for none, which sync-all reads as "a failed earlier run"."""
        try:
            prs = self.prs_for_branch(branch, 1)
        except ForgeUnreadable as e:
            return 1, "", f"{e}\n"
        if not prs:
            return 1, "", f'no pull requests found for branch "{branch}" (no merge request on {self.host})\n'
        return 0, f"{prs[0]['state'].upper()} {prs[0]['url']}\n", ""

    def create_pr(self, title: str, body: str) -> tuple[int, str, str]:
        """Open an MR from the current branch (pushed already) onto the project's default branch."""
        r = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=self.cwd, check=False,
                           capture_output=True, text=True, timeout=10)
        branch = r.stdout.strip()
        if r.returncode != 0 or branch in ("", "HEAD"):
            return 1, "", "not on a branch\n"
        try:
            base = self._get(self.project).get("default_branch") or "main"
            m = self._json(self._api(f"{self.project}/merge_requests", "-X", "POST",
                                     "-f", f"source_branch={branch}", "-f", f"target_branch={base}",
                                     "-f", f"title={title}", "-f", f"description={body}",
                                     "-F", "remove_source_branch=true"))
        except ForgeUnreadable as e:
            return 1, "", f"{e}\n"
        return 0, f"{m.get('web_url')}\n", ""

    def open_prs(self, limit: int, timeout: float) -> list[dict]:
        """Open MRs, oldest first, each with created_at, draft and its notes as {trusted, body}
        — trusted when the author is a Developer or above on the project. The notes cost a
        call per MR that has any, so they are read only while the timeout lasts; an MR past
        it keeps an empty list (no "reviewed" mark, never a wrong one)."""
        end = time.monotonic() + timeout
        q = urlencode({"state": "opened", "order_by": "created_at", "sort": "asc", "per_page": limit})
        mrs = json.loads(self._run(self._api(f"{self.project}/merge_requests?{q}"), timeout=timeout,
                                   env=_QUIET_GLAB) or "[]")
        out, members = [], None
        for m in mrs:
            rec = self.record(m)
            rec["comments"] = []
            left = end - time.monotonic()
            if m.get("user_notes_count") and left > 0.5:
                try:
                    if members is None:  # the first 100 only: anyone past them reads as untrusted
                        members = {u.get("username"): u.get("access_level") or 0 for u in json.loads(
                            self._run(self._api(f"{self.project}/members/all?per_page=100"),
                                      timeout=left, env=_QUIET_GLAB) or "[]")}
                    rec["comments"] = [
                        {"trusted": members.get(c["author"], 0) >= 30, "body": c["body"]}
                        for c in self.comments(m.get("iid"), timeout=end - time.monotonic())]
                except (ForgeUnreadable, ValueError, TypeError, AttributeError):
                    pass
            out.append(rec)
        return out

    def comments(self, n, timeout: float | None = None) -> list[dict]:
        """[{author, created_at, updated_at, body}] of the MR's notes, oldest first, GitLab's
        own events (system notes) left out. A token that cannot read notes gets 403 here —
        "cannot read", never "no review" (…/discussions would answer [] instead)."""
        if timeout is not None and timeout <= 0:
            raise ForgeUnreadable("out of time before the notes were read")
        try:
            raw = _pages(self._run(self._api(
                f"{self.project}/merge_requests/{int(n)}/notes?sort=asc&order_by=created_at&per_page=100",
                "--paginate"), timeout=timeout))
        except ValueError as e:
            raise ForgeUnreadable(f"{self.cli} gave unparseable JSON ({e})") from None
        return [{"author": (c.get("author") or {}).get("username"), "created_at": c.get("created_at"),
                 "updated_at": c.get("updated_at"), "body": c.get("body")}
                for c in raw if not c.get("system")]

    def commit_parents(self, sha: str) -> int:
        return len(self._get(f"{self.project}/repository/commits/{sha}").get("parent_ids") or [])

    # -- CI: pipelines -------------------------------------------------------------------

    def check_runs(self, sha: str) -> list[dict]:
        """[{name, status, conclusion}], one per pipeline on sha (the push's and the MR's).
        A pipeline that failed with no jobs never ran (a new gitlab.com account's runner
        verification read this way, 2026-10-13): its conclusion is "not_run", which the ci
        row names as no evidence, never as a red build. A broken .gitlab-ci.yml also fails
        with no jobs, so the pipeline's own yaml_errors is read first: set, it stays red."""
        out = []
        for p in self._get(f"{self.project}/pipelines?sha={sha}&per_page=100"):
            status, conclusion = _PIPELINE.get(p.get("status"), (p.get("status"), None))
            if p.get("status") == "failed" and not self._get(
                    f"{self.project}/pipelines/{p.get('id')}/jobs?include_retried=true&per_page=1"):
                try:
                    broken = self._get(f"{self.project}/pipelines/{p.get('id')}").get("yaml_errors")
                except (ForgeUnreadable, AttributeError):
                    broken = None
                conclusion = "failure" if broken else "not_run"
            out.append({"name": f"pipeline {p.get('id')} ({p.get('source')})",
                        "status": status, "conclusion": conclusion})
        return out

    @staticmethod
    def ci_runs_registered(sha: str) -> list[dict]:
        """GitLab creates the pipeline with the push (both were there when the MR was read), so
        there is no registered-but-not-listed run to wait for: check_runs lists it, pending."""
        return []

    @staticmethod
    def ci_active_workflows() -> int:
        return 0

    # -- settings ----------------------------------------------------------------------------

    def _project_for(self, slug: str) -> "GitLab":
        return self if slug.lower() == f"{self.host}/{self.path}".lower() else GitLab(
            slug=slug, cwd=self.cwd, spent=self.spent, per_call=self.per_call, total=self.total)

    def repo_settings(self, slug: str) -> tuple[int, str, str]:
        """(rc, the project's JSON, stderr). A key the JSON lacks is one this token cannot see."""
        g = self._project_for(slug)
        return g.call(g._api(g.project))

    def settings_lines(self, slug: str) -> str:
        rc, out, err = self.repo_settings(slug)
        if rc != 0:
            msg = (err or out).strip()
            raise ForgeUnreadable(msg.splitlines()[-1] if msg else f"{self.cli} failed")
        try:
            got = json.loads(out)
        except ValueError as e:
            raise ForgeUnreadable(f"{self.cli} gave unparseable JSON ({e})") from None
        # null is "this token cannot see it" (adopt_repo_settings.sh's word); a key that is
        # there but null (the squash template, until set) is "unset": drift, not unreadable
        return "".join(f"{k}={'null' if k not in got else 'unset' if got[k] is None else show(got[k])}\n"
                       for k in self.settings_wanted)

    def patch_settings(self, slug: str, pairs: list[str]) -> None:
        g = self._project_for(slug)
        args = g._api(g.project, "-X", "PUT")
        for p in pairs:
            k, _, v = p.partition("=")
            v = unshow(v)
            args += ["-F", f"{k}={str(v).lower()}"] if isinstance(v, bool) else ["-f", f"{k}={v}"]
        g._run(args)


# GitLab's notes call runs from the SessionStart hook too: glab must never prompt there.
_QUIET_GLAB = {"NO_PROMPT": "true"}


def _ts(s):
    """An ISO time as an aware datetime; a bare date or a zoneless time reads as UTC, so
    `--since 2026-10-01` compares with GitLab's zoned merged_at instead of raising."""
    from datetime import datetime, timezone
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00")) if s else None
    except ValueError:
        return None
    return t.replace(tzinfo=timezone.utc) if t and t.tzinfo is None else t


def _pages(text: str) -> list:
    """`glab api --paginate` output as one list. How glab 1.123 joins pages was not read
    (TD-104's facts came from one-page answers); gh writes them back to back (`[..][..]`),
    so each JSON value is decoded in turn and the lists are joined either way."""
    out, dec, i, text = [], json.JSONDecoder(), 0, text.strip()
    while i < len(text):
        v, i = dec.raw_decode(text, i)
        out += v if isinstance(v, list) else [v]
        while i < len(text) and text[i].isspace():
            i += 1
    return out


def show(v) -> str:
    """A setting's value as one `name=value` line carries it: true/false/null, a plain word
    as is, anything with a newline, a quote or a space as a JSON string (GitLab's template)."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    v = str(v)
    return v if re.fullmatch(r"[A-Za-z0-9_.:-]+", v) else json.dumps(v)


def unshow(v: str):
    """show()'s inverse: true/false as booleans, a JSON string as its text, else the word."""
    if v in ("true", "false"):
        return v == "true"
    if v.startswith('"'):
        try:
            return json.loads(v)
        except ValueError:
            pass
    return v


def repo_key(line: str) -> tuple[str, str] | None:
    """(host, owner/repo) of a machine-scope list line (remote_repos.txt, no_auto_delete.txt):
    `host/owner/repo` (`host/group/sub/repo` on GitLab), or the older `owner/repo`, which
    reads as github.com. None when the line is neither."""
    parts = line.strip().strip("/").split("/")
    if len(parts) == 2 and all(parts):
        return "github.com", "/".join(parts).lower()
    if len(parts) >= 3 and all(parts) and "." in parts[0]:
        return parts[0].lower(), "/".join(parts[1:]).lower()
    return None


# --- CLI (adopt_repo_settings.sh, sync-all.sh) -------------------------------------------


def _for_slug(slug: str) -> "GitHub | GitLab":
    key = repo_key(slug)
    if key is None:
        raise ForgeUnreadable(f"{slug!r} is neither owner/repo nor host/owner/repo")
    # the checkout's own origin is classified with its forge setting, so a GitLab host not
    # named gitlab.* (forge = "gitlab") is still GitLab to adopt_repo_settings.sh
    kind, here = origin_forge(Path("."))
    if is_gitlab_host(key[0]) or (kind == "gitlab" and here and here.lower() == f"{key[0]}/{key[1]}"):
        return GitLab(slug=f"{key[0]}/{key[1]}")
    if key[0] != "github.com" or key[1].count("/") != 1:
        raise ForgeUnreadable(forge_unread_line(key[0]))
    return GitHub(slug=key[1])


def origin_slug(root: "Path | str") -> str:
    """The SLUG of the repo at root, from origin (never `gh repo view`, which prefers an
    upstream remote, TD-058): owner/repo on github.com, host/path on GitLab."""
    kind, slug = origin_forge(Path(root))
    if kind == "github" and slug:
        host, _ = _origin(Path(root))
        return slug if host in (None, "github.com") else f"{host}/{slug}"
    if kind == "gitlab" and slug:
        return slug
    if kind == "other":
        raise ForgeUnreadable(forge_unread_line(slug or "?"))
    raise ForgeUnreadable("origin names no repo the forge can be asked about")


def _passthrough(rc: int, out: str, err: str) -> int:
    sys.stdout.write(out)
    sys.stderr.write(err)
    return 2 if rc < 0 else rc


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="the forge adapter (TD-103)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    b = sub.add_parser("pr-for-branch")
    b.add_argument("branch")
    c = sub.add_parser("create-pr")
    c.add_argument("--title", required=True)
    c.add_argument("--body", required=True)
    h = sub.add_parser("has-cli")
    h.add_argument("slug", nargs="?")
    sub.add_parser("origin-slug")
    w = sub.add_parser("wanted")
    w.add_argument("slug")
    w.add_argument("--no-auto-delete", action="store_true")
    s = sub.add_parser("repo-settings")
    s.add_argument("slug")
    p = sub.add_parser("patch-settings")
    p.add_argument("slug")
    p.add_argument("pairs", nargs="+")
    a = ap.parse_args(argv)
    if a.cmd == "origin-slug":
        try:
            print(origin_slug("."))
        except ForgeUnreadable as e:
            print(e, file=sys.stderr)
            return 2
        return 0
    try:
        f = backend(".") if not getattr(a, "slug", None) else _for_slug(a.slug)
    except ForgeUnreadable as e:
        print(e, file=sys.stderr)
        return 2
    if a.cmd == "has-cli":
        gone = f.missing()
        if gone:
            print(gone, file=sys.stderr)
            return 2
        return 0
    if a.cmd == "check":
        why = f.check()
        if why:
            print(why, file=sys.stderr)
            return 2
        return 0
    if a.cmd == "wanted":
        sys.stdout.write("".join(f"{k}={show(v)}\n" for k, v in f.settings_wanted.items()
                                 if not (a.no_auto_delete and k == f.auto_delete)))
        return 0
    if isinstance(f, GitLab):
        if a.cmd == "pr-for-branch":
            return _passthrough(*f.pr_for_branch_line(a.branch))
        if a.cmd == "create-pr":
            return _passthrough(*f.create_pr(a.title, a.body))
    if a.cmd == "pr-for-branch":
        return _passthrough(*f.call(["pr", "view", a.branch, "--json", "url,state",
                                     "-q", '.state + " " + .url']))
    if a.cmd == "create-pr":
        return _passthrough(*f.call(["pr", "create", "--title", a.title, "--body", a.body]))
    key = repo_key(a.slug)   # _for_slug has read it
    slug = f"{key[0]}/{key[1]}" if isinstance(f, GitLab) else key[1]
    try:
        if a.cmd == "repo-settings":
            sys.stdout.write(f.settings_lines(slug))
        else:
            f.patch_settings(slug, a.pairs)
    except ForgeUnreadable as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
