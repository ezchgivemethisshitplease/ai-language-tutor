"""Real process coverage for the serving lifetime lock, with no account or learner."""

import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
LAUNCH = """
import os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'tools'))
import serve
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
sys.argv = ['serve.py', '0', '--open']
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
        process = subprocess.Popen(
            [sys.executable, "-c", LAUNCH, str(ready)],
            cwd=ROOT,
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.processes.append(process)
        return process, ready

    def wait_until(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        self.fail("process state did not settle before deadline")

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
        self.assertEqual(len(alive), 1, "exactly one process must own the serving lock")
        survivor = alive[0]
        other = second if survivor is first else first
        stdout, stderr = other.communicate(timeout=2)
        self.assertEqual(other.returncode, 0, stderr)
        control_path = self.student / ".serve.json"
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
        self.wait_until(control_path.exists)
        self.assertIsNone(restarted.poll())
        self.assertEqual((self.student / ".serve.lock").stat().st_ino, inode)
        stopped = self.command("stop")
        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        restarted.wait(timeout=3)
        self.assertEqual(restarted.returncode, 0)
        self.assertFalse((self.student / "english").exists())
        self.assertFalse((self.student / "web-chat.json").exists())

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
