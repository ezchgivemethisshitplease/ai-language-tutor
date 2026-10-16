import json
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
import serve
import speech_service
import srs
import web_tutor


class FakeSpeech:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.ready = False
        self.calls = []
        self.setup_calls = 0
        self.fail_setup = False

    def status(self):
        return {
            "status": "ready" if self.ready else "unavailable",
            "available": self.ready,
            "backend": "whisper.cpp",
            "setup_available": True,
        }

    def setup(self, progress_callback):
        self.setup_calls += 1
        self.started.set()
        progress_callback("download_model")
        self.release.wait(2)
        if self.fail_setup:
            raise RuntimeError("private-token-and-build-output")
        self.ready = True
        return self.status()

    def transcribe_bytes(self, data, content_type, *, language):
        self.calls.append((data, content_type, language))
        return {
            "text": "  I am at home.\n",
            "language": language,
            "duration_seconds": 2.5,
            "backend": "whisper.cpp",
            "model": "base",
            "evidence_policy": "transcript_only",
        }


class SpeechServiceTests(unittest.TestCase):
    def test_setup_is_async_deduplicated_and_status_tracks_safe_stages(self):
        engine = FakeSpeech()
        service = speech_service.SpeechService(engine)
        self.assertFalse(service.setup()["duplicate"])
        self.assertTrue(engine.started.wait(1))
        self.assertTrue(service.setup()["duplicate"])
        status = service.status()
        self.assertTrue(status["setup"]["running"])
        self.assertEqual(status["setup"]["stage"], "download_model")
        with self.assertRaises(RuntimeError):
            service.transcribe(b"audio", "audio/webm")
        engine.release.set()
        end = time.monotonic() + 2
        while service.status()["setup"]["running"] and time.monotonic() < end:
            time.sleep(0.01)
        self.assertEqual(service.status()["setup"]["stage"], "ready")
        self.assertEqual(engine.setup_calls, 1)
        result = service.transcribe(b"audio", "audio/webm", "en")
        self.assertEqual(result["text"], "  I am at home.\n")
        self.assertEqual(engine.calls, [(b"audio", "audio/webm", "en")])

    def test_setup_failure_does_not_expose_build_logs_or_block_text_work(self):
        engine = FakeSpeech()
        engine.fail_setup = True
        engine.release.set()
        service = speech_service.SpeechService(engine)
        service.setup()
        end = time.monotonic() + 2
        while service.status()["setup"]["running"] and time.monotonic() < end:
            time.sleep(0.01)
        status = service.status()
        self.assertEqual(status["setup"]["stage"], "failed")
        self.assertNotIn("private-token", json.dumps(status))
        with self.assertRaises(ValueError):
            service.transcribe(b"audio", "audio/webm", "../../elsewhere")

    def test_http_audio_requires_session_namespace_and_bounded_raw_body(self):
        with tempfile.TemporaryDirectory() as temporary:
            student = Path(temporary) / "student"
            tutor = web_tutor.WebTutor(student, runtime=Path(temporary) / "runtime")
            engine = FakeSpeech()
            service = speech_service.SpeechService(engine)
            with patch.object(serve, "STUDENT", student), patch.object(srs, "STUDENT", student):
                server = serve.create_server(tutor=tutor, speech=service)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base = f"http://127.0.0.1:{server.server_address[1]}"

                def request(path, data=None, extra=None, expected=200):
                    headers = {
                        "X-Tutor-Token": server.shutdown_token,
                        "X-Tutor-Namespace": serve.namespace(),
                        "Content-Type": "audio/webm;codecs=opus",
                    }
                    headers.update(extra or {})
                    req = urllib.request.Request(base + path, data=data, headers=headers)
                    try:
                        response = urllib.request.urlopen(req, timeout=3)
                    except urllib.error.HTTPError as error:
                        response = error
                    with response:
                        self.assertEqual(response.status, expected)
                        return json.load(response)

                try:
                    request("/api/speech/status", extra={"X-Tutor-Token": ""}, expected=403)
                    request(
                        "/api/speech/transcribe",
                        b"sample",
                        {"Origin": "https://evil.example"},
                        expected=403,
                    )
                    request(
                        "/api/speech/transcribe",
                        b"sample",
                        {"X-Tutor-Namespace": "stale"},
                        expected=409,
                    )
                    result = request(
                        "/api/speech/transcribe", b"sample", {"X-Speech-Language": "en"}
                    )
                    self.assertEqual(result["text"], "  I am at home.\n")
                    self.assertEqual(engine.calls, [(b"sample", "audio/webm;codecs=opus", "en")])
                    request(
                        "/api/speech/transcribe",
                        b"sample",
                        {"Content-Length": str(serve.MAX_AUDIO_BODY + 1)},
                        expected=413,
                    )
                    request(
                        "/api/speech/transcribe",
                        b"sample",
                        {"X-Speech-Language": "fr"},
                        expected=422,
                    )
                    engine.release.set()
                    self.assertTrue(
                        request(
                            "/api/speech/setup",
                            b"{}",
                            {"Content-Type": "application/json"},
                            expected=202,
                        )["accepted"]
                    )
                    self.assertFalse((student / "english/learner.json").exists())
                finally:
                    server.shutdown()
                    thread.join(timeout=2)
                    server.server_close()


if __name__ == "__main__":
    unittest.main()
