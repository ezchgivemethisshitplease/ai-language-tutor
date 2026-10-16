# Portable teaching workflow

Codex loads root AGENTS.md; Claude Code imports the same file through CLAUDE.md. No custom MCP, model API, paid speech service or agent-specific skill is required. Shell/file-capable agents invoke the same Python CLI. Selected live host acceptance is recorded in `host-acceptance.md`; unit tests establish deterministic contracts, not future model adherence.

## Prepare and resume

From an activated virtual environment:

```sh
python tools/tutor.py init --native-language russian --daily-minutes 30 --objective "Read work emails"
python tools/tutor.py status
python tools/tutor.py start
```

`start` returns a stored session with an `id` and numbered plan steps; on re-entry it returns the existing session instead of generating another. Read its exact ID from JSON. Reuse it in every mutation. `plan` previews without starting. `--student-dir PATH` before the subcommand and `TUTOR_STUDENT_DIR=PATH` support isolated fixtures; the environment variable also applies to SRS/server/TTS.

## Exercises and observations

An original constrained exercise file:

```json
{
  "id": "a1-be-introduction-001",
  "type": "cloze",
  "skill_id": "a1-01",
  "level": "A1",
  "domain": "grammar",
  "prompt": "I ___ a student.",
  "answers": ["am"],
  "exhaustive": true,
  "error_tags": ["be_omission"]
}
```

Choose error IDs from russian.json; `be_omission` is the Russian zero-copula contrast. `error_tags` on an exercise are hypotheses. Only pass `--error-tag` after the actual response supports a diagnosis. A supplied tag must exist in the KB; audio-only tags require audio evidence.

Validate the full controller exercise with `python tools/tutor.py validate-exercise exercise.json` before presenting it. Save the exact response as UTF-8 and invoke:

```sh
python tools/tutor.py attempt --session SESSION_ID --exercise exercise.json --response-file response.txt --id ATTEMPT_ID
python tools/tutor.py step --session SESSION_ID --step learn-1
```

Use a unique stable ID per actual trial; retries must reuse it and identical payloads. Hints, retries and LLM ratings do not establish independent mastery. Never change an exercise's semantics while retaining its item ID. Unknown translations/transformations remain `needs_review` unless the accepted answer set is genuinely exhaustive. Use multiple accepted alternatives, not a blanket exact-match penalty.

Open tasks (`dialogue`, `short_writing`, `extended_writing`, `spoken_response`) require `rubric: {criterion: description}`. A review file contains `source` (`llm` or `human`), `judgment` (`correct`, `correct_alternative`, `incorrect`, `unnatural`, `stylistically_inappropriate`, `contextually_inappropriate`), `rationale` and `criteria` (all rubric criteria, each scored 0–1). Inspect the actual schema in `learning._review_grade`; validate before use. `--review review.json` records provenance. A stylistic judgment must explain the audience/context, not erase a grammatical alternative. Audio tasks require an audio reference and actual sound; a filename does not prove the evaluator listened.

A later review uses `python tools/tutor.py review --observation ATTEMPT_ID --review review.json --id REVIEW_ID`. This appends an idempotent annotation while preserving the original exercise, response, initial grade and trial date. LLM reviews cannot override a human review or a definite deterministic result. `python tools/tutor.py reconcile` explicitly rebuilds stale derived caches after a policy update; it never repairs or invents raw evidence.

Mastery estimates are derived from raw observations, never from session completion. Diagnostic-bank tasks support diagnostics and never establish unit mastery. The current policy requires distinct items, multiple sessions/dates, delayed retrieval and productive evidence. These are conservative course safeguards, not empirically calibrated probabilities. Read PEDAGOGY.md for thresholds and limitations.

## Placement, checks and course progression

```sh
python tools/tutor.py items --level A1 --limit 6
python tools/tutor.py assess --level A1
python tools/tutor.py gate --target-level A2
```

The bank has 100 original tasks across A1–C1, including 20 independent listening scripts, extended/open writing and real-speech prompts. `items` returns learner fields without keys or audio scripts; add `--controller` for the full exercise saved by the tutor. Do not pass a redacted learner view to the scorer. Native English audio can be prepared without printing the script:

```sh
python tools/tutor.py audio diag-a1-listening-01 /existing/path/stimulus.aiff
python tools/tutor.py placement --target-level B1
python tools/tutor.py accept-placement --target-level B1
```

Linux uses `.wav` with eSpeak; macOS uses installed Samantha speech. No playback or cloud call occurs. Actually present the audio, hide transcripts/keys, record the audio reference and the truthful `--presentation FILE` fields. Missing real listening stays missing. The application does not authenticate a playback claim or grade acoustics.

Provisional entry requires fresh independent authored reading/listening evidence across multiple units. It selects materials at the sampled level while retaining the nominal baseline and unconfirmed production/prerequisites. Confirmation probes revisit those assumptions; diagnostic items cannot inflate mastery. The [assessment policy](assessment.md) documents thresholds, family independence, uncertainty and later reviews. These are local course safeguards, not CEFR calibration.

`gate` lists every missing requirement. If it succeeds, a real human may submit a review JSON with exactly `source: "human"`, `reviewer`, `rationale`, `evidence_reference`, then use `progress --target-level A2 --human-review review.json`. This attestation is recorded, not authenticated. The result advances internal curriculum planning and never certifies CEFR. An AI cannot sign as that human.

Weekly checks use the same observation path and `assess`; they do not change levels. Delayed cumulative reviews and remedial lessons are selected by `plan`. A legacy level is retained as a working starting point with `legacy_unverified`, while its old completion records do not unlock prerequisites.

## Finish, interrupt and debt

```sh
python tools/tutor.py interrupt --session SESSION_ID
python tools/tutor.py resume --session SESSION_ID
python tools/tutor.py step --session SESSION_ID --step STEP_ID --defer
python tools/tutor.py finish --session SESSION_ID
```

Only voice steps may be explicitly deferred. `finish --allow-incomplete` closes unfinished work as abandoned. Preserve the distinction in feedback. To settle a deferred spoken skill, use `settle-debt --session ORIGIN_SESSION_ID --observation OBSERVATION_ID` after a later eligible matching speech observation; no typed or AI-only report can settle it.

## Browser observations

Prepared browser quiz schemas remain compatible with `choice|gap|reorder` (`answers` accepts alternatives). Use `exhaustive: true` only for constrained tasks. New dictation uses language-neutral `l1`; legacy `es` remains readable. Validate with `validate-activity`, then open the matching app on localhost. Browser results are stored separately in `activity-results.json`; `events` prints durable receipts. They are observed item responses, not automatically accepted mastery. Record pedagogically meaningful independent observations via the CLI, preserving provenance and item identity.

Flashcard reviews are applied immediately and idempotently. The completion event is separate. Review due times use UTC; historic date-only records migrate without inventing review history. FSRS minute steps are not a promise of fixed “~4 days” on every card.

## Data ownership and recovery

```sh
python tools/tutor.py backup /existing/safe/location/learner.zip
python tools/tutor.py backup-check /existing/safe/location/learner.zip
python tools/tutor.py restore /existing/safe/location/learner.zip /new/location/restored-student
python tools/tutor.py recover learner.json
```

Full ZIP archives validate managed files across every language and learner media with sizes/checksums before publishing a new destination. They exclude credentials, control state, caches, arbitrary files and session artifacts already captured in canonical observations. The compatible `export`/`import` JSON commands retain their active-English semantic scope. Both restoration paths preserve live data. Recovery restores a validated `.bak` generation and preserves current bytes as `.recovery-*`.

Optional rotation uses an existing `TUTOR_BACKUP_DIR`, retention/interval settings and an optional required mount. It runs after successful mutations and lock release, without installing a daemon. An unavailable backup volume reports a warning while the saved trial/review remains acknowledged. See [backup policy](backup.md) for scope, filesystem requirements, quotas, restore drills and manual scheduling. Files are personal information and are not automatically encrypted.
