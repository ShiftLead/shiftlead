#!/usr/bin/env bash
# vendor_ledgerboard.sh <tag> — take a ledgerboard release into ShiftLead's wheel (ADR 2026-10-12,
# *How ledgerboard is consumed*; TD-585).
#
# Copies, from ShiftLead/ledgerboard at <tag> (e.g. v1.0):
#   ledgerboard.py -> src/sessionorc/ledgerboard.py   (the wheel's copy: container nodes have no scripts/)
#   fixtures/      -> tests/ledgerboard/              (tooling: never synced)
# and writes tests/ledgerboard/MANIFEST (the tag, its commit, a sha256 per file). ledgerboard.py
# also ships in dev-cadence, and this repo runs the pinned tree's (`docs/cadence.toml`'s
# [dev-cadence], TD-129; `dev-cadence path scripts/ledgerboard.py`) — run this in the dev-cadence
# bump PR that brings a new release, with the tag the pinned copy's header names, so
# tests/test_ledgerboard_fixtures.py (the two copies byte-equal) never merges half a release.
# Refuses a module whose release header is not <tag>'s or not intact.
#
# LEDGERBOARD_SRC=<path to a ledgerboard clone> reads the tag from that clone instead of a
# fresh shallow clone of https://github.com/ShiftLead/ledgerboard.
set -euo pipefail
tag="${1:-}"
[[ "$tag" =~ ^v[0-9]+\.[0-9]+$ ]] || { echo "usage: vendor_ledgerboard.sh v<major>.<minor>" >&2; exit 2; }
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
if [ -n "${LEDGERBOARD_SRC:-}" ]; then
    git -C "$LEDGERBOARD_SRC" rev-parse -q --verify "refs/tags/$tag" >/dev/null \
        || { echo "no tag $tag in $LEDGERBOARD_SRC" >&2; exit 2; }
    git -C "$LEDGERBOARD_SRC" archive "$tag" | tar -x -C "$TMP"
    commit=$(git -C "$LEDGERBOARD_SRC" rev-parse "$tag^{commit}")
else
    git clone -q --depth 1 --branch "$tag" https://github.com/ShiftLead/ledgerboard.git "$TMP/src"
    commit=$(git -C "$TMP/src" rev-parse HEAD)
    mv "$TMP/src"/* "$TMP/" && rm -rf "$TMP/src"
fi
head -1 "$TMP/ledgerboard.py" | grep -q "^# ledgerboard $tag sha256:" \
    || { echo "ledgerboard.py at $tag does not carry the $tag release header" >&2; exit 1; }
python3 "$TMP/fixtures/run.py" --check-header --module "$TMP/ledgerboard.py"
install -m 644 "$TMP/ledgerboard.py" "$ROOT/src/sessionorc/ledgerboard.py"
rm -rf "$ROOT/tests/ledgerboard"
cp -R "$TMP/fixtures" "$ROOT/tests/ledgerboard"
{
    echo "# Written by scripts/vendor_ledgerboard.sh — do not edit by hand."
    echo "tag: $tag"
    echo "commit: $commit"
    (cd "$ROOT" && find src/sessionorc/ledgerboard.py tests/ledgerboard -type f ! -name MANIFEST | LC_ALL=C sort \
        | while read -r f; do echo "file: $f $(sha256sum "$f" | cut -d' ' -f1)"; done)
} > "$ROOT/tests/ledgerboard/MANIFEST"
python3 "$ROOT/tests/ledgerboard/run.py" --module "$ROOT/src/sessionorc/ledgerboard.py"
echo "vendored ledgerboard $tag ($commit) into the wheel — commit it with the sync PR that brought it"
