using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Net.Sockets;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace UniversalDownloader.Core;

public record InstalledBrowserInfo(string Name, string ExecutablePath);

/// <summary>
/// Manages an interactive, user-authenticated browser sign-in window using a dedicated,
/// isolated app-owned browser profile and official Chrome DevTools Protocol (Storage.getCookies).
/// Never touches or bypasses the user's personal browser profile or OS encryption.
/// </summary>
public sealed class BrowserLoginSession : IDisposable
{
    private Process? _browserProcess;
    private int _debugPort;
    private bool _disposed;

    public bool IsRunning => _browserProcess is { HasExited: false } && _debugPort > 0;
    public InstalledBrowserInfo? Browser { get; private set; }

    public static string GetAppLoginProfileDirectory()
    {
        var dir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "UniversalDownloader",
            "login_profile"
        );
        Directory.CreateDirectory(dir);
        return dir;
    }

    public static InstalledBrowserInfo? FindInstalledChromiumBrowser()
    {
        var candidates = new List<(string Name, string Path)>();

        if (OperatingSystem.IsWindows())
        {
            var pf = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
            var pf86 = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86);
            var localApp = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);

            candidates.Add(("Google Chrome", Path.Combine(pf, "Google", "Chrome", "Application", "chrome.exe")));
            candidates.Add(("Google Chrome", Path.Combine(pf86, "Google", "Chrome", "Application", "chrome.exe")));
            candidates.Add(("Google Chrome", Path.Combine(localApp, "Google", "Chrome", "Application", "chrome.exe")));
            candidates.Add(("Microsoft Edge", Path.Combine(pf86, "Microsoft", "Edge", "Application", "msedge.exe")));
            candidates.Add(("Microsoft Edge", Path.Combine(pf, "Microsoft", "Edge", "Application", "msedge.exe")));
            candidates.Add(("Brave", Path.Combine(pf, "BraveSoftware", "Brave-Browser", "Application", "brave.exe")));
            candidates.Add(("Brave", Path.Combine(localApp, "BraveSoftware", "Brave-Browser", "Application", "brave.exe")));
            candidates.Add(("Vivaldi", Path.Combine(localApp, "Vivaldi", "Application", "vivaldi.exe")));
        }
        else if (OperatingSystem.IsMacOS())
        {
            candidates.Add(("Google Chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"));
            candidates.Add(("Microsoft Edge", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"));
            candidates.Add(("Brave", "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"));
        }
        else
        {
            candidates.Add(("Google Chrome", "/usr/bin/google-chrome"));
            candidates.Add(("Chromium", "/usr/bin/chromium"));
            candidates.Add(("Chromium", "/usr/bin/chromium-browser"));
            candidates.Add(("Microsoft Edge", "/usr/bin/microsoft-edge"));
            candidates.Add(("Brave", "/usr/bin/brave-browser"));
        }

        foreach (var (name, path) in candidates)
        {
            if (!string.IsNullOrWhiteSpace(path) && File.Exists(path))
            {
                return new InstalledBrowserInfo(name, path);
            }
        }

        return null;
    }

    private static int FindFreeLocalPort()
    {
        using var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        return ((IPEndPoint)listener.LocalEndpoint).Port;
    }

    public static bool HasSavedLoginProfile()
    {
        var dir = GetAppLoginProfileDirectory();
        return File.Exists(Path.Combine(dir, "Default", "Network", "Cookies"))
            || File.Exists(Path.Combine(dir, "Default", "Cookies"))
            || File.Exists(Path.Combine(dir, "Local State"));
    }

    public async Task StartAsync(string loginUrl, bool headless = false, CancellationToken cancellationToken = default)
    {
        await CloseBrowserGracefullyAsync();

        var browser = FindInstalledChromiumBrowser()
            ?? throw new InvalidOperationException(
                "No Chromium-based browser (Google Chrome, Microsoft Edge, or Brave) was found on this system.");

        Browser = browser;
        _debugPort = FindFreeLocalPort();
        var profileDir = GetAppLoginProfileDirectory();

        var psi = new ProcessStartInfo
        {
            FileName = browser.ExecutablePath,
            UseShellExecute = false,
            CreateNoWindow = headless,
        };
        psi.ArgumentList.Add($"--user-data-dir={profileDir}");
        psi.ArgumentList.Add($"--remote-debugging-port={_debugPort}");
        psi.ArgumentList.Add("--no-first-run");
        psi.ArgumentList.Add("--no-default-browser-check");
        if (headless)
        {
            psi.ArgumentList.Add("--headless=new");
            psi.ArgumentList.Add("--disable-gpu");
        }
        else
        {
            psi.ArgumentList.Add("--window-size=1080,780");
        }
        psi.ArgumentList.Add(loginUrl);

        _browserProcess = Process.Start(psi)
            ?? throw new InvalidOperationException($"Failed to launch {browser.Name}.");

        // Wait until the local DevTools endpoint responds (up to 12 seconds)
        using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(2) };
        var versionUrl = $"http://127.0.0.1:{_debugPort}/json/version";
        var deadline = DateTime.UtcNow.AddSeconds(12);
        while (DateTime.UtcNow < deadline)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (_browserProcess.HasExited)
            {
                throw new InvalidOperationException(
                    $"{browser.Name} closed before the login session could connect. Close any previous Web Login window and try again.");
            }
            try
            {
                var resp = await http.GetAsync(versionUrl, cancellationToken);
                if (resp.IsSuccessStatusCode)
                {
                    return;
                }
            }
            catch
            {
                // Still starting up
            }
            await Task.Delay(250, cancellationToken);
        }

        throw new TimeoutException(
            $"Timed out waiting for {browser.Name} login window to initialize.");
    }

    /// <summary>
    /// Silently re-syncs fresh cookies from the already-signed-in persistent app login profile
    /// without prompting the user to sign in again.
    /// </summary>
    public async Task<int> QuickResyncSavedSessionAsync(
        string cookiesFilePath,
        string? targetDomainFilter = null,
        CancellationToken cancellationToken = default)
    {
        if (!HasSavedLoginProfile())
        {
            throw new InvalidOperationException(
                "No saved Web Login profile found yet. Click 'Open Browser & Sign In' once to sign in, and future syncs will be automatic.");
        }

        await StartAsync("about:blank", headless: true, cancellationToken: cancellationToken);
        try
        {
            return await SyncCookiesToFileAsync(cookiesFilePath, targetDomainFilter, closeAfterSync: true, cancellationToken: cancellationToken);
        }
        finally
        {
            await CloseBrowserGracefullyAsync();
        }
    }

    public async Task<int> SyncCookiesToFileAsync(
        string cookiesFilePath,
        string? targetDomainFilter = null,
        bool closeAfterSync = true,
        CancellationToken cancellationToken = default)
    {
        if (!IsRunning)
        {
            throw new InvalidOperationException("The Web Login browser window is not running. Click 'Open Browser & Sign In' first.");
        }

        using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(5) };
        var versionJson = await http.GetStringAsync($"http://127.0.0.1:{_debugPort}/json/version", cancellationToken);

        string? wsUrl = null;
        using (var vdoc = JsonDocument.Parse(versionJson))
        {
            if (vdoc.RootElement.TryGetProperty("webSocketDebuggerUrl", out var wsProp))
            {
                wsUrl = wsProp.GetString();
            }
        }

        if (string.IsNullOrWhiteSpace(wsUrl))
        {
            throw new InvalidOperationException("Could not obtain browser session endpoint.");
        }

        using var ws = new ClientWebSocket();
        await ws.ConnectAsync(new Uri(wsUrl), cancellationToken);

        // Request cookies using official Storage.getCookies (browser-level target supports it cleanly)
        var cdpResponse = await SendCdpCommandAsync(ws, 1, "Storage.getCookies", cancellationToken);
        var netscapeLines = ConvertCdpCookiesJsonToNetscapeLines(cdpResponse, targetDomainFilter);

        if (netscapeLines.Count == 0)
        {
            // Fallback to Network.getAllCookies if Storage.getCookies returned empty
            cdpResponse = await SendCdpCommandAsync(ws, 2, "Network.getAllCookies", cancellationToken);
            netscapeLines = ConvertCdpCookiesJsonToNetscapeLines(cdpResponse, targetDomainFilter);
        }

        if (netscapeLines.Count == 0)
        {
            try { await ws.CloseAsync(WebSocketCloseStatus.NormalClosure, "Done", CancellationToken.None); } catch { }
            var domainLabel = string.IsNullOrWhiteSpace(targetDomainFilter) ? "this site" : targetDomainFilter;
            throw new InvalidOperationException(
                $"No session cookies found for {domainLabel} yet. Complete signing in inside the browser window first, then click Sync & Apply Cookies.");
        }

        // Gracefully ask Chrome to exit via CDP Browser.close so it flushes all session cookies
        // cleanly to login_profile on disk (so the user never has to sign in again!).
        if (closeAfterSync)
        {
            try
            {
                var closeBytes = Encoding.UTF8.GetBytes("{\"id\":99,\"method\":\"Browser.close\"}");
                await ws.SendAsync(closeBytes, WebSocketMessageType.Text, true, CancellationToken.None);
            }
            catch { }
        }

        try
        {
            await ws.CloseAsync(WebSocketCloseStatus.NormalClosure, "Done", CancellationToken.None);
        }
        catch { }

        if (closeAfterSync)
        {
            await WaitForCleanExitAsync();
        }

        var joined = NetscapeCookieHelper.NetscapeHeader + Environment.NewLine + string.Join(Environment.NewLine, netscapeLines);
        return NetscapeCookieHelper.MergeIntoCookiesFile(cookiesFilePath, joined, targetDomainFilter ?? string.Empty);
    }

    private static async Task<string> SendCdpCommandAsync(
        ClientWebSocket ws,
        int id,
        string method,
        CancellationToken cancellationToken)
    {
        var payload = $"{{\"id\":{id},\"method\":\"{method}\"}}";
        var bytes = Encoding.UTF8.GetBytes(payload);
        await ws.SendAsync(bytes, WebSocketMessageType.Text, true, cancellationToken);

        var buffer = new byte[16384];
        while (true)
        {
            using var ms = new MemoryStream();
            WebSocketReceiveResult result;
            do
            {
                result = await ws.ReceiveAsync(buffer, cancellationToken);
                if (result.MessageType == WebSocketMessageType.Close)
                {
                    return string.Empty;
                }
                ms.Write(buffer, 0, result.Count);
            } while (!result.EndOfMessage);

            var text = Encoding.UTF8.GetString(ms.ToArray());
            using var doc = JsonDocument.Parse(text);
            if (doc.RootElement.TryGetProperty("id", out var idProp) && idProp.GetInt32() == id)
            {
                return text;
            }
        }
    }

    /// <summary>
    /// Converts a CDP Storage.getCookies / Network.getAllCookies JSON response into Netscape cookies.txt lines.
    /// Preserves #HttpOnly_ flags, domain scoping, secure flags, and expiration timestamps.
    /// </summary>
    public static List<string> ConvertCdpCookiesJsonToNetscapeLines(string cdpJson, string? domainFilter = null)
    {
        var lines = new List<string>();
        if (string.IsNullOrWhiteSpace(cdpJson)) return lines;

        var normalizedFilter = NormalizeDomainFilter(domainFilter);
        var defaultExpiry = DateTimeOffset.UtcNow.AddDays(365).ToUnixTimeSeconds();

        using var doc = JsonDocument.Parse(cdpJson);
        if (!doc.RootElement.TryGetProperty("result", out var resultElem)) return lines;
        if (!resultElem.TryGetProperty("cookies", out var cookiesElem) || cookiesElem.ValueKind != JsonValueKind.Array)
        {
            return lines;
        }

        foreach (var cookie in cookiesElem.EnumerateArray())
        {
            var domain = cookie.TryGetProperty("domain", out var dProp) ? dProp.GetString() ?? "" : "";
            var name = cookie.TryGetProperty("name", out var nProp) ? nProp.GetString() ?? "" : "";
            var value = cookie.TryGetProperty("value", out var vProp) ? vProp.GetString() ?? "" : "";
            var path = cookie.TryGetProperty("path", out var pProp) ? pProp.GetString() ?? "/" : "/";
            var secure = cookie.TryGetProperty("secure", out var sProp) && sProp.ValueKind == JsonValueKind.True;
            var httpOnly = cookie.TryGetProperty("httpOnly", out var hProp) && hProp.ValueKind == JsonValueKind.True;

            if (string.IsNullOrWhiteSpace(domain) || string.IsNullOrWhiteSpace(name)) continue;

            var cleanDomain = domain.Trim().TrimStart('.').ToLowerInvariant();
            if (!string.IsNullOrWhiteSpace(normalizedFilter))
            {
                if (!cleanDomain.Equals(normalizedFilter, StringComparison.OrdinalIgnoreCase) &&
                    !cleanDomain.EndsWith("." + normalizedFilter, StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }
            }

            long expires = defaultExpiry;
            if (cookie.TryGetProperty("expires", out var eProp) && eProp.ValueKind == JsonValueKind.Number)
            {
                var rawExp = eProp.GetDouble();
                if (rawExp > 0)
                {
                    expires = (long)Math.Floor(rawExp);
                }
            }

            var includeSubdomains = domain.StartsWith('.') ? "TRUE" : "FALSE";
            var secureStr = secure ? "TRUE" : "FALSE";
            var domainField = httpOnly ? $"#HttpOnly_{domain}" : domain;

            lines.Add($"{domainField}\t{includeSubdomains}\t{path}\t{secureStr}\t{expires}\t{name}\t{value}");
        }

        return lines;
    }

    private static string NormalizeDomainFilter(string? filter)
    {
        if (string.IsNullOrWhiteSpace(filter)) return string.Empty;
        var f = filter.Trim().ToLowerInvariant();
        if (f.Contains("://") && Uri.TryCreate(f, UriKind.Absolute, out var uri))
        {
            f = uri.Host.ToLowerInvariant();
        }
        f = f.Split('/')[0].Trim().TrimStart('.');
        if (f.StartsWith("www.")) f = f[4..];
        if (f.StartsWith("m.")) f = f[2..];
        return f;
    }

    private async Task WaitForCleanExitAsync()
    {
        if (_browserProcess == null) return;
        try
        {
            using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(5));
            try
            {
                if (!_browserProcess.HasExited)
                {
                    await _browserProcess.WaitForExitAsync(cts.Token);
                }
            }
            catch (OperationCanceledException)
            {
                if (!_browserProcess.HasExited)
                {
                    _browserProcess.CloseMainWindow();
                    _browserProcess.WaitForExit(1500);
                }
            }
        }
        catch { }
        finally
        {
            try { _browserProcess?.Dispose(); } catch { }
            _browserProcess = null;
            _debugPort = 0;
        }
    }

    public async Task CloseBrowserGracefullyAsync()
    {
        if (_browserProcess == null) return;

        if (!_browserProcess.HasExited && _debugPort > 0)
        {
            try
            {
                using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(2) };
                var versionJson = await http.GetStringAsync($"http://127.0.0.1:{_debugPort}/json/version");
                using var vdoc = JsonDocument.Parse(versionJson);
                if (vdoc.RootElement.TryGetProperty("webSocketDebuggerUrl", out var wsProp))
                {
                    var wsUrl = wsProp.GetString();
                    if (!string.IsNullOrWhiteSpace(wsUrl))
                    {
                        using var ws = new ClientWebSocket();
                        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(2));
                        await ws.ConnectAsync(new Uri(wsUrl), cts.Token);
                        var closeBytes = Encoding.UTF8.GetBytes("{\"id\":99,\"method\":\"Browser.close\"}");
                        await ws.SendAsync(closeBytes, WebSocketMessageType.Text, true, cts.Token);
                    }
                }
            }
            catch { }
        }

        await WaitForCleanExitAsync();
    }

    public void CloseBrowser()
    {
        if (_browserProcess != null)
        {
            try
            {
                if (!_browserProcess.HasExited)
                {
                    _browserProcess.CloseMainWindow();
                    if (!_browserProcess.WaitForExit(3500))
                    {
                        _browserProcess.Kill(entireProcessTree: true);
                    }
                }
            }
            catch { }
            finally
            {
                _browserProcess.Dispose();
                _browserProcess = null;
                _debugPort = 0;
            }
        }
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        CloseBrowser();
    }
}
