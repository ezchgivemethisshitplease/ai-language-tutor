"""Small, local JSON store with serialized read/modify/write transactions.

Locks are advisory: all application writers must use this module. Each file is
an independent transaction; this is not a multi-file database or network store.
"""

from contextlib import contextmanager
from copy import deepcopy
import errno
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import threading
import time
from typing import Any

try:
    import fcntl
except ImportError as exc:
    raise RuntimeError("The tutor requires macOS or Linux with POSIX file locking") from exc


class StorageError(ValueError):
    """Stored data is invalid or cannot be changed safely."""


_locks: dict[str, Any] = {}
_locks_guard = threading.Lock()
_held = threading.local()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise StorageError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def decode(raw, path="JSON"):
    """Reject truncated JSON, duplicate keys and nonstandard NaN/Infinity."""
    try:
        return json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                StorageError(f"non-finite number: {value}")
            ),
        )
    except (ValueError, UnicodeError) as exc:
        raise StorageError(
            f"invalid JSON in {path}: {exc}; restore a verified backup explicitly"
        ) from exc


def _path(path):
    path = Path(path).absolute()
    if path.is_symlink():
        raise StorageError(f"refusing symlink data file: {path}")
    return path


@contextmanager
def locked(path, timeout=15):
    """Lock a stable sidecar, so replacing the JSON does not replace its lock."""
    path = _path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _locks_guard:
        lock = _locks.setdefault(str(path), threading.RLock())
    with lock:
        held: set[str] = getattr(_held, "paths", set())
        if str(path) in held:
            yield path
            return
        lock_path = path.with_name(path.name + ".lock")
        if lock_path.is_symlink():
            raise StorageError(f"refusing symlink lock: {lock_path}")
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        acquired = False
        try:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise StorageError(f"timed out locking {path}") from None
                    time.sleep(0.02)
            acquired = True
            _held.paths = held | {str(path)}
            yield path
        finally:
            _held.paths = held
            if acquired:
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def _read(path, default):
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return deepcopy(default), None
    return decode(raw, path), raw


def load(path, default):
    with locked(path) as path:
        return _read(path, default)[0]


def _encode(data):
    try:
        return (json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode(
            "utf-8"
        )
    except (TypeError, ValueError) as exc:
        raise StorageError(f"data is not valid JSON: {exc}") from exc


def _sync_directory(directory):
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    except OSError as exc:
        if exc.errno not in (errno.EINVAL, errno.ENOTSUP):
            raise
    finally:
        os.close(fd)


def _atomic_bytes(path, raw):
    path = _path(path)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), mode)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
            if sys.platform == "darwin":
                # macOS fsync may flush only to a drive's volatile cache.
                if hasattr(fcntl, "F_FULLFSYNC"):
                    fcntl.fcntl(handle.fileno(), fcntl.F_FULLFSYNC)
        os.replace(name, path)
        _sync_directory(path.parent)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def _write(path, data, old_raw):
    raw = _encode(data)
    if raw == old_raw:
        return
    if old_raw is not None:
        _atomic_bytes(path.with_name(path.name + ".bak"), old_raw)
    _atomic_bytes(path, raw)


def save(path, data):
    """Atomically replace JSON. Use transaction() for read/modify/write."""
    with locked(path) as path:
        _, old_raw = _read(path, None)  # Refuse to overwrite corrupted evidence.
        _write(path, data, old_raw)


@contextmanager
def transaction(path, default):
    """Yield mutable state; commit once on success, rollback on any exception."""
    with locked(path) as path:
        data, old_raw = _read(path, default)
        before = deepcopy(data)
        yield data
        if data != before:
            _write(path, data, old_raw)


def restore_backup(path):
    """Explicitly restore the last valid JSON generation; preserve corrupt bytes."""
    with locked(path) as path:
        backup = _path(path.with_name(path.name + ".bak"))
        raw = backup.read_bytes()
        data = decode(raw, backup)
        if path.exists():
            evidence = path.with_name(path.name + f".recovery-{time.time_ns()}")
            _atomic_bytes(evidence, path.read_bytes())
        _atomic_bytes(path, raw)
        return data


def export_json(path, destination):
    """Export one verified JSON object without copying locks or credentials."""
    data = load(path, None)
    save(destination, data)
    return data


def import_json(source, destination, validator=None):
    data = load(source, None)
    if validator is not None:
        validator(data)
    save(destination, data)
    return data
