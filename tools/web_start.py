#!/usr/bin/env python3
"""Prepare the local web runtime once, then launch the loopback tutor server."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
PROBE = """import importlib.metadata as metadata, json, sys
pins = json.loads(sys.argv[1])
versions = {}
for name in pins:
    try:
        versions[name] = metadata.version(name)
    except metadata.PackageNotFoundError:
        versions[name] = None
try:
    from fsrs import Card, Rating, Scheduler
    imports_ok = True
except Exception:
    imports_ok = False
print(json.dumps({'prefix': sys.prefix, 'version': list(sys.version_info[:3]),
                  'versions': versions, 'imports_ok': imports_ok}))
"""


class SetupError(RuntimeError):
    """A prerequisite or the local runtime needs attention."""


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _capture(args):
    result = subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=15,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if result.returncode:
        raise SetupError(
            f"Не удалось выполнить {Path(args[0]).name}; проверь установку инструмента."
        )
    return result.stdout.strip()


def _pins():
    result = {}
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        value = line.split("#", 1)[0].strip()
        if not value:
            continue
        matched = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)", value)
        if not matched:
            raise SetupError("requirements.txt должен содержать точные версии name==version.")
        result[matched[1]] = matched[2]
    if not result:
        raise SetupError("requirements.txt не содержит зависимостей.")
    return result


def _python_state(pins):
    directory = ROOT / ".venv"
    if directory.is_symlink():
        raise SetupError(".venv должна быть локальным каталогом, а не символьной ссылкой.")
    executable = directory / "bin/python"
    if not executable.is_file():
        return False
    try:
        state = json.loads(_capture([str(executable), "-c", PROBE, json.dumps(pins)]))
    except (OSError, ValueError, SetupError, subprocess.TimeoutExpired):
        return False
    if Path(state["prefix"]).resolve() != directory.resolve():
        raise SetupError(
            ".venv/bin/python указывает вне локальной среды; системный Python не изменён."
        )
    if tuple(state["version"]) < (3, 10):
        raise SetupError("В .venv устаревший Python. Создай среду заново с Python 3.10+.")
    return state["versions"] == pins and state["imports_ok"] is True


def _node_tools():
    node, npm = shutil.which("node"), shutil.which("npm")
    if not node or not npm:
        raise SetupError(
            "Нужны Node.js 22+ и npm 10+. Установи актуальный Node.js LTS с nodejs.org."
        )
    node_info = json.loads(
        _capture(
            [
                node,
                "-p",
                "JSON.stringify({version:process.versions.node,platform:process.platform,arch:process.arch})",
            ]
        )
    )
    if (
        int(node_info["version"].split(".", 1)[0]) < 22
        or int(_capture([npm, "--version"]).split(".", 1)[0]) < 10
    ):
        raise SetupError("Нужны Node.js 22+ и npm 10+; рекомендуем Node.js LTS.")
    if node_info["platform"] != sys.platform or node_info["arch"] not in {"x64", "arm64"}:
        raise SetupError("Локальный Codex runtime поддерживает macOS/Linux на x64 и arm64.")
    return npm, node_info


def _local_codex_ready(node_info):
    try:
        manifest = _read_json(ROOT / "package.json")
        locked = _read_json(ROOT / "package-lock.json")["packages"]
        installed = _read_json(ROOT / "node_modules/.package-lock.json")["packages"]
        pin = manifest["dependencies"]["@openai/codex"]
        if (
            not re.fullmatch(r"\d+\.\d+\.\d+", pin)
            or locked["node_modules/@openai/codex"]["version"] != pin
        ):
            raise SetupError(
                "package.json и package-lock.json не согласованы; нужен точный pin Codex."
            )
        for name, item in locked.items():
            if not name:
                continue
            if "os" in item and node_info["platform"] not in item["os"]:
                continue
            if "cpu" in item and node_info["arch"] not in item["cpu"]:
                continue
            actual = installed.get(name, {})
            if any(
                actual.get(key) != item.get(key) for key in ("version", "resolved", "integrity")
            ):
                return False
            if not (ROOT / name / "package.json").is_file():
                return False
        actual_manifest = _read_json(ROOT / "node_modules/@openai/codex/package.json")
        if actual_manifest.get("version") != pin:
            return False
        architecture = "aarch64" if node_info["arch"] == "arm64" else "x86_64"
        target = (
            f"{architecture}-apple-darwin"
            if sys.platform == "darwin"
            else f"{architecture}-unknown-linux-musl"
        )
        native = (
            ROOT
            / f"node_modules/@openai/codex-{sys.platform}-{node_info['arch']}/vendor/{target}/bin/codex"
        )
        entrypoint = ROOT / "node_modules/.bin/codex"
        return (
            native.is_file()
            and os.access(native, os.X_OK)
            and entrypoint.is_file()
            and os.access(entrypoint, os.X_OK)
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _install(args):
    environment = {
        **os.environ,
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_REQUIRE_VIRTUALENV": "true",
    }
    result = subprocess.run(args, cwd=ROOT, env=environment)
    if result.returncode:
        raise SetupError(
            "Установка зависимостей не завершена. Проверь сеть и сообщения выше, затем повтори ./start.sh."
        )


def _setup(pins, npm, node_info, override):
    # Separate invocations must not run pip/npm concurrently in the same checkout.
    import fcntl

    descriptor = os.open(
        ROOT / ".runtime-setup.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        if not (ROOT / ".venv/bin/python").is_file():
            if (ROOT / ".venv").is_symlink():
                raise SetupError(".venv не должна быть символьной ссылкой.")
            print("Создаю локальную среду Python…", flush=True)
            result = subprocess.run([sys.executable, "-m", "venv", str(ROOT / ".venv")], cwd=ROOT)
            if result.returncode:
                raise SetupError(
                    "Не удалось создать .venv. На Linux может потребоваться пакет python3-venv."
                )
        if not _python_state(pins):
            print("Устанавливаю закреплённые зависимости Python…", flush=True)
            _install(
                [
                    str(ROOT / ".venv/bin/python"),
                    "-m",
                    "pip",
                    "install",
                    "--force-reinstall",
                    "-r",
                    str(ROOT / "requirements.txt"),
                ]
            )
            if not _python_state(pins):
                raise SetupError("Локальная среда Python не прошла проверку после установки.")
        if not override and not _local_codex_ready(node_info):
            print("Устанавливаю локальный Codex из package-lock.json…", flush=True)
            _install([npm, "ci", "--ignore-scripts", "--no-audit", "--no-fund"])
            if not _local_codex_ready(node_info):
                raise SetupError(
                    "Codex runtime не установлен полностью; проверь Node.js/npm и повтори запуск."
                )


def _port(value):
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("порт должен быть числом от 0 до 65535") from exc
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("порт должен быть числом от 0 до 65535")
    return port


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Локальный веб-репетитор: подготовка зависимостей и запуск."
    )
    parser.add_argument("--no-open", action="store_true", help="не открывать браузер автоматически")
    parser.add_argument(
        "--port",
        type=_port,
        default=8765,
        help="loopback-порт (по умолчанию 8765; 0 выбирает свободный)",
    )
    parser.add_argument(
        "--check", action="store_true", help="проверить готовность без установки и запуска"
    )
    parser.add_argument(
        "--setup-only", action="store_true", help="подготовить зависимости без запуска сервера"
    )
    args = parser.parse_args(argv)
    try:
        if sys.platform not in {"darwin", "linux"}:
            raise SetupError("Веб-приложение поддерживает macOS и Linux.")
        if sys.version_info < (3, 10):
            raise SetupError("Нужен Python 3.10+; выбери его через TUTOR_PYTHON.")
        os.chdir(ROOT)
        pins = _pins()
        override = os.environ.get("TUTOR_CODEX_BIN")
        if override:
            executable = shutil.which(os.path.expanduser(override))
            if not executable:
                raise SetupError(
                    "TUTOR_CODEX_BIN должен указывать на существующий исполняемый файл."
                )
            npm, node_info = "", {}
            codex_ready = True
        else:
            npm, node_info = _node_tools()
            executable = str(ROOT / "node_modules/.bin/codex")
            codex_ready = _local_codex_ready(node_info)
        python_ready = _python_state(pins)
        if args.check:
            print(
                json.dumps(
                    {
                        "ready": python_ready and codex_ready,
                        "python_dependencies": python_ready,
                        "codex_runtime": codex_ready,
                        "custom_codex": bool(override),
                    },
                    ensure_ascii=False,
                )
            )
            return 0 if python_ready and codex_ready else 1
        _setup(pins, npm, node_info, override)
        if args.setup_only:
            print("Локальные зависимости готовы. Запуск: ./start.sh", flush=True)
            return 0
        os.environ["TUTOR_CODEX_BIN"] = executable
        command = [str(ROOT / ".venv/bin/python"), str(ROOT / "tools/serve.py"), str(args.port)]
        if not args.no_open:
            command.append("--open")
        os.execv(command[0], command)
    except (OSError, ValueError, KeyError, SetupError, subprocess.TimeoutExpired) as exc:
        print(f"Запуск не завершён: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
