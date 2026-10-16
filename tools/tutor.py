#!/usr/bin/env python3
"""Agent-independent learner lifecycle. Use --help for reproducible commands."""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import activity
import learning
import srs
import storage

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "languages/english/curriculum/catalog.json"
KB = ROOT / "languages/english/l1-notes/russian.json"
ONBOARDING_RU = (
    "Будем учить английский. Объяснения начнутся на русском и будут меняться по результатам практики. "
    "В любой момент можно попросить: «Объясни по-русски». Первые задания дадут предварительный профиль; "
    "непроверенные навыки останутся неизвестными. Голосовые занятия можно подключить отдельно."
)


def emit(data):
    print(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False))


def learner_path():
    directory = srs.lang_dir()
    if directory.name != "english":
        raise ValueError(
            "The structured engine currently supports English; other language files are preserved"
        )
    return directory / "learner.json"


def reference(path):
    return storage.decode(path.read_bytes(), path)


def catalog():
    data = reference(CATALOG)
    learning.validate_catalog(data)
    return data


def state_load():
    state = storage.load(learner_path(), None)
    if state is None:
        raise ValueError("Run tutor.py init first; existing legacy files will be preserved")
    learning.validate_state(state)
    return state


def _text_write(path, value):
    # Use the same durable primitive as JSON, without interpreting Markdown as instructions.
    with storage.locked(path):
        storage._atomic_bytes(path, value.encode("utf-8"))


def initialize(args):
    if srs.STUDENT.is_symlink():
        raise ValueError("learner directory cannot be a symlink")
    srs.STUDENT.mkdir(parents=True, exist_ok=True)
    active = srs.STUDENT / "active.txt"
    if not active.exists():
        (srs.STUDENT / "english").mkdir(exist_ok=True)
        _text_write(active, "english\n")
    directory = srs.lang_dir()
    if directory.name != "english":
        raise ValueError(
            "Select the existing English learner explicitly; no other data was replaced"
        )
    for name in ("cards.json", "progress.json", "known_words.txt", "errors.md"):
        destination = directory / name
        with storage.locked(destination):
            if not destination.exists():
                template = (ROOT / "student.example/english" / name).read_text(encoding="utf-8")
                _text_write(destination, template)
    profile_path = srs.STUDENT / "profile.md"
    with storage.locked(profile_path):
        if not profile_path.exists():
            _text_write(
                profile_path, (ROOT / "student.example/profile.md").read_text(encoding="utf-8")
            )
    path = learner_path()
    with storage.locked(path):
        if path.exists():
            state = storage.load(path, None)
            learning.validate_state(state)
            return {
                "status": "existing_learner_preserved",
                "onboarding_ru": ONBOARDING_RU,
                "proficiency": state["proficiency"],
            }
        state = learning.migrate_legacy(
            storage.load(directory / "progress.json", {}), args.native_language
        )
        # Preserve existing profile preferences without evaluating Markdown or shell syntax.
        profile = profile_path.read_text(encoding="utf-8")
        for key in ("native_language", "daily_minutes", "voice_channel"):
            match = re.search(rf"^\- \*\*{key}:\*\*\s*([^<\n]+)", profile, re.MULTILINE)
            value = match[1].strip() if match else None
            if key == "native_language" and value and value != "—":
                state["native_language"] = value.lower()
            elif key == "daily_minutes" and value and value.isdecimal() and 5 <= int(value) <= 240:
                state["profile"][key] = int(value)
            elif key == "voice_channel" and value in {"none", "external"}:
                state["profile"][key] = value
        if args.daily_minutes is not None:
            state["profile"]["daily_minutes"] = args.daily_minutes
        if args.voice_channel is not None:
            state["profile"]["voice_channel"] = args.voice_channel
        learning.validate_state(state)
        storage.save(path, state)
    return {
        "status": "initialized",
        "onboarding_ru": ONBOARDING_RU,
        "proficiency": state["proficiency"],
        "legacy_preserved": True,
    }


def make_plan(state):
    return learning.plan(state, catalog(), due_count=len(srs.due_cards(srs.cards_path())))


def export_bundle(destination):
    """A consistent semantic backup of this active learner, excluding credentials/audio/cache."""
    directory = srs.lang_dir()
    destination = destination.absolute()
    if destination.resolve().is_relative_to(srs.STUDENT.resolve()):
        raise ValueError("export destination must be outside the live learner directory")
    # Take every application data lock in a fixed order. No app transaction holds two of these locks.
    from contextlib import ExitStack

    names = [
        "active.txt",
        "profile.md",
        f"{directory.name}/cards.json",
        f"{directory.name}/progress.json",
        f"{directory.name}/learner.json",
        f"{directory.name}/known_words.txt",
        f"{directory.name}/errors.md",
        "activity-results.json",
    ]
    with ExitStack() as stack:
        names.remove(f"{directory.name}/learner.json")
        names.insert(0, f"{directory.name}/learner.json")
        paths = [srs.STUDENT / name for name in names]
        for path in paths:
            stack.enter_context(storage.locked(path))
        files = {}
        for path in paths:
            if path.exists():
                if path.suffix == ".json":
                    files[path.relative_to(srs.STUDENT).as_posix()] = storage.load(path, None)
                else:
                    files[path.relative_to(srs.STUDENT).as_posix()] = path.read_text(
                        encoding="utf-8"
                    )
        data = {
            "format": "ai-language-tutor-export",
            "version": 1,
            "language": directory.name,
            "files": files,
        }
        validate_bundle(data)
        storage.save(destination, data)
    return {"exported": str(destination), "files": len(files), "contains_personal_data": True}


def validate_bundle(data):
    if (
        not isinstance(data, dict)
        or data.get("format") != "ai-language-tutor-export"
        or data.get("version") != 1
    ):
        raise ValueError("unsupported export")
    if data.get("language") != "english" or not isinstance(data.get("files"), dict):
        raise ValueError("unsupported export language/files")
    allowed = {
        "active.txt",
        "profile.md",
        "english/cards.json",
        "english/progress.json",
        "english/learner.json",
        "english/known_words.txt",
        "english/errors.md",
        "activity-results.json",
    }
    files = data["files"]
    if (
        not set(files) <= allowed
        or "english/learner.json" not in files
        or files.get("active.txt") != "english\n"
    ):
        raise ValueError("export contains invalid paths or missing learner")
    learning.validate_state(files["english/learner.json"])
    if "english/cards.json" in files:
        srs.validate_deck(files["english/cards.json"])
    for name, value in files.items():
        if name.endswith(".json"):
            if not isinstance(value, dict):
                raise ValueError("invalid JSON document in export")
        elif not isinstance(value, str):
            raise ValueError("invalid text document in export")
    # Known credential-shaped keys must never enter progress archives. Free text remains learner-owned.
    forbidden = {
        "api_key",
        "openai_api_key",
        "elevenlabs_api_key",
        "authorization",
        "access_token",
        "refresh_token",
    }

    def check(value):
        if isinstance(value, dict):
            if any(key.lower() in forbidden for key in value):
                raise ValueError("export contains credential fields")
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)

    check(files)


def import_bundle(source, destination):
    """Restore to a NEW directory, then atomically publish it. Never replace live progress."""
    import shutil
    import tempfile

    data = storage.load(source, None)
    validate_bundle(data)
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("import destination must not exist; choose a new directory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".tutor-import-", dir=destination.parent))
    try:
        for name, value in data["files"].items():
            path = stage / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if name.endswith(".json"):
                storage.save(path, value)
            else:
                _text_write(path, value)
        if destination.exists():
            raise ValueError("import destination appeared during import")
        os.rename(stage, destination)
        storage._sync_directory(destination.parent)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return {"imported": str(destination), "original_data_unchanged": True}


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--student-dir", type=Path, help="isolated learner folder; default: student/")
    sub = p.add_subparsers(dest="command", required=True)
    init = sub.add_parser(
        "init", help="idempotent setup/migration; never overwrite existing learner data"
    )
    init.add_argument("--native-language", default="russian")
    init.add_argument("--daily-minutes", type=int)
    init.add_argument("--voice-channel", choices=["external", "none"])
    configuration = sub.add_parser("configure")
    configuration.add_argument("--native-language")
    configuration.add_argument("--daily-minutes", type=int)
    configuration.add_argument("--voice-channel", choices=["external", "none"])
    debt = sub.add_parser("settle-debt")
    debt.add_argument("--session", required=True)
    debt.add_argument("--observation", required=True)
    for command in ("status", "plan", "start", "validate", "events"):
        sub.add_parser(command)
    for command in ("resume", "interrupt", "finish", "step", "attempt"):
        sp = sub.add_parser(command)
        sp.add_argument("--session", required=True)
        if command == "finish":
            sp.add_argument("--allow-incomplete", action="store_true")
        if command == "step":
            sp.add_argument("--step", required=True)
            sp.add_argument("--defer", action="store_true")
        if command == "attempt":
            sp.add_argument("--exercise", type=Path, required=True)
            sp.add_argument("--response-file", type=Path, required=True)
            sp.add_argument("--review", type=Path)
            sp.add_argument("--id", required=True, help="stable retry-safe attempt ID")
            sp.add_argument("--hints-used", action="store_true")
            sp.add_argument(
                "--error-tag",
                action="append",
                default=[],
                help="confirmed diagnosis; repeat for multiple tags",
            )
    items = sub.add_parser("items")
    items.add_argument("--level", choices=learning.LEVELS)
    items.add_argument("--limit", type=int, default=6)
    progress = sub.add_parser("progress")
    progress.add_argument("--target-level", choices=learning.LEVELS[1:], required=True)
    progress.add_argument("--human-review", type=Path, required=True)
    assess = sub.add_parser("assess")
    assess.add_argument("--level", choices=learning.LEVELS)
    gate = sub.add_parser("gate")
    gate.add_argument("--target-level", choices=learning.LEVELS[1:], required=True)
    export = sub.add_parser("export")
    export.add_argument("destination", type=Path)
    restore = sub.add_parser("import")
    restore.add_argument("source", type=Path)
    restore.add_argument("destination", type=Path, help="new directory only")
    recovery = sub.add_parser("recover")
    recovery.add_argument("document", choices=["learner.json", "cards.json", "progress.json"])
    voice = sub.add_parser("validate-voice")
    voice.add_argument("lesson_pass", type=Path)
    voice.add_argument("report", type=Path)
    prepared = sub.add_parser("validate-activity")
    prepared.add_argument("kind", choices=["quiz", "text", "dictation"])
    prepared.add_argument("path", type=Path)
    return p


def run(args):
    if args.student_dir:
        srs.STUDENT = args.student_dir.absolute()
    command = args.command
    if command == "init":
        return initialize(args)
    if command == "import":
        return import_bundle(args.source, args.destination)
    if command == "validate-voice":
        import voice

        return voice.validate_report(
            storage.load(args.lesson_pass, None), storage.load(args.report, None)
        )
    if command == "validate-activity":
        data = activity.validate(args.kind, storage.load(args.path, None))
        return {"valid": True, "activity_id": activity.identity(data)}
    if command == "recover":
        path = srs.lang_dir() / args.document
        # Validate candidate before replacing anything.
        backup = storage.load(path.with_name(path.name + ".bak"), None)
        if args.document == "learner.json":
            learning.validate_state(backup)
        elif args.document == "cards.json":
            srs.validate_deck(backup)
        elif not isinstance(backup, dict):
            raise ValueError("invalid backup")
        storage.restore_backup(path)
        return {"recovered": args.document, "previous_bytes_preserved": True}
    if command == "export":
        return export_bundle(args.destination)
    if command == "events":
        return storage.load(srs.STUDENT / "activity-results.json", {"receipts": {}})
    state = state_load()
    if command in {"status", "validate"}:
        srs.validate_deck(storage.load(srs.cards_path(), {"cards": []}))
        return {
            "valid": True,
            "proficiency": state["proficiency"],
            "active_session_id": state["active_session_id"],
            "language_policy": learning.language_policy(state),
            "observations": len(state["observations"]),
        }
    if command == "plan":
        return make_plan(state)
    if command == "items":
        return learning.assessment_items(
            state, reference(ROOT / "data/assessments.json"), args.level, args.limit
        )
    if command == "assess":
        return learning.assessment_summary(state, args.level)
    if command == "gate":
        return learning.promotion_eligibility(state, catalog(), args.target_level)
    with storage.transaction(learner_path(), None) as state:
        learning.validate_state(state)
        if command == "start":
            if state["active_session_id"]:
                session = state["sessions"][state["active_session_id"]]
                if session["status"] == "interrupted":
                    session = learning.resume_session(state, session["id"])
                result = {"resumed": True, "session": session}
            else:
                result = learning.start_session(state, make_plan(state))
        elif command == "attempt":
            exercise = storage.load(args.exercise, None)
            review = storage.load(args.review, None) if args.review else None
            response = args.response_file.read_text(encoding="utf-8")
            observation = learning.record_attempt(
                state,
                args.session,
                exercise,
                response,
                attempt_id=args.id,
                hints_used=args.hints_used,
                review=review,
                error_tags=args.error_tag,
                error_kb=reference(KB),
                catalog=catalog(),
            )
            result = {
                "attempt_id": observation["id"],
                "feedback": learning.feedback(observation, reference(KB), state["native_language"]),
            }
        elif command == "configure":
            if args.native_language is not None:
                state["native_language"] = args.native_language.lower()
            if args.daily_minutes is not None:
                state["profile"]["daily_minutes"] = args.daily_minutes
            if args.voice_channel is not None:
                state["profile"]["voice_channel"] = args.voice_channel
            result = {"profile": state["profile"], "native_language": state["native_language"]}
        elif command == "settle-debt":
            result = learning.settle_speaking_debt(state, args.session, args.observation)
        elif command == "progress":
            result = learning.accept_progression(
                state, catalog(), args.target_level, storage.load(args.human_review, None)
            )
        elif command == "step":
            result = learning.complete_step(state, args.session, args.step, args.defer)
        elif command == "finish":
            result = learning.finish_session(state, args.session, args.allow_incomplete)
        elif command == "interrupt":
            result = learning.interrupt_session(state, args.session)
        elif command == "resume":
            result = learning.resume_session(state, args.session)
        else:
            raise ValueError("unsupported command")
        learning.validate_state(state)
        return copy.deepcopy(result)


def main():
    # Coding-agent pipes use an explicit UTF-8 text contract.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        emit(run(parser().parse_args()))
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        # Avoid tracebacks containing imported learner responses or credentials.
        print(f"Tutor error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
