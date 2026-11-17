using Avalonia.Media.Imaging;
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Linq;
using System.Runtime.CompilerServices;
using UniversalDownloader.Core.Models;

namespace UniversalDownloader.Avalonia;

public class QualityOptionChip : INotifyPropertyChanged
{
    private bool _isSelected;

    public string Label { get; init; } = string.Empty;
    public string QualityValue { get; init; } = "best";
    public PlaylistVideoCardModel? Owner { get; init; }

    public bool IsSelected
    {
        get => _isSelected;
        set
        {
            if (_isSelected != value)
            {
                _isSelected = value;
                OnPropertyChanged();
                OnPropertyChanged(nameof(BackgroundHex));
                OnPropertyChanged(nameof(BorderHex));
                OnPropertyChanged(nameof(ForegroundHex));
            }
        }
    }

    public string BackgroundHex => IsSelected ? "#4F46E5" : "#27272A";
    public string BorderHex => IsSelected ? "#818CF8" : "#3F3F46";
    public string ForegroundHex => IsSelected ? "#FFFFFF" : "#CBD5E1";

    public event PropertyChangedEventHandler? PropertyChanged;

    private void OnPropertyChanged([CallerMemberName] string? name = null) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}

public class PlaylistVideoCardModel : INotifyPropertyChanged
{
    private Bitmap? _thumbnailBitmap;
    private bool _isThumbnailLoading = true;
    private bool _isLoadingQualities;
    private bool _needsManualQualityLoad;
    private string _qualityStatusText = string.Empty;
    private string _selectedQualityValue = "best";
    private bool _isQueued;

    public int Index { get; init; }
    public string IndexBadge => $"#{Index}";
    public string Url { get; init; } = string.Empty;
    public string Title { get; init; } = string.Empty;
    public string Uploader { get; init; } = string.Empty;
    public string DurationFormatted { get; init; } = string.Empty;
    public bool HasDuration => !string.IsNullOrWhiteSpace(DurationFormatted);
    public string? ThumbnailUrl { get; init; }

    public ObservableCollection<QualityOptionChip> Qualities { get; } = new();

    public Bitmap? ThumbnailBitmap
    {
        get => _thumbnailBitmap;
        set { if (_thumbnailBitmap != value) { _thumbnailBitmap = value; OnPropertyChanged(); } }
    }

    public bool IsThumbnailLoading
    {
        get => _isThumbnailLoading;
        set { if (_isThumbnailLoading != value) { _isThumbnailLoading = value; OnPropertyChanged(); } }
    }

    public bool IsLoadingQualities
    {
        get => _isLoadingQualities;
        set
        {
            if (_isLoadingQualities != value)
            {
                _isLoadingQualities = value;
                OnPropertyChanged();
                OnPropertyChanged(nameof(ShowQualityStatusText));
            }
        }
    }

    public bool NeedsManualQualityLoad
    {
        get => _needsManualQualityLoad;
        set { if (_needsManualQualityLoad != value) { _needsManualQualityLoad = value; OnPropertyChanged(); } }
    }

    public bool HasQualities => Qualities.Count > 0;

    public bool ShowQualityStatusText => !IsLoadingQualities && !HasQualities && !NeedsManualQualityLoad && !string.IsNullOrWhiteSpace(QualityStatusText);

    public string QualityStatusText
    {
        get => _qualityStatusText;
        set
        {
            if (_qualityStatusText != value)
            {
                _qualityStatusText = value;
                OnPropertyChanged();
                OnPropertyChanged(nameof(ShowQualityStatusText));
            }
        }
    }

    public string SelectedQualityValue
    {
        get => _selectedQualityValue;
        set { if (_selectedQualityValue != value) { _selectedQualityValue = value; OnPropertyChanged(); } }
    }

    public bool IsQueued
    {
        get => _isQueued;
        set
        {
            if (_isQueued != value)
            {
                _isQueued = value;
                OnPropertyChanged();
                OnPropertyChanged(nameof(QueueButtonText));
            }
        }
    }

    public string QueueButtonText => IsQueued ? "Queued ✓" : "+ Queue";

    public static PlaylistVideoCardModel FromEntry(PlaylistEntryModel entry)
    {
        var card = new PlaylistVideoCardModel
        {
            Index = entry.Index,
            Url = entry.Url,
            Title = string.IsNullOrWhiteSpace(entry.Title) ? $"Video #{entry.Index}" : entry.Title,
            Uploader = entry.Uploader,
            DurationFormatted = entry.DurationFormatted,
            ThumbnailUrl = entry.Thumbnail,
            IsThumbnailLoading = !string.IsNullOrWhiteSpace(entry.Thumbnail),
        };

        if (entry.Qualities.Count > 0)
        {
            card.SetQualities(entry.Qualities);
        }

        return card;
    }

    public void SetQualities(IEnumerable<string> labels)
    {
        Qualities.Clear();
        var list = labels
            .Where(l => !string.IsNullOrWhiteSpace(l))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        for (int i = 0; i < list.Count; i++)
        {
            var label = list[i];
            var value = label.Equals("Audio", StringComparison.OrdinalIgnoreCase)
                ? "audio"
                : label.Equals("Best", StringComparison.OrdinalIgnoreCase)
                    ? "best"
                    : label.ToLowerInvariant();

            var chip = new QualityOptionChip
            {
                Label = label,
                QualityValue = value,
                IsSelected = i == 0,
                Owner = this,
            };
            Qualities.Add(chip);
        }

        SelectedQualityValue = Qualities.FirstOrDefault()?.QualityValue ?? "best";
        IsLoadingQualities = false;
        NeedsManualQualityLoad = false;
        QualityStatusText = Qualities.Count == 0 ? "Best available (default)" : string.Empty;
        OnPropertyChanged(nameof(HasQualities));
        OnPropertyChanged(nameof(ShowQualityStatusText));
    }

    public void SelectQuality(QualityOptionChip selected)
    {
        foreach (var chip in Qualities)
        {
            chip.IsSelected = ReferenceEquals(chip, selected);
        }
        SelectedQualityValue = selected.QualityValue;
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    private void OnPropertyChanged([CallerMemberName] string? name = null) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}
