using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

namespace UniversalDownloader.Core.Media;

/// <summary>
/// Lightweight in-app media player for audio and video files and streams.
/// Uses native OS multimedia subsystems on Windows (MCI / winmm) for local files,
/// with seamless automatic fallback to bundled/system ffplay for WebM/MKV/Opus and direct streams.
/// </summary>
public sealed class MiniMediaPlayer : IDisposable
{
    [DllImport("winmm.dll", EntryPoint = "mciSendStringA", CharSet = CharSet.Ansi)]
    private static extern int MciSendString(string command, StringBuilder? returnString, int returnLength, IntPtr hwndCallback);

    private const string Alias = "UmdMiniPlayer";
    private readonly bool _isWindows;
    private bool _isLoaded;
    private bool _isPlaying;
    private bool _isProcessPlayback;
    private Process? _playerProcess;
    private double _durationSeconds;
    private string? _currentFilePath;
    private int _currentVolume = 85;

    public bool IsPlaying => _isPlaying;
    public bool IsLoaded => _isLoaded;
    public bool IsProcessPlayback => _isProcessPlayback;
    public double DurationSeconds => _durationSeconds;
    public string? CurrentFilePath => _currentFilePath;

    public MiniMediaPlayer()
    {
        _isWindows = RuntimeInformation.IsOSPlatform(OSPlatform.Windows);
    }

    /// <summary>
    /// Find ffplay binary if installed on the system or in the application bin directory.
    /// </summary>
    public static string? FindFfplay()
    {
        var exeName = OperatingSystem.IsWindows() ? "ffplay.exe" : "ffplay";

        // 1. Check local bin directory
        var localBin = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "UniversalDownloader",
            "bin",
            exeName
        );
        if (File.Exists(localBin)) return localBin;

        // 2. Check standard Windows ffmpeg paths
        if (OperatingSystem.IsWindows())
        {
            var candidates = new[]
            {
                @"C:\ffmpeg\bin\ffplay.exe",
                @"C:\Program Files\ffmpeg\bin\ffplay.exe",
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "scoop", "shims", "ffplay.exe"),
            };
            foreach (var c in candidates)
            {
                if (File.Exists(c)) return c;
            }
        }

        // 3. Search PATH
        var pathEnv = Environment.GetEnvironmentVariable("PATH") ?? "";
        foreach (var dir in pathEnv.Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries))
        {
            try
            {
                var candidate = Path.Combine(dir.Trim(), exeName);
                if (File.Exists(candidate)) return candidate;
            }
            catch { }
        }

        return null;
    }

    /// <summary>
    /// Load a local media file or streaming URL for playback.
    /// </summary>
    public bool Load(string filePathOrUrl)
    {
        Close();

        if (string.IsNullOrWhiteSpace(filePathOrUrl))
            return false;

        bool isUrl = filePathOrUrl.StartsWith("http://", StringComparison.OrdinalIgnoreCase) ||
                     filePathOrUrl.StartsWith("https://", StringComparison.OrdinalIgnoreCase);

        if (!isUrl && !File.Exists(filePathOrUrl))
            return false;

        _currentFilePath = isUrl ? filePathOrUrl : Path.GetFullPath(filePathOrUrl);

        if (isUrl)
        {
            _isLoaded = true;
            _isProcessPlayback = true;
            _durationSeconds = 0.0;
            return true;
        }

        if (_isWindows)
        {
            string ext = Path.GetExtension(_currentFilePath).ToLowerInvariant();
            // Native MCI supports mp3, mp4, wav, wma, avi
            bool isMciCandidate = ext is ".mp3" or ".wav" or ".wma" or ".mp4" or ".avi";

            if (isMciCandidate)
            {
                string shortPath = GetShortPath(_currentFilePath);
                int res = MciSendString($"open \"{shortPath}\" type mpegvideo alias {Alias}", null, 0, IntPtr.Zero);
                if (res != 0)
                {
                    res = MciSendString($"open \"{shortPath}\" alias {Alias}", null, 0, IntPtr.Zero);
                }

                if (res == 0)
                {
                    MciSendString($"set {Alias} time format milliseconds", null, 0, IntPtr.Zero);
                    _durationSeconds = QueryLengthMilliseconds() / 1000.0;
                    _isLoaded = true;
                    _isProcessPlayback = false;
                    SetVolume(_currentVolume);
                    return true;
                }
            }

            // Fallback to process playback (ffplay) for MKV, WebM, FLAC, Opus
            if (FindFfplay() != null)
            {
                _isLoaded = true;
                _isProcessPlayback = true;
                _durationSeconds = 0.0;
                return true;
            }

            return false;
        }

        // POSIX simulation/fallback
        _isLoaded = true;
        _durationSeconds = 120.0;
        return true;
    }

    public bool Play()
    {
        if (!_isLoaded || string.IsNullOrWhiteSpace(_currentFilePath)) return false;

        if (_isProcessPlayback)
        {
            var ffplay = FindFfplay();
            if (ffplay == null) return false;

            StopProcess();
            try
            {
                var isVideo = _currentFilePath.Contains(".mp4", StringComparison.OrdinalIgnoreCase) ||
                              _currentFilePath.Contains(".webm", StringComparison.OrdinalIgnoreCase) ||
                              _currentFilePath.Contains(".mkv", StringComparison.OrdinalIgnoreCase) ||
                              _currentFilePath.Contains(".mov", StringComparison.OrdinalIgnoreCase);

                var args = isVideo
                    ? $"-autoexit -volume {_currentVolume} -window_title \"Media Preview\" \"{_currentFilePath}\""
                    : $"-autoexit -nodisp -volume {_currentVolume} \"{_currentFilePath}\"";

                var psi = new ProcessStartInfo
                {
                    FileName = ffplay,
                    Arguments = args,
                    UseShellExecute = false,
                    CreateNoWindow = !isVideo,
                };
                _playerProcess = Process.Start(psi);
                _isPlaying = _playerProcess != null && !_playerProcess.HasExited;
                return _isPlaying;
            }
            catch
            {
                return false;
            }
        }

        if (_isWindows)
        {
            int res = MciSendString($"play {Alias}", null, 0, IntPtr.Zero);
            _isPlaying = (res == 0);
            return _isPlaying;
        }

        _isPlaying = true;
        return true;
    }

    public bool Pause()
    {
        if (!_isLoaded) return false;

        if (_isProcessPlayback)
        {
            StopProcess();
            _isPlaying = false;
            return true;
        }

        if (_isWindows)
        {
            MciSendString($"pause {Alias}", null, 0, IntPtr.Zero);
            _isPlaying = false;
            return true;
        }

        _isPlaying = false;
        return true;
    }

    public bool Resume()
    {
        if (!_isLoaded) return false;

        if (_isProcessPlayback)
        {
            return Play();
        }

        if (_isWindows)
        {
            int res = MciSendString($"resume {Alias}", null, 0, IntPtr.Zero);
            _isPlaying = (res == 0);
            return _isPlaying;
        }

        _isPlaying = true;
        return true;
    }

    public bool Stop()
    {
        if (!_isLoaded) return false;

        if (_isProcessPlayback)
        {
            StopProcess();
            _isPlaying = false;
            return true;
        }

        if (_isWindows)
        {
            MciSendString($"stop {Alias}", null, 0, IntPtr.Zero);
            MciSendString($"seek {Alias} to 0", null, 0, IntPtr.Zero);
            _isPlaying = false;
            return true;
        }

        _isPlaying = false;
        return true;
    }

    public bool Seek(double seconds)
    {
        if (!_isLoaded || _isProcessPlayback) return false;

        double clamped = Math.Max(0, Math.Min(seconds, _durationSeconds));
        long ms = (long)(clamped * 1000.0);

        if (_isWindows)
        {
            int res = MciSendString($"seek {Alias} to {ms}", null, 0, IntPtr.Zero);
            if (_isPlaying)
            {
                MciSendString($"play {Alias}", null, 0, IntPtr.Zero);
            }
            return res == 0;
        }

        return true;
    }

    public void SetVolume(int volumePercent)
    {
        _currentVolume = Math.Clamp(volumePercent, 0, 100);
        if (!_isLoaded || _isProcessPlayback) return;

        int mciVolume = _currentVolume * 10; // MCI volume scale 0-1000
        if (_isWindows)
        {
            MciSendString($"setaudio {Alias} volume to {mciVolume}", null, 0, IntPtr.Zero);
        }
    }

    public double GetCurrentPositionSeconds()
    {
        if (!_isLoaded || _isProcessPlayback) return 0.0;

        if (_isWindows)
        {
            var sb = new StringBuilder(128);
            int res = MciSendString($"status {Alias} position", sb, sb.Capacity, IntPtr.Zero);
            if (res == 0 && long.TryParse(sb.ToString().Trim(), out long ms))
            {
                return ms / 1000.0;
            }
        }

        return 0.0;
    }

    private long QueryLengthMilliseconds()
    {
        if (!_isWindows) return 0;

        var sb = new StringBuilder(128);
        int res = MciSendString($"status {Alias} length", sb, sb.Capacity, IntPtr.Zero);
        if (res == 0 && long.TryParse(sb.ToString().Trim(), out long ms))
        {
            return ms;
        }

        return 0;
    }

    private void StopProcess()
    {
        if (_playerProcess != null)
        {
            try
            {
                if (!_playerProcess.HasExited)
                {
                    _playerProcess.Kill(entireProcessTree: true);
                }
            }
            catch { }
            finally
            {
                _playerProcess.Dispose();
                _playerProcess = null;
            }
        }
    }

    public void Close()
    {
        StopProcess();

        if (_isWindows)
        {
            MciSendString($"stop {Alias}", null, 0, IntPtr.Zero);
            MciSendString($"close {Alias}", null, 0, IntPtr.Zero);
        }

        _isLoaded = false;
        _isPlaying = false;
        _isProcessPlayback = false;
        _durationSeconds = 0.0;
        _currentFilePath = null;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Auto)]
    private static extern int GetShortPathName(string lpszLongPath, StringBuilder lpszShortPath, int cchBuffer);

    private static string GetShortPath(string path)
    {
        try
        {
            var sb = new StringBuilder(512);
            int len = GetShortPathName(path, sb, sb.Capacity);
            if (len > 0)
            {
                return sb.ToString();
            }
        }
        catch { }
        return path;
    }

    public void Dispose()
    {
        Close();
    }
}
