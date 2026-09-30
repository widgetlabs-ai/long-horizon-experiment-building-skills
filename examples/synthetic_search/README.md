# synthetic_search

A complete long-horizon search, small enough to read in an afternoon and real
enough to run. An agent edits one rule table; a frozen scorer grades it against
a generated corpus; an outer loop promotes, gates and adopts only what holds up
on data the loop never fitted.

It exists to be **copied**. Nothing here is a mock: the corpus is generated
rather than downloaded, so there is nothing to fetch and no credentials to
have, but every other part — the guard, the cache, the splits, the gate, the
supervisor's error branches — is what you would write for a real search.

Design: `DESIGN.md`. The pattern it follows: `../../FIELD-GUIDE.md`.

## Try it in one minute

```bash
cd long-horizon/skills/examples/synthetic_search
export SYNTH_STATE=$PWD/state
uv run --extra orchestrator --group dev pytest -q # the substrate's own suite
uv run python -m synthetic_search.substrate.cli stage --seed 7 --rows 2000
uv run python -m synthetic_search.substrate.cli pin
uv run python -m synthetic_search.substrate.cli baseline --split all
uv run python -m synthetic_search.substrate.cli report --limit 3
```

`report` prints the table's weakest categories — the same ones the brief hands
an agent. Nothing above needs Docker, a model, or a key.

`verifiers` lives behind `--extra orchestrator`, not in the `dev` group —
leave it off and `uv run --group dev pytest -q` still exits 0, but it silently
skips every test gated on `find_spec("verifiers") is None`, six in this suite,
including the guard against `build` ever writing the tracked artifact. A green
run without the extra has verified none of those.

## Layout

```
artifact/rules.py         the editable artifact — the ONLY thing the search changes
brief.md                  what the agent is told, rendered per task
src/synthetic_search/
  taskset.py              the verifiers v1 taskset: one task per category
  substrate/
    corpus.py             generate, split three ways, resolve without a default
    artifact.py           load the table, and refuse one that could read its labels
    scorer.py             macro-F1 — frozen
    measure.py            the only way anything is scored, cached on a real key
    evaluate.py           metrics that disambiguate a zero
    promote.py            rank on train, stage a winner, adopt a gated one
    regression_gate.py    rescore on val, per category; discard what fails
    selftest.py           the invariants, and the post-generation trace read
    box.py                `rt` — the agent's tool inside the container
    taskset_contract.py   what comes back from a rollout; the brief renders from it
    cli.py                every phase, one exit-code contract
tests/                    the suite that proves all of the above
tools/reference_run.py    R: drives the real writers with only the agent scripted
viewer/                   the viewer-scaffold output for this experiment
Dockerfile                the rollout image
Dockerfile.dockerignore   the leak boundary: val and test are not in the context
provider.sh run.sh supervisor.sh
```

## Running the search

```bash
export OPENCODE_API_KEY=...          # or OPENROUTER_API_KEY
./run.sh --check                     # preflight, ending in one real model call
MAX_GENERATIONS=1 NUM_ROLLOUTS=1 ./run.sh
```

| variable | default | what |
|---|---|---|
| `MAX_GENERATIONS` | 1 | generations this run does |
| `NUM_ROLLOUTS` | 3 | rollouts per task (5 tasks, one per category) |
| `MAX_CONCURRENT` | 3 | rollout containers at once |
| `MAX_TURNS` | the config's 120 | agent turns per rollout |

`run.sh --check` runs every check it can and **names the ones it skipped** —
the image build without Docker, the live call without a key. A preflight that
reported readiness on the strength of a skipped stage would be worse than none.

Read the first generation before launching a long run:

```bash
uv run python -m synthetic_search.substrate.cli post-generation --run outputs/<run>
```

It prints every rollout's reward, gain, turn count and verdict — and a verdict
is never just "zero": `artifact_unchanged`, `guard_rejected` and `score_error`
are distinct, because a generation where every rollout returned the table
untouched looks exactly like one where the scorer broke, until something says
which it was.

## The reviewer

A second opinion between the gate and adoption, off by default. To enable it,
set `enabled = true` in `review.toml` and export the variable named there:

```bash
export REVIEW_API_KEY=...            # the `api_key_var` in review.toml
```

It costs **one model call per generation whose candidate passes the gate**;
generations that lose earlier never reach it. It can refuse an adoption and
nothing else. A wrong model id is a 4xx from the provider, which stops the run
with exit 2 and says so. Check `model` against your provider's list first.
Verdicts accumulate in `state/reviews.jsonl`. The reasoning is in
[DESIGN.md](DESIGN.md#the-reviewer).

## What to copy, and what to think about again

Copy: the exit-code contract, the supervisor's error branches, `provider.sh`,
the abort sentinel, the state layout, the `.gitignore` shape.

Think again about: the categories (yours are not these), the tolerance, the
split mode, and above all **the list of ways your search can return zero**.
That list is the one part of an experiment that cannot be copied from another
one.
