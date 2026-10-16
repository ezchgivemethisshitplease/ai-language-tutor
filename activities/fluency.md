# Activity: Fluency development

Follow [the shared agent workflow](../docs/agent-workflow.md) and the [portable voice contract](../portable/voice-tutor.md). **Mode:** voice-required for spoken practice. A short repeated-talk activity often fits roughly 10 minutes; adjust the task to the learner and plan.

Choose familiar content that lets the learner focus on expressing a message with less effort. Do not promise that every word is already known. If the task repeatedly demands unfamiliar language, simplify or practise that language separately.

## Repeated talk with shrinking time

1. Choose an easy personal topic, such as work, family, a recent trip or a familiar story.
2. Allow brief preparation. Decide whether notes are available and keep that condition consistent across rounds if comparing performance.
3. Build a finite plan: preparation, then three attempts at the same message. The familiar 4/3/2-minute sequence is one option; use shorter rounds or gentler reductions if needed. Preparation ends at ready/skip. Each timed round ends at its timer or an explicit learner stop/skip, rather than after one short utterance.
4. Use the saved voice route and portable handoff. Keep corrections out of the timed rounds unless communication or wellbeing requires an interruption. The learner does not need to speak faster at the expense of intelligibility.

Afterward, discuss what the actual evidence shows: fewer abandoned phrases, clearer organization or a more comfortable delivery. Do not infer a rate or pause improvement from a model's impression if no recording or timing supports it. Increased speed is not automatically broader proficiency or retained accuracy.

## Alternatives

Try a repeated reading aloud of a familiar text, or repeat a finite set of familiar questions with less preparation on the second pass. A silent timed rereading can be a separate text activity; it does not satisfy a planned speaking step.

## Evidence and follow-up

Validate any returned voice report against its pass. Record an actual spoken task through `tutor.py attempt` with a rubric appropriate to the task, real audio evidence and honest provenance. Keep preparation, support and partial attempts visible. A fluency observation alone does not establish grammar or vocabulary mastery.

Complete the step through the CLI when its conditions are met. If the voice route is unavailable, defer the planned voice step and continue usable activities. Do not fabricate performance or manually change streak, error, knowledge or progress files. Later eligible speech can settle the recorded debt through the shared workflow.
