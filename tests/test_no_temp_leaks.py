"""No test leaves a directory in `/tmp` (TD-1053).

`/tmp` on kmaster is a tmpfs every session shares. Tests that wrote their browser probe into
`tempfile.mkdtemp()` and never removed it left about 105,000 directories there by 2026-10-26, and
the inode table ran out: no command in any session could start. A test takes `tmp_path`, and a
helper with no fixture to hand takes `conftest.scratch_dir()`; pytest cleans both.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

pytestmark = pytest.mark.unit

TESTS = pathlib.Path(__file__).parent
# A script run by hand on a scratch home, never collected: it keeps its home to be read afterwards.
EXEMPT = {TESTS / "conformance" / "fixtures" / "claude-code" / "captured" / "subagent-permission" / "probe.py"}


def _name(call: ast.Call) -> str:
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""


def leaks(source: str) -> list[tuple[int, str]]:
    """Each temp-directory call in `source` that nothing removes: (line, what it is)."""
    tree = ast.parse(source)
    managed = {id(item.context_expr) for node in ast.walk(tree) if isinstance(node, ast.With | ast.AsyncWith)
               for item in node.items}  # fmt: skip
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _name(node)
        if name in ("mkdtemp", "mkstemp"):
            found.append((node.lineno, f"{name}()"))
        elif name == "TemporaryDirectory" and id(node) not in managed:
            found.append((node.lineno, "TemporaryDirectory() outside a with"))
        elif name == "NamedTemporaryFile" and any(
            k.arg == "delete" and isinstance(k.value, ast.Constant) and k.value.value is False for k in node.keywords
        ):
            found.append((node.lineno, "NamedTemporaryFile(delete=False)"))
    return sorted(found)


def test_no_test_makes_a_temp_directory_that_nothing_removes():
    bad = [
        f"{path.relative_to(TESTS)}:{line}: {what}"
        for path in sorted(TESTS.rglob("*.py"))
        if path not in EXEMPT
        for line, what in leaks(path.read_text())
    ]
    assert not bad, "take tmp_path, or conftest.scratch_dir() in a helper (TD-1053):\n" + "\n".join(bad)


@pytest.mark.parametrize(
    "source",
    [
        "import tempfile\nd = tempfile.mkdtemp()\n",
        "from tempfile import mkdtemp\nd = mkdtemp(prefix='x')\n",
        "import tempfile\nt = tempfile.TemporaryDirectory()\n",
        "import tempfile\nwith open('x') as f:\n    t = tempfile.TemporaryDirectory()\n",
        "import tempfile\nf = tempfile.NamedTemporaryFile('w', delete=False)\n",
    ],
)
def test_the_guard_fails_on_a_planted_leak(source):
    assert leaks(source)


@pytest.mark.parametrize(
    "source",
    [
        "import tempfile\nwith tempfile.TemporaryDirectory() as d:\n    pass\n",
        "import tempfile\nwith open('x') as a, tempfile.TemporaryDirectory(dir='/tmp') as d:\n    pass\n",
        "import tempfile\nwith tempfile.NamedTemporaryFile('w') as f:\n    pass\n",
        "from conftest import scratch_dir\nd = scratch_dir()\n",
    ],
)
def test_the_guard_passes_what_is_removed(source):
    assert leaks(source) == []
