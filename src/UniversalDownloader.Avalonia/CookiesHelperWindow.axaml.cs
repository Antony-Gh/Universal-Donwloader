using Avalonia.Controls;
using Avalonia.Interactivity;
using System;
using UniversalDownloader.Core;

namespace UniversalDownloader.Avalonia;

public partial class CookiesHelperWindow : Window
{
    public string? SavedCookiesPath { get; private set; }
    public int SavedCookieCount { get; private set; }

    public CookiesHelperWindow()
    {
        InitializeComponent();
    }

    public CookiesHelperWindow(string? initialUrlOrDomain) : this()
    {
        if (!string.IsNullOrWhiteSpace(initialUrlOrDomain))
        {
            var lowered = initialUrlOrDomain.ToLowerInvariant();
            if (lowered.Contains("facebook") || lowered.Contains("fb.watch")) SiteComboBox.SelectedIndex = 0;
            else if (lowered.Contains("instagram")) SiteComboBox.SelectedIndex = 1;
            else if (lowered.Contains("youtube") || lowered.Contains("youtu.be")) SiteComboBox.SelectedIndex = 2;
            else if (lowered.Contains("tiktok")) SiteComboBox.SelectedIndex = 3;
            else if (lowered.Contains("x.com") || lowered.Contains("twitter")) SiteComboBox.SelectedIndex = 4;
        }
    }

    private void SiteComboBox_SelectionChanged(object? sender, SelectionChangedEventArgs e)
    {
        if (CustomDomainBox != null)
        {
            CustomDomainBox.IsVisible = SiteComboBox.SelectedIndex == 5;
        }
    }

    private async void PasteClipboardButton_Click(object? sender, RoutedEventArgs e)
    {
        var clipboard = TopLevel.GetTopLevel(this)?.Clipboard;
        if (clipboard == null) return;
        var text = await clipboard.GetTextAsync();
        if (!string.IsNullOrWhiteSpace(text))
        {
            CookiesInputBox.Text = text.Trim();
            StatusText.Text = "Pasted from clipboard — click Save & Apply Cookies.";
        }
    }

    private void SaveButton_Click(object? sender, RoutedEventArgs e)
    {
        var raw = CookiesInputBox.Text?.Trim();
        if (string.IsNullOrWhiteSpace(raw))
        {
            StatusText.Text = "Please paste a Cookie header or Netscape cookies.txt content first.";
            return;
        }

        var domain = SiteComboBox.SelectedIndex switch
        {
            0 => "facebook.com",
            1 => "instagram.com",
            2 => "youtube.com",
            3 => "tiktok.com",
            4 => "x.com",
            _ => CustomDomainBox.Text?.Trim() ?? string.Empty,
        };

        try
        {
            var destPath = NetscapeCookieHelper.GetDefaultManagedCookiesPath();
            var count = NetscapeCookieHelper.MergeIntoCookiesFile(destPath, raw, domain);
            SavedCookiesPath = destPath;
            SavedCookieCount = count;
            Close(true);
        }
        catch (Exception ex)
        {
            StatusText.Text = ex.Message;
        }
    }

    private void CancelButton_Click(object? sender, RoutedEventArgs e)
    {
        Close(false);
    }
}
