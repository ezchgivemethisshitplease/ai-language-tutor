"""Native stimulus generation is bounded, local, and publishes no partial file."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import backup, tts

ACTUAL_PLATFORM = sys.platform


class NativeAudioTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.real_publish = backup._publish_archive

    def publish_on_real_os(self, stage, destination):
        with patch.object(tts.sys, "platform", ACTUAL_PLATFORM):
            self.real_publish(stage, destination)

    def tearDown(self):
        self.temporary.cleanup()

    def test_mac_text_is_stdin_data_and_cloud_configuration_does_not_enable_transmission(self):
        text = "--voice other $(touch do-not-run)"
        output = self.root / "stimulus.aiff"

        def render(command, **kwargs):
            self.assertEqual(command[:4], ["/usr/bin/say", "-v", "Samantha", "-o"])
            self.assertEqual(kwargs["input"], text)
            self.assertNotIn(text, command)
            Path(command[-1]).write_bytes(b"FORM" + b"\0" * 4 + b"AIFC" + b"\0" * 100)

        with (
            patch.object(tts.sys, "platform", "darwin"),
            patch.object(
                tts.shutil,
                "which",
                side_effect=lambda name: "/usr/bin/say" if name == "say" else None,
            ),
            patch.object(tts.subprocess, "run", side_effect=render),
            patch.object(backup, "_publish_archive", side_effect=self.publish_on_real_os),
            patch.dict(tts.os.environ, {"TUTOR_TTS": "openai", "OPENAI_API_KEY": "fixture"}),
            patch.object(tts.urllib.request, "urlopen", side_effect=AssertionError("cloud call")),
        ):
            result = tts.native_file(text, output)
        self.assertTrue(result["synthetic_stimulus"])
        self.assertEqual(result["provider"], "macos-say")
        self.assertEqual(len(result["sha256"]), 64)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_timeout_and_invalid_audio_leave_no_published_output(self):
        for failure in (subprocess.TimeoutExpired("say", 30), None):
            with self.subTest(failure=failure):
                output = self.root / "stimulus.aiff"
                with (
                    patch.object(tts.sys, "platform", "darwin"),
                    patch.object(tts.shutil, "which", return_value="/usr/bin/say"),
                    patch.object(tts.subprocess, "run", side_effect=failure),
                ):
                    with self.assertRaises(ValueError):
                        tts.native_file("An original short script.", output)
                self.assertFalse(output.exists())
                self.assertFalse(list(self.root.iterdir()))

    def test_linux_uses_english_espeak_and_wave(self):
        def render(command, **kwargs):
            self.assertEqual(command[:4], ["/usr/bin/espeak-ng", "-v", "en", "-w"])
            Path(command[-1]).write_bytes(b"RIFF" + b"\0" * 4 + b"WAVE" + b"\0" * 100)

        with (
            patch.object(tts.sys, "platform", "linux"),
            patch.object(
                tts.shutil,
                "which",
                side_effect=lambda name: "/usr/bin/espeak-ng" if name == "espeak-ng" else None,
            ),
            patch.object(tts.subprocess, "run", side_effect=render),
            patch.object(backup, "_publish_archive", side_effect=self.publish_on_real_os),
        ):
            result = tts.native_file("The train leaves at ten.", self.root / "stimulus.wav")
        self.assertEqual(result["provider"], "espeak")

    def test_existing_audio_and_oversized_text_are_rejected_before_synthesis(self):
        output = self.root / "original.aiff"
        output.write_bytes(b"original learner audio")
        with patch.object(tts.subprocess, "run", side_effect=AssertionError("must not synthesize")):
            with self.assertRaises(ValueError):
                tts.native_file("Hello", output)
            with self.assertRaises(ValueError):
                tts.native_file("a" * 2001, self.root / "new.aiff")
        self.assertEqual(output.read_bytes(), b"original learner audio")


if __name__ == "__main__":
    unittest.main()
