#!/usr/bin/env python3
"""Print a design section's dated record (design §4.4 *Two PRs' records merge in either order*, TD-1513).

The design's history is one file per ledger entry under `docs/history/` (`TD-<n>.md`, or
`<YYYY-MM-DD>-<branch>.md` for a PR that works for no entry), each `## §<section>` headings over
`- YYYY-MM-DD …` lines. `docs/design-history.md` holds every line written before the cut and is never
written again. `history.py <section>` prints the section's whole record from both: first the
`docs/history/` lines, newest first by their date, a tie by the file's name in plain string order, then
later in the file first; then the frozen file's heading or headings for the section, as written.

    scripts/history.py 6
    scripts/history.py 4.4a --grep relay
    scripts/history.py title

`grep -rn <text> docs/design-history.md docs/history/` stays the plain read.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

INDEX_BULLET = re.compile(r"^- \*\*§(\S+?)\*\*")
FILE_NAME = re.compile(r"^(TD-[1-9][0-9]*|[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9]+(?:-[a-z0-9]+)*)\.md$")
HEADING = re.compile(r"^## §(\S+)$")
DATED = re.compile(r"^- ([0-9]{4}-[0-9]{2}-[0-9]{2}) ")


def slug(branch: str) -> str:
    """A branch as a `docs/history/<YYYY-MM-DD>-<slug>.md` name writes it: lowercased, every character
    outside `[a-z0-9]` written `-`, runs collapsed (and none at either end)."""
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]", "-", branch.lower())).strip("-")


def sections(root: Path = ROOT) -> list[str]:
    """The sections the design indexes: `docs/design.md`'s `- **§<n>**` bullets, then `title`."""
    found = []
    for line in (root / "docs" / "design.md").read_text(encoding="utf-8").splitlines():
        m = INDEX_BULLET.match(line)
        if m:
            found.append(m.group(1))
    return [*found, "title"]


def normal(section: str) -> str:
    """`§6`, `6` and `6.` all name §6; `Title`, `§title` name the title and status."""
    s = section.strip().removeprefix("§").rstrip(".")
    return "title" if s.lower() == "title" else s


@dataclass
class Line:
    """One `- ` bullet with its indented continuation lines, where it was read."""

    file: str
    index: int  # the bullet's place in its file, from 0
    date: str  # YYYY-MM-DD, or "" for an undated bullet
    text: str


def _bullets(body: list[str], file: str) -> list[Line]:
    out: list[Line] = []
    for raw in body:
        if raw.startswith("- "):
            m = DATED.match(raw)
            out.append(Line(file, len(out), m.group(1) if m else "", raw))
        elif out and (raw.startswith((" ", "\t")) or not raw.strip()):
            out[-1].text += "\n" + raw
    for ln in out:
        ln.text = ln.text.rstrip("\n ")
    return out


def _blocks(text: str) -> list[tuple[str, str, list[str]]]:
    """`(heading line, its number or 'title', the lines under it)` for each `## ` heading in order."""
    out: list[tuple[str, str, list[str]]] = []
    for raw in text.splitlines():
        if raw.startswith("## "):
            # `## 6. Policies …`, `## §4.10 (middle …)`, `## Title and status`: the leading token names it
            out.append((raw, normal(raw[3:].split()[0]), []))
        elif out:
            out[-1][2].append(raw)
    return out


def new_lines(section: str, root: Path = ROOT) -> list[Line]:
    """Every `docs/history/` file's lines under `## §<section>`, newest first by date, a tie by the
    file's name in plain string order, then later in the file first."""
    hist = root / "docs" / "history"
    lines: list[Line] = []
    if hist.is_dir():
        for p in sorted(hist.glob("*.md")):
            if p.name == "README.md":
                continue
            for _, key, body in _blocks(p.read_text(encoding="utf-8")):
                if key == section:
                    lines.extend(_bullets(body, p.name))
    lines.sort(key=lambda ln: (ln.file, -ln.index))
    lines.sort(key=lambda ln: ln.date, reverse=True)  # stable: the tie keeps (name, later first)
    return lines


def frozen(section: str, root: Path = ROOT) -> list[tuple[str, list[str]]]:
    """`docs/design-history.md`'s heading or headings for the section, as written, in file order."""
    path = root / "docs" / "design-history.md"
    if not path.exists():
        return []
    return [(h, body) for h, key, body in _blocks(path.read_text(encoding="utf-8")) if key == section]


def render(section: str, grep: str | None = None, root: Path = ROOT) -> str:
    """The section's whole record as `history.py` prints it."""
    out: list[str] = []
    new = [ln for ln in new_lines(section, root) if grep is None or grep in ln.text]
    if new:
        out.append(f"## §{section} — docs/history/, newest first")
        out.append("")
        out.extend(f"docs/history/{ln.file}: {ln.text}" for ln in new)
        out.append("")
    for heading, body in frozen(section, root):
        if grep is None:
            kept = "\n".join(body).strip("\n")
        else:
            kept = "\n".join(ln.text for ln in _bullets(body, "design-history.md") if grep in ln.text)
        if not kept:
            continue
        out.append(f"{heading} — docs/design-history.md, as written")
        out.append("")
        out.append(kept)
        out.append("")
    return "\n".join(out)


def _is_date(text: str) -> bool:
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def check(root: Path = ROOT) -> list[str]:
    """What is wrong with `docs/history/`'s shape (design §4.4): each problem as one line, none when sound.

    Every file but `README.md` is named `TD-<n>.md` or `<YYYY-MM-DD>-<slug>.md`, there is no
    subdirectory, and a file holds only `## §<section>` headings naming an indexed section (or
    `§title`), with only `- YYYY-MM-DD ` bullets and their indented continuations under them; blank
    lines pass anywhere. A `TD-<n>.md` names an entry the ledger holds, open or archived."""
    hist = root / "docs" / "history"
    if not hist.is_dir():
        return []
    known = set(sections(root))
    ledger = root / "docs" / "ledger"
    problems: list[str] = []
    for p in sorted(hist.iterdir()):
        rel = f"docs/history/{p.name}"
        if p.is_dir():
            problems.append(f"{rel}: a subdirectory; docs/history/ has none")
            continue
        if p.name == "README.md":
            continue
        if not FILE_NAME.match(p.name):
            problems.append(f"{rel}: not named TD-<n>.md or <YYYY-MM-DD>-<slug>.md")
            continue
        stem = p.name.removesuffix(".md")
        if stem.startswith("TD-") and not ((ledger / p.name).exists() or (ledger / "archive" / p.name).exists()):
            problems.append(f"{rel}: names {stem}, which the ledger does not hold (renumbered? git mv it)")
        in_heading, in_bullet = False, False
        for n, raw in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if not raw.strip():
                continue
            m = HEADING.match(raw)
            if m:
                key = m.group(1)  # as the index writes it: `§6`, never the frozen file's `6.`
                if key not in known:
                    problems.append(f"{rel}:{n}: `{raw}` names no section docs/design.md indexes")
                in_heading, in_bullet = True, False
            elif (d := DATED.match(raw)) and in_heading and _is_date(d.group(1)):
                in_bullet = True
            elif raw.startswith((" ", "\t")) and in_bullet:
                pass
            else:
                problems.append(f"{rel}:{n}: only `## §<section>` headings and `- YYYY-MM-DD ` lines belong here")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("section", nargs="?", help="a section docs/design.md indexes (6, §4.4a, 4.10), or title")
    ap.add_argument("--grep", help="only the lines holding this text")
    ap.add_argument("--check", action="store_true", help="check docs/history/'s shape instead")
    args = ap.parse_args(argv)
    if args.check:
        problems = check()
        print("\n".join(problems) or "docs/history/: sound")
        return 1 if problems else 0
    if args.section is None:
        ap.error("a section is needed (or --check)")
    section = normal(args.section)
    if section not in sections():
        print(f"history.py: §{section} is not a section docs/design.md indexes", file=sys.stderr)
        return 1
    text = render(section, args.grep)
    print(text or f"§{section}: no record{' holding that text' if args.grep else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
