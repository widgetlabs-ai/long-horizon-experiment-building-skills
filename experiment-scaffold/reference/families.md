# Families, and what this skill refuses

Not every search fits this pattern, and the ones that do not are better served
by something else. Establish the family in the first few minutes: a refusal
costs a conversation, and a scaffold around a search that cannot be gated costs
a week.

## The four questions

Ask these first. Each is answerable by looking, not by discussing.

1. **Is there an artifact that survives the rollout** and can be serialized out
   of a container? One file, one directory, one patch — something that can be
   copied out and scored again somewhere else.
2. **Is there a scorer that runs on the host, deterministically, in
   seconds-when-cached?** Run it twice on the same input and diff the numbers.
3. **Is there a held-out slice with meaning?** Not "can the data be split" —
   whether a split says something. Held-out *what*, and what would it prove?
4. **Can a winner be adopted**, so the next generation starts from it?

**No to (1) or (4): refuse.** Name which question failed. Without an artifact
there is nothing to promote, and without adoption there is no search — only a
sequence of unrelated attempts. This is not a limitation to work around; it is
what distinguishes a long-horizon search from an evaluation.

**No to (2): this is family D.** Proceed only after the person acknowledges, in
their own words, that the reward is noisy and the gate is a coin flip unless
validation is re-judged with pinned seeds.

**No to (3):** usually a corpus that has not been thought about yet rather than
a real no. Spend ten minutes on it before concluding anything.

## The families

| family | artifact | reward | corpus | fit |
|---|---|---|---|---|
| **A. Artifact over a corpus** | source, rule table, prompt, config | a frozen scorer, meaned over train | labelled, split three ways | native |
| **B. Benchmark pass-rate** | the system under test | a benchmark harness's rate | benchmark tasks, split three ways | native; the scorer is third-party |
| **C. Spec / test satisfaction** | source under test | fraction of a suite passing | suites, not rows | supported, with "split" re-read |
| **D. Judge-scored generation** | prompt or generator | an LLM judge's score | prompts, split | allowed on acknowledgment |
| **E. Policy over a game environment** | strategy file or prompt | return over fixed seeds | seed sets as splits | allowed if the seeds are frozen |
| **F. Pure evaluation / weight training** | none / weights | — | — | **refused** |

### A — artifact over a corpus

The shape `examples/synthetic_search` demonstrates, and the one most searches
turn out to be. Everything in the field guide applies without translation.

### B — benchmark pass-rate

Identical in structure; the difference is that you did not write the scorer, so
you cannot assume it is deterministic, fast when cached, or honest about a
failed run. Time it and run it twice before anything else. Third-party
harnesses commonly return 0 for "errored" and 0 for "failed everything", which
is §4's ambiguous zero arriving from outside your code — wrap it so the two are
distinguishable before you use it as a reward.

### C — spec / test satisfaction

The reward is a pass rate over a suite. The re-reading is of "split": rows do
not split meaningfully, **suites** do. Hold out whole suites, not individual
cases, or the agent fits the held-out cases through their neighbours in the
same file.

Watch for the degenerate solution. A search whose reward is "tests pass" and
whose artifact includes the tests will delete the tests. Freeze them, and treat
the test files as instrument.

### D — judge-scored generation

Structurally fine, and it breaks two things the pattern leans on:

- **Determinism.** The same artifact scores differently on two runs, so the
  selftest's determinism check cannot hold, and a "gain" of a few hundredths
  may be noise. Pin seeds and temperature where the judge allows it, and set a
  gain threshold well above the measured run-to-run spread — measure that
  spread first, by scoring one artifact ten times.
- **Cheap cached scoring.** A judged measurement costs money and seconds. The
  agent cannot score dozens of times per rollout. Expect to redesign the inner
  loop: a cheap proxy the agent steers by, and the judge only on the host.

Say both out loud before scaffolding. A search built on an unacknowledged noisy
reward produces a curve that rises and means nothing.

### E — policy over a game environment

Works when the seed set is frozen and treated exactly like a corpus: train
seeds for the reward, held-out seeds for the gate. An unfrozen seed set is the
same failure as a moving corpus — the denominator changes under you and the
curve is uninterpretable.

### F — refused

Pure evaluation environments have no artifact: they measure a model, and there
is nothing to adopt. Weight training has an optimiser already, and it is not
the agent. Neither is a defect; they are different activities, well served by
the frameworks built for them.

## Environment hubs: what they give you and what they do not

Public hubs host thousands of ready-made environments — an environment there is
an **episode scorer**: a task goes in, a reward comes out, and nothing survives
the episode.

That is the *inner* half of one of these searches, and often a genuinely good
one: somebody has already written the task construction, the parsing and the
reward for your domain.

What it does not give you, and what stays yours to write:

| you still need | why |
|---|---|
| the artifact | the environment scores a model's output, not a thing you keep |
| the splits | an environment's dataset is not split for *your* gate |
| promote / gate / adopt | the environment has no memory across episodes |
| the leak boundary | nothing stops the box seeing what you plan to gate on |

**Mounting one as the inner half.** Read its `pyproject.toml` for its
dependencies and its entry point, install it beside your experiment rather than
inside it, and call its reward from your task's `score` on the host. Keep your
own metrics around it — an external scorer's zero is not self-describing.

Do not build a live hub lookup into an unattended procedure. Hub listings are
not reliably machine-readable without credentials, and a step that guesses at
search results is a step that guesses.
