# Settings experience · 0.31.1

The previous Settings dialog put six exclusive accordion sections in a 560px column behind More options. Data handling combined the recovery control with a long disclosure. Logs shared the narrow column and nested scrolling. The redesign gives each task a visible destination and preserves the existing preference and storage behavior.

## Access and organization

The app header has one labeled **Menu** for Settings and interview actions. Settings is first in the dropdown; Ctrl/Command + comma still opens it directly. Save, open, transcript, submit, library, example and start-over actions remain available below it. After opening Settings, every section takes one selection. Reopening keeps the last section in the current page. Context and cited interview setup open Interview context directly and retain their return-focus behavior.

| Section | What it contains |
| --- | --- |
| Preferences | System/light/dark appearance choices, searchable question-playback voice picker, preview, typing playback, pause detection and available reviewed-voice controls. |
| Interview context | Participant, process owner, interview goal and background. Existing locks after starting remain in effect. |
| Data & recovery | Existing optional recovery copy, concise local/service summaries and expandable complete disclosures. |
| AI usage | Reported daily/interview counts, configured token limits, progress meters and refresh. Unknown usage is explicit. |
| Application logs | Recent/current app session selection, search, refresh and expandable saved records. The existing bounded reader and request protection are unchanged. |
| Help & about | Three-step guide, saving guidance, release version and build identity. |

The setting finder searches a static index of control names and descriptions. It never indexes interview content or private values. Selecting a result opens its section, reveals a needed disclosure, and focuses the control or its section when disabled. Unavailable reviewed-voice and recovery controls are omitted from results.

## Interaction details

The native modal provides focus containment and Escape-to-close. Section tabs support arrows, Home and End. The custom voice selector keeps the established voice select as its underlying source, omits disabled choices, supports voice search and roving keyboard focus, and returns focus after selection. Escape first dismisses the picker or clears a setting search; a subsequent Escape closes Settings. Theme and voice preference persistence continue through the existing application handlers.

The layout uses the existing GPFS colors, fonts and icon resources, with dedicated Settings styles and no added dependencies or downloaded assets. On narrow screens, all six destinations remain visible in a two-row navigation grid. Content scrolls independently from navigation; log entries use the main content scroll rather than a second scrolling list. Dark/light themes, visible focus and reduced-motion rules use the app's shared tokens.

## Verification scope

The offline Settings suite covers direct access, all destinations, keyboard navigation, finder results and empty states, theme dispatch, voice selection, disabled voice state, usage limits, log scope, remembered section and Context focus. Existing source, validation, notices, recovery, theme and release-boundary suites remain part of verification. Browser review uses synthetic data in an isolated project work directory and covers desktop/mobile layouts and actual controls. It does not establish full screen-reader certification or physical microphone/speaker behavior.
