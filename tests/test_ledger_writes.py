"""ShiftLead's code writes no ledger text of its own (design §4.4 *A session writes the ledger and the board only
through the helpers*, TD-1373): a ledger write goes through ledgerboard's vendored writer
(`sessionorc.ledgerboard.ledger`), which dates the ledger in UTC, while the board's dates stay the machine's local
date."""

from __future__ import annotations

import ast
import re
import subprocess
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from sessionorc import workorders
from sessionorc.ledgerboard import ledger as lb_ledger

SRC = Path(__file__).resolve().parent.parent / "src"
VENDORED = SRC / "sessionorc" / "ledgerboard"

# what names a ledger's files in ShiftLead's code: sessionorc.ledger's paths and ledgerboard's layout names
LEDGER_NAMES = re.compile(
    r"\b(?:ledger_path|ledger_default|ledger_set|archive_of|archive_path|LEDGER_DIR_REL|ARCHIVE_REL|LEDGER_REL"
    r"|LEDGER_ARCHIVE|LEDGER_README|ENTRY_FILE_RE|entry_file)\b|technical_debt|docs/ledger"
)
PATH_WRITES = {"write_text", "write_bytes", "unlink", "touch"}  # a write on any receiver
MODULE_WRITES = {"os": {"replace", "rename", "remove", "unlink"}, "shutil": {"move", "copy", "copy2", "copyfile"}}


def _writes(fn: ast.AST) -> list[tuple[int, str]]:
    """The file writes in `fn`'s body: a `Path` write, an `open` for writing, an `os`/`shutil` move or copy."""
    out: list[tuple[int, str]] = []
    for n in ast.walk(fn):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        if isinstance(f, ast.Attribute) and f.attr in PATH_WRITES:
            out.append((n.lineno, f.attr))
        elif (
            isinstance(f, ast.Attribute)
            and isinstance(f.value, ast.Name)
            and f.attr in MODULE_WRITES.get(f.value.id, ())
        ):
            out.append((n.lineno, f"{f.value.id}.{f.attr}"))
        elif (isinstance(f, ast.Name) and f.id == "open") or (isinstance(f, ast.Attribute) and f.attr == "open"):
            mode = n.args[1] if len(n.args) > 1 else next((k.value for k in n.keywords if k.arg == "mode"), None)
            if isinstance(mode, ast.Constant) and isinstance(mode.value, str) and set(mode.value) & set("wax+"):
                out.append((n.lineno, f"open({mode.value!r})"))
    return out


def _ledger_writers(path: Path, text: str) -> list[str]:
    """Each function in `text` that names a ledger's files and writes a file: `path:line name (writes)`."""
    found = []
    for fn in ast.walk(ast.parse(text)):
        if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            w = _writes(fn)
            if w and LEDGER_NAMES.search(ast.get_source_segment(text, fn) or ""):
                found.append(f"{path}:{fn.lineno} {fn.name} ({', '.join(x for _, x in w)})")
    return found


def test_the_scan_finds_a_ledger_write():
    """The audit below is a real check: a function that writes beside a ledger path is named."""
    text = (
        "from sessionorc import ledger\n"
        "def bad(root):\n"
        "    (root / ledger.ledger_path(root) / 'TD-001.md').write_text('## TD-001: x')\n"
        "def also(root):\n"
        "    with open(f'{root}/docs/ledger/TD-002.md', 'a') as fh:\n"
        "        fh.write('x')\n"
        "def fine(root):\n"
        "    return (root / ledger.ledger_path(root)).read_text()\n"
    )
    got = _ledger_writers(Path("x.py"), text)
    assert [g.split()[1] for g in got] == ["bad", "also"]


def test_no_code_writes_ledger_text_by_its_own_file_handling():
    """No function in `src/` outside the vendored ledgerboard both names a ledger's files and writes a file
    (TD-1373): a ledger write is ledgerboard's writer's, `plan_*` then `apply`."""
    found = []
    for path in sorted(SRC.rglob("*.py")):
        if VENDORED in path.parents:
            continue
        found += _ledger_writers(path.relative_to(SRC), path.read_text(encoding="utf-8"))
    assert found == []


def test_the_grep_finds_no_entry_text_written_outside_the_writer():
    """The grep half (TD-1373's *Done when*): no module outside the vendored ledgerboard writes an entry's
    heading or a `**Log:**` line into a string it then writes — the shapes only the writer makes."""
    out = subprocess.run(
        ["grep", "-rnE", r"write\w*\(.*(## TD-|\*\*Log:\*\*|\*\*Status:\*\*)", str(SRC), "--include=*.py"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    assert [ln for ln in out.splitlines() if str(VENDORED) not in ln] == []


class _Evening(datetime):
    """A clock at 23:30 on 2026-11-05 at UTC-7: the local day is the 5th, the UTC day the 6th."""

    ZONE = timezone(timedelta(hours=-7))

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        at = datetime(2026, 11, 5, 23, 30, tzinfo=cls.ZONE)
        return at.astimezone(tz) if tz is not None else at.replace(tzinfo=None)


def _ledger(tmp_path: Path) -> Path:
    d = tmp_path / "docs" / "ledger"
    (d / "archive").mkdir(parents=True)
    (d / "README.md").write_text("Ledgerboard: 2\n\n# Ledger\n", encoding="utf-8")
    (d / "TD-001.md").write_text(
        "## TD-001: A thing waits on the person\n\n**Priority:** Medium\n**Added:** 2026-11-01\n**Status:** Open\n"
        "**Blocked by:** decision (paul)\n\n**Why:** because.\n\n**Ask:** Go?\n\n**Fix:** do it.\n",
        encoding="utf-8",
    )
    return d


def test_a_lift_through_the_writer_is_dated_utc(tmp_path, monkeypatch):
    """A lift written through ledgerboard's writer with no date of its caller's is dated the UTC day, never the
    machine's local one (TD-1373; the press that writes one is TD-1375's)."""
    d = _ledger(tmp_path)
    monkeypatch.setattr(lb_ledger, "datetime", _Evening)
    plan = lb_ledger.plan_lift(lb_ledger.Ledger.open(str(d)), "TD-001", "decision (paul)", "paul", answer="Go")
    assert lb_ledger.apply(plan)
    text = (d / "TD-001.md").read_text(encoding="utf-8")
    assert "- 2026-11-06: gate lifted: decision (paul) — by paul" in text
    assert "2026-11-05:" not in text


def test_the_board_reading_dates_are_local(tmp_path, monkeypatch):
    """The board's dates are the machine's local civil date (§4.4 *Board write-back*): `read_boards`'s `today`
    is the local day where the UTC day is already the next (TD-1373)."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "user_attention.md").write_text("# Needs the user\n\n", encoding="utf-8")
    monkeypatch.setattr(workorders, "datetime", _Evening)
    got = workorders.read_boards(tmp_path, fetch=False)
    assert got["today"] == "2026-11-05"
    assert _Evening.now(UTC).date().isoformat() == "2026-11-06"
