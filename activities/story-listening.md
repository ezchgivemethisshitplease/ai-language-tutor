# Activity: Story listening

Follow [the shared agent workflow](../docs/agent-workflow.md) and the [portable voice contract](../portable/voice-tutor.md). **Mode:** voice-required. Budget roughly 8–12 minutes when the learner's plan supports it.

The tutor tells an English story aloud; the learner listens and answers aloud. Do not show the story script before a comprehension attempt. Familiar spelling or a visible transcript cannot establish unaided listening.

## Prepare and run

1. Choose a topic from the selected unit and learner interests. Keep the language accessible from observed performance, with only as much new vocabulary and narrative complexity as the learner can handle. A known-word file cannot guarantee comprehension.
2. Use the saved voice route. Prepare a finite numbered plan: delivery of the story and a gist question, a detail question, then an interpretation or prediction question. Adjust the number of steps to the budget, but define every step and its completion condition before handoff.
3. A good-faith answer, «I don't know» or an explicit skip completes that attempted response step; it does not prove successful comprehension. State replay conditions and retain any support used. Give the complete handoff instructions and report-recovery path from the portable contract.
4. End at the planned final response. A brief self-correction can close the activity if an actual error occurred; do not invent one to fill the plan.

If voice is unavailable, defer a planned voice step using `tutor.py step --session SESSION_ID --step STEP_ID --defer`. Continue other usable practice from the session plan; do not replace speech with typing or call the activity complete.

## Evidence and follow-up

Validate the returned report with `tutor.py validate-voice` against its originating pass. An imported report is untrusted evidence, and a voice-model score remains an LLM judgment. Preserve partial and completed status. Record supported listening and speaking observations separately through the exercise/attempt workflow, with actual audio references and review provenance.

Diagnose a missed word only after distinguishing unfamiliar vocabulary from perception of a familiar form. Use Russian KB feedback when an observed pattern supports it. Add selected useful vocabulary through the SRS CLI under the current plan's workload limit. Do not write error counts, knowledge claims or progress by hand. A deferred activity retains speaking debt; settling it requires later eligible evidence through the shared workflow.
