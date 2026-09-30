# Fixture sources

A, the hand fixtures for this viewer. Every value is invented to tell one story
(below), so no figure in them means anything. The shapes follow the writer map,
which was built from the code and checked against B (`tools/reference_run.py`,
the experiment's real writers with only the agent and the container scripted)
with `viewer-scaffold/scripts/shape_diff.py`.

Line numbers are as of this generation of the viewer.

## The writer map

| file | writer | field | type | created at | notes |
|---|---|---|---|---|---|
| `outputs/<run>/traces.jsonl` | verifiers `write_episode` (`v1/cli/output.py:150`), `dump_json(exclude_none=True)` | one `Episode` per line: `id`, `env`, `task`, `run`, `ok`, `errors`, `traces` | object | `Env.run` (`v1/env.py:258`), `record_run` by the eval runner | `exclude_none` drops `None` model fields only; a `None` inside `traces[].metrics` is written as `null` |
| | | `ok` | bool | `env.py:304`, `all(t.ok for t in traces)`; stays false on an episode-level error | the runs table's `fail` column |
| | | `errors[]` | `{type, message, status_code?, traceback?}` | `env.py:286`, `:300` | a box that died leaves `traces: []` and an error here |
| | | `traces[].id` | str | `Trace` default uuid hex | also the candidate directory's name (`taskset.py:82`) |
| | | `traces[].ok`, `stop_condition`, `errors` | bool, str, list | `rollout.py:503`; `Trace.record_error` sets `ok` false and stop `error` | `ok` false only via `RolloutRun.fail` |
| | | `traces[].rewards.reward` | `{score, weight}` | `SyntheticTask.score` (`taskset.py:114`, `:122`), `record_reward("reward", report["reward"] or 0.0)` | **zero, not null, on an unmeasured rollout**: the viewer reads the metrics' flags and shows `—` |
| | | `traces[].metrics` | `{reward, artifact_unchanged, guard_rejected, validity_failed, score_error, rows, turns?}` | `evaluate.summarize` (`evaluate.py:23-31`) via `taskset.py:111`, `:118`; `turns` at `taskset.py:120` | `reward` is the host's macro-F1 on train or `null`; `turns` absent on the no-artifact path; empty when scoring never ran |
| | | `traces[].task.data` | `SyntheticData` | `taskset.load_taskset` (`taskset.py:167-176`) | `task_class` is the rollout's label, `turns` the brief's turn limit |
| | | `traces[].nodes`, `calls`, `tools` | lists | written during a live model call | A only; checked against `MessageNode`, `ModelCall`, `Tool` by reading |
| `state/candidates/<trace>/candidate.json` | `taskset_contract.record_candidate` (`taskset_contract.py:50-84`), read-modify-write, `os.replace` | `trace`, `task_class` | str | `finalize` (`taskset.py:92`) | absent when `finalize` never ran |
| | | `reward`, `artifact_unchanged`, `guard_rejected`, `validity_failed`, `score_error`, `rows` | number or null | `score` (`taskset.py:113`, `:121`) via `evaluate.summarize` | absent when scoring never ran ("no report") |
| `state/candidates/<trace>/rules.py` | `SyntheticTask.finalize` (`taskset.py:85-88`) | the returned table | text | `taskset.py:88` | absent when `finalize` never ran |
| `state/candidates/<trace>/status.txt` | `SyntheticTask.finalize` (`taskset.py:90-91`) | `git status --porcelain` in the box | text | `taskset.py:91` | the candidate's hover text |
| `state/promotions.jsonl` | `promote.adopt` (`promote.py:209-210`, append) | `trace`, `train_reward`, `gain`, `artifact_digest`, `gate_passed` | str, number, number, str, bool | `promote.promote` (`promote.py:159-165`) | `train_reward` is the curve's reward: the winner's host macro-F1 on train, the split `promote` ranks on (DESIGN.md "Promotion, gate, adoption") |
| | | `generation`, `val_reward`, `adopted_train_reward` | int, number, number | `promote.adopt` (`promote.py:203-208`) | `val_reward` is the held-out point; the first record's `train_reward - gain` is the pre-search train baseline (`evaluate.gain`) |
| `state/gate_report.json` | `regression_gate.gate` (`regression_gate.py:72`) | `verdict`, `trace`, `artifact_digest`, `val_reward`, `baseline_val_reward`, `per_category{before, after, support, exempt?}`, `exempt`, `failures` | | `regression_gate.py:263-297` | **no generation**: the viewer finds it via the same trace in `promotions.jsonl` or `reviews.jsonl`, and shows none for a gate that failed |
| `state/reviews.jsonl` (optional) | `review._record` (`review.py:299-301`, append), from `review.review`, from `cli._review` | `generation`, `trace`, `model`, `decision`, `cited`, `concern`, `quote`, `reason`, `note`, `streak`, `runaway`, `at` | | `review.py:318-324` | absent while review is disabled (`review.toml`); a downgraded refusal is `decision: "pass"` with the reviewer's `concern`/`quote` kept and a `note` saying why |
| `state/review_streak` | `review.write_streak` (`review.py:292-296`) | consecutive refusals | text int | | not shown |
| `state/baseline_{train,val}.json` | `cli._baseline` (`cli.py:82`); `promote.write_baseline` on adopt (`promote.py:64-65`, `:198-200`) | a `measure_source` report | object | `measure.py:327-395` | current high-water marks |
| `state/baseline_test.json` | `cli._baseline` only (`cli.py:82`) | as above | object | | never rewritten by adopt: the canary |
| `state/cache/<key>.json` | `measure.measure_source` (`measure.py:133`) | a successful report | object | | not shown |
| `state/instrument.json` | `cli._pin` (`cli.py:56`) | `instrument`, `files` | str, list | | shown as the pin |
| `state/corpus/manifest.json`, `<split>/rows.jsonl` | `corpus.stage` (`corpus.py:166`, `:170`) | `seed`, `n`, `counts`, `categories`; rows | | | manifest shown; rows not read |
| `state/runs/supervisor.log` | `supervisor.sh:29` (`exec >>"$LOG"`) | the loop's log | text | | live card and generation number |
| `state/generation` | `supervisor.sh:214`, `:227`, `:240`, `:258` | next generation number | text int | | not shown |
| `state/pending.json`, `state/staged/` | `promote.promote`, `regression_gate.gate` | | | | transient between promote and adopt; not read |

## One line per fixture file

The story: generation 0 adopts, generation 1 adopts after a review that was
downgraded to a pass, generation 2's winner passes the gate and is refused by
the reviewer, generation 3's winner fails the gate, and generation 4's eval dies
before writing an episode, which stops the supervisor.

- `outputs/run-000/traces.jsonl`: generation 0, three episodes: scored (with a
  message graph), the no-artifact path (`artifact_unchanged`, no graph), and
  `guard_rejected`.
- `outputs/run-001/traces.jsonl`: generation 1: `score_error`, scored (the
  winner), and a rollout whose scoring raised a substrate error (`ok: false`,
  stop `error`, empty metrics).
- `outputs/run-002/traces.jsonl`: generation 2: `validity_failed`, scored (the
  winner the reviewer refuses), and a scored rollout stopped at `max_turns`.
- `outputs/run-003/traces.jsonl`: generation 3: scored (the winner the gate
  fails), and an episode with no trace and an `EnvError` (the box died).
- `outputs/run-004/traces.jsonl`: generation 4: empty, as `save_config` leaves
  it when the eval dies before its first episode.
- `state/candidates/run-000-00/`: scored, adopted in generation 0.
- `state/candidates/run-000-01/candidate.json`: `artifact_unchanged`: `score`
  found no `rules.py`; no `finalize` fields, no `rules.py`, no `status.txt`.
- `state/candidates/run-000-02/`: `guard_rejected`.
- `state/candidates/run-001-00/`: `score_error`.
- `state/candidates/run-001-01/`: scored, adopted in generation 1.
- `state/candidates/run-001-02/`: no report: `finalize`'s half only.
- `state/candidates/run-002-00/`: `validity_failed`.
- `state/candidates/run-002-01/`: scored, the winner refused by the reviewer.
- `state/candidates/run-002-02/`: scored, empty `status.txt`.
- `state/candidates/run-003-00/`: scored, the winner that fails the gate.
- `state/promotions.jsonl`: the two adoptions (generations 0 and 1).
- `state/reviews.jsonl`: a pass, a refusal downgraded to a pass (uncited
  concern), and a cited refusal.
- `state/review_streak`: one refusal in a row.
- `state/gate_report.json`: generation 3's failed gate; every category is
  exempt at this corpus size, and the val mean fell.
- `state/baseline_{train,val,test}.json`, `state/cache/<key>.json`,
  `state/instrument.json`, `state/corpus/**`: as the writers leave them after
  generation 1's adoption.
- `state/generation`, `state/runs/supervisor.log`: the supervisor's own files,
  after generation 4 stopped the run.
- `mtimes.json`: the story's order, one time per run directory and per
  `candidate.json`.
