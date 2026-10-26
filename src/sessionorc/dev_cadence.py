#!/usr/bin/env python3
"""dev-cadence — the launcher: resolve a repo's pinned dev-cadence and exec it (TD-129).

    dev-cadence [-C <dir>] <word> [args…]    run <word> from the dev-cadence the repo pins
                                             (-C as git's: resolve and run in <dir>)
    dev-cadence --interface                  print this launcher's interface number

Installed once per machine, never per repo (docs/plans/2026-10-25-pinned-not-synced.md,
*Decision* 3):

    git clone <dev-cadence source> && git -C dev-cadence checkout <tag>
    install -m 755 dev-cadence/launcher/dev_cadence.py ~/.local/bin/dev-cadence

THIS FILE IS KEPT SMALL AND FROZEN. Every repo on the machine runs through it, and it is the one
piece of dev-cadence that is not pinned, so its only job is *resolve and exec*:

  1. the root — the main checkout's for the word `hook` (every worktree's hooks behave alike, and
     a branch that bumps the pin does not run its new pin in hooks before it merges), otherwise
     the checkout the command runs in (`git rev-parse --show-toplevel`), so a bump branch tests
     its own pin;
  2. the pin — `[dev-cadence]` in the root's docs/cadence.toml: `source` (a git URL) and `ref`
     (a full 40-hex commit, never a tag or branch: a moved tag would change what a repo runs
     without a PR). No pin and no dev-cadence tree at the root: not a cadence repo. dev-cadence's
     own repo has no pin and runs from its own tree;
  3. the tree — ${XDG_CACHE_HOME:-~/.cache}/dev-cadence/: one bare clone per source
     (sources/<sha256(source)[:16]>.git) and one read-only tree per commit (trees/<commit>/),
     made on first use under one cache-wide lock, checked out from the object database into a
     temp directory and renamed into place, so a tree that exists is whole. A tree is never
     updated in place. The fetch never prompts for a credential and gives up after NET_TIMEOUT;
  4. the exec — the tree's launcher/words.py with the word and its arguments, CADENCE_REPO_ROOT
     set to the root. What each word does is that pinned script's, never this file's.

Its interface is frozen: INTERFACE below, the pin's keys, and the cache's layout. A pinned tree
names the lowest interface it runs under in launcher/INTERFACE; an older launcher refuses it with
the install line. So any two launchers on one machine share one cache safely. Stdlib only;
Python >= 3.11 (tomllib).

Exit codes: the word's own once exec'd; 2 when nothing could be resolved (usage, no repo, no pin,
a bad pin, a fetch that failed, an interface this launcher is too old for).
"""
import fcntl
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

INTERFACE = 1
INSTALL = ("install a newer launcher: clone dev-cadence at its latest tag and "
           "`install -m 755 launcher/dev_cadence.py ~/.local/bin/dev-cadence`")
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
# a git URL (scheme://…), scp-like (host:path) or an absolute path — never a relative one, which
# would resolve against wherever the launcher happens to run
SOURCE_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S+|[^/\s:]+:\S+|/\S*")
NET_TIMEOUT = 300   # a clone or fetch, which holds the cache's lock
LOCK_WAIT = 600     # how long to wait for another launcher's clone or fetch
# inherited from a git hook, these would point every git call at the hook's repo
GIT_ENV_DROP = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
                "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_PREFIX")


class Refusal(Exception):
    pass


def _git(*args, cwd=None, check=True, env=None, timeout=None):
    e = {k: v for k, v in os.environ.items() if k not in GIT_ENV_DROP}
    e.update(GIT_TERMINAL_PROMPT="0", **(env or {}))   # a credential prompt would hold the lock forever
    try:
        p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False,
                           stdin=subprocess.DEVNULL, env=e, timeout=timeout)
    except FileNotFoundError:
        raise Refusal("git is not installed") from None
    except subprocess.TimeoutExpired:
        raise Refusal(f"git {' '.join(args)}: no answer in {timeout}s") from None
    if check and p.returncode != 0:
        raise Refusal(f"git {' '.join(args)}: {p.stderr.strip() or 'failed'}")
    return p


def find_root(word, start):
    """The checkout whose pin is read: the main checkout's for `hook`, else the one at start."""
    p = _git("rev-parse", "--show-toplevel", cwd=start, check=False)
    if p.returncode != 0:
        raise Refusal(f"not in a git checkout: {start}")
    root = p.stdout.strip()
    if word != "hook":
        return root
    common = _git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=root).stdout.strip()
    main = os.path.dirname(common) if os.path.basename(common) == ".git" else None
    if not main or not os.path.isdir(main):
        raise Refusal(f"cannot find the main checkout of {root} (its git dir is {common})")
    return main


def read_pin(root):
    """(source, ref) from [dev-cadence] in docs/cadence.toml, or None when there is no pin."""
    path = os.path.join(root, "docs", "cadence.toml")
    if not os.path.isfile(path):
        return None
    try:
        import tomllib
    except ImportError:
        raise Refusal("reading docs/cadence.toml needs Python >= 3.11 (tomllib)") from None
    try:
        with open(path, "rb") as f:
            table = tomllib.load(f).get("dev-cadence")
    except (OSError, ValueError) as e:
        raise Refusal(f"{path}: {e}") from None
    if table is None:
        return None
    if not isinstance(table, dict):
        raise Refusal(f"{path}: dev-cadence must be a table ([dev-cadence]), not {table!r}")
    source, ref = table.get("source"), table.get("ref")
    if not isinstance(source, str) or not SOURCE_RE.fullmatch(source.strip()):
        raise Refusal(f"{path}: [dev-cadence] source must be a git URL or an absolute path, not {source!r}")
    if not isinstance(ref, str) or not COMMIT_RE.fullmatch(ref):
        raise Refusal(f"{path}: [dev-cadence] ref must be a full 40-hex commit (never a tag or "
                      f"branch), not {ref!r}")
    return source.strip(), ref


def cache_dir():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "dev-cadence")


def _writable(path):
    """Give back write permission under path, so a half-made or stale tree can be removed."""
    if os.path.islink(path):
        return
    os.chmod(path, 0o755)
    for d, dirs, _files in os.walk(path):   # os.walk never descends a symlink; chmod would follow one
        for name in dirs:
            if not os.path.islink(os.path.join(d, name)):
                os.chmod(os.path.join(d, name), 0o755)


def _remove(path):
    if os.path.lexists(path):
        _writable(path)
        if os.path.islink(path):
            os.unlink(path)
        else:
            shutil.rmtree(path, ignore_errors=True)


def ensure_tree(source, ref):
    """The read-only tree of ref from source, made on first use."""
    cache = cache_dir()
    tree = os.path.join(cache, "trees", ref)
    if os.path.isdir(tree):
        return tree
    os.makedirs(os.path.join(cache, "trees"), exist_ok=True)
    os.makedirs(os.path.join(cache, "sources"), exist_ok=True)
    with open(os.path.join(cache, "lock"), "a") as lock:
        deadline = time.monotonic() + LOCK_WAIT
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    raise Refusal(f"another launcher has held {cache}/lock for {LOCK_WAIT}s") from None
                time.sleep(0.2)
        if os.path.isdir(tree):
            return tree
        for name in os.listdir(os.path.join(cache, "trees")):
            if name.startswith(".tmp-"):   # left by a run that died; nothing else holds the lock
                _remove(os.path.join(cache, "trees", name))
        bare = os.path.join(cache, "sources", hashlib.sha256(source.encode()).hexdigest()[:16] + ".git")
        if not os.path.isdir(bare):
            tmp = bare + ".tmp"
            _remove(tmp)
            _git("clone", "--bare", "--quiet", "--", source, tmp, timeout=NET_TIMEOUT)
            os.rename(tmp, bare)
        if _git("--git-dir", bare, "cat-file", "-e", ref + "^{commit}", check=False).returncode != 0:
            _git("--git-dir", bare, "fetch", "--quiet", "--", source,
                 "+refs/heads/*:refs/heads/*", "+refs/tags/*:refs/tags/*", timeout=NET_TIMEOUT)
            if _git("--git-dir", bare, "cat-file", "-e", ref + "^{commit}", check=False).returncode != 0:
                raise Refusal(f"commit {ref} is not in {source}")
        tmp = os.path.join(cache, "trees", f".tmp-{ref}-{os.getpid()}")
        os.makedirs(tmp)
        try:
            # from the object database through a scratch index — not `git archive`, whose
            # export-ignore and export-subst would make the tree differ from the commit
            with tempfile.TemporaryDirectory(dir=os.path.join(cache, "trees"), prefix=".tmp-index-") as ix:
                env = {"GIT_INDEX_FILE": os.path.join(ix, "index")}
                _git("--git-dir", bare, "read-tree", ref, env=env)
                _git("--git-dir", bare, "--work-tree", tmp, "checkout-index", "--all", env=env)
            for d, dirs, files in os.walk(tmp, topdown=False):
                for name in files:
                    f = os.path.join(d, name)
                    if not os.path.islink(f):
                        os.chmod(f, os.stat(f).st_mode & 0o555)
                for name in dirs:
                    if not os.path.islink(os.path.join(d, name)):
                        os.chmod(os.path.join(d, name), 0o555)
            os.sync()   # the rename below says the tree is whole; make that true after a crash too
            os.rename(tmp, tree)
            os.chmod(tree, 0o555)
        except BaseException:
            _remove(tmp)
            raise
    return tree


def resolve(word, start):
    """(root, tree): the root whose pin is read and the dev-cadence tree that runs."""
    root = find_root(word, start)
    pin = read_pin(root)
    if pin is None:
        if os.path.isfile(os.path.join(root, "launcher", "INTERFACE")):
            return root, root   # dev-cadence's own repo: no pin, it runs from its own tree
        raise Refusal(f"{root} is not a cadence repo: docs/cadence.toml has no [dev-cadence] pin "
                      "(source and ref)")
    return root, ensure_tree(*pin)


def check_interface(tree):
    path = os.path.join(tree, "launcher", "INTERFACE")
    try:
        with open(path, encoding="utf-8") as f:
            need = int(f.read().strip())
    except (OSError, ValueError):
        raise Refusal(f"{tree} has no readable launcher/INTERFACE: its commit predates the launcher, "
                      "so it cannot be run through it") from None
    if need > INTERFACE:
        raise Refusal(f"this pin needs launcher interface {need}; this launcher is {INTERFACE} — {INSTALL}")


def main(argv):
    start = os.getcwd()
    if argv[:1] == ["-C"]:
        if len(argv) < 2:
            raise Refusal("-C needs a directory")
        start, argv = argv[1], argv[2:]
        try:
            os.chdir(start)   # as git's -C: the word runs there too
        except OSError as e:
            raise Refusal(f"-C {start}: {e.strerror}") from None
        start = os.getcwd()
    if argv[:1] == ["--interface"]:
        print(INTERFACE)
        return 0
    if argv[:1] in (["-h"], ["--help"]):
        print(__doc__)
        return 0
    if not argv or argv[0].startswith("-"):
        print("usage: dev-cadence [-C <dir>] <word> [args…]  (`dev-cadence words` lists them)", file=sys.stderr)
        return 2
    root, tree = resolve(argv[0], start)
    check_interface(tree)
    env = dict(os.environ, CADENCE_REPO_ROOT=root)
    words = os.path.join(tree, "launcher", "words.py")
    os.execve(sys.executable, [sys.executable, words, *argv], env)
    return 2   # not reached


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Refusal as e:
        print(f"dev-cadence: {e}", file=sys.stderr)
        sys.exit(2)
    except OSError as e:   # a full disk, a cache it cannot write: still a refusal, never a traceback
        print(f"dev-cadence: {e}", file=sys.stderr)
        sys.exit(2)
