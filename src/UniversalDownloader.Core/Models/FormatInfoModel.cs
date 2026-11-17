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

    public bool HasVideo => !string.IsNullOrWhiteSpace(VCodec) && VCodec != "none";
    public bool HasAudio => !string.IsNullOrWhiteSpace(ACodec) && ACodec != "none";

    public string DisplayText => $"{Resolution} ({Extension}) {(Fps.HasValue ? Fps + "fps" : "")} - {FormatNote}".Trim();
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
