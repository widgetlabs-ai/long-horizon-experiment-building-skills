# skills

Agent skills for building and watching long-horizon searches, plus the field
guide they share and the worked example they are tested against.

This directory is written to become a **standalone repository**: everything in
it is self-contained, and nothing in it may reference a path outside it at run
time. Treat this directory as the repository root when reading any relative
path below.

| path | what |
|---|---|
| `FIELD-GUIDE.md` | the pattern: architecture, vocabulary, and the failure catalogue |
| `examples/` | runnable example experiments — the worked examples, and what the skills' tests run against |
| `experiment-scaffold/` | walks a user through creating an experiment |
| `viewer-scaffold/` | generates an experiment's live read-only dashboard |

The two skills pair: `experiment-scaffold` produces an experiment laid out so
that `viewer-scaffold` can instrument it without modification.

## Discovery

A consuming repository finds a skill through a symlink at its own
`.claude/skills/`, which is where both Claude Code and opencode look:

```bash
ln -s ../../long-horizon/skills/<name> .claude/skills/<name>
```

Adjust the link target to wherever this directory sits in that repository. When
it becomes a submodule, that is the only line that changes.

## Rules for anything added here

- **Self-contained.** No import, path, or documentation reference that leaves
  this directory. A skill that reads a sibling project's live files stops
  working the day this directory moves.
- **No proprietary content.** No names, figures, or vocabulary from the
  repository that happens to host this directory. Examples are synthetic, and
  every number in the documentation is measured against them.
- **One guide, shared.** Both skills cite `FIELD-GUIDE.md`. A copy per skill is
  a copy that diverges.
