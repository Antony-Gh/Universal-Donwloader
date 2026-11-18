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
        if (detected != null)
        {
            BrowserDetectedText.Text = $"{detected.Name} (ready)";
        }
        else
        {
            BrowserDetectedText.Text = "No Chrome / Edge / Brave detected";
            LaunchBrowserButton.IsEnabled = false;
            StatusText.Text = "Install Google Chrome, Microsoft Edge, or Brave to use Web Login, or use Paste Cookies instead.";
        }
    }

    public BrowserLoginWindow(string? initialUrlOrDomain) : this()
    {
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
            0 => ("https://www.facebook.com/login/", "facebook.com"),
            1 => ("https://www.instagram.com/accounts/login/", "instagram.com"),
            2 => ("https://www.youtube.com/", "youtube.com"),
            3 => ("https://www.tiktok.com/login", "tiktok.com"),
            4 => ("https://x.com/i/flow/login", "x.com"),
            5 => ("https://www.reddit.com/login/", "reddit.com"),
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

    private async void LaunchBrowserButton_Click(object? sender, RoutedEventArgs e)
    {
        var (loginUrl, domain) = GetSelectedSite();
        if (string.IsNullOrWhiteSpace(loginUrl))
        {
            StatusText.Text = "Please enter a valid login URL first.";
            return;
        }

        LaunchBrowserButton.IsEnabled = false;
        SyncCookiesButton.IsEnabled = false;
        StatusText.Text = $"Opening browser window for {domain}...";

        try
        {
            await _session.StartAsync(loginUrl);
            SyncCookiesButton.IsEnabled = true;
            LaunchBrowserButton.IsEnabled = true;
            StatusText.Text = $"Browser opened for {domain}. Sign in to your account, then click 'Sync & Apply Cookies'.";
        }
        catch (Exception ex)
        {
            LaunchBrowserButton.IsEnabled = true;
            StatusText.Text = ex.Message;
        }
    }

    private async void SyncCookiesButton_Click(object? sender, RoutedEventArgs e)
    {
        var (_, domain) = GetSelectedSite();
        SyncCookiesButton.IsEnabled = false;
        LaunchBrowserButton.IsEnabled = false;
        StatusText.Text = $"Syncing cookies for {domain}...";

        try
        {
            var destPath = NetscapeCookieHelper.GetDefaultManagedCookiesPath();
            var count = await _session.SyncCookiesToFileAsync(destPath, domain);
            SavedCookiesPath = destPath;
            SavedCookieCount = count;
            SyncedDomain = domain;
            _session.CloseBrowser();
            Close(true);
        }
        catch (Exception ex)
        {
            SyncCookiesButton.IsEnabled = _session.IsRunning;
            LaunchBrowserButton.IsEnabled = true;
            StatusText.Text = ex.Message;
        }
    }

    private void CloseButton_Click(object? sender, RoutedEventArgs e)
    {
        _session.CloseBrowser();
        Close(false);
    }

    protected override void OnClosed(EventArgs e)
    {
        base.OnClosed(e);
        _session.Dispose();
    }
}
