---
name: viewer-scaffold
description: Use when an experiment under long-horizon/ needs a dashboard — "build a viewer for <experiment>", "I want to watch this search", or when a new long-horizon experiment is set up. Generates a committed, live, read-only viewer for one experiment by writing its mapping onto a shared skeleton. Works from the experiment's code before its first run; refuses experiments whose code writes no promotions, gate or candidates.
---

# viewer-scaffold

Generate a viewer for one long-horizon experiment: a small FastAPI app, committed
into that experiment's directory, that renders its search live while it runs and
its record afterwards.

**Announce at start:** "I'm using the viewer-scaffold skill to generate a viewer
for `<experiment>`."

This skill runs at **build time only**. Nothing it produces puts a model in the
loop of a running search: the output is an ordinary server you read, test and fix
by hand.

## What you are given and what you produce

Input: an experiment root, e.g. `long-horizon/<experiment>/`, and **only its
code**: `src/**`, `supervisor.sh`, `README.md`, `DESIGN.md`, `pyproject.toml`,
`uv.lock`, and its environment after `uv sync`. It has typically never run.
**Do not open `state/` or `outputs/`**, even if they exist: the viewer must not
depend on whether anything has run.

Output: `<experiment>/viewer/` — the skeleton copied from `template/`, plus the
files you write: **`experiment.py`**, **`fixtures/state/`, `fixtures/outputs/`**
(A), **`fixtures/SOURCES.md`**, **`fixtures/mtimes.json`**, and `OMISSIONS.md`. Scratch (the B generator and
its output) stays in your scratchpad.

## Non-negotiables

1. **You write code, never values.** Every number the dashboard shows must be
   read from a file at request time. Never type a measured figure into
   `experiment.py` — not a reward, not a category count, not a tolerance, not "the
   current baseline", and not in a sentence either ("3 rollouts per task"). A transcribed number renders exactly like a measured one
   and cannot be caught by looking at the page. `check_literals.py` enforces
   this and a run that fails it is not finished.
2. **In the skeleton, you edit `experiment.py` and nothing else.** `app.py`, `lib.py` and
   `static/index.html` are the skeleton and are identical in every generated
   viewer. If you believe the skeleton needs a change, stop and say so — do not
   fork it silently into one experiment.
3. **Never invent a concept the experiment does not have.** If there is no gate,
   there is no gate — do not derive one from promotion deltas. A section with no
   source renders empty; that is correct and intended.
4. **Read-only.** The viewer never runs eval, promote, gate or adopt, and writes
   nothing.

## Procedure

The person who invoked you may know nothing beyond "I want a viewer". Guide
them. Ask only what you cannot find out yourself, and settle everything else
without asking. There are exactly two stops: the question in step 0, when the
experiment is not named, and the checkpoint at the end of step 2.

### 0. Start

1. **The experiment.** If the request names one, use it. Otherwise list the
   directories under `long-horizon/` that contain `src/`. Mark the ones that
   already have a `viewer/`. Ask which one, as a single question with those
   directories as the options. Ask nothing else here.
2. **Prerequisites.** Check them yourself:
   - `python3 --version` is 3.12 or newer;
   - `uv --version` works;
   - the experiment root syncs, **with its eval framework installed**.

   A bare `uv sync` is not always that sync, and where it is not it actively
   removes what step 1 needs: an experiment whose orchestrator is an optional
   dependency gets it uninstalled by a sync that does not name it, and step 1
   then finds no serializer to read in `.venv`. So read `pyproject.toml` first
   and sync according to where the framework is declared — a plain
   `dependencies` entry, a `[project.optional-dependencies]` group
   (`--extra <name>`), or a `[dependency-groups]` entry (`--group <name>`).
   Then confirm it by looking, not by the sync's output: the framework's
   package must be there under `.venv/lib/python*/site-packages/`.

   If one fails, tell the person what is missing and the exact command that
   fixes it, then stop. Do not work around a missing prerequisite.
3. **An existing viewer.** If `<experiment>/viewer/` exists, say so and stop,
   unless the request was to update it (see "Updating a viewer later") or to
   regenerate it because the experiment's writers changed (see "Regenerating a
   viewer"). Never overwrite it otherwise.
4. **Scratch and ports.** Use the harness's scratchpad directory if it gives
   you one, otherwise `mktemp -d`. That is `<scratch>` below. Pick two free
   ports for step 7: try to bind them, do not guess. Do not ask about either.

Then announce the skill as above, naming the experiment.

### 1. Read the code

- `README.md` and `DESIGN.md` — the vocabulary and what the reward means
- `src/**` — the CLI subcommands name the phases; the writers name the artifacts
- `supervisor.sh` — the generation loop
- `pyproject.toml` / `uv.lock` — the eval framework; run `uv sync` and read its
  serializer in `.venv`. If the environment does not install, refuse.

You are answering six questions: what is a run, what is a rollout, what is the
number being maximised, what does a promotion record look like, what does the
gate write, and what does a candidate leave behind.

### 2. Writer map and membership test

Follow `reference/writer-map.md`: find every write site, follow each field to
the line that creates it, and build the map. The membership test is on write
sites: the code must write promotions, a gate report and candidates. If any
of the three is missing, **refuse**. Reviews are **not** required: making them
so would refuse every experiment that does not want a reviewer, so `reviews()`
stays optional. Print the greps and their hits. There is no
force flag. The skill serves experiments built to
`long-horizon/Long-Horizon-Search-Field-Guide.md`, and nothing else.

**Checkpoint.** Before writing any code, show the person a short summary in
plain words, not the full map:
- for each section of the page (runs, rollouts, promotions, gate,
  candidates, extras, and reviews when the experiment has a reviewer stage;
  otherwise delete the `reviews()` stub), the file that feeds it;
- what the viewer will not show, and why;
- any choice of meaning you had to make, e.g. which of two numbers is "the
  reward".

Ask whether that is right, and wait. The person may know something the code
does not tell you, e.g. that a file is obsolete or a field is misnamed. Take
corrections into the map. Past this point, do not stop again until step 8.

### 3. Write `experiment.py`

Copy `template/` to `<experiment>/viewer/`, then fill in `experiment.py` against
`reference/spine.md`, which gives the field-by-field contract. Keep every
function reading from disk on each call — no caching, no module-level data.

Anything the experiment measures that the spine has no word for goes through
`extras()` as self-describing blocks. That is the pressure valve: a new
measurement is a change in `experiment.py` and nowhere else. Domain prose that
explains a block belongs in that block's `note`, never in the HTML.

Write `notes()` too: the legend for each spine section — what the reward is,
what each verdict and stop reason means, what a run consists of. Take the
wording from `README.md` and `DESIGN.md`. The page has no prose of its own, so a
viewer without notes shows numbers nobody can read a month later. **No
measured figures in note text**: read any figure a note needs at call time
and interpolate it. A metric's name (`macro-F1`) is not a figure and may be
typed in directly (see `reference/spine.md`, "notes").


Write it against the map, not against sample data. There is none.

### 4. Write A: the hand fixtures

In `<experiment>/viewer/fixtures/`, write a small `state/` and `outputs/` as the
map says the code would write them. Include two or three generations, a failed
gate, and a candidate in every verdict the host can produce, plus one with no
report. `fixtures/SOURCES.md` is the map's table plus one line per fixture file
saying which path it stands for. These are committed.

If the experiment has a reviewer stage, the fixtures must include
`state/reviews.jsonl`: at least a pass, a refusal that cites something (a
`concern` and a `quote`), and a pass that downgraded a refusal the reviewer
could not account for (a record with a `note`). An experiment with no reviewer
stage writes no such file, so write none.

Write `fixtures/mtimes.json` too: one distinct time for every file or directory
whose mtime `experiment.py` sorts by, i.e. each run dir and each candidate's
writer file, in the order the story happened. The format is in
`touch_fixtures.py`. Git does not store mtimes, so without this file the
fixtures of a fresh clone come back in whatever order the file system lists
them, and which run counts as the newest is left to chance.

### 5. Write and run B

Follow `reference/generator.md`: a script in your scratchpad that runs the
experiment's real writers with only the measuring layer mocked.

```bash
<experiment>/.venv/bin/python <scratch>/generate_b.py --out <scratch>/b
```

### 6. Compare A with B

```bash
python3 <skill>/scripts/shape_diff.py <experiment>/viewer/fixtures <scratch>/b --rules <scratch>/rules.txt
```

The rules file (format in the docstring of `shape_diff.py`) needs two kinds of
line:
- **`map <file> <path>`** for every object whose keys are data, not schema:
  category names, class names, trace ids. That includes the same maps nested
  inside a trace, e.g. `traces[].info.<signals>.per_category`. Without these,
  A and B match only when they happen to use the same names.
- **`ignore <file> <path>  # reason`** for what B cannot write. `[]` in a path
  means "array item" and is literal. It is not an fnmatch set.

A rule is always three tokens, so a whole **file** that only one side has
cannot be ignored by naming the file alone — that difference is matched at the
empty path, and an empty token cannot be typed. Write `*` as the path instead:
`ignore state/generation *  # written by bash, not by any Python writer`.

Every difference is either **fixed** or **declared**:
- fixed in A, and in `experiment.py` if it read the wrong field;
- declared as an `ignore` rule with its reason and listed in `OMISSIONS.md`,
  e.g. a field only a live model call writes.

When the reference run's ids are not hex (this branch's names candidates
`run-GGG-II`), `shape_diff` does not normalise them, so every candidate B has
and A lacks shows up as a whole-file difference. Either pass `--subset`, which
ignores files only B has, or declare targeted `ignore` rules for those paths,
each with a reason. Do not hide real differences behind a broad ignore.

Repeat until the diff is clean. A clean diff says nothing about fields that B
never writes: see "What B cannot reach" in `reference/generator.md`.

### 7. The viewer on both roots

```bash
cd <experiment>/viewer
python3 check_literals.py                                                 # must print "clean"
python3 touch_fixtures.py                                                 # mtimes from fixtures/mtimes.json
VIEWER_EXPERIMENT_ROOT=fixtures uv run uvicorn app:app --port 8771 &
VIEWER_EXPERIMENT_ROOT=<scratch>/b uv run uvicorn app:app --port 8772 &
uv run python smoke.py --port 8771 --fixtures fixtures                    # must print PASS
uv run python smoke.py --port 8772                                        # must print PASS
```

`VIEWER_EXPERIMENT_ROOT` is read by the template's `experiment.py`. Keep that
line when you fill the file in. Use `python3`, not `python`, which is not on
every PATH. `--fixtures` makes smoke also check that runs and candidates come
newest first in the order `mtimes.json` gives. B needs no such file: the
generator writes it in order, so its mtimes are real. Use the ports you picked
in step 0; the commands above show 8771 and 8772 only as examples. When done,
stop the B server and leave the fixtures server running for step 8.

Open the page on each root and check that:
- every section is non-empty, except reviews, which is empty by design when
  the experiment has no reviewer stage or none has run yet;
- every **verdict** the legend names actually appears;
- every value the host did not measure shows `—`, never `0.00000`. This covers
  rewards, gains, class means and per-category values alike.

A verdict that B never produces is a mapping bug, and not a gap in the
fixtures, **unless** it is declared in `OMISSIONS.md` with the framework path
that produces it. Some verdicts come from paths the comparison run cannot
reach: `error` from `Rollout.fail`, and `no trace` from `Env.run_episode`'s
episode boundary. Keep those in the mapping and declare them there. Stop reasons are
not verdicts: one that only a live run produces, like hitting the turn limit,
appears in A alone.

### 8. Hand over, and do not claim more than you checked

Write for someone who has not followed the work. Put what they can do first,
then what you checked:

1. **See it now:** the URL of the fixtures server still running from step 7,
   with one sentence on what the fixtures stand for. Say it is invented data,
   so no figure on it means anything.
2. **Use it on the real search:** the one command that serves the real data,
   run from `<experiment>/viewer/`:
   `uv run uvicorn app:app --port <port>`. With no `VIEWER_EXPERIMENT_ROOT`
   the viewer reads the experiment's own `state/` and `outputs/`. It shows
   empty sections until the first generation writes something, and it
   refreshes on its own.
3. **Checked:** the actual last lines of `check_literals.py`, `shape_diff.py`
   and both `smoke.py` runs. Quote them; do not summarise them as "passed".
4. **Not checked:** the fields only A covers, what could not be mapped, and
   what was left out on purpose. Point to `OMISSIONS.md` and
   `fixtures/SOURCES.md` for the full map instead of pasting it.
5. **What to commit:** the new `<experiment>/viewer/` directory. Do not commit
   it yourself unless asked.

**Done** = steps 6 and 7 clean. All of it happens before the first run.

## Updating a viewer later

Run-once per experiment. When a writer in the experiment changes, update the
map, `experiment.py` and the A fixtures together. That is why the mapping lives
in exactly one file. Then re-run steps 5–7. Do not regenerate over a viewer that
has been edited by hand.

## Regenerating a viewer

Update when only the map changes. **Regenerate** when the experiment's writers
changed in a way that moves the shape of what the viewer reads: a new write
site, a new verdict, or a changed record shape. The steps are 1 to 8 again,
against the current code, with these differences:

- **Replaced:** `experiment.py`, `fixtures/` (state, outputs, `SOURCES.md`,
  `mtimes.json`), `OMISSIONS.md`, and the skeleton files, re-copied from
  `template/` so they match the current template.
- **First:** check the viewer for hand edits (`git status` and `git log` on
  `<experiment>/viewer`). Carry any intended edit forward into the map before
  replacing anything.
- **Kept:** anything outside the viewer directory, the experiment's own
  `state/` and `outputs/`, and the scratchpad B generator if it still runs.
- **Afterwards:** compare against the previous generation in git
  (`git diff -- <experiment>/viewer`) and explain each difference: a deliberate
  consequence of the writers changing, or a mapping bug. An unexplained
  difference is a defect in one of the two generations.

## Known limits — state these, do not paper over them

- **A/B compare shape, not meaning.** A field with the right name and type read
  with the wrong meaning (`reward` vs `baseline_train_reward`, both numbers)
  passes every check. The map's notes column is where the choice is argued,
  and it is worth a human's eye once.
- **Detection is by write site.** Code that builds a state path in a way the
  greps in `reference/writer-map.md` do not match is refused. Say what you
  searched for.
- **B cannot reach what only a live run writes.** Trace message graphs, the
  runner's launch config and bash-written logs are covered by A alone, and
  listed as such.
- **The literal check is Python-only.** A number hardcoded into JS display text
  in `static/index.html` passes both `check_literals.py` and every diff. Do not
  hand-edit the front end with figures in it.
- **The golden snapshot's source of truth is the template**, so it catches the
  template changing, not the template being wrong.
- **The independence check — the template reproducing a viewer someone
  designed without seeing it — exists but is not published here.** It runs
  against a private experiment whose hand-written viewer predates this skill;
  the public example has no such artifact and building one now would be
  circular (it would be derived from the same spine the template already
  encodes). See `docs/2026-09-24-migration-record.md` for what that check is
  and why it stayed unpublished rather than being retired or recreated.

## Testing the skill itself

From the skill directory:

- `python3 -m unittest discover -s test -p 'test_*.py'` — five harnesses:
  `test_shape_diff.py`, `test_touch_fixtures.py`, `test_check_literals.py`,
  `test_fixtures_vs_real.py`, and `test_golden_endpoints.py`, the golden
  snapshot of a generated viewer's endpoint JSON. That last one is a drift
  guard, not proof of correctness: its source of truth is the template
  itself, so it catches the template *changing*, not the template being
  wrong.
- `python3 test/fixtures_vs_real.py` — the method: B (`test/synthetic_generator.py`,
  the experiment's real writers with only the measuring layer mocked) against
  `examples/synthetic_search/tools/reference_run.py`'s real writers. A
  difference is a flaw in the method. The declared ones are in
  `test/synthetic_shape_rules.txt`.

A fidelity check on the reference run itself — that `reference_run.py`
genuinely drives the experiment's own writers rather than a mock standing in
for them, and that a build never leaks into the tracked artifact — lives
outside this directory, in `examples/synthetic_search/tests/test_reference_run.py`:
it needs the experiment's own substrate and its `orchestrator` extra, which
belong to the experiment, not to this skill. This is not the independence
check (below) — it does not compare against anything designed independently
of the template.

Run both commands above whenever the template, the scripts or a reference doc
changes.
