# AI Language Tutor

A local English tutor with a browser chat, Russian explanations, a persistent learner model and maintained FSRS scheduling. The web app uses an independent Codex CLI process with ChatGPT subscription login; Codex Desktop is optional. Python validates exercises, records evidence and manages progress. The course contains 60 A1–C1 lesson outlines. Placement and internal readiness estimates are uncalibrated.

[Инструкция на русском](docs/usage.ru.md) · [Audit](AUDIT.md) · [Architecture](ARCHITECTURE.md) · [Pedagogy](PEDAGOGY.md) · [Implemented changes](IMPROVEMENTS.md) · [Remaining work](ROADMAP.md)

## Install

Supports macOS and Linux with Python 3.10+, Node.js 22+ and npm 10+. There is no frontend build or hosted service to deploy.

```sh
git clone https://github.com/ezchgivemethisshitplease/ai-language-tutor.git
cd ai-language-tutor
git switch improve/reliable-russian-tutor
./start.sh
```

Open the local page, choose **Войти через ChatGPT**, complete the official OpenAI login and set your study profile. Chat, conversation history, lesson controls, exercises, cards, reading, dictation, progress and backup download are available in the browser. The app installs pinned dependencies locally and keeps a separate private Codex profile under `.runtime/codex-home`; it never imports Desktop credentials. No API key is needed. Account eligibility and subscription limits still apply. [Web setup and troubleshooting](docs/web.md) explain the details.

Codex app-server and dynamic tools are experimental; the adapter pins version `0.163.0`. The web tutor has a restricted filesystem/network policy and uses curated learning tools. Optional [local Whisper dictation](docs/speech.md) turns recordings into editable drafts; the model receives confirmed text, without acoustic assessment. Replies can be read aloud using installed local browser voices. Human reviews, recovery and archive restore remain explicit CLI workflows. Keep the server running while using the web tutor; stop it with `Ctrl+C` or `.venv/bin/python tools/serve.py stop`.

For the existing Codex/Claude Code workflow, a file/shell-capable agent can use just the Python core:

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
python tools/tutor.py items --level A1 --limit 6   # learner view, keys/scripts hidden
python tools/tutor.py assess --level A1
python tools/tutor.py --help
```

Russian explanations remain available at every level: «Объясни по-русски». Support fades according to observed eligible performance. The Russian KB supplies 31 contextual contrasts linked to units and remedial exercise types. Diagnoses require actual evidence; native language alone never proves an error.

Each meaningful attempt retains the exercise, exact response, hints and rating source. A later `review` appends an annotation to that same trial; it does not rewrite the answer or count as a new independent response. Repeated delayed evidence supports a separate mastery estimate. An LLM review remains provisional and cannot by itself establish mastery or promote a level. Open writing/speech progression needs human review; the local attestation records provenance but cannot authenticate a reviewer. See [workflow commands](docs/agent-workflow.md) for attempts, interruptions, debt and internal progression.

## Reviews and browser practice

```sh
python tools/srs.py due
python tools/srs.py stats
python tools/serve.py
```

Open `http://localhost:8765/flashcards.html`, `quiz.html`, `reader.html`, `dictation.html` or `dashboard.html`. The agent prepares and validates quiz/reading/dictation JSON first. Flashcard recall grades are saved immediately; retries use stable IDs. Apps retain pending submissions/drafts in browser localStorage until acknowledged. Failed loads show an error; demonstration data requires `?demo=1` explicitly. On shared computers, treat browser drafts as personal data.

FSRS owns learning/relearning steps and due times. Hard means remembered with difficulty; Again means forgotten. The browser does not loop forgotten cards until you choose Good. Unknown wording in non-exhaustive language tasks stays `needs_review`. Quiz outcomes never automatically add cards or establish mastery.

For an agent-hosted activity, stop after the final acknowledged activity with `python tools/serve.py stop`. Keep it running for browser chat. The service binds to loopback and enforces Host/Origin/session-token checks. It is a single-user local service, not a public application server.

## Audio and privacy

OS/browser speech is the default. On macOS, `python tools/tts.py say "I am a student."` uses the installed OS voice. Browser dictation has an explicit browser-speech fallback. Optional cloud providers require `TUTOR_TTS=edge`, `openai` or `elevenlabs`; provider packages/credentials alone never enable them. Cloud speech receives the requested text. Edge requires an optional `edge-tts` installation; it is not a runtime dependency of the core.

The 100-item original diagnostic bank covers reading, listening, writing and speaking. Listening has original scripts and independent contexts. `python tools/tutor.py audio diag-a1-listening-01 /existing/path/stimulus.aiff` renders an English stimulus locally on macOS without printing its script or playing it; Linux uses `.wav` with optional eSpeak. Present audio before the answer and keep transcripts/keys hidden. Generating a file does not prove the learner heard it. [Assessment instructions](docs/assessment.md) describe actual delivery evidence and provisional advanced entry.

Speech production uses an optional external voice conversation and a finite pass/report workflow. The [voice bridge](portable/voice-tutor.md) and `validate-voice` check structure, pass identity and completion fields. They do not authenticate sound, score pronunciation or calibrate proficiency. Missing speaking/listening evidence stays unassessed. No paid speech dependency is required.

Learner files stay under ignored `student/`. The coding agent receives whatever learner context it reads into its conversation, and external voice receives the handoff context. Optional TTS/image services receive the text/query sent to them. Local storage therefore does not imply offline inference. API keys belong only in environment variables. Archives contain personal data and are not encrypted. Full backups include managed files from every language plus learner images/audio/video; credentials, server control files, caches and arbitrary unknown files are excluded.

```sh
python tools/tutor.py backup /existing/safe/location/learner.zip
python tools/tutor.py backup-check /existing/safe/location/learner.zip
python tools/tutor.py restore /existing/safe/location/learner.zip /new/location/restored-student
python tools/tutor.py recover learner.json
```

Restore validates the complete archive and publishes a new directory without replacing live data. Use `--student-dir PATH` or `TUTOR_STUDENT_DIR` to select isolated/restored data. The older `export`/`import` JSON commands remain compatible for the active English semantic state.

Set `TUTOR_BACKUP_DIR` to an existing directory on your own backup storage to enable rotating copies after successful study mutations. `TUTOR_BACKUP_KEEP` defaults to 7 and `TUTOR_BACKUP_INTERVAL_HOURS` to 24. `TUTOR_BACKUP_REQUIRE_MOUNT` can require a mounted external volume. No background service is installed; `backup-auto` also runs the policy explicitly. A missing backup volume leaves saved study data intact and reports that the backup is unavailable. [Backup policy and restore drills](docs/backup.md) specify the exact scope and limits.

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
node tests/web_chat_ui.cjs
node tests/speech_ui.cjs
python tools/check_browser_scripts.py
```

Tests use temporary data. They cover FSRS reference parity, migration, corruption/recovery, concurrent writes/retries, 100 simulated sessions, assessment limits, Russian feedback and browser transport. [VALIDATION.md](VALIDATION.md) records the actual results/platforms. CI runs Python 3.10 and 3.14 on Ubuntu and macOS plus the Node checks. Selected real Codex and Claude Code flows are recorded separately from deterministic tests. Learner outcomes, psychometric calibration and actual human speech ratings still require external evidence.

## Files and boundaries

`tools/learning.py` is the evidence/planning model; `tools/tutor.py` is its CLI; `tools/storage.py` serializes durable JSON updates; `tools/srs.py` adapts pinned FSRS. `activities/` contains teaching procedures, `languages/english/` content and Russian contrasts, and `apps/` static local practice. `student.example/` is a compatibility template; initialization never copies it over existing data.

MIT license. The adapted Humanizer skill includes its upstream MIT attribution. Do not redistribute proprietary vocabulary corpora or exam materials through contributions.
