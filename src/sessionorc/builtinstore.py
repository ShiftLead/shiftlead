"""The built-in sets (design §4.9d *The built-in seats and their page*, TD-2066): `settings.yml`'s `builtins.<set>` and
`repos.<repo>.builtins`, the page's four writes on them, and the one function that gives a repo's set and a seat's model
and login.

Pure: each function takes the settings document, or the rows a caller read, and neither reads nor writes a file. The
host agent's `builtins_*` calls make the write. No launch reads `seat` yet: that is the launch path's (§4.9e, TD-1976).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from typing import Any

from sessionorc import logins, teamstore
from sessionorc.teamstore import BEFORE, STALE, TeamError

DEFAULT = "default"
# key, the row's name, the words in a *cannot run* line, what it does, whom it acts for
SEATS: tuple[tuple[str, str, str, str, str], ...] = (
    ("tech-lead", "Tech lead", "the tech lead", "answers sessions' questions, tags new entries", "each team"),
    ("prompts", "Prompts", "the prompts seat", "answers permission prompts", "the repo"),
    ("board-answers", "Board answers", "board answers", "carries out what you decided on the board", "the repo"),
    (
        "unheld-pull-requests",
        "Pull requests nobody holds",
        "pull requests nobody holds",
        "cures a red or orphaned pull request",
        "the repo",
    ),
    ("sweeper", "Sweeper", "the sweeper", "the periodic sweep for stranded work", "the repo"),
)
SEAT_KEYS = tuple(s[0] for s in SEATS)
PROMPTS = "prompts"
# the package's models (§4.9d *The store*): what a seat a set leaves out runs on
PACKAGE_MODELS: dict[str, str] = {
    "tech-lead": "opus",
    "prompts": "sonnet",
    "board-answers": "sonnet",
    "unheld-pull-requests": "sonnet",
    "sweeper": "haiku",
}
SET_KEYS = ("label", "models", "logins")
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _held(doc: Mapping[str, Any]) -> Mapping[str, Any]:
    value = doc.get("builtins")
    return value if isinstance(value, Mapping) else {}


def _clean_models(value: Any) -> dict[str, str]:
    """A set's `models` as written: a hand edit's unknown seat or non-text model is left out, so that seat reads the
    package's."""
    if not isinstance(value, Mapping):
        return {}
    return {k: v for k, v in value.items() if k in SEAT_KEYS and isinstance(v, str) and _MODEL.fullmatch(v)}


def _clean_logins(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for lk in value:
        if isinstance(lk, str) and lk not in out:
            tool, name = logins.split(lk)
            if tool and logins.valid_name(name):
                out.append(lk)
    return out


def _read(entry: Any) -> dict[str, Any]:
    row = entry if isinstance(entry, Mapping) else {}
    label = row.get("label")
    return {
        "label": label if isinstance(label, str) and label else None,
        "models": _clean_models(row.get("models")),
        "logins": _clean_logins(row.get("logins")),
    }


def sets(doc: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Every set, `default` first and the rest by name. Where the file holds no `default`, it reads as the package's
    models and an empty list (§4.9d *The store*)."""
    held = _held(doc)
    first = _read(held[DEFAULT]) if DEFAULT in held else {"label": None, "models": dict(PACKAGE_MODELS), "logins": []}
    names = sorted(
        (n for n in held if isinstance(n, str) and n != DEFAULT), key=str.casefold
    )  # a hand edit's other key
    rest = {n: _read(held[n]) for n in names}
    return {DEFAULT: first, **rest}


def repo_set(doc: Mapping[str, Any], repo: str) -> str:
    """The set a repo uses: the one it names, else `default`; a name no set holds, a hand edit's, reads `default`."""
    repos = doc.get("repos")
    row = repos.get(repo) if isinstance(repos, Mapping) else None
    named = row.get("builtins") if isinstance(row, Mapping) else None
    return named if isinstance(named, str) and named in sets(doc) else DEFAULT


def named_by(doc: Mapping[str, Any], name: str) -> list[str]:
    """The repos whose `builtins` key names this set, by name. A repo with no pick names none, `default` included."""
    repos = doc.get("repos")
    if not isinstance(repos, Mapping):
        return []
    return sorted(str(r) for r, row in repos.items() if isinstance(row, Mapping) and row.get("builtins") == name)


def model(entry: Mapping[str, Any], seat: str) -> str:
    """The model a set gives a seat: its own, else the package's."""
    return str((entry.get("models") or {}).get(seat) or PACKAGE_MODELS[seat])


def seat(doc: Mapping[str, Any], repo: str, key: str, rows: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """The one reading of a repo's built-in seat (§4.9d *The login a seat starts on*): the repo's `set`, the seat's
    `model` and teamstore's first-usable-login `pick` on the set's list, with no team's reserve added."""
    name = repo_set(doc, repo)
    entry = sets(doc)[name]
    held = model(entry, key)
    return {"set": name, "model": held, "now": teamstore.pick(entry["logins"], held, rows)}


def cannot_run(
    name: str, entry: Mapping[str, Any], rows: Mapping[str, Mapping[str, Any]], *, director: bool = False
) -> list[str]:
    """Each seat this set cannot run, in the page's words (§4.9d): its list is empty, or no login in it offers the
    seat's model. A login offering it but unusable right now is a wait, not this. Where the org has a director the
    prompts seat is not written, so it is not read."""
    order = list(entry.get("logins") or ())
    out: list[str] = []
    for key, _shown, words, _does, _for in SEATS:
        if director and key == PROMPTS:
            continue
        held = model(entry, key)
        if not order:
            out.append(f"{name} cannot run {words}: its login list is empty")
        elif not any(teamstore.offers(rows.get(lk) or {}, held) for lk in order):
            out.append(f"{name} cannot run {words}: no login in its list offers {held}")
    return out


def version(doc: Mapping[str, Any]) -> str:
    """The version of what the page writes: every set and every repo's pick. The page draws one form of them, and a
    repo's other switches save on their own road, so they do not move it."""
    repos = doc.get("repos")
    picks = (
        {str(r): row["builtins"] for r, row in repos.items() if isinstance(row, Mapping) and "builtins" in row}
        if isinstance(repos, Mapping)
        else {}
    )
    return hashlib.sha256(json.dumps([_held(doc), picks], sort_keys=True, default=str).encode()).hexdigest()[:12]


def _gate(doc: Mapping[str, Any], sent: str | None) -> None:
    if not teamstore.cut_over(doc):
        raise TeamError(BEFORE)
    if sent is None or sent != version(doc):
        raise TeamError(STALE)


def _models(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise TeamError("models names a seat and its model")
    out: dict[str, str] = {}
    for key, held in value.items():
        if key not in SEAT_KEYS:
            raise TeamError(f"{key!r} is not a built-in seat: {', '.join(SEAT_KEYS)}")
        if not isinstance(held, str) or not _MODEL.fullmatch(held):
            raise TeamError(f"{held!r} is not a model")
        out[key] = held
    return out


def _writable(doc: dict[str, Any]) -> dict[str, Any]:
    """`builtins:` as a mapping to write in, with `default` in it as it reads, so a first write keeps the package's."""
    held = doc.get("builtins")
    out = held if isinstance(held, dict) else {}
    if DEFAULT not in out:
        out[DEFAULT] = {"models": dict(PACKAGE_MODELS), "logins": []}
    doc["builtins"] = out
    return out


def new(doc: dict[str, Any], name: str, label: Any = None) -> str:
    """**+ New set**'s write, in place: `default`'s models and an empty list. Its name follows a team's rule: a login's
    characters, unique compared case-folded, fixed once made. Refused before the cut-over."""
    if not teamstore.cut_over(doc):
        raise TeamError(BEFORE)
    if not isinstance(name, str) or not logins.valid_name(name):
        raise TeamError(f"{name!r} is not a set's name: letters, digits, dashes and underscores, at most 24")
    if name.casefold() in {n.casefold() for n in sets(doc)}:
        raise TeamError(f"there is already a set named {name}")
    words = teamstore._label(label)
    models = dict(sets(doc)[DEFAULT]["models"])
    held = _writable(doc)
    held[name] = {**({"label": words} if words else {}), "models": models, "logins": []}
    return f"built-in set {name} made"


def apply(doc: dict[str, Any], name: str, change: Mapping[str, Any], sent: str | None) -> str:
    """One `builtins_set` on the document, in place: its words for the commit line. `models` is the whole mapping; an
    empty label clears the label."""
    _gate(doc, sent)
    if name not in sets(doc):
        raise TeamError(f"no built-in set {name!r}")
    if len(change) != 1 or next(iter(change)) not in SET_KEYS:
        raise TeamError(f"builtins_set takes one of {', '.join(SET_KEYS)}")
    key, value = next(iter(change.items()))
    if key == "label":
        new_value: Any = teamstore._label(value)
    elif key == "models":
        new_value = _models(value)
    else:
        new_value = teamstore._logins(value)
    store = _writable(doc)
    entry = store[name] if isinstance(store.get(name), dict) else store.setdefault(name, {})
    if not isinstance(entry, dict):  # a hand edit's non-mapping: this write replaces it
        entry = store[name] = {}
    if new_value is None:
        entry.pop(key, None)
    else:
        entry[key] = new_value
    return f"built-in set {name} {key} {'cleared' if new_value is None else 'set'}"


def delete(doc: dict[str, Any], name: str, sent: str | None) -> str:
    """**Delete**'s write, in place: refused for `default`, and for a set a repo names until its pick moves."""
    _gate(doc, sent)
    if name == DEFAULT:
        raise TeamError("the default set always exists")
    if name not in sets(doc):
        raise TeamError(f"no built-in set {name!r}")
    if using := named_by(doc, name):
        raise TeamError(f"{name} is used by {', '.join(using)}: move their pick first")
    del doc["builtins"][name]
    return f"built-in set {name} deleted"


def pick(doc: dict[str, Any], repo: str, name: str, sent: str | None) -> str:
    """`repo_builtins`' write, in place: the set a repo uses. `default` is the key's absence (§4.9d *The store*)."""
    _gate(doc, sent)
    if not isinstance(repo, str) or not repo:
        raise TeamError("name the repo")
    if name not in sets(doc):
        raise TeamError(f"no built-in set {name!r}")
    repos = doc.get("repos")
    held = repos if isinstance(repos, dict) else {}
    row = held.get(repo)
    entry = dict(row) if isinstance(row, Mapping) else {}
    if name == DEFAULT:
        entry.pop("builtins", None)
    else:
        entry["builtins"] = name
    if entry:
        held[repo] = entry
    else:
        held.pop(repo, None)
    if held:
        doc["repos"] = held
    else:
        doc.pop("repos", None)
    return f"{repo} uses built-in set {name}"


def using(doc: Mapping[str, Any], name: str, repos: Iterable[str]) -> list[str]:
    """The registered repos that use this set, `default` taking every repo that names none."""
    return [r for r in repos if repo_set(doc, r) == name]
