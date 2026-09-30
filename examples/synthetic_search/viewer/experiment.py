"""THE ONLY FILE THE SCAFFOLDER WRITES.

Everything here maps synthetic_search's own files onto the spine that `app.py`
and `static/index.html` render. Nothing else in the generated viewer should
need editing, and when the experiment's state layout later changes, this is the
file to change.

The spine, in full — see `reference/spine.md` for the field-by-field contract:

    run           one generation's eval output     runs(), run_mtime(), run_rollout_count()
    rollout       one container, one agent         rollouts(run), rollout_trace(run, id)
    promotion     an adopted winner                promotions()
    gate          the held-out check on a winner   gate()
    review        a stronger model's veto          reviews()  (optional)
    candidate     a returned artifact, scored      candidates()
    extras        everything else, self-describing extras()

THE RULE THIS FILE EXISTS TO KEEP: return values read from files at call time.
Never write a measured number into this file as a literal. Every figure on the
page must be traceable to a file on disk at the moment of the request — that is
what makes the dashboard an instrument rather than a report. `check_literals.py`
enforces it; it is not decoration.

Where each file comes from (the writer map; `fixtures/SOURCES.md` has it whole):

    outputs/<run>/traces.jsonl              verifiers `write_episode` (cli/output.py), one Episode per line
    state/candidates/<trace>/candidate.json `taskset_contract.record_candidate`, from `finalize` then `score`
    state/candidates/<trace>/rules.py       `SyntheticTask.finalize` (taskset.py)
    state/candidates/<trace>/status.txt     `SyntheticTask.finalize` (taskset.py)
    state/promotions.jsonl                  `promote.adopt` (append)
    state/gate_report.json                  `regression_gate.gate`
    state/reviews.jsonl                     `review._record` (append), only when review is enabled
    state/baseline_{train,val,test}.json    `cli._baseline`, and `promote.write_baseline` for train/val on adopt
    state/instrument.json                   `cli._pin`
    state/corpus/manifest.json              `corpus.stage`
    state/runs/supervisor.log               `supervisor.sh` (`exec >>"$LOG"`)
"""

from __future__ import annotations

import os
from pathlib import Path

from lib import count_lines, mtime, read_json, read_jsonl, read_jsonl_counted

# --------------------------------------------------------------------- where

NAME = "synthetic_search"
# The experiment root: <experiment>/viewer/.. by default. VIEWER_EXPERIMENT_ROOT
# points the viewer at any other root holding state/ and outputs/ — the committed
# fixtures (`VIEWER_EXPERIMENT_ROOT=fixtures`), a B output, or a copy of a real
# run. A relative value resolves against this directory, not the cwd.
_HERE = Path(__file__).resolve().parent
ROOT = (_HERE / os.environ["VIEWER_EXPERIMENT_ROOT"]).resolve() if os.environ.get("VIEWER_EXPERIMENT_ROOT") else _HERE.parent
# supervisor.sh: SYNTH_STATE defaults to $EXPERIMENT/state, SYNTH_OUTPUTS to $EXPERIMENT/outputs.
STATE_DIR = ROOT / "state"
OUTPUTS_DIR = ROOT / "outputs"

# config.*.toml: [runtime] image. The supervisor loop outlives one generation;
# a single `uv run eval` does not, so the pattern names the supervisor.
DOCKER_IMAGE = "synthetic-search:pinned"
PROCESS_PATTERN = "supervisor.sh"
LOG_GLOB = (STATE_DIR / "runs", "*.log")
GENERATION_RE = r"^--- generation (\d+)\b"

# evaluate.ZERO_REASONS, most specific first. `measure.measure_source` returns at
# the first one it hits and `SyntheticTask.score`'s no-artifact path sets only
# `artifact_unchanged`, so on this writer they never stack; the order is kept
# anyway so a writer that starts stacking them cannot turn a guard rejection
# into a generic label.
ZERO_REASONS = ("guard_rejected", "validity_failed", "score_error", "artifact_unchanged")

# ------------------------------------------------------------------ helpers

def _short(value) -> str:
    return str(value or "")[:12]


def _zero_reason(metrics: dict) -> str | None:
    for reason in ZERO_REASONS:
        if metrics.get(reason):
            return reason
    return None


def _baseline_reward(split: str) -> float | None:
    return read_json(STATE_DIR / f"baseline_{split}.json").get("reward")


def _traces_file(run_id: str) -> Path:
    return OUTPUTS_DIR / run_id / "traces.jsonl"


def _first_trace(episode: dict) -> dict | None:
    traces = episode.get("traces")
    return traces[0] if isinstance(traces, list) and traces else None


def _trace_reward(trace: dict) -> float | None:
    """`score * weight` over `trace.rewards`, as `selftest.trace_reward` reads it.

    `SyntheticTask.score` records `report["reward"] or 0.0`, so a rollout the
    host never measured still carries a reward of zero. The metrics' own flags
    say which rollouts those are, and they read `None` here.
    """
    if _zero_reason(trace.get("metrics") or {}):
        return None
    rewards = trace.get("rewards")
    if not isinstance(rewards, dict):
        return None
    total, seen = None, False
    for reward in rewards.values():
        if isinstance(reward, dict) and "score" in reward:
            total = (total or 0) + reward["score"] * reward.get("weight", 1)
            seen = True
    return total if seen else None


def _errors(*holders) -> list[str]:
    out = []
    for holder in holders:
        for err in (holder or {}).get("errors") or []:
            if isinstance(err, dict):
                out.append(f"{err.get('type', 'Error')}: {err.get('message', '')}")
            else:
                out.append(str(err))
    return out


def _rollout_verdict(episode: dict, trace: dict | None) -> str | None:
    if trace is None:
        return "no trace"
    if not trace.get("ok"):
        return "error"
    metrics = trace.get("metrics") or {}
    reason = _zero_reason(metrics)
    if reason:
        return reason
    if not any(name in metrics for name in ZERO_REASONS):
        return "no report"
    return "scored"


def _turns(trace: dict | None) -> int | None:
    """Sampled nodes. A trace with no message graph has no turn count."""
    nodes = (trace or {}).get("nodes") or []
    if not nodes:
        return None
    return sum(1 for node in nodes if node.get("sampled"))


def _task_data(episode: dict, trace: dict | None) -> dict:
    task = (trace or {}).get("task") or episode.get("task") or {}
    data = task.get("data")
    return data if isinstance(data, dict) else {}


def _gain(reward: float | None, baseline: float | None) -> float | None:
    if reward is None or baseline is None:
        return None
    return reward - baseline


# ---------------------------------------------------------------------- runs

def runs() -> list[str]:
    """Run ids, newest first. One run = one generation's eval output.

    Every run directory, by its own mtime, the same order `latest_run` in
    supervisor.sh uses — including one with no trace file yet.
    """
    if not OUTPUTS_DIR.is_dir():
        return []
    dirs = [p for p in OUTPUTS_DIR.iterdir() if p.is_dir()]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [p.name for p in dirs]


def run_mtime(run_id: str) -> str:
    return mtime(OUTPUTS_DIR / run_id)


def run_rollout_count(run_id: str) -> int:
    """Cheap count for the live cards — must not parse the whole trace file."""
    return count_lines(_traces_file(run_id))


# ------------------------------------------------------------------ rollouts

def rollouts(run_id: str) -> tuple[list[dict], int]:
    """(rollout summaries, count of unreadable lines)."""
    episodes, unreadable = read_jsonl_counted(_traces_file(run_id))
    baseline = _baseline_reward("train")
    out = []
    for episode in episodes:
        trace = _first_trace(episode)
        reward = _trace_reward(trace) if trace else None
        data = _task_data(episode, trace)
        out.append({
            "id": _short((trace or {}).get("id") or episode.get("id")),
            "ok": bool(episode.get("ok")) and bool((trace or {}).get("ok")),
            "errors": _errors(episode, trace),
            "stop": (trace or {}).get("stop_condition"),
            "turns": _turns(trace),
            "reward": reward,
            "gain": _gain(reward, baseline),
            "verdict": _rollout_verdict(episode, trace),
            "label": data.get("task_class") or None,
            "detail": [f"{len(episode.get('traces') or [])} trace(s) in the episode"],
        })
    return out, unreadable


def _content(content) -> str:
    """`MessageContent` is `str | list[ContentPart]`; text parts are joined."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                parts.append(part.get("text") or f"[{part.get('type', 'part')}]")
        return "\n".join(parts)
    return ""


def rollout_trace(run_id: str, rollout_id: str) -> dict | None:
    """One rollout's full transcript, or None when there is no such rollout."""
    for episode in read_jsonl(_traces_file(run_id)):
        trace = _first_trace(episode)
        key = _short((trace or {}).get("id") or episode.get("id"))
        if key != rollout_id:
            continue
        trace = trace or {}
        nodes = []
        for node in trace.get("nodes") or []:
            message = node.get("message") or {}
            text = _content(message.get("content"))
            if not text and message.get("reasoning_content"):
                text = f"[reasoning] {message['reasoning_content']}"
            nodes.append({
                "role": message.get("role"),
                "content": text[:4000],
                "tool_calls": [
                    {"name": call.get("name"), "input": str(call.get("arguments", ""))[:1200],
                     "call_id": call.get("id")}
                    for call in message.get("tool_calls") or []
                ],
            })
        return {
            "id": key,
            "ok": bool(episode.get("ok")) and bool(trace.get("ok")),
            "errors": _errors(episode, trace),
            "stop": trace.get("stop_condition"),
            "rewards": trace.get("rewards") or {},
            "metrics": trace.get("metrics") or {},
            "tools": [tool.get("name") for tool in trace.get("tools") or [] if isinstance(tool, dict)],
            "calls": trace.get("calls") or [],
            "nodes": nodes,
        }
    return None


# ---------------------------------------------------------------- promotions

def promotions() -> list[dict]:
    """The adopted winners, in order. This is the reward curve.

    `reward` is `train_reward`, the winner's host macro-F1 on train as `promote`
    ranked it; `held_out` is `val_reward`, measured by `adopt`. Neither record
    stores the pre-search level, but `gain` is `train_reward` minus the train
    baseline it beat (`evaluate.gain`), so the first record gives it back.
    """
    out = []
    for i, record in enumerate(read_jsonl(STATE_DIR / "promotions.jsonl")):
        reward = record.get("train_reward")
        gain = record.get("gain")
        detail = []
        if record.get("artifact_digest"):
            detail.append(f"artifact {record['artifact_digest']}")
        if record.get("adopted_train_reward") is not None:
            detail.append(f"train after adoption {record['adopted_train_reward']}")
        out.append({
            "generation": record.get("generation"),
            "id": _short(record.get("trace")),
            "reward": reward,
            "baseline": (reward - gain) if i == 0 and reward is not None and gain is not None else None,
            "gain": gain,
            "held_out": record.get("val_reward"),
            "detail": detail,
        })
    return out


# ---------------------------------------------------------------------- gate

def _generation_of(trace_id) -> int | None:
    """The gate report records no generation. Find it where the same trace
    appears with one: its promotion, or its review. A gate that failed reaches
    neither, and its generation is not recorded anywhere."""
    if not trace_id:
        return None
    for record in read_jsonl(STATE_DIR / "promotions.jsonl") + read_jsonl(STATE_DIR / "reviews.jsonl"):
        if record.get("trace") == trace_id and record.get("generation") is not None:
            return record["generation"]
    return None


def gate() -> dict | None:
    """The most recent held-out check, or None when there has not been one."""
    report = read_json(STATE_DIR / "gate_report.json")
    if not report:
        return None
    return {
        "generation": _generation_of(report.get("trace")),
        "passed": report.get("verdict") == "passed",
        "before": report.get("baseline_val_reward"),
        "after": report.get("val_reward"),
        "failures": [str(f) for f in report.get("failures") or []],
    }


# ------------------------------------------------------------------- reviews

def reviews() -> list[dict]:
    """One entry per review, newest first. See reference/spine.md, `reviews`.

    `review._record` appends one line per generation that reached the stage.
    A field the record does not carry is None, never a default.
    """
    out = []
    for record in reversed(read_jsonl(STATE_DIR / "reviews.jsonl")):
        out.append({
            "generation": record.get("generation"),
            "trace": record.get("trace"),
            "refused": record.get("decision") == "refuse",
            "cited": bool(record.get("cited")),
            "concern": record.get("concern"),
            "quote": record.get("quote"),
            "reason": record.get("reason"),
            "note": record.get("note"),
            "model": record.get("model"),
            "at": record.get("at"),
            "runaway": bool(record.get("runaway")),
        })
    return out


# ---------------------------------------------------------------- candidates

def _candidate_verdict(record: dict) -> str | None:
    reason = _zero_reason(record)
    if reason:
        return reason
    if not any(name in record for name in ZERO_REASONS):
        # `finalize` wrote its half; `score` never ran.
        return "no report"
    return "scored" if record.get("reward") is not None else None


def _candidate_time(directory: Path) -> float:
    # candidate.json is the one file every candidate has: `score` writes it even
    # when `finalize` never ran. Fall back to the newest file for a directory
    # `finalize` left before recording anything.
    record = directory / "candidate.json"
    if record.is_file():
        return record.stat().st_mtime
    return max((p.stat().st_mtime for p in directory.iterdir()), default=directory.stat().st_mtime)


def candidates() -> list[dict]:
    """Everything a rollout returned that was scored, adopted or not. Newest first."""
    root = STATE_DIR / "candidates"
    if not root.is_dir():
        return []
    dirs = sorted((p for p in root.iterdir() if p.is_dir()), key=_candidate_time, reverse=True)
    out = []
    for directory in dirs:
        record = read_json(directory / "candidate.json")
        verdict = _candidate_verdict(record)
        detail = []
        if not (directory / "rules.py").is_file():
            detail.append("no rules.py came back")
        if verdict == "scored" and record.get("rows") is not None:
            detail.append(f"{record['rows']:g} train rows")
        status_path = directory / "status.txt"
        out.append({
            "id": _short(directory.name),
            "label": record.get("task_class"),
            "reward": record.get("reward") if verdict == "scored" else None,
            "verdict": verdict,
            "detail": detail,
            "status": status_path.read_text(errors="replace").strip() if status_path.is_file() else None,
        })
    return out


# -------------------------------------------------------------------- extras

def _f1(report: dict, category: str):
    stats = (report.get("per_category") or {}).get(category) or {}
    return stats.get("f1")


def extras() -> list[dict]:
    """Everything this experiment measures that the spine has no word for."""
    blocks = []
    train = read_json(STATE_DIR / "baseline_train.json")
    val = read_json(STATE_DIR / "baseline_val.json")
    test = read_json(STATE_DIR / "baseline_test.json")
    manifest = read_json(STATE_DIR / "corpus" / "manifest.json")
    pin = read_json(STATE_DIR / "instrument.json")

    rows = []
    if train:
        rows.append(["train macro-F1 (adopted table)", {"text": train.get("reward"), "fmt": "score"}])
    if val:
        rows.append(["val macro-F1 (adopted table)", {"text": val.get("reward"), "fmt": "score"}])
    if test:
        rows.append(["test macro-F1 (the table `baseline` last measured)", {"text": test.get("reward"), "fmt": "score", "class": "muted"}])
    for split, count in (manifest.get("counts") or {}).items():
        rows.append([f"{split} rows", {"text": count, "fmt": "int"}])
    if pin.get("instrument"):
        rows.append(["instrument pin", pin["instrument"]])
    if rows:
        blocks.append({
            "kind": "kv", "title": "baselines and corpus", "place": "top",
            "note": ("The baselines are the high-water marks every candidate is ranked against. "
                     "Adoption rewrites train and val; test is written only by `cli baseline` and is "
                     "never read by the loop, so it stays the canary it was when the search began."),
            "rows": rows,
        })

    categories = manifest.get("categories") or sorted(set(train.get("per_category") or {}) | set(val.get("per_category") or {}))
    if train or val:
        table = [["whole split", {"text": train.get("reward"), "fmt": "score"},
                  {"text": val.get("reward"), "fmt": "score"}, "", ""]]
        for name in categories:
            t_stats = (train.get("per_category") or {}).get(name) or {}
            v_stats = (val.get("per_category") or {}).get(name) or {}
            table.append([
                name,
                {"text": t_stats.get("f1"), "fmt": "score"},
                {"text": v_stats.get("f1"), "fmt": "score"},
                {"text": t_stats.get("support"), "fmt": "int"},
                {"text": v_stats.get("support"), "fmt": "int"},
            ])
        blocks.append({
            "kind": "table", "title": "the adopted table, per category", "place": "promotions",
            "note": ("Macro-F1 is the mean of these F1s over categories with support. A category with no "
                     "rows in a split has no F1, not a zero. The starting per-category values are not kept: "
                     "adoption overwrites both baselines."),
            "columns": ["category", "train F1", "val F1", "train support", "val support"],
            "rows": table,
        })

    report = read_json(STATE_DIR / "gate_report.json")
    moved = []
    for name, entry in (report.get("per_category") or {}).items():
        before, after = entry.get("before"), entry.get("after")
        if before == after and not entry.get("exempt"):
            continue
        delta = None if before is None or after is None else after - before
        moved.append((delta if delta is not None else float("-inf"), name, entry, delta))
    moved.sort(key=lambda item: item[0])
    if moved:
        blocks.append({
            "kind": "table", "title": "last gate, categories that moved or were exempt", "place": "promotions",
            "note": ("Val F1 per category before and after the staged table. Every category not listed "
                     "scored exactly its baseline. An exempt category had too little val support to judge, "
                     "and the gate skipped it; the support is shown so that can be rechecked."),
            "columns": ["category", "before", "after", "change", "support", "exempt"],
            "rows": [
                [name,
                 {"text": entry.get("before"), "fmt": "score"},
                 {"text": entry.get("after"), "fmt": "score"},
                 {"text": delta, "fmt": "score",
                  "class": "bad" if delta is not None and delta < 0 else ("ok" if delta else "muted")},
                 {"text": entry.get("support"), "fmt": "int"},
                 {"text": "exempt", "class": "warn"} if entry.get("exempt") else ""]
                for _, name, entry, delta in moved
            ],
        })
    return blocks


# --------------------------------------------------------------------- notes

def _turn_limit() -> int | None:
    """The turn limit the newest rollout was briefed with (`SyntheticData.turns`)."""
    for run_id in runs():
        for episode in reversed(read_jsonl(_traces_file(run_id))):
            turns = _task_data(episode, _first_trace(episode)).get("turns")
            if turns:
                return turns
    return None


def notes() -> dict:
    """Prose explaining each spine section, in this experiment's vocabulary."""
    limit = _turn_limit()
    turn_sentence = f" The brief allows up to {limit} turns." if limit else ""
    return {
        "live": ("Containers running the rollout image, the supervisor loop if it is up, and the tail "
                 "of the supervisor's log. The generation number is read from that log."),
        "runs": {
            "text": ("One run is one generation's eval: one rollout per task per repeat, where a task is "
                     "one category. A rollout counts as failed only when the framework marks it not ok: "
                     "the container did not start, it ran past its time budget, the model or harness "
                     "crashed, or scoring raised because the substrate is broken. A bad candidate is a "
                     "task outcome, never a fail."),
            "terms": [["eval died", "the run wrote no episode at all"],
                      ["running", "the newest run, while the supervisor is up"]],
        },
        "rollouts": {
            "text": ("An agent edits the rule table in a container and stops by replying with its own "
                     "score. The host then re-scores the returned table on train; that is the reward, and "
                     "gain is the reward minus the current train baseline." + turn_sentence),
            "terms": [["scored", "the host measured the returned table"],
                      ["artifact_unchanged", "no table came back to score: the rollout never reached finalize"],
                      ["guard_rejected", "the table reached outside the text it was handed (imports, open, eval, dunders)"],
                      ["validity_failed", "the table broke an invariant the reward cannot see: labels outside the taxonomy, "
                                          "answers that change between calls, a correct row that flips under a "
                                          "label-preserving rewrite, or a check over its time budget. Never scored"],
                      ["score_error", "the scorer could not produce a number"],
                      ["no report", "the rollout ended before the host scored it"],
                      ["error", "the framework marked the rollout failed"],
                      ["no trace", "the episode produced no trace: the box died before the agent ran"],
                      ["final_answer", "stop: the reply ended with a number"],
                      ["max_turns", "stop: the turn limit"]],
        },
        "promotions": ("The reward curve: each adopted winner's macro-F1 on train, with its held-out "
                       "macro-F1 on val. A generation appears here only if promote found an eligible "
                       "candidate, the gate passed it and, when review is on, the reviewer did not refuse it. "
                       "The dashed line is the train baseline the first winner beat."),
        "gate": ("The val gate re-scores the staged winner on a split nothing in the loop has fitted, per "
                 "category. It fails when the val mean falls, or when any category with enough support "
                 "drops by more than its tolerance; a category already perfect has no tolerance at all. "
                 "A failed gate discards the candidate. The report does not record its generation, so a "
                 "generation is shown only when the same trace was later reviewed or adopted."),
        "reviews": ("A stronger model asked, after the gate passes, whether the candidate earned its score. "
                    "Veto only: it can refuse an adoption, never cause one, and never changes a reward. A "
                    "refusal counts only when it cites a rubric concern and quotes the diff's changed lines; "
                    "anything else is recorded and passes, with the reason shown. Too many refusals in a row "
                    "stop the run, marked here as run stopped."),
        "candidates": {
            "text": ("Every table a rollout returned, from its candidate record. The verdict is the host's "
                     "measurement only; promote's own ranking verdicts (no gain, regresses a category, "
                     "eligible) are printed to the supervisor's log and not written to any file."),
            "terms": [["scored", "measured on train; the reward is its macro-F1"],
                      ["artifact_unchanged", "no rules.py came back, so nothing was measured"],
                      ["guard_rejected", "refused by the guard before it ran"],
                      ["validity_failed", "refused by the validity check before it was scored"],
                      ["score_error", "the table raised while classifying, or the scorer returned nothing"],
                      ["no report", "finalize recorded it, but scoring never ran"]],
        },
    }
