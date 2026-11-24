# Provider use

The app records input, cached-input, output and reasoning-token counts when the configured provider returns them: each finished Responses request adds a `provider_request_finished` row with those counts and the model name to `work/server-lifecycle.jsonl`. Reasoning tokens are part of output tokens, and cached input is part of input. The app keeps no running total, no prices and no limits. Dollar totals require the rates for the team's provider project. Direct WebRTC audio, delegated live calls, transcription, playback and responses without token counts are not counted.

| Operation | Calls on a paced interview | Historical estimate |
| --- | --- | --- |
| Typed answer | One next question, then background capture and map work with a possible audit | About 45,000 to 100,000 input tokens per answer in the November 12 offline replay. Fast answers can coalesce queued work. |
| Sixteen paced answers | Up to about 64 calls under that replay's assumptions | About 862,000 input tokens. Hidden reasoning and prompt-cache discounts were unavailable. |
| Completion review | One process review and four bounded coverage groups | About 33,100 input tokens at sixteen answers in that replay. |
| Generate a draft | Generation, evidence audit and possible coverage assessment or focused route recheck | The historical five-answer sample used about 52,400 input tokens before any recheck. |
| Review a document | A quick read followed by selected batches of text or visual pages | Size and content determine the number of batches. |
| File a process | Local write followed by at most one matching request for the job | Eligible related submissions determine the content sent. |

The estimates use characters divided by four on a past prompt set. They are planning examples, not current charges. For an actual run, use provider-reported tokens and the current contracted model rates. Apply cached and uncached input rates separately and the output rate once. Compare with the provider account's own usage and configured budget.

When the provider reports that the project has no available quota, the request fails with a message that says so. The app does not purchase credit or change provider settings. The project provider's budget controls apply.

Generated artifacts can carry the provider stage, model, prompt fingerprint, reasoning setting, UTC completion time and application build. Existing files keep whatever attribution was originally recorded. New lead-captured facts carry their recording time and the model when the provider reports it. A saved correction history keeps a bounded list of anonymous references, topics and states. It omits withdrawn wording and retired file excerpts.
