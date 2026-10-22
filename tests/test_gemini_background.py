"""The Gemini CLI adapter's background read (design §4.3 `background`, TD-786): the process tree captured from
the real tool (`tests/conformance/fixtures/gemini/procs/`), and the shapes around it a launch can take."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from conformance._harness import RecordedProc

from shiftlead.adapters.gemini import GeminiAdapter

pytestmark = pytest.mark.unit

SNAP = json.loads(
    (Path(__file__).parent / "conformance" / "fixtures" / "gemini" / "procs" / "two-tasks.json").read_text("utf-8")
)
CMDS = ["timeout 300 sleep 290", "python3 -c import time; time.sleep(280)"]


def _relaunch(procs: dict) -> tuple[str, str]:
    pane = str(SNAP["pane_pid"])
    return pane, str(procs[pane]["children"][0])


def test_under_a_hand_started_shell_the_walk_finds_the_node_below_it():
    procs = copy.deepcopy(SNAP["procs"])
    procs["9"] = {
        "comm": "bash",
        "children": [SNAP["pane_pid"]],
        "cmdline": ["bash"],
        "stat": {**procs[str(SNAP["pane_pid"])]["stat"]},
    }
    assert [t["cmd"] for t in GeminiAdapter("gemini").background(9, RecordedProc(procs))] == CMDS


def test_a_launch_that_does_not_relaunch_keeps_its_shells_beside_a_node_mcp_server():
    procs = copy.deepcopy(SNAP["procs"])
    pane, child = _relaunch(procs)
    # the shells hang off the pane's own node, and its one node child is an MCP server with none
    procs[pane]["children"] = procs[child]["children"] + [int(child)]
    procs[child].update(children=[], cmdline=["node", "/opt/mcp/server.js"])
    got = GeminiAdapter("gemini").background(int(pane), RecordedProc(procs))
    assert [t["cmd"] for t in got] == CMDS


def test_a_child_that_is_not_the_wrapper_is_not_a_task():
    procs = copy.deepcopy(SNAP["procs"])
    _, child = _relaunch(procs)
    wrapper = str(procs[child]["children"][0])
    procs[wrapper]["cmdline"] = ["/usr/bin/bash", "-c", "some other script"]
    got = GeminiAdapter("gemini").background(SNAP["pane_pid"], RecordedProc(procs))
    assert [t["cmd"] for t in got] == CMDS[1:]
