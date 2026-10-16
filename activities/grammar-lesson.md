# Activity: Grammar micro-lesson

Follow [the shared agent workflow](../docs/agent-workflow.md). **Mode:** chat. A brief explanation followed by practice often fits 5–10 minutes; adjust to the task and available time.

## Choose a contrast

Use the stored plan's reason and error tags, the selected unit's outcome, or the learner's explicit question. Recurring confirmed errors can justify remediation, but old text-log counts are not independent mastery evidence. Check the [Russian KB](../languages/english/l1-notes/russian.md) for a useful contrast; L1 membership alone is not a diagnosis.

## Explain, retrieve and use

1. Start from the learner's actual example when available: «Ты написал *I have seen him yesterday*. Yesterday — законченный период. Какое время здесь нужно?» Avoid promising that one explanation will fix a pattern permanently.
2. Explain the contrast in the instruction language returned by `tutor.py status`. Honor a request for Russian at every level. Use plain words and a few clear examples. For example: «since обозначает начало, for — длительность». Name a grammar term if useful, and qualify a rule when exceptions or English varieties affect the answer.
3. Ask a manageable constrained retrieval or transformation question, then a new personal response: «Tell me about someone you saw last week». Tie form to intended meaning rather than relying on a signal-word shortcut.
4. Ask for self-correction before giving a fix when that is useful. Give direct explanation if the learner needs it, and mark that support in the later observation. Revisit the contrast in a different context after a delay.

Cloze, translation, transformation and a short meaningful response can complement one another. Accept grammatical alternatives and distinguish a form error from a meaning, register or naturalness issue. If repeated practice is not helping, change the context, explanation or task difficulty instead of increasing repetition blindly.

## Evidence and follow-up

Use catalog skill and grammar tags in validated exercise files. Record the original attempt through `tutor.py attempt`, with `--hints-used` when supported, and include a review source for open responses. Only add `--error-tag` when the observed mistake supports that diagnosis. A corrected copy is supported practice, not independent mastery.

Add a useful contextual card through `tools/srs.py add` if warranted by the current plan. For a pattern card, `answer` is the exact gap replacement: *have been* in “I ___ working all morning”; keep the sentence and intended meaning clear. Do not require a fixed number of new cards after every explanation.

Complete the planned step through the CLI. Error counts, grammar estimates and retrieval priorities come from stored observations; do not edit learner progress or text logs to claim improvement.
