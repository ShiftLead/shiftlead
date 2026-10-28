# ShiftLead

> **Not ready for use yet.** ShiftLead is under active development and is not yet meant for anyone
> outside the project to install or run: interfaces, names and on-disk state still change without
> notice, and there is no support. Please hold off on sharing it until a release is announced.

*The project is **ShiftLead** ([shiftlead.dev](https://shiftlead.dev)), decided 2026-09-21; the command is `ao`.
The packages, the state directory, the units and the config file carry the name since 2026-10-10 (TD-060;
`ao migrate` moves a machine from the old names once), and the repo is `ShiftLead/shiftlead` since 2026-10-11.
Was `sessionherd` for the first day of design, and `agentorc` from 2026-09-04 to 2026-10-10, to sit beside [cmdorc](https://github.com/eyecantell/textual-cmdorc).*

A self-hosted web dashboard that orchestrates interactive AI coding-agent sessions (Claude Code first;
Gemini CLI, Codex CLI, and on-prem harnesses via adapters) — and plain shells — running in tmux across one or more
hosts. One view of every session and whether it is **working**, **needs you**, **idle**, or
**exited**; read and drive any of them in an embedded terminal; start, resume, and close them;
see git status per checkout; press configured command buttons; jump to VS Code; and supervise
unattended workers with run windows and usage caps. Sessions live on the host, so closing the
laptop changes nothing.

**Status: phase 1 in progress.** The host agent, the Claude Code adapter, the Sessions page, Focus and
Inbox pages (mail and the sessions' states; due board items are still to come — TD-069), New session and the CLI are built and
running; phase 2 (a second host over ssh) is not.
Read [`docs/design.md`](docs/design.md) — §7 has the phase plan, and what is deferred is in
[`docs/ledger/`](docs/ledger/README.md).

Grew out of [samscrape](https://github.com/eyecantell/samscrape)'s `tdgrind` worker supervisor
and the [dev-cadence](https://github.com/eyecantell/dev-cadence) working-cadence system, whose
repo registry it depends on.

## Start here (handoff, updated 2026-09-06 evening; the next-steps list below is from that
date — the live lists are [`docs/user_attention.md`](docs/user_attention.md) and
[`docs/ledger/`](docs/ledger/README.md))

**Phase 1 is built** (PRs #1–#4; each was reviewed by a Sonnet subagent in the build session and
the findings folded into the PR before merge — see the "review fixes" commits): host agent, Claude Code adapter, Sessions
and Focus pages, New session, CLI. Run it per "Run it" below. What to do next, in order:

1. **Use it** against a real repo and note what the flows get wrong (board item, due 2026-09-13).
   From the laptop, reach the UI with `ssh -L 8765:127.0.0.1:8765 kmaster`; from the phone, set up
   the Tailscale route (*Reach it from your phone*, below).
2. **Decisions waiting on Paul**: see [`docs/user_attention.md`](docs/user_attention.md)
   (dev-cadence PRs #82/#83, GitHub merge settings, the two permission-dialog questions).
3. **Deferred work** is in [`docs/ledger/`](docs/ledger/README.md) (TD-001 `limited`
   state, TD-002 attachments, TD-003 phone, TD-004 `hosts.yml`, TD-010 adopting hand-started
   sessions), then **phase 2** of [`docs/design.md`](docs/design.md) §7: second host, ssh
   transport, agent install script.
4. Known gap in the phase 1 success test: only sessions ShiftLead launched (or hand-started
   `ao-*` tmux sessions) appear in the Sessions page. A Claude Code session opened in a VS Code terminal
   is not a tmux session and is invisible until Adopt (TD-010) exists.

Mockups: https://claude.ai/code/artifact/0e14af3a-5e5a-4d9c-88b2-74205c394c04 (sources and
regeneration notes in [`docs/mockups/`](docs/mockups/)). The CSS block at the top of
`docs/mockups/gen.py` is the seed for the app's stylesheet tokens; the dark artboard is a token
swap of the light one, which is how the real dark mode should work too.

## Layout

One repo, one distribution (`shiftlead`, with an `[ui]` extra for the host that serves the web
UI), two import packages: `sessionorc` (tmux, hosts, ssh, the pty terminal bridge, run logs, the
shell adapter) and `shiftlead` (hook adapters, profiles, policies, Ready to close, the board) on
top of it. `sessionorc` never imports `shiftlead`; it becomes its own repo only when a second
consumer appears (docs/design.md §10).

## Requirements

Python 3.12+, tmux 3.2+ (`new-session -e`, bracketed `paste-buffer -p`; kmaster has 3.5a), and
on each session host a user systemd session with `loginctl enable-linger` so the agent and its
tmux server survive logout and reboot.

## Run it (phase 1, one host)

```bash
pdm install -G ui                      # or: pipx install 'shiftlead[ui]' once published
pdm run shiftlead-agent serve           # the host agent: tmux, sessions, hooks, run logs
pdm run ao ui                          # the web UI on http://127.0.0.1:8765 (localhost by default; see below)
pdm run ao new td-302 -d ~/samscrape   # or the New session form; `ao shell` for a plain shell
pdm run ao service install             # instead of the two `serve`/`ui` terminals: systemd user units
                                       # (survive logout and reboot with linger; `ao service status`)
```

To work on ShiftLead *with* ShiftLead, keep the running copy separate from the checkout: install
a stable, non-editable copy and point the units at it, then promote a merge deliberately.

```bash
python3 -m virtualenv ~/.local/share/shiftlead-venv          # (pipx works the same way, if you have it)
~/.local/share/shiftlead-venv/bin/pip install '/path/to/shiftlead[ui]'
~/.local/share/shiftlead-venv/bin/ao service install          # units now run the stable copy; restarts them
# after a merge you want live:
~/.local/share/shiftlead-venv/bin/pip install --upgrade '/path/to/shiftlead[ui]' && ~/.local/share/shiftlead-venv/bin/ao service install
```

**A machine with a Gemini profile** (an `adapter: gemini` entry in `profiles.yml`) needs one more line,
run once by you with `sudo`. Gemini CLI reads its hooks only from a settings file that root owns, so
ShiftLead writes the file it wants to `~/.shiftlead/gemini-settings/layer.json` and you install it.
Until you do, a Gemini launch is refused (design §4.3 *The second adapter*). `ao doctor hooks` prints
the same line, and prints it again whenever the installed copy is stale:

```bash
sudo install -d -o root -g root -m 0755 /etc/shiftlead && sudo install -o root -g root -m 0644 ~/.shiftlead/gemini-settings/layer.json /etc/shiftlead/gemini-settings.json
```

### Reach it from your phone

Never a bare public port (design §4.5). The UI listens on two loopback ports: the **plain port**
8765, for a browser on this machine and an `ssh -L`, and the **route port** 8766, for a proxy that
proves who you are on every request. Tailscale is that proxy here. Nothing below hands shiftlead a
key, and `ao connect` never runs `sudo` (design §4.5b, §4.7).

1. A **Tailscale account** (sign in with Google, GitHub or Microsoft) with a **second factor** on
   that login: whoever holds it reaches your sessions.
2. The **client** on this machine (<https://tailscale.com/download>), then `tailscale up` and open
   the link it prints.
3. On Linux, let your user run `tailscale serve` without root: `sudo tailscale set --operator=$USER`.
4. In the admin console's DNS page (<https://login.tailscale.com/admin/dns>), turn on **MagicDNS**
   and **HTTPS Certificates**; `tailscale serve` needs them for its certificate.
5. Turn on **Tailnet Lock**, so a device nobody you trust signed cannot join the tailnet.
6. In the tailnet's **access rules**, grant your login this machine's ports **443** (the UI) and
   **22** (an ssh from the phone, for the case below).
7. `ao connect tailscale`. It checks each step above and names the first one missing. It writes
   `reach:` in `settings.yml`, serves 443 at the route port, and probes the result; a probe that
   fails is undone. On the first run the probe can wait a minute or two while Tailscale fetches the
   machine's first HTTPS certificate. `--allow <login>` names the login to let in (a tagged machine needs it).
   `ao connect` alone shows the route; `ao doctor route` checks it.
8. On the phone: the **Tailscale app**, signed in as the same login, then open the URL
   `ao connect` printed.
9. On each computer you code from: the **client**, signed in as the same login. Point the ssh alias
   your editor uses (VS Code Remote-SSH, and the UI's VS Code links through `vscode_host`) at this
   machine's tailnet name or address, not its LAN address:

   ```
   Host kmaster
     HostName 100.x.y.z        # `tailscale ip -4` on this machine, or kmaster.<tailnet>.ts.net
     User you
   ```

   The alias goes in the ssh config of the program that runs ssh: on Windows, VS Code reads
   `C:\Users\<you>\.ssh\config` by default, not WSL's `~/.ssh/config`; and when `HostName` is a
   name, a line for it in `C:\Windows\System32\drivers\etc\hosts` decides where it goes. The first connect asks you to accept the
   host key again, because ssh files it under the new address. Port 22 is already granted (step 6).

**If 443 already serves the plain port** (the interim of design §4.5b, before the route port
existed), the UI refuses what that proxy sends, and the phone shows a page saying so. Run
`tailscale serve --https=443 off`, then `ao connect tailscale`. From the phone, do it over an ssh
to this machine's tailnet name, so keep an ssh app on the phone while that serve is in use.

**A lost phone**: remove the device from the tailnet in the admin console's Machines page; it
reaches nothing from then on. `ao connect off` removes the route and turns off only the serve it
added.

`ssh -L 8765:127.0.0.1:8765 <this machine>` always works as the fallback. A script that POSTs to
the UI over HTTP sends an `Origin` naming the UI's own address, as a browser does; one without it is
refused (design §4.5b). A private network you run yourself (WireGuard) can reach the plain port bound
to its address with `ao ui --bind <addr>` (and `--allow-host <name>` for a name it is reached by).

**Do not start the agent or the UI from a VS Code Remote-SSH terminal.** VS Code auto-forwards
any port a process in its terminal starts listening on, so `127.0.0.1:8765` on your laptop ends
up served by VS Code's forwarder instead of your `ssh -L`, and the terminal websockets never
arrive (pages still load, which makes it hard to spot; found 2026-09-06). Start both from a plain
ssh session, or set `remote.autoForwardPorts` to false for that remote.

State lives under `~/.shiftlead/` (`SHIFTLEAD_HOME` overrides it — every session the agent creates
carries it, so hooks inside find the right agent). Profiles: `~/.shiftlead/profiles.yml`
(design §4.2a). Host identity: `~/.shiftlead/hosts.yml`, e.g. `local: {name: kmaster, vscode_host: kmaster}` —
`vscode_host` is the ssh alias VS Code links use and must be in your own `~/.ssh/config`; add
`local: true` when the UI runs on the machine you sit at (`vscode://file/…` links). Without the
file the machine's hostname is used, which is rarely what VS Code can resolve. The same entry
takes `volatile: true` (a laptop: an unreachable agent is asleep, not an alert), `repos_registry`
(one file in place of the default: `~/.shiftlead/repos.txt`, then dev-cadence's
`~/.config/dev-cadence/repos.txt` when it exists; their repos head the New session directory list) and
`runs_keep_days` (default 30; run logs of exited/closed sessions older than that are deleted on
the agent's tick, `0` keeps all) — the full shape is in `sessionorc/hosts.py`. A top-level `home: <host>` makes this
host agent a *node* of that home (design §4.4a); leave it out on a single machine.

**Linking a second machine to the home** (TD-057 step 3a — the link comes up and stays up; nothing is
forwarded over it yet, so a node still serves only its own host's sessions):

```bash
# on the node (say `laptop`): a key used for nothing else
ssh-keygen -t ed25519 -N '' -f ~/.ssh/shiftlead-link
# on the home (kmaster), one line in ~/.ssh/authorized_keys — the name after --host is the node's
# name as far as the home is concerned, and it is set HERE, never by the node:
command="shiftlead-agent link --host laptop",restrict ssh-ed25519 AAAA… laptop-link
# on the home, ~/.shiftlead/hosts.yml:      nodes: [laptop]
# on the node, ~/.shiftlead/hosts.yml:      home: kmaster
#                                          local: {name: laptop}
#                                          link: {ssh: kmaster-link}   # an alias in ~/.ssh/config using that key
```

`ao`'s `host` RPC (`shiftlead-agent rpc` → `{"method": "host"}`) shows the link's state at both ends,
with the reason when it is down: *ssh failed*, *agent down on the home*, or *refused: …*.

## CLI

The package installs `shiftlead` and an `ao` alias. Reading: `ao status [-v]`, `ao tail`,
`ao explain`. Acting on a session: `ao new`, `ao shell`, `ao send`, `ao keys`, `ao allow` /
`ao deny`, `ao mode`, `ao kill`, `ao close`, `ao forget`. Capabilities and reports (design §4.8):
`ao grant` / `ao revoke`, `ao progress claim|done|drop`, `ao finding`, `ao doing "<one line>"` (what
this session is doing now — its card shows it with its age; `--clear` empties it). Who is calling
(design §4.8a): `ao whoami` (what the host agent takes this process to be, from its connection),
`ao identity` (this host's mode — `local: {identity: off | observe | enforce}` in `hosts.yml`,
`observe` by default — its tally of connections, and its identity alarms, which the Inbox also lists with
**Acknowledge**; `ao status -v` prints the mode and whether the detached-process check is on). Serving: `ao ui`,
`ao service`. A container node (design §4.4a): `ao host up|rebuild|forget|status <name>`; `ao new
--host <name>` starts a session on it, every act on the `<id>@<name>` it prints is gated here
and run there, and `ao focus <id>@<name>` attaches through `docker exec`. `ao new
--attach` (or `ao shell --attach`) starts the session and attaches your terminal to it — type it
where you would have typed `claude`, and the session is a first-class card; `ao focus <id>`
attaches to an existing one. Every
subcommand takes `--json` (before or after the subcommand) and then prints only the RPC result —
the session dict, the tail lines, `{"ok": true, "id": …}` for calls that return nothing — or
`{"error": …}` with the same exit codes, so a script or an agent driving `ao` parses ids instead
of prose (design §4.7). `ao --skill` prints the rules an agent driving `ao` from inside a session must
follow; `ao --skill > .claude/skills/ao/SKILL.md` installs them in a repo (TD-019).

## Stand up a team

One command is the whole of it, and it is the same text for a person and for an agent:

```
ao team --skill
```

It prints the recipe — the node (if the team runs on one), the project and the team definition in
`~/.shiftlead/org.yml` or a repo's own `.shiftlead.yml`, the roles and their briefs, and
`ao team list / start / status / stop` — each step a command and what it does. It needs no host
agent and no checkout of this repo, so it works inside a container node too. That is the source;
this section is the pointer (TD-067). `ao --skill` is the other document and answers the other
question: how to behave *inside* a session, once one is running.

## License

MIT — see [LICENSE](LICENSE).
