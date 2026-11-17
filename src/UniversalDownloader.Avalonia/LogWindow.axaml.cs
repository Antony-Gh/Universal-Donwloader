using Avalonia.Controls;
using Avalonia.Interactivity;
using Avalonia.Platform.Storage;
using Avalonia.Threading;
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.IO;
using System.Linq;
using UniversalDownloader.Core;
using UniversalDownloader.Core.Models;

namespace UniversalDownloader.Avalonia;

public partial class LogWindow : Window
{
    private const int MaxLogCapacity = 5000;
    private readonly List<LogMessage> _allLogs = new();
    private readonly ObservableCollection<LogMessage> _filteredLogs = new();

    public LogWindow()
    {
        InitializeComponent();
        LogVersionLabel.Text = $"{UpdateChecker.AppDisplayName} v{UpdateChecker.GetCurrentVersion()}";
        LogListBox.ItemsSource = _filteredLogs;
    }

    public void AppendLog(string message)
    {
        var log = LogMessage.Create(message);

        if (_allLogs.Count >= MaxLogCapacity)
        {
            _allLogs.RemoveRange(0, 500);
        }
        _allLogs.Add(log);

        Dispatcher.UIThread.Post(() =>
        {
            var filter = FilterBox.Text?.Trim();
            if (string.IsNullOrEmpty(filter) || log.FormattedText.Contains(filter, StringComparison.OrdinalIgnoreCase))
            {
                if (_filteredLogs.Count >= MaxLogCapacity)
                {
                    _filteredLogs.RemoveAt(0);
                }
                _filteredLogs.Add(log);

                if (AutoScrollCheck.IsChecked ?? true)
                {
                    LogListBox.ScrollIntoView(log);
                }
            }
            UpdateCountLabel();
        });
    }

    public void LoadLogs(IEnumerable<LogMessage> existingLogs)
    {
        _allLogs.Clear();
        _allLogs.AddRange(existingLogs.TakeLast(MaxLogCapacity));
        ApplyFilter();
    }

    private void ApplyFilter()
    {
        var filter = FilterBox.Text?.Trim();
        var matching = string.IsNullOrEmpty(filter)
            ? _allLogs
            : _allLogs.Where(l => l.FormattedText.Contains(filter, StringComparison.OrdinalIgnoreCase)).ToList();

        _filteredLogs.Clear();
        foreach (var item in matching)
        {
            _filteredLogs.Add(item);
        }

        if ((AutoScrollCheck.IsChecked ?? true) && _filteredLogs.Count > 0)
        {
            LogListBox.ScrollIntoView(_filteredLogs[^1]);
        }

        UpdateCountLabel(matching.Count);
    }

    private void UpdateCountLabel(int? filteredCount = null)
    {
        var total = _allLogs.Count;
        var shown = filteredCount ?? _filteredLogs.Count;
        LogCountLabel.Text = total == shown
            ? $"Total: {total} log lines"
            : $"Showing {shown} of {total} log lines (filtered)";
    }

    private void FilterBox_TextChanged(object? sender, TextChangedEventArgs e)
    {
        ApplyFilter();
    }

    private async void CopyButton_Click(object? sender, RoutedEventArgs e)
    {
        var clipboard = TopLevel.GetTopLevel(this)?.Clipboard;
        if (clipboard != null && _filteredLogs.Count > 0)
        {
            var fullText = string.Join(Environment.NewLine, _filteredLogs.Select(l => l.FormattedText));
            await clipboard.SetTextAsync(fullText);
            CopyButtonText.Text = "Copied!";
            DispatcherTimer.RunOnce(() => CopyButtonText.Text = "Copy All", TimeSpan.FromSeconds(2));
        }
    }

    private async void SaveButton_Click(object? sender, RoutedEventArgs e)
    {
        if (_filteredLogs.Count == 0) return;

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
            var fullText = string.Join(Environment.NewLine, _filteredLogs.Select(l => l.FormattedText));
            await writer.WriteAsync(fullText);
            SaveButtonText.Text = "Saved!";
            DispatcherTimer.RunOnce(() => SaveButtonText.Text = "Save Logs", TimeSpan.FromSeconds(2));
        }
    }

    private void ClearButton_Click(object? sender, RoutedEventArgs e)
    {
        _allLogs.Clear();
        _filteredLogs.Clear();
        UpdateCountLabel();
    }
}
