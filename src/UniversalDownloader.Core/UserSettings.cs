using System.Text.Json;

namespace UniversalDownloader.Core;

/// <summary>
/// Persistent desktop user preferences stored in LocalApplicationData/UniversalDownloader/settings.json.
/// </summary>
public class UserSettings
{
    public int QualityIndex { get; set; } = 0;
    public int CodecIndex { get; set; } = 0;
    public int ConcurrentFragments { get; set; } = 4;
    public string OutputDirectory { get; set; } = string.Empty;
    public bool EmbedMetadata { get; set; } = true;
    public bool EmbedThumbnail { get; set; } = true;
    public bool EmbedSubs { get; set; } = false;
    public bool WriteThumbnail { get; set; } = false;
    public int CookiesBrowserIndex { get; set; } = 0;
    public string CookiesFilePath { get; set; } = string.Empty;
    public bool SponsorBlockEnabled { get; set; } = false;
    public bool TelemetryEnabled { get; set; } = true;
    public bool ShowTelemetryInfo { get; set; } = false;
    public string? TelemetryUrl { get; set; } = null;
    public string? TelemetryKey { get; set; } = null;
    public string? FriendTag { get; set; } = null;
    public string Language { get; set; } = "en";
    public bool MinimizeToTray { get; set; } = true;
    public bool WatchClipboard { get; set; } = true;
    public string ThemePreset { get; set; } = "default";
    public int SpeedLimitIndex { get; set; } = 0;
    public bool UseAria2 { get; set; } = false;

    public static string SettingsFilePath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "UniversalDownloader",
        "settings.json"
    );

    public static UserSettings Load(string? customPath = null)
    {
        var path = customPath ?? SettingsFilePath;
        try
        {
            if (File.Exists(path))
            {
                var json = File.ReadAllText(path);
                var loaded = JsonSerializer.Deserialize(json, DownloaderJsonContext.Default.UserSettings);
                if (loaded != null)
                {
                    loaded.ConcurrentFragments = Math.Clamp(loaded.ConcurrentFragments, 1, 16);
                    return loaded;
                }
            }
        }
        catch
        {
            // Fall back to defaults on corrupt or inaccessible config
        }
        return new UserSettings();
    }

    public void Save(string? customPath = null)
    {
        var path = customPath ?? SettingsFilePath;
        try
        {
            var dir = Path.GetDirectoryName(path);
            if (!string.IsNullOrWhiteSpace(dir))
            {
                Directory.CreateDirectory(dir);
            }
            var json = JsonSerializer.Serialize(this, DownloaderJsonContext.Default.UserSettings);
            File.WriteAllText(path, json);
        }
        catch
        {
            // Best-effort persistence
        }
    }
}
