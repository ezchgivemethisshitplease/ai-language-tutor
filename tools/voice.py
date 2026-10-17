"""Validate external voice reports without pretending to authenticate audio evidence."""

import math

TYPES = {
    "conversation",
    "fluency",
    "pronunciation",
    "exam-speaking",
    "listening",
    "weekly-speaking",
    "placement-speaking",
}
LEVEL_JUDGMENTS = {"on-level", "above", "below", "not_assessed"}


def _text(value, name, limit=12000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"invalid {name}")


def validate_pass(lesson_pass):
    if not isinstance(lesson_pass, dict) or lesson_pass.get("lesson_type") not in TYPES:
        raise ValueError("unsupported voice lesson")
    for field in (
        "pass_id",
        "student",
        "native_language",
        "target_language",
        "scenario",
        "activity_rules",
    ):
        _text(lesson_pass.get(field), field)
    if lesson_pass.get("level") not in {"A1", "A2", "B1", "B2", "C1"}:
        raise ValueError("invalid level")
    plan = lesson_pass.get("plan")
    if not isinstance(plan, list) or not 1 <= len(plan) <= 30:
        raise ValueError("voice plan needs 1–30 steps")
    for index, step in enumerate(plan, 1):
        if not isinstance(step, dict) or type(step.get("step")) is not int or step["step"] != index:
            raise ValueError("voice steps must be consecutive integers")
        _text(step.get("instruction"), "instruction")
        _text(step.get("complete_when"), "completion condition")
    return lesson_pass


def validate_report(lesson_pass, report):
    validate_pass(lesson_pass)
    if not isinstance(report, dict):
        raise ValueError("report must be an object")
    required = {
        "pass_id",
        "lesson",
        "completed",
        "completed_steps",
        "partial_reason",
        "duration_minutes",
        "performance",
        "corrections",
        "did_well",
        "pronunciation",
        "words_struggled",
        "level_impression",
    }
    if set(report) != required:
        raise ValueError("report fields do not match schema")
    if report["pass_id"] != lesson_pass["pass_id"]:
        raise ValueError("report belongs to another voice pass")
    if report["lesson"] != {
        "type": lesson_pass["lesson_type"],
        "scenario": lesson_pass["scenario"],
    }:
        raise ValueError("voice report does not match originating lesson")
    if type(report["completed"]) is not bool:
        raise ValueError("completion must be boolean")
    completed = report["completed_steps"]
    if (
        not isinstance(completed, list)
        or any(type(step) is not int for step in completed)
        or completed != sorted(set(completed))
        or not set(completed) <= set(range(1, len(lesson_pass["plan"]) + 1))
    ):
        raise ValueError("invalid completed steps")
    if report["completed"]:
        if report["partial_reason"] is not None or len(completed) != len(lesson_pass["plan"]):
            raise ValueError("completed report is missing steps or has a partial reason")
    else:
        _text(report["partial_reason"], "partial reason")
    duration = report["duration_minutes"]
    if (
        type(duration) not in {int, float}
        or not math.isfinite(duration)
        or not 0 <= duration <= 240
    ):
        raise ValueError("invalid duration")
    for field in ("performance", "did_well", "pronunciation"):
        _text(report[field], field)
    corrections = report["corrections"]
    if not isinstance(corrections, list) or len(corrections) > 3:
        raise ValueError("at most three corrections")
    for correction in corrections:
        if not isinstance(correction, dict) or set(correction) != {"said", "fix", "why"}:
            raise ValueError("invalid correction")
        for field in correction:
            _text(correction[field], field)
    words = report["words_struggled"]
    if not isinstance(words, list) or len(words) > 30:
        raise ValueError("invalid struggled words")
    for word in words:
        if not isinstance(word, dict) or set(word) != {"word", "sentence", "intended_meaning"}:
            raise ValueError("invalid struggled word")
        for field in word:
            _text(word[field], field)
    if report["level_impression"] not in LEVEL_JUDGMENTS:
        raise ValueError("invalid level impression")
    kind = lesson_pass["lesson_type"]
    if kind == "fluency" and corrections:
        raise ValueError("fluency reports cannot contain accuracy corrections")
    if (
        kind in {"fluency", "pronunciation", "listening"}
        and report["level_impression"] != "not_assessed"
    ):
        raise ValueError("this activity cannot assess a CEFR level")
    return {
        "valid": True,
        "pass_id": report["pass_id"],
        "completed": report["completed"],
        "evidence_source": "external_unverified_report",
        "calibrated": False,
        "pronunciation_measured": False,
        "automatic_writeback": False,
    }
