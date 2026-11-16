"""The window host's own rules (desktop/NativeHost.cs, class HostLogic), exercised without a window.

The host is never started by the suite: it opens a window, a browser profile and a local service.
Its decisions that need none of those live in the static class HostLogic. This file compiles
NativeHost.cs together with tests/desktop_host_checks.cs, a console front end whose own Main is
selected (/main:HostChecks), and asks that program questions. Program.Main and the form never run.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


DESKTOP = Path(__file__).resolve().parents[1] / "desktop"
CHECKS = Path(__file__).resolve().with_name("desktop_host_checks.cs")
NOTHING = "<null>"


BUILT = {}


def setUpModule():
    compiler = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
    sdk = Path.home() / ".nuget" / "packages" / "microsoft.web.webview2" / "1.0.4258.31" / "lib" / "net462"
    references = [sdk / "Microsoft.Web.WebView2.Core.dll", sdk / "Microsoft.Web.WebView2.WinForms.dll"]
    if not compiler.is_file() or not all(reference.is_file() for reference in references):
        return  # HostRules skips: the .NET Framework C# compiler or the WebView2 SDK is not on this computer.
    scratch = tempfile.TemporaryDirectory()
    unittest.addModuleCleanup(scratch.cleanup)
    program = Path(scratch.name) / "host-checks.exe"
    # The host's own source and switches (desktop/install.ps1), as a console program with
    # the checks' entry point. The WebView2 libraries are needed to compile, never loaded.
    result = subprocess.run(
        [str(compiler), "/nologo", "/target:exe", "/main:HostChecks", "/platform:x64", "/optimize+", "/codepage:65001",
         "/out:" + str(program), *("/reference:" + str(reference) for reference in references),
         "/reference:System.Drawing.dll", "/reference:System.Windows.Forms.dll",
         str(DESKTOP / "NativeHost.cs"), str(CHECKS)],
        capture_output=True, stdin=subprocess.DEVNULL, timeout=300)
    BUILT["report"] = (result.stdout + result.stderr).decode(errors="replace")
    if not result.returncode and program.is_file():
        BUILT["program"] = program


class HostRules(unittest.TestCase):
    """Asks the compiled rules. Subclasses hold the questions."""

    def setUp(self):
        if "report" not in BUILT:
            self.skipTest("the .NET Framework C# compiler or the WebView2 SDK is not on this computer")
        self.assertIn("program", BUILT, "The window host's rules did not compile:\n" + BUILT["report"])
        self.assertNotIn("warning", BUILT["report"].lower(), BUILT["report"])
        self.program = BUILT["program"]

    def ask(self, *requests):
        """One answer per request; each request is a tuple of fields (None for a missing value)."""
        lines = ["\t".join(NOTHING if field is None else str(field).replace("\r", "<CR>").replace("\n", "<LF>")
                           for field in request) for request in requests]
        result = subprocess.run([str(self.program)], input=("\n".join(lines) + "\n").encode("utf-8"),
                                capture_output=True, timeout=120, cwd=self.program.parent)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        answers = result.stdout.decode("utf-8").splitlines()
        self.assertEqual(len(answers), len(requests), answers)
        return [None if answer == NOTHING else answer.replace("<CR>", "\r").replace("<LF>", "\n") for answer in answers]

class InstalledInterpreter(HostRules):
    def test_window_uses_the_python_written_at_installation_and_nothing_else(self):
        usable = {
            "C:\\Tools\\Python312\\python.exe": "C:\\Tools\\Python312\\python.exe",
            "C:\\Tools\\Python312\\python.exe\r\n": "C:\\Tools\\Python312\\python.exe",
            "\ufeffD:\\py\\PYTHON.EXE\n": "D:\\py\\PYTHON.EXE",
            '"C:\\Program Files\\Python 3\\python.exe"\n': "C:\\Program Files\\Python 3\\python.exe",
            "\\\\server\\share\\py\\python.exe": "\\\\server\\share\\py\\python.exe",
            "C:\\new\\python.exe\nsecond line is ignored": "C:\\new\\python.exe",
        }
        refused = [None, "", "\n", "python.exe", "py\\python.exe", "\\python.exe", "C:python.exe",
                   "C:\\Tools\\pythonw.exe", "C:\\Tools\\python.exe.bak", "C:\\Tools\\cmd.exe", "C:\\Tools\\python.exe -c x",
                   "C:\\Tools\\python.exe:stream", "C:\\a|b\\python.exe", "https://example.test/python.exe",
                   "C:\\" + "x" * 1100 + "\\python.exe"]
        answers = self.ask(*(("python", text) for text in [*usable, *refused]))
        self.assertEqual(answers[:len(usable)], list(usable.values()))
        self.assertEqual(answers[len(usable):], [None] * len(refused))


def area(left, top, width, height):
    return "%d,%d,%d,%d" % (left, top, width, height)


def numbers(answer):
    return [int(value) for value in answer.split()[:4]]


class WindowPlacement(HostRules):
    """The window is sized in the pixels of the monitor it opens on, so the page gets the layout
    it was designed for at every display scale, and it reopens where it was closed."""

    # Working areas (the taskbar taken off) of common panels, and the scales Windows offers.
    PANELS = {"1366 x 768": (1366, 728), "full HD": (1920, 1040), "QHD": (2560, 1400), "4K": (3840, 2120)}
    SCALES = (96, 120, 144, 168, 192, 240)

    def test_first_window_has_the_designed_layout_at_every_display_scale(self):
        cases = [(name, size, scale) for name, size in self.PANELS.items() for scale in self.SCALES]
        answers = self.ask(*(("initial", area(0, 0, *size), scale) for _, size, scale in cases))
        for (name, (width, height), scale), answer in zip(cases, answers):
            with self.subTest(panel=name, scale="%d%%" % round(scale * 100 / 96)):
                left, top, wide, high = numbers(answer)
                # Never larger than the monitor, and centred in it.
                self.assertTrue(0 <= left and left + wide <= width and 0 <= top and top + high <= height, answer)
                self.assertLessEqual(abs((width - wide) - 2 * left), 1)
                self.assertLessEqual(abs((height - high) - 2 * top), 1)
                # In the page's own units the window is the designed 1250 x 850, or all the monitor has.
                room = (width * 96 / scale, height * 96 / scale)
                self.assertAlmostEqual(wide * 96 / scale, min(1250, room[0]), delta=1)
                self.assertAlmostEqual(high * 96 / scale, min(850, room[1]), delta=1)
                if room[0] > 760:
                    self.assertGreater(wide * 96 / scale, 760, "the page fell into its narrow layout on a monitor with room")
        # The audit's two examples: a full-HD panel at 150% and at 175% opened 1250 x 850 pixels,
        # which the page saw as about 833 and 714 wide. It now sees 1250 and 1097.
        by_case = {(name, scale): numbers(answer) for (name, _, scale), answer in zip(cases, answers)}
        self.assertEqual(by_case[("full HD", 96)], [335, 95, 1250, 850])
        self.assertEqual(by_case[("full HD", 144)], [22, 0, 1875, 1040])
        self.assertEqual(by_case[("full HD", 168)], [0, 0, 1920, 1040])
        # A monitor to the left of, or above, the main one has negative coordinates.
        self.assertEqual(self.ask(("initial", area(-1920, -200, 1920, 1040), 96)), ["-1585 -105 1250 850"])

    def test_smallest_window_is_what_the_layout_supports_at_that_scale(self):
        answers = self.ask(*(("least", area(0, 0, 3840, 2120), scale) for scale in self.SCALES),
                           ("least", area(0, 0, 800, 500), 192), ("least", area(0, 0, 3840, 2120), 0))
        for scale, answer in zip(self.SCALES, answers):
            wide, high = map(int, answer.split())
            self.assertEqual((round(wide * 96 / scale), round(high * 96 / scale)), (640, 480), scale)
        self.assertEqual(answers[-2], "800 500")   # Never more than the monitor has room for.
        self.assertEqual(answers[-1], "640 480")   # An unknown scale counts as 100%.

    def test_window_reopens_where_it_was_closed(self):
        main, left = area(0, 0, 1920, 1040) + "@96", area(-2560, 0, 2560, 1400) + "@144"
        closed = self.ask(("remember", area(200, 100, 1300, 900), 0, 96), ("remember", area(-2000, 50, 1900, 1200), 1, 144))
        self.assertEqual(closed, ["200 100 1300 900 0 96", "-2000 50 1900 1200 1 144"])
        reopened = self.ask(("recall", closed[0], main + ";" + left), ("recall", closed[1], main + ";" + left),
                            ("recall", closed[0] + "\r\n", main))
        self.assertEqual(reopened, ["200 100 1300 900 normal", "-2000 50 1900 1200 maximized", "200 100 1300 900 normal"])

    def test_remembered_place_is_fitted_to_the_monitors_connected_now(self):
        main, second = area(0, 0, 1920, 1040) + "@96", area(1920, 0, 1920, 1040) + "@96"
        cases = {
            # The second monitor it was on has been unplugged: open afresh.
            "monitor gone": ("2100 100 1250 850 0 96", main, "none"),
            "monitor still there": ("2100 100 1250 850 0 96", main + ";" + second, "2100 100 1250 850 normal"),
            # Dragged mostly off the right and bottom edges: brought back whole.
            "mostly off screen": ("1500 700 1250 850 0 96", main, "670 190 1250 850 normal"),
            "off the top left": ("-300 -200 1250 850 0 96", main, "0 0 1250 850 normal"),
            # Only a sliver would show: not a window anyone can find.
            "sliver": ("1870 100 1250 850 0 96", main, "none"),
            "sliver below": ("100 1000 1250 850 0 96", main, "none"),
            "just enough showing": ("1800 100 1250 850 0 96", main, "670 100 1250 850 normal"),
            # The resolution was lowered since: no larger than the monitor.
            "larger than the monitor": ("0 0 2560 1400 1 96", main, "0 0 1920 1040 maximized"),
            # The monitor's scale was raised from 100% to 150%: the window keeps its apparent size.
            "scale raised": ("100 50 1000 600 0 96", area(0, 0, 2560, 1400) + "@144", "100 50 1500 900 normal"),
            "scale raised, no room": ("100 50 1250 850 0 96", area(0, 0, 1920, 1040) + "@144", "45 0 1875 1040 normal"),
            # And lowered from 200% to 100%: smaller, but never below what the layout supports.
            "scale lowered": ("100 50 2500 1700 0 192", main, "100 50 1250 850 normal"),
            "scale lowered to the least": ("100 50 1000 700 0 192", main, "100 50 640 480 normal"),
            # Across two monitors: the one that shows most of it.
            "across two": ("1700 100 1250 850 0 96", main + ";" + second, "1920 100 1250 850 normal"),
            "smaller than the least": ("100 100 300 200 0 96", main, "100 100 640 480 normal"),
        }
        answers = self.ask(*(("recall", remembered, monitors) for remembered, monitors, _ in cases.values()))
        for (label, (_, _, expected)), answer in zip(cases.items(), answers):
            with self.subTest(case=label):
                self.assertEqual(answer, expected)

    def test_unusable_memory_is_ignored(self):
        main = area(0, 0, 1920, 1040) + "@96"
        unusable = [None, "", "\n", "window", "200 100 1300 900", "200 100 1300 900 0", "200 100 1300 900 0 96 7",
                    "200 100 1300 900 2 96", "200 100 1300 900 0 0", "200 100 1300 900 0 95", "200 100 1300 900 0 5000",
                    "200 100 0 900 0 96", "200 100 1300 -900 0 96", "200 100 1300.5 900 0 96", "2e2 100 1300 900 0 96",
                    "200  100 1300 900 0 96", "200,100,1300,900,0,96", "99999999999 100 1300 900 0 96",
                    "200 100 999999 900 0 96", "0x10 100 1300 900 0 96", "{\"left\": 200}"]
        self.assertEqual(self.ask(*(("recall", text, main) for text in unusable)), ["none"] * len(unusable))
        # With no monitor described, nothing can be recalled either.
        self.assertEqual(self.ask(("recall", "200 100 1300 900 0 96", "")), ["none"])


class ClosingTheWindow(HostRules):
    def test_window_gives_its_service_time_to_end_before_it_ends_it(self):
        manager = (DESKTOP / "manage.py").read_text(encoding="utf-8")
        drain = int(re.search(r"^DRAIN_SECONDS = (\d+)$", manager, re.MULTILINE)[1])
        self.assertIn("\nWINDOW_PATIENCE = DRAIN_SECONDS + 5\n", manager)
        serving, starting = map(int, self.ask(("patience", "serving"), ("patience", "starting")))
        # Longer than the service's own limit for running requests, so that ending it from the
        # window stays the last resort; shorter than a reopened window waits for the lock.
        self.assertGreater(serving, drain * 1000 + 2000)
        self.assertLess(serving, (drain + 5) * 1000)
        self.assertEqual(starting, 2000)


HOME = "http://127.0.0.1:8776/"
LOG = r"C:\Users\someone\Documents\Process Collector\.local\desktop\updates.log"


class ManagerLines(HostRules):
    """What the window makes of the lines its local service writes, and what it then shows."""

    def test_only_ready_and_error_lines_are_for_the_window(self):
        kinds = {
            "READY " + HOME: "ready",
            "ERROR Port 8776 is not available: another program may be using it.": "error",
            "ERROR x": "error",
            # A service that answers somewhere else is not this window's service.
            "READY http://127.0.0.1:8777/": "elsewhere",
            "READY " + HOME + " ": "elsewhere",
            "READY " + HOME + "admin": "elsewhere",
            "READY  " + HOME: "elsewhere",
            # Anything else is passed over: a build may print while it is loaded.
            "": "other", "READY": "other", "ERROR": "other", "ready " + HOME: "other", " READY " + HOME: "other",
            "Error: something a build printed": "other", "READY" + HOME: "other", "ERRORS 3": "other",
            "AI Process Collector 0.29.0: " + HOME: "other", "Loading READY " + HOME: "other",
            "NOTICE Running the previous build": "other", "PROBLEM x": "other",
            None: "end",
        }
        self.assertEqual(self.ask(*(("kind", line, HOME) for line in kinds)), list(kinds.values()))

    def test_reason_comes_from_the_managers_own_sentences_only(self):
        reasons = self.ask(
            ("reason", "ERROR Port 8776 is not available: another program may be using it.", HOME),
            ("reason", "ERROR   padded   ", HOME),
            ("reason", "ERROR bell\x07 and \x1b[2J escape", HOME),
            ("reason", "ERROR " + "x" * 2000, HOME),
            ("reason", "READY http://127.0.0.1:8777/", HOME),
            ("reason", None, HOME),
            ("reason", "ERROR  ", HOME))
        self.assertEqual(reasons[:3], ["Port 8776 is not available: another program may be using it.", "padded",
                                       "bell  and  [2J escape"])
        self.assertEqual(reasons[3], "x" * 700)
        self.assertEqual(reasons[4:], ["The local service answered at an unexpected address.", None, None])
        said = {
            "Process Collector desktop: The list of approved builds cannot be read.": "The list of approved builds cannot be read.",
            "Process Collector desktop: The desktop command stopped on an unexpected error (PermissionError).":
                "The desktop command stopped on an unexpected error (PermissionError).",
            # Not the manager's sentence: a traceback, a build's request log, a look-alike.
            "Traceback (most recent call last):": None,
            '  File "C:\\x\\server.py", line 12, in main': None,
            "PermissionError: [WinError 5] Access is denied: 'C:\\\\Users\\\\someone\\\\secret'": None,
            '127.0.0.1 - - [13/Nov/2026 10:00:00] "GET / HTTP/1.1" 200 -': None,
            "process collector desktop: lower case": None,
            " Process Collector desktop: indented": None,
            "Process Collector desktop:": None,
            "Process Collector desktop:  ": None,
            "": None,
            None: None,
        }
        self.assertEqual(self.ask(*(("diagnostic", line) for line in said)), list(said.values()))
        blocked = {
            "PROBLEM The download from GitHub did not complete: this computer may be offline, or the connection stalled.":
                "The download from GitHub did not complete: this computer may be offline, or the connection stalled.",
            "PROBLEM": None, "PROBLEM ": None, "problem x": None, "UPDATE " + "a" * 40: None, "FIRST " + "a" * 40: None,
            "": None, None: None,
        }
        self.assertEqual(self.ask(*(("problem", line) for line in blocked)), list(blocked.values()))

    def test_failure_names_the_reason_and_the_full_path_of_the_log(self):
        port = "Port 8776 is not available: another program may be using it."
        unreadable = "The list of approved builds cannot be read."
        where = "\n\nThe update log names what happened, and to which build:\n" + LOG
        answers = self.ask(("failure", port, unreadable, LOG), ("failure", None, unreadable, LOG),
                           ("failure", port, None, LOG), ("failure", None, None, LOG), ("failure", "  ", "\x07", LOG))
        self.assertEqual(answers[0], port + where)            # The ERROR line first,
        self.assertEqual(answers[1], unreadable + where)      # else the sentence on the error output,
        self.assertEqual(answers[2], port + where)
        self.assertEqual(answers[3], "The local service ended without giving a reason." + where)   # else say so.
        self.assertEqual(answers[4], answers[3])
        # Two different failures no longer read the same.
        self.assertNotEqual(answers[0], answers[1])


class HostSource(unittest.TestCase):
    """Wiring that only a running window would show is read from the source: weaker than a run,
    and said so. Each line here names a call the fixes depend on."""

    @classmethod
    def setUpClass(cls):
        cls.source = (DESKTOP / "NativeHost.cs").read_text(encoding="utf-8")

    def has(self, *fragments):
        for fragment in fragments:
            self.assertTrue(fragment in self.source, "desktop/NativeHost.cs no longer contains: " + fragment)

    def lacks(self, *fragments):
        for fragment in fragments:
            self.assertFalse(fragment in self.source, "desktop/NativeHost.cs still contains: " + fragment)

    def test_source_is_plain_text(self):
        # No invisible characters: a byte-order mark inside the file once slipped into a literal.
        self.lacks(chr(0xFEFF), chr(0x200B), chr(0x202E))

    def test_window_starts_the_interpreter_named_in_its_own_folder(self):
        self.has('HostLogic.ChosenPython(ReadSmallFile("python.txt"))')
        self.assertEqual(self.source.count(r"codex-primary-runtime\dependencies\python\python.exe"), 1,
                         "the Codex runtime is the fallback in one place only")

    def test_window_is_placed_by_the_rules_and_remembers_its_place(self):
        self.lacks("Width = 1250; Height = 850", "new Size(420, 420)", "FormStartPosition.CenterScreen;\n        Controls")
        self.has('HostLogic.Recall(ReadSmallFile("window.txt"), areas, scales, out place, out maximized)',
                 "HostLogic.Initial(areas[under], scales[under])", "MinimumSize = HostLogic.Least(areas[on], scales[on])",
                 "StartPosition = FormStartPosition.Manual", "RememberPlacement();",
                 'Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "window.txt")')
        # The result of asking Windows for per-monitor awareness is checked, with weaker forms to fall back on.
        self.has("if (SetProcessDpiAwarenessContext(new IntPtr(-4))) return;", "if (SetProcessDpiAwareness(2) == 0) return;",
                 "SetProcessDPIAware();")

    def test_closing_waits_for_the_service_off_the_window_thread_and_ends_it_only_then(self):
        self.has("Release(backend, HostLogic.ClosingPatience(serving));",
                 "try { if (!leaving.WaitForExit(patience)) leaving.Kill(); }", "last.IsBackground = false;")
        # The window's own thread no longer waits (a reopened window would find this one still there).
        closed = self.source[self.source.index("FormClosed += delegate"):self.source.index("private void PlaceWindow")]
        self.assertNotIn("WaitForExit", closed)
        self.assertNotIn("Kill()", closed)

    def test_window_reads_the_managers_error_output_and_waits_for_a_protocol_line(self):
        # Both ways the manager is started: the long-running service and the single commands.
        self.assertEqual(self.source.count("RedirectStandardError = true"), 2)
        self.has("backend.BeginErrorReadLine();", "string sentence = HostLogic.Diagnostic(e.Data);",
                 'if (kind != "other") break;',
                 "HostLogic.Failure(HostLogic.Reason(kind, line), Volatile.Read(ref said[0]), log)",
                 'Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "updates.log")',
                 "HostLogic.Problem(offer[0])", "HostLogic.Failure(null, approval.Problem, log)")
        # The one sentence that used to stand for every failure, and the first-line-only test, are gone.
        self.lacks("The local service could not open", 'ready != "READY "', "Check the desktop update log.")


if __name__ == "__main__":
    unittest.main()
