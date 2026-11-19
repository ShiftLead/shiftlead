"""The `ao login` and `ao account` verbs (design §4.2b *Controls and verbs*, TD-1974): each a person's own act
(`mail.PERSON_ONLY`, §4.8), acting on the host it is run on and refused before the switch-over (no `logins.yml`).
Each edit is one `logins.update` — the file as it stands, under the one lock, committed as `logins: <change>` — made by
`sessionorc.logins`' pure edits; a write sends back the entry's version it read, and one over a newer version is
refused. The kept Tools read is dropped after a write, so the next `tools` reads afresh. A mixin `HostAgent`
inherits.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sessionorc import adapters, agent_common, logins
from sessionorc import settings as settings_mod
from sessionorc.agent_common import RpcError, log

SECTION = "§4.2b *Controls and verbs*"
ENDED = ("exited", "closed")


class LoginsMixin:
    async def _login_write(self, edit: Callable[[dict[str, Any]], str]) -> dict[str, Any]:
        """One write of the host's logins: `edit` makes it on the file as it stands, its words the change."""
        try:
            words = await asyncio.to_thread(logins.update, edit)
        except logins.LoginError as e:
            raise RpcError(str(e)) from None
        except OSError as e:
            log.warning("a logins write failed: %s", e)
            raise RpcError(f"this host's logins could not be written: {type(e).__name__}") from None
        self._tools_kept = None  # the page reads afresh: what it drew is stale
        return {"change": words}

    async def _login_keys(self) -> list[str]:
        """This host's logins' keys as the file stands, none before the switch-over or where it cannot be read (the
        write that follows says why)."""
        try:
            data = await asyncio.to_thread(logins.load)
        except logins.LoginError:
            return []
        return sorted((data or {}).get("logins") or {})

    def _login_kept(self, lk: str) -> dict[str, Any] | None:
        """The login's account as the kept read drew it, or None."""
        tool, name = logins.split(lk)
        for card in (self._tools_kept or {}).get("tools") or []:
            if card.get("adapter") != tool:
                continue
            for lg in card.get("logins") or []:
                if lg.get("name") == name:
                    return next((a for a in card.get("accounts") or [] if a.get("key") == lg.get("account")), None)
        return None

    def _login_users(self, lk: str) -> list[str]:
        """What runs on a login (§4.2b *⋯ on a login*): each live session of this host whose record names it — its
        `login`, or, before the cut-over writes one, its `profile` by the login's name."""
        tool, name = logins.split(lk)
        out = []
        for s in self.sessions.values():
            if s.state in ENDED or s.adapter != tool:
                continue
            if (getattr(s, "login", None) or s.profile) == name:
                out.append(s.id)
        return out

    async def rpc_login_label(
        self, login: str = "", label: str | None = None, version: str | None = None, caller: Any = None
    ) -> dict[str, Any]:
        """`ao login label <login> [<label>]`, ✎ on a login: a label only, the name fixed; none clears it."""
        agent_common.person_only(caller, "label a login", SECTION, self._graph())
        return await self._login_write(lambda d: logins.label_login(d, str(login or ""), label, version))

    async def rpc_account_label(
        self, key: str = "", label: str | None = None, version: str | None = None, caller: Any = None
    ) -> dict[str, Any]:
        """`ao account label <key> [<label>]`, ✎ on an account: a label only, the key fixed; none clears it."""
        agent_common.person_only(caller, "label an account", SECTION, self._graph())
        return await self._login_write(lambda d: logins.label_account(d, str(key or ""), label, version))

    async def rpc_login_note(
        self, login: str = "", text: str | None = None, version: str | None = None, caller: Any = None
    ) -> dict[str, Any]:
        """`ao login note <login> <text>`, **Edit note**: one line under the login; empty clears it. It must hold no
        secret: the file is committed."""
        agent_common.person_only(caller, "edit a login's note", SECTION, self._graph())
        return await self._login_write(lambda d: logins.note_login(d, str(login or ""), text, version))

    async def rpc_login_set(
        self, login: str = "", key: str = "", value: Any = None, version: str | None = None, caller: Any = None
    ) -> dict[str, Any]:
        """`ao login set <login> <key> <value>`, a login's **Settings** (§4.2b *A login's Settings*): the key one of
        `billing`, `prices`, `extra_args`, `unattended_args`, `permission_wait`, `pin`, checked by §4.2a's rules; an
        empty value clears it."""
        agent_common.person_only(caller, "change a login's settings", SECTION, self._graph())
        kept = {lk: self._login_kept(lk) for lk in await self._login_keys()}  # read in the loop

        def edit(d: dict[str, Any]) -> str:
            lk, e = logins.resolve(d, str(login or ""))
            tool = logins.split(lk)[0]
            try:
                ad = adapters.get(tool)
            except KeyError:
                raise logins.LoginError(f"{lk}'s tool {tool} has no adapter here") from None
            folder = Path(str(e.get("folder") or "")).expanduser()
            try:
                default = adapters.same_home(folder, ad.default_home(os.environ))
            except Exception:  # noqa: BLE001 — an adapter with no default home: the folder is its own
                default = False
            acct = kept.get(lk)
            families = ((acct or {}).get("models") or {}).get("families") if acct else None
            rules = {"default_home": default, "spends": callable(getattr(ad, "spend", None)), "families": families}
            return logins.set_setting(d, lk, str(key or ""), value, version, **rules)

        return await self._login_write(edit)

    async def rpc_login_account(
        self, login: str = "", account: str = "", version: str | None = None, caller: Any = None
    ) -> dict[str, Any]:
        """`ao login account <login> <key or new name>`, **name its account** and settling a mismatch (§4.2b
        *Matching across a restart*): an account's key, or a name, a name no account has making a new key; refused
        where the result would leave the matches disagreeing."""
        agent_common.person_only(caller, "name a login's account", SECTION, self._graph())
        try:
            reserve_keys = set(settings_mod.reserves(settings_mod.load()))
        except Exception:  # noqa: BLE001 — an unreadable settings file retires nothing it holds
            reserve_keys = set()
        matches = dict(self._tools_memory.last)
        return await self._login_write(
            lambda d: logins.join(
                d, str(login or ""), str(account or ""), version, reserve_keys=reserve_keys, matches=matches
            )
        )

    async def rpc_login_forget(self, login: str = "", version: str | None = None, caller: Any = None) -> dict[str, Any]:
        """`ao login forget <login>`, **Forget this login**: moved to `forgotten:`, its folder left on disk; refused,
        naming them, while a live session runs on it."""
        agent_common.person_only(caller, "forget a login", SECTION, self._graph())

        users = {lk: self._login_users(lk) for lk in await self._login_keys()}  # read in the loop

        def edit(d: dict[str, Any]) -> str:
            lk, _ = logins.resolve(d, str(login or ""))
            return logins.forget(d, lk, version, in_use=users.get(lk, []))

        return await self._login_write(edit)

    async def rpc_login_shell(self, login: str = "", caller: Any = None) -> dict[str, Any]:
        """`ao login shell <login>`, **Sign in**, **Sign in again** and **Open a shell here** (§4.2b *The tools
        shell*): the login's tools shell, its sign-in command typed with no Enter; a second press reopens it."""
        agent_common.person_only(caller, "open a login's tools shell", SECTION, self._graph())
        try:
            data = await asyncio.to_thread(logins.load)
            if data is None:
                raise logins.LoginError("this host has no logins until the switch-over (design §4.2b)")
            lk, e = logins.resolve(data, str(login or ""))
        except logins.LoginError as err:
            raise RpcError(str(err)) from None
        tool, name = logins.split(lk)
        return await self._login_shell(tool, name, Path(str(e.get("folder") or "")).expanduser())
