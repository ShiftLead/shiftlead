#!/usr/bin/env bash
# vendor_ledgerboard.sh <tag> — take a ledgerboard release into ShiftLead's wheel (ADR 2026-10-12,
# *How ledgerboard is consumed*; TD-585, TD-1330).
#
# Copies, from ShiftLead/ledgerboard at <tag> (v2.3 or later: the package):
#   ledgerboard/*.py -> src/sessionorc/ledgerboard/   (the wheel's copy: container nodes have no scripts/)
#   fixtures/        -> tests/ledgerboard/            (tooling: never synced)
# and writes tests/ledgerboard/MANIFEST (the tag, its commit, a sha256 per file). The package also
# ships in agent-cadence, and this repo runs the pinned tree's (`docs/cadence.toml`'s [agent-cadence],
# TD-129; `agent-cadence path scripts/ledgerboard/__init__.py`) — run this in the agent-cadence bump PR
# that brings a new release, with the tag the pinned copy's header names, so
# tests/test_ledgerboard_fixtures.py (the two copies byte-equal) never merges half a release.
# Refuses a package file whose release header is not <tag>'s or not intact.
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
[ -f "$TMP/ledgerboard/__init__.py" ] \
    || { echo "ledgerboard at $tag is not the package (v2.3 or later): no ledgerboard/__init__.py" >&2; exit 1; }
for f in "$TMP"/ledgerboard/*.py; do
    head -1 "$f" | grep -q "^# ledgerboard $tag sha256:" \
        || { echo "ledgerboard/$(basename "$f") at $tag does not carry the $tag release header" >&2; exit 1; }
done
python3 "$TMP/fixtures/run.py" --check-header --module "$TMP/ledgerboard"
rm -rf "$ROOT/src/sessionorc/ledgerboard" "$ROOT/src/sessionorc/ledgerboard.py"
mkdir -p "$ROOT/src/sessionorc/ledgerboard"
install -m 644 "$TMP"/ledgerboard/*.py "$ROOT/src/sessionorc/ledgerboard/"
rm -rf "$ROOT/tests/ledgerboard"
cp -R "$TMP/fixtures" "$ROOT/tests/ledgerboard"
{
    echo "# Written by scripts/vendor_ledgerboard.sh — do not edit by hand."
    echo "tag: $tag"
    echo "commit: $commit"
    (cd "$ROOT" && find src/sessionorc/ledgerboard tests/ledgerboard -type f ! -name MANIFEST ! -path '*/__pycache__/*' | LC_ALL=C sort \
        | while read -r f; do echo "file: $f $(sha256sum "$f" | cut -d' ' -f1)"; done)
} > "$ROOT/tests/ledgerboard/MANIFEST"
python3 "$ROOT/tests/ledgerboard/run.py" --module "$ROOT/src/sessionorc/ledgerboard"
echo "vendored ledgerboard $tag ($commit) into the wheel — commit it with the agent-cadence bump PR that brought it"
