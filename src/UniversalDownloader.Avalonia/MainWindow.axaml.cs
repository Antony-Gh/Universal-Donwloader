using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Threading;
using System;
using System.Threading;
using System.Threading.Tasks;
using UniversalDownloader.Core;
using UniversalDownloader.Core.Models;

namespace UniversalDownloader.Avalonia;

public partial class MainWindow : Window
{
    private readonly DownloaderClient _client;
    private CancellationTokenSource? _cts;

    public MainWindow()
    {
        InitializeComponent();

        _client = new DownloaderClient();
        _client.ProgressChanged += OnProgressChanged;
        _client.DownloadCompleted += OnDownloadCompleted;
        _client.DownloadFailed += OnDownloadFailed;
        _client.StatusChanged += OnStatusChanged;

        Opened += async (s, e) => await LoadHistoryAsync();
    }

    private void OnProgressChanged(object? sender, DownloadProgressEvent e)
    {
        Dispatcher.UIThread.Post(() =>
        {
            DownloadProgressBar.Value = Math.Clamp(e.Percent, 0, 100);
            PercentLabel.Text = $"{e.Percent:F1}%";
            DetailsLabel.Text = $"{e.DownloadedFormatted} / {e.TotalFormatted} • {e.SpeedFormatted}";
            EtaLabel.Text = $"ETA: {e.EtaFormatted}";
            GlobalStatusText.Text = $"Downloading: {e.Percent:F1}% at {e.SpeedFormatted}";
        });
    }

    private void OnStatusChanged(object? sender, string status)
    {
        Dispatcher.UIThread.Post(() =>
        {
            StatusLabel.Text = status;
            GlobalStatusText.Text = status;
        });
    }

    private void OnDownloadCompleted(object? sender, DownloadCompleteEvent e)
    {
        Dispatcher.UIThread.Post(async () =>
        {
            DownloadProgressBar.Value = 100;
            PercentLabel.Text = "100%";
            StatusLabel.Text = "✓ Download finished!";
            GlobalStatusText.Text = $"Successfully downloaded: {e.Title ?? e.Url}";
            SetDownloading(false);
            await LoadHistoryAsync();
        });
    }

    private void OnDownloadFailed(object? sender, DownloadErrorEvent e)
    {
        Dispatcher.UIThread.Post(() =>
        {
            StatusLabel.Text = "✗ Download failed";
            GlobalStatusText.Text = $"Failed: {e.Error}";
            SetDownloading(false);
        });
    }

    private async void DownloadButton_Click(object? sender, RoutedEventArgs e)
    {
        var url = UrlTextBox.Text?.Trim();
        if (string.IsNullOrWhiteSpace(url)) return;

        SetDownloading(true);
        ProgressCard.IsVisible = true;
        DownloadProgressBar.Value = 0;
        PercentLabel.Text = "0.0%";
        StatusLabel.Text = "Starting download...";

        var options = new DownloadOptions
        {
            EmbedMetadata = EmbedMetadataCheck.IsChecked ?? true,
            EmbedThumbnail = EmbedThumbnailCheck.IsChecked ?? true,
            EmbedSubs = EmbedSubsCheck.IsChecked ?? false,
            WriteThumbnail = WriteThumbnailCheck.IsChecked ?? false,
            ConcurrentFragments = (int)(FragmentsNumeric.Value ?? 4),
            Quality = QualityComboBox.SelectedIndex switch
            {
                1 => "1080p",
                2 => "720p",
                3 => "480p",
                4 => "audio",
                _ => "best",
            },
            PreferCodec = CodecComboBox.SelectedIndex switch
            {
                1 => "h264",
                2 => "vp9",
                3 => "av01",
                _ => null,
            }
        };

        if (QualityComboBox.SelectedIndex == 4)
        {
            options.AudioOnly = true;
            options.AudioFormat = "mp3";
            options.AudioQuality = "320k";
        }

        _cts = new CancellationTokenSource();
        try
        {
            await _client.DownloadAsync(url, options, _cts.Token);
        }
        catch (OperationCanceledException)
        {
            StatusLabel.Text = "Download canceled.";
            SetDownloading(false);
        }
        catch (Exception ex)
        {
            StatusLabel.Text = $"Error: {ex.Message}";
            SetDownloading(false);
        }
    }

    private void CancelButton_Click(object? sender, RoutedEventArgs e)
    {
        _cts?.Cancel();
        _client.Cancel();
        CancelButton.IsEnabled = false;
    }

    private async void InspectButton_Click(object? sender, RoutedEventArgs e)
    {
        var url = UrlTextBox.Text?.Trim();
        if (string.IsNullOrWhiteSpace(url)) return;

        GlobalStatusText.Text = "Inspecting stream formats...";
        try
        {
            var formats = await _client.GetFormatsAsync(url);
            GlobalStatusText.Text = $"Found {formats.Count} streams available.";
        }
        catch (Exception ex)
        {
            GlobalStatusText.Text = $"Inspection failed: {ex.Message}";
        }
    }

    private async void PasteButton_Click(object? sender, RoutedEventArgs e)
    {
        var clipboard = TopLevel.GetTopLevel(this)?.Clipboard;
        if (clipboard != null)
        {
            var text = await clipboard.GetTextAsync();
            if (!string.IsNullOrWhiteSpace(text))
            {
                UrlTextBox.Text = text.Trim();
            }
        }
    }

    private async Task LoadHistoryAsync(string? search = null)
    {
        try
        {
            var records = await _client.GetHistoryAsync(limit: 50, search: search);
            HistoryListBox.ItemsSource = records;
        }
        catch { }
    }

    private async void HistorySearchButton_Click(object? sender, RoutedEventArgs e)
    {
        var q = HistorySearchBox.Text?.Trim();
        await LoadHistoryAsync(string.IsNullOrWhiteSpace(q) ? null : q);
    }

    private async void HistoryRefreshButton_Click(object? sender, RoutedEventArgs e)
    {
        HistorySearchBox.Text = string.Empty;
        await LoadHistoryAsync();
    }

    private void SetDownloading(bool active)
    {
        DownloadButton.IsEnabled = !active;
        InspectButton.IsEnabled = !active;
        CancelButton.IsEnabled = active;
    }
}
