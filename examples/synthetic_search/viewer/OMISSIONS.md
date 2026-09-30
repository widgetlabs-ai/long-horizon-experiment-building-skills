# What this viewer does not show, and what only A covers

## A only: checked by reading, not by B

B here is `tools/reference_run.py`, which scripts the agent, so it writes none
of what a live model call writes. `shape_diff` compares nothing under an array
that is empty on one side, so these fields pass the A/B diff without being
checked by it.

- `traces[].nodes`, `calls`, `tools` — A only, checked against
  `verifiers.v1.graph.MessageNode`, `verifiers.v1.trace.ModelCall` and
  `verifiers.v1.types.Tool` by reading, not by B. Written with
  `exclude_none=True`, so a `null` model field never appears. `message.content`
  is `str | list[ContentPart]` (A's user node uses the list form), and an
  assistant reply with empty `content` can carry `reasoning_content` (A's first
  assistant node does); `experiment.rollout_trace` handles both.
- stop reasons other than `final_answer`: `max_turns` (A's `run-002-02`) and
  `error` (A's `run-001-02`). R hardcodes `final_answer`.
- a rollout the framework marks failed (`ok: false`, verdict `error`) and an
  episode with no trace (verdict `no trace`). R marks every trace and episode
  ok and always runs one trace per episode, so **B never produces these two
  rollout verdicts**; they come from `Rollout.fail` (`verifiers/v1/rollout.py:157`)
  and `Env.run_episode`'s episode boundary (`verifiers/v1/env.py:279-287`), which R does
  not drive.
- a gate that fails. R's gates all pass at its default size; A's latest gate
  report is a failure.
- a review downgraded to a pass (`note` set). R's fake reviewer passes or
  cites correctly.

## Declared differences between A and B (the rules file)

- `traces[].agent.config.*`: a live eval resolves the agent config from its
  launch file; R builds `AgentInfo(config={})`. The viewer reads nothing under
  it.
- `state/generation`, `state/runs/*`: written by `supervisor.sh` (bash); R
  never runs the supervisor.
- candidates `run-00[0-3]-0[34]`, `run-003-0[12]`: R runs five rollouts per
  generation and names them `run-GGG-II`, and A uses the same names for fewer.
  Candidate paths carry the id, which `shape_diff` normalises only when it is
  hex.
- `reward` in `run-002-00` and `run-002-01`'s `candidate.json`: the same id
  tells a different story on each side (null on one, a number on the other).
  Both types occur on both sides under other ids.

## Not shown, on purpose

- `promote`'s ranking verdicts (`eligible`, `no_gain`, `regresses_a_category`,
  and its own `artifact_unchanged` for a table identical to the adopted one) —
  printed to the supervisor's log, never written to a file. The candidates'
  verdicts are the host's measurement only.
- the validity check's `violations` — `cli score` prints them, but
  `SyntheticTask.score` records only `evaluate.summarize`'s metrics, so they
  reach no file the viewer can read.
- the gate report's generation — not recorded. The viewer shows one only when
  the same trace appears in `promotions.jsonl` or `reviews.jsonl`, so a failed
  gate shows none.
- per-category starting values — adoption overwrites both baselines, and no
  file keeps the originals (`baseline_test.json` does, but for another split).
- `state/review_streak`, `state/generation`, `state/cache/`, `state/pending.json`,
  `state/staged/`, the corpus rows — bookkeeping, not measurements.
- `review.toml`'s `max_consecutive_vetoes` and `enabled` — outside the state
  dir; the reviews section shows `runaway` from the record instead.
