"""Why a question taken up from a session was not answered (design §4.9b *Why it did not answer*, TD-1423,
built by TD-1430).

When a session takes its own open question to another session up to the person (`ao msg person --thread
<id>`), the home reads the addressee's record as it stands and writes `unanswered` on the new question's
every copy. `read` makes that stamp from what the send already knows; `words` is the one place its fixed
sentence is written, which the CLI and the UI both call — never two copies.

The stamp carries the design's fields — `{by, state, at, since?, ended?, held?, lapsed?, gate?, cap?,
modal?, resets?, kind?, start_at?, waiting?, taken_by?}` — and four the words need when read later from the
stamp alone: `name` (the record's name, the words' `<name>`), `seat` (a seat's ceiling reads *Resume*, a
non-seat's *Restart*), `tail` (the *when it is read* sentence a session's send to it would have printed
at the read, on `working` and `idle`) and `taken_name` (on `taken_over`, the name of the session that
took it over, when `taken_by` is one)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sessionorc.mail import _NOT_LIVE, taken_over
from sessionorc.models import Session

# design §4.9b's states, in the order the first that holds is chosen
STATES = (
    "gone",
    "suspended",
    "held",
    "fills_exhausted",
    "restart_ceiling",
    "unreachable",
    "scheduled",
    "taken_over",
    "gated",
    "limited",
    "not_filled",
    "ended",
    "needs_you",
    "working",
    "idle",
)
_CEILINGS = ("gone", "suspended", "fills_exhausted", "restart_ceiling")


def _when(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _end(r: Session) -> str | None:
    """An `exited` or `closed` record's end: its `ended.at`, else its `closed_at`, else its `since` (a Stop
    or a Forget that no SessionEnd reported)."""
    ended = r.ended.get("at") if isinstance(r.ended, dict) else None
    return str(ended or r.closed_at or r.since or "") or None


def _later(a: str | None, b: str | None) -> bool:
    """Whether instant `a` is strictly later than `b` (an unreadable one: no)."""
    ta, tb = _when(a), _when(b)
    return ta is not None and tb is not None and ta > tb


def read(
    r: Session | None,
    by: str,
    *,
    question_at: str,
    at: str,
    unreachable: bool = False,
    over: Mapping[str, Any] | None = None,
    modal: bool = False,
    waiting: int = 0,
    tail: str = "",
    agent: bool = True,
    names: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """The stamp, the first state that holds (§4.9b). `r` is the walk's last record (None: `gone`), `by` its
    address; `question_at` the taken question's `at`; `over` the profile's usage-gate row (`_profile_over`)
    or None; `modal` whether a `limited` record's cap is a dialog; `waiting` its questions waiting, the taken
    one left out; `tail` the `read_when` sentence a session's send to it would print now; `agent` whether the
    record runs an agent (a shell is never `taken_over`); `names` the home's records' names by id, for the
    session a `taken_over` stamp names."""
    out: dict[str, Any] = {"by": by, "at": at}
    if r is None:
        return {**out, "state": "gone"}
    out["name"] = r.name or by
    seat = bool(r.seat)
    if seat:
        out["seat"] = True
    gate = None
    if over is not None:
        gate = {"profile": r.profile, **({"resets": over["resets"]} if over.get("resets") else {})}
    ceiling = r.restart_ceiling if isinstance(r.restart_ceiling, dict) else None
    if r.suspended:
        return {**out, "state": "suspended", "since": r.suspended.get("at")}
    if seat and isinstance(r.stop_held, Mapping):
        # held by its team's stop (§6 rule 3 *A stopped team's seats are held*, TD-1564): the hold before the ceiling
        mark = r.stop_held
        held = {"state": "held", "since": mark.get("at"), "team": mark.get("team") or r.team}
        return {k: v for k, v in {**out, **held, "stopped_by": mark.get("by")}.items() if v is not None}
    if ceiling is not None:
        fill = ceiling.get("why") == "fill"
        out.update(state="fills_exhausted" if fill else "restart_ceiling", since=ceiling.get("at"))
        if fill and ceiling.get("held"):
            out["held"] = True
        if gate is not None:
            out["gate"] = gate
        return out
    live = r.state not in _NOT_LIVE
    if unreachable or r.state == "unreachable":
        out["state"] = "unreachable"
    elif r.state == "scheduled":
        out.update(state="scheduled", start_at=r.start_at)
    elif taken_over(r, agent):
        # held: a member taken over, its mail not waking it (§4.5 *A taken-over member*, TD-1444)
        out.update(state="taken_over", since=r.mode_at, taken_by=r.mode_by)
        if r.mode_by and r.mode_by != "person":
            out["taken_name"] = (names or {}).get(r.mode_by) or None
    elif gate is not None and (live or seat):
        out.update(state="gated", gate=gate)
        if gate.get("resets"):
            out["resets"] = gate["resets"]
    elif r.state == "limited":
        out["state"] = "limited"
        cap = r.pending.text if r.pending is not None else ""
        if cap:
            out["cap"] = cap
        if modal:
            out["modal"] = True
    elif not live:
        end = _end(r)
        if seat and not _later(r.created, question_at) and not _later(end, question_at):
            out["state"] = "not_filled"
        elif _later(end, question_at):
            since = r.created if _later(r.created, question_at) else question_at
            out.update(state="ended", since=since, ended=end)
        else:
            out.update(state="ended", ended=end)
    elif r.state == "needs-you":
        out.update(state="needs_you", kind=r.pending.kind if r.pending is not None else "")
    else:
        out.update(state="idle" if r.state == "idle" else "working", waiting=waiting)
        if tail:
            out["tail"] = tail
    lapsed = r.fill_lapsed.get("at") if isinstance(r.fill_lapsed, dict) else None
    if lapsed and _later(lapsed, question_at):
        out["lapsed"] = lapsed
    return {k: v for k, v in out.items() if v is not None}


# what each state's sentence names, without which `words` says the plain line
_NEEDS = {
    "suspended": ("since",),
    "held": ("since", "team", "stopped_by"),
    "fills_exhausted": ("since",),
    "restart_ceiling": ("since",),
    "scheduled": ("start_at",),
    "gated": ("gate",),
    "ended": ("ended",),
}


def clock(value: Any, now: datetime | None = None) -> str:
    """A stamp's time as the Inbox draws times: local `HH:MM`, its weekday first when not today; the value
    as given when it is no time."""
    t = _when(value)
    if t is None:
        return str(value or "")
    t = t.astimezone()
    today = (now or datetime.now(UTC)).astimezone().date()
    return f"{'' if t.date() == today else t.strftime('%a ')}{t:%H:%M}"


def _until(gate: Mapping[str, Any], now: datetime | None) -> str:
    resets = gate.get("resets")
    return f"until {clock(resets, now)}" if resets else "until its usage reading resets"


def words(stamp: Mapping[str, Any], now: datetime | None = None) -> str:
    """The home's fixed words for a stamp (design §4.9b *Why it did not answer*): one sentence per state,
    the same for every asker, its times local."""
    s = stamp.get("state")
    name = str(stamp.get("name") or stamp.get("by") or "")
    plain = f"{name} did not answer."
    # a stamp missing what its state's sentence names reads as the plain line, never a half sentence
    if any(not stamp.get(k) for k in _NEEDS.get(str(s), ())) or s not in STATES:
        return plain
    t = lambda key: clock(stamp.get(key), now)  # noqa: E731
    gate = stamp.get("gate") if isinstance(stamp.get("gate"), Mapping) else None
    seat = bool(stamp.get("seat"))
    if s == "gone":
        return f"{name} is no longer a session; nobody holds this question."
    if s == "suspended":
        return f"{name} is suspended since {t('since')} — your own resume of that conversation, or Forget, ends it."
    if s == "held":
        # *stopped*, never *wound down*: the stamp keeps who ended the team, not its later reading (§4.9b, TD-1564)
        who = "by you" if stamp.get("stopped_by") == "person" else "at its stop time"
        return f"{name} waits for its team's Start: {stamp.get('team')} was stopped ({who})."
    if s == "fills_exhausted":
        if stamp.get("held"):
            text = (
                f"{name} was not filled: fills exhausted since {t('since')}, tripped twice running — "
                "Restart on its fills-exhausted row brings it back"
            )
        else:
            text = (
                f"{name} was not filled: fills exhausted since {t('since')} — it fills again after the hour, "
                "or Restart on its fills-exhausted row now"
            )
        if gate is not None:
            text += f" — its profile {gate.get('profile')} is paused {_until(gate, now)}, and the fill waits for it"
        return text + "."
    if s == "restart_ceiling":
        press = "Resume on its restart row brings it back" if seat else "Restart on its restart row brings it back"
        text = f"{name} stopped at the restart ceiling at {t('since')} — {press}"
        if not seat:
            text += " into its team's run"
            if gate is not None:
                paused = f"its profile {gate.get('profile')} is paused {_until(gate, now)}"
                text += f" — {paused}, and Restart refuses until then"
        return text + "."
    if s == "unreachable":
        text = f"{name}'s host is not answering; the question is delivered when it is back"
    elif s == "scheduled":
        text = f"{name} starts at {t('start_at')}"
    elif s == "taken_over":
        by = stamp.get("taken_by")
        if not stamp.get("since"):
            held = "held interactive"
        elif not by:  # a start's stamp names nobody
            held = f"held interactive since {t('since')}, from its start"
        else:
            who = "you" if by == "person" else str(stamp.get("taken_name") or by)
            held = f"held interactive since {t('since')} by {who}"
        text = f"{name} is {held} — its mail does not wake it; Hand back on its Focus or its held row returns it"
    elif s == "gated":
        if gate is None or not gate.get("profile"):
            return plain
        text = f"{name}'s profile {gate['profile']} is paused by the usage gate {_until(gate, now)}"
    elif s == "limited":
        cap = f": {stamp['cap']}" if stamp.get("cap") else ""
        text = f"{name} is at its usage cap{cap} — " + (
            "answered on its pane" if stamp.get("modal") else "it is rung after"
        )
    elif s == "not_filled":
        text = f"{name} was never filled for this question"
    elif s == "ended":
        if stamp.get("since"):
            text = f"{name} held the question from {t('since')} and ended at {t('ended')} without answering"
        else:
            text = f"{name} ended at {t('ended')}, before the question was sent"
    elif s == "needs_you":
        what = {"permission": "a permission", "question": "its own question"}.get(str(stamp.get("kind")), "you")
        text = f"{name} is waiting on {what} in its pane — its row under Needs you answers it"
    elif s in ("working", "idle"):
        try:
            n = int(stamp.get("waiting") or 0)
        except (TypeError, ValueError):
            return plain
        text = f"{name} is {s} and has not answered, {n} question{'' if n == 1 else 's'} waiting"
        if stamp.get("tail"):
            text += f" — {stamp['tail']}"
    else:
        return plain
    if stamp.get("lapsed"):
        text += f" — it was at its fill ceiling until {t('lapsed')}"
    return text + "."
