"""Curated linguistic counterexamples, independent of the item author's answer key.

These probes protect valid alternatives and provenance. They are not CEFR calibration.
"""

import copy
import json
import unittest
from pathlib import Path

from tools import learning

ROOT = Path(__file__).resolve().parents[1]


class LinguisticReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bank = json.loads((ROOT / "data/assessments.json").read_text(encoding="utf-8"))
        cls.items = {item["id"]: item for item in cls.bank["items"]}
        cls.kb = json.loads(
            (ROOT / "languages/english/l1-notes/russian.json").read_text(encoding="utf-8")
        )

    def test_unlisted_reading_paraphrases_are_reserved_for_contextual_review(self):
        # Responses were authored separately from the answer keys. Exact-match
        # rejection would penalise meaning-preserving subject/tense paraphrases.
        responses = {
            "a1-reading-01": "Maya is playing a game with her sister today.",
            "a2-reading-01": "The writer suggests seven o'clock.",
            "b1-reading-01": "They will meet in the library.",
            "b2-reading-01": "An unusually motivated volunteer sample could bias the result.",
            "c1-reading-01": "The committee might refuse to fund it.",
        }
        for item_id, response in responses.items():
            with self.subTest(item=item_id, response=response):
                grade = learning.grade_answer(self.items[item_id], response)
                self.assertEqual(grade["status"], "needs_review")
                self.assertIsNone(grade["score"])

    def test_contractions_and_reported_speech_do_not_enforce_one_surface_form(self):
        cases = [
            ("a1-routine-01", "She doesn’t work on Sundays"),
            ("a1-routine-01", "She does not work on Sundays."),
            ("b1-report-01", "Maya said that she was tired."),
            ("b1-report-01", "Maya said that she is tired."),
        ]
        for item_id, response in cases:
            with self.subTest(item=item_id, response=response):
                self.assertEqual(
                    learning.grade_answer(self.items[item_id], response)["status"], "correct"
                )

    def test_timeline_contrasts_remain_constrained_where_prompt_supplies_the_form(self):
        cases = [
            ("a1-article-01", "an", "a"),
            ("a2-past-01", "went", "go"),
            ("b1-duration-01", "since", "for"),
            ("b2-conditional-01", "had left", "leave"),
        ]
        for item_id, correct, incorrect in cases:
            with self.subTest(item=item_id):
                self.assertEqual(
                    learning.grade_answer(self.items[item_id], correct)["status"], "correct"
                )
                self.assertEqual(
                    learning.grade_answer(self.items[item_id], incorrect)["status"], "incorrect"
                )

    def test_selected_distractors_preserve_the_intended_meaning_contrast(self):
        # A finished yesterday event, a past-to-present counterfactual, and an
        # uncertainty-qualified claim are different communicative targets.
        cases = [
            ("a2-experience-01", "I saw him yesterday.", "I have seen him yesterday."),
            (
                "b2-mixed-01",
                "If I had accepted the job, I would live in Rome now.",
                "If I accept the job, I will live in Rome next year.",
            ),
            (
                "c1-hedging-01",
                "The findings suggest a possible association, but further research is needed.",
                "The findings prove that the treatment always works.",
            ),
        ]
        for item_id, accepted, distractor in cases:
            with self.subTest(item=item_id):
                self.assertEqual(
                    learning.grade_answer(self.items[item_id], accepted)["status"], "correct"
                )
                self.assertEqual(
                    learning.grade_answer(self.items[item_id], distractor)["status"], "incorrect"
                )

    def test_valid_gerund_alternative_keeps_the_actual_response_and_llm_source(self):
        item = {
            "id": "review-like-infinitive",
            "skill_id": "a1-05",
            "level": "A1",
            "type": "error_correction",
            "domain": "writing",
            "prompt": "Correct the verb pattern: I like eat fish.",
            "answers": ["I like eating fish."],
            "error_tags": ["gerund_infinitive"],
        }
        response = "I like to eat fish."
        original = copy.deepcopy(item)
        self.assertEqual(learning.grade_answer(item, response)["status"], "needs_review")
        state = learning.new_state("russian")
        session = learning.start_session(
            state,
            {
                "date": "2026-10-16",
                "steps": [{"id": "repair", "type": "practice", "minutes": 5, "mode": "chat"}],
            },
            session_id="independent-linguistic-probe",
        )
        observation = learning.record_attempt(
            state,
            session["id"],
            item,
            response,
            attempt_id="like-valid-alternative",
            review={
                "source": "llm",
                "judgment": "correct_alternative",
                "criteria": {"accuracy": 1},
                "rationale": "Like permits a to-infinitive for a general preference.",
            },
            error_kb=self.kb,
            today="2026-10-16",
        )
        self.assertEqual(observation["response"], response)
        self.assertEqual(observation["grade"]["source"], "llm")
        self.assertEqual(observation["grade"]["judgment"], "correct_alternative")
        self.assertFalse(state["errors"])
        self.assertFalse(state["estimates"]["skills"]["a1-05"]["mastered"])
        self.assertEqual(item, original)

    def test_real_voice_tasks_are_unscored_until_an_audio_backed_review(self):
        for item in self.bank["items"]:
            if item["type"] != "spoken_response":
                continue
            with self.subTest(item=item["id"]):
                grade = learning.grade_answer(item, "A perfectly spelled typed response.")
                self.assertEqual(grade["status"], "needs_review")
                self.assertIsNone(grade["score"])
                self.assertEqual(item["mode"], "voice-required")

    def test_duplicate_or_accepted_distractors_cannot_hide_in_choice_options(self):
        # Normalisation can collapse typographical variants into the same choice.
        for item in self.bank["items"]:
            if "options" not in item:
                continue
            with self.subTest(item=item["id"]):
                normalized = [" ".join(o.casefold().split()).rstrip(".!?") for o in item["options"]]
                self.assertEqual(len(normalized), len(set(normalized)))
                self.assertLess(len(item["answers"]), len(item["options"]))

    def test_learner_views_hide_all_keys_and_listening_scripts(self):
        for item in self.bank["items"]:
            with self.subTest(item=item["id"]):
                before = copy.deepcopy(item)
                visible = learning.present_assessment_item(item)
                self.assertNotIn("answers", visible)
                self.assertNotIn("grammar_tags", visible)
                self.assertNotIn("error_tags", visible)
                self.assertNotIn("explanation_ru", visible)
                if "delivery" in item:
                    self.assertNotIn("text", visible["delivery"])
                    self.assertTrue(visible["audio_required"])
                    self.assertFalse(visible["delivery"]["transcript_visible"])
                if item["domain"] == "reading":
                    self.assertEqual(visible["context"], item["context"])
                controller = learning.present_assessment_item(item, controller=True)
                self.assertEqual(controller, item)
                controller["prompt"] = "Mutation must not alter the authored item."
                self.assertEqual(item, before)

    def test_replacement_listening_keys_follow_the_script_rather_than_topic_expectations(self):
        cases = [
            ("diag-a1-listening-01", "At seven.", "At eight."),
            (
                "diag-a2-listening-01",
                "At the café near the exit.",
                "At the main information desk.",
            ),
            (
                "diag-b1-listening-04",
                "It will start later in the usual room.",
                "It will begin at the usual time in a smaller room.",
            ),
            (
                "diag-b2-listening-03",
                "The speaker now values wording that preserves the character's uncertainty.",
                "The speaker now prefers the smoother version for its speed.",
            ),
            (
                "diag-c1-listening-04",
                "It developed judgment through guided exposure to ordinary decisions.",
                "It provided a set of rules that could be applied without discussion.",
            ),
        ]
        for item_id, accepted, distractor in cases:
            with self.subTest(item=item_id):
                self.assertEqual(
                    learning.grade_answer(self.items[item_id], accepted)["status"], "correct"
                )
                self.assertEqual(
                    learning.grade_answer(self.items[item_id], distractor)["status"], "incorrect"
                )


if __name__ == "__main__":
    unittest.main()
