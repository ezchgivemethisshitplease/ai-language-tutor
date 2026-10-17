# Product mechanics and actual implementation

This file records design choices, not comparative efficacy or marketing claims. [`PEDAGOGY.md`](../../PEDAGOGY.md) is the current educational rationale; [`ARCHITECTURE.md`](../../ARCHITECTURE.md) describes implementation boundaries. Similarity to another app does not establish the same educational effect or capability.

## Implemented mechanisms

| Mechanism | Current boundary |
|---|---|
| Spaced card retrieval | `tools/srs.py` wraps the maintained, pinned Python FSRS dependency, preserves stable card IDs and review history, and disables interval fuzzing for reproducibility. A memory estimate is a model output, not knowledge of the exact moment a person will forget. |
| Learner evidence | `tools/learning.py` keeps original observations separate from derived summaries. Curriculum mastery and unit review use explicit local heuristics; they are not FSRS card-memory estimates or calibrated CEFR probabilities. |
| Structured practice | The curriculum catalog supplies outcomes, prerequisites and task-format options. Agents still write lesson content and answer keys; validators check structure rather than linguistic or educational truth. |
| Browser activities | The reader, quiz, dictation and flashcard apps support local practice. A quiz score describes its submitted items. A tapped word, streak or completed screen does not prove acquisition. |
| Corrective feedback | Observed error tags can retrieve Russian explanations and contextual examples. Open-ended judgments retain their source. LLM-only ratings do not satisfy independent progression evidence. |
| Speech | TTS supplies listening audio when a configured provider works. External voice conversations use a portable handoff/report workflow; actual availability depends on the external service and the learner's saved route. Speech that did not occur stays deferred. |

See the implementation and test reports for verified behavior. The dependency's own [Python FSRS repository](https://github.com/open-spaced-repetition/py-fsrs) is the reference for its scheduler; simplified historical equations in older notes are not a substitute for the maintained implementation.

## Useful design patterns, with limits

Contextual recall can connect a word with its sense, grammar and collocation, but one sentence can be ambiguous. Include precise cues and accept valid alternatives where the task permits them. Repeated retrieval and feedback matter more than the visual resemblance to a flashcard product.

Assisted reading can reduce lookup friction. It still needs a coherent text, a useful glossary, meaningful comprehension questions and a manageable task. A known-word file is a partial inventory, not a reliable automatic measurement of lexical coverage or comprehension.

A streak can describe recent participation. The system does not establish that streaks are the main cause of retention, that a particular gamification design improves proficiency or that missed days erase knowledge. Use learner goals and actual successful communication to explain progress.

Roleplay, writing and reflective review can connect form practice to communicative purposes. An LLM-written rubric or examiner role does not create a validated exam score. Likewise, a voice model's impression is not equivalent to an independently evaluated pronunciation or speaking assessment.

## Optional capabilities and unfinished work

A calibrated pronunciation scorer, a controlled multi-talker training corpus, local recording/STT orchestration and a fully automatic voice pipeline are not supplied by these notes. STT may expose a gross transcription mismatch; it cannot by itself diagnose individual phones, prosody or accent quality. A text-only environment cannot assess actual speech.

TTS, external voice services and media lookup can transmit the relevant request content to providers. Their presence does not imply permission to send learner history or credentials. Keep integrations modular, use the existing data controls, and describe the actual provider and data flow before use.

There are no verified percentage gains, competitor superiority claims or universal review-efficiency savings for this repository. Paid services are optional and do not remove the need for evidence, contextual feedback or independently reviewed assessment. Remaining work belongs in [`ROADMAP.md`](../../ROADMAP.md), with its implementation status stated explicitly.
