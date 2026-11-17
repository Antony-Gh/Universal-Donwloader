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
    private const int AutoInspectPlaylistQualityLimit = 25;
    private readonly DownloaderClient _client;
    private readonly object _allLogsLock = new();
    private readonly List<LogMessage> _allLogs = new();
    private readonly System.Collections.Concurrent.ConcurrentQueue<LogMessage> _incomingLogs = new();
    private readonly ObservableCollection<LogMessage> _quickLogs = new();
    private readonly ObservableCollection<LogMessage> _filteredMainLogs = new();
    private readonly ObservableCollection<QueueItemModel> _queueItems = new();
    private readonly ObservableCollection<PlaylistVideoCardModel> _playlistCards = new();
    private CancellationTokenSource? _queueCts;
    private CancellationTokenSource? _playlistQualityCts;
    private bool _isQueueRunning;
    private readonly DispatcherTimer _logBatchTimer;
    private long _lastProgressUpdateMs = 0;
    private LogWindow? _logWindow;
    private CancellationTokenSource? _cts;
    private CancellationTokenSource? _metadataCts;
    private string? _lastInspectedMetadataUrl;
    private int _activeTaskCount = 0;
    private AppUpdateInfo? _latestUpdateInfo;
    private UserSettings _settings = new();
    private string? _detectedClipboardUrl;
    private string? _dismissedClipboardUrl;
    private static readonly string[] SupportedClipboardHosts =
    [
        "youtube.com", "youtu.be", "instagram.com", "tiktok.com", "facebook.com", "fb.watch",
        "twitter.com", "x.com", "soundcloud.com", "vimeo.com", "reddit.com", "redd.it",
        "twitch.tv", "threads.net", "pinterest.com", "pin.it", "dailymotion.com", "bilibili.com"
    ];
    private static readonly HttpClient _httpClient = new() { Timeout = TimeSpan.FromSeconds(12) };

    public MainWindow()
    {
        InitializeComponent();

        AppVersionBadge.Text = $"v{UpdateChecker.GetCurrentVersion()}";
        LoadUserSettings();
        QuickLogListBox.ItemsSource = _quickLogs;
        MainLogListBox.ItemsSource = _filteredMainLogs;
        QueueListBox.ItemsSource = _queueItems;
        PlaylistCardsItemsControl.ItemsSource = _playlistCards;

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

        Opened += async (s, e) =>
        {
            await LoadHistoryAsync();
            _ = CheckForAppUpdatesAsync(silent: true);
            await CheckClipboardForMediaUrlAsync();
        };
        Activated += async (s, e) => await CheckClipboardForMediaUrlAsync();
        Closing += (s, e) =>
        {
            _playlistQualityCts?.Cancel();
            SaveUserSettings();
        };
    }

    private async Task CheckClipboardForMediaUrlAsync()
    {
        try
        {
            var clipboard = TopLevel.GetTopLevel(this)?.Clipboard;
            if (clipboard == null) return;
            var raw = (await clipboard.GetTextAsync())?.Trim();
            if (string.IsNullOrWhiteSpace(raw) || raw.Length > 1000) return;

            if (!Uri.TryCreate(raw, UriKind.Absolute, out var uri) ||
                (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps))
            {
                return;
            }

            var host = uri.Host.ToLowerInvariant();
            if (!SupportedClipboardHosts.Any(h => host == h || host.EndsWith("." + h)))
            {
                return;
            }

            var currentInput = UrlTextBox.Text?.Trim();
            if (string.Equals(raw, currentInput, StringComparison.OrdinalIgnoreCase) ||
                string.Equals(raw, _dismissedClipboardUrl, StringComparison.OrdinalIgnoreCase))
            {
                ClipboardBanner.IsVisible = false;
                return;
            }

            _detectedClipboardUrl = raw;
            ClipboardBannerText.Text = $"Copied link detected: {raw}";
            ClipboardBanner.IsVisible = true;
        }
        catch
        {
            // Clipboard access may fail silently when locked by another app
        }
    }

    private void AcceptClipboardButton_Click(object? sender, RoutedEventArgs e)
    {
        if (!string.IsNullOrWhiteSpace(_detectedClipboardUrl))
        {
            ClipboardBanner.IsVisible = false;
            UrlTextBox.Text = _detectedClipboardUrl;
        }
    }

    private void DismissClipboardButton_Click(object? sender, RoutedEventArgs e)
    {
        _dismissedClipboardUrl = _detectedClipboardUrl;
        ClipboardBanner.IsVisible = false;
    }

    private void LoadUserSettings()
    {
        _settings = UserSettings.Load();
        QualityComboBox.SelectedIndex = Math.Clamp(_settings.QualityIndex, 0, Math.Max(0, QualityComboBox.ItemCount - 1));
        CodecComboBox.SelectedIndex = Math.Clamp(_settings.CodecIndex, 0, Math.Max(0, CodecComboBox.ItemCount - 1));
        FragmentsNumeric.Value = Math.Clamp(_settings.ConcurrentFragments, 1, 16);
        OutputDirBox.Text = _settings.OutputDirectory;
        CookiesBrowserComboBox.SelectedIndex = Math.Clamp(_settings.CookiesBrowserIndex, 0, Math.Max(0, CookiesBrowserComboBox.ItemCount - 1));
        CookiesFileBox.Text = _settings.CookiesFilePath;
        EmbedMetadataCheck.IsChecked = _settings.EmbedMetadata;
        EmbedThumbnailCheck.IsChecked = _settings.EmbedThumbnail;
        EmbedSubsCheck.IsChecked = _settings.EmbedSubs;
        WriteThumbnailCheck.IsChecked = _settings.WriteThumbnail;
        SponsorBlockCheck.IsChecked = _settings.SponsorBlockEnabled;
        ApplyLanguage(_settings.Language);
    }

    private void LanguageToggleButton_Click(object? sender, RoutedEventArgs e)
    {
        var nextLang = _settings.Language == "ar" ? "en" : "ar";
        _settings.Language = nextLang;
        ApplyLanguage(nextLang);
        SaveUserSettings();
    }

    private void ApplyLanguage(string lang)
    {
        var code = lang == "ar" ? "ar" : "en";
        FlowDirection = code == "ar"
            ? global::Avalonia.Media.FlowDirection.RightToLeft
            : global::Avalonia.Media.FlowDirection.LeftToRight;

        string T(string key) => Localization.Get(code, key);

        Title = T("AppTitle");
        AppTitleText.Text = T("AppTitle");
        LanguageToggleButton.Content = T("LangToggle");
        CheckUpdatesText.Text = T("CheckUpdates");

        DownloadTab.Header = T("TabDownload");
        QueueTab.Header = T("TabQueue");
        StreamsTab.Header = T("TabStreams");
        HistoryTab.Header = T("TabHistory");
        LogsTab.Header = T("TabLogs");

        MediaUrlHeader.Text = T("MediaUrl");
        UrlTextBox.Watermark = T("UrlWatermark");
        PasteButtonText.Text = T("Paste");
        InspectButtonText.Text = T("InspectStreams");

        DownloadOptionsHeader.Text = T("DownloadOptions");
        QualityHeader.Text = T("Quality");
        CodecHeader.Text = T("Codec");
        FragmentsHeader.Text = T("Fragments");
        SaveDirHeader.Text = T("SaveDirectory");
        BrowseDirText.Text = T("Browse");
        OpenDirText.Text = T("Open");
        BrowserCookiesHeader.Text = T("BrowserCookies");
        CookiesFileHeader.Text = T("CookiesFile");

        EmbedMetadataCheck.Content = T("EmbedMetadata");
        EmbedThumbnailCheck.Content = T("EmbedCoverArt");
        EmbedSubsCheck.Content = T("EmbedSubtitles");
        WriteThumbnailCheck.Content = T("SaveThumbnail");
        AdvancedExpanderHeader.Text = T("AdvancedHeader");
        StartTimeHeader.Text = T("StartTime");
        EndTimeHeader.Text = T("EndTime");
        PlaylistItemsHeader.Text = T("PlaylistItems");
        SponsorBlockCheck.Content = T("SponsorBlock");

        StartDownloadText.Text = T("StartDownload");
        ProfilePicButtonText.Text = T("ProfilePic");
        AddToQueueButton.Content = T("AddToQueue");
        CancelButton.Content = T("Cancel");
        LiveTerminalHeader.Text = T("LiveTerminal");
        QuickCopyText.Text = T("CopyOutput");

        QueueHeaderLabel.Text = T("QueueHeader");
        QueueParallelLabel.Text = T("QueueParallel");
        QueueAddBatchButton.Content = T("QueueAddUrls");
        StartQueueButton.Content = T("StartQueue");
        StopQueueButton.Content = T("Stop");
        ClearQueueButton.Content = T("ClearCompleted");
        QueueAllPlaylistButton.Content = T("AddAllToQueue");
        LoadAllQualitiesButton.Content = T("LoadAllQualities");
        SupportedQualitiesLabel.Text = T("SupportedQualities");

        RefreshStreamsButtonText.Text = T("RefreshStreams");
        BackendLogsHeader.Text = T("BackendLogs");
    }

    private void SaveUserSettings()
    {
        _settings.QualityIndex = QualityComboBox.SelectedIndex;
        _settings.CodecIndex = CodecComboBox.SelectedIndex;
        _settings.ConcurrentFragments = (int)(FragmentsNumeric.Value ?? 4);
        _settings.OutputDirectory = OutputDirBox.Text?.Trim() ?? string.Empty;
        _settings.CookiesBrowserIndex = CookiesBrowserComboBox.SelectedIndex;
        _settings.CookiesFilePath = CookiesFileBox.Text?.Trim() ?? string.Empty;
        _settings.EmbedMetadata = EmbedMetadataCheck.IsChecked ?? true;
        _settings.EmbedThumbnail = EmbedThumbnailCheck.IsChecked ?? true;
        _settings.EmbedSubs = EmbedSubsCheck.IsChecked ?? false;
        _settings.WriteThumbnail = WriteThumbnailCheck.IsChecked ?? false;
        _settings.SponsorBlockEnabled = SponsorBlockCheck.IsChecked ?? false;
        _settings.Save();
    }

    private string? GetSelectedCookiesBrowser() => CookiesBrowserComboBox.SelectedIndex switch
    {
        1 => "chrome",
        2 => "edge",
        3 => "firefox",
        4 => "brave",
        5 => "opera",
        6 => "vivaldi",
        7 => "safari",
        _ => null,
    };

    private string? GetSelectedCookiesFile()
    {
        var path = CookiesFileBox.Text?.Trim();
        return string.IsNullOrWhiteSpace(path) ? null : path;
    }

    private async void BrowseCookiesButton_Click(object? sender, RoutedEventArgs e)
    {
        var topLevel = TopLevel.GetTopLevel(this);
        if (topLevel == null) return;

        var files = await topLevel.StorageProvider.OpenFilePickerAsync(new FilePickerOpenOptions
        {
            Title = "Select Netscape cookies.txt File",
            AllowMultiple = false,
            FileTypeFilter =
            [
                new FilePickerFileType("Text Files") { Patterns = ["*.txt"] },
                FilePickerFileTypes.All
            ]
        });

        if (files.Count > 0)
        {
            CookiesFileBox.Text = files[0].Path.LocalPath;
            SaveUserSettings();
        }
    }

    private void ClearCookiesButton_Click(object? sender, RoutedEventArgs e)
    {
        CookiesFileBox.Text = string.Empty;
        SaveUserSettings();
    }

    private async void CheckUpdatesButton_Click(object? sender, RoutedEventArgs e)
    {
        await CheckForAppUpdatesAsync(silent: false);
    }

    private async Task CheckForAppUpdatesAsync(bool silent)
    {
        CheckUpdatesButton.IsEnabled = false;
        CheckUpdatesIcon.IsVisible = false;
        CheckUpdatesSpinner.IsVisible = true;
        CheckUpdatesText.Text = "Checking...";
        if (!silent)
        {
            BeginGlobalActivity("Checking GitHub Releases for updates...");
        }

        try
        {
            var info = await UpdateChecker.CheckForUpdatesAsync();
            _latestUpdateInfo = info;

            if (info.IsUpdateAvailable)
            {
                var sizeSuffix = info.AssetSizeBytes > 0 ? $" ({PlatformUtils.FormatBytes(info.AssetSizeBytes)})" : "";
                UpdateBannerMessage.Text = $"New version v{info.LatestVersion} is available! (Current: v{info.CurrentVersion}){sizeSuffix}";
                UpdateBanner.IsVisible = true;
                CheckUpdatesText.Text = $"Update v{info.LatestVersion}";
                if (!silent)
                {
                    GlobalStatusText.Text = $"Update available: v{info.LatestVersion}";
                }
            }
            else
            {
                UpdateBanner.IsVisible = false;
                if (!silent)
                {
                    CheckUpdatesText.Text = "Up to date!";
                    GlobalStatusText.Text = $"You are running the latest version (v{info.CurrentVersion}).";
                    DispatcherTimer.RunOnce(() => CheckUpdatesText.Text = "Check Updates", TimeSpan.FromSeconds(3));
                }
                else
                {
                    CheckUpdatesText.Text = "Check Updates";
                }
            }
        }
        catch (Exception ex)
        {
            CheckUpdatesText.Text = "Check Updates";
            if (!silent)
            {
                GlobalStatusText.Text = $"Update check failed: {ex.Message}";
            }
        }
        finally
        {
            CheckUpdatesButton.IsEnabled = true;
            CheckUpdatesIcon.IsVisible = true;
            CheckUpdatesSpinner.IsVisible = false;
            if (!silent)
            {
                EndGlobalActivity();
            }
        }
    }

    private async void DownloadUpdateButton_Click(object? sender, RoutedEventArgs e)
    {
        var info = _latestUpdateInfo;
        if (info == null || string.IsNullOrWhiteSpace(info.AssetName))
        {
            PlatformUtils.OpenUrl(info?.DownloadUrl ?? UpdateChecker.LatestReleaseWebUrl);
            return;
        }

        DownloadUpdateButton.IsEnabled = false;
        BeginGlobalActivity($"Downloading update v{info.LatestVersion}...");
        try
        {
            var progress = new Progress<double>(pct =>
            {
                Dispatcher.UIThread.Post(() =>
                {
                    UpdateBannerMessage.Text = $"Downloading v{info.LatestVersion}... {pct:F1}%";
                    GlobalStatusText.Text = $"Downloading update v{info.LatestVersion}: {pct:F1}%";
                });
            });

            var downloadedPath = await UpdateChecker.DownloadAndVerifyUpdateAsync(info, progress);
            UpdateBannerMessage.Text = $"Verified v{info.LatestVersion} (SHA-256 OK). Installing...";

            if (UpdateChecker.TryLaunchWindowsSelfReplace(downloadedPath))
            {
                Close();
                return;
            }

            PlatformUtils.OpenFolder(downloadedPath);
            UpdateBannerMessage.Text = $"Update v{info.LatestVersion} downloaded and verified!";
            GlobalStatusText.Text = $"Update ready at: {downloadedPath}";
        }
        catch (Exception ex)
        {
            UpdateBannerMessage.Text = $"Auto-download failed ({ex.Message}) — opening browser...";
            PlatformUtils.OpenUrl(info.DownloadUrl);
        }
        finally
        {
            DownloadUpdateButton.IsEnabled = true;
            EndGlobalActivity();
        }
    }

    private void ViewReleaseNotesButton_Click(object? sender, RoutedEventArgs e)
    {
        var url = _latestUpdateInfo?.ReleaseUrl ?? UpdateChecker.LatestReleaseWebUrl;
        PlatformUtils.OpenUrl(url);
    }

    private void DismissUpdateButton_Click(object? sender, RoutedEventArgs e)
    {
        UpdateBanner.IsVisible = false;
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

    private void BeginGlobalActivity(string? statusText = null)
    {
        var count = Interlocked.Increment(ref _activeTaskCount);
        Dispatcher.UIThread.Post(() =>
        {
            if (count > 0)
            {
                GlobalSpinner.IsVisible = true;
                GlobalActivityBar.IsVisible = true;
            }
            if (!string.IsNullOrWhiteSpace(statusText))
            {
                GlobalStatusText.Text = statusText;
            }
        });
    }

    private void EndGlobalActivity()
    {
        var count = Interlocked.Decrement(ref _activeTaskCount);
        if (count < 0)
        {
            Interlocked.Exchange(ref _activeTaskCount, 0);
            count = 0;
        }
        Dispatcher.UIThread.Post(() =>
        {
            if (count == 0)
            {
                GlobalSpinner.IsVisible = false;
                GlobalActivityBar.IsVisible = false;
            }
        });
    }

    private void OnProgressChanged(object? sender, DownloadProgressEvent e)
    {
        var now = Environment.TickCount64;
        if (e.Percent >= 100 || now - _lastProgressUpdateMs >= 60)
        {
            _lastProgressUpdateMs = now;
            Dispatcher.UIThread.Post(() =>
            {
                DownloadProgressBar.IsIndeterminate = false;
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
            if (status.Contains("Processing", StringComparison.OrdinalIgnoreCase) ||
                status.Contains("Merging", StringComparison.OrdinalIgnoreCase))
            {
                DownloadProgressBar.IsIndeterminate = true;
            }
        });
    }

    private void OnDownloadCompleted(object? sender, DownloadCompleteEvent e)
    {
        Dispatcher.UIThread.Post(async () =>
        {
            DownloadProgressBar.IsIndeterminate = false;
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
            DownloadProgressBar.IsIndeterminate = false;
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

        options.CookiesFile = GetSelectedCookiesFile();
        options.CookiesFromBrowser = string.IsNullOrWhiteSpace(options.CookiesFile) ? GetSelectedCookiesBrowser() : null;

        var startTime = StartTimeBox.Text?.Trim();
        if (!string.IsNullOrWhiteSpace(startTime)) options.StartTime = startTime;

        var endTime = EndTimeBox.Text?.Trim();
        if (!string.IsNullOrWhiteSpace(endTime)) options.EndTime = endTime;

        var playlistItems = PlaylistItemsBox.Text?.Trim();
        if (!string.IsNullOrWhiteSpace(playlistItems)) options.PlaylistItems = playlistItems;

        if (SponsorBlockCheck.IsChecked == true)
        {
            options.SponsorBlockRemove = "sponsor,intro,outro,selfpromo";
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

        SaveUserSettings();
        var options = BuildOptionsFromUi();
        await StartDownloadWithUrl(url, options);
    }

    private async void ProfilePicButton_Click(object? sender, RoutedEventArgs e)
    {
        var input = UrlTextBox.Text?.Trim();
        if (string.IsNullOrWhiteSpace(input))
        {
            GlobalStatusText.Text = "Enter a profile URL or platform:username (e.g. instagram:user, facebook:user, tiktok:user).";
            return;
        }

        SaveUserSettings();
        ProfilePicButton.IsEnabled = false;
        ProfilePicIcon.IsVisible = false;
        ProfilePicSpinner.IsVisible = true;
        BeginGlobalActivity("Resolving & downloading profile picture...");
        OnRawOutputReceived(this, $"[Profile] Resolving profile picture for: {input}");

        try
        {
            var customDir = OutputDirBox.Text?.Trim();
            var cookiesFile = GetSelectedCookiesFile();
            var cookiesBrowser = string.IsNullOrWhiteSpace(cookiesFile) ? GetSelectedCookiesBrowser() : null;

            var savedPath = await _client.DownloadProfilePictureAsync(
                input,
                outputDirectory: string.IsNullOrWhiteSpace(customDir) ? null : customDir,
                cookiesFromBrowser: cookiesBrowser,
                cookiesFile: cookiesFile);

            OnRawOutputReceived(this, $"[Complete] Profile picture saved: {savedPath}");
            GlobalStatusText.Text = $"Profile picture saved: {Path.GetFileName(savedPath)}";

            // Display saved image in preview card immediately
            if (File.Exists(savedPath))
            {
                try
                {
                    var bytes = await File.ReadAllBytesAsync(savedPath);
                    using var ms = new MemoryStream(bytes);
                    ThumbnailImage.Source = new Bitmap(ms);
                    PlatformBadge.Text = "PROFILE PIC";
                    VideoTitleLabel.Text = Path.GetFileName(savedPath);
                    UploaderLabel.Text = savedPath;
                    ViewsLabel.Text = PlatformUtils.FormatBytes(bytes.Length);
                    DurationBadge.IsVisible = false;
                    MetadataLoadingText.IsVisible = false;
                    MetadataCard.IsVisible = true;
                }
                catch { }
            }
        }
        catch (Exception ex)
        {
            OnRawOutputReceived(this, $"[Error] Profile picture failed: {ex.Message}");
            GlobalStatusText.Text = $"Profile picture failed: {ex.Message}";
        }
        finally
        {
            ProfilePicButton.IsEnabled = true;
            ProfilePicIcon.IsVisible = true;
            ProfilePicSpinner.IsVisible = false;
            EndGlobalActivity();
        }
    }

    private async Task StartDownloadWithUrl(string url, DownloadOptions options)
    {
        SetDownloading(true);
        ProgressCard.IsVisible = true;
        DownloadProgressBar.IsIndeterminate = true;
        DownloadProgressBar.Value = 0;
        PercentLabel.Text = "0.0%";
        DetailsLabel.Text = "Connecting & resolving stream...";
        EtaLabel.Text = "ETA: --:--";
        StatusLabel.Text = "Starting download...";
        BeginGlobalActivity("Resolving media streams & starting download...");

        _cts = new CancellationTokenSource();
        try
        {
            await _client.DownloadAsync(url, options, _cts.Token);
        }
        catch (OperationCanceledException)
        {
            StatusLabel.Text = "Download canceled.";
            GlobalStatusText.Text = "Download canceled.";
            SetDownloading(false);
        }
        catch (Exception ex)
        {
            StatusLabel.Text = $"Error: {ex.Message}";
            GlobalStatusText.Text = $"Error: {ex.Message}";
            SetDownloading(false);
        }
        finally
        {
            DownloadProgressBar.IsIndeterminate = false;
            EndGlobalActivity();
        }
    }

    private void CancelButton_Click(object? sender, RoutedEventArgs e)
    {
        _cts?.Cancel();
        _client.Cancel();
        CancelButton.IsEnabled = false;
    }

    private void AddToQueueButton_Click(object? sender, RoutedEventArgs e)
    {
        var url = UrlTextBox.Text?.Trim();
        if (string.IsNullOrWhiteSpace(url)) return;

        SaveUserSettings();
        var title = PlaylistCardsPanel.IsVisible && !string.IsNullOrWhiteSpace(PlaylistTitleLabel.Text)
            ? PlaylistTitleLabel.Text
            : MetadataCard.IsVisible && !string.IsNullOrWhiteSpace(VideoTitleLabel.Text) &&
              !VideoTitleLabel.Text.StartsWith("Fetching", StringComparison.OrdinalIgnoreCase)
                ? VideoTitleLabel.Text
                : url;

        _queueItems.Add(new QueueItemModel
        {
            Url = url,
            Title = title,
            Options = BuildOptionsFromUi(),
            StatusDetail = "Waiting in queue",
        });
        UpdateQueueSummary();
        GlobalStatusText.Text = $"Added to queue ({_queueItems.Count} total).";
    }

    private void QueueAddBatchButton_Click(object? sender, RoutedEventArgs e)
    {
        var raw = QueueBatchUrlsBox.Text;
        if (string.IsNullOrWhiteSpace(raw)) return;

        SaveUserSettings();
        var lines = raw.Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries)
            .Select(l => l.Trim())
            .Where(l => Uri.TryCreate(l, UriKind.Absolute, out var u) && (u.Scheme == Uri.UriSchemeHttp || u.Scheme == Uri.UriSchemeHttps))
            .ToList();

        foreach (var line in lines)
        {
            _queueItems.Add(new QueueItemModel
            {
                Url = line,
                Title = line,
                Options = BuildOptionsFromUi(),
                StatusDetail = "Waiting in queue",
            });
        }

        QueueBatchUrlsBox.Text = string.Empty;
        UpdateQueueSummary();
        GlobalStatusText.Text = $"Added {lines.Count} URL(s) to queue.";
    }

    private async void StartQueueButton_Click(object? sender, RoutedEventArgs e)
    {
        if (_isQueueRunning) return;
        var pending = _queueItems.Where(q => q.Status == QueueItemStatus.Queued || q.Status == QueueItemStatus.Failed || q.Status == QueueItemStatus.Canceled).ToList();
        if (pending.Count == 0) return;

        foreach (var item in pending)
        {
            item.Status = QueueItemStatus.Queued;
            item.Progress = 0;
            item.StatusDetail = "Waiting in queue";
        }

        _isQueueRunning = true;
        _queueCts = new CancellationTokenSource();
        var token = _queueCts.Token;
        StartQueueButton.IsEnabled = false;
        StopQueueButton.IsEnabled = true;

        var maxParallel = Math.Clamp((int)(QueueConcurrencyNumeric.Value ?? 2), 1, 3);
        using var semaphore = new SemaphoreSlim(maxParallel, maxParallel);
        BeginGlobalActivity($"Running download queue ({pending.Count} items, {maxParallel} parallel)...");

        try
        {
            var tasks = pending.Select(async item =>
            {
                await semaphore.WaitAsync(token);
                try
                {
                    if (token.IsCancellationRequested) return;
                    Dispatcher.UIThread.Post(() =>
                    {
                        item.Status = QueueItemStatus.Downloading;
                        item.StatusDetail = "Starting download...";
                    });

                    var worker = new DownloaderClient();
                    worker.RawOutputReceived += OnRawOutputReceived;
                    worker.ProgressChanged += (_, prog) =>
                    {
                        Dispatcher.UIThread.Post(() =>
                        {
                            item.Progress = prog.Percent;
                            item.StatusDetail = $"{prog.Percent:F1}% • {prog.SpeedFormatted} • ETA {prog.EtaFormatted}";
                        });
                    };
                    worker.StatusChanged += (_, st) =>
                    {
                        Dispatcher.UIThread.Post(() => item.StatusDetail = st);
                    };

                    var result = await worker.DownloadAsync(item.Url, item.Options, token);
                    Dispatcher.UIThread.Post(() =>
                    {
                        if (!string.IsNullOrWhiteSpace(result.Title)) item.Title = result.Title;
                        item.Progress = 100;
                        item.Status = QueueItemStatus.Completed;
                        item.StatusDetail = "Completed";
                        UpdateQueueSummary();
                    });
                }
                catch (OperationCanceledException)
                {
                    Dispatcher.UIThread.Post(() =>
                    {
                        item.Status = QueueItemStatus.Canceled;
                        item.StatusDetail = "Canceled";
                        UpdateQueueSummary();
                    });
                }
                catch (Exception ex)
                {
                    Dispatcher.UIThread.Post(() =>
                    {
                        item.Status = QueueItemStatus.Failed;
                        item.StatusDetail = ex.Message;
                        UpdateQueueSummary();
                    });
                }
                finally
                {
                    semaphore.Release();
                }
            }).ToList();

            await Task.WhenAll(tasks);
            await LoadHistoryAsync();
            GlobalStatusText.Text = "Download queue finished.";
        }
        catch (OperationCanceledException)
        {
            GlobalStatusText.Text = "Download queue stopped.";
        }
        finally
        {
            _isQueueRunning = false;
            StartQueueButton.IsEnabled = true;
            StopQueueButton.IsEnabled = false;
            UpdateQueueSummary();
            EndGlobalActivity();
        }
    }

    private void StopQueueButton_Click(object? sender, RoutedEventArgs e)
    {
        _queueCts?.Cancel();
        StopQueueButton.IsEnabled = false;
    }

    private void ClearQueueButton_Click(object? sender, RoutedEventArgs e)
    {
        for (int i = _queueItems.Count - 1; i >= 0; i--)
        {
            if (_queueItems[i].Status != QueueItemStatus.Downloading)
            {
                _queueItems.RemoveAt(i);
            }
        }
        UpdateQueueSummary();
    }

    private void RemoveQueueItem_Click(object? sender, RoutedEventArgs e)
    {
        if (sender is Button btn && btn.DataContext is QueueItemModel item && item.Status != QueueItemStatus.Downloading)
        {
            _queueItems.Remove(item);
            UpdateQueueSummary();
        }
    }

    private void UpdateQueueSummary()
    {
        var total = _queueItems.Count;
        var done = _queueItems.Count(q => q.Status == QueueItemStatus.Completed);
        var active = _queueItems.Count(q => q.Status == QueueItemStatus.Downloading);
        QueueSummaryLabel.Text = active > 0
            ? $"{active} downloading • {done}/{total} completed"
            : $"{total} items in queue ({done} completed)";
    }

    private async void InspectButton_Click(object? sender, RoutedEventArgs e)
    {
        var url = UrlTextBox.Text?.Trim();
        if (string.IsNullOrWhiteSpace(url)) return;

        // Show loading state across Download button, Streams button, Streams tab, and global footer
        InspectButton.IsEnabled = false;
        RefreshStreamsButton.IsEnabled = false;
        InspectIconPath.IsVisible = false;
        InspectSpinner.IsVisible = true;
        InspectButtonText.Text = "Inspecting...";
        RefreshStreamsIconPath.IsVisible = false;
        RefreshStreamsSpinner.IsVisible = true;
        RefreshStreamsButtonText.Text = "Inspecting...";

        MainTabControl.SelectedItem = StreamsTab;
        StreamsLoadingLabel.Text = "Inspecting available video & audio streams...";
        StreamsLoadingPanel.IsVisible = true;
        StreamsListBox.IsVisible = false;
        StreamsStatusHeader.Text = $"Inspecting available streams for: {url}...";
        BeginGlobalActivity("Inspecting stream formats...");

        try
        {
            var cookiesFile = GetSelectedCookiesFile();
            var cookiesBrowser = string.IsNullOrWhiteSpace(cookiesFile) ? GetSelectedCookiesBrowser() : null;
            var formats = await _client.GetFormatsAsync(url, cookiesFromBrowser: cookiesBrowser, cookiesFile: cookiesFile);
            StreamsListBox.ItemsSource = formats;
            var isImageList = formats.Count > 0 && formats.All(f => f.IsImage);
            StreamsStatusHeader.Text = isImageList
                ? $"Found {formats.Count} verified picture(s) for: {url}"
                : $"Found {formats.Count} streams for: {url}";
            GlobalStatusText.Text = isImageList
                ? $"Found {formats.Count} verified picture(s) available."
                : $"Found {formats.Count} streams available.";
        }
        catch (Exception ex)
        {
            StreamsStatusHeader.Text = $"Inspection failed: {ex.Message}";
            GlobalStatusText.Text = $"Inspection failed: {ex.Message}";
        }
        finally
        {
            StreamsLoadingPanel.IsVisible = false;
            StreamsListBox.IsVisible = true;
            InspectButton.IsEnabled = true;
            RefreshStreamsButton.IsEnabled = true;
            InspectIconPath.IsVisible = true;
            InspectSpinner.IsVisible = false;
            InspectButtonText.Text = "Inspect Streams";
            RefreshStreamsIconPath.IsVisible = true;
            RefreshStreamsSpinner.IsVisible = false;
            RefreshStreamsButtonText.Text = "Refresh Streams";
            EndGlobalActivity();
        }
    }

    private async void DownloadStream_Click(object? sender, RoutedEventArgs e)
    {
        if (sender is Button btn && btn.DataContext is FormatInfoModel format)
        {
            var url = UrlTextBox.Text?.Trim();
            if (string.IsNullOrWhiteSpace(url)) return;

            MainTabControl.SelectedIndex = 0; // Switch to Download tab

            if (format.IsImage && !string.IsNullOrWhiteSpace(format.DirectUrl))
            {
                SaveUserSettings();
                BeginGlobalActivity($"Downloading {format.ResolutionFormatted} image...");
                OnRawOutputReceived(this, $"[Profile] Downloading selected image ({format.ResolutionFormatted}, {format.FormatNote})...");
                try
                {
                    var customDir = OutputDirBox.Text?.Trim();
                    var cookiesFile = GetSelectedCookiesFile();
                    var cookiesBrowser = string.IsNullOrWhiteSpace(cookiesFile) ? GetSelectedCookiesBrowser() : null;

                    var savedPath = await _client.DownloadDirectImageAsync(
                        format.DirectUrl,
                        sourceProfileUrl: url,
                        outputDirectory: string.IsNullOrWhiteSpace(customDir) ? null : customDir,
                        cookiesFromBrowser: cookiesBrowser,
                        cookiesFile: cookiesFile);

                    OnRawOutputReceived(this, $"[Complete] Image saved: {savedPath}");
                    GlobalStatusText.Text = $"Image saved: {Path.GetFileName(savedPath)}";

                    if (File.Exists(savedPath))
                    {
                        try
                        {
                            var bytes = await File.ReadAllBytesAsync(savedPath);
                            using var ms = new MemoryStream(bytes);
                            ThumbnailImage.Source = new Bitmap(ms);
                            PlatformBadge.Text = format.ResolutionFormatted;
                            VideoTitleLabel.Text = Path.GetFileName(savedPath);
                            UploaderLabel.Text = savedPath;
                            ViewsLabel.Text = PlatformUtils.FormatBytes(bytes.Length);
                            DurationBadge.IsVisible = false;
                            MetadataLoadingText.IsVisible = false;
                            MetadataCard.IsVisible = true;
                        }
                        catch { }
                    }
                }
                catch (Exception ex)
                {
                    OnRawOutputReceived(this, $"[Error] Image download failed: {ex.Message}");
                    GlobalStatusText.Text = $"Image download failed: {ex.Message}";
                }
                finally
                {
                    EndGlobalActivity();
                }
                return;
            }

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
            SaveUserSettings();
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
            ClearPlaylistCards();
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
                ClearPlaylistCards();
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

        ClearPlaylistCards();
        SingleVideoQualitiesPanel.IsVisible = false;
        SingleVideoQualitiesItems.ItemsSource = null;
        PlatformBadge.Text = platformDisplay;
        VideoTitleLabel.Text = "Fetching media details...";
        UploaderLabel.Text = uri.Host;
        ViewsLabel.Text = "";
        DurationBadge.IsVisible = false;
        ThumbnailImage.Source = null;
        ThumbnailSpinner.IsVisible = true;
        MetadataHeaderSpinner.IsVisible = true;
        MetadataProgressBar.IsVisible = true;
        MetadataLoadingText.Text = "Loading details...";
        MetadataLoadingText.IsVisible = true;
        MetadataCard.IsVisible = true;
        BeginGlobalActivity("Fetching video metadata & thumbnail...");

        try
        {
            var cookiesFile = GetSelectedCookiesFile();
            var cookiesBrowser = string.IsNullOrWhiteSpace(cookiesFile) ? GetSelectedCookiesBrowser() : null;
            var meta = await _client.GetMetadataAsync(rawUrl, token, cookiesFromBrowser: cookiesBrowser, cookiesFile: cookiesFile);
            if (token.IsCancellationRequested) return;

            if (meta != null && meta.IsPlaylist && meta.Entries.Count > 0)
            {
                DisplayPlaylistCards(meta, uri, cookiesBrowser, cookiesFile);
                GlobalStatusText.Text = $"Loaded playlist ({meta.Entries.Count} videos): {meta.Title}";
            }
            else if (meta != null && !string.IsNullOrWhiteSpace(meta.Title))
            {
                MetadataLoadingText.IsVisible = false;
                MetadataHeaderSpinner.IsVisible = false;
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

                if (meta.Qualities.Count > 0)
                {
                    SingleVideoQualitiesItems.ItemsSource = meta.Qualities;
                    SingleVideoQualitiesPanel.IsVisible = true;
                }

                if (!string.IsNullOrWhiteSpace(meta.Thumbnail))
                {
                    await LoadThumbnailAsync(meta.Thumbnail, token);
                }

                GlobalStatusText.Text = $"Loaded media preview: {meta.Title}";
            }
            else
            {
                MetadataLoadingText.Text = "Ready to download";
                GlobalStatusText.Text = "Ready";
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
                GlobalStatusText.Text = "Ready";
            }
        }
        finally
        {
            if (!token.IsCancellationRequested)
            {
                ThumbnailSpinner.IsVisible = false;
                MetadataHeaderSpinner.IsVisible = false;
                MetadataProgressBar.IsVisible = false;
            }
            EndGlobalActivity();
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

    private void ClearPlaylistCards()
    {
        _playlistQualityCts?.Cancel();
        _playlistQualityCts?.Dispose();
        _playlistQualityCts = null;
        _playlistCards.Clear();
        PlaylistCardsPanel.IsVisible = false;
        PlaylistScanSpinner.IsVisible = false;
        PlaylistScanStatusLabel.Text = string.Empty;
        LoadAllQualitiesButton.IsVisible = false;
    }

    private void DisplayPlaylistCards(MediaMetadataModel meta, Uri uri, string? cookiesBrowser, string? cookiesFile)
    {
        MetadataCard.IsVisible = false;
        _playlistCards.Clear();

        PlaylistPlatformBadge.Text = !string.IsNullOrWhiteSpace(meta.Platform)
            ? $"{meta.Platform.ToUpperInvariant()} PLAYLIST"
            : "PLAYLIST";
        PlaylistCountBadge.Text = meta.Entries.Count == 1 ? "1 video" : $"{meta.Entries.Count} videos";
        PlaylistTitleLabel.Text = meta.Title;
        PlaylistUploaderLabel.Text = !string.IsNullOrWhiteSpace(meta.Uploader) ? meta.Uploader : uri.Host;

        var autoInspectCards = new List<PlaylistVideoCardModel>();
        var manualCards = 0;

        for (int i = 0; i < meta.Entries.Count; i++)
        {
            var card = PlaylistVideoCardModel.FromEntry(meta.Entries[i]);
            if (!card.HasQualities)
            {
                if (autoInspectCards.Count < AutoInspectPlaylistQualityLimit)
                {
                    card.IsLoadingQualities = true;
                    autoInspectCards.Add(card);
                }
                else
                {
                    card.NeedsManualQualityLoad = true;
                    manualCards++;
                }
            }
            _playlistCards.Add(card);
        }

        LoadAllQualitiesButton.IsVisible = manualCards > 0;
        PlaylistCardsPanel.IsVisible = true;

        _playlistQualityCts = new CancellationTokenSource();
        var ct = _playlistQualityCts.Token;

        _ = LoadPlaylistThumbnailsAsync(_playlistCards.ToList(), ct);
        if (autoInspectCards.Count > 0)
        {
            _ = LoadPlaylistCardQualitiesAsync(autoInspectCards, cookiesBrowser, cookiesFile, ct);
        }
    }

    private async Task LoadPlaylistThumbnailsAsync(List<PlaylistVideoCardModel> cards, CancellationToken token)
    {
        using var semaphore = new SemaphoreSlim(4, 4);
        var tasks = cards.Select(async card =>
        {
            if (string.IsNullOrWhiteSpace(card.ThumbnailUrl))
            {
                Dispatcher.UIThread.Post(() => card.IsThumbnailLoading = false);
                return;
            }

            try
            {
                await semaphore.WaitAsync(token);
                try
                {
                    var bytes = await _httpClient.GetByteArrayAsync(card.ThumbnailUrl, token);
                    if (token.IsCancellationRequested || bytes == null || bytes.Length == 0) return;

                    await Dispatcher.UIThread.InvokeAsync(() =>
                    {
                        using var ms = new MemoryStream(bytes);
                        card.ThumbnailBitmap = new Bitmap(ms);
                        card.IsThumbnailLoading = false;
                    });
                }
                finally
                {
                    semaphore.Release();
                }
            }
            catch
            {
                if (!token.IsCancellationRequested)
                {
                    Dispatcher.UIThread.Post(() => card.IsThumbnailLoading = false);
                }
            }
        }).ToList();

        try { await Task.WhenAll(tasks); } catch { }
    }

    private async Task LoadPlaylistCardQualitiesAsync(
        List<PlaylistVideoCardModel> cards,
        string? cookiesBrowser,
        string? cookiesFile,
        CancellationToken token)
    {
        int total = cards.Count;
        int completed = 0;

        Dispatcher.UIThread.Post(() =>
        {
            PlaylistScanSpinner.IsVisible = true;
            PlaylistScanStatusLabel.Text = $"Loading supported qualities (0/{total})...";
        });

        using var semaphore = new SemaphoreSlim(3, 3);
        var tasks = cards.Select(async card =>
        {
            try
            {
                await semaphore.WaitAsync(token);
                try
                {
                    if (token.IsCancellationRequested) return;
                    await LoadSingleCardQualitiesAsync(card, cookiesBrowser, cookiesFile, token);
                }
                finally
                {
                    semaphore.Release();
                    var done = Interlocked.Increment(ref completed);
                    if (!token.IsCancellationRequested)
                    {
                        Dispatcher.UIThread.Post(() =>
                        {
                            PlaylistScanStatusLabel.Text = done < total
                                ? $"Loading supported qualities ({done}/{total})..."
                                : $"Supported qualities loaded ({total}/{total})";
                        });
                    }
                }
            }
            catch (OperationCanceledException) { }
        }).ToList();

        try
        {
            await Task.WhenAll(tasks);
        }
        catch (OperationCanceledException) { }
        finally
        {
            if (!token.IsCancellationRequested)
            {
                Dispatcher.UIThread.Post(() =>
                {
                    PlaylistScanSpinner.IsVisible = false;
                    LoadAllQualitiesButton.IsVisible = _playlistCards.Any(c => c.NeedsManualQualityLoad);
                });
            }
        }
    }

    private static async Task LoadSingleCardQualitiesAsync(
        PlaylistVideoCardModel card,
        string? cookiesBrowser,
        string? cookiesFile,
        CancellationToken token)
    {
        Dispatcher.UIThread.Post(() =>
        {
            card.NeedsManualQualityLoad = false;
            card.IsLoadingQualities = true;
        });

        try
        {
            var worker = new DownloaderClient();
            var formats = await worker.GetFormatsAsync(card.Url, token, cookiesFromBrowser: cookiesBrowser, cookiesFile: cookiesFile);
            if (token.IsCancellationRequested) return;

            var qualities = FormatInfoModel.ExtractSupportedQualities(formats);
            Dispatcher.UIThread.Post(() => card.SetQualities(qualities));
        }
        catch (OperationCanceledException) { }
        catch
        {
            if (!token.IsCancellationRequested)
            {
                Dispatcher.UIThread.Post(() =>
                {
                    card.IsLoadingQualities = false;
                    card.QualityStatusText = "Best available (default)";
                });
            }
        }
    }

    private DownloadOptions BuildOptionsForPlaylistCard(PlaylistVideoCardModel card)
    {
        var options = BuildOptionsFromUi();
        options.PlaylistItems = null; // Target this individual video directly

        var q = card.SelectedQualityValue;
        if (string.Equals(q, "audio", StringComparison.OrdinalIgnoreCase))
        {
            options.Quality = "audio";
            options.AudioOnly = true;
            options.AudioFormat = "mp3";
            options.AudioQuality = "320k";
        }
        else
        {
            options.AudioOnly = false;
            options.Quality = string.IsNullOrWhiteSpace(q) ? "best" : q;
        }

        return options;
    }

    private void PlaylistQualityChip_Click(object? sender, RoutedEventArgs e)
    {
        if (sender is Button btn && btn.DataContext is QualityOptionChip chip)
        {
            chip.Owner?.SelectQuality(chip);
        }
    }

    private async void DownloadPlaylistCard_Click(object? sender, RoutedEventArgs e)
    {
        if (sender is Button btn && btn.DataContext is PlaylistVideoCardModel card)
        {
            SaveUserSettings();
            var options = BuildOptionsForPlaylistCard(card);
            await StartDownloadWithUrl(card.Url, options);
        }
    }

    private void QueuePlaylistCard_Click(object? sender, RoutedEventArgs e)
    {
        if (sender is Button btn && btn.DataContext is PlaylistVideoCardModel card)
        {
            SaveUserSettings();
            _queueItems.Add(new QueueItemModel
            {
                Url = card.Url,
                Title = card.Title,
                Options = BuildOptionsForPlaylistCard(card),
                StatusDetail = "Waiting in queue",
            });
            card.IsQueued = true;
            UpdateQueueSummary();
            GlobalStatusText.Text = $"Added '{card.Title}' to queue ({_queueItems.Count} total).";
        }
    }

    private void QueueAllPlaylistButton_Click(object? sender, RoutedEventArgs e)
    {
        if (_playlistCards.Count == 0) return;

        SaveUserSettings();
        int added = 0;
        foreach (var card in _playlistCards)
        {
            _queueItems.Add(new QueueItemModel
            {
                Url = card.Url,
                Title = card.Title,
                Options = BuildOptionsForPlaylistCard(card),
                StatusDetail = "Waiting in queue",
            });
            card.IsQueued = true;
            added++;
        }

        UpdateQueueSummary();
        GlobalStatusText.Text = $"Added {added} playlist video(s) to queue ({_queueItems.Count} total).";
    }

    private async void LoadCardQualities_Click(object? sender, RoutedEventArgs e)
    {
        if (sender is Button btn && btn.DataContext is PlaylistVideoCardModel card)
        {
            var cookiesFile = GetSelectedCookiesFile();
            var cookiesBrowser = string.IsNullOrWhiteSpace(cookiesFile) ? GetSelectedCookiesBrowser() : null;
            var ct = _playlistQualityCts?.Token ?? CancellationToken.None;
            await LoadSingleCardQualitiesAsync(card, cookiesBrowser, cookiesFile, ct);
            LoadAllQualitiesButton.IsVisible = _playlistCards.Any(c => c.NeedsManualQualityLoad);
        }
    }

    private void LoadAllQualitiesButton_Click(object? sender, RoutedEventArgs e)
    {
        var remaining = _playlistCards.Where(c => c.NeedsManualQualityLoad).ToList();
        if (remaining.Count == 0)
        {
            LoadAllQualitiesButton.IsVisible = false;
            return;
        }

        LoadAllQualitiesButton.IsVisible = false;
        var cookiesFile = GetSelectedCookiesFile();
        var cookiesBrowser = string.IsNullOrWhiteSpace(cookiesFile) ? GetSelectedCookiesBrowser() : null;
        var ct = _playlistQualityCts?.Token ?? CancellationToken.None;
        _ = LoadPlaylistCardQualitiesAsync(remaining, cookiesBrowser, cookiesFile, ct);
    }

    private async Task LoadHistoryAsync(string? search = null)
    {
        HistoryLoadingBar.IsVisible = true;
        BeginGlobalActivity("Loading download history...");
        try
        {
            var records = await _client.GetHistoryAsync(limit: 50, search: search);
            HistoryListBox.ItemsSource = records;
            GlobalStatusText.Text = "Ready";
        }
        catch { }
        finally
        {
            HistoryLoadingBar.IsVisible = false;
            EndGlobalActivity();
        }
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
