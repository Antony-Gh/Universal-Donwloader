using System;
using System.Threading.Tasks;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;

namespace UniversalDownloader.Avalonia;

public partial class QuickDownloadWindow : Window
{
    public event Action<string, string, string?, bool>? DownloadTriggered;

    public QuickDownloadWindow()
    {
        InitializeComponent();
        Loaded += QuickDownloadWindow_Loaded;
        KeyDown += QuickDownloadWindow_KeyDown;
    }

    public void ApplyLanguage(string lang)
    {
        var code = lang == "ar" ? "ar" : "en";
        FlowDirection = code == "ar"
            ? global::Avalonia.Media.FlowDirection.RightToLeft
            : global::Avalonia.Media.FlowDirection.LeftToRight;

        string T(string key) => Localization.Get(code, key);

        Title = T("QuickHudTitle");
        HudTitleText.Text = T("QuickHudHeader");
        HudSubtitleText.Text = T("QuickHudSubtitle");
        HudUrlTextBox.Watermark = T("QuickHudUrlWatermark");
        HudPasteText.Text = T("Paste");
        HudFormatQualityLabel.Text = T("QuickHudFormatQuality");
        HudPresetLabel.Text = T("QuickHudPreset");
        HudDownloadVideoText.Text = T("QuickHudDownloadVideo");
        HudDownloadAudioText.Text = T("QuickHudDownloadAudio");
        HudQueueText.Text = T("QuickHudAddToQueue");
        HudTipText.Text = T("QuickHudTip");
        HudDismissButton.Content = T("QuickHudDismiss");
    }

    private async void QuickDownloadWindow_Loaded(object? sender, RoutedEventArgs e)
    {
        HudUrlTextBox.Focus();
        try
        {
            var clipboard = TopLevel.GetTopLevel(this)?.Clipboard;
            if (clipboard != null)
            {
                var text = await clipboard.GetTextAsync();
                if (!string.IsNullOrWhiteSpace(text) && (text.StartsWith("http://", StringComparison.OrdinalIgnoreCase) || text.StartsWith("https://", StringComparison.OrdinalIgnoreCase)))
                {
                    HudUrlTextBox.Text = text.Trim();
                    HudUrlTextBox.SelectAll();
                    ShowStatus("Detected media URL from clipboard!", "#38BDF8");
                }
            }
        }
        catch
        {
            // Clipboard access might fail silently
        }
    }

    private void QuickDownloadWindow_KeyDown(object? sender, KeyEventArgs e)
    {
        if (e.Key == Key.Escape)
        {
            Close();
            e.Handled = true;
        }
        else if (e.Key == Key.Enter && !e.KeyModifiers.HasFlag(KeyModifiers.Shift))
        {
            HudDownloadVideoButton_Click(this, new RoutedEventArgs());
            e.Handled = true;
        }
    }

    private async void HudPasteButton_Click(object? sender, RoutedEventArgs e)
    {
        try
        {
            var clipboard = TopLevel.GetTopLevel(this)?.Clipboard;
            if (clipboard != null)
            {
                var text = await clipboard.GetTextAsync();
                if (!string.IsNullOrWhiteSpace(text))
                {
                    HudUrlTextBox.Text = text.Trim();
                    ShowStatus("Pasted from clipboard.", "#38BDF8");
                }
            }
        }
        catch (Exception ex)
        {
            ShowStatus($"Paste error: {ex.Message}", "#F87171");
        }
    }

    private void HudDownloadVideoButton_Click(object? sender, RoutedEventArgs e)
    {
        SubmitRequest(formatAudio: false, queueOnly: false);
    }

    private void HudDownloadAudioButton_Click(object? sender, RoutedEventArgs e)
    {
        SubmitRequest(formatAudio: true, queueOnly: false);
    }

    private void HudQueueButton_Click(object? sender, RoutedEventArgs e)
    {
        SubmitRequest(formatAudio: false, queueOnly: true);
    }

    private void SubmitRequest(bool formatAudio, bool queueOnly)
    {
        var url = HudUrlTextBox.Text?.Trim();
        if (string.IsNullOrWhiteSpace(url))
        {
            ShowStatus("Please enter or paste a valid media URL.", "#F87171");
            return;
        }

        string quality;
        if (formatAudio)
        {
            quality = "Audio";
        }
        else
        {
            quality = HudQualityCombo.SelectedIndex switch
            {
                1 => "1080p",
                2 => "720p",
                3 => "480p",
                4 => "Audio",
                5 => "Audio",
                6 => "Audio",
                _ => "best"
            };
        }

        string? preset = HudPresetCombo.SelectedIndex switch
        {
            1 => "discord",
            2 => "discord_10mb",
            3 => "whatsapp",
            4 => "car_audio",
            5 => "tv_theater",
            _ => null
        };

        DownloadTriggered?.Invoke(url, quality, preset, queueOnly);
        ShowStatus(queueOnly ? "Added to download queue!" : "Download initiated!", "#34D399");

        Task.Delay(850).ContinueWith(_ =>
        {
            global::Avalonia.Threading.Dispatcher.UIThread.Post(Close);
        });
    }

    private void ShowStatus(string message, string hexColor)
    {
        HudStatusText.Text = message;
        HudStatusText.Foreground = global::Avalonia.Media.Brush.Parse(hexColor);
        HudStatusBorder.IsVisible = true;
    }

    private void CloseButton_Click(object? sender, RoutedEventArgs e)
    {
        Close();
    }
}
