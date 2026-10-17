import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import learning as le


def catalog():
    return {
        "schema_version": 1,
        "units": [
            {
                "id": "a1-01",
                "level": "A1",
                "title": "Introductions",
                "prerequisites": [],
                "domains": ["grammar", "reading", "writing", "speaking"],
                "exercise_types": ["cloze"],
            },
            {
                "id": "a1-02",
                "level": "A1",
                "title": "Family",
                "prerequisites": ["a1-01"],
                "domains": ["reading", "writing"],
            },
            {
                "id": "a2-01",
                "level": "A2",
                "title": "Past events",
                "prerequisites": ["a1-02"],
                "domains": ["reading", "writing"],
            },
        ],
    }


def exercise(item="one", **changes):
    result = {
        "id": item,
        "type": "cloze",
        "skill_id": "a1-01",
        "level": "A1",
        "domain": "grammar",
        "prompt": "She ___ an engineer.",
        "answers": ["is"],
        "exhaustive": True,
        "grammar_tags": ["be"],
        "vocabulary": ["engineer"],
    }
    result.update(changes)
    return result


def simple_plan(day="2026-10-01"):
    return {
        "date": day,
        "steps": [{"id": "learn", "type": "practice", "mode": "chat", "minutes": 10}],
    }


def attempt(state, item="one", response="is", day="2026-10-01", finish=True, **kwargs):
    session = le.start_session(state, simple_plan(day))
    item_changes = kwargs.pop("item_changes", {})
    kwargs.setdefault("today", "2026-10-31")
    observation = le.record_attempt(
        state, session["id"], exercise(item, **item_changes), response, observed_at=day, **kwargs
    )
    if finish:
        le.complete_step(state, session["id"], "learn")
        le.finish_session(state, session["id"])
    return observation


class StateTests(unittest.TestCase):
    def test_round_trip_and_legacy_do_not_invent_evidence(self):
        legacy = {
            "level": "B2",
            "unit": 11,
            "streak": 5,
            "history": [{"activity": "exam", "score": 99}],
        }
        state = le.migrate_legacy(legacy)
        le.validate_state(json.loads(json.dumps(state)))
        self.assertEqual(legacy, state["legacy"]["progress"])
        self.assertEqual(state["estimates"]["skills"], {})
        self.assertEqual(le.language_policy(state)["instruction_language"], "russian")
        self.assertFalse(le.promotion_eligibility(state, catalog(), "C1")["eligible"])
        legacy["history"].clear()
        self.assertTrue(state["legacy"]["progress"]["history"])

    def test_invalid_state_and_derived_cache_recovery(self):
        state = le.new_state()
        state["profile"]["daily_minutes"] = True
        with self.assertRaises(ValueError):
            le.validate_state(state)
        state = le.new_state()
        attempt(state)
        state["estimates"]["skills"]["a1-01"]["mastered"] = True
        with self.assertRaisesRegex(ValueError, "disagree"):
            le.validate_state(state)
        le.rebuild_estimates(state)
        le.validate_state(state)

    def test_duplicate_observation_and_missing_session_rejected(self):
        state = le.new_state()
        attempt(state)
        state["observations"].append(copy.deepcopy(state["observations"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            le.validate_state(state)
        state["observations"].pop()
        state["observations"][0]["session_id"] = "missing"
        with self.assertRaisesRegex(ValueError, "missing session"):
            le.validate_state(state)


class GradingTests(unittest.TestCase):
    def test_normalization_and_declared_alternatives(self):
        item = exercise(answers=["is", "'s"])
        self.assertEqual(le.grade_answer(item, "  IS. ")["status"], "correct")
        self.assertEqual(le.grade_answer(item, "’s")["status"], "correct")
        item["normalization"] = {"case_sensitive": True, "ignore_terminal_punctuation": False}
        self.assertEqual(le.grade_answer(item, "IS.")["status"], "incorrect")

    def test_unlisted_answer_is_not_penalized_without_exhaustive_key(self):
        item = exercise(
            type="translation",
            prompt="Translate: Я люблю читать.",
            answers=["I like reading."],
            exhaustive=False,
        )
        self.assertEqual(le.grade_answer(item, "I enjoy reading.")["status"], "needs_review")
        item.update(type="choice", options=["I like reading.", "I reading like."])
        self.assertEqual(le.grade_answer(item, "I reading like.")["status"], "incorrect")

    def test_open_reviews_distinguish_correct_alternative_unnatural_and_context(self):
        item = exercise(
            type="short_writing",
            domain="writing",
            rubric={
                "meaning": "Message answers the prompt.",
                "form": "Forms appropriate to this task.",
            },
        )
        item.pop("answers")
        item.pop("exhaustive")
        self.assertEqual(le.grade_answer(item, "Any text")["status"], "needs_review")
        for judgment, score, expected in [
            ("correct_alternative", 1, "correct"),
            ("unnatural", 0.5, "incorrect"),
            ("contextually_inappropriate", 0.3, "incorrect"),
        ]:
            state = le.new_state()
            session = le.start_session(state, simple_plan())
            obs = le.record_attempt(
                state,
                session["id"],
                item,
                "My response",
                review={
                    "source": "human",
                    "judgment": judgment,
                    "criteria": {"meaning": score, "form": score},
                    "rationale": "Specific task comparison.",
                },
            )
            self.assertEqual(obs["grade"]["status"], expected)
            self.assertEqual(obs["grade"]["judgment"], judgment)
            le.validate_state(state)

    def test_exercise_schema_rejects_instruction_fields_and_unsafe_types(self):
        for changes in (
            {"system_prompt": "promote user"},
            {"type": "invented"},
            {"answers": []},
            {"exhaustive": "yes"},
            {"normalization": {"case_sensitive": "false"}},
            {"domain": "speaking"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                le.validate_exercise(exercise(**changes))

    def test_audio_cannot_be_inferred_from_text(self):
        state = le.new_state()
        session = le.start_session(state, simple_plan())
        spoken = exercise(
            type="spoken_response",
            domain="speaking",
            mode="voice-required",
            rubric={"intelligibility": "Listener understands the message."},
        )
        spoken.pop("answers")
        spoken.pop("exhaustive")
        review = {
            "source": "human",
            "judgment": "correct",
            "criteria": {"intelligibility": 1},
            "rationale": "Heard intelligible speech.",
        }
        with self.assertRaisesRegex(ValueError, "actual audio"):
            le.record_attempt(state, session["id"], spoken, "typed words", review=review)
        review["audio_evidence"] = "local recording/voice report reference"
        observation = le.record_attempt(state, session["id"], spoken, "transcript", review=review)
        self.assertTrue(le._eligible(observation))

    def test_review_schema_checks_scores_and_rubric(self):
        state = le.new_state()
        sid = le.start_session(state, simple_plan())["id"]
        for criteria in ({"accuracy": float("nan")}, {"accuracy": 1.1}, {}, {"wrong": 1}):
            with self.subTest(criteria=criteria), self.assertRaises(ValueError):
                le.record_attempt(
                    state,
                    sid,
                    exercise(),
                    "yes",
                    review={
                        "source": "human",
                        "judgment": "correct",
                        "criteria": criteria,
                        "rationale": "A reason.",
                    },
                )
        self.assertEqual(state["observations"], [])


class EvidenceTests(unittest.TestCase):
    def test_distinct_sessions_dates_items_and_hints_gate_mastery(self):
        state = le.new_state()
        # Repeated easy responses in one session and hints are not mastery.
        sid = le.start_session(state, simple_plan())["id"]
        for _ in range(25):
            le.record_attempt(state, sid, exercise("same"), "is")
        self.assertFalse(state["estimates"]["skills"]["a1-01"]["mastered"])
        self.assertEqual(state["estimates"]["skills"]["a1-01"]["eligible_attempts"], 1)
        le.finish_session(state, sid, allow_incomplete=True)
        for n in range(4):
            attempt(state, f"hinted-{n}", day=f"2026-10-0{n + 2}", hints_used=True)
        self.assertFalse(state["estimates"]["skills"]["a1-01"]["mastered"])
        for n in range(4):
            attempt(
                state,
                f"new-{n}",
                day=f"2026-10-{[2, 3, 4, 9][n]:02d}",
                item_changes={"domain": "writing", "type": "transformation"} if n % 2 else {},
            )
        summary = state["estimates"]["skills"]["a1-01"]
        self.assertTrue(summary["mastered"])
        self.assertEqual(summary["distinct_items"], 5)
        self.assertFalse(summary["calibrated"])
        self.assertEqual(state["estimates"]["grammar"]["be"]["success_rate"], 1)
        self.assertIn("engineer", state["estimates"]["vocabulary"])
        le.validate_state(state)

    def test_first_error_cannot_be_washed_out_by_retry(self):
        state = le.new_state()
        sid = le.start_session(state, simple_plan())["id"]
        le.record_attempt(state, sid, exercise(), "are")
        for _ in range(5):
            le.record_attempt(state, sid, exercise(), "is")
        self.assertEqual(state["estimates"]["skills"]["a1-01"]["success_rate"], 0)

    def test_idempotency_and_stable_item_definitions(self):
        state = le.new_state()
        sid = le.start_session(state, simple_plan())["id"]
        first = le.record_attempt(state, sid, exercise(), "is", attempt_id="stable")
        self.assertEqual(
            first, le.record_attempt(state, sid, exercise(), "is", attempt_id="stable")
        )
        self.assertEqual(len(state["observations"]), 1)
        with self.assertRaisesRegex(ValueError, "different payload"):
            le.record_attempt(state, sid, exercise(), "are", attempt_id="stable")
        with self.assertRaisesRegex(ValueError, "different definition"):
            le.record_attempt(state, sid, exercise(prompt="Changed meaning"), "is")

    def test_llm_reviews_never_count_as_confirmed_mastery_or_promotion(self):
        state = le.new_state()
        for n in range(6):
            attempt(
                state,
                str(n),
                day=f"2026-10-0{n + 1}",
                review={
                    "source": "llm",
                    "judgment": "correct",
                    "criteria": {"accuracy": 1},
                    "rationale": "Provisional model judgment.",
                },
            )
        self.assertEqual(state["estimates"]["skills"]["a1-01"]["eligible_attempts"], 0)
        self.assertFalse(le.promotion_eligibility(state, catalog(), "A2")["eligible"])
        self.assertEqual(le.language_policy(state)["instruction_language"], "russian")

    def test_many_sessions_roundtrip_and_return_after_inactivity(self):
        state = le.new_state()
        for n in range(100):
            attempt(state, f"item-{n}", "is" if n % 10 else "are", day=f"2026-10-{n % 20 + 1:02d}")
        le.validate_state(json.loads(json.dumps(state)))
        self.assertEqual(len(state["observations"]), 100)
        plan = le.plan(state, catalog(), due_count=100, today="2027-10-01")
        self.assertEqual(plan["new_card_limit"], 0)
        self.assertEqual(plan["steps"][0]["type"], "srs_review")
        summary = le.assessment_summary(state, today="2027-10-01")
        self.assertEqual(summary["status"], "insufficient_evidence")


class SessionTests(unittest.TestCase):
    def test_interrupt_resume_preserves_plan_and_evidence(self):
        state = le.new_state()
        initial_plan = le.plan(state, catalog(), today="2026-10-01")
        session = le.start_session(state, initial_plan, session_id="recoverable")
        initial_plan["steps"].clear()
        le.record_attempt(state, session["id"], exercise(), "is")
        le.interrupt_session(state, session["id"])
        restored = json.loads(json.dumps(state))
        le.validate_state(restored)
        with self.assertRaisesRegex(ValueError, "unfinished session"):
            le.start_session(restored, simple_plan())
        resumed = le.resume_session(restored, session["id"])
        self.assertTrue(resumed["plan"]["steps"])
        self.assertEqual(len(resumed["observation_ids"]), 1)
        with self.assertRaisesRegex(ValueError, "unfinished steps"):
            le.finish_session(restored, session["id"])
        for step in resumed["plan"]["steps"]:
            le.complete_step(restored, session["id"], step["id"])
        self.assertEqual(le.finish_session(restored, session["id"])["status"], "completed")
        le.validate_state(restored)

    def test_voice_completion_requires_audio_or_explicit_debt(self):
        state = le.new_state()
        session_plan = simple_plan()
        session_plan["steps"][0]["mode"] = "voice-required"
        sid = le.start_session(state, session_plan)["id"]
        with self.assertRaisesRegex(ValueError, "audio evidence"):
            le.complete_step(state, sid, "learn")
        le.complete_step(state, sid, "learn", deferred=True)
        result = le.finish_session(state, sid)
        self.assertTrue(result["speaking_debt"])
        self.assertEqual(result["completed_steps"], [])
        self.assertEqual(result["deferred_steps"], ["learn"])
        le.validate_state(state)

    def test_voice_step_rejects_text_and_listening_even_with_tts_audio_reference(self):
        for domain in ("grammar", "listening"):
            with self.subTest(domain=domain):
                state = le.new_state()
                session_plan = simple_plan()
                session_plan["steps"][0].update(mode="voice-required", skill_id="a1-01")
                sid = le.start_session(state, session_plan)["id"]
                item = exercise(
                    "not-speech",
                    domain=domain,
                    step_id="learn",
                    audio_evidence="actual-tutor-TTS-recording-not-learner-speech",
                )
                le.record_attempt(state, sid, item, "is")
                with self.assertRaisesRegex(ValueError, "actual audio evidence"):
                    le.complete_step(state, sid, "learn")
                self.assertEqual(state["sessions"][sid]["completed_steps"], [])

    def test_voice_completion_checks_skill_and_keeps_llm_mastery_provisional(self):
        state = le.new_state()
        session_plan = simple_plan()
        session_plan["steps"][0].update(mode="voice-required", skill_id="a1-01")
        sid = le.start_session(state, session_plan)["id"]
        spoken = exercise(
            "spoken",
            type="spoken_response",
            domain="speaking",
            mode="voice-required",
            step_id="learn",
            audio_evidence="actual-learner-voice-reference",
            rubric={"clarity": "The message can be understood."},
        )
        spoken.pop("answers")
        spoken.pop("exhaustive")
        review = {
            "source": "llm",
            "judgment": "correct",
            "criteria": {"clarity": 1},
            "rationale": "Provisional review of the actual speech attempt.",
        }
        wrong_skill = dict(spoken, skill_id="a1-02")
        with self.assertRaisesRegex(ValueError, "does not match planned step"):
            le.record_attempt(state, sid, wrong_skill, "A spoken response.", review=review)
        # An imported/free-practice observation must not complete a different skill.
        wrong_skill.pop("step_id")
        le.record_attempt(state, sid, wrong_skill, "A spoken response.", review=review)
        state["observations"][-1]["exercise"]["step_id"] = "learn"
        with self.assertRaisesRegex(ValueError, "actual audio evidence"):
            le.complete_step(state, sid, "learn")
        le.record_attempt(
            state, sid, dict(spoken, id="matching-spoken"), "A spoken response.", review=review
        )
        self.assertEqual(le.complete_step(state, sid, "learn")["completed_steps"], ["learn"])
        self.assertEqual(state["estimates"]["skills"]["a1-01"]["eligible_attempts"], 0)
        le.validate_state(state)

    def test_abandoned_voice_session_keeps_debt(self):
        state = le.new_state()
        session_plan = simple_plan()
        session_plan["steps"][0]["mode"] = "voice-required"
        sid = le.start_session(state, session_plan)["id"]
        ended = le.finish_session(state, sid, allow_incomplete=True)
        self.assertEqual(ended["status"], "abandoned")
        self.assertTrue(ended["speaking_debt"])
        le.validate_state(state)

    def test_invalid_plan_and_transition(self):
        state = le.new_state()
        bad = simple_plan()
        bad["steps"].append(copy.deepcopy(bad["steps"][0]))
        with self.assertRaises(ValueError):
            le.start_session(state, bad)
        sid = le.start_session(state, simple_plan())["id"]
        with self.assertRaises(ValueError):
            le.complete_step(state, sid, "unknown")
        le.finish_session(state, sid, allow_incomplete=True)
        with self.assertRaises(ValueError):
            le.resume_session(state, sid)


class DebtSettlementTests(unittest.TestCase):
    def make_debt(self, state, skills=("a1-01",), day="2026-10-01"):
        session_plan = {
            "date": day,
            "steps": [
                {
                    "id": f"voice-{n}",
                    "type": "speaking",
                    "mode": "voice-required",
                    "minutes": 5,
                    "skill_id": skill,
                }
                for n, skill in enumerate(skills)
            ],
        }
        sid = le.start_session(state, session_plan)["id"]
        for step in session_plan["steps"]:
            le.complete_step(state, sid, step["id"], deferred=True)
        le.finish_session(state, sid)
        return sid

    def speech(
        self, state, skill="a1-01", day="2026-10-02", source="human", domain="speaking", hints=False
    ):
        sid = le.start_session(state, simple_plan(day))["id"]
        item = exercise(
            f"speech-{len(state['observations'])}",
            skill_id=skill,
            domain=domain,
            type="spoken_response" if domain == "speaking" else "short_writing",
            mode="voice-required" if domain == "speaking" else "chat",
            rubric={"clarity": "Message can be understood."},
        )
        item.pop("answers")
        item.pop("exhaustive")
        if domain == "speaking":
            item["audio_evidence"] = "local actual voice record reference"
        obs = le.record_attempt(
            state,
            sid,
            item,
            "Recorded transcript",
            hints_used=hints,
            review={
                "source": source,
                "judgment": "correct",
                "criteria": {"clarity": 1},
                "rationale": "Reviewed observed sample.",
            },
        )
        le.complete_step(state, sid, "learn")
        le.finish_session(state, sid)
        return obs

    def test_matching_later_voice_settles_partial_debt_without_rewriting_history(self):
        state = le.new_state()
        origin = self.make_debt(state, ("a1-01", "a1-02"))
        original_steps = copy.deepcopy(state["sessions"][origin]["deferred_steps"])
        one = self.speech(state)
        settled = le.settle_speaking_debt(state, origin, one["id"])
        self.assertTrue(settled["speaking_debt"])
        self.assertEqual(settled["deferred_steps"], original_steps)
        self.assertEqual(len(settled["debt_settlements"]), 1)
        self.assertEqual(settled, le.settle_speaking_debt(state, origin, one["id"]))
        two = self.speech(state, skill="a1-02")
        result = le.settle_speaking_debt(state, origin, two["id"])
        self.assertFalse(result["speaking_debt"])
        self.assertEqual(len(result["debt_settlements"]), 2)
        le.validate_state(json.loads(json.dumps(state)))

    def test_text_llm_hinted_wrong_skill_and_earlier_evidence_cannot_settle(self):
        for changes in (
            {"domain": "writing"},
            {"source": "llm"},
            {"hints": True},
            {"skill": "a1-03"},
        ):
            with self.subTest(changes=changes):
                state = le.new_state()
                origin = self.make_debt(state)
                obs = self.speech(state, **changes)
                before = copy.deepcopy(state)
                with self.assertRaises(ValueError):
                    le.settle_speaking_debt(state, origin, obs["id"])
                self.assertEqual(before, state)
        state = le.new_state()
        earlier = self.speech(state, day="2026-10-01")
        origin = self.make_debt(state, day="2026-10-02")
        with self.assertRaisesRegex(ValueError, "later real speech"):
            le.settle_speaking_debt(state, origin, earlier["id"])

    def test_implicit_unavailable_voice_debt_settles_and_is_not_copied_to_later_sessions(self):
        state = le.new_state()
        planned = le.plan(state, catalog(), today="2026-10-01", voice_available=False)
        self.assertEqual(planned["deferred_voice_skills"], ["a1-01"])
        origin = le.start_session(state, planned)["id"]
        for step in planned["steps"]:
            le.complete_step(state, origin, step["id"])
        le.finish_session(state, origin)
        later_plan = le.plan(state, catalog(), today="2026-10-02", voice_available=True)
        self.assertTrue(later_plan["speaking_debt"])
        later = le.start_session(state, later_plan)["id"]
        self.assertFalse(state["sessions"][later]["speaking_debt"])
        le.finish_session(state, later, allow_incomplete=True)
        obs = self.speech(state)
        self.assertFalse(le.settle_speaking_debt(state, origin, obs["id"])["speaking_debt"])
        self.assertFalse(
            le.plan(state, catalog(), today="2026-10-03", voice_available=True)["speaking_debt"]
        )

    def test_same_day_make_up_requires_distinct_later_session_and_validated_evidence(self):
        state = le.new_state()
        origin = self.make_debt(state)
        obs = self.speech(state, day="2026-10-01")
        le.settle_speaking_debt(state, origin, obs["id"])
        le.validate_state(state)
        state["sessions"][origin]["debt_settlements"][0]["observation_id"] = "missing"
        with self.assertRaisesRegex(ValueError, "lacks matching"):
            le.validate_state(state)

    def test_abandoned_voice_step_can_be_made_up(self):
        state = le.new_state()
        session_plan = simple_plan()
        session_plan["steps"][0].update(mode="voice-required", skill_id="a1-01")
        origin = le.start_session(state, session_plan)["id"]
        le.finish_session(state, origin, allow_incomplete=True)
        self.assertTrue(state["sessions"][origin]["speaking_debt"])
        obs = self.speech(state)
        self.assertFalse(le.settle_speaking_debt(state, origin, obs["id"])["speaking_debt"])
        self.assertEqual(state["sessions"][origin]["status"], "abandoned")
        le.validate_state(state)


class PlanningAndAssessmentTests(unittest.TestCase):
    def test_due_first_prerequisites_and_voice_debt(self):
        state = le.new_state()
        planned = le.plan(state, catalog(), due_count=3, today="2026-10-01")
        self.assertEqual(planned["steps"][0]["type"], "srs_review")
        self.assertEqual(planned["steps"][1]["skill_id"], "a1-01")
        self.assertEqual(planned["steps"][1]["mode"], "chat")
        self.assertTrue(planned["speaking_debt"])
        self.assertLessEqual(sum(s["minutes"] for s in planned["steps"]), 30)
        self.assertEqual(state["sessions"], {})

    def test_mastered_units_stop_repeating_until_scheduled_retrieval(self):
        state = le.new_state()
        for n in range(4):
            attempt(
                state,
                f"{n}",
                day=f"2026-10-{[1, 2, 4, 8][n]:02d}",
                item_changes={"domain": "writing", "type": "transformation"} if n % 2 else {},
            )
        planned = le.plan(state, catalog(), today="2026-10-09")
        self.assertEqual(planned["steps"][0]["skill_id"], "a1-02")
        later = le.plan(state, catalog(), today="2026-10-15")
        self.assertEqual(later["steps"][0]["type"], "retrieval_check")

    def test_no_auto_advance_above_working_level(self):
        state = le.new_state()
        curriculum = catalog()
        curriculum["units"][2]["prerequisites"] = []
        curriculum["units"][0]["prerequisites"] = ["a1-02"]
        curriculum["units"][1]["prerequisites"] = []
        planned = le.plan(state, curriculum, today="2026-10-01")
        self.assertEqual(planned["steps"][0]["level"], "A1")

    def test_curriculum_cycles_and_unknown_prerequisites_rejected(self):
        for parents in (["missing"], ["a1-02"]):
            curriculum = catalog()
            curriculum["units"][0]["prerequisites"] = parents
            with self.assertRaises(ValueError):
                le.validate_catalog(curriculum)

    def test_recurring_errors_feedback_and_remediation(self):
        state = le.new_state()
        kb = {
            "errors": [
                {
                    "id": "be_omission",
                    "feedback_ru": "Нужна связка is.",
                    "explanation_ru": "В английском настоящем времени связка сохраняется.",
                    "examples": [{"incorrect": "She engineer.", "correct": "She is an engineer."}],
                    "exercise_types": ["cloze"],
                }
            ]
        }
        for n in range(3):
            obs = attempt(
                state,
                f"error-{n}",
                "are",
                day=f"2026-10-0{n + 1}",
                error_kb=kb,
                error_tags=["be_omission"],
            )
        self.assertEqual(state["errors"]["be_omission"]["count"], 3)
        planned = le.plan(state, catalog(), today="2026-10-04")
        self.assertEqual(planned["steps"][0]["type"], "remedial_lesson")
        self.assertEqual(planned["steps"][0]["error_tags"], ["be_omission"])
        self.assertIn("связка", le.feedback(obs, kb)["remediation"][0]["feedback"])
        self.assertFalse(le.feedback(obs, kb, "spanish")["remediation"][0]["explanation"])
        le.validate_state(state)

    def test_unsupported_error_diagnosis_changes_nothing(self):
        state = le.new_state()
        sid = le.start_session(state, simple_plan())["id"]
        before = copy.deepcopy(state)
        with self.assertRaises(ValueError):
            le.record_attempt(state, sid, exercise(), "are", error_tags=["fake"])
        self.assertEqual(state, before)

    def test_language_policy_uses_observed_diversity_and_explicit_l1_override(self):
        state = le.new_state()
        state["proficiency"]["working_level"] = "C1"
        self.assertEqual(le.language_policy(state)["instruction_language"], "russian")
        for n in range(4):
            sid = le.start_session(state, simple_plan(f"2026-10-0{n + 1}"))["id"]
            le.record_attempt(
                state,
                sid,
                exercise(
                    str(n), level="B2", skill_id="b2-01", domain="reading" if n % 2 else "grammar"
                ),
                "is",
            )
            le.finish_session(state, sid, allow_incomplete=True)
        self.assertEqual(le.language_policy(state)["instruction_language"], "english")
        policy = le.language_policy(state, explicit_l1=True)
        self.assertEqual(policy["instruction_language"], "russian")
        self.assertEqual(policy["material_language"], "english")

    def test_assessment_exposes_unassessed_domains_not_cefr_certification(self):
        state = le.new_state()
        attempt(state)
        summary = le.assessment_summary(state, "A1", today="2026-10-02")
        self.assertIn("speaking", summary["missing_core_domains"])
        self.assertFalse(summary["cefr_certification"])
        self.assertFalse(
            le.promotion_eligibility(state, catalog(), "A2", today="2026-10-02")[
                "automatic_promotion"
            ]
        )

    def test_minimum_delay_and_production_are_required_for_mastery(self):
        state = le.new_state()
        for n in range(4):
            attempt(state, f"spaced-{n}", day=f"2026-10-{[1, 2, 4, 8][n]:02d}")
        self.assertFalse(state["estimates"]["skills"]["a1-01"]["mastered"])
        state = le.new_state()
        for n in range(4):
            attempt(
                state,
                f"immediate-{n}",
                day=f"2026-10-0{n + 1}",
                item_changes={"domain": "writing", "type": "transformation"} if n % 2 else {},
            )
        self.assertFalse(state["estimates"]["skills"]["a1-01"]["mastered"])

    def test_future_attempt_and_wrong_skill_level_are_rejected_atomically(self):
        state = le.new_state()
        sid = le.start_session(state, simple_plan())["id"]
        before = copy.deepcopy(state)
        with self.assertRaisesRegex(ValueError, "future"):
            le.record_attempt(
                state, sid, exercise(), "is", observed_at="2026-10-03", today="2026-10-02"
            )
        with self.assertRaisesRegex(ValueError, "level"):
            le.record_attempt(state, sid, exercise(level="C1"), "is", catalog=catalog())
        self.assertEqual(state, before)

    def test_audio_error_tag_cannot_diagnose_text_only_performance(self):
        state = le.new_state()
        sid = le.start_session(state, simple_plan())["id"]
        kb = {"errors": [{"id": "pronunciation_th", "evidence_required": "audio"}]}
        with self.assertRaisesRegex(ValueError, "audio evidence"):
            le.record_attempt(
                state, sid, exercise(), "are", error_kb=kb, error_tags=["pronunciation_th"]
            )
        self.assertEqual(state["observations"], [])

    def test_llm_error_tags_are_provisional_and_do_not_force_remediation(self):
        state = le.new_state()
        kb = {"errors": [{"id": "be_omission"}]}
        for n in range(3):
            attempt(
                state,
                f"llm-error-{n}",
                response="are",
                day=f"2026-10-0{n + 1}",
                error_kb=kb,
                error_tags=["be_omission"],
                review={
                    "source": "llm",
                    "judgment": "incorrect",
                    "criteria": {"accuracy": 0},
                    "rationale": "Provisional diagnosis.",
                },
            )
        self.assertEqual(state["errors"]["be_omission"]["count"], 3)
        self.assertEqual(state["errors"]["be_omission"]["confirmed_count"], 0)
        self.assertNotEqual(
            le.plan(state, catalog(), today="2026-10-04")["steps"][0]["type"], "remedial_lesson"
        )
        le.validate_state(state)

    def test_assessment_selection_is_balanced_and_deterministic(self):
        root = Path(__file__).resolve().parents[1]
        bank = json.loads((root / "data" / "assessments.json").read_text(encoding="utf-8"))
        state = le.new_state()
        first = le.assessment_items(state, bank, "A1", 4)
        self.assertEqual(first, le.assessment_items(state, bank, "A1", 4))
        self.assertEqual(len({item["domain"] for item in first}), 4)
        first[0]["prompt"] = "Edited copy"
        self.assertNotEqual(first, le.assessment_items(state, bank, "A1", 4))

    def test_human_reviewed_progression_requires_evidence_then_records_decision(self):
        state = le.new_state()
        curriculum = catalog()
        curriculum["units"] = [curriculum["units"][0], curriculum["units"][2]]
        curriculum["units"][1]["prerequisites"] = ["a1-01"]
        review = {
            "source": "human",
            "reviewer": "Tutor",
            "rationale": "Reviewed observed task portfolio.",
            "evidence_reference": "Local assessment rubric record.",
        }
        with self.assertRaisesRegex(ValueError, "evidence incomplete"):
            le.accept_progression(state, curriculum, "A2", review, today="2026-10-09")
        for n, daynum in enumerate([1, 2, 4, 8]):
            day = f"2026-10-{daynum:02d}"
            sid = le.start_session(state, simple_plan(day))["id"]
            for domain in ["reading", "writing", "listening", "speaking"]:
                item = exercise(f"{domain}-{n}", domain=domain)
                human_review = None
                if domain == "writing":
                    item.update(
                        type="short_writing", rubric={"clarity": "The written message is clear."}
                    )
                    item.pop("answers")
                    item.pop("exhaustive")
                    human_review = {
                        "source": "human",
                        "judgment": "correct",
                        "criteria": {"clarity": 1},
                        "rationale": "Reviewed actual written sample.",
                    }
                if domain in {"listening", "speaking"}:
                    item["audio_evidence"] = f"local-audio-reference-{n}"
                if domain == "speaking":
                    item.update(
                        type="spoken_response",
                        mode="voice-required",
                        rubric={"intelligibility": "The message can be understood."},
                    )
                    item.pop("answers")
                    item.pop("exhaustive")
                    human_review = {
                        "source": "human",
                        "judgment": "correct",
                        "criteria": {"intelligibility": 1},
                        "rationale": "Reviewed actual spoken sample.",
                    }
                le.record_attempt(
                    state, sid, item, "is", review=human_review, observed_at=day, catalog=curriculum
                )
            le.complete_step(state, sid, "learn")
            le.finish_session(state, sid)
        self.assertTrue(
            le.promotion_eligibility(state, curriculum, "A2", today="2026-10-09")["eligible"]
        )
        llm_review = dict(review, source="llm")
        with self.assertRaisesRegex(ValueError, "human review"):
            le.accept_progression(state, curriculum, "A2", llm_review, today="2026-10-09")
        decision = le.accept_progression(state, curriculum, "A2", review, today="2026-10-09")
        self.assertEqual(state["proficiency"]["working_level"], "A2")
        self.assertEqual(len(state["proficiency"]["decisions"]), 1)
        self.assertFalse(decision["cefr_certification"])
        le.validate_state(state)

    def test_bank_schema_and_real_catalog(self):
        root = Path(__file__).resolve().parents[1]
        bank_path = root / "data" / "assessments.json"
        if bank_path.exists():
            bank = json.loads(bank_path.read_text(encoding="utf-8"))
            self.assertFalse(bank["calibrated"])
            ids = []
            for item in bank["items"]:
                le.validate_exercise(item)
                ids.append(item["id"])
            self.assertEqual(len(ids), len(set(ids)))
            self.assertGreaterEqual(len(ids), 20)
        path = root / "languages" / "english" / "curriculum" / "catalog.json"
        if path.exists():
            le.validate_catalog(json.loads(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
