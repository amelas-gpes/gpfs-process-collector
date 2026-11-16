# Provider use and local limits

The app records input, cached-input, output and reasoning-token counts when the configured provider returns them. Reasoning tokens are part of output tokens, and cached input is part of input. Daily totals use UTC. Dollar totals require the rates for the team's provider project. Direct WebRTC audio, delegated live calls, playback and responses without token counts can be missing from these totals.

| Operation | Calls on a paced interview | Historical estimate |
| --- | --- | --- |
| Typed answer | One next question, then background capture and map work with a possible audit | About 45,000 to 100,000 input tokens per answer in the November 12 offline replay. Fast answers can coalesce queued work. |
| Sixteen paced answers | Up to about 64 calls under that replay's assumptions | About 862,000 input tokens. Hidden reasoning and prompt-cache discounts were unavailable. |
| Completion review | One process review and four bounded coverage groups | About 33,100 input tokens at sixteen answers in that replay. |
| Generate a draft | Generation, evidence audit and possible coverage assessment or focused route recheck | The historical five-answer sample used about 52,400 input tokens before any recheck. |
| Review a document | A quick read followed by selected batches of text or visual pages | Size and content determine the number of batches. |
| File a process | Local write followed by at most one matching request for the job | Eligible related submissions determine the content sent. |

The estimates use characters divided by four on a past prompt set. They are planning examples, not current charges. For an actual run, use provider-reported tokens and the current contracted model rates. Apply cached and uncached input rates separately and the output rate once. Compare with the provider account's own usage and configured budget.

Optional local settings DAILY_TOKEN_CAP and INTERVIEW_TOKEN_CAP accept whole token counts. Zero disables a cap. Before a Responses call, the server compares completed usage and current reservations with a conservative estimate of input plus maximum output. Consequently it can decline a request the model might have completed under the limit. Map work yields near the threshold. Saving the interview requires no provider call. Separate server processes can have simultaneous outstanding requests. The project provider's budget controls also apply.

An exhausted-project response pauses further requests in that server. After resolving the provider issue, select **Check again** in Settings. The next requested action can then contact the provider. The app does not purchase credit or change provider settings.


Generated artifacts can carry the provider stage, model, prompt fingerprint, reasoning setting, UTC completion time and application build. Existing files keep whatever attribution was originally recorded. New lead-captured facts carry their recording time and the model when the provider reports it. A saved correction history keeps a bounded list of anonymous references, topics and states. It omits withdrawn wording and retired file excerpts.
