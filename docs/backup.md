# Learner backup and recovery

`tools/backup.py` creates verified archives of the managed learner data for every detected language, plus learner media. Restores go to a new directory. Existing learner files, archives, and destination directories are never replaced.

This complements the previous-generation `.bak` files used for individual JSON recovery. An archive preserves a complete generation of the managed files; it is not a copy of every arbitrary file under `student/`.

## What is included

| Location | Included |
| --- | --- |
| Learner root | `active.txt`, `profile.md`, `activity-results.json`, `quiz-current.json`, `reading-current.json`, `dictation-current.json`, `web-chat.json` |
| Each language directory | `cards.json`, `progress.json`, `learner.json`, `known_words.txt`, `errors.md` |
| Root and language media | Files below `img/`, `media/`, `audio/`, and `recordings/`, including nested directories |

Language directories use the existing simple names, such as `english` and `french`, and must contain at least one managed learner file. Names that would collide on a case-insensitive filesystem are rejected.

`img/` accepts `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`, and `.avif`. Other media directories also accept `.mp3`, `.wav`, `.m4a`, `.ogg`, `.flac`, `.aiff`, `.aif`, `.mp4`, and `.webm`. Media bytes are preserved exactly; validation checks their integrity rather than assessing their content.

The allowlist excludes credentials and control files such as `.env` and `.serve.json`, TTS caches, event notifications, locks, `.bak` files, hidden paths, scripts, and arbitrary custom files. `english/session-artifacts/` is scratch material and is excluded; canonical observations already contain recorded responses and exercises. Put audio evidence that needs recovery in a managed media directory. Separately preserve anything outside this scope.

`web-chat.json` includes conversation transcripts, request receipts and prepared task definitions. The isolated `.runtime/codex-home` authentication/session store is outside the learner archive. A restored transcript can start a fresh Codex thread when its original rollout is unavailable; sign in again if needed. Legacy JSON `export`/`import` retains its previous scope and does not include web conversations. The browser's download button creates the same verified ZIP; archive restoration remains the explicit CLI operation below.

Known credential-shaped JSON fields are rejected rather than copied or redacted. Free-form profile text, answers, and media remain learner-owned content and may contain personal information. The backup tool does not scan or rewrite those contents, and it does not encrypt archives. Use a protected destination or an encrypted volume appropriate to the data.

## Manual backup and restore drill

Choose an existing destination directory outside the live learner directory. Each archive name must be new:

```sh
python tools/tutor.py backup /path/to/backups/manual-2026-10-16.zip
python tools/tutor.py backup-check /path/to/backups/manual-2026-10-16.zip
python tools/tutor.py restore /path/to/backups/manual-2026-10-16.zip ./restored-student
```

The restore parent must already exist; `restored-student` must not exist. Verification finishes before any restore staging directory is created. The tool then writes and flushes a private staging tree, verifies each file again while copying, and publishes the completed tree atomically. Original learner data stays in place.

Inspect the recovered files and media. When English is active, validate the structured learner state independently:

```sh
python tools/tutor.py --student-dir ./restored-student validate
```

The archive supports legacy data for all detected languages. Full learner-model validation applies to `english/learner.json`; other languages' learner JSON is preserved as an object with a matching target language when declared. All language decks receive SRS validation. The structured learning engine currently supports English, so its `validate` command does not claim support for other active languages.

A checksum match proves byte integrity against this manifest. It does not authenticate who created an archive: someone who changes both data and manifest can recompute checksums. Restore trusted archives, and test recovery periodically rather than relying only on the presence of a ZIP file.

## Automatic rotating backups

Automatic backups are off by default. The owner enables them through environment variables in the shell that launches the tutor or server. Learner files cannot enable backups or choose a destination.

For a mounted drive, mount it first and create its backup subdirectory on that volume. Configure its actual paths, for example on macOS:

```sh
export TUTOR_BACKUP_DIR=/Volumes/StudyBackup/tutor
export TUTOR_BACKUP_REQUIRE_MOUNT=/Volumes/StudyBackup
export TUTOR_BACKUP_KEEP=7
export TUTOR_BACKUP_INTERVAL_HOURS=24
python tools/tutor.py backup-auto
```

On Linux, use the actual mounted volume and backup directory instead. `TUTOR_BACKUP_REQUIRE_MOUNT` is optional for a local destination. When supplied, the named path must be a mounted filesystem and contain the backup directory. A missing directory or unmounted required volume produces `unavailable`; the tool does not create a replacement directory on the local disk.

| Setting | Meaning |
| --- | --- |
| `TUTOR_BACKUP_DIR` | Absolute, existing directory outside the learner root. Its presence opts in. |
| `TUTOR_BACKUP_KEEP` | Number of verified generations retained for this learner root, from 2 to 100; default 7. |
| `TUTOR_BACKUP_INTERVAL_HOURS` | Minimum time between generations, from 1 to 8760 hours; default 24. |
| `TUTOR_BACKUP_REQUIRE_MOUNT` | Optional absolute mountpoint that must currently be mounted and contain the destination. |

The policy runs lazily after successful tutor mutations, SRS CLI mutations, and browser result saves. All learner transaction locks are released before the backup hook runs. It is not a background daemon: no new mutation means no scheduled run. `backup-auto` explicitly evaluates the same policy.

Within the interval, scheduling reads bounded archive metadata and manifests without rereading media payloads. A new generation receives full checksum/schema validation before publication. When rotation is due, previous candidates are fully validated before choosing which generations to remove. Rotation begins only after a new verified archive exists. Corrupt or foreign archives are retained for inspection, and unrelated files are left alone. The latest generation is always kept, including after clock changes.

Before deleting an old generation, rotation moves it into a private quarantine directory and verifies it against the expected manifest again. A same-name replacement is preserved. It returns to its old name when that name is free; otherwise its quarantine location is reported in `retained_paths` for inspection.

A background backup failure returns a warning or unavailable status while the completed study operation stays saved. Tutor CLI results and browser API receipts include the backup outcome; the SRS CLI prints backup warnings on stderr. Explicit `backup-auto` exits unsuccessfully when its configured destination is unavailable. Check these outcomes and reconnect the volume when needed.

A local copy shares the computer's hardware risks. A mounted drive also remains reachable while mounted. Keep an additional separate or disconnected copy when the recovery needs justify it; this tool neither uploads data nor manages cloud credentials.

## Format, limits, and failure handling

Archives use stored, uncompressed ZIP members and a versioned `manifest.json`. Each managed file has a relative path, exact byte length, and SHA-256 checksum. The manifest records languages, creation time, scope, and a hash identifying the source learner directory; it does not store the absolute source path or environment configuration.

Default limits are 5,000 files, 128 MiB per file, 16 MiB per document, 512 MiB total learner bytes, 600 MiB per archive, and 2 MiB for the manifest. Trusted Python callers can supply a stricter or larger `Limits` instance within the format's non-ZIP64 bounds. Archive contents cannot raise these limits.

Validation rejects traversal, absolute or hidden paths, duplicate and normalization-colliding names, symlinks, special files, reparse metadata, extra ZIP metadata, compression, encryption, comments, trailing data, unsupported versions, schema errors, checksum mismatches, and files outside the managed scope. It bounds the central directory before constructing ZIP member objects and streams media checks. Source symlinks and hard links are rejected; unreadable or changing managed media causes the backup to fail rather than silently omit files.

Publication uses the OS no-replace rename primitive: `renamex_np(RENAME_EXCL)` on macOS and `renameat2(RENAME_NOREPLACE)` on Linux. Unsupported libraries or filesystems fail safely. File and directory flushes are used, including macOS `F_FULLFSYNC`. These operations rely on the local filesystem and device honoring flushes and atomic rename; network filesystems may have different guarantees.

A process killed before publication may leave a private `.tutor-backup-*.tmp` file or `.tutor-restore-*` staging directory. Such artifacts are not valid published generations and are not rotated automatically. Inspect an identified orphan after confirming its operation is no longer running. Never use an incomplete archive to replace live data.

Interrupted pruning or retained replacement evidence may also leave a private `.tutor-prune-*` directory. Its archive may still be complete: run `backup-check` on the identified file before deciding how to retain it. Automatic rotation does not delete quarantined evidence.

## Verification

```sh
python -m unittest tests.test_backup -v
python -m mypy tools/backup.py
python -m ruff check tools/backup.py tests/test_backup.py
```

Tests cover multilingual byte-preserving recovery, media, excluded files, malformed archives, quota enforcement, missing mounts, interval/rotation behavior, and real `SIGKILL` interruptions immediately before and after archive and restore publication. These are process-crash drills, not a simulation of physical power loss or hardware failure. The local run exercises macOS; Linux runs use the same tests in CI.

Implementation decisions follow Python's [ZIP security guidance](https://docs.python.org/3.14/library/zipfile.html#decompression-pitfalls), [file and directory APIs](https://docs.python.org/3.14/library/os.html), and the Linux [exclusive rename semantics](https://man7.org/linux/man-pages/man2/rename.2.html). Keeping separate copies and performing recovery drills follows CISA's [data backup guidance](https://www.cisa.gov/sites/default/files/publications/data_backup_options.pdf).
