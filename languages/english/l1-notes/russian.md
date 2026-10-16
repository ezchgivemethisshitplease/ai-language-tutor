# English ← Russian: contrastive teaching notes

The machine-readable source is [`russian.json`](russian.json). It contains 31 candidate error patterns with stable IDs, Russian explanations and feedback, contextual examples, curriculum links, exercise types and remedial tags. `tools/learning.py` uses these IDs to connect **observed** errors with lesson selection and feedback. A Russian L1 never proves that a learner has a particular error.

## Language and onboarding

Start onboarding in Russian after the learner identifies Russian as their preferred instruction language. Useful first prompts: «Для чего тебе английский?» and «Сколько минут в день реально удобно заниматься?». Ask about speaking access separately; typed answers cannot establish pronunciation or spoken fluency.

At A1 use brief Russian instructions around short English examples. At A2 lead with an English task and clarify in Russian when useful. At B1 use mostly English if comprehension supports it; at B2–C1 use English for normal interaction. **«Объясни по-русски» works at every level.** These are adjustable scaffolding defaults, not experimentally calibrated percentages or a ban on the learner's L1. Judge the transition using actual comprehension and the learner's preference, not a single placement label.

Explain a contrast, ask for retrieval, give feedback, then ask for a new personal example. Do not make every response a translation exercise. Russian can clarify a misconception while the learner still produces meaningful English.

## Diagnosis and corrective feedback

1. Preserve the learner's original answer and intended meaning. Check context, English variety and register before marking an error.
2. Select a KB ID only if an observed example supports it. For audio-only patterns require actual audio/perception evidence; spelling and STT text do not support a phoneme score.
3. Use `feedback_ru` as a starting point, ask one self-correction question, then show the correction and explain the contrast if necessary. Mark a natural alternative as valid rather than turning it into a miss.
4. Practise the contrast in a new context with a different prompt. A corrected copy is supported performance, not independent mastery.
5. Record the error ID with the attempted skill. Revision selection uses observed error evidence; repeat successful retrieval later before treating the problem as resolved. Human/agent tagging remains necessary: this KB is not an automatic linguistic classifier.

For example: «Ты написал *I have seen him yesterday*. Yesterday — законченный период. Какое время нужно?» After the attempt: «I saw him yesterday. Теперь расскажи, кого ты видел на прошлой неделе». Do not diagnose all Present Perfect uses as Russian interference.

## Candidate patterns

The short examples below are contextual diagnostics, not a blacklist of strings. The JSON contains the complete context, Russian teaching explanation and actionable feedback for each entry.

| ID | Example or contrast | Practice |
|---|---|---|
| `articles` | She is engineer. → She is an engineer. | cloze, translation, error_correction |
| `be_omission` | I tired. → I am tired. | cloze, reorder, translation |
| `word_order` | I very like this film. → I like this film very much. | reorder, transformation, error_correction |
| `auxiliaries` | Does she works here? → Does she work here? | cloze, transformation, error_correction |
| `questions` | Where you live? → Where do you live? | reorder, transformation, dialogue |
| `negation` | I not understand. → I do not understand. | cloze, transformation, error_correction |
| `present_simple` | She work every day. → She works every day. | cloze, transformation, short_writing |
| `continuous` | She reading now. → She is reading now. | cloze, transformation, short_writing |
| `perfect_vs_past` | I have seen him yesterday. → I saw him yesterday. | cloze, transformation, dialogue |
| `tense_aspect` | I have lived here since three years. → I have lived here for three years. | cloze, transformation, short_writing |
| `prepositions_place` | I go to home after work. → I go home after work. | cloze, translation, dialogue |
| `prepositions_time` | I start work in nine o'clock. → I start work at nine o'clock. | cloze, translation, short_writing |
| `verb_prepositions` | We discussed about the problem. → We discussed the problem. | cloze, translation, error_correction |
| `phrasal_verbs` | Turn off it, please. → Turn it off, please. | cloze, reorder, dialogue |
| `countability` | She gave me an advice. → She gave me some advice. | cloze, transformation, translation |
| `quantifiers` | How much books do you need? → How many books do you need? | cloze, translation, error_correction |
| `conditionals_real` | If it will rain tomorrow, we will stay home. → If it rains tomorrow, we will stay home. | cloze, transformation, short_writing |
| `conditionals_unreal` | If I would have more time, I would travel. → If I had more time, I would travel. | cloze, transformation, dialogue |
| `modals` | She can to swim. → She can swim. | cloze, transformation, dialogue |
| `gerund_infinitive` | I enjoy to cook. → I enjoy cooking. | cloze, transformation, short_writing |
| `reported_speech` | She said me she was tired. → She told me she was tired. | cloze, transformation, dialogue |
| `relative_clauses` | The woman who she helped me is here. → The woman who helped me is here. | cloze, transformation, error_correction |
| `false_friends` | I buy bread at this magazine. → I buy bread at this shop. | cloze, translation, dialogue |
| `calques` | I feel myself tired. → I feel tired. | cloze, translation, error_correction |
| `impersonal_subject` | Is cold today. → It is cold today. | reorder, translation, short_writing |
| `pronunciation_vowels` | ship pronounced as sheep → ship /ʃɪp/ | minimal_pairs, listening_comprehension, spoken_response |
| `pronunciation_th` | thin pronounced as sin → thin /θɪn/ | minimal_pairs, spoken_response |
| `pronunciation_wv` | wine pronounced as vine → wine /waɪn/ | minimal_pairs, spoken_response |
| `pronunciation_final_voicing` | leave perceived as leaf → leave /liːv/ | minimal_pairs, listening_comprehension, spoken_response |
| `word_stress` | photography with first-syllable stress → photography /fəˈtɒɡrəfi/ | listening_comprehension, spoken_response |
| `sentence_stress` | Equal strong stress on every word obscures intended contrast → I wanted the BLUE one. | listening_comprehension, spoken_response |

## Pronunciation: evidence and intelligibility

Choose from observed needs: /ɪ/–/iː/ (*ship/sheep*), /æ/–/e/ (*bad/bed*), /ʊ/–/uː/ (*full/fool*); /θ, ð/; /w/–/v/; final-consonant contrasts; word stress and sentence focus. Russian learners differ, so this is a candidate menu, not a mandatory failure sequence.

Use fixed, replayable audio for a perception contrast; alternate words and keep the answer hidden until retrieval. Then practise production in words, short phrases and meaningful speech when a real voice route exists. A transcription mismatch can prompt a closer listening check but is not a pronunciation measurement. Do not manufacture audio assessment from typed spelling. Assess whether the message is intelligible, and respect normal English accent variation.

Mark word stress with the word, e.g. PHOtograph / phoTOGraphy. Explain /w/ by rounded lips and /v/ by upper teeth touching the lower lip; explain /θ, ð/ as dental fricatives with airflow and different voicing. Avoid Cyrillic transliterations as authoritative pronunciation targets: they cannot reliably encode these contrasts.

## Common traps when giving feedback

- *Will*, *going to* and present continuous overlap. Ask what the speaker means before imposing a form.
- Simple and continuous aspect can both be grammatical with different viewpoints. A time word is a clue, not an answer key.
- Non-backshifted reported speech can be correct when the statement remains current.
- *Two coffees* can mean two servings; this is not necessarily a countability error.
- *I suggest that he should go* is standard. Subjunctive forms are useful options, not the only English grammar.
- Distinguish a wrong form from a naturalness, register or contextual-meaning problem. Offer a more natural wording without pretending the original was ungrammatical.

## Extending to another L1

Add `<language>.json` beside this file using the same versioned structure. Keep the current English skill IDs; add L1-specific error IDs, examples and feedback. The engine must validate references and fall back to general feedback if no KB exists. Learner-specific observations outrank population-level contrastive hypotheses. No personal learner data belongs in this shared knowledge base.

## Sources and limits

These entries are authored contrastive teaching hypotheses, not prevalence statistics, a validated diagnostic instrument or a claim that Russian causes every listed error. English usage checks draw on [Cambridge English Grammar Today](https://dictionary.cambridge.org/grammar/british-grammar/) (notably [reported speech](https://dictionary.cambridge.org/us/grammar/british-grammar/reporting-verbs), [aspect choices](https://dictionary.cambridge.org/uk/grammar/british-grammar/past-continuous) and [suggest](https://dictionary.cambridge.org/grammar/british-grammar/suggest)). The target for pronunciation follows the [Council of Europe's phonological competence guidance](https://www.coe.int/en/web/common-european-framework-reference-languages/phonological-competence): intelligibility and communicative effectiveness. See [`PEDAGOGY.md`](../../../PEDAGOGY.md) for evidence, uncertainty and product heuristics.
