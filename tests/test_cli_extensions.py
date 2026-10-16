"""Exercise the public diagnostic and backup commands with isolated learner data."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CLIExtensionsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.student = self.root / "student"
        self.environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("TUTOR_BACKUP_") and key != "TUTOR_STUDENT_DIR"
        }

    def tearDown(self):
        self.temporary.cleanup()

    def cli(self, *arguments, success=True, environment=None):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools/tutor.py"),
                "--student-dir",
                str(self.student),
                *arguments,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
            env={**self.environment, **(environment or {})},
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        return result.stderr

    def state(self):
        return json.loads((self.student / "english/learner.json").read_text(encoding="utf-8"))

    def test_confirmed_goals_survive_reinitialization_and_can_be_updated(self):
        self.cli("init", "--objective", "Read work emails", "--daily-minutes", "20")
        original = self.state()
        self.cli("init", "--objective", "This must not overwrite saved preferences")
        self.assertEqual(self.state(), original)
        self.cli("configure", "--objective", "Discuss technical work", "--objective", "Read emails")
        self.assertEqual(self.state()["objectives"], ["Discuss technical work", "Read emails"])

    def test_learner_items_hide_keys_and_audio_scripts_but_controller_can_validate(self):
        self.cli("init")
        public = self.cli("items", "--level", "A1", "--limit", "50")
        private = self.cli("items", "--level", "A1", "--limit", "50", "--controller")
        self.assertEqual([item["id"] for item in public], [item["id"] for item in private])
        for item in public:
            self.assertNotIn("answers", item)
            self.assertNotIn("text", item.get("delivery", {}))
        self.assertTrue(any("answers" in item for item in private))
        prepared = self.root / "exercise.json"
        prepared.write_text(json.dumps(private[0]), encoding="utf-8")
        self.assertTrue(self.cli("validate-exercise", str(prepared))["valid"])
        prepared.write_text('{"id":"broken"}', encoding="utf-8")
        self.cli("validate-exercise", str(prepared), success=False)

    def test_full_backup_cli_restores_inactive_language_and_media_without_live_overwrite(self):
        self.cli("init")
        other = self.student / "french"
        (other / "recordings").mkdir(parents=True)
        (other / "cards.json").write_text('{"cards": []}', encoding="utf-8")
        (other / "recordings/original.wav").write_bytes(b"synthetic restore fixture")
        (self.student / ".env").write_text("DO_NOT_EXPORT=fixture", encoding="utf-8")
        archive = self.root / "learner.zip"
        self.cli("backup", str(archive))
        manifest = self.cli("backup-check", str(archive))
        self.assertEqual(manifest["languages"], ["english", "french"])
        destination = self.root / "restored"
        self.cli("restore", str(archive), str(destination))
        self.assertEqual(
            (destination / "french/recordings/original.wav").read_bytes(),
            b"synthetic restore fixture",
        )
        self.assertFalse((destination / ".env").exists())
        self.cli("restore", str(archive), str(self.student), success=False)
        self.assertEqual(
            json.loads((destination / "english/learner.json").read_text()), self.state()
        )

    def test_automatic_backup_failure_cannot_hide_a_committed_configuration(self):
        self.cli("init")
        missing = self.root / "missing-backup-volume"
        environment = {"TUTOR_BACKUP_DIR": str(missing)}
        result = self.cli("configure", "--daily-minutes", "45", environment=environment)
        self.assertEqual(result["backup"]["status"], "unavailable")
        self.assertEqual(self.state()["profile"]["daily_minutes"], 45)
        self.assertFalse(missing.exists())
        self.cli("backup-auto", environment=environment, success=False)
        destination = self.root / "backups"
        destination.mkdir()
        environment["TUTOR_BACKUP_DIR"] = str(destination)
        self.assertEqual(self.cli("backup-auto", environment=environment)["status"], "created")
        self.assertEqual(self.cli("backup-auto", environment=environment)["status"], "not_due")

    def test_late_review_preserves_raw_attempt_and_reconcile_repairs_only_derived_caches(self):
        self.cli("init")
        sid = self.cli("start")["id"]
        items = self.cli("items", "--level", "A1", "--limit", "50", "--controller")
        item = next(item for item in items if item["type"] == "short_writing")
        exercise = self.root / "exercise.json"
        exercise.write_text(json.dumps(item), encoding="utf-8")
        response = self.root / "response.txt"
        response.write_text("I work with a small team. We help each other.", encoding="utf-8")
        self.cli(
            "attempt",
            "--session",
            sid,
            "--exercise",
            str(exercise),
            "--response-file",
            str(response),
            "--id",
            "trial",
        )
        raw = self.state()["observations"]
        review = self.root / "review.json"
        review.write_text(
            json.dumps(
                {
                    "source": "llm",
                    "judgment": "correct",
                    "criteria": {key: 1 for key in item["rubric"]},
                    "rationale": "Synthetic integration-test review.",
                }
            ),
            encoding="utf-8",
        )
        result = self.cli(
            "review", "--observation", "trial", "--review", str(review), "--id", "review-1"
        )
        self.assertEqual(result["effective_observation"]["grade"]["source"], "llm")
        self.assertEqual(self.state()["observations"], raw)
        repeated = self.cli(
            "review", "--observation", "trial", "--review", str(review), "--id", "review-1"
        )
        self.assertTrue(repeated["duplicate"])
        state = self.state()
        state["estimates"]["skills"] = {"a1-01": {"mastered": True}}
        path = self.student / "english/learner.json"
        path.write_text(json.dumps(state), encoding="utf-8")
        self.cli("validate", success=False)
        self.assertTrue(self.cli("reconcile")["reconciled"])
        self.assertEqual(self.state()["observations"], raw)
        self.assertEqual(len(self.state()["reviews"]), 1)
        self.assertTrue(self.cli("validate")["valid"])

    def test_advanced_entry_refuses_an_unobserved_self_report(self):
        self.cli("init", "--objective", "I believe I am C1")
        original = self.state()
        report = self.cli("placement", "--target-level", "C1")
        self.assertFalse(report["eligible"])
        self.assertFalse(report["mastery_granted"])
        self.cli("accept-placement", "--target-level", "C1", success=False)
        self.assertEqual(self.state(), original)


if __name__ == "__main__":
    unittest.main()
