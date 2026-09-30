# synthetic_search — design

This document is also an **example of the output** `experiment-scaffold`
produces at its mid-point checkpoint: the decisions, written down and confirmed
before any code existed. A reader a month later should be able to answer "why
is it like this" from here alone.

## Goal

Maximise macro-F1 of a rule table over a generated corpus, by letting an agent
edit the table and keeping only the edits that survive a held-out check.

Family **A** (artifact over a corpus), per `../../FIELD-GUIDE.md`.

## The four questions

| question | answer |
|---|---|
| Is there an artifact that survives the rollout and serializes out of a container? | Yes: `artifact/rules.py`, one file, returned by `finalize`. |
| Is there a scorer that runs on the host, deterministically, in seconds when cached? | Yes. Measured: **7.0 ms cold, 0.38 ms cached** over 1,200 train rows. |
| Is there a held-out slice with meaning? | Yes: val gates, test is never read by the loop. |
| Can a winner be adopted, so the next generation starts from it? | Yes: `adopt` rewrites the table and both baselines; the supervisor commits. |

## The spike

Before any of the loop was written, one artifact was scored end to end, twice,
and the two runs were diffed.

| measurement | value |
|---|---|
| corpus | 2,000 rows → 1,200 train / 400 val / 400 test |
| baseline macro-F1 (train) | 0.74772925 |
| cold measurement | 7.0 ms |
| cached measurement | 0.38 ms |
| ratio | ~19× |
| two cold runs agree | exactly, to all nine quantized places |

The ratio is what decides whether the loop is usable: the agent scores dozens
of times per rollout, and a scorer that takes minutes turns every rollout into
a waiting game. Had the cached path not been fast, the right move would have
been to fix that before writing a single line of the outer loop.

## Editable artifact and frozen instrument

**Editable:** `artifact/rules.py`, and nothing else. `ARTIFACT_PATHS` in
`taskset_contract.py` is the single definition; `finalize` returns exactly
those paths and `brief.md` renders its promises from the same constant, so the
two cannot drift into telling an agent to write somewhere that is discarded.

**Frozen:** `scorer.py`, `measure.py`, `artifact.py`, `corpus.py`, `validity.py`, pinned by
content hash in `state/instrument.json`. `score`, `baseline`, `promote`, `gate`
and preflight all refuse on a mismatch. Changing the instrument is deliberate:
re-pin, re-baseline.

**The guard** is part of the instrument, not a nicety. A table that can `open`
a file can read the labels it is graded against, score 1.0, and teach nothing —
and the number is indistinguishable from a real result. `check_source` walks the
AST before the source is executed and refuses:

- imports, and the names `open`, `eval`, `exec`, `compile`, `__import__` and
  their kin;
- dunder attribute access;
- the attributes that reach an execution frame (`gi_frame`, `cr_frame`,
  `ag_frame`, `tb_frame`, `tb_next`, `f_back`, `f_globals`, `f_locals`,
  `f_builtins`): a running generator's `gi_frame.f_back.f_globals` is the
  caller's module globals, and through the real call path that reached `open`;
- `format` and `format_map` (use an f-string), because a format string walks
  attributes the guard cannot see, and the caller's name alone tells scoring
  from validity;
- `mro`, because `re.error.mro()[-1]` is `object`;
- whole constructs no rule table needs: `match`, `yield`, `yield from`,
  `global`, `nonlocal`, `class`, and async code. A class pattern's keywords
  (`case O(__call__=c)`) look attributes up with no `ast.Attribute` node, so
  every attribute check above missed them: they walked `re.search` to a real
  `__import__`, and to the `re` module's globals — a writable dict every load
  shares, which restored the load-counting cheat at reward 1.0. Generator
  functions supply the frame a walk starts from; comprehensions and generator
  expressions stay allowed, since they cannot be named inside themselves.
  Class-pattern keywords are also run through the attribute checks, in case
  `match` is ever allowed back.

**This is an audited denylist, not a sandbox.** It is audited against the routes
listed here, and it is not complete: Python has more ways to look an attribute
up than an AST walk can enumerate, and the `match` route survived two reviews.
Nor does it contain anything. In the rollout the container does. **On the host,
the candidate runs in-process** in whatever measures it: the scoring subprocess
`taskset` starts, or `promote`, `gate`, `adopt` and `review` in the supervisor's
own process. On the host, then, the containment boundary is that process, with
its user's files and network. That is a known limit of this example. Anything
beyond it should score where an escape gains nothing: inside the rollout image,
or in an isolated container with no network and no held-out splits.

`Pattern.sub` with a backreference template (`P.sub(r"<\1>", text)`) raises
`KeyError('__import__')` under the restricted builtins, because CPython's `_sre`
imports `re` lazily to expand it. Use `re.sub(pattern, template, text)`, which
works through the stand-in.

## The validity check

The reward says how good a candidate is. It cannot say whether the candidate
earned its number. `substrate/validity.py` asks that, on the **train** split,
inside `measure_source` and before any scoring, and a candidate that fails is
never scored: `reward` stays `None` and the report carries `validity_failed`
and the violations. Four invariants:

| invariant | holds when |
|---|---|
| `labels_in_vocabulary` | every answer is a category or `unknown`; a label that is not a string is a violation |
| `deterministic` | the same text gives the same answer twice, on an instance the first pass never touched |
| `robust_to_perturbation` | a row the table gets right is still right after a label-preserving rewrite |
| `bounded_time` | the whole check, all passes together, finishes inside 5 seconds |

A pass whose own load fails is reported as `load_stable`, naming the pass, and
ends the check. It is not a fifth invariant but the check being unable to ask:
letting the `CandidateError` out would have exited 2 and stopped the search
over one candidate. A table that passes every pass and then fails the scoring
load is `guard_rejected`, the flag every other refused load already sets.

**Behavioural, not structural.** None of them reads the table's source, so none
can be evaded by restructuring it and none dictates how a candidate is
written. `robust_to_perturbation` is the one that earns its place: a rule keyed
to an exact training string dies under a rewrite the grammar guarantees keeps
the label, and an inlined copy of that rule dies the same way. A deliberately
memorising table was caught: 40 rules, each memorising one training row
exactly, and the perturbation broke 36 of those 40 rules. One violation is
enough, so the table as a whole was refused. The shipped artifact passes all
four. Those two figures, and the 111 of 176 below, were measured at planning
time on 300 rows from `corpus.generate(seed=7, n=300)`, not on the staged
corpus. Separately, on the 1,225 train rows of a default staging the check
takes about 0.017 s (five runs of my own after the determinism pass began asking
each row twice, not a benchmark), and the 5 s budget is set several hundred
times above that on purpose: it catches a table that is slow but finishes. A
table that never finishes cannot be caught by the check, because Python cannot
interrupt a running regex in-process. Only rollout scoring bounds that case,
through the host's scoring subprocess timeout, `taskset.SCORE_TIMEOUT`.
`promote`, `gate`, `adopt`, `review` and `rt` measure in-process with no
timeout, so such a table hangs them rather than failing. The budget is a
constant, not an environment variable.

**Every pass gets a fresh table, and so does scoring.** `validity.check` takes a
loader, not a `classify`, and calls it once per pass; `measure_source` then
loads the table once more to score it. One shared instance let a table count
its calls in a module-level list, answer honestly for the 2×N calls the first
two passes made, and answer from a memorised copy of the split once scoring
began: validity passed, train reward went to 1.0, and `promote` staged it. The
determinism pass asks each row twice of its own instance, so a table whose
answer depends on having been asked before is still caught.

**Fresh loads are only fresh if the loads share nothing.** Each load executes
the source into a new namespace dict with a new `__builtins__` dict, and
`artifact.regex_namespace()` builds a new `re` stand-in per load: functions
wrapped in slotted callables that accept no attribute, flags as plain `int`s,
and a new `error` class that the wrappers re-raise into. Before that the shim
handed every load the same real `re.search`, and a function takes attributes:
`re.search.loads += 1` counted loads, and a table that memorised the split on
the fifth (the scoring load on train) passed validity and scored 1.0. With
nothing shared, the scored instance starts from the state the first validity
pass started from, and the number belongs to the table the check saw.

That rests on one assumption the code cannot prove: **a candidate reaches no
object shared between loads.** It holds as far as the guard does, and the guard
is a denylist. What a load hands over was audited: the builtins are immutable
types and builtin functions, which take no attributes; compiled patterns are
cached and shared by `re`, but a `Pattern` takes no attributes, and its
`groupindex` is a read-only view or, with no named groups, a new dict on each
access; the routes back into the caller or into `re`'s own globals — frame
attributes, format-string walks, class-pattern keywords, `mro` — are refused.
Audited against those routes, not proven complete. A new builtin, a new `re`
export, a newly allowed construct, or a language feature that looks attributes
up without an `ast.Attribute` node has to be checked against it before it is
added.

**The perturbations live in `corpus.py`**, as `perturbations(text, label)`,
because only the module that owns the grammar can make a rewrite label-preserving
by construction. The first version was written by hand in `validity.py`
(insert a neutral token after the first word) and it failed the shipped
artifact on 111 of 176 correct rows: `good morning ...` became
`good really morning ...`, which no longer means what it did. A perturbation
invented outside the grammar is a guess. Three rewrites are offered:
`trailing_punct`, `upper`, and `noise_swap`, which replaces the row's filler
word using the row's opener and body as the grammar decomposes them. A row the
grammar can no longer account for still gets the first two, so a grammar edit
degrades the check rather than silently disabling it.

**Be exact about what each catches.** Only `noise_swap` breaks a sentence
copied verbatim into a rule. This example's table lowercases its input and
matches unanchored, so `upper` and a trailing full stop do not break such a
rule; they are there for tables that do not normalise. Rows the candidate
cannot classify at all are skipped, not reported: the scorer already names
that `score_error`, and one defect under two names cannot be counted.

**`validity.py` joined the instrument pin.** The check decides which candidates
get a number at all, so an edit to it changes what a number means exactly as an
edit to the scorer does. It also runs inside the box (`rt check`), so an agent
can ask the same question the host will, without scoring.

## Corpus and splits

Generated from a seed: no network, no credentials, nothing to lose, and a
corpus that is byte-identical on every machine.

Splits are 3:1:1 **within every category**, assigned by a hash of `(seed,
row_id)`, so re-staging never moves a row and no category lands entirely in one
split. A category the val split never saw is a category the gate cannot judge.

| split | share | purpose |
|---|---|---|
| train | 3/5 | reward, candidate ranking, the brief |
| val | 1/5 | the gate, and nothing else |
| test | 1/5 | canary; never read by the loop |

**The leak boundary is the build context.** `Dockerfile.dockerignore` excludes
`state/corpus/val`, `state/corpus/test` and `baseline_val.json`, so the rollout
image structurally cannot carry them — Docker cannot read outside its context.
`rt score --split val` inside the box is refused with an explanation rather
than answered. A gate on a split the box could optimise against is decoration.

## Reward

`measure_source(source, split, state)` is the only path to a number. The
reward is the whole-train macro-F1; the box's own score is steering.

`reward` is `None` unless a measurement actually happened, and every way of not
happening is a named metric:

| metric | means |
|---|---|
| `artifact_unchanged` | the agent returned the table it was given |
| `guard_rejected` | the table reached outside the text it was handed |
| `score_error` | the scorer could not produce a number |
| `validity_failed` | the table broke an invariant the reward cannot see |

Without that list, a summary of fifteen rollouts reading `0.000` cannot
distinguish a bad generation from a broken one.

## Promotion, gate, adoption

- **promote** ranks on **train** — the split the rewards already used. Selecting
  on val would spend the only split that can still say no. A candidate is
  eligible when it parsed, changed the table, beat the baseline mean, and took
  no category down by more than its tolerance.
- **tolerance** is `CATEGORY_TOLERANCE` (0.002), or **zero** for a category
  whose baseline is exactly 1.0. A perfect category has no defects left to
  trade, so any drop is one the candidate introduced; allowing a few
  thousandths per generation is how "every category works" decays into "every
  category nearly works".
- **gate** rescores the staged table on val, per category, and discards it on
  failure — re-gating could only fail again. A category with fewer than
  `MIN_GATE_SUPPORT` rows is **exempt**, and the exemption prints its support,
  because a gate at that support is a coin flip dressed as a criterion.
- **adopt** runs only on a table the gate passed: it replaces the artifact,
  rewrites both baselines from that same measurement, and appends to
  `promotions.jsonl`.

A lost generation leaves the artifact untouched and the run continues. Exit
codes: 0 ok, 1 this candidate lost, 2 the substrate is broken — stop.

## The reviewer

`substrate/review.py`, run as `cli review`, sits **after the gate and before
adoption**. Earlier, it would spend a model call on candidates that were going
to lose anyway; later, the artifact would already have changed. At this point
the candidate is the best eligible one, it has passed val, and the only thing
left to decide is whether to adopt it. The reviewer is shown the diff between
the adopted table and the candidate, the brief, the rubric (`review.md`, four
concerns) and the score report, and is asked whether the change earned its score.

**Veto-only.** It can refuse an adoption; it can never cause one, and it never
touches a reward. The reward stays deterministic, so the same candidate scored
twice gives the same number and the curve keeps its meaning. The one
non-deterministic stage in the loop is confined to subtracting candidates. A
refusal discards the pending candidate, and the generation is lost like any
other.

A reviewer that refuses spuriously would kill a search silently, because a lost
generation is something the loop is built to tolerate. So a refusal has to be
accountable:

| the response | outcome |
|---|---|
| a refusal citing a rubric concern and quoting the diff | the candidate is discarded |
| a refusal whose concern is not in the rubric, or with no quote | recorded, and it **passes** |
| a quote under 8 non-space characters, or not found in the diff's changed lines | recorded, and it **passes** |
| a reply holding several decision objects | any one that is a cited refusal is the verdict, so an echoed `{"decision": "pass"}` cannot override it; the count is recorded |
| a completion that is text but holds no readable verdict, or is neither text nor a list of text parts | recorded, and it **passes** |
| an envelope that is not JSON, holds no completion, has `content: null`, or is an error page | absence: retried 3 times, then the run stops (exit 2) |
| a 4xx other than 429 | the run stops at once, naming the model and key (exit 2) |
| `max_consecutive_vetoes` refusals in a row | the run stops (exit 2) |

The rule behind the table: **nonsense passes; silence stops.** A response that
arrives and cannot be read is the reviewer speaking and catching nothing. No
response at all means the instrument is absent, and nothing is measured with an
absent instrument. A quote counts only against the diff's *changed* lines, so
copying a context line cannot make a refusal look grounded; a removed line does
count, because deleting a guard can be the cheat. A stuck search and a broken
reviewer look identical from inside the loop, which is what the streak limit is
for. Every verdict is appended to `state/reviews.jsonl`. After a runaway stop,
delete `state/review_streak` (or set it to 0) before restarting, or the first
refusal of the new run stops it again.

**Its own `review.toml`**, not a block in `config.*.toml`. The eval framework
parses those files and both must stay identical apart from three fields, and
the reviewer's provider is independent of the rollouts'. **It ships disabled**:
enabling it costs a model call for every generation whose candidate passes the
gate, and an example that spent money on a first run would be the wrong
default. A missing file or table is also a disabled reviewer. `cli review
--check` asks, with no call, whether an enabled reviewer could run — key set,
rubric naming a concern, an http(s) `base_url` — and the preflight runs it, so
a misconfigured reviewer stops the run before generation 0 rather than after it.

## The verification layer

| item | where |
|---|---|
| preflight | `run.sh --check` — provider, abort, corpus, selftest, reviewer config (`cli review --check`, no call), image, one live model call |
| selftest | `selftest.run` — determinism, quantization, cache agreement, taxonomy, baselines |
| post-generation | `cli post-generation` — every rollout's reward, gain, turns and verdict |
| metrics that disambiguate a zero | `evaluate.ZERO_REASONS` |
| abort sentinel | `state/ABORT`; preflight, taskset and supervisor all refuse while it exists |
| exit codes | `errors.py`, propagated cli → promote → gate → supervisor |

## What a reader should not copy blindly

The categories, the tolerance and the split shares are this corpus's. The list
of zero-reasons is this search's. Everything else — the exit-code contract, the
supervisor's error branches, the provider resolution, the state layout — is
pattern, and copying it is the point.
