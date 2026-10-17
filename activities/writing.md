# Activity: Writing

Follow [the shared agent workflow](../docs/agent-workflow.md). **Mode:** chat. Budget roughly 10–20 minutes when appropriate.

## Set a purpose and audience

Choose a meaningful task from the selected unit: a personal note or short description, a message recounting an event, a connected explanation, a review or recommendation, or an extended argument/report. Match complexity to observed performance and the learner's goal. If length matters, state a manageable target as a task condition, not a universal CEFR word count or proficiency measure.

Give an audience, purpose and a few required content points. Make room for current unit language without forcing awkward forms. For exam preparation, verify the current provider's task requirements; a locally generated task is not an official exam.

## Declare a rubric and give feedback

Create a `short_writing` or `extended_writing` exercise with rubric criteria such as task fulfilment, organization, range and language control. Each description should explain what success means for this audience. The review schema scores each declared criterion from 0 to 1 and records a source, judgment and rationale. This is an instructional judgment, not a calibrated CEFR score.

1. Identify something that works, using a specific example from the text.
2. Select a small number of useful improvement targets. Prioritize meaning and the learner's current objective; do not pretend every unmarked phrase is correct.
3. Prompt repair on a marked example before revealing a correction when useful. Distinguish an error, a valid alternative, an unnatural phrase, unsuitable register and a meaning that does not fit the context.
4. Offer a corrected version that preserves the intended message. Explain consequential changes rather than silently rewriting the learner's voice.
5. Ask for a new sentence or brief revision that uses the contrast. Record support; a corrected copy is not an independent assessment.

Do not automatically reward complexity over clarity, or fluent simplicity over appropriate range. Evaluate whether the writing achieves its purpose with the language attempted.

## Evidence and follow-up

Save the exact original response and record it with `tutor.py attempt`, adding the review file and its true `llm` or `human` source. Keep later independent work under a new stable item ID; retrying an identical submission uses the same attempt ID. Use `--hints-used` for supported attempts and confirmed error tags only when the example warrants them.

Use [Russian contrastive feedback](../languages/english/l1-notes/russian.md) where it clarifies an observed problem; Russian remains available on request at every level. Add selected useful cards through the SRS CLI under the current workload plan, without requiring a card for every corrected sentence.

Complete the planned step through the CLI. Stored observations drive estimates and internal readiness; do not write rubric totals into legacy progress or manually promote a learner.
