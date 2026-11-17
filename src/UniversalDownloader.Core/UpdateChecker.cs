using System.Net.Http;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text.Json;

namespace UniversalDownloader.Core;

public record AppUpdateInfo
{
    public string CurrentVersion { get; init; } = "1.5.0";
    public string LatestVersion { get; init; } = "1.5.0";
    public bool IsUpdateAvailable { get; init; }
    public string ReleaseTitle { get; init; } = string.Empty;
    public string ReleaseUrl { get; init; } = "https://github.com/Antony-Gh/Universal-Donwloader/releases/latest";
    public string DownloadUrl { get; init; } = "https://github.com/Antony-Gh/Universal-Donwloader/releases/latest";
    public string? AssetName { get; init; }
    public long AssetSizeBytes { get; init; }
    public string ReleaseNotes { get; init; } = string.Empty;
}

/// <summary>
/// Cross-platform update checker querying GitHub Releases for Windows, Linux, and macOS builds.
/// </summary>
public static class UpdateChecker
{
    public const string RepoOwner = "Antony-Gh";
    public const string RepoName = "Universal-Donwloader";
    public const string LatestReleaseApiUrl = $"https://api.github.com/repos/{RepoOwner}/{RepoName}/releases/latest";
    public const string LatestReleaseWebUrl = $"https://github.com/{RepoOwner}/{RepoName}/releases/latest";

    private static readonly HttpClient Http = new() { Timeout = TimeSpan.FromSeconds(12) };

    public static string GetCurrentVersion()
    {
        var ver = Assembly.GetEntryAssembly()?.GetName().Version
            ?? typeof(UpdateChecker).Assembly.GetName().Version;
        if (ver == null) return "1.5.0";
        return $"{ver.Major}.{ver.Minor}.{Math.Max(0, ver.Build)}";
    }

    public static async Task<AppUpdateInfo> CheckForUpdatesAsync(CancellationToken cancellationToken = default)
    {
        var currentVersionStr = GetCurrentVersion();

        using var req = new HttpRequestMessage(HttpMethod.Get, LatestReleaseApiUrl);
        req.Headers.Add("User-Agent", $"UniversalDownloader/{currentVersionStr}");
        req.Headers.Add("Accept", "application/vnd.github+json");

        using var resp = await Http.SendAsync(req, cancellationToken);
        resp.EnsureSuccessStatusCode();

        var json = await resp.Content.ReadAsStringAsync(cancellationToken);
        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;

        var tagName = root.TryGetProperty("tag_name", out var tagEl) ? tagEl.GetString() ?? "" : "";
        var latestVersionStr = NormalizeVersion(tagName);
        var releaseUrl = root.TryGetProperty("html_url", out var urlEl) ? urlEl.GetString() ?? LatestReleaseWebUrl : LatestReleaseWebUrl;
        var releaseTitle = root.TryGetProperty("name", out var nameEl) ? nameEl.GetString() ?? tagName : tagName;
        var releaseNotes = root.TryGetProperty("body", out var bodyEl) ? bodyEl.GetString() ?? "" : "";

        string downloadUrl = releaseUrl;
        string? matchedAssetName = null;
        long matchedAssetSize = 0;

        if (root.TryGetProperty("assets", out var assetsEl) && assetsEl.ValueKind == JsonValueKind.Array)
        {
            var assets = new List<(string Name, string Url, long Size)>();
            foreach (var item in assetsEl.EnumerateArray())
            {
                var aName = item.TryGetProperty("name", out var n) ? n.GetString() ?? "" : "";
                var aUrl = item.TryGetProperty("browser_download_url", out var u) ? u.GetString() ?? "" : "";
                var aSize = item.TryGetProperty("size", out var s) && s.TryGetInt64(out var sz) ? sz : 0L;
                if (!string.IsNullOrWhiteSpace(aName) && !string.IsNullOrWhiteSpace(aUrl))
                {
                    assets.Add((aName, aUrl, aSize));
                }
            }

            var best = PickPlatformAsset(assets);
            if (best.HasValue)
            {
                matchedAssetName = best.Value.Name;
                downloadUrl = best.Value.Url;
                matchedAssetSize = best.Value.Size;
            }
        }

        var isNewer = CompareVersions(latestVersionStr, currentVersionStr) > 0;

        return new AppUpdateInfo
        {
            CurrentVersion = currentVersionStr,
            LatestVersion = string.IsNullOrEmpty(latestVersionStr) ? currentVersionStr : latestVersionStr,
            IsUpdateAvailable = isNewer,
            ReleaseTitle = releaseTitle,
            ReleaseUrl = releaseUrl,
            DownloadUrl = downloadUrl,
            AssetName = matchedAssetName,
            AssetSizeBytes = matchedAssetSize,
            ReleaseNotes = releaseNotes,
        };
    }

    private static (string Name, string Url, long Size)? PickPlatformAsset(
        List<(string Name, string Url, long Size)> assets)
    {
        if (assets.Count == 0) return null;

        if (PlatformUtils.IsWindows)
        {
            var exe = assets.FirstOrDefault(a => a.Name.Equals("UniversalDownloader.exe", StringComparison.OrdinalIgnoreCase));
            if (!string.IsNullOrEmpty(exe.Name)) return exe;

            var anyExe = assets.FirstOrDefault(a => a.Name.EndsWith(".exe", StringComparison.OrdinalIgnoreCase));
            if (!string.IsNullOrEmpty(anyExe.Name)) return anyExe;

            var winZip = assets.FirstOrDefault(a => a.Name.Contains("windows", StringComparison.OrdinalIgnoreCase) && a.Name.EndsWith(".zip", StringComparison.OrdinalIgnoreCase));
            if (!string.IsNullOrEmpty(winZip.Name)) return winZip;
        }
        else if (PlatformUtils.IsMacOS)
        {
            bool isArm = RuntimeInformation.OSArchitecture == Architecture.Arm64;
            var archToken = isArm ? "arm64" : "x64";

            var exactMac = assets.FirstOrDefault(a =>
                a.Name.Contains("macos", StringComparison.OrdinalIgnoreCase) &&
                a.Name.Contains(archToken, StringComparison.OrdinalIgnoreCase));
            if (!string.IsNullOrEmpty(exactMac.Name)) return exactMac;

            var anyMac = assets.FirstOrDefault(a => a.Name.Contains("macos", StringComparison.OrdinalIgnoreCase));
            if (!string.IsNullOrEmpty(anyMac.Name)) return anyMac;
        }
        else if (PlatformUtils.IsLinux)
        {
            var linuxTar = assets.FirstOrDefault(a =>
                a.Name.Contains("linux", StringComparison.OrdinalIgnoreCase) &&
                a.Name.EndsWith(".tar.gz", StringComparison.OrdinalIgnoreCase));
            if (!string.IsNullOrEmpty(linuxTar.Name)) return linuxTar;

            var anyLinux = assets.FirstOrDefault(a => a.Name.Contains("linux", StringComparison.OrdinalIgnoreCase));
            if (!string.IsNullOrEmpty(anyLinux.Name)) return anyLinux;
        }

        return null;
    }

    public static string NormalizeVersion(string raw)
    {
        var cleaned = raw.Trim().TrimStart('v', 'V');
        var dashIdx = cleaned.IndexOf('-');
        if (dashIdx > 0) cleaned = cleaned[..dashIdx];
        return cleaned;
    }

    public static int CompareVersions(string a, string b)
    {
        var partsA = ParseVersionParts(a);
        var partsB = ParseVersionParts(b);
        var maxLen = Math.Max(partsA.Length, partsB.Length);
        for (int i = 0; i < maxLen; i++)
        {
            int va = i < partsA.Length ? partsA[i] : 0;
            int vb = i < partsB.Length ? partsB[i] : 0;
            if (va != vb) return va.CompareTo(vb);
        }
        return 0;
    }

    private static int[] ParseVersionParts(string version)
    {
        return NormalizeVersion(version)
            .Split('.', StringSplitOptions.RemoveEmptyEntries)
            .Select(p => int.TryParse(p, out var n) ? n : 0)
            .ToArray();
    }
}
