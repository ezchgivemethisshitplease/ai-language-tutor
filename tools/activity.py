"""Validation and reproducible scoring for the existing browser activity format.

Scores describe only these items. They are never CEFR measurements or mastery.
"""

import hashlib
import json
import re
import unicodedata


def text(value, name, limit=12000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{name} must be non-empty text (max {limit} characters)")
    return value


def normalize(value):
    value = unicodedata.normalize("NFC", value).replace("’", "'")
    return re.sub(r"\s+", " ", value).strip().casefold().rstrip(".!?")


def validate(kind, data):
    if not isinstance(data, dict):
        raise ValueError("activity must be an object")
    text(data.get("title"), "title", 300)
    key = {"quiz": "questions", "text": "paragraphs", "dictation": "sentences"}[kind]
    items = data.get(key)
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        raise ValueError(f"{key} needs 1–100 entries")
    for item in items:
        if kind == "text":
            text(item, "paragraph")
        elif kind == "dictation":
            if not isinstance(item, dict):
                raise ValueError("sentence must be an object")
            text(item.get("en"), "sentence", 2000)
            for field in ("l1", "es", "note"):
                if field in item:
                    text(item[field], field)
        else:
            if not isinstance(item, dict) or item.get("type") not in {"choice", "gap", "reorder"}:
                raise ValueError("unsupported quiz item")
            if item["type"] == "choice":
                text(item.get("prompt"), "prompt")
                options, correct = item.get("options"), item.get("correct")
                if not isinstance(options, list) or not 2 <= len(options) <= 8:
                    raise ValueError("choice needs 2–8 options")
                for option in options:
                    text(option, "option", 2000)
                if type(correct) is not int or not 0 <= correct < len(options):
                    raise ValueError("invalid correct option index")
                if len(set(map(normalize, options))) != len(options):
                    raise ValueError("duplicate choice options")
            else:
                answers = item.get("answers", [item.get("answer")])
                if not isinstance(answers, list) or not 1 <= len(answers) <= 30:
                    raise ValueError("accepted answers must be a non-empty list")
                for answer in answers:
                    text(answer, "answer", 2000)
                if item["type"] == "gap":
                    if text(item.get("prompt"), "prompt").count("___") != 1:
                        raise ValueError("gap needs exactly one ___")
                else:
                    words = item.get("words")
                    if not isinstance(words, list) or not 2 <= len(words) <= 40:
                        raise ValueError("reorder needs 2–40 words")
                    for word in words:
                        text(word, "word", 100)
            if "explain" in item:
                text(item["explain"], "explanation")
    if kind == "text":
        glossary = data.get("glossary", {})
        if not isinstance(glossary, dict) or len(glossary) > 200:
            raise ValueError("invalid glossary")
        for word, entry in glossary.items():
            text(word, "glossary word", 100)
            if not isinstance(entry, dict):
                raise ValueError("invalid glossary entry")
            for field in ("def", "l1", "example"):
                text(entry.get(field), field)
    return data


def identity(data):
    """Content identity rejects results for a replaced activity."""
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def score_quiz(data, answers):
    validate("quiz", data)
    if not isinstance(answers, list) or len(answers) != len(data["questions"]):
        raise ValueError("submit exactly one response per question")
    results = []
    for q, response in zip(data["questions"], answers):
        if q["type"] == "choice":
            if type(response) is not int or not 0 <= response < len(q["options"]):
                raise ValueError("invalid choice response")
            outcome = "correct" if response == q["correct"] else "incorrect"
        else:
            text(response, "response", 4000)
            accepted = q.get("answers", [q.get("answer")])
            outcome = (
                "correct"
                if normalize(response) in set(map(normalize, accepted))
                else ("incorrect" if q.get("exhaustive") is True else "needs_review")
            )
        results.append({"response": response, "outcome": outcome})
    return {
        "score": sum(r["outcome"] == "correct" for r in results),
        "total": len(results),
        "needs_review": sum(r["outcome"] == "needs_review" for r in results),
        "results": results,
        "calibrated": False,
    }
