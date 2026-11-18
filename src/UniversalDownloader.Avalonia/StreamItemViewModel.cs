using Avalonia.Media.Imaging;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using UniversalDownloader.Core.Models;

namespace UniversalDownloader.Avalonia;

/// <summary>
/// Presentation wrapper for a discovered stream or picture item in the Streams Explorer list,
/// supporting asynchronous live image thumbnail previews.
/// </summary>
public sealed class StreamItemViewModel : INotifyPropertyChanged
{
    private Bitmap? _previewBitmap;
    private bool _isLoadingPreview;

    public FormatInfoModel Format { get; }

    public StreamItemViewModel(FormatInfoModel format)
    {
        Format = format;
        _isLoadingPreview = format.IsImage && !string.IsNullOrWhiteSpace(format.DirectUrl);
    }

    public bool IsImage => Format.IsImage;
    public string ResolutionFormatted => Format.ResolutionFormatted;
    public string Extension => Format.Extension;
    public string CodecSummary => Format.CodecSummary;
    public string FormatNote => Format.FormatNote;
    public string FilesizeFormatted => Format.FilesizeFormatted;

    public Bitmap? PreviewBitmap
    {
        get => _previewBitmap;
        set
        {
            if (!ReferenceEquals(_previewBitmap, value))
            {
                _previewBitmap = value;
                OnPropertyChanged();
            }
        }
    }

    public bool IsLoadingPreview
    {
        get => _isLoadingPreview;
        set
        {
            if (_isLoadingPreview != value)
            {
                _isLoadingPreview = value;
                OnPropertyChanged();
            }
        }
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    private void OnPropertyChanged([CallerMemberName] string? propertyName = null)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
}
