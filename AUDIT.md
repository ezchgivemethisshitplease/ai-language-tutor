# Audit of the original AI Language Tutor

Audit date: 2026-10-16. Original revision: `510fc6daf0d1220ae796af31a65a07a262a753f9`.
Scope: original source, all 60 English curriculum units, activities, agent instructions, templates and browser apps. Findings below describe the original revision; remediation evidence is tracked separately in IMPROVEMENTS.md. Learner outcomes and live agent/voice behavior have not been empirically validated.

## Reproducible baseline

The original repository has four Python scripts, five static HTML applications, Markdown teaching procedures and no dependency manifest, test directory or CI workflow. Python on the audit host: 3.14.6, macOS.

| Command | Observed result before edits |
| --- | --- |
| `python3 tools/srs.py selfcheck` | Passed internal assertions |
| `python3 tools/serve.py selfcheck` | Passed loopback health/shutdown smoke check |
| `python3 tools/voice_selfcheck.py` | Passed string-presence assertions |
| `python3 -m unittest discover -v` | 0 tests; Python 3.14 exits 5 (NO TESTS RAN) |

These assertions do not establish algorithm conformance, transactional storage, language proficiency or live audio quality. The unittest failure is absence of tests, not a failing test case. No learner directory existed at baseline. Checks used temporary/selfcheck data only.

## Advertised feature inventory

Classification: **tested** = narrow implementation with existing check; **partial** = executable but incomplete; **instructions** = Markdown workflow only; **LLM** = relies on uncalibrated model judgment; **absent** = no implementation found.

| Advertised feature | Original status | Verified implementation and limitation |
| --- | --- | --- |
| A1–C1 course | partial | 60 content files exist; no machine-readable prerequisites or mastery model |
| Placement finds real CEFR | LLM | `activities/placement-test.md` assigns a level after a few probes; no validated bank, scoring or uncertainty |
| Adaptive daily sessions | instructions | `activities/session.md` asks the agent to balance history and errors; no deterministic selector |
| Persistent learner progress | partial | Plain files exist; `srs.save()` truncates and rewrites without locks, validation or recovery |
| FSRS reviews | partial | `tools/srs.py` contains a simplified 17-weight scheduler; a few assertions, no reference comparison |
| Browser activities | partial | Real HTML/API paths; client can submit arbitrary scores, save failures are hidden |
| Speaking and pronunciation | instructions | Self-contained external voice handoff; no audio capture or pronunciation measurement in Python |
| Voice validation | tested (contract text only) | `voice_selfcheck.py` checks strings; report validation remains prose |
| Russian native-language support | absent | Only Spanish interference notes; generated translations requested from the LLM |
| Agent portability | instructions | AGENTS.md plus a one-line CLAUDE.md pointer and command wrappers; no live agent eval |
| TTS | partial | Executable optional cloud providers and OS playback; cloud provider auto-detection can transmit text implicitly |
| Image lookup | partial | Openverse query/download exists; no URL/size/content checks and incomplete attribution fallback |
| Privacy | partial | student/ ignored and loopback binding; no Origin/Host defenses, unrestricted local API writes |
| Multi-language progress | partial | Folder convention; active.txt can escape the learner directory |
| Export/import, versioned migrations | absent | No durable migration, archive or recovery command |
| Automated regression verification | absent | No unit/integration suite, static analysis or CI |

## Prioritized findings

### P0 — Durable state and local API correctness

**P0-01: progress can be lost or corrupted.** `tools/srs.py:save`, `tools/serve.py:do_POST` and `write_event` write directly; threaded requests read/modify/write without a common lock. Process interruption may leave truncated JSON and concurrent reviews may overwrite each other. No schema or backup distinguishes corruption from an empty learner. Fix: validated, atomic fsync writes, process/thread transactions, previous-valid backups and explicit recovery. Never silently reset corrupt data.

**P0-02: untrusted browser requests can mutate learning data.** `tools/serve.py:Handler` accepts POST JSON without Origin, Host, content-type, size or per-session token validation. Loopback binding alone is insufficient against malicious websites and DNS rebinding. `int(Content-Length)` and malformed payloads can raise unhandled errors. `srs.review` accepts invalid grades (including 0, negative indices and booleans). Fix: bounded same-origin API, server-side validation and transactional all-or-nothing grading.

**P0-03: arbitrary active-language paths.** `srs.lang_dir` joins unchecked active.txt content to student/. Absolute paths, `..` and symlinks can resolve outside learner data. Fix: validate slugs and resolved containment before every access.

### P1 — Learning evidence, scheduling and assessment

**P1-01: the FSRS claim exceeds the implementation.** `srs.review` omits maintained reference state transitions/learning steps and full review logs. Same-day successful reviews do not grow stability under its elapsed-day formula; Again simply returns today and the browser loops until a non-Again grade. No history supports optimization or auditing. Fix: maintained FSRS with deterministic settings, compatible legacy conversion, explicit grades, stable identities and durable per-review logs. Do not claim calibration without data.

**P1-02: completion is conflated with knowledge.** `AGENTS.md` treats known_words + cards + level/unit as knowledge. `activities/placement-test.md` asks the agent to seed 150–400 supposed high-frequency known words from sparse evidence. No observations, assistance flags, delayed checks or uncertainty exist. Fix: preserve old records as unverified legacy data, record independent attempts separately from mastery estimates, require repeated spaced evidence, and stop inferring unseen vocabulary.

**P1-03: placement and promotion lack reliable evidence.** `activities/placement-test.md` says two probes are enough and sets the level at a guessed boundary. `activities/exam-simulator.md` uses model-generated exams and raw 70%/60% thresholds, without equating forms or validating difficulty. These are local course policies, not CEFR cut scores. Fix: conservative provisional diagnostics, explicit criteria/sample counts/uncertainty, skill coverage, delayed checks and a deterministic course gate. A course gate must never be represented as certification.

**P1-04: adaptation has no executable state machine.** `activities/session.md`, weekly checks and errors.md rely entirely on the agent counting and planning correctly. Interrupted sessions, retries and duplicate browser events have no identity. Fix: stored plans, session/attempt IDs, idempotent observations, explicit transitions, prerequisite checks and skill balancing.

**P1-05: Russian L1 interference is unsupported.** `languages/english/l1-notes/` contains only Spanish notes. Curriculum and voice defaults repeatedly illustrate Spanish; language fade is tied to a single assumed level. Fix: structured extensible Russian contrastive knowledge, Russian onboarding/feedback and evidence-sensitive explanations with L1 rescue on request.

**P1-06: browser saves can silently fail.** `apps/flashcards.html:finish` and `apps/quiz.html:finish` catch and ignore network failures; flashcards are saved only at the end. Reloading/interruption discards reviews, repeated submission can grade twice, and Again has no repeat cap. `quiz.html` promises missed items will be added although the server only writes an event. Fix: acknowledged saves, pending retries, idempotency, immediate per-review persistence, bounded repetition and accurate UI messages.

**P1-07: imported voice reports are trusted by prose only.** `portable/voice-tutor.md` describes validation but executable tools only test section names. Model reports are not authenticated audio evidence. Fix: executable schema/pass checks and keep reports as uncalibrated observations; never use them alone for promotion or pronunciation measurement.

### P2 — Quality, privacy and maintainability

**P2-01: no installation or verification contract.** No supported Python version, pinned scheduler, CI, lint/type check or regression suite. Fix: minimal dependency/development manifests and reproducible commands on macOS/Linux/Windows.

**P2-02: hidden external transmission.** `tools/tts.py:provider` chooses cloud services automatically if a package/key is present. Fix: local-first defaults, explicit cloud selection and bounded synthesis. The bundled CSS already uses local/system fonts. Cloud use must identify the text/context sent.

**P2-03: validation and accepted alternatives differ across activities.** Browser gap/reorder equality and LLM open scoring have no shared typed outcome, ambiguity policy or evidence provenance. Fix: accepted answer sets with conservative normalization; unmatched natural-language responses require review, not a confident rejection.

**P2-04: curriculum metadata and evidence claims need restraint.** The syllabus labels word counts and grammar sequencing as official while source access is not automated; unit lists are not a licensed frequency corpus. CEFR describes communicative performance, not a universal grammar/vocabulary checklist. Fix: original structured metadata, transparent prerequisites, no fabricated frequency rankings and clear distinction between teaching policy and scientific evidence.

**P2-05: availability and privacy of audio vary by platform.** OS playback, browser voices and external voice AI have different capabilities. A transcript does not preserve pronunciation information. Fix: optional modular providers, explicit unassessed skills, text-safe degradation and macOS smoke coverage without implying an acoustic assessment.

## Audit method and references

Implementation was read directly, rather than inferred from README. Sources consulted on 2026-10-16 include [Codex instruction discovery](https://developers.openai.com/codex/guides/agents-md/), [Claude memory/imports](https://code.claude.com/docs/en/memory), [Python HTTP server limitations](https://docs.python.org/3/library/http.server.html), and [OWASP CSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html). Scheduler and pedagogy reference details are recorded in ARCHITECTURE.md and PEDAGOGY.md alongside the corresponding implementation choices.

This audit is source inspection plus reproducible software checks. It is not a learner study, CEFR validation study, production penetration test, or live Codex/Claude/voice-provider acceptance test. Remaining limitations must remain visible in ROADMAP.md.
