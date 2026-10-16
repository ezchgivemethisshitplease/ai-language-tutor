# Implemented improvements and evidence

Changes are based on original revision `510fc6daf0d1220ae796af31a65a07a262a753f9`. AUDIT.md describes that baseline; VALIDATION.md records actual verification. No learning outcomes, CEFR calibration or production pronunciation assessment are claimed.

| Original finding | Delivered change | Evidence |
| --- | --- | --- |
| P0-01 direct writes/concurrent loss | Common strict JSON storage, process/thread locks, atomic flush/replace, previous generation, explicit validated recovery | Storage tests inject replacement failure, corrupt/duplicate/nonfinite JSON, concurrent thread and four-process increments, recovery and import/export |
| P0-02 untrusted API/invalid grades | Origin/Host/token/namespace checks, bounded content/type, strict body decoding, whole-batch validation, stable retry receipts | Local HTTP tests reject malformed/cross-origin/no-token input and prove invalid batches leave cards unchanged |
| P0-03 active path escape | Validated language slugs, resolved containment and symlink rejection; request captures authorized directory | Traversal fixtures and concurrent-language-switch regression |
| P1-01 simplified FSRS | Pinned maintained py-fsrs, full learning/relearning state, precise UTC due times, stable IDs/review histories and deduplication | All four initial grades plus 250 reviews compared directly with the reference, long-gap/lapse/migration/retry tests |
| P1-02 invented knowledge | Raw attempts separate from derived skill/grammar/vocabulary summaries; legacy progress retained unverified | Estimate tampering, hinted/repeated/AI-only/easy-only/no-delay evidence rejection tests |
| P1-03 unreliable assessment | Explicit task/rubric schemas, descriptive uncertainty, missing-modality reporting, bounded internal readiness and actual human-review attestation for progression | Positive and negative gate/progression tests, authored 30-item diagnostic bank, live certification explicitly absent |
| P1-04 prompt-only adaptation | Persistent plans, recoverable session state, explicit step transitions, prerequisites, recent-domain balance, delayed retrieval and confirmed-error priority | 100 simulated sessions; resume/replay, future dates, prerequisites, long inactivity and recurring-error recovery tests |
| P1-05 Russian support | Russian onboarding/CLI feedback, evidence-sensitive language policy and 31 contextual L1 patterns linked to all 60 catalog units | Catalog/KB reference/reachability checks, Russian feedback integration and audio-only-diagnosis rejection |
| P1-06 browser loss and false promises | Per-review save, per-batch durable browser outbox, acknowledgments/retry, scoped drafts, separate completion event, explicit demos and accurate review messages | HTTP receipts and Node transport scenarios; actual IAB flashcard/quiz flows, including `I love coffee` retained as needs_review |
| P1-07 prose-only voice validation | Executable pass/report schema/binding/completed-step checks, limited correction fields and unverified evidence labels | Valid/invalid pass/report regression cases and updated contract selfcheck; actual voice/audio truth remains outside validator |
| P2-01 no reproducible tooling | Runtime/dev manifests, formatting/lint/type checks, Python/platform CI and Node checks | Commands and actual platform results in VALIDATION.md |
| P2-02 implicit cloud TTS | Local OS/browser default, explicit cloud selection, bounded synthesis/cache writes and timeout cleanup | Mock tests prove credentials alone do not enable cloud and timeout leaves no temporary audio; real cloud calls not tested |
| P2-03 alternative penalties | Accepted alternatives and conservative normalization, reviewable open/unlisted answers, distinct naturalness/context/register judgments | Unit/HTTP tests and actual browser alternative-answer check |
| P2-04 unsupported curriculum claims | Explicit 60-unit catalog/DAG/outcomes, repairs in 32 lesson files, rewritten syllabus/research/methodology without fixed frequency/timing/certification promises | Structural/source correspondence tests and full content audit; external teacher validation remains open |
| P2-05 platform voice ambiguity | Modular optional TTS/external pass, explicit audio evidence requirements and evidence-checked deferred-speech settlement | Lifecycle/audio/debt tests; no phonetic scorer or speech capture claimed |
| Added user request: natural communication | Portable project humanize skill, Claude discovery wrapper, shared communication examples and standalone voice style summary | Both skill manifests validate; independent Russian tutoring/technical rewrite cases preserve quotations/numbers/commands and uncertainty. Host adherence still needs live acceptance |

## Independent second pass

Separate reviewers inspected the new persistence, learning, curriculum and integration code. Fixes made during that review include concurrent outbox acknowledgment loss, learner draft isolation, stale-result replay blockage, premature flashcard completion, lock-order inversion, TTS timeout cleanup, misleading treatment/display of unreviewed alternatives, missing CLI diagnosis input and active-language mutation races. Meaningful regressions cover these boundaries. Formatting, type checks and the full suite were rerun after integration.

## Compatibility and limits

Original card IDs, extra fields, memory parameters and progress files are preserved. Initialization is idempotent. Scheduling moves to the reference algorithm when a card is reviewed; exact future intervals can therefore change. Old unrecorded reviews and pronunciation evidence cannot be recovered. The previous scheduler was not equivalent to the maintained implementation.

The structured core currently supports English. Full learner archives exclude inactive languages, media and cache. Other-language authoring is explicitly experimental. Browser quizzes produce separate observed outcomes; agents must record meaningful validated attempts through the CLI rather than promote from a score. Open writing/speech progression requires real human review because LLM-only scoring is excluded. Local files/browser drafts are unencrypted personal data.

The project now has a substantially stronger local engineering foundation. Live host/model adherence, real speech providers, advanced placement, long-term learning effectiveness and calibration remain work in ROADMAP.md.
