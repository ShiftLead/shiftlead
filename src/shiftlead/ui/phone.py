"""The phone's Focus (design §4.5 *Phone layout*, §4.5a *the strip* and *the switcher*; TD-003, built by TD-1299).

What the narrow screen needs of the other records, read once when the page is drawn: one row per record for
**the switcher** — its name, its state, what it waits on and since when — from which the page also counts the
strip's **▲ n**. The light stream keeps each row's state afterwards (`SHAPE_KEYS`); the grouping and the order are
the page's, so they follow it."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from shiftlead.ending import waiting_words

SUB_MAX = 160  # what a row's second line can show at a phone's width, and a little more


def _sub(s: Mapping[str, Any], waits: Mapping[str, Any]) -> str:
    """What the record waits on (§4.5a *the switcher*): the needs-you text, else the waiting mark's words, else
    its repo. A session's or a tool's words, escaped by the page, never a control."""
    pend = s.get("pending") if isinstance(s.get("pending"), Mapping) else {}
    if s.get("state") == "needs-you" and pend and pend.get("text"):
        text = str(pend["text"])
        text = text if pend.get("kind") == "permission" else f"{pend.get('kind')}: {text}"
    else:
        text = waiting_words(waits.get(str(s.get("id")))) or ""
    if not text:
        where = str(s.get("repo") or s.get("dir") or "").rstrip("/")
        text = where.rsplit("/", 1)[-1]
    text = " ".join(text.split())
    return text if len(text) <= SUB_MAX else text[: SUB_MAX - 1] + "…"


def switch_rows(fleet: list[dict[str, Any]], here: str, waits: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """One row per record (§4.5a *the switcher*): `{id, name, state, sub, since, here}`, in the fleet's order —
    the page groups and sorts them, so a state that moves after the page was drawn moves its row."""
    waits = waits or {}
    return [
        {
            "id": str(s.get("id") or ""),
            "name": str(s.get("name") or s.get("id") or ""),
            "state": str(s.get("state") or ""),
            "sub": _sub(s, waits),
            "since": str(s.get("since") or ""),
            "here": str(s.get("id")) == here,
        }
        for s in fleet
        if s.get("id")
    ]
