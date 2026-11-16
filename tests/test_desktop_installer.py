"""The desktop installer scripts: their shared rules, and that each script parses.

install.ps1, register-updates.ps1 and uninstall.ps1 are never run by the suite: they change the
computer (a scheduled task, a shortcut, the installed window). Their decisions live in
desktop/common.ps1, which only defines functions; this file loads that one script and calls
the functions with made-up inputs. The other scripts are parsed, not executed.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


DESKTOP = Path(__file__).resolve().parents[1] / "desktop"
SHELL = shutil.which("powershell") or shutil.which("pwsh")


def powershell(body, **values):
    """Run a PowerShell fragment with common.ps1 loaded. Values arrive as $env:QA_<NAME>."""
    environment = {**os.environ, "QA_COMMON": str(DESKTOP / "common.ps1"),
                   **{"QA_" + name.upper(): value for name, value in values.items()}}
    environment.pop("VOICE_INTERVIEWER_PYTHON", None)
    script = "$ErrorActionPreference = 'Stop'; . $env:QA_COMMON; " + body
    result = subprocess.run([SHELL, "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                            stdin=subprocess.DEVNULL, env=environment, timeout=300)
    return result.returncode, result.stdout.decode("utf-8", "replace"), result.stderr.decode("utf-8", "replace")


# Calls one function of common.ps1 once per case and reports each result, or the error text.
EACH_CASE = (
    "$answers = foreach ($case in (ConvertFrom-Json $env:QA_CASES)) { "
    "try { __CALL__ } catch { 'ERROR: ' + $_.Exception.Message } }; "
    "ConvertTo-Json -Compress @($answers)")


@unittest.skipUnless(SHELL, "PowerShell is not on this computer")
class InstallerScripts(unittest.TestCase):
    def test_every_script_parses_and_the_shared_one_only_defines_functions(self):
        scripts = sorted(DESKTOP.glob("*.ps1"))
        self.assertLessEqual({"common.ps1", "install.ps1", "register-updates.ps1"}, {script.name for script in scripts})
        check = ("$failed = 0; foreach ($path in $env:QA_SCRIPTS -split '\\|') { $errors = $null; "
                 "[void][System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$null, [ref]$errors); "
                 "foreach ($problem in $errors) { $failed++; Write-Output ($path + ': ' + $problem) } }; exit $failed")
        result = subprocess.run([SHELL, "-NoProfile", "-NonInteractive", "-Command", check], capture_output=True, timeout=300,
                                stdin=subprocess.DEVNULL, env={**os.environ, "QA_SCRIPTS": "|".join(map(str, scripts))})
        self.assertEqual(result.returncode, 0, (result.stdout + result.stderr).decode(errors="replace"))
        # common.ps1 may be loaded by a test because its top level holds nothing but functions.
        kinds = ("$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:QA_COMMON, [ref]$null, [ref]$null); "
                 "ConvertTo-Json -Compress @($ast.EndBlock.Statements | ForEach-Object { $_.GetType().Name })")
        code, out, err = powershell(kinds)
        self.assertEqual(code, 0, err)
        statements = json.loads(out)
        self.assertTrue(statements and set(statements) == {"FunctionDefinitionAst"}, statements)
        # A script that uses those functions loads them from its own folder before its first use.
        load = ". (Join-Path $PSScriptRoot 'common.ps1')"
        users = [script for script in scripts if script.name != "common.ps1" and "-Collector" in script.read_text(encoding="utf-8")]
        self.assertIn("register-updates.ps1", [script.name for script in users])
        for script in users:
            text = script.read_text(encoding="utf-8")
            self.assertIn(load, text, script.name)
            self.assertLess(text.index(load), text.index("-Collector"), script.name)


@unittest.skipUnless(SHELL, "PowerShell is not on this computer")
class InstalledPython(unittest.TestCase):
    """VOICE_INTERVIEWER_PYTHON is resolved once, when the installer runs, into the interpreter
    of both the update task (pythonw.exe) and the window (python.exe)."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def python(self, name, files=("python.exe", "pythonw.exe")):
        folder = self.root / name
        folder.mkdir()
        for item in files:
            (folder / item).write_bytes(b"")
        return folder

    def resolve(self, cases):
        call = ("$found = Resolve-CollectorPython -Configured $case.configured -Default $case.default; "
                "$found.Console + '|' + $found.Windowless + '|' + $found.Source")
        code, out, err = powershell(EACH_CASE.replace("__CALL__", call), cases=json.dumps(cases))
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def test_variable_wins_and_the_codex_runtime_is_the_default(self):
        codex, own, spaced = self.python("codex"), self.python("own"), self.python("with space")
        default = str(codex / "python.exe")
        answers = self.resolve([
            {"configured": "", "default": default},
            {"configured": None, "default": default},
            {"configured": str(own / "python.exe"), "default": default},
            {"configured": str(own / "pythonw.exe"), "default": default},       # either executable names the folder
            {"configured": '"' + str(spaced / "python.exe") + '"', "default": default},  # quoted, as typed in a shell
            {"configured": "  " + str(own / "python.exe") + "  ", "default": default},
            {"configured": str(own / "python.exe"), "default": str(self.root / "missing" / "python.exe")},
        ])
        runtime = "|".join([default, str(codex / "pythonw.exe"), "the Codex runtime"])
        chosen = "|".join([str(own / "python.exe"), str(own / "pythonw.exe"), "VOICE_INTERVIEWER_PYTHON"])
        self.assertEqual(answers, [runtime, runtime, chosen, chosen,
                                   "|".join([str(spaced / "python.exe"), str(spaced / "pythonw.exe"), "VOICE_INTERVIEWER_PYTHON"]),
                                   chosen, chosen])

    def test_unusable_choice_stops_the_installation_and_says_which_file(self):
        codex = self.python("codex")
        console_only = self.python("console-only", files=("python.exe",))
        windowless_only = self.python("windowless-only", files=("pythonw.exe",))
        default = str(codex / "python.exe")
        missing = str(self.root / "nowhere" / "python.exe")
        answers = self.resolve([
            {"configured": missing, "default": default},                         # set, but not there: no silent fallback
            {"configured": str(self.root / "codex"), "default": default},        # a folder, not an executable
            {"configured": "python.exe", "default": default},                    # not a full path
            {"configured": str(console_only / "python.exe"), "default": default},
            {"configured": str(windowless_only / "pythonw.exe"), "default": default},
            {"configured": "", "default": missing},
        ])
        self.assertTrue(all(answer.startswith("ERROR: ") for answer in answers), answers)
        self.assertIn(missing, answers[0])
        self.assertIn("VOICE_INTERVIEWER_PYTHON", answers[0])
        self.assertIn("python.exe", answers[2])
        self.assertIn(str(console_only / "pythonw.exe"), answers[3])
        self.assertIn(str(windowless_only / "python.exe"), answers[4])
        self.assertIn("the Codex runtime", answers[5])

    def test_scripts_give_the_task_and_the_window_the_resolved_interpreter(self):
        # Read from the source: the scripts themselves are not run.
        register = (DESKTOP / "register-updates.ps1").read_text(encoding="utf-8")
        self.assertIn("Resolve-CollectorPython -Configured $env:VOICE_INTERVIEWER_PYTHON", register)
        self.assertIn("$pythonWindowless = $python.Windowless", register)
        self.assertIn("New-ScheduledTaskAction -Execute $pythonWindowless", register)
        self.assertIn("'python.txt'), $python.Console", register)
        # The file is written only after Windows has accepted and confirmed the task.
        self.assertLess(register.index("with unexpected settings"), register.index("'python.txt'"))
        self.assertEqual(register.count("codex-primary-runtime"), 1)
        self.assertNotIn("codex-primary-runtime", (DESKTOP / "install.ps1").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
