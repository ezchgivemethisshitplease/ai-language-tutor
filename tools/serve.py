#!/usr/bin/env python3
"""Loopback-only browser activities. Run with the project's virtual environment.

python tools/serve.py [port|status|stop|selfcheck]
The local service is single-user and is not an internet deployment server.
"""

import hashlib
import json
import mimetypes
import os
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parent))
import activity
import backup
import srs
import storage
import tts

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

    def _bytes(self, path, content_type):
        if not path.is_file():
            return self._json({"error": "not found"}, 404)
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        # Avoid SimpleHTTPRequestHandler bypassing the static allowlist.
        self._json({"error": "method not supported"}, 405)

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
            if directory is None or self.headers.get("X-Tutor-Namespace") != namespace(directory):
                return self._json({"error": "learner changed; reload before submitting"}, 409)
        except (OSError, ValueError):
            return self._json({"error": "invalid learner path"}, 409)
        if self.headers.get_content_type() != "application/json":
            return self._json({"error": "application/json required"}, 415)
        raw_length = self.headers.get("Content-Length", "")
        if not raw_length.isdecimal() or not 0 < int(raw_length) <= MAX_BODY:
            return self._json({"error": "invalid request size"}, 413)
        try:
            body = storage.decode(self.rfile.read(int(raw_length)))
            if not isinstance(body, dict):
                raise ValueError("object required")
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


def create_server(port=0):
    server = TutorServer(("127.0.0.1", port), Handler)
    server.shutdown_token = secrets.token_urlsafe(32)
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
    # Coding-agent pipes use an explicit UTF-8 text contract.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    command = sys.argv[1] if len(sys.argv) > 1 else None
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
    running = server_status()
    if running:
        print(f"server already running on http://localhost:{running['port']}")
        return
    # Do not silently overwrite a corrupt/stale control file: explicit stop or cleanup is needed.
    if CONTROL.exists():
        raise SystemExit(
            "stale/corrupt control file: inspect student/.serve.json before removing it"
        )
    server = create_server(int(command) if command else 8765)
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
        f"serving apps/ on http://localhost:{server.server_address[1]} — python tools/serve.py stop",
        flush=True,
    )
    try:
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
