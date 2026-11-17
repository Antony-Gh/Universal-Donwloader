using System.Diagnostics;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using UniversalDownloader.Core;
using UniversalDownloader.Core.Models;

namespace UniversalDownloader.App;

public partial class MainWindow : Window
{
    private readonly DownloaderClient _client;
    private CancellationTokenSource? _downloadCts;

    public MainWindow()
    {
        InitializeComponent();

        _client = new DownloaderClient();
        _client.ProgressChanged += OnProgressChanged;
        _client.DownloadCompleted += OnDownloadCompleted;
        _client.DownloadFailed += OnDownloadFailed;
        _client.StatusChanged += OnStatusChanged;

        Loaded += async (s, e) => await LoadHistoryAsync();
    }

    private void OnProgressChanged(object? sender, DownloadProgressEvent e)
    {
        Dispatcher.Invoke(() =>
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
        Dispatcher.Invoke(() =>
        {
            StatusLabel.Text = status;
            GlobalStatusText.Text = status;
        });
    }

    private void OnDownloadCompleted(object? sender, DownloadCompleteEvent e)
    {
        Dispatcher.Invoke(async () =>
        {
            DownloadProgressBar.Value = 100;
            PercentLabel.Text = "100%";
            StatusLabel.Text = "✓ Download finished!";
            GlobalStatusText.Text = $"Successfully downloaded: {e.Title ?? e.Url}";
            SetDownloadingState(false);

            await LoadHistoryAsync();
        });
    }

    private void OnDownloadFailed(object? sender, DownloadErrorEvent e)
    {
        Dispatcher.Invoke(() =>
        {
            StatusLabel.Text = "✗ Download failed";
            GlobalStatusText.Text = $"Failed: {e.Error}";
            SetDownloadingState(false);
            MessageBox.Show(e.Error, "Download Error", MessageBoxButton.OK, MessageBoxImage.Error);
        });
    }

    private async void DownloadButton_Click(object sender, RoutedEventArgs e)
    {
        var url = UrlTextBox.Text.Trim();
        if (string.IsNullOrWhiteSpace(url))
        {
            MessageBox.Show("Please enter a media URL.", "Input Required", MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }

        SetDownloadingState(true);
        ProgressCard.Visibility = Visibility.Visible;
        DownloadProgressBar.Value = 0;
        PercentLabel.Text = "0.0%";
        StatusLabel.Text = "Connecting to extractor...";

        var options = BuildOptionsFromUI();
        _downloadCts = new CancellationTokenSource();

        try
        {
            await _client.DownloadAsync(url, options, _downloadCts.Token);
        }
        catch (OperationCanceledException)
        {
            StatusLabel.Text = "Download canceled.";
            GlobalStatusText.Text = "Canceled by user.";
            SetDownloadingState(false);
        }
        catch (Exception ex)
        {
            StatusLabel.Text = "✗ Download failed";
            GlobalStatusText.Text = $"Error: {ex.Message}";
            SetDownloadingState(false);
        }
    }

    private void CancelButton_Click(object sender, RoutedEventArgs e)
    {
        _downloadCts?.Cancel();
        _client.Cancel();
        CancelButton.IsEnabled = false;
        GlobalStatusText.Text = "Canceling download...";
    }

    private async void InspectButton_Click(object sender, RoutedEventArgs e)
    {
        var url = UrlTextBox.Text.Trim();
        if (string.IsNullOrWhiteSpace(url))
        {
            MessageBox.Show("Please enter a media URL to inspect.", "Input Required", MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }

        InspectButton.IsEnabled = false;
        GlobalStatusText.Text = "Inspecting formats...";

        try
        {
            var formats = await _client.GetFormatsAsync(url);
            FormatsDataGrid.ItemsSource = formats;
            FormatsCard.Visibility = formats.Count > 0 ? Visibility.Visible : Visibility.Collapsed;
            GlobalStatusText.Text = $"Found {formats.Count} available streams.";
        }
        catch (Exception ex)
        {
            MessageBox.Show($"Failed to inspect formats: {ex.Message}", "Inspection Error", MessageBoxButton.OK, MessageBoxImage.Error);
            GlobalStatusText.Text = "Inspection failed.";
        }
        finally
        {
            InspectButton.IsEnabled = true;
        }
    }

    private void PasteButton_Click(object sender, RoutedEventArgs e)
    {
        if (Clipboard.ContainsText())
        {
            UrlTextBox.Text = Clipboard.GetText().Trim();
            UrlTextBox.Focus();
        }
    }

    private void UrlTextBox_KeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter)
        {
            DownloadButton_Click(sender, e);
        }
    }

    private DownloadOptions BuildOptionsFromUI()
    {
        var options = new DownloadOptions
        {
            OutputDirectory = DownloadDirBox.Text.Trim(),
            EmbedMetadata = EmbedMetadataCheck.IsChecked ?? true,
            EmbedThumbnail = EmbedThumbnailCheck.IsChecked ?? true,
            EmbedSubs = EmbedSubsCheck.IsChecked ?? false,
            WriteThumbnail = WriteThumbnailCheck.IsChecked ?? false,
            StartTime = string.IsNullOrWhiteSpace(StartTimeBox.Text) ? null : StartTimeBox.Text.Trim(),
            EndTime = string.IsNullOrWhiteSpace(EndTimeBox.Text) ? null : EndTimeBox.Text.Trim(),
            Proxy = string.IsNullOrWhiteSpace(ProxyBox.Text) ? null : ProxyBox.Text.Trim(),
            LimitRate = string.IsNullOrWhiteSpace(LimitRateBox.Text) ? null : LimitRateBox.Text.Trim(),
        };

        // Quality mapping
        options.Quality = QualityComboBox.SelectedIndex switch
        {
            1 => "1080p",
            2 => "720p",
            3 => "480p",
            4 => "audio",
            _ => "best",
        };

        if (QualityComboBox.SelectedIndex == 4)
        {
            options.AudioOnly = true;
            options.AudioFormat = AudioFormatComboBox.SelectedIndex switch
            {
                1 => "mp3",
                2 => "m4a",
                3 => "flac",
                4 => "best",
                _ => "mp3",
            };
            options.AudioQuality = AudioFormatComboBox.SelectedIndex == 1 ? "320k" : "192k";
        }

        // Codec preference
        options.PreferCodec = CodecComboBox.SelectedIndex switch
        {
            1 => "h264",
            2 => "vp9",
            3 => "av01",
            _ => null,
        };

        // Browser cookies
        options.CookiesFromBrowser = BrowserCookiesComboBox.SelectedIndex switch
        {
            1 => "chrome",
            2 => "edge",
            3 => "firefox",
            4 => "brave",
            _ => null,
        };

        return options;
    }

    private void SetDownloadingState(bool isDownloading)
    {
        DownloadButton.IsEnabled = !isDownloading;
        InspectButton.IsEnabled = !isDownloading;
        CancelButton.IsEnabled = isDownloading;
    }

    private async Task LoadHistoryAsync(string? search = null)
    {
        try
        {
            var records = await _client.GetHistoryAsync(limit: 100, search: search);
            HistoryDataGrid.ItemsSource = records;
        }
        catch (Exception ex)
        {
            GlobalStatusText.Text = $"Failed to load history: {ex.Message}";
        }
    }

    private async void HistorySearchButton_Click(object sender, RoutedEventArgs e)
    {
        var query = HistorySearchBox.Text.Trim();
        await LoadHistoryAsync(string.IsNullOrWhiteSpace(query) ? null : query);
    }

    private async void HistoryRefreshButton_Click(object sender, RoutedEventArgs e)
    {
        HistorySearchBox.Clear();
        await LoadHistoryAsync();
    }

    private async void HistoryClearButton_Click(object sender, RoutedEventArgs e)
    {
        var result = MessageBox.Show("Are you sure you want to clear all download history?", "Confirm Clear", MessageBoxButton.YesNo, MessageBoxImage.Question);
        if (result == MessageBoxResult.Yes)
        {
            await _client.ClearHistoryAsync();
            await LoadHistoryAsync();
        }
    }

    private void HistorySearchBox_KeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter)
        {
            HistorySearchButton_Click(sender, e);
        }
    }

    private void OpenMediaFile_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button btn && btn.DataContext is HistoryRecordModel record)
        {
            if (File.Exists(record.PrimaryFilepath))
            {
                PlatformUtils.OpenFile(record.PrimaryFilepath);
            }
            else
            {
                MessageBox.Show($"File does not exist on disk:\n{record.PrimaryFilepath}", "File Not Found", MessageBoxButton.OK, MessageBoxImage.Warning);
            }
        }
    }

    private void ShowFolder_Click(object sender, RoutedEventArgs e)
    {
        if (sender is Button btn && btn.DataContext is HistoryRecordModel record)
        {
            if (!string.IsNullOrWhiteSpace(record.PrimaryFilepath))
            {
                PlatformUtils.OpenFolder(record.PrimaryFilepath);
            }
        }
    }

    private void BrowseDirButton_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new Microsoft.Win32.OpenFolderDialog
        {
            Title = "Select Default Download Directory",
            InitialDirectory = Path.GetFullPath(DownloadDirBox.Text),
        };

        if (dialog.ShowDialog() == true)
        {
            DownloadDirBox.Text = dialog.FolderName;
        }
    }

    private void RegisterProtocolButton_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var res = Process.Start(new ProcessStartInfo("python", "downloader.py --register-protocol")
            {
                UseShellExecute = false,
                CreateNoWindow = true,
            });
            res?.WaitForExit();
            MessageBox.Show("Successfully registered downloader:// protocol in Windows Registry!\nYou can now trigger downloads directly from browser bookmarklets.", "Success", MessageBoxButton.OK, MessageBoxImage.Information);
        }
        catch (Exception ex)
        {
            MessageBox.Show($"Failed to register protocol: {ex.Message}", "Error", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }
}
