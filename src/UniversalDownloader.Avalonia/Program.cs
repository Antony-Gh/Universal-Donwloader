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

    public static string NormalizeArgumentUrl(string raw)
    {
        if (string.IsNullOrWhiteSpace(raw)) return string.Empty;
        var trimmed = raw.Trim();
        if (trimmed.StartsWith("udloader://", StringComparison.OrdinalIgnoreCase))
        {
            trimmed = trimmed.Substring(11).TrimStart('/');
            try { trimmed = Uri.UnescapeDataString(trimmed); } catch { }
        }
        else if (trimmed.StartsWith("udloader:", StringComparison.OrdinalIgnoreCase))
        {
            trimmed = trimmed.Substring(9).TrimStart('/');
            try { trimmed = Uri.UnescapeDataString(trimmed); } catch { }
        }
        else if (trimmed.StartsWith("downloader://", StringComparison.OrdinalIgnoreCase))
        {
            trimmed = trimmed.Substring(13).TrimStart('/');
            try { trimmed = Uri.UnescapeDataString(trimmed); } catch { }
        }
        else if (trimmed.StartsWith("downloader:", StringComparison.OrdinalIgnoreCase))
        {
            trimmed = trimmed.Substring(11).TrimStart('/');
            try { trimmed = Uri.UnescapeDataString(trimmed); } catch { }
        }
        return trimmed;
    }

    private static bool TryForwardToExistingInstance(string[] args)
    {
        try
        {
            using var client = new NamedPipeClientStream(".", "UniversalDownloader_IPC", PipeDirection.Out);
            client.Connect(250);
            using var writer = new StreamWriter(client, System.Text.Encoding.UTF8);

            string payload;
            if (args != null && args.Length > 0)
            {
                var combined = string.Join(" ", args).Trim();
                if (combined.Equals("--hud", StringComparison.OrdinalIgnoreCase) || combined.Equals("/hud", StringComparison.OrdinalIgnoreCase))
                {
                    payload = "HUD";
                }
                else
                {
                    var normalized = NormalizeArgumentUrl(combined);
                    payload = string.IsNullOrWhiteSpace(normalized) || normalized.Equals("OPEN", StringComparison.OrdinalIgnoreCase)
                        ? "OPEN"
                        : $"URL {normalized}";
                }
            }
            else
            {
                payload = "OPEN";
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
