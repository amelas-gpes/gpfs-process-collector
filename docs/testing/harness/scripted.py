#!/usr/bin/env python3
"""A scripted participant: narrates a library process from its section 8, without an agent.

  scripted.py CASE PORT PROCESS STYLE [--per N] [--max N] [--rate WPM] [--file PATH ...]

Styles
  narrate          N steps per answer (--per), until the steps run out or --max answers
  unknown          two real answers, then "I don't know" answers and two skips
  early            two answers, then Wrap up
  file_mid         two answers, upload --file, then two more answers
  file_only        upload --file, one short answer, Wrap up
  file_contradict  upload --file, confirm it, then say one step is done differently now
  voice            like narrate, but every answer is spoken (--rate) and transcribed by the app

Every case ends with wrap, (waitmap), draft and report. Output goes to logs/CASE.log and logs/CASE.report.txt.
"""
import json, os, re, subprocess, sys, time

# The scratch folder that holds lib/ (these scripts), cases/, logs/, and text/ (see mktext.py).
STRESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
PC = [PY, "-I", "-B", os.path.join(STRESS, "lib", "pc.py")]
LABELS = ["Who performs it:", "What you need before starting:", "Actions:", "System or supporting file:", "Output:",
          "Required check or approval:", "If something is missing or fails:", "Related check IDs:", "Related decision IDs:",
          "Related items to confirm:"]


def section(text, n):
    heads = [(m.start(), int(m.group(1))) for m in re.finditer(r'^(\d{1,2})\.\s+[A-Z][^\n]{3,80}$', text, re.M)]
    body = [h for h in heads if h[0] > 5000] or heads
    for i, (pos, num) in enumerate(body):
        if num == n:
            return text[pos: body[i + 1][0] if i + 1 < len(body) else len(text)]
    return ""


def clean_lines(block):
    out = []
    for line in block.splitlines():
        line = line.strip()
        if not line or line.isdigit() or re.fullmatch(r'(FA|GP|MC)-\d{2}[A-Z]?', line):
            continue
        out.append(line)
    return out


def short(block, limit=2):
    """The first sentence or two lines of a field: enough to state it, without page debris."""
    lines, kept = clean_lines(block), []
    for line in lines[:limit + 1]:
        kept.append(line)
        if line.endswith((".", ";")) or len(kept) >= limit:
            break
    return " ".join(kept).strip().rstrip(";")


def actions(block):
    items, current = [], None
    for line in clean_lines(block):
        m = re.match(r'^([a-z])\.\s+(.*)$', line)
        if m:
            if current:
                items.append(current)
            current = m.group(2)
        elif current is not None and len(current) < 260 and not current.rstrip().endswith("."):
            current += " " + line
        elif current is not None:
            items.append(current); current = None
    if current:
        items.append(current)
    return [re.sub(r'\s+', ' ', x).strip() for x in items if len(x) > 8][:8]


def steps_of(process):
    text = open(os.path.join(STRESS, "text", process + ".txt"), encoding="utf-8").read()
    parts = re.split(r'^Step (\d+) — (.+)$', section(text, 8), flags=re.M)
    steps = []
    for i in range(1, len(parts) - 2, 3):
        title, body = parts[i + 1].strip(), parts[i + 2]
        found = [(m.start(), m.group(0)) for m in re.finditer("|".join(map(re.escape, LABELS)), body)]
        field = {}
        for j, (pos, label) in enumerate(found):
            end = found[j + 1][0] if j + 1 < len(found) else len(body)
            field.setdefault(label, body[pos + len(label):end])
        steps.append({"n": int(parts[i]), "title": title,
                      "who": short(field.get(LABELS[0], ""), 1), "need": short(field.get(LABELS[1], "")),
                      "actions": actions(field.get(LABELS[2], "")), "system": short(field.get(LABELS[3], "")),
                      "output": short(field.get(LABELS[4], "")), "check": short(field.get(LABELS[5], "")),
                      "fail": short(field.get(LABELS[6], ""))})
    return steps


def low(s):
    return s[:1].lower() + s[1:] if s and not s[:2].isupper() else s


def say(step, index):
    opener = ["To begin with", "Next", "After that", "Then", "Once that is done", "Following that"][min(index, 5)]
    out = [f"{opener}, we {low(step['title']).rstrip('.')}."]
    if step["who"]:
        out.append(f"That is done by: {step['who'].rstrip('.')}.")
    if step["need"]:
        out.append(f"Before starting we need {low(step['need']).rstrip('.')}.")
    if step["actions"]:
        out.append("What we do: " + "; ".join(low(a).rstrip(".") for a in step["actions"]) + ".")
    if step["system"]:
        out.append(f"We use {step['system'].rstrip('.')} for it.")
    if step["output"]:
        out.append(f"What comes out is {low(step['output']).rstrip('.')}.")
    if step["check"]:
        out.append(f"The check on it: {low(step['check']).rstrip('.')}.")
    if step["fail"]:
        out.append(step["fail"].rstrip(".") + ".")
    return " ".join(out)


def pc(log, *args, timeout=1040):
    t0 = time.time()
    try:
        p = subprocess.run(PC + list(args), capture_output=True, text=True, timeout=timeout)
        out = p.stdout + (("\n[stderr] " + p.stderr[-800:]) if p.stderr.strip() else "")
    except subprocess.TimeoutExpired:
        out = f"[harness] command timed out after {timeout}s"
    log.write(f"\n$ pc {' '.join(a if len(a) < 90 else a[:87] + '...' for a in args)}   ({time.time() - t0:.1f}s)\n{out}\n")
    log.flush()
    return out


def main():
    a = sys.argv[1:]
    case, port, process, style = a[0], a[1], a[2], a[3]
    opt = lambda name, default: (a[a.index(name) + 1] if name in a else default)
    per, most, rate = int(opt("--per", 1)), int(opt("--max", 8)), opt("--rate", "185")
    files = [a[i + 1] for i, x in enumerate(a) if x == "--file"]
    replayed = json.load(open(opt("--answers", ""))) if "--answers" in a else None
    steps = steps_of(process) if replayed is None else []
    index = json.load(open(os.path.join(STRESS, "text", "index.json")))
    title = opt("--title", index.get(process, {}).get("title", process))
    answers_dir = os.path.join(STRESS, "logs", "answers", case)
    os.makedirs(answers_dir, exist_ok=True)
    log = open(os.path.join(STRESS, "logs", case + ".log"), "w", encoding="utf-8")
    log.write(f"scripted case {case}: {process} {title} | style {style} | {len(steps)} steps parsed\n")
    count = [0]

    def answer(text, voice=False):
        count[0] += 1
        path = os.path.join(answers_dir, f"a{count[0]:02d}.txt")
        open(path, "w", encoding="utf-8").write(text)
        extra = ["--voice", "--rate", rate] if voice else []
        return pc(log, "answer", case, "--file", path, "--think", "45", *extra)

    chunks = [" ".join(say(s, i + j) for j, s in enumerate(steps[i:i + per])) for i in range(0, len(steps), per)]
    start = ["start", case, "--port", port, "--name", title]
    if "--objective" in a:
        start += ["--objective", opt("--objective", "")]
    if "--background" in a:
        start += ["--background", opt("--background", "")]
    pc(log, *start)
    if style == "answers":
        if files:
            pc(log, "upload", case, *files, "--readwait", "360", "--think", "30")
        for text in replayed[:most]:
            if text == "SKIP":
                pc(log, "skip", case)
            else:
                answer(text)
    elif style in ("narrate", "voice"):
        for chunk in chunks[:most]:
            answer(chunk, voice=style == "voice")
    elif style == "unknown":
        for chunk in chunks[:2]:
            answer(chunk)
        role = (steps[0]["who"].split(";")[0] if steps else "my manager") or "my manager"
        for i, text in enumerate(["I don't know, I only joined three weeks ago and have not done that part yet.",
                                  "SKIP", f"I'm not sure. {role} would be the person to ask.",
                                  "I don't know how that works.", "SKIP",
                                  "I can't say, I have not seen that happen yet."]):
            if text == "SKIP":
                pc(log, "skip", case)
            else:
                answer(text)
    elif style == "early":
        for chunk in chunks[:2]:
            answer(chunk)
    elif style == "file_mid":
        for chunk in chunks[:2]:
            answer(chunk)
        pc(log, "upload", case, *files, "--readwait", "360", "--think", "30")
        for chunk in chunks[2:4]:
            answer(chunk)
    elif style == "file_only":
        pc(log, "upload", case, *files, "--readwait", "360", "--think", "30")
        answer("Yes, the file describes how we do this today. I have nothing to add to it.")
    elif style == "file_contradict":
        pc(log, "upload", case, *files, "--readwait", "360", "--think", "30")
        answer("Yes, that file is our written procedure and most of it is still right.")
        target = steps[min(1, len(steps) - 1)] if steps else {"title": "the second step", "n": 2}
        answer(f"One correction to the file: step {target['n']}, {low(target['title'])}, is no longer done the way the file says. "
               "Since this quarter the team lead does that step herself in a shared tracker and emails me when it is finished, "
               "so I only start my part after her email arrives. Everything else in the file is current.")
        for chunk in chunks[2:4]:
            answer(chunk)
    out = pc(log, "wrap", case, "--mapwait", "240")
    if "(none produced)" in out:
        pc(log, "waitmap", case, "--mapwait", "240")
    if "--nodraft" not in a:
        pc(log, "draft", case)
    report = pc(log, "report", case)
    open(os.path.join(STRESS, "logs", case + ".report.txt"), "w", encoding="utf-8").write(report)
    log.write("\nDONE\n")
    log.close()


if __name__ == "__main__":
    main()
