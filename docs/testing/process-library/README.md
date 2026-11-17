# Process library

`IP1-export.pdf` is the September 2026 GPFS business process library: 43 processes across 2,020 pages. It is the source of truth for live tests. A participant, human or scripted, answers from it and leaves open whatever it marks as unresolved; notes and diagrams are then checked against what was said and against these pages.

## Contents

| Area | IDs | Processes |
| --- | --- | --- |
| Fund Administration | FA-01 to FA-21, including FA-15A/B, FA-18A/B/C and FA-19A/B | 28 |
| GP Vehicle Services | GP-01 to GP-06 | 6 |
| Management Company | MC-01 to MC-07, including MC-02A/B | 9 |

The first two pages are a table of contents with the starting page of every process. Each process follows the same sixteen sections; the ones tests lean on are:

- **8. Step-by-step procedure**: numbered steps with who performs each, the actions and the result.
- **9. Decisions, exceptions, and escalation**
- **10. Required checks**
- **16. Items to confirm**: what the library itself marks as unresolved. A participant should say "I don't know" for these.

## Using it

- Cite pages when recording where an answer came from.
- To upload part of it, cut the pages into a new PDF and drop link annotations first; otherwise a few pages carry the whole 27 MB document with them (`pypdf`: delete `/Annots` from each page before adding it).
- The file is binary in Git and is left out of release archives.
