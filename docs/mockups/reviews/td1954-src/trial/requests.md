# The trial's requests

Each run gets only `flow-reference.md`, the command `python3 flowcheck.py <file>` (run, never read), and one of these prompts. It saves every attempt, a trace of an entry through its final flow, and notes on what it had to guess.

## Request 1

```
You are testing whether a short reference document is clear enough to write a working "flow" file from. Work only in the current directory. Use ONLY flow-reference.md; do not read flowcheck.py (run it, never read it), do not look outside this directory, and do not search the web.

Checker: python3 flowcheck.py <file>

The request, as a person would put it:
"Every entry, whatever kind it is, is built by one model. A different, cheaper model reviews every pull request, and it is merged once the reviewer is happy. If the reviewer keeps sending it back, I want to see it after three rounds. Separately, once a day something should look through the docs for anything that has gone stale and file what it finds."

Steps:
1. Write your first attempt to attempt-1.yml BEFORE running the checker. Run the checker on it and save its full output to attempt-1.out.
2. If it is not OK, write attempt-2.yml (never overwrite an earlier attempt), check it, and so on, up to 5 attempts.
3. Write trace.md: in plain sentences, walk an entry through your final flow, including one round where a reviewer says "changes wanted". Name the stage the entry is in after each outcome, which session (fresh or the same) does each part, and what the person has to do and when.
4. Write notes.md: anything in the reference that was unclear, missing, or that you had to guess; anything the request asked for that the format could not express; and any checker message you did not understand.

Your final reply: the number of attempts, whether the last one printed OK, and your notes. Be honest about guesses; a failed attempt is useful information, not a fault.
```

## Request 2

```
You are testing whether a short reference document is clear enough to write a working "flow" file from. Work only in the current directory. Use ONLY flow-reference.md; do not read flowcheck.py (run it, never read it), do not look outside this directory, and do not search the web.

Checker: python3 flowcheck.py <file>

The request, as a person would put it:
"Entries that need a design get one from a strong model first, and I do not need the design reviewed. Building is done on a cheap model. If the cheap builder gets stuck, a stronger model should try once before it comes to me. Every code pull request is reviewed by a different model. I merge pull requests myself; no session should merge."

Steps:
1. Write your first attempt to attempt-1.yml BEFORE running the checker. Run the checker on it and save its full output to attempt-1.out.
2. If it is not OK, write attempt-2.yml (never overwrite an earlier attempt), check it, and so on, up to 5 attempts.
3. Write trace.md: in plain sentences, walk an entry through your final flow, including one round where a reviewer says "changes wanted". Name the stage the entry is in after each outcome, which session (fresh or the same) does each part, and what the person has to do and when.
4. Write notes.md: anything in the reference that was unclear, missing, or that you had to guess; anything the request asked for that the format could not express; and any checker message you did not understand.

Your final reply: the number of attempts, whether the last one printed OK, and your notes. Be honest about guesses; a failed attempt is useful information, not a fault.
```

## Request 3

```
You are testing whether a short reference document is clear enough to write a working "flow" file from. Work only in the current directory. Use ONLY flow-reference.md; do not read flowcheck.py (run it, never read it), do not look outside this directory, and do not search the web.

Checker: python3 flowcheck.py <file>

The request, as a person would put it:
"Tests first. One session writes failing tests for the entry; a second session, on a different model, makes the tests pass. Two reviewers on two different models must both pass it. After that, pull requests that touch protected paths get one more read from my strongest model, and then it is merged automatically, without spending the strongest model on pull requests it does not read. Every entry starts the same way; I have no separate design step. Nothing should be able to go round in circles for ever."

Steps:
1. Write your first attempt to attempt-1.yml BEFORE running the checker. Run the checker on it and save its full output to attempt-1.out.
2. If it is not OK, write attempt-2.yml (never overwrite an earlier attempt), check it, and so on, up to 5 attempts.
3. Write trace.md: in plain sentences, walk an entry through your final flow, including one round where a reviewer says "changes wanted". Name the stage the entry is in after each outcome, which session (fresh or the same) does each part, and what the person has to do and when.
4. Write notes.md: anything in the reference that was unclear, missing, or that you had to guess; anything the request asked for that the format could not express; and any checker message you did not understand.

Your final reply: the number of attempts, whether the last one printed OK, and your notes. Be honest about guesses; a failed attempt is useful information, not a fault.
```
