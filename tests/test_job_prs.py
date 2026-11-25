"""The pull requests a built-in seat's job holds, for the home's Sync policy (design §6 *Sync*, TD-2165)."""

import tomllib
from pathlib import Path

from sessionorc import agent_stage
from shiftlead import job_prs


def test_the_open_pr_jobs_numbers_a_closed_or_person_waiting_one_aside():
    jobs = {
        "pr-12": {"id": "pr-12"},
        "pr-13": {"id": "pr-13", "closed_at": "2026-11-25T00:00:00Z"},
        "pr-14": {"id": "pr-14", "waits": "person"},
        "pr-15": {"id": "pr-15", "waits": "merging"},
        "board-1a2b3c4d": {"id": "board-1a2b3c4d", "pr": 16},  # a board answer's own PR is no pr- job's
        "pr-x": {"id": "pr-x"},
    }
    assert job_prs.numbers(jobs) == {12, 15}


def test_call_reads_the_repos_state_branch(monkeypatch):
    class Store:
        def __init__(self, root):
            self.root = root

        def jobs(self):
            return {"pr-7": {}} if self.root == "/r" else {}

    monkeypatch.setattr(job_prs, "StageStore", Store)
    assert job_prs.call("/r") == {7}


def test_the_module_is_on_the_home_calls_entry_point():
    """Read from pyproject.toml: the installed metadata names it only once the package is reinstalled."""
    eps = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())["project"]["entry-points"]
    assert eps["shiftlead.home_calls"][agent_stage.JOB_PRS] == "shiftlead.job_prs"
