"""A team's settings after the cut-over (design §4.9d *What a team is*, *Sessions at once*, *The logins, in order*,
TD-2060): the keys under `settings.yml` `teams.<team>` that only the team page writes, the `cut_over` marker that gates
those writes, and the one function that picks a login for a model.

Pure: each function takes the settings document, or the rows a caller read, and neither reads nor writes a file. The
host agent's `team_set` makes the write. No launch calls `pick` yet: that is the launch path's (§4.9e, TD-1976).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from sessionorc import logins
from sessionorc import settings as settings_mod

STORE_KEYS = ("label", "repo", "host", "logins", "at_once", "most")
SET_KEYS = ("label", "logins", "at_once", "most")  # what `team_set` writes; `repo` and `host` never change
LABEL_MAX = 60
BEFORE = "after the switch-over"
STALE = "changed since this page read it — reload"


class TeamError(ValueError):
    """A team write refused, its words the person's to read."""


def cut_over(doc: Mapping[str, Any]) -> str | None:
    """The cut-over's marker, the one reading of it (§4.9d *What the cut-over's move must produce*): its date, or
    None before the window has written it."""
    value = doc.get("cut_over")
    return str(value) if value else None


def _entry(doc: Mapping[str, Any], team: str) -> Mapping[str, Any]:
    teams = doc.get("teams")
    entry = teams.get(team) if isinstance(teams, Mapping) else None
    return entry if isinstance(entry, Mapping) else {}


def switched(doc: Mapping[str, Any], team: str) -> bool:
    """Whether a team is switched (§4.9d *Before and after the cut-over*): `settings.yml` holds its `repo`."""
    repo = _entry(doc, team).get("repo")
    return isinstance(repo, str) and bool(repo.strip())


def version(doc: Mapping[str, Any], team: str) -> str:
    """The version of what the team page's writes change: its store keys and its flow. The running settings save on
    their own road (`set_settings`), so a changed stop time does not refuse a press on a page drawn before it."""
    entry = _entry(doc, team)
    held = {k: entry[k] for k in (*STORE_KEYS, "flow") if entry.get(k) is not None}
    return hashlib.sha256(json.dumps(held, sort_keys=True, default=str).encode()).hexdigest()[:12]


def _label(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TeamError("a label is text")
    text = value.strip()
    if "\n" in text or "\r" in text:
        raise TeamError("a label is one line")
    if len(text) > LABEL_MAX:
        raise TeamError(f"a label is at most {LABEL_MAX} characters")
    return text or None


def _logins(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise TeamError("logins is the whole list, each <tool>:<name>")
    out: list[str] = []
    for lk in value:
        tool, name = logins.split(lk) if isinstance(lk, str) else ("", "")
        if not tool or not logins.valid_name(name):
            raise TeamError(f"{lk!r} is not a login: each is <tool>:<name>")
        if lk in out:
            raise TeamError(f"{lk} is in the list twice")
        out.append(lk)
    return out


def _number(value: Any, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise TeamError(f"{what} is a whole number of 1 or more, not {value!r}")
    return value


def _at_once(current: Any, value: Any) -> dict[str, int]:
    """`current` with `value`'s keys laid over it: a number sets a stage's, None removes it."""
    if not isinstance(value, Mapping) or not value:
        raise TeamError("at_once names a stage and its number")
    out = dict(current) if isinstance(current, Mapping) else {}
    for key, n in value.items():
        if not isinstance(key, str) or not key or key != key.strip().lower().replace(" ", "-"):
            raise TeamError(f"{key!r} is not a stage's key")
        if n is None:
            out.pop(key, None)
        else:
            out[key] = _number(n, f"at_once.{key}")
    return out


def apply(doc: dict[str, Any], team: str, change: Mapping[str, Any], sent: str | None) -> str:
    """One `team_set` on the document, in place; its words for the commit line. Refused before the cut-over, for a team
    that is not switched, over a newer version, and unless `change` holds exactly one of `SET_KEYS`."""
    if not cut_over(doc):
        raise TeamError(BEFORE)
    if not switched(doc, team):
        raise TeamError(f"no switched team {team!r}")
    if sent is None or sent != version(doc, team):
        raise TeamError(STALE)
    if len(change) != 1 or next(iter(change)) not in SET_KEYS:
        raise TeamError(f"team_set takes one of {', '.join(SET_KEYS)}")
    key, value = next(iter(change.items()))
    entry = doc["teams"][team]
    if key == "label":
        new: Any = _label(value)
    elif key == "logins":
        new = _logins(value)
    elif key == "at_once":
        new = _at_once(entry.get("at_once"), value) or None
    else:
        new = None if value is None else _number(value, "most")
    if new is None:
        entry.pop(key, None)
    else:
        entry[key] = new
    return f"{team} {key} {'cleared' if new is None else 'set'}"


def rekey(doc: dict[str, Any], flow: str, renames: Mapping[str, str]) -> list[str]:
    """Each switched team on `flow` with its `at_once` keys renamed, in place (§4.9c *A switch or a rename re-keys the
    records*): the teams changed. Renames are applied at once, so a swap of two names holds, and a renamed stage's
    number wins over a stale key."""
    changed: list[str] = []
    teams = doc.get("teams")
    if not renames or not isinstance(teams, dict):
        return changed
    for team, entry in teams.items():
        if not switched(doc, team) or entry.get("flow") != flow or not isinstance(entry.get("at_once"), dict):
            continue
        held = entry["at_once"]
        now = {k: n for k, n in held.items() if k not in renames}  # a stale key a stage is renamed onto gives way
        now.update({renames[k]: n for k, n in held.items() if k in renames})
        if now != entry["at_once"]:
            entry["at_once"] = now
            changed.append(str(team))
    return changed


def _at_reserve(entry: Mapping[str, Any] | None, extra: int, now: datetime, metered: bool = False) -> bool:
    """Whether an account's `gate` entry is at its reserve for one login, the team's `reserve` added (§6 *Usage gate*).
    A metered window's line is its amount, reserve 0 as the gate reads it, since its `pct` is the spend over the amount.
    An account whose logins disagree on billing is read by the rows of this login's billing alone. A window the gate
    has no number for is never over."""
    rows = [dict(r) for r in (entry or {}).get("windows") or () if isinstance(r, Mapping)]
    if (entry or {}).get("billing") == "mixed":
        rows = [r for r in rows if bool(r.get("metered")) == metered]
    rows = [r for r in rows if r.get("metered") or r.get("reserve") is not None]
    by_label = {str(r.get("label")): 0 if r.get("metered") else r["reserve"] for r in rows}
    return settings_mod.crossed(settings_mod.lines(by_label, rows, now, extra)) is not None


def login_rows(
    read: Mapping[str, Any], accounts: Mapping[str, Any], extra: int = 0, now: datetime | None = None
) -> dict[str, dict[str, Any]]:
    """`pick`'s rows from the host's `tools` read and the `gate` reply's `accounts`, by login key: each login's
    `state`, `account`, `pin`, its account's model `models`, and `at_reserve` with the team's `extra` added."""
    when = now or datetime.now(UTC)
    out: dict[str, dict[str, Any]] = {}
    for card in read.get("tools") or ():
        by_key = {str(a.get("key")): a for a in card.get("accounts") or ()}
        for lg in card.get("logins") or ():
            account = lg.get("account")
            held = by_key.get(str(account)) or {}
            out[logins.key(str(card.get("adapter")), str(lg.get("name")))] = {
                "label": lg.get("label"),
                "state": lg.get("state"),
                "account": account,
                "pin": lg.get("pin"),
                "models": list((held.get("models") or {}).get("families") or ()),
                "at_reserve": bool(account)
                and _at_reserve(
                    accounts.get(str(account)),
                    extra,
                    when,
                    (lg.get("settings") or {}).get("billing") == "metered",
                ),
            }
    return out


def offers(row: Mapping[str, Any], model: str) -> bool:
    """Whether a login offers a model family: its account's `models`, narrowed by its `pin` (§4.9d)."""
    families = row.get("models") or ()
    pin = row.get("pin")
    return model in families and (not pin or pin == model)


def unusable(row: Mapping[str, Any]) -> str | None:
    """Why a login is not usable now, or None (§4.9d *The logins, in order*). The smoke pass is TD-2046's, unread."""
    state = row.get("state")
    if state == "limited":
        return "limited"
    if state != "signed_in":
        return "not signed in"
    if not row.get("account"):
        return "its account is not named"
    if row.get("at_reserve"):
        return "at its reserve"
    return None


def reasons(order: Iterable[str], rows: Mapping[str, Mapping[str, Any]]) -> dict[str, str | None]:
    """Why each login of the list is not usable, in order, or None: `unusable`, and a login on an account an earlier
    unusable login of the list shares is unusable too (§4.9d *The logins, in order*). The pick and the page read it."""
    barred: set[str] = set()
    out: dict[str, str | None] = {}
    for lk in order:
        row = rows.get(lk) or {}
        account = row.get("account")
        why = unusable(row)
        if why is None and account in barred:
            why = "shares an account with an unusable login above it"
        if why is not None and account:
            barred.add(str(account))
        out[lk] = why
    return out


def pick(order: Iterable[str], model: str, rows: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """The first usable login of `order` that offers `model` (§4.9d *The logins, in order*): `{login, state, why}`,
    `state` `usable`, `waits` (only unusable logins offer it) or `none` (no login offers it). A login on an account an
    earlier unusable login of the list shares is unusable too, whichever models that earlier login offers."""
    waiting: list[str] = []
    for lk, why in reasons(order, rows).items():
        row = rows.get(lk) or {}
        if why is None:
            if offers(row, model):
                return {"login": lk, "state": "usable", "why": None}
            continue
        if offers(row, model):
            waiting.append(f"{lk}: {why}")
    if waiting:
        return {"login": None, "state": "waits", "why": "; ".join(waiting)}
    return {"login": None, "state": "none", "why": f"no login in its list offers {model}"}


def cannot_run(
    team: str, flow: str, models: Iterable[str], order: Iterable[str], rows: Mapping[str, Mapping[str, Any]]
) -> str | None:
    """Why a team cannot run its flow, in the page's words (§4.9d *A team that cannot run says why*), or None. A model
    offered only by logins unusable right now is a wait, not this."""
    listed = list(order)
    if not listed:
        return f"{team} cannot run {flow}: its login list is empty"
    for model in models:
        if not any(offers(rows.get(lk) or {}, model) for lk in listed):
            return f"{team} cannot run {flow}: no login in its list offers {model}"
    return None
