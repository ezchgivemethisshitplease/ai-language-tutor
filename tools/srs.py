#!/usr/bin/env python3
"""Maintained FSRS scheduling and durable learner decks.

Commands: due, grade <id> <1-4>, add (JSON on stdin), img <id> <query>,
          streak, stats, export <file>, import <file>, selfcheck.
Install dependencies with: python -m pip install -r requirements.txt
"""

from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import unicodedata
import uuid
from typing import Any, cast

try:
    from . import storage
except ImportError:
    import storage  # type: ignore[no-redef]  # Direct-script and package imports share this module.

ROOT = Path(__file__).resolve().parent.parent
STUDENT = Path(os.environ.get("TUTOR_STUDENT_DIR", str(ROOT / "student")))
SCHEMA_VERSION = 2
FSRS_VERSION = "6.3.2"
load = storage.load
save = storage.save


def language_dir(language):
    """Resolve one language name and reject absolute paths, traversal and symlinks."""
    if not isinstance(language, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", language):
        raise ValueError("language must be a simple folder name, e.g. english")
    root = STUDENT.resolve()
    candidate = STUDENT / language
    if candidate.is_symlink() or candidate.resolve().parent != root:
        raise ValueError("language folder must stay inside student/")
    return candidate


def lang_dir():
    active = STUDENT / "active.txt"
    if active.exists():
        if active.is_symlink():
            raise ValueError("active.txt must not be a symlink")
        result = language_dir(active.read_text(encoding="utf-8").strip())
        if not result.is_dir():
            raise ValueError(f"active language folder does not exist: {result.name}")
        return result
    folders = (
        [
            path
            for path in STUDENT.iterdir()
            if path.is_dir() and not path.name.startswith(".") and not path.is_symlink()
        ]
        if STUDENT.exists()
        else []
    )
    if len(folders) == 1:
        return language_dir(folders[0].name)
    raise ValueError(
        "no active language folder; write its name to student/active.txt (e.g. english)"
    )


def cards_path():
    return lang_dir() / "cards.json"


def progress_path():
    return lang_dir() / "progress.json"


def _when(value=None):
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("review datetime must include a timezone")
        return value.astimezone(timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, time.min, timezone.utc)
    if isinstance(value, str):
        try:
            return _when(
                date.fromisoformat(value) if len(value) == 10 else datetime.fromisoformat(value)
            )
        except ValueError as exc:
            raise ValueError("expected an ISO date or timezone-aware datetime") from exc
    raise ValueError("expected a date or timezone-aware datetime")


def _grade(grade):
    if type(grade) is not int or grade not in (1, 2, 3, 4):
        raise ValueError("grade must be an integer 1–4 (Again, Hard, Good, Easy)")
    return grade


def _identifier(value, label="id"):
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError(f"{label} must be a non-empty string of at most 200 characters")
    return value


def _number(value, label, low, high=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    if value < low or (high is not None and value > high):
        raise ValueError(f"{label} is out of range")


@lru_cache(maxsize=1)
def scheduler():
    try:
        from fsrs import Scheduler
        from importlib.metadata import version
    except ImportError as exc:
        raise RuntimeError(
            "FSRS is required; run python -m pip install -r requirements.txt"
        ) from exc
    if version("fsrs") != FSRS_VERSION:
        raise RuntimeError(
            f"expected fsrs=={FSRS_VERSION}; run python -m pip install -r requirements.txt"
        )
    # Fuzzing is disabled for reproducible schedules and regression tests.
    return Scheduler(enable_fuzzing=False)


def _fsrs_card(card):
    scheduler()  # Actionable dependency/version error before importing classes.
    from fsrs import Card, State
    from fsrs.card import CardDict

    if "fsrs" in card:
        data = card["fsrs"]
        if not isinstance(data, dict):
            raise ValueError("card fsrs state must be an object")
        if type(data.get("card_id")) is not int or type(data.get("state")) is not int:
            raise ValueError("FSRS card_id and state must be integers")
        for field, low, high in (("stability", 0.001, None), ("difficulty", 1, 10)):
            if data.get(field) is not None:
                _number(data[field], field, low, high)
        try:
            result = Card.from_dict(cast(CardDict, data))
        except (KeyError, ValueError, TypeError, OverflowError) as exc:
            raise ValueError("invalid canonical FSRS card state") from exc
        for timestamp in (result.due, result.last_review):
            if timestamp is not None:
                _when(timestamp)
        result.due = _when(result.due)
        result.last_review = _when(result.last_review) if result.last_review else None
        if result.stability is not None:
            _number(result.stability, "stability", 0.001)
        if result.difficulty is not None:
            _number(result.difficulty, "difficulty", 1, 10)
        if result.last_review is not None and (
            result.stability is None or result.difficulty is None
        ):
            raise ValueError("reviewed FSRS card needs stability and difficulty")
        if result.state in (State.Learning, State.Relearning) and (
            type(result.step) is not int
            or result.step < 0
            or result.step >= (2 if result.state == State.Learning else 1)
        ):
            raise ValueError("invalid FSRS learning step")
        return result
    stable_id = int.from_bytes(
        hashlib.sha256(str(card.get("id", "anonymous")).encode()).digest()[:8], "big"
    )
    due = _when(card.get("due") or date.today())
    last = card.get("last_review")
    if last is None:
        return Card(card_id=stable_id, due=due)
    # The old scheduler did not record states or individual reviews. Carry its
    # available memory state forward without fabricating a retrospective log.
    _number(card.get("S"), "legacy stability", 0.001)
    _number(card.get("D"), "legacy difficulty", 1, 10)
    return Card(
        card_id=stable_id,
        state=State.Review,
        step=None,
        stability=card["S"],
        difficulty=card["D"],
        due=due,
        last_review=_when(last),
    )


def retrievability(card, today=None):
    state = _fsrs_card(card)
    when = _when(today)
    if state.last_review and when < state.last_review:
        raise ValueError("review time precedes the card's last review")
    return scheduler().get_card_retrievability(state, current_datetime=when)


def review(card, grade, today=None, review_id=None):
    """Update one in-memory card; persistence belongs to apply_reviews().

    Retains the original three-argument API and integer interval return value.
    Every accepted review records its exact UTC time and canonical FSRS log.
    """
    _grade(grade)
    when = _when(today)
    review_id = _identifier(review_id or uuid.uuid4().hex, "review_id")
    history = card.get("review_history", [])
    if not isinstance(history, list):
        raise ValueError("review_history must be an array")
    for old in history:
        if not isinstance(old, dict):
            raise ValueError("review history entries must be objects")
        if old.get("review_id") == review_id:
            if old.get("grade") != grade:
                raise ValueError("review_id already used with a different grade")
            if type(old.get("interval_days")) is not int or old["interval_days"] < 0:
                raise ValueError("invalid stored review interval")
            return old["interval_days"]
    old_state = _fsrs_card(card)
    if old_state.last_review and when < old_state.last_review:
        raise ValueError("review time precedes the card's last review")
    from fsrs import Rating, State

    new_state, log = scheduler().review_card(old_state, Rating(grade), review_datetime=when)
    interval = max(0, (new_state.due - when).days)
    updated = deepcopy(card)
    if "fsrs" not in updated:
        updated["migration"] = {
            "from": "legacy-simplified-fsrs",
            "at": when.isoformat(),
            "historical_reviews_available": False,
        }
    updated.update(
        {
            "fsrs": new_state.to_dict(),
            "scheduler": f"py-fsrs-{FSRS_VERSION}",
            "S": new_state.stability,
            "D": new_state.difficulty,
            "due": new_state.due.date().isoformat(),
            "due_at": new_state.due.isoformat(),
            "last_review": when.date().isoformat(),
            "reps": card.get("reps", 0) + 1,
            "lapses": card.get("lapses", 0) + int(grade == 1 and old_state.state == State.Review),
        }
    )
    entry = {
        "review_id": review_id,
        "card_id": card.get("id"),
        "grade": grade,
        "reviewed_at": when.isoformat(),
        "due_at": new_state.due.isoformat(),
        "interval_days": interval,
        "fsrs": log.to_dict(),
        "scheduler": f"py-fsrs-{FSRS_VERSION}",
    }
    updated["review_history"] = history + [entry]
    card.clear()
    card.update(updated)
    return interval


def validate_card(card):
    if not isinstance(card, dict):
        raise ValueError("each card must be a JSON object")
    front, answer, hint = card.get("front"), card.get("answer"), card.get("hint")
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("each card needs a non-empty answer")
    if not isinstance(hint, str) or not hint.strip():
        raise ValueError("each card needs a non-empty L1 hint")
    if not isinstance(front, str) or front.count("___") != 1:
        raise ValueError("each card front needs exactly one ___")
    if sum(ch.isalnum() for ch in front.replace("___", "")) < 3:
        raise ValueError("each card front needs meaningful sentence context around ___")
    if "id" in card:
        _identifier(card["id"])
    for field in ("reps", "lapses"):
        if field in card and (type(card[field]) is not int or card[field] < 0):
            raise ValueError(f"{field} must be a nonnegative integer")
    for field in ("due", "due_at", "last_review"):
        if card.get(field) is not None:
            _when(card[field])


def validate_deck(data):
    if not isinstance(data, dict) or not isinstance(data.get("cards"), list):
        raise ValueError("deck must be an object containing a cards array")
    version = data.get("schema_version", 1)
    if type(version) is not int or version not in (1, SCHEMA_VERSION):
        raise ValueError("unsupported deck schema version")
    identifiers = set()
    scheduler_ids = set()
    all_reviews = set()
    for card in data["cards"]:
        validate_card(card)
        identifier = _identifier(card.get("id"))
        if identifier in identifiers:
            raise ValueError(f"duplicate card id: {identifier}")
        identifiers.add(identifier)
        if card.get("last_review") is not None or "fsrs" in card:
            state = _fsrs_card(card)
            if state.card_id in scheduler_ids:
                raise ValueError("duplicate canonical FSRS card id")
            scheduler_ids.add(state.card_id)
            if "fsrs" in card:
                if (
                    not isinstance(card.get("due_at"), str)
                    or card.get("due") != state.due.date().isoformat()
                    or _when(card["due_at"]) != state.due
                ):
                    raise ValueError("card due mirrors disagree with canonical FSRS state")
                last = state.last_review.date().isoformat() if state.last_review else None
                if card.get("last_review") != last:
                    raise ValueError("last_review disagrees with canonical FSRS state")
                if state.last_review and (
                    card.get("S") != state.stability or card.get("D") != state.difficulty
                ):
                    raise ValueError("card memory mirrors disagree with canonical FSRS state")
        history = card.get("review_history", [])
        if not isinstance(history, list):
            raise ValueError("review_history must be an array")
        seen = set()
        for log in history:
            if not isinstance(log, dict):
                raise ValueError("review history entry must be an object")
            identifier = _identifier(log.get("review_id"), "review_id")
            if identifier in seen:
                raise ValueError("duplicate review id in history")
            if identifier in all_reviews:
                raise ValueError("review id must be unique across the deck")
            seen.add(identifier)
            all_reviews.add(identifier)
            _grade(log.get("grade"))
            if not isinstance(log.get("reviewed_at"), str) or not isinstance(
                log.get("due_at"), str
            ):
                raise ValueError("review history needs reviewed_at and due_at timestamps")
            _when(log["reviewed_at"])
            _when(log["due_at"])
            if log.get("card_id") != card["id"]:
                raise ValueError("review history belongs to a different card")
            if type(log.get("interval_days")) is not int or log["interval_days"] < 0:
                raise ValueError("review interval must be a nonnegative integer")
    if not isinstance(data.get("review_batches", {}), dict):
        raise ValueError("review_batches must be an object")
    for identifier, receipt in data.get("review_batches", {}).items():
        _identifier(identifier, "batch_id")
        if not isinstance(receipt, dict) or not isinstance(receipt.get("fingerprint"), str):
            raise ValueError("invalid stored batch receipt")
        result = receipt.get("result")
        if (
            not isinstance(result, dict)
            or result.get("batch_id") != identifier
            or not isinstance(result.get("graded"), list)
        ):
            raise ValueError("invalid stored batch result")
    return data


def _migrate_deck(data):
    validate_deck(data)
    data["schema_version"] = SCHEMA_VERSION
    data.setdefault("review_batches", {})
    data.setdefault(
        "scheduler",
        {
            "implementation": "py-fsrs",
            "version": FSRS_VERSION,
            "desired_retention": 0.9,
            "enable_fuzzing": False,
            "parameters": list(scheduler().parameters),
        },
    )
    return data


def _key(card):
    def normalize(text):
        return " ".join(unicodedata.normalize("NFKC", text).casefold().split())

    return normalize(card["front"]), normalize(card["answer"])


def add_cards(path, cards, today=None):
    """Validate an entire addition before writing; skip equivalent front/answer."""
    if isinstance(cards, dict):
        cards = [cards]
    if not isinstance(cards, list):
        raise ValueError("cards must be a JSON object or array")
    incoming = deepcopy(cards)
    for card in incoming:
        validate_card(card)
    result: dict[str, Any] = {"added": [], "duplicates": []}
    when = _when(today)
    with storage.transaction(path, {"cards": []}) as data:
        _migrate_deck(data)
        keys = {_key(card): card["id"] for card in data["cards"]}
        ids = {card["id"] for card in data["cards"]}
        for card in incoming:
            key = _key(card)
            if key in keys:
                result["duplicates"].append(keys[key])
                continue
            card.setdefault("id", uuid.uuid4().hex)
            if card["id"] in ids:
                raise ValueError(f"card id already exists with different content: {card['id']}")
            for field, default in (
                ("last_review", None),
                ("due", when.date().isoformat()),
                ("reps", 0),
                ("lapses", 0),
            ):
                card.setdefault(field, default)
            if "fsrs" not in card and card.get("last_review") is None:
                card["fsrs"] = _fsrs_card(card).to_dict()
                card["due_at"] = card["fsrs"]["due"]
            data["cards"].append(card)
            keys[key] = card["id"]
            ids.add(card["id"])
            result["added"].append(card["id"])
        validate_deck(data)
        result["total"] = len(data["cards"])
    return result


def apply_reviews(path, reviews, today=None, batch_id=None):
    """Atomically validate and apply reviews, with persistent retry receipts.

    Clients must reuse batch_id and/or review_id on retries. An idempotency key
    reused with different content is rejected. No caller-supplied review time is
    read from the review dictionaries; the server chooses the trusted clock.
    """
    if not isinstance(reviews, list) or not reviews or len(reviews) > 1000:
        raise ValueError("reviews must be a non-empty array of at most 1000 items")
    when = _when(today)
    batch_id = _identifier(batch_id, "batch_id") if batch_id is not None else None
    normalized = []
    seen_ids = set()
    for item in reviews:
        if not isinstance(item, dict):
            raise ValueError("each review must be an object")
        identifier = _identifier(item.get("id"))
        _grade(item.get("grade"))
        if identifier in seen_ids:
            raise ValueError("a batch may review each card only once")
        seen_ids.add(identifier)
        review_id = item.get("review_id")
        if review_id is not None:
            _identifier(review_id, "review_id")
        normalized.append({"id": identifier, "grade": item["grade"], "review_id": review_id})
    fingerprint = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()
    result = None
    with storage.transaction(path, {"cards": []}) as data:
        _migrate_deck(data)
        previous = data["review_batches"].get(batch_id) if batch_id else None
        if previous is not None:
            if previous["fingerprint"] != fingerprint:
                raise ValueError("batch_id already used with different reviews")
            result = deepcopy(previous["result"])
            result["duplicate"] = True
        else:
            deck = {card["id"]: card for card in data["cards"]}
            for item in normalized:
                if item["id"] not in deck:
                    raise ValueError(f"no card with id {item['id']}")
            graded = []
            for index, item in enumerate(normalized):
                card = deck[item["id"]]
                review_id = item["review_id"] or (
                    hashlib.sha256(f"{batch_id}:{index}".encode()).hexdigest()
                    if batch_id
                    else uuid.uuid4().hex
                )
                _identifier(review_id, "review_id")
                already = any(
                    log["review_id"] == review_id for log in card.get("review_history", [])
                )
                interval = review(card, item["grade"], when, review_id=review_id)
                graded.append(
                    {
                        "id": card["id"],
                        "review_id": review_id,
                        "next_due": card["due"],
                        "due_at": card["due_at"],
                        "interval_days": interval,
                        "duplicate": already,
                    }
                )
            result = {"graded": graded, "batch_id": batch_id, "duplicate": False}
            if batch_id:
                data["review_batches"][batch_id] = {
                    "fingerprint": fingerprint,
                    "result": deepcopy(result),
                }
            validate_deck(data)
    return result


def due_cards(path, today=None):
    data = validate_deck(load(path, {"cards": []}))
    when = _when(today)
    day_mode = isinstance(today, date) and not isinstance(today, datetime)

    def due(card):
        if day_mode:
            return card.get("due") is None or card["due"] <= when.date().isoformat()
        value = card.get("due_at") or card.get("due")
        return value is None or _when(value) <= when

    return sorted(
        (card for card in data["cards"] if due(card)),
        key=lambda card: (card.get("due_at") or card.get("due") or "", card["id"]),
    )


def cmd_due(today):
    print(json.dumps(due_cards(cards_path(), today), indent=2, ensure_ascii=False))


def cmd_grade(card_id, grade, today):
    result = apply_reviews(cards_path(), [{"id": card_id, "grade": grade}], today)
    print(json.dumps(result["graded"][0]))


def cmd_add(today):
    result = add_cards(cards_path(), storage.decode(sys.stdin.read()), today)
    print(json.dumps(result, ensure_ascii=False))


def cmd_img(card_id, query):
    import urllib.parse
    import urllib.request

    if not query:
        raise ValueError("usage: img <card-id> <search query>")
    directory = lang_dir()
    path = directory / "cards.json"
    data = validate_deck(load(path, {"cards": []}))
    if not any(card["id"] == card_id for card in data["cards"]):
        raise ValueError(f"no card with id {card_id}")
    ua = {"User-Agent": "learning-language-tutor/2.0"}
    api = "https://api.openverse.org/v1/images/?" + urllib.parse.urlencode(
        {"q": query, "page_size": 3, "mature": "false"}
    )
    with urllib.request.urlopen(urllib.request.Request(api, headers=ua), timeout=15) as response:
        hits = json.load(response)["results"]
    if not hits:
        raise ValueError(f"no images found for {query!r}")
    pick = hits[0]
    with urllib.request.urlopen(
        urllib.request.Request(pick.get("thumbnail") or pick["url"], headers=ua), timeout=30
    ) as response:
        raw = response.read(10 * 1024 * 1024 + 1)
    if len(raw) > 10 * 1024 * 1024:
        raise ValueError("image exceeds 10 MiB")
    # An imported ID must never become an arbitrary filesystem path.
    name = hashlib.sha256(card_id.encode()).hexdigest()[:32] + ".jpg"
    out = directory / "img" / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(raw)
    with storage.transaction(path, {"cards": []}) as data:
        card = next((card for card in data["cards"] if card["id"] == card_id), None)
        if card is None:
            raise ValueError(f"card disappeared during image download: {card_id}")
        card["image"] = name
        if pick.get("attribution"):
            card["image_credit"] = pick["attribution"]
    print(json.dumps({"id": card_id, "image": str(out.relative_to(ROOT))}, ensure_ascii=False))


def cmd_streak(today):
    day = _when(today).date()
    with storage.transaction(
        progress_path(), {"streak": 0, "last_active": None, "level": None, "unit": 1, "history": []}
    ) as data:
        if (
            not isinstance(data, dict)
            or type(data.get("streak", 0)) is not int
            or data.get("streak", 0) < 0
        ):
            raise ValueError("invalid progress streak")
        last = data.get("last_active")
        if last is not None and date.fromisoformat(last) > day:
            raise ValueError("study day precedes last_active")
        if last != day.isoformat():
            data["streak"] = (
                data.get("streak", 0) + 1 if last == (day - timedelta(days=1)).isoformat() else 1
            )
            data["last_active"] = day.isoformat()
        result = {"streak": data["streak"], "last_active": data["last_active"]}
    print(json.dumps(result))


def cmd_stats(today):
    deck = validate_deck(load(cards_path(), {"cards": []}))["cards"]
    print(
        json.dumps(
            {
                "cards": len(deck),
                "due": len(due_cards(cards_path(), today)),
                "new": sum(card.get("last_review") is None for card in deck),
            }
        )
    )


def selfcheck():
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "cards.json"
        add_cards(
            path,
            [{"front": "Can I ___ your pen?", "answer": "borrow", "hint": "одолжить"}],
            date(2026, 1, 1),
        )
        identifier = load(path, None)["cards"][0]["id"]
        result = apply_reviews(
            path, [{"id": identifier, "grade": 3}], date(2026, 1, 1), batch_id="selfcheck"
        )
        assert result["graded"][0]["interval_days"] == 0
        assert apply_reviews(
            path, [{"id": identifier, "grade": 3}], date(2026, 1, 1), batch_id="selfcheck"
        )["duplicate"]
        assert load(path, None)["cards"][0]["reps"] == 1
    print("selfcheck OK")


def main():
    # Coding-agent pipes use an explicit UTF-8 text contract.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    command = args[0]
    when = datetime.now(timezone.utc)
    try:
        if command == "due" and len(args) == 1:
            cmd_due(when)
        elif command == "grade" and len(args) == 3:
            cmd_grade(args[1], int(args[2]), when)
        elif command == "add" and len(args) == 1:
            cmd_add(when)
        elif command == "img" and len(args) >= 3:
            cmd_img(args[1], " ".join(args[2:]))
        elif command == "streak" and len(args) == 1:
            cmd_streak(date.today())
        elif command == "stats" and len(args) == 1:
            cmd_stats(when)
        elif command == "export" and len(args) == 2:
            storage.export_json(cards_path(), args[1])
            print("deck exported")
        elif command == "import" and len(args) == 2:
            incoming = load(args[1], None)
            validate_deck(incoming)
            # Import merges; existing IDs/state are never replaced implicitly.
            result = add_cards(cards_path(), incoming["cards"], when)
            print(json.dumps(result))
        elif command == "selfcheck" and len(args) == 1:
            selfcheck()
        else:
            raise ValueError(__doc__)
        if command in {"grade", "add", "img", "streak", "import"}:
            if __package__:
                from . import backup
            else:
                import backup  # type: ignore[no-redef]

            outcome = backup.maybe_automatic_backup(STUDENT)
            if outcome["status"] in {"warning", "unavailable"}:
                print("Backup warning: " + outcome["reason"], file=sys.stderr)
    except (ValueError, RuntimeError, OSError) as exc:
        sys.exit(f"error: {exc}")


if __name__ == "__main__":
    main()
