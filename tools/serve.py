#!/usr/bin/env python3
"""Loopback-only browser activities. Run with the project's virtual environment.

python tools/serve.py [port|status|stop|selfcheck]
The local service is single-user and is not an internet deployment server.
"""

import hashlib
import argparse
import json
import mimetypes
import os
import re
import secrets
import sys
import threading
import time
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parent))
import activity
import backup
import srs
import speech_service
import storage
import tts
import web_tutor

ROOT = Path(__file__).resolve().parent.parent
STUDENT = srs.STUDENT
APPS = ROOT / "apps"
CONTROL = STUDENT / ".serve.json"


def backup_status():
    # Mutation handlers call this only after releasing the data transaction.
    # An offline backup volume does not invalidate a saved browser response.
    return backup.maybe_automatic_backup(STUDENT)


def namespace(directory=None):
    resolved = directory if directory is not None else lang_dir()
    active = resolved.name if resolved is not None else "uninitialized"
    return hashlib.sha256(f"{STUDENT.resolve()}:{active}".encode()).hexdigest()[:16]


MAX_BODY = 256 * 1024
MAX_AUDIO_BODY = 12 * 1024 * 1024
read_json = storage.load


def read_control():
    try:
        data = read_json(CONTROL, None)
    except (OSError, ValueError):
        return None
    if (
        not isinstance(data, dict)
        or type(data.get("port")) is not int
        or not isinstance(data.get("token"), str)
    ):
        return None
    return data


def control_request(action, method="GET", timeout=2):
    data = read_control()
    if data is None:
        raise RuntimeError("no server control file")
    url = f"http://127.0.0.1:{data['port']}/api/{action}"
    request = urllib.request.Request(url, method=method, headers={"X-Tutor-Token": data["token"]})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def server_status():
    try:
        result = control_request("health")
    except (OSError, RuntimeError, ValueError):
        return None
    return read_control() if result.get("ok") else None


def stop_server():
    if read_control() is None:
        print("server not running")
        return 0
    try:
        control_request("shutdown", method="POST")
    except (OSError, RuntimeError, ValueError):
        print("server did not respond; control file kept", file=sys.stderr)
        return 1
    for _ in range(40):
        if not CONTROL.exists():
            print("server stopped")
            return 0
        time.sleep(0.05)
    print("shutdown requested but not confirmed", file=sys.stderr)
    return 1


def write_event(app, payload):
    # Server metadata cannot be overridden by imported learner content.
    out = {**payload, "app": app, "at": datetime.now(timezone.utc).isoformat()}
    storage.save(STUDENT / f".event-{app}.json", out)


def lang_dir():
    try:
        if (
            not STUDENT.exists()
            or not (STUDENT / "active.txt").exists()
            and not any(p.is_dir() and not p.name.startswith(".") for p in STUDENT.iterdir())
        ):
            return None
        return srs.lang_dir()
    except SystemExit:
        return None


def due_cards(limit=None):
    d = lang_dir()
    cards = srs.due_cards(d / "cards.json") if d else []
    return cards[:limit] if limit is not None else cards


def progress_payload():
    d = lang_dir()
    if d is None:
        return {
            "streak": 0,
            "language": None,
            "level": None,
            "unit": 1,
            "levelPct": 0,
            "knownWords": 0,
            "dueCount": 0,
            "topErrors": [],
            "history": [0],
        }
    p = read_json(d / "progress.json", {"history": []})
    if not isinstance(p, dict):
        raise ValueError("invalid legacy progress")
    known_path = d / "known_words.txt"
    known = (
        len(
            {
                line.strip().casefold()
                for line in known_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            }
        )
        if known_path.exists()
        else 0
    )
    errors: list[dict[str, Any]] = []
    err_path = d / "errors.md"
    if err_path.exists():
        for line in err_path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^(\d+)[x×]\s*\|\s*([^|]+?)\s*\|\s*(.+)$", line.strip())
            if match:
                errors.append({"count": int(match[1]), "label": match[2], "example": match[3]})
    learner = read_json(d / "learner.json", None)
    level = p.get("level")
    mastered_units = 0
    if learner:
        import learning

        learning.validate_state(learner)
        level = learner["proficiency"]["working_level"]
        mastered_units = sum(
            value.get("mastered", False)
            for key, value in learner["estimates"]["skills"].items()
            if key.startswith(level.lower() + "-")
        )
        errors = [
            {"count": value.get("confirmed_count", 0), "label": key, "example": ""}
            for key, value in learner["errors"].items()
            if value.get("confirmed_count", 0) > 0
        ]
    errors.sort(key=lambda value: -value["count"])
    history = [entry["known_words"] for entry in p.get("history", []) if "known_words" in entry]
    return {
        "streak": p.get("streak", 0),
        "language": d.name,
        "level": level,
        "unit": p.get("unit", 1),
        "levelPct": round(mastered_units / 12 * 100),
        "masteredUnits": mastered_units,
        "knownWords": known,
        "dueCount": len(due_cards()),
        "topErrors": errors[:3],
        "history": history or [known],
        "calibrated": False,
        "legacyVocabularyUnverified": True,
    }


class TutorServer(ThreadingHTTPServer):
    shutdown_token: str
    tutor: web_tutor.WebTutor
    speech: speech_service.SpeechService

    def server_close(self):
        self.speech.close()
        self.tutor.close()
        super().server_close()


class Handler(SimpleHTTPRequestHandler):
    server: TutorServer

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(APPS), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
        )
        super().end_headers()

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _origin_ok(self):
        port = cast(tuple, self.server.server_address)[1]
        hosts = {f"localhost:{port}", f"127.0.0.1:{port}"}
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        return (
            host in hosts
            and self.headers.get("Sec-Fetch-Site") not in {"cross-site"}
            and (origin is None or origin == f"http://{host}")
        )

    def _authorized(self, query):
        token = self.headers.get("X-Tutor-Token", "")
        if not token:
            token = (urllib.parse.parse_qs(query).get("token") or [""])[0]
        return secrets.compare_digest(token, self.server.shutdown_token)

    def _activity(self, kind):
        filename = {"quiz": "quiz", "text": "reading", "dictation": "dictation"}[kind]
        data = read_json(STUDENT / f"{filename}-current.json", None)
        return activity.validate(kind, data) if data is not None else None

    def do_GET(self):
        if not self._origin_ok():
            return self._json({"error": "forbidden origin or host"}, 403)
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        try:
            if route == "/api/session":
                return self._json(
                    {"token": self.server.shutdown_token, "locale": "ru", "namespace": namespace()}
                )
            if route == "/api/health":
                return self._json(
                    {"ok": True} if self._authorized(parsed.query) else {"error": "forbidden"},
                    200 if self._authorized(parsed.query) else 403,
                )
            if route == "/api/speech/status":
                if not self._authorized(parsed.query):
                    return self._json({"error": "token required"}, 403)
                return self._json(self.server.speech.status())
            if route.startswith("/api/web/"):
                if not self._authorized(parsed.query):
                    return self._json({"error": "token required"}, 403)
                query = urllib.parse.parse_qs(parsed.query)
                if route == "/api/web/status":
                    return self._json(self.server.tutor.status())
                if route == "/api/web/conversation":
                    return self._json(self.server.tutor.conversation((query.get("id") or [""])[0]))
                if route == "/api/web/events":
                    return self._json(
                        self.server.tutor.events(
                            (query.get("conversation_id") or [""])[0],
                            int((query.get("after") or ["0"])[0]),
                        )
                    )
                if route == "/api/web/backup":
                    # No caller-supplied paths. The archive excludes the isolated Codex auth store.
                    with tempfile.TemporaryDirectory(prefix="tutor-download-") as temporary:
                        destination = Path(temporary) / "learner.zip"
                        backup.create_backup(STUDENT, destination)
                        return self._bytes(destination, "application/zip", "tutor-backup.zip")
                return self._json({"error": "unknown endpoint"}, 404)
            if route == "/api/tts":
                if not self._authorized(parsed.query):
                    return self._json({"error": "token required"}, 403)
                text = (urllib.parse.parse_qs(parsed.query).get("text") or [""])[0]
                if not text.strip() or len(text) > 2000:
                    raise ValueError("TTS needs 1–2000 characters")
                path = tts.synth(text)
                if path is None:
                    self.send_response(204)
                    self.end_headers()
                    return
                return self._bytes(path, mimetypes.guess_type(path)[0] or "audio/mpeg")
            if route == "/api/deck":
                return self._json({"cards": due_cards(30), "totalDue": len(due_cards())})
            if route == "/api/progress":
                return self._json(progress_payload())
            if route in {"/api/quiz", "/api/text", "/api/dictation"}:
                data = self._activity(route.split("/")[-1])
                return self._json(
                    {**data, "activity_id": activity.identity(data)}
                    if data
                    else {"error": "activity not prepared"},
                    200 if data else 404,
                )
            if route.startswith("/api/img/"):
                d = lang_dir()
                name = urllib.parse.unquote(route[len("/api/img/") :])
                if not d or Path(name).name != name or not name:
                    raise ValueError("invalid image name")
                path = d / "img" / name
                if not path.resolve().is_relative_to((d / "img").resolve()) or path.is_symlink():
                    raise ValueError("invalid image path")
                return self._bytes(
                    path, mimetypes.guess_type(path)[0] or "application/octet-stream"
                )
            if route.startswith("/api/"):
                return self._json({"error": "unknown endpoint"}, 404)
            if route == "/":
                return self._bytes(APPS / "index.html", "text/html; charset=utf-8")
            # Do not expose directory listings or follow static symlinks outside apps/.
            path = (APPS / urllib.parse.unquote(route).lstrip("/")).resolve()
            if not path.is_relative_to(APPS.resolve()) or path.suffix not in {
                ".html",
                ".css",
                ".js",
            }:
                return self._json({"error": "not found"}, 404)
            return super().do_GET()
        except (ValueError, KeyError, TypeError):
            return self._json({"error": "invalid or corrupt data; validate before continuing"}, 409)
        except (OSError, RuntimeError):
            return self._json(
                {"error": "operation failed; data retained; check local configuration"}, 503
            )

    def _bytes(self, path, content_type, download=None):
        if not path.is_file():
            return self._json({"error": "not found"}, 404)
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{download}"')
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        # Avoid SimpleHTTPRequestHandler bypassing the static allowlist.
        self._json({"error": "method not supported"}, 405)

    def _transcribe(self):
        length = self.headers.get("Content-Length", "")
        if (
            self.headers.get("Transfer-Encoding")
            or not length.isdecimal()
            or not 0 < int(length) <= MAX_AUDIO_BODY
        ):
            return self._json(
                {"error": "too_large", "message": "Запись должна быть не больше 12 МиБ."}, 413
            )
        previous_timeout = self.connection.gettimeout()
        try:
            self.connection.settimeout(30)
            data = self.rfile.read(int(length))
            if len(data) != int(length):
                raise ValueError("incomplete audio upload")
            self.connection.settimeout(previous_timeout)
            result = self.server.speech.transcribe(
                data,
                self.headers.get("Content-Type", ""),
                self.headers.get("X-Speech-Language", "auto"),
            )
            return self._json(result)
        except (TimeoutError, ConnectionError):
            return self._json(
                {"error": "timeout", "message": "Передача записи прервалась. Повторите отправку."},
                408,
            )
        except Exception as error:
            statuses = {
                "unavailable": 503,
                "busy": 409,
                "invalid_audio": 422,
                "too_large": 413,
                "too_long": 422,
                "timeout": 504,
                "setup_failed": 503,
                "transcription_failed": 422,
                "canceled": 409,
            }
            code = getattr(error, "code", None)
            message = getattr(error, "message", None)
            if (
                isinstance(code, str)
                and code in statuses
                and isinstance(message, str)
                and len(message) <= 1000
            ):
                return self._json({"error": code, "message": message}, statuses[code])
            if isinstance(error, ValueError):
                return self._json(
                    {
                        "error": "invalid_audio",
                        "message": "Не удалось прочитать запись или язык распознавания.",
                    },
                    422,
                )
            return self._json(
                {
                    "error": "unavailable",
                    "message": "Распознавание пока недоступно. Проверьте подготовку Whisper. Текстовый чат работает.",
                },
                503,
            )
        finally:
            self.connection.settimeout(previous_timeout)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if not self._origin_ok() or not self._authorized(parsed.query):
            return self._json({"error": "same-origin session token required"}, 403)
        if parsed.path == "/api/shutdown":
            self._json({"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        try:
            directory = lang_dir()
            if (
                directory is None and not parsed.path.startswith(("/api/web/", "/api/speech/"))
            ) or self.headers.get("X-Tutor-Namespace") != namespace(directory):
                return self._json({"error": "learner changed; reload before submitting"}, 409)
        except (OSError, ValueError):
            return self._json({"error": "invalid learner path"}, 409)
        if parsed.path == "/api/speech/transcribe":
            return self._transcribe()
        if self.headers.get_content_type() != "application/json":
            return self._json({"error": "application/json required"}, 415)
        raw_length = self.headers.get("Content-Length", "")
        if not raw_length.isdecimal() or not 0 < int(raw_length) <= MAX_BODY:
            return self._json({"error": "invalid request size"}, 413)
        try:
            body = storage.decode(self.rfile.read(int(raw_length)))
            if not isinstance(body, dict):
                raise ValueError("object required")
            if parsed.path == "/api/speech/setup":
                if body:
                    raise ValueError("speech setup takes no options")
                return self._json(self.server.speech.setup(), 202)
            if parsed.path.startswith("/api/web/"):
                route = parsed.path.removeprefix("/api/web/")
                tutor = self.server.tutor
                if route == "setup":
                    return self._json(tutor.setup(body))
                if route == "login":
                    return self._json(tutor.login())
                if route == "chat":
                    return self._json(tutor.chat(body))
                if route == "interrupt":
                    return self._json(tutor.interrupt(body.get("conversation_id")))
                if route == "session":
                    return self._json(
                        tutor.lesson(body.get("action"), body.get("allow_incomplete", False))
                    )
                return self._json({"error": "unknown endpoint"}, 404)
            if parsed.path == "/api/deck":
                d = directory
                if not d:
                    raise ValueError("no learner")
                batch_id = activity.text(body.get("batch_id"), "batch_id", 128)
                receipt = srs.apply_reviews(
                    d / "cards.json", body.get("results"), batch_id=batch_id
                )
                return self._json({"ok": True, "receipt": receipt, "backup": backup_status()})
            if parsed.path in {"/api/quiz", "/api/text", "/api/deck/complete"}:
                kind = (
                    "flashcards"
                    if parsed.path.endswith("/complete")
                    else parsed.path.split("/")[-1]
                )
                batch_id = activity.text(body.get("batch_id"), "batch_id", 128)
                # Lock order is cards before activity-results, matching export_bundle.
                known = set()
                if kind == "flashcards":
                    deck = read_json(directory / "cards.json", {"cards": []})
                    known = {
                        r["review_id"]
                        for card in deck["cards"]
                        for r in card.get("review_history", [])
                    }
                with storage.transaction(
                    STUDENT / "activity-results.json", {"receipts": {}}
                ) as store:
                    fingerprint = activity.identity(body)
                    previous = store["receipts"].get(batch_id)
                    if previous:
                        if previous["fingerprint"] != fingerprint or previous["activity"] != kind:
                            raise ValueError("batch ID reused with different data")
                        result = previous["result"]
                    else:
                        if kind == "flashcards":
                            ids = body.get("review_ids")
                            if (
                                not isinstance(ids, list)
                                or len(ids) > 300
                                or any(not isinstance(rid, str) for rid in ids)
                            ):
                                raise ValueError("invalid review IDs")
                            if not set(ids) <= known or len(ids) != len(set(ids)):
                                raise ValueError("reviews were not saved")
                            result = {"completed": True, "reviews": len(ids)}
                        else:
                            data = self._activity(kind)
                            if data is None or body.get("activity_id") != activity.identity(data):
                                raise ValueError("stale activity")
                            if kind == "quiz":
                                result = activity.score_quiz(data, body.get("answers"))
                            else:
                                field = "addWord" if "addWord" in body else "askWord"
                                word = activity.text(body.get(field), "word", 100).lower()
                                if field == "addWord" and word not in data.get("glossary", {}):
                                    raise ValueError("word outside glossary")
                                if field == "askWord" and word not in {
                                    w.lower()
                                    for w in re.findall(r"[^\W\d_]+", " ".join(data["paragraphs"]))
                                }:
                                    raise ValueError("word outside reading")
                                result = {field: word, "title": data["title"]}
                        store["receipts"][batch_id] = {
                            "fingerprint": fingerprint,
                            "activity": kind,
                            "activity_id": body.get("activity_id"),
                            "result": result,
                            "at": datetime.now(timezone.utc).isoformat(),
                        }
                write_event(
                    "reader" if kind == "text" else kind,
                    {"batch_id": batch_id, "activity_id": body.get("activity_id"), **result},
                )
                return self._json({"ok": True, **result, "backup": backup_status()})
            return self._json({"error": "unknown endpoint"}, 404)
        except (ValueError, KeyError, TypeError):
            return self._json({"error": "invalid result or corrupt data; nothing graded"}, 400)
        except (OSError, RuntimeError):
            return self._json({"error": "save not confirmed; retry with the same batch ID"}, 503)

    def log_message(self, fmt, *args):
        pass  # No learner content, TTS text, or tokens in request logs.


def create_server(port=0, tutor=None, speech=None):
    server = TutorServer(("127.0.0.1", port), Handler)
    server.shutdown_token = secrets.token_urlsafe(32)
    server.tutor = tutor or web_tutor.WebTutor(STUDENT)
    server.speech = speech or speech_service.SpeechService()
    return server


def selfcheck():
    server = create_server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        headers = {"X-Tutor-Token": server.shutdown_token}
        with urllib.request.urlopen(
            urllib.request.Request(base + "/api/health", headers=headers), timeout=2
        ) as r:
            assert json.loads(r.read()) == {"ok": True}
        with urllib.request.urlopen(
            urllib.request.Request(base + "/api/shutdown", headers=headers, method="POST"),
            timeout=2,
        ) as r:
            assert json.loads(r.read()) == {"ok": True}
        thread.join(timeout=2)
        assert not thread.is_alive()
    finally:
        server.shutdown()
        server.server_close()
    print("server selfcheck OK")


def main():
    import fcntl

    # Coding-agent pipes use an explicit UTF-8 text contract.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", help="port, status, stop or selfcheck")
    parser.add_argument("--open", action="store_true", help="open the local web tutor")
    args = parser.parse_args()
    command = args.command
    if command == "stop":
        raise SystemExit(stop_server())
    if command == "status":
        data = server_status()
        print(
            f"server running on http://localhost:{data['port']}" if data else "server not running"
        )
        raise SystemExit(0 if data else 1)
    if command == "selfcheck":
        return selfcheck()
    STUDENT.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Keep this inode for the entire server lifetime, including control publication/cleanup.
    # Unlinking it would let a later process lock a different inode and start a second writer.
    descriptor = os.open(STUDENT / ".serve.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "a") as singleton:
        try:
            fcntl.flock(singleton, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            # The owner may still be publishing its control file. Bound both file-lock
            # acquisition and HTTP health checks; never wait for the serving lock itself.
            deadline = time.monotonic() + 1.25
            while time.monotonic() < deadline:
                try:
                    with storage.locked(CONTROL, timeout=0.05):
                        running = read_control()
                    if running:
                        request = urllib.request.Request(
                            f"http://127.0.0.1:{running['port']}/api/health",
                            headers={"X-Tutor-Token": running["token"]},
                        )
                        remaining = max(0.01, deadline - time.monotonic())
                        with urllib.request.urlopen(
                            request, timeout=min(0.15, remaining)
                        ) as response:
                            healthy = json.loads(response.read()).get("ok") is True
                        if healthy:
                            print(f"server already running on http://localhost:{running['port']}")
                            if args.open:
                                webbrowser.open(f"http://localhost:{running['port']}/")
                            return
                except (OSError, RuntimeError, ValueError, AttributeError):
                    pass
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
            raise SystemExit("server startup or shutdown in progress; retry shortly") from None

        running = server_status()
        if running:
            print(f"server already running on http://localhost:{running['port']}")
            if args.open:
                webbrowser.open(f"http://localhost:{running['port']}/")
            return
        # Do not silently overwrite a corrupt/stale control file.
        if CONTROL.exists():
            raise SystemExit(
                "stale/corrupt control file: inspect student/.serve.json before removing it"
            )
        server = create_server(int(command) if command else 8765)
        try:
            storage.save(
                CONTROL,
                {
                    "pid": os.getpid(),
                    "port": server.server_address[1],
                    "token": server.shutdown_token,
                    "root": str(ROOT),
                },
            )
            print(
                f"AI Language Tutor: http://localhost:{server.server_address[1]}/ — python tools/serve.py stop",
                flush=True,
            )
            if args.open:
                webbrowser.open(f"http://localhost:{server.server_address[1]}/")
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
            current = read_control()
            if current and secrets.compare_digest(current["token"], server.shutdown_token):
                CONTROL.unlink(missing_ok=True)
                CONTROL.with_suffix(CONTROL.suffix + ".bak").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
