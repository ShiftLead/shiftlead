# ADR 2026-10-13: How shiftlead could make money — for discussion

Status: **for discussion**. Nothing here is decided or designed. It writes down the options Paul and
a session talked through on 2026-10-13, alongside the reachability decision
([§4.5b](../design/4.5b-reachability.md), TD-646), so they are not lost with that conversation. An
option Paul picks becomes a design round and a TD entry. One he declines is marked so here.

## What any answer has to fit

Four things already settled constrain every option:

- **The licence is MIT** (`pyproject.toml`). Anyone may run their own copy of anything shiftlead
  hosts. What is sold is therefore convenience, operations, team features, or a piece that only works
  as a service, never the code itself.
- **shiftlead runs nothing that can read the person's session** (a summary of §4.5b, decided
  2026-10-13). The route is the person's own, Tailscale first. A relay, if one is built, *carries
  only ciphertext*, and one that ends TLS, serves the UI's code or holds the login *is ruled out*,
  because *a technical user would not hand that to a small company's servers*. A paid service
  that needs to see the terminal fails this test.
- **The person's subscription and tools stay theirs** (§4.5c). shiftlead does not resell model
  access (an inference from §4.5c: the login and its cost *stay with them*). Neutrality across tools
  is the moat, and the runtime is commodity (§4.5c, after
  [ADR 2026-09-13](2026-09-13-openai-agents-api.md)).
- **What leaves the machine is minimal**: the Telegram note carries no pending text, question
  words or `doing` line (§4.10 *Told on Telegram*). Any hosted piece inherits that rule.

## The options

They are ordered by the session's view of their promise. *Size* is a guess, as in the lessons ADR.

### 1. Push notifications as a small paid service

- **What:** the moment that matters most is *a session needs you*, reaching a locked phone. A
  **native** phone app's push needs a server holding that app's push credentials, which a
  self-hoster cannot run for an app they did not publish. The message carries only *something needs you* and opens the person's own route
  (`reach.url`), so the service learns that an event happened and nothing about it.
- **shiftlead now:** a one-way Telegram note through the person's own bot (§4.10, TD-092). It is
  free and self-hosted, but needs a bot and a chat app. TD-003 plans the phone layout and *Add to
  Home Screen*. A web app on the home screen can receive Web Push on recent iOS and Android. That
  push goes through the browser vendor's push service, but the keys that sign it (VAPID) can be the
  home's own, **so self-hosted Web Push needs no paid relay**. That weakens this option: what is
  left to sell is a native app, or push with nothing to set up.
- **Trust fit:** good. No content, no path to the shell.
- **Size:** medium (a native app, the push relay, billing). **Open:** is a native app's
  notification worth paying for when Telegram and self-hosted Web Push are free? Is self-hosted Web
  Push simply a feature (with TD-003), and not a product?

### 2. A team edition (open core)

- **What:** the one-person product stays free and MIT. A paid licence adds what companies need
  when several people share an org: sign-in through their identity provider, roles, an audit log of
  who typed into which session, shared boards, and policies set centrally.
- **shiftlead now:** one person per home is a design premise (§1; §4.7, *the home has no second person to let in*). Multi-user access control
  is a non-goal *for now* (§2).
- **Trust fit:** good. It runs on the customer's machines.
- **Size:** large: it reverses a premise. **Open:** is there demand from teams, or is shiftlead a
  personal tool? **The decision that is cheap now and dear later is the licence**: if team features
  are to be paid, their code starts in a separate package, or under a separate licence, before
  outside contributors arrive (and with a contributor agreement or sign-off, chosen then).

### 3. A managed host ("we host your workspace")

- **What:** a machine with shiftlead, tmux and Tailscale set up, kept updated and backed up. The
  person brings their own tool login. §4.5c already names it: *an add-on for someone with no
  machine, built when someone asks for it*.
- **Trust fit:** weaker. The machine is ours, so whoever runs it could read it. That is honest
  for a person who chooses it, but it is the very thing §4.5b keeps out of the default product.
- **Size:** medium to large (provisioning, operations, support). **Open:** margins over a bare
  cloud VM are thin, so the value is operations. Before offering it, check that the tool vendors'
  terms allow a subscription login on a machine a third party runs (Claude's consumer terms
  especially). This session did not check them.

### 4. Cost and throughput reporting

- **What:** token spend, entries finished, PRs merged and the share of each usage window left
  unused, per repo, team and model, over weeks. Useful to a team that manages agent budgets.
- **shiftlead now:** the usage gate reads each account's windows (§6 *Usage gate*, §4.2a), and the
  model trailer (TD-638) will say which model did what.
- **Trust fit:** good, if it runs on the home. **Size:** medium. **Open:** a paid view inside the
  team edition (option 2), or free and a reason to adopt?

### 5. A ciphertext relay as a paid convenience

- **What:** §4.5b's relay, for a person with no Tailscale or Cloudflare account: install, join, a
  passkey, a link.
- **Trust fit:** acceptable only in §4.5b's shape (TLS ends on the home, the home serves the UI and
  holds the login). Even then the relay sees timing and volume.
- **Size:** large: a service to run, on everyone's critical path. **Open:** bring-your-own route
  covers technical users, so this waits for non-technical ones (§4.5c's later step).

### 6. Sponsorship and support contracts

- **What:** GitHub Sponsors, paid support or setup help. **Size:** small. **Open:** small income;
  worth it only once there are users.

## Prices

None are written here. This session's knowledge of provider prices and quotas (Tailscale's
plans, Cloudflare Access's free tier, push providers) may be out of date, and none of them is
needed to choose a direction. Check them when an option is designed.

## Questions for Paul

1. Is shiftlead to be a business at all, or a tool Paul uses and shares? The answer changes how much
   of the rest matters.
2. If a business: personal users first (options 1, 3, 6), or teams (options 2, 4)?
3. The licence: does it stay MIT for everything, or is a team edition kept separate from now on?
4. Which one, if any, becomes a design round first? The session's view: self-hosted Web Push is a
   feature to build anyway (with TD-003), not a product. Option 2 is the real prize if teams want
   it, and the licence question (3) is what to settle first. Option 3 waits for someone to ask, as
   §4.5c already says.
