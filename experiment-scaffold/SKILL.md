---
name: experiment-scaffold
description: Use when someone wants to set up a long-horizon agentic search — "I want an agent to improve X over time", "set up an experiment for this", "search over my rule table / prompt / engine" — or when an existing experiment needs the loop built around code they already have. Interviews, measures, then writes a runnable experiment laid out so viewer-scaffold can instrument it. Refuses searches with no artifact to adopt.
---

# experiment-scaffold

Build a long-horizon search: an outer loop that edits one artifact, scores it
with a frozen instrument, and adopts only what survives a held-out check.

**Announce at start:** "I'm using the experiment-scaffold skill to set up
`<name>`."

The pattern is in `../FIELD-GUIDE.md`. The worked example is
`../examples/synthetic_search`, which runs offline. This skill's output is an
experiment of that shape, in the person's own domain.

It pairs with **viewer-scaffold**, which builds the dashboard. An experiment
this skill produces is admissible to that one without negotiation, and the
membership check at the end proves it.

## What you produce

A runnable experiment directory: the package, the taskset, the substrate, the
CLI, the supervisor, the provider resolution, the image, the brief, the tests,
and the six pieces of verification the field guide's §4 lists. Not a skeleton
with TODOs, and not a design document alone.

What you cannot produce without asking: what an example is, how a candidate is
built, what the scorer measures. Those come from the interview and from reading
their code. **Refuse rather than guess** — a scorer you invented is a search
that measures nothing.

## Non-negotiables

1. **Measure before you scaffold.** The spike (step 2) is a gate. A search
   whose scorer is not deterministic, or whose cached path is not fast, needs
   fixing there — not wrapping in seven hundred lines of loop.
2. **No default path to anything outside the experiment.** Exit 2 naming the
   variable. A fallback is a path that is silently wrong on the next machine.
3. **The leak boundary is structural, and you verify it.** Held-out splits must
   not be in the image's build context. Run the greps and print them.
4. **A reward of zero is never ambiguous.** Ask the person to name every way
   their search can return zero. Fewer than three answers means they have not
   thought about it yet.
5. **Never claim a check you did not run.** The hand-over quotes real output and
   has a separate "Not checked" section.
6. **Every candidate passes a validity check before it is scored.** Separate
   from the reward, runnable in the box, enforced on the host against the
   returned artifact, and kept outside the editable area. When the artifact is
   code, that check is its test suite. See `reference/contracts.md` §7.

## Procedure

Three stops: the classification, the spike, and the design. Nothing else waits
on the person.

### 0. Start

1. **The experiment.** If the request names one, use it. Otherwise ask what the
   search should improve — one question, in their words, not a form.
2. **Prerequisites**, checked by you, not asked: `python3 --version` ≥ 3.12,
   `uv --version`, `docker --version` (note its absence rather than failing —
   the image build becomes a "Not checked" line), and git. **Linux, not
   macOS.** `template/supervisor.sh`'s `latest_run` uses `find -printf`, which
   is GNU-only and has no BSD `find` equivalent; every scaffolded experiment
   inherits that supervisor unmodified, so it will not run its outer loop on a
   Mac.
3. **An existing experiment.** If the directory exists, you are retrofitting:
   see "Retrofit" below. Never overwrite.
4. **Scratch.** Use the harness's scratchpad if it offers one, else `mktemp -d`.

### 1. Classify — and be willing to refuse

Work `reference/families.md`. Ask its four questions and answer them by
looking, not by discussing:

1. Is there an artifact that survives a rollout and serializes out of a
   container?
2. Is there a scorer that runs on the host, deterministically, fast when
   cached?
3. Is there a held-out slice with meaning?
4. Can a winner be adopted, so the next generation starts from it?

**No to (1) or (4): stop.** Say which question failed and why the pattern does
not fit. There is no force flag. **No to (2):** family D — proceed only after
they acknowledge, in their own words, that the gate is a coin flip unless
validation is re-judged with pinned seeds.

**Stop here** and tell them the family, in one short paragraph, before going on.

### 2. Spike — the gate

Follow `reference/spike.md`. Score one real example end to end, by hand, twice
cold and once warm. Record all of it.

- **The two cold runs must agree exactly.** Not nearly — a threshold comparison
  does not care how small a disagreement is.
- **The cached run must be fast**, because the agent scores dozens of times per
  rollout.

If either fails, **stop and say so**. The fix is in their substrate, and it is
much cheaper now than after a loop is wrapped around it.

### 3. Write `DESIGN.md`, show it, wait

This is the checkpoint. Write the experiment's `DESIGN.md` covering: the goal,
the family and the four answers, the spike's numbers, what is editable and what
is frozen, the corpus and its splits, the leak boundary, the reward and the
ways it can return zero, the failures the reward prices and the ones it
ignores, promotion, the gate and its tolerances, adoption, the rollout model,
the reviewer model, the rollouts per generation, the budget, and the
verification layer.

Four of those are not in the code and belong to the person, not the template.
Ask each, with a default they can accept rather than a blank they must fill:

- **rollout model** — the model the outer loop's rollouts use;
- **reviewer model** — the stronger model the reviewer asks, only if review is on;
- **rollouts per generation** — `NUM_ROLLOUTS`, default 3;
- **budget** — the most the whole search may spend.

Ask explicitly **whether to enable the reviewer**, instead of only reporting the
choice at hand-over. The reviewer template ships enabled because a scaffolder is
meant to choose deliberately; a deliberate "off" is the answer that keeps a
cloned example from silently charging.

`../examples/synthetic_search/DESIGN.md` is what one looks like.

Show it in plain words — not the file — and ask whether it is right. They know
things the code does not: which data is real, which measurement is trusted,
what a regression would mean to them. Take corrections into the document.

**Past this point, do not stop until step 7.**

### 4. Generate

Copy from `template/` per `reference/template-manifest.md`:

- **verbatim** files are copied unchanged. They encode failures somebody has
  already paid for — the supervisor's error branches, the exit codes, the
  provider refusal, the ignore-file shape. Do not improve them per experiment.
- **adapt** files are copied and filled; the placeholders are in the manifest.
  A file still containing `__` is unfinished.
- **write-fresh** files are written against `reference/contracts.md`. This is
  the domain half: the corpus, the measurement, the scorer, eligibility, the
  gate, the in-box tool, the Dockerfile's `COPY` list.

Write the brief with its fixed opening — the turn budget, land an edit early,
each edit is a checkpoint, scratch is discarded, and exactly which paths come
back. Then check mechanically that those paths equal what `finalize` returns.

Write the tests as you go, not after: each piece of the substrate gets the test
that would catch its failure. The example's `tests/` is the model, and its
`test_supervisor.py` in particular — the loop's error branches are the least
tested code in any search and they run at 3am.

Those are the substrate's tests, and they run on the host before a search
starts. They are **not** the validity check, which runs per candidate and is
the one rail a rollout agent can see. Write that too, and ship it in the image.

Write `review.md` the way you write the brief: the frame is fixed, the concerns
are the domain. Ask the person the same question as for zero rewards — *name the
ways a candidate could beat this reward without solving the problem* — and turn
every answer the validity check cannot express into a concern. Fewer than three
means they have not thought about it yet.

### 5. Verify what you can

```bash
uv sync --extra orchestrator --group dev
uv run --extra orchestrator --group dev pytest -q

# viewer-scaffold admissibility — the three write sites
grep -rnE "promotions.*\.jsonl" src/ | grep -vE "/tests?/"
grep -rnE "gate.*\.json" src/ | grep -vE "/tests?/"
grep -rnE "candidates" src/ | grep -vE "/tests?/"

# the leak boundary — note the leading dot; a *.dockerignore glob misses it
grep -nE "corpus/(val|test)" Dockerfile            # must find nothing
grep -nE "corpus/(val|test)" .dockerignore         # must find them
grep -nE "^COPY \\.( |$)" Dockerfile               # must find nothing

./run.sh --check

# the validity check is part of the instrument and enforced before scoring
grep -n "validity" src/*/substrate/measure.py   # must find the call and the pin

# the reviewer sits between gate and adopt, and a refusal is recorded
grep -n "run_review" supervisor.sh
grep -n "reviews.jsonl" .gitignore supervisor.sh
```

Preflight needs a corpus, an image and a key. Whatever is missing, it names —
and so do you. Never report readiness on the strength of a stage that did not
run.

### 6. Hand over

Write for someone who has not followed the work:

1. **What it is:** one paragraph — the artifact, the instrument, what a
   generation does.
2. **Try it now:** the commands that work today with no key and no Docker.
3. **Checked:** quote the **actual last lines** of `pytest`, the membership
   greps, the leak greps and each preflight stage that ran. Do not summarise
   them as "passed".
4. **Not checked:** every stage that did not run, why, and the exact command
   that runs it.
5. **Next:** `/viewer-scaffold <experiment>` for the dashboard; then the pilot
   — one generation, one rollout — with its cost estimate. Once the experiment
   is scaffolded and its preflight passes, viewer-scaffold generates a live
   read-only dashboard for it, and the contracts in `reference/contracts.md`
   are exactly what it greps for.
   Also state the step-3 answers the scaffolded configs carry: the rollout
   model, the rollouts per generation, the budget, and whether review is enabled
   — and, if it is, the reviewer model and the key variable it reads.
6. **Read the first generation before launching a long run.** Give them the
   four questions: did rewards land in a plausible spread, did the artifact
   actually change in most rollouts, what did the agents spend their turns on,
   and what fraction of attempts failed. This is the step everybody skips, and
   it is the cheapest one.

## Retrofit

Meeting a half-built experiment is normal, not exceptional. Retrofit is
**additive only**:

1. Inventory what exists — package, taskset, scorer, splits, loop, tests.
2. Print what you found and what you will add. Get a yes.
3. Add only what is missing. **Never overwrite**, and treat any conflict as a
   stop.
4. Run step 5's checks regardless, so the result is still admissible to
   viewer-scaffold.

Do not re-scaffold an experiment that has run. Its files carry hand-tuning you
cannot distinguish from your own output.

## Known limits — state these, do not paper over them

- **The spike proves the scorer runs, not that it measures the right thing.**
  Two runs agreeing says nothing about whether the number means what the person
  thinks. That judgement is theirs, and `DESIGN.md` is where it is argued.
- **The leak greps check the paths you know about.** A scorer that reaches the
  held-out data by some other route — a database, a network call, an absolute
  path — passes them. Ask where the data comes from.
- **A context filter is only half the boundary, and the weaker half.** Named
  `Dockerfile.dockerignore` it is honoured by BuildKit alone, so on a host or CI
  runner with the legacy builder it does nothing at all. Use `.dockerignore`,
  and rely on the `COPY` list — which holds everywhere — as the half that
  actually keeps held-out data out of the image.
- **Family D searches get a loop that runs, not a search that works.** A noisy
  reward needs a gain threshold derived from its measured spread, and that
  measurement is the person's to make.
- **A generated preflight has never passed until it passes.** Say which stages
  ran.
- **The reviewer is the one non-deterministic stage in a deterministic loop.**
  Veto-only confines it to subtracting candidates, so the reward curve stays
  sound, but the *set of adopted candidates* is no longer a function of the
  seed alone: two runs with the same seed can adopt different winners. Record
  that when comparing runs, and turn the reviewer off when reproducing one.

## Testing the skill itself

From this directory:

```bash
python3 -m unittest discover -s test -p 'test_*.py' -t test
cd ../examples/synthetic_search && uv run --group dev pytest -q
```

The first checks this skill: the manifest covers the templates, the verbatim
templates have not drifted from the example, nothing here carries proprietary
vocabulary, and `SKILL.md` references only files that exist. The second runs
the example, which is what the drift test diffs against — if it is failing, the
source of truth is broken and the templates cannot be trusted.

Run both whenever a template, a reference document or the example changes.
