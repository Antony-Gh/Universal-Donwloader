using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Media;
using Avalonia.Platform.Storage;
using Avalonia.Threading;
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;

namespace UniversalDownloader.Avalonia;

public partial class LogWindow : Window
{
    private const int MaxLogCapacity = 5000;
    private readonly List<string> _allLogs = new();

    public LogWindow()
    {
        InitializeComponent();
    }

    public void AppendLog(string message)
    {
        var timestamped = $"[{DateTime.Now:HH:mm:ss}] {message}";

        if (_allLogs.Count >= MaxLogCapacity)
        {
            _allLogs.RemoveRange(0, 500);
        }
        _allLogs.Add(timestamped);

        Dispatcher.UIThread.Post(() =>
        {
            var filter = FilterBox.Text?.Trim();
            if (string.IsNullOrEmpty(filter) || timestamped.Contains(filter, StringComparison.OrdinalIgnoreCase))
            {
                if (string.IsNullOrEmpty(LogTextBox.Text))
                {
                    LogTextBox.Text = timestamped;
                }
                else
                {
                    LogTextBox.Text += Environment.NewLine + timestamped;
                }

                if (AutoScrollCheck.IsChecked ?? true)
                {
                    LogTextBox.CaretIndex = LogTextBox.Text.Length;
                }
            }
            UpdateCountLabel();
        });
    }

    public void LoadLogs(IEnumerable<string> existingLogs)
    {
        _allLogs.Clear();
        _allLogs.AddRange(existingLogs.TakeLast(MaxLogCapacity));
        ApplyFilter();
    }

    private void ApplyFilter()
    {
        var filter = FilterBox.Text?.Trim();
        var filtered = string.IsNullOrEmpty(filter)
            ? _allLogs
            : _allLogs.Where(l => l.Contains(filter, StringComparison.OrdinalIgnoreCase)).ToList();

        LogTextBox.Text = string.Join(Environment.NewLine, filtered);
        if (AutoScrollCheck.IsChecked ?? true)
        {
            LogTextBox.CaretIndex = LogTextBox.Text?.Length ?? 0;
        }

        UpdateCountLabel(filtered.Count);
    }

    private void UpdateCountLabel(int? filteredCount = null)
    {
        var total = _allLogs.Count;
        var shown = filteredCount ?? total;
        LogCountLabel.Text = total == shown
            ? $"Total: {total} log lines"
            : $"Showing {shown} of {total} log lines (filtered)";
    }

    private void FilterBox_TextChanged(object? sender, TextChangedEventArgs e)
    {
        ApplyFilter();
    }

    private void WordWrapCheck_IsCheckedChanged(object? sender, RoutedEventArgs e)
    {
        LogTextBox.TextWrapping = (WordWrapCheck.IsChecked ?? true)
            ? global::Avalonia.Media.TextWrapping.Wrap
            : global::Avalonia.Media.TextWrapping.NoWrap;
    }

    private async void CopyButton_Click(object? sender, RoutedEventArgs e)
    {
        var clipboard = TopLevel.GetTopLevel(this)?.Clipboard;
        if (clipboard != null && !string.IsNullOrEmpty(LogTextBox.Text))
        {
            await clipboard.SetTextAsync(LogTextBox.Text);
            CopyButton.Content = "✓ Copied!";
            DispatcherTimer.RunOnce(() => CopyButton.Content = "📋 Copy All", TimeSpan.FromSeconds(2));
        }
    }

    private async void SaveButton_Click(object? sender, RoutedEventArgs e)
    {
        if (string.IsNullOrEmpty(LogTextBox.Text)) return;

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
            await writer.WriteAsync(LogTextBox.Text);
            SaveButton.Content = "✓ Saved!";
            DispatcherTimer.RunOnce(() => SaveButton.Content = "💾 Save Logs", TimeSpan.FromSeconds(2));
        }
    }

    private void ClearButton_Click(object? sender, RoutedEventArgs e)
    {
        _allLogs.Clear();
        LogTextBox.Text = string.Empty;
        UpdateCountLabel();
    }
}
