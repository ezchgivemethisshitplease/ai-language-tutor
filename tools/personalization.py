"""Explicit owner settings and confirmed memories, separate from learning evidence.

Free text is contextual data, never tool authority. Model proposals cannot become
active memories without an owner action (OWASP LLM01 prompt-injection guidance).
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, TypedDict


class AccountPreferences(TypedDict):
    dialect: str
    register: str
    explanation_language: str
    explanation_style: str
    grammar_terminology: str
    correction_style: str
    topics: list[str]
    notes: str


ENUMS = {
    "dialect": {"us", "uk", "international"},
    "register": {"informal", "neutral", "professional"},
    "explanation_language": {"native", "english"},
    "explanation_style": {"plain", "detailed"},
    "grammar_terminology": {"minimal", "standard"},
    "correction_style": {"balanced", "gentle", "detailed"},
}
OVERRIDES = set(ENUMS) - {"explanation_language"}
DEFAULTS: AccountPreferences = {
    "dialect": "us",
    "register": "informal",
    "explanation_language": "native",
    "explanation_style": "plain",
    "grammar_terminology": "minimal",
    "correction_style": "balanced",
    "topics": [],
    "notes": "",
}
CONTEXT: dict[str, Any] = {
    "title": "",
    "goal": "",
    "topics": [],
    "scenario": "",
    "notes": "",
    "direction_id": None,
    "mode": "guided",
    "challenge": "adaptive",
    **dict.fromkeys(OVERRIDES),
}
DIRECTIONS: list[dict[str, Any]] = [
    {
        "id": "everyday",
        "title": "На каждый день",
        "description": "Обычные ситуации и живой разговор",
        "goal": "Увереннее общаться в повседневных ситуациях",
        "topics": [],
        "mode": "conversation",
        "scenario": "",
        "register": "informal",
    },
    {
        "id": "work",
        "title": "Работа",
        "description": "Сообщения, встречи и рабочие объяснения",
        "goal": "Понятно общаться по рабочим вопросам",
        "topics": [],
        "mode": "guided",
        "scenario": "",
        "register": "professional",
    },
    {
        "id": "travel",
        "title": "Поездки",
        "description": "Разобраться на месте и договориться",
        "goal": "Решать практические вопросы в поездках",
        "topics": [],
        "mode": "roleplay",
        "scenario": "Ситуация в поездке, которую выберет ученик",
        "register": "neutral",
    },
    {
        "id": "interests",
        "title": "Мои интересы",
        "description": "Разговор о темах, которые выберете вы",
        "goal": "Обсуждать интересующие меня темы",
        "topics": [],
        "mode": "conversation",
        "scenario": "",
        "register": "informal",
    },
    {
        "id": "custom",
        "title": "Своё направление",
        "description": "Своя цель и формат практики",
        "goal": "",
        "topics": [],
        "mode": "guided",
        "scenario": "",
        "register": None,
    },
]


class Conflict(ValueError):
    """The owner edited a stale settings snapshot."""


def stamp():
    return datetime.now(timezone.utc).isoformat()


def _text(value, limit, empty=True):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise ValueError("invalid personalization text")
    return value


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("invalid personalization identifier")
    return value


def _topics(value):
    if not isinstance(value, list) or len(value) > 12:
        raise ValueError("invalid topics")
    for item in value:
        _text(item, 120, False)
    if len(value) != len(set(value)):
        raise ValueError("duplicate topics")


def preferences(patch=None, base=None):
    result: dict[str, Any] = copy.deepcopy(base or dict(DEFAULTS))
    if patch is None:
        patch = {}
    if not isinstance(patch, dict) or set(patch) - set(DEFAULTS):
        raise ValueError("unknown account preference")
    result.update(copy.deepcopy(patch))
    for key, choices in ENUMS.items():
        if not isinstance(result.get(key), str) or result[key] not in choices:
            raise ValueError("invalid account preference")
    _topics(result.get("topics"))
    _text(result.get("notes"), 1200)
    return result


def context(patch=None, base=None, direction_id=None):
    result = copy.deepcopy(base or CONTEXT)
    if direction_id is not None:
        direction = next((d for d in DIRECTIONS if d["id"] == direction_id), None)
        if direction is None:
            raise ValueError("unknown learning direction")
        result.update(
            {
                k: copy.deepcopy(direction[k])
                for k in ("title", "goal", "topics", "mode", "scenario", "register")
            }
        )
        result["direction_id"] = direction_id
    if patch is None:
        patch = {}
    if not isinstance(patch, dict) or set(patch) - set(CONTEXT):
        raise ValueError("unknown conversation setting")
    result.update(copy.deepcopy(patch))
    for key, limit in {"title": 100, "goal": 800, "scenario": 1200, "notes": 1600}.items():
        _text(result.get(key), limit)
    _topics(result.get("topics"))
    if result.get("mode") not in {
        "guided",
        "conversation",
        "roleplay",
        "writing",
        "diagnostic",
    } or result.get("challenge") not in {"adaptive", "easy", "stretch"}:
        raise ValueError("invalid conversation mode/challenge")
    if result.get("direction_id") is not None and result["direction_id"] not in {
        d["id"] for d in DIRECTIONS
    }:
        raise ValueError("invalid direction")
    for key in OVERRIDES:
        if result.get(key) is not None and (
            not isinstance(result[key], str) or result[key] not in ENUMS[key]
        ):
            raise ValueError("invalid conversation preference")
    return result


def effective(account, chat_context):
    result = preferences(account)
    for key in OVERRIDES:
        if chat_context.get(key) is not None:
            result[key] = chat_context[key]
    return result


def empty():
    return {
        "schema": 1,
        "revision": 0,
        "account_preferences": preferences(),
        "memories": [],
        "pending_memories": [],
        "audit": [],
    }


def read(history):
    return copy.deepcopy(history.get("personalization", empty()))


def _source(source, conversations):
    if not isinstance(source, dict) or source.get("type") not in {
        "user_setting",
        "explicit_message",
    }:
        raise ValueError("invalid memory provenance")
    if set(source) != (
        {"type"}
        if source["type"] == "user_setting"
        else {"type", "conversation_id", "message_id", "evidence"}
    ):
        raise ValueError("invalid memory source fields")
    if source["type"] == "explicit_message":
        cid = _id(source.get("conversation_id"))
        mid = _text(source.get("message_id"), 200, False)
        evidence = _text(source.get("evidence"), 600, False)
        messages = conversations.get(cid, {}).get("messages", [])
        if not any(
            m["id"] == mid and m["role"] == "user" and evidence in m["text"] for m in messages
        ):
            raise ValueError("memory needs exact evidence from a stored human message")


def validate(data, conversations):
    if not isinstance(data, dict) or set(data) != set(empty()) or data.get("schema") != 1:
        raise ValueError("invalid personalization document")
    if type(data.get("revision")) is not int or data["revision"] < 0:
        raise ValueError("invalid settings revision")
    if not isinstance(data.get("account_preferences"), dict) or set(
        data["account_preferences"]
    ) != set(DEFAULTS):
        raise ValueError("incomplete account preferences")
    preferences(data["account_preferences"])
    seen = set()
    for field, limit in (("memories", 100), ("pending_memories", 50)):
        items = data.get(field)
        if not isinstance(items, list) or len(items) > limit:
            raise ValueError("invalid memory collection")
        for memory in items:
            if not isinstance(memory, dict) or set(memory) - {
                "id",
                "text",
                "scope",
                "conversation_id",
                "source",
                "created_at",
                "updated_at",
                "confirmed_at",
            }:
                raise ValueError("invalid memory")
            mid = _id(memory.get("id"))
            if mid in seen:
                raise ValueError("duplicate memory")
            seen.add(mid)
            _text(memory.get("text"), 600, False)
            scope = memory.get("scope")
            cid = memory.get("conversation_id")
            if (
                scope not in {"account", "conversation"}
                or (scope == "conversation" and cid not in conversations)
                or (scope == "account" and cid is not None)
            ):
                raise ValueError("invalid memory scope")
            _source(memory.get("source"), conversations)
            _text(memory.get("created_at"), 80, False)
            if field == "memories":
                _text(memory.get("updated_at"), 80, False)
    audit = data.get("audit")
    if not isinstance(audit, list) or len(audit) > 500:
        raise ValueError("invalid settings audit")
    for event in audit:
        if not isinstance(event, dict) or set(event) - {
            "at",
            "operation",
            "actor",
            "id",
            "before_digest",
            "after_digest",
        }:
            raise ValueError("invalid settings audit event")
        for value in event.values():
            _text(value, 128)


def check_revision(data, expected):
    if expected is not None and (type(expected) is not int or expected != data["revision"]):
        raise Conflict("Настройки изменились. Обновите страницу перед сохранением.")


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def audit(data, operation, before, after, *, actor="user", ident="settings"):
    data["revision"] += 1
    data["audit"].append(
        {
            "at": stamp(),
            "operation": operation,
            "actor": actor,
            "id": ident,
            "before_digest": _digest(before),
            "after_digest": _digest(after),
        }
    )
    del data["audit"][:-500]


def snapshot(history):
    data = read(history)
    directions = copy.deepcopy(DIRECTIONS)
    for direction in directions:
        direction["context"] = context(direction_id=direction["id"])
    return {
        key: data[key]
        for key in ("revision", "account_preferences", "memories", "pending_memories")
    } | {"directions": directions}


def selected_memories(history, cid):
    return [
        copy.deepcopy(m)
        for m in read(history)["memories"]
        if m["scope"] == "account" or m["conversation_id"] == cid
    ]


def propose(history, cid, args):
    data = read(history)
    text = _text(args.get("text"), 600, False)
    scope = args.get("scope", "conversation")
    source = {
        "type": "explicit_message",
        "conversation_id": cid,
        "message_id": args.get("source_message_id"),
        "evidence": args.get("evidence"),
    }
    _source(source, history["conversations"])
    if scope not in {"account", "conversation"}:
        raise ValueError("invalid memory scope")
    body = {
        "text": text,
        "scope": scope,
        "conversation_id": cid if scope == "conversation" else None,
        "source": source,
    }
    mid = "memory-" + _digest(body)[:32]
    if not any(m["id"] == mid for field in ("memories", "pending_memories") for m in data[field]):
        if len(data["pending_memories"]) >= 50:
            raise ValueError("pending memory limit reached")
        data["pending_memories"].append({"id": mid, **body, "created_at": stamp()})
        audit(data, "propose_memory", None, body, actor="assistant_proposal", ident=mid)
        validate(data, history["conversations"])
        history["personalization"] = data
    return {
        "proposed": True,
        "saved": False,
        "id": mid,
        "requires_confirmation": True,
        "instruction": "This is pending, not an active saved memory. The owner must confirm it in settings. Do not claim it is remembered.",
    }


def change_memory(history, body):
    data = read(history)
    check_revision(data, body.get("expected_revision"))
    action = body.get("action")
    mid = body.get("id")
    if mid is not None:
        _id(mid)
    before = next(
        (m for f in ("memories", "pending_memories") for m in data[f] if m["id"] == mid), None
    )
    after = None
    if action == "save":
        text = _text(body.get("text"), 600, False)
        scope = body.get("scope", "account")
        cid = body.get("conversation_id") if scope == "conversation" else None
        if scope not in {"account", "conversation"} or (
            scope == "conversation" and cid not in history["conversations"]
        ):
            raise ValueError("invalid memory scope")
        mid = (
            mid or "memory-" + _digest({"text": text, "scope": scope, "conversation_id": cid})[:32]
        )
        before = next((m for m in data["memories"] if m["id"] == mid), None)
        after = {
            "id": mid,
            "text": text,
            "scope": scope,
            "conversation_id": cid,
            "source": {"type": "user_setting"},
            "created_at": before["created_at"] if before else stamp(),
            "updated_at": stamp(),
        }
        if before and all(
            before[k] == after[k] for k in ("text", "scope", "conversation_id", "source")
        ):
            return False
    elif action == "confirm":
        if before is None:
            raise ValueError("unknown memory proposal")
        if any(m["id"] == mid for m in data["memories"]):
            return False
        after = {**before, "updated_at": stamp(), "confirmed_at": stamp()}
    elif action in {"delete", "dismiss"}:
        if before is None:
            return False
        if action == "dismiss" and any(m["id"] == mid for m in data["memories"]):
            raise ValueError("dismiss only applies to pending proposals")
    else:
        raise ValueError("invalid memory action")
    for field in ("memories", "pending_memories"):
        data[field] = [m for m in data[field] if m["id"] != mid]
    if after is not None:
        data["memories"].append(after)
    audit(data, action + "_memory", before, after, ident=mid)
    validate(data, history["conversations"])
    history["personalization"] = data
    return True
