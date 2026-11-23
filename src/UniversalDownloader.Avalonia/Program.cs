using Avalonia;
using System;
using System.IO;
using System.IO.Pipes;
using System.Threading.Tasks;

namespace UniversalDownloader.Avalonia;

sealed class Program
{
    [STAThread]
    public static void Main(string[] args)
    {
        // If an instance is already running (e.g. in tray), forward command and exit immediately
        if (TryForwardToExistingInstance(args))
        {
            return;
        }

        AppDomain.CurrentDomain.UnhandledException += (s, e) =>
        {
            if (e.ExceptionObject is Exception ex)
            {
                Core.CrashReporter.RecordCrash(ex, "Desktop");
            }
        };

        TaskScheduler.UnobservedTaskException += (s, e) =>
        {
            Core.CrashReporter.RecordCrash(e.Exception, "Desktop");
        };

        BuildAvaloniaApp()
            .StartWithClassicDesktopLifetime(args);
    }

    private static bool TryForwardToExistingInstance(string[] args)
    {
        try
        {
            using var client = new NamedPipeClientStream(".", "UniversalDownloader_IPC", PipeDirection.Out);
            client.Connect(250);
            using var writer = new StreamWriter(client, System.Text.Encoding.UTF8);
            var payload = args != null && args.Length > 0 ? string.Join(" ", args) : "OPEN";
            if (!payload.StartsWith("URL ", StringComparison.OrdinalIgnoreCase) && !payload.Equals("OPEN", StringComparison.OrdinalIgnoreCase))
            {
                payload = $"URL {payload}";
            }
            writer.WriteLine(payload);
            writer.Flush();
            return true;
        }
        catch
        {
            return false;
        }
    }

    public static AppBuilder BuildAvaloniaApp()
        => AppBuilder.Configure<App>()
            .UsePlatformDetect()
            .WithInterFont()
            .LogToTrace();
}
