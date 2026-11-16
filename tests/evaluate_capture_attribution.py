"""Opt-in provider regression for actor attribution across typed interview notes."""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.live:
        parser.error('Use --live to run the fictional interview through the configured provider.')

    context = {'process_name': 'Workshop waivers', 'process_owner': '',
               'objective': '', 'background': 'Fictional training example.'}
    turns = [
        {'id': 'u1', 'role': 'user', 'text': 'I am the registrar. I prepare a waiver for each workshop.'},
        {'id': 'a1', 'role': 'assistant', 'text': 'Who signs it, and what happens to the signed waiver?'},
        {'id': 'u2', 'role': 'user', 'text': 'The instructor signs the waiver. Once the instructor signs, '
         'I file the signed waiver in the green binder. The instructor keeps the room schedule.'},
    ]
    client = server.OpenAIClient(server.load_settings())
    result = client.coordinator.interview({'context': context, 'turns': turns, 'action': 'answer'})
    findings = {item['key']: item['answer'] for item in result['memo_findings']}
    report = {'turns': turns, 'findings': findings, 'closure': result['closure']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')

    validate_attribution(findings)


def validate_attribution(findings):
    """Check who files the waiver in each section, including pronouns and passive voice."""
    archive = r"(?:fil(?:e[sd]?|ing)|archiv(?:e[sd]?|ing)|stor(?:e[sd]?|ing)|retain(?:s|ed|ing)?|plac(?:e[sd]?|ing)|put(?:s|ting)?|keep(?:s|ing)?)"
    roles = r"registrars?|participants?|instructors?|i"
    correct = False
    for topic, text in findings.items():
        for clause in re.split(r"[.;!\n]|,\s*(?=(?:then )?(?:the )?(?:instructor|registrar|participant|i)\b)", text.casefold()):
            passive = re.search(r"(?:waivers?|signed forms?|it|they)\b.{0,60}?" + archive +
                                r"\s+by\s+(?:the\s+)?(" + roles + r")\b", clause)
            actors = [passive.group(1)] if passive else []
            if not passive:
                for verb in re.finditer(r"\b" + archive + r"\s+(?:(?:a|the|each|their) )?(?:signed |completed )?(?:waivers?|forms?|it|them)\b", clause):
                    subjects = list(re.finditer(r"\b(" + roles + r")\b", clause[:verb.start()]))
                    if subjects:
                        actors.append(subjects[-1].group(1))
            if any(actor.startswith("instructor") for actor in actors):
                raise AssertionError(f"{topic}: the note assigns filing to the instructor.")
            correct = correct or bool(actors)
    if not correct:
        raise AssertionError("The notes do not establish who filed the waiver.")
    if "waiver" not in findings.get("materials", "").casefold() or not any(
            "green binder" in answer.casefold() for answer in findings.values()):
        raise AssertionError('Review whether the notes retained the artifact and its reported location.')


if __name__ == '__main__':
    main()
