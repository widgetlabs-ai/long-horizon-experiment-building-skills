# The spike

Before any scaffolding, score one real example end to end, by hand, twice.

This is a gate, not a warm-up. Everything in the interview so far is a claim;
the spike is the first evidence. It answers three questions at once — the
artifact can be produced, the scorer runs on the host, and it agrees with
itself — and it catches the float-nondeterminism failure for free, before it
costs a night.

If the spike cannot be done, the experiment cannot be scaffolded. That is
information, and it is cheap.

## What to do

**1. Produce one artifact by hand.** Whatever the search will edit, produce a
version of it the way a rollout would: check it out, copy it, patch it. Not a
mock. If this is hard, note *why* — it is the same difficulty `finalize` will
have.

**2. Score it, cold.** No cache, nothing warm. Time it.

**3. Score it again, cold.** Same input, same command, cache still bypassed.
Time it, and **diff the numbers**.

**4. Score it a third time, warm.** Whatever caching the design intends. Time
it.

**5. Write all four numbers into `DESIGN.md`**, with the corpus size they were
measured on.

## What the numbers have to say

### The two cold runs must agree exactly

Not nearly. A threshold comparison does not care how small a disagreement is:
`>` flips, a candidate is promoted or refused on a difference of 1e-16, and the
result is a search whose decisions cannot be reproduced.

If they disagree:

- Look for a subtraction of two similar floats — cancellation produces a
  build-dependent sign.
- Look for an accumulation over an unordered collection.
- Fix by keeping counts as integers and dividing once at the end, and by
  quantizing everything that feeds a comparison (nine decimal places is a
  reasonable default).
- Then pin it with a selftest that measures twice and requires equality, so it
  cannot come back.

If they disagree *and you cannot make them agree* — a judged reward, a timing
measurement, a genuinely stochastic environment — this is family D in
`families.md`. Stop and say so. The gate needs a different design, and the
person needs to know that before the loop is built around it.

### The cached run must be fast

The agent scores dozens of times per rollout. That is the number that decides
whether the loop is usable at all — not the cold path, which runs once per
candidate on the host.

Rough guidance: seconds is fine, tens of seconds is painful, minutes means the
agent spends its budget waiting and the search is bounded by the wrong thing.

If the cached path is not fast, **stop and fix that first**. It is the one
problem that gets structurally harder once a loop is wrapped around it, and the
fix is nearly always the same: find the expensive stage, do it once, key the
result on everything that could change the answer, and make a stale key
impossible rather than unlikely.

### The cold run tells you the host's cost per candidate

Multiply by candidates per generation. If that is a meaningful fraction of a
generation's wall clock, scoring needs to be off the event loop — a blocking
subprocess call inside an `async def` stalls every other live rollout's
streaming while it runs.

## What the spike also settles, quietly

- **Where the data actually is.** A path you had to type here is a path that
  needs a resolver with no default, not a constant.
- **What "one example" means.** Often the first time anybody says precisely
  what the unit of scoring is.
- **Whether the scorer is honest about failure.** Feed it something broken. If
  it returns `0` rather than saying it failed, that ambiguity is now yours to
  fix, and `contracts.md` §3 says how.

## Recording it

`DESIGN.md` gets a short table:

| measurement | value |
|---|---|
| corpus | (size, and how split) |
| baseline | (the number, at full precision) |
| cold measurement | (time) |
| cached measurement | (time) |
| ratio | |
| two cold runs agree | exactly / to N places / no |

Written down, this is what a reader compares against six months later when
scoring has quietly become slow, or when a number stops reproducing.
