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

            RawOutputReceived?.Invoke(this, line);

            try
            {
                using var doc = JsonDocument.Parse(line);
                var root = doc.RootElement;
                if (!root.TryGetProperty("event", out var eventProp)) return;

                var eventName = eventProp.GetString();
                switch (eventName)
                {
                    case "progress":
                        var prog = JsonSerializer.Deserialize<DownloadProgressEvent>(line);
                        if (prog != null)
                        {
                            ProgressChanged?.Invoke(this, prog);
                        }
                        break;

                    case "postprocess":
                        StatusChanged?.Invoke(this, "Processing media container...");
                        break;

                    case "complete":
                        completedResult = JsonSerializer.Deserialize<DownloadCompleteEvent>(line);
                        if (completedResult != null)
                        {
                            DownloadCompleted?.Invoke(this, completedResult);
                        }
                        break;

                    case "error":
                        var errEvt = JsonSerializer.Deserialize<DownloadErrorEvent>(line);
                        failureMessage = errEvt?.Error ?? "Unknown download error.";
                        if (errEvt != null)
                        {
                            DownloadFailed?.Invoke(this, errEvt);
                        }
                        break;
                }
            }
            catch (JsonException)
            {
                // Non-JSON standard line (e.g. logger outputs)
            }
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
    /// Inspect available formats for a given URL without downloading.
    /// </summary>
    public async Task<List<FormatInfoModel>> GetFormatsAsync(string url, CancellationToken cancellationToken = default)
    {
        var arguments = new List<string>();
        if (_scriptPath != null) arguments.Add($"\"{_scriptPath}\"");
        arguments.Add("--formats");
        arguments.Add($"\"{url}\"");
        arguments.Add("--json");

        var output = await RunProcessAndCaptureOutputAsync(arguments, cancellationToken);

        try
        {
            using var doc = JsonDocument.Parse(output);
            if (doc.RootElement.TryGetProperty("formats", out var formatsArray))
            {
                return JsonSerializer.Deserialize<List<FormatInfoModel>>(formatsArray.GetRawText()) ?? new();
            }
        }
        catch (JsonException ex)
        {
            throw new Exception($"Failed to parse formats JSON: {ex.Message}\nOutput: {output}");
        }

        return new();
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
            return JsonSerializer.Deserialize<List<HistoryRecordModel>>(output) ?? new();
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
    /// Download a public profile picture.
    /// </summary>
    public async Task<string?> DownloadProfilePictureAsync(string profileInput, CancellationToken cancellationToken = default)
    {
        var arguments = new List<string>();
        if (_scriptPath != null) arguments.Add($"\"{_scriptPath}\"");
        arguments.Add("--profile");
        arguments.Add($"\"{profileInput}\"");
        arguments.Add("--json");

        var output = await RunProcessAndCaptureOutputAsync(arguments, cancellationToken);
        try
        {
            using var doc = JsonDocument.Parse(output);
            if (doc.RootElement.TryGetProperty("saved_profile", out var saved))
            {
                return saved.GetString();
            }
        }
        catch (JsonException) { }

        return null;
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
        var psi = new ProcessStartInfo
        {
            FileName = _executableOrPython,
            Arguments = string.Join(" ", arguments),
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };

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

            // Locate embedded binary resource
            var names = asm.GetManifestResourceNames();
            var resourceName = names.FirstOrDefault(n => n.EndsWith("downloader.exe", StringComparison.OrdinalIgnoreCase) || n.EndsWith("downloader", StringComparison.OrdinalIgnoreCase))
                ?? entryAsm?.GetManifestResourceNames().FirstOrDefault(n => n.EndsWith("downloader.exe", StringComparison.OrdinalIgnoreCase) || n.EndsWith("downloader", StringComparison.OrdinalIgnoreCase));

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

            if (File.Exists(targetFile) && new FileInfo(targetFile).Length == resourceStream.Length)
            {
                return targetFile;
            }

            using (var fileStream = File.Create(targetFile))
            {
                resourceStream.CopyTo(fileStream);
            }

            if (!PlatformUtils.IsWindows)
            {
                try
                {
                    var chmod = Process.Start("chmod", $"+x \"{targetFile}\"");
                    chmod?.WaitForExit();
                }
                catch { }
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
        var lines = new List<string>();
        await RunProcessAsync(arguments, line => lines.Add(line), cancellationToken);
        return string.Join(Environment.NewLine, lines).Trim();
    }
}
