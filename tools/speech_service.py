"""Web-facing lifecycle for optional local speech setup and transcription."""

from __future__ import annotations

import importlib
import threading


class SpeechService:
    def __init__(self, engine=None):
        self.engine = engine
        self.lock = threading.Lock()
        self.setup_running = False
        self.setup_stage = None
        self.setup_error = None
        self.closed = False

    def _engine(self):
        if self.engine is None:
            self.engine = importlib.import_module("speech")
        return self.engine

    def status(self):
        result = self._engine().status()
        with self.lock:
            return {
                **result,
                "setup": {
                    "running": self.setup_running,
                    "stage": self.setup_stage,
                    "error": self.setup_error,
                },
            }

    def setup(self):
        with self.lock:
            if self.closed:
                raise RuntimeError("speech service is closed")
            if self.setup_running:
                return {"accepted": True, "duplicate": True}
            self.setup_running = True
            self.setup_stage = "starting"
            self.setup_error = None
        threading.Thread(target=self._run_setup, daemon=True, name="tutor-speech-setup").start()
        return {"accepted": True, "duplicate": False}

    def _run_setup(self):
        def progress(stage):
            with self.lock:
                self.setup_stage = (
                    stage if isinstance(stage, str) and len(stage) <= 100 else "working"
                )

        try:
            self._engine().setup(progress_callback=progress)
            with self.lock:
                self.setup_stage = "ready"
        except Exception:
            # Do not forward build logs, paths or process output to the browser.
            with self.lock:
                self.setup_error = "Не удалось подготовить Whisper. Проверьте зависимости и выполните команду установки из инструкции. Текстовый чат доступен."
                self.setup_stage = "failed"
        finally:
            with self.lock:
                self.setup_running = False

    def transcribe(self, data, content_type, language="auto"):
        with self.lock:
            if self.closed or self.setup_running:
                raise RuntimeError("speech setup is in progress")
        if language not in {"auto", "ru", "en"}:
            raise ValueError("unsupported recognition language")
        return self._engine().transcribe_bytes(data, content_type, language=language)

    def close(self):
        with self.lock:
            self.closed = True
            engine = self.engine
        cancel = getattr(engine, "cancel_active", None)
        if callable(cancel):
            cancel()
