using System;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
using Avalonia.Platform;

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
            desktop.ShutdownMode = ShutdownMode.OnExplicitShutdown;
            desktop.MainWindow = new MainWindow();
            EnsureTrayIconInitialized();
        }

        base.OnFrameworkInitializationCompleted();
    }

    private void EnsureTrayIconInitialized()
    {
        try
        {
            var icons = TrayIcon.GetIcons(this);
            if (icons == null || icons.Count == 0)
            {
                WindowIcon? winIcon = null;
                try
                {
                    var iconUri = new Uri("avares://UniversalDownloader/Assets/app-icon.ico");
                    winIcon = new WindowIcon(AssetLoader.Open(iconUri));
                }
                catch { }

                var tray = new TrayIcon
                {
                    ToolTipText = "Universal Media Downloader",
                    IsVisible = true
                };
                if (winIcon != null) tray.Icon = winIcon;
                tray.Clicked += TrayIcon_Clicked;

                var menu = new NativeMenu();
                var openItem = new NativeMenuItem { Header = "Open Universal Downloader" };
                openItem.Click += ShowApp_Click;
                var exitItem = new NativeMenuItem { Header = "Exit" };
                exitItem.Click += ExitApp_Click;
                menu.Add(openItem);
                menu.Add(new NativeMenuItemSeparator());
                menu.Add(exitItem);
                tray.Menu = menu;

                TrayIcon.SetIcons(this, new TrayIcons { tray });
            }
            else
            {
                foreach (var icon in icons)
                {
                    icon.IsVisible = true;
                }
            }
        }
        catch { }
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
                mw.Close();
            }
            desktop.Shutdown();
        }
    }

    public void ShowWindow()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop && desktop.MainWindow != null)
        {
            if (desktop.MainWindow is MainWindow mw)
            {
                mw.RestoreAndActivateWindow();
            }
            else
            {
                desktop.MainWindow.Show();
                desktop.MainWindow.WindowState = WindowState.Normal;
                desktop.MainWindow.Activate();
            }
        }
    }
}
