# Your task

You have **{{TURNS}} turns**. Only one thing survives this container:
`artifact/rules.py`. Everything else — scratch scripts, notes, anything under
`/tmp` — is discarded the moment the rollout ends, and no part of it is read,
scored, or remembered.

So: **land an edit to `artifact/rules.py` in your first ten turns**, then treat
every further edit as a checkpoint. A rollout that spends sixty turns analysing
and edits nothing scores exactly what it was given, which looks like a
perfectly reasonable result and teaches nobody anything. An imperfect edit that
exists beats a perfect one you did not write down.

Finish by replying with your best score as the last thing in your message.

## What you are working on

Focus category: **{{CLASS}}**

The table currently scores **{{BASELINE}}** macro-F1 over {{ROWS}} training
rows. The weakest categories right now:

{{WORST}}

You may fix anything — the reward is the whole-train macro-F1, not your
category's alone. The focus is where to start, not a fence.

## The tools

- `rt score` — score the current table against the train rows, with the delta
  against the baseline and a per-category breakdown
- `rt rows [--class C]` — sample rows, optionally of one category, with what
  the table currently predicts for each
- `__VALIDITY_TOOL__` — run the guard and the validity check without scoring

`rt score` is the same scorer that produces the reward, run on the same rows.
It takes well under a second, so run it after every edit.

## The rules

- **`artifact/rules.py` is the only file that comes back.** Editing anything
  else is wasted effort.
- **You cannot import anything in that file.** `re` is already in scope. The
  guard rejects the candidate outright if you try — and the restriction is the
  point: a table that can open a file can read the labels it is graded against,
  score 1.0, and prove nothing.
- **First match wins.** Rule order is part of the design: a broad rule placed
  early shadows every specific rule under it.
- **The scorer, the rows and the splits are frozen.** If you think the
  measurement is wrong, say so in your reply — do not work around it.
- **A candidate that breaks the validity check is refused, whatever it
  scores.** `__VALIDITY_TOOL__` runs the same check the host runs after the
  rollout. It runs whether or not you do; running it yourself is how you find
  out while you can still fix it.
