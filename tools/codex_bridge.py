"""Bounded local client for the official Codex 0.163.0 app-server JSONL protocol.

The child owns ChatGPT login and token storage. This module never opens auth
files, exports credentials, invokes Desktop or offers a generic browser RPC.
An isolated CODEX_HOME and a deny-by-default named permissions profile prevent
personal MCP/hooks/config inheritance and restrict agent filesystem access.

Protocol/config contracts were inspected from the generated experimental schema
and openai/codex rust-v0.163.0 config.schema.json/permissions.rs. This release
has no --ignore-user-config or readOnly.access field; named permissions provide
its supported restricted-read alternative. Analytics stays disabled.
https://github.com/openai/codex/blob/rust-v0.163.0/codex-rs/core/config/permissions.rs
https://github.com/openai/codex/blob/rust-v0.163.0/codex-rs/core/config.schema.json
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import copy
import json
import os
from pathlib import Path
import queue
import re
import select
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Callable
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
CODEX_VERSION = "0.163.0"
MAX_FRAME_BYTES = 2 * 1024 * 1024
MAX_REQUEST_BYTES = 512 * 1024
MAX_TOOL_BYTES = 128 * 1024
PERMISSIONS_PROFILE = "tutor_readonly"
DISABLED_FEATURES = (
    "shell_tool",
    "unified_exec",
    "view_image",
    "hooks",
    "apps",
    "plugins",
    "remote_plugin",
    "computer_use",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "multi_agent",
    "multi_agent_v2",
    "image_generation",
    "code_mode",
    "code_mode_host",
    "memories",
    "memory_tool",
    "skill_search",
    "skill_mcp_dependency_install",
    "daemon_auto_start",
    "in_app_browser",
    "in_app_voice",
    "remote_control",
)
_ALLOWED_ENV = {
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
    "TMPDIR",
    "TMP",
    "TEMP",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "https_proxy",
    "http_proxy",
    "all_proxy",
    "no_proxy",
}
_SECRET_KEYS = {
    "email",
    "accountid",
    "chatgptaccountid",
    "accesstoken",
    "refreshtoken",
    "idtoken",
    "apikey",
    "authorization",
    "cookie",
    "cookies",
    "clientsecret",
    "workspacerouting",
    "authtoken",
    "password",
    "secret",
    "token",
    "authurl",
    "verificationurl",
    "credentials",
    "client_secret",
}
_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
)


class BridgeError(RuntimeError):
    """Safe, content-free transport/configuration failure."""


class BridgeTimeout(BridgeError):
    """A timed-out mutation may have run; callers must reconcile, not retry blindly."""


@dataclass
class _Pending:
    method: str
    event: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: BridgeError | None = None


def _text(value: Any, name: str, limit: int = 200000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{name} must be nonempty bounded text")
    return value


def _identifier(value: Any, name: str) -> str:
    value = _text(value, name, 200)
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", value):
        raise ValueError(f"invalid {name}")
    return value


def _redact(value: Any, depth: int = 0) -> Any:
    """Redact structured credentials/account identity before any event leaves us."""
    if depth > 24:
        return "[truncated]"
    if isinstance(value, dict):
        return {
            key: _redact(child, depth + 1)
            for key, child in value.items()
            if re.sub(r"[^a-z]", "", key.lower()) not in _SECRET_KEYS
        }
    if isinstance(value, list):
        return [_redact(child, depth + 1) for child in value]
    if isinstance(value, str):
        for pattern in _SECRET_PATTERNS:
            value = pattern.sub("[redacted]", value)
        return value
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate protocol key")
        result[key] = value
    return result


def _decode(raw: bytes) -> dict:
    value = json.loads(
        raw,
        object_pairs_hook=_unique_object,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")),
    )
    if not isinstance(value, dict):
        raise ValueError("protocol frame must be an object")
    return value


def select_binary(binary: str | Path | None = None) -> Path:
    selected = binary or os.environ.get("TUTOR_CODEX_BIN") or ROOT / "node_modules/.bin/codex"
    path = Path(selected).expanduser().absolute()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise BridgeError(
            "Codex runtime unavailable; run npm ci or set TUTOR_CODEX_BIN to Codex 0.163.0"
        )
    return path


class CodexBridge:
    """One independent stdio process; callbacks run outside the protocol reader.

    tool_callback receives DynamicToolCallParams and must return the official
    {contentItems: [...], success: bool} shape. Only explicitly allowed tools and
    threads started/resumed through this instance may reach that callback.
    event_callback receives (method, redacted_params). It must remain quick;
    bounded queues report dropped events explicitly. The controller owns durable
    chat/event history and all business rules, including assessment provenance.
    """

    def __init__(
        self,
        *,
        cwd: str | Path,
        codex_home: str | Path | None = None,
        binary: str | Path | None = None,
        event_callback: Callable[[str, dict], None] | None = None,
        tool_callback: Callable[[dict], dict] | None = None,
        allowed_tools: tuple[str, ...] = ("tutor",),
        request_timeout: float = 30,
        tool_timeout: float = 30,
        max_events: int = 256,
    ):
        if sys.platform not in {"darwin", "linux"}:
            raise BridgeError("The local Codex tutor supports macOS and Linux")
        if not 0.05 <= request_timeout <= 300 or not 0.05 <= tool_timeout <= 300:
            raise ValueError("timeouts must be between 0.05 and 300 seconds")
        if type(max_events) is not int or not 2 <= max_events <= 4096:
            raise ValueError("max_events must be an integer from 2 to 4096")
        self.cwd = Path(cwd).expanduser().absolute()
        self.codex_home = Path(codex_home or ROOT / ".runtime/codex-home").expanduser().absolute()
        self._binary_choice = binary
        self.event_callback = event_callback
        self.tool_callback = tool_callback
        self.allowed_tools = {_identifier(name, "tool name") for name in allowed_tools}
        self.request_timeout = float(request_timeout)
        self.tool_timeout = float(tool_timeout)
        self._events: deque[dict] = deque(maxlen=max_events)
        self._callback_events: deque[dict] = deque(maxlen=max_events)
        self._condition = threading.Condition()
        self._pending_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._start_lock = threading.RLock()
        self._pending: dict[int, _Pending] = {}
        self._threads: set[str] = set()
        self._request_id = 0
        self._process: subprocess.Popen[bytes] | None = None
        self._workers: list[threading.Thread] = []
        self._server_requests: queue.Queue[dict] = queue.Queue(maxsize=16)
        self._tool_slots = threading.BoundedSemaphore(2)
        self._closed = threading.Event()
        self._failure: BridgeError | None = None
        self._initialized = False
        self._events_dropped = 0
        self._callback_dropped = 0
        self._stderr_bytes = 0
        self._callback_errors = 0

    def __enter__(self) -> CodexBridge:
        return self.start()

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _environment(self) -> dict[str, str]:
        environment = {key: value for key, value in os.environ.items() if key in _ALLOWED_ENV}
        # Configure only the child. Never modify the user's global environment.
        environment["CODEX_HOME"] = str(self.codex_home)
        return environment

    def _command(self, binary: Path) -> list[str]:
        filesystem = json.dumps(
            {":minimal": "read", str(self.cwd.resolve()): "read"}, ensure_ascii=False
        )
        # JSON inline objects use ':'; TOML inline objects require '='.
        filesystem = (
            "{"
            + ",".join(
                f"{json.dumps(key)}={json.dumps(value)}"
                for key, value in json.loads(filesystem).items()
            )
            + "}"
        )
        command = [str(binary), "app-server", "--listen", "stdio://", "--strict-config"]
        config = [
            'approval_policy="never"',
            f'default_permissions="{PERMISSIONS_PROFILE}"',
            f"permissions.{PERMISSIONS_PROFILE}.filesystem={filesystem}",
            f"permissions.{PERMISSIONS_PROFILE}.network.enabled=false",
            'web_search="disabled"',
            "analytics.enabled=false",
            'shell_environment_policy.inherit="none"',
            "features.skip_host_skill_discovery=true",
            "project_doc_max_bytes=0",
        ]
        for value in config:
            command.extend(["-c", value])
        for feature in DISABLED_FEATURES:
            command.extend(["--disable", feature])
        return command

    def start(self) -> CodexBridge:
        with self._start_lock:
            if self._initialized and not self._closed.is_set():
                return self
            if self._process is not None or self._closed.is_set():
                raise BridgeError("A closed bridge cannot be restarted; create a new instance")
            for directory in (self.cwd, self.codex_home):
                if directory.is_symlink():
                    raise BridgeError("Codex runtime directories must not be symlinks")
            if (
                self.cwd.resolve() == self.codex_home.resolve()
                or self.cwd.resolve() in self.codex_home.resolve().parents
            ):
                raise BridgeError("Codex auth storage must be outside the readable tutor workspace")
            personal = (
                Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
                .expanduser()
                .resolve()
            )
            if self.codex_home.resolve() == personal:
                raise BridgeError(
                    "Use an isolated Codex home; personal config and auth are not imported"
                )
            # Validate before touching either path, including its permissions.
            for directory in (self.cwd, self.codex_home):
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                os.chmod(directory, 0o700)
            binary = select_binary(self._binary_choice)
            try:
                version = subprocess.run(
                    [str(binary), "--version"],
                    capture_output=True,
                    timeout=10,
                    check=True,
                    env=self._environment(),
                )
                if (
                    len(version.stdout) > 4096
                    or version.stdout.decode("utf-8", errors="replace").strip()
                    != f"codex-cli {CODEX_VERSION}"
                ):
                    raise BridgeError("Codex runtime must be exactly 0.163.0")
                self._process = subprocess.Popen(
                    self._command(binary),
                    cwd=self.cwd,
                    env=self._environment(),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=0,
                    start_new_session=True,
                )
                assert self._process.stdin is not None
                os.set_blocking(self._process.stdin.fileno(), False)
            except (OSError, subprocess.SubprocessError) as exc:
                self.close()
                raise BridgeError("Could not start the pinned Codex runtime") from exc
            for name, target in (
                ("reader", self._read_loop),
                ("stderr", self._drain_stderr),
                ("tools", self._tool_loop),
                ("events", self._callback_loop),
            ):
                worker = threading.Thread(target=target, daemon=True, name=f"tutor-codex-{name}")
                self._workers.append(worker)
                worker.start()
            try:
                self._request(
                    "initialize",
                    {
                        "clientInfo": {
                            "name": "ai_language_tutor",
                            "title": "AI Language Tutor",
                            "version": "1.0.0",
                        },
                        "capabilities": {"experimentalApi": True},
                    },
                    allow_uninitialized=True,
                )
                self._send({"method": "initialized", "params": {}})
                self._initialized = True
            except BridgeError:
                self.close()
                raise
            return self

    def _send(self, message: dict) -> None:
        raw = (
            json.dumps(message, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
        ).encode()
        if len(raw) > MAX_REQUEST_BYTES:
            raise ValueError("Codex request exceeds the bounded protocol limit")
        deadline = time.monotonic() + self.request_timeout
        if not self._write_lock.acquire(timeout=self.request_timeout):
            raise BridgeTimeout("Codex write timed out; reconcile before retrying a mutation")
        try:
            process = self._process
            if self._closed.is_set() or process is None or process.stdin is None:
                raise self._failure or BridgeError("Codex bridge is closed")
            fd = process.stdin.fileno()
            offset = 0
            while offset < len(raw):
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([], [fd], [], max(0, remaining))[1]:
                    raise BridgeTimeout(
                        "Codex write timed out; reconcile before retrying a mutation"
                    )
                try:
                    offset += os.write(fd, raw[offset : offset + 65536])
                except BlockingIOError:
                    continue
        except (OSError, ValueError) as exc:
            raise BridgeError("Codex transport is unavailable") from exc
        finally:
            self._write_lock.release()

    def _request(self, method: str, params: dict, *, allow_uninitialized: bool = False) -> Any:
        if not allow_uninitialized and not self._initialized:
            raise BridgeError("Start the Codex bridge before requesting work")
        with self._pending_lock:
            if self._closed.is_set():
                raise self._failure or BridgeError("Codex bridge is closed")
            if len(self._pending) >= 32:
                raise BridgeError("Too many simultaneous Codex requests")
            self._request_id += 1
            identifier = self._request_id
            pending = _Pending(method)
            self._pending[identifier] = pending
        try:
            self._send({"id": identifier, "method": method, "params": params})
            if not pending.event.wait(self.request_timeout):
                raise BridgeTimeout(
                    f"Codex {method} timed out; reconcile before retrying a mutation"
                )
            if pending.error is not None:
                raise pending.error
            return pending.result
        finally:
            with self._pending_lock:
                self._pending.pop(identifier, None)

    def _read_loop(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        try:
            while not self._closed.is_set():
                raw = self._process.stdout.readline(MAX_FRAME_BYTES + 1)
                if not raw:
                    self._fail(BridgeError("Codex process ended"))
                    return
                if len(raw) > MAX_FRAME_BYTES or not raw.endswith(b"\n"):
                    raise ValueError("oversized or incomplete frame")
                message = _decode(raw)
                method = message.get("method")
                if isinstance(method, str):
                    params = message.get("params", {})
                    if not isinstance(params, dict):
                        raise ValueError("invalid event parameters")
                    if "id" in message:
                        self._server_request(message)
                    else:
                        self._publish(method, params)
                elif "id" in message and type(message["id"]) is int:
                    with self._pending_lock:
                        pending = self._pending.get(message["id"])
                    if pending is not None:
                        if "error" in message:
                            error = message["error"]
                            code = error.get("code") if isinstance(error, dict) else None
                            safe_code = str(code) if type(code) is int else "unknown"
                            pending.error = BridgeError(
                                f"Codex {pending.method} rejected ({safe_code})"
                            )
                        elif "result" in message:
                            pending.result = message["result"]
                        else:
                            pending.error = BridgeError("Codex returned an invalid response")
                        pending.event.set()
                else:
                    raise ValueError("unknown protocol frame")
        except (OSError, ValueError, UnicodeError, RecursionError, BridgeError):
            if not self._closed.is_set():
                self._fail(BridgeError("Codex sent an invalid or unavailable protocol stream"))

    def _drain_stderr(self) -> None:
        assert self._process is not None and self._process.stderr is not None
        try:
            while not self._closed.is_set():
                raw = self._process.stderr.read(4096)
                if not raw:
                    return
                # Drain, count, discard. Auth/debug messages never become logs/events.
                self._stderr_bytes = min(2**63 - 1, self._stderr_bytes + len(raw))
        except (OSError, ValueError):
            pass

    def _publish(self, method: str, params: dict) -> None:
        if method == "account/updated":
            params = {key: params.get(key) for key in ("authMode", "planType")}
        elif method == "account/login/completed":
            params = {
                "loginId": params.get("loginId"),
                "success": params.get("success") is True,
                "error": "Login failed" if params.get("error") else None,
            }
        elif method.startswith("account/"):
            return
        event = {"method": method, "params": _redact(params)}
        with self._condition:
            if len(self._events) == self._events.maxlen:
                self._events_dropped += 1
            self._events.append(copy.deepcopy(event))
            if self.event_callback is not None:
                if len(self._callback_events) == self._callback_events.maxlen:
                    self._callback_dropped += 1
                self._callback_events.append(event)
            self._condition.notify_all()

    def next_event(self, timeout: float = 0) -> dict | None:
        if not 0 <= timeout <= 60:
            raise ValueError("event timeout must be from 0 to 60 seconds")
        deadline = time.monotonic() + timeout
        with self._condition:
            while not self._events and not self._events_dropped and not self._closed.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
            if self._events_dropped:
                dropped = self._events_dropped
                self._events_dropped = 0
                return {"method": "bridge/eventsDropped", "params": {"count": dropped}}
            return self._events.popleft() if self._events else None

    def _callback_loop(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(
                    lambda: bool(self._callback_events) or self._closed.is_set()
                )
                if not self._callback_events:
                    return
                event = self._callback_events.popleft()
                dropped = self._callback_dropped
                self._callback_dropped = 0
            try:
                if self.event_callback is not None:
                    if dropped:
                        self.event_callback("bridge/eventsDropped", {"count": dropped})
                    self.event_callback(event["method"], event["params"])
            except Exception:
                self._callback_errors += 1

    @staticmethod
    def _tool_failure() -> dict:
        return {
            "contentItems": [
                {
                    "type": "inputText",
                    "text": "Tool unavailable or request declined by the local tutor.",
                }
            ],
            "success": False,
        }

    def _server_request(self, message: dict) -> None:
        identifier = message["id"]
        if type(identifier) not in {int, str}:
            raise ValueError("invalid server request id")
        method = message["method"]
        if method == "item/tool/call":
            try:
                self._server_requests.put_nowait(message)
            except queue.Full:
                self._send({"id": identifier, "result": self._tool_failure()})
            return
        result: dict[str, Any]
        if method in {"item/commandExecution/requestApproval", "item/fileChange/requestApproval"}:
            result = {"decision": "decline"}
        elif method in {"execCommandApproval", "applyPatchApproval"}:
            result = {"decision": "abort"}
        elif method == "item/permissions/requestApproval":
            result = {"permissions": {}, "scope": "turn"}
        elif method in {"item/tool/requestUserInput", "tool/requestUserInput"}:
            result = {"answers": {}}
        elif method == "mcpServer/elicitation/request":
            result = {"action": "decline", "content": None}
        else:
            self._send(
                {
                    "id": identifier,
                    "error": {"code": -32601, "message": "Unsupported local tutor request"},
                }
            )
            return
        self._send({"id": identifier, "result": result})

    def _invoke_tool(self, params: dict) -> dict:
        if (
            self.tool_callback is None
            or params.get("threadId") not in self._threads
            or params.get("namespace") not in {None, ""}
            or params.get("tool") not in self.allowed_tools
            or not isinstance(params.get("arguments"), dict)
        ):
            return self._tool_failure()
        for key in ("callId", "threadId", "turnId", "tool"):
            _identifier(params.get(key), key)
        if not self._tool_slots.acquire(blocking=False):
            return self._tool_failure()
        completed = threading.Event()
        results: list[Any] = []

        def invoke() -> None:
            try:
                assert self.tool_callback is not None
                results.append(self.tool_callback(copy.deepcopy(params)))
            except Exception:
                results.append(None)
            finally:
                self._tool_slots.release()
                completed.set()

        threading.Thread(target=invoke, daemon=True, name="tutor-codex-tool-callback").start()
        if not completed.wait(self.tool_timeout) or not results:
            return self._tool_failure()
        result = results[0]
        if (
            not isinstance(result, dict)
            or set(result) != {"contentItems", "success"}
            or type(result["success"]) is not bool
            or not isinstance(result["contentItems"], list)
        ):
            return self._tool_failure()
        for item in result["contentItems"]:
            fields = {"inputText": "text", "inputImage": "imageUrl", "inputAudio": "audioUrl"}
            if not isinstance(item, dict) or item.get("type") not in fields:
                return self._tool_failure()
            field_name = fields[item["type"]]
            if set(item) != {"type", field_name} or not isinstance(item[field_name], str):
                return self._tool_failure()
        try:
            if len(json.dumps(result, allow_nan=False).encode()) > MAX_TOOL_BYTES:
                return self._tool_failure()
        except (TypeError, ValueError, RecursionError):
            return self._tool_failure()
        return result

    def _tool_loop(self) -> None:
        while not self._closed.is_set():
            try:
                message = self._server_requests.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                result = self._invoke_tool(message.get("params", {}))
                self._send({"id": message["id"], "result": result})
            except (BridgeError, ValueError, TypeError):
                if not self._closed.is_set():
                    self._fail(BridgeError("Codex tool response could not be delivered"))

    def _fail(self, error: BridgeError) -> None:
        self._failure = error
        self._publish("bridge/closed", {"reason": str(error)})
        self._closed.set()
        with self._pending_lock:
            for pending in self._pending.values():
                pending.error = error
                pending.event.set()
        with self._condition:
            self._condition.notify_all()
        process = self._process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def close(self) -> None:
        self._closed.set()
        with self._pending_lock:
            for pending in self._pending.values():
                pending.error = self._failure or BridgeError("Codex bridge closed")
                pending.event.set()
        with self._condition:
            self._condition.notify_all()
        process = self._process
        if process is not None:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe is not None:
                    pipe.close()
        for worker in self._workers:
            if worker is not threading.current_thread():
                worker.join(timeout=0.2)

    def account_status(self) -> dict:
        result = self._request("account/read", {"refreshToken": False})
        account = result.get("account") if isinstance(result, dict) else None
        if not isinstance(account, dict):
            return {"status": "unauthenticated", "plan_type": None}
        return {
            "status": "chatgpt" if account.get("type") == "chatgpt" else "unsupported",
            "plan_type": account.get("planType") if account.get("type") == "chatgpt" else None,
        }

    def login_start(self) -> dict:
        result = self._request(
            "account/login/start",
            {"type": "chatgpt", "useHostedLoginSuccessPage": True, "appBrand": "chatgpt"},
        )
        if not isinstance(result, dict) or result.get("type") != "chatgpt":
            raise BridgeError("Codex returned an unsupported login flow")
        url = _text(result.get("authUrl"), "authUrl", 20000)
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname
            not in {"auth.openai.com", "auth0.openai.com", "chatgpt.com", "login.openai.com"}
            or parsed.username
            or parsed.password
        ):
            raise BridgeError("Codex returned an unexpected login destination")
        return {
            "login_id": _identifier(result.get("loginId"), "loginId"),
            "auth_url": url,
        }

    def login_cancel(self, login_id: str) -> dict:
        result = self._request(
            "account/login/cancel", {"loginId": _identifier(login_id, "loginId")}
        )
        return {"status": result.get("status", "unknown")}

    def models(self, cursor: str | None = None, limit: int = 50) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("model page limit must be from 1 to 100")
        params: dict[str, Any] = {"limit": limit, "includeHidden": False}
        if cursor is not None:
            params["cursor"] = _text(cursor, "cursor", 2000)
        result = self._request("model/list", params)
        if not isinstance(result, dict) or not isinstance(result.get("data"), list):
            raise BridgeError("Codex returned an invalid model catalog")
        keys = {
            "id",
            "model",
            "displayName",
            "description",
            "isDefault",
            "defaultReasoningEffort",
            "supportedReasoningEfforts",
            "inputModalities",
        }
        return [
            _redact({key: value for key, value in model.items() if key in keys})
            for model in result["data"][:100]
            if isinstance(model, dict)
        ]

    def _thread_params(
        self, model: str | None, base_instructions: str | None, developer_instructions: str | None
    ) -> dict:
        params: dict[str, Any] = {
            "cwd": str(self.cwd.resolve()),
            "runtimeWorkspaceRoots": [str(self.cwd.resolve())],
            "approvalPolicy": "never",
            "allowProviderModelFallback": False,
            "permissions": PERMISSIONS_PROFILE,
            "config": {
                "web_search": "disabled",
                "project_doc_max_bytes": 0,
                "features": {feature: False for feature in DISABLED_FEATURES},
            },
        }
        if model is not None:
            params["model"] = _identifier(model, "model")
        for field_name, value in (
            ("baseInstructions", base_instructions),
            ("developerInstructions", developer_instructions),
        ):
            if value is not None:
                params[field_name] = _text(value, field_name)
        return params

    def thread_start(
        self,
        *,
        model: str | None = None,
        base_instructions: str | None = None,
        developer_instructions: str | None = None,
        dynamic_tools: list[dict] | None = None,
        ephemeral: bool = False,
    ) -> dict:
        if type(ephemeral) is not bool:
            raise ValueError("ephemeral must be boolean")
        params = self._thread_params(model, base_instructions, developer_instructions)
        params["ephemeral"] = ephemeral
        if dynamic_tools is not None:
            if not isinstance(dynamic_tools, list) or len(dynamic_tools) > 16:
                raise ValueError("invalid dynamic tools")
            for tool in dynamic_tools:
                if (
                    not isinstance(tool, dict)
                    or set(tool) - {"type", "name", "description", "inputSchema", "deferLoading"}
                    or tool.get("type") != "function"
                    or tool.get("name") not in self.allowed_tools
                ):
                    raise ValueError("only registered dynamic function tools are allowed")
                _text(tool.get("description"), "tool description", 12000)
                if not isinstance(tool.get("inputSchema"), dict):
                    raise ValueError("tool inputSchema must be an object")
            params["dynamicTools"] = copy.deepcopy(dynamic_tools)
        result = self._request("thread/start", params)
        return self._register_thread(result)

    def _register_thread(self, result: Any) -> dict:
        if not isinstance(result, dict) or not isinstance(result.get("thread"), dict):
            raise BridgeError("Codex returned an invalid thread")
        self._threads.add(_identifier(result["thread"].get("id"), "threadId"))
        return _redact(result)

    def thread_resume(
        self,
        thread_id: str,
        *,
        model: str | None = None,
        base_instructions: str | None = None,
        developer_instructions: str | None = None,
    ) -> dict:
        params = self._thread_params(model, base_instructions, developer_instructions)
        params.pop("allowProviderModelFallback", None)
        params.update(threadId=_identifier(thread_id, "threadId"), excludeTurns=True)
        return self._register_thread(self._request("thread/resume", params))

    def thread_read(self, thread_id: str, include_turns: bool = False) -> dict:
        if type(include_turns) is not bool:
            raise ValueError("include_turns must be boolean")
        return _redact(
            self._request(
                "thread/read",
                {"threadId": _identifier(thread_id, "threadId"), "includeTurns": include_turns},
            )
        )

    def turn_start(
        self,
        thread_id: str,
        text: str,
        *,
        model: str | None = None,
        effort: str | None = None,
        client_message_id: str | None = None,
    ) -> dict:
        thread_id = _identifier(thread_id, "threadId")
        if thread_id not in self._threads:
            raise ValueError("start or resume the tutor thread before a turn")
        params: dict[str, Any] = {
            "threadId": thread_id,
            "input": [{"type": "text", "text": _text(text, "text")}],
            "cwd": str(self.cwd.resolve()),
            "runtimeWorkspaceRoots": [str(self.cwd.resolve())],
            "approvalPolicy": "never",
            "permissions": PERMISSIONS_PROFILE,
            "summary": "none",
        }
        if model is not None:
            params["model"] = _identifier(model, "model")
        if effort is not None:
            params["effort"] = _identifier(effort, "effort")
        if client_message_id is not None:
            params["clientUserMessageId"] = _identifier(client_message_id, "client_message_id")
        return _redact(self._request("turn/start", params))

    def turn_interrupt(self, thread_id: str, turn_id: str) -> dict:
        thread_id = _identifier(thread_id, "threadId")
        if thread_id not in self._threads:
            raise ValueError("unknown tutor thread")
        return _redact(
            self._request(
                "turn/interrupt", {"threadId": thread_id, "turnId": _identifier(turn_id, "turnId")}
            )
        )
