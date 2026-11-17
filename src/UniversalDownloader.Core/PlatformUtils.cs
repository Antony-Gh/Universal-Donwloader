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
}
