# Live host acceptance

Date: 2026-10-16. All scenarios run in isolated source copies with synthetic learner data. No personal learner files or provider credentials are copied into the repository or report. These checks establish selected client/model behaviors, not educational efficacy or guaranteed future instruction adherence.

## Codex CLI

The globally installed 0.39.0 rejected the user's current reasoning configuration before project execution. An invocation-only override passed configuration parsing but its model request was rejected. An official `@openai/codex@0.163.0` installation in the task's scratch directory was then used with `--ignore-user-config` and `--sandbox workspace-write`; the global installation and configuration were preserved. Authentication remained the existing account. The selected current CLI default was used without requesting a model override.

Three actual turns on the source contract at `41554cf4cfa3b9ff72f28469c1d78b93d02bb12d` passed:

1. A Russian learner supplied 20 minutes/day, work goals and no voice. The client explicitly read the canonical communication/humanize files, initialized a Russian profile, started one stored session and presented one A1 article item in Russian.
2. The learner answered `an` and requested interruption. The exact response was recorded as deterministic correct before the session moved to interrupted.
3. On continuation, a prepared non-exhaustive preference item received the exact answer `love`. The original session resumed; the response stayed `needs_review`/`pending`. Feedback recognized its possible meaning. The planner's existing speaking debt remained true; no nonexistent voice step, assessed speech or promotion was invented.

Durable inspection found one session, two original responses, baseline A1/unassessed, Russian instruction policy and no manufactured human rating. A further actual turn after updating the isolated copy to code revision `278aef9a0da2de8b879eb48e441c8e6fcc70d1b2` reloaded the current instructions, resumed that same session, preserved both original responses and inspected all 99 remaining learner-view items, including 20 listening tasks. No keys/scripts appeared; no new trial or promotion was added.

## Claude Code

The installed client is 2.1.283. Its existing configuration uses a third-party `deepseek-ai/DeepSeek-V4-Flash-0731` model endpoint, so this run must not be described as a test of an Anthropic model. The client loaded the shared communication and humanize files, initialized the same Russian/20-minute/no-voice preferences and started one real stored session. The initial model turn did not produce its final learner reply within roughly 14 minutes and was interrupted. Those real tool calls prove only the stated partial behavior. A bounded continuation on code `278aef9` completed: the exact `love` response was recorded as pending/needs_review, interrupt/start retained the same session ID, and speech debt stayed true with no promotion or fabricated human review. Durable JSON confirmed one original attempt and one session. The client staged the synthetic response in a fixed `/tmp` path despite the task-local instruction; the project instructions were tightened to require unique files under `student/english/session-artifacts/`. This is a recorded adherence deviation, not proof of perfect sandboxing or style compliance. A final focused request to author/validate one A1 item under the tightened staging rule reached CLI help and a staging announcement but did not finish within 180 seconds. It was stopped by the harness timeout; no successful exercise-generation or learner-facing style result is inferred from that partial turn. The configured provider therefore still has an unresolved teaching-latency/acceptance limitation, despite completing the narrower persistence scenario. The client configuration remains separate from an Anthropic-model acceptance claim.

An additional isolated invocation used the existing Anthropic subscription login, project-only settings and the documented `sonnet` alias. Provider-routing environment overrides were removed for that invocation only; no account/global settings changed. It failed before model execution with `401 OAuth access token has been revoked`, with zero model usage reported. This is an authentication blocker requiring owner reauthentication; no login or credential replacement was attempted. It does not establish Anthropic-model teaching behavior.

## Reproducing the scenarios

Use a fresh source copy, an empty isolated `student/`, runtime dependencies in `.venv`, no Git remote and synthetic responses. Do not point the trial at a personal learner. Run the installed clients' own help before selecting supported flags. Noninteractive operation follows the official [Codex CLI reference](https://learn.chatgpt.com/docs/cli/reference) and [Claude Code programmatic guide](https://code.claude.com/docs/en/headless). Preserve project instruction/skill discovery; disabling all customizations would not exercise the integration.

First prompt:

> Меня зовут Тестовый ученик. Я русскоязычный новичок, учу английский для работы по 20 минут в день. Голоса сейчас нет. Начнём первый урок. Это изолированная проверка проекта: используй только student/ в текущем каталоге, не обращайся к моим другим данным и не делай git-коммиты. Достаточно начать урок и дать одно задание.

Answer the actual item, request interruption, then resume with a separately prepared cloze item `I ___ coffee. Write a verb expressing a positive preference.`, `answers: ["like"]`, `exhaustive: false` and the exact answer `love`. Check the raw canonical files after each turn rather than trusting the final prose. Verify original session identity, exact response, grading source, speaking debt, unchanged proficiency and loaded humanize path. Review the language and tone separately.

Full raw traces stay in scratch storage because host startup messages can include unrelated local configuration. This report records only synthetic prompts, relevant behavior and implementation versions.
