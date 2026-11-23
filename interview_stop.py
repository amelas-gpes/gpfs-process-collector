"""Participant stop intent for typed interviews, live voice, and background capture."""
import re


# Every reply the server itself gives to a stop request (the typed-turn path, the
# Coordinator, and both variants of the response boundary below). A stop request
# followed by one of these has been answered and is not answered again.
STOP_ACKNOWLEDGEMENTS = (
    "Of course. We can pause here and keep the unfinished parts open.",
    "Of course. We can stop here. Your account is retained, with any unfinished sections still open.",
    "Of course. We can stop here. The captured account remains available for review.",
    "Of course. We can stop here. The unfinished sections remain open; this is a partial capture.")
_STOP_FILLER = r"(?:okay|ok|sorry|actually|um+|uh+|er+|well|alright|all right|right|so|look|thanks|thank you)"
_STOP_COURTESY = (r"(?:please|sorry|bye|goodbye|thanks|thank you)"
                  r"(?: (?:very|so) much| a lot| for (?:your|the) (?:help|time|patience)| about that)?")
_STOP_APPOINTMENT = r"(?:a|an|another|my|my next|the next) (?:meeting|call|appointment)"
_STOP_GO = (r"i(?:(?: have|['’]ve got| have got| need) to| must) (?:go|leave|run)(?: now| soon| shortly)?"
            r"(?: (?:to|for) " + _STOP_APPOINTMENT + r")?")
# When the meeting or call is: 'now', 'in five minutes', 'at three'. Nothing longer
# may follow, so 'I have a meeting with the controller before anything is released'
# stays an answer.
_STOP_SOON = (r"(?: (?:now|right now|soon|shortly|coming up|in (?:\w+ ){1,2}(?:minutes?|mins?|moments?)"
              r"|at (?:\d{1,2}(?::\d\d)?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|noon)"
              r"(?: (?:o['’]clock|am|pm))?))?")
# The participant's own reason for leaving, as a whole clause. Anything else beside
# an ambiguous stop word is process content ('Stop. Nothing is released until the
# controller signs', 'Pause. My call with the custodian confirms the amount').
_STOP_REASON = (r"(?:" + _STOP_GO +
                r"|i(?: have|['’]ve got| have got) (?:(?:another|a|an|my next)(?: \w+)? (?:meeting|call|appointment|commitment)"
                r"|a hard stop)" + _STOP_SOON +
                r"|i can (?:get to|go to|make|join|take) (?:a|an|another|my|my next|the next) (?:meeting|call|appointment)"
                r"|(?:i['’]m|i am|we['’]re|we are) (?:out of|running out of|short on) time"
                r"|(?:i['’]m|i am) (?:running )?late(?: for (?:a|an|another|my|my next|the|the next) (?:meeting|call|appointment))?"
                r"|my (?:next )?(?:meeting|call|appointment) (?:is (?:starting|about to start)|starts)" + _STOP_SOON +
                r"|it['’]s getting late|something (?:urgent |important )?(?:has |just )?c[ao]me up)")
_STOP_SOMEONE = r"my (?:boss|manager|supervisor|director|team lead|colleague|client|customer|phone)"
# Everyday first-person reasons and parting requests, again as a whole clause.
_STOP_PERSONAL = (
    r"(?:(?:i['’]m|i am)(?: (?:really|very|so|too|just|quite|pretty|a bit|a little|getting|feeling)){0,3}"
    r" (?:tired|exhausted|worn out|unwell|sick|ill|not (?:feeling|doing)(?: (?:very|too|so))? (?:well|good|great)|not well)"
    r"|i (?:do not|don['’]t) feel (?:very |too |so )?(?:well|good|great)"
    r"|i (?:really |just )?(?:need|want|could use|have to take|need to take) (?:a|another|five|ten|a few)"
    r"(?: (?:short|quick|little|comfort|bathroom|lunch))? (?:break|rest|breather|minutes?|moment)"
    r"|i (?:really |just )?(?:have|need|['’]ve got) to (?:get back to (?:work|my desk)|take (?:this|a|another) call"
    r"|pick up (?:my|the) (?:kids?|children|son|daughter))"
    r"|" + _STOP_SOMEONE + r"(?: is|['’]s)? (?:calling|ringing|waiting|asking|looking)(?: for)?(?: me)?(?: now| again)?"
    r"|" + _STOP_SOMEONE + r" (?:needs|wants) me(?: now)?"
    r"|my shift (?:is|['’]s|has) (?:over|ending|ended|finished)"
    r"|this is taking (?:too|so|very) long"
    r"|(?:save|keep) (?:what (?:we have|we['’]ve got|i (?:have )?said)|my (?:notes|answers)|the notes)"
    r"|no more questions(?: (?:today|for (?:now|today)))?)")
# 'and continue tomorrow', 'we can pick this up next week': resuming the interview
# later. A later time is required, so 'and go back to the approval step' is not it.
_STOP_LATER = (r"(?:later(?: on| today)?|tomorrow|another (?:time|day)|some other (?:time|day)|next (?:time|week|month)"
               r"|(?:on|next) (?:monday|tuesday|wednesday|thursday|friday)|after (?:lunch|the break)"
               r"|this (?:afternoon|evening)|in the (?:morning|afternoon))")
_STOP_RESUME = (r"(?:(?:we can|can we|could we|we could|i can|i could|i['’]ll|i will|we['’]ll|we will|let['’]?s|shall we) )?"
                r"(?:(?:continue|resume|carry on|finish|reschedule)(?: (?:this|it|that|the rest|the interview|the conversation))?"
                r"|pick (?:this|it|that|things)(?: back)? up|pick up(?: again| where we left off)?"
                r"|(?:come|get) back(?: to (?:this|it|that|the rest|you))?|do (?:this|the rest))(?: again)? " + _STOP_LATER)
# The participant speaking about the conversation: 'I need to stop', 'I'd like to
# pause'; put to the interviewer: 'let's stop', 'can we pause'; and the weaker 'we
# need to stop', which is as often a statement about the work. 'End' and 'finish'
# keep their narrower set of openers because 'we have to finish today' is about the work.
_STOP_NEED = (r"(?:(?:i (?:need|want|have|would like)|i['’]d like) to (?:stop|pause)"
              r"|(?:i (?:need|want|would like)|i['’]d like) to (?:end|finish))")
_STOP_ASK = (r"(?:let['’]?s (?:stop|pause|end|finish)"
             r"|(?:can|could|may|shall|should) (?:we|i)(?: please)? (?:stop|pause)"
             r"|(?:can|could) we(?: please)? (?:end|finish))")
_STOP_WE = r"we (?:need|have) to (?:stop|pause)"
_STOP_INTERVIEW = r"(?:this|the|our) (?:interview|conversation)"
# 'The session', 'the call', 'here' and 'there' can also be a thing or a point in
# the work, so they never make a request firm.
_STOP_SESSION = r"(?:this|the|our) (?:interview|conversation|session)"
_STOP_CALL = r"(?:this|the|our) (?:call|meeting)"
_STOP_WHEN = r"(?:now|right now|for now|for today|for the day|for the moment|for a (?:minute|moment))"
_STOP_TIME_UP = r"that(?:['’]s| is) all (?:i|we) have time for(?: (?:today|now|right now))?"
_STOP_DONE = (r"(?:(?:i['’]m|i am|we['’]re|we are) done (?:for (?:now|today|the day|the moment)"
              r"|with (?:this|that|the|our) (?:interview|conversation|session))|(?:i['’]m|i am) done with this)")
_STOP_OPEN = r"(?:" + _STOP_FILLER + r" ){0,4}(?:please )?"
_STOP_AND_LATER = r"(?: (?:and|but|so)(?: then)? " + _STOP_RESUME + r")?"
# After a firm request, the speaker can share a subject with a second verb:
# “I need to stop now and go to a meeting.” Work destinations stay outside this list.
_STOP_LEAVING = (r"(?:(?:go|get|head|run) to|leave for|join|attend|take) " + _STOP_APPOINTMENT +
                 r"|get back to (?:work|my desk)|take (?:a|my) break|pick up (?:my|the) (?:kids?|children)")
# The message is read clause by clause (see _stop_clauses); every pattern is
# anchored to one clause, so matching stays linear in the length of the message.
# A firm request is the participant's own ('I', 'let's', 'can we', 'please') and
# names the interview itself or the present moment: 'I need to stop now', 'please
# stop the interview', 'I'm done for today'. Any reason may be given with it.
_STOP_FIRM = re.compile(
    _STOP_OPEN + r"(?:(?:" + _STOP_NEED + r"|" + _STOP_ASK + r")(?: (?:here|there|talking))? (?:" + _STOP_INTERVIEW + r"|" + _STOP_WHEN + r")"
    r"(?: (?:" + _STOP_INTERVIEW + r"|" + _STOP_WHEN + r"|here|there)){0,2}"
    r"|(?:stop|pause)(?: (?:" + _STOP_WHEN + r"|here)){0,2} " + _STOP_INTERVIEW + r"(?: (?:" + _STOP_WHEN + r"|here)){0,2}"
    r"|" + _STOP_TIME_UP +
    r"|(?:i['’]m|i am) done (?:for (?:now|today|the moment)|with (?:this|the|our) (?:interview|conversation)))"
    r"(?: " + _STOP_COURTESY + r")?(?: (?:because|since|so|as(?! soon\b| long\b)) .+|"
    r" (?:and|but)(?: then)? (?:" + _STOP_REASON + r"|" + _STOP_PERSONAL + r"|" + _STOP_LEAVING + r")|"
    + _STOP_AND_LATER + r"(?: " + _STOP_COURTESY + r")?)",
    re.IGNORECASE)
# Any request, including the ambiguous ones: a bare 'Stop.', 'Let's finish.', 'I
# need to stop', 'We need to stop now', 'I'm done with this', 'I have to go'. With
# these only a listed reason for leaving or a later time to resume may be joined.
_STOP_SOFT_NAMED_HEAD = (
    _STOP_NEED + r"(?: (?:" + _STOP_SESSION + r"|" + _STOP_WHEN + r"|" + _STOP_CALL + r"|here|talking)){0,3}"
    r"|" + _STOP_ASK + r"(?: (?:" + _STOP_SESSION + r"|" + _STOP_WHEN + r"|" + _STOP_CALL + r"|here|there|talking)){0,3}"
    r"|" + _STOP_TIME_UP + r"|" + _STOP_DONE + r"|" + _STOP_GO)
_STOP_SOFT_TAIL = (r"(?: " + _STOP_COURTESY + r")?(?: (?:because|since|as|so) (?:" + _STOP_REASON + r"|" + _STOP_PERSONAL + r"))?" +
                   _STOP_AND_LATER + r"(?: " + _STOP_COURTESY + r")?")
_STOP_SOFT = re.compile(
    _STOP_OPEN + r"(?:(?:stop|pause|" + _STOP_WE + r")(?: (?:" + _STOP_SESSION + r"|" + _STOP_WHEN + r"|here|talking)){0,3}"
    r"|" + _STOP_SOFT_NAMED_HEAD + r")" + _STOP_SOFT_TAIL, re.IGNORECASE)
# The same without a bare 'Stop.' or 'Pause.' and without 'we need to stop': only
# requests that name the speaker ('I need to stop', 'can we pause', 'I have to go').
# A courtesy said after a request is passed over only for these and the firm ones
# (see stop_request_prefix): 'A duplicate shows up in the batch. We need to stop.
# Okay.' is an answer.
_STOP_SOFT_NAMED = re.compile(_STOP_OPEN + r"(?:" + _STOP_SOFT_NAMED_HEAD + r")" + _STOP_SOFT_TAIL, re.IGNORECASE)
# Beside an ambiguous request, any other clause may only be a filler, a courtesy,
# a reason for leaving or a later time to resume.
_STOP_ASIDE = re.compile(
    r"(?:" + _STOP_FILLER + r" ){0,4}(?:" + _STOP_FILLER + r"|" + _STOP_COURTESY +
    r"|(?:(?:because|since|as|and|but|so) )?(?:" + _STOP_REASON + r"|" + _STOP_PERSONAL + r")(?: " + _STOP_COURTESY + r")?"
    r"|(?:(?:and|but|so|maybe|perhaps) )?" + _STOP_RESUME + r"(?: please)?)", re.IGNORECASE)
# What follows a firm request is the participant's business ('my boss is calling',
# 'leave those gaps recorded'), unless it carries on with the work: 'I need to
# stop now, then check the file.'
_STOP_CONTINUES = re.compile(
    r"(?:(?:and|but|so) )?(?:then|after that|afterwards|otherwise|or else"
    r"|next(?! (?:time|week|month|monday|tuesday|wednesday|thursday|friday)))\b"
    r"|and (?!i\b|i['’]|we\b|we['’]|you\b|can\b|could\b|let['’]?s\b|thank|sorry\b|my\b|please\b|maybe\b"
    r"|that['’]s\b|it['’]s\b|this\b)", re.IGNORECASE)
# An explicit request to the interviewer to stop recording is a control. An instruction
# about recording a receipt or completing a process step does not match the whole clause.
_STOP_RECORDING = re.compile(
    r"(?:(?:can|could|would) you (?:please )?|(?:please )?)(?:stop|pause) (?:the |this )?recording(?: now)?", re.I)
# The browser's immediate microphone cutoff is conservative: it checks a final sentence.
# The server also recognizes multipart farewells and decides which prior testimony to keep.
STOP_INTENT_PATTERNS = tuple("^(?:" + pattern.pattern + ")$" for pattern in (_STOP_FIRM, _STOP_SOFT, _STOP_RECORDING))
# The requests that stand with a courtesy around them (see _STOP_SOFT_NAMED).
STOP_NAMED_INTENT_PATTERNS = tuple("^(?:" + pattern.pattern + ")$" for pattern in (_STOP_FIRM, _STOP_SOFT_NAMED, _STOP_RECORDING))
# A sentence that is only a courtesy or a goodbye: 'Thanks.', 'Thank you very much!',
# 'Okay, bye.', 'Cheers.', 'Have a good day.' Said after a request to stop that names
# the speaker, it leaves the request standing, so the request is read in the sentence
# before it. The browser skips the same sentences (it is sent this pattern with the
# stop patterns), so it is written in lower case and in syntax JavaScript reads the same way.
_STOP_SIGN_OFF_GAP = r"[\s,;:…—–-]"
_STOP_SIGN_OFF_WORD = (r"(?:okay|ok|alright|all right|great|cheers|sorry(?: about that)?|take care"
                       r"|see you(?: (?:later|soon|next time))?|(?:talk|speak)(?: to you)? soon"
                       r"|have a (?:good|nice|great|lovely) (?:day|one|afternoon|evening|weekend)"
                       r"|(?:it was )?(?:nice|good|great) (?:talking|speaking) (?:to|with) you"
                       r"|bye(?:[ -]bye| now| for now)?|goodbye"
                       r"|(?:thanks|thank you)(?: (?:again|(?:very|so) much|a lot|for having me"
                       r"|for (?:your|the|all (?:your|the)) (?:help|time|patience)(?: today)?)){0,2})")
STOP_SIGN_OFF_PATTERN = (r"^" + _STOP_SIGN_OFF_GAP + r"*" + _STOP_SIGN_OFF_WORD
                         + r"(?:" + _STOP_SIGN_OFF_GAP + r"+(?:and )?" + _STOP_SIGN_OFF_WORD + r"){0,3}"
                         + _STOP_SIGN_OFF_GAP + r"*$")
_STOP_SIGN_OFF = re.compile(STOP_SIGN_OFF_PATTERN, re.IGNORECASE)
_STOP_SENTENCE_BREAK = re.compile(r"[.!?…;\n]+")
_STOP_CLAUSE_BREAK = re.compile(r"[,()]|:(?!\d)|\s[—–-]+\s")


def _stop_clauses(text, limit):
    """The first clauses of a message: split at sentence ends, commas, colons, dashes and brackets."""
    clauses = []
    for sentence in _STOP_SENTENCE_BREAK.split(text):
        for clause in _STOP_CLAUSE_BREAK.split(sentence):
            clause = " ".join(clause.split())
            if clause:
                clauses.append(clause)
                if len(clauses) == limit:
                    return clauses
    return clauses


def stop_request_text(text, soft=_STOP_SOFT):
    """Only a direct request to stop the interview itself.

    Process instructions ('we stop the merge on an error', 'Stop and escalate to
    the controller', 'I'm done with this when the bank confirms'), quoted text and
    a local 'no' are not requests. A firm request stands with whatever reason or
    parting remark is added to it, after any punctuation ('I need to stop now, my
    boss is calling', 'I need to stop now. Leave those gaps recorded.'), unless
    the next thing said carries on with the work ('I need to stop now, then check
    the file'). An ambiguous one counts only when nothing but a courtesy, a
    reason for leaving or a later time to resume comes with it: 'Stop. Nothing
    is released until the controller signs' is an answer. With `soft` set to
    _STOP_SOFT_NAMED, a bare 'Stop.' and 'we need to stop' are not requests.
    """
    clauses = _stop_clauses(text, 9)
    requested = False
    for index, clause in enumerate(clauses[:8]):
        if _STOP_FIRM.fullmatch(clause) or _STOP_RECORDING.fullmatch(clause):
            following = next((later for later in clauses[index + 1:] if not _STOP_ASIDE.fullmatch(later)), "")
            return not _STOP_CONTINUES.match(following)
        if soft.fullmatch(clause):
            requested = True
        elif not _STOP_ASIDE.fullmatch(clause):
            return False
    return requested and len(clauses) <= 8


def stop_request_prefix(text):
    """Return testimony before a closing request, an empty string for control alone, or None."""
    if stop_request_text(text):
        return ""
    # Keep preceding sentences intact when the participant both reports work and asks to stop.
    # Only the final sentence can take this shortcut, so "Stop. Then check the file" stays intact.
    # A courtesy after a request that names the speaker ("... I need to stop now. Thanks.")
    # is passed over: it is neither testimony nor a new request. After a bare "Stop." or
    # "We need to stop." it is not: "The batch has a duplicate. We need to stop. Okay." is an answer.
    body = text.rstrip(".!?…;\n ")
    breaks = list(_STOP_SENTENCE_BREAK.finditer(body))
    soft = _STOP_SOFT
    while breaks and _STOP_SIGN_OFF.fullmatch(body[breaks[-1].end():].strip()):
        body, soft = body[:breaks.pop().start()], _STOP_SOFT_NAMED
    if soft is _STOP_SOFT_NAMED and stop_request_text(body, soft):
        return ""
    final = breaks[-1] if breaks else None
    if final and stop_request_text(body[final.end():], soft):
        return text[:final.end()].strip()
    return None


def _courtesy_only(text):
    """A message that is only courtesies or goodbyes: 'Thanks.', 'Okay. Bye.'"""
    sentences = [sentence.strip() for sentence in _STOP_SENTENCE_BREAK.split(text) if sentence.strip()]
    return bool(sentences) and all(_STOP_SIGN_OFF.fullmatch(sentence) for sentence in sentences)


def stop_request_turn(turns):
    """The participant's latest turn, or the request to stop that only courtesies follow.

    In live voice a thank-you said once the interviewer has answered a request to stop
    is a turn of its own ('I need to stop now.' ... 'Thanks.'). The request was a whole
    turn, and the page ended voice on it, so the thank-you leaves it standing.
    """
    said = [t for t in turns if t["role"] == "user" and not t.get("document_event")]
    index = len(said) - 1
    while index > 0 and _courtesy_only(said[index]["text"]):
        index -= 1
    if index < len(said) - 1 and stop_request_prefix(said[index]["text"]) is not None:
        return said[index]
    return said[-1] if said else None


def participant_requested_stop(turns, action="answer"):
    """Whether the participant's latest message is a request to stop that is still unanswered."""
    # An explicit Wrap up, Skip or file follow-up is a newer instruction than an
    # earlier request to stop: it is answered, never met with the pause reply again.
    if action in ("close", "skip", "document_followup"):
        return False
    spoken = [t for t in turns if not t.get("document_event")]
    request = stop_request_turn(spoken)
    if request is None:
        return False
    last = next(index for index, turn in enumerate(spoken) if turn is request)
    # In live voice the model's own spoken caption can already follow the request
    # when a capture is posted, so a later interviewer turn alone does not consume
    # it. The server's own acknowledgement does.
    if any(t["role"] == "assistant" and t["text"].strip() in STOP_ACKNOWLEDGEMENTS for t in spoken[last + 1:]):
        return False
    return stop_request_prefix(spoken[last]["text"]) is not None
