"""Settings and usage (TD-317 slice 2, TD-108's design): the usage a session reports and the home merges
(`rpc_usage_report`, `rpc_usage`), the gate's reading (`rpc_gate`), the one settings file read and written
by the Settings page (`rpc_settings`, `rpc_set_settings`, design §4.5 screen 9, §4.4 *Settings*) and the
home's definition files committed (`rpc_commit_defs`). A mixin `HostAgent` inherits; moved from
`agent_wake.py` as written, and the state it reads is the agent's.
"""

from __future__ import annotations

import asyncio
import copy
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sessionorc import (
    adapters,
    agent_common,
    agent_spend,
    defs,
    gitinfo,
    hosts,
)
from sessionorc import cadence as cadence_mod
from sessionorc import seams as seams_mod
from sessionorc import settings as settings_mod
from sessionorc import settle as settle_mod
from sessionorc import spend as spend_mod
from sessionorc import usage as usage_mod
from sessionorc.agent_common import (
    RpcError,
    _parse,
    _usage_key,
    log,
)
from sessionorc.models import (
    PERSON,
    Session,
    now_iso,
)


class SettingsMixin:
    async def rpc_usage_report(self, windows: Any = None, fresh: bool = False, caller: Any = None) -> dict[str, Any]:
        """What a session of the tool was told about its account's limits (§4.4 *Usage, reported
        first and asked for last*, TD-233 slice 2), from its adapter's hook command: `windows`
        `[{label, pct, resets}]` as the adapter's `usage_report` read them, `fresh` whether the
        session had a response since its last report. The caller is the session, as the envelope
        names it. Merged into its account's reading by what a window can do (`sessionorc.usage`),
        never by who spoke last; a report that is not fresh moves no age. Answers `{taken}`: false
        for a caller that is no live tool session here, a metered profile, or no windows — a
        report is never refused in words, since the status line that sends it prints nothing."""
        s = self.sessions.get(str(caller or ""))
        cleaned = usage_mod.clean_windows(windows)
        if s is None or (key := await self._usage_merge_report(s, cleaned, bool(fresh))) is None:
            return {"taken": False}
        self._forward_usage_report(s, key, cleaned, bool(fresh))
        return {"taken": True}

    async def _usage_merge_report(
        self, s: Session, cleaned: list[dict[str, Any]], fresh: bool, key: str | None = None
    ) -> str | None:
        """One session's report merged into its account's reading, this host's session or a node's
        (§4.4 *A node's sessions report to their node*, TD-233 slice 2), under `key`, the account
        a node keyed its session's profile by, or the one this host keys it by. The account key it
        merged under, or None for a session that is no live tool session, a metered profile, or
        no windows."""
        if not adapters.has_agent(s.adapter) or s.state in ("exited", "closed") or not cleaned:
            return None
        ad = adapters.get(s.adapter)
        # `_metered` is read from this host's profile files, and a node's profile of the same name
        # may be another login there: a node withholds its own metered profiles (the techlead's
        # read of #783)
        if not getattr(ad, "usage_for", None) or (self.sessions.get(s.id) is s and s.profile in self._metered):
            return None
        key = key or _usage_key(ad, s.adapter, s.profile)[0]
        # an account first met since a restart takes the reading its profile held, if it is of this
        # account — a node's included, so its history does not start again (the techlead's read of #783)
        self._usage_seed(key, [s.profile], strict=self.sessions.get(s.id) is not s)
        was = self._usage_acct.get(key)
        merged = usage_mod.merge(was, cleaned, at=now_iso(), source="reported", fresh=fresh, by=s.name)
        if merged != was:
            self._usage_acct[key] = merged
            await self._usage_spread(key)
            self._usage_limits(self._usage_live(), self._metered)
            await self._push_changes()
            await self._push_usage_readings()
        return key

    async def rpc_usage(self) -> dict[str, dict[str, Any]]:
        """Last known usage per profile (TD-001): what the top bar shows."""
        return dict(self._usage)

    async def rpc_gate(self) -> dict[str, Any]:
        """The usage gate as it stands (design §4.7 `ao gate`, §6 *The readers*, TD-100, TD-1610): `{accounts:
        {<key>: {profiles, billing, reserves | amounts, windows, labels}}, file, max_age}`, an account for each
        key under this host's `settings.yml` `usage_gate:` and each the profiles here or a node name
        (`_gate_accounts`); `max_age` is `usage.max_age` as kept (TD-233 slice 4). A read: never gated."""
        now = datetime.now(UTC)
        whole = settings_mod.load()
        raw = whole.get("usage_gate") if isinstance(whole.get("usage_gate"), dict) else {}
        watched = {
            s.profile
            for s in self.sessions.values()
            if s.unattended and s.state not in ("exited", "closed", "scheduled")
        }
        max_age = settings_mod.usage(whole).get("max_age", settings_mod.MAX_AGE_DEFAULT)
        return {
            "accounts": self._gate_accounts(whole, raw, watched, now),
            "file": str(settings_mod.settings_file()),
            "max_age": max_age,
        }

    def _gate_accounts(
        self, whole: dict[str, Any], raw: dict[str, Any], watched: set[str], now: datetime
    ) -> dict[str, Any]:
        """The `gate` reply's `accounts` (§6 *The readers*, TD-1610): `{<key>: {profiles, billing, reserves |
        amounts, windows, labels}}` — an account for each key under `usage_gate:`, each the adapters' profiles
        name and each a node has reported under. One with no reading carries `windows: []`, so its card can
        take a first reserve; an orphan key no profile names carries `profiles: []`, so it is seen. An
        account whose profiles disagree on billing (§4.2a) is `billing: "mixed"`, each profile's in
        `billings`, with both its percents and its amounts. A profile with unattended sessions live makes the
        account's rows the gate's (`_gate_windows`), projected past `max_age` as the gate reads them."""
        doc, amounts = settings_mod.reserves(whole), settings_mod.amounts(whole)
        keys = {str(k) for k in raw if settings_mod.account_key(k)}
        keys |= {k for p in self._gate_profiles() if (k := self._account_key(p)) is not None}
        keys |= set(self._usage_remote_keys.values())
        keys |= {k for accts in self._spend_named.values() for k in accts}
        records = [*self.sessions.values(), *(r for recs in self.remote.values() for r in recs.values())]
        # the unnamed default profile a record runs under (§6 *The profiles on an account*): `_account_on`
        # counts it as the listed name it stands for, but a reading and a chip are keyed `""`, so the
        # reply lists it on the account it resolves to, where its reading and its chip's line are found
        bare = (
            self._account_key("") if any(r.profile == "" and adapters.has_agent(r.adapter) for r in records) else None
        )
        out: dict[str, Any] = {}
        for key in sorted(keys):
            on = self._account_on(key)
            if key == bare and "" not in on:
                on[""] = "metered" if self._is_metered("") else "subscription"  # as `_account_on` bills a record's
            names, bills = sorted(on), set(on.values())
            if not bills and amounts.get(key) and not doc.get(key):
                bills = {"metered"}  # an orphan key holding only amounts reads as what it holds
            billing = "metered" if bills == {"metered"} else "subscription" if len(bills) <= 1 else "mixed"
            entry: dict[str, Any] = {"profiles": names, "billing": billing}
            if billing == "mixed":
                entry["billings"] = dict(sorted(on.items()))
            if billing != "subscription":
                written = raw.get(key) if isinstance(raw.get(key), dict) else {}
                mine = {label: written[label] for label in amounts.get(key) or {} if label in written}
                first = next((p for p in names if p in self._usage), names[0] if names else "")
                entry |= {"amounts": mine, "windows": self._amount_rows(first, mine), "labels": list(spend_mod.LABELS)}
            if billing != "metered":
                by_label = doc.get(key) or {}
                reading = self._usage_acct.get(key) or next((self._usage[p] for p in names if p in self._usage), {})
                windows = reading.get("windows")
                if live := [p for p in names if p in watched]:
                    windows = self._gate_windows(live[0], now, whole)
                rows = settings_mod.lines(by_label, windows, now)
                entry |= {
                    "reserves": by_label,
                    "labels": [
                        *(entry.get("labels") or []),  # a mixed account's spend labels first
                        *(
                            label
                            for w in windows or []
                            if isinstance(w, dict) and (label := str(w.get("label"))) not in (entry.get("labels") or [])
                        ),
                    ],
                    **({"fetched": reading["fetched"]} if reading.get("fetched") else {}),
                    **({"source": reading.get("source") or "asked"} if reading.get("fetched") else {}),
                }
                entry["windows"] = rows if billing == "subscription" else [*entry["windows"], *rows]
            out[key] = entry
        return out

    def _gate_profiles(self) -> dict[str, bool]:
        """The profiles the `gate` reply lists, each to whether its adapter's `profiles()` bills it
        `metered`: every profile an adapter here lists (§4.3) and every one a record runs under."""
        out: dict[str, bool] = {}
        for name in adapters.names():
            if not adapters.has_agent(name):
                continue
            try:
                listed = getattr(adapters.get(name), "profiles", None)
                for p in (listed() if listed else None) or ():
                    if isinstance(p, dict) and isinstance(p.get("name"), str):
                        out[p["name"]] = out.get(p["name"], False) or p.get("billing") == "metered"
            except Exception as e:  # noqa: BLE001 — an adapter's list never stops the read
                log.warning("profiles() on %s failed: %s", name, e)
        records = [*self.sessions.values(), *(r for recs in self.remote.values() for r in recs.values())]
        for r in records:
            if adapters.has_agent(r.adapter):
                out.setdefault(r.profile, False)
        return out

    async def rpc_settings(self, caller: Any = None, profiles: Any = None) -> dict[str, Any]:
        """`ao settings` and the Settings page's read (design §5, §4.7, TD-146): the home's
        `settings.yml`, each key as its reader keeps it, with what it makes today — each account's
        lines against its last reading (`usage_accounts`, as `gate` answers its `accounts`), each
        team's stop time with whether it has passed and its reserve priority. `migrate` names a
        `ui.yml` still on disk, which is no longer read. **A person's own**, refused to a session as
        `set_settings` is: `person:` is theirs, and what a session needs of the gate `gate` answers.
        `profiles`, the profile names the
        Settings page read from `profiles.yml` (this agent reads no profile list), adds `labels`: each
        name to the window labels of the reading the gate judges it by, in the reading's order — the
        ones a schedule's window is checked against (§4.5a *Settings page: Teams*, TD-1346); a value
        that is not a list of strings is taken as absent."""
        agent_common.person_only(caller, "read the settings", "§5 settings.yml", self._graph())
        doc, now = settings_mod.load(), datetime.now(UTC)
        reply = await self.rpc_gate()
        teams = {
            name: {
                **t,
                **({"passed": _parse(t["until"]) <= now} if "until" in t else {}),
                **({"starts": self._schedule_starts(name, t["schedule"], now)} if "schedule" in t else {}),
            }
            for name, t in settings_mod.teams(doc).items()
        }
        out = {
            "file": str(settings_mod.settings_file()),
            "usage_accounts": reply["accounts"],  # `ao settings` prints by account (TD-1610)
            "teams": teams,
            "repos": settings_mod.repos(doc),
            "usage": {"max_age": settings_mod.usage(doc).get("max_age", settings_mod.MAX_AGE_DEFAULT)},
            # the install's `settle:` as written, `{}` for the built-in alone (§4.4, TD-710)
            "settle": doc["settle"] if isinstance(doc.get("settle"), dict) else {},
            # the weights the seat pass reads: the design's default under what the person set (TD-830)
            "spend": {"weights": settings_mod.weights(doc)},
            "person": settings_mod.person(doc),
            "notify": settings_mod.notify(doc),
            "sweep": settings_mod.sweep(doc),
            "reach": settings_mod.reach(doc),
            "permissions": self._permissions_read(doc),
            "migrate": [],
        }
        if isinstance(profiles, list) and all(isinstance(p, str) for p in profiles):
            out["labels"] = {p: self._window_labels(p) for p in profiles}
        if settings_mod.ui_yml().exists():
            out["migrate"].append(
                f"{settings_mod.ui_yml()}: ui.yml is no longer read — its open_in lives under person:"
            )
        return out

    def _window_labels(self, profile: str) -> list[str]:
        """The window labels of the reading the gate judges `profile` by (its own, else its account's,
        TD-456), in the reading's order: what a schedule's window is checked against (§6 *Schedule*)."""
        return [str(w.get("label")) for w in self._gate_reading(profile).get("windows") or [] if isinstance(w, dict)]

    def _schedule_window_known(self, rule: dict[str, str]) -> bool:
        """A schedule's window checked against its profile's reading (§6 *Schedule*, §4.7 `ao schedule`,
        TD-133): a label the reading does not report is refused, naming the reported ones, as `ao gate`'s
        reserves are; False when the profile has no reading yet, so nothing could be checked."""
        reported = self._window_labels(rule["profile"])
        if not reported:
            return False
        if rule["window"] not in reported:
            raise RpcError(
                f"schedule: profile {rule['profile']} reports no window {rule['window']}: "
                f"its windows are {', '.join(reported)} (design §4.7)"
            )
        return True

    def _schedule_starts(self, team: str, rule: Any, now: datetime) -> dict[str, Any]:
        """When a team's schedule next fires (§4.7 `ao schedule`, §4.5a *starts* note, TD-133): the
        upcoming reset the tick last read for this rule (`schedule_next` on the home's host record), else
        the reset in the profile's reading while it is ahead — `{at}`, with `held` while a passed reset
        waits for a node's link; `{at: None}` when nothing is known to wait for."""
        if not isinstance(rule, dict):
            return {"at": None}

        def utc(value: Any) -> datetime | None:  # an offset-carrying instant, else None: never a guessed clock
            try:
                t = _parse(str(value))
            except (TypeError, ValueError):
                return None
            return t.astimezone(UTC).replace(microsecond=0) if t.tzinfo is not None else None

        def said(t: datetime) -> str:
            return t.isoformat().replace("+00:00", "Z")

        teams = self._host_rec.get("teams")
        rec = teams.get(team) if isinstance(teams, dict) else None
        nxt = rec.get("schedule_next") if isinstance(rec, dict) else None
        same = isinstance(nxt, dict) and all(nxt.get(k) == rule.get(k) for k in ("profile", "window"))
        if same and (at := utc(nxt.get("at"))) is not None:
            return {"at": said(at), **({"held": True} if nxt.get("held") else {})}
        for w in self._gate_reading(str(rule.get("profile") or "")).get("windows") or []:
            mine = isinstance(w, dict) and w.get("label") == rule.get("window")
            if mine and (at := utc(w.get("resets"))) is not None and at > now:
                return {"at": said(at)}
        return {"at": None}

    @staticmethod
    def _permissions_read(doc: dict[str, Any]) -> dict[str, Any]:
        """`permissions:` as the host matches it (§4.9b, TD-641), with every malformed entry named:
        a shape the reader drops, or a rule no adapter's syntax carries (each adapter with a
        `rule_problem` is asked, and a rule is malformed only when every one of them refuses it)."""
        rules, bad = settings_mod.permissions(doc)
        judges = [j for name in adapters.names() if (j := getattr(adapters.get(name), "rule_problem", None))]
        kept: dict[str, dict[str, list[str]]] = {}
        for role, lists in rules.items():
            for key, got in lists.items():
                for rule in got:
                    problems = [p for j in judges if (p := j(rule))]
                    if judges and len(problems) == len(judges):
                        bad.append(f"permissions.{role}.{key}: {problems[0]}")
                    else:
                        kept.setdefault(role, {}).setdefault(key, []).append(rule)
        return {"rules": kept, "malformed": bad}

    async def rpc_add_repo(self, path: str = "", adopted: bool = False, caller: Any = None) -> dict[str, Any]:
        """`ao repo add <path>` (design §4.7 **`ao repo add`**, §5 *Repos*, TD-1010): append the main
        checkout `path` is in to the home's roster, `repos.txt` (`repos_registry` where `hosts.yml` names
        one) — **a person's own**, refused to a session as `set_settings` is, and at the home alone. A
        checkout holding agent-cadence's lock, or agent-cadence's source, is added; one without is refused
        here, since its adoption is offered by the client, unless `adopted` (its adoption PR is open: the
        repo is unserved until it merges, §5 *The seams*). A path already in the roster is refused. The
        next tick reads a checkout new to the roster whole, at once (`_refresh_repos`). Returns `{root,
        name, served}`, `served` as the seams reading finds it (§5 *The seams*: the tree, the gate and the
        ledger), whatever let it be added."""
        agent_common.person_only(caller, "add a repo", "§4.7 ao repo add", self._graph())
        if self.mode != "home":
            raise RpcError("ao repo add runs at the home (design §4.7): run ao repo add on the home")
        if not path:
            raise RpcError("ao repo add takes a checkout's path")
        try:
            here = (await asyncio.to_thread(gitinfo.main_checkout, Path(path).expanduser())).resolve()
        except gitinfo.WorktreeError:
            raise RpcError(f"{path} is not in a git checkout") from None
        if not (here / ".git").exists():  # a bare repo's parent, or a submodule's `.git/modules`
            raise RpcError(f"{path} is not in a checkout with a work tree")
        root = str(here)
        host = hosts.local_host()
        if any(Path(r).expanduser().resolve() == here for r in host.repos()):
            raise RpcError(f"{root} is in the roster already (design §5 Repos)")
        if not (await asyncio.to_thread(cadence_mod.holds, here) or adopted):
            raise RpcError(
                f"{root} holds no agent-cadence (no pin in {cadence_mod.PIN}, no {cadence_mod.LOCK}): "
                "its adoption comes first (design §4.7)"
            )
        reg = host.repos_registry
        try:
            reg.parent.mkdir(parents=True, exist_ok=True)
            with reg.open("ab+") as f:  # appended, never rewritten: nothing of the roster is lost
                f.seek(0, 2)
                ends = f.tell() == 0 or (f.seek(-1, 2), f.read(1))[1] == b"\n"
                f.write((b"" if ends else b"\n") + f"{root}\n".encode())
        except OSError as e:
            raise RpcError(f"could not write the roster {reg}: {e}") from None
        log.info("add_repo: %s added to %s by %s", root, reg, caller)
        roster = [*host.repos(), root]  # the age lack reads agent-cadence's checkout among them (TD-1012)
        served = (await asyncio.to_thread(seams_mod.reading, here, roster))["serve"]["ok"]
        return {"root": root, "name": here.name, "served": served}

    async def rpc_set_settings(
        self,
        profile: str = "",
        reserves: dict[str, Any] | None = None,
        account: str | None = None,
        teams: dict[str, Any] | None = None,
        repos: dict[str, Any] | None = None,
        person: dict[str, Any] | None = None,
        usage: dict[str, Any] | None = None,
        notify: dict[str, Any] | None = None,
        settle: dict[str, Any] | None = None,
        spend: dict[str, Any] | None = None,
        sweep: dict[str, Any] | None = None,
        reach: Any = None,
        caller: Any = None,
    ) -> dict[str, Any]:
        """Write the home's `settings.yml` (design §5, §4.7 `ao gate` / `ao team until` / `ao team
        reserve`, the Settings page; TD-100, TD-146): any subset of its keys, each validated before
        anything is written, then the whole file rewritten. **A person's own**, refused to a session
        as `inbox_pause` is. Takes effect on the next tick. At the home alone: a node forwards it while
        its link is up and refuses it offline (`modes.HOME_EDITS`), and every linked node is sent
        the file after the write (§4.4a *Settings, replicated*, TD-147).

        - `profile` + `reserves`: a window label to a flat percent, to `{per_day: N}`, or to None,
          which clears that window's reserve. A label the profile's adapter does not report is
          refused, with the reported ones named — except before the profile has any reading, when
          nothing can be checked and the reply says `unchecked`. The reserve is the profile's account's
          (§6 *A reserve is the account's*, TD-1581): it writes `usage_gate.<adapter>:<account>`, and the
          reply names the account and its profiles.
        - `account` + `reserves`: the same, the account's usage key named (`<adapter>:<account>`), for an
          account a node alone names, or one set before its first profile; one this home has not seen —
          no profile here names it, no node has reported under it — is refused.
        - `teams`: `{team: {schedule?, until?, reserve?, balance?, on_work?, flow?, size?} | None}` — a field set to
          None is cleared, a team set to None removed. The team's name is the client's to check
          against the org's definitions; the agent takes the key. A stop time already past is refused, as `ao until`'s.
        - `repos`: `{repo: {promote?: {auto: bool}, pull?: bool} | None}`.
        - `person`: `{open_in?, terminal?: {size?, face?, copy_on_select?}, inbox?: {board_show?},
          attach?: {max?}}`, a None clearing that key (or that field of terminal, inbox or attach).
        - `usage`: `{max_age: "1h" | "90m" | "off" | None}` (§6 *A reading the gate can no longer
          trust*, TD-233), None clearing it back to the default hour.
        - `notify`: `{telegram: {on?, secrets?, link?} | None}` (§4.10 *Told on Telegram when nobody is
          looking*, TD-319), a field set to None cleared; `on: true` with no secrets is refused.
        - `settle`: `{kind: duration}` (§4.4 *A new entry settles before it is pickable*, TD-710), the
          whole map replaced — `{}` removes the key, so the built-in `{design-first: 5m}` holds; a Kind
          that is not a word or a duration that is not `5m`, `1h`, `0` is refused.
        - `spend`: `{weights: {as_of?, <model prefix>: {<kind>: $ per million}}}` (§5 `spend.weights`, §4.4
          *Spend per seat*, TD-830), the whole key replaced — `{}` removes it, so the design's default
          holds; an unknown kind or a price that is not a number at or above zero is refused.
        - `sweep`: `{on?, every?, profile?}` (§5 `sweep:`, §4.9b *The sweep*, TD-1091), a field set to None
          cleared; and `repos.<repo>.sweep` turns one repo out of it.

        `reach` is refused, naming `ao connect`: `set_reach` is the one RPC that writes it (§4.7, TD-648)."""
        agent_common.person_only(caller, "change the settings", "§5 settings.yml", self._graph())
        if reach is not None:
            raise RpcError("set_settings does not write reach: — `ao connect` does, through set_reach (design §4.7)")
        if all(v is None for v in (reserves, teams, repos, person, usage, notify, settle, spend, sweep)):
            raise RpcError(
                "set_settings needs reserves, teams, repos, person, usage, notify, settle, spend or sweep "
                "(design §5 settings.yml)"
            )
        doc = settings_mod.load()
        before = copy.deepcopy(doc)
        before_teams = settings_mod.teams(doc)
        out: dict[str, Any] = {}
        if reserves is not None:
            out.update(self._reserves_change(doc, str(profile or ""), reserves, account))
        now = datetime.now(UTC)
        for key, value, parse, known in (
            ("teams", teams, settings_mod.parse_team, settings_mod.TEAM_KEYS),
            ("repos", repos, settings_mod.parse_repo, settings_mod.REPO_KEYS),
        ):
            if value is None:
                continue
            if not isinstance(value, dict) or not value:
                raise RpcError(f"set_settings: {key} is a mapping of names (design §5 settings.yml)")
            change: dict[str, Any] = {}
            for name, fields in value.items():
                if not str(name or "").strip():
                    raise RpcError(f"set_settings: {key} needs a name")
                if fields is None:
                    change[str(name)] = None
                    continue
                if not isinstance(fields, dict):
                    raise RpcError(f"{key}.{name}: a mapping of fields, or null to remove it")
                if unknown := sorted(set(map(str, fields)) - set(known)):
                    # a clear of a mistyped key is refused too: a typo is never a silent no-op
                    raise RpcError(f"{key}.{name}: unknown key {', '.join(unknown)} (known: {', '.join(known)})")
                kept = {k: v for k, v in fields.items() if v is not None}
                try:
                    parsed = parse(kept)
                except ValueError as e:
                    raise RpcError(f"{key}.{name}: {e}") from None
                if "until" in parsed and _parse(parsed["until"]) <= now:
                    raise RpcError(f"{key}.{name}: until {parsed['until']} has passed — a stop time is ahead (§6)")
                if key == "teams" and "schedule" in parsed and not self._schedule_window_known(parsed["schedule"]):
                    out["unchecked"] = True  # no reading of the profile yet: its labels cannot be checked
                change[str(name)] = {**{k: None for k in fields if fields[k] is None}, **parsed}
            doc[key] = settings_mod.merge(doc.get(key), change)
            out[key] = getattr(settings_mod, key)(doc)
            if key == "teams":  # the reply says when a schedule fires, as the `settings` read does (§4.7)
                for name, t in out[key].items():
                    if "schedule" in t:
                        t["starts"] = self._schedule_starts(name, t["schedule"], now)
        if person is not None:
            doc["person"] = self._person_change(doc.get("person"), person)
            out["person"] = settings_mod.person(doc)
        if usage is not None:
            if not isinstance(usage, dict) or not usage:
                raise RpcError("set_settings: usage is {max_age: 1h | 90m | off | null} (design §5 settings.yml)")
            if unknown := sorted(set(map(str, usage)) - set(settings_mod.USAGE_KEYS)):
                raise RpcError(f"usage: unknown key {', '.join(unknown)} (known: {', '.join(settings_mod.USAGE_KEYS)})")
            kept = dict(doc["usage"]) if isinstance(doc.get("usage"), dict) else {}
            if usage["max_age"] is None:
                kept.pop("max_age", None)
            else:
                try:
                    kept["max_age"] = settings_mod.parse_max_age(usage["max_age"])
                except ValueError as e:
                    raise RpcError(f"usage.max_age: {e}") from None
            doc["usage"] = kept
            out["usage"] = {"max_age": settings_mod.usage(doc).get("max_age", settings_mod.MAX_AGE_DEFAULT)}
        push_secrets = settings_mod.push(doc)["secrets"]
        if notify is not None:
            doc["notify"] = self._notify_change(doc.get("notify"), notify)
            out["notify"] = settings_mod.notify(doc)
        if settle is not None:
            try:
                doc["settle"] = settle_mod.parse(settle)
            except ValueError as e:
                raise RpcError(str(e)) from None
            out["settle"] = doc["settle"]
        if spend is not None:
            try:
                doc["spend"] = settings_mod.parse_spend(spend) if spend else {}
            except ValueError as e:
                raise RpcError(str(e)) from None
            out["spend"] = {"weights": settings_mod.weights(doc)}
        if sweep is not None:
            doc["sweep"] = self._sweep_change(doc.get("sweep"), sweep)
            out["sweep"] = settings_mod.sweep(doc)
        for key in ("teams", "repos", "person", "usage", "notify", "settle", "spend", "sweep"):
            if key in doc and not doc[key]:
                doc.pop(key)
        settings_mod.save(doc)
        if settings_mod.push(doc)["secrets"] != push_secrets:
            self._push_secrets_moved()  # a Save that moves either `secrets` reads the key afresh (§4.10, TD-1304)
        if teams is not None:
            after = settings_mod.teams(doc)
            for name in teams:
                await self._restamp_team(
                    str(name),
                    (before_teams.get(str(name)) or {}).get("until"),
                    (after.get(str(name)) or {}).get("until"),
                )
        held = [
            k
            for k in ("usage_gate", "usage", "teams", "repos", "person", "notify", "settle", "spend", "sweep")
            if k in doc
        ]
        log.info("settings.yml written; it holds %s", ", ".join(held) or "nothing")
        await self._push_settings()
        # detached, as the tick's hand-edit commit is: a wedged git must not hold Save up to its
        # timeouts, and the write it follows has already happened (the techlead's read of #800)
        task = asyncio.create_task(self._commit_defs(defs.settings_message(before, doc), ("settings.yml",)))
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)
        return out

    async def rpc_set_reach(self, reach: Any = None, caller: Any = None) -> dict[str, Any]:
        """`ao connect`'s write (design §4.7, §5 `reach:`, §4.5b *The setting*, TD-648): the one RPC that
        writes `settings.yml`'s `reach:` key — `set_settings` refuses it — `reach` the whole mapping, or
        None to remove it. Its shape is checked before anything is written: a known route, an `https`
        URL, a non-empty `allow`, and `team` and `aud` for `cloudflare`. **A person's own**, refused to a
        session as `set_settings` is, and the home's alone (`modes.HOME_EDITS`). Answers `{reach,
        before}`, `before` what the file held, which `ao connect` restores when its probe fails. The UI's
        route port reads the file itself; linked nodes are sent it, as after `set_settings`."""
        agent_common.person_only(caller, "change the route", "§4.7 ao connect", self._graph())
        doc = settings_mod.load()
        before_doc = copy.deepcopy(doc)
        before = doc.get("reach")
        if reach is None:
            doc.pop("reach", None)
        else:
            try:
                parsed = settings_mod.parse_reach(reach)
            except ValueError as e:
                raise RpcError(f"set_reach: {e}") from None
            if not parsed["allow"]:
                raise RpcError("set_reach: reach.allow names at least one login (design §4.5b)")
            if parsed["route"] == "cloudflare" and not ("team" in parsed and "aud" in parsed):
                raise RpcError("set_reach: a cloudflare route needs team and aud (design §4.5b)")
            doc["reach"] = parsed
        if doc.get("reach") == before:  # nothing changed: no write, no push to the nodes, no commit
            return {"reach": before, "before": before}
        settings_mod.save(doc)
        log.info("settings.yml: reach %s", "removed" if reach is None else f"set to {doc['reach']['route']}")
        await self._push_settings()
        task = asyncio.create_task(self._commit_defs(defs.settings_message(before_doc, doc), ("settings.yml",)))
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)
        return {"reach": doc.get("reach"), "before": before}

    @staticmethod
    def _sweep_change(current: Any, sweep: Any) -> dict[str, Any]:
        """`set_settings`'s `sweep` half: `{on?, every?, profile?}` laid over what the file holds, a field
        set to None cleared, each checked by `parse_sweep` before anything is written."""
        if not isinstance(sweep, dict) or not sweep:
            raise RpcError("set_settings: sweep is {on, every, profile} (design §5 settings.yml)")
        if unknown := sorted(set(map(str, sweep)) - set(settings_mod.SWEEP_KEYS)):
            raise RpcError(f"sweep: unknown key {', '.join(unknown)} (known: {', '.join(settings_mod.SWEEP_KEYS)})")
        try:
            parsed = settings_mod.parse_sweep({k: v for k, v in sweep.items() if v is not None})
        except ValueError as e:
            raise RpcError(str(e)) from None
        kept = {k: v for k, v in (current if isinstance(current, dict) else {}).items() if k in settings_mod.SWEEP_KEYS}
        for k, v in sweep.items():
            if v is None:
                kept.pop(k, None)
        return {**kept, **parsed}

    async def rpc_sweep_switch(self) -> dict[str, Any]:
        """The sweep switch as `ao team start` reads it (design §4.9b *The sweep*, TD-1091): `{on, every,
        profile?, off: [<repo>…]}` from `settings.yml` and nothing else of it, none of it secret. **Open to
        every caller**, the person and a session alike — a session runs `ao team start` (§4.9), where
        `settings` is the person's own read — and served at a node from its replica (§4.4a)."""
        return settings_mod.sweep(settings_mod.load())

    @staticmethod
    def _notify_change(current: Any, notify: Any) -> dict[str, Any]:
        """`set_settings`'s `notify` half: `{telegram: {on?, secrets?, link?} | None, push: {on?, telegram?,
        secrets?} | None}` laid over what the file holds, each field checked, a None clearing it; Telegram
        refused when it is switched on with no secrets to send with (§4.10, TD-319, TD-1302)."""
        if not isinstance(notify, dict) or not notify:
            raise RpcError(
                "set_settings: notify is {telegram: {on, secrets, link}, push: {on, telegram, secrets}} "
                "(design §5 settings.yml)"
            )
        if unknown := sorted(set(map(str, notify)) - set(settings_mod.NOTIFY_KEYS)):
            raise RpcError(f"notify: unknown key {', '.join(unknown)} (known: {', '.join(settings_mod.NOTIFY_KEYS)})")
        kept = dict(current) if isinstance(current, dict) else {}
        parts = (("telegram", settings_mod.TELEGRAM_KEYS, settings_mod.parse_telegram),
                 ("push", settings_mod.PUSH_KEYS, settings_mod.parse_push))  # fmt: skip
        for name, known_keys, parse in parts:
            if name not in notify:
                continue
            fields = notify[name]
            if fields is None:
                kept.pop(name, None)
                continue
            if not isinstance(fields, dict):
                raise RpcError(f"notify.{name}: a mapping of {', '.join(known_keys)}, or null to remove it")
            if unknown := sorted(set(map(str, fields)) - set(known_keys)):
                raise RpcError(f"notify.{name}: unknown key {', '.join(unknown)} (known: {', '.join(known_keys)})")
            try:
                parsed = parse({k: v for k, v in fields.items() if v is not None})
            except ValueError as e:
                raise RpcError(f"notify.{e}") from None
            got = settings_mod.notify({"notify": kept}).get(name, {})
            got = {**{k: v for k, v in got.items() if fields.get(k, ...) is not None}, **parsed}
            if name == "telegram" and got.get("on") and not got.get("secrets"):
                raise RpcError(
                    "notify.telegram.secrets: switching Telegram on needs the Doppler project/config that holds "
                    "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (design §4.10)"
                )
            if got:
                kept[name] = got
            else:
                kept.pop(name, None)
        return kept

    async def rpc_commit_defs(self, message: str = "", caller: Any = None) -> dict[str, Any]:
        """Commit the home's definition files with the act's words (design §4.9 *What is left at the
        home has a history*, TD-229 slice 5): a client calls it after it wrote `org.yml` itself —
        **Members…**'s `edit_members` — as `org: ao-grind +grinder-ao-3`. A person's own, and the
        home's alone (`modes.HOME_EDITS`). `{committed}`: false when nothing changed, the home is no
        work tree, or git failed (logged; the write it follows stands)."""
        agent_common.person_only(caller, "commit the definitions", "§4.9", self._graph())
        if self.mode != "home":
            raise RpcError("commit_defs runs at the home (design §4.9): this host is a node")
        message = " ".join(str(message or "").split())
        if not message:
            raise RpcError("commit_defs needs the act's words as its message")
        return {"committed": await self._commit_defs(message[:200])}

    async def _commit_defs(self, message: str, files: tuple[str, ...] = defs.DEFINITIONS) -> bool:
        """The home's one committer (§4.9): at the home only, one git at a time, in a thread; never
        raises, since the write it follows has already happened."""
        if self.mode != "home":
            return False  # a node's replica of `settings.yml` is not tracked
        try:
            async with self._defs_lock:
                return await asyncio.to_thread(defs.commit, message, files=files)
        except Exception:  # noqa: BLE001 — a history that fails is a log line, never the write's failure
            log.exception("committing the home's definitions failed")
            return False

    def _reserves_change(self, doc: dict[str, Any], prof: str, reserves: Any, account: Any = None) -> dict[str, Any]:
        """`set_settings`'s usage-gate half, laid onto `doc` in place (the caller writes the file): the
        reserves of `account`, or of the account `prof` runs under (§6 *A reserve is the account's*,
        TD-1581). Its billing, prices and labels are its profiles' (`_account_on`), one billing (§4.2a);
        an account whose profiles disagree, or whose name holds a `:` (*Names*), is refused."""
        if not isinstance(reserves, dict) or not reserves:
            raise RpcError("set_settings needs reserves: {label: percent | {per_day: N} | null}")
        if account is not None:
            if prof:
                raise RpcError("set_settings takes a profile or an account for its reserves, not both")
            key = str(account).strip()
            if not settings_mod.account_key(key) or not all(key.split(":", 1)):
                raise RpcError(
                    f"account {key!r} is not a usage key: <adapter>:<account>, as `ao gate` names it "
                    "(design §6 Usage gate)"
                )
            who = f"account {key}"
        else:
            key = self._account_key(prof)
            if key is None:
                raise RpcError(
                    f"profile {prof or '(default)'} is named by no adapter here and runs no session, so its "
                    "account is not known: a reserve is the account's (design §6 Usage gate)"
                )
            who = f"profile {prof or '(default)'}"
        if ":" in key.split(":", 1)[1]:
            raise RpcError(
                f"{who}: the account part of {key} holds a ':', so its key does not split into adapter and "
                "account: rename the account in profiles.yml (its `account`, else the profile's name; a '.' is "
                "allowed) (design §6 Usage gate, Names)"
            )
        on = self._account_on(key)
        if account is None and prof not in on and (prof or not on):  # "" is the default, listed by its name
            on[prof] = "metered" if self._billing_of(prof) is not None else "subscription"
        if len(set(on.values())) > 1:
            each = ", ".join(f"{p or '(default)'} {b}" for p, b in sorted(on.items()))
            raise RpcError(
                f"{key}'s profiles disagree on billing ({each}): an account has one billing, so its reserve is "
                "refused until profiles.yml agrees (design §4.2a, §6 Usage gate)"
            )
        if not on and key not in self._usage_acct:
            raise RpcError(
                f"account {key} is one this home has not seen: no profile here names it and no node has "
                "reported under it (design §6 Usage gate)"
            )
        names = sorted(on)
        if set(on.values()) == {"metered"}:
            # the account's prices are its profiles', pooled, on either path (§6 *One billing*)
            bills = [b for p in dict.fromkeys([prof, *names]) if (b := self._billing_of(p)) is not None]
            prices = next((b.get("prices") for b in bills if b.get("prices")), None) or {}
            rows_of = prof if account is None else (names or [""])[0]  # whose reading the rows read
            out = self._amounts_change(doc, rows_of, key, reserves, prices, who)
            return out | {"profile": prof, "profiles": names}
        reading = self._usage_acct.get(key) or next((self._usage[p] for p in [prof, *names] if p in self._usage), {})
        windows = reading.get("windows")
        reported = [str(w.get("label")) for w in windows or []]
        if windows is not None and (unknown := sorted(set(map(str, reserves)) - set(reported))):
            raise RpcError(
                f"{who} reports no window {', '.join(unknown)}: its windows are {', '.join(reported) or 'none'} "
                "(design §4.7)"
            )
        parsed: dict[str, Any] = {}
        for label, value in reserves.items():
            if isinstance(value, str):
                raise RpcError(
                    f"{label}: {who} is billed by subscription, so its reserve is a percent "
                    f"(30, 10/day), not an amount like {value!r} (design §6 Usage gate)"
                )
            try:
                parsed[str(label)] = None if value is None else settings_mod.parse_reserve(value)
            except ValueError as e:
                raise RpcError(f"{label}: {e}") from None
        self._lay_gate(doc, key, parsed)
        mine = (doc["usage_gate"] or {}).get(key) or {}
        log.info("usage gate for account %s (%s) set to %s", key, who, mine or "no reserves")
        return {
            "profile": prof,
            "account": key,
            "profiles": names,
            "reserves": mine,
            "windows": settings_mod.lines(mine, windows, datetime.now(UTC)),
            "unchecked": windows is None,
        }

    def _account_on(self, key: str) -> dict[str, str]:
        """The profiles on the account `key`, each to its billing (§6 *The profiles on an account*): those
        its adapter's `profiles()` lists on it, those a record here or on a node runs under that resolve to
        it, and those a node's usage or spend call named under it (a node's spend is metered)."""
        out: dict[str, str] = {}
        name, account = key.split(":", 1)
        if adapters.has_agent(name):
            try:
                listed = getattr(adapters.get(name), "profiles", None)
                for p in (listed() if listed else None) or ():
                    if isinstance(p, dict) and str(p.get("account") or p.get("name")) == account:
                        out[str(p.get("name"))] = str(p.get("billing") or "subscription")
            except Exception as e:  # noqa: BLE001 — an adapter's list never stops the write
                log.warning("profiles() on %s failed: %s", name, e)
        records = [*self.sessions.values(), *(r for recs in self.remote.values() for r in recs.values())]
        # "" is the default profile, which a listed name already counts
        for prof in sorted(
            {r.profile for r in records if adapters.has_agent(r.adapter)} - set(out) - ({""} if out else set())
        ):
            if self._account_key(prof) == key:
                out[prof] = "metered" if self._is_metered(prof) else "subscription"
        for accts in self._spend_named.values():
            for prof in accts.get(key) or ():
                out.setdefault(prof, "metered")
        for (_node, prof), k in self._usage_remote_keys.items():
            if k == key:
                out.setdefault(prof, "subscription")
        return out

    def _amounts_change(
        self,
        doc: dict[str, Any],
        prof: str,
        key: str,
        reserves: dict[str, Any],
        prices: dict[str, Any],
        who: str = "",
    ) -> dict[str, Any]:
        """A metered profile's half (§6 *Usage gate*, TD-151 slice 5): an amount per window of the
        home's three — `$5` where the profile has prices, `2M tok` either way — or None to clear it;
        a percent refused by naming the billing, as is money on a profile with no prices, which would
        make no line."""
        who = who or f"profile {prof or '(default)'}"
        if unknown := sorted(set(map(str, reserves)) - set(spend_mod.LABELS)):
            raise RpcError(
                f"{who} is metered: its windows are {', '.join(spend_mod.LABELS)}, "
                f"not {', '.join(unknown)} (design §4.2a)"
            )
        parsed: dict[str, Any] = {}
        for label, value in reserves.items():
            if value is None:
                parsed[str(label)] = None
                continue
            if not isinstance(value, str):
                raise RpcError(
                    f"{label}: {who} is metered, so its reserve is an amount ($5, 20M tok), "
                    f"not a percent like {value!r} (design §6 Usage gate)"
                )
            try:
                amount = settings_mod.parse_amount(value)
            except ValueError as e:
                raise RpcError(f"{label}: {e}") from None
            if amount["unit"] == "$" and not prices:
                raise RpcError(
                    f"{label}: {who} declares no prices, so its spend is tokens: an amount like 20M tok, "
                    f"not {value!r} (design §4.2a)"
                )
            parsed[str(label)] = value.strip()
        self._lay_gate(doc, key, parsed)
        mine = (doc["usage_gate"] or {}).get(key) or {}
        log.info("usage gate for metered account %s (%s) set to %s", key, who, mine or "no amounts")
        return {
            "profile": prof,
            "account": key,
            "reserves": mine,
            "windows": self._amount_rows(prof, mine),
            "metered": True,
        }

    def _amount_rows(self, prof: str, mine: dict[str, Any]) -> list[dict[str, Any]]:
        """A metered profile's rows for `gate` and `set_settings`' reply: each window with an amount,
        its amount as written, and the account's spend and `pct` from the last reading — `unread`
        before there is one. The `pct` is the reading's, made at the amount it last read."""
        windows = {str(w.get("label")): w for w in (self._usage.get(prof) or {}).get("windows") or ()}
        rows = []
        for label in spend_mod.LABELS:
            if label not in mine:
                continue
            w = windows.get(label)
            row: dict[str, Any] = {"label": label, "reserve": mine[label], "metered": True}
            if w is None:
                row["unread"] = True
            else:
                row |= {"spent": w.get("spent"), "pct": w.get("pct"), "resets": w.get("resets")}
            rows.append(row)
        return rows

    def _lay_gate(self, doc: dict[str, Any], key: str, parsed: dict[str, Any]) -> None:
        """`parsed` laid onto `doc`'s `usage_gate.<key>` in place, `key` the account's (TD-1581): None
        clears a window, an account with none left leaves the key."""
        gate = doc.get("usage_gate") if isinstance(doc.get("usage_gate"), dict) else {}
        mine = dict(gate.get(key) or {}) if isinstance(gate.get(key), dict) else {}
        for label, value in parsed.items():
            if value is None:
                mine.pop(label, None)
            else:
                mine[label] = value
        if mine:
            gate[key] = mine
        else:
            gate.pop(key, None)
        doc["usage_gate"] = gate

    async def _migrate_reserves(self) -> None:
        """The reserves moved from profiles to accounts (§6 *A reserve is the account's*, *The migration*,
        TD-1581), the host agent's second write of `settings.yml` outside `set_settings` beside td-max's
        `_migrate_scale`: once per tick, first in the home's part of it, every `usage_gate:` key holding no
        `:` moved by `settings.migrate_reserves`. A tick that finds none does nothing more. The file as it
        stands is committed first, and the move goes on only once it is clean against HEAD, its restore
        point (a failed commit moves nothing this tick: logged once, and after a day of such ticks the
        person told once); a home that is no tree copies it to `settings.yml.before-TD-1581` instead,
        never overwritten. Then one load, edit and save with no wait between, pushed to the nodes and
        committed as a `set_settings` write is, and one `system` note says what moved."""
        if self.mode != "home":
            return
        path = settings_mod.settings_file()
        doc = settings_mod.read() if path.exists() else None
        gate = doc.get("usage_gate") if isinstance(doc, dict) else None
        if not isinstance(gate, dict) or all(settings_mod.account_key(k) for k in gate):
            self._reserves_unclean = None
            return
        names = ["" if k is None else str(k) for k in gate if not settings_mod.account_key(k)]
        accounts, billing = await asyncio.to_thread(self._reserve_accounts, names)
        restore = ""
        if defs.is_tree(path.parent):
            await self._commit_defs("settings.yml before TD-1581's migration", ("settings.yml",))
            if not await asyncio.to_thread(defs.clean, path):
                self._reserves_not_clean()
                return
            head = await asyncio.to_thread(defs.head, path.parent)
            restore = f"restore from the home's commit {head[:12]}" if head else ""
        else:
            copy_path = path.with_name("settings.yml.before-TD-1581")
            if not copy_path.exists():
                await asyncio.to_thread(shutil.copyfile, path, copy_path)
                restore = f"restore from {copy_path}"
            else:
                restore = "restore from this note's values"
        self._reserves_unclean = None
        # one load, edit and save with no await between: a `set_settings` is either read by it or
        # lands after it (§6 *The migration*)
        doc = settings_mod.read()
        if doc is None:
            return
        before = copy.deepcopy(doc)
        said = settings_mod.migrate_reserves(doc, accounts, billing)
        if said is None:
            return
        settings_mod.save(doc)
        log.info("usage reserves moved to their accounts: %s", "; ".join(said))
        await self._push_settings()
        await self._commit_defs(defs.settings_message(before, doc), ("settings.yml",))
        text = "Usage reserves are now per account: " + "; ".join(said) + "."
        self._system_note(PERSON, text + (f" To go back, {restore}." if restore else ""))

    def _reserve_accounts(self, names: list[str]) -> tuple[dict[str, str | None], dict[str, set[str]]]:
        """The migration's resolution, in a thread: each profile key to its account key — only the adapter
        the profile names answers (`_account_of`); None where none does — and each such account to the
        billings of the profiles its adapter's `profiles()` lists on it."""
        accounts: dict[str, str | None] = {}
        billing: dict[str, set[str]] = {}
        agents = [n for n in adapters.names() if adapters.has_agent(n)]
        for prof in names:
            accounts[prof] = next(
                (f"{n}:{a}" for n in agents if (a := agent_spend._account_of(n, prof)) is not None), None
            )
        for key in {k for k in accounts.values() if k}:
            name, account = key.split(":", 1)
            try:
                listed = getattr(adapters.get(name), "profiles", None)
                profs = (listed() if listed else None) or []
            except Exception:  # noqa: BLE001 — an adapter's list never stops the tick
                profs = []
            billing[key] = {
                str(p.get("billing") or "subscription")
                for p in profs
                if isinstance(p, dict) and str(p.get("account") or p.get("name")) == account
            }
        return accounts, billing

    def _reserves_not_clean(self) -> None:
        """A pre-commit that left `settings.yml` dirty against HEAD: logged once, the person told once after
        a day of such ticks (the day in memory, from the first, reset by a clean tick or a restart)."""
        now = time.monotonic()
        since, logged, told = self._reserves_unclean or (now, False, False)
        if not logged:
            log.warning(
                "settings.yml is not clean against HEAD after the pre-commit (defs.commit's warning says why): "
                "the reserve migration waits for the next tick"
            )
        if not told and now - since >= 86400:
            self._system_note(
                PERSON,
                "Usage reserves are still per profile: for a day the home could not commit settings.yml as it "
                "stood before moving them to their accounts (the host agent's log says why), so the gate reads "
                "no reserve for those profiles until it can.",
            )
            told = True
        self._reserves_unclean = (since, True, told)

    @staticmethod
    def _person_change(current: Any, change: Any) -> dict[str, Any]:
        """`person:` with `change` laid over it: a key set to None cleared; `terminal`, `inbox`, `attach` and
        `file_link` merged field by field, a field set to None cleared. Validated whole before it is returned."""
        known = settings_mod.PERSON_KEYS
        nested = {
            "terminal": settings_mod.TERMINAL_KEYS,
            "inbox": settings_mod.INBOX_KEYS,
            "attach": settings_mod.ATTACH_KEYS,
            "file_link": settings_mod.FILE_LINK_KEYS,
        }
        if not isinstance(change, dict) or not change:
            raise RpcError(f"set_settings: person is a mapping of {', '.join(known)} (design §5)")
        if unknown := sorted(set(map(str, change)) - set(known)):
            raise RpcError(f"person: unknown key {', '.join(unknown)} (known: {', '.join(known)})")
        for key, keys in nested.items():
            sub = change.get(key)
            if isinstance(sub, dict) and (bad := sorted(set(map(str, sub)) - set(keys))):
                raise RpcError(f"person.{key}: unknown key {', '.join(bad)} (known: {', '.join(keys)})")
        out = dict(current) if isinstance(current, dict) else {}
        for key, value in change.items():
            if value is None:
                out.pop(key, None)
            elif key in nested and isinstance(value, dict):
                sub = dict(out.get(key) or {}) if isinstance(out.get(key), dict) else {}
                for f, v in value.items():
                    if v is None:
                        sub.pop(f, None)
                    else:
                        sub[f] = v
                out[key] = sub
                if not sub:
                    out.pop(key)
            else:
                out[key] = value
        try:
            return settings_mod.parse_person(out)  # as parsed: `07d` is written `7d`
        except ValueError as e:
            raise RpcError(f"person: {e}") from None
