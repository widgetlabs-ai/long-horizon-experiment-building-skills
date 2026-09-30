# The spine

The vocabulary every long-horizon search shares, and the exact shapes
`experiment.py` returns. The renderer knows these five nouns and nothing else;
everything particular to one experiment arrives through `extras()`.

```
run           one generation's eval output      runs(), run_mtime(), run_rollout_count()
rollout       one container, one agent          rollouts(run), rollout_trace(run, id)
promotion     an adopted winner                 promotions()
gate          the held-out check on a winner    gate()
review        a stronger model's veto           reviews()  (optional)
candidate     a returned artifact, scored       candidates()
extras        everything else                   extras()
notes         prose explaining each section     notes()
```

Read `Long-Horizon-Search-Field-Guide.md` for what these mean in a search. This
file is only the data contract.

## Rules that hold for every function

- **Read from disk on every call.** No caching, no module-level data. The viewer
  is stateless by design: a request shows what is on disk now.
- **Never raise on missing data.** A file that does not exist yet returns `{}`,
  `[]` or `None`, and the section renders empty. An experiment mid-run has not
  written everything, and a viewer that 500s during a run is a viewer nobody
  opens during a run.
- **Never write a measured number into the source.** See `check_literals.py`.
- **Use `lib.read_jsonl_counted` for every `.jsonl`.** It splits on `"\n"` only.
  `splitlines()` also splits on U+2028, which JSON leaves raw inside strings and
  agent transcripts are full of — that bug made every run read as zero episodes.
- A missing *optional* value is `None`, never `0`. On a dashboard `0` is a
  reading; `None` renders as `—`.
- **A value the host never measured is `None`, even when the file says `0.0`.**
  Scorers commonly start a report from a default (`reward: 0.0`) and fail
  before overwriting it — a build error, a crash in scoring. Read the report's
  own failure flags and return `None` on those rollouts and candidates. A
  rule-table experiment once showed three failed candidates as `0.00000`,
  indistinguishable from a rule table that scored exactly zero. The rule is
  not only for `reward` and `gain`. It applies to **every** figure you put on
  the page:
  - a class mean over zero categories, which `class_means` writes as `0.0`;
  - a per-category score for a category with no held-out rows, which the gate
    writes as `0.0`;
  - a turn count for a trace with no message graph.
  For each figure, find the line in the writer that produces its fallback, and
  return `None` on that path.

## Module constants

```python
NAME              str            short experiment name, shown in the header
STATE_DIR         Path           the experiment's state dir
OUTPUTS_DIR       Path           where one run dir per generation lands
DOCKER_IMAGE      str | None     live probe: `docker ps --filter ancestor=…`
PROCESS_PATTERN   str | None     live probe: `pgrep -af <pattern>`
LOG_GLOB          (Path, str)    (directory, glob) for the supervisor's logs
GENERATION_RE     str | None     regex with one group, the generation number
```

The four optional probes may each be `None`; the card then says "unavailable"
rather than drawing a zero that reads as "nothing is running".

## runs

```python
runs()                  -> list[str]     # run ids, newest first; every run dir
run_mtime(run_id)       -> str           # ISO seconds, "" when unknown
run_rollout_count(id)   -> int           # cheap; must not parse the trace file
```

`run_rollout_count` is called for the live cards on every poll. Count lines;
do not parse.

List **every** run directory, including one with no trace file: an eval that
died before writing its first episode is exactly what someone watching the
search needs to see. It must not be left off the list.

The renderer does not show such a run as `0 · 0 · 0`: that reads as "nothing
went wrong", the opposite of what happened. `app.py` marks a run with no
episode and no unreadable line **eval died** when it is not the newest run, or
when it is the newest and `PROCESS_PATTERN` matches nothing. The newest run
reads **running** while the process is up, since an eval that is starting has no
episodes yet either. When `PROCESS_PATTERN` is `None`, the newest empty run
cannot be judged and stays unmarked. So make `PROCESS_PATTERN` match the
process that outlives one generation, e.g. the supervisor loop, and not a
single eval.

The runs table's `fail` counts rollouts with `ok: false`. Find out from the
framework what sets that, and say it in `notes()["runs"]`. In verifiers it is a
framework failure: the sandbox did not start, the rollout ran past its time
budget, the model or harness crashed, or scoring threw. A bad candidate or a
turn-limit stop is a task outcome and never a fail. Without that sentence, a
column of zeros over a search full of failed builds looks like a bug.

## rollouts

```python
rollouts(run_id) -> (list[rollout], int)      # summaries, count of unreadable lines
```

The second element is how many lines of the trace file did not parse. While a
run is live the last line is usually a record being written right now — it is
reported, not hidden and not raised.

```python
rollout = {
  "id":      str,           # short, stable within the run
  "ok":      bool,
  "errors":  list[str],
  "stop":    str | None,    # why the episode ended
  "turns":   int | None,
  "reward":  float | None,  # this rollout's measured score
  "gain":    float | None,  # reward minus the current baseline
  "verdict": str | None,    # what the host made of what came back
  "label":   str | None,    # which sub-problem it worked on
  "detail":  list[str],     # free strings, shown as a count with a hover
}
```

`verdict` is a short free string. `"scored"` renders neutral; anything else
renders as a problem. Typical set: `scored`, `unchanged`, `build failed`,
`out of scope`, `error`.

Derive it from the host's flags **most specific first**, and check the order
against the writer: a writer may set a general flag alongside a specific one.
`synthetic_search`'s own `ZERO_REASONS` (`evaluate.py:16-21`, read by
`experiment.py`'s `_verdict`) are mutually exclusive by construction —
`measure.measure_source` returns at the first one it hits — but that is a
property of this writer, not something a viewer may assume: check the order
against the writer it is reading, the same way, every time. Every verdict the
legend names must be producible from some path of the writer.

```python
rollout_trace(run_id, rollout_id) -> dict | None
{
  "id", "ok", "errors", "stop",
  "rewards":  dict,
  "metrics":  dict,
  "tools":    list[str],
  "calls":    list[dict],
  "nodes":    [{"role": str,
                "content": str,
                "tool_calls": [{"name", "input", "call_id"}]}],
}
```

**Read this from the harness's own trace file.** Do not normalise the trace into
a format of your own: one generation is megabytes, and the format is not yours
to own. Truncate long content — the original viewer used 4000 characters per
message and 1200 per tool input.

## promotions

The reward curve. One record per adopted winner, in order.

```python
promotion = {
  "generation": int,
  "id":         str,
  "reward":     float,          # the measure the search optimises
  "baseline":   float | None,   # the level before the search began
  "gain":       float | None,
  "held_out":   float | None,   # the same measure on data never searched on
  "detail":     list[str],
}
```

`baseline` is read from the first record and drawn as the dashed line and the
`start` point one generation before the first promotion. Later records may
repeat or omit it.

## gate

The most recent held-out check, or `None` when there has not been one.

```python
gate = {
  "generation": int,
  "passed":     bool,
  "before":     float | None,
  "after":      float | None,
  "failures":   list[str],
}
```

If the experiment has no gate, return `None`. **Never derive one.**

## reviews

**Optional.** One entry per review a stronger model made of a gated candidate,
**newest first**. An experiment with no reviewer stage defines no `reviews()`;
`/api/state["reviews"]` is then `[]` and the page shows no reviews section.

```python
review = {
  "generation": int | None,
  "trace":      str | None,
  "refused":    bool,          # the record's decision == "refuse"
  "cited":      bool,
  "concern":    str | None,
  "quote":      str | None,
  "reason":     str | None,
  "note":       str | None,
  "model":      str | None,
  "at":         str | None,
  "runaway":    bool,
}
```

A field absent from the record is `None`, never a default: a review with no
`quote` has no quote, and a made-up empty string would read as one the reviewer
gave. `reviews()` must read the file with `read_jsonl` (or `read_jsonl_counted`)
and never with a raw `json.loads` per line, because the reviews writer appends
non-atomically and a torn last line is normal while a run is live.

## candidates

Everything a rollout returned that was scored, adopted or not. **Newest
first**: the list grows by one per rollout for the whole search, and the page
shows the first few and folds the rest behind a verdict filter and "show all".

Sort by the mtime of one **file** in the candidate's directory, never by the
directory's own mtime. Later stages write into the candidate's directory:
`synthetic_search`'s `finalize` creates the directory and copies the artifact
source into it, and `score` merge-writes `candidate.json` there afterward —
either write bumps the directory's mtime and scrambles the order. Pick the
file the code tells you every candidate has, and check how often it is
written. `candidate.json` is merge-written twice (`finalize`, then `score`),
so it is not a write-once file. Its mtime is still a sound key, because every
candidate's last write is `score`, in the order the candidates were scored;
the example's `_candidate_time` sorts by it, and falls back to the newest file
in a directory `finalize` left before any record existed. If a file that is
written only at creation exists (the returned artifact, say), that is an
equally good key; a record that is rewritten at unpredictable times is not.

```python
candidate = {
  "id":      str,
  "label":   str | None,
  "reward":  float | None,
  "verdict": str | None,
  "detail":  list[str],
  "status":  str | None,     # free text, shown on hover
}
```

## extras

Everything the experiment measures that the spine has no word for. Blocks
describe themselves; the renderer knows nothing about them, which is what keeps
a new measurement from needing a UI change.

```python
{"kind": "kv",     "title": str, "note": str | None,
 "rows": [[label, value], ...]}

{"kind": "table",  "title": str, "note": str | None,
 "columns": [str], "rows": [[cell, ...], ...]}

{"kind": "series", "title": str, "note": str | None,
 "points": [[x, y], ...]}
```

Every block may also carry `"place"`, which picks where it renders:

```python
"place": "top"          # default — under the live cards, above the drill-down
       | "promotions"   # under the reward curve and gate
       | "candidates"   # under the candidates list
```

Put the headline state of the search at the top (current baselines) and a
breakdown next to what it breaks down — `synthetic_search`'s per-class table
sits under the reward curve, whose reward it splits by class. `smoke.py` fails
an unknown place.

**A per-item table shows only the items that moved.** A gate report often
records every held-out item, e.g. every val category before and after. When the gate
passes and nothing moved, a table of all of them is rows of identical figures
that repeat the one line the gate section already shows. List only the items
whose value changed or that failed, worst first, and return no block at all
when there are none. Say in the note that the rest scored exactly their
baseline.

**A breakdown covers every split the experiment measures, and says where it
started.** When the baselines exist for both the searched split and the
held-out one, give each its own column. Put a whole-split row first, whose
figure is the one the curve plots or the gate defends. Next to a count
that has changed since the first promotion, show the starting value too
(`17 ← 25`), so a row reads as progress and not as a snapshot. A category
that no item carries any more is a result, so say so in words (`clean`)
rather than rendering `—` as if it were missing data.

A cell is a scalar, or:

```python
{"text":  str | float,
 "fmt":   "score" | "int" | None,   # see below
 "class": "ok" | "bad" | "warn" | "muted" | "tiny",
 "title": str,                      # hover text
 "spark": [[x, y], ...],            # sparkline drawn inside the cell
 "spark_stroke": str}               # optional colour
```

`fmt` decides how a number reads. By default an integer renders as an integer
and a fraction to five decimals — 32 categories is `32`, not `32.00000`. Mark a cell
`"score"` when the value is a measurement that merely happens to be whole, so a
perfect 1 still renders as `1.00000` instead of looking like a count.

A sparkline scales to its own range, so it carries the *shape* of a series and
not its size — put the figures in `title`. Plot a series that **rises when things
get better**; if the natural measure falls, plot what has been fixed rather than
what is left, and say so in the note. Nothing here should ever be read off an
inverted axis.

Domain prose belongs in `note` (or in `notes()`), never in the HTML. Return `[]` when there is
nothing beyond the spine.

## notes

The legend for each spine section, in the experiment's own vocabulary — what a
column means, what each verdict means, why a run stops. The page carries no
prose of its own, so this is the only place the spine sections get explained.

```python
notes() -> {section: note}      # section: live | runs | rollouts | promotions | gate | candidates | reviews
note = str
     | {"text": str | None, "terms": [[term, definition], ...]}   # terms: a glossary
```

Rendered as plain text above the section. A section with no note renders
nothing; return `{}` for none. `smoke.py` fails a section name the page has no
slot for, so a typo cannot silently render nowhere.

**No measured figures in note prose.** A number typed into a sentence goes
stale exactly like one typed into code, and nobody rereads a legend: a
hand-written viewer once still said "100 rows per split" after the corpus was
regenerated at a different size. When a note needs a figure — a turn limit, a
rollout count — read it at call time (a config, the newest supervisor log) and
interpolate it, and leave the sentence out when the figure cannot be found. A
figure that lives only in the experiment's source (a tolerance constant) is
described, not quoted. A metric's *name* is not a figure — "macro-F1", "R2"
and "P95" are fine typed in directly. `check_literals.py` flags a standalone
numeral or a decimal in a string literal inside `notes()` and in any extras
block's `"note"`, but lets a digit stand when it is bound directly to a
letter. A **hyphenated** name — "top-5", "BLEU-4" — does not qualify: the hyphen
between the letter and the digit reads as a figure and the check refuses it
in note prose, correctly, since a hyphen before a digit is just as often a
real minus or a range. Put a hyphenated metric's name in an extras block's
`"title"` instead, which the check does not scan — do not loosen the rule to
let it through in a note.
