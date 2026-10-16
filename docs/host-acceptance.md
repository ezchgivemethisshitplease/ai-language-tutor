# Live host acceptance

Date: 2026-10-16. All scenarios run in isolated source copies with synthetic learner data. No personal learner files or provider credentials are copied into the repository or report. These checks establish selected client/model behaviors, not educational efficacy or guaranteed future instruction adherence.

## Codex CLI

The globally installed 0.39.0 rejected the user's current reasoning configuration before project execution. An invocation-only override passed configuration parsing but its model request was rejected. An official `@openai/codex@0.163.0` installation in the task's scratch directory was then used with `--ignore-user-config` and `--sandbox workspace-write`; the global installation and configuration were preserved. Authentication remained the existing account. The selected current CLI default was used without requesting a model override.

Three actual turns on the source contract at `41554cf4cfa3b9ff72f28469c1d78b93d02bb12d` passed:

1. A Russian learner supplied 20 minutes/day, work goals and no voice. The client explicitly read the canonical communication/humanize files, initialized a Russian profile, started one stored session and presented one A1 article item in Russian.
2. The learner answered `an` and requested interruption. The exact response was recorded as deterministic correct before the session moved to interrupted.
3. On continuation, a prepared non-exhaustive preference item received the exact answer `love`. The original session resumed; the response stayed `needs_review`/`pending`. Feedback recognized its possible meaning. The planner's existing speaking debt remained true; no nonexistent voice step, assessed speech or promotion was invented.

Durable inspection found one session, two original responses, baseline A1/unassessed, Russian instruction policy and no manufactured human rating.

## Claude Code

The installed client is 2.1.283. Its existing configuration uses a third-party `deepseek-ai/DeepSeek-V4-Flash-0731` model endpoint, so this run must not be described as a test of an Anthropic model. The client loaded the shared communication and humanize files, initialized the same Russian/20-minute/no-voice preferences and started one real stored session. The initial model turn has not yet produced its final learner reply at this reporting point; full scenario acceptance is pending and is not inferred from those tool calls.

## Reproducing the scenarios

Use a fresh source copy, an empty isolated `student/`, runtime dependencies in `.venv`, no Git remote and synthetic responses. Do not point the trial at a personal learner. Run the installed clients' own help before selecting supported flags. Noninteractive operation follows the official [Codex CLI reference](https://learn.chatgpt.com/docs/cli/reference) and [Claude Code programmatic guide](https://code.claude.com/docs/en/headless). Preserve project instruction/skill discovery; disabling all customizations would not exercise the integration.

First prompt:

> Меня зовут Тестовый ученик. Я русскоязычный новичок, учу английский для работы по 20 минут в день. Голоса сейчас нет. Начнём первый урок. Это изолированная проверка проекта: используй только student/ в текущем каталоге, не обращайся к моим другим данным и не делай git-коммиты. Достаточно начать урок и дать одно задание.

Answer the actual item, request interruption, then resume with a separately prepared cloze item `I ___ coffee. Write a verb expressing a positive preference.`, `answers: ["like"]`, `exhaustive: false` and the exact answer `love`. Check the raw canonical files after each turn rather than trusting the final prose. Verify original session identity, exact response, grading source, speaking debt, unchanged proficiency and loaded humanize path. Review the language and tone separately.

Full raw traces stay in scratch storage because host startup messages can include unrelated local configuration. This report records only synthetic prompts, relevant behavior and implementation versions.
