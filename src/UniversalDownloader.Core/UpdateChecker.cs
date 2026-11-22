using System.Net;
using System.Net.Http;
using System.Net.Sockets;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text.Json;

namespace UniversalDownloader.Core;

public record AppUpdateInfo
{
    public string CurrentVersion { get; init; } = "4.2.0";
    public string LatestVersion { get; init; } = "4.2.0";
    public bool IsUpdateAvailable { get; init; }
    public string ReleaseTitle { get; init; } = string.Empty;
    public string ReleaseUrl { get; init; } = "https://github.com/Antony-Gh/Universal-Donwloader/releases/latest";
    public string DownloadUrl { get; init; } = "https://github.com/Antony-Gh/Universal-Donwloader/releases/latest";
    public string? AssetName { get; init; }
    public long AssetSizeBytes { get; init; }
    public string? ChecksumsAssetUrl { get; init; }
    public string ReleaseNotes { get; init; } = string.Empty;
}

public record VersionPolicyResult
{
    public bool IsSupported { get; init; } = true;
    public bool IsBlockedVersion { get; init; }
    public string MinSupportedVersion { get; init; } = "3.6.0";
    public string LatestVersion { get; init; } = "4.2.0";
    public string SunsetMessage { get; init; } = string.Empty;
    public string DownloadUrl { get; init; } = "https://github.com/Antony-Gh/Universal-Donwloader/releases/latest";
    public string EnforcementMode { get; init; } = "block";
}

/// <summary>
/// Cross-platform update checker querying GitHub Releases for Windows, Linux, and macOS builds.
/// Reads app version, version code, display name, and GitHub repo directly from app_config.json (embedded via Directory.Build.props).
/// </summary>
public static class UpdateChecker
{
    public static string RepoOwner => GetAssemblyMetadata("GitHubOwner") ?? "Antony-Gh";
    public static string RepoName => GetAssemblyMetadata("GitHubRepo") ?? "Universal-Donwloader";
    public static string AppDisplayName => GetAssemblyMetadata("AppDisplayName") ?? "Universal Media Downloader";
    public static int AppVersionCode => int.TryParse(GetAssemblyMetadata("AppVersionCode"), out var code) ? code : 420;
    public static bool ShowTelemetryInfo => bool.TryParse(GetAssemblyMetadata("ShowTelemetryInfo"), out var show) && show;
    public static string LatestReleaseApiUrl => $"https://api.github.com/repos/{RepoOwner}/{RepoName}/releases/latest";
    public static string LatestReleaseWebUrl => $"https://github.com/{RepoOwner}/{RepoName}/releases/latest";

    private static readonly HttpClient ApiHttp = new(CreateHttpHandler(allowAutoRedirect: true))
    {
        Timeout = TimeSpan.FromSeconds(25)
    };

    private static readonly HttpClient RedirectHttp = new(CreateHttpHandler(allowAutoRedirect: false))
    {
        Timeout = TimeSpan.FromSeconds(15)
    };

    private static readonly HttpClient DownloadHttp = new(CreateHttpHandler(allowAutoRedirect: true))
    {
        Timeout = TimeSpan.FromMinutes(15)
    };

    private static SocketsHttpHandler CreateHttpHandler(bool allowAutoRedirect)
    {
        return new SocketsHttpHandler
        {
            AllowAutoRedirect = allowAutoRedirect,
            AutomaticDecompression = DecompressionMethods.All,
            PooledConnectionLifetime = TimeSpan.FromMinutes(2),
            ConnectTimeout = TimeSpan.FromSeconds(10),
            ConnectCallback = async (context, ct) =>
            {
                // Prefer IPv4 addresses first to avoid Windows IPv6 blackhole stalls against GitHub endpoints
                var addresses = await Dns.GetHostAddressesAsync(context.DnsEndPoint.Host, ct);
                var ordered = addresses
                    .OrderBy(a => a.AddressFamily == AddressFamily.InterNetwork ? 0 : 1)
                    .ToArray();

                Exception? lastError = null;
                foreach (var addr in ordered)
                {
                    var socket = new Socket(addr.AddressFamily, SocketType.Stream, ProtocolType.Tcp)
                    {
                        NoDelay = true
                    };
                    try
                    {
                        using var perAttemptCts = CancellationTokenSource.CreateLinkedTokenSource(ct);
                        perAttemptCts.CancelAfter(TimeSpan.FromSeconds(8));
                        await socket.ConnectAsync(addr, context.DnsEndPoint.Port, perAttemptCts.Token);
                        return new NetworkStream(socket, ownsSocket: true);
                    }
                    catch (Exception ex) when (ex is not OperationCanceledException || !ct.IsCancellationRequested)
                    {
                        socket.Dispose();
                        lastError = ex;
                    }
                }

                throw lastError ?? new SocketException((int)SocketError.HostNotFound);
            }
        };
    }

    private static string? GetAssemblyMetadata(string key)
    {
        var asm = Assembly.GetEntryAssembly() ?? typeof(UpdateChecker).Assembly;
        return asm.GetCustomAttributes<AssemblyMetadataAttribute>()
            .FirstOrDefault(a => string.Equals(a.Key, key, StringComparison.OrdinalIgnoreCase))
            ?.Value
            ?? typeof(UpdateChecker).Assembly.GetCustomAttributes<AssemblyMetadataAttribute>()
                .FirstOrDefault(a => string.Equals(a.Key, key, StringComparison.OrdinalIgnoreCase))
                ?.Value;
    }

    public static string GetCurrentVersion()
    {
        var ver = Assembly.GetEntryAssembly()?.GetName().Version
            ?? typeof(UpdateChecker).Assembly.GetName().Version;
        if (ver == null) return "4.2.0";
        return $"{ver.Major}.{ver.Minor}.{Math.Max(0, ver.Build)}";
    }

    /// <summary>
    /// Fetches the public version_policy.json (the same file the CLI and Android app read)
    /// and evaluates it for the running version. Falls back to embedded defaults when offline.
    /// </summary>
    public static async Task<VersionPolicyResult> CheckVersionPolicyAsync(UserSettings? settings = null)
    {
        string? json = null;
        try
        {
            var rawUrl = Environment.GetEnvironmentVariable("UD_VERSION_POLICY_URL");
            if (string.IsNullOrWhiteSpace(rawUrl))
                rawUrl = $"https://raw.githubusercontent.com/{RepoOwner}/{RepoName}/master/version_policy.json";
            using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(5));
            var resp = await ApiHttp.GetAsync(rawUrl, cts.Token).ConfigureAwait(false);
            if (resp.IsSuccessStatusCode)
                json = await resp.Content.ReadAsStringAsync(cts.Token).ConfigureAwait(false);
        }
        catch { }

        return EvaluateVersionPolicy(GetCurrentVersion(), json);
    }

    /// <summary>
    /// Pure evaluation of a version_policy.json document. Same rules as the CLI and Android:
    /// a version is unsupported if it is listed in blocked_versions or is below min_supported_version.
    /// A null/invalid document uses the embedded defaults.
    /// </summary>
    public static VersionPolicyResult EvaluateVersionPolicy(string currentVersion, string? policyJson)
    {
        var minSupported = "3.6.0";
        var latestVersion = "3.6.0";
        var sunsetMsg = "This version of Universal Media Downloader has reached End of Life and is no longer supported. Please update to continue.";
        var downloadUrl = LatestReleaseWebUrl;
        var mode = "block";
        var blocked = new List<string>();

        if (!string.IsNullOrWhiteSpace(policyJson))
        {
            try
            {
                using var doc = JsonDocument.Parse(policyJson);
                var root = doc.RootElement;
                if (root.ValueKind == JsonValueKind.Object)
                {
                    minSupported = ReadString(root, "min_supported_version") ?? minSupported;
                    latestVersion = ReadString(root, "latest_version") ?? latestVersion;
                    sunsetMsg = ReadString(root, "sunset_message") ?? sunsetMsg;
                    downloadUrl = ReadString(root, "download_url") ?? downloadUrl;
                    mode = ReadString(root, "enforcement_mode") ?? mode;
                    if (root.TryGetProperty("blocked_versions", out var blockedProp) && blockedProp.ValueKind == JsonValueKind.Array)
                    {
                        foreach (var item in blockedProp.EnumerateArray())
                        {
                            if (item.ValueKind == JsonValueKind.String && !string.IsNullOrWhiteSpace(item.GetString()))
                                blocked.Add(NormalizeVersion(item.GetString()!));
                        }
                    }
                }
            }
            catch (JsonException) { }
        }

        mode = mode.Trim().ToLowerInvariant();
        var normalizedCurrent = NormalizeVersion(currentVersion);
        var isBlocked = blocked.Any(b => CompareVersions(b, normalizedCurrent) == 0);
        var belowMinimum = CompareVersions(normalizedCurrent, minSupported) < 0;

        return new VersionPolicyResult
        {
            // 'allow' switches the gate off remotely
            IsSupported = mode == "allow" || (!isBlocked && !belowMinimum),
            IsBlockedVersion = isBlocked,
            MinSupportedVersion = minSupported,
            LatestVersion = latestVersion,
            SunsetMessage = sunsetMsg,
            DownloadUrl = downloadUrl,
            EnforcementMode = mode
        };
    }

    private static string? ReadString(JsonElement root, string name)
    {
        return root.TryGetProperty(name, out var prop) && prop.ValueKind == JsonValueKind.String
            ? prop.GetString()
            : null;
    }

    public static async Task<AppUpdateInfo> CheckForUpdatesAsync(CancellationToken cancellationToken = default)
    {
        var currentVersionStr = GetCurrentVersion();
        Exception? apiError = null;

        // Primary: GitHub Releases REST API (with 1 automatic retry on transient timeout/network error)
        for (int attempt = 0; attempt < 2; attempt++)
        {
            try
            {
                return await CheckViaGitHubApiAsync(currentVersionStr, cancellationToken);
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                throw;
            }
            catch (Exception ex)
            {
                apiError = ex;
                if (attempt == 0)
                {
                    await Task.Delay(500, cancellationToken);
                }
            }
        }

        // Fallback: follow github.com/<owner>/<repo>/releases/latest redirect (fast, never API-rate-limited)
        try
        {
            var fallbackInfo = await TryCheckViaLatestRedirectAsync(currentVersionStr, cancellationToken);
            if (fallbackInfo != null)
            {
                return fallbackInfo;
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch
        {
            // Surface clean primary error below
        }

        if (apiError is TaskCanceledException || apiError is TimeoutException)
        {
            throw new TimeoutException(
                "Timed out connecting to GitHub Releases. Please check your internet connection and try again.",
                apiError);
        }

        throw apiError ?? new HttpRequestException("Unable to reach GitHub Releases.");
    }

    private static async Task<AppUpdateInfo> CheckViaGitHubApiAsync(
        string currentVersionStr,
        CancellationToken cancellationToken)
    {
        using var req = new HttpRequestMessage(HttpMethod.Get, LatestReleaseApiUrl);
        req.Headers.Add("User-Agent", $"UniversalDownloader/{currentVersionStr}");
        req.Headers.Add("Accept", "application/vnd.github+json");

        using var resp = await ApiHttp.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
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
        string? checksumsUrl = null;

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
                    if (aName.Equals("SHA256SUMS.txt", StringComparison.OrdinalIgnoreCase))
                    {
                        checksumsUrl = aUrl;
                    }
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
            ChecksumsAssetUrl = checksumsUrl,
            ReleaseNotes = releaseNotes,
        };
    }

    private static async Task<AppUpdateInfo?> TryCheckViaLatestRedirectAsync(
        string currentVersionStr,
        CancellationToken cancellationToken)
    {
        using var req = new HttpRequestMessage(HttpMethod.Head, LatestReleaseWebUrl);
        req.Headers.Add("User-Agent", $"UniversalDownloader/{currentVersionStr}");
        using var resp = await RedirectHttp.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, cancellationToken);

        var location = resp.Headers.Location?.ToString();
        if (string.IsNullOrWhiteSpace(location)) return null;

        var resolvedUrl = location.StartsWith("http", StringComparison.OrdinalIgnoreCase)
            ? location
            : $"https://github.com{location}";

        var latestVersionStr = ExtractVersionFromReleaseUrl(resolvedUrl);
        if (string.IsNullOrWhiteSpace(latestVersionStr)) return null;

        var tag = $"v{latestVersionStr}";
        string? assetName = null;
        string downloadUrl = resolvedUrl;
        if (PlatformUtils.IsWindows)
        {
            assetName = IsInstalledInProgramFiles()
                ? "UniversalDownloader-Setup-x64.msi"
                : "UniversalDownloader.exe";
            downloadUrl = $"https://github.com/{RepoOwner}/{RepoName}/releases/download/{tag}/{assetName}";
        }

        return new AppUpdateInfo
        {
            CurrentVersion = currentVersionStr,
            LatestVersion = latestVersionStr,
            IsUpdateAvailable = CompareVersions(latestVersionStr, currentVersionStr) > 0,
            ReleaseTitle = $"{AppDisplayName} {tag}",
            ReleaseUrl = resolvedUrl,
            DownloadUrl = downloadUrl,
            AssetName = assetName,
            ChecksumsAssetUrl = $"https://github.com/{RepoOwner}/{RepoName}/releases/download/{tag}/SHA256SUMS.txt",
        };
    }

    public static string ExtractVersionFromReleaseUrl(string releaseUrl)
    {
        if (string.IsNullOrWhiteSpace(releaseUrl)) return string.Empty;
        var marker = "/releases/tag/";
        var idx = releaseUrl.IndexOf(marker, StringComparison.OrdinalIgnoreCase);
        if (idx < 0) return string.Empty;
        var tag = releaseUrl[(idx + marker.Length)..].Split(['?', '#', '/'], StringSplitOptions.RemoveEmptyEntries).FirstOrDefault() ?? "";
        return NormalizeVersion(tag);
    }

    /// <summary>
    /// Download the update asset to a temporary staging folder and verify its SHA-256 against SHA256SUMS.txt if published.
    /// </summary>
    public static async Task<string> DownloadAndVerifyUpdateAsync(
        AppUpdateInfo info,
        IProgress<double>? progress = null,
        CancellationToken cancellationToken = default)
    {
        var stagingDir = Path.Combine(Path.GetTempPath(), "UniversalDownloader_Update");
        Directory.CreateDirectory(stagingDir);
        var fileName = !string.IsNullOrWhiteSpace(info.AssetName) ? info.AssetName : "UniversalDownloader-update";
        var destPath = Path.Combine(stagingDir, fileName);

        using var req = new HttpRequestMessage(HttpMethod.Get, info.DownloadUrl);
        req.Headers.Add("User-Agent", $"UniversalDownloader/{GetCurrentVersion()}");
        using var resp = await DownloadHttp.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
        resp.EnsureSuccessStatusCode();

        var totalBytes = resp.Content.Headers.ContentLength ?? info.AssetSizeBytes;
        await using (var remoteStream = await resp.Content.ReadAsStreamAsync(cancellationToken))
        await using (var localStream = File.Create(destPath))
        {
            var buffer = new byte[81920];
            long totalRead = 0;
            int read;
            while ((read = await remoteStream.ReadAsync(buffer, cancellationToken)) > 0)
            {
                await localStream.WriteAsync(buffer.AsMemory(0, read), cancellationToken);
                totalRead += read;
                if (totalBytes > 0)
                {
                    progress?.Report(Math.Clamp(totalRead * 100.0 / totalBytes, 0, 100));
                }
            }
        }

        // Verify SHA-256 checksum if SHA256SUMS.txt was published alongside the release
        if (!string.IsNullOrWhiteSpace(info.ChecksumsAssetUrl) && !string.IsNullOrWhiteSpace(info.AssetName))
        {
            using var sumReq = new HttpRequestMessage(HttpMethod.Get, info.ChecksumsAssetUrl);
            sumReq.Headers.Add("User-Agent", $"UniversalDownloader/{GetCurrentVersion()}");
            using var sumResp = await ApiHttp.SendAsync(sumReq, cancellationToken);
            if (sumResp.IsSuccessStatusCode)
            {
                var sumsText = await sumResp.Content.ReadAsStringAsync(cancellationToken);
                var expectedHash = sumsText
                    .Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries)
                    .Select(line => line.Trim().Split([' ', '\t'], StringSplitOptions.RemoveEmptyEntries))
                    .Where(parts => parts.Length >= 2 && parts[^1].TrimStart('*').Equals(info.AssetName, StringComparison.OrdinalIgnoreCase))
                    .Select(parts => parts[0])
                    .FirstOrDefault();

                if (!string.IsNullOrWhiteSpace(expectedHash))
                {
                    await using var verifyStream = File.OpenRead(destPath);
                    var actualHash = Convert.ToHexString(await System.Security.Cryptography.SHA256.HashDataAsync(verifyStream, cancellationToken));
                    if (!actualHash.Equals(expectedHash, StringComparison.OrdinalIgnoreCase))
                    {
                        File.Delete(destPath);
                        throw new InvalidOperationException($"SHA-256 verification failed for {info.AssetName}.");
                    }
                }
            }
        }

        progress?.Report(100);
        return destPath;
    }

    /// <summary>
    /// Detects whether the current Windows executable is running from a protected Program Files installation (e.g. MSI setup).
    /// </summary>
    public static bool IsInstalledInProgramFiles(string? processPath = null)
    {
        if (!PlatformUtils.IsWindows) return false;
        var path = processPath ?? Environment.ProcessPath;
        if (string.IsNullOrWhiteSpace(path)) return false;

        var programFiles = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
        var programFilesX86 = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86);

        return (!string.IsNullOrWhiteSpace(programFiles) && path.StartsWith(programFiles, StringComparison.OrdinalIgnoreCase)) ||
               (!string.IsNullOrWhiteSpace(programFilesX86) && path.StartsWith(programFilesX86, StringComparison.OrdinalIgnoreCase));
    }

    /// <summary>
    /// On Windows, launches the MSI installer (if an .msi was downloaded) or swaps the running portable .exe and relaunches.
    /// </summary>
    public static bool TryLaunchWindowsSelfReplace(string downloadedPath)
    {
        if (!PlatformUtils.IsWindows || string.IsNullOrWhiteSpace(downloadedPath))
            return false;

        // MSI installation upgrade path (handles UAC elevation and Program Files upgrade cleanly)
        if (downloadedPath.EndsWith(".msi", StringComparison.OrdinalIgnoreCase))
        {
            System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo
            {
                FileName = "msiexec.exe",
                Arguments = $"/i \"{downloadedPath}\"",
                UseShellExecute = true,
            });
            return true;
        }

        if (!downloadedPath.EndsWith(".exe", StringComparison.OrdinalIgnoreCase))
            return false;

        var currentExe = Environment.ProcessPath;
        if (string.IsNullOrWhiteSpace(currentExe) || !currentExe.EndsWith(".exe", StringComparison.OrdinalIgnoreCase))
            return false;
        if (Path.GetFileName(currentExe).Equals("dotnet.exe", StringComparison.OrdinalIgnoreCase))
            return false;

        var pid = Environment.ProcessId;
        var scriptPath = Path.Combine(Path.GetTempPath(), $"ud_updater_{pid}.cmd");
        var script = $"""
@echo off
:wait
tasklist /FI "PID eq {pid}" 2>NUL | find /I "{pid}" >NUL
if "%ERRORLEVEL%"=="0" (
    timeout /t 1 /nobreak >NUL
    goto wait
)
move /Y "{downloadedPath}" "{currentExe}" >NUL
start "" "{currentExe}"
del "%~f0"
""";
        File.WriteAllText(scriptPath, script);
        System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo
        {
            FileName = "cmd.exe",
            Arguments = $"/C \"{scriptPath}\"",
            CreateNoWindow = true,
            UseShellExecute = false,
        });
        return true;
    }

    private static (string Name, string Url, long Size)? PickPlatformAsset(
        List<(string Name, string Url, long Size)> assets)
    {
        if (assets.Count == 0) return null;

        if (PlatformUtils.IsWindows)
        {
            if (IsInstalledInProgramFiles())
            {
                var msi = assets.FirstOrDefault(a => a.Name.EndsWith(".msi", StringComparison.OrdinalIgnoreCase));
                if (!string.IsNullOrEmpty(msi.Name)) return msi;
            }

            var exe = assets.FirstOrDefault(a => a.Name.Equals("UniversalDownloader.exe", StringComparison.OrdinalIgnoreCase));
            if (!string.IsNullOrEmpty(exe.Name)) return exe;

            var anyMsi = assets.FirstOrDefault(a => a.Name.EndsWith(".msi", StringComparison.OrdinalIgnoreCase));
            if (!string.IsNullOrEmpty(anyMsi.Name)) return anyMsi;

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
