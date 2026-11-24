"""One reader of a repo's own YAML text for sessionorc (TD-2150): `yaml.safe_load`, with a text nested past the
parser's depth raised as `yaml.YAMLError` like any other bad file, as `shiftlead.repoconfig.parse_yaml` does
(TD-2135), which sessionorc cannot import. Every reader of `.shiftlead.yml` or a flow's `flow.yml` that reads a bad
file as a problem then reads that one too, never crashing on a RecursionError."""

from __future__ import annotations

from typing import Any

import yaml


def load(text: str) -> Any:
    """`yaml.safe_load(text)`; a RecursionError is a `yaml.YAMLError`."""
    try:
        return yaml.safe_load(text)
    except RecursionError:
        raise yaml.YAMLError("nested too deeply to read") from None
