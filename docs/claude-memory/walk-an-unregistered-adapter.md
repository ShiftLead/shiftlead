---
name: walk-an-unregistered-adapter
description: The conformance walk on an adapter with no entry point yet (Gemini until TD-785): register it from a scratch dist-info on PYTHONPATH, never by editing pyproject or the live install
metadata:
  type: reference
---

`scripts/conformance.py` and its host agent find adapters through `entry_points(group="shiftlead.adapters")`, so an adapter whose code exists but is not in `pyproject.toml` (Gemini, until TD-785 registers it) is refused as *no agent adapter*. Register it for one run from a scratch directory, nothing installed or committed (2026-10-21, TD-875's walk):

```bash
D=<scratchpad>/gemreg/shiftlead_gemini_walk-0.0.dist-info; mkdir -p $D
printf 'Metadata-Version: 2.1\nName: shiftlead-gemini-walk\nVersion: 0.0\n' > $D/METADATA
printf '[shiftlead.adapters]\ngemini = shiftlead.adapters.gemini:GeminiAdapter\n' > $D/entry_points.txt
PYTHONPATH=$PWD/src:<scratchpad>/gemreg /home/kmaster/shiftlead/.venv/bin/python scripts/conformance.py gemini --profile gemini-conformance --capture
```

The walk's host agent inherits `PYTHONPATH` (`look_home.child_env`). The hook needs no registration: `shiftlead-hook --adapter gemini` imports the module directly. Gemini's walk also needs the root-owned layer in `/etc/shiftlead/` (installed 2026-10-21). Running the walk from a worktree: [[scratch-worktree-tests-import-main-checkout]].
