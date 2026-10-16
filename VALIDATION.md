# Verification record

Date: 2026-10-16. Baseline: `510fc6daf0d1220ae796af31a65a07a262a753f9`. Local environment: macOS arm64, Python 3.14.6, Node 24.3.0, fsrs 6.3.2, Ruff 0.17.1, mypy 2.4.0. All learner scenarios use temporary/synthetic data. No personal learner files were migrated or overwritten.

## Local results

| Command or check | Observed result |
| --- | --- |
| `python -m unittest discover -s tests -q` | 78 tests passed |
| `python -m ruff check tools tests` | Passed |
| `python -m ruff format --check tools tests` | Passed |
| `python -m mypy tools` | Passed, 11 source files; checked untyped function bodies, not strict fully annotated typing |
| `python tools/srs.py selfcheck` | Passed |
| `python tools/serve.py selfcheck` | Passed |
| `python tools/voice_selfcheck.py` | Passed; structural contract check only |
| `python -m pip check` | Passed |
| `python -m compileall -q tools tests` | Passed |
| `node tests/browser_transport.cjs` | Three scenarios passed: concurrent separate submissions, offline replay, learner isolation |
| `python tools/check_browser_scripts.py` | All inline/shared browser JavaScript parsed |
| Both humanize manifests with skill-creator `quick_validate.py` | Passed; all five relative links resolved, ordinary files without symlinks/home paths |
| Independent humanize cases | Russian self-correction/alternative-answer feedback and technical rewrites retained raw answers, commands, numbers and uncertainty; no human reviewer invented |
| macOS `/usr/bin/say -o ../native-speech.aiff 'I am a student.'` | Created non-empty AIFF-C file; no playback or pronunciation measurement performed |

The suite includes four-process/thread storage mutation, failure injection and corruption recovery, legacy FSRS conversion, 250 reference-matched reviews, 100 learner sessions, exact retry identities, delayed/productive mastery guards, L1 feedback, unassessed audio, readiness/progression and speaking debt settlement. These are deterministic synthetic scenarios, not outcome benchmarks.

## Actual browser checks

The Codex in-app browser opened a loopback server against a separate synthetic learner directory:

1. Two flashcards were revealed and explicitly graded Again/Good. Each grade showed an acknowledgment and advanced once; the final screen confirmed completion. Server tests separately verify that per-card saves do not emit the completion event.
2. A two-item quiz accepted `am`, then received `love` where its non-exhaustive key listed `like`. Feedback stayed `needs_review`; the summary showed the exact `I love coffee.` response with a question marker, and saving was acknowledged.
3. The Russian reader loaded its original passage and glossary, showed «книга» for `book`, and acknowledged a request for later card creation. Actual durable receipts and review histories were inspected; the isolated server then stopped cleanly. Additional full browser listening, accessibility and offline lifecycle coverage remains open.

A screenshot of the quiz outcome is delivered alongside the source archive. The screenshot uses synthetic content. This manual browser smoke is separate from the automated Node transport test; it does not constitute comprehensive cross-browser E2E coverage.

## Hosted CI

The workflow targets Python 3.10/3.14 on Ubuntu, macOS and Windows, plus Node browser checks. The first hosted run exposed Windows CLI encoding/archive-path defects and a commit-level mismatch between the updated voice selfcheck and the not-yet-pushed pass template. The CLI now explicitly uses UTF-8 and has a regression with an ASCII-configured pipe; archive keys now use portable forward slashes and the template includes the validated binding fields. The final hosted run will be recorded after the integrated commit completes.

## Limits

No live paid/cloud speech call, STT, acoustic score, external voice conversation, fresh independent Codex/Claude teaching session, calibrated placement study, learner study or long-term filesystem crash/power-loss study was performed. Audio references and human-rating labels are checked structurally; their truth/identity cannot be established by these tests. Large multi-year history performance has not been benchmarked. Source-level compatibility and selected browser behavior must not be reported as validated educational efficacy.
