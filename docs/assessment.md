# Diagnostics, provisional entry and assessment limits

The assessment bank contains 100 original tasks across A1–C1: reading, listening with hidden delivery scripts, controlled form checks, open writing and actual speaking. These are curriculum design labels. The project has no calibrated item difficulties, CEFR cut scores, equated forms, rater-reliability study or certification authority.

A continuing learner can enter suitable practice without pretending that every earlier unit is mastered. The system records a provisional routing decision, its original evidence, the assumed prerequisite IDs and confirmation probes. It does not insert mastery, known vocabulary, a human signature or an overall CEFR result.

## Why the distinction matters

The Council of Europe describes classroom assessment as a way to inform teaching, concentrating on what learners demonstrate in relevant tasks. It distinguishes this from reporting an attained level, where training and double marking can help reduce subjectivity. See [Classroom assessment](https://www.coe.int/en/web/common-european-framework-reference-languages/classroom-assessment) and [Assessment](https://www.coe.int/en/web/common-european-framework-reference-languages/assessment).

Claims that an examination is linked to CEFR require an explicit argument involving content specification, standardisation and validation. A few labelled tasks and a percentage do not establish that link. The [Council of Europe linking manual](https://www.coe.int/en/web/common-european-framework-reference-languages/relating-examinations-to-the-cefr) and [test-development guidance](https://www.coe.int/en/web/common-european-framework-reference-languages/developing-tests-examining) inform the safeguards here; they do not endorse or validate this instrument.

## Run a diagnostic without revealing answers

Use the repository virtual environment. After `init`, start or resume a stored session:

```sh
python tools/tutor.py start
python tools/tutor.py items --level B1 --limit 14
```

The learner-facing item view omits answer keys, grammatical hints, corrective explanations and listening transcripts. Reading passages and response options remain visible. Rubric descriptions communicate the requested performance; they are not answer keys. The tutor controller may inspect full definitions with `items --level B1 --limit 14 --controller`. Never paste controller output into the learner-facing conversation.

The reported history, goals and previous study can guide which level to sample. They supply no scored evidence. Sample another level explicitly if the tasks are plainly unsuitable, record the result and keep unassessed skills unknown. Present one task at a time. Diagnostic `skill_id` identifies a curriculum sampling stratum; broad communicative success does not prove that unit's particular grammar outcomes.

Save the original complete item definition and exact independent response as UTF-8 files. Preserve the response before hints, corrections or a style-editing pass. Use a stable attempt ID:

```sh
python tools/tutor.py validate-exercise exercise.json
python tools/tutor.py attempt --session SESSION_ID --exercise exercise.json --response-file response.txt --id ATTEMPT_ID
```

All bank tasks have `purpose: diagnostic` and a stable `family_id`. They remain observations and assessment evidence, but are excluded from unit, grammar and vocabulary mastery caches. Separate targeted learning checks must demonstrate the actual unit outcomes over time.

## Listening requires actual delivery

Each listening item contains an original TTS script in `delivery.text`, a replay limit and `transcript_visible: false`. No human recording is bundled. Reading that script silently measures reading, not listening. Native synthesis runs locally and does not print the script or keys:

```sh
mkdir -p work
python tools/tutor.py audio diag-b1-listening-01 work/listening.aiff
```

macOS requires `.aiff` or `.aif` and uses its installed English voice. Linux requires `.wav` and eSpeak. A destination must be new and its parent directory must exist. Play the resulting stimulus to the learner through the actual supported audio channel; a generated file alone does not establish that playback occurred. Synthetic speech is not learner speech or a validated simulation of natural listening conditions.

After actual delivery, attach the stimulus reference as `audio_evidence` in the controller's exercise definition and save a presentation record, for example:

```json
{
  "audio_played": true,
  "transcript_shown": false,
  "answer_revealed": false,
  "plays": 1
}
```

Pass that file with `attempt --presentation presentation.json`. Record what actually happened. Missing audio references, an absent delivery record, a visible transcript, an exposed answer, excessive replays or hints prevent independent diagnostic listening credit. The system validates these declarations; it cannot authenticate physical playback or stop a person inventing a reference. A learner's spoken production needs its own actual voice evidence, not the stimulus TTS file.

## First responses, alternatives and later review

One stimulus family supplies at most one independent diagnostic trial across sessions. The first trial owns that slot even when it was hinted, incorrect or awaiting review. Changing an item ID, repeating a known answer, adding another question about the same passage or starting a new session does not create independent evidence. Consumed diagnostic families disappear from `items`. Author and review genuinely new material when more samples are needed.

Unlisted wording in an open or non-exhaustive task remains `needs_review`. Preserve it immediately; review can follow later without issuing the task again:

```sh
python tools/tutor.py review --observation ATTEMPT_ID --review review.json --id REVIEW_ID
```

The review file uses the original rubric criteria, `source: llm|human`, an explicit judgment and rationale. Scores must cover every criterion. Only an actual human review may use `source: human`; the local record does not authenticate identity. Audio-domain reviews require an actual audio reference. Level/task-specific rubric anchors describe expected organisation and language control without demanding native accent, elaborate wording for its own sake or fixed error counts.

Reviews are append-only annotations. The raw response, exercise, initial grade and original date remain unchanged. Derived effective grades identify the review IDs; review retries are idempotent and reject altered content. An LLM cannot overwrite a human rating or a definite deterministic result. A human can explicitly correct an incomplete answer key, retaining the original result and rationale in history. A corrected diagnosis no longer supplies confirmed recurring-error evidence. Late review does not refresh an old trial or create another trial.

## Provisional advanced entry

```sh
python tools/tutor.py placement --target-level B1
python tools/tutor.py accept-placement --target-level B1
python tools/tutor.py plan
```

Acceptance requires fresh first trials from registered, unchanged bank definitions with:

- At least three independently scored reading families and three actual-audio listening families at the requested curriculum target.
- At least three different curriculum sampling units across those receptive trials.
- At least 0.8 observed success in each receptive domain; one domain cannot compensate for another.
- Deterministic scoring, no hints or revealed answers, and trial dates within 90 days.

These are explicit product safeguards, not validated placement cut scores. Six successful tasks still provide limited evidence. The report exposes task counts and a descriptive Wilson reference interval for observed success. The purposively selected tasks and family controls do not establish random sampling or calibrated uncertainty about latent proficiency; the interval is not a CEFR confidence interval.

Writing and speaking are reported separately. Controlled sentence transformations do not count as broad writing. LLM-only production reviews remain provisional and cannot supply confirmed productive evidence or objective receptive routing. Missing or sparse production remains marked as unconfirmed. Initial advanced routing selects receptive practice; it does not declare productive competence.

A stored decision retains its target and cited evidence. The planner may provisionally assume lower-level ancestors of entry units for lesson selection, clearly listing those assumptions and adding prerequisite probes. Within-level prerequisites still require actual mastery. Evidence ageing, new difficulty or a bank update produces `recheck_required`; it does not silently send the learner back to A1. Continue sampling and revise the route deliberately when warranted. Old evidence remains dated and inspectable.

## Progression remains a separate gate

`gate --target-level B2` can use an active B1 routing decision as the current course for evaluating B1→B2 readiness. It still requires genuine mastery of every B1 unit and fresh four-domain evidence, including open writing and actual speech. Diagnostic routing assumptions never satisfy those mastery checks.

Actual `progress` also requires an explicit real human review. The decision records the effective current course, the previous nominal baseline and the routing decision ID. A successful transition deactivates the superseded provisional route. The result is internal course progression, never a CEFR certificate.

## Persistence and verification

Raw observations and review annotations are retained. Derived-cache policy corrections may make an earlier cache stale. `validate` fails instead of silently changing it. Use `reconcile` explicitly to reconstruct estimates and error indexes from validated raw evidence; the normal storage transaction preserves the prior JSON generation. Malformed responses, annotations or routing references are rejected rather than repaired. Back up valuable learner data before recovery.

```sh
python tools/tutor.py reconcile
python -m unittest tests.test_assessment tests.test_learning tests.test_linguistic_review -v
```

The fixtures simulate declarations and scores; they do not constitute learner validation, actual human ratings or proof of playback. Open issues include empirical item/rater studies, larger independent forms, naturally recorded audio and live teaching acceptance. See ROADMAP.md.
