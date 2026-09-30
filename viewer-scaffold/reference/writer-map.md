# The writer map

The map is the only input `experiment.py` is written against, and it is built
from **code**: the experiment has usually never run, and even when it has, the
state dir is not opened. For every file the viewer reads, the map says which
line of code writes it, which fields it holds, and where each field is created.

## 1. Find the write sites

From the experiment root:

```bash
# files written from a value
grep -rnE "write_text|write_bytes|json\.dump|\.open\([^)]*['\"](a|w|ab|wb)['\"]" src/ | grep -v /tests/
# files and trees that arrive by copy, move or unpack
grep -rnE "copytree|copy2|shutil\.(copy|move)|extractall|\.rename\(|symlink_to" src/ | grep -v /tests/
# bash redirections
grep -nE '>>?\s*"?\$[A-Z_]+' supervisor.sh *.sh
# the framework's own writers
grep -rnE "^(async )?def (write|save|dump|append)_" .venv/lib/python*/site-packages/<framework>/
```

For each hit, answer two questions: which path does it write, relative to the
state dir or the outputs dir, and which dict does it serialize? A copy or an
unpack serializes nothing of its own. It only tells you that a directory exists
and whose files it holds — `synthetic_search` has no such writer (its second
grep, for `copytree`/`copy2`/`extractall`/`.rename(`/`symlink_to`, returns
nothing under `src/`); `finalize` reads and writes each file's bytes
individually instead (`taskset.py:88`). The framework grep does find files next
to the traces, e.g. verifiers `write_config` (`cli/output.py:96`), which writes
`configs/resolved/<cli>.json` into every run dir.

The greps are a starting point, not a proof. Read each writer's module too,
because a path built in one function and written in another is easy to miss.

`synthetic_search`, for orientation:

| file | writer |
|---|---|
| `state/promotions.jsonl` | `promote.py:209-210` (append) |
| `state/gate_report.json` | `regression_gate.py:72` |
| `state/reviews.jsonl` (optional) | `review._record`, `substrate/review.py:299-301` (append) |
| `state/candidates/<trace>/{rules.py,status.txt,candidate.json}` | `taskset.py:79-92` (`finalize`) |
| `state/cache/<hash>.json` | `measure.py:133` |
| `state/baseline_{train,val}.json` | `promote.write_baseline` |
| `outputs/<run>/traces.jsonl` | verifiers `cli/output.py:150` `write_episode` |
| `state/runs/supervisor.log` | `supervisor.sh:29` (`exec >>"$LOG"`) |
| `state/generation` | `supervisor.sh:214`, `:227`, `:240`, `:258` (bash) |

## 2. Membership test

| concept | counts as a writer |
|---|---|
| promotions | an append to `promotions*.jsonl` |
| gate | a write of `gate*.json` |
| candidates | files created under `candidates/<id>/` |

Reviews are **not** on this list. An experiment with a reviewer stage writes
`state/reviews.jsonl`, one line per generation that reached the stage, from
`review._record` (`substrate/review.py`), called from `review.review`, which
`cli._review` (`substrate/cli.py`) calls. Whether the viewer defines `reviews()`
turns on whether the experiment HAS a reviewer stage, not on whether it is
enabled: with a stage, `reviews()` is defined and is empty while the file is
absent (review disabled, or not yet run); with no stage at all, the viewer
defines no `reviews()`.

If any of the three is missing, **refuse**. Print the greps you ran and every hit
they returned, so that a writer the greps missed is a quick fix and not a
mystery. There is no force flag.

## 3. Follow every field to where it is created

A write site often serializes a dict that was assembled somewhere else. Follow
every `{**x}`, `.update(...)` and returned dict until each field has the line
that creates it:

- `promote.adopt` writes `{**pending, "generation": …, "val_reward": …,
  "adopted_train_reward": …}` (`promote.py:203-208`). `pending` is built by
  `promote.promote` (`promote.py:159-165`), so `trace`, `train_reward`,
  `gain`, `artifact_digest` and `gate_passed` are created there, not in
  `adopt`.
- `cli._score` (`cli.py:88-95`) calls `measure.measure_source`, whose report
  it merges with `evaluate.summarize(...)` (`cli.py:93`, `evaluate.py:24-32`).
  `summarize` starts from `{"artifact_unchanged": 0.0, "guard_rejected": 0.0,
  "validity_failed": 0.0, "score_error": 0.0}` (`evaluate.py:26`, the
  `ZERO_REASONS` tuple at `evaluate.py:16-21`) and copies `reward` straight
  from the report (`evaluate.py:27`) — it is never a second flag stacked on
  top of a first. `measure_source` itself returns at the first `ZERO_REASON`
  it hits (`guard_rejected` on a `CandidateError`, `validity_failed` when the
  validity check refuses the artifact, `score_error` on the classifier
  raising or a split with no support — `measure.py:100`, `:111`, `:119`,
  `:127`), so the three flags it sets are mutually exclusive by construction.
  The fourth, `artifact_unchanged`, is not set there: `SyntheticTask.score`
  sets it (`taskset.py:111`) for a candidate whose `finalize` never returned a
  source, and `promote` reports it for a table identical to the adopted one
  (`promote.py:110`). That is a property of this writer, not a law:
  a new experiment's writer may stack a general flag on a specific one, and
  the map exists to catch exactly that before a verdict function assumes it
  can't happen.

## 4. Framework-written files

A file written by the eval framework has no writer in `src/`. Find the
framework in `pyproject.toml` / `uv.lock`, run `uv sync`, and read its
serializer in `.venv`. For verifiers:
- `write_episode` (`verifiers/v1/cli/output.py:150`) dumps an `Episode`
  (`episode.py:86`) holding `Trace`s (`trace.py:375`);
- `Env.run_episode` builds them (`env.py:258`).

These line numbers are for the verifiers version locked in the experiment's
`uv.lock`. Re-check them after a verifiers upgrade.

The pydantic model classes are the schema. Read their fields, their defaults and
any `exclude=`. Task-specific fields live in `trace.info` and
`trace.task.data`, and those come back to the experiment's own code (the
`SyntheticData` fields — `task_class`, `worst`, `baseline_reward`, `rows` — in
`taskset.py`).

## 5. The map and `SOURCES.md`

The map is a table:

| file | writer | field | type | created at | notes |
|---|---|---|---|---|---|
| `state/promotions.jsonl` | `promote.py:209-210` | `train_reward` | number | `promote.py:161` | the winner's host reward on train |

It goes into your report. `viewer/fixtures/SOURCES.md` is the same table, plus
one line per fixture file saying which verdict or path it stands for
("`candidates/…03/`: build failed").

## 6. What the map cannot tell you

Meaning. `train_reward` and `baseline_train_reward` are both numbers in the same
record. Use the notes column to say which one the viewer reads and why, citing
the README or DESIGN sentence. No check downstream catches the wrong choice.
