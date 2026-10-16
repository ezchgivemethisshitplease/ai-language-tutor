# English curriculum mapping to CEFR (A1–C1)

This is a project-authored teaching map. It is not an official English syllabus, a validated grammar-level inventory or a calibrated examination specification. The [Council of Europe CEFR Companion Volume](https://www.coe.int/en/web/common-european-framework-reference-languages/cefr-companion-volume-and-its-language-versions) provides the proficiency framework; this repository supplies its own sequence and tasks. [`../../PEDAGOGY.md`](../../PEDAGOGY.md) describes the current evidence policy and limits.

## Framework and course sequence

CEFR describes what a learner can do in reception, production, interaction and mediation, including online communication. A learner can have different strengths across these areas. A grammar topic, vocabulary total or completed unit cannot establish an overall CEFR level.

The summaries below are broad course aims rather than quoted official descriptors. Use the original CEFR scales when selecting an assessment descriptor and retain the skill-specific context and conditions.

| Curriculum label | Communicative direction | Project grammar and discourse focus |
|---|---|---|
| A1 | Exchange basic personal details; understand and produce short, supported messages about immediate needs. | Be, possession, articles, basic word order, routines, questions, simple ongoing actions, place and time, initial past forms and plans. |
| A2 | Handle familiar practical exchanges; describe simple past events, plans and comparisons. | Past simple/continuous, comparatives, future forms, advice and obligation, quantity, initial perfect forms, purpose and basic conditions. |
| B1 | Link ideas in familiar-topic narratives and explanations; give reasons and respond to practical suggestions. | Tense/aspect contrasts, narrative sequence, hypothetical situations, reporting, passive forms, relative clauses and verb patterns. |
| B2 | Develop detailed explanations and arguments; compare options, respond to objections and adapt familiar discourse to an audience. | Complex conditions, passive reporting, causatives, past modality, reported questions, clause relationships, word formation and collocation. |
| C1 | Manage nuanced, extended communication; qualify claims, adjust register and reformulate complex ideas for an audience. | Hedging, information focus, ellipsis, cohesive discourse, formal options, aspect nuance, idiom and reasoned argument. |

These labels organize material. Features are recycled and combined; they are not exclusive to one level. Learner goals and observed difficulties may justify a different teaching order. The course still needs broader independently reviewed coverage of mediation, pragmatics, online interaction, genres and authentic listening variation.

## Implemented content and assessment

[`curriculum/catalog.json`](curriculum/catalog.json) indexes all 60 unit outlines, their prerequisites, outcomes, grammar tags, vocabulary and supported exercise types. [`curriculum/overview.md`](curriculum/overview.md) explains how to use that index. The vocabulary is author-selected; the repository does not ship a licensed frequency corpus or a validated per-level vocabulary inventory. Do not attribute exact word counts to Oxford, Cambridge or CEFR without verifying the specific dataset and counting unit.

`data/assessments.json` contains a small authored diagnostic sample with project level labels. It does not establish CEFR cut scores. Writing and speaking need contextual review; listening remains unassessed when no actual audio task was administered. `tools/learning.py` returns observed evidence, uncertainty warnings and missing-skill information. Internal progression requires explicit evidence and human review; it is not certification.

Activities may borrow task shapes from public exam descriptions, but a generated simulation is not an official exam, an equated score or proof of readiness. Verify the current provider's specifications before preparing someone for a particular examination. The A1–C1 outlines alone do not constitute complete Cambridge, IELTS or other exam preparation.

## Time, vocabulary and pronunciation

No fixed number of study hours or words guarantees a level. Progress depends on prior knowledge, opportunity to use English, the quality and breadth of practice, and the demands of the intended tasks. Distinguish productive from receptive knowledge and words from lemmas, senses, word families and multiword expressions. Do not convert an estimated classroom-hour range into a promised completion date.

Pronunciation work targets intelligibility and effective use of sound and prosody. A retained accent is compatible with proficiency; see the [Council of Europe phonological competence guidance](https://www.coe.int/en/web/common-european-framework-reference-languages/phonological-competence). Real audio is required for claims about speech, and typed responses cannot substitute for it.

## Further primary references

[English Profile](https://englishprofile.org/) offers English-specific descriptive resources. Consult the actual resource, access terms and intended use before importing data or claiming level alignment. The present catalog is not an export of English Grammar Profile, English Vocabulary Profile or Oxford lists. Learning-science references and the distinction between supporting evidence and local product heuristics are maintained in [`PEDAGOGY.md`](../../PEDAGOGY.md).
