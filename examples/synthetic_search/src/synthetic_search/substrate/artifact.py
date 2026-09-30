"""Loading the editable artifact, and refusing one that can cheat.

A candidate that can read files can read the labels it is graded against. It
then scores 1.0 and teaches nothing, and the number looks exactly like a real
result. The guard is therefore part of the instrument, not a nicety: it walks
the returned source and rejects anything that could reach outside the text it
was handed.

The guard is an **audited AST denylist, not a sandbox**. It refuses imports, a
few names, dunder attributes, the attributes that reach a frame or an MRO, and
whole constructs no rule table needs (`match`, `yield`, `global`, `class`,
async code) -- each because a route out was found through it. It is audited
against the routes listed in `DESIGN.md`, not proven complete: Python offers
more ways to look an attribute up than an AST walk can enumerate, and the
`match` route was missed by two reviews before a third found it.

It is also not what contains the code. In the rollout, the container is. On the
host, the candidate is executed in-process by whichever `cli` command measures
it -- the scoring subprocess `taskset` starts, or `promote`, `gate`, `adopt` and
`review` in the supervisor's own process -- so on the host the containment
boundary is that process, with its user's files and network. That is a known
limit of this example. For anything beyond it, score where escaping gains
nothing: inside the rollout image, or an isolated container with no network
and no access to the held-out splits.

**Never hand a real module object to the artifact.** A module is a bridge to
everything it imported: CPython's `re` imports `enum`, and `enum` imports
`builtins`, so `re.enum.bltns.open` is `open` again — reached with no import
statement, no denied name and no dunder attribute, and therefore invisible to
every check below. The namespace gets a curated shim instead.

**Never hand two loads an object they share, either.** Every validity pass and
the scoring load the table afresh so that none can tell it is the scored one.
An object both loads can reach and write to -- an attribute on `re.search`, a
class attribute on `re.error` -- is a counter that survives the fresh load and
undoes that. The shim is therefore built anew for every load, and nothing in it
accepts an attribute.
"""

from __future__ import annotations

import ast
import hashlib
import re

from synthetic_search.substrate.errors import CandidateError

UNKNOWN = "unknown"

# Names a rule table has no business touching. `open` and the import hooks reach
# the filesystem; `eval`/`exec`/`compile` reach anything at all.
_DENIED_NAMES = frozenset(
    {"open", "eval", "exec", "compile", "__import__", "globals", "locals", "vars", "input", "breakpoint"}
)

# Attributes that reach an execution frame, or walk to one. A running
# generator's `gi_frame.f_back` is whoever called `classify`, and that frame's
# `f_globals` holds the real builtins and every module the caller imported: a
# way out with no import, no denied name and no dunder. `format` and
# `format_map` are here because a format string walks attributes the guard
# cannot see (`"{0.gi_frame.f_back}".format(g)`); that only ever yields a
# string, but the calling function's name tells the scored pass from the rest.
_DENIED_ATTRIBUTES = frozenset(
    {
        "gi_frame", "cr_frame", "ag_frame", "tb_frame", "tb_next",
        "f_back", "f_globals", "f_locals", "f_builtins",
        "format", "format_map",
        # `re.error.mro()[-1]` is `object`, which a class pattern matches
        # against anything; no rule table needs a class's MRO.
        "mro",
    }
)

# Statements and expressions no rule table needs, refused by node type because
# the attribute checks cannot see what they do. A class pattern's keywords
# (`case O(attr=x)`) look attributes up with no `ast.Attribute` node: that walked
# `__call__`, `__func__`, `__closure__` and `__globals__` to a real
# `__import__`, and to the real `re` module's globals, a writable dict every load
# shares. A generator function supplies the frame a walk starts from (a
# comprehension or generator expression cannot be named inside itself, so those
# stay). `global` is how such a function reaches the generator; classes and
# async code have no use in a table and open more of the same.
_DENIED_NODES = {
    ast.Match: "match",
    ast.Yield: "yield",
    ast.YieldFrom: "yield from",
    ast.AsyncFunctionDef: "async def",
    ast.Await: "await",
    ast.AsyncFor: "async for",
    ast.AsyncWith: "async with",
    ast.Global: "global",
    ast.Nonlocal: "nonlocal",
    ast.ClassDef: "class",
}

# What a rule table legitimately needs. Anything outside this is not available
# at run time, so a source that passes the guard and then reaches for something
# else fails loudly rather than silently returning wrong answers.
_ALLOWED_BUILTINS = (
    "abs", "all", "any", "bool", "dict", "enumerate", "filter", "float", "frozenset",
    "int", "len", "list", "map", "max", "min", "range", "repr", "reversed", "round",
    "set", "sorted", "str", "sum", "tuple", "zip", "True", "False", "None",
)

# What a rule table legitimately uses from `re`. Functions, flags and the error
# class only: a function object's module is not reachable by attribute access,
# while the module object itself carries every module `re` imported.
_RE_FUNCTIONS = (
    "compile", "search", "match", "fullmatch", "findall", "finditer",
    "split", "sub", "subn", "escape",
)
_RE_FLAGS = ("I", "IGNORECASE", "M", "MULTILINE", "S", "DOTALL", "X", "VERBOSE", "A", "ASCII")


def _sealed(fn, error: type):
    """`fn` behind a callable that holds no attribute and accepts none.

    The real `re.search` is one function object shared by every load, and a
    function takes any attribute: `re.search.loads += 1` was a counter that
    survived a fresh load and told a table which load was the scored one. This
    wrapper has empty `__slots__` and keeps `fn` in a closure, reachable only
    through dunder attributes the guard refuses. `re.error` is re-raised as this
    load's own `error`, so `except re.error` still works.
    """

    class _Function:
        __slots__ = ()

        def __call__(self, *args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except re.error as exc:
                raised = error(str(exc))
                raised.msg, raised.pattern, raised.pos = exc.msg, exc.pattern, exc.pos
                raise raised from None

        def __repr__(self) -> str:  # pragma: no cover - debugging aid
            return f"<regex function {fn.__name__}>"

    return _Function()


def regex_namespace():
    """A new stand-in for `re`, holding its functions, flags and error, nothing else.

    Built afresh for every load, so no object in it is shared between two loads:
    a table can only carry state from one load to the next through an object
    both loads can reach. The functions are sealed callables, the flags plain
    `int`s (the real ones are `RegexFlag` members, which take attributes and
    carry the enum's shared member maps), and `error` is a new class each time
    (the real one is a class every load, and `re` itself, would share). The
    instance has empty `__slots__`, so nothing can be added to it or replaced.
    Exposed so it can be tested.
    """
    error = type("error", (Exception,), {"__doc__": "A regular expression that does not compile."})
    members: dict = {name: _sealed(getattr(re, name), error) for name in _RE_FUNCTIONS}
    members.update({name: int(getattr(re, name)) for name in _RE_FLAGS})
    members["error"] = error
    members["__slots__"] = ()
    members["__repr__"] = lambda self: "<regex namespace>"
    return type("_RegexNamespace", (), members)()


def check_source(source: str) -> None:
    """Raise `CandidateError` naming the offending construct, or return None.

    Every message names the line, because the agent reads it and a rejection it
    cannot locate costs a turn.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise CandidateError(f"the artifact does not parse: line {exc.lineno}: {exc.msg}") from exc

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise CandidateError(
                f"line {node.lineno}: import is not allowed in the artifact; `re` is already in scope"
            )
        if isinstance(node, ast.Name) and node.id in _DENIED_NAMES:
            raise CandidateError(f"line {node.lineno}: `{node.id}` is not allowed in the artifact")
        if isinstance(node, ast.Attribute):
            _check_attribute(node.attr, node.lineno)
        # Refused by `_DENIED_NODES` today; checked anyway in case `match` is
        # ever allowed again, because these ARE attribute lookups.
        if isinstance(node, ast.MatchClass):
            for attr in node.kwd_attrs:
                _check_attribute(attr, node.lineno)
        construct = _DENIED_NODES.get(type(node))
        if construct is not None:
            raise CandidateError(f"line {node.lineno}: `{construct}` is not allowed in the artifact")


def _check_attribute(attr: str, lineno: int) -> None:
    if (attr.startswith("__") and attr.endswith("__")) or attr in _DENIED_ATTRIBUTES:
        hint = "; use an f-string" if attr in ("format", "format_map") else ""
        raise CandidateError(f"line {lineno}: attribute `{attr}` is not allowed in the artifact{hint}")


def load(source: str):
    """Check the source, execute it in a restricted namespace, return `classify`."""
    check_source(source)
    import builtins

    namespace = {
        "re": regex_namespace(),
        "__builtins__": {name: getattr(builtins, name) for name in _ALLOWED_BUILTINS if hasattr(builtins, name)},
    }
    try:
        exec(compile(source, "<artifact>", "exec"), namespace)  # noqa: S102 - the guard above is the gate
    except Exception as exc:  # the candidate's own code failing is the candidate's problem
        raise CandidateError(f"the artifact raised while loading: {exc!r}") from exc

    classify = namespace.get("classify")
    if not callable(classify):
        raise CandidateError("the artifact defines no callable `classify`")
    return classify


def digest(source: str) -> str:
    """The artifact's half of the cache key."""
    return hashlib.sha256(source.encode()).hexdigest()[:16]
