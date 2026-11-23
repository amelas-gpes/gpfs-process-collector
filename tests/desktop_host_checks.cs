// Exercises the production decision rules in desktop/HostLogic.cs without starting the window.
// One request per input line, fields separated by tabs; one answer line per request.
using System;
using System.Drawing;
using System.IO;
using System.Text;

internal static class HostChecks
{
    private const string Nothing = "<null>";

    // Line ends inside a field travel as <LF> and <CR>; a missing value as <null>.
    private static string Field(string value) { return value == Nothing ? null : value.Replace("<LF>", "\n").Replace("<CR>", "\r"); }

    private static string Shown(string value) { return value == null ? Nothing : value.Replace("\r", "<CR>").Replace("\n", "<LF>"); }

    // "left,top,width,height"
    private static Rectangle Area(string value)
    {
        string[] n = value.Split(',');
        return new Rectangle(int.Parse(n[0]), int.Parse(n[1]), int.Parse(n[2]), int.Parse(n[3]));
    }

    private static string Shown(Rectangle value)
    {
        return value.Left + " " + value.Top + " " + value.Width + " " + value.Height;
    }

    // Monitors as "left,top,width,height@scale;..." (working areas).
    private static string Recall(string remembered, string monitors)
    {
        string[] each = monitors.Length == 0 ? new string[0] : monitors.Split(';');
        var areas = new Rectangle[each.Length];
        var scales = new int[each.Length];
        for (int i = 0; i < each.Length; i++)
        {
            areas[i] = Area(each[i].Split('@')[0]);
            scales[i] = int.Parse(each[i].Split('@')[1]);
        }
        Rectangle place;
        bool maximized;
        return HostLogic.Recall(remembered, areas, scales, out place, out maximized)
            ? Shown(place) + (maximized ? " maximized" : " normal") : "none";
    }

    private static int Main()
    {
        var input = new StreamReader(Console.OpenStandardInput(), new UTF8Encoding(false));
        var output = new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false));
        string line;
        while ((line = input.ReadLine()) != null)
        {
            string[] a = line.Split('\t');
            string answer;
            switch (a[0])
            {
                case "python": answer = Shown(HostLogic.ChosenPython(Field(a[1]))); break;
                case "initial": answer = Shown(HostLogic.Initial(Area(a[1]), int.Parse(a[2]))); break;
                case "least": { Size least = HostLogic.Least(Area(a[1]), int.Parse(a[2])); answer = least.Width + " " + least.Height; break; }
                case "remember": answer = HostLogic.Remember(Area(a[1]), a[2] == "1", int.Parse(a[3])); break;
                case "recall": answer = Recall(Field(a[1]), a[2]); break;
                case "patience": answer = HostLogic.ClosingPatience(a[1] == "serving").ToString(); break;
                case "kind": answer = HostLogic.Kind(Field(a[1]), a[2]); break;
                case "reason": answer = Shown(HostLogic.Reason(HostLogic.Kind(Field(a[1]), a[2]), Field(a[1]))); break;
                case "diagnostic": answer = Shown(HostLogic.Diagnostic(Field(a[1]))); break;
                case "problem": answer = Shown(HostLogic.Problem(Field(a[1]))); break;
                case "failure": answer = Shown(HostLogic.Failure(Field(a[1]), Field(a[2]), a[3])); break;
                default: answer = "unknown request"; break;
            }
            output.WriteLine(answer);
        }
        output.Flush();
        return 0;
    }
}
