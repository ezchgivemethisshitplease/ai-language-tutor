# English curriculum overview (A1–C1)

The course contains 60 authored unit outlines, 12 per level. [`catalog.json`](catalog.json) is the executable index: stable unit IDs, paths, prerequisites, can-do outcomes, grammar tags, vocabulary, exercise types and Russian contrastive-error links. Unit Markdown remains the teaching content. The catalog's selection metadata does not turn its grammar topics into official CEFR requirements.

| Level | Stable IDs | Vocabulary slots | Distinct strings within level | Main emphasis |
|---|---|---:|---:|---|
| A1 | `a1-01` … `a1-12` | 144 | 144 | Basic personal information, routines, places and simple plans |
| A2 | `a2-01` … `a2-12` | 144 | 144 | Past events, comparisons, practical transactions and basic experience |
| B1 | `b1-01` … `b1-12` | 144 | 144 | Connected narratives, explanations and familiar-topic interaction |
| B2 | `b2-01` … `b2-12` | 144 | 142 | Hypotheticals, reporting, detailed discourse and word partnerships |
| C1 | `c1-01` … `c1-12` | 144 | 144 | Nuance, extended argument, register and flexible discourse |

There are 720 vocabulary slots and 672 distinct case-folded spelling strings across the complete course. These include chunks and repeated words, not a measured count of acquired lemmas or word families. They do not deliver a promised 5,500-word vocabulary, a licensed frequency list or independently validated CEFR word levels. Select additional useful vocabulary from the learner's goals and observed gaps; record frequency only when a real cited source supports it.

## Using a unit

Every unit contains a can-do goal, grammar focus and examples, target vocabulary, functions, suggested reading/conversation/quiz activities and warnings. The English examples stay in English; explanations and feedback may use the learner's L1. Russian contrasts are in [`../l1-notes/russian.md`](../l1-notes/russian.md) and its structured JSON KB.

Use a unit's `outcomes` to choose a communicative task. Use `grammar_tags` and observed `l1_error_tags` to select a contrast to practise. `exercise_types` lists supported task formats for generation; it is not a bank of already reviewed items. The `minutes` field is a planning hint for one practice block, not the time required to master a unit.

Prerequisites represent teaching judgments, including dependencies across levels. Unit 12 reviews the previous 11 units. The graph is acyclic and every source file has one catalog entry. A learner may revisit any needed contrast; encountering a grammar feature earlier or later does not by itself contradict CEFR. Curriculum levels are organizing labels for practice, not calibrated measurements.

## Progression and evidence

Use `tools/tutor.py` and the learner evidence model for planning and write-backs. `tools/learning.py` distinguishes observed responses from derived mastery, excludes hints and LLM-only judgments from promotion evidence, requires diverse delayed retrieval, and returns an explicit human-review readiness verdict. A read unit, completed activity or one 70% quiz cannot independently establish mastery or a new CEFR level. See [`../../../PEDAGOGY.md`](../../../PEDAGOGY.md) for the actual heuristic thresholds and their limits.

Unobserved listening, speaking and pronunciation remain unassessed. A typed answer cannot substitute for speech; unavailable voice practice remains deferred. Cumulative checks need new contextualized tasks across skills, with accepted alternatives and explicit rubrics. Local exam-shaped practice is not an official examination or a validated readiness prediction.

## Pace and after C1 content

Daily availability, prior learning, task difficulty and real-world use all affect pace. Do not turn guided-hour estimates into promised calendar dates or extrapolate vocabulary totals from the unit count. Use the learner's observed progress and preferences to adjust workload.

After the C1 outlines, continue goal-directed practice and spaced retrieval. If a certificate matters, recommend the appropriate official assessment and preparation based on externally evaluated evidence. Passing a locally generated simulation does not establish exam readiness. Other target-language generation remains an agent workflow and requires separate language-specific review; English metadata is not automatically transferable to other languages.
