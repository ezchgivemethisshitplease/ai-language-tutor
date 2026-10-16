"""Launcher boundaries: read-only diagnostics, safe local setup, no repeated install."""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import web_start

REPOSITORY = Path(__file__).resolve().parents[1]


class WebStartTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "tools").mkdir()
        for name in (
            "start.sh",
            "tools/web_start.py",
            "package.json",
            "package-lock.json",
            "requirements.txt",
        ):
            shutil.copyfile(REPOSITORY / name, self.root / name)
        (self.root / "start.sh").chmod(0o755)
        binary = self.root / "bin"
        binary.mkdir()
        node = binary / "node"
        node.write_text(
            "#!/bin/sh\nprintf '%s\\n' '"
            + json.dumps({"version": "24.0.0", "platform": sys.platform, "arch": "arm64"})
            + "'\n"
        )
        node.chmod(0o755)
        npm = binary / "npm"
        npm.write_text("#!/bin/sh\nprintf '%s\\n' '10.9.0'\n")
        npm.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": str(binary) + os.pathsep + os.environ.get("PATH", ""),
            "TUTOR_PYTHON": sys.executable,
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        self.env.pop("TUTOR_CODEX_BIN", None)
        self.previous_cwd = Path.cwd()
        self.addCleanup(os.chdir, self.previous_cwd)

    def files(self):
        return {
            path.relative_to(self.root).as_posix(): path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file()
        }

    def run_launcher(self, *args):
        return subprocess.run(
            [str(self.root / "start.sh"), *args],
            cwd="/",
            env=self.env,
            capture_output=True,
            text=True,
            timeout=15,
        )

    def test_help_and_missing_runtime_check_never_install_or_create_files(self):
        before = self.files()
        help_result = self.run_launcher("--help")
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        checked = self.run_launcher("--check")
        self.assertEqual(checked.returncode, 1, checked.stderr)
        self.assertEqual(
            json.loads(checked.stdout),
            {
                "ready": False,
                "python_dependencies": False,
                "codex_runtime": False,
                "custom_codex": False,
            },
        )
        self.assertEqual(self.files(), before)

    def test_invalid_port_fails_before_mutation(self):
        before = self.files()
        for port in ("-1", "65536", "not-a-port"):
            with self.subTest(port=port):
                result = self.run_launcher("--port", port)
                self.assertEqual(result.returncode, 2)
        self.assertEqual(self.files(), before)

    def test_prepared_environment_does_not_run_pip_or_npm_again(self):
        with (
            patch.object(web_start, "ROOT", self.root),
            patch.object(web_start, "_python_state", return_value=True),
            patch.object(web_start, "_local_codex_ready", return_value=True),
            patch.object(
                web_start.subprocess, "run", side_effect=AssertionError("unexpected reinstall")
            ),
        ):
            (self.root / ".venv/bin").mkdir(parents=True)
            (self.root / ".venv/bin/python").touch()
            web_start._setup({"fsrs": "6.3.2"}, "npm", {}, None)
        self.assertTrue((self.root / ".runtime-setup.lock").exists())

    def test_symlinked_environment_is_rejected_before_probe_or_pip(self):
        outside = self.root / "unrelated-environment"
        outside.mkdir()
        (self.root / ".venv").symlink_to(outside, target_is_directory=True)
        with (
            patch.object(web_start, "ROOT", self.root),
            patch.object(
                web_start,
                "_capture",
                side_effect=AssertionError("must not inspect unrelated environment"),
            ),
            self.assertRaises(web_start.SetupError),
        ):
            web_start._python_state({"fsrs": "6.3.2"})

    def test_wrong_python_prefix_cannot_trigger_system_pip_install(self):
        (self.root / ".venv/bin").mkdir(parents=True)
        (self.root / ".venv/bin/python").touch()
        state = {"prefix": "/usr", "version": [3, 12, 0], "versions": {}, "imports_ok": False}
        with (
            patch.object(web_start, "ROOT", self.root),
            patch.object(web_start, "_capture", return_value=json.dumps(state)),
            self.assertRaises(web_start.SetupError),
        ):
            web_start._python_state({"fsrs": "6.3.2"})

    def test_explicit_native_override_does_not_require_node_or_npm(self):
        executable = self.root / "bin/custom-codex"
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
        output = io.StringIO()
        with (
            patch.object(web_start, "ROOT", self.root),
            patch.dict(os.environ, {"TUTOR_CODEX_BIN": str(executable)}),
            patch.object(
                web_start, "_node_tools", side_effect=AssertionError("unexpected Node dependency")
            ),
            patch.object(web_start, "_python_state", return_value=True),
            redirect_stdout(output),
        ):
            self.assertEqual(web_start.main(["--check"]), 0)
        self.assertTrue(json.loads(output.getvalue())["custom_codex"])
        self.assertFalse((self.root / ".runtime-setup.lock").exists())

    def test_launcher_forwards_only_loopback_port_and_browser_choice(self):
        for flags, expected in (
            ([], ["8765", "--open"]),
            (["--no-open", "--port", "9876"], ["9876"]),
        ):
            with (
                self.subTest(flags=flags),
                patch.object(web_start, "ROOT", self.root),
                patch.dict(os.environ, {}, clear=True),
                patch.object(web_start, "_node_tools", return_value=("npm", {})),
                patch.object(web_start, "_local_codex_ready", return_value=True),
                patch.object(web_start, "_python_state", return_value=True),
                patch.object(web_start, "_setup"),
                patch.object(web_start.os, "execv") as execute,
            ):
                self.assertEqual(web_start.main(flags), 0)
                command = execute.call_args.args[1]
                self.assertEqual(
                    command,
                    [
                        str(self.root / ".venv/bin/python"),
                        str(self.root / "tools/serve.py"),
                        *expected,
                    ],
                )
                self.assertEqual(
                    os.environ["TUTOR_CODEX_BIN"], str(self.root / "node_modules/.bin/codex")
                )

    def test_requirements_reject_unpinned_or_executable_sources(self):
        with patch.object(web_start, "ROOT", self.root):
            for raw in (
                "fsrs>=6\n",
                "-r https://example.invalid/requirements.txt\n",
                "git+https://example.invalid/code\n",
            ):
                (self.root / "requirements.txt").write_text(raw)
                with self.subTest(raw=raw), self.assertRaises(web_start.SetupError):
                    web_start._pins()


if __name__ == "__main__":
    unittest.main()
