"""Verified multi-language recovery, hostile ZIPs, rotation and real SIGKILL drills."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import warnings
import zipfile

from tools import backup, learning, storage

NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.student = self.root / "student"
        self.student.mkdir()
        for language in ("english", "french"):
            directory = self.student / language
            directory.mkdir()
            storage.save(
                directory / "cards.json",
                {
                    "cards": [
                        {
                            "id": "stable-id",
                            "front": "I ___ here.",
                            "answer": "live",
                            "hint": "жить",
                            "last_review": None,
                        }
                    ]
                },
            )
            storage.save(
                directory / "progress.json", {"level": "A1", "history": [{"note": "сохранить"}]}
            )
            (directory / "known_words.txt").write_text("hello\nbonjour\n", encoding="utf-8")
            (directory / "errors.md").write_text("1× | articles | needs review\n", encoding="utf-8")
            (directory / "img").mkdir()
            (directory / "img" / "word.jpg").write_bytes(b"\xff\xd8image-fixture\xff\xd9")
        storage.save(self.student / "english/learner.json", learning.new_state())
        storage.save(
            self.student / "french/learner.json",
            {"schema_version": 1, "target_language": "french", "notes": ["legacy"]},
        )
        (self.student / "active.txt").write_text("english\n")
        (self.student / "profile.md").write_text("Learner: Тест\n", encoding="utf-8")
        storage.save(self.student / "activity-results.json", {"receipts": {}})
        storage.save(
            self.student / "quiz-current.json",
            {
                "title": "Choose",
                "questions": [
                    {
                        "type": "choice",
                        "prompt": "She ___ here.",
                        "options": ["is", "are"],
                        "correct": 0,
                    }
                ],
            },
        )
        (self.student / "recordings").mkdir()
        (self.student / "recordings/голос.wav").write_bytes(b"RIFF\x00\x01audio-fixture")
        (self.student / ".env").write_text("OPENAI_API_KEY=synthetic-test-value\n")
        (self.student / ".serve.json").write_text('{"token":"synthetic-control-token"}')
        (self.student / ".tts-cache").mkdir()
        (self.student / ".tts-cache/audio.mp3").write_bytes(b"cached")
        (self.student / "english/session-artifacts").mkdir()
        (self.student / "english/session-artifacts/answer.txt").write_text("raw scratch response")
        self.archive = self.root / "backup.zip"

    def create(self):
        return backup.create_backup(self.student, self.archive, now=NOW)

    def rewrite(self, mutate, destination=None):
        with zipfile.ZipFile(self.archive) as source:
            records = [(info, source.read(info)) for info in source.infolist()]
        records = mutate(records)
        destination = destination or self.root / "modified.zip"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED) as target:
                for info, raw in records:
                    target.writestr(info, raw)
        return destination

    def assert_refused(self, archive):
        destination = self.root / "refused-restore"
        with self.assertRaises((backup.BackupError, storage.StorageError)):
            backup.restore_backup(archive, destination)
        self.assertFalse(destination.exists())
        self.assertEqual(list(self.root.glob(".tutor-restore-*")), [])

    def test_all_languages_media_exact_bytes_and_private_restore(self):
        original = {
            path.relative_to(self.student).as_posix(): path.read_bytes()
            for path in self.student.rglob("*")
            if path.is_file()
        }
        result = self.create()
        self.assertEqual(result["languages"], ["english", "french"])
        manifest = backup.validate_backup(self.archive)
        names = {entry["path"] for entry in manifest["files"]}
        self.assertIn("french/learner.json", names)
        self.assertIn("recordings/голос.wav", names)
        self.assertIn("english/img/word.jpg", names)
        self.assertNotIn(".env", names)
        self.assertNotIn(".serve.json", names)
        self.assertFalse(
            any(
                ".tts-cache" in name or "session-artifacts" in name or name.endswith(".lock")
                for name in names
            )
        )
        restored = self.root / "restored"
        backup.restore_backup(self.archive, restored)
        for entry in manifest["files"]:
            with self.subTest(path=entry["path"]):
                raw = (restored / entry["path"]).read_bytes()
                self.assertEqual(raw, original[entry["path"]])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), entry["sha256"])
                self.assertEqual(stat.S_IMODE((restored / entry["path"]).stat().st_mode), 0o600)
        for name, raw in original.items():
            self.assertEqual((self.student / name).read_bytes(), raw)
        self.assertEqual(stat.S_IMODE(self.archive.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(restored.stat().st_mode), 0o700)

    def test_no_overwrite_live_source_archive_or_restore_destinations(self):
        self.create()
        original = self.archive.read_bytes()
        with self.assertRaises(backup.BackupError):
            backup.create_backup(self.student, self.archive)
        self.assertEqual(self.archive.read_bytes(), original)
        with self.assertRaises(backup.BackupError):
            backup.create_backup(self.student, self.student / "inside.zip")
        with self.assertRaises(backup.BackupError):
            backup.restore_backup(self.archive, self.student)
        empty = self.root / "already-empty"
        empty.mkdir()
        with self.assertRaises(OSError):
            backup._rename_new(self.root / "student", empty)
        self.assertTrue(self.student.is_dir())
        self.assertEqual(list(empty.iterdir()), [])

    def test_source_symlink_hardlink_special_and_directory_links_rejected(self):
        path = self.student / "english/img/word.jpg"
        raw = path.read_bytes()
        path.unlink()
        outside = self.root / "outside.jpg"
        outside.write_bytes(raw)
        variants = ("symlink", "hardlink", "fifo")
        for variant in variants:
            if path.exists() or path.is_symlink():
                path.unlink()
            if variant == "symlink":
                path.symlink_to(outside)
            elif variant == "hardlink":
                os.link(outside, path)
            else:
                os.mkfifo(path)
            with self.subTest(variant=variant), self.assertRaises(backup.BackupError):
                self.create()
            self.assertFalse(self.archive.exists())
        path.unlink()
        path.write_bytes(raw)
        (self.student / "english/img/link").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(backup.BackupError):
            self.create()

    def test_credential_field_or_corrupt_source_preserves_previous_backup(self):
        self.create()
        previous = self.archive.read_bytes()
        storage.save(
            self.student / "french/progress.json", {"OPENAI_API_KEY": "synthetic-test-value"}
        )
        with self.assertRaises(backup.BackupError):
            backup.create_backup(self.student, self.root / "next.zip")
        self.assertEqual(self.archive.read_bytes(), previous)
        self.assertFalse((self.root / "next.zip").exists())
        self.assertEqual(list(self.root.glob(".tutor-backup-*.tmp")), [])

    def test_duplicate_casefold_unicode_and_traversal_members_refused(self):
        self.create()
        for name in (
            "data/english/cards.json",
            "DATA/ENGLISH/CARDS.JSON",
            "../outside.wav",
            "/absolute.wav",
            "data\\escape.wav",
            "data/english/.env",
        ):

            def inject(records, name=name):
                return records + [(zipfile.ZipInfo(name), b"untrusted")]

            with self.subTest(name=name):
                self.assert_refused(self.rewrite(inject))

        def unicode_collision(records):
            return records + [
                (zipfile.ZipInfo("data/media/é.wav"), b"a"),
                (zipfile.ZipInfo("data/media/e\u0301.wav"), b"b"),
            ]

        self.assert_refused(self.rewrite(unicode_collision))

    def test_symlink_special_reparse_and_extra_metadata_members_refused(self):
        self.create()
        for mode, extra, dos in (
            (stat.S_IFLNK | 0o777, b"", 0),
            (stat.S_IFIFO | 0o600, b"", 0),
            (stat.S_IFREG | 0o600, b"", 0x400),
            (stat.S_IFREG | 0o600, b"\x0a\x00\x00\x00", 0),
        ):

            def mutate(records, mode=mode, extra=extra, dos=dos):
                info, raw = records[0]
                info.external_attr = (mode << 16) | dos
                info.extra = extra
                return [(info, raw)] + records[1:]

            with self.subTest(mode=mode, extra=extra, dos=dos):
                self.assert_refused(self.rewrite(mutate))

    def test_checksum_size_manifest_and_schema_tampering_refused(self):
        self.create()

        def changed_bytes(records):
            return [
                (info, raw + b"x" if info.filename == "data/english/known_words.txt" else raw)
                for info, raw in records
            ]

        self.assert_refused(self.rewrite(changed_bytes))
        for key, value in (
            ("version", 99),
            ("total_bytes", -1),
            ("languages", ["english", "English"]),
            ("format", "other"),
        ):

            def change_manifest(records, key=key, value=value):
                output = []
                for info, raw in records:
                    if info.filename == "manifest.json":
                        data = json.loads(raw)
                        data[key] = value
                        raw = json.dumps(data).encode()
                    output.append((info, raw))
                return output

            with self.subTest(key=key):
                self.assert_refused(self.rewrite(change_manifest))

        def invalid_schema_with_valid_checksum(records):
            bad = b'{"cards": [{"id": "broken"}]}'
            output = []
            old = next(raw for info, raw in records if info.filename == "data/english/cards.json")
            for info, raw in records:
                if info.filename == "data/english/cards.json":
                    raw = bad
                elif info.filename == "manifest.json":
                    data = json.loads(raw)
                    for entry in data["files"]:
                        if entry["path"] == "english/cards.json":
                            entry.update(size=len(bad), sha256=hashlib.sha256(bad).hexdigest())
                    data["total_bytes"] += len(bad) - len(old)
                    raw = json.dumps(data).encode()
                output.append((info, raw))
            return output

        self.assert_refused(self.rewrite(invalid_schema_with_valid_checksum))

    def test_missing_manifest_trailing_bytes_compression_and_encryption_refused(self):
        self.create()
        self.assert_refused(
            self.rewrite(
                lambda records: [
                    (info, raw) for info, raw in records if info.filename != "manifest.json"
                ]
            )
        )
        corrupted = self.root / "trailing.zip"
        corrupted.write_bytes(self.archive.read_bytes() + b"trailer")
        self.assert_refused(corrupted)
        compressed = self.root / "compressed.zip"
        with (
            zipfile.ZipFile(self.archive) as source,
            zipfile.ZipFile(compressed, "w", compression=zipfile.ZIP_DEFLATED) as target,
        ):
            for info in source.infolist():
                target.writestr(
                    info.filename, source.read(info), compress_type=zipfile.ZIP_DEFLATED
                )
        self.assert_refused(compressed)
        raw = bytearray(self.archive.read_bytes())
        central = raw.index(b"PK\x01\x02")
        struct.pack_into("<H", raw, central + 8, 1)
        encrypted = self.root / "encrypted.zip"
        encrypted.write_bytes(raw)
        self.assert_refused(encrypted)

    def test_quotas_checked_before_create_or_restore(self):
        for limits in (
            replace(backup.DEFAULT_LIMITS, max_files=1),
            replace(backup.DEFAULT_LIMITS, max_document_bytes=4),
            replace(backup.DEFAULT_LIMITS, max_total_bytes=4),
            replace(backup.DEFAULT_LIMITS, max_archive_bytes=22),
        ):
            with self.subTest(limits=limits), self.assertRaises(backup.BackupError):
                backup.create_backup(self.student, self.archive, limits=limits)
            self.assertFalse(self.archive.exists())
        self.create()
        with self.assertRaises(backup.BackupError):
            backup.restore_backup(
                self.archive,
                self.root / "over-quota",
                limits=replace(backup.DEFAULT_LIMITS, max_files=1),
            )
        self.assertFalse((self.root / "over-quota").exists())

    def test_media_change_during_backup_rejected(self):
        original = backup._document
        changed = False

        def mutate(name, raw, languages):
            nonlocal changed
            result = original(name, raw, languages)
            if not changed:
                changed = True
                (self.student / "french/img/word.jpg").write_bytes(b"different-image")
            return result

        with (
            patch.object(backup, "_document", side_effect=mutate),
            self.assertRaises(backup.BackupError),
        ):
            self.create()
        self.assertFalse(self.archive.exists())

    def test_unreadable_media_subdirectory_cannot_be_silently_skipped(self):
        blocked = self.student / "recordings/blocked"
        blocked.mkdir()
        (blocked / "evidence.wav").write_bytes(b"evidence")
        original = os.scandir

        def refuse(path):
            if Path(path) == blocked:
                raise PermissionError("simulated unreadable media directory")
            return original(path)

        with (
            patch.object(backup.os, "scandir", side_effect=refuse),
            self.assertRaises(backup.BackupError),
        ):
            self.create()
        self.assertFalse(self.archive.exists())

    def test_auto_is_opt_in_missing_directory_or_required_mount_no_fallback(self):
        self.assertEqual(backup.automatic_backup(self.student, environ={})["status"], "disabled")
        missing = self.root / "missing-drive/backup"
        result = backup.automatic_backup(self.student, environ={"TUTOR_BACKUP_DIR": str(missing)})
        self.assertEqual(result["status"], "unavailable")
        self.assertFalse(missing.parent.exists())
        mount = self.root / "unmounted"
        mount.mkdir()
        directory = mount / "backups"
        directory.mkdir()
        result = backup.automatic_backup(
            self.student,
            environ={"TUTOR_BACKUP_DIR": str(directory), "TUTOR_BACKUP_REQUIRE_MOUNT": str(mount)},
        )
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(list(directory.iterdir()), [])

    def test_auto_rotation_interval_foreign_and_corrupt_archives_preserved(self):
        directory = self.root / "backups"
        directory.mkdir()
        env = {
            "TUTOR_BACKUP_DIR": str(directory),
            "TUTOR_BACKUP_KEEP": "2",
            "TUTOR_BACKUP_INTERVAL_HOURS": "24",
        }
        first = backup.automatic_backup(self.student, environ=env, now=NOW)
        self.assertEqual(
            backup.automatic_backup(self.student, environ=env, now=NOW + timedelta(hours=23))[
                "status"
            ],
            "not_due",
        )
        malformed = directory / Path(first["archive"]).name.replace(".zip", "-invalid.zip")
        # A matching filename with corrupt content is evidence, not a rotation candidate.
        malformed = directory / (Path(first["archive"]).name[:-12] + "deadbeef.zip")
        malformed.write_bytes(b"broken archive")
        foreign = directory / "other-owner.zip"
        foreign.write_bytes(b"untouched")
        backup.automatic_backup(self.student, environ=env, now=NOW + timedelta(days=1))
        third = backup.automatic_backup(self.student, environ=env, now=NOW + timedelta(days=2))
        self.assertEqual(third["removed"], 1)
        self.assertEqual(third["invalid_retained"], 1)
        self.assertFalse(Path(first["archive"]).exists())
        self.assertEqual(malformed.read_bytes(), b"broken archive")
        self.assertEqual(foreign.read_bytes(), b"untouched")
        valid = [path for path in directory.glob("*.zip") if path not in (malformed, foreign)]
        self.assertEqual(len(valid), 2)
        for path in valid:
            backup.validate_backup(path)

    def test_failed_auto_backup_does_not_prune_old_generation_or_rollback_study(self):
        directory = self.root / "backups"
        directory.mkdir()
        env = {"TUTOR_BACKUP_DIR": str(directory)}
        first = backup.automatic_backup(self.student, environ=env, now=NOW)
        old = Path(first["archive"]).read_bytes()
        (self.student / "english/cards.json").write_bytes(b'{"cards":')
        result = backup.maybe_automatic_backup(
            self.student, environ=env, now=NOW + timedelta(days=1)
        )
        self.assertEqual(result["status"], "warning")
        self.assertTrue(result["study_data_committed"])
        self.assertEqual(Path(first["archive"]).read_bytes(), old)
        self.assertEqual((self.student / "english/cards.json").read_bytes(), b'{"cards":')
        self.assertEqual(len(list(directory.glob("*.zip"))), 1)

    def test_not_due_auto_checks_metadata_without_rereading_media_payload(self):
        directory = self.root / "backups"
        directory.mkdir()
        env = {"TUTOR_BACKUP_DIR": str(directory)}
        backup.automatic_backup(self.student, environ=env, now=NOW)
        original = backup._read_member

        def guard(archive, member, *args, **kwargs):
            self.assertEqual(member.filename, "manifest.json")
            return original(archive, member, *args, **kwargs)

        with patch.object(backup, "_read_member", side_effect=guard):
            result = backup.automatic_backup(
                self.student, environ=env, now=NOW + timedelta(hours=1)
            )
        self.assertEqual(result["status"], "not_due")

    def test_rotation_preserves_foreign_replacement_after_candidate_validation(self):
        directory = self.root / "backups"
        directory.mkdir()
        env = {"TUTOR_BACKUP_DIR": str(directory), "TUTOR_BACKUP_KEEP": "2"}
        first = backup.automatic_backup(self.student, environ=env, now=NOW)
        backup.automatic_backup(self.student, environ=env, now=NOW + timedelta(days=1))
        victim = Path(first["archive"])
        original = backup.validate_backup
        changed = False

        def replace_after_validation(path, **kwargs):
            nonlocal changed
            manifest = original(path, **kwargs)
            if Path(path) == victim and not changed:
                changed = True
                victim.unlink()
                victim.write_bytes(b"foreign replacement after verification")
            return manifest

        with patch.object(backup, "validate_backup", side_effect=replace_after_validation):
            result = backup.automatic_backup(self.student, environ=env, now=NOW + timedelta(days=2))
        self.assertEqual(result["removed"], 0)
        self.assertEqual(result["invalid_retained"], 1)
        self.assertEqual(victim.read_bytes(), b"foreign replacement after verification")
        self.assertIn(str(victim), result["retained_paths"])

    def test_overflowing_archive_timestamp_cannot_fail_committed_cli_change(self):
        directory = self.root / "backups"
        directory.mkdir()
        first = backup.automatic_backup(
            self.student, environ={"TUTOR_BACKUP_DIR": str(directory)}, now=NOW
        )
        self.archive = Path(first["archive"])

        def overflow(records):
            output = []
            for info, raw in records:
                if info.filename == "manifest.json":
                    manifest = json.loads(raw)
                    manifest["created_at"] = "9999-12-31T23:59:59-23:00"
                    raw = json.dumps(manifest).encode()
                output.append((info, raw))
            return output

        altered = self.rewrite(overflow)
        os.replace(altered, self.archive)
        with self.assertRaises(backup.BackupError):
            backup.validate_backup(self.archive)
        env = {
            key: value for key, value in os.environ.items() if not key.startswith("TUTOR_BACKUP_")
        }
        env["TUTOR_BACKUP_DIR"] = str(directory)
        result = subprocess.run(
            [
                sys.executable,
                "tools/tutor.py",
                "--student-dir",
                str(self.student),
                "configure",
                "--daily-minutes",
                "47",
            ],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            text=True,
            capture_output=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        state = storage.load(self.student / "english/learner.json", None)
        self.assertEqual(state["profile"]["daily_minutes"], 47)
        self.assertEqual(json.loads(result.stdout)["backup"]["status"], "created")
        self.assertTrue(self.archive.exists())

    def test_archive_truncation_between_stat_and_directory_read_is_normalized(self):
        self.create()
        with self.archive.open("rb") as source:
            truncating = SimpleNamespace(
                fileno=source.fileno, seek=source.seek, read=lambda size: b""
            )
            with self.assertRaises(backup.BackupError):
                backup._zip_index(truncating, backup.DEFAULT_LIMITS)

    def _kill_at_publication(self, operation, destination, after=False):
        marker = self.root / f"{operation}-{after}.ready"
        script = """from pathlib import Path
from tools import backup
import os, signal, sys
operation, source, destination, marker, after = sys.argv[1:]
name = '_publish_archive' if operation == 'create' else '_publish_restore'
original = getattr(backup, name)
def paused(stage, destination):
    if after == 'yes':
        original(stage, destination)
    Path(marker).write_text('ready')
    os.kill(os.getpid(), signal.SIGSTOP)
    original(stage, destination)
setattr(backup, name, paused)
if operation == 'create':
    backup.create_backup(Path(source), Path(destination))
else:
    backup.restore_backup(Path(source), Path(destination))
"""
        source = self.student if operation == "create" else self.archive
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                script,
                operation,
                str(source),
                str(destination),
                str(marker),
                "yes" if after else "no",
            ],
            cwd=Path(__file__).resolve().parents[1],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        deadline = time.monotonic() + 8
        while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        if not marker.exists():
            process.kill()
            _, stderr = process.communicate(timeout=5)
            self.fail(f"child did not reach publication: {stderr.decode()}")
        process.kill()
        process.communicate(timeout=5)
        self.assertEqual(process.returncode, -signal.SIGKILL)

    def test_sigkill_before_archive_publication_keeps_old_backup_and_source(self):
        self.create()
        original = self.archive.read_bytes()
        destination = self.root / "killed-backup.zip"
        self._kill_at_publication("create", destination)
        self.assertFalse(destination.exists())
        self.assertEqual(self.archive.read_bytes(), original)
        backup.validate_backup(self.archive)
        self.assertEqual((self.student / "active.txt").read_text(), "english\n")

    def test_sigkill_after_archive_publication_exposes_only_complete_archive(self):
        destination = self.root / "published-backup.zip"
        self._kill_at_publication("create", destination, after=True)
        backup.validate_backup(destination)

    def test_sigkill_before_restore_publication_leaves_no_partial_destination(self):
        self.create()
        destination = self.root / "killed-restore"
        self._kill_at_publication("restore", destination)
        self.assertFalse(destination.exists())
        backup.validate_backup(self.archive)

    def test_sigkill_after_restore_publication_leaves_complete_recoverable_tree(self):
        self.create()
        destination = self.root / "published-restore"
        self._kill_at_publication("restore", destination, after=True)
        manifest = backup.validate_backup(self.archive)
        for entry in manifest["files"]:
            self.assertEqual(
                hashlib.sha256((destination / entry["path"]).read_bytes()).hexdigest(),
                entry["sha256"],
            )


if __name__ == "__main__":
    unittest.main()
