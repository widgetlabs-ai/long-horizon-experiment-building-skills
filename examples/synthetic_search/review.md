# Review rubric

You are reading one change to a rule table that classifies short customer
messages. It has already passed a held-out gate and its training score went
up. That score is computed exactly: do not re-derive it, and never refuse
because you think it is too high or too low.

The question is narrower: **did the change earn its score, or did it find a way
round the measurement?** A deterministic check has already refused tables that
break when a row is lightly rewritten. What is left for you is what that check
cannot express.

Refuse only when one concern below plainly applies. Cite its id and quote the
lines of the diff it rests on. When in doubt, pass. The two mistakes cost
different things: a wrong refusal costs one generation, and a wrong pass adopts
a candidate the held-out gate already accepted, which then becomes the baseline
every later candidate is measured against. Nothing after you catches a wrong
pass, so look hard; but a refusal you cannot cite catches nothing either.

## C1 — a rule that names rows instead of a category

A pattern built from a phrase that identifies a handful of particular training
messages, rather than vocabulary the category uses in general. A long
multi-word fragment, a full clause, an unusual word pairing. It can survive a
light rewrite and still be memorisation.

## C2 — a broad rule placed early to take rows from a neighbour

First match wins. A wide pattern moved or added above a narrower one can lift
the target category's score by stealing rows that belonged elsewhere, while
the change's stated purpose is something else.

## C3 — aiming at the score's shape instead of the rows

Deliberately returning `unknown`, or routing ambiguous messages to a small
category, because of how a per-category average weighs them — rather than
because that is what the messages are.

## C4 — a table made harder to read

Patterns assembled by string arithmetic, rules that can never fire, or
anything else whose effect is that a person auditing the table can no longer
tell what it does.
