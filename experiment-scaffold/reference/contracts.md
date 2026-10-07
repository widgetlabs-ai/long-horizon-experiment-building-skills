# Contracts

What a scaffolded experiment must write, what it must never let the box see,
and what every exit code means. These are the parts other things depend on: the
dashboard reads the files, the supervisor reads the codes, and the gate depends
on the boundary.

## 1. Exit codes

| code | means | what the supervisor does |
|---|---|---|
| `0` | it worked | continue |
| `1` | this candidate lost — nothing eligible, or the gate said no | continue to the next generation |
| `2` | the substrate is broken | **stop the run** |

The distinction between 1 and 2 is the whole point. A lost generation is
ordinary. A broken substrate means every further generation would produce
plausible numbers that measure nothing, and the cheapest moment to stop is the
first one.

The code must propagate: scorer → cli → promote → gate → supervisor. A phase
that swallows a 2 and returns 1 turns a broken run into a long quiet one.

## 2. State files

These are the files a dashboard reads and a human audits. Paths are relative to
the experiment's state directory.

| path | written by | holds |
|---|---|---|
| `promotions.jsonl` | `adopt`, **append** | one record per adopted winner: generation, trace id, rewards, gain |
| `gate_report.json` | `gate` | the verdict, the artifact digest it judged, per-sub-problem before/after, exemptions, failures |
| `candidates/<trace-id>/` | the taskset's `finalize` | what came back: the artifact, a status, a small manifest |
| `baseline_<split>.json` | `baseline`, `adopt` | the current high-water mark per split |
| `cache/<key>.json` | `measure` | one measurement, keyed on artifact + instrument + split |
| `instrument.json` | `pin` | the frozen instrument's content hash |
| `pending.json` | `promote`, cleared by `gate`/`adopt` | the staged candidate, and whether the gate passed it |
| `generation` | the supervisor | the next generation number, so numbering continues across runs |
| `ABORT` | anyone | the sentinel; while it exists nothing starts |

**The first three are mandatory.** A viewer-scaffolding skill detects them by
grepping for their write sites, and refuses an experiment that has none. Run
the greps yourself at the end of a scaffold and print the hits:

```bash
grep -rnE "promotions.*\.jsonl" src/ | grep -vE "/tests?/"
grep -rnE "gate.*\.json" src/ | grep -vE "/tests?/"
grep -rnE "candidates" src/ | grep -vE "/tests?/"
```

Beyond compatibility, each earns its place: promotions are the only record of
why the artifact is what it is, the gate report is the only evidence the gate
did anything, and the candidate directory is what survives a rollout the
framework threw away.

### Shape rules for the files

- **A value nobody measured is `null`, never `0`.** On a dashboard and in a
  mean, `0` is a reading. This applies to every figure, not just the reward: a
  sub-problem's score over zero rows, a per-item value for an item that failed,
  a turn count for a trace with no message graph.
- **Append, never rewrite, the promotions log.** The history is the point.
- **Read a `.jsonl` by splitting on `"\n"` only.** `splitlines()` also splits on
  U+2028, which JSON leaves raw inside strings and agent transcripts are full
  of. Note that `json.dumps` escapes it by default — so a test that *writes*
  its fixture with the default will pass even against a broken reader. Write
  such fixtures with `ensure_ascii=False` and assert the raw character is in
  the file.
- **Record what was judged, not just the verdict.** A gate report without the
  artifact's digest cannot be tied back to anything.

## 3. Metrics

Every trace carries, at minimum:

- `reward` — `null` unless a measurement actually happened
- one 0/1 flag per way this search can return zero
- `turns`

The flag list is the one part of an experiment that cannot be copied. Ask the
question explicitly — *name every way this can return zero* — and refuse to
proceed with fewer than three answers. The usual three, under some name:

| flag | means |
|---|---|
| the artifact came back unchanged | the rollout spent its budget on analysis |
| the artifact was rejected before scoring | it did not build, parse, or pass the guard |
| the scorer failed | the measurement itself broke |

Without them, a summary of fifteen rollouts reading `0.000` cannot distinguish a
bad generation from a broken one, and the difference takes log forensics to
recover.

The flags name the ways a run can return zero. They do not name the failures a
reward *ignores* — the examples a candidate can flag wrongly at no cost. A
metric that prices only tagged positives and good negatives credits a rule that
fingerprints "made by the generator" rather than "has the defect": its false
alarms on untagged bad examples cost nothing, so recall rises for free and the
gate can see the change only on the good examples. An ignored class of failures
is a class a candidate can game. At reward design, ask *what class of failures
does this metric ignore?* and refuse a metric whose answer is a non-empty set
the gate cannot see. Record both halves — which failures the reward prices, and
which it ignores and why — in `DESIGN.md`.

## 4. The leak boundary

Three splits, always:

| split | read by | never read by |
|---|---|---|
| train | the reward, candidate ranking, the brief | — |
| val | the gate | the reward, the box |
| test | a human, occasionally | the loop, ever |

**Make it structural, in two halves.** The rollout image's build context must
not contain the held-out splits, and the image must not copy the context
wholesale. Both, not either:

- **Name the filter `.dockerignore`.** A `Dockerfile.dockerignore` is honoured
  *only* by BuildKit; under the legacy builder (`DOCKER_BUILDKIT=0`, or any
  Docker before 23) it is ignored in full and every held-out row enters the
  context, silently. Verified against Docker 29 in both modes.
- **Copy named paths, never `COPY .`.** This half holds under every builder,
  and it is what actually keeps held-out data out of the image if a filter is
  ever not applied.

Verify rather than assert, and print the result. Note the leading dot: a shell
glob like `*.dockerignore` does not match it, so a check written that way
reports "no such file" instead of failing.

```bash
grep -nE "corpus/(val|test)" Dockerfile            # must find nothing
grep -nE "corpus/(val|test)" .dockerignore         # must find both
grep -nE "^COPY \\.( |$)" Dockerfile               # must find nothing
```

Go one step further where you can: have the in-box tool **refuse** a held-out
split with an explanation rather than answer it. An agent that can score itself
on the split it is gated against can optimise against it, and the gate stops
meaning anything.

### Small support

Where a sub-problem has too few held-out items to judge, exempt it
**explicitly, in code, printing the support numbers**. A gate at four items is
a coin flip dressed as a criterion, and the decision to exempt should be
recheckable against the data by anyone reading the output.

### No tolerance for the perfect

A sub-problem already at a perfect score has nothing left to trade, so any drop
is one the candidate introduced. Give it a tolerance of zero while others get a
small one. A few thousandths per generation is how "everything works" decays
into "everything nearly works".

## 5. The brief

The brief is agent-facing code, and it has one mandatory opening: the turn
budget, *land an edit early*, *each edit is a checkpoint*, *scratch space is
discarded*, and exactly which paths come back.

**Keep the returned paths in one constant** that both the brief and `finalize`
use. When the two drift, agents write to a path that is deleted with the
container, every rollout looks healthy, and the only symptom is that nothing
improves. Assert it: every path the brief names is a path `finalize` returns,
and no other.

## 6. The package's two environments

The package is imported by the orchestrator, which needs the eval framework,
and inside the rollout container, which must not. Keep the framework import
behind a lazy accessor, and put the facts both sides need — what comes back,
what is held out — in a module that imports neither.

## 7. The validity check

The reward says how good a candidate is. It cannot say whether the candidate
earned its number. A model handed a fixed split and a scalar to maximise will
eventually stop solving the problem and start solving the measurement, and the
cheaper the model the sooner. The curve keeps rising while it happens, which is
what makes it expensive: nothing in the loop notices.

Every experiment therefore has a check, separate from the reward, that answers
**is this candidate admissible at all**. Three requirements:

1. **Separate from the reward.** It returns pass or named violations, never a
   number, and is never folded into the score.
2. **Runnable in the box**, through the in-box tool the agent already has. A
   rail the agent cannot see costs it turns and teaches it nothing.
3. **Enforced on the host, against the returned artifact.** The agent running
   it is a convenience. The loop running it is the rail.

**The check is frozen instrument, and that is structural.** Tests that live
where the agent can edit them are not a constraint; they are another file to
optimise. A model that cannot make the suite pass will make the suite pass. So
the check sits **outside the editable area** exactly as the scorer does, is
added to the instrument pin so a cached score cannot outlive a change to it,
and is re-run host-side against what the rollout returned, from the host's
copy.

| on failure | |
|---|---|
| reward | `null`. Refused before scoring means never measured, and `0` is a lie the curve cannot tell apart from a bad candidate |
| metric | a named entry in `ZERO_REASONS` |
| exit | ordinary — the candidate is ineligible and the run continues. Never exit 2: a bad candidate is not a broken substrate |

**When the artifact is code**, the check is its test suite, and three things
follow. The suite ships in the image outside the editable path. The brief names
it and says it is enforced whatever the candidate scores. And the host re-runs
it against the returned code before scoring — if the in-box and host runs can
diverge, only the host's counts.

**Prefer behavioural invariants to structural ones.** A check that reads the
artifact's shape — "no literal longer than N", "no rule after line 40" — is
evaded by restructuring, and constrains how honest candidates are written. A
check that asks what the artifact *does* cannot be. The worked example's is
`robust_to_perturbation`: every row the candidate gets right must stay right
under a rewrite that provably preserves its label. A rule keyed to one training
string fails under a rewrite that changes a part it copied — in the example,
the filler word. Know which rewrites your artifact's matching style already
absorbs (a table that lower-cases its input is untouched by an upper-cased
copy) and make sure at least one rewrite changes what a memorising rule would
have to copy.

**Check and score fresh instances.** If one loaded artifact serves every pass
of the check and then the scoring, an artifact can count its calls, behave for
as long as the check is asking, and cheat once scoring starts. Load it afresh
for each pass and again to score, and ask the determinism question twice of one
instance, so state kept between calls is still caught.

**Fresh means the loads share no object.** Anything two loads can both reach
and write to is a counter that survives the reload: in the example, an
attribute set on the `re.search` handed to every load let a table count loads
and cheat on the scoring one. Build whatever you hand the artifact anew per
load, and make it refuse attributes. Only then does the number belong to the
artifact the check saw — and it still rests on the artifact reaching nothing
shared, which only holds as far as the guard does.

**A static guard is an audited denylist, not a sandbox.** Audit it against the
routes you know and say that is what it is; do not call it complete. The
example's guard refused every dunder `ast.Attribute` and was still walked
through by `match` class patterns, which look attributes up with no attribute
node. Refuse by node type any construct the artifact has no use for, rather
than trying to police everything it could do. And know where the code actually
runs: the check and the scoring execute the candidate on the host, so on the
host the containment boundary is the scoring process. For anything beyond a
worked example, score inside the rollout image or an isolated, no-network
container.

**A load that fails is the candidate's failure.** Every pass loading its own
instance is every pass able to fail to load. Catch it wherever it happens —
the check names it as a violation of its own, the scoring load reports an
unmeasured candidate — or one candidate exits 2 and stops the run.

**Derive perturbations from whatever generated the data**, never by inspection.
A rewrite invented by looking at examples is a guess about what preserves the
label, and the obvious guess is usually wrong. See
`examples/synthetic_search/src/synthetic_search/substrate/corpus.py`,
`perturbations`, for the reason in full.

## 8. The reviewer

An optional stage, after the gate and before adoption, that asks a stronger
model whether the promoted candidate **earned** its score. The validity check
(§7) refuses what can be written down in advance; the reviewer is for what
cannot.

```
eval → post-generation → promote → gate → review → adopt → commit
```

**After the gate**, because the gate is local, deterministic and costs
milliseconds, and the reviewer is a paid network call. Pay only for candidates
that already survived the cheap refusal.

**Veto-only, and that is the whole safety argument.** It can refuse an
adoption. It can never cause one, and it never touches a reward, so the reward
stays deterministic and the curve keeps meaning what it meant. Never feed its
verdict into a reward, and never feed its findings into the next brief: the
first makes the curve non-deterministic, the second makes rollouts across
generations incomparable.

**A refusal discards the candidate**, exactly as a failed gate does. A refused
candidate left in `pending.json` with `gate_passed: true` is one a hand-run
`adopt` would adopt the next morning. **So does a failed or absent reviewer**:
an unreachable endpoint, an unset key, a missing rubric, or any exception once
the pending record has been read. Only a pass leaves the candidate for `adopt`;
a reviewer that never answered has not approved anything.

**The rubric must not restate the reward.** A concern that says "check the
score improved" asks a model to re-derive a number the scorer already has
exactly. Every concern names a way to beat the reward that the reward cannot
see — and that §7's check does not already refuse.

**Keeping a veto accountable.** A reviewer that refuses spuriously kills a
search silently, because a lost generation is an outcome the loop is built to
tolerate. So:

| outcome | the loop does |
|---|---|
| refusal citing a rubric concern, quoting at least 8 characters from the diff's changed lines | refuses — exit 1. A removed line counts: deleting a guard can be the cheat |
| refusal that cites an unknown id, quotes nothing, quotes too little, or quotes a header or unchanged context | **passes**, and records why |
| a reply holding several decision objects | any cited refusal among them is the verdict — an echoed pass planted in the diff must not override it |
| a well-formed completion whose *text* cannot be read as a verdict | **passes**, and records why — the reviewer spoke and caught nothing. Content given as a list of text parts is joined and read first |
| a response whose *envelope* cannot be read — not JSON, no completion in it, `content: null`, an error page | **absence**: retried, then **stops the run** — exit 2. Treating it as a pass would make a misconfigured endpoint approve every candidate |
| no response at all, after retries | **stops the run** — exit 2. The instrument is absent |
| `max_consecutive_vetoes` refusals in a row | **stops the run** — exit 2. A stuck search and a broken reviewer look identical from inside. Reset `state/review_streak` before restarting, or the first refusal stops it again |
| a rubric with no concern headings | **stops the run** — nothing could ever be cited |

**Its own config file**, `review.toml`, not a block in the eval config: the
eval framework parses that file, and the reviewer's provider is independent of
the rollouts'. An unknown key in `[review]` stops the run, because `enable =
true` silently leaving review off is exactly a silent failure. So does a value
of the wrong type: `enabled = "false"` is a truthy string.

**Two test seams.** `SYNTH_FAKE_REVIEW` swaps the transport and runs the real
parse, record, streak and discard. `SYNTH_FAKE_REVIEW_EXIT` fakes the stage's
exit code in the supervisor, which is what a branch test needs. No test makes a
real model call.
