using System.ComponentModel;
using System.Runtime.CompilerServices;
using UniversalDownloader.Core.Models;

namespace UniversalDownloader.Avalonia;

/// <summary>
/// Click-to-copy metadata chip displayed on the profile preview card (ID, @handle, Followers, Posts, Channel ID, DID, etc.).
/// </summary>
public sealed class ProfileInfoChipViewModel : INotifyPropertyChanged
{
    private bool _recentlyCopied;

    public string Label { get; }
    public string Value { get; }
    public string CopyValue { get; }

    public ProfileInfoChipViewModel(ProfileInfoItemModel model)
    {
        Label = model.Label;
        Value = model.Value;
        CopyValue = model.EffectiveCopyValue;
    }

    public ProfileInfoChipViewModel(string label, string value, string? copyValue = null)
    {
        Label = label;
        Value = value;
        CopyValue = string.IsNullOrWhiteSpace(copyValue) ? value : copyValue;
    }

    public bool RecentlyCopied
    {
        get => _recentlyCopied;
        set
        {
            if (_recentlyCopied != value)
            {
                _recentlyCopied = value;
                OnPropertyChanged();
                OnPropertyChanged(nameof(DisplayText));
                OnPropertyChanged(nameof(BorderHex));
                OnPropertyChanged(nameof(ForegroundHex));
            }
        }
    }

    public string DisplayText => RecentlyCopied ? $"✓ Copied {Label}" : $"{Label}: {Value}";
    public string TooltipText => $"Click to copy {Label}: {CopyValue}";
    public string BorderHex => RecentlyCopied ? "#10B981" : "#334155";
    public string ForegroundHex => RecentlyCopied ? "#6EE7B7" : "#BAE6FD";

    public event PropertyChangedEventHandler? PropertyChanged;

    private void OnPropertyChanged([CallerMemberName] string? propertyName = null)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
}
