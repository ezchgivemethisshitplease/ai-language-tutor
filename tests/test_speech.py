"""Local speech contract; no microphone, auth, network or model required."""

from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import wave
import zipfile

from tools import speech


def pcm(path, duration=1, amplitude=100):
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(
            int(amplitude).to_bytes(2, "little", signed=True) * int(duration * 16000)
        )


class SpeechTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.service = speech.LocalSpeech(self.root / "speech")
        self.commands = []
        self.decode_duration = 1
        self.amplitude = 100
        self.transcript = {
            "result": {"language": "en"},
            "transcription": [{"text": " Hello world."}],
        }

    def tearDown(self):
        self.temporary.cleanup()

    def runner(self, command, *, cwd, timeout, code, **kwargs):
        self.commands.append(command)
        if "-c:a" in command:
            self.assertEqual(
                Path(command[command.index("-i") + 1]).read_bytes(), b"raw browser audio"
            )
            pcm(Path(command[-1]), self.decode_duration, self.amplitude)
        elif "--output-json" in command:
            prefix = Path(command[command.index("--output-file") + 1])
            prefix.with_suffix(".json").write_text(json.dumps(self.transcript), encoding="utf-8")
        return b""

    @contextmanager
    def ready(self):
        with (
            patch.object(self.service, "status", return_value={"available": True}),
            patch.object(self.service, "_ffmpeg", return_value=Path("/local/ffmpeg")),
            patch.object(speech, "_run", side_effect=self.runner),
            patch.object(
                speech.urllib.request, "urlopen", side_effect=AssertionError("network forbidden")
            ),
        ):
            yield

    def no_audio_temps(self):
        if self.service.runtime.exists():
            self.assertEqual(list(self.service.runtime.glob("audio-*")), [])

    def test_status_is_read_only_and_does_not_install_or_connect(self):
        with patch.object(speech.urllib.request, "urlopen", side_effect=AssertionError("network")):
            status = self.service.status()
        self.assertEqual(status["status"], "unavailable")
        self.assertFalse(status["available"])
        self.assertEqual(status["max_bytes"], 12 * 1024 * 1024)
        self.assertEqual(status["evidence_policy"], "transcript_only")
        self.assertFalse(self.service.runtime.exists())

    def test_raw_audio_transcribes_locally_into_text_without_assessment_or_retention(self):
        with self.ready():
            result = self.service.transcribe_bytes(b"raw browser audio", "audio/webm;codecs=opus")
        self.assertEqual(
            result,
            {
                "text": "Hello world.",
                "language": "en",
                "duration_seconds": 1.0,
                "backend": "whisper.cpp",
                "model": "base",
                "evidence_policy": "transcript_only",
            },
        )
        self.assertNotIn("audio_evidence", result)
        decoder, recognizer = self.commands
        self.assertEqual(decoder[decoder.index("-f") + 1], "matroska")
        self.assertIn("file,pipe", decoder)
        self.assertEqual(decoder[decoder.index("-t") + 1], "61")
        self.assertEqual(recognizer[recognizer.index("--language") + 1], "auto")
        self.assertNotIn("--translate", recognizer)
        self.no_audio_temps()
        self.assertEqual(os.stat(self.service.runtime).st_mode & 0o777, 0o700)

    def test_browser_formats_use_fixed_demuxers_and_mp4_external_refs_are_disabled(self):
        for mime, demuxer in (
            ("audio/webm", "matroska"),
            ("audio/ogg", "ogg"),
            ("audio/mp4", "mov"),
            ("audio/wav", "wav"),
            ("audio/mpeg", "mp3"),
        ):
            self.commands.clear()
            with self.subTest(mime=mime), self.ready():
                result = self.service.transcribe_bytes(b"raw browser audio", mime, language="ru")
            self.assertEqual(result["evidence_policy"], "transcript_only")
            decoder, recognizer = self.commands
            self.assertEqual(decoder[decoder.index("-f") + 1], demuxer)
            self.assertEqual(recognizer[recognizer.index("--language") + 1], "ru")
            if mime == "audio/mp4":
                self.assertEqual(decoder[decoder.index("-enable_drefs") + 1], "0")
                self.assertEqual(decoder[decoder.index("-use_absolute_path") + 1], "0")
            self.no_audio_temps()

    def test_input_validation_does_not_start_any_child(self):
        cases = [
            (b"", "audio/webm", "auto", "invalid_audio"),
            (b"x" * (speech.MAX_BYTES + 1), "audio/webm", "auto", "too_large"),
            (b"x", "text/plain", "auto", "invalid_audio"),
            (b"x", "audio/webm", "$(command)", "invalid_audio"),
        ]
        with patch.object(speech, "_run") as runner:
            for data, mime, language, code in cases:
                with self.subTest(code=code), self.assertRaises(speech.SpeechError) as error:
                    self.service.transcribe_bytes(data, mime, language=language)
                self.assertEqual(error.exception.code, code)
            runner.assert_not_called()
        self.assertFalse(self.service.runtime.exists())

    def test_missing_backend_remains_unavailable_without_auto_setup(self):
        with patch.object(self.service, "setup") as setup, patch.object(speech, "_run") as run:
            with self.assertRaises(speech.SpeechError) as error:
                self.service.transcribe_bytes(b"audio", "audio/webm")
            self.assertEqual(error.exception.code, "unavailable")
            setup.assert_not_called()
            run.assert_not_called()
        self.no_audio_temps()

    def test_bad_or_partial_media_does_not_reach_whisper_and_cleans_temps(self):
        def decode_failure(*args, **kwargs):
            raise speech.SpeechError("invalid_audio", "decoder failed")

        with self.ready(), patch.object(speech, "_run", side_effect=decode_failure):
            with self.assertRaises(speech.SpeechError) as error:
                self.service.transcribe_bytes(b"raw browser audio", "audio/webm")
        self.assertEqual(error.exception.code, "invalid_audio")
        self.no_audio_temps()

    def test_decoded_duration_and_silence_are_checked_before_inference(self):
        for duration, amplitude, code in [
            (61, 100, "too_long"),
            (0.1, 100, "invalid_audio"),
            (1, 0, "invalid_audio"),
        ]:
            with self.subTest(duration=duration, amplitude=amplitude):
                self.decode_duration, self.amplitude = duration, amplitude
                self.commands.clear()
                with self.ready(), self.assertRaises(speech.SpeechError) as error:
                    self.service.transcribe_bytes(b"raw browser audio", "audio/webm")
                self.assertEqual(error.exception.code, code)
                self.assertEqual(len(self.commands), 1)
                self.no_audio_temps()

    def test_timeout_or_whisper_failure_cleans_audio_and_releases_lock(self):
        original = self.runner

        def timeout(command, **kwargs):
            if "--output-json" in command:
                raise speech.SpeechError("timeout", "deadline")
            return original(command, **kwargs)

        with self.ready(), patch.object(speech, "_run", side_effect=timeout):
            with self.assertRaises(speech.SpeechError) as error:
                self.service.transcribe_bytes(b"raw browser audio", "audio/webm")
        self.assertEqual(error.exception.code, "timeout")
        self.no_audio_temps()
        with self.ready():
            self.assertEqual(
                self.service.transcribe_bytes(b"raw browser audio", "audio/webm")["text"],
                "Hello world.",
            )

    def test_bad_empty_or_oversized_transcripts_remain_errors(self):
        for transcript in (
            {},
            {"transcription": None},
            {"transcription": [{}]},
            {"result": {"language": "en"}, "transcription": [{"text": ""}]},
            {"result": {"language": "en"}, "transcription": [{"text": "x" * 16001}]},
        ):
            self.transcript = transcript
            with self.ready(), self.assertRaises(speech.SpeechError) as error:
                self.service.transcribe_bytes(b"raw browser audio", "audio/webm")
            self.assertEqual(error.exception.code, "transcription_failed")
            self.no_audio_temps()

    def test_cross_instance_and_process_resource_lock_is_nonblocking(self):
        another = speech.LocalSpeech(self.service.runtime)
        with self.service._operation():
            with self.assertRaises(speech.SpeechBusy):
                with another._operation():
                    self.fail("concurrent operation admitted")
            command = [
                sys.executable,
                "-c",
                "import fcntl,sys; f=open(sys.argv[1],'a+b'); fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)",
                str(self.service.runtime / ".resource.lock"),
            ]
            child = subprocess.run(command, capture_output=True, timeout=5)
            self.assertNotEqual(child.returncode, 0)
        with another._operation():
            pass

    def test_same_instance_busy_does_not_wait_for_long_transcription(self):
        errors = []

        def other_thread():
            try:
                with self.service._operation():
                    pass
            except speech.SpeechBusy as exc:
                errors.append(exc.code)

        with self.service._operation():
            thread = threading.Thread(target=other_thread)
            thread.start()
            thread.join(timeout=1)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, ["busy"])

    def test_resource_symlink_is_rejected(self):
        self.service.runtime.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(speech.SpeechError):
            with self.service._operation():
                self.fail("symlink admitted")

    def test_setup_missing_compiler_is_explicit_and_does_not_download(self):
        with (
            patch.object(self.service, "_prerequisites", return_value=["c++"]),
            patch.object(speech, "_download") as download,
        ):
            with self.assertRaises(speech.SpeechError) as error:
                self.service.setup()
            self.assertEqual(error.exception.code, "unavailable")
            download.assert_not_called()

    def test_setup_checks_source_commit_before_building_or_downloading_model(self):
        self.service.source.mkdir(parents=True)
        with (
            patch.object(self.service, "_prerequisites", return_value=[]),
            patch.object(self.service, "_install_ffmpeg"),
            patch.object(speech, "_run", return_value=b"different-commit\n") as runner,
            patch.object(speech, "_download") as download,
        ):
            with self.assertRaises(speech.SpeechError) as error:
                self.service.setup()
            self.assertEqual(error.exception.code, "setup_failed")
            self.assertEqual(runner.call_count, 1)
            download.assert_not_called()

    def test_model_hash_is_checked_and_rechecked_after_content_changes(self):
        self.service.model.parent.mkdir(parents=True)
        self.service.model.write_bytes(b"model")
        digest = hashlib.sha256(b"model").hexdigest()
        with patch.object(speech, "MODEL_BYTES", 5), patch.object(speech, "MODEL_SHA256", digest):
            self.assertTrue(self.service._model_valid())
            self.service.model.write_bytes(b"other")
            self.assertFalse(self.service._model_valid())

    def test_download_checks_digest_and_cleans_partial_on_corrupt_or_offline_response(self):
        destination = self.root / "model.bin"
        for failure in (False, True):
            with (
                self.subTest(offline=failure),
                patch.object(
                    speech.urllib.request,
                    "urlopen",
                    side_effect=OSError("private network detail") if failure else None,
                    return_value=io.BytesIO(b"wrong bytes"),
                ),
            ):
                with self.assertRaises(speech.SpeechError) as error:
                    speech._download("https://official.invalid/file", destination, "0" * 64, 100)
                self.assertEqual(error.exception.code, "setup_failed")
                self.assertNotIn("private", str(error.exception))
                self.assertFalse(destination.exists())
                self.assertFalse(destination.with_suffix(".bin.part").exists())
        with patch.object(speech.urllib.request, "urlopen", return_value=io.BytesIO(b"model")):
            speech._download(
                "https://official.invalid/file",
                destination,
                hashlib.sha256(b"model").hexdigest(),
                5,
            )
        self.assertEqual(destination.read_bytes(), b"model")

    def test_private_ffmpeg_wheel_extracts_only_binary_and_license(self):
        self.service.runtime.mkdir()

        def download(url, destination, digest, max_bytes, **kwargs):
            self.assertIn("imageio_ffmpeg-0.6.0", url)
            self.assertEqual(len(digest), 64)
            with zipfile.ZipFile(destination, "w") as archive:
                archive.writestr("imageio_ffmpeg/binaries/ffmpeg-test", b"binary")
                archive.writestr("imageio_ffmpeg/binaries/README.md", b"not installed")
                archive.writestr("imageio_ffmpeg-0.6.0.dist-info/LICENSE", b"license")
                archive.writestr("../escape", b"ignored")

        with (
            patch.object(self.service, "_ffmpeg", return_value=None),
            patch.object(speech, "_download", side_effect=download),
            patch.object(speech.platform, "machine", return_value="arm64"),
            patch.object(speech.sys, "platform", "darwin"),
        ):
            self.service._install_ffmpeg()
        self.assertEqual((self.service.runtime / "ffmpeg/ffmpeg").read_bytes(), b"binary")
        self.assertTrue((self.service.runtime / "ffmpeg/LICENSE").exists())
        self.assertFalse((self.service.runtime / "ffmpeg/decoder.whl").exists())
        self.assertFalse((self.service.runtime / "escape").exists())

    def test_native_child_timeout_and_output_bound_hide_private_log_content(self):
        for snippet, timeout in [
            ("import time; time.sleep(2)", 0.05),
            ("print('private ' * 50000)", 5),
        ]:
            with self.subTest(timeout=timeout), self.assertRaises(speech.SpeechError) as error:
                speech._run(
                    [sys.executable, "-c", snippet],
                    cwd=self.root,
                    timeout=timeout,
                    code="transcription_failed",
                )
            self.assertNotIn("private", str(error.exception))

    def test_child_environment_excludes_service_credentials(self):
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "private", "CODEX_HOME": "private", "ELEVENLABS_API_KEY": "private"},
        ):
            environment = speech._environment()
        self.assertNotIn("OPENAI_API_KEY", environment)
        self.assertNotIn("CODEX_HOME", environment)
        self.assertNotIn("ELEVENLABS_API_KEY", environment)

    def test_close_kills_only_owned_native_child_and_prevents_new_work(self):
        errors = []

        def run():
            try:
                self.service._run(
                    [sys.executable, "-c", "import time; time.sleep(30)"],
                    cwd=self.root,
                    timeout=60,
                    code="setup_failed",
                )
            except speech.SpeechError as error:
                errors.append(error.code)

        unrelated = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True
        )
        thread = threading.Thread(target=run)
        thread.start()
        try:
            deadline = time.monotonic() + 2
            while not self.service._children and time.monotonic() < deadline:
                time.sleep(0.001)
            self.assertTrue(self.service._children)
            owned = list(self.service._children)
            self.service.close()
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, ["canceled"])
            self.assertTrue(all(child.poll() is not None for child in owned))
            self.assertIsNone(unrelated.poll())
            self.assertEqual(self.service._children, set())
            with self.assertRaises(speech.SpeechError) as error:
                with self.service._operation():
                    pass
            self.assertEqual(error.exception.code, "canceled")
            self.service.close()
        finally:
            unrelated.kill()
            unrelated.wait(timeout=2)
            self.service.close()
            thread.join(timeout=2)

    def test_cancelled_download_does_not_connect_or_leave_partial_file(self):
        event = threading.Event()
        event.set()
        destination = self.root / "canceled.bin"
        with patch.object(speech.urllib.request, "urlopen") as connect:
            with self.assertRaises(speech.SpeechError) as error:
                speech._download(
                    "https://official.invalid/file", destination, "0" * 64, 100, cancel_event=event
                )
            self.assertEqual(error.exception.code, "canceled")
            connect.assert_not_called()
        self.assertFalse(destination.exists())
        self.assertFalse(destination.with_suffix(".bin.part").exists())


if __name__ == "__main__":
    unittest.main()
