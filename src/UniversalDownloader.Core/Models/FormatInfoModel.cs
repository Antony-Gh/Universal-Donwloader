using System.Text.Json.Serialization;

namespace UniversalDownloader.Core.Models;

public record FormatInfoModel
{
    [JsonPropertyName("format_id")]
    public string FormatId { get; init; } = string.Empty;

    [JsonPropertyName("ext")]
    public string Extension { get; init; } = string.Empty;

    [JsonPropertyName("resolution")]
    public string Resolution { get; init; } = string.Empty;

    [JsonPropertyName("height")]
    public int? Height { get; init; }

    [JsonPropertyName("width")]
    public int? Width { get; init; }

    [JsonPropertyName("fps")]
    public double? Fps { get; init; }

    [JsonPropertyName("filesize")]
    public long? Filesize { get; init; }

    [JsonPropertyName("vcodec")]
    public string VCodec { get; init; } = "none";

    [JsonPropertyName("acodec")]
    public string ACodec { get; init; } = "none";

    [JsonPropertyName("format_note")]
    public string FormatNote { get; init; } = string.Empty;

    [JsonPropertyName("url")]
    public string? DirectUrl { get; init; }

    public bool IsImage => string.Equals(VCodec, "image", StringComparison.OrdinalIgnoreCase);
    public bool HasVideo => !IsImage && !string.IsNullOrWhiteSpace(VCodec) && VCodec != "none";
    public bool HasAudio => !string.IsNullOrWhiteSpace(ACodec) && ACodec != "none";

    public string FilesizeFormatted => Filesize.HasValue ? PlatformUtils.FormatBytes(Filesize.Value) : "Unknown size";

    public string CodecSummary => IsImage
        ? $"Image • {(string.IsNullOrWhiteSpace(FormatNote) ? "Profile Picture" : FormatNote)}"
        : (HasVideo && HasAudio) ? $"Video: {VCodec} • Audio: {ACodec}" :
          HasVideo ? $"Video: {VCodec}" :
          HasAudio ? $"Audio: {ACodec}" : "Direct Stream";

    public string ResolutionFormatted => IsImage
        ? (!string.IsNullOrWhiteSpace(Resolution) ? Resolution : "Image")
        : (!string.IsNullOrWhiteSpace(Resolution) && Resolution != "audio only"
            ? (Fps.HasValue ? $"{Resolution} @ {Fps:0}fps" : Resolution)
            : (HasAudio ? "Audio Only" : "Stream"));

    public string DisplayText => $"{Resolution} ({Extension}) {(Fps.HasValue ? Fps + "fps" : "")} - {FormatNote}".Trim();

    /// <summary>
    /// Extracts clean, descending unique video quality labels (e.g. 2160p, 1080p, 720p) plus Audio when available.
    /// </summary>
    public static List<string> ExtractSupportedQualities(IEnumerable<FormatInfoModel> formats)
    {
        var list = formats?.ToList() ?? new List<FormatInfoModel>();
        if (list.Count == 0) return new List<string>();

        var heights = list
            .Where(f => f.HasVideo && f.Height.HasValue && f.Height.Value >= 144)
            .Select(f => f.Height!.Value)
            .Distinct()
            .OrderByDescending(h => h)
            .Select(h => $"{h}p")
            .ToList();

        if (heights.Count == 0 && list.Any(f => f.HasVideo))
        {
            heights.Add("Best");
        }

        if (list.Any(f => f.HasAudio))
        {
            heights.Add("Audio");
        }

        return heights;
    }
}

public record FormatInspectionResult
{
    public List<FormatInfoModel> Formats { get; init; } = new();
    public bool ProfileLocked { get; init; }
    public string? ProfileNotice { get; init; }
}

public record HistoryRecordModel
{
    [JsonPropertyName("id")]
    public int Id { get; init; }

    [JsonPropertyName("url")]
    public string Url { get; init; } = string.Empty;

    [JsonPropertyName("title")]
    public string Title { get; init; } = string.Empty;

    [JsonPropertyName("uploader")]
    public string Uploader { get; init; } = string.Empty;

    [JsonPropertyName("platform")]
    public string Platform { get; init; } = string.Empty;

    [JsonPropertyName("content_type")]
    public string ContentType { get; init; } = string.Empty;

    [JsonPropertyName("duration")]
    public int Duration { get; init; }

    [JsonPropertyName("filesize")]
    public long Filesize { get; init; }

    [JsonPropertyName("primary_filepath")]
    public string PrimaryFilepath { get; init; } = string.Empty;

    [JsonPropertyName("thumbnail_url")]
    public string ThumbnailUrl { get; init; } = string.Empty;

    [JsonPropertyName("status")]
    public string Status { get; init; } = string.Empty;

    [JsonPropertyName("downloaded_at")]
    public string DownloadedAt { get; init; } = string.Empty;

    public string DateFormatted => DownloadedAt.Length >= 19 ? DownloadedAt.Substring(0, 19).Replace("T", " ") : DownloadedAt;
}
