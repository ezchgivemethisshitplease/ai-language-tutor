# Activity: daily session

Run the repository interpreter and `tools/tutor.py start`. It creates a stored plan or resumes the existing one. Follow [the shared workflow](../docs/agent-workflow.md) for exact commands. Load the canonical learner, relevant unit and L1 notes, then present the returned plan briefly. Do not reconstruct mastery from legacy progress or rewrite level/unit by hand.

Run one planned step at a time. Due SRS comes first when scheduled. Use the selected skill/domain and adapt the scenario to the learner's stated goals; do not silently replace a required audio modality with text. On explicit requests, explain fully in Russian at any level. Each meaningful exercise records the exact response, hints, provenance and stable attempt ID. Confirmed recurring errors use explicit KB tags, never nationality or substring matching alone.

Browser app events must match the prepared activity. Per-card review saves do not finish the activity; wait for `.event-flashcards.json` from the completion endpoint. A quiz result is separate observed performance, not mastery. `tools/tutor.py events` recovers durable receipts. Stop and explain unconfirmed saves; the outbox retains them.

Mark each step with `tutor.py step`. If a voice step is unavailable, defer it explicitly; other steps still proceed. Periodically use `assess` and a cumulative check to identify missing evidence. Speaking debt remains visible until a matching later eligible audio observation settles it.

Wrap with specific feedback and the next practice target. `tutor.py finish` verifies step status. If ending early, `finish --allow-incomplete` records abandonment, or `interrupt` retains resumable work. Completion does not itself confer mastery. Optionally update the legacy streak with `srs.py streak`; it is motivation metadata only. Stop the local browser server with `tools/serve.py stop` after all acknowledgments. Never kill unrelated processes.
