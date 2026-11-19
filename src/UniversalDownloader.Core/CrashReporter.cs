using System;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;

namespace UniversalDownloader.Core;

/// <summary>
/// Anonymous crash reporting dispatcher for unhandled desktop exceptions into Neon database.
/// </summary>
public static class CrashReporter
{
    public static void RecordCrash(Exception ex, string clientPlatform = "Desktop")
    {
        Task.Run(() =>
        {
            try
            {
                var telemetryUrl = Environment.GetEnvironmentVariable("NEON_DATABASE_URL")
                                   ?? Environment.GetEnvironmentVariable("UD_TELEMETRY_URL");
                if (string.IsNullOrWhiteSpace(telemetryUrl)) return;

                var token = Environment.GetEnvironmentVariable("NEON_TELEMETRY_KEY");

                var errType = (ex.GetType().Name ?? "UnknownException").Replace("'", "''");
                var errMsg = (ex.Message ?? "").Replace("'", "''");
                var stack = (ex.StackTrace ?? "").Replace("'", "''");
                var osName = Environment.OSVersion.ToString().Replace("'", "''");

                var query = $"SELECT record_crash_report(" +
                            $"'00000000-0000-0000-0000-000000000000'::UUID, " +
                            $"'3.9.0', " +
                            $"'{clientPlatform.Replace("'", "''")}', " +
                            $"'{osName}', " +
                            $"'{errType}', " +
                            $"'{errMsg}', " +
                            $"'{stack}'" +
                            $");";

                var payload = new { query };
                var json = JsonSerializer.Serialize(payload);

                using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(4) };
                var content = new StringContent(json, Encoding.UTF8, "application/json");
                if (!string.IsNullOrWhiteSpace(token))
                {
                    client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", token);
                }
                client.PostAsync(telemetryUrl, content).GetAwaiter().GetResult();
            }
            catch
            {
                // Crash reporting must never throw or disrupt crash shutdown
            }
        });
    }
}
