"""Real process coverage for the serving lifetime lock, with no account or learner."""

import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LAUNCH = """
import faulthandler, os, signal, sys, time
from pathlib import Path
faulthandler.enable()
faulthandler.register(signal.SIGUSR1, all_threads=True)
sys.path.insert(0, str(Path.cwd() / 'tools'))
import serve
print('phase: modules imported', flush=True)
ready = Path(sys.argv[1])
ready.touch()
gate = Path(os.environ['TUTOR_TEST_GATE'])
while not gate.exists():
    time.sleep(.01)
def open_browser(url):
    with open(os.environ['TUTOR_TEST_OPENED'], 'a', encoding='utf-8') as handle:
        handle.write(url + '\\n')
    return True
serve.webbrowser.open = open_browser
original_create = serve.create_server
def create_server(*args, **kwargs):
    print('phase: creating loopback server', flush=True)
    result = original_create(*args, **kwargs)
    print('phase: loopback server created', flush=True)
    return result
serve.create_server = create_server
original_save = serve.storage.save
def save(path, data):
    if path == serve.CONTROL:
        print('phase: publishing control', flush=True)
    result = original_save(path, data)
    if path == serve.CONTROL:
        print('phase: control published', flush=True)
    return result
serve.storage.save = save
sys.argv = ['serve.py', '0', '--open']
print('phase: entering main', flush=True)
serve.main()
"""


class SingletonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="tutor-singleton-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.student = self.base / "student"
        self.gate = self.base / "go"
        self.opened = self.base / "opened.txt"
        self.env = {
            **os.environ,
            "TUTOR_STUDENT_DIR": str(self.student),
            "TUTOR_TEST_GATE": str(self.gate),
            "TUTOR_TEST_OPENED": str(self.opened),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        self.processes = []
        self.logs = {}
        self.addCleanup(self.stop_children)

    def stop_children(self):
        for process in self.processes:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
        for process in self.processes:
            try:
                process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            process.communicate()

    def launch(self, number):
        ready = self.base / f"ready-{number}"
        stdout_path, stderr_path = self.base / f"stdout-{number}", self.base / f"stderr-{number}"
        with stdout_path.open("w") as stdout, stderr_path.open("w") as stderr:
            process = subprocess.Popen(
                [sys.executable, "-c", LAUNCH, str(ready)],
                cwd=ROOT,
                env=self.env,
                stdout=stdout,
                stderr=stderr,
                text=True,
            )
        self.processes.append(process)
        self.logs[process.pid] = (stdout_path, stderr_path)
        return process, ready

    def output(self, process):
        return tuple(path.read_text(errors="replace") for path in self.logs[process.pid])

    def diagnostics(self):
        for process in self.processes:
            if process.poll() is None:
                try:
                    process.send_signal(signal.SIGUSR1)
                except ProcessLookupError:
                    pass
        time.sleep(0.1)
        details = []
        for process in self.processes:
            stdout, stderr = self.output(process)
            details.append(
                f"pid={process.pid} returncode={process.poll()}\n"
                f"stdout:\n{stdout[-8000:]}\nstderr/stack:\n{stderr[-12000:]}"
            )
        details.append(f"student entries: {sorted(p.name for p in self.student.glob('*'))}")
        return "\n".join(details)

    def wait_until(self, predicate, timeout=5, owner=None):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            if owner is not None and owner.poll() is not None:
                self.fail("server owner exited before readiness\n" + self.diagnostics())
            time.sleep(0.01)
        self.fail("process state did not settle before deadline\n" + self.diagnostics())

    def command(self, action):
        return subprocess.run(
            [sys.executable, str(ROOT / "tools/serve.py"), action],
            cwd=ROOT,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=5,
        )

    def test_simultaneous_free_ports_share_one_server_and_preserve_lock_inode(self):
        first, first_ready = self.launch(1)
        second, second_ready = self.launch(2)
        self.wait_until(lambda: first_ready.exists() and second_ready.exists())
        self.gate.touch()
        self.wait_until(lambda: first.poll() is not None or second.poll() is not None)
        alive = [process for process in (first, second) if process.poll() is None]
        if len(alive) != 1:
            self.fail("exactly one process must own the serving lock\n" + self.diagnostics())
        survivor = alive[0]
        other = second if survivor is first else first
        other.wait(timeout=2)
        stdout, stderr = self.output(other)
        control_path = self.student / ".serve.json"
        # A slow durable publication can outlast the bounded startup wait. In
        # that case the loser must fail safely, then reuse the ready host on retry.
        if other.returncode:
            self.assertEqual(other.returncode, 1, stderr)
            self.assertIn("startup or shutdown in progress", stderr)
            self.wait_until(control_path.exists, timeout=15, owner=survivor)
            retry, _ = self.launch(4)
            retry.wait(timeout=15)
            stdout, stderr = self.output(retry)
            self.assertEqual(retry.returncode, 0, stderr)
        else:
            self.assertEqual(other.returncode, 0, stderr)
        control = json.loads(control_path.read_text())
        url = f"http://localhost:{control['port']}/"
        self.assertIn(url.rstrip("/"), stdout)
        self.assertIn("server already running", stdout)
        self.assertEqual(control["pid"], survivor.pid)
        with urllib.request.urlopen(
            urllib.request.Request(
                f"http://127.0.0.1:{control['port']}/api/health",
                headers={"X-Tutor-Token": control["token"]},
            ),
            timeout=2,
        ) as response:
            self.assertEqual(json.load(response), {"ok": True})
        self.wait_until(
            lambda: self.opened.exists() and len(self.opened.read_text().splitlines()) == 2
        )
        self.assertEqual(self.opened.read_text().splitlines(), [url, url])
        inode = (self.student / ".serve.lock").stat().st_ino
        status = self.command("status")
        self.assertEqual(status.returncode, 0, status.stderr)
        stopped = self.command("stop")
        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        survivor.wait(timeout=3)
        self.assertEqual(survivor.returncode, 0)
        self.assertFalse(control_path.exists())
        self.assertEqual((self.student / ".serve.lock").stat().st_ino, inode)

        # A later lifetime reuses the inode after the previous owner closes its handle.
        restarted, _ = self.launch(3)
        self.wait_until(control_path.exists, owner=restarted)
        self.assertIsNone(restarted.poll())
        self.assertEqual((self.student / ".serve.lock").stat().st_ino, inode)
        stopped = self.command("stop")
        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        restarted.wait(timeout=3)
        self.assertEqual(restarted.returncode, 0)
        self.assertFalse((self.student / "english").exists())
        self.assertFalse((self.student / "web-chat.json").exists())

    def test_loopback_bind_and_health_never_require_reverse_dns(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import serve
        import srs

        with (
            patch.object(serve, "STUDENT", self.student),
            patch.object(srs, "STUDENT", self.student),
            patch("socket.getfqdn", side_effect=AssertionError("reverse DNS is forbidden")),
        ):
            server = serve.create_server()
            self.assertEqual(server.server_name, "localhost")
            self.assertEqual(server.server_port, server.server_address[1])
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{server.server_port}/api/health",
                    headers={"X-Tutor-Token": server.shutdown_token},
                )
                with urllib.request.urlopen(request, timeout=2) as response:
                    self.assertEqual(json.load(response), {"ok": True})
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()
        self.assertFalse((self.student / "english").exists())

    def test_busy_startup_without_control_returns_prompt_error(self):
        self.student.mkdir()
        lock_path = self.student / ".serve.lock"
        with lock_path.open("a") as owner:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            started = time.monotonic()
            result = self.command("0")
            elapsed = time.monotonic() - started
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("startup or shutdown in progress", result.stderr)
        self.assertLess(elapsed, 2)
        self.assertTrue(lock_path.exists())
        self.assertFalse((self.student / ".serve.json").exists())
        self.assertFalse((self.student / "english").exists())

    def test_lock_symlink_is_rejected_without_touching_target(self):
        self.student.mkdir()
        foreign = self.base / "foreign.txt"
        foreign.write_text("preserve")
        (self.student / ".serve.lock").symlink_to(foreign)
        result = self.command("0")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(foreign.read_text(), "preserve")
        self.assertFalse((self.student / ".serve.json").exists())


if __name__ == "__main__":
    unittest.main()
