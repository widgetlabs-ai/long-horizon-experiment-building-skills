"""The editable artifact and the guard that keeps it from reading its own labels."""

from pathlib import Path

import pytest

from synthetic_search.substrate import artifact
from synthetic_search.substrate.errors import CandidateError

ARTIFACT = Path(__file__).resolve().parents[1] / "artifact" / "rules.py"


def test_check_source_rejects_import():
    with pytest.raises(CandidateError, match="import"):
        artifact.check_source("import json\ndef classify(t): return 'a'")


def test_check_source_rejects_from_import():
    with pytest.raises(CandidateError, match="import"):
        artifact.check_source("from pathlib import Path\ndef classify(t): return 'a'")


def test_check_source_rejects_open():
    with pytest.raises(CandidateError, match="open"):
        artifact.check_source("def classify(t): return open('/labels').read()")


def test_check_source_rejects_eval():
    with pytest.raises(CandidateError, match="eval"):
        artifact.check_source("def classify(t): return eval('1')")


def test_check_source_rejects_dunder_access():
    with pytest.raises(CandidateError):
        artifact.check_source("def classify(t): return ().__class__.__bases__")


def test_check_source_names_the_line():
    with pytest.raises(CandidateError, match="line 2"):
        artifact.check_source("def classify(t):\n    return open('x')\n")


def test_check_source_accepts_the_shipped_rules():
    artifact.check_source(ARTIFACT.read_text())


def test_load_returns_a_working_classifier():
    classify = artifact.load(ARTIFACT.read_text())
    assert classify("hello how are you") == "greeting"


def test_load_returns_unknown_for_unmatched_text():
    classify = artifact.load(ARTIFACT.read_text())
    assert classify("zzzz qqqq") == artifact.UNKNOWN


def test_load_refuses_a_guarded_source():
    with pytest.raises(CandidateError):
        artifact.load("import os\ndef classify(t): return 'a'")


def test_load_refuses_a_source_without_classify():
    with pytest.raises(CandidateError, match="classify"):
        artifact.load("RULES = []")


def test_digest_changes_with_the_source():
    assert artifact.digest("a") != artifact.digest("b")


def test_digest_is_stable():
    assert artifact.digest("a") == artifact.digest("a")


# The guard's whole purpose is that a table cannot reach the labels it is
# graded against. `re` is handed to the artifact, and a real module object is a
# bridge: CPython's re imports enum, and enum imports builtins. No import
# statement, no denied name, no dunder — and `open` is back.
CHEAT_VIA_RE = '''
_B = re.enum.bltns
def classify(text):
    return _B.open("/etc/hostname").read()
'''


def test_the_re_handed_in_is_not_a_bridge_to_builtins():
    with pytest.raises(CandidateError):
        classify = artifact.load(CHEAT_VIA_RE)
        classify("anything")


def test_re_exposes_no_module_attributes():
    classify = artifact.load(ARTIFACT.read_text())
    namespace_re = artifact.regex_namespace()
    for escape_hatch in ("enum", "functools", "copyreg", "sys", "os"):
        assert not hasattr(namespace_re, escape_hatch), escape_hatch


def test_re_still_does_what_a_rule_table_needs():
    source = "def classify(t):\n    return 'hit' if re.search(r'\\bfoo\\b', t, re.I) else 'miss'\n"
    classify = artifact.load(source)
    assert classify("a FOO b") == "hit"
    assert classify("bar") == "miss"


_RE_CALLABLES = ("compile", "search", "match", "fullmatch", "findall", "finditer", "split", "sub", "subn", "escape")


@pytest.mark.parametrize("name", _RE_CALLABLES)
def test_no_re_function_accepts_an_attribute(name):
    # A function object takes any attribute, and the real `re.search` is shared
    # by every load: an attribute on it is a counter that survives a fresh load.
    with pytest.raises(CandidateError):
        artifact.load(f"re.{name}.loads = 1\ndef classify(t):\n    return 'unknown'\n")


@pytest.mark.parametrize("name", ("I", "IGNORECASE", "M", "MULTILINE", "S", "DOTALL", "X", "VERBOSE", "A", "ASCII"))
def test_no_re_flag_accepts_an_attribute(name):
    # The real flags are `RegexFlag` members, which take attributes and carry
    # the enum's shared member maps.
    with pytest.raises(CandidateError):
        artifact.load(f"re.{name}.loads = 1\ndef classify(t):\n    return 'unknown'\n")


def test_re_error_carries_nothing_from_one_load_to_the_next():
    source = (
        "try:\n"
        "    re.error.loads += 1\n"
        "except:\n"
        "    re.error.loads = 1\n"
        "N = re.error.loads\n"
        "def classify(t):\n"
        "    return N\n"
    )
    assert [artifact.load(source)("x") for _ in range(3)] == [1, 1, 1]


def test_no_load_shares_a_namespace_object_with_another():
    first, second = artifact.regex_namespace(), artifact.regex_namespace()
    assert first is not second
    for name in _RE_CALLABLES + ("error",):
        assert getattr(first, name) is not getattr(second, name), name


def test_re_error_still_catches_a_bad_pattern():
    source = (
        "def classify(t):\n"
        "    try:\n"
        "        re.compile(t)\n"
        "    except re.error:\n"
        "        return 'bad'\n"
        "    return 'good'\n"
    )
    classify = artifact.load(source)
    assert classify("(") == "bad"
    assert classify("a+") == "good"


def test_re_flags_still_combine():
    classify = artifact.load("def classify(t):\n    return bool(re.search('^b', t, re.I | re.M))\n")
    assert classify("a\nB") is True


# A running generator's frame is reachable with no dunder: `gi_frame`, then
# `f_back` to whoever called `classify`, then that module's `f_globals` -- which
# hold the real builtins, `open` among them, and every module the substrate
# imported. That is both a way out and an object shared between loads.
FRAME_ESCAPE = '''
def _peek():
    yield _g.gi_frame.f_back.f_back.f_globals
def classify(text):
    global _g
    _g = _peek()
    for found in _g:
        return found["__builtins__"]["open"]
'''

# The same walk inside a format string, where the guard cannot see it. It only
# ever yields a string, but the calling function's name is enough to tell the
# scoring pass from a validity pass.
FORMAT_ORACLE = '''
def _peek():
    yield "{0.gi_frame.f_back.f_back.f_code.co_name}".format(_g)
def classify(text):
    global _g
    _g = _peek()
    for caller in _g:
        return "unknown" if caller == "_safe" else "billing"
'''


def test_a_generator_frame_is_not_a_way_out():
    # Refused twice over: `global` and `yield` by node type, and the frame walk
    # by attribute, which is what this pins -- with the node refusals lifted.
    with pytest.raises(CandidateError, match="`(global|yield)` is not allowed"):
        artifact.load(FRAME_ESCAPE)


def test_a_generator_frame_walk_is_refused_by_attribute_too(monkeypatch):
    monkeypatch.setattr(artifact, "_DENIED_NODES", {})
    # The walk reports the outermost attribute of the chain first.
    with pytest.raises(CandidateError, match="line 3: attribute `f_globals` is not allowed"):
        artifact.load(FRAME_ESCAPE)


def test_a_format_string_cannot_walk_to_a_frame():
    with pytest.raises(CandidateError, match="`(global|yield)` is not allowed"):
        artifact.load(FORMAT_ORACLE)


def test_a_format_string_walk_is_refused_by_attribute_too(monkeypatch):
    monkeypatch.setattr(artifact, "_DENIED_NODES", {})
    with pytest.raises(CandidateError, match="attribute `format` is not allowed"):
        artifact.load(FORMAT_ORACLE)


@pytest.mark.parametrize(
    "attr", ("gi_frame", "cr_frame", "ag_frame", "tb_frame", "tb_next", "f_back", "f_globals", "f_locals", "f_builtins", "format", "format_map")
)
def test_every_frame_reaching_attribute_is_refused(attr):
    with pytest.raises(CandidateError, match=f"line 2: attribute `{attr}` is not allowed"):
        artifact.check_source(f"def classify(t):\n    return t.{attr}\n")


# A class pattern's keywords (`case O(attr=x)`) look attributes up with no
# `ast.Attribute` node, so an attribute check alone never sees them, and
# `re.error.mro()[-1]` is `object`, which matches anything. Each of these ran.
MATCH_FRAME_WALK = '''
O = re.error.mro()[-1]
def _peek():
    match _g:
        case O(gi_frame=fr):
            pass
    match fr:
        case O(f_back=b):
            pass
    match b:
        case O(f_back=bb):
            pass
    match bb:
        case O(f_globals=gl, f_builtins=fb):
            yield fb
def classify(text):
    global _g
    _g = _peek()
    for fb in _g:
        return fb["open"]
'''

MATCH_CLOSURE_IMPORT = '''
O = re.error.mro()[-1]
def classify(text):
    match re.search:
        case O(__call__=call):
            pass
    match call:
        case O(__func__=f):
            pass
    match f:
        case O(__closure__=cl):
            pass
    for cell in cl:
        match cell:
            case O(cell_contents=v):
                match v:
                    case O(__globals__=g):
                        return g["__builtins__"]["__import__"]("os").getcwd()
    return "unknown"
'''

MATCH_SUBCLASSES = '''
O = re.error.mro()[-1]
def classify(text):
    match O:
        case O(__subclasses__=sc):
            return len(sc())
'''

MATCH_FORMAT = '''
O = re.error.mro()[-1]
def classify(text):
    match "{0.__class__}":
        case O(format=f):
            return f(text)
'''


@pytest.mark.parametrize(
    "source", (MATCH_FRAME_WALK, MATCH_CLOSURE_IMPORT, MATCH_SUBCLASSES, MATCH_FORMAT), ids=("b1", "b2", "b3", "b4")
)
def test_a_match_class_pattern_is_not_a_way_out(source):
    with pytest.raises(CandidateError, match="is not allowed in the artifact"):
        artifact.load(source)


@pytest.mark.parametrize(
    "source, construct",
    (
        ("def classify(t):\n    match t:\n        case _:\n            return 'unknown'\n", "match"),
        ("def g():\n    yield 1\ndef classify(t):\n    return 'unknown'\n", "yield"),
        ("def g():\n    yield from [1]\ndef classify(t):\n    return 'unknown'\n", "yield from"),
        ("async def g():\n    return 1\ndef classify(t):\n    return 'unknown'\n", "async def"),
        ("async def g(x):\n    await x\ndef classify(t):\n    return 'unknown'\n", "async def"),
        ("N = 0\ndef classify(t):\n    global N\n    return 'unknown'\n", "global"),
        ("def classify(t):\n    n = 0\n    def f():\n        nonlocal n\n    return 'unknown'\n", "nonlocal"),
        ("class C:\n    pass\ndef classify(t):\n    return 'unknown'\n", "class"),
        ("def classify(t):\n    return re.error.mro()\n", "mro"),
    ),
)
def test_constructs_no_rule_table_needs_are_refused(source, construct):
    with pytest.raises(CandidateError, match=rf"line \d+: (attribute )?`{construct}` is not allowed in the artifact"):
        artifact.check_source(source)


@pytest.mark.parametrize("construct", ("await", "async for", "async with"))
def test_every_async_construct_is_refused_on_its_own(construct, monkeypatch):
    # `async def` is refused first in any real source; take it out of the way
    # to show the others are refused by themselves, should it ever come back.
    denied = {k: v for k, v in artifact._DENIED_NODES.items() if v != "async def"}
    monkeypatch.setattr(artifact, "_DENIED_NODES", denied)
    body = {"await": "await x", "async for": "async for y in x:\n        pass", "async with": "async with x:\n        pass"}
    source = f"async def g(x):\n    {body[construct]}\ndef classify(t):\n    return 'unknown'\n"
    with pytest.raises(CandidateError, match=f"line 2: `{construct}` is not allowed in the artifact"):
        artifact.check_source(source)


@pytest.mark.parametrize("attr", ("__call__", "gi_frame", "format", "mro"))
def test_class_pattern_keywords_are_checked_even_if_match_were_allowed(attr, monkeypatch):
    denied = {k: v for k, v in artifact._DENIED_NODES.items() if v != "match"}
    monkeypatch.setattr(artifact, "_DENIED_NODES", denied)
    source = f"def classify(t):\n    match t:\n        case str({attr}=x):\n            return 'unknown'\n"
    with pytest.raises(CandidateError, match=f"line 3: attribute `{attr}` is not allowed in the artifact"):
        artifact.check_source(source)


def test_the_format_refusal_points_at_f_strings():
    with pytest.raises(CandidateError, match="f-string"):
        artifact.check_source("def classify(t):\n    return '{}'.format(t)\n")


def test_comprehensions_and_generator_expressions_are_still_allowed():
    source = (
        "def classify(t):\n"
        "    words = [w for w in t.split()]\n"
        "    if any(w == 'hello' for w in words):\n"
        "        return 'greeting'\n"
        "    return {k: v for k, v in [('a', 'unknown')]}['a']\n"
    )
    classify = artifact.load(source)
    assert classify("hello there") == "greeting"
    assert classify("x") == "unknown"


def test_re_sub_takes_a_backreference_template():
    # `Pattern.sub` with a template raises KeyError('__import__') here: CPython's
    # `_sre` imports `re` lazily to expand it, and the builtins have no import.
    # `re.sub(pattern, template, text)` compiles the template outside the
    # artifact, so it works; DESIGN.md tells an honest table to use it.
    classify = artifact.load("def classify(t):\n    return re.sub('(a)', r'<\\1>', t)\n")
    assert classify("cat") == "c<a>t"


def test_a_pattern_groupindex_carries_nothing_between_loads():
    # With no named groups it is a new, writable dict on every access; with
    # named groups a read-only view. Either way, no counter survives a load.
    source = (
        "g = re.compile('abc').groupindex\n"
        "g['n'] = g.get('n', 0) + 1\n"
        "N = g['n']\n"
        "def classify(t):\n"
        "    return N\n"
    )
    assert [artifact.load(source)("x") for _ in range(3)] == [1, 1, 1]
