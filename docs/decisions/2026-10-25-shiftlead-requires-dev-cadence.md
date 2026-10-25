# ADR 2026-10-25: ShiftLead requires dev-cadence, and the person's own texts live in their dev-cadence layer

**Status:** proposed — for Paul's decision (drafted with him, 2026-10-25, session `ao-shiftlead-prompts`)
**Date:** 2026-10-25
**Supersedes, if decided:** in [ADR 2026-10-12](2026-10-12-ledgerboard-dev-cadence-shiftlead.md), the line
that ShiftLead never owns *a requirement that dev-cadence be installed*, and with it design §8's *recommends
dev-cadence and requires only a ledger*; the rest of that ADR (the three layers, ledgerboard) stands.
**Related:** TD-1009 (this decision), TD-993 (Told at start moves to the Session card and the Transcript,
where it prompted this), TD-657 / TD-662 (the director's preference layers, designed, not built), TD-681
(the mechanical sync PR), TD-588 (the briefs' layout slots); dev-cadence TD-126 (the personal layer), TD-128
(the owner's preferences out of the shared cadence), TD-129 and its
[ADR 2026-10-25](https://github.com/ShiftLead/dev-cadence/blob/main/docs/plans/2026-10-25-pinned-not-synced.md)
(dev-cadence pinned, not synced); [ADR 2026-10-08](2026-10-08-agentorc-dev-cadence-split.md); design §4.8,
§4.9, §4.9b, §5, §8

## Context

**What ADR 2026-10-12 decided.** Paul, 2026-10-12: dev-cadence should work in any repo and any session with
no ShiftLead on the machine, and *ShiftLead should recommend dev-cadence but not require it*. So ShiftLead
carries a path for a repo without dev-cadence:
- the built-in briefs' layout slots each have a sentence for an absent seam (§5 *The layout slots*:
  `{gate}` *no gate: a person merges*, `{board}`, `{ledger_check}`, `{cadence_rules}` *no cadence rules: the
  repo's README says how a change lands*);
- `ao repo init` writes a bare ledger for a repo with no seeds (§4.7);
- each reader of a dev-cadence file degrades silently when it is absent: the roster, the gate
  (`sessionorc/cadence.py`), convention notices, worktree setup, the SessionStart line (the ADR's own list).

No repo exercises that path: every repo on kmaster's roster (samscrape, contractmatch, pneuma-ops,
shiftlead, guardians-devenv, ledgerboard) is synced, and dev-cadence is its own source. Paul, 2026-10-25:
*we talked previously about letting someone use a different cadence mechanism (other than dev-cadence) but
I wonder if that is needless complication, especially given that we are building personal prefs into
dev-cadence now.*

**What a person can change today.** Prompted by TD-993 (the start context made visible: *as soon as users
can see it they will want the ability to modify it*):
- the role briefs take a repo's or a team's supplement (`roles.<name>.brief`, a definition's `brief:`),
  filled into the template's *This repo's rules* slot (§4.8); nothing of the person's own, across repos;
- `entry.md` (an Add entry session's start context) and `work.md` are read from the package alone
  (`repoconfig.entry_text`) and cannot be changed at all;
- the director's preferences are designed (TD-657) as `~/.shiftlead/preferences.md`, under the home's own
  git work tree (TD-210), which never pushes — so they do not follow the person to another machine.

**What dev-cadence now has.** TD-126's personal layer: the person's own rules in their own git repo,
private by default, cloned on each machine and named by a machine-wide `cadence.toml` key; read at session
start; rules keyed to the cadence § they change; `--effective` shows each rule's layer, line and commit; a
publish check before a layer goes public; others' layers adopted at a pinned ref and never pulled.
Slices 1–6 are built, and Paul's layer is live (dev-cadence #313): the private repo `eyecantell/cadence-layer`, cloned at `~/cadence-layer`, its rules in `cadence-personal.md`, named by `[[layers]] path` in `~/.config/dev-cadence/cadence.toml`. And its companion ADR proposes that a
repo pins dev-cadence and runs it from a cache instead of carrying 41 synced files — which removes most of
what requiring it would cost a repo.

## Options

1. **Keep dev-cadence optional (do nothing).** Keeps a path no repo uses, every slot's absent-seam
   sentence, `ao repo init`, and the silent fallbacks, each a branch to keep right. The person's texts get a
   second, ShiftLead-only home.
2. **Make the cadence pluggable** — an interface any process could implement, dev-cadence the first. One
   implementation and no second in view; the interface would be shaped by the one. Rejected.
3. **Merge dev-cadence into ShiftLead.** Ends the standalone cadence, which ADR 2026-10-12 kept for
   sessions and people with no orchestrator. Rejected.
4. **ShiftLead requires dev-cadence; dev-cadence stays usable alone.** The dependency runs one way. The
   person's ShiftLead texts live in the same layer repo as their cadence rules. **Recommended.**

## Decision

Proposed: **4**. The question for Paul: ShiftLead requires dev-cadence in every repo it serves, and the
person's briefs, start prompts and preferences live in their dev-cadence layer repo?

What 4 means:

1. **A repo ShiftLead serves is a dev-cadence repo.** `ao repo add` adopts dev-cadence when the repo has
   none — through dev-cadence's own adopt command (`dev-cadence adopt` under the companion ADR, `sync.sh`
   until then), never ShiftLead's code — and says what it wrote. A repo that refuses adoption is refused,
   naming the command. ShiftLead's wheel declares the dev-cadence version range it reads.
2. **What goes.** The layout slots' absent-seam sentences for the cadence's own seams (`{gate}`, `{board}`,
   `{ledger_check}`, `{cadence_rules}`); `ao repo init`; each silent fallback becomes one refusal naming the
   missing sync. Slots for the repo's own commands (`{test}`, `{lint}`, `worktree_setup:`) are the repo's,
   not the cadence's, and keep their sentences.
3. **One personal home: the person's dev-cadence layer repo.** It gains a `shiftlead/` directory beside the
   cadence rules: `preferences.md` (the director's, TD-657 — moved there from `~/.shiftlead/` before TD-662
   builds it), `briefs/<role>.md` (the person's additions to a role's brief), `entry.md` and `work.md` (their
   additions to the start context and the first prompt). ShiftLead finds the layers through dev-cadence's
   reader (`cadence_layer.py`), never its own setting: `shiftlead/` sits at the root of the git repo that
   holds a layer's file (for Paul, `~/cadence-layer/shiftlead/`), read from the working tree for one's own
   layer and at the pinned `ref` for someone else's. ShiftLead reads the `shiftlead/` files itself; dev-cadence
   documents only that a tool may keep a directory of its own in a layer repo, and never reads it.
   `~/.shiftlead/` keeps what belongs to this install (`org.yml`, `profiles.yml`, `settings.yml`).
4. **Additions, never replacements, in one order.** The package's text, then the person's layer, then the
   repo's (`.shiftlead.yml`, a definition's `brief:`), the more specific winning where they disagree — the
   order the cadence (cadence.md → layer → the repo's CLAUDE.md) and the designed preferences already use.
   A person's brief text is filled into a slot of its own beside *This repo's rules*, under the same
   sentence; no layer replaces a whole brief or heading (§4.8: a copied brief goes stale and wins over the
   template's current mechanics), and none takes from a *never* list or moves a host-agent gate.
5. **Where it shows.** A session reads its texts at start, so an edit applies to the next start (a team
   member by §6 rule 7's restart, as a brief change does now). The Session card's *told at start* row
   (TD-993) names each part's source — the package, a layer and its commit, the repo — from the same reading
   `--effective` gives.

## Consequences

- ShiftLead's release waits on dev-cadence being publishable: TD-090's scrub, and TD-128 moving the
  owner's preferences out of the shared cadence.
- Without the companion ADR this still holds, at the cost of the synced files in every served repo; with
  it, adoption is a pin, the seeds, and one wiring line, and TD-681's sync check shrinks to a one-line bump.
- dev-cadence never calls `ao`, never reads `shiftlead/`, and stays usable with no ShiftLead on the
  machine (ADR 2026-10-08's rule and ADR 2026-10-12's goal, both kept).
- Builds follow the decision, each its own entry: the adopt-or-refuse in `ao repo add` and the refusals in
  place of the fallbacks; the slots and `ao repo init` removed; the `shiftlead/` reader and the brief, entry
  and work additions; TD-657's preferences moved before TD-662; the Session card row's sources (with
  TD-993). Design §4.8, §4.9, §4.9b, §5 and §8 change first, as every behaviour change does.
- Out of bounds once decided: a repo served without dev-cadence, and a second home for the person's
  ShiftLead texts.

## Revisit triggers

- A person or team asks to run ShiftLead under another process, and dev-cadence's adoption is what stops
  them.
- dev-cadence needs to call ShiftLead to do its job (the dependency would no longer run one way).
- The layer repo needs something only ShiftLead can provide (a server, a database), so the person's texts
  outgrow a git repo.
