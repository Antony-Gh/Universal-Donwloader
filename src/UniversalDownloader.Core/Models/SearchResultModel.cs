using System.Text.Json.Serialization;

namespace UniversalDownloader.Core.Models;

/// <summary>
/// Model representing a YouTube search result returned by the backend.
/// </summary>
public class SearchResultModel
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = string.Empty;

    [JsonPropertyName("url")]
    public string Url { get; set; } = string.Empty;

    [JsonPropertyName("title")]
    public string Title { get; set; } = string.Empty;

    [JsonPropertyName("uploader")]
    public string Uploader { get; set; } = string.Empty;

    [JsonPropertyName("duration")]
    public double? Duration { get; set; }

    [JsonPropertyName("duration_string")]
    public string? DurationString { get; set; }

    [JsonPropertyName("thumbnail")]
    public string? Thumbnail { get; set; }

    [JsonPropertyName("view_count")]
    public long? ViewCount { get; set; }

    [JsonPropertyName("source")]
    public string Source { get; set; } = "YouTube";
}
