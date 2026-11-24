"""One reader of a repo's own YAML text for sessionorc (TD-2150), and of the home's own files (TD-2154):
`yaml.safe_load`, with a text nested past the parser's depth raised as `yaml.YAMLError` like any other bad file, as
`shiftlead.repoconfig.parse_yaml` does (TD-2135), which sessionorc cannot import. Every reader of `.shiftlead.yml`, a
flow's `flow.yml`, or the home's settings.yml, hosts.yml, logins.yml, profiles.yml and org.yml that reads a bad file as
a problem then reads that one too, never crashing on a RecursionError."""

from __future__ import annotations

from typing import Any

import yaml


def load(text: str) -> Any:
    """`yaml.safe_load(text)`; a RecursionError is a `yaml.YAMLError`."""
    try:
        return yaml.safe_load(text)
    except RecursionError:
        raise yaml.YAMLError("nested too deeply to read") from None
