# Activity: Reading

Follow [the shared agent workflow](../docs/agent-workflow.md) for session IDs, validated exercises, attempts and completion. **Mode:** chat; the reader app can add replayable audio. Budget roughly 10–20 minutes when it fits the learner's plan.

## Prepare an accessible text

Use the selected catalog unit's outcome and the learner's interests to choose a purpose: understand a message, follow a story, compare options or evaluate an argument. Start with a short text and adjust its length, vocabulary, syntax and support to observed comprehension. Rotate dialogue, email, narrative, review, news brief and forum-style text.

Use known-word observations and the unit vocabulary as hints about difficulty. A word list cannot guarantee lexical coverage, and familiar spelling does not establish knowledge of a sense or collocation. Introduce a manageable amount of useful new language; do not force every unit word into one passage. Use the unit grammar naturally.

## Run it

With the browser, prepare `student/reading-current.json` using the reader schema in [AGENTS.md](../AGENTS.md). Validate before opening the app:

```sh
python tools/tutor.py validate-activity text student/reading-current.json
```

Start the local server and open the reader as described in the shared workflow. Handle gloss requests in context: brief meaning, why it fits this sentence, and Russian clarification when useful. Treat a tapped word as a question or learning interest, not as a failed assessment or proof of mastery. Consume durable browser receipts through `python tools/tutor.py events`; do not remove learner history to clear a screen.

In chat, show the title, purpose and text. Offer this useful three-pass procedure when new to the learner:

1. Read for the main message without stopping at every unfamiliar word.
2. Revisit the words that still block understanding; try the context, then ask or use a gloss.
3. If audio is available, follow the text while listening to connect sound and phrasing.

Audio is optional for this reading activity. `python tools/tts.py say "<paragraph>"` can supply a read-aloud; use one paragraph at a time after the learner is ready. Listening with the script visible is read-along practice, not an unaided listening assessment. An oral summary belongs in a separate real voice step.

Ask a literal question, then an inference or explanation where the text supports one. An opinion question can lead to an optional short written response. If comprehension breaks down, identify whether vocabulary, syntax, background knowledge or task demands caused it and simplify appropriately.

## Evidence and follow-up

Create schema-validated `reading_comprehension` exercises with accepted alternatives or a contextual rubric. Record actual responses using `tutor.py attempt`; unlisted valid wording stays reviewable. Record a written summary as its own writing observation. Browser completion alone does not establish mastery.

Add useful contextual cards through `tools/srs.py add` under the current plan's workload limit, rather than turning every tap into a card. Keep learner knowledge and error estimates derived from observations; do not append guesses to known-word or error files. Complete the planned step through the CLI. See [PEDAGOGY.md](../PEDAGOGY.md) for the evidence limits.
