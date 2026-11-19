using System.Diagnostics;
using System.Runtime.InteropServices;

namespace UniversalDownloader.Core;

/// <summary>
/// Cross-platform operating system utilities for process launching, shell openers, and binary location.
/// Works uniformly across Windows, Linux, and macOS.
/// </summary>
public static class PlatformUtils
{
    public static bool IsWindows => RuntimeInformation.IsOSPlatform(OSPlatform.Windows);
    public static bool IsLinux => RuntimeInformation.IsOSPlatform(OSPlatform.Linux);
    public static bool IsMacOS => RuntimeInformation.IsOSPlatform(OSPlatform.OSX);

    /// <summary>
    /// Open a file in the default system viewer/player.
    /// </summary>
    public static bool OpenFile(string filePath)
    {
        if (string.IsNullOrWhiteSpace(filePath) || !File.Exists(filePath))
            return false;

        try
        {
            if (IsWindows)
            {
                Process.Start(new ProcessStartInfo(filePath) { UseShellExecute = true });
                return true;
            }

            if (IsMacOS)
            {
                Process.Start("open", $"\"{filePath}\"");
                return true;
            }

            if (IsLinux)
            {
                Process.Start("xdg-open", $"\"{filePath}\"");
                return true;
            }
        }
        catch
        {
            // Fallback
        }

        return false;
    }

    /// <summary>
    /// Open the parent folder of a file, highlighting or selecting the file when supported.
    /// </summary>
    public static bool OpenFolder(string path)
    {
        if (string.IsNullOrWhiteSpace(path)) return false;

        try
        {
            if (IsWindows)
            {
                if (File.Exists(path))
                {
                    Process.Start("explorer.exe", $"/select,\"{path}\"");
                    return true;
                }

                if (Directory.Exists(path))
                {
                    Process.Start("explorer.exe", $"\"{path}\"");
                    return true;
                }
            }

            var targetFolder = File.Exists(path) ? Path.GetDirectoryName(path) : path;
            if (string.IsNullOrWhiteSpace(targetFolder) || !Directory.Exists(targetFolder))
                return false;

            if (IsMacOS)
            {
                if (File.Exists(path))
                {
                    Process.Start("open", $"-R \"{path}\"");
                }
                else
                {
                    Process.Start("open", $"\"{targetFolder}\"");
                }
                return true;
            }

            if (IsLinux)
            {
                Process.Start("xdg-open", $"\"{targetFolder}\"");
                return true;
            }
        }
        catch
        {
            // Fallback
        }

        return false;
    }

    /// <summary>
    /// Locate the appropriate python binary for the current operating system.
    /// </summary>
    public static string ResolvePythonExecutable()
    {
        if (IsWindows)
        {
            // Check PATH for python or py
            return "python";
        }

        // On Linux / macOS, python3 is standard; fallback to python
        return "python3";
    }

    /// <summary>
    /// Locate a binary filename with appropriate OS extension.
    /// </summary>
    public static string GetBinaryName(string baseName)
    {
        return IsWindows ? $"{baseName}.exe" : baseName;
    }

    /// <summary>
    /// Format raw bytes into human-readable representation (e.g. 15.4 MB, 1.2 GB).
    /// </summary>
    public static string FormatBytes(long bytes)
    {
        if (bytes <= 0) return "0 B";
        string[] units = { "B", "KB", "MB", "GB", "TB" };
        int digitGroups = (int)(Math.Log10(bytes) / Math.Log10(1024));
        digitGroups = Math.Clamp(digitGroups, 0, units.Length - 1);
        return $"{bytes / Math.Pow(1024, digitGroups):F1} {units[digitGroups]}";
    }

    /// <summary>
    /// Open an HTTP/HTTPS URL in the default system browser across Windows, macOS, and Linux.
    /// </summary>
    public static bool OpenUrl(string url)
    {
        if (string.IsNullOrWhiteSpace(url)) return false;
        try
        {
            if (IsWindows)
            {
                Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
                return true;
            }
            if (IsMacOS)
            {
                Process.Start("open", $"\"{url}\"");
                return true;
            }
            if (IsLinux)
            {
                Process.Start("xdg-open", $"\"{url}\"");
                return true;
            }
        }
        catch { }
        return false;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct SYSTEM_POWER_STATUS
    {
        public byte ACLineStatus;
        public byte BatteryFlag;
        public byte BatteryLifePercent;
        public byte SystemStatusFlag;
        public uint BatteryLifeTime;
        public uint BatteryFullLifeTime;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetSystemPowerStatus(out SYSTEM_POWER_STATUS sps);

    /// <summary>
    /// Detect whether the current host is a Desktop PC, Laptop, macOS, or Linux device.
    /// </summary>
    public static string DetectDeviceType()
    {
        if (IsWindows)
        {
            try
            {
                if (GetSystemPowerStatus(out var sps))
                {
                    // 128 = No system battery, 255 = Unknown
                    if (sps.BatteryFlag == 128 || (sps.BatteryFlag == 255 && sps.BatteryLifePercent == 255))
                    {
                        return "Desktop PC";
                    }
                    else if (sps.BatteryLifePercent <= 100 || (sps.BatteryFlag & 128) == 0)
                    {
                        return "Laptop";
                    }
                }
            }
            catch { }
            return "Desktop PC";
        }

        if (IsLinux)
        {
            try
            {
                var powerDir = "/sys/class/power_supply";
                if (Directory.Exists(powerDir))
                {
                    foreach (var dir in Directory.GetDirectories(powerDir))
                    {
                        var name = Path.GetFileName(dir).ToLowerInvariant();
                        if (name.StartsWith("bat")) return "Laptop";
                        var typeFile = Path.Combine(dir, "type");
                        if (File.Exists(typeFile) && File.ReadAllText(typeFile).Trim().Equals("Battery", StringComparison.OrdinalIgnoreCase))
                        {
                            return "Laptop";
                        }
                    }
                }
            }
            catch { }
            return "Linux Desktop";
        }

        if (IsMacOS)
        {
            try
            {
                var psi = new ProcessStartInfo("pmset", "-g batt")
                {
                    RedirectStandardOutput = true,
                    UseShellExecute = false,
                    CreateNoWindow = true
                };
                using var p = Process.Start(psi);
                if (p != null)
                {
                    var output = p.StandardOutput.ReadToEnd();
                    p.WaitForExit(1000);
                    if (output.Contains("Battery", StringComparison.OrdinalIgnoreCase) ||
                        output.Contains("InternalBattery", StringComparison.OrdinalIgnoreCase))
                    {
                        return "Laptop";
                    }
                }
            }
            catch { }
            return "macOS";
        }

        return "Desktop PC";
    }

    /// <summary>
    /// Returns or creates a persistent anonymous UUIDv4 for this installation.
    /// Stored in LocalApplicationData/UniversalDownloader/device_id.json.
    /// </summary>
    public static string GetOrCreateInstallId()
    {
        try
        {
            var dir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "UniversalDownloader"
            );
            Directory.CreateDirectory(dir);
            var file = Path.Combine(dir, "device_id.json");
            if (File.Exists(file))
            {
                var text = File.ReadAllText(file);
                using var doc = System.Text.Json.JsonDocument.Parse(text);
                if (doc.RootElement.TryGetProperty("install_id", out var prop))
                {
                    var id = prop.GetString();
                    if (!string.IsNullOrWhiteSpace(id) && Guid.TryParse(id, out _))
                    {
                        return id;
                    }
                }
            }

            var newId = Guid.NewGuid().ToString();
            File.WriteAllText(file, $"{{\"install_id\":\"{newId}\"}}");
            return newId;
        }
        catch
        {
            return Guid.NewGuid().ToString();
        }
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Auto)]
    private class MEMORYSTATUSEX
    {
        public uint dwLength;
        public uint dwMemoryLoad;
        public ulong ullTotalPhys;
        public ulong ullAvailPhys;
        public ulong ullTotalPageFile;
        public ulong ullAvailPageFile;
        public ulong ullTotalVirtual;
        public ulong ullAvailVirtual;
        public ulong ullAvailExtendedVirtual;

        public MEMORYSTATUSEX()
        {
            dwLength = (uint)Marshal.SizeOf(typeof(MEMORYSTATUSEX));
        }
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Auto, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GlobalMemoryStatusEx([In, Out] MEMORYSTATUSEX lpBuffer);

    [DllImport("user32.dll")]
    private static extern int GetSystemMetrics(int nIndex);

    public static double DetectTotalRamGb()
    {
        try
        {
            if (IsWindows)
            {
                var stat = new MEMORYSTATUSEX();
                if (GlobalMemoryStatusEx(stat))
                {
                    return Math.Round(stat.ullTotalPhys / (1024.0 * 1024 * 1024), 1);
                }
            }
            else if (IsLinux && File.Exists("/proc/meminfo"))
            {
                foreach (var line in File.ReadLines("/proc/meminfo"))
                {
                    if (line.StartsWith("MemTotal:"))
                    {
                        var parts = line.Split(' ', StringSplitOptions.RemoveEmptyEntries);
                        if (parts.Length >= 2 && double.TryParse(parts[1], out var kb))
                        {
                            return Math.Round(kb / (1024.0 * 1024), 1);
                        }
                    }
                }
            }
        }
        catch { }
        return 0;
    }

    public static string DetectScreenResolution()
    {
        try
        {
            if (IsWindows)
            {
                var w = GetSystemMetrics(0);
                var h = GetSystemMetrics(1);
                if (w > 0 && h > 0) return $"{w}x{h}";
            }
        }
        catch { }
        return "Unknown";
    }

    /// <summary>
    /// Identify which friend/contributor downloaded the tool from settings, env, or binary filename.
    /// </summary>
    public static string? DetectFriendTag(UserSettings? settings = null)
    {
        try
        {
            if (!string.IsNullOrWhiteSpace(settings?.FriendTag))
                return settings.FriendTag.Trim().ToLowerInvariant();

            var envTag = Environment.GetEnvironmentVariable("UD_FRIEND_TAG") 
                ?? Environment.GetEnvironmentVariable("UD_REF");
            if (!string.IsNullOrWhiteSpace(envTag))
                return envTag.Trim().ToLowerInvariant();

            var processPath = Environment.ProcessPath;
            if (!string.IsNullOrWhiteSpace(processPath))
            {
                var stem = Path.GetFileNameWithoutExtension(processPath);
                var match = System.Text.RegularExpressions.Regex.Match(
                    stem,
                    @"(?:universal[_-]?downloader|downloader)[_-]([a-zA-Z0-9_\-]+)$",
                    System.Text.RegularExpressions.RegexOptions.IgnoreCase
                );
                if (match.Success)
                {
                    return match.Groups[1].Value.Trim().ToLowerInvariant();
                }
            }
        }
        catch { }
        return null;
    }

    /// <summary>
    /// Sends an anonymous heartbeat to Neon Serverless Postgres via SQL-over-HTTPS.
    /// Safe, non-blocking, zero personal data.
    /// </summary>
    public static async Task<bool> SendTelemetryHeartbeatAsync(UserSettings? settings = null)
    {
        try
        {
            if (Environment.GetEnvironmentVariable("UD_NO_TELEMETRY") is "1" or "true")
                return false;

            if (settings != null && !settings.TelemetryEnabled)
                return false;

            var url = settings?.TelemetryUrl 
                ?? Environment.GetEnvironmentVariable("NEON_DATABASE_URL")
                ?? Environment.GetEnvironmentVariable("UD_TELEMETRY_URL");

            if (string.IsNullOrWhiteSpace(url)) return false;

            var key = settings?.TelemetryKey 
                ?? Environment.GetEnvironmentVariable("NEON_TELEMETRY_KEY");

            var installId = GetOrCreateInstallId();
            var deviceType = DetectDeviceType();
            var osName = RuntimeInformation.OSDescription;
            var deviceModel = "PC";
            var appVersion = UpdateChecker.GetCurrentVersion();
            var locale = System.Globalization.CultureInfo.CurrentCulture.Name;
            var timezone = TimeZoneInfo.Local.StandardName;
            var cpuCores = Environment.ProcessorCount;
            var cpuArch = RuntimeInformation.ProcessArchitecture.ToString();
            var ramGb = DetectTotalRamGb();
            var screenRes = DetectScreenResolution();
            var connType = System.Net.NetworkInformation.NetworkInterface.GetIsNetworkAvailable() ? "Connected" : "Offline";
            var friendTag = DetectFriendTag(settings);

            var escId = installId.Replace("'", "''");
            var escType = deviceType.Replace("'", "''");
            var escOs = osName.Replace("'", "''");
            var escModel = deviceModel.Replace("'", "''");
            var escVer = appVersion.Replace("'", "''");
            var escLocale = locale.Replace("'", "''");
            var escTz = timezone.Replace("'", "''");
            var escArch = cpuArch.Replace("'", "''");
            var escScreen = screenRes.Replace("'", "''");
            var escConn = connType.Replace("'", "''");
            var escRam = ramGb > 0 ? ramGb.ToString("F1", System.Globalization.CultureInfo.InvariantCulture) : "NULL";
            var escFriend = !string.IsNullOrWhiteSpace(friendTag) ? $"'{friendTag.Replace("'", "''")}'" : "NULL";

            var sql = $"SELECT record_device_heartbeat('{escId}'::UUID, '{escType}', '{escOs}', '{escModel}', '{escVer}', '{escLocale}', '{escTz}', {cpuCores}, '{escArch}', {escRam}, '{escScreen}', '{escConn}', {escFriend});";
            var jsonPayload = $"{{\"query\":\"{sql}\"}}";

            using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(5) };
            using var req = new HttpRequestMessage(HttpMethod.Post, url);
            req.Content = new StringContent(jsonPayload, System.Text.Encoding.UTF8, "application/json");
            if (!string.IsNullOrWhiteSpace(key))
            {
                req.Headers.TryAddWithoutValidation("Authorization", $"Bearer {key}");
            }
            req.Headers.TryAddWithoutValidation("User-Agent", $"UniversalDownloader/{appVersion}");

            var resp = await client.SendAsync(req).ConfigureAwait(false);
            return resp.IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }
}
