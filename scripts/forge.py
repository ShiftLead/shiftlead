#!/usr/bin/env python3
# SYNCED FILE — canonical copy: ShiftLead/dev-cadence files/scripts/forge.py
# Edit it there and re-run sync.sh; an edit made in a consumer repo is overwritten (sync.sh --verify detects one).
"""The forge adapter (TD-103, the decision in TD-097): every question the PR tooling asks a
forge goes through here, in one neutral shape, so a second forge is one more backend and
never a branch in each caller.

Callers: check_cadence.py (the rows), nudge_user_attention.py (the open-PR line, the settings
line, the remote tier), adopt_repo_settings.sh and sync-all.sh (through the CLI below). No
other script runs the forge's CLI (`gh`): a new question is an operation here first.

Which forge (cadence.md §9.18, the `forge` key): `auto` (the default) reads origin's host —
github.com is GitHub, anything else is a forge the cadence cannot read yet, never GitHub by
default; `github` says a host under another name (GitHub Enterprise) is GitHub; `gitlab`
is a recorded choice whose backend is TD-104, and reads as "PRs not checked" until then;
`none` says there is no PR API at all (TD-105): check_cadence.py --since reads the review
line from each commit's body (NoForge), and every other caller says "no forge" once. An origin that names no host (a local path, file://) is read with the
GitHub backend, as before TD-103: `gh` then answers or fails on its own.

Every operation raises ForgeUnreadable(reason) when it cannot ask — no CLI, not
authenticated, offline, an unsupported forge — and a caller turns that into "cannot see",
never into an empty answer (cadence.md §7). The backend shells out to the forge's own CLI
and never holds a credential.

    forge.py check                     exit 0 when the forge here can be read (its CLI present
                                       and authenticated), else the reason, exit 2
    forge.py pr-for-branch BRANCH      "<STATE> <url>" of BRANCH's PR (STATE as the forge says it);
                                       the CLI's own error and exit code when it has none
    forge.py create-pr --title T --body B
                                       open a PR from the current branch; prints its url
    forge.py has-cli [SLUG]            exit 0 when the forge's CLI is installed, else the reason, exit 2
    forge.py repo-settings SLUG        one "name=value" line per merge setting the cadence wants
    forge.py patch-settings SLUG name=value…
                                       write those settings

SLUG is `owner/repo` (github.com) or `host/owner/repo`, and picks the forge itself; the other
commands read the forge of the repo in the current directory.

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


def _slug(path: str) -> str | None:
    slug = re.sub(r"\.git$", "", path.strip("/")).lower()
    return slug if re.fullmatch(r"[^/]+/[^/]+", slug) else None


def origin_forge(root: Path) -> tuple[str, str | None]:
    """Classify a repo's origin once (TD-098, moved here by TD-103): ("github", "owner/repo")
    for GitHub; ("other", host) for a forge the cadence cannot read yet (GitLab, Gitea, a
    GitHub Enterprise host not named by `forge = "github"` — TD-104), or ("other", "none")
    for `forge = "none"` (TD-105); ("none", None) for no origin, or one that names no host (a
    local path, a bare file:// clone: what every test fixture uses) — there the caller
    behaves as before. A detector told "other" says it could not look, never stays quiet:
    an empty answer must mean nothing there (cadence.md §7)."""
    want = setting(root)
    host, path = _origin(Path(root))
    if want == "none":
        return "other", "none"
    if want not in KNOWN:
        return "other", f"!{want}"
    if want == "gitlab":
        return "other", host or "gitlab"
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


def backend(root: "Path | str | None" = None, **kw) -> "GitHub":
    """The backend for the repo at root (default: the current directory's). Raises
    ForgeUnreadable with the "PRs not checked" line for a forge with no backend."""
    kind, host = origin_forge(Path(root or "."))
    if kind == "other":
        raise ForgeUnreadable(forge_unread_line(host or "?"))
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


class GitHub:
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

    def __init__(self, slug: str | None = None, cwd: "Path | str | None" = None,
                 spent: dict | None = None, per_call: float = 60.0, total: float | None = None):
        self.slug, self.cwd = slug, cwd
        # The remote tier's budget (nudge_user_attention.py): elapsed time is booked into
        # spent["t"]; a call past `total` is not made, and spent["hit"] says so.
        self.spent, self.per_call, self.total = spent, per_call, total

    @staticmethod
    def ref(n) -> str:
        return f"#{n}"

    @staticmethod
    def retarget_hint(n, base: str) -> str:
        return f"`gh pr edit {n} --base {base}`"

    @staticmethod
    def landed_pr_hint(branch: str) -> str:
        return f"gh pr list --head {branch} --state merged"

    # -- the one place gh runs -------------------------------------------------------------

    def call(self, args: list[str], timeout: float | None = None,
             env: dict | None = None) -> tuple[int, str, str]:
        """(rc, stdout, stderr) of one gh call; rc -1 timeout, -2 budget exhausted (not
        attempted), -3 gh not installed."""
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

    def missing(self) -> str | None:
        """Why the CLI cannot be run at all, or None."""
        from shutil import which
        return None if which(self.cli) else f"{self.cli} is not installed"

    def check(self) -> str | None:
        """Why this forge cannot be asked at all (no CLI, not authenticated), or None."""
        gone = self.missing()
        if gone:
            return gone
        rc, _, _ = self.call(["auth", "status"], timeout=30)
        return None if rc == 0 else f"{self.cli} is not authenticated ({self.cli} auth login)"

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


def repo_key(line: str) -> tuple[str, str] | None:
    """(host, owner/repo) of a machine-scope list line (remote_repos.txt, no_auto_delete.txt):
    `host/owner/repo`, or the older `owner/repo`, which reads as github.com. None when the
    line is neither."""
    parts = line.strip().strip("/").split("/")
    if len(parts) == 2 and all(parts):
        return "github.com", "/".join(parts).lower()
    if len(parts) == 3 and all(parts) and "." in parts[0]:
        return parts[0].lower(), "/".join(parts[1:]).lower()
    return None


# --- CLI (adopt_repo_settings.sh, sync-all.sh) -------------------------------------------


def _for_slug(slug: str) -> GitHub:
    key = repo_key(slug)
    if key is None:
        raise ForgeUnreadable(f"{slug!r} is neither owner/repo nor host/owner/repo")
    if key[0] != "github.com":
        raise ForgeUnreadable(forge_unread_line(key[0]))
    return GitHub(slug=key[1])


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
    s = sub.add_parser("repo-settings")
    s.add_argument("slug")
    p = sub.add_parser("patch-settings")
    p.add_argument("slug")
    p.add_argument("pairs", nargs="+")
    a = ap.parse_args(argv)
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
    if a.cmd == "pr-for-branch":
        return _passthrough(*f.call(["pr", "view", a.branch, "--json", "url,state",
                                     "-q", '.state + " " + .url']))
    if a.cmd == "create-pr":
        return _passthrough(*f.call(["pr", "create", "--title", a.title, "--body", a.body]))
    slug = repo_key(a.slug)[1]   # _for_slug has read it
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
