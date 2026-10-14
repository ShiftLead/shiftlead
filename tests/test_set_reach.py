"""`set_reach` (design §4.7 `ao connect`, §5 `reach:`, §4.5b *The setting*, TD-648): the one RPC that
writes `settings.yml`'s `reach:` key, its shape checked before anything is written; `set_settings`
refuses the key; a person's own, and the home's."""

from __future__ import annotations

import pytest

from sessionorc import mail, modes
from sessionorc import settings as settings_mod
from sessionorc.client import AgentError, LocalClient

TAILSCALE = {"route": "tailscale", "url": "https://home.tail1234.ts.net/", "allow": ["Paul@Example.com"]}


def test_set_reach_is_a_persons_and_the_homes():
    assert "set_reach" in mail.PERSON_ONLY and "set_reach" in modes.HOME_EDITS


async def test_set_reach_writes_the_key_and_answers_what_was_there(agent):
    async with LocalClient() as person:
        await person.call("set_settings", usage={"max_age": "2h"})
        got = await person.call("set_reach", reach=TAILSCALE)
        want = {"route": "tailscale", "url": "https://home.tail1234.ts.net", "allow": ["paul@example.com"]}
        assert got == {"reach": want, "before": None}
        doc = settings_mod.load()
        assert settings_mod.reach(doc) == want and doc["usage"] == {"max_age": "2h"}  # the rest kept
        got = await person.call("set_reach", reach={**TAILSCALE, "allow": ["other@example.com"]})
        assert got["before"] == want and got["reach"]["allow"] == ["other@example.com"]
        got = await person.call("set_reach", reach=None)  # `ao connect off`
        assert got["reach"] is None and "reach" not in settings_mod.load()
        assert settings_mod.load()["usage"] == {"max_age": "2h"}


@pytest.mark.parametrize(
    "bad, says",
    [
        ({**TAILSCALE, "route": "wireguard"}, "reach.route is tailscale or cloudflare"),
        ({**TAILSCALE, "url": "http://home:8766"}, "reach.url is an https:// address"),
        ({**TAILSCALE, "url": "https://home/inbox"}, "reach.url is an https:// address"),
        ({**TAILSCALE, "allow": []}, "names at least one login"),
        ({k: v for k, v in TAILSCALE.items() if k != "allow"}, "allow is required"),
        ({**TAILSCALE, "route": "cloudflare", "team": "t"}, "needs team and aud"),
        ({**TAILSCALE, "port": 443}, "unknown key"),
    ],
)
async def test_set_reach_refuses_a_bad_shape_and_writes_nothing(agent, bad, says):
    async with LocalClient() as person:
        await person.call("set_reach", reach=TAILSCALE)
        with pytest.raises(AgentError, match=says):
            await person.call("set_reach", reach=bad)
        assert settings_mod.load()["reach"]["route"] == "tailscale"


async def test_a_cloudflare_route_keeps_team_and_aud(agent):
    async with LocalClient() as person:
        got = await person.call(
            "set_reach",
            reach={
                "route": "cloudflare",
                "url": "https://ao.example.com",
                "allow": ["p@x.org"],
                "team": "t",
                "aud": "a",
            },
        )
        assert got["reach"]["team"] == "t" and got["reach"]["aud"] == "a"


async def test_set_settings_refuses_reach_naming_ao_connect(agent):
    async with LocalClient() as person:
        with pytest.raises(AgentError, match="`ao connect` does, through set_reach"):
            await person.call("set_settings", reach=TAILSCALE, usage={"max_age": "2h"})
        assert "reach" not in settings_mod.load() and "usage" not in settings_mod.load()


async def test_a_session_cannot_set_the_route(agent, tmp_path):
    async with LocalClient() as person:
        sid = (
            await person.call(
                "create",
                name="w",
                dir=str(tmp_path),
                adapter="shell",
                role="worker",
                argv=["bash", "--norc", "--noprofile"],
            )
        )["id"]
        try:
            async with LocalClient(caller=sid) as itself:
                with pytest.raises(AgentError, match="cannot change the route: a person's own act"):
                    await itself.call("set_reach", reach=TAILSCALE)
            assert "reach" not in settings_mod.load()
        finally:
            await person.call("kill", id=sid)
            await person.call("remove", id=sid)


def test_the_telegram_link_is_the_route_when_absent():
    """§4.5b *The setting*: `notify.telegram.link`, absent, is `reach.url` — the link a phone opens."""
    on = {"on": True, "secrets": "p/c"}
    route = {"reach": dict(TAILSCALE)}
    assert settings_mod.telegram({"notify": {"telegram": on}})["link"] == ""
    assert settings_mod.telegram({"notify": {"telegram": on}, **route})["link"] == "https://home.tail1234.ts.net"
    own = {"notify": {"telegram": {**on, "link": "http://kmaster:8765"}}, **route}
    assert settings_mod.telegram(own)["link"] == "http://kmaster:8765"
    assert settings_mod.telegram_link({"reach": {"route": "tailscale"}}) == ""  # a malformed route is none
