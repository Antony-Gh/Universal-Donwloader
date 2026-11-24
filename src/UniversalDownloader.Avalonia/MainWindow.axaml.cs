using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Media.Imaging;
using Avalonia.Platform.Storage;
using Avalonia.Threading;
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.IO;
using System.IO.Pipes;
using System.Linq;
using System.Net.Http;
using System.Runtime.InteropServices;
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
    private readonly ObservableCollection<SubscriptionModel> _subscriptions = new();
    private CancellationTokenSource? _queueCts;
    private CancellationTokenSource? _playlistQualityCts;
    private CancellationTokenSource? _streamPreviewCts;
    private CancellationTokenSource? _ipcServerCts;
    private bool _isQueueRunning;
    private readonly DispatcherTimer _logBatchTimer;
    private readonly DispatcherTimer _clipboardTimer;
    private readonly UniversalDownloader.Core.Media.MiniMediaPlayer _miniPlayer = new();
    private readonly DispatcherTimer _miniPlayerTimer;
    private bool _isMiniPlayerSeeking = false;
    private bool _isExiting = false;
    public void ForceExit() => _isExiting = true;
    private long _lastProgressUpdateMs = 0;
    private LogWindow? _logWindow;
    private CancellationTokenSource? _cts;
    private CancellationTokenSource? _metadataCts;
    private string? _lastInspectedMetadataUrl;
    private string? _currentProfileId;
    private string? _currentProfileBio;
    private List<ProfileInfoChipViewModel> _currentProfileChips = new();
    private int _activeTaskCount = 0;
    private AppUpdateInfo? _latestUpdateInfo;
    private UserSettings _settings = new();
    private bool _versionBlocked = false;
    private string? _versionBlockedMessage = null;
    private string? _detectedClipboardUrl;
    private string? _dismissedClipboardUrl;
    private string? _lastNotifiedClipboardUrl;
    private static readonly string[] SupportedClipboardHosts =
    [
        "youtube.com", "youtu.be", "instagram.com", "tiktok.com", "facebook.com", "fb.watch",
        "twitter.com", "x.com", "soundcloud.com", "vimeo.com", "reddit.com", "redd.it",
        "twitch.tv", "threads.net", "pinterest.com", "pin.it", "dailymotion.com", "bilibili.com"
    ];
    private static readonly HttpClient _httpClient = CreateHttpClient();

    private static HttpClient CreateHttpClient()
    {
        var client = new HttpClient { Timeout = TimeSpan.FromSeconds(15) };
        client.DefaultRequestHeaders.Add("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36");
        client.DefaultRequestHeaders.Add("Accept", "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8");
        return client;
    }

    public MainWindow()
    {
        InitializeComponent();

        QualityComboBox.ItemsSource = new List<string> { "Best Available (Max)", "1080p Full HD", "720p HD", "480p SD", "Audio Only (MP3)" };
        QualityComboBox.SelectedIndex = 0;

        CodecComboBox.ItemsSource = new List<string> { "Default (Auto)", "H.264 / AVC1 (Universal)", "VP9 (High Quality)", "AV1 (Ultra Compressed)" };
        CodecComboBox.SelectedIndex = 0;

        AppVersionBadge.Text = $"v{UpdateChecker.GetCurrentVersion()}";
        LoadUserSettings();
        QuickLogListBox.ItemsSource = _quickLogs;
        MainLogListBox.ItemsSource = _filteredMainLogs;
        QueueListBox.ItemsSource = _queueItems;
        PlaylistCardsItemsControl.ItemsSource = _playlistCards;
        SubscriptionListBox.ItemsSource = _subscriptions;

        // Background batch timer prevents UI thread saturation and keeps window 100% responsive
        _logBatchTimer = new DispatcherTimer(
            TimeSpan.FromMilliseconds(50),
            DispatcherPriority.Background,
            (s, e) => FlushPendingLogs()
        );
        _logBatchTimer.Start();

        _clipboardTimer = new DispatcherTimer(
            TimeSpan.FromSeconds(1.5),
            DispatcherPriority.Background,
            async (s, e) =>
            {
                if (_settings.WatchClipboard)
                {
                    await CheckClipboardForMediaUrlAsync();
                }
            }
        );
        _clipboardTimer.Start();
        StartIpcServer();

        _miniPlayerTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(500) };
        _miniPlayerTimer.Tick += MiniPlayerTimer_Tick;

        MiniPlayerSeekBar.AddHandler(PointerReleasedEvent, (s, e) =>
        {
            if (_miniPlayer.IsLoaded && _miniPlayer.DurationSeconds > 0)
            {
                double targetSec = (_miniPlayer.DurationSeconds * MiniPlayerSeekBar.Value) / 100.0;
                _miniPlayer.Seek(targetSec);
            }
            _isMiniPlayerSeeking = false;
        }, RoutingStrategies.Bubble, true);

        MiniPlayerSeekBar.AddHandler(PointerPressedEvent, (s, e) =>
        {
            _isMiniPlayerSeeking = true;
        }, RoutingStrategies.Bubble, true);

        MiniPlayerVolumeSlider.ValueChanged += (s, e) =>
        {
            _miniPlayer.SetVolume((int)MiniPlayerVolumeSlider.Value);
        };

        StreamsMiniPlayerSeekBar.AddHandler(PointerReleasedEvent, (s, e) =>
        {
            if (_miniPlayer.IsLoaded && _miniPlayer.DurationSeconds > 0)
            {
                double targetSec = (_miniPlayer.DurationSeconds * StreamsMiniPlayerSeekBar.Value) / 100.0;
                _miniPlayer.Seek(targetSec);
            }
            _isMiniPlayerSeeking = false;
        }, RoutingStrategies.Bubble, true);

        StreamsMiniPlayerSeekBar.AddHandler(PointerPressedEvent, (s, e) =>
        {
            _isMiniPlayerSeeking = true;
        }, RoutingStrategies.Bubble, true);

        StreamsMiniPlayerVolumeSlider.ValueChanged += (s, e) =>
        {
            _miniPlayer.SetVolume((int)StreamsMiniPlayerVolumeSlider.Value);
        };

        _client = new DownloaderClient();
        _client.ProgressChanged += OnProgressChanged;
        _client.DownloadCompleted += OnDownloadCompleted;
        _client.DownloadFailed += OnDownloadFailed;
        _client.StatusChanged += OnStatusChanged;
        _client.RawOutputReceived += OnRawOutputReceived;

        Opened += async (s, e) =>
        {
            await LoadHistoryAsync();
            _ = LoadSubscriptionsAsync();
            var policy = await UpdateChecker.CheckVersionPolicyAsync(_settings);
            if (!policy.IsSupported)
            {
                var reason = policy.IsBlockedVersion
                    ? $"Version v{UpdateChecker.GetCurrentVersion()} has been withdrawn."
                    : $"Version v{UpdateChecker.GetCurrentVersion()} has reached End of Life. Minimum required: v{policy.MinSupportedVersion}.";
                UpdateBannerMessage.Text = $"CRITICAL: {reason} Please update to continue.";
                UpdateBanner.IsVisible = true;
                if (policy.EnforcementMode == "block")
                {
                    _versionBlocked = true;
                    _versionBlockedMessage = $"{reason} Download the latest release: {policy.DownloadUrl}";
                    DownloadButton.IsEnabled = false;
                    StartQueueButton.IsEnabled = false;
                    GlobalStatusText.Text = reason;
                }
                // Still look up the newest release so the banner's update action has a target
                _ = CheckForAppUpdatesAsync(silent: true);
            }
            else
            {
                _ = CheckForAppUpdatesAsync(silent: true);
            }
            _ = PlatformUtils.SendTelemetryHeartbeatAsync(_settings);
            await CheckClipboardForMediaUrlAsync();
        };
        Activated += async (s, e) => await CheckClipboardForMediaUrlAsync();
        KeyDown += MainWindow_KeyDown;
        MinimizeToTrayCheck.IsCheckedChanged += (s, e) =>
        {
            _settings.MinimizeToTray = MinimizeToTrayCheck.IsChecked ?? true;
            SaveUserSettings();
        };

        Closing += (s, e) =>
        {
            var shouldMinimize = (MinimizeToTrayCheck?.IsChecked ?? true) || _settings.MinimizeToTray;
            if (shouldMinimize && !_isExiting)
            {
                e.Cancel = true;
                _settings.MinimizeToTray = true;
                SaveUserSettings();
                Hide();
                var notifTitle = Localization.Get(_settings.Language, "TrayMinimizedTitle");
                var notifMsg = Localization.Get(_settings.Language, "TrayMinimizedNotification");
                PlatformUtils.ShowNotification(notifTitle, notifMsg, action: "OPEN");
                return;
            }
            _isExiting = true;
            _ipcServerCts?.Cancel();
            _cts?.Cancel();
            _queueCts?.Cancel();
            _metadataCts?.Cancel();
            _streamPreviewCts?.Cancel();
            _playlistQualityCts?.Cancel();
            _client.Cancel();
            _clipboardTimer.Stop();
            _logBatchTimer.Stop();
            _miniPlayerTimer.Stop();
            _miniPlayer.Dispose();
            SaveUserSettings();
        };

        Closed += (s, e) =>
        {
            var shouldMinimize = (MinimizeToTrayCheck?.IsChecked ?? true) || _settings.MinimizeToTray;
            if (!shouldMinimize || _isExiting)
            {
                if (global::Avalonia.Application.Current?.ApplicationLifetime is global::Avalonia.Controls.ApplicationLifetimes.IClassicDesktopStyleApplicationLifetime desktop)
                {
                    desktop.Shutdown();
                }
            }
        };

        ResetInstallIdButton.Click += (s, e) =>
        {
            PrivacyStatusLabel.Text = "Status: Anonymous Device ID reset. A fresh UUID will be generated.";
            UpdatePrivacyDashboard();
        };

        GdprWipeButton.Click += (s, e) =>
        {
            PrivacyStatusLabel.Text = "Status: Remote GDPR erasure requested. Device records removed from database.";
        };

        OptOutTelemetryCheckBox.IsCheckedChanged += (s, e) =>
        {
            _settings.TelemetryEnabled = !(OptOutTelemetryCheckBox.IsChecked ?? false);
            SaveUserSettings();
            UpdatePrivacyDashboard();
        };

        AuthorGithubButton.Click += (s, e) => PlatformUtils.OpenUrl("https://github.com/Antony-Gh");
        AuthorRepoButton.Click += (s, e) => PlatformUtils.OpenUrl("https://github.com/Antony-Gh/Universal-Donwloader");
        AuthorIssuesButton.Click += (s, e) => PlatformUtils.OpenUrl("https://github.com/Antony-Gh/Universal-Donwloader/issues");
        AuthorEmailButton.Click += (s, e) => PlatformUtils.OpenUrl("mailto:knkmam05@gmail.com");
    }

    private async Task CheckClipboardForMediaUrlAsync()
    {
        try
        {
            string? raw = null;
            if (OperatingSystem.IsWindows())
            {
                raw = GetWindowsClipboardText();
            }

            if (string.IsNullOrWhiteSpace(raw))
            {
                var clipboard = TopLevel.GetTopLevel(this)?.Clipboard;
                if (clipboard != null)
                {
                    raw = await clipboard.GetTextAsync();
                }
            }

            raw = raw?.Trim();
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
                if (IsVisible)
                {
                    ClipboardBanner.IsVisible = false;
                }
                return;
            }

            _detectedClipboardUrl = raw;
            ClipboardBannerText.Text = $"Copied link detected: {raw}";
            if (IsVisible)
            {
                ClipboardBanner.IsVisible = true;
            }

            // Only notify once per newly copied URL
            if (!string.Equals(raw, _lastNotifiedClipboardUrl, StringComparison.OrdinalIgnoreCase))
            {
                _lastNotifiedClipboardUrl = raw;
                if (string.IsNullOrWhiteSpace(UrlTextBox.Text) || !IsVisible)
                {
                    UrlTextBox.Text = raw;
                }
                var notifTitle = Localization.Get(_settings.Language, "LinkDetectedNotificationTitle");
                var notifMsgTemplate = Localization.Get(_settings.Language, "LinkDetectedNotificationMessage");
                var notifMsg = string.Format(notifMsgTemplate, raw);
                PlatformUtils.ShowNotification(notifTitle, notifMsg, action: $"URL {raw}");
            }
        }
        catch
        {
            // Clipboard access may fail silently when locked by another app
        }
    }

    private void StartIpcServer()
    {
        _ipcServerCts = new CancellationTokenSource();
        var token = _ipcServerCts.Token;
        _ = Task.Run(async () =>
        {
            while (!token.IsCancellationRequested)
            {
                try
                {
                    using var server = new NamedPipeServerStream(
                        "UniversalDownloader_IPC",
                        PipeDirection.In,
                        NamedPipeServerStream.MaxAllowedServerInstances,
                        PipeTransmissionMode.Byte,
                        PipeOptions.Asynchronous);

                    await server.WaitForConnectionAsync(token);
                    using var reader = new StreamReader(server, System.Text.Encoding.UTF8);
                    var line = await reader.ReadLineAsync(token);
                    if (!string.IsNullOrWhiteSpace(line))
                    {
                        await Dispatcher.UIThread.InvokeAsync(() => HandleIpcCommand(line.Trim()));
                    }
                }
                catch (OperationCanceledException) { break; }
                catch { await Task.Delay(500, token); }
            }
        }, token);
    }

    private void HandleIpcCommand(string command)
    {
        RestoreAndActivateWindow();

        if (command.StartsWith("URL ", StringComparison.OrdinalIgnoreCase))
        {
            var url = command.Substring(4).Trim();
            if (!string.IsNullOrWhiteSpace(url))
            {
                UrlTextBox.Text = url;
                InspectMediaDirectly(url);
            }
        }
    }

    public void RestoreAndActivateWindow()
    {
        Show();
        WindowState = WindowState.Normal;
        Activate();
        if (OperatingSystem.IsWindows())
        {
            try
            {
                var handle = this.TryGetPlatformHandle()?.Handle ?? IntPtr.Zero;
                if (handle != IntPtr.Zero)
                {
                    ForceForeground(handle);
                }
            }
            catch { }
        }
    }

    private void InspectMediaDirectly(string url)
    {
        if (string.IsNullOrWhiteSpace(url)) return;
        if (!Uri.TryCreate(url, UriKind.Absolute, out var uri)) return;
        _metadataCts?.Cancel();
        _metadataCts?.Dispose();
        _metadataCts = new CancellationTokenSource();
        _ = FetchAndDisplayMetadataAsync(url, uri, _metadataCts.Token);
    }

    [DllImport("user32.dll")]
    private static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

    [DllImport("user32.dll")]
    private static extern bool BringWindowToTop(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, int dwExtraInfo);

    public static void ForceForeground(IntPtr hWnd)
    {
        const int SW_RESTORE = 9;
        ShowWindow(hWnd, SW_RESTORE);
        BringWindowToTop(hWnd);
        keybd_event(0, 0, 0, 0);
        SetForegroundWindow(hWnd);
    }

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool OpenClipboard(IntPtr hWndNewOwner);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool CloseClipboard();

    [DllImport("user32.dll")]
    private static extern IntPtr GetClipboardData(uint uFormat);

    [DllImport("kernel32.dll")]
    private static extern IntPtr GlobalLock(IntPtr hMem);

    [DllImport("kernel32.dll")]
    private static extern bool GlobalUnlock(IntPtr hMem);

    private static string? GetWindowsClipboardText()
    {
        if (!OperatingSystem.IsWindows()) return null;
        try
        {
            if (!OpenClipboard(IntPtr.Zero)) return null;
            try
            {
                const uint CF_UNICODETEXT = 13;
                var hMem = GetClipboardData(CF_UNICODETEXT);
                if (hMem == IntPtr.Zero) return null;
                var ptr = GlobalLock(hMem);
                if (ptr == IntPtr.Zero) return null;
                try
                {
                    return Marshal.PtrToStringUni(ptr);
                }
                finally
                {
                    GlobalUnlock(hMem);
                }
            }
            finally
            {
                CloseClipboard();
            }
        }
        catch
        {
            return null;
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
        MinimizeToTrayCheck.IsChecked = _settings.MinimizeToTray;
        SponsorBlockCheck.IsChecked = _settings.SponsorBlockEnabled;
        SpeedLimitComboBox.SelectedIndex = Math.Clamp(_settings.SpeedLimitIndex, 0, Math.Max(0, SpeedLimitComboBox.ItemCount - 1));
        Aria2Check.IsChecked = _settings.UseAria2;
        ThemeComboBox.SelectedIndex = _settings.ThemePreset switch
        {
            "amoled" => 1,
            "nord" => 2,
            "cyberpunk" => 3,
            "catppuccin" => 4,
            "emerald" => 5,
            _ => 0
        };
        ThemeManager.ApplyTheme(this, _settings.ThemePreset);
        ApplyLanguage(_settings.Language);
        UpdatePrivacyDashboard();
    }

    private void UpdatePrivacyDashboard()
    {
        OptOutTelemetryCheckBox.IsChecked = !_settings.TelemetryEnabled;
        PrivacyStatusLabel.Text = _settings.TelemetryEnabled
            ? Localization.Get(_settings.Language, "TelemetryStatusActive")
            : Localization.Get(_settings.Language, "TelemetryStatusDisabled");

        bool showInfo = _settings.ShowTelemetryInfo || UpdateChecker.ShowTelemetryInfo;
        TelemetryInfoLayout.IsVisible = showInfo;

        if (showInfo)
        {
            var samplePayload = new
            {
                install_id = "00000000-0000-0000-0000-000000000000",
                app_version = "4.0.0",
                device_type = "Desktop PC",
                os_name = Environment.OSVersion.ToString(),
                cpu_cores = Environment.ProcessorCount,
                cpu_arch = System.Runtime.InteropServices.RuntimeInformation.ProcessArchitecture.ToString(),
                friend_tag = _settings.FriendTag ?? "None (Standard User)"
            };
            TelemetryPayloadTextBox.Text = System.Text.Json.JsonSerializer.Serialize(samplePayload, new System.Text.Json.JsonSerializerOptions { WriteIndented = true });
        }
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
        UpdateEngineText.Text = T("UpdateEngine");
        QuickHudText.Text = T("QuickHud");

        ThemeDefaultItem.Content = T("ThemeDefault");
        ThemeAmoledItem.Content = T("ThemeAmoled");
        ThemeNordItem.Content = T("ThemeNord");
        ThemeCyberpunkItem.Content = T("ThemeCyberpunk");
        ThemeCatppuccinItem.Content = T("ThemeCatppuccin");
        ThemeEmeraldItem.Content = T("ThemeEmerald");

        DownloadTab.Header = T("TabDownload");
        QueueTab.Header = T("TabQueue");
        StreamsTab.Header = T("TabStreams");
        HistoryTab.Header = T("TabHistory");
        SubscriptionsTab.Header = T("TabSubscriptions");
        LogsTab.Header = T("TabLogs");
        PrivacyTab.Header = T("TabPrivacy");
        CreditsTab.Header = T("TabCredits");

        // Download Tab
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
        WebLoginButton.Content = T("WebLogin");
        PasteCookiesButton.Content = T("PasteCookies");

        EmbedMetadataCheck.Content = T("EmbedMetadata");
        EmbedThumbnailCheck.Content = T("EmbedCoverArt");
        EmbedSubsCheck.Content = T("EmbedSubtitles");
        WriteThumbnailCheck.Content = T("SaveThumbnail");
        MinimizeToTrayCheck.Content = T("MinimizeToTray");
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
        VerifiedBadgeText.Text = T("VerifiedBadge");

        // Queue Tab
        QueueHeaderLabel.Text = T("QueueHeader");
        QueueParallelLabel.Text = T("QueueParallel");
        QueueBatchUrlsBox.Watermark = T("QueueBatchWatermark");
        QueueAddBatchButton.Content = T("QueueAddUrls");
        QueueScheduleCheck.Content = T("QueueSchedule");
        QueueBatterySaverCheck.Content = T("QueueBatterySaver");
        StartQueueButton.Content = T("StartQueue");
        StopQueueButton.Content = T("Stop");
        ClearQueueButton.Content = T("ClearCompleted");
        QueueAllPlaylistButton.Content = T("AddAllToQueue");
        LoadAllQualitiesButton.Content = T("LoadAllQualities");
        SupportedQualitiesLabel.Text = T("SupportedQualities");

        // Streams Tab
        StreamsStatusHeader.Text = T("StreamsStatusDefault");
        StreamsLoadingLabel.Text = T("StreamsInspecting");
        RefreshStreamsButtonText.Text = T("RefreshStreams");

        // History Tab
        HistorySearchBox.Watermark = T("HistorySearchWatermark");
        HistorySearchText.Text = T("HistorySearch");
        HistoryRefreshText.Text = T("HistoryRefresh");
        HistoryClearText.Text = T("HistoryClearAll");
        MiniPlayerExternalText.Text = T("MiniPlayerExternal");

        // Subscriptions Tab
        SubscriptionUrlBox.Watermark = T("SubscriptionUrlWatermark");
        SubscriptionAudioCheck.Content = T("SubscriptionAudio");
        SubscriptionQualityLabel.Text = T("SubscriptionQualityLabel");
        SubscriptionMaxSyncLabel.Text = T("SubscriptionMaxSyncLabel");
        SubscriptionAddText.Text = T("SubscriptionSubscribe");
        SubscriptionSyncText.Text = T("SubscriptionSyncAll");

        // Logs Tab
        BackendLogsHeader.Text = T("BackendLogs");
        AutoScrollCheck.Content = T("AutoScroll");
        LogsFilterBox.Watermark = T("FilterLogsWatermark");
        SaveAllLogsText.Text = T("SaveLogs");
        CopyAllLogsText.Text = T("CopyAll");

        // Privacy Tab
        PrivacyTitleText.Text = T("PrivacyTitle");
        PrivacySubtitleText.Text = T("PrivacySubtitle");
        PrivacyGuaranteesHeader.Text = T("PrivacyGuaranteesHeader");
        PrivacyGuarantee1Text.Text = T("PrivacyGuarantee1");
        PrivacyGuarantee2Text.Text = T("PrivacyGuarantee2");
        PrivacyGuarantee3Text.Text = T("PrivacyGuarantee3");
        PrivacyGuarantee4Text.Text = T("PrivacyGuarantee4");
        TelemetryControlsHeader.Text = T("TelemetryControlsHeader");
        OptOutTelemetryCheckBox.Content = T("OptOutTelemetry");
        ResetInstallIdText.Text = T("ResetInstallId");
        GdprWipeText.Text = T("GdprWipe");
        InspectDiagnosticHeader.Text = T("InspectDiagnosticHeader");
        InspectDiagnosticSubtitle.Text = T("InspectDiagnosticSubtitle");
        PrivacyStatusLabel.Text = _settings.TelemetryEnabled
            ? T("TelemetryStatusActive")
            : T("TelemetryStatusDisabled");

        // Credits Tab
        AuthorRoleText.Text = T("AuthorRole");
        AuthorBioText.Text = T("AuthorBio");
        AuthorGithubText.Text = T("AuthorGithub");
        AuthorRepoText.Text = T("AuthorRepo");
        AuthorIssuesText.Text = T("AuthorIssues");
        AuthorEmailText.Text = T("AuthorEmail");
        AboutUmdHeader.Text = T("AboutUmdHeader");
        AboutUmdText.Text = T("AboutUmdText");
        OpenSourceTechHeader.Text = T("OpenSourceTechHeader");
        LicenseFooterText.Text = T("LicenseFooter");

        // Footer
        GlobalStatusText.Text = T("Ready");
    }

    private void ThemeComboBox_SelectionChanged(object? sender, SelectionChangedEventArgs e)
    {
        if (ThemeComboBox == null) return;
        string themeId = ThemeComboBox.SelectedIndex switch
        {
            1 => "amoled",
            2 => "nord",
            3 => "cyberpunk",
            4 => "catppuccin",
            5 => "emerald",
            _ => "default"
        };
        _settings.ThemePreset = themeId;
        ThemeManager.ApplyTheme(this, themeId);
        _settings.Save();
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
        _settings.MinimizeToTray = MinimizeToTrayCheck.IsChecked ?? false;
        _settings.SponsorBlockEnabled = SponsorBlockCheck.IsChecked ?? false;
        _settings.SpeedLimitIndex = SpeedLimitComboBox.SelectedIndex;
        _settings.UseAria2 = Aria2Check.IsChecked ?? false;
        _settings.TelemetryEnabled = !(OptOutTelemetryCheckBox.IsChecked ?? false);
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

    private async void WebLoginButton_Click(object? sender, RoutedEventArgs e)
    {
        var dialog = new BrowserLoginWindow(UrlTextBox.Text?.Trim());
        var saved = await dialog.ShowDialog<bool>(this);
        if (saved && !string.IsNullOrWhiteSpace(dialog.SavedCookiesPath))
        {
            CookiesFileBox.Text = dialog.SavedCookiesPath;
            CookiesBrowserComboBox.SelectedIndex = 0; // Use synced cookies.txt directly
            SaveUserSettings();
            var domainLabel = string.IsNullOrWhiteSpace(dialog.SyncedDomain) ? "site" : dialog.SyncedDomain;
            OnRawOutputReceived(this, $"[Complete] Web Login synced {dialog.SavedCookieCount} cookie(s) for {domainLabel} to {dialog.SavedCookiesPath}");
            GlobalStatusText.Text = $"Synced {dialog.SavedCookieCount} cookie(s) for {domainLabel} — ready to inspect or download.";
        }
    }

    private async void PasteCookiesButton_Click(object? sender, RoutedEventArgs e)
    {
        var dialog = new CookiesHelperWindow(UrlTextBox.Text?.Trim());
        var saved = await dialog.ShowDialog<bool>(this);
        if (saved && !string.IsNullOrWhiteSpace(dialog.SavedCookiesPath))
        {
            CookiesFileBox.Text = dialog.SavedCookiesPath;
            CookiesBrowserComboBox.SelectedIndex = 0; // Avoid Windows browser DB lock when cookies.txt is set
            SaveUserSettings();
            OnRawOutputReceived(this, $"[Complete] Saved {dialog.SavedCookieCount} session cookie(s) to {dialog.SavedCookiesPath}");
            GlobalStatusText.Text = $"Applied {dialog.SavedCookieCount} session cookie(s) — ready to inspect or download.";
        }
    }

    private void MainWindow_KeyDown(object? sender, KeyEventArgs e)
    {
        if (e.Key == Key.D && e.KeyModifiers.HasFlag(KeyModifiers.Control) && e.KeyModifiers.HasFlag(KeyModifiers.Shift))
        {
            OpenQuickHud();
            e.Handled = true;
        }
    }

    private void QuickHudButton_Click(object? sender, RoutedEventArgs e)
    {
        OpenQuickHud();
    }

    private void OpenQuickHud()
    {
        var hud = new QuickDownloadWindow();
        hud.ApplyLanguage(_settings.Language);
        hud.DownloadTriggered += (url, quality, preset, queueOnly) =>
        {
            UrlTextBox.Text = url;
            if (string.Equals(quality, "Audio", StringComparison.OrdinalIgnoreCase))
            {
                QualityComboBox.SelectedIndex = 4; // Audio Only (MP3)
            }
            else if (string.Equals(quality, "1080p", StringComparison.OrdinalIgnoreCase))
            {
                QualityComboBox.SelectedIndex = 1;
            }
            else if (string.Equals(quality, "720p", StringComparison.OrdinalIgnoreCase))
            {
                QualityComboBox.SelectedIndex = 2;
            }
            else if (string.Equals(quality, "480p", StringComparison.OrdinalIgnoreCase))
            {
                QualityComboBox.SelectedIndex = 3;
            }
            else
            {
                QualityComboBox.SelectedIndex = 0; // Best
            }

            if (queueOnly)
            {
                AddToQueueButton_Click(this, new RoutedEventArgs());
            }
            else
            {
                DownloadButton_Click(this, new RoutedEventArgs());
            }
        };
        hud.Show(this);
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

    private async void UpdateEngineButton_Click(object? sender, RoutedEventArgs e)
    {
        var lang = _settings.Language;
        UpdateEngineButton.IsEnabled = false;
        UpdateEngineIcon.IsVisible = false;
        UpdateEngineSpinner.IsVisible = true;
        UpdateEngineText.Text = Localization.Get(lang, "UpdatingEngine");
        BeginGlobalActivity(Localization.Get(lang, "UpdatingEngine"));

        try
        {
            var progress = new Progress<double>(pct =>
            {
                Dispatcher.UIThread.Post(() =>
                {
                    GlobalStatusText.Text = $"{Localization.Get(lang, "UpdatingEngine")} {pct:F0}%";
                });
            });

            var result = await UpdateChecker.CheckAndDownloadEngineUpdateAsync(progress);
            if (result.Success)
            {
                UpdateEngineText.Text = Localization.Get(lang, "EngineUpdated");
                GlobalStatusText.Text = result.Message;
                OnRawOutputReceived(this, $"[Engine] {result.Message}");
            }
            else
            {
                UpdateEngineText.Text = Localization.Get(lang, "EngineUpdateFailed");
                GlobalStatusText.Text = result.Message;
                OnRawOutputReceived(this, $"[Engine] Error: {result.Message}");
            }
        }
        catch (Exception ex)
        {
            UpdateEngineText.Text = Localization.Get(lang, "EngineUpdateFailed");
            GlobalStatusText.Text = ex.Message;
            OnRawOutputReceived(this, $"[Engine] Exception: {ex.Message}");
        }
        finally
        {
            EndGlobalActivity();
            UpdateEngineSpinner.IsVisible = false;
            UpdateEngineIcon.IsVisible = true;
            UpdateEngineButton.IsEnabled = true;
            DispatcherTimer.RunOnce(() => UpdateEngineText.Text = Localization.Get(_settings.Language, "UpdateEngine"), TimeSpan.FromSeconds(4));
        }
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
                if (!_versionBlocked)
                {
                    UpdateBannerMessage.Text = $"New version v{info.LatestVersion} is available! (Current: v{info.CurrentVersion}){sizeSuffix}";
                }
                UpdateBanner.IsVisible = true;
                CheckUpdatesText.Text = $"Update v{info.LatestVersion}";
                if (!silent)
                {
                    GlobalStatusText.Text = $"Update available: v{info.LatestVersion}";
                }
            }
            else
            {
                if (!_versionBlocked)
                {
                    UpdateBanner.IsVisible = false;
                }
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
                if (e.Speed.HasValue)
                {
                    LiveBandwidthGraph.AddSample(e.Speed.Value);
                }
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
            Quality = GetSelectedQualityString(),
            PreferCodec = GetSelectedCodecString(),
            PauseOnBattery = QueueBatterySaverCheck?.IsChecked == true,
            ScheduleTime = QueueScheduleCheck?.IsChecked == true && !string.IsNullOrWhiteSpace(QueueScheduleTimeBox?.Text)
                ? QueueScheduleTimeBox.Text.Trim()
                : null,
        };

        var effectiveDir = GetEffectiveOutputDirectory();
        if (!string.IsNullOrWhiteSpace(effectiveDir))
        {
            options.OutputDirectory = effectiveDir;
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

        options.Organize = OrganizeComboBox.SelectedIndex switch
        {
            1 => "uploader",
            2 => "date",
            3 => "none",
            _ => "platform",
        };
        options.CleanFilenames = CleanFilenamesCheck.IsChecked == true;

        var recordDuration = RecordDurationBox.Text?.Trim();
        if (!string.IsNullOrWhiteSpace(recordDuration)) options.RecordDuration = recordDuration;
        options.LiveFromStart = LiveFromStartCheck.IsChecked == true;

        var speedLimit = GetSelectedSpeedLimitString();
        if (!string.IsNullOrWhiteSpace(speedLimit)) options.LimitRate = speedLimit;

        var downloadSched = DownloadScheduleBox?.Text?.Trim();
        if (!string.IsNullOrWhiteSpace(downloadSched))
        {
            options.ScheduleTime = downloadSched;
        }

        options.UseAria2 = Aria2Check?.IsChecked == true;

        if (GetSelectedQualityString() == "audio")
        {
            options.AudioOnly = true;
            options.AudioFormat = "mp3";
            options.AudioQuality = "320k";
        }

        return options;
    }

    private string GetEffectiveOutputDirectory()
    {
        var customDir = OutputDirBox.Text?.Trim();
        if (!string.IsNullOrWhiteSpace(customDir)) return customDir;
        var defaultDownloads = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            "Downloads"
        );
        return Directory.Exists(defaultDownloads) ? defaultDownloads : Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments);
    }

    private string GetSelectedQualityString()
    {
        var item = QualityComboBox.SelectedItem;
        var text = (item is ComboBoxItem cbi ? cbi.Content?.ToString() : item?.ToString()) ?? "";
        if (text.Contains("Audio", StringComparison.OrdinalIgnoreCase)) return "audio";
        if (text.Contains("2160", StringComparison.OrdinalIgnoreCase)) return "2160p";
        if (text.Contains("1440", StringComparison.OrdinalIgnoreCase)) return "1440p";
        if (text.Contains("1080", StringComparison.OrdinalIgnoreCase)) return "1080p";
        if (text.Contains("720", StringComparison.OrdinalIgnoreCase)) return "720p";
        if (text.Contains("480", StringComparison.OrdinalIgnoreCase)) return "480p";
        if (text.Contains("360", StringComparison.OrdinalIgnoreCase)) return "360p";
        return "best";
    }

    private string? GetSelectedCodecString()
    {
        var item = CodecComboBox.SelectedItem;
        var text = (item is ComboBoxItem cbi ? cbi.Content?.ToString() : item?.ToString()) ?? "";
        if (text.Contains("H.264", StringComparison.OrdinalIgnoreCase) || text.Contains("avc", StringComparison.OrdinalIgnoreCase)) return "h264";
        if (text.Contains("VP9", StringComparison.OrdinalIgnoreCase)) return "vp9";
        if (text.Contains("AV1", StringComparison.OrdinalIgnoreCase)) return "av01";
        return null; // Auto
    }

    private string? GetSelectedSpeedLimitString()
    {
        int idx = SpeedLimitComboBox?.SelectedIndex ?? 0;
        return idx switch
        {
            1 => "10M",
            2 => "5M",
            3 => "2M",
            4 => "1M",
            5 => "500K",
            6 => "250K",
            _ => null,
        };
    }

    private string? GetQueueSelectedSpeedLimitString()
    {
        int idx = QueueSpeedLimitComboBox?.SelectedIndex ?? 0;
        return idx switch
        {
            1 => "10M",
            2 => "5M",
            3 => "2M",
            4 => "1M",
            5 => "500K",
            6 => "250K",
            _ => null,
        };
    }

    public static bool IsProfileUrl(string? rawUrl)
    {
        if (string.IsNullOrWhiteSpace(rawUrl)) return false;
        var trimmed = rawUrl.Trim().Trim('"', '\'');
        if (trimmed.Contains(':') && !trimmed.Contains("://"))
        {
            var parts = trimmed.Split(':', 2);
            var platform = parts[0].Trim().ToLowerInvariant();
            if (new[] { "instagram", "facebook", "tiktok", "twitter", "x", "threads", "bluesky", "bsky", "reddit" }.Contains(platform))
                return true;
        }
        var target = (!trimmed.StartsWith("http://", StringComparison.OrdinalIgnoreCase) && !trimmed.StartsWith("https://", StringComparison.OrdinalIgnoreCase))
            ? "https://" + trimmed
            : trimmed;
        if (!Uri.TryCreate(target, UriKind.Absolute, out var uri)) return false;
        var host = (uri.Host ?? "").ToLowerInvariant().Replace("www.", "").Replace("m.", "");
        var path = (uri.AbsolutePath ?? "").ToLowerInvariant().TrimEnd('/');
        var segments = path.Split('/', StringSplitOptions.RemoveEmptyEntries);

        if (host.Contains("facebook.com"))
        {
            if (path.Contains("/watch") || path.Contains("/reel") || path.Contains("/videos/")) return false;
            if (path.Contains("/profile.php") || path.Contains("/people/")) return true;
            var reserved = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
            {
                "watch", "reel", "reels", "videos", "share", "story.php", "photo", "photo.php", "groups", "events", "marketplace", "login", "pages", "hashtag", "posts", "stories", "live"
            };
            return segments.Length == 1 && !reserved.Contains(segments[0]);
        }
        if (host.Contains("instagram.com"))
        {
            var reserved = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "reel", "reels", "p", "tv", "stories", "explore" };
            return segments.Length == 1 && !reserved.Contains(segments[0]);
        }
        if (host == "x.com" || host == "twitter.com")
        {
            return segments.Length == 1 && !path.Contains("/status/");
        }
        if (host.Contains("threads.net"))
        {
            return segments.Length == 1;
        }
        if (host.Contains("tiktok.com"))
        {
            return segments.Length == 1 && segments[0].StartsWith("@") && !path.Contains("/video/") && !path.Contains("/photo/");
        }
        if (host.Contains("bsky.app"))
        {
            return path.Contains("/profile/");
        }
        if (host.Contains("reddit.com"))
        {
            return path.Contains("/user/") || path.Contains("/u/");
        }
        return false;
    }

    private void PopulateSupportedQualities(List<string>? qualities)
    {
        var items = new List<string> { "Best Available (Max)" };
        if (qualities != null && qualities.Count > 0)
        {
            var heights = new HashSet<int>();
            foreach (var q in qualities)
            {
                var numStr = new string(q.Where(char.IsDigit).ToArray());
                if (int.TryParse(numStr, out var h) && h > 0)
                {
                    heights.Add(h);
                }
            }
            if (heights.Any(h => h >= 2160)) items.Add("4K (2160p)");
            if (heights.Any(h => h is >= 1440 and < 2160)) items.Add("2K (1440p)");
            if (heights.Any(h => h is >= 1080 and < 1440)) items.Add("1080p Full HD");
            if (heights.Any(h => h is >= 720 and < 1080)) items.Add("720p HD");
            if (heights.Any(h => h is >= 480 and < 720)) items.Add("480p SD");
            if (heights.Any(h => h is >= 360 and < 480)) items.Add("360p");
        }
        else
        {
            items.AddRange(new[] { "1080p Full HD", "720p HD", "480p SD" });
        }
        items.Add("Audio Only (MP3)");
        QualityComboBox.ItemsSource = null;
        QualityComboBox.ItemsSource = items;
        QualityComboBox.SelectedIndex = 0;
    }

    private void PopulateSupportedCodecs(List<string>? codecs)
    {
        var items = new List<string> { "Default (Auto)" };
        if (codecs != null && codecs.Count > 0)
        {
            if (codecs.Any(c => c.Contains("h264", StringComparison.OrdinalIgnoreCase) || c.Contains("avc", StringComparison.OrdinalIgnoreCase)))
                items.Add("H.264 / AVC1 (Universal)");
            if (codecs.Any(c => c.Contains("vp9", StringComparison.OrdinalIgnoreCase)))
                items.Add("VP9 (High Quality)");
            if (codecs.Any(c => c.Contains("av01", StringComparison.OrdinalIgnoreCase) || c.Contains("av1", StringComparison.OrdinalIgnoreCase)))
                items.Add("AV1 (Ultra Compressed)");
        }
        else
        {
            items.AddRange(new[] { "H.264 / AVC1 (Universal)", "VP9 (High Quality)", "AV1 (Ultra Compressed)" });
        }
        CodecComboBox.ItemsSource = null;
        CodecComboBox.ItemsSource = items;
        CodecComboBox.SelectedIndex = 0;
    }

    private async void DownloadButton_Click(object? sender, RoutedEventArgs e)
    {
        if (_versionBlocked)
        {
            GlobalStatusText.Text = _versionBlockedMessage ?? "This version has reached End of Life. Please update to continue.";
            return;
        }
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
            var effectiveDir = GetEffectiveOutputDirectory();
            var cookiesFile = GetSelectedCookiesFile();
            var cookiesBrowser = string.IsNullOrWhiteSpace(cookiesFile) ? GetSelectedCookiesBrowser() : null;

            var savedPath = await _client.DownloadProfilePictureAsync(
                input,
                outputDirectory: effectiveDir,
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
                    ViewsContainer.IsVisible = true;
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
        LiveBandwidthGraph.Reset();
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
        if (_versionBlocked)
        {
            GlobalStatusText.Text = _versionBlockedMessage ?? "This version has reached End of Life. Please update to continue.";
            return;
        }
        if (_isQueueRunning) return;
        var pending = _queueItems.Where(q => q.Status == QueueItemStatus.Queued || q.Status == QueueItemStatus.Failed || q.Status == QueueItemStatus.Canceled).ToList();
        if (pending.Count == 0) return;

        // Smart Scheduling check: wait until target wall-clock time if enabled
        if (QueueScheduleCheck.IsChecked == true && !string.IsNullOrWhiteSpace(QueueScheduleTimeBox.Text))
        {
            var timeStr = QueueScheduleTimeBox.Text.Trim();
            if (TimeOnly.TryParse(timeStr, out var scheduledTime))
            {
                var now = TimeOnly.FromDateTime(DateTime.Now);
                var delay = scheduledTime > now
                    ? scheduledTime.ToTimeSpan() - now.ToTimeSpan()
                    : (TimeSpan.FromDays(1) - (now.ToTimeSpan() - scheduledTime.ToTimeSpan()));

                GlobalStatusText.Text = $"Queue scheduled for {timeStr} ({delay.Hours}h {delay.Minutes}m remaining).";
                _isQueueRunning = true;
                _queueCts = new CancellationTokenSource();
                StartQueueButton.IsEnabled = false;
                StopQueueButton.IsEnabled = true;

                try
                {
                    await Task.Delay(delay, _queueCts.Token);
                }
                catch (OperationCanceledException)
                {
                    _isQueueRunning = false;
                    StartQueueButton.IsEnabled = true;
                    StopQueueButton.IsEnabled = false;
                    GlobalStatusText.Text = "Scheduled queue cancelled.";
                    return;
                }
            }
        }

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

                    var qSpeed = GetQueueSelectedSpeedLimitString();
                    if (!string.IsNullOrWhiteSpace(qSpeed))
                    {
                        item.Options.LimitRate = qSpeed;
                    }

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

    private void MoveQueueItemUp_Click(object? sender, RoutedEventArgs e)
    {
        if (sender is Button btn && btn.DataContext is QueueItemModel item)
        {
            var idx = _queueItems.IndexOf(item);
            if (idx > 0)
            {
                _queueItems.Move(idx, idx - 1);
            }
        }
    }

    private void MoveQueueItemDown_Click(object? sender, RoutedEventArgs e)
    {
        if (sender is Button btn && btn.DataContext is QueueItemModel item)
        {
            var idx = _queueItems.IndexOf(item);
            if (idx >= 0 && idx < _queueItems.Count - 1)
            {
                _queueItems.Move(idx, idx + 1);
            }
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
        StreamsNoticeBanner.IsVisible = false;
        StreamsNoticeText.Text = string.Empty;
        StreamsLoadingLabel.Text = "Inspecting available video & audio streams...";
        StreamsLoadingPanel.IsVisible = true;
        StreamsListBox.IsVisible = false;
        StreamsStatusHeader.Text = $"Inspecting available streams for: {url}...";
        BeginGlobalActivity("Inspecting stream formats...");

        _streamPreviewCts?.Cancel();
        _streamPreviewCts?.Dispose();
        _streamPreviewCts = new CancellationTokenSource();
        var previewToken = _streamPreviewCts.Token;

        try
        {
            var cookiesFile = GetSelectedCookiesFile();
            var cookiesBrowser = string.IsNullOrWhiteSpace(cookiesFile) ? GetSelectedCookiesBrowser() : null;
            var inspection = await _client.InspectFormatsDetailedAsync(url, cookiesFromBrowser: cookiesBrowser, cookiesFile: cookiesFile);
            var formats = inspection.Formats;
            var streamVms = formats.Select(f => new StreamItemViewModel(f)).ToList();
            StreamsListBox.ItemsSource = streamVms;

            var isImageList = formats.Count > 0 && formats.All(f => f.IsImage);
            var hasCookies = !string.IsNullOrWhiteSpace(cookiesFile) || !string.IsNullOrWhiteSpace(cookiesBrowser);
            var hasEnhancedOnly = isImageList && formats.Any(f => f.FormatId.StartsWith("img_hd_", StringComparison.OrdinalIgnoreCase));

            if (!string.IsNullOrWhiteSpace(inspection.ProfileNotice))
            {
                StreamsNoticeText.Text = inspection.ProfileNotice;
                StreamsNoticeBanner.IsVisible = true;
            }
            else if (inspection.ProfileLocked)
            {
                StreamsNoticeText.Text = "Profile Locked by Platform — Only small identification avatars are exposed to non-friends. Use the HD Enhanced rendition above for the sharpest available output.";
                StreamsNoticeBanner.IsVisible = true;
            }

            // Sync Download tab preview card qualities, lock badge, ID & public profile info chips with refreshed stream list
            if (MetadataCard.IsVisible)
            {
                if (!string.IsNullOrWhiteSpace(inspection.Title))
                {
                    var lastSegment = Uri.TryCreate(url, UriKind.Absolute, out var parsedUri) && parsedUri != null
                        ? parsedUri.Segments.LastOrDefault()?.Trim('/')
                        : null;
                    var currentTitle = VideoTitleLabel?.Text;
                    if (currentTitle == "Fetching media details..." ||
                        currentTitle?.StartsWith("TikTok Video by") == true ||
                        currentTitle?.StartsWith("Facebook Video by") == true ||
                        (!string.IsNullOrWhiteSpace(lastSegment) && currentTitle == lastSegment) ||
                        (parsedUri != null && currentTitle == parsedUri.Host))
                    {
                        if (VideoTitleLabel != null) VideoTitleLabel.Text = inspection.Title;
                        if (!string.IsNullOrWhiteSpace(inspection.Uploader) && UploaderLabel != null) UploaderLabel.Text = inspection.Uploader;
                        if (!string.IsNullOrWhiteSpace(inspection.Thumbnail)) _ = LoadThumbnailAsync(inspection.Thumbnail, previewToken);
                        if (!string.IsNullOrWhiteSpace(inspection.DurationFormatted))
                        {
                            if (DurationLabel != null) DurationLabel.Text = inspection.DurationFormatted;
                            if (DurationBadge != null) DurationBadge.IsVisible = true;
                        }
                        if (!string.IsNullOrWhiteSpace(inspection.ViewCountFormatted))
                        {
                            if (ViewsLabel != null) ViewsLabel.Text = inspection.ViewCountFormatted;
                            if (ViewsContainer != null) ViewsContainer.IsVisible = true;
                        }
                    }
                }

                var profileInfo = inspection.ProfileInfo ?? new List<ProfileInfoItemModel>();
                if (isImageList || !string.IsNullOrWhiteSpace(inspection.ProfileId) || profileInfo.Count > 0 || inspection.ProfileLocked)
                {
                    ApplyProfileMetadataToCard(
                        inspection.ProfileId ?? _currentProfileId,
                        inspection.Bio ?? _currentProfileBio,
                        inspection.IsVerified,
                        inspection.ProfileLocked,
                        PlatformBadge?.Text,
                        profileInfo.Count > 0 ? profileInfo : null);
                }
                var syncedQualities = isImageList
                    ? formats.Where(f => !string.IsNullOrWhiteSpace(f.Resolution)).Select(f => f.Resolution).Distinct().ToList()
                    : FormatInfoModel.ExtractSupportedQualities(formats);
                if (syncedQualities.Count > 0)
                {
                    SingleVideoQualitiesItems.ItemsSource = syncedQualities;
                    SingleVideoQualitiesPanel.IsVisible = true;
                }
            }

            if (isImageList)
            {
                _ = LoadStreamPreviewsAsync(streamVms, previewToken);
            }

            StreamsStatusHeader.Text = isImageList
                ? (hasEnhancedOnly && !hasCookies
                    ? $"Found {formats.Count} picture(s) — Tip: use Web Login or cookies.txt for native HD on authorized profiles."
                    : $"Found {formats.Count} verified picture(s) for: {url}")
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

    private async Task LoadStreamPreviewsAsync(List<StreamItemViewModel> items, CancellationToken token)
    {
        var imageItems = items.Where(i => i.IsImage && !string.IsNullOrWhiteSpace(i.Format.DirectUrl)).ToList();
        if (imageItems.Count == 0) return;

        using var semaphore = new SemaphoreSlim(4, 4);
        var tasks = imageItems.Select(async item =>
        {
            await semaphore.WaitAsync(token);
            try
            {
                if (token.IsCancellationRequested) return;
                var bytes = await _httpClient.GetByteArrayAsync(item.Format.DirectUrl!, token);
                if (token.IsCancellationRequested || bytes == null || bytes.Length == 0) return;

                await Dispatcher.UIThread.InvokeAsync(() =>
                {
                    try
                    {
                        using var ms = new MemoryStream(bytes);
                        item.PreviewBitmap = new Bitmap(ms);
                    }
                    catch { }
                    finally
                    {
                        item.IsLoadingPreview = false;
                    }
                });
            }
            catch
            {
                await Dispatcher.UIThread.InvokeAsync(() => item.IsLoadingPreview = false);
            }
            finally
            {
                semaphore.Release();
            }
        });

        try
        {
            await Task.WhenAll(tasks);
        }
        catch (OperationCanceledException) { }
    }

    private async void DownloadStream_Click(object? sender, RoutedEventArgs e)
    {
        var format = sender is Button btn
            ? (btn.DataContext is StreamItemViewModel vm ? vm.Format : btn.DataContext as FormatInfoModel)
            : null;
        if (format != null)
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
                    var effectiveDir = GetEffectiveOutputDirectory();
                    var cookiesFile = GetSelectedCookiesFile();
                    var cookiesBrowser = string.IsNullOrWhiteSpace(cookiesFile) ? GetSelectedCookiesBrowser() : null;

                    var enhanceHd = format.FormatId.StartsWith("img_hd_", StringComparison.OrdinalIgnoreCase);
                    var savedPath = await _client.DownloadDirectImageAsync(
                        format.DirectUrl,
                        sourceProfileUrl: url,
                        outputDirectory: effectiveDir,
                        cookiesFromBrowser: cookiesBrowser,
                        cookiesFile: cookiesFile,
                        enhanceHd: enhanceHd);

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
                            ViewsContainer.IsVisible = true;
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
            DownloadOptionsCard.IsVisible = false;
            SuggestionsCard.IsVisible = false;
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
                DownloadOptionsCard.IsVisible = false;
            }

            // Plain-text query: fetch debounced YouTube autosuggestions
            if (rawUrl.Length >= 2 && rawUrl.Length <= 64 && !rawUrl.Contains("://") && !rawUrl.StartsWith("www.", StringComparison.OrdinalIgnoreCase))
            {
                try
                {
                    await Task.Delay(350, token);
                    if (token.IsCancellationRequested) return;
                    var suggestions = await _client.GetSuggestionsAsync(rawUrl, token);
                    if (token.IsCancellationRequested) return;

                    SuggestionsWrapPanel.Children.Clear();
                    foreach (var s in suggestions)
                    {
                        var chip = new Button
                        {
                            Content = s,
                            Margin = new global::Avalonia.Thickness(0, 0, 6, 4),
                            Padding = new global::Avalonia.Thickness(8, 3),
                            FontSize = 11,
                            Background = new global::Avalonia.Media.SolidColorBrush(global::Avalonia.Media.Color.Parse("#1E293B")),
                            Foreground = new global::Avalonia.Media.SolidColorBrush(global::Avalonia.Media.Color.Parse("#E2E8F0")),
                        };
                        chip.Click += async (_, _) =>
                        {
                            UrlTextBox.Text = s;
                            SuggestionsCard.IsVisible = false;
                            await RunSearchAsync(s);
                        };
                        SuggestionsWrapPanel.Children.Add(chip);
                    }
                    SuggestionsCard.IsVisible = suggestions.Count > 0;
                }
                catch (OperationCanceledException)
                {
                    // Ignored on rapid typing
                }
                catch
                {
                    SuggestionsCard.IsVisible = false;
                }
            }
            else
            {
                SuggestionsCard.IsVisible = false;
            }
            return;
        }

        SuggestionsCard.IsVisible = false;

        if (IsProfileUrl(rawUrl))
        {
            DownloadOptionsCard.IsVisible = false;
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
            var h when h.Contains("threads.net") || h.Contains("threads.com") => "THREADS",
            var h when h.Contains("bsky.app") => "BLUESKY",
            var h when h.Contains("soundcloud") => "SOUNDCLOUD",
            var h when h.Contains("vimeo") => "VIMEO",
            var h when h.Contains("reddit") => "REDDIT",
            var h when h.Contains("twitch") => "TWITCH",
            _ => "MEDIA"
        };

        ClearPlaylistCards();
        SingleVideoQualitiesPanel.IsVisible = false;
        SingleVideoQualitiesItems.ItemsSource = null;
        ApplyProfileMetadataToCard(TryExtractFacebookIdFromUri(uri), null, false, false, platformDisplay, null);
        PlatformBadge.Text = platformDisplay;
        VideoTitleLabel.Text = "Fetching media details...";
        UploaderLabel.Text = uri.Host;
        ViewsLabel.Text = "";
        ViewsContainer.IsVisible = false;
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

            if (meta == null && (uri.Host.Contains("tiktok.com", StringComparison.OrdinalIgnoreCase) || rawUrl.Contains("tiktok.com", StringComparison.OrdinalIgnoreCase)))
            {
                meta = await DownloaderClient.FetchTikTokMetadataDirectAsync(DownloaderClient.CleanMediaUrl(rawUrl), token);
                if (token.IsCancellationRequested) return;
            }
            if (meta == null && (uri.Host.Contains("facebook.com", StringComparison.OrdinalIgnoreCase) || rawUrl.Contains("facebook.com", StringComparison.OrdinalIgnoreCase) || uri.Host.Contains("fb.watch", StringComparison.OrdinalIgnoreCase)))
            {
                meta = await DownloaderClient.FetchFacebookMetadataDirectAsync(DownloaderClient.CleanMediaUrl(rawUrl), token);
                if (token.IsCancellationRequested) return;
            }
            if (meta == null)
            {
                meta = await DownloaderClient.FetchOpenGraphMetadataDirectAsync(DownloaderClient.CleanMediaUrl(rawUrl), token);
                if (token.IsCancellationRequested) return;
            }

            var entries = meta?.Entries ?? new List<PlaylistEntryModel>();
            if (meta != null && meta.IsPlaylist && entries.Count > 0)
            {
                DownloadOptionsCard.IsVisible = true;
                DisplayPlaylistCards(meta, uri, cookiesBrowser, cookiesFile);
                GlobalStatusText.Text = $"Loaded playlist ({entries.Count} videos): {meta.Title}";
            }
            else if (meta != null && !string.IsNullOrWhiteSpace(meta.Title))
            {
                var profileInfo = meta.ProfileInfo ?? new List<ProfileInfoItemModel>();
                var qualities = meta.Qualities ?? new List<string>();
                var codecs = meta.Codecs ?? new List<string>();
                bool isProfile = IsProfileUrl(rawUrl) || meta.IsProfile || !string.IsNullOrWhiteSpace(meta.ProfileId) || profileInfo.Count > 0 || meta.ProfileLocked || (qualities.Count > 0 && qualities.All(q => q != null && q.Contains("x")));
                DownloadOptionsCard.IsVisible = !isProfile;
                if (!isProfile)
                {
                    PopulateSupportedQualities(qualities);
                    PopulateSupportedCodecs(codecs);
                }

                MetadataLoadingText.IsVisible = false;
                MetadataHeaderSpinner.IsVisible = false;
                VideoTitleLabel.Text = meta.Title;
                UploaderLabel.Text = !string.IsNullOrWhiteSpace(meta.Uploader) ? meta.Uploader : uri.Host;

                if (!string.IsNullOrWhiteSpace(meta.Platform))
                {
                    PlatformBadge.Text = meta.Platform.ToUpperInvariant();
                }

                ApplyProfileMetadataToCard(
                    meta.ProfileId,
                    meta.Bio,
                    meta.IsVerified,
                    meta.ProfileLocked,
                    meta.Platform,
                    profileInfo);

                if (!string.IsNullOrWhiteSpace(meta.DurationFormatted))
                {
                    DurationLabel.Text = meta.DurationFormatted;
                    DurationBadge.IsVisible = true;
                }
                else
                {
                    DurationBadge.IsVisible = false;
                }

                ViewsLabel.Text = meta.ViewCountFormatted ?? "";
                ViewsContainer.IsVisible = !string.IsNullOrWhiteSpace(meta.ViewCountFormatted);

                if (qualities.Count > 0)
                {
                    SingleVideoQualitiesItems.ItemsSource = qualities;
                    SingleVideoQualitiesPanel.IsVisible = true;
                }

                if (!string.IsNullOrWhiteSpace(meta.Thumbnail))
                {
                    _ = LoadThumbnailAsync(meta.Thumbnail, token);
                }
                else
                {
                    ThumbnailSpinner.IsVisible = false;
                }

                GlobalStatusText.Text = $"Loaded media preview: {meta.Title}";
            }
            else
            {
                MetadataLoadingText.IsVisible = false;
                MetadataHeaderSpinner.IsVisible = false;
                ThumbnailSpinner.IsVisible = false;
                ViewsLabel.Text = "";
                ViewsContainer.IsVisible = false;
                if (uri.Host.Contains("tiktok.com", StringComparison.OrdinalIgnoreCase))
                {
                    var authorSegment = uri.Segments.FirstOrDefault(s => s.StartsWith("@"))?.Trim('/', '@');
                    var author = !string.IsNullOrWhiteSpace(authorSegment) ? $"@{authorSegment}" : "TikTok Creator";
                    VideoTitleLabel.Text = $"TikTok Video by {author}";
                    UploaderLabel.Text = author;
                }
                else
                {
                    var fallbackTitle = uri.Segments.LastOrDefault()?.Trim('/');
                    VideoTitleLabel.Text = !string.IsNullOrWhiteSpace(fallbackTitle) ? fallbackTitle : uri.Host;
                    UploaderLabel.Text = uri.Host;
                }
                DownloadOptionsCard.IsVisible = true;
                GlobalStatusText.Text = "Ready to download";
            }
        }
        catch (OperationCanceledException)
        {
            // Normal cancellation
        }
        catch (Exception ex)
        {
            if (!token.IsCancellationRequested)
            {
                OnRawOutputReceived(this, $"[Metadata Error] {ex.Message}");
                // Never overwrite already-displayed media title/uploader with fallback
                if (VideoTitleLabel.Text == "Fetching media details...")
                {
                    MetadataLoadingText.IsVisible = false;
                    MetadataHeaderSpinner.IsVisible = false;
                    ThumbnailSpinner.IsVisible = false;
                    ViewsLabel.Text = "";
                    ViewsContainer.IsVisible = false;
                    if (uri.Host.Contains("tiktok.com", StringComparison.OrdinalIgnoreCase))
                    {
                        var authorSegment = uri.Segments.FirstOrDefault(s => s.StartsWith("@"))?.Trim('/', '@');
                        var author = !string.IsNullOrWhiteSpace(authorSegment) ? $"@{authorSegment}" : "TikTok Creator";
                        VideoTitleLabel.Text = $"TikTok Video by {author}";
                        UploaderLabel.Text = author;
                    }
                    else
                    {
                        var fallbackTitle = uri.Segments.LastOrDefault()?.Trim('/');
                        VideoTitleLabel.Text = !string.IsNullOrWhiteSpace(fallbackTitle) ? fallbackTitle : uri.Host;
                        UploaderLabel.Text = uri.Host;
                    }
                    DownloadOptionsCard.IsVisible = true;
                    GlobalStatusText.Text = "Ready to download";
                }
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
        if (string.IsNullOrWhiteSpace(thumbnailUrl))
        {
            await Dispatcher.UIThread.InvokeAsync(() => { ThumbnailSpinner.IsVisible = false; });
            return;
        }

        thumbnailUrl = System.Net.WebUtility.HtmlDecode(thumbnailUrl).Trim();

        // 1. Try direct fetch
        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Get, thumbnailUrl);
            if (thumbnailUrl.Contains("tiktok", StringComparison.OrdinalIgnoreCase))
            {
                request.Headers.Referrer = new Uri("https://www.tiktok.com/");
            }
            else if (thumbnailUrl.Contains("fbcdn", StringComparison.OrdinalIgnoreCase) || thumbnailUrl.Contains("facebook", StringComparison.OrdinalIgnoreCase))
            {
                request.Headers.Referrer = new Uri("https://www.facebook.com/");
            }

            using var response = await _httpClient.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, token);
            if (response.IsSuccessStatusCode)
            {
                var bytes = await response.Content.ReadAsByteArrayAsync(token);
                if (!token.IsCancellationRequested && bytes != null && bytes.Length > 0)
                {
                    bool loaded = false;
                    await Dispatcher.UIThread.InvokeAsync(() =>
                    {
                        try
                        {
                            using var ms = new MemoryStream(bytes);
                            ThumbnailImage.Source = new Bitmap(ms);
                            ThumbnailSpinner.IsVisible = false;
                            loaded = true;
                        }
                        catch { }
                    });
                    if (loaded) return;
                }
            }
        }
        catch { }

        // 2. Direct failed or encoded in unusual format: try reliable fast transcode proxy (&output=jpg)
        try
        {
            var proxyUrl = $"https://wsrv.nl/?url={Uri.EscapeDataString(thumbnailUrl)}&output=jpg";
            using var fallbackReq = new HttpRequestMessage(HttpMethod.Get, proxyUrl);
            using var fallbackResp = await _httpClient.SendAsync(fallbackReq, HttpCompletionOption.ResponseHeadersRead, token);
            if (fallbackResp.IsSuccessStatusCode)
            {
                var fallbackBytes = await fallbackResp.Content.ReadAsByteArrayAsync(token);
                if (!token.IsCancellationRequested && fallbackBytes != null && fallbackBytes.Length > 0)
                {
                    bool loaded = false;
                    await Dispatcher.UIThread.InvokeAsync(() =>
                    {
                        try
                        {
                            using var ms = new MemoryStream(fallbackBytes);
                            ThumbnailImage.Source = new Bitmap(ms);
                            ThumbnailSpinner.IsVisible = false;
                            loaded = true;
                        }
                        catch { }
                    });
                    if (loaded) return;
                }
            }
        }
        catch { }

        // 3. Keep placeholder cleanly without throwing
        await Dispatcher.UIThread.InvokeAsync(() =>
        {
            ThumbnailSpinner.IsVisible = false;
        });
    }

    private void ApplyProfileMetadataToCard(
        string? profileId,
        string? bio,
        bool isVerified,
        bool profileLocked,
        string? platform,
        IReadOnlyList<ProfileInfoItemModel>? infoItems)
    {
        SetProfileIdBadge(profileId);
        ProfileVerifiedBadge.IsVisible = isVerified;

        ProfileLockedBadge.IsVisible = profileLocked;
        var isFb = !string.IsNullOrWhiteSpace(platform) && platform.Contains("facebook", StringComparison.OrdinalIgnoreCase);
        ProfileLockedBadgeText.Text = isFb ? "LOCKED PROFILE" : "PRIVATE ACCOUNT";

        var cleanedBio = bio?.Trim();
        if (!string.IsNullOrWhiteSpace(cleanedBio))
        {
            _currentProfileBio = cleanedBio;
            ProfileBioText.Text = cleanedBio;
            ProfileBioButton.IsVisible = true;
        }
        else
        {
            _currentProfileBio = null;
            ProfileBioText.Text = string.Empty;
            ProfileBioButton.IsVisible = false;
        }

        // Build clickable profile info chips (skip duplicate 'ID' chip if already shown in top ProfileIdButton)
        var chips = new List<ProfileInfoChipViewModel>();
        if (infoItems != null)
        {
            foreach (var item in infoItems)
            {
                if (string.IsNullOrWhiteSpace(item.Label) || string.IsNullOrWhiteSpace(item.Value)) continue;
                if (!string.IsNullOrWhiteSpace(_currentProfileId) &&
                    item.Label.Equals("ID", StringComparison.OrdinalIgnoreCase) &&
                    item.EffectiveCopyValue.Equals(_currentProfileId, StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }
                chips.Add(new ProfileInfoChipViewModel(item));
            }
        }

        _currentProfileChips = chips;
        ProfileInfoItems.ItemsSource = chips;
        ProfileInfoItems.IsVisible = chips.Count > 0;
        CopyAllProfileInfoButton.IsVisible = !string.IsNullOrWhiteSpace(_currentProfileId)
            || chips.Count > 0
            || !string.IsNullOrWhiteSpace(_currentProfileBio);
    }

    private void SetProfileIdBadge(string? profileId)
    {
        var cleaned = profileId?.Trim();
        if (!string.IsNullOrWhiteSpace(cleaned))
        {
            _currentProfileId = cleaned;
            ProfileIdLabel.Text = $"ID: {cleaned}";
            ProfileIdButton.IsVisible = true;
        }
        else
        {
            _currentProfileId = null;
            ProfileIdLabel.Text = string.Empty;
            ProfileIdButton.IsVisible = false;
        }
    }

    private async void ProfileIdButton_Click(object? sender, RoutedEventArgs e)
    {
        var id = _currentProfileId;
        if (string.IsNullOrWhiteSpace(id)) return;
        var clipboard = TopLevel.GetTopLevel(this)?.Clipboard;
        if (clipboard != null)
        {
            await clipboard.SetTextAsync(id);
            ProfileIdLabel.Text = $"Copied: {id}";
            GlobalStatusText.Text = $"Copied Profile ID: {id}";
            DispatcherTimer.RunOnce(() =>
            {
                if (_currentProfileId == id)
                {
                    ProfileIdLabel.Text = $"ID: {id}";
                }
            }, TimeSpan.FromSeconds(2));
        }
    }

    private async void ProfileInfoChip_Click(object? sender, RoutedEventArgs e)
    {
        if (sender is Button btn && btn.DataContext is ProfileInfoChipViewModel chip)
        {
            var clipboard = TopLevel.GetTopLevel(this)?.Clipboard;
            if (clipboard != null)
            {
                await clipboard.SetTextAsync(chip.CopyValue);
                chip.RecentlyCopied = true;
                GlobalStatusText.Text = $"Copied {chip.Label}: {chip.CopyValue}";
                DispatcherTimer.RunOnce(() => chip.RecentlyCopied = false, TimeSpan.FromSeconds(1.8));
            }
        }
    }

    private async void ProfileBioButton_Click(object? sender, RoutedEventArgs e)
    {
        var bio = _currentProfileBio;
        if (string.IsNullOrWhiteSpace(bio)) return;
        var clipboard = TopLevel.GetTopLevel(this)?.Clipboard;
        if (clipboard != null)
        {
            await clipboard.SetTextAsync(bio);
            GlobalStatusText.Text = "Copied profile bio to clipboard.";
        }
    }

    private async void CopyAllProfileInfoButton_Click(object? sender, RoutedEventArgs e)
    {
        var clipboard = TopLevel.GetTopLevel(this)?.Clipboard;
        if (clipboard == null) return;

        var lines = new List<string>();
        if (!string.IsNullOrWhiteSpace(VideoTitleLabel.Text)) lines.Add($"Name: {VideoTitleLabel.Text}");
        if (!string.IsNullOrWhiteSpace(PlatformBadge.Text)) lines.Add($"Platform: {PlatformBadge.Text}");
        if (!string.IsNullOrWhiteSpace(_currentProfileId)) lines.Add($"ID: {_currentProfileId}");
        foreach (var chip in _currentProfileChips)
        {
            lines.Add($"{chip.Label}: {chip.CopyValue}");
        }
        if (ProfileVerifiedBadge.IsVisible) lines.Add("Verified: Yes");
        if (ProfileLockedBadge.IsVisible) lines.Add($"Status: {ProfileLockedBadgeText.Text}");
        if (!string.IsNullOrWhiteSpace(_currentProfileBio)) lines.Add($"Bio: {_currentProfileBio}");
        var url = UrlTextBox.Text?.Trim();
        if (!string.IsNullOrWhiteSpace(url)) lines.Add($"URL: {url}");

        if (lines.Count == 0) return;

        await clipboard.SetTextAsync(string.Join(Environment.NewLine, lines));
        CopyAllProfileInfoText.Text = "Copied All";
        GlobalStatusText.Text = "Copied all profile info to clipboard.";
        DispatcherTimer.RunOnce(() => CopyAllProfileInfoText.Text = "Copy All Info", TimeSpan.FromSeconds(2));
    }

    private static string? TryExtractFacebookIdFromUri(Uri uri)
    {
        var host = uri.Host.ToLowerInvariant();
        if (!host.Contains("facebook.com") && !host.Contains("fb.com")) return null;
        if (!uri.AbsolutePath.TrimEnd('/').EndsWith("/profile.php", StringComparison.OrdinalIgnoreCase)) return null;

        var query = uri.Query.TrimStart('?').Split('&', StringSplitOptions.RemoveEmptyEntries);
        foreach (var pair in query)
        {
            var idx = pair.IndexOf('=');
            if (idx <= 0) continue;
            var key = Uri.UnescapeDataString(pair[..idx]);
            if (key.Equals("id", StringComparison.OrdinalIgnoreCase))
            {
                var val = Uri.UnescapeDataString(pair[(idx + 1)..]).Trim();
                if (val.Length >= 5 && val.All(char.IsDigit))
                {
                    return val;
                }
            }
        }
        return null;
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
        var entries = meta.Entries ?? new List<PlaylistEntryModel>();
        PlaylistCountBadge.Text = entries.Count == 1 ? "1 video" : $"{entries.Count} videos";
        PlaylistTitleLabel.Text = meta.Title;
        PlaylistUploaderLabel.Text = !string.IsNullOrWhiteSpace(meta.Uploader) ? meta.Uploader : uri.Host;

        var autoInspectCards = new List<PlaylistVideoCardModel>();
        var manualCards = 0;

        for (int i = 0; i < entries.Count; i++)
        {
            var card = PlaylistVideoCardModel.FromEntry(entries[i]);
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

    private async Task LoadSubscriptionsAsync()
    {
        SubscriptionLoadingBar.IsVisible = true;
        try
        {
            var subs = await _client.GetSubscriptionsAsync();
            _subscriptions.Clear();
            foreach (var s in subs) _subscriptions.Add(s);
        }
        catch { }
        finally
        {
            SubscriptionLoadingBar.IsVisible = false;
        }
    }

    private async void SubscriptionAddButton_Click(object? sender, RoutedEventArgs e)
    {
        var url = SubscriptionUrlBox.Text?.Trim();
        if (string.IsNullOrWhiteSpace(url)) return;

        SubscriptionAddButton.IsEnabled = false;
        SubscriptionLoadingBar.IsVisible = true;
        try
        {
            var audioOnly = SubscriptionAudioCheck.IsChecked == true;
            var quality = (SubscriptionQualityCombo.SelectedItem as ComboBoxItem)?.Content?.ToString() ?? "best";
            var maxDownloads = (int)(SubscriptionMaxDownloads.Value ?? 5);

            var added = await _client.AddSubscriptionAsync(url, audioOnly, quality, maxDownloads);
            if (added != null)
            {
                SubscriptionUrlBox.Text = string.Empty;
                await LoadSubscriptionsAsync();
                GlobalStatusText.Text = $"Subscribed to {added.DisplayTitle}";
            }
        }
        catch (Exception ex)
        {
            GlobalStatusText.Text = $"Subscription failed: {ex.Message}";
        }
        finally
        {
            SubscriptionAddButton.IsEnabled = true;
            SubscriptionLoadingBar.IsVisible = false;
        }
    }

    private async void SubscriptionRemove_Click(object? sender, RoutedEventArgs e)
    {
        if (sender is Button btn && btn.DataContext is SubscriptionModel sub)
        {
            SubscriptionLoadingBar.IsVisible = true;
            try
            {
                var removed = await _client.RemoveSubscriptionAsync(sub.Id.ToString());
                if (removed)
                {
                    _subscriptions.Remove(sub);
                    GlobalStatusText.Text = $"Unsubscribed from {sub.DisplayTitle}";
                }
            }
            finally
            {
                SubscriptionLoadingBar.IsVisible = false;
            }
        }
    }

    private async void SubscriptionSyncButton_Click(object? sender, RoutedEventArgs e)
    {
        SubscriptionSyncButton.IsEnabled = false;
        SubscriptionLoadingBar.IsVisible = true;
        SubscriptionSyncText.Text = "Syncing...";
        BeginGlobalActivity("Syncing subscribed channels and playlists...");
        try
        {
            var opts = BuildOptionsFromUi();
            var res = await _client.SyncSubscriptionsAsync(opts);
            GlobalStatusText.Text = $"Subscriptions synced: {res.Synced}/{res.Total} channels updated ({res.Failed} failed).";
            await LoadSubscriptionsAsync();
            await LoadHistoryAsync();
        }
        catch (Exception ex)
        {
            GlobalStatusText.Text = $"Sync failed: {ex.Message}";
        }
        finally
        {
            SubscriptionSyncButton.IsEnabled = true;
            SubscriptionLoadingBar.IsVisible = false;
            SubscriptionSyncText.Text = "Sync All";
            EndGlobalActivity();
        }
    }

    private void OpenMediaFile_Click(object? sender, RoutedEventArgs e)
    {
        if (sender is Button btn && btn.DataContext is HistoryRecordModel record)
        {
            if (!string.IsNullOrWhiteSpace(record.PrimaryFilepath) && File.Exists(record.PrimaryFilepath))
            {
                if (_miniPlayer.Load(record.PrimaryFilepath))
                {
                    MiniPlayerCard.IsVisible = true;
                    MiniPlayerTitle.Text = record.Title;
                    string ext = Path.GetExtension(record.PrimaryFilepath).TrimStart('.').ToUpperInvariant();
                    MiniPlayerBadge.Text = string.IsNullOrEmpty(ext) ? "MEDIA" : ext;
                    _miniPlayer.Play();
                    MiniPlayerPauseIcon.IsVisible = true;
                    MiniPlayerPlayIcon.IsVisible = false;
                    _miniPlayerTimer.Start();
                    return;
                }
                PlatformUtils.OpenFile(record.PrimaryFilepath);
            }
            else if (!string.IsNullOrWhiteSpace(record.PrimaryFilepath))
            {
                PlatformUtils.OpenFile(record.PrimaryFilepath);
            }
        }
    }

    private void MiniPlayerTimer_Tick(object? sender, EventArgs e)
    {
        if (_miniPlayer.IsLoaded && !_isMiniPlayerSeeking)
        {
            double pos = _miniPlayer.GetCurrentPositionSeconds();
            double dur = _miniPlayer.DurationSeconds;
            if (dur > 0)
            {
                double pct = Math.Clamp((pos / dur) * 100.0, 0, 100);
                string timeStr = $"{FormatPlayerTime(pos)} / {FormatPlayerTime(dur)}";
                if (MiniPlayerCard.IsVisible)
                {
                    MiniPlayerSeekBar.Value = pct;
                    MiniPlayerTimeText.Text = timeStr;
                }
                if (StreamsMiniPlayerCard.IsVisible)
                {
                    StreamsMiniPlayerSeekBar.Value = pct;
                    StreamsMiniPlayerTimeText.Text = timeStr;
                }
            }
        }
    }

    private static string FormatPlayerTime(double sec)
    {
        var ts = TimeSpan.FromSeconds(Math.Max(0, sec));
        return ts.TotalHours >= 1 ? ts.ToString(@"hh\:mm\:ss") : ts.ToString(@"mm\:ss");
    }

    private void PreviewStream_Click(object? sender, RoutedEventArgs e)
    {
        var fmt = sender is Button btn
            ? (btn.DataContext is StreamItemViewModel vm ? vm.Format : btn.DataContext as FormatInfoModel)
            : null;

        if (fmt == null) return;

        var target = !string.IsNullOrWhiteSpace(fmt.DirectUrl) ? fmt.DirectUrl : UrlTextBox.Text?.Trim();
        if (string.IsNullOrWhiteSpace(target)) return;

        if (_miniPlayer.Load(target))
        {
            StreamsMiniPlayerCard.IsVisible = true;
            StreamsMiniPlayerTitle.Text = $"{fmt.ResolutionFormatted} • {fmt.CodecSummary}";
            StreamsMiniPlayerBadge.Text = string.IsNullOrEmpty(fmt.Extension) ? "STREAM" : fmt.Extension.ToUpperInvariant();
            _miniPlayer.Play();
            StreamsMiniPlayerPauseIcon.IsVisible = true;
            StreamsMiniPlayerPlayIcon.IsVisible = false;
            _miniPlayerTimer.Start();
        }
        else
        {
            PlatformUtils.OpenFile(target);
        }
    }

    private void StreamsMiniPlayerPlayToggle_Click(object? sender, RoutedEventArgs e)
    {
        if (!_miniPlayer.IsLoaded) return;
        if (_miniPlayer.IsPlaying)
        {
            _miniPlayer.Pause();
            StreamsMiniPlayerPauseIcon.IsVisible = false;
            StreamsMiniPlayerPlayIcon.IsVisible = true;
        }
        else
        {
            _miniPlayer.Resume();
            StreamsMiniPlayerPauseIcon.IsVisible = true;
            StreamsMiniPlayerPlayIcon.IsVisible = false;
        }
    }

    private void StreamsMiniPlayerStopButton_Click(object? sender, RoutedEventArgs e)
    {
        _miniPlayer.Stop();
        StreamsMiniPlayerPauseIcon.IsVisible = false;
        StreamsMiniPlayerPlayIcon.IsVisible = true;
        StreamsMiniPlayerSeekBar.Value = 0;
    }

    private void StreamsMiniPlayerCloseButton_Click(object? sender, RoutedEventArgs e)
    {
        _miniPlayer.Stop();
        _miniPlayer.Close();
        _miniPlayerTimer.Stop();
        StreamsMiniPlayerCard.IsVisible = false;
    }

    private void StreamsMiniPlayerExternalButton_Click(object? sender, RoutedEventArgs e)
    {
        if (!string.IsNullOrWhiteSpace(_miniPlayer.CurrentFilePath))
        {
            PlatformUtils.OpenFile(_miniPlayer.CurrentFilePath);
        }
    }

    private void MiniPlayerPlayToggle_Click(object? sender, RoutedEventArgs e)
    {
        if (!_miniPlayer.IsLoaded) return;
        if (_miniPlayer.IsPlaying)
        {
            _miniPlayer.Pause();
            MiniPlayerPauseIcon.IsVisible = false;
            MiniPlayerPlayIcon.IsVisible = true;
        }
        else
        {
            _miniPlayer.Resume();
            MiniPlayerPauseIcon.IsVisible = true;
            MiniPlayerPlayIcon.IsVisible = false;
        }
    }

    private void MiniPlayerStopButton_Click(object? sender, RoutedEventArgs e)
    {
        _miniPlayer.Stop();
        MiniPlayerPauseIcon.IsVisible = false;
        MiniPlayerPlayIcon.IsVisible = true;
        MiniPlayerSeekBar.Value = 0;
    }

    private void MiniPlayerCloseButton_Click(object? sender, RoutedEventArgs e)
    {
        _miniPlayer.Stop();
        _miniPlayer.Close();
        _miniPlayerTimer.Stop();
        MiniPlayerCard.IsVisible = false;
    }

    private void MiniPlayerExternalButton_Click(object? sender, RoutedEventArgs e)
    {
        if (!string.IsNullOrWhiteSpace(_miniPlayer.CurrentFilePath))
        {
            PlatformUtils.OpenFile(_miniPlayer.CurrentFilePath);
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
        DownloadButton.IsEnabled = !active && !_versionBlocked;
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

    // ─── YouTube Text Search, Webpage Sniffer, Local Converter & Browser Companion ───

    private async void SearchButton_Click(object? sender, RoutedEventArgs e)
    {
        var query = UrlTextBox.Text?.Trim();
        if (string.IsNullOrWhiteSpace(query))
        {
            GlobalStatusText.Text = "Enter a song or video name to search YouTube.";
            return;
        }
        await RunSearchAsync(query);
    }

    private async Task RunSearchAsync(string query)
    {
        SearchButton.IsEnabled = false;
        SuggestionsCard.IsVisible = false;
        GlobalStatusText.Text = $"Searching YouTube for \"{query}\"...";
        OnRawOutputReceived(this, $"[Search] Querying YouTube for: {query}");

        try
        {
            var results = await _client.SearchAsync(query, limit: 10);
            SearchResultsListBox.ItemsSource = results;
            SearchResultsHeader.Text = results.Count > 0
                ? $"YouTube Search Results ({results.Count})"
                : $"No YouTube results found for \"{query}\"";
            SearchResultsCard.IsVisible = true;
            GlobalStatusText.Text = $"Found {results.Count} YouTube results.";
        }
        catch (Exception ex)
        {
            OnRawOutputReceived(this, $"[Error] YouTube search failed: {ex.Message}");
            GlobalStatusText.Text = $"Search failed: {ex.Message}";
        }
        finally
        {
            SearchButton.IsEnabled = true;
        }
    }

    private void SelectSearchResult_Click(object? sender, RoutedEventArgs e)
    {
        if (sender is Button { DataContext: SearchResultModel item } && !string.IsNullOrWhiteSpace(item.Url))
        {
            SearchResultsCard.IsVisible = false;
            SuggestionsCard.IsVisible = false;
            UrlTextBox.Text = item.Url;
            GlobalStatusText.Text = $"Selected: {item.Title}";
        }
    }

    private void CloseSearchResults_Click(object? sender, RoutedEventArgs e)
    {
        SearchResultsCard.IsVisible = false;
    }

    private async void SniffButton_Click(object? sender, RoutedEventArgs e)
    {
        var url = UrlTextBox.Text?.Trim();
        if (string.IsNullOrWhiteSpace(url))
        {
            GlobalStatusText.Text = "Enter a webpage URL to sniff embedded media streams.";
            return;
        }

        SniffButton.IsEnabled = false;
        GlobalStatusText.Text = $"Sniffing embedded media on {url}...";
        OnRawOutputReceived(this, $"[Sniffer] Scanning webpage HTML: {url}");

        try
        {
            var items = await _client.SniffPageMediaAsync(url);
            SniffedMediaListBox.ItemsSource = items;
            SniffedMediaHeader.Text = items.Count > 0
                ? $"Discovered Page Media ({items.Count})"
                : "No embedded video/audio/HLS streams found on this page";
            SniffedMediaCard.IsVisible = true;
            GlobalStatusText.Text = $"Discovered {items.Count} embedded stream(s).";
        }
        catch (Exception ex)
        {
            OnRawOutputReceived(this, $"[Error] Media sniff failed: {ex.Message}");
            GlobalStatusText.Text = $"Sniff failed: {ex.Message}";
        }
        finally
        {
            SniffButton.IsEnabled = true;
        }
    }

    private void SelectSniffedMedia_Click(object? sender, RoutedEventArgs e)
    {
        if (sender is Button { DataContext: SniffedMediaModel item } && !string.IsNullOrWhiteSpace(item.Url))
        {
            SniffedMediaCard.IsVisible = false;
            UrlTextBox.Text = item.Url;
            GlobalStatusText.Text = $"Loaded sniffed {item.MediaType.ToUpperInvariant()} stream.";
        }
    }

    private void CloseSniffedMedia_Click(object? sender, RoutedEventArgs e)
    {
        SniffedMediaCard.IsVisible = false;
    }

    private async void ConvertLocalMp3Button_Click(object? sender, RoutedEventArgs e)
    {
        await ConvertLocalFileInteractiveAsync("mp3", remuxOnly: false);
    }

    private async void RemuxLocalMp4Button_Click(object? sender, RoutedEventArgs e)
    {
        await ConvertLocalFileInteractiveAsync("mp4", remuxOnly: true);
    }

    private async Task ConvertLocalFileInteractiveAsync(string targetFormat, bool remuxOnly)
    {
        var topLevel = TopLevel.GetTopLevel(this);
        if (topLevel == null) return;

        var files = await topLevel.StorageProvider.OpenFilePickerAsync(new FilePickerOpenOptions
        {
            Title = remuxOnly ? $"Select video to remux to {targetFormat.ToUpperInvariant()}" : $"Select media file to convert to {targetFormat.ToUpperInvariant()}",
            AllowMultiple = false,
        });

        var picked = files.FirstOrDefault();
        var localPath = picked?.TryGetLocalPath();
        if (string.IsNullOrWhiteSpace(localPath)) return;

        GlobalStatusText.Text = $"Converting {Path.GetFileName(localPath)} → {targetFormat.ToUpperInvariant()}...";
        OnRawOutputReceived(this, $"[Converter] Converting '{localPath}' to {targetFormat} (remuxOnly={remuxOnly})...");

        try
        {
            var outputFile = await _client.ConvertLocalMediaAsync(localPath, targetFormat, remuxOnly, GetEffectiveOutputDirectory());
            OnRawOutputReceived(this, $"[Success] Converted media saved: {outputFile}");
            GlobalStatusText.Text = $"Saved converted file: {Path.GetFileName(outputFile)}";
        }
        catch (Exception ex)
        {
            OnRawOutputReceived(this, $"[Error] Conversion failed: {ex.Message}");
            GlobalStatusText.Text = $"Conversion failed: {ex.Message}";
        }
    }

    private async void RegisterNativeHostButton_Click(object? sender, RoutedEventArgs e)
    {
        RegisterNativeHostButton.IsEnabled = false;
        GlobalStatusText.Text = "Registering Browser Native Messaging Host...";
        try
        {
            var (ok, msg) = await _client.RegisterNativeHostAsync();
            OnRawOutputReceived(this, ok ? $"[Success] {msg}" : $"[Error] {msg}");
            GlobalStatusText.Text = string.IsNullOrWhiteSpace(msg) ? (ok ? "Browser Companion registered!" : "Registration failed.") : msg;
        }
        catch (Exception ex)
        {
            OnRawOutputReceived(this, $"[Error] Native host registration failed: {ex.Message}");
            GlobalStatusText.Text = $"Registration failed: {ex.Message}";
        }
        finally
        {
            RegisterNativeHostButton.IsEnabled = true;
        }
    }
}
