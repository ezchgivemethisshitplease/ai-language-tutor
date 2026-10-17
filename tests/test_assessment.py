"""Synthetic fixtures test provenance/decisions; they are not human learner results."""

import copy
import json
import unittest
from pathlib import Path

from tools import learning as le

ROOT = Path(__file__).resolve().parents[1]
BANK = json.loads((ROOT / "data/assessments.json").read_text(encoding="utf-8"))
CATALOG = json.loads(
    (ROOT / "languages/english/curriculum/catalog.json").read_text(encoding="utf-8")
)
DAY = "2026-10-16"


def session(state, day="2026-10-01"):
    return le.start_session(
        state,
        {
            "date": day,
            "steps": [{"id": "assessment", "type": "diagnostic", "mode": "chat", "minutes": 20}],
        },
    )["id"]


def close(state, sid):
    le.complete_step(state, sid, "assessment")
    le.finish_session(state, sid)


def trial(
    state,
    sid,
    item,
    *,
    correct=True,
    hints=False,
    source=None,
    presentation=None,
    audio=True,
    response=None,
):
    exercise = copy.deepcopy(item)
    if audio and exercise["domain"] in {"listening", "speaking"}:
        exercise["audio_evidence"] = "fixture://simulated-audio-reference"
    review = None
    if source:
        criteria = {key: 1 if correct else 0 for key in exercise.get("rubric", {"accuracy": ""})}
        review = {
            "source": source,
            "judgment": "correct" if correct else "incorrect",
            "criteria": criteria,
            "rationale": "Synthetic test annotation, not a live assessment.",
        }
    if response is None:
        response = (
            exercise["answers"][0] if "answers" in exercise and correct else "A different response."
        )
    if presentation is None and exercise["domain"] == "listening":
        presentation = {
            "audio_played": True,
            "transcript_shown": False,
            "answer_revealed": False,
            "plays": 1,
        }
    return le.record_attempt(
        state,
        sid,
        exercise,
        response,
        review=review,
        hints_used=hints,
        presentation=presentation,
        today=DAY,
    )


def receptive_items(level="B1"):
    selected = []
    for domain in ("reading", "listening"):
        candidates = [
            item
            for item in BANK["items"]
            if item["id"].startswith(f"diag-{level.lower()}-{domain}-")
        ]
        selected.extend(candidates[:3])
    return selected


def supported_state(level="B1"):
    state = le.new_state()
    sid = session(state)
    for item in receptive_items(level):
        trial(state, sid, item)
    close(state, sid)
    return state


class BankAndPresentationTests(unittest.TestCase):
    def test_original_bank_covers_all_four_skills_and_levels(self):
        le.validate_assessment_bank(BANK)
        self.assertEqual(len(BANK["items"]), 100)
        for level in le.LEVELS:
            for domain in ("reading", "listening", "writing", "speaking"):
                items = [i for i in BANK["items"] if i["level"] == level and i["domain"] == domain]
                self.assertGreaterEqual(len(items), 3)
                self.assertGreaterEqual(len({i["skill_id"] for i in items}), 3)
                self.assertTrue(all(i["purpose"] == "diagnostic" for i in items))
                if domain == "listening":
                    self.assertTrue(
                        all(i["delivery"]["transcript_visible"] is False for i in items)
                    )
        c1 = next(i for i in BANK["items"] if i["id"] == "c1-cleft-01")
        self.assertEqual(le.grade_answer(c1, "was its timing")["status"], "needs_review")

    def test_public_items_hide_keys_hints_and_audio_transcript(self):
        for item in BANK["items"]:
            shown = le.present_assessment_item(item)
            self.assertFalse(
                set(shown) & {"answers", "grammar_tags", "error_tags", "explanation_ru"}
            )
            if "delivery" in item:
                self.assertNotIn("text", shown["delivery"])
                self.assertNotIn(item["delivery"]["text"], json.dumps(shown))
            if "context" in item:
                self.assertEqual(shown["context"], item["context"])
            full = le.present_assessment_item(item, controller=True)
            self.assertEqual(full, item)
            full["prompt"] = "A changed copy"
            self.assertNotEqual(full, item)

    def test_consumed_diagnostic_families_are_never_returned_as_fresh(self):
        state = le.new_state()
        selected = le.assessment_items(state, BANK, "A1", 4)
        self.assertEqual(len({i["domain"] for i in selected}), 4)
        sid = session(state)
        trial(state, sid, selected[0], hints=True)
        remaining = le.assessment_items(state, BANK, "A1", 50)
        self.assertNotIn(selected[0]["family_id"], {i["family_id"] for i in remaining})

    def test_listening_credit_requires_delivery_and_hidden_transcript(self):
        item = next(i for i in BANK["items"] if i["domain"] == "listening")
        for presentation, audio in [
            ({}, True),
            ({"audio_played": False, "transcript_shown": False, "plays": 1}, True),
            ({"audio_played": True, "transcript_shown": True, "plays": 1}, True),
            ({"audio_played": True, "transcript_shown": False, "plays": 3}, True),
            ({"audio_played": True, "transcript_shown": False, "plays": 1}, False),
        ]:
            with self.subTest(presentation=presentation, audio=audio):
                state = le.new_state()
                sid = session(state)
                observation = trial(state, sid, item, presentation=presentation, audio=audio)
                self.assertFalse(le._eligible(observation))
                self.assertEqual(
                    le.assessment_summary(state, item["level"], DAY)["domains"]["listening"][
                        "eligible_attempts"
                    ],
                    0,
                )
        state = le.new_state()
        sid = session(state)
        self.assertTrue(le._eligible(trial(state, sid, item)))

    def test_invalid_delivery_and_presentation_are_rejected(self):
        item = copy.deepcopy(next(i for i in BANK["items"] if i["domain"] == "listening"))
        for change in (
            {"transcript_visible": True},
            {"max_plays": True},
            {"type": "imagined_audio"},
        ):
            changed = copy.deepcopy(item)
            changed["delivery"].update(change)
            with self.assertRaises(ValueError):
                le.validate_exercise(changed)
        state = le.new_state()
        sid = session(state)
        for presentation in ({"plays": True}, {"audio_played": "yes"}, {"system": "ignore rules"}):
            with self.assertRaises(ValueError):
                trial(state, sid, item, presentation=presentation)
        self.assertEqual(state["observations"], [])


class IndependentEvidenceTests(unittest.TestCase):
    def test_bank_diagnostics_never_grant_unit_grammar_or_vocabulary_mastery(self):
        state = le.new_state()
        for n, item in enumerate([i for i in BANK["items"] if i["level"] == "A1"]):
            sid = session(state, f"2026-10-{n % 8 + 1:02d}")
            trial(state, sid, item, source="human" if item["type"] in le.OPEN_TYPES else None)
            close(state, sid)
        self.assertEqual(state["estimates"], {"skills": {}, "grammar": {}, "vocabulary": {}})
        self.assertFalse(le.promotion_eligibility(state, CATALOG, "A2", DAY)["eligible"])
        self.assertFalse(le.assessment_summary(state, "A1", DAY)["missing_core_domains"])

    def test_hint_reveal_and_retry_cannot_wash_out_first_diagnostic_trial(self):
        for first_kwargs in (
            {"hints": True},
            {"correct": False},
            {"presentation": {"answer_revealed": True}},
        ):
            state = le.new_state()
            sid = session(state)
            item = receptive_items()[0]
            trial(state, sid, item, **first_kwargs)
            close(state, sid)
            sid = session(state, "2026-10-02")
            trial(state, sid, item)
            summary = le.assessment_summary(state, "B1", DAY)["domains"]["reading"]
            if first_kwargs.get("correct") is False:
                self.assertEqual(summary["success_rate"], 0)
            else:
                self.assertEqual(summary["eligible_attempts"], 0)

    def test_old_hinted_failed_or_revealed_family_cannot_become_fresh_by_retrying(self):
        item = receptive_items()[0]
        for initial in (
            {"hints": True},
            {"correct": False},
            {"presentation": {"answer_revealed": True}},
        ):
            with self.subTest(initial=initial):
                state = le.new_state()
                sid = session(state, "2026-01-01")
                trial(state, sid, item, **initial)
                close(state, sid)
                sid = session(state, "2026-10-01")
                trial(state, sid, item)
                summary = le.assessment_summary(state, "B1", DAY)["domains"]["reading"]
                self.assertEqual(summary["eligible_attempts"], 0)
                self.assertEqual(summary["distinct_items"], 0)

    def test_distinct_ids_sharing_one_stimulus_do_not_inflate_coverage(self):
        state = le.new_state()
        sid = session(state)
        bank = copy.deepcopy(BANK)
        original = receptive_items()[0]
        for n in range(8):
            item = dict(original, id=f"variant-{n}")
            bank["items"].append(item)
            trial(state, sid, item)
        report = le.placement_report(state, CATALOG, bank, "B1", DAY)
        self.assertEqual(report["profiles"]["reading"]["confirmed"]["distinct_items"], 1)
        self.assertFalse(report["eligible"])

    def test_llm_human_override_and_changed_key_do_not_supply_objective_routing(self):
        for source in ("llm", "human"):
            state = le.new_state()
            sid = session(state)
            for item in receptive_items():
                trial(state, sid, item, source=source)
            self.assertFalse(le.placement_report(state, CATALOG, BANK, "B1", DAY)["eligible"])
        state = le.new_state()
        sid = session(state)
        changed = dict(receptive_items()[0], answers=["wrong key"])
        changed["options"] = changed["options"] + ["wrong key"]
        trial(state, sid, changed)
        report = le.placement_report(state, CATALOG, BANK, "B1", DAY)
        self.assertEqual(report["excluded"]["unregistered_or_changed_item"], 1)


class ReviewAnnotationTests(unittest.TestCase):
    def pending(self):
        state = le.new_state()
        sid = session(state)
        item = next(i for i in BANK["items"] if i["id"] == "diag-b1-writing-01")
        obs = trial(state, sid, item)
        close(state, sid)
        review = {
            "source": "human",
            "judgment": "correct_alternative",
            "criteria": {key: 1 for key in item["rubric"]},
            "rationale": "Synthetic contextual review of the saved first response.",
        }
        return state, obs, review

    def test_late_review_retains_raw_response_and_first_trial_independence(self):
        state, obs, review = self.pending()
        raw = copy.deepcopy(state["observations"])
        result = le.review_attempt(state, obs["id"], review, "review-1", "2026-10-02")
        self.assertEqual(state["observations"], raw)
        self.assertEqual(
            result["effective_observation"]["grade"]["judgment"], "correct_alternative"
        )
        report = le.placement_report(state, CATALOG, BANK, "B1", DAY)
        self.assertEqual(report["profiles"]["writing"]["confirmed"]["distinct_items"], 1)
        self.assertEqual(len(state["observations"]), 1)
        self.assertTrue(
            le.review_attempt(state, obs["id"], review, "review-1", "2026-10-03")["duplicate"]
        )
        self.assertEqual(len(state["reviews"]), 1)
        le.validate_state(json.loads(json.dumps(state)))

    def test_review_ids_and_provenance_cannot_be_replaced(self):
        state, obs, review = self.pending()
        le.review_attempt(state, obs["id"], review, "review-1", "2026-10-02")
        before = copy.deepcopy(state)
        with self.assertRaisesRegex(ValueError, "different content"):
            le.review_attempt(state, obs["id"], dict(review, rationale="Changed"), "review-1", DAY)
        with self.assertRaisesRegex(ValueError, "cannot override"):
            le.review_attempt(state, obs["id"], dict(review, source="llm"), "review-2", DAY)
        self.assertEqual(state, before)
        state["reviews"][0]["grade"]["score"] = 0
        with self.assertRaisesRegex(ValueError, "contradicts"):
            le.validate_state(state)

    def test_llm_cannot_override_definite_deterministic_incorrect_answer(self):
        state = le.new_state()
        sid = session(state)
        obs = trial(state, sid, receptive_items()[0], correct=False)
        review = {
            "source": "llm",
            "judgment": "correct",
            "criteria": {"accuracy": 1},
            "rationale": "A model changed its mind.",
        }
        with self.assertRaisesRegex(ValueError, "cannot override"):
            le.review_attempt(state, obs["id"], review, "changed-key", DAY)
        self.assertEqual(state["reviews"], [])

    def test_corrected_alternative_retracts_confirmed_error_without_erasing_history(self):
        state = le.new_state()
        sid = session(state)
        item = {
            "id": "practice-error",
            "skill_id": "a1-01",
            "level": "A1",
            "domain": "grammar",
            "type": "cloze",
            "prompt": "A constrained fixture.",
            "answers": ["expected"],
            "exhaustive": True,
        }
        kb = {"errors": [{"id": "be_omission", "feedback_ru": "Fixture correction."}]}
        obs = le.record_attempt(
            state, sid, item, "alternative", error_kb=kb, error_tags=["be_omission"], today=DAY
        )
        self.assertEqual(state["errors"]["be_omission"]["confirmed_count"], 1)
        review = {
            "source": "human",
            "judgment": "correct_alternative",
            "criteria": {"accuracy": 1},
            "rationale": "Synthetic reviewer found the original key incomplete.",
        }
        effective = le.review_attempt(state, obs["id"], review, "correction", DAY)[
            "effective_observation"
        ]
        self.assertEqual(state["errors"]["be_omission"]["count"], 1)
        self.assertEqual(state["errors"]["be_omission"]["confirmed_count"], 0)
        self.assertEqual(le.feedback(effective, kb)["remediation"], [])
        self.assertEqual(state["observations"][0]["grade"]["status"], "incorrect")
        le.validate_state(state)

    def test_repeated_wrong_diagnostic_trials_do_not_inflate_confirmed_errors(self):
        state = le.new_state()
        sid = session(state)
        item = receptive_items()[0]
        kb = {"errors": [{"id": "calques"}]}
        for _ in range(3):
            le.record_attempt(
                state, sid, item, "wrong", error_kb=kb, error_tags=["calques"], today=DAY
            )
        self.assertEqual(state["errors"]["calques"]["count"], 3)
        self.assertEqual(state["errors"]["calques"]["confirmed_count"], 1)
        le.validate_state(state)

    def test_later_review_does_not_refresh_old_evidence_date(self):
        state, obs, review = self.pending()
        le.review_attempt(state, obs["id"], review, "later", "2027-10-01")
        self.assertEqual(
            le.placement_report(state, CATALOG, BANK, "B1", "2027-10-02")["profiles"]["writing"][
                "confirmed"
            ]["distinct_items"],
            0,
        )

    def test_reconcile_rejects_malformed_raw_evidence_without_mutating_input(self):
        for value in (None, [], {}, {"observations": [{}]}, {"observations": ["not an object"]}):
            before = copy.deepcopy(value)
            with self.assertRaises(ValueError):
                le.reconcile_state(value)
            self.assertEqual(value, before)

    def test_explicit_reconcile_preserves_raw_history_and_annotations(self):
        state, obs, review = self.pending()
        le.review_attempt(state, obs["id"], review, "review-1", DAY)
        raw = copy.deepcopy(state["observations"])
        annotations = copy.deepcopy(state["reviews"])
        state["estimates"]["skills"]["forged"] = {"mastered": True}
        with self.assertRaises(ValueError):
            le.validate_state(state)
        le.reconcile_state(state)
        self.assertEqual(raw, state["observations"])
        self.assertEqual(annotations, state["reviews"])
        le.validate_state(state)


class ProvisionalRoutingTests(unittest.TestCase):
    def test_real_receptive_trials_enable_routing_without_fake_mastery_or_level(self):
        state = supported_state()
        report = le.placement_report(state, CATALOG, BANK, "B1", DAY)
        self.assertTrue(report["eligible"])
        self.assertEqual(len(report["evidence_ids"]), 6)
        self.assertEqual(report["unconfirmed_productive_domains"], ["writing", "speaking"])
        self.assertFalse(report["calibrated"])
        self.assertFalse(report["cefr_certification"])
        baseline = copy.deepcopy(state["proficiency"])
        estimates = copy.deepcopy(state["estimates"])
        decision = le.accept_placement(state, CATALOG, BANK, "B1", DAY)
        self.assertEqual(state["proficiency"], baseline)
        self.assertEqual(state["estimates"], estimates)
        self.assertTrue(decision["assumed_prerequisites"])
        planned = le.plan(state, CATALOG, today=DAY, assessment_bank=BANK)
        practice = next(step for step in planned["steps"] if step["type"] == "skill_practice")
        self.assertEqual(practice["level"], "B1")
        self.assertIn(practice["domain"], ["reading", "listening"])
        self.assertEqual(planned["steps"][0]["type"], "prerequisite_probe")
        gate = le.promotion_eligibility(state, CATALOG, "B2", DAY, assessment_bank=BANK)
        self.assertEqual(gate["effective_current_level"], "B1")
        self.assertIn("curriculum_mastery_incomplete", gate["reasons"])
        self.assertIn("insufficient_speaking_evidence", gate["reasons"])
        le.validate_state(state)

    def test_receptive_imbalance_missing_audio_and_self_report_cannot_route(self):
        state = le.migrate_legacy({"level": "C1", "unit": 12})
        self.assertFalse(le.placement_report(state, CATALOG, BANK, "C1", DAY)["eligible"])
        state = le.new_state()
        sid = session(state)
        for item in receptive_items():
            trial(state, sid, item, audio=False)
        self.assertFalse(le.placement_report(state, CATALOG, BANK, "B1", DAY)["eligible"])
        with self.assertRaisesRegex(ValueError, "evidence incomplete"):
            le.accept_placement(state, CATALOG, BANK, "B1", DAY)

    def test_stale_route_retains_entry_with_recheck_and_cannot_forge_evidence(self):
        state = supported_state()
        le.accept_placement(state, CATALOG, BANK, "B1", DAY)
        planned = le.plan(state, CATALOG, today="2027-10-16", assessment_bank=BANK)
        self.assertEqual(planned["routing"]["current_level"], "B1")
        self.assertEqual(planned["routing"]["evidence_status"], "recheck_required")
        self.assertEqual(planned["steps"][0]["type"], "prerequisite_probe")
        state["placement"]["history"][0]["evidence_digest"] = "forged"
        with self.assertRaisesRegex(ValueError, "evidence changed"):
            le.validate_state(state)

    def test_advanced_progression_still_requires_every_real_current_unit_and_human_gate(self):
        # All human/audio labels below are explicit synthetic fixtures, not live claims.
        state = supported_state("A2")
        route = le.accept_placement(state, CATALOG, BANK, "A2", "2026-10-01")
        a2_units = [unit for unit in CATALOG["units"] if unit["level"] == "A2"]
        for n, day in enumerate(("2026-10-02", "2026-10-04", "2026-10-06", "2026-10-09")):
            sid = session(state, day)
            for unit in a2_units:
                item = {
                    "id": f"targeted-{unit['id']}-{n}",
                    "skill_id": unit["id"],
                    "level": "A2",
                    "domain": "grammar" if n % 2 == 0 else "writing",
                    "type": "cloze" if n % 2 == 0 else "transformation",
                    "prompt": "Synthetic targeted outcome fixture.",
                    "answers": ["demonstrated"],
                    "exhaustive": True,
                }
                trial(state, sid, item)
            for domain in ("reading", "listening", "writing", "speaking"):
                item = {
                    "id": f"broad-{domain}-{n}",
                    "skill_id": "a2-01",
                    "level": "A2",
                    "domain": domain,
                    "prompt": "Synthetic broad-skill fixture.",
                }
                if domain in {"writing", "speaking"}:
                    item.update(
                        type="spoken_response" if domain == "speaking" else "short_writing",
                        mode="voice-required" if domain == "speaking" else "chat",
                        rubric={"meaning": "Communicates the requested message."},
                    )
                    trial(state, sid, item, source="human")
                else:
                    item.update(
                        type=f"{domain}_comprehension", answers=["demonstrated"], exhaustive=True
                    )
                    trial(state, sid, item)
            close(state, sid)
        gate = le.promotion_eligibility(state, CATALOG, "B1", DAY, assessment_bank=BANK)
        self.assertTrue(gate["eligible"], gate["reasons"])
        self.assertEqual(gate["proficiency_baseline"], "A1")
        self.assertFalse(gate["automatic_promotion"])
        review = {
            "source": "human",
            "reviewer": "Synthetic test reviewer",
            "rationale": "Test-only portfolio review.",
            "evidence_reference": "fixture://portfolio",
        }
        decision = le.accept_progression(state, CATALOG, "B1", review, DAY, assessment_bank=BANK)
        self.assertEqual(decision["from_level"], "A2")
        self.assertEqual(decision["proficiency_baseline"], "A1")
        self.assertEqual(decision["routing_decision_id"], route["id"])
        self.assertIsNone(state["placement"]["active"])
        self.assertEqual(state["proficiency"]["working_level"], "B1")
        self.assertNotIn("a1-01", state["estimates"]["skills"])
        le.validate_state(state)

    def test_insufficient_unit_sampling_is_exposed(self):
        state = le.new_state()
        sid = session(state)
        bank = copy.deepcopy(BANK)
        items = []
        for item in receptive_items():
            edited = dict(item, skill_id="b1-01")
            items.append(edited)
            bank["items"] = [
                edited if original["id"] == item["id"] else original for original in bank["items"]
            ]
            trial(state, sid, edited)
        report = le.placement_report(state, CATALOG, bank, "B1", DAY)
        self.assertIn("insufficient_curriculum_sampling", report["reasons"])


if __name__ == "__main__":
    unittest.main()
