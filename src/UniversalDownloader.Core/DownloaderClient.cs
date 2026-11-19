using System.Diagnostics;
using System.Text.Json;
using UniversalDownloader.Core.Models;

namespace UniversalDownloader.Core;

/// <summary>
/// High-speed asynchronous IPC client communicating with the Universal Downloader backend.
/// Supports both compiled standalone binary (downloader.exe) and Python script mode (downloader.py).
/// </summary>
public class DownloaderClient
{
    private readonly string _executableOrPython;
    private readonly string? _scriptPath;
    private Process? _currentProcess;
    private readonly object _lock = new();

    public event EventHandler<DownloadProgressEvent>? ProgressChanged;
    public event EventHandler<DownloadCompleteEvent>? DownloadCompleted;
    public event EventHandler<DownloadErrorEvent>? DownloadFailed;
    public event EventHandler<string>? StatusChanged;
    public event EventHandler<string>? RawOutputReceived;

    public DownloaderClient(string? customBinaryPath = null, string? customScriptPath = null)
    {
        // 1. If explicit standalone executable provided
        if (!string.IsNullOrWhiteSpace(customBinaryPath) && File.Exists(customBinaryPath))
        {
            _executableOrPython = Path.GetFullPath(customBinaryPath);
            _scriptPath = null;
            return;
        }

        // 2. Check for packaged dist/downloader (.exe on Windows, executable on Linux/macOS)
        var binaryName = PlatformUtils.GetBinaryName("downloader");
        var baseDir = AppDomain.CurrentDomain.BaseDirectory;
        var relativeDistExe = Path.Combine(baseDir, binaryName);
        var projectDistExe = Path.GetFullPath(Path.Combine(baseDir, "..", "..", "..", "..", "..", "dist", binaryName));

        if (File.Exists(relativeDistExe))
        {
            _executableOrPython = relativeDistExe;
            _scriptPath = null;
            return;
        }

        if (File.Exists(projectDistExe))
        {
            _executableOrPython = projectDistExe;
            _scriptPath = null;
            return;
        }

        // 2.5. Check embedded resource (for single-file all-in-one executable distribution)
        TryExtractEmbeddedBackend(PlatformUtils.IsWindows ? "ffmpeg.exe" : "ffmpeg");
        TryExtractEmbeddedBackend(PlatformUtils.IsWindows ? "ffprobe.exe" : "ffprobe");

        var extractedPath = TryExtractEmbeddedBackend(binaryName);
        if (extractedPath != null && File.Exists(extractedPath))
        {
            _executableOrPython = extractedPath;
            _scriptPath = null;
            return;
        }

        // 3. Fallback to python/python3 + downloader.py
        _executableOrPython = PlatformUtils.ResolvePythonExecutable();
        var candidateScript = customScriptPath ?? Path.GetFullPath(Path.Combine(baseDir, "..", "..", "..", "..", "..", "downloader.py"));
        _scriptPath = File.Exists(candidateScript) ? candidateScript : "downloader.py";
    }

    /// <summary>
    /// Download a media URL with real-time JSON streaming events.
    /// </summary>
    public async Task<DownloadCompleteEvent> DownloadAsync(
        string url,
        DownloadOptions? options = null,
        CancellationToken cancellationToken = default)
    {
        options ??= new DownloadOptions();
        var arguments = new List<string>();

        if (_scriptPath != null)
        {
            arguments.Add($"\"{_scriptPath}\"");
        }

        arguments.Add("--json-stream");
        arguments.AddRange(options.BuildCliArguments());
        arguments.Add($"\"{url}\"");

        DownloadCompleteEvent? completedResult = null;
        string? failureMessage = null;
        var tcs = new TaskCompletionSource<DownloadCompleteEvent>(TaskCreationOptions.RunContinuationsAsynchronously);

        void OnLineReceived(string line)
        {
            if (string.IsNullOrWhiteSpace(line)) return;

            try
            {
                using var doc = JsonDocument.Parse(line);
                var root = doc.RootElement;
                if (root.TryGetProperty("event", out var eventProp))
                {
                    var eventName = eventProp.GetString();
                    switch (eventName)
                    {
                        case "progress":
                            var prog = JsonSerializer.Deserialize(line, DownloaderJsonContext.Default.DownloadProgressEvent);
                            if (prog != null)
                            {
                                ProgressChanged?.Invoke(this, prog);
                            }
                            return; // Suppress raw high-frequency JSON progress events from terminal output

                        case "postprocess":
                            StatusChanged?.Invoke(this, "Processing media container...");
                            RawOutputReceived?.Invoke(this, "[Processing] Merging audio and video tracks with FFmpeg...");
                            return;

                        case "complete":
                            completedResult = JsonSerializer.Deserialize(line, DownloaderJsonContext.Default.DownloadCompleteEvent);
                            if (completedResult != null)
                            {
                                DownloadCompleted?.Invoke(this, completedResult);
                                RawOutputReceived?.Invoke(this, $"[Complete] Download finished: {completedResult.Title ?? completedResult.Url}");
                            }
                            return;

                        case "error":
                            var errEvt = JsonSerializer.Deserialize(line, DownloaderJsonContext.Default.DownloadErrorEvent);
                            failureMessage = errEvt?.Error ?? "Unknown download error.";
                            if (errEvt != null)
                            {
                                DownloadFailed?.Invoke(this, errEvt);
                                RawOutputReceived?.Invoke(this, $"[Error] {failureMessage}");
                            }
                            return;
                    }
                }

                if (root.TryGetProperty("success", out var successProp))
                {
                    if (!successProp.GetBoolean() && root.TryGetProperty("error", out var errProp))
                    {
                        var errMsg = errProp.GetString() ?? "Operation failed.";
                        failureMessage ??= errMsg;
                        RawOutputReceived?.Invoke(this, $"[Error] {errMsg}");
                    }
                    return; // Suppress raw JSON CLI summary from terminal
                }
            }
            catch (JsonException)
            {
                // Non-JSON standard line (e.g. logger outputs, engine notices, ffmpeg output)
            }

            RawOutputReceived?.Invoke(this, line);
        }

        using var registration = cancellationToken.Register(() =>
        {
            Cancel();
            tcs.TrySetCanceled(cancellationToken);
        });

        int exitCode = await RunProcessAsync(arguments, OnLineReceived, cancellationToken);

        if (cancellationToken.IsCancellationRequested)
        {
            throw new OperationCanceledException(cancellationToken);
        }

        if (completedResult != null)
        {
            return completedResult;
        }

        throw new Exception(failureMessage ?? $"Download process exited with code {exitCode}.");
    }

    /// <summary>
    /// Fetch media metadata, title, uploader, duration, and thumbnail URL for a URL without downloading.
    /// </summary>
    public async Task<MediaMetadataModel?> GetMetadataAsync(
        string url,
        CancellationToken cancellationToken = default,
        string? cookiesFromBrowser = null,
        string? cookiesFile = null)
    {
        var arguments = new List<string>();
        if (_scriptPath != null) arguments.Add($"\"{_scriptPath}\"");
        if (!string.IsNullOrWhiteSpace(cookiesFromBrowser))
        {
            arguments.Add("--cookies-from-browser");
            arguments.Add(cookiesFromBrowser);
        }
        if (!string.IsNullOrWhiteSpace(cookiesFile))
        {
            arguments.Add("--cookies");
            arguments.Add($"\"{cookiesFile}\"");
        }
        arguments.Add("--metadata");
        arguments.Add($"\"{url}\"");
        arguments.Add("--json");

        var output = await RunProcessAndCaptureOutputAsync(arguments, cancellationToken);
        if (string.IsNullOrWhiteSpace(output)) return null;

        try
        {
            return JsonSerializer.Deserialize(output, DownloaderJsonContext.Default.MediaMetadataModel);
        }
        catch (JsonException)
        {
            return null;
        }
    }

    /// <summary>
    /// Inspect available formats for a given URL without downloading.
    /// </summary>
    public async Task<List<FormatInfoModel>> GetFormatsAsync(
        string url,
        CancellationToken cancellationToken = default,
        string? cookiesFromBrowser = null,
        string? cookiesFile = null)
    {
        var result = await InspectFormatsDetailedAsync(url, cancellationToken, cookiesFromBrowser, cookiesFile);
        return result.Formats;
    }

    /// <summary>
    /// Inspect available formats and profile lock notices for a given URL without downloading.
    /// </summary>
    public async Task<FormatInspectionResult> InspectFormatsDetailedAsync(
        string url,
        CancellationToken cancellationToken = default,
        string? cookiesFromBrowser = null,
        string? cookiesFile = null)
    {
        var arguments = new List<string>();
        if (_scriptPath != null) arguments.Add($"\"{_scriptPath}\"");
        if (!string.IsNullOrWhiteSpace(cookiesFromBrowser))
        {
            arguments.Add("--cookies-from-browser");
            arguments.Add(cookiesFromBrowser);
        }
        if (!string.IsNullOrWhiteSpace(cookiesFile))
        {
            arguments.Add("--cookies");
            arguments.Add($"\"{cookiesFile}\"");
        }
        arguments.Add("--formats");
        arguments.Add($"\"{url}\"");
        arguments.Add("--json");

        var output = await RunProcessAndCaptureOutputAsync(arguments, cancellationToken);

        try
        {
            using var doc = JsonDocument.Parse(output);
            var root = doc.RootElement;
            var formats = root.TryGetProperty("formats", out var formatsArray)
                ? JsonSerializer.Deserialize(formatsArray.GetRawText(), DownloaderJsonContext.Default.ListFormatInfoModel) ?? new()
                : new List<FormatInfoModel>();

            var profileLocked = root.TryGetProperty("profile_locked", out var lockedProp) && lockedProp.ValueKind == JsonValueKind.True;
            var profileNotice = root.TryGetProperty("profile_notice", out var noticeProp) && noticeProp.ValueKind == JsonValueKind.String
                ? noticeProp.GetString()
                : null;
            var profileId = root.TryGetProperty("profile_id", out var idProp) && idProp.ValueKind == JsonValueKind.String
                ? idProp.GetString()
                : null;
            var bio = root.TryGetProperty("bio", out var bioProp) && bioProp.ValueKind == JsonValueKind.String
                ? bioProp.GetString()
                : null;
            var isVerified = root.TryGetProperty("is_verified", out var verProp) && verProp.ValueKind == JsonValueKind.True;
            var profileInfo = root.TryGetProperty("profile_info", out var infoArr) && infoArr.ValueKind == JsonValueKind.Array
                ? JsonSerializer.Deserialize(infoArr.GetRawText(), DownloaderJsonContext.Default.ListProfileInfoItemModel) ?? new()
                : new List<ProfileInfoItemModel>();

            return new FormatInspectionResult
            {
                Formats = formats,
                ProfileLocked = profileLocked,
                ProfileNotice = profileNotice,
                ProfileId = profileId,
                Bio = bio,
                IsVerified = isVerified,
                ProfileInfo = profileInfo,
            };
        }
        catch (JsonException ex)
        {
            throw new Exception($"Failed to parse formats JSON: {ex.Message}\nOutput: {output}");
        }
    }

    /// <summary>
    /// Fetch download history records from the backend SQLite database.
    /// </summary>
    public async Task<List<HistoryRecordModel>> GetHistoryAsync(
        int limit = 50,
        string? search = null,
        CancellationToken cancellationToken = default)
    {
        var arguments = new List<string>();
        if (_scriptPath != null) arguments.Add($"\"{_scriptPath}\"");
        arguments.Add("--history");
        arguments.Add(limit.ToString());

        if (!string.IsNullOrWhiteSpace(search))
        {
            arguments.Add("--history-search");
            arguments.Add($"\"{search}\"");
        }

        arguments.Add("--json");

        var output = await RunProcessAndCaptureOutputAsync(arguments, cancellationToken);
        if (string.IsNullOrWhiteSpace(output)) return new();

        try
        {
            return JsonSerializer.Deserialize(output, DownloaderJsonContext.Default.ListHistoryRecordModel) ?? new();
        }
        catch (JsonException)
        {
            return new();
        }
    }

    /// <summary>
    /// Clear all records from the SQLite history database.
    /// </summary>
    public async Task<bool> ClearHistoryAsync(CancellationToken cancellationToken = default)
    {
        var arguments = new List<string>();
        if (_scriptPath != null) arguments.Add($"\"{_scriptPath}\"");
        arguments.Add("--history-clear");
        arguments.Add("--json");

        var output = await RunProcessAndCaptureOutputAsync(arguments, cancellationToken);
        return output.Contains("\"success\": true");
    }

    /// <summary>
    /// Search YouTube for videos matching a text query.
    /// </summary>
    public async Task<List<SearchResultModel>> SearchAsync(
        string query,
        int limit = 10,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(query))
        {
            return new();
        }

        var arguments = new List<string>();
        if (_scriptPath != null) arguments.Add($"\"{_scriptPath}\"");
        arguments.Add("--search");
        arguments.Add($"\"{query.Trim()}\"");
        arguments.Add("--search-limit");
        arguments.Add(Math.Clamp(limit, 1, 25).ToString());
        arguments.Add("--json");

        var output = await RunProcessAndCaptureOutputAsync(arguments, cancellationToken);
        if (string.IsNullOrWhiteSpace(output))
        {
            return new();
        }

        try
        {
            using var doc = JsonDocument.Parse(output);
            if (doc.RootElement.TryGetProperty("results", out var resultsEl) && resultsEl.ValueKind == JsonValueKind.Array)
            {
                var list = new List<SearchResultModel>();
                foreach (var el in resultsEl.EnumerateArray())
                {
                    list.Add(new SearchResultModel
                    {
                        Id = el.TryGetProperty("id", out var id) ? id.GetString() ?? "" : "",
                        Url = el.TryGetProperty("url", out var url) ? url.GetString() ?? "" : "",
                        Title = el.TryGetProperty("title", out var title) ? title.GetString() ?? "" : "",
                        Uploader = el.TryGetProperty("uploader", out var up) ? up.GetString() ?? "" : "",
                        Duration = el.TryGetProperty("duration", out var dur) && dur.ValueKind == JsonValueKind.Number ? dur.GetDouble() : null,
                        DurationString = el.TryGetProperty("duration_string", out var ds) ? ds.GetString() : null,
                        Thumbnail = el.TryGetProperty("thumbnail", out var th) ? th.GetString() : null,
                        ViewCount = el.TryGetProperty("view_count", out var vc) && vc.ValueKind == JsonValueKind.Number ? vc.GetInt64() : null,
                    });
                }
                return list;
            }
        }
        catch
        {
            // Parse error fallback
        }

        return new();
    }

    /// <summary>
    /// Download a public or cookie-authorized profile picture (accepts profile URL or platform:username).
    /// </summary>
    public async Task<string> DownloadProfilePictureAsync(
        string profileInput,
        string? outputDirectory = null,
        string? cookiesFromBrowser = null,
        string? cookiesFile = null,
        CancellationToken cancellationToken = default)
    {
        var arguments = new List<string>();
        if (_scriptPath != null) arguments.Add($"\"{_scriptPath}\"");
        if (!string.IsNullOrWhiteSpace(outputDirectory))
        {
            arguments.Add("--output");
            arguments.Add($"\"{outputDirectory}\"");
        }
        if (!string.IsNullOrWhiteSpace(cookiesFile))
        {
            arguments.Add("--cookies");
            arguments.Add($"\"{cookiesFile}\"");
        }
        else if (!string.IsNullOrWhiteSpace(cookiesFromBrowser))
        {
            arguments.Add("--cookies-from-browser");
            arguments.Add(cookiesFromBrowser);
        }
        arguments.Add("--profile");
        arguments.Add($"\"{profileInput}\"");
        arguments.Add("--json");

        var output = await RunProcessAndCaptureOutputAsync(arguments, cancellationToken);
        if (string.IsNullOrWhiteSpace(output))
        {
            throw new Exception("Backend returned no output while resolving profile picture.");
        }

        // Parse last JSON object in output (in case any diagnostic text preceded it)
        var jsonStart = output.LastIndexOf('{');
        var candidateJson = jsonStart >= 0 ? output[jsonStart..] : output;
        try
        {
            using var doc = JsonDocument.Parse(candidateJson);
            if (doc.RootElement.TryGetProperty("saved_profile", out var saved))
            {
                var path = saved.GetString();
                if (!string.IsNullOrWhiteSpace(path)) return path;
            }
            if (doc.RootElement.TryGetProperty("error", out var err))
            {
                throw new Exception(err.GetString() ?? "Profile picture download failed.");
            }
        }
        catch (JsonException) { }

        throw new Exception(output.Trim());
    }

    /// <summary>
    /// Download a specific discovered profile or cover image URL directly (from Inspect Streams).
    /// </summary>
    public async Task<string> DownloadDirectImageAsync(
        string imageUrl,
        string? sourceProfileUrl = null,
        string? outputDirectory = null,
        string? cookiesFromBrowser = null,
        string? cookiesFile = null,
        bool enhanceHd = false,
        CancellationToken cancellationToken = default)
    {
        var arguments = new List<string>();
        if (_scriptPath != null) arguments.Add($"\"{_scriptPath}\"");
        if (!string.IsNullOrWhiteSpace(outputDirectory))
        {
            arguments.Add("--output");
            arguments.Add($"\"{outputDirectory}\"");
        }
        if (!string.IsNullOrWhiteSpace(cookiesFile))
        {
            arguments.Add("--cookies");
            arguments.Add($"\"{cookiesFile}\"");
        }
        else if (!string.IsNullOrWhiteSpace(cookiesFromBrowser))
        {
            arguments.Add("--cookies-from-browser");
            arguments.Add(cookiesFromBrowser);
        }
        if (!string.IsNullOrWhiteSpace(sourceProfileUrl))
        {
            arguments.Add("--profile-source-url");
            arguments.Add($"\"{sourceProfileUrl}\"");
        }
        if (enhanceHd)
        {
            arguments.Add("--enhance-hd");
        }
        arguments.Add("--profile-image-url");
        arguments.Add($"\"{imageUrl}\"");
        arguments.Add("--json");

        var output = await RunProcessAndCaptureOutputAsync(arguments, cancellationToken);
        if (string.IsNullOrWhiteSpace(output))
        {
            throw new Exception("Backend returned no output while downloading image.");
        }

        var jsonStart = output.LastIndexOf('{');
        var candidateJson = jsonStart >= 0 ? output[jsonStart..] : output;
        try
        {
            using var doc = JsonDocument.Parse(candidateJson);
            if (doc.RootElement.TryGetProperty("saved_profile", out var saved))
            {
                var path = saved.GetString();
                if (!string.IsNullOrWhiteSpace(path)) return path;
            }
            if (doc.RootElement.TryGetProperty("error", out var err))
            {
                throw new Exception(err.GetString() ?? "Image download failed.");
            }
        }
        catch (JsonException) { }

        throw new Exception(output.Trim());
    }

    /// <summary>
    /// Cancel the active download process.
    /// </summary>
    public void Cancel()
    {
        lock (_lock)
        {
            if (_currentProcess != null && !_currentProcess.HasExited)
            {
                try
                {
                    _currentProcess.Kill(entireProcessTree: true);
                }
                catch { }
            }
        }
    }

    private async Task<int> RunProcessAsync(
        IEnumerable<string> arguments,
        Action<string> onOutputLine,
        CancellationToken cancellationToken)
    {
        var localAppDataDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "UniversalDownloader"
        );
        try
        {
            Directory.CreateDirectory(localAppDataDir);
        }
        catch { }

        var psi = new ProcessStartInfo
        {
            FileName = _executableOrPython,
            Arguments = string.Join(" ", arguments),
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
            WorkingDirectory = Directory.Exists(localAppDataDir) ? localAppDataDir : Path.GetTempPath(),
        };

        var logsDir = Path.Combine(localAppDataDir, "logs");
        try { Directory.CreateDirectory(logsDir); } catch { }
        psi.EnvironmentVariables["LOG_DIR"] = logsDir;

        var localBin = Path.Combine(localAppDataDir, "bin");
        if (Directory.Exists(localBin))
        {
            var curPath = psi.EnvironmentVariables.ContainsKey("PATH") ? psi.EnvironmentVariables["PATH"] : Environment.GetEnvironmentVariable("PATH") ?? "";
            psi.EnvironmentVariables["PATH"] = $"{localBin}{Path.PathSeparator}{curPath}";
        }

        using var process = new Process { StartInfo = psi, EnableRaisingEvents = true };

        lock (_lock)
        {
            _currentProcess = process;
        }

        process.OutputDataReceived += (s, e) =>
        {
            if (e.Data != null) onOutputLine(e.Data);
        };

        process.ErrorDataReceived += (s, e) =>
        {
            if (e.Data != null) RawOutputReceived?.Invoke(this, e.Data);
        };

        process.Start();
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();

        await process.WaitForExitAsync(cancellationToken);

        lock (_lock)
        {
            _currentProcess = null;
        }

        return process.ExitCode;
    }

    private static string? TryExtractEmbeddedBackend(string binaryName)
    {
        try
        {
            var asm = typeof(DownloaderClient).Assembly;
            var entryAsm = System.Reflection.Assembly.GetEntryAssembly();

            // Locate embedded binary resource matching binaryName
            var names = asm.GetManifestResourceNames();
            var resourceName = names.FirstOrDefault(n => n.EndsWith(binaryName, StringComparison.OrdinalIgnoreCase))
                ?? entryAsm?.GetManifestResourceNames().FirstOrDefault(n => n.EndsWith(binaryName, StringComparison.OrdinalIgnoreCase));

            if (resourceName == null) return null;

            using var resourceStream = asm.GetManifestResourceStream(resourceName)
                ?? entryAsm?.GetManifestResourceStream(resourceName);

            if (resourceStream == null) return null;

            var cacheDir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "UniversalDownloader",
                "bin"
            );
            Directory.CreateDirectory(cacheDir);
            var targetFile = Path.Combine(cacheDir, binaryName);
            var hashFile = targetFile + ".sha256";

            // Compute embedded resource SHA-256 so stale cached binaries are always refreshed
            string embeddedHash;
            using (var sha = System.Security.Cryptography.SHA256.Create())
            {
                embeddedHash = Convert.ToHexString(sha.ComputeHash(resourceStream));
            }
            resourceStream.Position = 0;

            if (File.Exists(targetFile) &&
                new FileInfo(targetFile).Length == resourceStream.Length &&
                File.Exists(hashFile) &&
                string.Equals(File.ReadAllText(hashFile).Trim(), embeddedHash, StringComparison.OrdinalIgnoreCase))
            {
                return targetFile;
            }

            try
            {
                using (var fileStream = File.Create(targetFile))
                {
                    resourceStream.CopyTo(fileStream);
                }
                File.WriteAllText(hashFile, embeddedHash);
            }
            catch (IOException)
            {
                // Fallback to hash-tagged binary if previous instance holds a lock
                var ext = Path.GetExtension(binaryName);
                var stem = Path.GetFileNameWithoutExtension(binaryName);
                targetFile = Path.Combine(cacheDir, $"{stem}_{embeddedHash[..8]}{ext}");
                if (!File.Exists(targetFile))
                {
                    resourceStream.Position = 0;
                    using var fileStream = File.Create(targetFile);
                    resourceStream.CopyTo(fileStream);
                }
            }

            if (OperatingSystem.IsLinux() || OperatingSystem.IsMacOS())
            {
                try
                {
                    File.SetUnixFileMode(
                        targetFile,
                        UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute |
                        UnixFileMode.GroupRead | UnixFileMode.GroupExecute |
                        UnixFileMode.OtherRead | UnixFileMode.OtherExecute
                    );
                }
                catch
                {
                    try
                    {
                        using var chmod = Process.Start("chmod", $"+x \"{targetFile}\"");
                        chmod?.WaitForExit(2000);
                    }
                    catch { }
                }
            }

            return targetFile;
        }
        catch
        {
            return null;
        }
    }

    private async Task<string> RunProcessAndCaptureOutputAsync(
        IEnumerable<string> arguments,
        CancellationToken cancellationToken)
    {
        var lines = new System.Collections.Concurrent.ConcurrentQueue<string>();
        await RunProcessAsync(arguments, line => lines.Enqueue(line), cancellationToken);
        return string.Join(Environment.NewLine, lines).Trim();
    }
}
