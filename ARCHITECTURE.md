# Architecture and decisions

The system is a single-user local tutor with an agent-independent deterministic core. It supports macOS and Linux. The browser host uses Python 3.10+, Node.js 22+/npm 10+ and a pinned standalone Codex CLI with ChatGPT login. Codex Desktop is optional; the existing shell/file-capable Codex/Claude workflow remains available. Generated teaching content still needs linguistic review. There is no public server, application user database or frontend compilation step.

## Component boundaries

```text
Codex AGENTS.md / Claude CLAUDE.md
        │ shared workflow + humanize communication skill
        ▼
tools/tutor.py ── tools/learning.py ── catalog + L1 KB + authored diagnostics
        │               │
        │        observations → derived estimates → stored plans/gates
        ▼
tools/storage.py ← tools/srs.py ← maintained fsrs==6.3.2
        ▲
tools/serve.py ← static apps + same-origin client + durable browser outbox
        │
        ├── web_tutor.py ← curated tutor tool / canonical human messages
        │       └── codex_bridge.py ← stdio JSONL ← independent Codex app-server
        │                                  └── isolated Codex-owned ChatGPT login
        │
        └── optional TTS / external voice pass validation
```

| Component | Responsibility | Excluded claims |
| --- | --- | --- |
| `learning.py` | Validate evidence, derive skill/grammar/vocabulary summaries, select prerequisite-eligible practice, manage session/debt transitions and internal readiness | Calibrated CEFR, semantic grading of arbitrary language, actual audio verification |
| `tutor.py` | Idempotent initialization/migration, transactional CLI mutations, diagnostics, export/import and recovery | Automatic human identity verification or autonomous certification |
| `srs.py` | Card validation/deduplication, stable IDs/history, FSRS adapter, explicit grades, idempotent review batches | Fitted learner-specific retention without an optimizer/data |
| `backup.py` | Bounded all-language managed-data/media archives, checksums, new-directory restore, opt-in rotation | Automatic off-device setup, encryption, physical power-loss guarantees or arbitrary-file backup |
| `storage.py` | Strict JSON decoding, process/thread locks, atomic durable replacement and previous-generation backup | Database transactions across arbitrary files or network-filesystem guarantees |
| `serve.py`, `activity.py` | Bounded same-origin local API, content identities, server-side quiz outcomes and result receipts | Internet hosting, multiuser security or browser quiz completion as mastery |
| `client.js` | Token/namespace transport, per-batch localStorage outbox and retry acknowledgment | Guaranteed browser-storage durability after user deletion/private-mode restrictions |
| `web_tutor.py`, `chat.js` | Durable conversation receipts, streamed replies, profile/session controls, curated teacher actions bound to actual human message IDs | Invented answer text, human attestation or fabricated audio evidence |
| `codex_bridge.py` | Pinned app-server JSONL, correlation, bounded FIFO events/tools, isolated auth, declined approvals, restricted named permissions | Generic browser RPC, inherited Desktop tools or stable production API guarantees |
| `voice.py`, `tts.py` | External pass/report structure and optional synthesis/playback | Acoustic pronunciation scoring, STT or verified live speech assessment |
| `speech.py`, `speech_service.py`, `speech.js` | Optional pinned native Whisper/FFmpeg, explicit bounded capture, local ASR into a protected draft, source provenance and local-voice playback | Acoustic assessment, independent writing from dictation or automatic message sending |

## Decision 1: use the maintained FSRS implementation

The original simplified algorithm lacked learning/relearning states and persistent review history. The adapter now uses [py-fsrs 6.3.2](https://github.com/open-spaced-repetition/py-fsrs/blob/v6.3.2/README.md), pinned with its typing dependency in requirements.txt. UTC scheduling retains minute learning steps; default retention parameters remain library defaults. Fuzzing is disabled to make simulations/retries reproducible.

A card retains its external ID and unknown learner fields. Canonical FSRS state is stored alongside compatibility mirrors (`S`, `D`, date-only `due`, counters). `due_at` is authoritative for precise scheduling. Existing memory-state parameters migrate at first review; old due dates remain respected before conversion. Reviews that were never stored cannot be reconstructed. New reviews carry stable IDs, explicit grades, prior/current schedule and the reference review log. Duplicate content/IDs and invalid batches are rejected or deduplicated before mutation. Idempotent receipts survive a lost HTTP response.

No optimizer is fitted. Exported histories support later analysis, but adding an optional optimizer requires sufficient real data, evaluation splits and privacy decisions. The regression suite compares initial grades and a 250-review sequence directly against the pinned reference, including long gaps and relearning.

## Decision 2: preserve JSON and serialize mutations

The original file layout is useful for a local agent. Replacing it with a database would impose migration/inspection cost without evidence that this workload needs it. A common storage layer now serializes read/modify/write operations with a stable sidecar lock. Thread locks combine with POSIX `flock`; a stable sidecar remains locked while the JSON destination is replaced.

Writes serialize with finite JSON values, write a temporary file, flush it, replace the destination and sync the directory where supported. macOS additionally uses full fsync when available. The previous valid JSON is written atomically to `.bak`. A failed operation never silently substitutes an empty learner; explicit recovery validates the backup and preserves current bytes. These follow the semantics of [Python persistence APIs](https://docs.python.org/3/library/os.html#os.replace). Filesystem/hardware durability still has practical limits.

Read/modify/write operations with concurrent writers use `transaction`; atomic `save` alone does not serialize them. The web conversation cache instead has one host, enforced by a learner-specific lifetime process lock and an in-process lock. Locks are advisory. External manual editors can bypass them. File-level transactions do not make a deck write and completion event a single database transaction. Durable receipts make retries recoverable. Export acquires data locks in a consistent order; import stages validated data and publishes a new directory, preserving the live learner.

## Decision 3: observations are authoritative, estimates are derived

`student/english/learner.json` schema version 1 stores raw exercise definitions, responses, dates, assistance, source labels, explicit error diagnoses and session/attempt identity. Skill, grammar and vocabulary summaries are derived and cross-checked against observations during validation. Later rubric reviews are append-only annotations; the effective evidence view retains the first trial date, raw response and initial grade. Repeated/hinted family attempts cannot replace that first independent trial. Explicit `reconcile` rebuilds only derived caches from validated evidence. Tampering with an estimate cannot silently unlock a unit. The original progress/history is preserved under legacy metadata and in its original files; it never becomes invented mastery.

The policy requires item diversity, multiple sessions/dates, delayed evidence and productive use. A repeated easy item, hints and LLM-only marks cannot establish mastery. Descriptive Wilson intervals are accompanied by sample counts and uncertainty; task sampling is not psychometric calibration. `assessment_summary` leaves missing modalities unknown. Internal progression requires the deterministic gate plus a recorded actual human review. Reviewer provenance is local attestation, not authentication.

A provisional entry decision may route a continuing learner to a higher material level after fresh authored reading/listening probes. It records assumptions and evidence digests, leaves productive skills/prerequisite mastery unknown and schedules confirmation. All diagnostic-bank items are excluded from unit mastery. A stale route requests rechecking without silently resetting the learner. Progression still requires actual mastery at the effective current level, fresh broad four-domain evidence and human review.

The planner allocates due retrieval, confirmed recurring-error work, overdue mastered skills and prerequisite-eligible material. Recent domain counts guide balance. This is a documented heuristic selector, not an estimated optimal learning policy. The 60-unit graph and Russian KB link lesson objectives to contrasts/remediation. A candidate L1 tag does not itself diagnose the learner.

## Decision 4: explicit session state and constrained generation

Stored plans use stable session and step IDs. Sessions transition through active, interrupted, completed or abandoned states. Re-entry resumes the saved plan; incomplete work cannot silently become completion. Deferred speech remains visible, with later eligible matching audio evidence required to settle the debt. Attempt IDs reject altered replays; item IDs cannot change their scoring definition across observations.

Generated exercise JSON has a validated type, domain, level, skill ID and either accepted alternatives or an explicit open rubric. The CLI checks skill/level against the catalog. Unknown non-exhaustive wording stays reviewable. Grammar accuracy, naturalness, register and context are distinct review judgments. Schemas validate shape and declared evidence, not truth or linguistic validity. Agents remain responsible for fair prompts/keys and must not impersonate a human reviewer.

## Decision 5: one agent contract and a portable communication skill

AGENTS.md owns workflow invariants; CLAUDE.md imports it. Activity files provide concrete teaching procedures without replacing executable state transitions. The shared CLI runs in either host, following [official Codex instruction discovery](https://developers.openai.com/codex/guides/agents-md/) and [Claude import semantics](https://code.claude.com/docs/en/memory). Host capability/discovery and model adherence remain acceptance-test concerns.

The canonical `.agents/skills/humanize/SKILL.md` contains a small embedded prose-editing workflow. `.claude/skills/humanize/SKILL.md` routes Claude discovery to it. Both are ordinary files and resolve their references from the repository. AGENTS.md loads the canonical skill; docs/communication.md supplies examples. Raw answers, keys, code, numerical evidence, grades and provenance are protected. There is no regex authorship detector or runtime rewrite of learner evidence. External voice receives a self-contained style summary because it cannot read repository files.

## Decision 6: local browser service with explicit trust boundaries

The server binds to 127.0.0.1, validates local Host/Origin/fetch metadata and requires a random token plus learner namespace for mutations. It captures the active language once to prevent a concurrent switch redirecting grades. Request sizes/types are bounded, JSON is strict, and static serving is restricted to the apps directory. CSP, no-store, no-referrer and nosniff headers reduce browser exposure. This follows [OWASP CSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html); loopback alone was insufficient.

The browser persists every submission under its own stable batch ID before delivery. Namespace boundaries prevent another learner's drafts/results being replayed on the same port. Server receipts acknowledge saved requests even if the current prepared activity changed. Unresolved stale submissions remain visible and retained. A failed unrelated stale result does not prevent all other apps loading. Flashcards autosave individual reviews; only an explicit completion endpoint releases the agent's activity wait. Quiz results are recomputed server-side and retained separately from mastery.

This protects ordinary local use, not a hostile process running as the user, disk theft or shared-host multiuser access. Personal JSON and browser drafts are not encrypted. Coding-agent providers receive the context read into their conversation. Optional external TTS/voice/image providers receive explicitly supplied content. API credentials remain environment-only; access logs omit learner text/tokens.

## Decision 7: reproducible verification before broader claims

Requirements pin the reference scheduler and development tools. CI uses read-only repository permissions and verified full action commit references, based on [GitHub's secure-use guidance](https://docs.github.com/en/actions/reference/security/secure-use). Unit/integration tests use temporary learner data. Node checks exercise transport concurrency/retry/isolation and parse browser scripts. Actual browser flows are checked separately. VALIDATION.md records outcomes and distinguishes local tests, hosted CI, source contracts, live providers and educational evidence.

## Decision 8: verified archives and owner-configured rotation

The legacy JSON export remains compatible. `backup.py` additionally snapshots managed learner documents for all languages and original learner media under a common lock order. Archives have explicit scope, quotas, byte lengths and SHA-256 checksums. Stored-only ZIP, a bounded directory parser, strict schemas and canonical path/member validation keep restore work bounded. Media is streamed; credentials/control/cache/arbitrary files are excluded. Complete validation precedes restore staging; exclusive OS rename publishes a new tree without replacing even a concurrently created empty directory.

Rotation is opt-in through environment configuration and runs after committed mutations release their locks. An optional mount requirement prevents a missing drive from silently becoming a local destination. The latest interval check reads bounded metadata; creation, restore and removal decisions receive full validation. Backup failure remains distinct from the already saved attempt or review. Browser acknowledgments show both outcomes. No daemon, cloud account, off-device path or encryption is configured automatically. See [policy and format](docs/backup.md) for scope, trust boundaries and process-crash drills.

## Decision 9: independent local web teacher

The official [Codex app-server](https://learn.chatgpt.com/docs/app-server) supports embedding Codex in local applications. This adapter pins CLI `0.163.0` because the protocol and dynamic tools are experimental. Each server owns a subprocess over stdio; no app-server network listener or Desktop connector is involved. Codex owns the official ChatGPT login and refresh in a separate `.runtime/codex-home`. The browser gets a validated login URL and a minimal account status, never credential tokens. Account/model eligibility and subscription limits remain service-controlled.

The child receives a small environment allowlist. Host hooks, plugins, apps, shell, browser, computer, agents, skills discovery and web search are disabled. A named deny-by-default permissions profile permits reading only its empty teaching workspace and minimal platform paths, disallows writes and blocks tool network. Codex's own inference/auth networking is separate from agent tool networking. Teaching references arrive through allowlisted Python tools, not unrestricted files. These controls are pinned to the actual release schema; the newer online `readOnly.access` example is not accepted as a security guarantee for this version.

`student/web-chat.json` holds human/assistant transcripts, stable request receipts and prepared task definitions. A human message is saved before starting inference. Attempts read that exact stored message and require a task registered before it; the model cannot supply replacement response text. Reviews are forced to `source: llm`; progression signing and audio claims are absent. A lost start reply retires the connection/thread before another turn, and old-generation/old-turn events and tools are ignored. Failed history writes roll back in-memory receipts and disable mutations until storage is repaired and the server restarted. A lifetime learner-specific process lock prevents two local servers from overwriting cached chat state.

Managed ZIP backups include the transcript but exclude Codex auth/rollout data. After restore, missing Codex threads are replaced with a new thread and selected transcript context; the learner evidence remains canonical. The compatible legacy JSON export retains its previous scope. Browser dialogs do not cover human review, emergency JSON recovery or archive restore; those remain explicit CLI operations. The web host also leaves live speech assessment to the external voice workflow.
