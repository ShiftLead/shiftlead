"""The wait guard (design §4.3 *A wait the guard refuses*, TD-991): a net under §4.10's rule.

A session never waits inside its own turn: what it waits on outside mail runs as one background
command, whose end wakes it. `waits` reads a shell command's shape and names a CI watch —
`gh pr checks … --watch` or `gh run watch` — read as the kill guard reads a kill: the text masked,
each command's word found past the same wrappers. A single `gh pr checks <n>`, a short `sleep` and a
loop pass. Whether the call is refused is the hook's: only in the foreground, on the main thread, of
an unattended record. It reads text only and calls nothing.
"""

from __future__ import annotations

from shiftlead.kill_guard import SEPARATORS, command_word, mask

REASON = (
    "shiftlead: refused — a foreground CI watch in an unattended session; run the same command in the "
    "background (`run_in_background`) and end the turn: its end wakes you (design §4.10)"
)

# `gh`'s own options before the subcommand that take the next word as their value.
GH_VALUES = {"-R", "--repo"}


def gh_subcommand(args: list[str]) -> list[str]:
    """`gh`'s arguments from its subcommand on, past its own options (`-R a/b`, `--repo=a/b`)."""
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in GH_VALUES else 1
    return args[i:]


def waits(command: str) -> bool:
    """True when `command` runs a CI watch (§4.3 *A wait the guard refuses*)."""
    for segment in SEPARATORS.split(mask(command)):
        word, args = command_word(segment.split())
        if word != "gh":
            continue
        sub = gh_subcommand(args)
        if sub[:2] == ["run", "watch"]:
            return True
        if sub[:2] == ["pr", "checks"] and any(a == "--watch" or a.startswith("--watch=") for a in sub[2:]):
            return True
    return False
