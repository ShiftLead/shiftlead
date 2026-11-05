# User Attention Board

Items that need the user to act or decide, plus in-flight work parked by a session. Sessions add entries **the moment they arise** and remove them when handled. Keep this file small — durable debt belongs in [technical_debt.md](technical_debt.md); this board is only "a human must act or decide."

All conventions — entry format and the `<host>` semantics, `Due:` dates and snoozing, the `Swept:`/`Swept-deep:` sweep stamps — live in `docs/cadence.md` §3 — the pinned agent-cadence's (`agent-cadence path cadence.md`; this repo pins it in `docs/cadence.toml`). That file is agent-cadence's (improvements reach this repo with a bump of the pin); this skeleton is SEED (yours, never overwritten), which is why the explanations do not live here (dev-cadence TD-17).

Format: `- [ ] YYYY-MM-DD (session <first-8-of-session-uuid> on <host>, or n/a) — what's needed. Context: TD-NNN / PR #N / branch. Due: YYYY-MM-DD.`

People: paul

## Needs the user

- [x] decide 2026-11-04 (person) — The home keeps a log of the events it witnesses and answers "at least N of this kind, matching this text, since this date", so an entry waiting on such an event can be checked mechanically. Context: TD-1295. Due: 2026-11-04. Decided: go (by paul) (2026-11-04). Closed: 2026-11-04 — see TD-1295: unblocked, its design round runs (the designer's).
- [ ] act 2026-10-26 (session `designer-ao-1` on kmaster) — **File one entry in dev-cadence's ledger, so a pinned repo's sessions hear of the convention changes a bump brings: `cadence_changes.py` reads the pinned commit's `cadence-changes.md`** — today, in a pinned repo, its `--hook` and `--json` read the repo's retired copy and say nothing, so neither a starting session nor ShiftLead's relay (rule 12) tells anyone. dev-cadence has no question seat, so no session here can file it; the full text is in TD-1025, under *dev-cadence's entry*. Once filed, put its id in TD-1025's and TD-1046's *Related* lines. Until it is built and a repo bumps to it, a pinned repo's members are told no convention change. Context: TD-1025, TD-1046. Due: 2026-10-29.
- [ ] act 2026-10-26 (session `grinder-ao-2` on kmaster) — **Have a samscrape session drop `.shiftlead.yml`'s stopgap `worktree_setup:` line (added by samscrape#1121):** ShiftLead's default worktree setup now runs the pinned dev-cadence tree's `hydrate_worktree.sh` in a pinned repo (#2409, live since 7209efb), so the key can be unset and its comment removed; shiftlead's own line went in #2424. samscrape has no question seat, so no session here can file it in samscrape's ledger. Check after: a new samscrape team worktree has `.claude/settings.local.json`. Context: TD-1044 / PR #2424. Due: 2026-11-02.
- [ ] act 2026-11-03 (session `grinder-ao-2` on kmaster) — **Once #2820 is promoted, turn on push from your iPhone and confirm one delivery through Apple's push service:** open the `https` address in Safari, Share → Add to Home Screen, open shiftlead from the home screen, Settings → **Push** → **tell me on this device**, allow notifications, then **Send a test to this device** — a notification should arrive, and a tap on it should open the Inbox in the app. The PR's tests stub the browser; only your phone can show Apple's push service takes the home's key. If it fails, the card's line under the device says why (*last failed …*); mark this with what it said. Context: TD-1305 / PR #2820. Due: 2026-11-04.
- [ ] 2026-10-17 (session `designer-ao-1` on kmaster) — TD-636 director seat: your default stands as merged in #1661 — your per-role rules first, then the org's director seat (off until you add it to org.yml), then you; TD-641 and TD-642 build it. Context: none. Due: 2026-10-24.

## In-flight (parked by a session)

- (none)
