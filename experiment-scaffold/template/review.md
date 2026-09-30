# Review rubric

You are reading one change to __ARTIFACT_DESCRIPTION__. It has already passed a
held-out gate and its training score went up. That score is computed exactly: do
not re-derive it, and never refuse because you think it is too high or too low.

The question is narrower: **did the change earn its score, or did it find a way
round the measurement?** A deterministic validity check has already refused
what could be written down in advance. What is left for you is what it cannot
express.

Refuse only when one concern below plainly applies. Cite its id and quote the
lines of the diff it rests on. When in doubt, pass. The two mistakes cost
different things: a wrong refusal costs one generation, and a wrong pass adopts
a candidate the held-out gate already accepted, which then becomes the baseline
every later candidate is measured against. Nothing after you catches a wrong
pass, so look hard; but a refusal you cannot cite catches nothing either.

__CONCERNS__
