# Activity: Conversation

Follow [the shared agent workflow](../docs/agent-workflow.md) and the [portable voice contract](../portable/voice-tutor.md). **Mode:** voice-required at every level. A typical roleplay can fit 10–15 minutes; the finite plan, rather than an assumed duration, defines its end.

## Setup and handoff

Choose a coherent scenario from the selected unit, learner interests or explicit request: a practical transaction, a description, an opinion exchange or free conversation around a purpose. Include a chance to ask a question, respond to a follow-up and clarify meaning.

Write a manageable set of exact numbered learner-facing questions/actions, each used once. Define completion as a good-faith response or an explicit skip, not a correct answer. Populate the Lesson Pass using the portable contract and include its complete instructions in the handoff. Use the current evidence-based language policy and honor Russian explanation requests; do not infer immersion solely from a declared level.

Use the saved voice route. If unavailable, defer the planned voice step through `tutor.py step --session SESSION_ID --step STEP_ID --defer` and continue usable steps from the session plan. A typed dialogue may be a separate writing exercise; it does not complete conversation or settle speaking debt.

## Interaction and feedback

Keep tutor turns short enough for the learner to contribute. Weave useful unit language into the scene and simplify when comprehension breaks down. During a fluency-oriented exchange, let the learner finish the message; use a clarification prompt when communication fails. In a deliberate form-practice segment, a timely correction can be useful.

At the planned end, select the errors that most affect meaning or the current goal. Ask for one self-correction where helpful, then show a natural fix and explain the contrast. Do not penalize a correct alternative or treat accent identity as an error. Praise only specific observed achievements.

## Evidence and follow-up

Validate a returned Lesson Report against its originating pass with `tutor.py validate-voice`. Validation checks structure and correspondence, not whether an evaluator heard audio or supplied a calibrated score. Preserve partial status and LLM provenance. A voice-model level impression can motivate another diagnostic task; it cannot promote the learner.

Record actual `spoken_response` or `dialogue` observations through `tutor.py attempt`, using the declared rubric and real audio reference. Russian KB tags require observed evidence; a transcript alone cannot diagnose phonemes. Selected useful gaps may become contextual cards through the SRS CLI within the current plan's workload.

Complete the planned step through the CLI when its evidence and completion conditions are met. Do not manually increment errors or progress. Deferred speech is settled only by later eligible matching evidence using the shared workflow.
