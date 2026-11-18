using System;
using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace UniversalDownloader.Core.Models;

public record PlaylistEntryModel
{
    [JsonPropertyName("index")]
    public int Index { get; init; }

    [JsonPropertyName("id")]
    public string Id { get; init; } = string.Empty;

    [JsonPropertyName("url")]
    public string Url { get; init; } = string.Empty;

    [JsonPropertyName("title")]
    public string Title { get; init; } = string.Empty;

    [JsonPropertyName("uploader")]
    public string Uploader { get; init; } = string.Empty;

    [JsonPropertyName("duration")]
    public double? Duration { get; init; }

    [JsonPropertyName("duration_string")]
    public string? DurationString { get; init; }

    [JsonPropertyName("thumbnail")]
    public string? Thumbnail { get; init; }

    [JsonPropertyName("view_count")]
    public long? ViewCount { get; init; }

    [JsonPropertyName("qualities")]
    public List<string> Qualities { get; init; } = new();

    public string DurationFormatted
    {
        get
        {
            if (!string.IsNullOrEmpty(DurationString)) return DurationString;
            if (Duration.HasValue && Duration.Value > 0)
            {
                var ts = TimeSpan.FromSeconds(Duration.Value);
                return ts.TotalHours >= 1 ? ts.ToString(@"h\:mm\:ss") : ts.ToString(@"m\:ss");
            }
            return "";
        }
    }
}

public record MediaMetadataModel
{
    [JsonPropertyName("url")]
    public string Url { get; init; } = string.Empty;

    [JsonPropertyName("platform")]
    public string Platform { get; init; } = string.Empty;

    [JsonPropertyName("title")]
    public string Title { get; init; } = string.Empty;

    [JsonPropertyName("uploader")]
    public string Uploader { get; init; } = string.Empty;

    [JsonPropertyName("duration")]
    public double? Duration { get; init; }

    [JsonPropertyName("duration_string")]
    public string? DurationString { get; init; }

    [JsonPropertyName("thumbnail")]
    public string? Thumbnail { get; init; }

    [JsonPropertyName("view_count")]
    public long? ViewCount { get; init; }

    [JsonPropertyName("description")]
    public string? Description { get; init; }

    [JsonPropertyName("is_playlist")]
    public bool IsPlaylist { get; init; }

    [JsonPropertyName("playlist_count")]
    public int PlaylistCount { get; init; }

    [JsonPropertyName("qualities")]
    public List<string> Qualities { get; init; } = new();

    [JsonPropertyName("entries")]
    public List<PlaylistEntryModel> Entries { get; init; } = new();

    [JsonPropertyName("profile_locked")]
    public bool ProfileLocked { get; init; }

    [JsonPropertyName("profile_notice")]
    public string? ProfileNotice { get; init; }

    public string DurationFormatted
    {
        get
        {
            if (!string.IsNullOrEmpty(DurationString)) return DurationString;
            if (Duration.HasValue && Duration.Value > 0)
            {
                var ts = TimeSpan.FromSeconds(Duration.Value);
                return ts.TotalHours >= 1 ? ts.ToString(@"h\:mm\:ss") : ts.ToString(@"m\:ss");
            }
            return "";
        }
    }

    public string ViewCountFormatted
    {
        get
        {
            if (!ViewCount.HasValue) return "";
            var v = ViewCount.Value;
            if (v >= 1_000_000_000) return $"{v / 1_000_000_000.0:0.#}B views";
            if (v >= 1_000_000) return $"{v / 1_000_000.0:0.#}M views";
            if (v >= 1_000) return $"{v / 1_000.0:0.#}K views";
            return $"{v} views";
        }
    }
}
