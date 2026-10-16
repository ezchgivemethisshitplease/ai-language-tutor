"""Audit the shipped curriculum and its executable L1 references, without learner data."""
import json
import re
import unittest
from pathlib import Path

from tools import learning

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "languages/english/curriculum/catalog.json"
KB_PATH = ROOT / "languages/english/l1-notes/russian.json"


class CurriculumTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        cls.kb = json.loads(KB_PATH.read_text(encoding="utf-8"))
        cls.units = {u["id"]: u for u in cls.catalog["units"]}
        cls.errors = {e["id"]: e for e in cls.kb["errors"]}

    def test_complete_a1_c1_catalog_matches_all_shipped_units(self):
        learning.validate_catalog(self.catalog)
        self.assertEqual(len(self.catalog["units"]), 60)
        expected = {f"{level}-{n:02}" for level in ("a1", "a2", "b1", "b2", "c1") for n in range(1, 13)}
        self.assertEqual(set(self.units), expected)
        sources = set((ROOT / "languages/english/curriculum").glob("*/unit-*.md"))
        self.assertEqual({ROOT / unit["path"] for unit in self.units.values()}, sources)
        for uid, unit in self.units.items():
            with self.subTest(unit=uid):
                path = (ROOT / unit["path"]).resolve()
                self.assertTrue(path.is_relative_to(ROOT / "languages/english/curriculum"))
                text = path.read_text(encoding="utf-8")
                self.assertEqual(unit["level"], uid.split("-")[0].upper())
                self.assertEqual(unit["title"], text.splitlines()[0].split(" — ", 1)[1])
                self.assertEqual(unit["outcomes"], [re.search(r"\*\*Can-do:\*\* (.+)", text).group(1)])
                for section in ("Grammar focus", "Target vocabulary", "Functions & phrases", "Suggested activities", "Watch out"):
                    self.assertIn("## " + section, text)
                vocabulary = text.split("## Target vocabulary", 1)[1].split("\n", 1)[1].split("## Functions", 1)[0]
                words = [line.split(" — ", 1)[0].strip() for line in vocabulary.splitlines() if " — " in line]
                self.assertEqual(unit["target_vocabulary"], words)
                self.assertGreaterEqual(len(words), 10)
                self.assertLessEqual(len(words), 12)

    def test_prerequisites_reach_all_units_without_future_or_self_dependencies(self):
        seen = set()
        order = {level: i for i, level in enumerate(self.catalog["levels"])}
        for unit in self.catalog["units"]:
            with self.subTest(unit=unit["id"]):
                self.assertTrue(set(unit["prerequisites"]) <= seen)
                self.assertNotIn(unit["id"], unit["prerequisites"])
                for prerequisite in unit["prerequisites"]:
                    self.assertLessEqual(order[self.units[prerequisite]["level"]], order[unit["level"]])
                if unit["id"].endswith("-12"):
                    prefix = unit["id"].split("-")[0]
                    self.assertEqual(set(unit["prerequisites"]), {f"{prefix}-{n:02}" for n in range(1, 12)})
                seen.add(unit["id"])
        self.assertEqual(len(seen), 60)

    def test_unit_metadata_and_russian_references_are_valid_and_bidirectional(self):
        grammar = {tag for u in self.units.values() for tag in u["grammar_tags"]}
        for unit in self.units.values():
            self.assertTrue(unit["outcomes"])
            self.assertTrue(unit["grammar_tags"])
            self.assertTrue(set(unit["domains"]) <= set(self.catalog["domains"]))
            self.assertTrue(set(unit["exercise_types"]) <= set(self.catalog["exercise_types"]))
            self.assertTrue(set(unit["l1_error_tags"]) <= set(self.errors))
            for tag in unit["l1_error_tags"]:
                self.assertIn(unit["id"], self.errors[tag]["skill_ids"])
        for entry in self.kb["errors"]:
            with self.subTest(error=entry["id"]):
                self.assertTrue(set(entry["skill_ids"]) <= set(self.units))
                self.assertTrue(set(entry["grammar_tags"]) <= grammar)
                self.assertTrue(set(entry["levels"]) <= set(self.catalog["levels"]))
                self.assertTrue(set(entry["exercise_types"]) <= set(self.catalog["exercise_types"]))
                for uid in entry["skill_ids"]:
                    self.assertIn(entry["id"], self.units[uid]["l1_error_tags"])
                for field in ("explanation_ru", "feedback_ru"):
                    self.assertRegex(entry[field], "[А-Яа-яЁё]")
                self.assertTrue(entry["diagnostic_cues"])
                self.assertTrue(entry["remedial_tags"])
                self.assertTrue(entry["examples"])
                for example in entry["examples"]:
                    self.assertTrue(all(example.get(k) for k in ("incorrect", "correct", "context")))
                    self.assertNotEqual(example["incorrect"], example["correct"])

    def test_russian_kb_covers_requested_interference_topics_without_text_audio_claims(self):
        required = {"articles", "be_omission", "word_order", "auxiliaries", "questions", "negation", "present_simple", "continuous", "perfect_vs_past", "tense_aspect", "prepositions_place", "prepositions_time", "verb_prepositions", "phrasal_verbs", "countability", "quantifiers", "conditionals_real", "conditionals_unreal", "modals", "gerund_infinitive", "reported_speech", "relative_clauses", "false_friends", "calques", "impersonal_subject", "pronunciation_vowels", "pronunciation_th", "pronunciation_wv", "pronunciation_final_voicing", "word_stress", "sentence_stress"}
        self.assertEqual(len(self.kb["errors"]), len(self.errors), "Error IDs must be stable and unique")
        self.assertTrue(required <= set(self.errors))
        for entry in self.errors.values():
            if entry["category"] in {"pronunciation", "prosody"}:
                self.assertEqual(entry["evidence_required"], "audio")
                self.assertIn("spoken_response", entry["exercise_types"])
            else:
                self.assertEqual(entry["evidence_required"], "text")

    def test_real_catalog_and_kb_connect_observed_error_to_russian_feedback(self):
        state = learning.new_state("russian")
        session = learning.start_session(state, learning.plan(state, self.catalog, today="2026-01-01"), session_id="curriculum-fixture")
        exercise = {"id": "copula-fixture", "skill_id": "a1-01", "level": "A1", "domain": "grammar", "type": "cloze", "prompt": "I ___ a student.", "answers": ["am"], "exhaustive": True, "grammar_tags": ["be_present"]}
        observation = learning.record_attempt(state, session["id"], exercise, "is", error_tags=["be_omission"], error_kb=self.kb, catalog=self.catalog, today="2026-01-01")
        feedback = learning.feedback(observation, self.kb, "russian")
        self.assertEqual(feedback["status"], "incorrect")
        self.assertEqual(feedback["remediation"][0]["feedback"], self.errors["be_omission"]["feedback_ru"])
        self.assertEqual(feedback["remediation"][0]["examples"], self.errors["be_omission"]["examples"])
        self.assertEqual(state["errors"]["be_omission"]["skill_ids"], ["a1-01"])
        learning.validate_state(state)

    def test_pronunciation_diagnosis_cannot_be_attached_to_text_only_failure(self):
        state = learning.new_state("russian")
        session = learning.start_session(state, learning.plan(state, self.catalog, today="2026-01-01"), session_id="audio-evidence-fixture")
        exercise = {"id": "th-text-fixture", "skill_id": "a1-03", "level": "A1", "domain": "grammar", "type": "cloze", "prompt": "___ is my book.", "answers": ["This"], "exhaustive": True}
        with self.assertRaises(ValueError):
            learning.record_attempt(state, session["id"], exercise, "Dis", error_tags=["pronunciation_th"], error_kb=self.kb, catalog=self.catalog, today="2026-01-01")
        self.assertEqual(state["observations"], [])
        self.assertEqual(state["errors"], {})


if __name__ == "__main__":
    unittest.main()
