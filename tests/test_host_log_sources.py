"""The ledger's host-log sources (design §4.4 *The home keeps a log of what it witnesses*, *The source*; TD-1388):
`docs/ledger/log-sources.toml` declares `witnessed`, `.shiftlead.yml`'s `held:` lists it, and every PR's
precheck validates it, with the ledger's host-log gates, through the tree's own vendored launcher."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import yaml

from conftest import pinned_script

ROOT = Path(__file__).resolve().parents[1]
SOURCES = "docs/ledger/log-sources.toml"
VALIDATE = (
    f"pdm run python src/sessionorc/agent_cadence.py -C . run hostlog.py validate --repo-config {SOURCES} "
    "--ledger docs/ledger"
)


def test_the_witnessed_source_is_declared_as_the_design_gives_it():
    conf = tomllib.loads((ROOT / SOURCES).read_text(encoding="utf-8"))
    assert conf == {
        "sources": {
            "witnessed": {
                "shape": "directory",
                "path": "~/.shiftlead/witnessed",
                "match": ["*.jsonl"],
                "records": "jsonl",
                "fields": {"at": "at", "kind": "kind", "text": "text", "id": "id", "repo": "repo"},
            }
        }
    }


def test_the_sources_file_is_a_held_path():
    held = yaml.safe_load((ROOT / ".shiftlead.yml").read_text(encoding="utf-8"))["held"]
    assert SOURCES in held


def test_the_precheck_validates_the_sources_after_its_sync_and_before_the_suite():
    pc = tomllib.loads((ROOT / "docs/cadence.toml").read_text(encoding="utf-8"))["precheck"]
    assert VALIDATE in pc
    assert pc.index("pdm sync") < pc.index(VALIDATE) < pc.index("pdm run test")


def test_the_committed_sources_pass_the_pinned_reader():
    script = pinned_script("hostlog.py")
    cp = subprocess.run(
        [sys.executable, str(script), "validate", "--repo-config", SOURCES, "--ledger", "docs/ledger"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert cp.returncode == 0, cp.stdout + cp.stderr
