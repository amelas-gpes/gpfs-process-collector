using System;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;

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
        if (n[0] < -1000000 || n[0] > 1000000 || n[1] < -1000000 || n[1] > 1000000 || n[2] < 1 || n[2] > 100000 || n[3] < 1 || n[3] > 100000 ||
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
