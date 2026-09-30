# Design record — 2026-09-24

Why this skill is shaped the way it is, and what was deliberately left undone.
The full specification lives with the repository that hosts this directory; this
is the short version that travels with the skill.

## Why it exists

`viewer-scaffold` builds a dashboard for an experiment, and **refuses** one
whose code does not write promotions, a gate report and candidates. Nothing
helped a person produce such an experiment in the first place. This skill is
that missing half: the two together are "build the search, then watch it".

## Decisions

- **The deliverable is a runnable experiment**, not a skeleton with TODOs and
  not a design document. The structural majority is mechanical from the field
  guide; the domain minority comes from an interview and from reading the
  person's code, with a refusal rather than a guess where the answer is not
  available.
- **Templates are a hybrid.** Files whose content encodes a lesson rather than
  a decision are shipped and copied verbatim; the domain half is written fresh.
  The tier of every file is recorded in `reference/template-manifest.md`.
- **The drift test's source of truth is the shipped example**, never a live
  sibling experiment. An example that lives outside this directory would make
  the skill unusable the day it is published on its own.
- **The spike is a gate.** Measuring one real example twice, before any
  scaffolding, is the only step that converts the interview's claims into
  evidence — and it catches nondeterminism for free.
- **`DESIGN.md` is the single mid-point checkpoint**, so heavy decisions are
  corrected on one page instead of in twelve files.
- **viewer-scaffold compatibility is verified by grep**, using the same
  detection the sibling skill uses to refuse, rather than claimed.
- **Environment hubs are a reference and an import path, never a live lookup.**
  Hub listings are not reliably machine-readable without credentials, and an
  unattended step that guesses at search results is a step that guesses.
- **Retrofit is additive-only.** Meeting a half-built experiment is the normal
  case; overwriting somebody's hand-tuning is not recoverable.

## Deliberately not done

- **`viewer-scaffold` still depends on a private experiment.** Its method tests
  run against that experiment's real state and outputs. Re-pointing them at
  `examples/synthetic_search` is required before this directory can be
  published, and it proves less than the current tests do, because synthetic
  state is state nobody was surprised by. That tradeoff deserves its own
  session. The proprietary-term scan lists the directory as deferred, with the
  reason, and fails if the exclusion is ever left in place after a cleanup.
- **Promoting this directory to a standalone repository.** Everything here is
  written to make that a `git init` and a symlink change, but it has not been
  done.
- **Publishing the example as a hub environment.** Its inner half is an
  ordinary environment and the audience would be the right one, but publication
  is an outward-facing decision, not a side effect of scaffolding.
