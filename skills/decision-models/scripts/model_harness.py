#!/usr/bin/env python3
"""Run candidate decision models over one fixed yes/no question set, through a System One route.

For every answer the harness checks that the response's `model` field equals the model that was
asked for. A different model name means the gateway or a client retry answered from another model
(a silent fallback). Such an answer is a fault for the candidate, not a result: it is excluded from
accuracy and Brier, and the candidate is disqualified for that run.

Stdlib only. The API key is read from the environment variable named by --key-env, sent in the
Authorization header, and never printed. Run the tests with test_model_harness.py beside this file.

Exit codes: 0 every answer verified and no fault; 1 at least one served-model mismatch (silent
fallback); 4 at least one transport or API error; 3 at least one unverifiable answer (no model
field) and no worse fault; 2 usage or input error.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Sequence
from typing import Any

YES_THRESHOLD = 0.8
NO_THRESHOLD = 0.2
QUESTION_KEY = "decision"
QUESTION_TYPE = "noul"  # the yes/no type the System One route uses (see decide.cs)

EXIT_OK = 0
EXIT_MISMATCH = 1
EXIT_USAGE = 2
EXIT_UNVERIFIABLE = 3
EXIT_TRANSPORT = 4


@dataclasses.dataclass(frozen=True)
class Question:
    """One fixed question: a JSON state, the yes/no wording, and the answer a person expects."""

    id: str
    state: Any
    text: str
    expect: bool


@dataclasses.dataclass(frozen=True)
class Outcome:
    """What came back for one (model, question) pair."""

    question_id: str
    requested: str
    served: str | None  # the response's model field, None when absent
    probability: float | None  # probability of yes, None when there is no answer
    error: str | None  # transport or API error text, None otherwise

    @property
    def status(self) -> str:
        if self.error is not None:
            return "error"
        if self.served is None:
            return "unverifiable"
        if self.served != self.requested:
            return "mismatch"
        return "verified"


class QuestionSetError(ValueError):
    """The question set file is not in the shape the harness expects."""


class SenderError(ValueError):
    """The sender cannot be built, for example the named key variable is unset."""


def load_question_set(path: str) -> list[Question]:
    """Read and validate a question set. Fails loudly on a wrong shape, an empty set or a duplicate id."""
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, list) or not raw:
        raise QuestionSetError("question set must be a non-empty JSON list")
    questions: list[Question] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise QuestionSetError(f"item {index} is not an object")
        qid = item.get("id")
        text = item.get("question")
        expect = item.get("expect")
        if not isinstance(qid, str) or not qid:
            raise QuestionSetError(f"item {index} needs a non-empty string id")
        if qid in seen:
            raise QuestionSetError(f"duplicate id {qid!r}")
        if not isinstance(text, str) or not text.strip():
            raise QuestionSetError(f"item {qid!r} needs a non-empty question")
        if not isinstance(expect, bool):
            raise QuestionSetError(f"item {qid!r} needs expect: true or false")
        if "state" not in item:
            raise QuestionSetError(f"item {qid!r} needs a state")
        seen.add(qid)
        questions.append(Question(id=qid, state=item["state"], text=text, expect=expect))
    return questions


def build_request(model: str, question: Question) -> dict[str, Any]:
    """The request body, in the shape decide.cs sends: model, state and named questions."""
    return {
        "model": model,
        "state": question.state,
        "questions": {QUESTION_KEY: {"type": QUESTION_TYPE, "instructions": question.text}},
    }


def parse_reply(question: Question, requested: str, status: int, body: str) -> Outcome:
    """Turn one HTTP reply into an Outcome. Never treats a missing field as a verified answer."""
    if status != 200:
        return Outcome(question.id, requested, None, None, f"HTTP {status}")
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return Outcome(question.id, requested, None, None, "reply is not JSON")
    if not isinstance(data, dict):
        return Outcome(question.id, requested, None, None, "reply is not a JSON object")
    if isinstance(data.get("error"), dict):
        return Outcome(question.id, requested, None, None, str(data["error"].get("message", "error")))
    served_raw = data.get("model")
    served = served_raw if isinstance(served_raw, str) and served_raw else None
    answers = data.get("answers")
    if not isinstance(answers, dict) or not isinstance(answers.get(QUESTION_KEY), dict):
        return Outcome(question.id, requested, served, None, "reply has no answer for the question")
    node = answers[QUESTION_KEY]
    value = node.get(QUESTION_TYPE)
    if node.get("type") != QUESTION_TYPE or not isinstance(value, (int, float)) or isinstance(value, bool):
        return Outcome(question.id, requested, served, None, "answer is not a yes/no probability")
    if not 0.0 <= float(value) <= 1.0:
        return Outcome(question.id, requested, served, None, "probability outside [0, 1]")
    return Outcome(question.id, requested, served, float(value), None)


def classify(probability: float) -> str:
    """yes, no or unsure, with the decide.cs defaults for yes/no thresholds."""
    if probability >= YES_THRESHOLD:
        return "yes"
    if probability <= NO_THRESHOLD:
        return "no"
    return "unsure"


def summarise(model: str, questions: Sequence[Question], outcomes: Iterable[Outcome]) -> dict[str, Any]:
    """Per-model result. Only verified answers count towards accuracy and Brier."""
    by_id = {q.id: q for q in questions}
    counts = {"verified": 0, "mismatch": 0, "unverifiable": 0, "error": 0}
    correct = 0
    unsure = 0
    brier_terms: list[float] = []
    mismatched_served: set[str] = set()
    errors: list[str] = []
    for outcome in outcomes:
        state = outcome.status
        counts[state] += 1
        if state == "mismatch" and outcome.served:
            mismatched_served.add(outcome.served)
        if state == "error" and outcome.error:
            errors.append(f"{outcome.question_id}: {outcome.error}")
        if state != "verified" or outcome.probability is None:
            continue
        question = by_id[outcome.question_id]
        label = classify(outcome.probability)
        if label == "unsure":
            unsure += 1
        elif (label == "yes") == question.expect:
            correct += 1
        brier_terms.append((outcome.probability - (1.0 if question.expect else 0.0)) ** 2)
    verified = counts["verified"]
    disqualified = counts["mismatch"] > 0
    return {
        "model": model,
        "questions": len(questions),
        "verified": verified,
        "mismatch": counts["mismatch"],
        "unverifiable": counts["unverifiable"],
        "error": counts["error"],
        "unsure": unsure,
        "correct": correct,
        "accuracy": round(correct / verified, 4) if verified else None,
        "brier": round(sum(brier_terms) / len(brier_terms), 4) if brier_terms else None,
        "served_as_instead": sorted(mismatched_served),
        "disqualified": disqualified,
        "reason": (
            f"answered by another model for {counts['mismatch']} of {len(questions)} questions"
            if disqualified
            else None
        ),
        "errors": errors,
    }


def run(
    models: Sequence[str],
    questions: Sequence[Question],
    send: Callable[[str, dict[str, Any]], tuple[int, str]],
) -> list[dict[str, Any]]:
    """Ask every model every question. `send` returns (HTTP status, body text) and may raise."""
    report = []
    for model in models:
        outcomes = []
        for question in questions:
            body = build_request(model, question)
            try:
                status, text = send(model, body)
            except Exception as exc:  # transport failure: recorded, never silently dropped
                outcome = Outcome(question.id, model, None, None, f"{type(exc).__name__}: {exc}")
            else:
                outcome = parse_reply(question, model, status, text)
            outcomes.append(outcome)
        report.append(summarise(model, questions, outcomes))
    return report


def exit_code(report: Sequence[dict[str, Any]]) -> int:
    """Worst fault wins: mismatch, then transport error, then unverifiable."""
    if any(row["mismatch"] for row in report):
        return EXIT_MISMATCH
    if any(row["error"] for row in report):
        return EXIT_TRANSPORT
    if any(row["unverifiable"] for row in report):
        return EXIT_UNVERIFIABLE
    return EXIT_OK


def make_sender(endpoint: str, key_env: str | None, timeout: float) -> Callable[[str, dict[str, Any]], tuple[int, str]]:
    """HTTP sender. Reads the key from the named environment variable; prints neither key nor value."""
    headers = {"Content-Type": "application/json"}
    if key_env:
        key = os.environ.get(key_env, "")
        if not key:
            raise SenderError(f"environment variable {key_env} is not set")
        headers["Authorization"] = f"Bearer {key}"

    def send(model: str, body: dict[str, Any]) -> tuple[int, str]:
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", errors="replace")

    return send


def render_text(report: Sequence[dict[str, Any]]) -> str:
    lines = ["model | verified/questions | correct | accuracy | brier | unsure | mismatch | error | verdict"]
    for row in report:
        if row["disqualified"]:
            verdict = f"DISQUALIFIED: {row['reason']}"
        elif row["error"] or row["unverifiable"]:
            verdict = f"INCOMPLETE: {row['error']} errors, {row['unverifiable']} unverifiable"
        else:
            verdict = "ok"
        lines.append(
            f"{row['model']} | {row['verified']}/{row['questions']} | {row['correct']} | "
            f"{row['accuracy']} | {row['brier']} | {row['unsure']} | {row['mismatch']} | "
            f"{row['error']} | {verdict}"
        )
        if row["served_as_instead"]:
            lines.append(f"  answered as: {', '.join(row['served_as_instead'])}")
        for message in row["errors"][:3]:
            lines.append(f"  error: {message}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--questions", required=True, help="fixed question set (JSON list)")
    parser.add_argument("--model", action="append", required=True, help="candidate model id; repeatable")
    parser.add_argument("--endpoint", default=os.environ.get("DECIDE_URL", ""), help="route URL (or DECIDE_URL)")
    parser.add_argument("--key-env", default="OPENROUTER_API_KEY", help="env var holding the key; '' for none")
    parser.add_argument("--timeout", type=float, default=120.0, help="seconds per request; cold loads need more")
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    parser.add_argument("--dry-run", action="store_true", help="print the first request body and send nothing")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        questions = load_question_set(args.questions)
    except (OSError, json.JSONDecodeError, QuestionSetError) as exc:
        print(f"model_harness: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if not args.endpoint and not args.dry_run:
        print("model_harness: give --endpoint or set DECIDE_URL", file=sys.stderr)
        return EXIT_USAGE
    if args.dry_run:
        print(json.dumps(build_request(args.model[0], questions[0]), indent=2))
        return EXIT_OK
    try:
        send = make_sender(args.endpoint, args.key_env or None, args.timeout)
    except SenderError as exc:
        print(f"model_harness: {exc}", file=sys.stderr)
        return EXIT_USAGE
    report = run(args.model, questions, send)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_text(report))
    return exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
