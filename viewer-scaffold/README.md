# viewer-scaffold

A skill that builds a live, read-only viewer for one long-horizon experiment
from the experiment's code, before its first run. `SKILL.md` is the procedure
the agent follows. This file only says how to start it.

## Starting it

In Claude Code or opencode, the skill is found through the symlink in
`.claude/skills/`. Type `/viewer-scaffold`, or ask for "a viewer for
<experiment>".

In any other harness whose agent can read and write files and run shell
commands, say:

> Read `<skill-dir>/SKILL.md` and follow it.

You do not need to know anything else up front. The agent asks which
experiment, if you did not say. It checks the prerequisites itself and tells
you how to fix a missing one. It stops once more, after reading the code, to
show you what each section of the page will be fed from and to ask whether
that is right. It ends with a URL to look at the viewer on example data, and
with the one command that serves the real search.

## Caveats

- The rule against reading `state/` and `outputs/` is an instruction only;
  nothing enforces it. For a weaker model, run it on a checkout without those
  directories.
- The worked examples are for verifiers. On another eval framework the agent
  has to find the equivalent writers in that framework's code;
  `reference/generator.md` says what to look for.
- The skill refuses an experiment whose code writes no promotions, gate or
  candidates. That is intended.
