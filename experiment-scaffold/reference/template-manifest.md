# The template manifest

Every file a scaffolded experiment gets, and where it comes from. Three tiers:

| tier | what it means |
|---|---|
| **verbatim** | copied unchanged from `template/`. A drift test fails if it stops matching its source in `examples/synthetic_search`. Do not edit these per experiment — if one needs changing, change it for everyone. |
| **adapt** | copied from `template/`, then filled in against the design. The placeholders are listed below. |
| **write-fresh** | not shipped at all. Written per experiment against `contracts.md`, because there is nothing domain-free to copy. |

The rule of thumb: a file is **verbatim** when its content encodes a lesson
rather than a decision. The supervisor's error branches, the exit codes and the
provider resolution are the same in every search, and each of them is a failure
somebody already paid for. A file is **write-fresh** when copying it would be
copying somebody else's domain.

## The manifest

| file | tier | notes |
|---|---|---|
| `errors.py` | verbatim | exit codes 0/1/2 and the two error kinds |
| `supervisor.sh` | verbatim | the generation loop; every error branch written the long way |
| `provider.sh` | verbatim | resolves an upstream from the keys set; refuses when none is |
| `run.sh` | verbatim | preflight, then the supervisor; names what it skipped |
| `gitignore` | verbatim | published as `.gitignore`; the `state/*` form, no inline comments |
| `review.py` | verbatim | the reviewer: citation rule, runaway guard, nonsense-passes-silence-stops |
| `cli.py` | adapt | the subcommand spine; `SUBCOMMANDS` and the handlers are yours |
| `evaluate.py` | adapt | `ZERO_REASONS` is the part you must rewrite |
| `taskset_contract.py` | adapt | `ARTIFACT_PATHS`, the held-out splits, the brief's placeholders |
| `taskset.py` | adapt | `setup`, `finalize`, `score`; the framework half |
| `brief.md` | adapt | the opening is fixed; the body is yours |
| `pyproject.toml` | adapt | name, package path, dependencies |
| `config.toml` | adapt | one per provider; identical apart from endpoint, key variable and model |
| `review.toml` | adapt | the reviewer's endpoint, key variable and model; its own file |
| `review.md` | adapt | the frame is fixed; the concerns are yours, and must not restate the reward |
| `Dockerfile` | write-fresh | its `COPY` list is the leak boundary and is entirely yours |
| `dockerignore` | write-fresh | must exclude every held-out split |
| `corpus.py` | write-fresh | what an example is, and how splits are assigned |
| `measure.py` | write-fresh | how a candidate is built and scored, and the cache key |
| `scorer.py` | write-fresh | the frozen instrument |
| `promote.py` | write-fresh | eligibility and tolerances are domain judgements; the template `cli.py` review handler calls its `resolve_artifact_path`, `_baseline`, `_generation` and `discard_pending`, so keep those four |
| `regression_gate.py` | write-fresh | what "a regression" means for your sub-problems |
| `selftest.py` | write-fresh | the invariants are yours, the shape is in `contracts.md` |
| `validity.py` | write-fresh | the candidate's invariants; the requirements are in `contracts.md` §7 |
| `box.py` | write-fresh | the agent's in-box tool |

## Placeholders in the adapt tier

| placeholder | becomes |
|---|---|
| `__EXPERIMENT__` | the experiment's name, and its package's bare module name |
| `__STATE_ENV__` | the environment variable naming the state directory |
| `__ARTIFACT_ENV__` | the environment variable overriding the artifact's path |
| `__ARTIFACT_PATHS__` | the paths a rollout returns |
| `__ZERO_REASONS__` | the ways this search returns no measurement |
| `__VALIDITY_TOOL__` | the in-box command that runs the validity check |
| `__REVIEW_BASE_URL__` | the reviewer's OpenAI-compatible endpoint |
| `__REVIEW_KEY_VAR__` | the environment variable holding the reviewer's key — not the rollouts' |
| `__REVIEW_MODEL__` | the provider's id for the reviewer model |
| `__ARTIFACT_DESCRIPTION__` | one phrase: what the artifact is, for a reader who has never seen it |
| `__CONCERNS__` | numbered `## C1 — …` headings, each a way to beat the reward that the validity check cannot see |

A generated file containing `__` after scaffolding is an unfinished file. Check
for it before handing over.

## Keeping the verbatim tier honest

`examples/synthetic_search` is the source of truth: the verbatim templates are
that experiment's files, and `test/test_template_drift.py` diffs them. When one
of them is improved, improve it there and re-copy — a template edited on its
own has quietly forked from the thing that is actually tested and run.

Where a verbatim template legitimately differs from its source, the difference
is declared below with a reason, and the test reads these declarations.

### Declared differences

| file | reason |
|---|---|
| `gitignore` | shipped without a leading dot so it is not interpreted as this skill's own ignore file; written out as `.gitignore` |
| `config.toml` | the example ships two provider configs; the template ships one with the provider fields as placeholders |

If the example is absent from a checkout, the drift test **skips with that
reason** rather than failing. The skill must work in a repository that ships no
examples.
