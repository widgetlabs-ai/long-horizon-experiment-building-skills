# experiment-scaffold

A skill that walks you through building a long-horizon search: an outer loop
that edits one artifact, scores it with a frozen instrument, and keeps only
what survives a held-out check. `SKILL.md` is the procedure the agent follows.
This file only says how to start it.

## Starting it

In a harness that discovers skills through `.claude/skills/`, type
`/experiment-scaffold`, or just say what you want to search over.

In any other harness whose agent can read and write files and run shell
commands:

> Read `<skill-dir>/SKILL.md` and follow it.

You do not need to prepare anything. The agent asks what the search should
improve, checks the prerequisites itself, and stops three times: once to tell
you whether your search fits the pattern at all (it refuses some, and says
why), once to show you the measurements it took before writing any code, and
once to agree the design. Then it writes the experiment and hands you a list of
what it checked and what it could not.

## What you get

A runnable experiment directory — package, taskset, scorer, splits, promotion,
gate, adoption, supervisor, image, brief, tests — laid out so that
`viewer-scaffold` can build its dashboard without any further work.

## The example

`../examples/synthetic_search` is a complete search of this shape that runs
offline, with no key and nothing to download. It is worth ten minutes before
starting your own: it is also what this skill's templates are copied from and
diffed against.

## Caveats

- **It refuses some searches.** No artifact that survives a rollout, or no way
  to adopt a winner, means there is nothing to promote and nothing to gate.
  That is intended, and `reference/families.md` says exactly which question
  failed.
- **The spike is a gate, not a formality.** If your scorer is not deterministic
  or is slow when cached, the skill stops there. That is the cheapest moment to
  find out.
- **A generated preflight has never passed until it passes.** The hand-over
  separates what was checked from what could not be, and the second list is the
  one to read.
- **The worked examples assume one eval framework.** On another, the agent has
  to find that framework's equivalents; `reference/contracts.md` says what to
  look for.
