import json
import subprocess
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import backup
import serve
import srs
import storage
import web_tutor


EXERCISE = {
    "id": "web-a1-test",
    "type": "cloze",
    "skill_id": "a1-01",
    "level": "A1",
    "domain": "grammar",
    "prompt": "I ___ at home.",
    "answers": ["am"],
    "exhaustive": True,
}


class FakeBridge:
    def __init__(self, **kwargs):
        self.event = kwargs["event_callback"]
        self.tool = kwargs["tool_callback"]
        self.turns = 0
        self.closed = False
        self.thread = "test-thread"

    def start(self):
        return self

    def account_status(self):
        return {"status": "chatgpt", "plan_type": "plus"}

    def models(self):
        return [{"id": "test-model", "displayName": "Test"}]

    def login_start(self):
        return {"auth_url": "https://auth.openai.com/test", "login_id": "test-login"}

    def thread_start(self, **kwargs):
        assert "Humanize" in kwargs["base_instructions"]
        assert kwargs["dynamic_tools"][0]["name"] == "tutor"
        return {"thread": {"id": self.thread}}

    def thread_resume(self, thread_id):
        return {"thread": {"id": thread_id}}

    def turn_start(self, thread_id, text, **kwargs):
        self.turns += 1
        tid = f"turn-{self.turns}"
        context = json.loads(text)
        self.event("turn/started", {"threadId": thread_id, "turn": {"id": tid}})
        if self.turns == 1:
            for action, arguments in [
                ("lesson", {"action": "start"}),
                ("present", {"exercise": EXERCISE}),
            ]:
                response = self.tool(
                    {
                        "threadId": thread_id,
                        "tool": "tutor",
                        "arguments": {"action": action, "arguments": arguments},
                    }
                )
                assert response["success"], response
            reply = "Вставь форму be: I ___ at home."
        else:
            response = self.tool(
                {
                    "threadId": thread_id,
                    "tool": "tutor",
                    "arguments": {
                        "action": "attempt",
                        "arguments": {
                            "exercise_id": EXERCISE["id"],
                            "response_message_id": context["response_message_id"],
                        },
                    },
                }
            )
            assert response["success"], response
            reply = "Ответ сохранён."
        mid = f"assistant-{self.turns}"
        self.event(
            "item/agentMessage/delta", {"threadId": thread_id, "itemId": mid, "delta": reply[:5]}
        )
        self.event(
            "item/agentMessage/delta", {"threadId": thread_id, "itemId": mid, "delta": reply[5:]}
        )
        self.event(
            "item/completed",
            {"threadId": thread_id, "item": {"id": mid, "type": "agentMessage", "text": reply}},
        )
        self.event(
            "turn/completed", {"threadId": thread_id, "turn": {"id": tid, "status": "completed"}}
        )
        return {"turn": {"id": tid}}

    def turn_interrupt(self, thread_id, turn_id):
        self.event(
            "turn/completed",
            {"threadId": thread_id, "turn": {"id": turn_id, "status": "interrupted"}},
        )

    def close(self):
        self.closed = True


class WebTutorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.student = self.root / "student"
        self.tutor = web_tutor.WebTutor(self.student, FakeBridge, self.root / "runtime")

    def tearDown(self):
        self.tutor.close()
        self.temp.cleanup()

    def setup_learner(self):
        self.tutor.setup({"daily_minutes": 15, "objectives": ["Read mail"]})

    def wait_for_turn(self, cid):
        end = time.monotonic() + 6
        while time.monotonic() < end:
            snapshot = self.tutor.conversation(cid)
            if not snapshot["active"]:
                self.assertEqual(snapshot["last_status"], "completed")
                return snapshot
            time.sleep(0.01)
        self.fail("fake turn timed out")

    def begin(self):
        self.setup_learner()
        receipt = self.tutor.chat({"message": "Начнём", "request_id": "r1"})
        self.wait_for_turn(receipt["conversation_id"])
        return receipt["conversation_id"]

    def test_uninitialized_profile_and_invalid_setup_do_not_make_learner(self):
        self.assertFalse(self.tutor.status()["initialized"])
        with self.assertRaises(ValueError):
            self.tutor.setup({"daily_minutes": True})
        self.assertFalse((self.student / "english/learner.json").exists())
        with self.assertRaises(ValueError):
            self.tutor.chat({"message": "Hi", "request_id": "first"})

    def test_profile_can_explicitly_clear_goals_without_resetting_progress(self):
        cid = self.begin()
        before = self.tutor.conversation(cid)
        session_id = self.tutor._state()["active_session_id"]
        self.tutor.setup({"objectives": [], "daily_minutes": 25})
        state = self.tutor._state()
        self.assertEqual(state["objectives"], [])
        self.assertEqual(state["profile"]["daily_minutes"], 25)
        self.assertEqual(state["active_session_id"], session_id)
        self.assertEqual(self.tutor.conversation(cid), before)

    def test_whisper_provenance_survives_retry_and_cannot_establish_written_production(self):
        self.setup_learner()
        request = {
            "message": "Начнём",
            "request_id": "voice-first",
            "input_source": "whisper_transcript",
        }
        cid = self.tutor.chat(request)["conversation_id"]
        self.wait_for_turn(cid)
        self.assertEqual(
            self.tutor.conversation(cid)["messages"][0]["input_source"], "whisper_transcript"
        )
        self.assertTrue(self.tutor.chat(request)["duplicate"])
        with self.assertRaises(ValueError):
            self.tutor.chat({**request, "input_source": "typed"})
        c = self.tutor.data["conversations"][cid]
        exercise = {
            "id": "voice-not-writing",
            "type": "short_writing",
            "skill_id": "a1-01",
            "level": "A1",
            "domain": "writing",
            "prompt": "Write about yourself.",
            "rubric": {"clarity": "The written response is clear."},
        }
        self.tutor._action(c, "present", {"exercise": exercise})
        c["current_message_id"] = "voice-writing-response"
        c["messages"].append(
            {
                "id": c["current_message_id"],
                "role": "user",
                "text": "I am at home.",
                "input_source": "whisper_transcript",
            }
        )
        result = self.tutor._action(
            c,
            "attempt",
            {"exercise_id": exercise["id"], "response_message_id": c["current_message_id"]},
        )
        self.assertFalse(result["recorded"])
        self.assertEqual(self.tutor._state()["observations"], [])

    def test_streaming_human_response_and_canonical_grading(self):
        cid = self.begin()
        exact = "Am  \n"
        self.tutor.chat({"conversation_id": cid, "message": exact, "request_id": "r2"})
        snapshot = self.wait_for_turn(cid)
        state = storage.load(self.student / "english/learner.json", None)
        self.assertEqual(state["observations"][0]["response"], exact)
        self.assertEqual(state["observations"][0]["grade"]["status"], "correct")
        self.assertEqual(snapshot["messages"][-1]["text"], "Ответ сохранён.")
        events = self.tutor.events(cid, 0)
        self.assertTrue(any(e["type"] == "delta" for e in events["events"]))
        self.assertFalse(self.tutor.events(cid, snapshot["cursor"])["events"])
        self.assertNotIn("answers", json.dumps(snapshot, ensure_ascii=False))

    def test_request_retry_does_not_duplicate_human_or_model_turn(self):
        cid = self.begin()
        before = self.tutor.conversation(cid)
        response = self.tutor.chat({"message": "Начнём", "request_id": "r1"})
        self.assertTrue(response["duplicate"])
        self.assertEqual(before, self.tutor.conversation(cid))
        with self.assertRaises(ValueError):
            self.tutor.chat({"message": "Changed", "request_id": "r1"})
        self.assertEqual(self.tutor.bridge.turns, 1)

    def test_no_model_invented_answer_pre_task_grade_or_human_attestation(self):
        cid = self.begin()
        c = self.tutor.data["conversations"][cid]
        c["active"] = True

        def call(action, args):
            return self.tutor._tool_call(
                {
                    "threadId": c["thread_id"],
                    "tool": "tutor",
                    "arguments": {"action": action, "arguments": args},
                }
            )

        self.assertFalse(
            call(
                "attempt",
                {"exercise_id": EXERCISE["id"], "response_message_id": c["current_message_id"]},
            )["success"]
        )
        self.assertFalse(
            call("review", {"observation_id": "x", "review": {"source": "human"}})["success"]
        )
        self.assertFalse(call("reference", {"name": "../../.codex/auth.json"})["success"])
        self.assertFalse(call("shell", {"command": "whoami"})["success"])
        self.assertEqual(self.tutor._state()["observations"], [])

    def test_repeated_attempt_is_idempotent_and_review_cannot_change_original(self):
        cid = self.begin()
        self.tutor.chat({"conversation_id": cid, "message": "am", "request_id": "r2"})
        self.wait_for_turn(cid)
        c = self.tutor.data["conversations"][cid]
        args = {"exercise_id": EXERCISE["id"], "response_message_id": c["current_message_id"]}
        first = self.tutor._action(c, "attempt", args)
        self.assertEqual(first, self.tutor._action(c, "attempt", args))
        self.assertEqual(len(self.tutor._state()["observations"]), 1)
        with self.assertRaises(ValueError):
            self.tutor._action(c, "attempt", {**args, "hints_used": True})

    def test_cannot_replace_exercise_or_invent_audio(self):
        cid = self.begin()
        c = self.tutor.data["conversations"][cid]
        with self.assertRaises(ValueError):
            self.tutor._action(c, "present", {"exercise": {**EXERCISE, "answers": ["was"]}})
        with self.assertRaises(ValueError):
            self.tutor._action(
                c, "present", {"exercise": {**EXERCISE, "audio_evidence": "fabricated.wav"}}
            )

    def test_backup_contains_transcript_excludes_codex_and_restart_preserves_evidence(self):
        cid = self.begin()
        self.tutor.data["conversations"][cid]["active"] = True
        self.tutor._save()
        auth = self.root / "runtime/codex-home/auth.json"
        auth.parent.mkdir(parents=True)
        auth.write_text('{"access_token":"secret"}')
        archive = self.root / "learner.zip"
        backup.create_backup(self.student, archive)
        restored = self.root / "restored"
        backup.restore_backup(archive, restored)
        second = web_tutor.WebTutor(restored, FakeBridge, self.root / "runtime2")
        try:
            snapshot = second.conversation(cid)
            self.assertFalse(snapshot["active"])
            self.assertEqual(snapshot["last_status"], "interrupted")
            self.assertEqual(snapshot["messages"][0]["text"], "Начнём")
            self.assertFalse(list(restored.rglob("auth.json")))
        finally:
            second.close()

    def test_event_gap_requires_snapshot_and_corruption_never_resets_history(self):
        cid = self.begin()
        c = self.tutor.data["conversations"][cid]
        for _ in range(web_tutor.MAX_EVENTS + 1):
            self.tutor._event(c, "state")
        self.assertTrue(self.tutor.events(cid, 0)["reset"])
        self.tutor.path.write_text("{broken")
        with self.assertRaises(ValueError):
            web_tutor.WebTutor(self.student, FakeBridge, self.root / "other")
        self.assertEqual(self.tutor.path.read_text(), "{broken")

    def test_failed_receipt_save_never_becomes_an_acknowledged_memory_only_retry(self):
        self.setup_learner()
        body = {"message": "Начнём", "request_id": "failed-write"}
        for error in (OSError("disk full"), storage.StorageError("corrupt history")):
            with self.subTest(error=type(error).__name__):
                tutor = web_tutor.WebTutor(self.student, FakeBridge, self.root / "failed-runtime")
                try:
                    with patch.object(storage, "save", side_effect=error):
                        with self.assertRaises((OSError, storage.StorageError)):
                            tutor.chat(body)
                    self.assertEqual(tutor.data["conversations"], {})
                    self.assertTrue(tutor.persistence_error)
                    with self.assertRaises(RuntimeError):
                        tutor.chat(body)
                    self.assertEqual(tutor.bridge.turns, 0)
                finally:
                    tutor.close()

    def test_bounded_stream_overflow_retires_generation_and_preserves_human_text(self):
        cid = self.begin()
        c = self.tutor.data["conversations"][cid]
        c["active"] = True
        before = self.tutor.conversation(cid)["messages"]
        old = self.tutor.bridge
        old.event("bridge/eventsDropped", {"count": 100})
        snapshot = self.tutor.conversation(cid)
        self.assertFalse(snapshot["active"])
        self.assertEqual(snapshot["messages"], before)
        self.assertIsNone(c["thread_id"])
        old.event("turn/started", {"threadId": old.thread, "turn": {"id": "stale"}})
        self.assertFalse(self.tutor.conversation(cid)["active"])

    def test_cli_timeout_is_a_controlled_failure_and_backup_warning_is_separate(self):
        self.setup_learner()
        with patch.object(
            web_tutor.subprocess, "run", side_effect=subprocess.TimeoutExpired("tutor", 45)
        ):
            with self.assertRaises(RuntimeError):
                self.tutor._engine("status")
        cid = self.begin()
        with patch.object(
            web_tutor.backup, "maybe_automatic_backup", return_value={"status": "unavailable"}
        ):
            self.tutor.chat({"conversation_id": cid, "message": "am", "request_id": "backup-r2"})
            self.wait_for_turn(cid)
        self.assertEqual(self.tutor.status()["backup"]["status"], "unavailable")
        self.assertEqual(len(self.tutor._state()["observations"]), 1)

    def test_identical_review_for_two_observations_has_distinct_stable_ids(self):
        cid = self.begin()
        c = self.tutor.data["conversations"][cid]
        review = {
            "source": "llm",
            "judgment": "correct",
            "rationale": "The sentence is accurate.",
            "criteria": {"accuracy": 1},
        }
        for i in range(2):
            c["current_message_id"] = f"prompt-{i}"
            c["messages"].append(
                {"id": c["current_message_id"], "role": "user", "text": "Next task"}
            )
            exercise = {
                "id": f"open-{i}",
                "type": "short_writing",
                "skill_id": "a1-01",
                "level": "A1",
                "domain": "writing",
                "prompt": "Write a sentence about yourself.",
                "rubric": {"accuracy": "The sentence is grammatical."},
            }
            self.tutor._action(c, "present", {"exercise": exercise})
            c["current_message_id"] = f"response-{i}"
            c["messages"].append(
                {"id": c["current_message_id"], "role": "user", "text": "I am at home."}
            )
            result = self.tutor._action(
                c,
                "attempt",
                {"exercise_id": exercise["id"], "response_message_id": c["current_message_id"]},
            )
            args = {"observation_id": result["attempt_id"], "review": review}
            first = self.tutor._action(c, "review", args)
            repeated = self.tutor._action(c, "review", args)
            self.assertTrue(repeated["duplicate"])
            self.assertEqual(first["annotation"], repeated["annotation"])
        state = self.tutor._state()
        self.assertEqual(len(state["reviews"]), 2)
        self.assertNotEqual(state["reviews"][0]["id"], state["reviews"][1]["id"])

    def test_ambiguous_start_retires_transport_and_stale_events_cannot_finish_new_turn(self):
        class TimeoutBridge(FakeBridge):
            def turn_start(self, thread_id, text, **kwargs):
                self.event("turn/started", {"threadId": thread_id, "turn": {"id": "old-turn"}})
                raise TimeoutError("response lost after accepted start")

        class HoldingBridge(FakeBridge):
            def turn_start(self, thread_id, text, **kwargs):
                self.event("turn/started", {"threadId": thread_id, "turn": {"id": "new-turn"}})
                return {"turn": {"id": "new-turn"}}

        bridges = []

        def factory(**kwargs):
            bridge = (TimeoutBridge if not bridges else HoldingBridge)(**kwargs)
            bridges.append(bridge)
            return bridge

        self.tutor.bridge_factory = factory
        self.setup_learner()
        cid = self.tutor.chat({"message": "First", "request_id": "first"})["conversation_id"]
        end = time.monotonic() + 5
        while self.tutor.conversation(cid)["active"] and time.monotonic() < end:
            time.sleep(0.01)
        self.assertEqual(self.tutor.conversation(cid)["last_status"], "failed")
        self.assertTrue(bridges[0].closed)
        self.assertIsNone(self.tutor.data["conversations"][cid]["thread_id"])
        self.tutor.chat({"conversation_id": cid, "message": "Continue", "request_id": "second"})
        end = time.monotonic() + 5
        while self.tutor.conversation(cid)["turn_id"] != "new-turn" and time.monotonic() < end:
            time.sleep(0.01)
        bridges[0].event(
            "turn/completed",
            {"threadId": "test-thread", "turn": {"id": "old-turn", "status": "completed"}},
        )
        self.tutor._on_event(
            "turn/completed",
            {"threadId": "test-thread", "turn": {"id": "old-turn", "status": "completed"}},
        )
        self.assertTrue(self.tutor.conversation(cid)["active"])
        old_call = bridges[0].tool(
            {
                "threadId": "test-thread",
                "tool": "tutor",
                "arguments": {"action": "lesson", "arguments": {"action": "start"}},
            }
        )
        self.assertFalse(old_call["success"])
        bridges[1].event(
            "turn/completed",
            {"threadId": "test-thread", "turn": {"id": "new-turn", "status": "completed"}},
        )
        self.assertFalse(self.tutor.conversation(cid)["active"])


class WebChatHTTPTests(unittest.TestCase):
    def test_port_collision_preserves_the_bind_error_and_existing_host(self):
        with tempfile.TemporaryDirectory() as temporary:
            student = Path(temporary) / "student"
            controller = web_tutor.WebTutor(student, FakeBridge, Path(temporary) / "runtime")
            with patch.object(serve, "STUDENT", student):
                first = serve.create_server(tutor=controller)
                try:
                    with self.assertRaises(OSError):
                        serve.create_server(first.server_address[1], tutor=controller)
                    self.assertFalse(controller.closed)
                finally:
                    first.server_close()

    def test_initial_setup_auth_static_and_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            student = root / "student"
            tutor = web_tutor.WebTutor(student, FakeBridge, root / "runtime")
            with patch.object(serve, "STUDENT", student), patch.object(srs, "STUDENT", student):
                server = serve.create_server(tutor=tutor)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base = f"http://127.0.0.1:{server.server_address[1]}"
                try:
                    with urllib.request.urlopen(base + "/") as response:
                        self.assertEqual(response.status, 200)
                    session = json.load(urllib.request.urlopen(base + "/api/session"))
                    with self.assertRaises(urllib.error.HTTPError) as rejected:
                        urllib.request.urlopen(base + "/api/web/status")
                    self.assertEqual(rejected.exception.code, 403)
                    rejected.exception.close()
                    headers = {
                        "X-Tutor-Token": session["token"],
                        "X-Tutor-Namespace": session["namespace"],
                        "Content-Type": "application/json",
                    }
                    with urllib.request.urlopen(
                        urllib.request.Request(base + "/api/web/status", headers=headers)
                    ) as response:
                        self.assertFalse(json.load(response)["initialized"])
                    self.assertEqual(serve.namespace(), session["namespace"])
                    with urllib.request.urlopen(
                        urllib.request.Request(base + "/api/web/login", headers=headers, data=b"{}")
                    ) as response:
                        self.assertIn("auth_url", json.load(response))
                    request = urllib.request.Request(
                        base + "/api/web/setup", headers=headers, data=b'{"daily_minutes":15}'
                    )
                    with urllib.request.urlopen(request) as response:
                        self.assertTrue(json.load(response)["ok"])
                    with urllib.request.urlopen(
                        urllib.request.Request(base + "/api/web/status", headers=headers)
                    ) as response:
                        self.assertTrue(json.load(response)["initialized"])
                    with self.assertRaises(urllib.error.HTTPError) as stale:
                        urllib.request.urlopen(
                            urllib.request.Request(
                                base + "/api/web/chat", headers=headers, data=b"{}"
                            )
                        )
                    self.assertEqual(stale.exception.code, 409)
                    stale.exception.close()
                    with urllib.request.urlopen(
                        urllib.request.Request(base + "/api/web/backup", headers=headers)
                    ) as response:
                        self.assertEqual(response.headers.get_content_type(), "application/zip")
                        self.assertTrue(response.read().startswith(b"PK"))
                finally:
                    server.shutdown()
                    thread.join(timeout=2)
                    server.server_close()


if __name__ == "__main__":
    unittest.main()
