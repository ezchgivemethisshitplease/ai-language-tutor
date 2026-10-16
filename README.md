# AI Language Tutor

A local English practice system for Codex and Claude Code, with Russian explanations, a persistent learner model and maintained FSRS scheduling. The coding agent teaches and authors material; Python validates exercises, records evidence and manages progress. The course contains 60 A1–C1 lesson outlines. Placement and internal readiness estimates are uncalibrated.

[Инструкция на русском](docs/usage.ru.md) · [Audit](AUDIT.md) · [Architecture](ARCHITECTURE.md) · [Pedagogy](PEDAGOGY.md) · [Implemented changes](IMPROVEMENTS.md) · [Remaining work](ROADMAP.md)

## Install

Supports macOS and Linux with Python 3.10+ and a file/shell-capable coding agent. Node 24 is needed only for browser script verification. There is no frontend build or hosted service to deploy.

```sh
git clone https://github.com/ezchgivemethisshitplease/ai-language-tutor.git
cd ai-language-tutor
git switch improve/reliable-russian-tutor
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python tools/tutor.py init --native-language russian --daily-minutes 30
python tools/tutor.py status
```

Use the virtual environment for every command. Do not install packages into the system interpreter.

Existing learners run the same `init` command: it preserves files, IDs and old progress, retaining the old level as unverified legacy information. Back up `student/` before migrating valuable progress. Corrupt files are rejected instead of reset. The previous JSON generation is kept as `.bak` when state changes.

## Study in Codex or Claude Code

Open this repository as the working folder and say «Давай заниматься английским». Codex reads `AGENTS.md`; Claude Code imports it through `CLAUDE.md`. Both use [the same workflow](docs/agent-workflow.md). Claude `/start` and `/session` wrappers are included; plain chat requests work in either agent.

The project includes a portable [`humanize` skill](.agents/skills/humanize/SKILL.md). The agent loads it through AGENTS.md and applies a silent editing pass to its own explanations, feedback and engineering replies. It preserves your exact answers and all assessment data. Codex can also invoke `$humanize`; Claude Code has a project skill wrapper. [Communication examples](docs/communication.md) show the intended tone. Skill discovery and instruction adherence depend on the host; they are not a guarantee that every future reply will have the desired style.

```sh
python tools/tutor.py start          # store today's plan or resume the unfinished one
python tools/tutor.py items --level A1 --limit 6
python tools/tutor.py assess --level A1
python tools/tutor.py --help
```

Russian explanations remain available at every level: «Объясни по-русски». Support fades according to observed eligible performance. The Russian KB supplies 31 contextual contrasts linked to units and remedial exercise types. Diagnoses require actual evidence; native language alone never proves an error.

Each meaningful attempt retains the exercise, exact response, hints and rating source. Repeated delayed evidence supports a separate mastery estimate. An LLM review remains provisional and cannot by itself establish mastery or promote a level. Open writing/speech progression needs human review; the local attestation records provenance but cannot authenticate a reviewer. See [workflow commands](docs/agent-workflow.md) for attempts, interruptions, debt and internal progression.

## Reviews and browser practice

```sh
python tools/srs.py due
python tools/srs.py stats
python tools/serve.py
```

Open `http://localhost:8765/flashcards.html`, `quiz.html`, `reader.html`, `dictation.html` or `dashboard.html`. The agent prepares and validates quiz/reading/dictation JSON first. Flashcard recall grades are saved immediately; retries use stable IDs. Apps retain pending submissions/drafts in browser localStorage until acknowledged. Failed loads show an error; demonstration data requires `?demo=1` explicitly. On shared computers, treat browser drafts as personal data.

FSRS owns learning/relearning steps and due times. Hard means remembered with difficulty; Again means forgotten. The browser does not loop forgotten cards until you choose Good. Unknown wording in non-exhaustive language tasks stays `needs_review`. Quiz outcomes never automatically add cards or establish mastery.

Stop after the final acknowledged activity: `python tools/serve.py stop`. The service binds to loopback and enforces Host/Origin/session-token checks. It is a single-user local service, not a public application server.

## Audio and privacy

OS/browser speech is the default. On macOS, `python tools/tts.py say "I am a student."` uses the installed OS voice. Browser dictation has an explicit browser-speech fallback. Optional cloud providers require `TUTOR_TTS=edge`, `openai` or `elevenlabs`; provider packages/credentials alone never enable them. Cloud speech receives the requested text. Edge requires an optional `edge-tts` installation; it is not a runtime dependency of the core.

Speech production uses an optional external voice conversation and a finite pass/report workflow. The [voice bridge](portable/voice-tutor.md) and `validate-voice` check structure, pass identity and completion fields. They do not authenticate sound, score pronunciation or calibrate proficiency. Missing speaking/listening evidence stays unassessed. No paid speech dependency is required.

Learner files stay under ignored `student/`. The coding agent receives whatever learner context it reads into its conversation, and external voice receives the handoff context. Optional TTS/image services receive the text/query sent to them. Local storage therefore does not imply offline inference. API keys belong only in environment variables. Exports contain personal data and are not encrypted; they exclude control credentials, audio cache and images.

```sh
python tools/tutor.py export /safe/location/learner-export.json
python tools/tutor.py import /safe/location/learner-export.json /new/location/restored-student
python tools/tutor.py recover learner.json
```

Import creates a new directory and preserves the live one. Use `--student-dir PATH` or `TUTOR_STUDENT_DIR` to select isolated/restored data. Full archives currently cover the active English learner; other language files remain untouched.

## Verify

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python -m ruff check tools tests
python -m ruff format --check tools tests
python -m mypy tools
python tools/srs.py selfcheck
python tools/serve.py selfcheck
python tools/voice_selfcheck.py
python -m pip check
node tests/browser_transport.cjs
python tools/check_browser_scripts.py
```

Tests use temporary data. They cover FSRS reference parity, migration, corruption/recovery, concurrent writes/retries, 100 simulated sessions, assessment limits, Russian feedback and browser transport. [VALIDATION.md](VALIDATION.md) records the actual results/platforms. CI runs Python 3.10 and 3.14 on Ubuntu and macOS plus the Node checks. Live agent teaching quality, learner outcomes and external speech providers require separate acceptance work.

## Files and boundaries

`tools/learning.py` is the evidence/planning model; `tools/tutor.py` is its CLI; `tools/storage.py` serializes durable JSON updates; `tools/srs.py` adapts pinned FSRS. `activities/` contains teaching procedures, `languages/english/` content and Russian contrasts, and `apps/` static local practice. `student.example/` is a compatibility template; initialization never copies it over existing data.

MIT license. The adapted Humanizer skill includes its upstream MIT attribution. Do not redistribute proprietary vocabulary corpora or exam materials through contributions.
