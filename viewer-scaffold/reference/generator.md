# B: fixtures written by the experiment's own code

A, the hand fixtures, and `experiment.py` both come from one reading of the
code, so a misreading shows up in both and every check passes. B does not go
through that reading. It **runs** the writers. `shape_diff.py` then compares A
with B, and a difference means the reading was wrong.

## The boundary

- **Mock** only what measures or touches the outside world: engine builds,
  containers, model calls, scoring subprocesses, and hashing or copying real
  source trees.
- **Call for real** everything that assembles a dict ending up in a file.
- **When a writer fails, feed it from the mocked layer.** Never patch the
  writer itself: a patched writer writes your idea of the file, which is A again.

## Running

```bash
cd <experiment> && uv sync
<experiment>/.venv/bin/python <scratch>/generate_b.py --out <scratch>/b
```

- Put `sys.path.insert(0, "<experiment>/src")` at the top of the script.
- Inputs the writers need, such as a stub corpus, go **outside** `state/` and
  `outputs/`, so that they are not compared.
- B is scratch and is never committed.

## The world object

Keep the mocked layer's answers in one object. Name each tree by a marker file
that the extract mock drops into it, so that code copying trees around (promote
staging, adopt) carries the name along. Keep levels per `(tree, split)` and a
plan per candidate:

```python
class World:
    def tree(self, root):                       # which tree is this path?
        marker = Path(root) / ".fake_tree"
        return marker.read_text() if marker.is_file() else self.adopted

    def measure_source(self, source, split, state, **_):
        tree = self.tree(state)
        if self.plan.get(tree) == "guard_rejected":
            raise CandidateError("the artifact reached outside the text it was handed")
        level = self.level[(tree, split)]
        return {"reward": level, "per_category": {c: {"f1": level, "support": 10} for c in CATEGORIES},
                "rows": 10, "error": None, "guard_rejected": 0.0, "score_error": 0.0}
```

Give mocked values the **real** types: strings where the real scorer writes
strings, and so on. A wrong type in a mock is the one mistake B is allowed to
make, and `test/fixtures_vs_real.py` exists to catch it in the worked example.

## Framework hooks (verifiers)

```python
task = SyntheticTask(data)
trace = Trace(task=TraceTask(type=type(task).__name__, data=data, key=task.key, hash=task.hash),
              agent=AgentInfo(config={}))             # as Env.run_episode builds it, env.py:258
await task.finalize(trace, FakeRuntime(...))          # the experiment's candidate dump
await task.score(trace, None)                         # the real @vf.reward / @vf.metric hooks
episode = Episode(env=EnvInfo(id=...), task=trace.task, traces=[trace], ok=True)
episode.record_run(EvalRunInfo(id=..., name=run_dir.name))   # as the eval runner does, runner.py:208
write_episode(run_dir, episode)
```

Also cover the episode that has **no** trace (an `Episode` with `errors` and
`traces=[]`), if the viewer has a verdict for it.

A reward hook that shells out to score, like `_score_candidate`, is replaced by
an in-process call to the same CLI function (`cli._score`), with the same
arguments.

### Another framework

The hooks above are verifiers'. For any other eval framework, find the
equivalents in its installed code under `.venv`. Do not work from its docs.
Find:
- the function that appends one finished episode to the run's output (verifiers:
  `write_episode`);
- the one that creates the run directory and its config files (`save_config`,
  `create_attempt_log_dir`);
- where the run's identity is stamped on each record (`record_run`);
- the flag that marks a rollout failed, and every path that sets it (verifiers:
  `Trace.ok`, set false only by `fail()`). The runs table's `fail` column and
  `notes()["runs"]` depend on this, see `spine.md`.

Call them from B exactly as the framework's runner calls them. If the runner
does something inline rather than through a function B can call, do not
rewrite it in B. Leave it to A and list it in `OMISSIONS.md` under "A only",
with the `file:line` of the inline code. A hand-rolled copy of a framework
writer only proves that the copy matches A.

Reviews, when the experiment has a reviewer stage, are produced the same way: B
calls the experiment's real `review` subcommand with `SYNTH_FAKE_REVIEW` set,
and never writes `reviews.jsonl` by hand, so the record's shape is the writer's
and not the generator's guess.

## Paths to exercise

- [ ] every candidate verdict the host can produce (read them off the report writer);
- [ ] a candidate with no report (the eval died before scoring);
- [ ] a rollout whose box died (no candidate at all);
- [ ] a generation that promotes and passes the gate;
- [ ] a generation that promotes and fails it;
- [ ] a generation that promotes nothing, when that writes anything different.

## What B cannot reach

These are covered by A alone:
- anything written during a live model call: trace `nodes`, `calls` and
  `tools`, and the stop reasons only a live agent triggers (the turn limit);
- the agent config the eval runner resolves from its launch file
  (`traces[].agent.config`, `configs/resolved/*.json`);
- anything written only by bash (`supervisor.sh` logs, the `generation` counter).

The run stamp (`episode.run`) is **not** on this list. B writes it with
`record_run`, exactly as the runner does.

**A clean diff proves nothing here, and needs no rule to get there.** B's
`nodes`, `calls` and `tools` are empty lists, and `shape_diff` compares nothing
under an array that is empty on one side. A mistake in A's `nodes` passes
silently. So check A's version of these fields by hand against the framework's
pydantic models:
- `serialize` settings: verifiers writes with `exclude_none`, so a `null` field
  never appears;
- unions: `message.content` is `str | list[ContentPart]`, and the viewer must
  handle both;
- alternates: a reply with empty `content` can carry `reasoning_content`.

List them in `OMISSIONS.md` as "A only — checked against `<model>` by
reading, not by B". Declare an `ignore` rule only for fields B writes
differently, like the resolved agent config.

## Worked example

- `test/synthetic_generator.py` is B for `synthetic_search`. Its mocked layer
  is deliberately tiny: this experiment's scorer is local, deterministic and
  takes milliseconds, so `measure.measure_source`, the `cli score` subprocess
  `task.score` shells out to, the instrument pin, and `promote`/`gate`/`adopt`
  all run for real, on real writers. Only two things are mocked: the rollout
  CONTAINER (the runtime `finalize` reads and writes through) and the AGENT
  (each rollout is a scripted table/status tuple instead of a live model
  loop).
- `test/fixtures_vs_real.py` no longer compares B against a real run's
  `state/` and `outputs/` — there is no private run to compare against in a
  published tree. It compares B against R,
  `examples/synthetic_search/tools/reference_run.py`, which drives the same
  writers for real with only the AGENT scripted (the container is real there
  too, over a stub runtime). A difference between B and R is a flaw in B's
  mock, declared in `test/synthetic_shape_rules.txt` when it can't be fixed.

This caught a real defect, not a hypothetical one: an earlier `score(trace) ->
Reward` override — called by neither B nor R the way `rollout.py` actually
calls `Task.score` (`runtime` positional, the return value discarded) — masked
a `TypeError` every live rollout would have hit and left `traces[].rewards`
empty on both sides of the comparison, so B matching R proved nothing about
the one thing that mattered. Fixed in both places by `00eddc1`, whose message
is the record: see `taskset.SyntheticTask.score`'s docstring, `reference_run.build`'s
docstring at the `task.score` call, and the regression test,
`examples/synthetic_search/tests/test_taskset.py::test_score_accepts_the_call_the_framework_makes`.
