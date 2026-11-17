using System.Text.Json.Serialization;

namespace UniversalDownloader.Core.Models;

/// <summary>
/// Real-time download progress event emitted from python backend via --json-stream.
/// </summary>
public record DownloadProgressEvent
{
    [JsonPropertyName("event")]
    public string Event { get; init; } = "progress";

    [JsonPropertyName("status")]
    public string Status { get; init; } = "downloading";

    [JsonPropertyName("downloaded_bytes")]
    public long DownloadedBytes { get; init; }

    [JsonPropertyName("total_bytes")]
    public long? TotalBytes { get; init; }

    [JsonPropertyName("percent")]
    public double Percent { get; init; }

    [JsonPropertyName("speed")]
    public double? Speed { get; init; }

    [JsonPropertyName("eta")]
    public int? Eta { get; init; }

    [JsonPropertyName("filename")]
    public string? Filename { get; init; }

    // Human-friendly helpers
    public string SpeedFormatted => Speed.HasValue ? $"{FormatBytes(Speed.Value)}/s" : "Calculating...";

    public string DownloadedFormatted => FormatBytes(DownloadedBytes);

    public string TotalFormatted => TotalBytes.HasValue ? FormatBytes(TotalBytes.Value) : "Unknown";

    public string ProgressSummary => $"{DownloadedFormatted} / {TotalFormatted} ({Percent:F1}%)";

    public string EtaFormatted
    {
        get
        {
            if (!Eta.HasValue || Eta.Value <= 0) return "--:--";
            var time = TimeSpan.FromSeconds(Eta.Value);
            return time.Hours > 0
                ? $"{time.Hours:D2}:{time.Minutes:D2}:{time.Seconds:D2}"
                : $"{time.Minutes:D2}:{time.Seconds:D2}";
        }
    }

    private static string FormatBytes(double bytes)
    {
        string[] units = { "B", "KB", "MB", "GB", "TB" };
        int unitIndex = 0;
        while (bytes >= 1024 && unitIndex < units.Length - 1)
        {
            bytes /= 1024;
            unitIndex++;
        }
        return $"{bytes:F2} {units[unitIndex]}";
    }
}
