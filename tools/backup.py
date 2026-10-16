"""Bounded, verified learner archives for macOS/Linux; no credentials or cloud client.

Application writes must use storage's advisory locks. Automatic backups are
explicitly configured by the owner and run only after application transactions.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
import ctypes
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import sys
import tempfile
from typing import Any
import unicodedata
import uuid
import zipfile

if __package__:
    from . import activity, learning, srs, storage
else:
    import activity, learning, srs, storage  # type: ignore[no-redef]

FORMAT = "ai-language-tutor-backup"
VERSION = 1
MANAGED_ROOT_FILES = frozenset(
    {
        "active.txt",
        "profile.md",
        "activity-results.json",
        "quiz-current.json",
        "reading-current.json",
        "dictation-current.json",
    }
)
MANAGED_LANGUAGE_FILES = frozenset(
    {"cards.json", "progress.json", "learner.json", "known_words.txt", "errors.md"}
)
MEDIA_DIRS = frozenset({"img", "media", "audio", "recordings"})
IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif"})
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | frozenset(
    {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aiff", ".aif", ".mp4", ".webm"}
)
LANGUAGE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
CREDENTIAL_KEYS = frozenset(
    {
        "api_key",
        "openai_api_key",
        "elevenlabs_api_key",
        "authorization",
        "access_token",
        "refresh_token",
        "password",
        "secret_key",
        "private_key",
    }
)
CHUNK = 64 * 1024


class BackupError(ValueError):
    """A backup cannot be safely created, verified or restored."""


@dataclass(frozen=True)
class Limits:
    max_files: int = 5000
    max_file_bytes: int = 128 * 1024 * 1024
    max_document_bytes: int = 16 * 1024 * 1024
    max_total_bytes: int = 512 * 1024 * 1024
    max_archive_bytes: int = 600 * 1024 * 1024
    max_manifest_bytes: int = 2 * 1024 * 1024

    def __post_init__(self):
        for value in vars(self).values():
            if type(value) is not int or value <= 0:
                raise BackupError("backup limits must be positive integers")
        if self.max_files >= 65535 or self.max_archive_bytes >= 2**32:
            raise BackupError("ZIP64 is outside this backup format")


DEFAULT_LIMITS = Limits()


def _time(value=None):
    value = datetime.now(timezone.utc) if value is None else value
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise BackupError("backup time must have a timezone")
    try:
        return value.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise BackupError("backup timestamp is outside the supported UTC range") from exc


def _directory(path):
    path = Path(path).absolute()
    if path.is_symlink() or not path.is_dir():
        raise BackupError("a real existing directory is required")
    return path.resolve(strict=True)


def _source_id(root):
    return hashlib.sha256(str(root).encode()).hexdigest()[:16]


def _path_name(name):
    if not isinstance(name, str) or not name or len(name.encode("utf-8")) > 512:
        raise BackupError("invalid archive path length")
    parts = name.split("/")
    if any(part in {"", ".", ".."} or part.startswith(".") for part in parts):
        raise BackupError("archive contains a hidden or unsafe path")
    if "\\" in name or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise BackupError("archive contains an unsafe path")
    if PurePosixPath(name).is_absolute() or PurePosixPath(name).as_posix() != name:
        raise BackupError("archive path is not canonical")
    return parts


def _kind(name, languages):
    parts = _path_name(name)
    if len(parts) == 1 and name in MANAGED_ROOT_FILES:
        return "document"
    if len(parts) == 2 and parts[0] in languages and parts[1] in MANAGED_LANGUAGE_FILES:
        return "document"
    media_index = 1 if parts[0] in languages else 0
    if len(parts) > media_index + 1 and parts[media_index] in MEDIA_DIRS:
        extensions = IMAGE_EXTENSIONS if parts[media_index] == "img" else MEDIA_EXTENSIONS
        if Path(parts[-1]).suffix.lower() in extensions:
            return "media"
    raise BackupError("archive includes a file outside the managed learner scope")


def _no_credentials(value):
    if isinstance(value, dict):
        if any(key.casefold() in CREDENTIAL_KEYS for key in value):
            raise BackupError("credential fields are not permitted in learner backups")
        for child in value.values():
            _no_credentials(child)
    elif isinstance(value, list):
        for child in value:
            _no_credentials(child)


def _document(name, raw, languages):
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise BackupError(f"{name}: document must be UTF-8") from exc
    if name.endswith(".json"):
        try:
            data = storage.decode(raw, name)
            if not isinstance(data, dict):
                raise BackupError("learner JSON must be an object")
            _no_credentials(data)
            leaf = name.rsplit("/", 1)[-1]
            if leaf == "cards.json":
                srs.validate_deck(data)
            elif name == "english/learner.json":
                learning.validate_state(data)
            elif (
                leaf == "learner.json"
                and data.get("target_language", name.split("/")[0]) != name.split("/")[0]
            ):
                raise BackupError("learner language disagrees with its directory")
            elif name in {"quiz-current.json", "reading-current.json", "dictation-current.json"}:
                activity.validate(
                    {
                        "quiz-current.json": "quiz",
                        "reading-current.json": "text",
                        "dictation-current.json": "dictation",
                    }[name],
                    data,
                )
            elif name == "activity-results.json" and not isinstance(data.get("receipts"), dict):
                raise BackupError("invalid activity receipts")
        except (ValueError, KeyError, TypeError, RecursionError) as exc:
            raise BackupError(
                f"{name}: invalid learner document/schema or credential field"
            ) from exc
    elif name == "active.txt":
        if text.strip() not in languages:
            raise BackupError("active language is not present in this backup")
    return text


def _walk_error(error):
    raise BackupError("cannot enumerate managed media; backup was not published") from error


def _inventory(root):
    languages = sorted(
        path.name
        for path in root.iterdir()
        if not path.name.startswith(".")
        and path.name not in MEDIA_DIRS
        and LANGUAGE.fullmatch(path.name)
        and path.is_dir()
        and any(
            (path / name).exists() or (path / name).is_symlink() for name in MANAGED_LANGUAGE_FILES
        )
    )
    if not languages:
        raise BackupError("no managed language data to back up")
    if len({name.casefold() for name in languages}) != len(languages):
        raise BackupError("language directories collide on case-insensitive filesystems")
    files = [
        name for name in MANAGED_ROOT_FILES if (root / name).exists() or (root / name).is_symlink()
    ]
    for language in languages:
        if (root / language).is_symlink():
            raise BackupError("language directories must not be symlinks")
        files.extend(
            f"{language}/{name}"
            for name in MANAGED_LANGUAGE_FILES
            if (root / language / name).exists() or (root / language / name).is_symlink()
        )
    for parent in [root] + [root / language for language in languages]:
        for media in MEDIA_DIRS:
            directory = parent / media
            if directory.is_symlink():
                raise BackupError("media directories must not be symlinks")
            if not directory.exists():
                continue
            if not directory.is_dir():
                raise BackupError("media path must be a directory")
            for current, dirs, names in os.walk(directory, followlinks=False, onerror=_walk_error):
                dirs[:] = sorted(name for name in dirs if not name.startswith("."))
                for subdirectory in dirs:
                    if (Path(current) / subdirectory).is_symlink():
                        raise BackupError("media directories must not contain symlinks")
                for name in sorted(names):
                    relative = (Path(current) / name).relative_to(root).as_posix()
                    if not name.startswith(".") and Path(name).suffix.lower() in (
                        IMAGE_EXTENSIONS if media == "img" else MEDIA_EXTENSIONS
                    ):
                        _kind(relative, languages)
                        files.append(relative)
    signatures = {}
    collisions = set()
    for name in sorted(files):
        _kind(name, languages)
        key = unicodedata.normalize("NFC", name).casefold()
        if key in collisions:
            raise BackupError("learner filenames collide on case-insensitive filesystems")
        collisions.add(key)
        info = (root / name).lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise BackupError("managed learner files must be regular files without hard links")
        signatures[name] = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    return languages, signatures


def _lock_order(name):
    # The existing tutor holds learner -> cards; legacy export holds learner ->
    # active/profile -> cards/progress/text -> activity-results. Preserve both.
    leaf = name.rsplit("/", 1)[-1]
    priority = {
        "learner.json": 0,
        "active.txt": 1,
        "profile.md": 2,
        "cards.json": 3,
        "progress.json": 4,
        "known_words.txt": 5,
        "errors.md": 6,
        "activity-results.json": 7,
    }
    return priority.get(leaf, 8), name


@contextmanager
def _source_file(root, name):
    """Open each component through descriptors, refusing symlink substitution."""
    parts = _path_name(name)
    with ExitStack() as stack:
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.callback(os.close, fd)
        for component in parts[:-1]:
            fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            stack.callback(os.close, fd)
        file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        handle = stack.enter_context(os.fdopen(file_fd, "rb"))
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise BackupError("source changed into a special or linked file")
        yield handle, info
        after = os.fstat(handle.fileno())
        if (info.st_ino, info.st_size, info.st_mtime_ns, info.st_nlink) != (
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_nlink,
        ):
            raise BackupError("learner file changed during backup; retry")


def _sync_file(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
        if sys.platform == "darwin" and hasattr(fcntl, "F_FULLFSYNC"):
            fcntl.fcntl(fd, fcntl.F_FULLFSYNC)
    finally:
        os.close(fd)


def _rename_new(stage, destination):
    """Atomic no-replace rename: even an existing empty directory is protected.

    Python's os.rename() can replace an empty directory between exists() and
    rename(). Use the supported OS primitives, failing closed if unavailable.
    """
    libc = ctypes.CDLL(None, use_errno=True)
    old, new = os.fsencode(stage), os.fsencode(destination)
    try:
        if sys.platform == "darwin":
            operation = libc.renamex_np
            operation.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
            operation.restype = ctypes.c_int
            result = operation(old, new, 0x00000004)  # RENAME_EXCL, macOS SDK sys/stdio.h.
        elif sys.platform.startswith("linux"):
            operation = libc.renameat2
            operation.argtypes = [
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            ]
            operation.restype = ctypes.c_int
            result = operation(0, old, 0, new, 1)  # RENAME_NOREPLACE; absolute paths ignore dirfds.
        else:
            raise BackupError("backup publication requires macOS or Linux")
    except AttributeError as exc:
        raise BackupError("this OS lacks atomic no-replace rename support") from exc
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))


def _publish_archive(stage, destination):
    _rename_new(stage, destination)
    storage._sync_directory(destination.parent)


def create_backup(student_dir, archive_path, *, limits=DEFAULT_LIMITS, now=None):
    """Create a new archive outside student/, preserving every source byte."""
    root = _directory(student_dir)
    destination = Path(archive_path).absolute()
    parent = _directory(destination.parent)
    destination = parent / destination.name
    if destination.exists() or destination.is_symlink() or destination.is_relative_to(root):
        raise BackupError("backup destination must be new and outside the learner directory")
    languages, signatures = _inventory(root)
    if len(signatures) > limits.max_files:
        raise BackupError("backup file count exceeds its limit")
    planned = {
        "format": FORMAT,
        "version": VERSION,
        "created_at": _time(now).isoformat(),
        "source_id": _source_id(root),
        "languages": languages,
        "scope": "managed-learner-data-and-media",
        "files": [
            {"path": name, "size": info[2], "sha256": "0" * 64} for name, info in signatures.items()
        ],
        "total_bytes": sum(info[2] for info in signatures.values()),
    }
    manifest_size = len(json.dumps(planned, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    # Stored ZIP has fixed local/central headers and no compression, comments,
    # extra fields or ZIP64 records. Bound the complete output before writing.
    member_names = ["data/" + name for name in signatures] + ["manifest.json"]
    archive_size = (
        planned["total_bytes"]
        + manifest_size
        + 22
        + sum(76 + 2 * len(name.encode("utf-8")) for name in member_names)
    )
    if (
        planned["total_bytes"] > limits.max_total_bytes
        or manifest_size > limits.max_manifest_bytes
        or archive_size > limits.max_archive_bytes
    ):
        raise BackupError("planned backup exceeds its size limits")
    fd, temporary = tempfile.mkstemp(prefix=".tutor-backup-", suffix=".tmp", dir=parent)
    os.close(fd)
    stage = Path(temporary)
    try:
        with ExitStack() as stack:
            lock_names = set(signatures) | MANAGED_ROOT_FILES
            lock_names.update(
                f"{language}/{name}" for language in languages for name in MANAGED_LANGUAGE_FILES
            )
            for name in sorted(lock_names, key=_lock_order):
                stack.enter_context(storage.locked(root / name))
            if (languages, signatures) != _inventory(root):
                raise BackupError("learner inventory changed before backup; retry")
            entries = []
            total = 0
            with zipfile.ZipFile(
                stage, "w", compression=zipfile.ZIP_STORED, allowZip64=False
            ) as archive:
                for name, signature in signatures.items():
                    document = _kind(name, languages) == "document"
                    cap = (
                        min(limits.max_file_bytes, limits.max_document_bytes)
                        if document
                        else limits.max_file_bytes
                    )
                    if signature[2] > cap or total + signature[2] > limits.max_total_bytes:
                        raise BackupError("learner data exceeds backup size limits")
                    digest = hashlib.sha256()
                    captured = bytearray()
                    size = 0
                    info = zipfile.ZipInfo("data/" + name)
                    info.create_system = 3
                    info.external_attr = (stat.S_IFREG | 0o600) << 16
                    with _source_file(root, name) as (source, _), archive.open(info, "w") as output:
                        while chunk := source.read(CHUNK):
                            size += len(chunk)
                            if size > cap or total + size > limits.max_total_bytes:
                                raise BackupError("learner data grew beyond backup limits")
                            output.write(chunk)
                            digest.update(chunk)
                            if document:
                                captured.extend(chunk)
                    if size != signature[2]:
                        raise BackupError("learner data changed during backup")
                    if document:
                        _document(name, bytes(captured), languages)
                    total += size
                    entries.append({"path": name, "size": size, "sha256": digest.hexdigest()})
                manifest = {**planned, "files": entries, "total_bytes": total}
                raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
                if len(raw) > limits.max_manifest_bytes:
                    raise BackupError("manifest exceeds its size limit")
                archive.writestr("manifest.json", raw)
            if (languages, signatures) != _inventory(root):
                raise BackupError("learner inventory changed during backup; retry")
        if stage.stat().st_size > limits.max_archive_bytes:
            raise BackupError("archive exceeds its size limit")
        _sync_file(stage)
        validate_backup(stage, limits=limits)
        _publish_archive(stage, destination)
        return {
            "status": "created",
            "archive": str(destination),
            "files": len(entries),
            "bytes": total,
            "languages": languages,
            "source_id": manifest["source_id"],
        }
    finally:
        stage.unlink(missing_ok=True)


def _zip_index(handle, limits):
    """Bound the central directory before ZipFile allocates member objects."""
    info = os.fstat(handle.fileno())
    if not stat.S_ISREG(info.st_mode) or not 22 <= info.st_size <= limits.max_archive_bytes:
        raise BackupError("invalid archive size/type")
    handle.seek(-22, os.SEEK_END)
    end = handle.read(22)
    try:
        signature, disk, central_disk, disk_count, count, size, offset, comment = struct.unpack(
            "<4s4H2IH", end
        )
    except struct.error as exc:
        raise BackupError("archive was truncated while reading its directory") from exc
    if signature != b"PK\x05\x06" or disk or central_disk or disk_count != count or comment:
        raise BackupError("unsupported ZIP directory, trailing bytes or comments")
    if (
        not 1 <= count <= limits.max_files + 1
        or size > (limits.max_files + 1) * 1024
        or offset + size != info.st_size - 22
    ):
        raise BackupError("ZIP directory exceeds limits or is inconsistent")
    handle.seek(0)
    return info


def _read_member(archive, member, cap, output=None):
    digest = hashlib.sha256()
    data = bytearray()
    size = 0
    with archive.open(member) as source:
        while chunk := source.read(min(CHUNK, cap - size + 1)):
            size += len(chunk)
            if size > cap:
                raise BackupError("archive member exceeds its size limit")
            digest.update(chunk)
            if output is None:
                data.extend(chunk)
            else:
                output.write(chunk)
    if size != member.file_size:
        raise BackupError("archive member size mismatch")
    return bytes(data), digest.hexdigest(), size


@contextmanager
def _verified_archive(path, limits, *, verify_contents=True):
    path = Path(path).absolute()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        before = _zip_index(handle, limits)
        try:
            with zipfile.ZipFile(handle, "r", allowZip64=False) as archive:
                members = archive.infolist()
                if not 1 <= len(members) <= limits.max_files + 1:
                    raise BackupError("too many ZIP members")
                seen = set()
                total = 0
                for member in members:
                    name = member.filename
                    _path_name(name)
                    key = unicodedata.normalize("NFC", name).casefold()
                    if key in seen or name != member.orig_filename:
                        raise BackupError("duplicate or colliding ZIP member names")
                    seen.add(key)
                    mode = member.external_attr >> 16
                    if (
                        member.is_dir()
                        or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                        or member.flag_bits & 1
                        or member.compress_type != zipfile.ZIP_STORED
                        or member.extra
                        or member.external_attr & 0x400
                    ):
                        raise BackupError("only unencrypted regular stored ZIP members are allowed")
                    if (
                        member.file_size > limits.max_file_bytes
                        or member.compress_size != member.file_size
                    ):
                        raise BackupError("ZIP member exceeds size limits")
                    total += member.file_size
                if total > limits.max_total_bytes + limits.max_manifest_bytes:
                    raise BackupError("archive expands beyond its total limit")
                if "manifest.json" not in archive.namelist():
                    raise BackupError("manifest is missing")
                raw, _, _ = _read_member(
                    archive, archive.getinfo("manifest.json"), limits.max_manifest_bytes
                )
                manifest = storage.decode(raw, "backup manifest")
                _validate_manifest(manifest, limits)
                expected = {"data/" + entry["path"] for entry in manifest["files"]} | {
                    "manifest.json"
                }
                if set(archive.namelist()) != expected:
                    raise BackupError("archive members disagree with the manifest")
                for entry in manifest["files"]:
                    member = archive.getinfo("data/" + entry["path"])
                    if member.file_size != entry["size"]:
                        raise BackupError("manifest file size mismatch")
                    if not verify_contents:
                        continue  # Scheduling only; restore/check always verify every byte.
                    document = _kind(entry["path"], manifest["languages"]) == "document"
                    if document:
                        data, digest, _ = _read_member(archive, member, limits.max_document_bytes)
                        _document(entry["path"], data, manifest["languages"])
                    else:
                        with open(os.devnull, "wb") as sink:
                            _, digest, _ = _read_member(
                                archive, member, limits.max_file_bytes, sink
                            )
                    if digest != entry["sha256"]:
                        raise BackupError("backup checksum mismatch")
                yield manifest, archive
                after = os.fstat(handle.fileno())
                if (before.st_size, before.st_mtime_ns, before.st_ino) != (
                    after.st_size,
                    after.st_mtime_ns,
                    after.st_ino,
                ):
                    raise BackupError("archive changed during verification/restore")
        except (
            zipfile.BadZipFile,
            zipfile.LargeZipFile,
            ValueError,
            UnicodeError,
            RecursionError,
            KeyError,
        ) as exc:
            raise BackupError("invalid or corrupt backup archive") from exc


def _validate_manifest(manifest, limits):
    keys = {
        "format",
        "version",
        "created_at",
        "source_id",
        "languages",
        "scope",
        "files",
        "total_bytes",
    }
    if (
        not isinstance(manifest, dict)
        or set(manifest) != keys
        or manifest["format"] != FORMAT
        or type(manifest["version"]) is not int
        or manifest["version"] != VERSION
    ):
        raise BackupError("unsupported backup manifest")
    if not isinstance(manifest["created_at"], str):
        raise BackupError("invalid backup timestamp")
    try:
        _time(datetime.fromisoformat(manifest["created_at"]))
    except ValueError as exc:
        raise BackupError("invalid backup timestamp") from exc
    if (
        not isinstance(manifest["source_id"], str)
        or not re.fullmatch(r"[0-9a-f]{16}", manifest["source_id"])
        or manifest["scope"] != "managed-learner-data-and-media"
    ):
        raise BackupError("invalid backup identity/scope")
    languages = manifest["languages"]
    if (
        not isinstance(languages, list)
        or not languages
        or any(
            not isinstance(name, str) or not LANGUAGE.fullmatch(name) or name in MEDIA_DIRS
            for name in languages
        )
        or languages != sorted(set(languages))
        or len({name.casefold() for name in languages}) != len(languages)
    ):
        raise BackupError("invalid backup languages")
    entries = manifest["files"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= limits.max_files:
        raise BackupError("invalid manifest file count")
    seen = set()
    total = 0
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "size", "sha256"}:
            raise BackupError("invalid manifest file entry")
        kind = _kind(entry["path"], languages)
        key = unicodedata.normalize("NFC", entry["path"]).casefold()
        if key in seen:
            raise BackupError("duplicate manifest file")
        seen.add(key)
        cap = (
            min(limits.max_document_bytes, limits.max_file_bytes)
            if kind == "document"
            else limits.max_file_bytes
        )
        if (
            type(entry["size"]) is not int
            or not 0 <= entry["size"] <= cap
            or not isinstance(entry["sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
        ):
            raise BackupError("invalid manifest size or checksum")
        total += entry["size"]
    if (
        type(manifest["total_bytes"]) is not int
        or manifest["total_bytes"] != total
        or total > limits.max_total_bytes
    ):
        raise BackupError("manifest total is invalid or over quota")
    if any(
        not any(
            entry["path"].split("/")[0] == language
            and entry["path"].rsplit("/", 1)[-1] in MANAGED_LANGUAGE_FILES
            for entry in entries
        )
        for language in languages
    ):
        raise BackupError("manifest language has no managed learner data")


def validate_backup(archive_path, *, limits=DEFAULT_LIMITS):
    with _verified_archive(archive_path, limits) as (manifest, _):
        return manifest


def _publish_restore(stage, destination):
    if destination.exists() or destination.is_symlink():
        raise BackupError("restore destination appeared; nothing replaced")
    _rename_new(stage, destination)
    storage._sync_directory(destination.parent)


def restore_backup(archive_path, new_destination, *, limits=DEFAULT_LIMITS):
    """Validate the complete archive before writing a private, new learner tree."""
    destination = Path(new_destination).absolute()
    parent = _directory(destination.parent)
    destination = parent / destination.name
    if destination.exists() or destination.is_symlink():
        raise BackupError("restore requires a new destination; existing data is never replaced")
    stage = None
    try:
        with _verified_archive(archive_path, limits) as (manifest, archive):
            stage = Path(tempfile.mkdtemp(prefix=".tutor-restore-", dir=parent))
            for entry in manifest["files"]:
                path = stage / entry["path"]
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, "wb") as output:
                    _, digest, size = _read_member(
                        archive, archive.getinfo("data/" + entry["path"]), entry["size"], output
                    )
                    output.flush()
                    os.fsync(output.fileno())
                _sync_file(path)
                if digest != entry["sha256"] or size != entry["size"]:
                    raise BackupError("archive changed during restore")
            for current, _, _ in os.walk(stage, topdown=False):
                storage._sync_directory(Path(current))
        # Publishing is outside verification's context, so a changed source can
        # never cause a failure after the destination has already been exposed.
        _publish_restore(stage, destination)
        return {
            "status": "restored",
            "destination": str(destination),
            "files": len(manifest["files"]),
            "languages": manifest["languages"],
        }
    finally:
        if stage is not None and stage.exists():
            shutil.rmtree(stage)


def _integer(environ, key, default, low, high):
    value = environ.get(key, str(default))
    if (
        not isinstance(value, str)
        or not value.isascii()
        or not value.isdecimal()
        or not low <= int(value) <= high
    ):
        raise BackupError(f"{key} must be an integer from {low} to {high}")
    return int(value)


def _prune_generation(candidate, expected_manifest, limits):
    """Reverify a private quarantined file, preserving same-name replacements."""
    directory = Path(tempfile.mkdtemp(prefix=".tutor-prune-", dir=candidate.parent))
    quarantined = directory / candidate.name
    try:
        _rename_new(candidate, quarantined)
        try:
            if validate_backup(quarantined, limits=limits) != expected_manifest:
                raise BackupError("rotation candidate changed after validation")
        except (OSError, ValueError, RuntimeError):
            try:
                _rename_new(quarantined, candidate)
                return False, str(candidate)
            except OSError:
                # Another file now occupies the old name. Keep both copies.
                return False, str(quarantined)
        quarantined.unlink()
        return True, None
    finally:
        if directory.exists() and not any(directory.iterdir()):
            directory.rmdir()
        storage._sync_directory(candidate.parent)


def automatic_backup(student_dir, *, environ=None, now=None, limits=DEFAULT_LIMITS):
    """Owner opt-in rotation. Call after committing and releasing learner locks."""
    environ = os.environ if environ is None else environ
    configured = environ.get("TUTOR_BACKUP_DIR")
    if not configured:
        return {"status": "disabled"}
    if not isinstance(configured, str) or not Path(configured).is_absolute():
        raise BackupError("TUTOR_BACKUP_DIR must be an absolute existing directory")
    directory = Path(configured)
    if not directory.exists():
        return {
            "status": "unavailable",
            "reason": "backup directory is missing; no directory was created",
        }
    directory = _directory(directory)
    root = _directory(student_dir)
    if directory.is_relative_to(root):
        raise BackupError("automatic backup directory must be outside the learner directory")
    required_mount = environ.get("TUTOR_BACKUP_REQUIRE_MOUNT")
    if required_mount:
        mount = Path(required_mount)
        if not mount.is_absolute() or mount.is_symlink():
            raise BackupError("TUTOR_BACKUP_REQUIRE_MOUNT must name a real absolute mountpoint")
        if not mount.is_mount():
            return {"status": "unavailable", "reason": "required backup volume is not mounted"}
        if not directory.is_relative_to(mount.resolve()):
            raise BackupError("backup directory is outside the required mountpoint")
    keep = _integer(environ, "TUTOR_BACKUP_KEEP", 7, 2, 100)
    hours = _integer(environ, "TUTOR_BACKUP_INTERVAL_HOURS", 24, 1, 8760)
    source = _source_id(root)
    timestamp = _time(now)
    managed = re.compile(rf"tutor-{source}-[0-9]{{8}}T[0-9]{{12}}Z-[0-9a-f]{{8}}\.zip\Z")
    with storage.locked(directory / f".tutor-{source}.rotation"):
        previous = []
        invalid = 0
        for candidate in directory.iterdir():
            if not managed.fullmatch(candidate.name):
                continue
            try:
                with _verified_archive(candidate, limits, verify_contents=False) as (manifest, _):
                    pass
                if manifest["source_id"] != source:
                    invalid += 1
                    continue
                previous.append((_time(datetime.fromisoformat(manifest["created_at"])), candidate))
            except (OSError, ValueError, RuntimeError):
                invalid += 1
        previous.sort(key=lambda entry: (entry[0], entry[1].name), reverse=True)
        if previous and timedelta(0) <= timestamp - previous[0][0] < timedelta(hours=hours):
            return {"status": "not_due", "latest": str(previous[0][1]), "invalid_retained": invalid}
        name = f"tutor-{source}-{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex[:8]}.zip"
        result = create_backup(root, directory / name, limits=limits, now=timestamp)
        verified = []
        for _, candidate in previous:
            try:
                manifest = validate_backup(candidate, limits=limits)
                if manifest["source_id"] != source:
                    invalid += 1
                    continue
                verified.append(
                    (_time(datetime.fromisoformat(manifest["created_at"])), candidate, manifest)
                )
            except (OSError, ValueError, RuntimeError):
                invalid += 1
        verified.sort(key=lambda entry: (entry[0], entry[1].name), reverse=True)
        # Keep the just-verified generation even if an older file has a future clock.
        removed = 0
        retained = []
        for _, candidate, expected_manifest in verified[keep - 1 :]:
            deleted, retained_path = _prune_generation(candidate, expected_manifest, limits)
            if deleted:
                removed += 1
            else:
                invalid += 1
                retained.append(retained_path)
        storage._sync_directory(directory)
        return {
            **result,
            "status": "created",
            "removed": removed,
            "invalid_retained": invalid,
            "retained_paths": retained,
        }


def maybe_automatic_backup(student_dir, **kwargs) -> dict[str, Any]:
    """Nonfatal post-commit hook: backup failure cannot invalidate saved work."""
    try:
        return automatic_backup(student_dir, **kwargs)
    except (OSError, ValueError, RuntimeError) as exc:
        return {"status": "warning", "reason": str(exc), "study_data_committed": True}
