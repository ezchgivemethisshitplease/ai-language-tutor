"""Owner authorization and scope tests; these never contact Codex or a real learner."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import backup
import personalization as prefs
import storage
import web_tutor
from tests.test_web_tutor import EXERCISE, FakeBridge


class PersonalizationTests(unittest.TestCase):
    def setUp(self):
        self.history = {
            "schema": 1,
            "conversations": {
                "chat1": {
                    "messages": [
                        {
                            "id": "human1",
                            "role": "user",
                            "text": 'Please remember: I prefer short explanations. Example: "I live in Mars".',
                        },
                        {"id": "assistant1", "role": "assistant", "text": "I prefer pineapple."},
                    ]
                },
                "chat2": {"messages": []},
            },
        }

    def test_defaults_are_explicit_without_invented_interests(self):
        before = copy.deepcopy(self.history)
        value = prefs.snapshot(self.history)
        self.assertEqual(value["account_preferences"]["dialect"], "us")
        self.assertEqual(value["account_preferences"]["topics"], [])
        self.assertEqual(before, self.history)
        for direction in value["directions"]:
            prefs.context(direction["context"])

    def test_account_and_chat_overrides_do_not_cross_scope(self):
        account = prefs.preferences({"register": "informal", "notes": "Keep it plain"})
        work = prefs.context({"register": "professional"}, direction_id="work")
        self.assertEqual(prefs.effective(account, work)["register"], "professional")
        self.assertEqual(prefs.effective(account, prefs.context())["register"], "informal")
        self.assertEqual(account["register"], "informal")

    def test_validation_rejects_unknowns_limits_and_invalid_enums(self):
        for value in (
            {"dialect": "invented"},
            {"level": "C1"},
            {"notes": "x" * 1201},
            {"topics": ["same", "same"]},
        ):
            with self.assertRaises(ValueError):
                prefs.preferences(value)
        with self.assertRaises(ValueError):
            prefs.context({"challenge": "certified"})
        with self.assertRaises(ValueError):
            prefs.context(direction_id="unknown")

    def proposal(self, scope="account"):
        return prefs.propose(
            self.history,
            "chat1",
            {
                "text": "I prefer short explanations",
                "scope": scope,
                "source_message_id": "human1",
                "evidence": "I prefer short explanations.",
            },
        )

    def test_model_proposal_requires_owner_confirmation(self):
        result = self.proposal()
        self.assertFalse(result["saved"])
        self.assertEqual(prefs.selected_memories(self.history, "chat2"), [])
        self.assertEqual(self.proposal()["id"], result["id"])
        self.assertEqual(prefs.read(self.history)["revision"], 1)
        prefs.change_memory(
            self.history, {"action": "confirm", "id": result["id"], "expected_revision": 1}
        )
        memory = prefs.selected_memories(self.history, "chat2")[0]
        self.assertEqual(memory["source"]["message_id"], "human1")
        self.assertIn("confirmed_at", memory)
        self.assertFalse(
            prefs.change_memory(self.history, {"action": "confirm", "id": result["id"]})
        )

    def test_forged_or_assistant_sources_are_rejected_without_mutation(self):
        for source, evidence in (
            ("assistant1", "I prefer pineapple."),
            ("human1", "Invented claim"),
            ("missing", "I prefer"),
        ):
            before = copy.deepcopy(self.history)
            with self.assertRaises(ValueError):
                prefs.propose(
                    self.history,
                    "chat1",
                    {"text": "claim", "source_message_id": source, "evidence": evidence},
                )
            self.assertEqual(self.history, before)

    def test_even_quote_proposal_remains_pending_until_owner_acts(self):
        prefs.propose(
            self.history,
            "chat1",
            {
                "text": "I live in Mars",
                "source_message_id": "human1",
                "evidence": '"I live in Mars"',
            },
        )
        self.assertEqual(prefs.selected_memories(self.history, "chat1"), [])

    def test_malformed_source_chat_is_rejected_as_schema_error(self):
        self.proposal()
        self.history["conversations"]["chat1"] = []
        with self.assertRaises(ValueError):
            prefs.validate(prefs.read(self.history), self.history["conversations"])
        with self.assertRaises(backup.BackupError):
            backup._document("web-chat.json", json.dumps(self.history).encode(), ["english"])

    def test_conversation_memory_is_never_supplied_to_other_chat(self):
        item = self.proposal("conversation")
        prefs.change_memory(self.history, {"action": "confirm", "id": item["id"]})
        self.assertEqual(len(prefs.selected_memories(self.history, "chat1")), 1)
        self.assertEqual(prefs.selected_memories(self.history, "chat2"), [])

    def test_owner_edit_delete_has_digest_only_audit_and_idempotent_retry(self):
        body = {"action": "save", "text": "private sentinel", "scope": "account"}
        prefs.change_memory(self.history, body)
        mid = prefs.read(self.history)["memories"][0]["id"]
        self.assertFalse(prefs.change_memory(self.history, body))
        prefs.change_memory(self.history, {"action": "save", "id": mid, "text": "changed sentinel"})
        self.assertEqual(
            prefs.read(self.history)["memories"][0]["source"], {"type": "user_setting"}
        )
        prefs.change_memory(self.history, {"action": "delete", "id": mid})
        self.assertNotIn("sentinel", json.dumps(prefs.read(self.history)))
        self.assertFalse(prefs.change_memory(self.history, {"action": "delete", "id": mid}))
        with self.assertRaises(prefs.Conflict):
            prefs.change_memory(
                self.history, {"action": "save", "text": "new", "expected_revision": 0}
            )


class WebPersonalizationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.tutor = web_tutor.WebTutor(self.root / "student", FakeBridge, self.root / "runtime")
        self.tutor.setup({})
        self.chat1 = self.tutor.create_conversation({"direction_id": "everyday"})["id"]
        self.chat2 = self.tutor.create_conversation({"direction_id": "work"})["id"]

    def tearDown(self):
        self.tutor.close()
        self.temporary.cleanup()

    def add_human(self, cid, text, mid="human1"):
        c = self.tutor._get(cid)
        c["messages"].append({"id": mid, "role": "user", "text": text})
        c["current_message_id"] = mid
        self.tutor._save()
        return c

    def test_settings_context_and_memories_preserve_learning_evidence(self):
        before = (self.tutor.student / "english/learner.json").read_bytes()
        self.tutor.preferences(
            {"preferences": {"dialect": "uk", "correction_style": "gentle"}, "expected_revision": 0}
        )
        self.tutor.context(
            {
                "conversation_id": self.chat1,
                "context": {"register": "neutral", "goal": "Order coffee"},
                "expected_revision": 1,
            }
        )
        self.tutor.memory({"action": "save", "text": "Short explanations please"})
        self.assertEqual(before, (self.tutor.student / "english/learner.json").read_bytes())
        self.assertEqual(
            self.tutor.conversation(self.chat1)["effective_preferences"]["register"], "neutral"
        )
        self.assertEqual(
            self.tutor.conversation(self.chat2)["effective_preferences"]["register"], "professional"
        )
        self.assertEqual(
            self.tutor.conversation(self.chat2)["effective_preferences"]["dialect"], "uk"
        )

    def test_stale_revision_and_invalid_preferences_leave_history_unchanged(self):
        before = self.tutor.path.read_bytes()
        for body in (
            {"preferences": {"dialect": "martian"}},
            {"preferences": {"dialect": "uk"}, "expected_revision": 42},
        ):
            with self.assertRaises(ValueError):
                self.tutor.preferences(body)
            self.assertEqual(before, self.tutor.path.read_bytes())
        with self.assertRaises(ValueError):
            self.tutor.memory(
                {
                    "action": "save",
                    "text": "private",
                    "scope": "conversation",
                    "conversation_id": "absent",
                }
            )
        self.assertEqual(before, self.tutor.path.read_bytes())

    def test_current_exercise_is_learner_view_without_keys(self):
        c = self.add_human(self.chat1, "Start")
        self.tutor._action(c, "present", {"exercise": EXERCISE})
        snapshot = self.tutor.conversation(self.chat1)["current_exercise"]
        self.assertFalse(snapshot["answered"])
        self.assertNotIn("answers", snapshot["learner_view"])
        self.assertNotIn("exhaustive", snapshot["learner_view"])
        self.assertIsNone(self.tutor.conversation(self.chat2)["current_exercise"])
        self.assertNotIn('"answers"', json.dumps(self.tutor.status()))

    def test_session_ownership_handoff_preserves_same_saved_plan(self):
        self.tutor.lesson("start", conversation_id=self.chat1)
        state_before = self.tutor._state()
        result = self.tutor.lesson("finish", True, self.chat2)
        self.assertEqual(result["reason"], "lesson_owned_elsewhere")
        self.assertEqual(self.tutor._state(), state_before)
        with self.assertRaises(prefs.Conflict):
            self.tutor.handoff({"conversation_id": self.chat2, "expected_owner": None})
        self.tutor.handoff({"conversation_id": self.chat2, "expected_owner": self.chat1})
        self.assertEqual(self.tutor._state(), state_before)
        self.assertFalse(self.tutor.conversation(self.chat1)["lesson"]["can_manage"])
        self.assertTrue(self.tutor.conversation(self.chat2)["lesson"]["can_manage"])
        self.assertEqual(
            self.tutor.status()["platform_summary"]["active_session_owner"]["conversation_id"],
            self.chat2,
        )

    def test_finishing_lesson_never_claims_later_cli_session(self):
        self.tutor.lesson("start", conversation_id=self.chat1)
        original_sid = self.tutor._state()["active_session_id"]
        engine = self.tutor._engine

        def finish_then_external_start(*args):
            result = engine(*args)
            if args[0] == "finish":
                engine("start")
            return result

        with patch.object(self.tutor, "_engine", side_effect=finish_then_external_start):
            self.tutor.lesson("finish", True, self.chat1)
        fresh_sid = self.tutor._state()["active_session_id"]
        self.assertNotEqual(original_sid, fresh_sid)
        self.assertNotIn(fresh_sid, self.tutor.data["session_owners"])
        self.assertEqual(self.tutor._get(self.chat1)["lesson_session_id"], original_sid)
        self.assertFalse(self.tutor.conversation(self.chat1)["lesson"]["can_manage"])

    def test_concurrent_cli_start_requires_explicit_handoff(self):
        engine = self.tutor._engine

        def external_start_then_resume(*args):
            if args[0] == "start":
                engine("start")
            return engine(*args)

        with patch.object(self.tutor, "_engine", side_effect=external_start_then_resume):
            result = self.tutor.lesson("start", conversation_id=self.chat1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "lesson_changed")
        self.assertNotIn(
            self.tutor._state()["active_session_id"], self.tutor.data.get("session_owners", {})
        )

    def test_legacy_unbound_session_requires_explicit_claim(self):
        self.tutor.lesson("start")
        sid = self.tutor._state()["active_session_id"]
        self.assertEqual(
            self.tutor.lesson("start", conversation_id=self.chat1)["reason"],
            "lesson_owned_elsewhere",
        )
        self.tutor.handoff({"conversation_id": self.chat1, "expected_owner": None})
        self.assertEqual(sid, self.tutor._state()["active_session_id"])

    def test_model_only_proposes_current_human_memory(self):
        c = self.add_human(self.chat1, "Remember that I like concise feedback.")
        args = {
            "text": "Concise feedback",
            "scope": "account",
            "source_message_id": "human1",
            "evidence": "I like concise feedback.",
        }
        result = self.tutor._action(c, "propose_memory", args)
        self.assertFalse(result["saved"])
        self.assertEqual(self.tutor._turn_personalization(c)["memories"], [])
        with self.assertRaises(ValueError):
            self.tutor._action(c, "propose_memory", {**args, "source_message_id": "past-human"})
        self.tutor.memory({"action": "confirm", "id": result["id"]})
        self.assertEqual(len(self.tutor._turn_personalization(c)["memories"]), 1)

    def test_backup_round_trip_preserves_explicit_settings_and_source(self):
        self.tutor.preferences({"preferences": {"dialect": "international"}})
        self.tutor.memory(
            {
                "action": "save",
                "scope": "conversation",
                "conversation_id": self.chat1,
                "text": "Use meeting scenarios",
            }
        )
        bundle = self.root / "archive.zip"
        backup.create_backup(self.tutor.student, bundle)
        destination = self.root / "restored"
        backup.restore_backup(bundle, destination)
        restored = storage.load(destination / "web-chat.json", None)
        web_tutor.validate_history(restored)
        self.assertEqual(restored["personalization"], self.tutor.data["personalization"])

    def test_pending_open_attempt_returns_actionable_review_contract(self):
        c = self.add_human(self.chat1, "Start")
        self.tutor.lesson("start", conversation_id=self.chat1)
        exercise = {
            "id": "open-web-test",
            "type": "short_writing",
            "skill_id": "a1-01",
            "level": "A1",
            "domain": "writing",
            "prompt": "Write a short update",
            "rubric": {
                "content": "Convey update",
                "clarity": "Readable",
                "grammar": "Forms",
                "tone": "Suitable",
            },
        }
        self.tutor._action(c, "present", {"exercise": exercise})
        self.add_human(self.chat1, "We has a delay because the tests is failing.", "human2")
        result = self.tutor._action(
            c, "attempt", {"exercise_id": exercise["id"], "response_message_id": "human2"}
        )
        self.assertTrue(result["review_required"])
        oid = result["observation_id"]
        review = {
            "source": "llm",
            "judgment": "incorrect",
            "criteria": {"content": 0.4, "clarity": 0.8, "grammar": 0.3, "tone": 1},
            "rationale": "Clear meaning with errors",
        }
        rejected = self.tutor._action(c, "review", {"observation_id": oid, "review": review})
        self.assertFalse(rejected["reviewed"])
        self.assertIn("contradicts", rejected["validation"])
        self.assertEqual(self.tutor._state()["reviews"], [])
        accepted = self.tutor._action(
            c, "review", {"observation_id": oid, "review": {**review, "judgment": "unnatural"}}
        )
        self.assertIn("annotation", accepted)
        self.assertEqual(
            self.tutor._state()["reviews"][0]["review"]["criteria"], review["criteria"]
        )
        other = self.add_human(self.chat2, "Review someone else")
        with self.assertRaises(ValueError):
            self.tutor._action(other, "review", {"observation_id": oid, "review": review})

    def test_turn_snapshot_is_fixed_but_next_turn_uses_current_preferences(self):
        c = self.add_human(self.chat1, "Hi")
        c["turn_personalization"] = self.tutor._turn_personalization(c)
        c["active"] = True
        c["tool_contract_revision"] = web_tutor.TOOL_CONTRACT_REVISION
        self.tutor.preferences({"preferences": {"dialect": "uk"}})
        self.assertEqual(
            self.tutor._action(c, "status", {})["personalization"]["effective_preferences"][
                "dialect"
            ],
            "us",
        )
        self.assertEqual(
            self.tutor._turn_personalization(c)["effective_preferences"]["dialect"], "uk"
        )

    def test_first_message_context_is_part_of_durable_retry_identity(self):
        body = {
            "message": "Coffee please",
            "request_id": "creation-retry",
            "context": {"goal": "Order coffee"},
            "direction_id": "everyday",
        }
        with patch.object(self.tutor, "_run_turn"):
            receipt = self.tutor.chat(body)
        self.assertTrue(self.tutor.chat(body)["duplicate"])
        cid = receipt["conversation_id"]
        self.assertEqual(self.tutor.conversation(cid)["context"]["goal"], "Order coffee")
        with self.assertRaises(ValueError):
            self.tutor.chat({**body, "context": {"goal": "Changed goal"}})
        self.assertEqual(len(self.tutor.conversation(cid)["messages"]), 1)

    def test_model_status_excludes_other_chat_raw_answers(self):
        c = self.add_human(self.chat1, "Start")
        self.tutor.lesson("start", conversation_id=self.chat1)
        self.tutor._action(c, "present", {"exercise": EXERCISE})
        self.add_human(self.chat1, "private raw sentinel", "human2")
        self.tutor._action(
            c, "attempt", {"exercise_id": EXERCISE["id"], "response_message_id": "human2"}
        )
        other = self.add_human(self.chat2, "Hello")
        view = self.tutor._action(other, "status", {})
        self.assertEqual(view["recent_observations"], [])
        self.assertNotIn("private raw sentinel", json.dumps(view))
        c.pop("observation_ids")
        c["exercises"][EXERCISE["id"]].pop("last_observation_id")
        self.assertEqual(len(self.tutor._action(c, "status", {})["recent_observations"]), 1)

    def test_legacy_history_defaults_are_nonmutating_and_contract_rotates(self):
        c = self.add_human(self.chat1, "Hi")
        c.update(active=True, thread_id="legacy-thread", current_message_id="human1")
        with (
            patch.object(FakeBridge, "turn_start", return_value={"turn": {"id": "new-turn"}}),
            patch.object(
                FakeBridge, "thread_start", return_value={"thread": {"id": "new-thread"}}
            ) as start,
        ):
            self.tutor._run_turn(self.chat1, "human1", None)
        start.assert_called_once()
        self.assertEqual(c["thread_id"], "new-thread")
        self.assertEqual(c["retired_thread_ids"], ["legacy-thread"])
        self.assertEqual(c["messages"][0]["text"], "Hi")
        self.assertEqual(c["tool_contract_revision"], web_tutor.TOOL_CONTRACT_REVISION)


class PersonalizationHTTPTests(unittest.TestCase):
    def test_protected_endpoints_revisions_scopes_and_session_handoff(self):
        import threading
        import urllib.error
        import urllib.request
        import serve
        import srs

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            student = root / "student"
            tutor = web_tutor.WebTutor(student, FakeBridge, root / "runtime")
            tutor.setup({})
            with patch.object(serve, "STUDENT", student), patch.object(srs, "STUDENT", student):
                server = serve.create_server(tutor=tutor)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base = f"http://127.0.0.1:{server.server_address[1]}"
                try:
                    session = json.load(urllib.request.urlopen(base + "/api/session"))
                    headers = {
                        "X-Tutor-Token": session["token"],
                        "X-Tutor-Namespace": session["namespace"],
                        "Content-Type": "application/json",
                    }

                    def request(path, body=None, override=None):
                        req = urllib.request.Request(
                            base + "/api/web/" + path,
                            headers=override or headers,
                            data=None if body is None else json.dumps(body).encode(),
                        )
                        with urllib.request.urlopen(req) as response:
                            return json.load(response)

                    with self.assertRaises(urllib.error.HTTPError) as unauthorized:
                        request("personalization", override={"X-Tutor-Token": "wrong"})
                    self.assertEqual(unauthorized.exception.code, 403)
                    unauthorized.exception.close()
                    self.assertEqual(
                        request("personalization")["account_preferences"]["dialect"], "us"
                    )
                    updated = request(
                        "preferences", {"preferences": {"dialect": "uk"}, "expected_revision": 0}
                    )
                    self.assertEqual(updated["revision"], 1)
                    with self.assertRaises(urllib.error.HTTPError) as stale:
                        request(
                            "preferences",
                            {"preferences": {"dialect": "us"}, "expected_revision": 0},
                        )
                    self.assertEqual(stale.exception.code, 409)
                    stale.exception.close()
                    first = request("conversations", {"direction_id": "everyday"})
                    second = request("conversations", {"direction_id": "work"})
                    changed = request(
                        "context",
                        {
                            "conversation_id": first["id"],
                            "context": {"title": "Coffee practice"},
                            "expected_revision": 1,
                        },
                    )
                    self.assertEqual(changed["context"]["title"], "Coffee practice")
                    memory = request(
                        "memory",
                        {
                            "action": "save",
                            "text": "Use concise feedback",
                            "scope": "account",
                            "expected_revision": 2,
                        },
                    )
                    self.assertEqual(memory["memories"][0]["source"], {"type": "user_setting"})
                    request("session", {"action": "start", "conversation_id": first["id"]})
                    denied = request(
                        "session",
                        {
                            "action": "finish",
                            "conversation_id": second["id"],
                            "allow_incomplete": True,
                        },
                    )
                    self.assertEqual(denied["reason"], "lesson_owned_elsewhere")
                    moved = request(
                        "session",
                        {
                            "action": "handoff",
                            "conversation_id": second["id"],
                            "expected_owner": first["id"],
                        },
                    )
                    self.assertTrue(moved["lesson"]["can_manage"])
                    current = request("status")
                    self.assertEqual(
                        current["personalization"]["account_preferences"]["dialect"], "uk"
                    )
                    self.assertEqual(current["platform_summary"]["pending_review_count"], 0)
                    self.assertEqual(
                        current["platform_summary"]["domains"]["speaking"]["eligible_attempts"], 0
                    )
                    self.assertNotIn('"answers"', json.dumps(current))
                finally:
                    server.shutdown()
                    thread.join(timeout=2)
                    server.server_close()
