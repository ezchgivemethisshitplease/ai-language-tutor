"""Persistence, reference-scheduler and legacy-compatibility regressions."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from fsrs import Rating, Scheduler, State
from tools import srs, storage


NOW = datetime(2026, 1, 1, 10, tzinfo=timezone.utc)


def sample(identifier="borrow"):
    return {
        "id": identifier,
        "front": "Can I ___ your pen?",
        "answer": "borrow",
        "hint": "одолжить",
    }


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "state.json"

    def test_unicode_defaults_and_backup(self):
        default = {"items": []}
        state = storage.load(self.path, default)
        state["items"].append("я учусь")
        self.assertEqual(default, {"items": []})
        storage.save(self.path, state)
        storage.save(self.path, {"items": ["я говорю"]})
        self.assertEqual(storage.load(self.path.with_suffix(".json.bak"), {}), state)
        self.assertEqual(storage.load(self.path, {})["items"], ["я говорю"])

    def test_rollback_and_invalid_json_do_not_change_bytes(self):
        storage.save(self.path, {"count": 1})
        before = self.path.read_bytes()
        with self.assertRaises(RuntimeError):
            with storage.transaction(self.path, {}) as data:
                data["count"] = 999
                raise RuntimeError("interrupted operation")
        self.assertEqual(self.path.read_bytes(), before)
        with self.assertRaises(storage.StorageError):
            storage.save(self.path, {"count": math.nan})
        self.assertEqual(self.path.read_bytes(), before)

    def test_corruption_is_rejected_and_explicit_restore_preserves_evidence(self):
        storage.save(self.path, {"count": 1})
        storage.save(self.path, {"count": 2})
        self.path.write_bytes(b'{"count": ')
        with self.assertRaises(storage.StorageError):
            storage.load(self.path, {})
        with self.assertRaises(storage.StorageError):
            storage.save(self.path, {})
        self.assertEqual(storage.restore_backup(self.path), {"count": 1})
        recovery = list(self.path.parent.glob("state.json.recovery-*"))
        self.assertEqual(len(recovery), 1)
        self.assertEqual(recovery[0].read_bytes(), b'{"count": ')

    def test_nonstandard_and_duplicate_json_rejected(self):
        for raw in ('{"x": 1, "x": 2}', '{"x": Infinity}', '{"x": NaN}', "\udcff"):
            with self.subTest(raw=repr(raw)), self.assertRaises(storage.StorageError):
                storage.decode(raw)

    def test_failed_replace_leaves_existing_generation_and_cleans_temp(self):
        storage.save(self.path, {"count": 1})
        real_replace = storage.os.replace

        def fail_main(source, destination):
            if Path(destination) == self.path:
                raise OSError("simulated power-loss boundary")
            return real_replace(source, destination)

        with patch.object(storage.os, "replace", side_effect=fail_main):
            with self.assertRaises(OSError):
                storage.save(self.path, {"count": 2})
        self.assertEqual(storage.load(self.path, {}), {"count": 1})
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])
        self.assertEqual(storage.load(self.path.with_suffix(".json.bak"), {}), {"count": 1})

    def test_thread_transactions_do_not_lose_updates(self):
        def increment(_):
            for _unused in range(10):
                with storage.transaction(self.path, {"count": 0}) as state:
                    state["count"] += 1

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(increment, range(4)))
        self.assertEqual(storage.load(self.path, {}), {"count": 40})

    def test_process_transactions_do_not_lose_updates(self):
        script = """from tools import storage
import sys
for _ in range(12):
    with storage.transaction(sys.argv[1], {'count': 0}) as state:
        state['count'] += 1
"""
        children = [
            subprocess.Popen(
                [sys.executable, "-c", script, str(self.path)],
                cwd=Path(__file__).resolve().parents[1],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for _ in range(4)
        ]
        for process in children:
            stdout, stderr = process.communicate(timeout=30)
            self.assertEqual(process.returncode, 0, stderr.decode())
        self.assertEqual(storage.load(self.path, {}), {"count": 48})

    def test_export_import_validator_and_symlink_rejection(self):
        storage.save(self.path, {"owner": "learner"})
        destination = self.path.parent / "export.json"
        storage.export_json(self.path, destination)
        self.assertEqual(storage.import_json(destination, self.path), {"owner": "learner"})

        def refuse(value):
            raise ValueError("invalid schema")

        with self.assertRaises(ValueError):
            storage.import_json(destination, self.path, refuse)
        if hasattr(Path, "symlink_to"):
            linked = self.path.parent / "linked.json"
            try:
                linked.symlink_to(self.path)
            except OSError:
                self.skipTest("symlinks unavailable")
            with self.assertRaises(storage.StorageError):
                storage.save(linked, {})


class SRSTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "cards.json"

    def test_new_schedule_matches_official_reference_for_all_grades(self):
        reference = Scheduler(enable_fuzzing=False)
        for grade in range(1, 5):
            with self.subTest(grade=grade):
                card = sample()
                state = srs._fsrs_card(card)
                expected, expected_log = reference.review_card(
                    state, Rating(grade), review_datetime=NOW
                )
                srs.review(card, grade, NOW, review_id="reference")
                self.assertEqual(card["fsrs"], expected.to_dict())
                self.assertEqual(card["review_history"][0]["fsrs"], expected_log.to_dict())
                self.assertEqual(card["id"], "borrow")

    def test_legacy_memory_state_ids_and_unknown_data_survive_lazy_migration(self):
        old = sample("old8char")
        old.update(
            {
                "S": 3.7145,
                "D": 4.1,
                "last_review": "2025-12-20",
                "due": "2025-12-24",
                "reps": 23,
                "lapses": 4,
                "teacher_note": "сохранить",
            }
        )
        storage.save(self.path, {"cards": [old], "custom_metadata": "keep"})
        raw = self.path.read_bytes()
        self.assertEqual(srs.due_cards(self.path, NOW)[0]["S"], 3.7145)
        self.assertEqual(self.path.read_bytes(), raw)  # reads never migrate silently
        expected, _ = Scheduler(enable_fuzzing=False).review_card(
            srs._fsrs_card(old), Rating.Good, review_datetime=NOW
        )
        srs.apply_reviews(self.path, [{"id": "old8char", "grade": 3}], NOW, batch_id="migration")
        data = storage.load(self.path, {})
        migrated = data["cards"][0]
        self.assertEqual(migrated["fsrs"], expected.to_dict())
        self.assertEqual(migrated["reps"], 24)
        self.assertEqual(migrated["lapses"], 4)
        self.assertEqual(migrated["teacher_note"], "сохранить")
        self.assertEqual(data["custom_metadata"], "keep")
        self.assertEqual(migrated["id"], "old8char")
        self.assertEqual(len(migrated["review_history"]), 1)
        self.assertFalse(migrated["migration"]["historical_reviews_available"])
        self.assertEqual(storage.load(self.path.with_suffix(".json.bak"), {})["cards"][0], old)

    def test_batch_is_atomic_for_unknown_card_bad_grade_or_conflicting_ids(self):
        srs.add_cards(self.path, sample(), NOW)
        before = self.path.read_bytes()
        for review in (
            {"id": "unknown", "grade": 3},
            {"id": "borrow", "grade": 0},
            {"id": "borrow", "grade": True},
            {"id": "borrow", "grade": "3"},
        ):
            with self.subTest(review=review), self.assertRaises(ValueError):
                srs.apply_reviews(self.path, [{"id": "borrow", "grade": 3}, review], NOW)
            self.assertEqual(self.path.read_bytes(), before)
        with self.assertRaises(ValueError):
            srs.add_cards(self.path, sample("borrow") | {"answer": "lend"}, NOW)
        self.assertEqual(self.path.read_bytes(), before)

    def test_review_and_batch_idempotency_with_payload_conflicts(self):
        srs.add_cards(self.path, sample(), NOW)
        payload = [{"id": "borrow", "grade": 3, "review_id": "stable-review"}]
        srs.apply_reviews(self.path, payload, NOW, batch_id="stable-batch")
        raw = self.path.read_bytes()
        self.assertTrue(
            srs.apply_reviews(self.path, payload, NOW + timedelta(days=1), batch_id="stable-batch")[
                "duplicate"
            ]
        )
        self.assertEqual(self.path.read_bytes(), raw)
        self.assertTrue(
            srs.apply_reviews(self.path, payload, NOW + timedelta(minutes=1))["graded"][0][
                "duplicate"
            ]
        )
        self.assertEqual(storage.load(self.path, {})["cards"][0]["reps"], 1)
        with self.assertRaises(ValueError):
            srs.apply_reviews(
                self.path, [{"id": "borrow", "grade": 4, "review_id": "stable-review"}], NOW
            )
        with self.assertRaises(ValueError):
            srs.apply_reviews(
                self.path, [{"id": "borrow", "grade": 4}], NOW, batch_id="stable-batch"
            )
        self.assertEqual(self.path.read_bytes(), raw)

    def test_duplicates_normalized_and_ids_stable(self):
        first = srs.add_cards(self.path, sample("kept"), NOW)
        repeated = sample("different") | {"front": " CAN I   ___ your pen? ", "answer": "BORROW"}
        second = srs.add_cards(self.path, [repeated, repeated], NOW)
        self.assertEqual(first["added"], ["kept"])
        self.assertEqual(second["added"], [])
        self.assertEqual(second["duplicates"], ["kept", "kept"])
        self.assertEqual(len(storage.load(self.path, {})["cards"]), 1)

    def test_learning_steps_precision_and_lapse_semantics(self):
        srs.add_cards(self.path, sample(), NOW)
        srs.apply_reviews(self.path, [{"id": "borrow", "grade": 3}], NOW)
        self.assertEqual(srs.due_cards(self.path, NOW + timedelta(minutes=9)), [])
        self.assertEqual(len(srs.due_cards(self.path, NOW + timedelta(minutes=10))), 1)
        srs.apply_reviews(self.path, [{"id": "borrow", "grade": 3}], NOW + timedelta(minutes=10))
        card = storage.load(self.path, {})["cards"][0]
        self.assertEqual(card["fsrs"]["state"], State.Review)
        next_due = datetime.fromisoformat(card["due_at"])
        srs.apply_reviews(self.path, [{"id": "borrow", "grade": 1}], next_due)
        card = storage.load(self.path, {})["cards"][0]
        self.assertEqual(card["lapses"], 1)
        self.assertEqual(card["fsrs"]["state"], State.Relearning)
        srs.apply_reviews(
            self.path, [{"id": "borrow", "grade": 1}], next_due + timedelta(minutes=10)
        )
        self.assertEqual(storage.load(self.path, {})["cards"][0]["lapses"], 1)

    def test_hundreds_of_reviews_match_reference_with_long_absence(self):
        card = sample()
        reference = Scheduler(enable_fuzzing=False)
        expected = srs._fsrs_card(card)
        current = NOW
        for index in range(250):
            grade = (3, 3, 4, 2, 1, 3, 3)[index % 7]
            current = max(current, expected.due) + timedelta(days=365 if index == 120 else 0)
            expected, _ = reference.review_card(expected, Rating(grade), review_datetime=current)
            srs.review(card, grade, current, review_id=f"simulation-{index}")
            self.assertEqual(card["fsrs"], expected.to_dict())
            self.assertTrue(math.isfinite(card["S"]))
            self.assertTrue(1 <= card["D"] <= 10)
        self.assertEqual(card["reps"], 250)
        self.assertEqual(len(card["review_history"]), 250)
        self.assertEqual(len({row["review_id"] for row in card["review_history"]}), 250)

    def test_validation_dates_state_and_conflicting_identifiers(self):
        card = sample()
        for grade in (0, 5, -1, True, 3.0, "3"):
            untouched = deepcopy(card)
            with self.assertRaises(ValueError):
                srs.review(untouched, grade, NOW)
            self.assertEqual(untouched, card)
        with self.assertRaises(ValueError):
            srs.review(card, 3, datetime(2026, 1, 1))
        srs.review(card, 3, NOW)
        untouched = deepcopy(card)
        with self.assertRaises(ValueError):
            srs.review(card, 3, NOW - timedelta(minutes=1))
        self.assertEqual(card, untouched)
        for state in (
            {"cards": [sample(), sample()]},
            {"cards": [], "schema_version": 99},
            {"cards": [sample() | {"last_review": "2026-01-01", "S": 0, "D": 4}]},
        ):
            with self.subTest(state=state), self.assertRaises(ValueError):
                srs.validate_deck(state)

    def test_language_paths_cannot_escape_student(self):
        root = Path(self.tmp.name) / "student"
        root.mkdir()
        (root / "english").mkdir()
        with patch.object(srs, "STUDENT", root):
            for active in (
                "../outside",
                "/tmp",
                "english/subdir",
                "",
                "..",
            ):  # no silent fallback on invalid active
                (root / "active.txt").write_text(active)
                with self.subTest(active=active), self.assertRaises(ValueError):
                    srs.lang_dir()
            (root / "active.txt").write_text("english")
            self.assertEqual(srs.lang_dir(), root / "english")
            outside = root.parent / "outside"
            outside.mkdir()
            try:
                (root / "other").symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("symlinks unavailable")
            with self.assertRaises(ValueError):
                srs.language_dir("other")

    def test_inconsistent_canonical_state_and_corrupt_receipts_rejected(self):
        srs.add_cards(self.path, sample(), NOW)
        data = storage.load(self.path, {})
        for change in (
            {"due_at": "2020-01-01T00:00:00+00:00"},
            {"due": "2020-01-01"},
            {"last_review": "2020-01-01"},
        ):
            corrupt = deepcopy(data)
            corrupt["cards"][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                srs.validate_deck(corrupt)
        data["review_batches"] = {"broken": {"result": {}}}
        with self.assertRaises(ValueError):
            srs.validate_deck(data)

    def test_concurrent_browser_retries_apply_only_one_review(self):
        srs.add_cards(self.path, sample(), NOW)
        payload = [{"id": "borrow", "grade": 3, "review_id": "browser-click"}]
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(
                pool.map(
                    lambda unused: srs.apply_reviews(
                        self.path, payload, NOW, batch_id="browser-retry"
                    ),
                    range(4),
                )
            )
        self.assertEqual(sum(not result["duplicate"] for result in results), 1)
        card = storage.load(self.path, {})["cards"][0]
        self.assertEqual(card["reps"], 1)
        self.assertEqual(len(card["review_history"]), 1)


if __name__ == "__main__":
    unittest.main()
