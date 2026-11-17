using System.ComponentModel;
using System.Runtime.CompilerServices;

namespace UniversalDownloader.Core.Models;

public enum QueueItemStatus
{
    Queued,
    Downloading,
    Completed,
    Failed,
    Canceled
}

public class QueueItemModel : INotifyPropertyChanged
{
    private string _title = string.Empty;
    private QueueItemStatus _status = QueueItemStatus.Queued;
    private double _progress;
    private string _statusDetail = "Waiting in queue";

    public string Id { get; init; } = Guid.NewGuid().ToString("N")[..8];
    public string Url { get; init; } = string.Empty;
    public DownloadOptions Options { get; init; } = new();

    public string Title
    {
        get => string.IsNullOrWhiteSpace(_title) ? Url : _title;
        set { if (_title != value) { _title = value; OnPropertyChanged(); } }
    }

    public QueueItemStatus Status
    {
        get => _status;
        set
        {
            if (_status != value)
            {
                _status = value;
                OnPropertyChanged();
                OnPropertyChanged(nameof(StatusBadgeText));
                OnPropertyChanged(nameof(StatusColorHex));
            }
        }
    }

    public double Progress
    {
        get => _progress;
        set
        {
            var clamped = Math.Clamp(value, 0, 100);
            if (Math.Abs(_progress - clamped) > 0.05)
            {
                _progress = clamped;
                OnPropertyChanged();
                OnPropertyChanged(nameof(ProgressText));
            }
        }
    }

    public string StatusDetail
    {
        get => _statusDetail;
        set { if (_statusDetail != value) { _statusDetail = value; OnPropertyChanged(); } }
    }

    public string StatusBadgeText => Status.ToString().ToUpperInvariant();
    public string QualityBadgeText => Options.AudioOnly
        ? "MP3"
        : (string.IsNullOrWhiteSpace(Options.Quality) ? "BEST" : Options.Quality.ToUpperInvariant());
    public string ProgressText => $"{Progress:F1}%";

    public string StatusColorHex => Status switch
    {
        QueueItemStatus.Downloading => "#38BDF8",
        QueueItemStatus.Completed => "#10B981",
        QueueItemStatus.Failed => "#EF4444",
        QueueItemStatus.Canceled => "#F59E0B",
        _ => "#94A3B8"
    };

    public event PropertyChangedEventHandler? PropertyChanged;

    private void OnPropertyChanged([CallerMemberName] string? name = null) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}
