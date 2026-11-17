using System.Text.Json.Serialization;

namespace UniversalDownloader.Core.Models;

/// <summary>
/// Event emitted upon successful completion of media download.
/// </summary>
public record DownloadCompleteEvent
{
    [JsonPropertyName("event")]
    public string Event { get; init; } = "complete";

    [JsonPropertyName("url")]
    public string Url { get; init; } = string.Empty;

    [JsonPropertyName("files")]
    public List<string> Files { get; init; } = new();

    [JsonPropertyName("title")]
    public string? Title { get; init; }

    [JsonPropertyName("uploader")]
    public string? Uploader { get; init; }

    public string PrimaryFile => Files.Count > 0 ? Files[0] : string.Empty;
}

/// <summary>
/// Event emitted when download fails.
/// </summary>
public record DownloadErrorEvent
{
    [JsonPropertyName("event")]
    public string Event { get; init; } = "error";

    [JsonPropertyName("url")]
    public string Url { get; init; } = string.Empty;

    [JsonPropertyName("error")]
    public string Error { get; init; } = string.Empty;
}
