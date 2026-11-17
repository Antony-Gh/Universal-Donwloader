using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Platform.Storage;
using Avalonia.Threading;
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using UniversalDownloader.Core;
using UniversalDownloader.Core.Models;

namespace UniversalDownloader.Avalonia;

public partial class MainWindow : Window
{
    private const int MaxLogCapacity = 5000;
    private readonly DownloaderClient _client;
    private readonly List<string> _allLogs = new();
    private LogWindow? _logWindow;
    private CancellationTokenSource? _cts;

    public MainWindow()
    {
        InitializeComponent();

        _client = new DownloaderClient();
        _client.ProgressChanged += OnProgressChanged;
        _client.DownloadCompleted += OnDownloadCompleted;
        _client.DownloadFailed += OnDownloadFailed;
        _client.StatusChanged += OnStatusChanged;
        _client.RawOutputReceived += OnRawOutputReceived;

        Opened += async (s, e) => await LoadHistoryAsync();
    }

    private void OnRawOutputReceived(object? sender, string line)
    {
        if (string.IsNullOrWhiteSpace(line)) return;

        var timestamped = $"[{DateTime.Now:HH:mm:ss}] {line}";
        if (_allLogs.Count >= MaxLogCapacity)
        {
            _allLogs.RemoveRange(0, 500);
        }
        _allLogs.Add(timestamped);

        Dispatcher.UIThread.Post(() =>
        {
            // Update quick log box on download page
            if (string.IsNullOrEmpty(QuickLogBox.Text))
            {
                QuickLogBox.Text = timestamped;
            }
            else
            {
                QuickLogBox.Text += Environment.NewLine + timestamped;
            }
            QuickLogBox.CaretIndex = QuickLogBox.Text.Length;

            // Update main log tab if matching filter
            var filter = LogsFilterBox.Text?.Trim();
            if (string.IsNullOrEmpty(filter) || timestamped.Contains(filter, StringComparison.OrdinalIgnoreCase))
            {
                if (string.IsNullOrEmpty(MainLogTextBox.Text))
                {
                    MainLogTextBox.Text = timestamped;
                }
                else
                {
                    MainLogTextBox.Text += Environment.NewLine + timestamped;
                }

                if (AutoScrollCheck.IsChecked ?? true)
                {
                    MainLogTextBox.CaretIndex = MainLogTextBox.Text.Length;
                }
            }

            UpdateMainLogCount();

            // Forward to standalone window if open
            _logWindow?.AppendLog(line);
        });
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

    private DownloadOptions BuildOptionsFromUi()
    {
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

        var customDir = OutputDirBox.Text?.Trim();
        if (!string.IsNullOrWhiteSpace(customDir))
        {
            options.OutputDirectory = customDir;
        }

        if (QualityComboBox.SelectedIndex == 4)
        {
            options.AudioOnly = true;
            options.AudioFormat = "mp3";
            options.AudioQuality = "320k";
        }

        return options;
    }

    private async void DownloadButton_Click(object? sender, RoutedEventArgs e)
    {
        var url = UrlTextBox.Text?.Trim();
        if (string.IsNullOrWhiteSpace(url)) return;

        var options = BuildOptionsFromUi();
        await StartDownloadWithUrl(url, options);
    }

    private async Task StartDownloadWithUrl(string url, DownloadOptions options)
    {
        SetDownloading(true);
        ProgressCard.IsVisible = true;
        DownloadProgressBar.Value = 0;
        PercentLabel.Text = "0.0%";
        StatusLabel.Text = "Starting download...";

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
        StreamsStatusHeader.Text = $"Inspecting available streams for: {url}...";
        try
        {
            var formats = await _client.GetFormatsAsync(url);
            StreamsListBox.ItemsSource = formats;
            StreamsStatusHeader.Text = $"Found {formats.Count} streams for: {url}";
            GlobalStatusText.Text = $"Found {formats.Count} streams available.";
            MainTabControl.SelectedItem = StreamsTab;
        }
        catch (Exception ex)
        {
            StreamsStatusHeader.Text = $"Inspection failed: {ex.Message}";
            GlobalStatusText.Text = $"Inspection failed: {ex.Message}";
        }
    }

    private async void DownloadStream_Click(object? sender, RoutedEventArgs e)
    {
        if (sender is Button btn && btn.DataContext is FormatInfoModel format)
        {
            var url = UrlTextBox.Text?.Trim();
            if (string.IsNullOrWhiteSpace(url)) return;

            MainTabControl.SelectedIndex = 0; // Switch to Download tab
            var options = BuildOptionsFromUi();
            options.Quality = format.FormatId; // Direct stream target
            await StartDownloadWithUrl(url, options);
        }
    }

    private async void BrowseDirButton_Click(object? sender, RoutedEventArgs e)
    {
        var topLevel = TopLevel.GetTopLevel(this);
        if (topLevel == null) return;

        var folders = await topLevel.StorageProvider.OpenFolderPickerAsync(new FolderPickerOpenOptions
        {
            Title = "Select Media Save Directory",
            AllowMultiple = false
        });

        if (folders.Count > 0)
        {
            OutputDirBox.Text = folders[0].Path.LocalPath;
        }
    }

    private void OpenDirButton_Click(object? sender, RoutedEventArgs e)
    {
        var dir = OutputDirBox.Text?.Trim();
        if (!string.IsNullOrWhiteSpace(dir) && Directory.Exists(dir))
        {
            PlatformUtils.OpenFolder(dir);
        }
        else
        {
            var userProfile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            var defaultDownloads = Path.Combine(userProfile, "Downloads");
            PlatformUtils.OpenFolder(Directory.Exists(defaultDownloads) ? defaultDownloads : Environment.CurrentDirectory);
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

    private async void HistoryClearButton_Click(object? sender, RoutedEventArgs e)
    {
        await _client.ClearHistoryAsync();
        await LoadHistoryAsync();
    }

    private void OpenMediaFile_Click(object? sender, RoutedEventArgs e)
    {
        if (sender is Button btn && btn.DataContext is HistoryRecordModel record)
        {
            if (!string.IsNullOrWhiteSpace(record.PrimaryFilepath))
            {
                PlatformUtils.OpenFile(record.PrimaryFilepath);
            }
        }
    }

    private void ShowFolder_Click(object? sender, RoutedEventArgs e)
    {
        if (sender is Button btn && btn.DataContext is HistoryRecordModel record)
        {
            if (!string.IsNullOrWhiteSpace(record.PrimaryFilepath))
            {
                PlatformUtils.OpenFolder(record.PrimaryFilepath);
            }
        }
    }

    private void SetDownloading(bool active)
    {
        DownloadButton.IsEnabled = !active;
        InspectButton.IsEnabled = !active;
        CancelButton.IsEnabled = active;
    }

    private async void QuickCopyLogsButton_Click(object? sender, RoutedEventArgs e)
    {
        var clipboard = TopLevel.GetTopLevel(this)?.Clipboard;
        if (clipboard != null && !string.IsNullOrEmpty(QuickLogBox.Text))
        {
            await clipboard.SetTextAsync(QuickLogBox.Text);
            QuickCopyLogsButton.Content = "✓ Copied!";
            DispatcherTimer.RunOnce(() => QuickCopyLogsButton.Content = "📋 Copy Output", TimeSpan.FromSeconds(2));
        }
    }

    private async void CopyAllLogsButton_Click(object? sender, RoutedEventArgs e)
    {
        var clipboard = TopLevel.GetTopLevel(this)?.Clipboard;
        if (clipboard != null && !string.IsNullOrEmpty(MainLogTextBox.Text))
        {
            await clipboard.SetTextAsync(MainLogTextBox.Text);
            CopyAllLogsButton.Content = "✓ Copied!";
            DispatcherTimer.RunOnce(() => CopyAllLogsButton.Content = "📋 Copy All", TimeSpan.FromSeconds(2));
        }
    }

    private async void SaveAllLogsButton_Click(object? sender, RoutedEventArgs e)
    {
        if (string.IsNullOrEmpty(MainLogTextBox.Text)) return;

        var topLevel = TopLevel.GetTopLevel(this);
        if (topLevel == null) return;

        var file = await topLevel.StorageProvider.SaveFilePickerAsync(new FilePickerSaveOptions
        {
            Title = "Save Console Logs",
            SuggestedFileName = $"universal-downloader-log-{DateTime.Now:yyyyMMdd-HHmmss}.txt",
            DefaultExtension = "txt"
        });

        if (file != null)
        {
            await using var stream = await file.OpenWriteAsync();
            await using var writer = new StreamWriter(stream);
            await writer.WriteAsync(MainLogTextBox.Text);
            SaveAllLogsButton.Content = "✓ Saved!";
            DispatcherTimer.RunOnce(() => SaveAllLogsButton.Content = "💾 Save Logs", TimeSpan.FromSeconds(2));
        }
    }

    private void MainLogWordWrap_IsCheckedChanged(object? sender, RoutedEventArgs e)
    {
        MainLogTextBox.TextWrapping = (MainLogWordWrapCheck.IsChecked ?? true)
            ? global::Avalonia.Media.TextWrapping.Wrap
            : global::Avalonia.Media.TextWrapping.NoWrap;
    }

    private void ClearLogsButton_Click(object? sender, RoutedEventArgs e)
    {
        _allLogs.Clear();
        QuickLogBox.Text = string.Empty;
        MainLogTextBox.Text = string.Empty;
        UpdateMainLogCount();
    }

    private void LogsFilterBox_TextChanged(object? sender, TextChangedEventArgs e)
    {
        var filter = LogsFilterBox.Text?.Trim();
        var filtered = string.IsNullOrEmpty(filter)
            ? _allLogs
            : _allLogs.Where(l => l.Contains(filter, StringComparison.OrdinalIgnoreCase)).ToList();

        MainLogTextBox.Text = string.Join(Environment.NewLine, filtered);
        if (AutoScrollCheck.IsChecked ?? true)
        {
            MainLogTextBox.CaretIndex = MainLogTextBox.Text?.Length ?? 0;
        }

        UpdateMainLogCount(filtered.Count);
    }

    private void UpdateMainLogCount(int? filteredCount = null)
    {
        var total = _allLogs.Count;
        var shown = filteredCount ?? total;
        MainLogCountLabel.Text = total == shown
            ? $"Total: {total} log lines"
            : $"Showing {shown} of {total} log lines (filtered)";
    }

    private void PopOutLogsButton_Click(object? sender, RoutedEventArgs e)
    {
        if (_logWindow == null)
        {
            _logWindow = new LogWindow();
            _logWindow.Closed += (s, ev) => _logWindow = null;
            _logWindow.LoadLogs(_allLogs);
            _logWindow.Show(this);
        }
        else
        {
            _logWindow.Activate();
        }
    }
}
