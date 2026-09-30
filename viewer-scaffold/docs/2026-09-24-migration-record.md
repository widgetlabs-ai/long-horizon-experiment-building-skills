# Migrating viewer-scaffold's tests off the private experiment

`viewer-scaffold` used to prove itself against a private experiment that
belongs to the company hosting this skill. That is no longer true, because
`skills/` (this directory's grandparent) is being published as a standalone
public repository, and a public repository cannot have a test suite that only
runs against data nobody outside the company can see. This record explains
what changed, why, and what the result does and does not still prove. It
assumes no prior knowledge of that private experiment.

## The three harnesses this skill used to run, and which of them worked in a
## fresh clone

Before this migration, "test the skill" meant three things:

1. **`python3 -m unittest discover`** — unit tests for `shape_diff.py` (the
   JSON-shape comparator) and `touch_fixtures.py` (the fixture-mtime helper),
   both exercised against small literal examples built inline in the test
   files. This is the only one of the three that ever ran in a fresh clone:
   it needs no experiment, private or otherwise.

2. **`fixtures_vs_real.py`** — generated synthetic fixtures (B) with a mock
   agent and mock container, and diffed their shape against the private
   experiment's actual `state/` and `outputs/` directories: real files
   written by a real run of that experiment, on the one machine that had run
   it and kept that state around.

3. **`endpoint_diff.py`** — assembled a viewer from `viewer-scaffold`'s own
   template and a mapping written for the private experiment, ran it side by
   side with that experiment's hand-written viewer (built before
   `viewer-scaffold` existed, by someone who had never seen the template),
   and diffed every API endpoint between the two. This needed synced Python
   environments inside the private experiment's own repository and inside its
   viewer, plus a populated `state/` directory — again, only reproducible on
   a machine with access to that private repository and its data.

So two of the three — `fixtures_vs_real.py` and `endpoint_diff.py` — proved
things only on one machine, against one private experiment, using data no
clone of this repository could ever see. A public repository inherits none
of that: the private experiment does not travel with it, so both harnesses
would fail on `git clone` with no experiment to point at, for reasons that
have nothing to do with whether the skill works.

## What replaced each of them

**The generic unit tests (harness 1) needed no change.** They never depended
on the private experiment and still don't.

**`fixtures_vs_real.py` was re-pointed, not retired.** It now diffs B
(`test/synthetic_generator.py`) against R
(`examples/synthetic_search/tools/reference_run.py`), the public worked
example's own reference run, instead of against the private experiment's real
`state/`/`outputs/`. Both sides of this comparison ship inside the public
repository, so the check runs in any clone. See "the seam" below for what R
actually exercises.

**`endpoint_diff.py` could not be re-pointed, so it was moved rather than
ported.** Its entire value came from comparing the template's output against
a viewer that was designed *independently* of the template — the private
experiment's hand-written viewer predates `viewer-scaffold` and was built by
someone who had not seen it. That independence is what makes a passing diff
meaningful: it is evidence the generic template reproduces a viewer someone
built without reference to it, not one shaped to match the template's own
assumptions.

`synthetic_search`, the skill's public worked example, has no such viewer.
Nothing about it predates `viewer-scaffold` — it was built alongside the
skill, from the same spine document, by the same effort that wrote the
template. Writing a "hand-written" viewer for it now, after the fact, would
be circular: that viewer would inevitably be derived from the same
assumptions already baked into the template, and a passing diff against it
would prove nothing about whether the template generalizes to a design it
didn't shape. There is no way to manufacture the missing independence, so the
check could not be recreated for the public example.

Rather than delete evidence that still means something, `endpoint_diff.py`
and its supporting files moved wholesale to a sibling directory
(`long-horizon/viewer-conformance/`) that stays outside `skills/` and is
never published. It still runs, still needs the private experiment's synced
environments and real state exactly as before, and still requires someone
with access to run it. It is preserved unpublished, not retired and not
recreated — see that directory's own README for how it finds this skill by
relative path and what running it requires.

**Its place in the public suite was taken by a fourth harness that didn't
exist before: the golden snapshot (`test_golden_endpoints.py`).** It
generates a viewer from the template against `examples/synthetic_search`'s
fixtures and pins the resulting endpoint JSON to a checked-in golden file
(`test/golden/synthetic_endpoints.json`), failing if the two ever diverge.

**Read this for what it is, not for what the moved harness was.** The golden
snapshot's source of truth is the template itself — the golden file is
generated *from* the template's own output. That means it catches the
template *changing* (a future edit that silently alters what a generated
viewer serves), which is real and useful. It cannot catch the template
*baking in a wrong assumption from day one*, because there is no independent
second opinion in this comparison the way the private experiment's
hand-written viewer was one. Anyone regenerating this golden file to make a
red test green should stop and read why it changed first — regenerating to
absorb an unexplained diff is how a drift guard quietly becomes decoration.
In this migration it changed exactly once, when the scrub below added an
accurate metric name ("macro-F1") to a note string that had previously said
nothing more specific than "re-scoring" — a deliberate content change, not
drift, and the regenerated golden file reflects it.

## Where the seam sits in the reference run, and why it is tighter than what
## it replaced

"The seam" means: of everything a full generation touches, which piece is
faked, and which pieces are the experiment's own real code.

The old comparison (the moved harness against the private experiment's real
`state/`/`outputs/`) had, in one sense, *no* seam at all — the reference side
was a real run: real agent, real container, real everything. That sounds
stronger than what replaced it, but it bought that strength at the price of
being unreproducible: nobody could tell you exactly what the reference proved
without also having a copy of the private experiment and its logs, because
the "real run" was whatever that one run happened to be.

The new reference, `tools/reference_run.py`, is explicit about its seam and
draws it in exactly two places:

- the **AGENT** is replaced by `mutate()`, a scripted edit to the rule table
  standing in for what a rollout would do; and
- the **CONTAINER** is replaced by `StubRuntime`, a local-directory substitute
  for the sandbox a real rollout runs inside.

Everything else — the CLI subcommands, `measure.measure_source`, `promote`,
`regression_gate`, `adopt` — runs for real, on real writers, because
`synthetic_search`'s scorer is pure Python and needs neither a live model nor
a container to execute. `test/synthetic_generator.py` (B) draws its seam at
the same two places, deliberately, so the comparison between B and R is
between two runs that share an identical, named, two-line boundary rather
than between "a mock" and "an opaque real system nobody outside one machine
could reproduce." That is what makes the new seam tighter: not that less is
faked in absolute terms, but that exactly what is faked is written down,
shared by both sides of the diff, and checkable by anyone who clones the
repository — `examples/synthetic_search/tests/test_reference_run.py` is the
test that the reference run's seam does what its docstring claims, and it
runs alongside the rest of the public example's suite.

## The build records

The two design/plan documents that describe how the moved harness was
originally built moved together with it, unrewritten. They describe that
harness at the location and in the vocabulary it had when it was built inside
`skills/viewer-scaffold/docs/`, against the private experiment, before any of
this migration happened. They are not edited to describe their new location
or the experiment this migration introduced, because a record edited after
the fact to describe events other than the ones it was written during stops
being a record of anything — it becomes a fiction wearing the original's
date. Read them as history, not as current documentation of that directory.
