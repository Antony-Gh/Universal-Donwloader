using System.Text.Json.Serialization;

namespace UniversalDownloader.Core.Models;

/// <summary>
/// Represents an embedded video, audio, HLS, or DASH stream discovered on a webpage via --sniff.
/// </summary>
public class SniffedMediaModel
{
    [JsonPropertyName("url")]
    public string Url { get; set; } = string.Empty;

    [JsonPropertyName("media_type")]
    public string MediaType { get; set; } = "video";

    [JsonPropertyName("source")]
    public string Source { get; set; } = string.Empty;

    [JsonPropertyName("mime_type")]
    public string? MimeType { get; set; }

    [JsonPropertyName("title")]
    public string? Title { get; set; }
}
