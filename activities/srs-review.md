# Activity: explicit retrieval review

Use `tools/srs.py due` or the flashcard app. Present a sentence cloze and its Russian meaning cue; let the learner attempt retrieval before revealing the answer. Valid alternatives can be discussed without declaring them bad English. If the intended target was not retrieved, explain that distinction and improve ambiguous card context.

Reveal the completed sentence and meaning, then ask the learner to self-grade: **1 Не вспомнил**, **2 Вспомнил с трудом**, **3 Вспомнил**, **4 Легко вспомнил**. Hard means successful recall; a wrong inflection or revealed answer is not successful independent recall. Apply `srs.py grade ID GRADE` immediately. Fixed “~4d” labels are not used; FSRS owns learning/relearning steps and intervals. Do not loop Again until the learner chooses Good.

The browser autosaves each grade and writes its completion event only when the shown batch ends. Failed saves remain pending and visible. A future minute-level due time requires later retrieval, not immediate success inflation. In chat, use brief batches and re-query due times instead of inventing timing. Audio after reveal is optional, with the learner's pacing respected.

Repeated lapses prompt card-quality inspection: context, sense, collocation and learner usefulness. They do not automatically prove a grammatical misconception. Use explicit observed evidence to tag real error patterns. Zero due cards means no review is needed now; new cards follow the stored plan and backlog policy.
