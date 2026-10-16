# Portable teaching workflow

Codex loads root AGENTS.md; Claude Code imports the same file through CLAUDE.md. No custom MCP, model API, paid speech service or agent-specific skill is required. Shell/file-capable agents invoke the same Python CLI. This is source-contract compatibility; live model adherence is not established by unit tests.

## Prepare and resume

From an activated virtual environment:

```sh
python tools/tutor.py init --native-language russian --daily-minutes 30
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

Save the exact response as UTF-8 and invoke:

```sh
python tools/tutor.py attempt --session SESSION_ID --exercise exercise.json --response-file response.txt --id ATTEMPT_ID
python tools/tutor.py step --session SESSION_ID --step learn-1
```

Use a unique stable ID per actual trial; retries must reuse it and identical payloads. Hints, retries and LLM ratings do not establish independent mastery. Never change an exercise's semantics while retaining its item ID. Unknown translations/transformations remain `needs_review` unless the accepted answer set is genuinely exhaustive. Use multiple accepted alternatives, not a blanket exact-match penalty.

Open tasks (`dialogue`, `short_writing`, `extended_writing`, `spoken_response`) require `rubric: {criterion: description}`. A review file contains `source` (`llm` or `human`), `judgment` (`correct`, `correct_alternative`, `incorrect`, `unnatural`, `stylistically_inappropriate`, `contextually_inappropriate`), `rationale` and `criteria` (all rubric criteria, each scored 0–1). Inspect the actual schema in `learning._review_grade`; validate before use. `--review review.json` records provenance. A stylistic judgment must explain the audience/context, not erase a grammatical alternative. Audio tasks require an audio reference and actual sound; a filename does not prove the evaluator listened.

Mastery estimates are derived from raw observations, never from session completion. The current policy requires distinct items, multiple sessions/dates, delayed retrieval and productive evidence. These are conservative course safeguards, not empirically calibrated probabilities. Read PEDAGOGY.md for thresholds and limitations.

## Placement, checks and course progression

```sh
python tools/tutor.py items --level A1 --limit 6
python tools/tutor.py assess --level A1
python tools/tutor.py gate --target-level A2
```

The authored bank is deliberately small: 30 original A1–C1 tasks, including open production prompts but no bundled listening recordings. Use these to find an appropriate provisional starting point and gaps. Do not infer unseen vocabulary or assess listening from visible text. Generate further reviewed tasks with original contexts and report uncertainty. Missing writing/speaking/listening evidence remains missing.

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
python tools/tutor.py export /safe/location/learner-export.json
python tools/tutor.py import /safe/location/learner-export.json /new/location/restored-student
python tools/tutor.py recover learner.json
```

Exports include the active English learner, deck, legacy progress/profile/text logs and activity receipts. They exclude credentials, control tokens, audio cache, images and inactive languages. Import validates before creating a new directory; use `--student-dir` or the environment variable to select it. Do not export into the live learner directory. Recovery restores a validated `.bak` generation and preserves current bytes as `.recovery-*`. Backups are local; copy an export to your own durable backup storage. JSON files are human-readable personal information, not encrypted.
