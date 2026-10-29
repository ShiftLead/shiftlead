---
name: shiftlead-is-pinned-run-dev-cadence-scripts
description: "Since #2391 (2026-10-26) shiftlead pins agent-cadence: no synced scripts/ledger.py, check_cadence.py or precheck.py — run them as `agent-cadence run <script>`"
metadata:
  type: project
---

On 2026-10-26 #2391 merged *Pin agent-cadence* (dev-cadence TD-129's rollout): `docs/cadence.toml` gained a `[agent-cadence]` table (`source`, `ref`) and the synced copies under `scripts/` were removed. `python3 scripts/ledger.py --check` now fails with *No such file or directory*. The commands are:
- `agent-cadence run ledger.py --check` (add `--since origin/main` for a new entry's `Taken by`);
- `agent-cadence run precheck.py --pr N` (the merge gate since TD-1035);
- `agent-cadence run check_cadence.py --pr N`.
The launcher is `~/.local/share/shiftlead-venv/bin/agent-cadence`, on PATH, and runs the pinned tree from `~/.cache/agent-cadence/`. `agent-cadence path <file>` prints where a doc lives (cadence.md, procedures/).

**Why:** the pin replaces the sync (agent-cadence ADR *pinned, not synced*), so the scripts are no longer in the repo.

**How to apply:** an older memory, brief or doc that says `scripts/<x>.py` for an agent-cadence script means `agent-cadence run <x>.py` now. ShiftLead's own scripts (`scripts/smoke.py`, `look_home.py`, `conformance.py`) are still in `scripts/`. See [[precheck-and-merge-in-one-command]].
