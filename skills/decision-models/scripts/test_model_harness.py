"""Tests for model_harness.py. Offline: every reply is a fixture, no route is contacted.

Run from this directory through the sandbox wrapper:
    mp-sandbox-test python3 -m unittest test_model_harness -v
"""

from __future__ import annotations

import io
import json
import os
import contextlib
import tempfile
import unittest
from typing import Any

import model_harness as mh

QUESTIONS_JSON = [
    {"id": "tank_low", "state": {"level_pct": 12}, "question": "Should the pump start?", "expect": True},
    {"id": "tank_full", "state": {"level_pct": 96}, "question": "Should the pump start?", "expect": False},
]


def reply(model: str | None, probability: float | None, *, answered: bool = True) -> tuple[int, str]:
    """A well-formed route reply. model=None omits the field, as a degraded gateway might."""
    body: dict[str, Any] = {"id": "x"}
    if model is not None:
        body["model"] = model
    if answered and probability is not None:
        body["answers"] = {"decision": {"type": "noul", "noul": probability}}
    return 200, json.dumps(body)


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.path = os.path.join(self._dir.name, "questions.json")
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(QUESTIONS_JSON, handle)
        self.questions = mh.load_question_set(self.path)

    def sender(self, responder):
        """A sender that answers each call by asking responder(model, question_id)."""

        def send(model, body):
            qid = body["questions"][mh.QUESTION_KEY]["instructions"]
            question = next(q for q in self.questions if q.text == qid and q.state == body["state"])
            return responder(model, question.id)

        return send


class QuestionSetTests(Base):
    def test_loads_valid_set(self) -> None:
        self.assertEqual([q.id for q in self.questions], ["tank_low", "tank_full"])

    def test_rejects_empty_list(self) -> None:
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump([], handle)
        with self.assertRaises(mh.QuestionSetError):
            mh.load_question_set(self.path)

    def test_rejects_duplicate_ids(self) -> None:
        dup = [dict(QUESTIONS_JSON[0]), dict(QUESTIONS_JSON[0])]
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(dup, handle)
        with self.assertRaisesRegex(mh.QuestionSetError, "duplicate"):
            mh.load_question_set(self.path)

    def test_rejects_non_boolean_expectation(self) -> None:
        bad = [dict(QUESTIONS_JSON[0], expect="yes")]
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(bad, handle)
        with self.assertRaisesRegex(mh.QuestionSetError, "expect"):
            mh.load_question_set(self.path)


class RequestShapeTests(Base):
    def test_request_names_the_model_asked_for(self) -> None:
        body = mh.build_request("candidate-a", self.questions[0])
        self.assertEqual(body["model"], "candidate-a")
        self.assertEqual(body["state"], {"level_pct": 12})
        self.assertEqual(body["questions"][mh.QUESTION_KEY]["type"], "noul")


class VerificationTests(Base):
    def test_matching_model_field_is_verified_and_correct(self) -> None:
        report = mh.run(
            ["candidate-a"],
            self.questions,
            self.sender(lambda model, qid: reply("candidate-a", 0.95 if qid == "tank_low" else 0.05)),
        )
        row = report[0]
        self.assertEqual(row["verified"], 2)
        self.assertEqual(row["correct"], 2)
        self.assertEqual(row["accuracy"], 1.0)
        self.assertFalse(row["disqualified"])
        self.assertEqual(mh.exit_code(report), mh.EXIT_OK)
        self.assertAlmostEqual(row["brier"], 0.0025, places=4)

    def test_unsure_answer_is_not_counted_correct(self) -> None:
        report = mh.run(["candidate-a"], self.questions, self.sender(lambda m, q: reply(m, 0.5)))
        row = report[0]
        self.assertEqual(row["unsure"], 2)
        self.assertEqual(row["correct"], 0)

    def test_provider_prefixed_name_is_a_mismatch_not_a_pass(self) -> None:
        # Exact comparison by design: a rewritten name needs an explicit alias, not a guess.
        report = mh.run(
            ["candidate-a"],
            self.questions,
            self.sender(lambda m, q: reply("provider/candidate-a", 0.95)),
        )
        self.assertEqual(report[0]["mismatch"], 2)
        self.assertEqual(mh.exit_code(report), mh.EXIT_MISMATCH)


class SilentFallbackTests(Base):
    def test_fallback_disqualifies_and_is_excluded_from_scores(self) -> None:
        def responder(model, qid):
            if qid == "tank_full":
                return reply("some-other-model", 0.01)  # answered from another model, and correctly
            return reply(model, 0.95)

        report = mh.run(["candidate-a"], self.questions, self.sender(responder))
        row = report[0]
        self.assertTrue(row["disqualified"])
        self.assertEqual(row["mismatch"], 1)
        self.assertEqual(row["verified"], 1)
        self.assertEqual(row["correct"], 1)
        self.assertEqual(row["served_as_instead"], ["some-other-model"])
        self.assertEqual(mh.exit_code(report), mh.EXIT_MISMATCH)

    def test_all_fallback_gives_no_accuracy_at_all(self) -> None:
        report = mh.run(["candidate-a"], self.questions, self.sender(lambda m, q: reply("other", 0.95)))
        self.assertIsNone(report[0]["accuracy"])
        self.assertIsNone(report[0]["brier"])
        self.assertTrue(report[0]["disqualified"])

    def test_green_case_stays_green_when_model_matches(self) -> None:
        # Negative control for the test above: the same wiring with matching names must pass.
        report = mh.run(["candidate-a"], self.questions, self.sender(lambda m, q: reply(m, 0.9)))
        self.assertFalse(report[0]["disqualified"])
        self.assertEqual(mh.exit_code(report), mh.EXIT_OK)


class FaultTests(Base):
    def test_missing_model_field_is_unverifiable_not_verified(self) -> None:
        report = mh.run(["candidate-a"], self.questions, self.sender(lambda m, q: reply(None, 0.95)))
        row = report[0]
        self.assertEqual(row["unverifiable"], 2)
        self.assertEqual(row["verified"], 0)
        self.assertIsNone(row["accuracy"])
        self.assertEqual(mh.exit_code(report), mh.EXIT_UNVERIFIABLE)

    def test_http_error_is_an_error_with_its_status(self) -> None:
        report = mh.run(["candidate-a"], self.questions, self.sender(lambda m, q: (503, "{}")))
        self.assertEqual(report[0]["error"], 2)
        self.assertIn("HTTP 503", report[0]["errors"][0])
        self.assertEqual(mh.exit_code(report), mh.EXIT_TRANSPORT)

    def test_api_error_body_is_an_error_even_with_status_200(self) -> None:
        body = json.dumps({"model": "candidate-a", "error": {"message": "quota exceeded"}})
        report = mh.run(["candidate-a"], self.questions, self.sender(lambda m, q: (200, body)))
        self.assertEqual(report[0]["error"], 2)
        self.assertIn("quota exceeded", report[0]["errors"][0])

    def test_transport_exception_is_recorded_not_dropped(self) -> None:
        def boom(model, body):
            raise OSError("connection refused")

        report = mh.run(["candidate-a"], self.questions, boom)
        self.assertEqual(report[0]["error"], 2)
        self.assertEqual(report[0]["questions"], 2)

    def test_probability_outside_unit_interval_is_an_error(self) -> None:
        report = mh.run(["candidate-a"], self.questions, self.sender(lambda m, q: reply(m, 1.7)))
        self.assertEqual(report[0]["error"], 2)
        self.assertEqual(report[0]["verified"], 0)

    def test_mismatch_outranks_transport_error_in_exit_code(self) -> None:
        def responder(model, qid):
            return (503, "{}") if qid == "tank_low" else reply("other", 0.9)

        report = mh.run(["candidate-a"], self.questions, self.sender(responder))
        self.assertEqual(mh.exit_code(report), mh.EXIT_MISMATCH)


class SenderAndCliTests(Base):
    def test_missing_key_variable_is_a_named_usage_error_without_a_value(self) -> None:
        name = "MODEL_HARNESS_TEST_UNSET_KEY"
        os.environ.pop(name, None)
        with self.assertRaisesRegex(mh.SenderError, name):
            mh.make_sender("http://127.0.0.1:9/unused", name, 1.0)

    def test_cli_returns_usage_for_missing_key_and_prints_no_value(self) -> None:
        name = "MODEL_HARNESS_TEST_UNSET_KEY"
        os.environ.pop(name, None)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = mh.main(["--questions", self.path, "--model", "m", "--endpoint", "http://127.0.0.1:9/x", "--key-env", name])
        self.assertEqual(code, mh.EXIT_USAGE)
        self.assertIn(name, err.getvalue())
        self.assertEqual(out.getvalue(), "")

    def test_all_errors_render_as_incomplete_not_ok(self) -> None:
        report = mh.run(["candidate-a"], self.questions, lambda m, b: (503, "{}"))
        text = mh.render_text(report)
        self.assertIn("INCOMPLETE", text)
        self.assertNotIn("| ok", text)

    def test_dry_run_prints_request_and_sends_nothing(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = mh.main(["--questions", self.path, "--model", "candidate-a", "--dry-run"])
        self.assertEqual(code, mh.EXIT_OK)
        printed = json.loads(out.getvalue())
        self.assertEqual(printed["model"], "candidate-a")

    def test_bad_question_file_is_a_usage_error(self) -> None:
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = mh.main(["--questions", self.path, "--model", "m", "--dry-run"])
        self.assertEqual(code, mh.EXIT_USAGE)


if __name__ == "__main__":
    unittest.main()
