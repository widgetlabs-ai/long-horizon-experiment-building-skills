"""The corpus: generated from a seed, staged into three splits, resolved without a default.

Generated rather than downloaded so the example runs anywhere with no network,
no credentials and no data to lose. Splits are shares within every category, so
no category lands entirely in one split — a gate on a category the val split
never saw is a gate that cannot fail.

There is no default for the state root. A path that falls back to a guess is a
path that is silently wrong on the next machine, and the whole run measures
nothing while every number stays plausible.
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

from synthetic_search.substrate.errors import EXIT_SUBSTRATE, SubstrateError

STATE_ENV = "SYNTH_STATE"
SPLITS = ("train", "val", "test")
SPLIT_WEIGHTS = {"train": 3, "val": 1, "test": 1}

CATEGORIES = ("greeting", "question", "complaint", "order", "farewell")

# Each category is a small grammar. The classifier's job is to recover the
# category from the surface form; the overlap between grammars is deliberate,
# so a rule table has something to get wrong.
_GRAMMARS: dict[str, dict[str, tuple[str, ...]]] = {
    "greeting": {
        "opener": ("hello", "hi there", "good morning", "hey", "greetings"),
        "body": ("how are you", "long time no see", "nice to meet you", "welcome back"),
    },
    "question": {
        "opener": ("could you tell me", "i wonder", "do you know", "any idea", "quick question"),
        "body": ("when this ships", "how the refund works", "where my parcel is", "what the price is"),
    },
    "complaint": {
        "opener": ("this is unacceptable", "i am disappointed", "very poor", "not happy", "frustrated"),
        "body": ("the parcel arrived broken", "nobody answered", "it stopped working", "i was charged twice"),
    },
    "order": {
        "opener": ("i would like", "please send", "can i order", "add to my cart", "i need"),
        "body": ("two of the blue ones", "a replacement cable", "the large size", "another box"),
    },
    "farewell": {
        "opener": ("thanks", "that is all", "goodbye", "see you", "cheers"),
        "body": ("have a good day", "until next time", "speak soon", "bye for now"),
    },
}

_NOISE = ("please", "really", "just", "actually", "honestly", "", "", "")


def _row_text(rng: random.Random, category: str) -> str:
    grammar = _GRAMMARS[category]
    parts = [
        rng.choice(grammar["opener"]),
        rng.choice(_NOISE),
        rng.choice(grammar["body"]),
    ]
    return " ".join(p for p in parts if p)


# Noise tokens a perturbation may substitute in. Drawn from `_NOISE` above, and
# deliberately more than one: a row whose own noise token is "really" needs a
# different one, or the "perturbation" is the identity.
_ALTERNATE_NOISE = ("really", "honestly", "just")


def decompose(text: str, label: str) -> tuple[str | None, str | None]:
    """The (opener, body) a row was built from, or `(None, None)` if it was not.

    Longest match wins on both ends, because one opener can prefix another.
    """
    grammar = _GRAMMARS.get(label)
    if grammar is None:
        return None, None
    opener = max((o for o in grammar["opener"] if text.startswith(o)), key=len, default=None)
    body = max((b for b in grammar["body"] if text.endswith(b)), key=len, default=None)
    return opener, body


def perturbations(text: str, label: str) -> dict[str, str]:
    """Label-preserving rewrites of one row, named.

    This lives here, and not in `validity.py`, because only the module that owns
    the grammar can make a rewrite label-preserving *by construction*. A
    perturbation invented outside it is a guess, and the obvious guess is wrong:
    inserting a neutral token after the first word turns `good morning ...` into
    `good really morning ...`, which does not mean what it used to and fails the
    very artifact it was meant to vindicate.

    Two rewrites are structure-free and always offered. `noise_swap` -- the one
    that breaks a rule keyed to an exact training string -- needs the grammar,
    so a row this module can no longer account for gets the other two rather
    than nothing. A grammar edit must degrade the check, not silently disable it.
    """
    rewrites = {"trailing_punct": f"{text}.", "upper": text.upper()}
    opener, body = decompose(text, label)
    if opener is None or body is None:
        return rewrites
    current = text[len(opener):len(text) - len(body)].strip()
    for alternate in _ALTERNATE_NOISE:
        if alternate != current:
            rewrites["noise_swap"] = " ".join(part for part in (opener, alternate, body) if part)
            break
    return rewrites


def generate(seed: int, n: int) -> list[dict]:
    """`n` rows, round-robin over the categories, reproducible for a seed."""
    rng = random.Random(seed)
    rows = []
    for index in range(n):
        category = CATEGORIES[index % len(CATEGORIES)]
        rows.append(
            {
                "id": f"r{index:05d}",
                "text": _row_text(rng, category),
                "label": category,
            }
        )
    return rows


def _split_of(seed: int, row_id: str) -> str:
    """Deterministic 3:1:1 bucket from a hash, so a re-stage cannot move a row."""
    digest = hashlib.sha256(f"{seed}:{row_id}".encode()).hexdigest()
    bucket = int(digest[:8], 16) % sum(SPLIT_WEIGHTS.values())
    for split in SPLITS:
        if bucket < SPLIT_WEIGHTS[split]:
            return split
        bucket -= SPLIT_WEIGHTS[split]
    raise SubstrateError("split weights do not sum to the bucket range")


def stage(state: Path, seed: int, n: int) -> dict[str, int]:
    """Write the three splits and a manifest under `state/corpus/`.

    Assignment is per row, by a hash that depends only on the seed and the row
    id, so a row keeps its split forever: re-staging at a different size adds
    rows and moves none.
    """
    state = Path(state)
    rows = generate(seed, n)
    by_split: dict[str, list[dict]] = {split: [] for split in SPLITS}

    # Assignment is per row, from a hash of (seed, row id) alone — never from a
    # row's position in a list. A positional deal is stable only for one corpus
    # size: growing the corpus mid-search would then hand the gate rows the
    # artifact had already been fitted on, and pull fitted rows out of the
    # reward's denominator, with nothing anywhere reporting it.
    for row in rows:
        by_split[_split_of(seed, row["id"])].append(row)

    corpus_dir = state / "corpus"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    for split in SPLITS:
        split_dir = corpus_dir / split
        split_dir.mkdir(exist_ok=True)
        lines = [json.dumps(row, sort_keys=True) for row in sorted(by_split[split], key=lambda r: r["id"])]
        (split_dir / "rows.jsonl").write_text("\n".join(lines) + "\n" if lines else "")

    counts = {split: len(by_split[split]) for split in SPLITS}
    manifest = {"seed": seed, "n": n, "counts": counts, "categories": list(CATEGORIES)}
    (corpus_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return counts


def load_split(state: Path, split: str) -> list[dict]:
    if split not in SPLITS:
        raise SubstrateError(f"unknown split {split!r}; known: {', '.join(SPLITS)}")
    path = Path(state) / "corpus" / split / "rows.jsonl"
    if not path.is_file():
        raise SubstrateError(f"split {split!r} is not staged: {path} does not exist")
    # Split on "\n" only. splitlines() also splits on U+2028, which JSON leaves
    # raw inside strings, and one such row would read as two broken records.
    return [json.loads(line) for line in path.read_text().split("\n") if line.strip()]


def split_digest(state: Path, split: str) -> str:
    """A hash of the manifest AND the split's own rows.

    The manifest alone is not enough: `stage` writes it last, so an interrupted
    re-stage leaves changed rows under an unchanged manifest — and a cache keyed
    on the manifest then serves a reward measured over rows that no longer
    exist, with every number still looking plausible.
    """
    if split not in SPLITS:
        raise SubstrateError(f"unknown split {split!r}; known: {', '.join(SPLITS)}")
    manifest = Path(state) / "corpus" / "manifest.json"
    if not manifest.is_file():
        raise SubstrateError(f"corpus is not staged: {manifest} does not exist")
    rows = Path(state) / "corpus" / split / "rows.jsonl"
    if not rows.is_file():
        raise SubstrateError(f"split {split!r} is not staged: {rows} does not exist")
    digest = hashlib.sha256()
    digest.update(manifest.read_bytes())
    digest.update(rows.read_bytes())
    return digest.hexdigest()[:16]


def resolve_state_root() -> Path:
    """The state root, from the environment, with three distinct failures.

    Resolved here rather than defaulted anywhere, so a wrong path costs zero
    tokens instead of a night of rollouts scoring against nothing.
    """
    import os

    raw = os.environ.get(STATE_ENV)
    if not raw:
        print(f"substrate: {STATE_ENV} is not set; it must name the experiment's state directory", file=sys.stderr)
        raise SystemExit(EXIT_SUBSTRATE)
    path = Path(raw)
    if not path.is_dir():
        print(f"substrate: {STATE_ENV}={raw} does not exist", file=sys.stderr)
        raise SystemExit(EXIT_SUBSTRATE)
    if not (path / "corpus" / "manifest.json").is_file():
        print(f"substrate: {STATE_ENV}={raw} holds no staged corpus (run `cli stage`)", file=sys.stderr)
        raise SystemExit(EXIT_SUBSTRATE)
    return path
