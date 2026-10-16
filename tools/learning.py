"""Deterministic learner evidence, constrained exercises and recoverable sessions.

All mutations operate on dicts; callers persist them inside storage.transaction().
The thresholds below are conservative *product heuristics*, not validated CEFR
cut scores, mastery probabilities or a calibrated psychometric model. Raw
observations are immutable evidence; estimates can always be reconstructed.
"""

from __future__ import annotations

import copy
import math
import re
import unicodedata
import uuid
from datetime import date, timedelta
from typing import Any

SCHEMA_VERSION = 1
LEVELS = ("A1", "A2", "B1", "B2", "C1")
DOMAINS = ("reading", "listening", "writing", "speaking", "grammar", "vocabulary", "pronunciation")
OPEN_TYPES = {"dialogue", "short_writing", "extended_writing", "spoken_response"}
CLOSED_TYPES = {
    "cloze",
    "translation",
    "transformation",
    "reorder",
    "error_correction",
    "reading_comprehension",
    "listening_comprehension",
    "minimal_pairs",
    "choice",
    "gap",
}
JUDGMENTS = {
    "incorrect",
    "correct",
    "correct_alternative",
    "unnatural",
    "stylistically_inappropriate",
    "contextually_inappropriate",
}
# Diversity and spacing prevent one easy item, retries or hints from gating progress.
POLICY = {
    "min_distinct_items": 4,
    "min_sessions": 3,
    "min_dates": 2,
    "min_success_rate": 0.8,
    "min_span_days": 7,
    "min_domains": 2,
    "min_production_items": 1,
    "review_after_days": 7,
    "assessment_min_items_per_domain": 4,
    "assessment_min_dates": 2,
    "assessment_success_rate": 0.8,
    "assessment_max_age_days": 90,
}


def _day(value: str | date | None = None) -> str:
    if value is None:
        return date.today().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        raise ValueError("date must be YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("date must be YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise ValueError("date must be YYYY-MM-DD")
    return value


def _text(value: Any, name: str, limit: int = 20000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{name} must be a nonempty string (max {limit})")
    return value


def _strings(value: Any, name: str, *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or (nonempty and not value):
        raise ValueError(f"{name} must be a list")
    for item in value:
        _text(item, name)
    if len(set(value)) != len(value):
        raise ValueError(f"{name} must not contain duplicates")
    return value


def new_state(native_language: str = "russian") -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "native_language": _text(native_language, "native_language", 80).lower(),
        "target_language": "english",
        "profile": {"daily_minutes": 30, "voice_channel": "none"},
        "proficiency": {"working_level": "A1", "status": "unassessed", "calibrated": False},
        "observations": [],
        "estimates": {"skills": {}, "grammar": {}, "vocabulary": {}},
        "errors": {},
        "sessions": {},
        "active_session_id": None,
        "objectives": [],
        "legacy": {},
    }


def migrate_legacy(progress: dict, native_language: str = "russian") -> dict:
    """Keep all original progress, but never infer evidence from completion/level."""
    if not isinstance(progress, dict):
        raise ValueError("legacy progress must be an object")
    state = new_state(native_language)
    state["legacy"] = {"progress": copy.deepcopy(progress)}
    if progress.get("level") in LEVELS:
        state["proficiency"].update(working_level=progress["level"], status="legacy_unverified")
    return state


def validate_state(state: dict) -> None:
    """Reject malformed canonical state rather than repairing silently."""
    if (
        not isinstance(state, dict)
        or type(state.get("schema_version")) is not int
        or state.get("schema_version") != SCHEMA_VERSION
    ):
        raise ValueError("unsupported learner schema_version")
    for key in ("native_language", "target_language"):
        _text(state.get(key), key, 80)
    profile = state.get("profile")
    if not isinstance(profile, dict) or profile.get("voice_channel") not in {"external", "none"}:
        raise ValueError("invalid learner profile/voice_channel")
    minutes = profile.get("daily_minutes")
    if type(minutes) is not int or not 5 <= minutes <= 240:
        raise ValueError("daily_minutes must be an integer from 5 to 240")
    proficiency = state.get("proficiency")
    if (
        not isinstance(proficiency, dict)
        or proficiency.get("working_level") not in LEVELS
        or proficiency.get("calibrated") is not False
    ):
        raise ValueError("invalid or unsupported calibrated proficiency claim")
    _strings(state.get("objectives"), "objectives")
    if not isinstance(state.get("legacy"), dict):
        raise ValueError("legacy must be an object")
    sessions = state.get("sessions")
    observations = state.get("observations")
    if not isinstance(sessions, dict) or not isinstance(observations, list):
        raise ValueError("sessions and observations have invalid types")
    ids: set[str] = set()
    for observation in observations:
        if not isinstance(observation, dict):
            raise ValueError("observation must be an object")
        oid = _text(observation.get("id"), "observation.id", 200)
        if oid in ids:
            raise ValueError("duplicate observation id")
        ids.add(oid)
        if observation.get("session_id") not in sessions:
            raise ValueError("observation references missing session")
        _day(_text(observation.get("date"), "observation.date", 10))
        validate_exercise(observation.get("exercise"))
        if not isinstance(observation.get("response"), str) or len(observation["response"]) > 20000:
            raise ValueError("invalid observation response")
        if type(observation.get("hints_used")) is not bool:
            raise ValueError("invalid hints_used")
        grade = observation.get("grade")
        if not isinstance(grade, dict) or grade.get("status") not in {
            "correct",
            "incorrect",
            "needs_review",
        }:
            raise ValueError("invalid observation grade")
        if grade.get("source") not in {"deterministic", "human", "llm", "pending"}:
            raise ValueError("invalid grade source")
        if grade.get("score") is not None and (
            type(grade["score"]) not in {float, int}
            or not math.isfinite(grade["score"])
            or not 0 <= grade["score"] <= 1
        ):
            raise ValueError("invalid observation score")
        _strings(observation.get("error_tags", []), "error_tags")
    active_ids = []
    for sid, session in sessions.items():
        if not isinstance(session, dict) or session.get("id") != sid:
            raise ValueError("invalid session identity")
        if session.get("status") not in {"active", "interrupted", "completed", "abandoned"}:
            raise ValueError("invalid session status")
        _day(_text(session.get("started_on"), "session.started_on", 10))
        _validate_plan(session.get("plan"))
        step_ids = {step["id"] for step in session["plan"]["steps"]}
        completed = _strings(session.get("completed_steps"), "completed_steps")
        deferred = _strings(session.get("deferred_steps", []), "deferred_steps")
        if not set(completed + deferred) <= step_ids or set(completed) & set(deferred):
            raise ValueError("invalid completed/deferred session steps")
        own_ids = _strings(session.get("observation_ids"), "observation_ids")
        if set(own_ids) != {o["id"] for o in observations if o["session_id"] == sid}:
            raise ValueError("session observation index mismatch")
        if type(session.get("speaking_debt")) is not bool:
            raise ValueError("speaking_debt must be boolean")
        if "sequence" in session and (
            type(session["sequence"]) is not int or session["sequence"] < 1
        ):
            raise ValueError("invalid session sequence")
        _strings(session.get("deferred_voice_skills", []), "deferred_voice_skills")
        settlements = session.get("debt_settlements", [])
        if not isinstance(settlements, list):
            raise ValueError("invalid speaking debt settlements")
        settled_skills = set()
        for settlement in settlements:
            if not isinstance(settlement, dict) or set(settlement) != {
                "skill_id",
                "observation_id",
            }:
                raise ValueError("invalid speaking debt settlement")
            skill = settlement["skill_id"]
            if skill not in session.get("deferred_voice_skills", []) or skill in settled_skills:
                raise ValueError("invalid or duplicate settled skill")
            evidence = next(
                (o for o in observations if o["id"] == settlement["observation_id"]), None
            )
            if (
                evidence is None
                or not _debt_evidence_eligible(state, session, evidence)
                or evidence["exercise"]["skill_id"] != skill
            ):
                raise ValueError("speaking debt settlement lacks matching later speech evidence")
            settled_skills.add(skill)
        if settlements and session["status"] not in {"completed", "abandoned"}:
            raise ValueError("active session cannot contain a settled historical debt")
        if settlements and session["speaking_debt"] != bool(
            set(session["deferred_voice_skills"]) - settled_skills
        ):
            raise ValueError("speaking debt flag disagrees with settlements")
        if session["status"] in {"active", "interrupted"}:
            active_ids.append(sid)
        if session["status"] == "completed" and set(completed + deferred) != step_ids:
            raise ValueError("completed session contains unfinished steps")
    sequences = [s["sequence"] for s in sessions.values() if "sequence" in s]
    if len(sequences) != len(set(sequences)):
        raise ValueError("duplicate session sequence")
    expected_active = active_ids[0] if len(active_ids) == 1 else None
    if len(active_ids) > 1 or state.get("active_session_id") != expected_active:
        raise ValueError("active session index mismatch")
    estimates = state.get("estimates")
    if not isinstance(estimates, dict) or any(
        not isinstance(estimates.get(k), dict) for k in ("skills", "grammar", "vocabulary")
    ):
        raise ValueError("invalid estimates")
    # Derived mastery is checked against evidence: a hand-edited estimate cannot unlock units.
    if estimates != _derive_estimates(observations):
        raise ValueError("estimates disagree with observations; rebuild from evidence")
    errors = state.get("errors")
    if not isinstance(errors, dict):
        raise ValueError("errors must be an object")
    expected_counts: dict[str, int] = {}
    for o in observations:
        for tag in o.get("error_tags", []):
            expected_counts[tag] = expected_counts.get(tag, 0) + 1
    if set(errors) != set(expected_counts):
        raise ValueError("error index mismatch")
    for tag, error in errors.items():
        if not isinstance(error, dict) or error.get("count") != expected_counts[tag]:
            raise ValueError("invalid recurring error count")
        _day(_text(error.get("last_seen"), "error.last_seen", 10))
        if error.get("confirmed_count") != sum(
            tag in o.get("error_tags", []) and _eligible(o) for o in observations
        ):
            raise ValueError("invalid confirmed recurring error count")
        confirmed_dates = [
            o["date"] for o in observations if tag in o.get("error_tags", []) and _eligible(o)
        ]
        if error.get("confirmed_last_seen") != max(confirmed_dates, default=None):
            raise ValueError("invalid confirmed error date")
        if set(error.get("observation_ids", [])) != {
            o["id"] for o in observations if tag in o.get("error_tags", [])
        }:
            raise ValueError("invalid error observation references")
        if set(error.get("skill_ids", [])) != {
            o["exercise"]["skill_id"] for o in observations if tag in o.get("error_tags", [])
        }:
            raise ValueError("invalid error skills")


def validate_catalog(catalog: dict) -> None:
    if (
        not isinstance(catalog, dict)
        or catalog.get("schema_version") != 1
        or not isinstance(catalog.get("units"), list)
        or not catalog["units"]
    ):
        raise ValueError("invalid curriculum catalog")
    ids = set()
    for unit in catalog["units"]:
        if not isinstance(unit, dict):
            raise ValueError("invalid catalog unit")
        uid = _text(unit.get("id"), "unit.id", 100)
        if uid in ids or unit.get("level") not in LEVELS:
            raise ValueError("duplicate unit or invalid level")
        ids.add(uid)
        _text(unit.get("title"), "unit.title")
        _strings(unit.get("prerequisites"), "prerequisites")
        domains = _strings(unit.get("domains"), "domains", nonempty=True)
        if not set(domains) <= set(DOMAINS):
            raise ValueError("unknown curriculum domain")
    edges = {u["id"]: u["prerequisites"] for u in catalog["units"]}
    visiting, visited = set(), set()

    def visit(uid: str) -> None:
        if uid in visiting:
            raise ValueError("curriculum prerequisite cycle")
        if uid in visited:
            return
        visiting.add(uid)
        for parent in edges[uid]:
            if parent not in edges:
                raise ValueError("unknown curriculum prerequisite")
            visit(parent)
        visiting.remove(uid)
        visited.add(uid)

    for uid in edges:
        visit(uid)


def validate_exercise(exercise: Any) -> None:
    if not isinstance(exercise, dict):
        raise ValueError("exercise must be an object")
    allowed = {
        "id",
        "type",
        "skill_id",
        "level",
        "domain",
        "prompt",
        "answers",
        "options",
        "rubric",
        "error_tags",
        "grammar_tags",
        "vocabulary",
        "mode",
        "step_id",
        "normalization",
        "audio_evidence",
        "exhaustive",
        "context",
        "explanation_ru",
    }
    if set(exercise) - allowed:
        raise ValueError(
            "unsupported exercise fields: " + ", ".join(sorted(set(exercise) - allowed))
        )
    for key in ("id", "skill_id", "prompt"):
        _text(exercise.get(key), key)
    curricular_id = re.fullmatch(r"(a1|a2|b1|b2|c1)-[0-9]{2}", exercise["skill_id"])
    if curricular_id and curricular_id.group(1).upper() != exercise.get("level"):
        raise ValueError("exercise level must match its curriculum skill")
    typ = exercise.get("type")
    if (
        typ not in OPEN_TYPES | CLOSED_TYPES
        or exercise.get("level") not in LEVELS
        or exercise.get("domain") not in DOMAINS
    ):
        raise ValueError("unknown exercise type, level or domain")
    mode = exercise.get("mode", "voice-required" if typ == "spoken_response" else "chat")
    if mode not in {"chat", "voice-required"}:
        raise ValueError("invalid exercise mode")
    if exercise["domain"] in {"speaking", "pronunciation"} and mode != "voice-required":
        raise ValueError("spoken production requires real voice mode")
    if typ in CLOSED_TYPES:
        answers = _strings(exercise.get("answers"), "answers", nonempty=True)
        if len(answers) > 100:
            raise ValueError("too many accepted answers")
        if "options" in exercise:
            options = _strings(exercise["options"], "options", nonempty=True)
            if not set(answers) <= set(options):
                raise ValueError("choice answers must be included in options")
    else:
        rubric = exercise.get("rubric")
        if not isinstance(rubric, dict) or not rubric or len(rubric) > 12:
            raise ValueError("open exercise requires explicit rubric criteria")
        for key, value in rubric.items():
            _text(key, "rubric criterion", 100)
            _text(value, "rubric description")
        if "answers" in exercise or exercise.get("exhaustive"):
            raise ValueError("open responses cannot have an exhaustive answer key")
    for key in ("error_tags", "grammar_tags", "vocabulary"):
        _strings(exercise.get(key, []), key)
    if "exhaustive" in exercise and type(exercise["exhaustive"]) is not bool:
        raise ValueError("exhaustive must be boolean")
    normalization = exercise.get("normalization", {})
    if (
        not isinstance(normalization, dict)
        or set(normalization) - {"case_sensitive", "ignore_terminal_punctuation"}
        or any(type(v) is not bool for v in normalization.values())
    ):
        raise ValueError("invalid answer normalization")
    for key in ("audio_evidence", "step_id", "context", "explanation_ru"):
        if key in exercise:
            _text(exercise[key], key)


def _normalize(answer: str, exercise: dict) -> str:
    settings = exercise.get("normalization", {})
    value = " ".join(unicodedata.normalize("NFKC", answer).replace("’", "'").split())
    if not settings.get("case_sensitive", False):
        value = value.casefold()
    if settings.get("ignore_terminal_punctuation", True):
        value = value.rstrip(".!? ")
    return value


def grade_answer(exercise: dict, response: str) -> dict:
    validate_exercise(exercise)
    if not isinstance(response, str) or len(response) > 20000:
        raise ValueError("response must be text (max 20000)")
    if exercise["type"] in OPEN_TYPES:
        return {
            "status": "needs_review",
            "score": None,
            "source": "pending",
            "reason": "Open production needs contextual rubric review; no exact-match penalty.",
        }
    normalized = _normalize(response, exercise)
    for accepted in exercise["answers"]:
        if normalized == _normalize(accepted, exercise):
            return {
                "status": "correct",
                "score": 1.0,
                "source": "deterministic",
                "accepted_answer": accepted,
            }
    if not response.strip() or exercise.get("exhaustive", False) or "options" in exercise:
        return {
            "status": "incorrect",
            "score": 0.0,
            "source": "deterministic",
            "reason": "Not an accepted answer for this constrained task.",
        }
    return {
        "status": "needs_review",
        "score": None,
        "source": "pending",
        "reason": "Unlisted wording may be a valid alternative; review meaning and context.",
    }


def _review_grade(exercise: dict, review: dict) -> dict:
    if not isinstance(review, dict) or set(review) - {
        "source",
        "judgment",
        "criteria",
        "rationale",
        "audio_evidence",
    }:
        raise ValueError("invalid rubric review")
    if review.get("source") not in {"human", "llm"} or review.get("judgment") not in JUDGMENTS:
        raise ValueError("review requires human/llm source and explicit judgment")
    _text(review.get("rationale"), "review rationale")
    rubric = exercise.get("rubric", {"accuracy": "The answer satisfies the task and context."})
    criteria = review.get("criteria")
    if not isinstance(criteria, dict) or set(criteria) != set(rubric):
        raise ValueError("review must score every rubric criterion")
    if any(
        type(v) not in {int, float} or not math.isfinite(v) or not 0 <= v <= 1
        for v in criteria.values()
    ):
        raise ValueError("rubric scores must be finite numbers from 0 to 1")
    needs_audio = exercise["domain"] in {"speaking", "pronunciation", "listening"}
    if needs_audio and not (exercise.get("audio_evidence") or review.get("audio_evidence")):
        raise ValueError("audio skills require a reference to actual audio evidence")
    score = sum(criteria.values()) / len(criteria)
    judgment = review["judgment"]
    if judgment == "incorrect" and score > 0.5:
        raise ValueError("incorrect judgment contradicts rubric score")
    if judgment in {"correct", "correct_alternative"} and score < 0.8:
        raise ValueError("correct judgment contradicts rubric score")
    return {
        "status": "correct" if judgment in {"correct", "correct_alternative"} else "incorrect",
        "score": score,
        "source": review["source"],
        "judgment": judgment,
        "criteria": copy.deepcopy(criteria),
        "rationale": review["rationale"],
        "audio_evidence": review.get("audio_evidence", exercise.get("audio_evidence")),
    }


def _eligible(observation: dict) -> bool:
    exercise, grade = observation["exercise"], observation["grade"]
    audio_ok = exercise["domain"] not in {"speaking", "pronunciation", "listening"} or bool(
        exercise.get("audio_evidence") or grade.get("audio_evidence")
    )
    return (
        not observation["hints_used"]
        and grade["source"] in {"deterministic", "human"}
        and grade["score"] is not None
        and audio_ok
    )


def _summary(observations: list[dict]) -> dict:
    eligible = [o for o in observations if _eligible(o)]
    # One first unassisted response per item/session; re-submission cannot wash out errors.
    independent: dict[tuple[str, str], dict] = {}
    for o in eligible:
        independent.setdefault((o["session_id"], o["exercise"]["id"]), o)
    evidence = list(independent.values())
    count = len(evidence)
    # Each item has equal weight; repeatedly passing one easy item cannot drown
    # out failures on other items. Latest *first response* per item is used.
    latest_by_item = {}
    for o in sorted(evidence, key=lambda item: item["date"]):
        latest_by_item[o["exercise"]["id"]] = o
    distinct = list(latest_by_item.values())
    successes = sum(o["grade"]["status"] == "correct" for o in distinct)
    rate = successes / len(distinct) if distinct else 0.0
    distinct_items = len(distinct)
    sessions = len({o["session_id"] for o in evidence})
    dates = len({o["date"] for o in evidence})
    # Wilson describes observed task success uncertainty only, not latent ability.
    interval = [0.0, 1.0]
    if distinct_items:
        n = distinct_items
        z = 1.96
        center = (rate + z * z / (2 * n)) / (1 + z * z / n)
        half = z * math.sqrt(rate * (1 - rate) / n + z * z / (4 * n * n)) / (1 + z * z / n)
        interval = [round(max(0, center - half), 4), round(min(1, center + half), 4)]
    latest = max((o["date"] for o in evidence), default=None)
    earliest = min((o["date"] for o in evidence), default=None)
    span = (
        (date.fromisoformat(latest) - date.fromisoformat(earliest)).days
        if latest and earliest
        else 0
    )
    domains = len({o["exercise"]["domain"] for o in evidence})
    production_items = len(
        {
            o["exercise"]["id"]
            for o in distinct
            if o["grade"]["status"] == "correct"
            and o["exercise"]["domain"] in {"writing", "speaking"}
            and o["exercise"]["type"]
            in OPEN_TYPES | {"transformation", "error_correction", "reorder", "translation"}
        }
    )
    mastered = (
        count > 0
        and distinct_items >= POLICY["min_distinct_items"]
        and sessions >= POLICY["min_sessions"]
        and dates >= POLICY["min_dates"]
        and rate >= POLICY["min_success_rate"]
        and span >= POLICY["min_span_days"]
        and domains >= POLICY["min_domains"]
        and production_items >= POLICY["min_production_items"]
    )
    return {
        "observations": len(observations),
        "eligible_attempts": count,
        "distinct_items": distinct_items,
        "sessions": sessions,
        "dates": dates,
        "span_days": span,
        "domains_sampled": domains,
        "production_items": production_items,
        "success_rate": round(rate, 4) if distinct_items else None,
        "observed_success_interval": interval,
        "mastered": mastered,
        "last_observed": latest,
        "review_due": (
            date.fromisoformat(latest) + timedelta(days=POLICY["review_after_days"])
        ).isoformat()
        if latest
        else None,
        "calibrated": False,
    }


def _derive_estimates(observations: list[dict]) -> dict:
    groups: dict[str, dict[str, list[dict]]] = {"skills": {}, "grammar": {}, "vocabulary": {}}
    for o in observations:
        exercise = o["exercise"]
        groups["skills"].setdefault(exercise["skill_id"], []).append(o)
        for group, field in (("grammar", "grammar_tags"), ("vocabulary", "vocabulary")):
            for tag in exercise.get(field, []):
                groups[group].setdefault(tag, []).append(o)
    return {
        group: {key: _summary(items) for key, items in values.items()}
        for group, values in groups.items()
    }


def rebuild_estimates(state: dict) -> None:
    """Explicit recovery for a stale derived cache, keeping every observation."""
    state["estimates"] = _derive_estimates(state["observations"])


def language_policy(state: dict, explicit_l1: bool = False) -> dict:
    if type(explicit_l1) is not bool:
        raise ValueError("explicit_l1 must be boolean")
    if explicit_l1:
        instruction = state["native_language"]
        support = "requested_l1"
    else:
        # Observed performance only: declared/legacy CEFR does not remove L1 support.
        demonstrated = [
            o for o in state["observations"] if _eligible(o) and o["grade"]["status"] == "correct"
        ]
        level = "A1"
        for candidate in LEVELS:
            samples = [o for o in demonstrated if o["exercise"]["level"] == candidate]
            if (
                len({o["exercise"]["id"] for o in samples}) >= 4
                and len({o["exercise"]["domain"] for o in samples}) >= 2
                and len({o["session_id"] for o in samples}) >= 2
            ):
                level = candidate
        instruction = state["native_language"] if level == "A1" else "english"
        support = (
            "l1_explanation"
            if level == "A1"
            else "brief_l1_available"
            if level in {"A2", "B1"}
            else "l1_rescue_available"
        )
    return {
        "instruction_language": instruction,
        "support": support,
        "material_language": state["target_language"],
        "explicit_l1_override_available": True,
        "basis": "unassisted observed performance; heuristic, not CEFR certification",
    }


def _validate_plan(session_plan: Any) -> None:
    if (
        not isinstance(session_plan, dict)
        or not isinstance(session_plan.get("steps"), list)
        or not session_plan["steps"]
    ):
        raise ValueError("session plan requires steps")
    _day(_text(session_plan.get("date"), "plan.date", 10))
    _strings(session_plan.get("deferred_voice_skills", []), "deferred_voice_skills")
    if "speaking_debt" in session_plan and type(session_plan["speaking_debt"]) is not bool:
        raise ValueError("plan speaking_debt must be boolean")
    ids = set()
    for step in session_plan["steps"]:
        if not isinstance(step, dict):
            raise ValueError("invalid session step")
        sid = _text(step.get("id"), "step.id", 100)
        if sid in ids:
            raise ValueError("duplicate session step")
        ids.add(sid)
        _text(step.get("type"), "step.type", 100)
        if step.get("mode") not in {"chat", "voice-required"}:
            raise ValueError("invalid step mode")
        if type(step.get("minutes")) is not int or not 1 <= step["minutes"] <= 240:
            raise ValueError("invalid step minutes")


def plan(
    state: dict,
    catalog: dict,
    due_count: int = 0,
    today: str | date | None = None,
    minutes: int | None = None,
    voice_available: bool | None = None,
) -> dict:
    validate_state(state)
    validate_catalog(catalog)
    day = _day(today)
    if type(due_count) is not int or due_count < 0:
        raise ValueError("due_count must be nonnegative integer")
    budget = state["profile"]["daily_minutes"] if minutes is None else minutes
    if type(budget) is not int or not 5 <= budget <= 240:
        raise ValueError("minutes must be integer from 5 to 240")
    voice = (
        state["profile"]["voice_channel"] == "external"
        if voice_available is None
        else voice_available
    )
    if type(voice) is not bool:
        raise ValueError("voice_available must be boolean")
    estimates = _derive_estimates(state["observations"])["skills"]
    mastered = {key for key, val in estimates.items() if val["mastered"]}
    units = {u["id"]: u for u in catalog["units"]}
    # Priority is lexicographic and documented: errors, overdue retrieval, new prerequisites.
    unresolved = []
    for error in state["errors"].values():
        if error.get("confirmed_count", 0) < 3:
            continue
        recovered = {
            o["session_id"]
            for o in state["observations"]
            if _eligible(o)
            and o["grade"]["status"] == "correct"
            and o["date"] > error["confirmed_last_seen"]
            and o["exercise"]["skill_id"] in error["skill_ids"]
        }
        if len(recovered) < 2:
            unresolved.append(error)
    recurrent = {skill for error in unresolved for skill in error["skill_ids"]}
    available = [
        u
        for u in catalog["units"]
        if set(u["prerequisites"]) <= mastered
        and u["id"] not in mastered
        and LEVELS.index(u["level"]) <= LEVELS.index(state["proficiency"]["working_level"])
    ]
    recurring_units = [
        units[s] for s in recurrent if s in units and set(units[s]["prerequisites"]) <= mastered
    ]
    overdue = [
        units[s]
        for s, e in estimates.items()
        if s in units and e["mastered"] and e["review_due"] <= day
    ]
    candidates = {u["id"]: u for u in recurring_units + overdue + available}
    recent = [
        o
        for o in state["observations"]
        if 0 <= (date.fromisoformat(day) - date.fromisoformat(o["date"])).days < 7
    ]
    counts = {domain: sum(o["exercise"]["domain"] == domain for o in recent) for domain in DOMAINS}

    def key(unit: dict) -> tuple:
        uid = unit["id"]
        return (
            0 if uid in recurrent else 1 if unit in overdue else 2,
            LEVELS.index(unit["level"]),
            min(counts[d] for d in unit["domains"]),
            uid,
        )

    ranked = sorted(candidates.values(), key=key)
    steps = []
    remaining = budget - 2
    if due_count:
        review_minutes = min(10, max(1, remaining // 3), due_count)
        steps.append(
            {
                "id": "review",
                "type": "srs_review",
                "mode": "chat",
                "minutes": review_minutes,
                "count": min(due_count, 30),
                "reason": "due retrieval before new material",
            }
        )
        remaining -= review_minutes
    selected = ranked[: 1 if budget < 45 else 2]
    debt = any(s.get("speaking_debt") for s in state["sessions"].values())
    deferred_voice_skills: list[str] = []
    if not selected:
        # No silent unlocking if a malformed or disconnected curriculum blocks progress.
        steps.append(
            {
                "id": "cumulative",
                "type": "cumulative_review",
                "mode": "chat",
                "minutes": max(1, remaining),
                "reason": "review demonstrated skills; no eligible new unit",
            }
        )
    else:
        allocation = max(1, remaining // len(selected))
        for i, unit in enumerate(selected):
            domains = sorted(unit["domains"], key=lambda d: (counts[d], DOMAINS.index(d)))
            usable = [d for d in domains if voice or d not in {"speaking", "pronunciation"}]
            domain = usable[0] if usable else "reading"
            if not voice and any(d in {"speaking", "pronunciation"} for d in domains):
                debt = True
                deferred_voice_skills.append(unit["id"])
            uid = unit["id"]
            reason = (
                "recurring_error"
                if uid in recurrent
                else "scheduled_retrieval"
                if unit in overdue
                else "prerequisites_met"
            )
            steps.append(
                {
                    "id": f"learn-{i + 1}",
                    "type": "remedial_lesson"
                    if uid in recurrent
                    else "retrieval_check"
                    if unit in overdue
                    else "skill_practice",
                    "skill_id": uid,
                    "domain": domain,
                    "level": unit["level"],
                    "mode": "voice-required" if domain in {"speaking", "pronunciation"} else "chat",
                    "minutes": allocation,
                    "reason": reason,
                    "title": unit["title"],
                    "error_tags": sorted(
                        tag
                        for tag, e in state["errors"].items()
                        if uid in e["skill_ids"] and e.get("confirmed_count", 0) >= 3
                    ),
                    "exercise_types": unit.get("exercise_types", []),
                }
            )
    steps.append(
        {
            "id": "wrap",
            "type": "reflection",
            "mode": "chat",
            "minutes": 2,
            "reason": "reflect and choose next objective",
        }
    )
    result = {
        "date": day,
        "steps": steps,
        "speaking_debt": debt,
        "deferred_voice_skills": deferred_voice_skills,
        "new_card_limit": 0 if due_count > 30 else 15,
        "language_policy": language_policy(state),
        "policy": copy.deepcopy(POLICY),
        "calibrated": False,
    }
    _validate_plan(result)
    return result


def start_session(
    state: dict, session_plan: dict, today: str | date | None = None, session_id: str | None = None
) -> dict:
    validate_state(state)
    _validate_plan(session_plan)
    if state["active_session_id"] is not None:
        raise ValueError("unfinished session exists; resume or abandon it explicitly")
    sid = str(uuid.uuid4()) if session_id is None else _text(session_id, "session_id", 200)
    if sid in state["sessions"]:
        raise ValueError("session_id already exists")
    sequence = max((s.get("sequence", 0) for s in state["sessions"].values()), default=0) + 1
    session = {
        "id": sid,
        "status": "active",
        "started_on": _day(today or session_plan["date"]),
        "sequence": sequence,
        "plan": copy.deepcopy(session_plan),
        "completed_steps": [],
        "deferred_steps": [],
        "observation_ids": [],
        "deferred_voice_skills": copy.deepcopy(session_plan.get("deferred_voice_skills", [])),
        "debt_settlements": [],
        "speaking_debt": bool(
            session_plan.get("deferred_voice_skills", session_plan.get("speaking_debt", False))
        ),
    }
    state["sessions"][sid] = session
    state["active_session_id"] = sid
    return copy.deepcopy(session)


def _session(state: dict, session_id: str, statuses: set[str] | None = None) -> dict:
    session = state["sessions"].get(session_id)
    if session is None or (statuses is not None and session["status"] not in statuses):
        raise ValueError("session does not exist or transition is invalid")
    return session


def interrupt_session(state: dict, session_id: str) -> dict:
    session = _session(state, session_id, {"active"})
    session["status"] = "interrupted"
    return copy.deepcopy(session)


def resume_session(state: dict, session_id: str) -> dict:
    session = _session(state, session_id, {"active", "interrupted"})
    if state["active_session_id"] != session_id:
        raise ValueError("another session is active")
    session["status"] = "active"
    return copy.deepcopy(session)


def complete_step(state: dict, session_id: str, step_id: str, deferred: bool = False) -> dict:
    session = _session(state, session_id, {"active"})
    step = next((s for s in session["plan"]["steps"] if s["id"] == step_id), None)
    if step is None:
        raise ValueError("unknown planned step")
    if type(deferred) is not bool:
        raise ValueError("deferred must be boolean")
    if deferred and step["mode"] != "voice-required":
        raise ValueError("only voice-required steps may be deferred")
    if step_id in session["completed_steps"] or step_id in session["deferred_steps"]:
        return copy.deepcopy(session)
    if step["mode"] == "voice-required":
        evidence = [
            o
            for o in state["observations"]
            if o["session_id"] == session_id
            and o["exercise"].get("step_id") == step_id
            and (o["exercise"].get("audio_evidence") or o["grade"].get("audio_evidence"))
        ]
        if not deferred and not evidence:
            raise ValueError("voice step requires actual audio evidence or explicit deferral")
    session["deferred_steps" if deferred else "completed_steps"].append(step_id)
    if deferred and step["mode"] == "voice-required":
        session["speaking_debt"] = True
        if step.get("skill_id") and step["skill_id"] not in session.setdefault(
            "deferred_voice_skills", []
        ):
            session["deferred_voice_skills"].append(step["skill_id"])
    return copy.deepcopy(session)


def finish_session(state: dict, session_id: str, allow_incomplete: bool = False) -> dict:
    session = _session(state, session_id, {"active", "interrupted"})
    if type(allow_incomplete) is not bool:
        raise ValueError("allow_incomplete must be boolean")
    pending = {s["id"] for s in session["plan"]["steps"]} - set(
        session["completed_steps"] + session["deferred_steps"]
    )
    if pending and not allow_incomplete:
        raise ValueError("session has unfinished steps: " + ", ".join(sorted(pending)))
    if allow_incomplete and pending:
        session["status"] = "abandoned"
        session["unfinished_steps"] = sorted(pending)
        for step in session["plan"]["steps"]:
            if step["mode"] == "voice-required" and step["id"] in pending:
                session["speaking_debt"] = True
                if step.get("skill_id") and step["skill_id"] not in session.setdefault(
                    "deferred_voice_skills", []
                ):
                    session["deferred_voice_skills"].append(step["skill_id"])
    else:
        session["status"] = "completed"
    state["active_session_id"] = None
    return copy.deepcopy(session)


def record_attempt(
    state: dict,
    session_id: str,
    exercise: dict,
    response: str,
    *,
    attempt_id: str | None = None,
    hints_used: bool = False,
    review: dict | None = None,
    observed_at: str | date | None = None,
    error_kb: dict | None = None,
    error_tags: list[str] | None = None,
    catalog: dict | None = None,
    today: str | date | None = None,
) -> dict:
    """Record first-hand task evidence; LLM judgments remain explicitly provisional.

    attempt_id is an idempotency key: identical retries return existing evidence,
    while a changed payload under the same key is rejected.
    """
    validate_state(state)
    validate_exercise(exercise)
    if catalog is not None:
        validate_catalog(catalog)
        unit = next((u for u in catalog["units"] if u["id"] == exercise["skill_id"]), None)
        if unit is None or unit["level"] != exercise["level"]:
            raise ValueError("exercise skill/level does not match curriculum catalog")
    session = _session(state, session_id, {"active"})
    if type(hints_used) is not bool:
        raise ValueError("hints_used must be boolean")
    tags = _strings(error_tags or [], "error_tags")
    if error_kb is not None:
        if not isinstance(error_kb, dict) or not isinstance(error_kb.get("errors"), list):
            raise ValueError("invalid L1 error knowledge base")
        kb = {entry["id"]: entry for entry in error_kb["errors"]}
        if not set(tags) <= set(kb):
            raise ValueError("unknown L1 error tag")
        if any(kb[tag].get("evidence_required") == "audio" for tag in tags) and not (
            exercise.get("audio_evidence") or (review or {}).get("audio_evidence")
        ):
            raise ValueError("pronunciation diagnosis requires actual audio evidence")
    elif tags:
        raise ValueError("diagnosed error tags require a validated knowledge base")
    if "step_id" in exercise:
        planned = next(
            (s for s in session["plan"]["steps"] if s["id"] == exercise["step_id"]), None
        )
        if planned is None or (
            planned.get("skill_id") and planned["skill_id"] != exercise["skill_id"]
        ):
            raise ValueError("exercise does not match planned step")
    grade = grade_answer(exercise, response)
    if review is not None:
        grade = _review_grade(exercise, review)
    if tags and grade["status"] != "incorrect":
        raise ValueError("error diagnosis requires an observed incorrect answer")
    day = _day(observed_at or session["started_on"])
    if day < session["started_on"]:
        raise ValueError("attempt cannot predate its session")
    if day > _day(today):
        raise ValueError("attempt cannot be in the future")
    oid = str(uuid.uuid4()) if attempt_id is None else _text(attempt_id, "attempt_id", 200)
    observation = {
        "id": oid,
        "session_id": session_id,
        "date": day,
        "exercise": copy.deepcopy(exercise),
        "response": response,
        "hints_used": hints_used,
        "grade": grade,
        "error_tags": tags,
    }
    existing = next((o for o in state["observations"] if o["id"] == oid), None)
    if existing is not None:
        if existing != observation:
            raise ValueError("attempt_id reused with different payload")
        return copy.deepcopy(existing)
    # Do not permit the same stable item ID to change meaning or difficulty.
    for previous in state["observations"]:
        if previous["exercise"]["id"] == exercise["id"]:
            old = {
                k: v
                for k, v in previous["exercise"].items()
                if k not in {"step_id", "audio_evidence"}
            }
            new = {k: v for k, v in exercise.items() if k not in {"step_id", "audio_evidence"}}
            if old != new:
                raise ValueError("stable exercise id has a different definition")
            break
    state["observations"].append(observation)
    session["observation_ids"].append(oid)
    for tag in tags:
        error = state["errors"].setdefault(
            tag,
            {
                "count": 0,
                "confirmed_count": 0,
                "confirmed_last_seen": None,
                "first_seen": day,
                "last_seen": day,
                "skill_ids": [],
                "observation_ids": [],
            },
        )
        error["count"] += 1
        if _eligible(observation):
            error["confirmed_count"] += 1
            error["confirmed_last_seen"] = max(error["confirmed_last_seen"] or day, day)
        error["last_seen"] = max(error["last_seen"], day)
        error["observation_ids"].append(oid)
        if exercise["skill_id"] not in error["skill_ids"]:
            error["skill_ids"].append(exercise["skill_id"])
    rebuild_estimates(state)
    return copy.deepcopy(observation)


def feedback(
    observation: dict, error_kb: dict | None = None, native_language: str = "russian"
) -> dict:
    """Specific KB-backed remediation; no automatic diagnosis from substring cues."""
    grade = observation["grade"]
    russian = native_language.lower() in {"russian", "ru", "русский"}
    messages = {
        "correct": "Ответ принят. Используйте эту конструкцию в новом контексте.",
        "incorrect": "Попробуйте исправить ответ. Сравните смысл и форму с условием.",
        "needs_review": "Нужна проверка по контексту: другой вариант формулировки может быть правильным.",
    }
    result = {
        "status": grade["status"],
        "message": messages[grade["status"]]
        if russian
        else {
            "correct": "Answer accepted. Use the form in a new context.",
            "incorrect": "Try a correction using the task context.",
            "needs_review": "Contextual review needed: alternative wording may be valid.",
        }[grade["status"]],
        "remediation": [],
    }
    kb = {e["id"]: e for e in (error_kb or {}).get("errors", [])}
    for tag in observation.get("error_tags", []):
        if tag in kb:
            entry = kb[tag]
            result["remediation"].append(
                {
                    "error_tag": tag,
                    "feedback": entry.get("feedback_ru", "")
                    if russian
                    else "Revisit the contrasting examples.",
                    "explanation": entry.get("explanation_ru", "") if russian else "",
                    "examples": entry.get("examples", []),
                    "exercise_types": entry.get("exercise_types", []),
                    "remedial_tags": entry.get("remedial_tags", []),
                    "skill_ids": entry.get("skill_ids", []),
                }
            )
    if grade.get("judgment"):
        result["judgment"] = grade["judgment"]
        result["rationale"] = grade["rationale"]
    return result


def assessment_summary(
    state: dict, level: str | None = None, today: str | date | None = None
) -> dict:
    validate_state(state)
    if level is not None and level not in LEVELS:
        raise ValueError("unknown assessment level")
    day = _day(today)
    cutoff = (
        date.fromisoformat(day) - timedelta(days=POLICY["assessment_max_age_days"])
    ).isoformat()
    relevant = [
        o
        for o in state["observations"]
        if (level is None or o["exercise"]["level"] == level) and cutoff <= o["date"] <= day
    ]
    domains = {d: _summary([o for o in relevant if o["exercise"]["domain"] == d]) for d in DOMAINS}
    assessed = [d for d, summary in domains.items() if summary["eligible_attempts"]]
    required = {"reading", "listening", "writing", "speaking"}
    missing = sorted(required - set(assessed))
    return {
        "level_sampled": level,
        "domains": domains,
        "unassessed_domains": sorted(set(DOMAINS) - set(assessed)),
        "missing_core_domains": missing,
        "status": "insufficient_evidence" if missing else "provisional_profile",
        "calibrated": False,
        "cefr_certification": False,
        "window_days": POLICY["assessment_max_age_days"],
        "warning_ru": "Это предварительный профиль по выполненным заданиям, а не подтверждённый уровень CEFR. Непроверенные навыки остаются неизвестными.",
    }


def promotion_eligibility(
    state: dict, catalog: dict, target_level: str, today: str | date | None = None
) -> dict:
    """Readiness for an internal curriculum step, never a CEFR certificate/promotion."""
    validate_catalog(catalog)
    if target_level not in LEVELS or target_level == "A1":
        raise ValueError("target_level must be A2..C1")
    current = LEVELS[LEVELS.index(target_level) - 1]
    summary = assessment_summary(state, current, today)
    reasons = []
    units = [u["id"] for u in catalog["units"] if u["level"] == current]
    mastery = _derive_estimates(state["observations"])["skills"]
    pending = [uid for uid in units if not mastery.get(uid, {}).get("mastered", False)]
    if not units or pending:
        reasons.append("curriculum_mastery_incomplete")
    for domain in ("reading", "listening", "writing", "speaking"):
        evidence = summary["domains"][domain]
        if (
            evidence["distinct_items"] < POLICY["assessment_min_items_per_domain"]
            or evidence["dates"] < POLICY["assessment_min_dates"]
            or (evidence["success_rate"] or 0) < POLICY["assessment_success_rate"]
        ):
            reasons.append("insufficient_" + domain + "_evidence")
    if state["proficiency"]["working_level"] != current:
        reasons.append("target_is_not_next_working_level")
    return {
        "eligible": not reasons,
        "target_level": target_level,
        "reasons": reasons,
        "pending_units": pending,
        "action": "human_review_required" if not reasons else "collect_missing_evidence",
        "automatic_promotion": False,
        "calibrated": False,
        "cefr_certification": False,
    }


def assessment_items(
    state: dict, bank: dict, level: str | None = None, limit: int = 6
) -> list[dict]:
    """Return unseen, domain-balanced authored tasks without fabricating placement.

    A caller may sample a different level explicitly. The bank is intentionally
    small and cannot establish CEFR proficiency or assess missing modalities.
    """
    validate_state(state)
    chosen_level = level or state["proficiency"]["working_level"]
    if chosen_level not in LEVELS or type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("invalid assessment level or limit")
    if (
        not isinstance(bank, dict)
        or bank.get("schema_version") != 1
        or not isinstance(bank.get("items"), list)
        or bank.get("calibrated") is not False
    ):
        raise ValueError("unsupported or falsely calibrated assessment bank")
    ids = set()
    for item in bank["items"]:
        validate_exercise(item)
        if item["id"] in ids:
            raise ValueError("duplicate assessment item id")
        ids.add(item["id"])
    seen = {o["exercise"]["id"] for o in state["observations"]}
    items = [item for item in bank["items"] if item["level"] == chosen_level]
    selected: list[dict] = []
    while items and len(selected) < limit:
        domain_counts = {
            domain: sum(item["domain"] == domain for item in selected) for domain in DOMAINS
        }
        item = min(
            items, key=lambda item: (item["id"] in seen, domain_counts[item["domain"]], item["id"])
        )
        items.remove(item)
        selected.append(item)
    return copy.deepcopy(selected)


def accept_progression(
    state: dict, catalog: dict, target_level: str, review: dict, today: str | date | None = None
) -> dict:
    """Record an explicitly human-reviewed internal curriculum transition.

    This is a local record of reviewer attestation, not identity verification or
    independent certification. Automated/LLM-only recommendations cannot pass.
    """
    if (
        not isinstance(review, dict)
        or set(review) != {"source", "reviewer", "rationale", "evidence_reference"}
        or review.get("source") != "human"
    ):
        raise ValueError("progression requires an explicit human review")
    for key in ("reviewer", "rationale", "evidence_reference"):
        _text(review.get(key), key)
    eligibility = promotion_eligibility(state, catalog, target_level, today)
    if not eligibility["eligible"]:
        raise ValueError("progression evidence incomplete: " + ", ".join(eligibility["reasons"]))
    decision = {
        "date": _day(today),
        "from_level": state["proficiency"]["working_level"],
        "to_level": target_level,
        "review": copy.deepcopy(review),
        "eligibility": eligibility,
        "observations_considered": len(state["observations"]),
        "cefr_certification": False,
    }
    proficiency = state["proficiency"]
    proficiency.setdefault("decisions", []).append(decision)
    proficiency["working_level"] = target_level
    proficiency["status"] = "human_reviewed_curriculum_progression"
    return copy.deepcopy(decision)


def _debt_evidence_eligible(state: dict, origin: dict, observation: dict) -> bool:
    exercise = observation["exercise"]
    evidence_session = state["sessions"].get(observation["session_id"])
    if evidence_session is None or evidence_session["id"] == origin["id"]:
        return False
    if observation["date"] < origin["started_on"]:
        return False
    # An explicit sequence supports same-day make-up work. Legacy sessions
    # without a sequence require a later calendar day to establish chronology.
    if "sequence" in origin and "sequence" in evidence_session:
        if type(origin["sequence"]) is not int or type(evidence_session["sequence"]) is not int:
            return False
        later = evidence_session["sequence"] > origin["sequence"]
    else:
        later = observation["date"] > origin["started_on"]
    return (
        later
        and _eligible(observation)
        and exercise["domain"] in {"speaking", "pronunciation"}
        and exercise.get(
            "mode", "voice-required" if exercise["type"] == "spoken_response" else "chat"
        )
        == "voice-required"
        and bool(exercise.get("audio_evidence") or observation["grade"].get("audio_evidence"))
    )


def settle_speaking_debt(state: dict, origin_session_id: str, observation_id: str) -> dict:
    """Link a later, matching observed speech attempt to a deferred skill.

    Settlement records actual practice, not mastery or a fabricated completion
    of the original voice activity. The original deferral remains in history.
    Human/checked audio evidence is required; LLM-only or typed evidence cannot
    settle debt. A genuine incorrect spoken attempt may settle practice debt.
    """
    validate_state(state)
    origin = _session(state, origin_session_id, {"completed", "abandoned"})
    observation = next((o for o in state["observations"] if o["id"] == observation_id), None)
    if observation is None or not _debt_evidence_eligible(state, origin, observation):
        raise ValueError("debt settlement requires eligible later real speech evidence")
    skill = observation["exercise"]["skill_id"]
    debts = origin.get("deferred_voice_skills", [])
    if skill not in debts:
        raise ValueError("speech evidence does not match a deferred skill")
    settlements = origin.setdefault("debt_settlements", [])
    previous = next((entry for entry in settlements if entry["skill_id"] == skill), None)
    if previous is not None:
        if previous["observation_id"] != observation_id:
            raise ValueError("deferred skill already settled by different evidence")
        return copy.deepcopy(origin)
    settlements.append({"skill_id": skill, "observation_id": observation_id})
    origin["speaking_debt"] = bool(set(debts) - {entry["skill_id"] for entry in settlements})
    return copy.deepcopy(origin)
