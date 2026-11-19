using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;

namespace UniversalDownloader.Avalonia;

public partial class App : Application
{
    public override void Initialize()
    {
        AvaloniaXamlLoader.Load(this);
    }

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            desktop.MainWindow = new MainWindow();
        }

        base.OnFrameworkInitializationCompleted();
    }

    private void TrayIcon_Clicked(object? sender, EventArgs e)
    {
        ShowWindow();
    }

    private void ShowApp_Click(object? sender, EventArgs e)
    {
        ShowWindow();
    }

    private void ExitApp_Click(object? sender, EventArgs e)
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            if (desktop.MainWindow is MainWindow mw)
            {
                mw.ForceExit();
            }
            desktop.Shutdown();
        }
    }

    private void ShowWindow()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop && desktop.MainWindow != null)
        {
            desktop.MainWindow.Show();
            desktop.MainWindow.WindowState = global::Avalonia.Controls.WindowState.Normal;
            desktop.MainWindow.Activate();
        }
    }
}
