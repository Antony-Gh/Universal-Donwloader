using Avalonia;
using System;
using System.Threading.Tasks;

namespace UniversalDownloader.Avalonia;

sealed class Program
{
    [STAThread]
    public static void Main(string[] args)
    {
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

    public static AppBuilder BuildAvaloniaApp()
        => AppBuilder.Configure<App>()
            .UsePlatformDetect()
            .WithInterFont()
            .LogToTrace();
}
