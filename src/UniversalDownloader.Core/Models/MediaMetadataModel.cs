using System;
using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace UniversalDownloader.Core.Models;

public record ProfileInfoItemModel
{
    [JsonPropertyName("label")]
    public string Label { get; init; } = string.Empty;

    [JsonPropertyName("value")]
    public string Value { get; init; } = string.Empty;

    [JsonPropertyName("copy_value")]
    public string? CopyValue { get; init; }

    public string EffectiveCopyValue => string.IsNullOrWhiteSpace(CopyValue) ? Value : CopyValue;
    public string DisplayText => $"{Label}: {Value}";
}

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

    [JsonPropertyName("codecs")]
    public List<string> Codecs { get; init; } = new();

    [JsonPropertyName("is_profile")]
    public bool IsProfile { get; init; }

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
    public List<string> Qualities
    {
        get => _qualities ??= new();
        init => _qualities = value ?? new();
    }
    private List<string>? _qualities;

    [JsonPropertyName("codecs")]
    public List<string> Codecs
    {
        get => _codecs ??= new();
        init => _codecs = value ?? new();
    }
    private List<string>? _codecs;

    [JsonPropertyName("is_profile")]
    public bool IsProfile { get; init; }

    [JsonPropertyName("entries")]
    public List<PlaylistEntryModel> Entries
    {
        get => _entries ??= new();
        init => _entries = value ?? new();
    }
    private List<PlaylistEntryModel>? _entries;

    [JsonPropertyName("profile_locked")]
    public bool ProfileLocked { get; init; }

    [JsonPropertyName("profile_notice")]
    public string? ProfileNotice { get; init; }

    [JsonPropertyName("profile_id")]
    public string? ProfileId { get; init; }

    [JsonPropertyName("bio")]
    public string? Bio { get; init; }

    [JsonPropertyName("is_verified")]
    public bool IsVerified { get; init; }

    [JsonPropertyName("profile_info")]
    public List<ProfileInfoItemModel> ProfileInfo
    {
        get => _profileInfo ??= new();
        init => _profileInfo = value ?? new();
    }
    private List<ProfileInfoItemModel>? _profileInfo;

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
