# Settings experience

The previous Settings dialog put six exclusive accordion sections in a 560px column behind More options. Data handling combined the recovery control with a long disclosure. Logs shared the narrow column and nested scrolling. The redesign gives each task a visible destination and preserves the existing preference and storage behavior.

## Access and organization

The app header has one labeled **Menu** for Settings and interview actions. Settings is first in the dropdown; Ctrl/Command + comma still opens it directly. Save, open, transcript, submit, library, example and start-over actions remain available below it. After opening Settings, every section takes one selection. Reopening keeps the last section in the current page. Context and cited interview setup open Interview context directly and retain their return-focus behavior.

| Section | What it contains |
| --- | --- |
| Preferences | System/light/dark appearance choices, searchable question-playback voice picker, preview, typing playback, pause detection and available reviewed-voice controls. |
| Interview context | Participant, process owner, interview goal and background. Existing locks after starting remain in effect. |
| Data & recovery | Existing optional recovery copy, concise local/service summaries and expandable complete disclosures. |
| AI usage | Reported daily/interview counts, configured token limits, progress meters and refresh. Unknown usage is explicit. |
| Agents | Administrators can follow the interview workflow, open the prompts for any agent and copy the full text of a selected prompt. |
| Application logs | Recent/current app session selection, search, refresh and expandable saved records. The existing bounded reader and request protection are unchanged. |
| Help & about | Interview guide, searchable definition of done, guidance on open gaps and owner follow-ups, saving, release version and build identity. |

The setting finder searches a static index of control names and descriptions. It never indexes interview content or private values. Selecting a result opens its section, reveals a needed disclosure, and focuses the control or its section when disabled. Unavailable reviewed-voice and recovery controls are omitted from results.

### Agent prompts

Open **Menu → Settings → Agents**. The overview follows an answer from interview input through capture, review and final confirmation. Select an agent in the diagram to see its role and instructions. Expand **Other paths** for voice, drafts and filed processes, or choose **Prompt library** to browse every role directly.

Select a prompt to see when the app uses it. **Copy prompt** copies the full template, including line breaks. Braced placeholders stand for information the app supplies at runtime, such as the current process or an approved spoken line. Opening this section reads the built-in instructions locally and makes no model request.

The server grants access to a trusted identity with `knowledge.admin` or the explicitly configured single-user loopback owner. Other participants do not see Agents in Settings navigation or search. [Local-owner configuration](KNOWLEDGE_GRAPH.md)

## Interaction details

The native modal provides focus containment and Escape-to-close. Section tabs support arrows, Home and End. The custom voice selector keeps the established voice select as its underlying source, omits disabled choices, supports voice search and roving keyboard focus, and returns focus after selection. Escape first dismisses the picker or clears a setting search; a subsequent Escape closes Settings. Theme and voice preference persistence continue through the existing application handlers.

The layout uses the existing GPFS colors, fonts and icon resources. On narrow screens, Settings uses a navigation grid that includes the sections available to the current user. Content scrolls independently from navigation. Dark/light themes, visible focus and reduced-motion rules use the app's shared tokens.

## Verification scope

The offline Settings suite covers direct access, all destinations, keyboard navigation, finder results and empty states, theme dispatch, voice selection, disabled voice state, usage limits, log scope, remembered section and Context focus. Existing source, validation, notices, recovery, theme and release-boundary suites remain part of verification. Browser review uses synthetic data in an isolated project work directory and covers desktop/mobile layouts and actual controls. It does not establish full screen-reader certification or physical microphone/speaker behavior.
