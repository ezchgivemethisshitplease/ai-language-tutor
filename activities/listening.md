# Activity: Listening

Follow [the shared agent workflow](../docs/agent-workflow.md). **Mode:** chat responses with actual generated or recorded audio. Budget roughly 10–15 minutes when appropriate. Live storytelling with spoken answers is the separate [story-listening activity](story-listening.md).

## Choose a task

- **Dictation:** a short set of sentences using familiar language and a useful current contrast. Check whether the response reflects vocabulary, sound perception, word boundaries or spelling; a transcription miss alone does not establish its cause.
- **Comprehension:** a short spoken message or passage followed by gist and detail questions. Choose complexity from observed understanding, not a guaranteed percentage of known words.
- **Micro-listening:** discriminate a real audio minimal pair, number, date or time. Keep the answer hidden before the attempt.

State the replay conditions before an assessment. In practice, let the learner request a useful replay; in a check, record the support used. One play at a high course level is a possible task condition, not a universal rule.

## Deliver the audio

For replayable dictation, prepare `student/dictation-current.json` using language-neutral `l1` for an optional translation; legacy `es` is readable but is not the default. Validate it, then use the browser workflow:

```sh
python tools/tutor.py validate-activity dictation student/dictation-current.json
```

The dictation app lets the learner replay a sentence and reveal its text. Revealing the answer changes the conditions: do not treat a later copied response as unaided listening. Browser receipts are available through `tutor.py events` and are separate from mastery observations.

Without the browser, use TTS one item at a time once the learner is ready. Avoid exposing the script in the visible teaching message before a listening attempt. If the environment necessarily exposes it, describe the task as supported listening/read-along rather than unaided assessment. When no audio is available, offer a reading activity and leave listening unassessed.

## Feedback and evidence

Ask what they understood before explaining a missed detail. For a suspected connected-speech problem, replay the exact segment, show its written form after the attempt, and explain the relevant boundary or reduction. Do not use an invented phonetic spelling as a measurement.

Record `listening_comprehension` or `minimal_pairs` tasks with an actual audio reference, a stable item ID and the exact response through `tutor.py attempt`. Use accepted alternatives or contextual review. Preserve replay/hint use and judgment provenance. Tag a Russian KB pattern only when the observed evidence supports it; audio-only tags require audio evidence.

Useful vocabulary may become contextual cards through the SRS CLI within the current plan's workload. Complete the planned step through `tutor.py step`. Do not manually change progress, error counts or known-word lists.
