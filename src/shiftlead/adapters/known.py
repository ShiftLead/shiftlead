"""Tools the Tools page names with no adapter yet (design §4.2b *Known tools without an adapter*, TD-1971).

Data, not code: read through `sessionorc.adapters.known_tools()` from the `shiftlead.known_tools` entry point, so no
tool's name is in core. Each row's `find()` is the PATH alone; a row whose name becomes a registered adapter is that
adapter's, and the row is dropped from the reply (and should be from here).
"""

from __future__ import annotations

KNOWN_TOOLS: tuple[dict[str, str], ...] = (
    {"name": "codex", "label": "Codex", "binary": "codex"},
    {"name": "opencode", "label": "opencode", "binary": "opencode"},
)
