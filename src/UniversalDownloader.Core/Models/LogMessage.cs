using System;

namespace UniversalDownloader.Core.Models;

public enum LogSeverity
{
    Info,
    Warning,
    Error,
    Success,
    Debug
}

public class LogMessage
{
    public string Timestamp { get; set; } = string.Empty;
    public string Message { get; set; } = string.Empty;
    public LogSeverity Severity { get; set; } = LogSeverity.Info;

    public string FormattedText => $"[{Timestamp}] {Message}";

    public string ColorHex => Severity switch
    {
        LogSeverity.Error => "#EF4444",    // Red
        LogSeverity.Warning => "#F59E0B",  // Orange / Amber
        LogSeverity.Success => "#10B981",  // Green
        LogSeverity.Debug => "#9CA3AF",    // Cool Gray
        _ => "#38BDF8"                     // Cyan / Sky Blue
    };

    public static LogMessage Create(string rawMessage)
    {
        var timestamp = DateTime.Now.ToString("HH:mm:ss");
        var severity = Classify(rawMessage);
        return new LogMessage
        {
            Timestamp = timestamp,
            Message = rawMessage,
            Severity = severity
        };
    }

    public static LogSeverity Classify(string message)
    {
        var lower = message.ToLowerInvariant();
        if (lower.Contains("error") || lower.Contains("fail") || lower.Contains("exception") || lower.Contains("traceback"))
            return LogSeverity.Error;
        if (lower.Contains("warning") || lower.Contains("warn") || lower.Contains("retry") || lower.Contains("skipped") || lower.Contains("retrying"))
            return LogSeverity.Warning;
        if (lower.Contains("finished") || lower.Contains("complete") || lower.Contains("success") || lower.Contains("✓") || lower.Contains("100%") || lower.Contains("ready at"))
            return LogSeverity.Success;
        if (lower.Contains("debug"))
            return LogSeverity.Debug;
        return LogSeverity.Info;
    }
}
