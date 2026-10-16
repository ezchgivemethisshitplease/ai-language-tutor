import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import activity
import serve
import srs
import storage
import tts
import voice

ROOT = Path(__file__).resolve().parents[1]


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.student = self.base / "student"

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *args, success=True):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools/tutor.py"),
                "--student-dir",
                str(self.student),
                *args,
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0 if success else 1, result.stderr)
        return json.loads(result.stdout) if success else result.stderr

    def test_lifecycle_recovery_and_safe_roundtrip(self):
        result = self.run_cli("init")
        self.assertIn("по-русски", result["onboarding_ru"])
        self.assertTrue(self.run_cli("status")["valid"])
        self.run_cli("configure", "--daily-minutes", "0", success=False)
        self.run_cli("configure", "--voice-channel", "external")
        self.assertEqual(
            storage.load(self.student / "english/learner.json", None)["profile"]["daily_minutes"],
            30,
        )
        first = self.run_cli("start")
        sid = first["id"]
        self.assertEqual(self.run_cli("start")["session"]["id"], sid)
        self.run_cli("interrupt", "--session", sid)
        self.assertEqual(self.run_cli("start")["session"]["status"], "active")
        self.run_cli("step", "--session", sid, "--step", "wrap", "--defer", success=False)
        self.run_cli("finish", "--session", sid, success=False)
        self.run_cli("finish", "--session", sid, "--allow-incomplete")
        archive = self.base / "backup.json"
        self.run_cli("export", str(archive))
        restored = self.base / "restored"
        self.run_cli("import", str(archive), str(restored))
        self.assertEqual(
            storage.load(restored / "english/learner.json", None),
            storage.load(self.student / "english/learner.json", None),
        )
        self.run_cli("import", str(archive), str(restored), success=False)
        self.run_cli("export", str(self.student / "english/learner.json"), success=False)
        self.run_cli("init")
        self.assertEqual(
            storage.load(restored / "english/learner.json", None),
            storage.load(self.student / "english/learner.json", None),
        )

    def test_corruption_is_not_reset_and_recovery_is_explicit(self):
        self.run_cli("init")
        self.run_cli("start")
        path = self.student / "english/learner.json"
        path.write_text("{broken", encoding="utf-8")
        self.run_cli("init", success=False)
        self.assertEqual(path.read_text(), "{broken")
        self.run_cli("recover", "learner.json")
        self.assertTrue(self.run_cli("validate")["valid"])
        self.assertTrue(list(path.parent.glob("learner.json.recovery-*")))

    def test_import_rejects_traversal_before_creating_destination(self):
        self.run_cli("init")
        archive = self.base / "backup.json"
        self.run_cli("export", str(archive))
        data = storage.load(archive, None)
        data["files"]["../../escape"] = "no"
        storage.save(archive, data)
        dest = self.base / "new"
        self.run_cli("import", str(archive), str(dest), success=False)
        self.assertFalse(dest.exists())


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.student = Path(self.temp.name) / "student"
        (self.student / "english").mkdir(parents=True)
        (self.student / "active.txt").write_text("english\n")
        self.patches = [
            patch.object(srs, "STUDENT", self.student),
            patch.object(serve, "STUDENT", self.student),
        ]
        for item in self.patches:
            item.start()
        srs.add_cards(
            self.student / "english/cards.json",
            [{"front": "I ___ at home.", "answer": "am", "hint": "быть"}],
        )
        self.card_id = storage.load(self.student / "english/cards.json", None)["cards"][0]["id"]
        self.server = serve.create_server()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def request(self, route, body=None, headers=None, expected=200):
        hdr = {"X-Tutor-Token": self.server.shutdown_token, "X-Tutor-Namespace": serve.namespace()}
        if body is not None:
            hdr["Content-Type"] = "application/json"
        hdr.update(headers or {})
        req = urllib.request.Request(
            self.base + route,
            data=json.dumps(body).encode() if body is not None else None,
            headers=hdr,
        )
        try:
            with urllib.request.urlopen(req, timeout=3) as response:
                result = response.read()
                self.assertEqual(response.status, expected)
                return (
                    json.loads(result)
                    if response.headers.get_content_type() == "application/json"
                    else result
                )
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, expected)
            result = json.loads(error.read())
            error.close()
            return result

    def test_origin_host_token_and_size_rejections(self):
        self.request("/api/session", headers={"Host": "evil.example"}, expected=403)
        self.request("/api/progress", headers={"Origin": "https://evil.example"}, expected=403)
        self.request("/api/deck", {}, {"X-Tutor-Token": ""}, expected=403)
        self.request("/api/deck", {}, {"Sec-Fetch-Site": "cross-site"}, expected=403)
        self.request("/api/deck", {}, {"Content-Type": "text/plain"}, expected=415)
        self.request("/api/deck", {}, {"Content-Length": "-1"}, expected=413)
        self.request("/api/deck", [], expected=400)
        self.request("/api/tts?text=hello", headers={"X-Tutor-Token": ""}, expected=403)

    def test_reviews_are_idempotent_and_invalid_batch_is_atomic(self):
        request = {
            "batch_id": "request-1",
            "results": [{"id": self.card_id, "grade": 3, "review_id": "review-1"}],
        }
        self.request("/api/deck", request)
        self.request("/api/deck", request)
        path = self.student / "english/cards.json"
        before = storage.load(path, None)
        self.assertEqual(before["cards"][0]["reps"], 1)
        self.request(
            "/api/deck",
            {
                "batch_id": "bad",
                "results": [{"id": self.card_id, "grade": 4}, {"id": self.card_id, "grade": False}],
            },
            expected=400,
        )
        self.assertEqual(storage.load(path, None), before)
        self.assertFalse((self.student / ".event-flashcards.json").exists())
        self.request("/api/deck/complete", {"batch_id": "complete", "review_ids": ["review-1"]})
        self.assertTrue((self.student / ".event-flashcards.json").exists())

    def test_language_switch_uses_captured_authorized_directory(self):
        old_namespace = serve.namespace()
        (self.student / "french").mkdir()
        french = self.student / "french/cards.json"
        storage.save(french, storage.load(self.student / "english/cards.json", None))
        original_namespace = serve.namespace

        def switch(directory=None):
            result = original_namespace(directory)
            if directory is not None:
                (self.student / "active.txt").write_text("french\n")
            return result

        with patch.object(serve, "namespace", side_effect=switch):
            self.request(
                "/api/deck",
                {"batch_id": "switch", "results": [{"id": self.card_id, "grade": 3}]},
                {"X-Tutor-Namespace": old_namespace},
            )
        self.assertEqual(storage.load(french, None)["cards"][0]["reps"], 0)
        self.assertEqual(
            storage.load(self.student / "english/cards.json", None)["cards"][0]["reps"], 1
        )

    def test_server_recomputes_quiz_and_preserves_alternatives_for_review(self):
        quiz = {
            "title": "Русский тест",
            "questions": [
                {
                    "type": "choice",
                    "prompt": "She ___ here.",
                    "options": ["is", "are"],
                    "correct": 0,
                },
                {
                    "type": "gap",
                    "prompt": "I ___ coffee.",
                    "answers": ["like"],
                    "explain": "Возможны и другие глаголы.",
                },
            ],
        }
        storage.save(self.student / "quiz-current.json", quiz)
        prepared = self.request("/api/quiz")
        result = self.request(
            "/api/quiz",
            {
                "activity_id": prepared["activity_id"],
                "batch_id": "q1",
                "answers": [1, "love"],
                "score": 999,
            },
        )
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["needs_review"], 1)
        self.request(
            "/api/quiz",
            {"activity_id": "old", "batch_id": "q2", "answers": [0, "like"]},
            expected=400,
        )
        self.request(
            "/api/quiz",
            {"activity_id": prepared["activity_id"], "batch_id": "q1", "answers": [0, "like"]},
            expected=400,
        )
        self.assertEqual(
            len(storage.load(self.student / "activity-results.json", None)["receipts"]), 1
        )
        storage.save(self.student / "quiz-current.json", {**quiz, "title": "New activity"})
        saved = self.request(
            "/api/quiz",
            {
                "activity_id": prepared["activity_id"],
                "batch_id": "q1",
                "answers": [1, "love"],
                "score": 999,
            },
        )
        self.assertEqual(saved["score"], 0)

    def test_corrupt_deck_and_static_paths_fail_closed(self):
        (self.student / "english/cards.json").write_text("{bad")
        self.request("/api/deck", expected=409)
        self.request("/../AGENTS.md", expected=404)
        self.request("/", expected=404)
        self.request("/quiz.html")
        external = Path(self.temp.name) / "secret.html"
        external.write_text("secret")
        link = ROOT / "apps/test-external-link.html"
        try:
            link.symlink_to(external)
            self.request("/test-external-link.html", expected=404)
        finally:
            link.unlink(missing_ok=True)


class ContractsTests(unittest.TestCase):
    def test_cloud_tts_is_opt_in_and_bounded(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "not-a-real-key"}, clear=True):
            self.assertEqual(tts.provider(), "say")
            self.assertIsNone(tts.synth("hello"))
        with self.assertRaises(ValueError):
            tts.synth("a" * 2001)
        with patch.dict(os.environ, {"TUTOR_TTS": "invalid"}, clear=True):
            with self.assertRaises(ValueError):
                tts.provider()

    def test_tts_timeout_cleans_partial_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(tts, "CACHE", Path(directory)),
                patch.dict(os.environ, {"TUTOR_TTS": "edge"}, clear=True),
            ):
                with patch.object(
                    tts.subprocess, "run", side_effect=subprocess.TimeoutExpired("edge_tts", 30)
                ):
                    self.assertIsNone(tts.synth("hello"))
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_quiz_validation_and_unicode_normalization(self):
        quiz = {
            "title": "t",
            "questions": [{"type": "gap", "prompt": "I ___ here.", "answers": ["don't live"]}],
        }
        self.assertEqual(activity.score_quiz(quiz, ["  DON’T   LIVE. "])["score"], 1)
        bad = copy.deepcopy(quiz)
        bad["questions"][0]["prompt"] = "no gap"
        with self.assertRaises(ValueError):
            activity.validate("quiz", bad)

    def test_voice_pass_binding_partial_completion_and_false_audio_claims(self):
        lesson = {
            "pass_id": "pass-1",
            "student": "Learner",
            "native_language": "russian",
            "target_language": "english",
            "level": "A1",
            "lesson_type": "conversation",
            "scenario": "Introduce yourself",
            "activity_rules": "No interruptions",
            "plan": [
                {
                    "step": 1,
                    "instruction": "Say your name",
                    "complete_when": "attempt or explicit skip",
                }
            ],
        }
        report = {
            "pass_id": "pass-1",
            "lesson": {"type": "conversation", "scenario": "Introduce yourself"},
            "completed": True,
            "completed_steps": [1],
            "partial_reason": None,
            "duration_minutes": 2,
            "performance": "One introduction",
            "corrections": [],
            "did_well": "Answered the prompt",
            "pronunciation": "Not independently verified",
            "words_struggled": [],
            "level_impression": "not_assessed",
        }
        result = voice.validate_report(lesson, report)
        self.assertFalse(result["pronunciation_measured"])
        self.assertFalse(result["automatic_writeback"])
        for change in (
            {"pass_id": "other"},
            {"completed_steps": []},
            {"completed": False},
            {"duration_minutes": True},
        ):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    voice.validate_report(lesson, {**report, **change})
