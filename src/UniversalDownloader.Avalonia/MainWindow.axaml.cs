using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Media.Imaging;
using Avalonia.Platform.Storage;
using Avalonia.Threading;
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using UniversalDownloader.Core;
using UniversalDownloader.Core.Models;

namespace UniversalDownloader.Avalonia;

public partial class MainWindow : Window
{
    private const int MaxLogCapacity = 5000;
    private readonly DownloaderClient _client;
    private readonly object _allLogsLock = new();
    private readonly List<LogMessage> _allLogs = new();
    private readonly System.Collections.Concurrent.ConcurrentQueue<LogMessage> _incomingLogs = new();
    private readonly ObservableCollection<LogMessage> _quickLogs = new();
    private readonly ObservableCollection<LogMessage> _filteredMainLogs = new();
    private readonly DispatcherTimer _logBatchTimer;
    private long _lastProgressUpdateMs = 0;
    private LogWindow? _logWindow;
    private CancellationTokenSource? _cts;
    private CancellationTokenSource? _metadataCts;
    private string? _lastInspectedMetadataUrl;
    private static readonly HttpClient _httpClient = new() { Timeout = TimeSpan.FromSeconds(12) };

    public MainWindow()
    {
        InitializeComponent();

        QuickLogListBox.ItemsSource = _quickLogs;
        MainLogListBox.ItemsSource = _filteredMainLogs;

        // Background batch timer prevents UI thread saturation and keeps window 100% responsive
        _logBatchTimer = new DispatcherTimer(
            TimeSpan.FromMilliseconds(50),
            DispatcherPriority.Background,
            (s, e) => FlushPendingLogs()
        );
        _logBatchTimer.Start();

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

        var log = LogMessage.Create(line);
        _incomingLogs.Enqueue(log);

        // Forward to standalone window if open
        _logWindow?.AppendLog(line);
    }

    private void FlushPendingLogs()
    {
        if (_incomingLogs.IsEmpty) return;

        var batch = new List<LogMessage>(64);
        while (batch.Count < 100 && _incomingLogs.TryDequeue(out var log))
        {
            batch.Add(log);
        }

        if (batch.Count == 0) return;

        lock (_allLogsLock)
        {
            if (_allLogs.Count + batch.Count > MaxLogCapacity)
            {
                var removeCount = Math.Min(_allLogs.Count, Math.Max(500, (_allLogs.Count + batch.Count) - MaxLogCapacity));
                _allLogs.RemoveRange(0, removeCount);
            }
            _allLogs.AddRange(batch);
        }

        // Update quick log box on download page (keep last 50)
        foreach (var log in batch)
        {
            if (_quickLogs.Count >= 50)
            {
                _quickLogs.RemoveAt(0);
            }
            _quickLogs.Add(log);
        }

        if (_quickLogs.Count > 0)
        {
            QuickLogListBox.ScrollIntoView(_quickLogs[^1]);
        }

        // Update main log tab if matching filter
        var filter = LogsFilterBox.Text?.Trim();
        var matching = string.IsNullOrEmpty(filter)
            ? batch
            : batch.Where(l => l.FormattedText.Contains(filter, StringComparison.OrdinalIgnoreCase)).ToList();

        if (matching.Count > 0)
        {
            foreach (var log in matching)
            {
                if (_filteredMainLogs.Count >= MaxLogCapacity)
                {
                    _filteredMainLogs.RemoveAt(0);
                }
                _filteredMainLogs.Add(log);
            }

            if ((AutoScrollCheck.IsChecked ?? true) && _filteredMainLogs.Count > 0)
            {
                MainLogListBox.ScrollIntoView(_filteredMainLogs[^1]);
            }
        }

        UpdateMainLogCount();
    }

    private void OnProgressChanged(object? sender, DownloadProgressEvent e)
    {
        var now = Environment.TickCount64;
        if (e.Percent >= 100 || now - _lastProgressUpdateMs >= 60)
        {
            _lastProgressUpdateMs = now;
            Dispatcher.UIThread.Post(() =>
            {
                DownloadProgressBar.Value = Math.Clamp(e.Percent, 0, 100);
                PercentLabel.Text = $"{e.Percent:F1}%";
                DetailsLabel.Text = $"{e.DownloadedFormatted} / {e.TotalFormatted} • {e.SpeedFormatted}";
                EtaLabel.Text = $"ETA: {e.EtaFormatted}";
                GlobalStatusText.Text = $"Downloading: {e.Percent:F1}% at {e.SpeedFormatted}";
            }, DispatcherPriority.Background);
        }
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
            StatusLabel.Text = "Download finished!";
            GlobalStatusText.Text = $"Successfully downloaded: {e.Title ?? e.Url}";
            SetDownloading(false);
            await LoadHistoryAsync();
        });
    }

    private void OnDownloadFailed(object? sender, DownloadErrorEvent e)
    {
        Dispatcher.UIThread.Post(() =>
        {
            StatusLabel.Text = "Download failed";
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

    private async void UrlTextBox_TextChanged(object? sender, TextChangedEventArgs e)
    {
        _metadataCts?.Cancel();
        _metadataCts?.Dispose();
        _metadataCts = new CancellationTokenSource();
        var token = _metadataCts.Token;

        var rawUrl = UrlTextBox.Text?.Trim()?.Trim('"', '\'');
        if (string.IsNullOrWhiteSpace(rawUrl))
        {
            MetadataCard.IsVisible = false;
            _lastInspectedMetadataUrl = null;
            return;
        }

        // Validate HTTP / HTTPS URL
        if (!Uri.TryCreate(rawUrl, UriKind.Absolute, out var uri) ||
            (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps))
        {
            if (rawUrl != _lastInspectedMetadataUrl)
            {
                MetadataCard.IsVisible = false;
            }
            return;
        }

        if (rawUrl == _lastInspectedMetadataUrl)
        {
            return; // Already fetched
        }

        try
        {
            // Debounce for 400ms to avoid querying on rapid typing
            await Task.Delay(400, token);
            if (token.IsCancellationRequested) return;

            await FetchAndDisplayMetadataAsync(rawUrl, uri, token);
        }
        catch (OperationCanceledException)
        {
            // Ignored on cancellation
        }
    }

    private async Task FetchAndDisplayMetadataAsync(string rawUrl, Uri uri, CancellationToken token)
    {
        _lastInspectedMetadataUrl = rawUrl;

        // Immediately show the card in loading state with host-based platform badge
        var host = uri.Host.ToLowerInvariant().Replace("www.", "").Replace("m.", "");
        var platformDisplay = host switch
        {
            var h when h.Contains("youtube") || h.Contains("youtu.be") => "YOUTUBE",
            var h when h.Contains("tiktok") => "TIKTOK",
            var h when h.Contains("instagram") => "INSTAGRAM",
            var h when h.Contains("facebook") || h.Contains("fb.watch") => "FACEBOOK",
            var h when h.Contains("twitter") || h.Contains("x.com") => "X / TWITTER",
            var h when h.Contains("soundcloud") => "SOUNDCLOUD",
            var h when h.Contains("vimeo") => "VIMEO",
            var h when h.Contains("reddit") => "REDDIT",
            var h when h.Contains("twitch") => "TWITCH",
            _ => "MEDIA"
        };

        PlatformBadge.Text = platformDisplay;
        VideoTitleLabel.Text = "Fetching media details...";
        UploaderLabel.Text = uri.Host;
        ViewsLabel.Text = "";
        DurationBadge.IsVisible = false;
        ThumbnailImage.Source = null;
        MetadataLoadingText.Text = "Loading details...";
        MetadataLoadingText.IsVisible = true;
        MetadataCard.IsVisible = true;

        try
        {
            var meta = await _client.GetMetadataAsync(rawUrl, token);
            if (token.IsCancellationRequested) return;

            if (meta != null && !string.IsNullOrWhiteSpace(meta.Title))
            {
                MetadataLoadingText.IsVisible = false;
                VideoTitleLabel.Text = meta.Title;
                UploaderLabel.Text = !string.IsNullOrWhiteSpace(meta.Uploader) ? meta.Uploader : uri.Host;

                if (!string.IsNullOrWhiteSpace(meta.Platform))
                {
                    PlatformBadge.Text = meta.Platform.ToUpperInvariant();
                }

                if (!string.IsNullOrWhiteSpace(meta.DurationFormatted))
                {
                    DurationLabel.Text = meta.DurationFormatted;
                    DurationBadge.IsVisible = true;
                }
                else
                {
                    DurationBadge.IsVisible = false;
                }

                ViewsLabel.Text = meta.ViewCountFormatted;

                if (!string.IsNullOrWhiteSpace(meta.Thumbnail))
                {
                    await LoadThumbnailAsync(meta.Thumbnail, token);
                }
            }
            else
            {
                MetadataLoadingText.Text = "Ready to download";
            }
        }
        catch (OperationCanceledException)
        {
            // Normal cancellation
        }
        catch (Exception)
        {
            if (!token.IsCancellationRequested)
            {
                MetadataLoadingText.Text = "Ready to download";
            }
        }
    }

    private async Task LoadThumbnailAsync(string thumbnailUrl, CancellationToken token)
    {
        try
        {
            var bytes = await _httpClient.GetByteArrayAsync(thumbnailUrl, token);
            if (token.IsCancellationRequested || bytes == null || bytes.Length == 0) return;

            await Dispatcher.UIThread.InvokeAsync(() =>
            {
                using var ms = new MemoryStream(bytes);
                ThumbnailImage.Source = new Bitmap(ms);
            });
        }
        catch
        {
            // Thumbnail failed or cancelled - keep default empty thumbnail
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
        if (clipboard != null && _quickLogs.Count > 0)
        {
            var fullText = string.Join(Environment.NewLine, _quickLogs.Select(l => l.FormattedText));
            await clipboard.SetTextAsync(fullText);
            QuickCopyText.Text = "Copied!";
            DispatcherTimer.RunOnce(() => QuickCopyText.Text = "Copy Output", TimeSpan.FromSeconds(2));
        }
    }

    private async void CopyAllLogsButton_Click(object? sender, RoutedEventArgs e)
    {
        var clipboard = TopLevel.GetTopLevel(this)?.Clipboard;
        if (clipboard != null && _filteredMainLogs.Count > 0)
        {
            var fullText = string.Join(Environment.NewLine, _filteredMainLogs.Select(l => l.FormattedText));
            await clipboard.SetTextAsync(fullText);
            CopyAllLogsText.Text = "Copied!";
            DispatcherTimer.RunOnce(() => CopyAllLogsText.Text = "Copy All", TimeSpan.FromSeconds(2));
        }
    }

    private async void SaveAllLogsButton_Click(object? sender, RoutedEventArgs e)
    {
        if (_filteredMainLogs.Count == 0) return;

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
            var fullText = string.Join(Environment.NewLine, _filteredMainLogs.Select(l => l.FormattedText));
            await writer.WriteAsync(fullText);
            SaveAllLogsText.Text = "Saved!";
            DispatcherTimer.RunOnce(() => SaveAllLogsText.Text = "Save Logs", TimeSpan.FromSeconds(2));
        }
    }

    private void ClearLogsButton_Click(object? sender, RoutedEventArgs e)
    {
        while (_incomingLogs.TryDequeue(out _)) { }
        lock (_allLogsLock)
        {
            _allLogs.Clear();
        }
        _quickLogs.Clear();
        _filteredMainLogs.Clear();
        UpdateMainLogCount();
    }

    private void LogsFilterBox_TextChanged(object? sender, TextChangedEventArgs e)
    {
        var filter = LogsFilterBox.Text?.Trim();
        List<LogMessage> matching;
        lock (_allLogsLock)
        {
            matching = string.IsNullOrEmpty(filter)
                ? new List<LogMessage>(_allLogs)
                : _allLogs.Where(l => l.FormattedText.Contains(filter, StringComparison.OrdinalIgnoreCase)).ToList();
        }

        _filteredMainLogs.Clear();
        foreach (var log in matching)
        {
            _filteredMainLogs.Add(log);
        }

        if ((AutoScrollCheck.IsChecked ?? true) && _filteredMainLogs.Count > 0)
        {
            MainLogListBox.ScrollIntoView(_filteredMainLogs[^1]);
        }

        UpdateMainLogCount(matching.Count);
    }

    private void UpdateMainLogCount(int? filteredCount = null)
    {
        int total;
        lock (_allLogsLock)
        {
            total = _allLogs.Count;
        }
        var shown = filteredCount ?? _filteredMainLogs.Count;
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
            List<LogMessage> copy;
            lock (_allLogsLock)
            {
                copy = new List<LogMessage>(_allLogs);
            }
            _logWindow.LoadLogs(copy);
            _logWindow.Show(this);
        }
        else
        {
            _logWindow.Activate();
        }
    }
}
