# Verification record

Updated: 2026-10-17. Baseline: `510fc6daf0d1220ae796af31a65a07a262a753f9`. Local environment: macOS arm64, Python 3.14.6, Node 24.3.0, fsrs 6.3.2, Ruff 0.17.1, mypy 2.4.0. All learner scenarios use temporary/synthetic data. No personal learner files were migrated or overwritten. The [web acceptance record](docs/web-acceptance.md) separates new local web checks from authenticated provider inference.

## Local results

| Command or check | Observed result |
| --- | --- |
| `python -m unittest discover -s tests -q` | 188 tests passed, including the new web/runtime/bridge cases |
| `python -m ruff check tools tests` | Passed |
| `python -m ruff format --check tools tests` | Passed |
| `python -m mypy tools` | Passed, 15 source files; checked untyped function bodies, not strict fully annotated typing |
| `python tools/srs.py selfcheck` | Passed |
| `python tools/serve.py selfcheck` | Passed |
| `python tools/voice_selfcheck.py` | Passed; structural contract check only |
| `python -m pip check` | Passed |
| `python -m compileall -q tools tests` | Passed |
| `node tests/browser_transport.cjs` | Four scenarios passed: concurrent separate submissions, offline replay, learner isolation, and a backup warning retained after completion |
| `node tests/web_chat_ui.cjs` | Eight scenarios passed: null-turn receipt/retry, scoped drafts, exact text, safe links, login URL checks, stream resume, interruption and a persistent backup warning |
| `python tools/check_browser_scripts.py` | All inline/shared browser JavaScript parsed |
| Source archive fresh installation | Passed runtime-only install, initialization/resume, redacted diagnostics, rejected unsupported entry, native bank audio, full multilingual/media backup/check/restore and legacy export/import; no development dependencies installed |
| Both humanize manifests with skill-creator `quick_validate.py` | Passed; all five relative links resolved, ordinary files without symlinks/home paths |
| Independent humanize cases | Russian self-correction/alternative-answer feedback and technical rewrites retained raw answers, commands, numbers and uncertainty; no human reviewer invented |
| macOS `/usr/bin/say -o ../native-speech.aiff 'I am a student.'` | Created non-empty AIFF-C file; current `tutor.py audio` also produced an 823,468-byte original bank stimulus during the fresh archive smoke. No playback or learner-pronunciation measurement performed |

The suite includes four-process/thread storage mutation, failure injection and corruption recovery, legacy FSRS conversion, 250 reference-matched reviews, 100 learner sessions, exact retry identities, delayed/productive mastery guards, L1 feedback, unassessed audio, readiness/progression and speaking debt settlement. It additionally covers registered diagnostic families, hidden listening scripts, first-trial independence across date windows, append-only reviews, broad productive evidence, provisional entry without mastery, multilingual/media restore, hostile archives, rotation and four actual SIGKILL drills immediately before/after archive/restore publication. These are deterministic synthetic scenarios, not outcome benchmarks.

## Actual browser checks

The Codex in-app browser opened a loopback server against a separate synthetic learner directory:

1. Two flashcards were revealed and explicitly graded Again/Good. Each grade showed an acknowledgment and advanced once; the final screen confirmed completion. Server tests separately verify that per-card saves do not emit the completion event.
2. A two-item quiz accepted `am`, then received `love` where its non-exhaustive key listed `like`. Feedback stayed `needs_review`; the summary showed the exact `I love coffee.` response with a question marker, and saving was acknowledged.
3. The Russian reader loaded its original passage and glossary, showed «книга» for `book`, and acknowledged a request for later card creation. Actual durable receipts and review histories were inspected; the isolated server then stopped cleanly. Additional full browser listening, accessibility and offline lifecycle coverage remains open.

A screenshot of the quiz outcome is delivered alongside the source archive. A further actual IAB flow graded synthetic cards with backup storage unavailable. Durable inspection found exactly one review per card and separate completion receipts. The warning initially disappeared behind completion feedback; that defect was fixed with a separate banner and regression, then the complete flow was rerun. The final page showed both saved answers and the unavailable backup warning; its screenshot is included. The screenshot uses synthetic content. This manual browser smoke is separate from the automated Node transport test; it does not constitute comprehensive cross-browser E2E coverage.

## Hosted CI

The workflow targets Python 3.10/3.14 on Ubuntu and macOS, plus Node browser checks. Windows support was removed at the user's request, including its lock/speech branches, installation instructions and CI jobs. UTF-8 output, portable archive names and voice-template binding remain covered by regressions. The [hosted run for code revision `278aef9`](https://github.com/ezchgivemethisshitplease/ai-language-tutor/actions/runs/38957258437) passed all five jobs: Python 3.10 and 3.14 on Ubuntu/macOS, plus browser transport/script checks. Each Python job ran all 142 tests, lint/format/type checks and selfchecks. This includes the actual OS no-replace publication and process-crash drills on both supported systems. Provider selection is mocked in the native Linux synthesis test; no actual Linux voice was played or synthesized.

## Live host and independent review

[Host acceptance](docs/host-acceptance.md) records four actual Codex turns, including final-code reload/resume, retained `an`/`love` responses, persistent voice debt and redaction of all 99 remaining diagnostic tasks. The old global Codex CLI could not load the current account configuration; a scratch-only official 0.163.0 installation completed the checks without changing global settings.

Claude Code 2.1.283 with the existing third-party model loaded the shared humanize/communication instructions and initialized/started a real synthetic learner. The initial turn was interrupted after roughly 14 minutes without a final task; its bounded continuation then completed exact-answer recording, interruption/resume and voice-debt checks on the final code. A scratch-file staging deviation, its instruction fix and a later one-exercise request that timed out after 180 seconds are recorded in the host report. Teaching pacing/style acceptance for that configured provider is not claimed. A separate Anthropic subscription invocation failed before inference with an explicitly revoked OAuth token. Full Anthropic-model acceptance is therefore blocked by owner authentication and is not claimed.

Independent code/content passes found and fixed meaning-changing curriculum transformations, reading/listening answer leakage, timestamp overflow that could hide a committed save, archive-rotation replacement loss, old hinted-family repeat credit, and a browser backup warning overwritten at completion. Dedicated regressions plus independent reproductions confirmed the corrected behavior. The [linguistic report](docs/linguistic-review.md) records the final bank hash and the distinct reciprocal review roles.


## Limits

No live paid/cloud speech call, STT, acoustic score, external voice conversation, calibrated placement study, learner study or physical power-loss/hardware study was performed. Selected real host flows and actual process-crash drills are described above; neither substitutes for those studies. Audio references and human-rating labels are checked structurally; their truth/identity cannot be established by these tests. Large multi-year history performance has not been benchmarked. Source-level compatibility and selected browser behavior must not be reported as validated educational efficacy.
