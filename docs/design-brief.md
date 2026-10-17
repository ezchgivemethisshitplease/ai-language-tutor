# Learning platform design

The web entry is a learning cabinet. A lesson conversation is one workspace inside it. This document describes the implemented information architecture, rather than an image-generation prompt.

## Routes and responsibilities

| Route | Learner task |
| --- | --- |
| `index.html` | Choose the next action, resume the owning lesson, select a direction, see saved contexts and due cards |
| `chat.html` | Work with the teacher: one current task, goal and preferences, saved plan, pause/resume and explicit handoff |
| `dashboard.html` | Inspect actual answers, completed sessions, due cards and separate language-domain evidence |
| `guide.html` | Understand capabilities, memory consent, voice and data boundaries |
| `flashcards.html`, `quiz.html`, `reader.html`, `dictation.html` | Focus on one prepared activity and return to learning or the lesson |

The primary home action follows saved state: initialize a profile, resume its owning lesson, begin preliminary diagnosis, or practise. Direction cards offer everyday English, work, travel and interests, with a custom option. Opening a card previews its context; it does not send a model message. Explicit goals and per-chat exceptions are visible before practice.

## Visual system

Shared CSS tokens live in `apps/theme.css`. The platform shell uses a neutral green/ink palette: light background `#F5F6F5`, ink `#192C2A`, primary `#235E50`; dark background `#111B1B`, surface `#192626`, ink `#EDF4F0`, primary `#A4DECA`. Installed system fonts require no CDN. Cards use restrained borders, 8–16px corners and clear grouping. The FSRS grades retain distinct Again/Hard/Good/Easy colors.

Desktop uses a fixed 238px navigation column and a two-column next-step/preferences row. Contexts and activities have separate destinations. At intermediate widths the summary stacks and direction cards become two columns. At 700px and below the sidebar gives way to bottom navigation; lesson navigation and plan are expandable. Main actions are at least 44px tall, mobile navigation at least 56px. Focus indicators, skip links, dialog focus handling and reduced-motion preferences are retained.

## State and trust

- Show saved observations and completed sessions. Do not infer streaks, vocabulary growth or a CEFR certificate from elapsed time or a list of known words.
- An unassessed profile does not display its starting A1 value as a measured level.
- Hide a route when no saved steps exist; clear old steps on refresh. Checkmarks come from completed-step IDs.
- Distinguish authentication required, unavailable teacher and failed data load. Retry remains visible.
- Treat titles, preferences and learner text as literal text. Filter malformed conversation IDs instead of routing them to an unrelated chat.
- Context edits retain exact drafts. Account settings apply from the next turn; chat overrides remain scoped.
- A global saved lesson has one owner. Moving it requires an explicit action and preserves the same plan.
- Memory proposals require confirmation. Deleting active memory does not erase historical messages or existing backups.

## Verification boundary

Synthetic browser fixtures exercised actual HTTP/controller/frontend behavior on desktop and a 390×844 override: preferences, memory save/delete, per-chat overrides, exact draft retention, context switching, handoff, diagnostics and progress. Automated Node tests cover state transitions and recovery. This is selected UI acceptance, not a comprehensive accessibility audit or a user study. See [references](design-references.md) and [web acceptance](web-acceptance.md).
