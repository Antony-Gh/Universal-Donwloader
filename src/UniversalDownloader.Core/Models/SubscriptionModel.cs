using System.Text.Json.Serialization;

namespace UniversalDownloader.Core.Models;

public record SubscriptionModel
{
    [JsonPropertyName("id")]
    public int Id { get; init; }

    [JsonPropertyName("url")]
    public string Url { get; init; } = string.Empty;

    [JsonPropertyName("label")]
    public string Label { get; init; } = string.Empty;

    [JsonPropertyName("audio_only")]
    public bool AudioOnly { get; init; }

    [JsonPropertyName("quality")]
    public string Quality { get; init; } = "best";

    [JsonPropertyName("max_downloads")]
    public int MaxDownloads { get; init; } = 5;

    [JsonPropertyName("created_at")]
    public string? CreatedAt { get; init; }

    [JsonPropertyName("last_synced_at")]
    public string? LastSyncedAt { get; init; }

    public string DisplayTitle => string.IsNullOrWhiteSpace(Label) ? Url : Label;
    public string PreferenceSummary => $"{(AudioOnly ? "Audio (MP3)" : Quality)} • Max {MaxDownloads} videos";
    public string LastSyncedSummary => string.IsNullOrWhiteSpace(LastSyncedAt) ? "Never synced" : $"Synced: {LastSyncedAt}";
}

public record SubscriptionSyncResult
{
    [JsonPropertyName("success")]
    public bool Success { get; init; }

    [JsonPropertyName("total")]
    public int Total { get; init; }

    [JsonPropertyName("synced")]
    public int Synced { get; init; }

    [JsonPropertyName("failed")]
    public int Failed { get; init; }

    [JsonPropertyName("archive")]
    public string? Archive { get; init; }
}
