#!/usr/bin/env bash
# SYNCED FILE — canonical copy: ShiftLead/dev-cadence files/scripts/adopt_repo_settings.sh
# Edit it there and re-run sync.sh; an edit made in a consumer repo is overwritten (sync.sh --verify detects one).
# Check (default) or apply the GitHub or GitLab repo settings the cadence assumes (TD-034, TD-104).
#
#   adopt_repo_settings.sh [--check|--apply [--yes]] [--no-auto-delete] [owner/repo | host/group/repo]
#
# The cadence mandates squash merges (cadence.md §4) and recommends GitHub's
# "Automatically delete head branches" (§4, "Give the rule teeth"); on GitLab
# the same is merge_method ff + squash_option always, the delete-source-branch
# default and a squash_commit_template that keeps the trailers (§4.2). They live
# only in prose, and prose is not re-read: measured 2026-08-27, auto-delete was
# off in 2 of 4 repos on one machine's roster, and one repo still allowed
# merge-commit and rebase merges — 83 merged heads accumulated on a remote
# before anyone noticed. This script makes the claim checkable.
#
#   --check   (default) print each setting, current vs cadence; exit 1 on drift,
#             0 when clean, 2 when the forge cannot answer (not authenticated, offline,
#             not a GitHub repo or GitLab project). Mutates nothing.
#   --apply   write the drifted settings (GitHub PATCH, GitLab PUT), then re-read and
#             confirm (a few reads, since GitHub's read can lag the write, TD-107). Idempotent:
#             a clean repo is left untouched (no API write at all). Before the write it
#             asks, naming the repo, when stdin is a terminal; with no terminal it refuses
#             (exit 2, naming --yes) — the repo came from `origin`'s URL, and a write to
#             another repo's settings is not something to do on a guess (TD-058).
#   --yes     apply without asking: the flag unattended callers pass.
#
#   --no-auto-delete   leave "Automatically delete head branches" out of both the check
#             and the apply (a repo that stacks PRs, below).
#
# The repo defaults to the current checkout's `origin` remote, parsed from its URL — never
# `gh repo view`, which prefers an `upstream` remote and honours `gh repo set-default`, so
# in a fork clone it named the PARENT, and --apply would have patched a repo that is not
# this one (TD-058). A setting the forge reads back as null (a non-admin cannot see it) is
# "cannot verify", exit 2 — never drift.
#
# WHY THIS IS NOT A sync.sh STEP
# A sync tool mutating a remote's settings is the wrong shape, and auto-delete
# is a per-repo decision: it also deletes the branch a *stacked* PR is based
# on, and GitHub then retargets the stacked PR onto the default branch (§4).
# A repo that stacks PRs may want auto-delete off — run --check, read, decide.
set -u

MODE=check
REPO=""
NO_AUTO_DELETE=0
YES=0
for a in "$@"; do
    case "$a" in
        --check) MODE=check ;;
        --apply) MODE=apply ;;
        --no-auto-delete) NO_AUTO_DELETE=1 ;;
        --yes|-y) YES=1 ;;
        -h|--help) awk 'NR>3 && /^[^#]/ {exit} NR>3 {sub(/^# ?/, ""); print}' "$0"; exit 0 ;;
        -*) echo "unknown option: $a" >&2; exit 2 ;;
        *) REPO="$a" ;;
    esac
done

# Every forge call goes through forge.py beside this script (TD-103).
FORGE="$(dirname "$0")/forge.py"
if [ -z "$REPO" ]; then
    REPO="$(python3 -B "$FORGE" origin-slug 2>/dev/null)" || REPO=""
    if [ -z "$REPO" ]; then
        url="$(git remote get-url origin 2>/dev/null)" || url=""
        # never echo a credential an https origin may carry (user:token@)
        shown="$(printf '%s' "${url%/}" | sed -E 's#//[^@/]+@#//#')"
        echo "cannot verify: no owner/repo given and this checkout's origin is not a GitHub repo or a GitLab project (${shown:-no origin})" >&2; exit 2
    fi
    echo "(repo from this checkout's origin: $REPO)"
fi
if ! why="$(python3 -B "$FORGE" has-cli "$REPO" 2>&1)"; then
    echo "cannot verify: ${why:-forge.py failed}" >&2; exit 2
fi

# setting=cadence value, in the order the report prints them — the forge's own list (forge.py's
# settings_wanted: GitHub's four, GitLab's merge method, squash, delete-source and template)
args=(); [ "$NO_AUTO_DELETE" = 1 ] && args=(--no-auto-delete)
mapfile -t WANT < <(python3 -B "$FORGE" wanted "$REPO" "${args[@]}")
[ "${#WANT[@]}" -gt 0 ] || { echo "cannot verify: forge.py named no settings for $REPO" >&2; exit 2; }

read_settings() {  # -> one "name=value" line per setting, or non-zero
    python3 -B "$FORGE" repo-settings "$REPO" 2>/dev/null
}

compare() {  # prints the table from $1 (the read_settings output); sets DRIFT (names) and PAIRS (name=value)
    DRIFT=(); PAIRS=()
    for w in "${WANT[@]}"; do
        name="${w%%=*}"; want="${w#*=}"
        have="$(printf '%s\n' "$1" | sed -n "s/^$name=//p")"
        if [ "$have" = "$want" ]; then mark="ok"
        else mark="DRIFT"; DRIFT+=("$name"); PAIRS+=("$name=$want"); fi
        printf '  %-6s %-32s %-6s (cadence: %s)\n' "$mark" "$name" "${have:-?}" "$want"
    done
}

current="$(read_settings)"
if [ -z "$current" ]; then
    echo "cannot verify: reading $REPO's settings failed (not authenticated, offline, or no such repo)" >&2; exit 2
fi
unreadable="$(printf '%s\n' "$current" | sed -n 's/=null$//p' | tr '\n' ' ')"
if [ -n "$unreadable" ]; then
    echo "cannot verify: the forge read ${unreadable% } as null on $REPO — a non-admin cannot see these; ask an admin to run this" >&2; exit 2
fi
echo "$REPO — merge settings vs cadence.md §4:"
compare "$current"

if [ "${#DRIFT[@]}" -eq 0 ]; then
    echo "clean: nothing to change"; exit 0
fi
if [ "$MODE" = check ]; then
    echo "drift: re-run with --apply to set the cadence values (auto-delete has a stacked-PR caveat, §4)"
    exit 1
fi

if [ "$YES" = 0 ]; then
    if [ ! -t 0 ]; then
        echo "not applied: --apply writes $REPO's settings and asks first, but there is no terminal to ask — re-run with --yes to apply unattended" >&2
        exit 2
    fi
    printf 'apply these to %s? [y/N] ' "$REPO"
    read -r answer || answer=""
    case "$answer" in
        y|Y|yes|YES) ;;
        *) echo "not applied: nothing changed"; exit 1 ;;
    esac
fi
echo "applying to $REPO: ${PAIRS[*]}"
if ! python3 -B "$FORGE" patch-settings "$REPO" "${PAIRS[@]}" >/dev/null; then
    echo "apply failed: the write of $REPO's settings returned non-zero (need admin on the repo?)" >&2; exit 2
fi
# GitHub's read can lag its write: on a repo created minutes earlier the re-read right
# after a PATCH that worked still showed the old values (TD-107). So read again, a few
# times, before calling it a failure. ADOPT_READ_TRIES / ADOPT_READ_SLEEP (seconds) move
# the bounds; the tests set the sleep to 0.
tries="${ADOPT_READ_TRIES:-5}"; pause="${ADOPT_READ_SLEEP:-2}"
case "$tries" in ''|*[!0-9]*) tries=5 ;; esac   # a non-number would never end the loop below
n=0
while :; do
    n=$((n + 1))
    after="$(read_settings)"
    compare "$after" >/dev/null
    [ "${#DRIFT[@]}" -eq 0 ] && [ -n "$after" ] && break
    [ "$n" -ge "$tries" ] && break
    sleep "$pause"
done
echo "after:"
compare "$after"
if [ "${#DRIFT[@]}" -eq 0 ] && [ -n "$after" ]; then
    if [ "$n" -gt 1 ]; then echo "applied (after $n reads — GitHub's first read lagged the write)"; else echo "applied"; fi
    exit 0
fi
echo "apply did not stick: settings still drift after the write ($n reads, ${pause}s apart)" >&2; exit 1
