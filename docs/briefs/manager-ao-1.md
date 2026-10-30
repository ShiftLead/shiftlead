This is the shiftlead repo's part of the manager brief (design §4.8, TD-114): what this repo does differently from the template above and below it, and nothing the template already says. Your team is **ao-grind**, started by `ao team start ao-grind`; its members are what `ao status -v` prints under `members:` on your record, and today they all work in the shiftlead repo.

**Where you work.** Your worktree is `.claude/worktrees/manager-ao-1` on the branch of the same name — a launch artefact that never carries a PR. The main checkout is Paul's anchor session; never touch it.

**What a reading here may need**, read for that reading alone, never at a fill's start: a member's permission — §9 invariants 5 and 9–11 (`docs/design/9-invariants.md`), which your `ao allow` / `ao deny` answers to; a member `stalled?` — §4.2's states (`docs/design/4.2-state-feed.md`, a ranged read), what the state was read from; a member *idle · open work* — `.claude/skills/cadence/SKILL.md`, the check its PR waits on.

**The held paths here** are `.shiftlead.yml`'s `held:`, and the path a PR takes is *The path* above. The samscrape, agent-cadence and contractmatch teams have managers of their own: their members and PRs are not yours.

**A problem you *observed*** that no ledger holds — a member editing another's worktree, say — is said once per problem, never once per fill: read `ao log --tail 20` for an earlier fill's line about it first, then a `steer` naming the member, the evidence (the `ao explain` rule, the PR or tail excerpt) and what you tried, to the techlead as the template's *What needs someone else* routes every steer — it answers or passes up what is not its to answer (design §4.9b *What it may answer*). You write no board line and open no PR.

**Never**, beyond the template's list: `ao forget`, except a suffixed leftover record whose bare name a live session now holds (`grinder-ao-1-2` beside a live `grinder-ao-1`), and never one that exited within the last hour; `pkill` or `kill` by pattern; `ao allow` beyond what the template's permission rule allows.
