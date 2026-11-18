# Checked-map draft and contextual help

The first draft pass used to generate every workflow step and route. The updated pass takes a source-checked map as its starting point and returns changes. The server builds a complete draft and sends it through the existing source audit.

## Live comparison

We replayed the repository's [synthetic invoice interview](../../../../Examples/Synthetic-reviewed-session.json). A fresh source check produced a map with 12 steps and 15 routes from 26 transcript turns. The old and new first passes ran concurrently on GPT-6.1 Terra with the same interview, checked map and notes. The two requests carried the same source payload. Each used its version's instructions and response schema.

| First draft pass | Previous version `bfb8bba` | Updated version |
| --- | ---: | ---: |
| Elapsed seconds | 95.0 | 71.2 |
| Output tokens | 8,356 | 6,216 |
| Steps written by the model | 14 | 9 |
| Routes written by the model | 17 | 2 |
| Original steps retained exactly | 0 of 12 | 6 of 12 |
| Original routes retained exactly | 9 of 15 | 15 of 15 |
| Memo sections returned | 16 | 16 |

Both candidates kept the 12 original step IDs. The updated first pass returned six revised steps and three additions. Exact matches in the table require every field and citation to match. The first pass saved 23.8 seconds and 2,140 output tokens in this interview. The timing covers one pair of requests and ends when the candidate is ready for audit.

The updated version also completed its independent source audit and four coverage reviews. It returned a validated draft 131.5 seconds after preparation, with 15 steps, 17 routes and 16 memo sections. All 12 original step IDs and all 15 original routes survived. At this point each original step differed in at least one field. The measurement did not distinguish audit corrections from normalization of optional fields. The comparison did not time the old version's final audit.

All eight provider requests completed. The estimated total for the map check, both first passes and the updated draft's final reviews was $0.52, using reported tokens and standard model prices. [GPT-6.1 Terra pricing](https://developers.openai.com/api/docs/models/gpt-6.1-terra) and [GPT-5.4 pricing](https://developers.openai.com/api/docs/models/gpt-5.4).

## Regression coverage

At `00cf9e3`, all 1,875 Python tests that ran passed. An additional 75 Windows-specific tests and three private-fixture tests skipped on this Mac. All 96 Node suites passed.

The Chrome typed-interview test waited for a checked map, opened Create draft in Review, and verified that a provider returning zero map edits produced the same three step IDs, titles, citations and routes. Separate regressions cover edited source text, pending checks, file excerpts, draft preparation, additions, deletions and conflicting changes.

The Chrome tooltip test exercised pointer hover, keyboard focus, Escape, existing accessible descriptions, review fields, settings, logs, map controls and a narrow component-library view. The navigation test completed 36 actions with zero page errors.
