"""`shiftlead-hook`'s entry point keeps its traceback (design §4.1 *The hook keeps its traceback*,
TD-720 slice 3): the hook is imported inside a `try`, and an import that fails is appended to
`<home>/hook-errors.log` with the session and the event, the log cut to its last 256 KB."""

from __future__ import annotations

import io
import json
import subprocess
import sys

from sessionorc import paths
from shiftlead import hook_entry


def _fail_import(monkeypatch) -> None:
    # `None` in sys.modules makes the import raise ImportError, as a half-replaced install would; the
    # package's attribute goes too, or `from … import hook` finds a module an earlier test imported
    import shiftlead.adapters.claude_code as pkg

    monkeypatch.setitem(sys.modules, "shiftlead.adapters.claude_code.hook", None)
    monkeypatch.delattr(pkg, "hook", raising=False)


def test_an_import_failure_is_logged_with_the_session_and_the_event(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SHIFTLEAD_SESSION", "ao-x-techlead")
    monkeypatch.setattr(sys, "argv", ["shiftlead-hook"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"hook_event_name": "SessionStart"})))
    _fail_import(monkeypatch)
    assert hook_entry.main() == 1  # non-zero: Claude Code still shows its one-line *hook error*
    log = paths.hook_errors_file()
    assert log == hook_entry.log_path()  # the readers' name and the writer's are one file
    text = log.read_text()
    assert "session=ao-x-techlead event=SessionStart" in text
    assert "ModuleNotFoundError" in text and "Traceback" in text
    assert str(log) in capsys.readouterr().err


def test_the_log_keeps_its_last_256_kb(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["shiftlead-hook", "--statusline"])
    hook_entry.log_path().write_text("old line\n" * 40000)  # ~360 KB
    _fail_import(monkeypatch)
    assert hook_entry.main() == 1
    data = hook_entry.log_path().read_bytes()
    assert len(data) <= hook_entry.LOG_LIMIT
    assert data.startswith(b"old line\n")  # cut at a whole line
    assert b"event=statusline" in data  # the newest entry kept


def test_a_working_install_runs_the_hook(monkeypatch):
    from shiftlead.adapters.claude_code import hook

    monkeypatch.setattr(hook, "main", lambda: 0)
    assert hook_entry.main() == 0


def test_the_entry_imports_nothing_of_sessionorc():
    code = "import sys, shiftlead.hook_entry; print(sorted(m for m in sys.modules if m.startswith('sessionorc')))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "[]"
