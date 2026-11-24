# Settings experience

The previous Settings dialog put exclusive accordion sections in a 560px column behind More options. The redesign gives each task a visible destination and preserves the existing preference and storage behavior.

## Access and organization

The app header has one labeled **Menu** for Settings and interview actions. Settings is first in the dropdown; Ctrl/Command + comma still opens it directly. Save, open, transcript, submit, example and start-over actions remain available below it. After opening Settings, every section takes one selection. Reopening keeps the last section in the current page. Context and cited interview setup open Interview context directly and retain their return-focus behavior.

Settings opens as a large window: up to 1280 by 900 pixels, and never closer than 24 pixels to the edge of the browser window. A sidebar holds the title, the setting finder and the sections in three groups: General (Preferences, Interview context), Workspace (Data handling) and Support (Help & about). The section on the right pins its title and description while its content scrolls, and **Done** stays in the top corner.

| Section | What it contains |
| --- | --- |
| Preferences | System/light/dark appearance choices, each with a miniature of the workspace in that theme; searchable question-playback voice picker and the option to read questions aloud when typing. |
| Interview context | Participant, process owner, interview goal and background. Existing locks after starting remain in effect and are explained at the top of the section. |
| Data handling | Concise local/service summaries and the expandable complete disclosure. |
| Help & about | Interview guide, searchable definition of done, guidance on open gaps and owner follow-ups, saving, keyboard shortcuts, release version and build identity. |

Each section is a column of labelled blocks: a short heading and explanation on the left and the controls in a card on the right. In a narrower window the explanation moves above its card.

The setting finder searches a static index of control names and descriptions. It never indexes interview content or private values. Selecting a result opens its section, reveals a needed disclosure, and focuses the control or its section when disabled. While results are listed no section is marked as current. A search with no match offers a few searches that do match.

## Interaction details

The native modal provides focus containment and Escape-to-close. Section tabs support arrows, Home and End. The custom voice selector keeps the established voice select as its underlying source, omits disabled choices, supports voice search and roving keyboard focus, and returns focus after selection. Escape first dismisses the picker or clears a setting search; a subsequent Escape closes Settings. Theme and voice preference persistence continue through the existing application handlers.

The layout uses the existing GPFS colors, fonts and icon resources. The voice list opens over the content below it instead of moving it. On narrow screens, Settings fills the window and uses a navigation grid of the sections; group names and section descriptions are omitted there, and section headings scroll with their content. Content scrolls independently from navigation. Dark/light themes, visible focus and reduced-motion rules use the app's shared tokens. The appearance miniatures use fixed colors so that each shows its own theme, and are hidden in forced-colors mode.

## Verification scope

The offline Settings suite covers direct access, all destinations, keyboard navigation, finder results, empty states and their suggestions, theme dispatch, voice selection, disabled voice state, remembered section and Context focus. Existing source, validation, notices, theme and release-boundary suites remain part of verification. Browser review uses synthetic data in an isolated project work directory and covers desktop/mobile layouts and actual controls. It does not establish full screen-reader certification or physical microphone/speaker behavior.
