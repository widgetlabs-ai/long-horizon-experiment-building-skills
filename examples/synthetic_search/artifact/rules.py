"""The editable artifact: a rule table over message text.

THIS FILE IS THE ONLY THING THE SEARCH EDITS. Everything that turns an edit
into a number — the corpus, the scorer, the splits — is frozen and is not
yours to change.

First match wins, so order matters: a broad rule placed early shadows every
specific rule below it. Return UNKNOWN when nothing matches; a wrong guess and
an honest "I don't know" score the same here, but only one of them is readable.

The table below is deliberately incomplete. Several categories are covered by
one or two openers and nothing else, and at least one rule is broad enough to
steal rows from its neighbour.

You cannot import anything here, and the guard will reject the candidate if you
try. `re` is already in scope; so are the ordinary builtins listed in
`substrate/artifact.py`. The restriction is not bureaucracy: a rule table that
can open a file can read the labels it is graded against, score perfectly, and
teach nobody anything.
"""

UNKNOWN = "unknown"

# (regular expression, category). Matched case-insensitively against the whole
# message, in order.
RULES = [
    (r"\b(hello|hi there|good morning)\b", "greeting"),
    (r"\b(could you tell me|do you know|any idea)\b", "question"),
    (r"\b(unacceptable|disappointed|frustrated)\b", "complaint"),
    (r"\b(i would like|please send|can i order)\b", "order"),
    (r"\b(goodbye|see you|bye for now)\b", "farewell"),
]


def classify(text):
    """Return the category of `text`, or UNKNOWN when no rule matches."""
    lowered = text.lower()
    for pattern, category in RULES:
        if re.search(pattern, lowered):
            return category
    return UNKNOWN
