# Activity: Draft material for another target language

**Status:** experimental authoring workflow. The structured learner engine, CLI, catalog and assessment bank currently support English only. Follow [the shared agent workflow](../docs/agent-workflow.md) for the supported English learner; generated material does not extend that contract automatically.

## Scope and data boundary

When the learner requests another language, establish the target, goal and preferred instruction language. Explain that you can draft teaching material requiring review. Do not claim that English's lesson sequence, placement, prerequisites or progression can be reused unchanged.

Draft in a clearly separate workspace or new language-content directory. Preserve existing material. Do not copy English progress into another learner, change `student/active.txt`, replace the active English learner or claim the CLI supports switching to the generated target. Other-language authoring and usable integrated learner support are separate work.

## Draft a manageable learning sequence

1. Consult authoritative references for the target language and the framework relevant to the learner's goal. Do not invent a CEFR-to-exam equivalence, a vocabulary inventory or a promised completion time.
2. Select one communicative goal and the language needed to accomplish it. Use the English unit anatomy as an organizational example: can-do goal, explanation and examples, useful vocabulary/chunks, functions, activities and contextual warnings.
3. Draft a small, reviewable sequence rather than imposing a fixed unit count. Mark each document `Generated draft; language-specific review required`. For an unfamiliar script, include script-learning support appropriate to the goal; romanization does not replace the script automatically.
4. Check examples, accepted alternatives, cultural/register context and prerequisites with competent language-specific review. Drafted level labels remain provisional.
5. Add candidate L1 contrasts only when they make sense for this language pair. The [Russian English KB](../languages/english/l1-notes/russian.md) illustrates structure and evidence limits; its error patterns are not universal. Use the learner's actual preferred L1, with explicit rescue explanations available.

## Integration is separate engineering work

To support the new target in the structured system, implement a language-specific catalog and diagnostic material, select the correct L1 KB, remove English-only assumptions deliberately, preserve independent learner data, and add migration, assessment and end-to-end tests. Review audio/provider support for the target language. Do not run English placement or internal progression as if it assessed another language.

Only describe the target as integrated after those components work together and have been verified. A draft folder can be a contribution for review; it is not automatically official support or a ready curriculum for the next learner.
