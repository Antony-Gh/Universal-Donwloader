using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;

namespace UniversalDownloader.Core;

/// <summary>
/// Converts raw HTTP Cookie headers (e.g. copied from browser DevTools) or Netscape cookies.txt text
/// into valid Netscape HTTP Cookie File format and merges them cleanly per domain.
/// </summary>
public static class NetscapeCookieHelper
{
    public const string NetscapeHeader = "# Netscape HTTP Cookie File";

    public static string GetDefaultManagedCookiesPath()
    {
        var dir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "UniversalDownloader"
        );
        Directory.CreateDirectory(dir);
        return Path.Combine(dir, "cookies.txt");
    }

    public static List<string> ParseToNetscapeLines(string rawInput, string domain)
    {
        var result = new List<string>();
        if (string.IsNullOrWhiteSpace(rawInput)) return result;

        var trimmed = rawInput.Trim();
        var lines = trimmed.Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries);

        // Detect existing Netscape tab-separated format
        bool looksNetscape = lines.Any(l =>
            !l.TrimStart().StartsWith('#') && l.Split('\t').Length >= 7);

        if (looksNetscape)
        {
            foreach (var rawLine in lines)
            {
                var line = rawLine.Trim();
                if (string.IsNullOrEmpty(line)) continue;
                if (line.StartsWith('#') && !line.StartsWith("#HttpOnly_", StringComparison.OrdinalIgnoreCase)) continue;
                var cols = line.Split('\t');
                if (cols.Length >= 7)
                {
                    result.Add(line);
                }
            }
            return result;
        }

        // Otherwise treat as HTTP Cookie header (optional leading "cookie:" / "Cookie:" prefix)
        var cleanedHeader = trimmed.Replace("\r", " ").Replace("\n", " ").Trim();
        if (cleanedHeader.StartsWith("cookie:", StringComparison.OrdinalIgnoreCase))
        {
            cleanedHeader = cleanedHeader["cookie:".Length..].Trim();
        }

        var normalizedDomain = NormalizeDomain(domain);
        if (string.IsNullOrWhiteSpace(normalizedDomain)) return result;

        var expiry = DateTimeOffset.UtcNow.AddDays(365).ToUnixTimeSeconds();
        var seenNames = new HashSet<string>(StringComparer.Ordinal);

        foreach (var pair in cleanedHeader.Split(';', StringSplitOptions.RemoveEmptyEntries))
        {
            var idx = pair.IndexOf('=');
            if (idx <= 0) continue;
            var name = pair[..idx].Trim();
            var value = pair[(idx + 1)..].Trim();
            if (string.IsNullOrWhiteSpace(name) || !seenNames.Add(name)) continue;

            // Netscape format: domain \t include_subdomains \t path \t secure \t expiration \t name \t value
            result.Add($"{normalizedDomain}\tTRUE\t/\tTRUE\t{expiry}\t{name}\t{value}");
        }

        return result;
    }

    public static int MergeIntoCookiesFile(string cookiesFilePath, string rawInput, string domain)
    {
        var newLines = ParseToNetscapeLines(rawInput, domain);
        if (newLines.Count == 0)
        {
            throw new InvalidOperationException(
                "No valid cookies were detected. Paste either a browser 'cookie:' header (name=value; ...) or Netscape cookies.txt lines."
            );
        }

        var replacedDomains = newLines
            .Select(l => l.Replace("#HttpOnly_", "", StringComparison.OrdinalIgnoreCase).Split('\t')[0].Trim().TrimStart('.').ToLowerInvariant())
            .Where(d => !string.IsNullOrWhiteSpace(d))
            .ToHashSet(StringComparer.OrdinalIgnoreCase);

        var preserved = new List<string>();
        if (File.Exists(cookiesFilePath))
        {
            foreach (var rawLine in File.ReadAllLines(cookiesFilePath))
            {
                var line = rawLine.Trim();
                if (string.IsNullOrEmpty(line)) continue;
                if (line.StartsWith('#') && !line.StartsWith("#HttpOnly_", StringComparison.OrdinalIgnoreCase)) continue;
                var cols = line.Replace("#HttpOnly_", "", StringComparison.OrdinalIgnoreCase).Split('\t');
                if (cols.Length < 7) continue;
                var existingDomain = cols[0].Trim().TrimStart('.').ToLowerInvariant();
                if (!replacedDomains.Contains(existingDomain))
                {
                    preserved.Add(line);
                }
            }
        }

        var parent = Path.GetDirectoryName(cookiesFilePath);
        if (!string.IsNullOrWhiteSpace(parent)) Directory.CreateDirectory(parent);

        var output = new List<string> { NetscapeHeader };
        output.AddRange(preserved);
        output.AddRange(newLines);
        File.WriteAllLines(cookiesFilePath, output);
        return newLines.Count;
    }

    private static string NormalizeDomain(string domain)
    {
        var d = (domain ?? string.Empty).Trim().ToLowerInvariant();
        if (d.Contains("://"))
        {
            if (Uri.TryCreate(d, UriKind.Absolute, out var uri)) d = uri.Host.ToLowerInvariant();
        }
        d = d.Split('/')[0].Trim();
        if (d.StartsWith("www.")) d = d[4..];
        if (d.StartsWith("m.")) d = d[2..];
        if (string.IsNullOrWhiteSpace(d)) return string.Empty;
        return d.StartsWith('.') ? d : "." + d;
    }
}
