using Avalonia.Controls;
using Avalonia.Interactivity;
using System;
using UniversalDownloader.Core;

namespace UniversalDownloader.Avalonia;

public partial class BrowserLoginWindow : Window
{
    private readonly BrowserLoginSession _session = new();

    public string? SavedCookiesPath { get; private set; }
    public int SavedCookieCount { get; private set; }
    public string? SyncedDomain { get; private set; }

    public BrowserLoginWindow()
    {
        InitializeComponent();
        var detected = BrowserLoginSession.FindInstalledChromiumBrowser();
        var hasSaved = BrowserLoginSession.HasSavedLoginProfile();
        if (detected != null)
        {
            BrowserDetectedText.Text = $"{detected.Name} (ready)";
            if (hasSaved)
            {
                SavedProfileBadge.IsVisible = true;
                QuickResyncButton.IsVisible = true;
                StatusText.Text = "Saved login profile detected — click 'Quick Re-Sync (Saved Login)' to refresh cookies instantly without signing in again.";
            }
        }
        else
        {
            BrowserDetectedText.Text = "No Chrome / Edge / Brave detected";
            LaunchBrowserButton.IsEnabled = false;
            QuickResyncButton.IsVisible = false;
            StatusText.Text = "Install Google Chrome, Microsoft Edge, or Brave to use Web Login, or use Paste Cookies instead.";
        }
    }

    public BrowserLoginWindow(string? initialUrlOrDomain, string? languageCode = null) : this()
    {
        if (languageCode == "ar")
        {
            FlowDirection = global::Avalonia.Media.FlowDirection.RightToLeft;
        }
        if (!string.IsNullOrWhiteSpace(initialUrlOrDomain))
        {
            var lowered = initialUrlOrDomain.ToLowerInvariant();
            if (lowered.Contains("facebook") || lowered.Contains("fb.watch")) SiteComboBox.SelectedIndex = 0;
            else if (lowered.Contains("instagram")) SiteComboBox.SelectedIndex = 1;
            else if (lowered.Contains("youtube") || lowered.Contains("youtu.be")) SiteComboBox.SelectedIndex = 2;
            else if (lowered.Contains("tiktok")) SiteComboBox.SelectedIndex = 3;
            else if (lowered.Contains("x.com") || lowered.Contains("twitter")) SiteComboBox.SelectedIndex = 4;
            else if (lowered.Contains("reddit")) SiteComboBox.SelectedIndex = 5;
        }
    }

    private void SiteComboBox_SelectionChanged(object? sender, SelectionChangedEventArgs e)
    {
        if (CustomUrlBox != null)
        {
            CustomUrlBox.IsVisible = SiteComboBox.SelectedIndex == 6;
        }
    }

    private (string LoginUrl, string DomainFilter) GetSelectedSite()
    {
        return SiteComboBox.SelectedIndex switch
        {
            0 => ("https://www.facebook.com/", "facebook.com"),
            1 => ("https://www.instagram.com/", "instagram.com"),
            2 => ("https://www.youtube.com/", "youtube.com"),
            3 => ("https://www.tiktok.com/", "tiktok.com"),
            4 => ("https://x.com/", "x.com"),
            5 => ("https://www.reddit.com/", "reddit.com"),
            _ => ParseCustomSite(CustomUrlBox.Text?.Trim() ?? string.Empty),
        };
    }

    private static (string LoginUrl, string DomainFilter) ParseCustomSite(string raw)
    {
        if (string.IsNullOrWhiteSpace(raw)) return (string.Empty, string.Empty);
        var url = raw.Contains("://") ? raw : $"https://{raw}";
        var host = Uri.TryCreate(url, UriKind.Absolute, out var uri) ? uri.Host : raw;
        return (url, host);
    }

    private async void QuickResyncButton_Click(object? sender, RoutedEventArgs e)
    {
        var (_, domain) = GetSelectedSite();
        if (string.IsNullOrWhiteSpace(domain))
        {
            StatusText.Text = "Please choose a platform or enter a valid URL first.";
            return;
        }

        QuickResyncButton.IsEnabled = false;
        LaunchBrowserButton.IsEnabled = false;
        SyncCookiesButton.IsEnabled = false;
        StatusText.Text = $"Silently refreshing saved cookies for {domain}...";

        try
        {
            var destPath = NetscapeCookieHelper.GetDefaultManagedCookiesPath();
            var count = await _session.QuickResyncSavedSessionAsync(destPath, domain);
            SavedCookiesPath = destPath;
            SavedCookieCount = count;
            SyncedDomain = domain;
            Close(true);
        }
        catch (Exception ex)
        {
            QuickResyncButton.IsEnabled = true;
            LaunchBrowserButton.IsEnabled = true;
            StatusText.Text = $"{ex.Message} (If you haven't signed in to {domain} in Web Login yet, click 'Open Browser & Sign In' once.)";
        }
    }

    private async void LaunchBrowserButton_Click(object? sender, RoutedEventArgs e)
    {
        var (loginUrl, domain) = GetSelectedSite();
        if (string.IsNullOrWhiteSpace(loginUrl))
        {
            StatusText.Text = "Please enter a valid login URL first.";
            return;
        }

        QuickResyncButton.IsEnabled = false;
        LaunchBrowserButton.IsEnabled = false;
        SyncCookiesButton.IsEnabled = false;
        StatusText.Text = $"Opening browser window for {domain}...";

        try
        {
            await _session.StartAsync(loginUrl);
            SyncCookiesButton.IsEnabled = true;
            LaunchBrowserButton.IsEnabled = true;
            StatusText.Text = $"Browser opened for {domain}. If not already signed in, log in once, then click 'Sync & Apply Cookies'.";
        }
        catch (Exception ex)
        {
            QuickResyncButton.IsEnabled = true;
            LaunchBrowserButton.IsEnabled = true;
            StatusText.Text = ex.Message;
        }
    }

    private async void SyncCookiesButton_Click(object? sender, RoutedEventArgs e)
    {
        var (_, domain) = GetSelectedSite();
        QuickResyncButton.IsEnabled = false;
        SyncCookiesButton.IsEnabled = false;
        LaunchBrowserButton.IsEnabled = false;
        StatusText.Text = $"Syncing cookies & saving session cleanly for {domain}...";

        try
        {
            var destPath = NetscapeCookieHelper.GetDefaultManagedCookiesPath();
            var count = await _session.SyncCookiesToFileAsync(destPath, domain, closeAfterSync: true);
            SavedCookiesPath = destPath;
            SavedCookieCount = count;
            SyncedDomain = domain;
            Close(true);
        }
        catch (Exception ex)
        {
            QuickResyncButton.IsEnabled = true;
            SyncCookiesButton.IsEnabled = _session.IsRunning;
            LaunchBrowserButton.IsEnabled = true;
            StatusText.Text = ex.Message;
        }
    }

    private async void CloseButton_Click(object? sender, RoutedEventArgs e)
    {
        await _session.CloseBrowserGracefullyAsync();
        Close(false);
    }

    protected override void OnClosed(EventArgs e)
    {
        base.OnClosed(e);
        _session.Dispose();
    }
}
