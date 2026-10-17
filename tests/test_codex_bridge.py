"""Protocol fixtures use OS pipes and a fake child, never real auth or inference."""

from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from tools import codex_bridge as cb


class FakeProcess:
    def __init__(self, handler=None):
        child_read, parent_write = os.pipe()
        parent_read, child_write = os.pipe()
        stderr_read, stderr_write = os.pipe()
        self.stdin = os.fdopen(parent_write, "wb", buffering=0)
        self.stdout = os.fdopen(parent_read, "rb", buffering=0)
        self.stderr = os.fdopen(stderr_read, "rb", buffering=0)
        self._input = os.fdopen(child_read, "rb", buffering=0)
        self._output = os.fdopen(child_write, "wb", buffering=0)
        self._stderr = os.fdopen(stderr_write, "wb", buffering=0)
        self.pid = 999999999
        self.returncode = None
        self.sent = []
        self.responses = queue.Queue()
        self.lock = threading.Lock()
        self.handler = handler
        self.initialized = threading.Event()
        self.request_seen = threading.Event()
        self.worker = threading.Thread(target=self.run, daemon=True)
        self.worker.start()

    def emit(self, message):
        self.raw((json.dumps(message) + "\n").encode())

    def raw(self, data):
        with self.lock:
            self._output.write(data)

    def respond(self, message, result):
        self.emit({"id": message["id"], "result": result})

    def default(self, message):
        method = message.get("method")
        if method == "initialize":
            self.respond(message, {"userAgent": "fixture", "codexHome": "/fixture/private"})
        elif method == "initialized":
            self.initialized.set()
        elif method == "account/read":
            self.respond(
                message,
                {
                    "account": {
                        "type": "chatgpt",
                        "email": "private@example.invalid",
                        "planType": "plus",
                    },
                    "requiresOpenaiAuth": True,
                    "workspaceRouting": {"chatgptAccountId": "private-id"},
                },
            )
        elif method == "account/login/start":
            self.respond(
                message,
                {
                    "type": "chatgpt",
                    "loginId": "login-1",
                    "authUrl": "https://auth.openai.com/oauth/authorize?state=fixture",
                },
            )
        elif method == "account/login/cancel":
            self.respond(message, {"status": "canceled"})
        elif method == "model/list":
            self.respond(
                message,
                {
                    "data": [
                        {
                            "id": "fixture-model",
                            "model": "fixture-model",
                            "displayName": "Fixture",
                            "isDefault": True,
                            "defaultReasoningEffort": "low",
                            "supportedReasoningEfforts": [
                                {"reasoningEffort": "low", "description": "Fixture"}
                            ],
                            "accessToken": "never-display-this",
                        }
                    ]
                },
            )
        elif method in {"thread/start", "thread/resume", "thread/read"}:
            self.respond(
                message, {"thread": {"id": "thread-1", "turns": []}, "model": "fixture-model"}
            )
        elif method == "turn/start":
            self.respond(message, {"turn": {"id": "turn-1", "status": "inProgress", "items": []}})
        elif method == "turn/interrupt":
            self.respond(message, {})
        elif "method" not in message:
            self.responses.put(message)
        else:
            raise AssertionError(f"Unexpected fixture RPC {method}")

    def run(self):
        try:
            while self.returncode is None:
                line = self._input.readline()
                if not line:
                    return
                message = json.loads(line)
                self.sent.append(message)
                self.request_seen.set()
                if self.handler is None or self.handler(self, message) is not True:
                    self.default(message)
        except (OSError, ValueError):
            pass
        finally:
            self._input.close()

    def poll(self):
        return self.returncode

    def terminate(self):
        if self.returncode is None:
            self.returncode = 0
            with self.lock:
                self._output.close()
                self._stderr.close()

    kill = terminate

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("fixture", timeout)
        return self.returncode


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.processes = []
        self.bridges = []
        self.handler = None

        def factory(*args, **kwargs):
            self.command = args[0]
            self.popen_kwargs = kwargs
            process = FakeProcess(self.handler)
            self.processes.append(process)
            return process

        self.patches = [
            patch.object(cb, "select_binary", return_value=Path("/fixture/codex")),
            patch.object(
                cb.subprocess,
                "run",
                return_value=subprocess.CompletedProcess([], 0, b"codex-cli 0.163.0\n", b""),
            ),
            patch.object(cb.subprocess, "Popen", side_effect=factory),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for bridge in self.bridges:
            bridge.close()
        for process in self.processes:
            process.terminate()
            process.worker.join(timeout=0.3)
        for item in reversed(self.patches):
            item.stop()
        self.directory.cleanup()

    def bridge(self, **kwargs):
        bridge = cb.CodexBridge(
            cwd=self.root / "workspace",
            codex_home=self.root / "private-home",
            request_timeout=0.3,
            **kwargs,
        )
        self.bridges.append(bridge)
        bridge.start()
        return bridge

    def tool_request(self, **changes):
        params = {
            "threadId": "thread-1",
            "turnId": "turn-1",
            "callId": "call-1",
            "tool": "tutor",
            "namespace": None,
            "arguments": {"action": "status", "arguments": {}},
        }
        params.update(changes)
        return {"id": "server-request", "method": "item/tool/call", "params": params}

    def test_initialize_is_once_and_experimental_dynamic_tools_opted_in(self):
        bridge = self.bridge()
        bridge.start()
        process = self.processes[0]
        self.assertTrue(process.initialized.wait(0.3))
        initialize = [m for m in process.sent if m.get("method") == "initialize"]
        self.assertEqual(len(initialize), 1)
        self.assertTrue(initialize[0]["params"]["capabilities"]["experimentalApi"])
        self.assertEqual(self.popen_kwargs["cwd"], self.root / "workspace")
        self.assertTrue(self.popen_kwargs["start_new_session"])
        self.assertNotIn("--ignore-user-config", self.command)
        self.assertIn("features.skip_host_skill_discovery=true", self.command)
        self.assertIn("permissions.tutor_readonly.network.enabled=false", self.command)
        self.assertTrue(
            any(
                ":minimal" in value and str(self.root / "workspace") in value
                for value in self.command
            )
        )
        for feature in ("shell_tool", "hooks", "apps", "view_image", "multi_agent", "plugins"):
            self.assertIn(feature, self.command)
        self.assertEqual(os.stat(self.root / "private-home").st_mode & 0o777, 0o700)

    def test_account_status_has_no_email_account_id_or_credentials(self):
        bridge = self.bridge()
        self.assertEqual(bridge.account_status(), {"status": "chatgpt", "plan_type": "plus"})
        self.assertNotIn("private", json.dumps(bridge.account_status()))
        for account, status in [(None, "unauthenticated"), ({"type": "apiKey"}, "unsupported")]:
            with self.subTest(account=account):
                self.processes[0].handler = lambda p, m, selected_account=account: (
                    (p.respond(m, {"account": selected_account}) or True)
                    if m.get("method") == "account/read"
                    else False
                )
                self.assertEqual(bridge.account_status()["status"], status)

    def test_child_does_not_inherit_api_credentials_or_desktop_environment(self):
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "sensitive",
                "CODEX_SHELL": "desktop",
                "ELEVENLABS_API_KEY": "sensitive",
                "ACCESS_TOKEN": "sensitive",
            },
        ):
            self.bridge()
        env = self.popen_kwargs["env"]
        self.assertEqual(env["CODEX_HOME"], str(self.root / "private-home"))
        for key in ("OPENAI_API_KEY", "CODEX_SHELL", "ELEVENLABS_API_KEY", "ACCESS_TOKEN"):
            self.assertNotIn(key, env)

    def test_model_required_code_mode_has_host_on_start_and_resume_without_enabling_shell(self):
        bridge = self.bridge()
        bridge.thread_start()
        bridge.thread_resume("thread-1")
        enabled = [
            self.command[i + 1] for i, value in enumerate(self.command) if value == "--enable"
        ]
        disabled = [
            self.command[i + 1] for i, value in enumerate(self.command) if value == "--disable"
        ]
        self.assertEqual(enabled, ["code_mode_host"])
        self.assertNotIn("code_mode_host", disabled)
        self.assertEqual(set(disabled), set(cb.DISABLED_FEATURES))
        self.assertIn("code_mode", disabled)
        self.assertIn("shell_tool", disabled)
        for message in self.processes[0].sent:
            if message.get("method") not in {"thread/start", "thread/resume"}:
                continue
            params = message["params"]
            self.assertIs(params["config"]["features"]["code_mode_host"], True)
            for feature in cb.DISABLED_FEATURES:
                self.assertIs(params["config"]["features"][feature], False)
            self.assertEqual(params["permissions"], cb.PERMISSIONS_PROFILE)
            self.assertEqual(params["approvalPolicy"], "never")

    def test_unsafe_auth_workspace_relationship_and_personal_home_rejected(self):
        for home in (self.root / "workspace", self.root / "workspace" / "private"):
            with self.assertRaisesRegex(cb.BridgeError, "outside"):
                cb.CodexBridge(cwd=self.root / "workspace", codex_home=home).start()
        with patch.dict(os.environ, {"CODEX_HOME": str(self.root / "private-home")}):
            with self.assertRaisesRegex(cb.BridgeError, "isolated"):
                cb.CodexBridge(
                    cwd=self.root / "workspace", codex_home=self.root / "private-home"
                ).start()

    def test_rejected_personal_home_is_never_created_or_chmodded(self):
        personal = self.root / "personal-home"
        with patch.dict(os.environ, {"CODEX_HOME": str(personal)}):
            with self.assertRaises(cb.BridgeError):
                cb.CodexBridge(cwd=self.root / "workspace", codex_home=personal).start()
            self.assertFalse(personal.exists())
            self.assertFalse((self.root / "workspace").exists())
            personal.mkdir(mode=0o750)
            with self.assertRaises(cb.BridgeError):
                cb.CodexBridge(cwd=self.root / "workspace", codex_home=personal).start()
            self.assertEqual(personal.stat().st_mode & 0o777, 0o750)

    def test_managed_chatgpt_login_only_and_https_destination_validated(self):
        bridge = self.bridge()
        result = bridge.login_start()
        self.assertEqual(set(result), {"login_id", "auth_url"})
        self.assertEqual(result["login_id"], "login-1")
        self.assertEqual(bridge.login_cancel("login-1"), {"status": "canceled"})
        request = next(
            m for m in self.processes[0].sent if m.get("method") == "account/login/start"
        )
        self.assertEqual(request["params"]["type"], "chatgpt")
        for url in (
            "http://auth.openai.com/",
            "https://attacker.invalid/",
            "https://name:password@auth.openai.com/",
        ):
            self.processes[0].handler = lambda p, m, selected_url=url: (
                (
                    p.respond(m, {"type": "chatgpt", "loginId": "login-1", "authUrl": selected_url})
                    or True
                )
                if m.get("method") == "account/login/start"
                else False
            )
            with self.assertRaises(cb.BridgeError):
                bridge.login_start()

    def test_model_catalog_is_a_sanitized_list_not_an_entitlement_claim(self):
        bridge = self.bridge()
        models = bridge.models()
        self.assertIsInstance(models, list)
        self.assertEqual(models[0]["id"], "fixture-model")
        self.assertNotIn("accessToken", models[0])
        with self.assertRaises(ValueError):
            bridge.models(limit=0)

    def test_interleaved_notifications_and_reverse_order_responses_match_ids(self):
        waiting = []

        def handler(process, message):
            if message.get("method") == "account/read":
                waiting.append(message)
                return True
            if message.get("method") == "model/list":
                process.emit(
                    {
                        "method": "item/agentMessage/delta",
                        "params": {"threadId": "thread-1", "itemId": "item-1", "delta": "Hello"},
                    }
                )
                process.default(message)
                process.default(waiting.pop())
                return True
            return False

        self.handler = handler
        bridge = self.bridge()
        with ThreadPoolExecutor(max_workers=2) as pool:
            account = pool.submit(bridge.account_status)
            deadline = time.monotonic() + 0.2
            while not waiting and time.monotonic() < deadline:
                time.sleep(0.001)
            models = pool.submit(bridge.models)
            self.assertEqual(models.result()[0]["id"], "fixture-model")
            self.assertEqual(account.result()["status"], "chatgpt")
        self.assertEqual(bridge.next_event(0.3)["params"]["delta"], "Hello")

    def test_thread_and_turn_policies_cannot_be_overridden_by_browser_input(self):
        bridge = self.bridge()
        tool = {
            "type": "function",
            "name": "tutor",
            "description": "Fixture.",
            "inputSchema": {"type": "object"},
        }
        result = bridge.thread_start(
            model="fixture-model",
            base_instructions="Teach English.",
            developer_instructions="Preserve evidence.",
            dynamic_tools=[tool],
        )
        self.assertEqual(result["thread"]["id"], "thread-1")
        bridge.turn_start(
            "thread-1",
            "Explain this.",
            model="fixture-model",
            effort="low",
            client_message_id="message-1",
        )
        bridge.thread_resume("thread-1")
        bridge.thread_read("thread-1")
        bridge.turn_interrupt("thread-1", "turn-1")
        methods = {m["method"]: m for m in self.processes[0].sent if "method" in m}
        for name in ("thread/start", "thread/resume", "turn/start"):
            params = methods[name]["params"]
            self.assertEqual(params["permissions"], cb.PERMISSIONS_PROFILE)
            self.assertEqual(params["approvalPolicy"], "never")
            self.assertNotIn("sandbox", params)
            self.assertNotIn("sandboxPolicy", params)
            self.assertEqual(params["cwd"], str((self.root / "workspace").resolve()))
        self.assertEqual(methods["thread/start"]["params"]["dynamicTools"], [tool])
        self.assertNotIn("allowProviderModelFallback", methods["thread/resume"]["params"])
        with self.assertRaises(ValueError):
            bridge.turn_start("unknown", "A message")
        with self.assertRaises(ValueError):
            bridge.thread_start(dynamic_tools=[dict(tool, name="shell")])
        with self.assertRaises(TypeError):
            bridge.thread_start(config={"sandbox_mode": "danger-full-access"})
        self.assertFalse(hasattr(bridge, "request"))

    def test_dynamic_tool_callback_can_make_rpc_without_blocking_reader(self):
        container = {}
        observed = []

        def callback(params):
            observed.append(copy.deepcopy(params))
            account = container["bridge"].account_status()
            return {
                "contentItems": [{"type": "inputText", "text": account["status"]}],
                "success": True,
            }

        bridge = self.bridge(tool_callback=callback)
        container["bridge"] = bridge
        bridge.thread_start()
        self.processes[0].emit(self.tool_request())
        response = self.processes[0].responses.get(timeout=0.5)
        self.assertTrue(response["result"]["success"])
        self.assertEqual(response["result"]["contentItems"][0]["text"], "chatgpt")
        self.assertEqual(observed[0]["arguments"]["action"], "status")

    def test_unknown_tools_threads_namespaces_and_nonobject_arguments_are_declined(self):
        calls = []
        bridge = self.bridge(tool_callback=lambda params: calls.append(params))
        bridge.thread_start()
        for change in (
            {"tool": "shell"},
            {"threadId": "other"},
            {"namespace": "filesystem"},
            {"arguments": "shell command"},
        ):
            self.processes[0].emit(self.tool_request(**change))
            response = self.processes[0].responses.get(timeout=0.5)
            self.assertFalse(response["result"]["success"])
        self.assertEqual(calls, [])

    def test_approvals_permissions_elicitations_and_userinput_fail_closed(self):
        bridge = self.bridge()
        process = self.processes[0]
        cases = {
            "item/commandExecution/requestApproval": {"decision": "decline"},
            "item/fileChange/requestApproval": {"decision": "decline"},
            "item/permissions/requestApproval": {"permissions": {}, "scope": "turn"},
            "item/tool/requestUserInput": {"answers": {}},
            "mcpServer/elicitation/request": {"action": "decline", "content": None},
            "execCommandApproval": {"decision": "abort"},
        }
        for method, expected in cases.items():
            process.emit({"id": method, "method": method, "params": {}})
            self.assertEqual(process.responses.get(timeout=0.5)["result"], expected)
        process.emit(
            {
                "id": "unknown",
                "method": "account/chatgptAuthTokens/refresh",
                "params": {"accessToken": "private"},
            }
        )
        self.assertEqual(process.responses.get(timeout=0.5)["error"]["code"], -32601)
        self.assertIsNone(bridge.next_event())

    def test_callback_timeout_is_bounded_and_does_not_deadlock_transport(self):
        release = threading.Event()
        calls = []

        def callback(params):
            calls.append(params)
            release.wait(1)
            return {"contentItems": [], "success": True}

        bridge = self.bridge(tool_callback=callback, tool_timeout=0.05)
        bridge.thread_start()
        try:
            for _ in range(3):
                self.processes[0].emit(self.tool_request())
                self.assertFalse(self.processes[0].responses.get(timeout=0.5)["result"]["success"])
            self.assertEqual(len(calls), 2)
            self.assertEqual(bridge.account_status()["status"], "chatgpt")
        finally:
            release.set()

    def test_event_callbacks_are_fifo_and_safely_redacted(self):
        seen = []
        completed = threading.Event()

        def event(method, params):
            seen.append((method, params))
            if method == "turn/completed":
                completed.set()

        self.bridge(event_callback=event)
        process = self.processes[0]
        process.emit(
            {
                "method": "account/updated",
                "params": {
                    "authMode": "chatgpt",
                    "planType": "plus",
                    "email": "private@example.invalid",
                    "accessToken": "secret",
                },
            }
        )
        process.emit(
            {
                "method": "item/agentMessage/delta",
                "params": {
                    "threadId": "thread-1",
                    "delta": "sk-12345678901234567890",
                    "email": "private@example.invalid",
                },
            }
        )
        process.emit(
            {
                "method": "turn/completed",
                "params": {"threadId": "thread-1", "turn": {"id": "turn-1", "status": "completed"}},
            }
        )
        self.assertTrue(completed.wait(0.5))
        self.assertEqual(
            [m for m, _ in seen], ["account/updated", "item/agentMessage/delta", "turn/completed"]
        )
        self.assertNotIn("private@example.invalid", json.dumps(seen))
        self.assertNotIn("sk-12345678901234567890", json.dumps(seen))

    def test_bounded_event_queue_reports_loss_explicitly(self):
        bridge = self.bridge(max_events=2)
        for index in range(5):
            bridge._publish("fixture/event", {"index": index})
        self.assertEqual(
            bridge.next_event(), {"method": "bridge/eventsDropped", "params": {"count": 3}}
        )
        self.assertEqual(bridge.next_event()["params"]["index"], 3)
        self.assertEqual(bridge.next_event()["params"]["index"], 4)

    def test_timeout_removes_pending_and_late_response_does_not_alias_new_request(self):
        waiting = []

        def handler(process, message):
            if message.get("method") == "account/read" and not waiting:
                waiting.append(message)
                return True
            return False

        self.handler = handler
        bridge = self.bridge()
        with self.assertRaises(cb.BridgeTimeout):
            bridge.account_status()
        self.assertEqual(bridge._pending, {})
        self.processes[0].default(waiting[0])
        self.assertEqual(bridge.account_status()["status"], "chatgpt")

    def test_process_death_rejects_waiters_and_delivers_closed_callback(self):
        waiting = threading.Event()
        closed = threading.Event()
        events = []

        def handler(process, message):
            if message.get("method") == "model/list":
                waiting.set()
                return True
            return False

        self.handler = handler

        def callback(method, params):
            events.append((method, params))
            if method == "bridge/closed":
                closed.set()

        bridge = self.bridge(event_callback=callback)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(bridge.models)
            self.assertTrue(waiting.wait(0.3))
            self.processes[0]._stderr.write(b"private-token-and-email-must-not-be-logged\n")
            self.processes[0].terminate()
            with self.assertRaises(cb.BridgeError):
                future.result(timeout=0.5)
        self.assertTrue(closed.wait(0.5))
        self.assertNotIn("private-token", json.dumps(events))
        self.assertTrue(bridge._closed.is_set())

    def test_malformed_duplicate_and_oversized_frames_fail_without_private_content(self):
        for payload in (
            b'{"id":1,"id":2}\n',
            b'{"method":"bad","params":NaN}\n',
            b"private-invalid-json\n",
            b"x" * (cb.MAX_FRAME_BYTES + 1),
        ):
            with self.subTest(size=len(payload)):
                bridge = self.bridge()
                try:
                    self.processes[-1].raw(payload)
                except BrokenPipeError:
                    pass
                self.assertTrue(bridge._closed.wait(0.5))
                events = []
                while (event := bridge.next_event()) is not None:
                    events.append(event)
                self.assertNotIn("private-invalid-json", json.dumps(events))
                bridge.close()

    def test_wrong_runtime_version_fails_before_starting_process(self):
        with patch.object(
            cb.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, b"codex-cli 0.39.0\n", b""),
        ):
            with self.assertRaisesRegex(cb.BridgeError, "0.163.0"):
                self.bridge()
        self.assertEqual(self.processes, [])

    def test_close_is_idempotent_and_bridge_instance_cannot_restart(self):
        bridge = self.bridge()
        bridge.close()
        bridge.close()
        with self.assertRaises(cb.BridgeError):
            bridge.start()


if __name__ == "__main__":
    unittest.main()
