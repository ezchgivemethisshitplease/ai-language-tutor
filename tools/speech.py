#!/usr/bin/env python3
"""Optional, local Whisper dictation for macOS/Linux; never records a microphone.

The browser owns recording and an editable draft. A transcript is text input,
not acoustic assessment or automatic speaking credit. Audio is decoded locally
and deleted after each request. Only explicit setup uses the network.

Backend/build flags: https://github.com/ggml-org/whisper.cpp/tree/v1.9.5
Model digest: https://huggingface.co/ggerganov/whisper.cpp/raw/main/ggml-base.bin
Optional FFmpeg wheels/digests: https://pypi.org/pypi/imageio-ffmpeg/0.6.0/json
FFmpeg decoder options: https://ffmpeg.org/ffmpeg-formats.html#mov_002fmp4_002f3gp

Usage: python tools/speech.py setup | status | transcribe FILE --language auto
Setup builds a pinned native CLI and downloads a checked multilingual base
model under .runtime/speech. It does not install Python/Torch or system packages.
"""

from __future__ import annotations

import argparse
from array import array
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable, Iterator
import urllib.request
import wave
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime/speech"
VERSION = "1.9.5"
SOURCE_COMMIT = "d1be6fde11ac6e0407606b4e42fe72d34add8037"
MODEL = "base"
MODEL_SHA256 = "60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe"
MODEL_BYTES = 147951465
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin"
MAX_BYTES = 12 * 1024 * 1024
MAX_SECONDS = 60
MAX_TEXT = 16000
MAX_LOG_BYTES = 256 * 1024
ACCEPTED_MIME_TYPES = (
    "audio/webm",
    "audio/ogg",
    "audio/mp4",
    "audio/wav",
    "audio/x-wav",
    "audio/mpeg",
)
_FORMATS = {
    "audio/webm": ("matroska", ".webm"),
    "audio/ogg": ("ogg", ".ogg"),
    "audio/mp4": ("mov", ".mp4"),
    "audio/wav": ("wav", ".wav"),
    "audio/x-wav": ("wav", ".wav"),
    "audio/mpeg": ("mp3", ".mp3"),
}
# Official imageio-ffmpeg 0.6.0 wheels. Only a checked binary and license are
# extracted, with no package import/install. This is used only without FFmpeg.
_WHEELS = {
    ("darwin", "arm64"): (
        "40/5c/f3d8a657d362cc93b81aab8feda487317da5b5d31c0e1fdfd5e986e55d17/"
        "imageio_ffmpeg-0.6.0-py3-none-macosx_11_0_arm64.whl",
        "b1ae3173414b5fc5f538a726c4e48ea97edc0d2cdc11f103afee655c463fa742",
    ),
    ("darwin", "x86_64"): (
        "da/58/87ef68ac83f4c7690961bce288fd8e382bc5f1513860fc7f90a9c1c1c6bf/"
        "imageio_ffmpeg-0.6.0-py3-none-macosx_10_9_intel.macosx_10_9_x86_64.whl",
        "9d2baaf867088508d4a3458e61eeb30e945c4ad8016025545f66c4b5aaef0a61",
    ),
    ("linux", "aarch64"): (
        "33/e7/1925bfbc563c39c1d2e82501d8372734a5c725e53ac3b31b4c2d081e895b/"
        "imageio_ffmpeg-0.6.0-py3-none-manylinux2014_aarch64.whl",
        "1d47bebd83d2c5fc770720d211855f208af8a596c82d17730aa51e815cdee6dc",
    ),
    ("linux", "x86_64"): (
        "a0/2d/43c8522a2038e9d0e7dbdf3a61195ecc31ca576fb1527a528c877e87d973/"
        "imageio_ffmpeg-0.6.0-py3-none-manylinux2014_x86_64.whl",
        "c7e46fcec401dd990405049d2e2f475e2b397779df2519b544b8aab515195282",
    ),
}


class SpeechError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class SpeechBusy(SpeechError):
    def __init__(self):
        super().__init__("busy", "Распознавание или установка уже выполняется. Попробуйте позже.")


def _environment() -> dict[str, str]:
    keys = {"PATH", "HOME", "USER", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TMP", "TEMP"}
    environment = {key: value for key, value in os.environ.items() if key in keys}
    # Public source checkout needs no personal Git configuration, hooks or auth.
    environment.update(
        GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null", GIT_TERMINAL_PROMPT="0"
    )
    return environment


def _kill(process: subprocess.Popen) -> None:
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            process.kill()


def _run(
    command: list[str],
    *,
    cwd: Path,
    timeout: float,
    code: str,
    cancel_event: threading.Event | None = None,
    process_callback: Callable[[subprocess.Popen, bool], None] | None = None,
) -> bytes:
    """Bound child time/output without retaining private raw audio or logs."""
    if cancel_event is not None and cancel_event.is_set():
        raise SpeechError("canceled", "Обработка речи остановлена.")
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as exc:
        raise SpeechError(code, "Не удалось запустить локальную обработку речи.") from exc
    if process_callback is not None:
        process_callback(process, True)
    if cancel_event is not None and cancel_event.is_set():
        _kill(process)
    output = bytearray()
    overflow = threading.Event()

    def drain() -> None:
        assert process.stdout is not None
        while True:
            chunk = process.stdout.read(8192)
            if not chunk:
                return
            if len(output) + len(chunk) > MAX_LOG_BYTES:
                overflow.set()
                _kill(process)
                return
            output.extend(chunk)

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _kill(process)
        process.wait(timeout=5)
        raise SpeechError("timeout", "Локальная обработка речи превысила время ожидания.") from exc
    finally:
        reader.join(timeout=2)
        if process.stdout is not None:
            process.stdout.close()
        if process_callback is not None:
            process_callback(process, False)
    if cancel_event is not None and cancel_event.is_set():
        raise SpeechError("canceled", "Обработка речи остановлена.")
    if process.returncode != 0 or overflow.is_set():
        raise SpeechError(code, "Локальная обработка не завершилась. Проверьте запись и установку.")
    return bytes(output)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(
    url: str,
    destination: Path,
    digest: str,
    max_bytes: int,
    *,
    cancel_event: threading.Event | None = None,
) -> None:
    """Explicit setup only: checked, bounded, atomic download, never audio."""
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        if cancel_event is not None and cancel_event.is_set():
            raise SpeechError("canceled", "Установка речи остановлена.")
        with urllib.request.urlopen(url, timeout=30) as source, temporary.open("wb") as target:
            os.chmod(temporary, 0o600)
            received = 0
            started = time.monotonic()
            while chunk := source.read(1024 * 1024):
                if cancel_event is not None and cancel_event.is_set():
                    raise SpeechError("canceled", "Установка речи остановлена.")
                received += len(chunk)
                if received > max_bytes or time.monotonic() - started > 600:
                    raise SpeechError(
                        "setup_failed", "Загрузка модели превысила допустимый размер или время."
                    )
                target.write(chunk)
        if _sha256(temporary) != digest:
            raise SpeechError(
                "setup_failed", "Контрольная сумма загрузки не совпала. Установка остановлена."
            )
        os.replace(temporary, destination)
    except (OSError, ValueError) as exc:
        raise SpeechError(
            "setup_failed", "Не удалось скачать компоненты. Проверьте подключение к сети."
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)


class LocalSpeech:
    def __init__(self, runtime_dir: Path = RUNTIME):
        self.runtime = Path(runtime_dir).absolute()
        self.source = self.runtime / "whisper.cpp"
        self.binary = self.source / "build/bin/whisper-cli"
        self.model = self.runtime / "models/ggml-base.bin"
        self._lock = threading.Lock()
        self._checked_model: tuple[int, int, int, int] | None = None
        self._cancelled = threading.Event()
        self._children_lock = threading.Lock()
        self._children: set[subprocess.Popen] = set()

    def _track_process(self, process: subprocess.Popen, running: bool) -> None:
        with self._children_lock:
            if running:
                self._children.add(process)
            else:
                self._children.discard(process)
        if running and self._cancelled.is_set():
            _kill(process)

    def _run(self, command: list[str], *, cwd: Path, timeout: float, code: str) -> bytes:
        return _run(
            command,
            cwd=cwd,
            timeout=timeout,
            code=code,
            cancel_event=self._cancelled,
            process_callback=self._track_process,
        )

    def close(self) -> None:
        """Cancel this instance's children; other servers keep their own jobs."""
        self._cancelled.set()
        with self._children_lock:
            children = list(self._children)
        for child in children:
            _kill(child)
        for child in children:
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass

    def _ffmpeg(self) -> Path | None:
        system = shutil.which("ffmpeg")
        bundled = self.runtime / "ffmpeg/ffmpeg"
        selected = Path(system) if system else bundled
        return selected if selected.is_file() and os.access(selected, os.X_OK) else None

    def _model_valid(self) -> bool:
        if not self.model.is_file() or self.model.is_symlink():
            return False
        stat = self.model.stat()
        identity = (stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        if stat.st_size != MODEL_BYTES:
            return False
        if identity != self._checked_model:
            if _sha256(self.model) != MODEL_SHA256:
                return False
            self._checked_model = identity
        return True

    def _prerequisites(self) -> list[str]:
        return [name for name in ("git", "cmake", "c++") if shutil.which(name) is None]

    def status(self) -> dict:
        """Read-only: status never downloads, creates dirs or records audio."""
        supported = sys.platform in {"darwin", "linux"}
        missing = self._prerequisites()
        available = (
            supported
            and not self._cancelled.is_set()
            and self.binary.is_file()
            and os.access(self.binary, os.X_OK)
            and self._ffmpeg() is not None
            and self._model_valid()
        )
        reason = None
        if not supported:
            reason = "Локальная речь поддерживается на macOS и Linux."
        elif not available:
            reason = "Локальное распознавание ещё не установлено."
            if missing:
                reason += " Для сборки нужны: " + ", ".join(missing) + "."
        return {
            "status": "ready" if available else "unavailable",
            "available": bool(available),
            "backend": "whisper.cpp",
            "version": VERSION,
            "model": MODEL,
            "languages": ["auto", "ru", "en"],
            "max_seconds": MAX_SECONDS,
            "max_bytes": MAX_BYTES,
            "accepted_mime_types": list(ACCEPTED_MIME_TYPES),
            "setup_command": "python tools/speech.py setup",
            "setup_available": supported and not missing,
            "reason": reason,
            "evidence_policy": "transcript_only",
        }

    @contextmanager
    def _operation(self) -> Iterator[None]:
        if self._cancelled.is_set():
            raise SpeechError("canceled", "Обработка речи остановлена.")
        if sys.platform not in {"darwin", "linux"}:
            raise SpeechError("unavailable", "Локальная речь поддерживается на macOS и Linux.")
        if not self._lock.acquire(blocking=False):
            raise SpeechBusy()
        handle = None
        try:
            if self.runtime.is_symlink():
                raise SpeechError(
                    "unavailable", "Папка локальной речи не должна быть символической ссылкой."
                )
            self.runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(self.runtime, 0o700)
            lock_path = self.runtime / ".resource.lock"
            if lock_path.is_symlink():
                raise SpeechError("unavailable", "Некорректный файл блокировки речи.")
            handle = lock_path.open("a+b")
            os.chmod(lock_path, 0o600)
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise SpeechBusy() from exc
            if self._cancelled.is_set():
                raise SpeechError("canceled", "Обработка речи остановлена.")
            yield
        finally:
            if handle is not None:
                handle.close()
            self._lock.release()

    def _install_ffmpeg(self) -> None:
        if self._ffmpeg() is not None:
            return
        key = (sys.platform, platform.machine().lower())
        if key not in _WHEELS:
            raise SpeechError(
                "unavailable", "Установите FFmpeg для этой архитектуры и повторите установку."
            )
        suffix, digest = _WHEELS[key]
        folder = self.runtime / "ffmpeg"
        folder.mkdir(mode=0o700, exist_ok=True)
        wheel = folder / "decoder.whl"
        _download(
            "https://files.pythonhosted.org/packages/" + suffix,
            wheel,
            digest,
            40 * 1024 * 1024,
            cancel_event=self._cancelled,
        )
        try:
            with zipfile.ZipFile(wheel) as archive:
                binaries = [
                    info
                    for info in archive.infolist()
                    if info.filename.startswith("imageio_ffmpeg/binaries/ffmpeg-")
                    and not info.is_dir()
                ]
                if len(binaries) != 1 or binaries[0].file_size > 160 * 1024 * 1024:
                    raise SpeechError("setup_failed", "Некорректный архив FFmpeg.")
                destination = folder / "ffmpeg"
                with archive.open(binaries[0]) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target)
                os.chmod(destination, 0o700)
                for info in archive.infolist():
                    if "license" in info.filename.lower() and info.file_size < 256 * 1024:
                        (folder / Path(info.filename).name).write_bytes(archive.read(info))
        finally:
            wheel.unlink(missing_ok=True)

    def setup(self, progress_callback: Callable[[str], None] | None = None) -> dict:
        def progress(stage: str) -> None:
            if progress_callback is not None:
                progress_callback(stage)

        with self._operation():
            missing = self._prerequisites()
            if missing:
                raise SpeechError(
                    "unavailable", "Для сборки установите: " + ", ".join(missing) + "."
                )
            progress("Проверка компонентов")
            self._install_ffmpeg()
            if not self.source.exists():
                progress("Загрузка whisper.cpp")
                self._run(
                    [
                        "git",
                        "clone",
                        "--depth",
                        "1",
                        "--branch",
                        "v" + VERSION,
                        "https://github.com/ggml-org/whisper.cpp.git",
                        str(self.source),
                    ],
                    cwd=self.runtime,
                    timeout=180,
                    code="setup_failed",
                )
            commit = (
                self._run(
                    ["git", "rev-parse", "HEAD"], cwd=self.source, timeout=10, code="setup_failed"
                )
                .decode()
                .strip()
            )
            if commit != SOURCE_COMMIT:
                raise SpeechError(
                    "setup_failed", "Версия исходного whisper.cpp не совпала с закреплённой."
                )
            progress("Сборка локального распознавателя")
            self._run(
                [
                    "cmake",
                    "-S",
                    str(self.source),
                    "-B",
                    str(self.source / "build"),
                    "-DCMAKE_BUILD_TYPE=Release",
                    "-DWHISPER_BUILD_TESTS=OFF",
                    "-DWHISPER_BUILD_SERVER=OFF",
                    "-DWHISPER_CURL=OFF",
                    "-DGGML_METAL=" + ("ON" if sys.platform == "darwin" else "OFF"),
                ],
                cwd=self.runtime,
                timeout=120,
                code="setup_failed",
            )
            self._run(
                [
                    "cmake",
                    "--build",
                    str(self.source / "build"),
                    "--config",
                    "Release",
                    "--target",
                    "whisper-cli",
                    "-j",
                    str(min(4, os.cpu_count() or 1)),
                ],
                cwd=self.runtime,
                timeout=900,
                code="setup_failed",
            )
            self.model.parent.mkdir(mode=0o700, exist_ok=True)
            if not self._model_valid():
                progress("Загрузка и проверка многоязычной модели base")
                _download(
                    MODEL_URL, self.model, MODEL_SHA256, MODEL_BYTES, cancel_event=self._cancelled
                )
            self._run(
                [str(self.binary), "--help"], cwd=self.runtime, timeout=20, code="setup_failed"
            )
            ffmpeg = self._ffmpeg()
            assert ffmpeg is not None
            self._run([str(ffmpeg), "-version"], cwd=self.runtime, timeout=20, code="setup_failed")
            result = self.status()
            if not result["available"]:
                raise SpeechError("setup_failed", "Установка не прошла итоговую проверку.")
            progress("Локальное распознавание готово")
            return result

    def transcribe_bytes(self, data: bytes, content_type: str, *, language: str = "auto") -> dict:
        if not isinstance(data, bytes) or not data:
            raise SpeechError("invalid_audio", "Запись пуста. Запишите фразу ещё раз.")
        if len(data) > MAX_BYTES:
            raise SpeechError(
                "too_large", "Запись превышает 12 МиБ. Запишите более короткую фразу."
            )
        if not isinstance(content_type, str):
            raise SpeechError("invalid_audio", "Неизвестный формат записи.")
        mime = content_type.split(";", 1)[0].strip().lower()
        if mime not in _FORMATS:
            raise SpeechError("invalid_audio", "Этот формат записи не поддерживается.")
        if language not in {"auto", "ru", "en"}:
            raise SpeechError("invalid_audio", "Выберите язык: auto, ru или en.")
        with self._operation():
            if not self.status()["available"]:
                raise SpeechError("unavailable", "Сначала установите локальное распознавание речи.")
            with tempfile.TemporaryDirectory(prefix="audio-", dir=self.runtime) as temporary:
                return self._transcribe(data, mime, language, Path(temporary))

    def _transcribe(self, data: bytes, mime: str, language: str, folder: Path) -> dict:
        demuxer, suffix = _FORMATS[mime]
        recording = folder / ("recording" + suffix)
        recording.write_bytes(data)
        os.chmod(recording, 0o600)
        wav_path = folder / "decoded.wav"
        ffmpeg = self._ffmpeg()
        assert ffmpeg is not None
        command = [
            str(ffmpeg),
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-threads",
            "1",
            "-filter_threads",
            "1",
            "-probesize",
            "5000000",
            "-analyzeduration",
            "5000000",
            "-f",
            demuxer,
        ]
        if demuxer == "mov":
            command += ["-enable_drefs", "0", "-use_absolute_path", "0"]
        command += [
            "-i",
            str(recording),
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            "-t",
            str(MAX_SECONDS + 1),
            str(wav_path),
        ]
        self._run(command, cwd=folder, timeout=25, code="invalid_audio")
        try:
            with wave.open(str(wav_path), "rb") as audio:
                if (
                    audio.getnchannels() != 1
                    or audio.getsampwidth() != 2
                    or audio.getframerate() != 16000
                ):
                    raise ValueError("unexpected PCM format")
                duration = audio.getnframes() / 16000
                if duration > MAX_SECONDS:
                    raise SpeechError(
                        "too_long", "Запись длиннее 60 секунд. Разделите её на части."
                    )
                if duration < 0.15:
                    raise SpeechError(
                        "invalid_audio", "Запись слишком короткая. Произнесите фразу ещё раз."
                    )
                samples = array("h", audio.readframes(audio.getnframes()))
                if sys.byteorder != "little":
                    samples.byteswap()
                if not samples or max(map(abs, samples)) < 8:
                    raise SpeechError(
                        "invalid_audio", "В записи не слышно сигнала. Проверьте микрофон."
                    )
        except (OSError, ValueError, EOFError, wave.Error) as exc:
            raise SpeechError(
                "invalid_audio", "Не удалось прочитать запись. Запишите фразу ещё раз."
            ) from exc
        prefix = folder / "transcript"
        self._run(
            [
                str(self.binary),
                "--model",
                str(self.model),
                "--file",
                str(wav_path),
                "--language",
                language,
                "--threads",
                str(min(4, os.cpu_count() or 1)),
                "--processors",
                "1",
                "--output-json",
                "--output-file",
                str(prefix),
                "--no-prints",
                "--suppress-nst",
            ],
            cwd=folder,
            timeout=180,
            code="transcription_failed",
        )
        output = prefix.with_suffix(".json")
        try:
            if output.stat().st_size > 256 * 1024:
                raise ValueError("oversized transcript")
            result = json.loads(output.read_text(encoding="utf-8"))
            segments = result["transcription"]
            if not isinstance(segments, list) or any(
                not isinstance(s.get("text"), str) for s in segments
            ):
                raise ValueError("invalid transcript")
            text = "".join(segment["text"] for segment in segments).strip()
            if not text or len(text) > MAX_TEXT:
                raise ValueError("empty or oversized transcript")
            detected = result["result"]["language"]
            if not isinstance(detected, str) or len(detected) > 20:
                raise ValueError("invalid detected language")
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise SpeechError(
                "transcription_failed", "Речь не распознана. Попробуйте ещё раз или введите текст."
            ) from exc
        return {
            "text": text,
            "language": detected,
            "duration_seconds": round(duration, 3),
            "backend": "whisper.cpp",
            "model": MODEL,
            "evidence_policy": "transcript_only",
        }


_service = LocalSpeech()


def status() -> dict:
    return _service.status()


def setup(progress_callback: Callable[[str], None] | None = None) -> dict:
    return _service.setup(progress_callback)


def transcribe_bytes(data: bytes, content_type: str, *, language: str = "auto") -> dict:
    return _service.transcribe_bytes(data, content_type, language=language)


def cancel_active() -> None:
    _service.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("setup")
    transcribe = sub.add_parser("transcribe")
    transcribe.add_argument("file", type=Path)
    transcribe.add_argument("--language", choices=("auto", "ru", "en"), default="auto")
    transcribe.add_argument("--mime-type", default="audio/wav")
    args = parser.parse_args()
    try:
        if args.command == "setup":
            result = setup(lambda stage: print(stage, file=sys.stderr))
        elif args.command == "status":
            result = status()
        else:
            if args.file.stat().st_size > MAX_BYTES:
                raise SpeechError("too_large", "Запись превышает 12 МиБ.")
            result = transcribe_bytes(
                args.file.read_bytes(), args.mime_type, language=args.language
            )
        print(json.dumps(result, ensure_ascii=False))
    except (SpeechError, OSError) as exc:
        print(
            json.dumps(
                {"error": str(exc), "code": getattr(exc, "code", "unavailable")}, ensure_ascii=False
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
