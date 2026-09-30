# Long-Horizon Search Field Guide

How to build an unattended agentic search on **verifiers v1** — the
architecture, the vocabulary, and the failures that are worth knowing about
before they cost you a night of tokens.

The worked example throughout is `examples/synthetic_search`, which is in this
repository and runs offline. Every number here is measured against it, not
recalled. Where a lesson came from a larger private search, the lesson is kept
and the setting is the example's.

---

## 1. The shape of the thing

A long-horizon search is **an outer loop that edits one artifact**. Everything
else is scaffolding to make that edit measurable, reversible, and safe to run
for eight hours with nobody watching.

```
run                 one ./run.sh                          hours to days
└── generation      one `uv run eval`                     ~1-2 h
    └── task        one sub-problem to work on            5 per generation
        └── rollout one container, one agent              3 per task
            └── turn one model exchange                   ≤120 per rollout
```

The unit of **learning** is the generation: rollouts propose, the outer loop
picks a winner, gates it, and commits. The unit of **isolation** is the
rollout: one container, destroyed at the end, nothing shared.

A run is a scheduling unit, not a boundary of the search. Number generations
across runs, so the promotions, the commit messages and any dashboard read as
one continuing history rather than as unrelated sessions.

### Where each is configured

| knob | where |
|---|---|
| generations | `MAX_GENERATIONS` → `supervisor.sh` |
| tasks | `[env.taskset] num_tasks` in the config |
| rollouts per task | `--num-rollouts` |
| turns per rollout | `[env.agent] max_turns` |
| containers in parallel | `--max-concurrent` |
| wall clock per rollout | `[env.agent.timeout] rollout` |

Episodes per generation = `tasks × num_rollouts`.

> **Trap:** there are two different `num_tasks`. The one in your config's
> taskset section is *yours* — how many tasks your taskset produces. The
> framework's `--num-tasks` subsamples the produced list. They are not the same
> knob.

> **Trap:** the framework calls one output directory a "run". That is one
> *generation* in the vocabulary above. A fifteen-generation run leaves fifteen
> of them.

---

## 2. The runtime chain

```
supervisor.sh                        host bash, one process for the whole run
└── eval @ config.toml               host python, one process per generation
    └── ×N rollouts (max_concurrent at a time)
        ├── docker run --detach ... sleep infinity      ← the box
        │   └── docker exec → the agent harness
        └── interception proxy (on the HOST)
            └── https://<provider>/v1/...
```

Three things surprise everyone the first time:

**The agent runs in the container; the model does not.** The harness points the
agent inside the box at an interception proxy on the host. The box needs no API
key. Choose the real upstream in your client config, never by setting a base
URL in the container's environment — the harness overwrites it, and you would
bypass tracing.

**The container is a shell to exec into, not a job.** It starts as
`--entrypoint sleep … infinity` and everything happens through `docker exec`.
Any `CMD` in your Dockerfile is overridden.

**Your reward is computed on the host, not in the box.** The agent's in-box
scoring is feedback it uses; the reward comes from your task's `score` running
in the orchestrator process against your real data. This distinction is the
single most important thing in this document — see §5.1.

### The rollout lifecycle

In order: the runtime starts the container; your `setup` writes your files in;
the harness installs itself inside the box; the proxy comes up and the prompt
is sent; the agent loop runs to `max_turns`; your `finalize` copies files out;
your `score` produces rewards and metrics; the container is force-removed.

**`finalize` and `score` are skipped when the rollout fails.** There is no
task-side hook on the failure path. A harness error therefore discards whatever
the agent produced, sitting in a container that is about to be deleted. Design
around this — see §5.9.

### Why the container is not optional

The agent asks permission to run things, and the framework auto-approves. So
nothing says no to the agent, and the boundary has to be the box.

Because one turn is a single blocking call, **there is no mid-turn
checkpoint**. When the HTTP leg underneath dies, the whole turn unwinds.

---

## 3. The design patterns that earn their keep

### 3.1 Split the artifact from the ruler

One thing is **editable** — what the search rewrites. Everything that turns an
edit into a number is **frozen**, and documented as frozen. A change that
cannot be measured by the frozen scorer does not count.

Enforce it structurally. The example's `artifact.check_source` walks the AST of
the returned file and rejects every `import`, plus `open`/`eval`/`exec` and
dunder attribute access. An artifact that can read the labels it is graded
against scores perfectly and teaches nothing — and the number is
indistinguishable from a real result.

**A static check is not enough on its own: never hand the artifact a module
object.** A module carries everything it imported, so one handed in as a
convenience is a path to the rest of the interpreter — CPython's `re` imports
`enum`, and `enum` imports `builtins`, which puts `open` back within reach with
no import statement, no denied name and no dunder anywhere in the source. Pass a
curated namespace of the functions the artifact actually needs. This was found
by a reviewer, in code whose own tests asserted the guard held.

### 3.2 Extract once, score many

The agent scores dozens of times per rollout, so the ratio between a cold
measurement and a cached one decides whether the loop is usable at all.

Measured on `examples/synthetic_search`, 1,200 training rows:

| | |
|---|---|
| cold measurement | 7.0 ms |
| cached measurement | 0.38 ms |
| ratio | ~19× |

Key the cache on everything that could change the answer — the artifact's
digest, the instrument's pin, and the split's **rows**, not merely its
manifest. Staging usually writes the manifest last, so an interrupted re-stage
leaves changed rows under an unchanged manifest, and a manifest-keyed cache then
serves a reward measured over rows that no longer exist. A cache that silently
disagrees with the code that filled it is the worst kind of bug, because every
number stays plausible.

If your cached path is not fast, fix that **before** writing the outer loop.
Scaffolding a loop around a slow scorer buries the problem under hundreds of
lines.

### 3.3 Make the leak boundary a build-context boundary

The rollout image contains **train only**. Validation and test never enter it.
Docker's inability to read outside its build context enforces this; a
convention someone has to remember does not.

**Two halves, because one of them is builder-dependent.** A context filter
named `Dockerfile.dockerignore` is honoured only by BuildKit — under the legacy
builder (`DOCKER_BUILDKIT=0`, or any Docker before 23) it is ignored in full and
every held-out row enters the context, with no warning. Use the plain
`.dockerignore` name, which both builders honour, *and* copy named paths rather
than the context wholesale. Verified against Docker 29 in both modes.

The example does this in `.dockerignore`, and goes one step further:
the in-box tool refuses `--split val` with an explanation rather than answering
it. A box that can score itself on the split it is gated against can be
optimised against that split, and the gate stops meaning anything.

### 3.4 An outer loop that can say no

The framework has no notion of "this edit helped the sub-problem it was aimed
at and broke another". So each generation is:

```
eval  →  promote the best candidate  →  gate it on VALIDATION  →  commit, or revert
```

- **promote** selects on *train* — the same split the rewards used. Never on
  validation: a candidate chosen for its validation score has already spent it.
- **the gate** rescores on validation, per sub-problem rather than on the mean,
  and a failure discards the candidate outright. Re-gating it could only fail
  again.
- **sub-problems with too little validation support are exempt**, explicitly,
  in code, with the support numbers printed. A gate at four rows is a coin flip
  dressed as a criterion, and the decision to exempt should be recheckable
  against the data.
- **a perfect sub-problem gets no tolerance at all.** It has no defects left to
  trade, so any drop is one the candidate introduced. Letting it slip a few
  thousandths per generation is how "everything works" decays into "everything
  nearly works".

---

## 4. Instrumentation to build **before** the first long run

Every item here was added after it cost somebody something.

| build this | because |
|---|---|
| **A preflight** that checks everything knowable at generation 0 | a weekend run that dies on generation 9 for a missing file is the failure this prevents. End it with **one live model call**: a key that is set but wrong looks exactly like a key that works |
| **A selftest** on the scoring invariants | determinism, quantization, cache agreement, taxonomy membership. Runs in seconds; catches the silent lies |
| **A post-generation check** that reads the traces | the eval exits 0 whether its rollouts learned anything or failed identically. The exit code cannot tell you anything |
| **Metrics that disambiguate a zero** | `reward=0` must never be ambiguous between "the candidate is bad", "the candidate never arrived", and "the scorer broke" |
| **An abort sentinel** | a rollout that discovers the substrate is broken cannot cancel its siblings, but it can leave a file the supervisor refuses to start on |
| **A distinct exit code for "nothing here can score"** | `2` = substrate broken (stop the run), `1` = this candidate lost (keep going). It propagates cli → promote → gate → supervisor |

Five of these are nearly domain-free and can be copied. The sixth cannot: the
list of ways *your* search returns zero is yours to write. Ask the question
explicitly — *name every way this can return zero* — and do not accept fewer
than three answers.

---

## 5. The failure catalogue

Each of these is a real incident. The lesson is the part that generalizes.

### 5.1 A default path that guesses

**Symptom.** A whole night of rollouts, every one `reward=0.000`, and the loop
never noticed.

**Cause.** A corpus path had a fallback default baked into six places. The data
moved; the fallback pointed at nothing. Rollouts scored happily against the
train slice baked into their image, while the host reward path found an empty
corpus and reported zeros.

**Fix.** No default, anywhere. One resolver, three distinct errors (unset /
missing / present-but-wrong-shape), and resolution **at taskset load** so a
wrong path costs zero tokens instead of a night.

> **Lesson.** For any path pointing outside the project: exit rather than guess.
> A fallback is a path that is silently wrong on the next machine. And where the
> same data exists on both sides of a sandbox boundary, a misconfiguration can
> look *locally* healthy on each side while the system as a whole measures
> nothing.

### 5.2 Reading a field that is never serialized

**Symptom.** A healthy generation killed by a safety check: "every scored
rollout returned reward 0.000". They had scored perfectly reasonable numbers,
and two were real improvements.

**Cause.** A reward serializes as `{"score": float, "weight": float}`. Its
`value` is a computed property — it never appears in the trace file. The reader
asked for `value`, got nothing, and summed to zero.

**Fix.** Read `score * weight`, plus tests built from real serialized records.
The reward also does not live where a framework's own API suggests it should:
each trace holds its own `rewards`, a `dict` keyed by reward name, and an
episode holds a **list** of traces — so a reader has to sum every named reward
on every trace, not read a single value off the episode itself. A reader
written against the episode directly, the natural place to look first, missed
this and returned nothing for months.

> **Lesson.** Never write a reader from a framework's *Python* API. Dump one
> real record and read the JSON. A property is invisible on the wire, and
> anything that can *stop* a run needs a test with a real payload before it is
> trusted to stop anything. "Tests built from real serialized records" means
> exactly that: a test that calls the framework's own writer and asserts the
> fixture agrees with what came out, not a fixture typed by hand to look
> plausible — a hand-typed fixture can encode the same wrong assumption as the
> reader it's supposed to catch, and then it passes forever while proving
> nothing.

### 5.3 The turn cap starved the actual work

**Symptom.** Most rollouts of a generation returned the artifact **unchanged**
and scored exactly the incumbent's numbers — which look like perfectly
reasonable rewards, because they are.

**Cause.** A turn cap set low as a stream-drop mitigation. Of all the write
operations across every trace, a handful touched the artifact; the rest were
analysis written to `/tmp`. Rollouts ended at the cap, and the few that reached
the artifact did so on the last turns available.

**Fix.** Three parts: raise the cap; rewrite the brief to **lead with the turn
budget** ("land an edit in the first ten turns, treat each edit as a
checkpoint, `/tmp` is discarded"); and add an `artifact_unchanged` metric
comparing what came back to what `setup` planted.

> **Lesson.** Agents will spend an unbounded budget on analysis if you let them.
> Tell them what survives the rollout, and **measure whether the artifact
> changed at all** — without that metric this is invisible in the summary and
> takes log forensics to find.
>
> Then check mechanically that the brief and `finalize` name the *same* paths.
> The example keeps both in one constant for exactly this reason.

### 5.4 Float nondeterminism between host and container

**Symptom.** Host and box disagreed on a handful of rows out of hundreds, and
the means differed in the third decimal.

**Cause.** A subtraction cancelling to ±1e-16 with a build-dependent sign, plus
last-ULP differences in summation, flipping `> 0` threshold tests.

**Fix.** Keep counts as integers and divide once at the end; quantize every
derived float that feeds a comparison (the example uses nine places); and pin
it with a selftest that measures twice and requires exact agreement.

> **Lesson.** If the same computation runs in two builds, quantize the values
> that feed threshold comparisons. And *check* that they agree — this is only
> ever found by running both and diffing.

### 5.5 The package pulled orchestrator dependencies into the box

**Symptom.** `docker build` failed: `ModuleNotFoundError: No module named
'verifiers'`.

**Cause.** `__init__.py` eagerly imported the taskset module, which imports the
orchestrator. The container needs the substrate, not the orchestrator.

**Fix.** A PEP 562 lazy `__getattr__` in `__init__.py`.

> **Lesson.** A taskset package is imported in two very different environments.
> Keep the heavy import behind a lazy accessor so the box stays minimal — and
> put the facts both sides need (what comes back, what is held out) in a module
> that imports neither.

### 5.6 Staging everything in an unattended loop

**Symptom.** Caught in review, not in production. The supervisor committed
after every generation, next to an untracked file holding a live API key.

**Fix.** Named paths only. Key-bearing files ignored.

> **Lesson.** An unattended loop that commits is a loop that can publish a
> secret. Enumerate what it may stage. (And rotate any key that has been in a
> working tree you later shared.)

### 5.7 Staging is atomic over its arguments

**Symptom.** Latent. A single ignored path among staged paths makes the **whole
stage fail**, and the `|| true` that must be there for the first generation
swallows it. Every later commit would have been empty, silently.

**Fix.** Stage each kept file by name, each guarded by its own `if [[ -f … ]]`.

> **Lesson.** Globs plus ignore rules plus `|| true` is a silent-failure
> machine.

### 5.8 Ignore-file subtleties that cost real time

Two, both verified the hard way:

- **No inline comments.** A comment after a pattern becomes part of the
  pattern, and the rule silently never matches.
- **`state/` blocks negations; `state/*` permits them.** Git does not descend
  into an excluded *directory*, so `state/` plus `!state/best.json` keeps
  nothing. Deny-by-default with exceptions requires the `/*` form.

For a search that commits its own progress, keep the provenance files — what
was promoted, by how much, what the gate said — and ignore everything else
under the state directory. A promoted artifact with no record of why is a
commit nobody can read.

### 5.9 `set -e` traps in the supervisor

Three, all found by testing the failure paths rather than the happy one:

```bash
cmd; case $? in ...; esac; if [[ $? -eq 0 ]]   # $? is now the CASE's status
[[ -f "$f" ]] && git add "$f"                  # returns 1 when absent → kills the script
some-command-that-can-lose                     # a normal non-zero exit kills the script
```

Use `status=0; cmd || status=$?` and `if [[ -f … ]]; then …; fi`.

> **Lesson.** The supervisor's error paths run at 3am and are the *least* tested
> code you own. Exercise each branch deliberately before the first long run —
> the example's `tests/test_supervisor.py` does this with fake exit codes, and
> it costs seconds.

### 5.10 Config that silently does not apply

A field set in the config file did not take effect; the resolved config still
showed the old value. The equivalent command-line flag worked.

> **Lesson.** After changing a config file, read the **resolved** config the
> framework writes into the run directory and confirm the field actually
> changed. Do not assume the file was honoured. Where it matters — uploading,
> for instance — set it in the file *and* pass the flag.

### 5.11 Failed rollouts discard the agent's work

**Symptom.** Several harness errors, each throwing away tens of minutes of
agent work.

**Cause.** The framework skips `finalize` and scoring on failure. The edited
artifact is in a container that is deleted the same second, and there is no
hook on that path.

**Mitigations, in order of cost:** whole-rollout retries (these do work);
keeping tool payloads small, since streamed tool arguments are where corruption
tends to appear and the big payloads are usually the agent's own scratch
scripts; and, if it persists, a host-side tool the agent calls to checkpoint
mid-rollout.

> **Lesson.** Find out early what your framework does on the failure path. If
> unfinished work is unrecoverable, every fix targets the failure *rate*, not
> the recovery — and the artifact should be cheap enough to re-derive that
> losing one attempt is affordable.

### 5.12 The dashboard that ate the error

**Symptom.** A generic "no handlers could be found" notice, and nothing else.

**Cause.** Under its rich dashboard mode, the framework suppresses last-resort
logging so stray records cannot print over the display, and intercepts exactly
one logger — its own. Any other logger's record, including the interception
proxy's, produces that notice instead of the error.

**Fix.** Run with streamed logs rather than the dashboard, and install a
**root** log handler early (a `sitecustomize.py` on `PYTHONPATH` runs before
the framework configures anything). Chain to the interpreter's own
`sitecustomize` rather than shadowing it.

> **Lesson.** A dashboard that owns the terminal is a dashboard that can eat
> your errors. For unattended runs, choose streamed logs and *prove* that a
> third-party logger's record reaches the file.

---

## 6. What it costs

You are bounded by remote model latency, not by CPU. `--max-concurrent` is the
only knob that moves total wall clock meaningfully, and it is also the one that
carries failure risk: many simultaneous long-lived streams are how first runs
die.

Budget from your own pilot rather than from anyone's table: one generation,
then read it. A rough shape to plan against is a few dollars and one to two
hours per generation at three concurrent rollouts, with a failure tax of
roughly a fifth on both time and spend — but measure it.

Host scoring should be negligible beside that. If it is not, §3.2 is where to
look. One more trap: scoring from inside an `async def` with a blocking
subprocess call stalls the whole event loop, including the other live rollouts'
streaming. Use a thread.

---

## 7. Where experiments live

Give **each experiment its own directory** under one common parent, rather than
letting it sprawl across a repository root. Its package, brief, configs, run
scripts, image, state and ignore rules all belong to it; a second experiment is
a new sibling directory, not an edit to a shared file.

### The one hard constraint: the taskset id must be a bare top-level module name

The loader takes the last path segment of the id, normalizes hyphens to
underscores, and imports *that*:

| id | result |
|---|---|
| `demo_search` | resolves |
| `demo-search` | resolves — hyphens are normalised |
| `group.demo_search` | **fails** |
| `group/demo_search` | **fails** — only `demo_search` is tried |

Dotted ids fail for a subtle reason worth knowing: the spec lookup **raises**
when a *parent* package is missing rather than returning nothing, so it blows
up before it can fall back to the bare name.

So: nest freely on **disk**; do not nest in the **module namespace**.

### The layout that works

```
experiments/<name>/                   project dir AND the id the taskset uses
├── pyproject.toml  uv.lock  .venv    its own dependencies, locked separately
├── src/<name>/                       the package, importable as a bare name
├── tests/  state/  outputs/  *.sh
```

The `src/` level is what lets the project directory and the package share a
name, which matters because the id is baked into configs and the image.

Each experiment pinning its own dependencies matters the moment one needs a
library another must not have.

**The Dockerfile is the one wrinkle.** If your image needs files from outside
the experiment directory, build with the wider directory as context and the
Dockerfile named explicitly, keeping every `COPY` path relative to that
context. If the experiment shares nothing, it owns its context entirely and
this disappears.

**Re-anchor your roots.** `Path(__file__).resolve().parents[N]` should mean
*the experiment's* root, and should say so:

```python
EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]   # the experiment, not the repo
```

Getting this wrong is §5.1 in a new costume: a path that resolves to something
plausible but wrong.

---

## 8. Checklist for the next experiment

**Before writing the taskset**

- [ ] Its own directory, config, scripts, state and ignore rules. The taskset id
      is still a bare top-level module name.
- [ ] Read the installed framework's source for every behaviour you depend on.
      Do not rely on recalled APIs.
- [ ] Decide what the editable artifact is, and what is frozen. **Write it
      down.**
- [ ] Decide the leak boundary and make it structural (build context), not
      conventional.
- [ ] Measure the scoring loop cold and cached. If cached scoring is not fast,
      fix that before anything else.

**Before the first long run**

- [ ] No default paths to anything outside the experiment. Exit 2 with the
      variable named.
- [ ] Preflight that ends with one real model call.
- [ ] Selftest covering determinism and host/box agreement.
- [ ] Metrics that make `reward=0` unambiguous, and one that says whether the
      artifact changed at all.
- [ ] A post-generation trace check — **with tests built from real records**.
- [ ] Exercise every error branch of the supervisor by hand.
- [ ] Confirm the resolved config matches what you wrote.
- [ ] Read the framework's failure path. Know what is lost when a rollout dies.
- [ ] Streamed logs, and prove a third-party logger's record reaches the file.
- [ ] Check the staged paths for credentials; stage by name, never everything.

**After the first generation — stop and read it**

- [ ] Did rewards land in a plausible spread, or are they suspiciously
      identical?
- [ ] Did the artifact actually change in most rollouts?
- [ ] What did the agents spend their turns on? Count tool calls by target path.
- [ ] What fraction of attempts failed, and did retries recover them?

That last block is the one everybody skips. One generation is a couple of hours
and a few dollars; reading it properly catches several of the failures above
before they compound.
