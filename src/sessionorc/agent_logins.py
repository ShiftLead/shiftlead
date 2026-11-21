"""The `ao login` and `ao account` verbs (design §4.2b *Controls and verbs*, TD-1974): each a person's own act
(`mail.PERSON_ONLY`, §4.8), acting on the host it is run on and refused before the switch-over (no `logins.yml`).
Each edit is one `logins.update` — the file as it stands, under the one lock, committed as `logins: <change>` — made by
`sessionorc.logins`' pure edits; a write sends back the entry's version it read, and one over a newer version is
refused. The kept Tools read is dropped after a write, so the next `tools` reads afresh. A mixin `HostAgent`
inherits.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sessionorc import adapters, agent_common, defs, logins
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
        self._tools_gen += 1  # a read in flight settled the file as it was: it is not kept (`_tools_keep`)
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
        for s in list(self.sessions.values()):  # a copy: forget reads it from the write's thread
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
        if key == "pin" and self._tools_kept is None:  # a write dropped the kept read: the families are read afresh
            await self.rpc_tools()
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
        if self._tools_kept is None and await self._login_pinned(str(login or "")):
            # a pin is checked against the joined account's families: read them afresh; with no read the join
            # stands, the pin cleared as unread
            with contextlib.suppress(RpcError):
                await self.rpc_tools()
        offered = self._kept_families()  # read in the loop
        emptied: dict[str, Any] = {}

        def edit(d: dict[str, Any]) -> str:
            lk, e = logins.resolve(d, str(login or ""))
            left = logins.account_of(lk, e)
            words = logins.join(
                d,
                lk,
                str(account or ""),
                version,
                reserve_keys=reserve_keys,
                matches=matches,
                families=offered.get,
            )
            if left not in logins.live_keys(d):  # its last login gone: its reserve goes with it (*A login changes
                acct = logins.account_of(lk, e)  # account*)
                under = {
                    str(oe.get("billing") or "subscription")
                    for o, oe in d["logins"].items()
                    if logins.account_of(o, oe) == acct
                }
                emptied.update(src=left, dst=acct, metered=None if len(under) > 1 else under == {"metered"})
            return words

        out = await self._login_write(edit)
        if emptied and self.mode == "home":  # the reserves are the home's `settings.yml` (§4.2b *Not here*)
            moved = self._move_reserve(**emptied)
            if moved:
                out["change"] += "; " + "; ".join(moved)
        return out

    def _move_reserve(self, src: str, dst: str, metered: bool | None) -> list[str] | None:
        """`settings.move_reserve` on the home's `settings.yml`: one read, edit and save with no wait between, as
        the migration's is, so a `set_settings` is either read by it or lands after it; then pushed to the nodes and
        committed as a `set_settings` write is. None where the file is absent or broken, or `src` holds none."""
        if not settings_mod.settings_file().exists():
            return None
        doc = settings_mod.read()
        if doc is None:
            return None
        before = copy.deepcopy(doc)
        said = settings_mod.move_reserve(doc, src, dst, metered)
        if said is None:
            return None
        settings_mod.save(doc)
        log.info("a login's join moved its account's reserve: %s", "; ".join(said))
        task = asyncio.create_task(self._after_reserve_move(before, doc))
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)
        return said

    async def _after_reserve_move(self, before: dict[str, Any], doc: dict[str, Any]) -> None:
        await self._push_settings()
        await self._commit_defs(defs.settings_message(before, doc), ("settings.yml",))

    async def _login_pinned(self, ref: str) -> bool:
        """Whether the login `ref` names has a model pin as the file stands (False where it cannot be read)."""
        try:
            data = await asyncio.to_thread(logins.load)
            return bool(data and logins.resolve(data, ref)[1].get("pin"))
        except logins.LoginError:
            return False

    def _kept_families(self) -> dict[str, list[str]]:
        """Each account's model families as the kept read drew them, by key; an account with none read is absent."""
        out: dict[str, list[str]] = {}
        for card in (self._tools_kept or {}).get("tools") or []:
            for a in card.get("accounts") or []:
                fam = (a.get("models") or {}).get("families")
                if a.get("key") and fam is not None:
                    out[str(a["key"])] = list(fam)
        return out

    async def rpc_login_forget(self, login: str = "", version: str | None = None, caller: Any = None) -> dict[str, Any]:
        """`ao login forget <login>`, **Forget this login**: moved to `forgotten:`, its folder left on disk; refused,
        naming them, while a live session runs on it."""
        agent_common.person_only(caller, "forget a login", SECTION, self._graph())

        def edit(d: dict[str, Any]) -> str:  # under the logins lock: what runs on it is read as the write is made
            lk, _ = logins.resolve(d, str(login or ""))
            return logins.forget(d, lk, version, in_use=self._login_users(lk))

        return await self._login_write(edit)

    async def rpc_login_add(
        self,
        tool: str = "",
        path: str | None = None,
        name: str | None = None,
        account: str | None = None,
        caller: Any = None,
    ) -> dict[str, Any]:
        """`ao login add <tool> [--path <folder>] [--name <name>] [--account <name>]`, **+ Add login**, **Use an
        existing folder** and **Add** on a found row (§4.2b *Controls and verbs*, *How a login is found and made*). A
        `path` that is the tool's home (`is_home`) is used; one that does not exist or is empty is made a home
        (`make_home`); any other is refused. With no `path` the folder is the adapter's `new_home(name)`, made. A
        forgotten login's folder takes back its name and account. A login whose folder was made has its tools shell
        opened for **Sign in**: its `shell` in the reply."""
        agent_common.person_only(caller, "add a login", SECTION, self._graph())
        tool = str(tool or "").strip()
        try:
            ad = adapters.get(tool)
        except KeyError:
            raise RpcError(f"no tool {tool!r} has an adapter here") from None
        if not adapters.has_agent(tool):
            raise RpcError(f"{tool} runs no agent: it has no logins")
        has = adapters.implements(ad)
        name = str(name).strip() if name else None
        if path:
            folder = Path(str(path)).expanduser()
            if not folder.is_absolute():
                raise RpcError(f"{path} is not a full path: give it from / or ~")
        elif not name:
            raise RpcError("name the new login (--name), or give the folder it is (--path)")
        elif "new_home" not in has:
            raise RpcError(f"the {tool} adapter suggests no folder for a new login: give one (--path)")
        else:
            folder = Path(ad.new_home(name)).expanduser()
        home = "is_home" in has and await asyncio.to_thread(ad.is_home, folder)
        if not home:
            try:
                empty = await asyncio.to_thread(
                    lambda: not folder.exists() or (folder.is_dir() and not any(folder.iterdir()))
                )
            except OSError as e:
                raise RpcError(
                    f"{folder} cannot be read ({e.strerror or type(e).__name__}): give another --path"
                ) from None
            if not empty:
                raise RpcError(f"{folder} is neither a {tool} home nor an empty folder: give another --path")
        suggested = None
        if home and not name and "identity" in has:
            try:
                ident = await asyncio.to_thread(ad.identity, folder, self._tools_salt)
            except Exception:  # noqa: BLE001 — no display read: the person types the name
                ident = None
            display = adapters.plain_name((ident or {}).get("display"))
            folded = logins.name_of(display) if display else ""
            suggested = logins.name_of(f"{tool}-{folded}") if folded else None
        try:
            reserve_keys = set(settings_mod.reserves(settings_mod.load()))
        except Exception:  # noqa: BLE001 — an unreadable settings file retires nothing it holds
            reserve_keys = set()
        tools = adapters.names()
        made: list[str] = []

        def edit(d: dict[str, Any]) -> str:
            lk, words = logins.add(
                d,
                tool,
                folder,
                name,
                account,
                tools=tools,
                reserve_keys=reserve_keys,
                same=adapters.same_home,
                suggested=suggested,
            )
            if not home:  # the last step before the entry stands: a refusal above makes no folder
                try:
                    if "make_home" in has:
                        ad.make_home(folder)
                    else:
                        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
                except OSError as e:
                    raise logins.LoginError(f"{folder} could not be made a home: {e.strerror or e}") from None
            made.append(lk)
            return words

        got = await self._login_write(edit)
        lk = made[0]
        got["login"] = lk
        if not home:
            try:
                got["shell"] = await self._login_shell(tool, logins.split(lk)[1], folder)
            except RpcError as e:  # the login stands; Sign in opens its shell again
                got["shell_error"] = str(e)
        return got

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
