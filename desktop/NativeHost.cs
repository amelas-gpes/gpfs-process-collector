using System;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

[assembly: AssemblyTitle("GPFS Process Collector")]
[assembly: AssemblyProduct("GPFS Process Collector")]
[assembly: AssemblyCompany("GP Fund Solutions")]

internal static class Program
{
    internal const string Title = "GPFS Process Collector";
    internal static readonly string Sdk = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
        @".nuget\packages\microsoft.web.webview2\1.0.4258.31");

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool SetProcessDpiAwarenessContext(IntPtr value);

    [DllImport("shcore.dll")]
    private static extern int SetProcessDpiAwareness(int value);

    [DllImport("user32.dll")]
    private static extern bool SetProcessDPIAware();

    [DllImport("user32.dll")]
    private static extern IntPtr MonitorFromPoint(Point point, uint flags);

    [DllImport("shcore.dll")]
    private static extern int GetDpiForMonitor(IntPtr monitor, int kind, out uint horizontal, out uint vertical);

    // Per-monitor (version 2) where Windows has it. If Windows refuses that, the weaker forms are tried in
    // turn instead of running unaware: an unaware window is laid out at 96 dpi and stretched by Windows, and
    // every size below would then be in the wrong units.
    private static void DeclareDpiAwareness()
    {
        try { if (SetProcessDpiAwarenessContext(new IntPtr(-4))) return; }
        catch (EntryPointNotFoundException) { }
        try { if (SetProcessDpiAwareness(2) == 0) return; }
        catch (DllNotFoundException) { }
        catch (EntryPointNotFoundException) { }
        try { SetProcessDPIAware(); }
        catch (EntryPointNotFoundException) { }
    }

    // The scale of one monitor in dots per inch (96 is 100%), in the units this process was granted above.
    internal static int DpiOf(Screen screen, int otherwise)
    {
        try
        {
            uint horizontal, vertical;
            Rectangle whole = screen.Bounds;
            IntPtr monitor = MonitorFromPoint(new Point(whole.Left + whole.Width / 2, whole.Top + whole.Height / 2), 2);
            if (monitor != IntPtr.Zero && GetDpiForMonitor(monitor, 0, out horizontal, out vertical) == 0 && horizontal >= 96)
                return (int)horizontal;
        }
        catch (DllNotFoundException) { }
        catch (EntryPointNotFoundException) { }
        return otherwise;
    }

    [STAThread]
    private static void Main()
    {
        using (var wake = new EventWaitHandle(false, EventResetMode.AutoReset, @"Local\GPFS.ProcessCollector.Activate"))
        {
            bool first;
            using (var instance = new Mutex(true, @"Local\GPFS.ProcessCollector.Desktop", out first))
            {
                if (!first) { wake.Set(); return; }
                AppDomain.CurrentDomain.AssemblyResolve += ResolveWebViewAssembly;
                try
                {
                    foreach (string part in new[] { @"lib\net462\Microsoft.Web.WebView2.Core.dll", @"lib\net462\Microsoft.Web.WebView2.WinForms.dll", @"runtimes\win-x64\native\WebView2Loader.dll" })
                        if (!File.Exists(Path.Combine(Sdk, part))) throw new IOException("Process Collector needs " + Path.Combine(Sdk, part) + ". Restore the WebView2 SDK and run desktop\\install.ps1 again.");
                    DeclareDpiAwareness();
                    Application.EnableVisualStyles();
                    Application.SetCompatibleTextRenderingDefault(false);
                    Run(wake);
                }
                catch (Exception error)
                {
                    MessageBox.Show(error.Message, Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
                }
            }
        }
    }

    private static Assembly ResolveWebViewAssembly(object sender, ResolveEventArgs args)
    {
        var name = new AssemblyName(args.Name).Name;
        if (name != "Microsoft.Web.WebView2.Core" && name != "Microsoft.Web.WebView2.WinForms") return null;
        return Assembly.LoadFrom(Path.Combine(Sdk, "lib", "net462", name + ".dll"));
    }

    // Resolve managed assemblies from the existing user SDK before the JIT loads the form.
    [MethodImpl(MethodImplOptions.NoInlining)]
    private static void Run(EventWaitHandle wake)
    {
        CoreWebView2Environment.SetLoaderDllFolderPath(Path.Combine(Sdk, @"runtimes\win-x64\native"));
        using (var window = new CollectorWindow(wake)) Application.Run(window);
    }
}

internal sealed class CollectorWindow : Form
{
    private static readonly Uri Home = new Uri("http://127.0.0.1:8776/");
    private readonly WebView2 browser = new WebView2 { Dock = DockStyle.Fill };
    private readonly Label message = new Label { Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleCenter,
        ForeColor = Color.FromArgb(68, 36, 65), Font = new Font("Segoe UI", 12), Text = "Opening Process Collector…" };
    private readonly System.Windows.Forms.Timer activation = new System.Windows.Forms.Timer { Interval = 200 };
    private Process backend;
    private bool loaded, serving, checkingClose, acceptedClose, closing;

    internal CollectorWindow(EventWaitHandle wake)
    {
        Text = Program.Title;
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        AutoScaleMode = AutoScaleMode.Dpi;
        PlaceWindow();
        Controls.Add(browser); Controls.Add(message);
        activation.Tick += delegate {
            if (!wake.WaitOne(0)) return;
            if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
            Activate();
        };
        activation.Start();
        Shown += async delegate { await StartCollector(); };
        FormClosing += ConfirmClose;
        FormClosed += delegate {
            closing = true;
            RememberPlacement();
            activation.Dispose();
            if (backend != null) {
                try { backend.StandardInput.Close(); } catch (IOException) { }
                Release(backend, HostLogic.ClosingPatience(serving));
            }
        };
    }

    // Sizes are in the pixels of the monitor the window opens on, so the page gets the same layout at every
    // display scale: where the window was when it last closed if that place is still on a connected monitor,
    // else the design size at the scale of the monitor under the pointer, never larger than its working area.
    private void PlaceWindow()
    {
        Screen[] screens = Screen.AllScreens;
        if (screens.Length == 0)
        {
            Width = HostLogic.DesignWidth; Height = HostLogic.DesignHeight;
            StartPosition = FormStartPosition.CenterScreen;
            return;
        }
        var areas = new Rectangle[screens.Length];
        var scales = new int[screens.Length];
        for (int i = 0; i < screens.Length; i++)
        {
            areas[i] = screens[i].WorkingArea;
            scales[i] = Program.DpiOf(screens[i], DeviceDpi);
        }
        Rectangle place;
        bool maximized;
        if (!HostLogic.Recall(ReadSmallFile("window.txt"), areas, scales, out place, out maximized))
        {
            int under = Math.Max(0, Array.IndexOf(screens, Screen.FromPoint(Cursor.Position)));
            place = HostLogic.Initial(areas[under], scales[under]);
        }
        int on = Math.Max(0, Array.IndexOf(screens, Screen.FromRectangle(place)));
        MinimumSize = HostLogic.Least(areas[on], scales[on]);
        StartPosition = FormStartPosition.Manual;
        Bounds = place;
        if (maximized) WindowState = FormWindowState.Maximized;
    }

    private void RememberPlacement()
    {
        try
        {
            Rectangle place = WindowState == FormWindowState.Normal ? Bounds : RestoreBounds;
            if (place.Width <= 0 || place.Height <= 0) return;
            File.WriteAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "window.txt"),
                HostLogic.Remember(place, WindowState == FormWindowState.Maximized, Program.DpiOf(Screen.FromRectangle(place), DeviceDpi)));
        }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
        catch (System.Security.SecurityException) { }
    }

    // The local service ends by itself once its input closes: at once when nothing is running, and within
    // a few seconds when a request is (desktop/manage.py bounds that wait). It is given that time and is
    // ended here only as the last resort: one that is still starting never reads its input, and an older
    // manager waits for a provider call for minutes. Left alone, either keeps the window's lock and blocks
    // the next launch. The wait is on a thread of its own so that this window closes, and a reopened one
    // can start, without waiting for it; a foreground thread, so that this process lasts until it is done.
    private static void Release(Process leaving, int patience)
    {
        var last = new Thread(delegate() {
            try { if (!leaving.WaitForExit(patience)) leaving.Kill(); }
            catch (InvalidOperationException) { }
            catch (System.ComponentModel.Win32Exception) { }
            finally { leaving.Dispose(); }
        });
        last.IsBackground = false;
        last.Start();
    }

    private async Task StartCollector()
    {
        try
        {
            string project = Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "..", ".."));
            string python = Python();
            string log = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "updates.log");
            // A downloaded build never runs on its own. "pending" downloads without running anything
            // and prints the build that is waiting; only a Yes here lets "serve" switch to it.
            string[] offer = ((await RunManager(python, project, "pending")).Output ?? "").Split(new[] { '\n' }, 2);
            if (closing) return;
            // Nothing to open and nothing to offer, and the manager says why (a first run offline, or without Git).
            string blocked = HostLogic.Problem(offer[0]);
            if (blocked != null)
            {
                message.Text = "Process Collector could not start.\n\n" + HostLogic.Failure(blocked, null, log);
                return;
            }
            Match waiting = Regex.Match(offer[0].Trim(), @"\A(UPDATE|FIRST) ([0-9a-f]{40})\z");
            if (waiting.Success && offer.Length == 2)
            {
                if (MessageBox.Show(this, offer[1].Trim(), Program.Title, MessageBoxButtons.YesNo,
                        MessageBoxIcon.Question, MessageBoxDefaultButton.Button2) == DialogResult.Yes)
                {
                    Answer approval = await RunManager(python, project, "approve " + waiting.Groups[2].Value);
                    if (approval.Output == null)
                        MessageBox.Show(this, "The build could not be switched.\n\n" + HostLogic.Failure(null, approval.Problem, log),
                            Program.Title, MessageBoxButtons.OK, MessageBoxIcon.Warning);
                }
                else if (waiting.Groups[1].Value == "FIRST")
                {
                    message.Text = "No build has been approved to run.\n\nReopen Process Collector to review the downloaded build.";
                    return;
                }
                if (closing) return;
            }
            var start = new ProcessStartInfo(python, "-I -B desktop/manage.py serve --port 8776") {
                WorkingDirectory = project, UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardOutput = true, RedirectStandardInput = true, RedirectStandardError = true
            };
            backend = Process.Start(start);
            // The manager writes its reason for a failure to its error output, which a window program does not
            // otherwise have. It is read for as long as the service runs, so the service can never block on a
            // full pipe, and only the manager's own last sentence is kept.
            var said = new string[1];
            backend.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e) {
                string sentence = HostLogic.Diagnostic(e.Data);
                if (sentence != null) Volatile.Write(ref said[0], sentence);
            };
            backend.BeginErrorReadLine();
            // Only a READY or ERROR line is for the window. A build may print other lines while it loads.
            string line, kind = "end";
            while ((line = await backend.StandardOutput.ReadLineAsync()) != null)
            {
                kind = HostLogic.Kind(line, Home.AbsoluteUri);
                if (kind != "other") break;
            }
            if (closing) return;
            if (kind != "ready")
            {
                // The reason is usually the last thing the manager writes: give it a moment to end.
                Process failed = backend;
                await Task.Run(delegate() {
                    try { failed.WaitForExit(3000); }
                    catch (InvalidOperationException) { }
                    catch (System.ComponentModel.Win32Exception) { }
                });
                if (closing) return;
                throw new IOException(HostLogic.Failure(HostLogic.Reason(kind, line), Volatile.Read(ref said[0]), log));
            }
            serving = true;
            backend.SynchronizingObject = this;
            backend.Exited += delegate {
                if (IsDisposed || closing) return;
                serving = false;
                message.Text = "The local service stopped. Close and reopen Process Collector to restart it.";
                message.Show(); message.BringToFront();
            };
            backend.EnableRaisingEvents = true;
            // One more line may follow READY: an older build is running because the newest could not start.
            ShowNotice(backend.StandardOutput.ReadLineAsync());

            var environment = await CoreWebView2Environment.CreateAsync(null, Path.Combine(project, ".local", "desktop", "browser"));
            if (closing) return;
            await browser.EnsureCoreWebView2Async(environment);
            if (closing) return;
            var core = browser.CoreWebView2;
            core.ProcessFailed += delegate {
                if (closing) return;
                message.Text = "The browser stopped. Close and reopen Process Collector to recover your saved work.";
                message.Show(); message.BringToFront();
            };
            core.Settings.IsStatusBarEnabled = false;
            core.Settings.AreHostObjectsAllowed = false;
            core.Settings.IsGeneralAutofillEnabled = false;
            core.Settings.IsPasswordAutosaveEnabled = false;
            core.PermissionRequested += delegate(object sender, CoreWebView2PermissionRequestedEventArgs e) {
                if (!IsLocal(e.Uri)) e.State = CoreWebView2PermissionState.Deny;
            };
            core.NavigationStarting += delegate(object sender, CoreWebView2NavigationStartingEventArgs e) {
                if (IsLocal(e.Uri)) return;
                e.Cancel = true;
                if (e.IsUserInitiated) OpenExternal(e.Uri);
            };
            core.NewWindowRequested += delegate(object sender, CoreWebView2NewWindowRequestedEventArgs e) {
                e.Handled = true;
                if (!e.IsUserInitiated) return;
                if (IsLocal(e.Uri)) core.Navigate(e.Uri);
                else OpenExternal(e.Uri);
            };
            // Keep browser/OS permission prompts for microphone capture and the download UI for exported files.
            core.NavigationCompleted += delegate(object sender, CoreWebView2NavigationCompletedEventArgs e) {
                if (e.IsSuccess) { loaded = true; message.Hide(); browser.Focus(); }
                else if (!loaded) message.Text = "Process Collector could not load. Close and reopen the app to retry.";
            };
            core.Navigate(Home.AbsoluteUri);
        }
        catch (Exception error)
        {
            if (!closing) message.Text = "Process Collector could not start.\n\n" + error.Message;
        }
    }

    // The interpreter chosen when the app was installed: desktop\register-updates.ps1 writes python.txt beside
    // this executable (VOICE_INTERVIEWER_PYTHON at that time, else the Codex runtime) and gives the update task
    // the same one. Without that file, or if it no longer names a file, the Codex runtime as before.
    private static string Python()
    {
        string usual = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            @".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe");
        string chosen = HostLogic.ChosenPython(ReadSmallFile("python.txt"));
        string python = chosen != null && File.Exists(chosen) ? chosen : usual;
        if (!File.Exists(python))
            throw new IOException("Python was not found at " + python + ".\n\nRun desktop\\install.ps1 again to choose the Python " +
                "the app uses (it reads VOICE_INTERVIEWER_PYTHON), or restore that file.");
        string windowless = Path.Combine(Path.GetDirectoryName(python), "pythonw.exe");
        if (chosen != null && !File.Exists(windowless))
            MessageBox.Show("Scheduled updates need " + windowless + ". Restore it or run desktop\\install.ps1 with a compatible interpreter. The window can still open its approved build.", Program.Title, MessageBoxButtons.OK, MessageBoxIcon.Warning);
        return python;
    }

    // A small file of the window's own, beside its executable (.local\desktop). Null if there is none to read.
    private static string ReadSmallFile(string name)
    {
        try
        {
            var file = new FileInfo(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, name));
            return file.Exists && file.Length <= 4096 ? File.ReadAllText(file.FullName) : null;
        }
        catch (IOException) { return null; }
        catch (UnauthorizedAccessException) { return null; }
        catch (System.Security.SecurityException) { return null; }
    }

    // Not awaited by the caller: an older manager prints nothing after READY, and the page must still open.
    private async void ShowNotice(Task<string> line)
    {
        try
        {
            Match notice = Regex.Match(await line ?? "", @"\A(NOTICE|NOTICE-NEW) (.{1,300})\z");
            if (!notice.Success || closing) return;
            // The title keeps saying it for as long as this window runs the older build.
            Text = Program.Title + " - " + notice.Groups[2].Value;
            if (notice.Groups[1].Value == "NOTICE-NEW")
                MessageBox.Show(this, notice.Groups[2].Value + "\n\nThe build that failed is not tried again by itself. " +
                    "Details are in .local\\desktop\\updates.log; docs\\DESKTOP.md explains how to choose a build.",
                    Program.Title, MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
        catch (IOException) { }
        catch (ObjectDisposedException) { }
        catch (InvalidOperationException) { }
    }

    // What one desktop/manage.py command answered: its output (null if it failed) and, if it gave one, its reason.
    private sealed class Answer
    {
        internal string Output, Problem;
    }

    // Runs one desktop/manage.py command to completion.
    private static async Task<Answer> RunManager(string python, string project, string command)
    {
        var start = new ProcessStartInfo(python, "-I -B desktop/manage.py " + command) {
            WorkingDirectory = project, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, StandardOutputEncoding = Encoding.UTF8,
            RedirectStandardError = true, StandardErrorEncoding = Encoding.UTF8
        };
        using (var manager = Process.Start(start))
        {
            // Both are read to their end together: reading one alone can leave the command blocked on the other.
            Task<string> output = manager.StandardOutput.ReadToEndAsync(), errors = manager.StandardError.ReadToEndAsync();
            await Task.WhenAll(output, errors);
            manager.WaitForExit();
            string problem = null;
            foreach (string line in errors.Result.Split('\n'))
                problem = HostLogic.Diagnostic(line.TrimEnd('\r')) ?? problem;
            return new Answer { Output = manager.ExitCode == 0 ? output.Result : null, Problem = problem };
        }
    }

    private static bool IsLocal(string value)
    {
        Uri target;
        return Uri.TryCreate(value, UriKind.Absolute, out target) && target.Scheme == Home.Scheme &&
            target.Host == Home.Host && target.Port == Home.Port && target.UserInfo.Length == 0;
    }

    private static void OpenExternal(string value)
    {
        Uri target;
        if (Uri.TryCreate(value, UriKind.Absolute, out target) &&
            (target.Scheme == Uri.UriSchemeHttps || target.Scheme == Uri.UriSchemeHttp))
            Process.Start(new ProcessStartInfo(target.AbsoluteUri) { UseShellExecute = true });
    }

    private async void ConfirmClose(object sender, FormClosingEventArgs e)
    {
        if (!loaded || acceptedClose || e.CloseReason != CloseReason.UserClosing) return;
        e.Cancel = true;
        if (checkingClose) return;
        checkingClose = true;
        bool clean = false;
        try
        {
            // Reuse the interview page's pending-edit / recording checks, including changes in future releases.
            var check = browser.CoreWebView2.ExecuteScriptAsync(
                "window.dispatchEvent(new Event('beforeunload', {cancelable:true}))");
            clean = await Task.WhenAny(check, Task.Delay(1500)) == check && await check == "true";
        }
        catch (InvalidOperationException) { }
        catch (COMException) { }
        checkingClose = false;
        if (clean || MessageBox.Show(this, "Work or a recording may still be in progress. Close Process Collector?",
                Program.Title, MessageBoxButtons.YesNo, MessageBoxIcon.Question, MessageBoxDefaultButton.Button2) == DialogResult.Yes)
        {
            acceptedClose = true;
            BeginInvoke(new Action(Close));
        }
    }
}

// What the window decides without needing a window. Kept apart from the form so that these
// rules can be exercised by themselves (tests/desktop_host_checks.cs); nothing here starts,
// shows or changes anything.
internal static class HostLogic
{
    // The window the page was designed for, and the smallest one its layout supports, both at 100% scale.
    internal const int DesignWidth = 1250, DesignHeight = 850, LeastWidth = 640, LeastHeight = 480;

    // A length given at 100% scale (96 dots per inch), in the pixels of a monitor at `scale`.
    internal static int Scaled(int length, int scale)
    {
        return (int)Math.Round(length * (double)Math.Max(scale, 96) / 96);
    }

    // The smallest size the window may be given on a monitor: the least the layout supports at that
    // monitor's scale, but never more than the monitor has room for.
    internal static Size Least(Rectangle area, int scale)
    {
        return new Size(Math.Min(Scaled(LeastWidth, scale), area.Width), Math.Min(Scaled(LeastHeight, scale), area.Height));
    }

    // Where the window opens when nothing is remembered: the design size at the monitor's scale, no larger
    // than the monitor's working area, centred in it.
    internal static Rectangle Initial(Rectangle area, int scale)
    {
        int width = Math.Min(Scaled(DesignWidth, scale), area.Width), height = Math.Min(Scaled(DesignHeight, scale), area.Height);
        return new Rectangle(area.Left + (area.Width - width) / 2, area.Top + (area.Height - height) / 2, width, height);
    }

    // The window's place when it closes, as kept in window.txt: left top width height maximized scale.
    internal static string Remember(Rectangle place, bool maximized, int scale)
    {
        return string.Format(CultureInfo.InvariantCulture, "{0} {1} {2} {3} {4} {5}",
            place.Left, place.Top, place.Width, place.Height, maximized ? 1 : 0, scale);
    }

    // The remembered place, fitted to the monitors connected now. False when nothing usable is remembered
    // or the place is no longer on any monitor (it was unplugged, or the arrangement changed): the caller
    // then opens at Initial. `areas` and `scales` describe the monitors, in the same order.
    internal static bool Recall(string remembered, Rectangle[] areas, int[] scales, out Rectangle place, out bool maximized)
    {
        place = Rectangle.Empty;
        maximized = false;
        string[] parts = (remembered ?? "").Trim().Split(' ');
        var n = new int[6];
        if (parts.Length != 6) return false;
        for (int i = 0; i < 6; i++)
            if (!int.TryParse(parts[i], NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out n[i])) return false;
        if (Math.Abs(n[0]) > 1000000 || Math.Abs(n[1]) > 1000000 || n[2] < 1 || n[2] > 100000 || n[3] < 1 || n[3] > 100000 ||
            n[4] < 0 || n[4] > 1 || n[5] < 96 || n[5] > 960) return false;
        var was = new Rectangle(n[0], n[1], n[2], n[3]);
        // The monitor that shows most of it. A sliver in a corner is not a window anyone can find.
        int on = -1;
        long most = 0;
        for (int i = 0; i < areas.Length && i < scales.Length; i++)
        {
            Rectangle shared = Rectangle.Intersect(was, areas[i]);
            long shown = (long)shared.Width * shared.Height;
            if (shared.Width >= Scaled(120, scales[i]) && shared.Height >= Scaled(80, scales[i]) && shown > most) { most = shown; on = i; }
        }
        if (on < 0) return false;
        // That monitor's scale may have changed since: keep the size the window appeared to have.
        Rectangle area = areas[on];
        Size least = Least(area, scales[on]);
        int width = Math.Min(Math.Max((int)Math.Round(was.Width * (double)scales[on] / n[5]), least.Width), area.Width);
        int height = Math.Min(Math.Max((int)Math.Round(was.Height * (double)scales[on] / n[5]), least.Height), area.Height);
        place = new Rectangle(Math.Min(Math.Max(was.Left, area.Left), area.Right - width),
            Math.Min(Math.Max(was.Top, area.Top), area.Bottom - height), width, height);
        maximized = n[4] == 1;
        return true;
    }

    // What a line from "manage.py serve" means to the window. "ready": the service answers at `home`.
    // "error": the manager's reason follows the word. "elsewhere": a service answered, but not at the
    // window's address. "end": there are no more lines. "other": not for the window (a build may print
    // while it loads), so the window reads on.
    internal static string Kind(string line, string home)
    {
        if (line == null) return "end";
        if (line == "READY " + home) return "ready";
        if (line.StartsWith("READY ", StringComparison.Ordinal)) return "elsewhere";
        if (line.StartsWith("ERROR ", StringComparison.Ordinal)) return "error";
        return "other";
    }

    // The reason carried by the line that ended the wait for READY, or null if it carried none.
    internal static string Reason(string kind, string line)
    {
        if (kind == "error") return Plain(line.Substring(6), 700);
        return kind == "elsewhere" ? "The local service answered at an unexpected address." : null;
    }

    // The sentence the manager wrote for a person on its error output ("Process Collector desktop: ..."),
    // or null for any other line: tracebacks and a build's own logging are not shown.
    internal static string Diagnostic(string line)
    {
        const string prefix = "Process Collector desktop: ";
        return line != null && line.StartsWith(prefix, StringComparison.Ordinal) ? Plain(line.Substring(prefix.Length), 700) : null;
    }

    // "PROBLEM <sentence>" from "manage.py pending": nothing can be opened or offered, and why. Else null.
    internal static string Problem(string line)
    {
        return line != null && line.StartsWith("PROBLEM ", StringComparison.Ordinal) ? Plain(line.Substring(8), 700) : null;
    }

    // What the window shows when the service did not start: the manager's own reason (its ERROR line first,
    // else its last sentence on the error output), and where the log is, by its full path.
    internal static string Failure(string reason, string diagnostic, string log)
    {
        return (Plain(reason, 700) ?? Plain(diagnostic, 700) ?? "The local service ended without giving a reason.") +
            "\n\nThe update log names what happened, and to which build:\n" + log;
    }

    // Printable text of limited length, or null if nothing is left.
    internal static string Plain(string text, int limit)
    {
        if (text == null) return null;
        var plain = new StringBuilder();
        foreach (char c in text)
            if (plain.Length < limit) plain.Append(char.IsControl(c) || char.GetUnicodeCategory(c) == UnicodeCategory.Format ? ' ' : c);
        string result = plain.ToString().Trim();
        return result.Length == 0 ? null : result;
    }

    // How long, in milliseconds, the local service is given to end by itself after the window closes, before
    // the window ends it. A service that is serving bounds its own wait for running requests at 5 seconds
    // (DRAIN_SECONDS in desktop/manage.py) and needs a moment more to close its stores; one that never
    // became ready is not waiting for anything worth keeping.
    internal static int ClosingPatience(bool serving)
    {
        return serving ? 9000 : 2000;
    }

    // The interpreter named on the first line of python.txt: the full path of a python.exe, or null.
    internal static string ChosenPython(string text)
    {
        if (text == null) return null;
        string line = text.Split('\n')[0].Trim().Trim((char)0xFEFF, '"').Trim();
        if (line.Length > 1024 || line.IndexOfAny(Path.GetInvalidPathChars()) >= 0) return null;
        return Regex.IsMatch(line, @"\A(?:[A-Za-z]:\\|\\\\)[^:*?<>|]*\\python\.exe\z", RegexOptions.IgnoreCase) ? line : null;
    }
}
