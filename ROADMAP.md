# Remaining work

The feasible local engineering P0/P1 work is implemented. Completion of code, editorial review and deterministic tests does not establish learning effectiveness or a certified CEFR level. The external validation items below remain explicit.

## P1 work delivered in this iteration

| Work | Delivered scope | Evidence |
| --- | --- | --- |
| Independent linguistic review | All 60 outlines, 31 Russian contrasts and 100 original diagnostic tasks checked by separate AI reviewers; meaning/alternative defects corrected; 20 independent listening contexts replace reading leakage | [Review scope, bank hash and regressions](docs/linguistic-review.md) |
| Advanced entry | Four-domain diagnostic profiles, guarded provisional reading/listening routing, confirmation probes, hidden keys/scripts, immutable first trials and append-only later reviews | [Assessment contract](docs/assessment.md), 142-test suite including positive/negative progression scenarios |
| Long-term recovery | All-language managed-data/media archives, strict quotas/checksums, exclusive new-directory restore, opt-in owner-configured rotation and nonfatal post-save hooks | [Backup policy](docs/backup.md), hostile archive tests, restore drills and four real SIGKILL checks |
| Host acceptance | Actual Codex lifecycle/humanize loading, interruption/resume, alternative answers, debt and final-code redaction; configured third-party Claude Code continuation also preserves the exact answer and session | [Host-specific record](docs/host-acceptance.md); Claude acceptance remains limited as stated below |
| Personal learning platform | Learning home, account preferences, chat-specific contexts/style overrides, confirmed scoped memory, current task, explicit lesson handoff and domain progress | [Capabilities](docs/capabilities.ru.md); 26 actual model turns across three iterations, two completed short lessons and selected actual browser flows |
| Authenticated web teacher | Owner completed the isolated project login. Fixed model-required code-mode dispatch; real status/lesson/diagnostic calls, exact-answer persistence and same-thread cold resume passed with a synthetic learner | [Web acceptance](docs/web-acceptance.md); browser/model combinations and broader teaching evaluation remain separate |

## Remaining validation and product work

| Priority | Work | Impact / effort | Acceptance evidence / dependency |
| --- | --- | --- | --- |
| P1, external | Finish Anthropic-backed Claude Code acceptance | High / small once authenticated | Existing account returns `401 OAuth access token has been revoked`; owner reauthentication is required. The configured third-party client completed persistence checks but timed out on a bounded teaching request; provider latency/configuration acceptance remains separate from the tested core |
| P1, empirical | Human assessment review and CEFR validation argument | High / large | Trained independent raters, consented learner trials, item/distractor analysis, fairness review, inter-rater reliability, standard setting and justified uncertainty. AI editorial review and synthetic fixtures cannot supply these observations |
| P2 | Listening and speech provider QA | High / medium | Naturally recorded/licensed voices, human listening/speaking trials, browser microphone/provider/OS matrix and reviewed production. Local Whisper passes synthetic macOS English/Russian/container checks; Linux native ASR and real human microphone QA remain open. No calibrated pronunciation scorer |
| P2 | Owner-specific off-device and hardware recovery validation | High / medium | Owner-configured mounted/disconnected storage, periodic real restore drills and physical power-loss/filesystem tests. Integration and process-crash recovery are implemented; no destination or remote credentials are chosen silently |
| P2 | Richer curriculum beyond grammar | High / large | Reviewed genre/pragmatics, mediation, online interaction, communicative tasks and cumulative coverage; external review of authored prerequisites |
| P2 | Vocabulary breadth and licensed frequency metadata | Medium / large | Open/licensed datasets with provenance, sense/collocation coverage and morphological text analysis. Current 672 distinct spelling strings are curated examples, not a frequency corpus or a 5,500-word course |
| P2 | Skill retention/remediation evaluation | Medium / large | Real delayed-performance data, fixed baselines and tag-specific transfer/recovery tasks. Current timing and error-recovery policies remain transparent heuristics |
| P2 | FSRS optimization after sufficient reviews | Medium / medium | Optional optimizer, held-out prediction evaluation, minimum-data policy, rollback and benchmarks. Do not fit or advertise personal calibration from synthetic histories |
| P2 | Wider browser lifecycle/accessibility coverage | Medium / medium | Real-browser E2E for private mode/quota, pending-result export/conflict UI, multi-tab close recovery, keyboard/screen-reader checks across browsers. Node transport and selected actual IAB flows are recorded separately |
| P2 | Scalable state representation | Medium / medium | Measure realistic multi-year history latency before choosing compaction, journaling or SQLite. JSON transactions currently rewrite the document; evidence must survive any migration |
| P2 | Audio cache policy and concurrent provider QA | Medium / medium | Opt-in provider calls, voice availability, expiry/deletion controls and multiprocess synthesis tests. Native synthesis is bounded; cloud-provider credentials/calls were not used for audio QA |
| P2 | More L1s and interface locales | Medium / medium | Another structured contrastive KB, localized bundles and compatibility tests. Russian has first-class structured support; Spanish Markdown survives, other L1 feedback stays generic |
| P3 | Ongoing teaching and humanize review | Medium / medium | Consented real-session review for clarity, pacing, usefulness and unchanged learner evidence across hosts/configurations. Fixed writing-pattern tests are not an authorship detector |
| P3 | Multi-device sync or public hosting | Optional / large | Product requirements, authentication, encryption, conflicts and a deployment threat model. The current loopback server stays local |

The added web host moves routine teaching, profile/session controls and practice into the browser without Desktop. Optional Whisper dictation and local-voice reply playback support spoken interaction through confirmed text. Explicit human progression review, archive restoration, emergency recovery and independently assessed speech remain separate workflows. A UI for those owner operations can be added without granting them to the AI teacher. Managed ZIP includes web transcripts and excludes Codex credentials.

Reference mismatches, lost/repeated reviews, accepted corrupt state, fabricated CEFR/human claims, or altered raw learner responses are regressions, not deferred roadmap items. Fix them before release. Human provenance and audio delivery remain declarations whose truth is outside schema validation.
