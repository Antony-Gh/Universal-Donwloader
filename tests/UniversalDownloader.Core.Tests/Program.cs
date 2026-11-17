using System.Text.Json;
using UniversalDownloader.Core;
using UniversalDownloader.Core.Models;

int passed = 0;
int failed = 0;

void RunTest(string name, Action test)
{
    try
    {
        test();
        Console.WriteLine($"  [PASS] {name}");
        passed++;
    }
    catch (Exception ex)
    {
        Console.Error.WriteLine($"  [FAIL] {name}: {ex.Message}");
        failed++;
    }
}

void AssertEqual<T>(T expected, T actual, string? msg = null)
{
    if (!EqualityComparer<T>.Default.Equals(expected, actual))
        throw new Exception($"{msg ?? "Assertion failed"}: expected '{expected}', got '{actual}'.");
}

void AssertTrue(bool condition, string msg)
{
    if (!condition) throw new Exception(msg);
}

Console.WriteLine("=== UniversalDownloader.Core Unit Tests ===");

RunTest("UpdateChecker.NormalizeVersion strips v prefix and prerelease suffix", () =>
{
    AssertEqual("1.5.0", UpdateChecker.NormalizeVersion("v1.5.0"));
    AssertEqual("2.0.1", UpdateChecker.NormalizeVersion("V2.0.1-beta.1"));
});

RunTest("UpdateChecker.CompareVersions orders semantic versions accurately", () =>
{
    AssertTrue(UpdateChecker.CompareVersions("1.6.0", "1.5.0") > 0, "1.6.0 > 1.5.0");
    AssertTrue(UpdateChecker.CompareVersions("1.5.0", "1.5.0") == 0, "1.5.0 == 1.5.0");
    AssertTrue(UpdateChecker.CompareVersions("1.4.9", "1.5.0") < 0, "1.4.9 < 1.5.0");
    AssertTrue(UpdateChecker.CompareVersions("2.0", "1.9.9") > 0, "2.0 > 1.9.9");
});

RunTest("UpdateChecker reads shared app_config.json assembly metadata", () =>
{
    AssertTrue(!string.IsNullOrWhiteSpace(UpdateChecker.RepoOwner), "RepoOwner populated");
    AssertTrue(!string.IsNullOrWhiteSpace(UpdateChecker.RepoName), "RepoName populated");
    AssertTrue(UpdateChecker.AppVersionCode >= 100, "AppVersionCode >= 100");
});

RunTest("DownloadOptions.BuildCliArguments builds cookies, clip, playlist, and sponsorblock flags", () =>
{
    var opts = new DownloadOptions
    {
        Quality = "1080p",
        PreferCodec = "h264",
        ConcurrentFragments = 8,
        OutputDirectory = @"C:\My Videos",
        CookiesFile = @"C:\My Folder\cookies.txt",
        StartTime = "00:00:30",
        EndTime = "00:02:00",
        PlaylistItems = "1,3-5",
        SponsorBlockRemove = "sponsor,intro",
    };

    var args = opts.BuildCliArguments();
    AssertTrue(args.Contains("--quality") && args.Contains("1080p"), "quality flag");
    AssertTrue(args.Contains("--prefer-codec") && args.Contains("h264"), "codec flag");
    AssertTrue(args.Contains("--concurrent-fragments") && args.Contains("8"), "fragments flag");
    AssertTrue(args.Contains("\"C:\\My Videos\""), "quoted output dir with space");
    AssertTrue(args.Contains("\"C:\\My Folder\\cookies.txt\""), "quoted cookies path with space");
    AssertTrue(args.Contains("--start-time") && args.Contains("00:00:30"), "start-time flag");
    AssertTrue(args.Contains("--end-time") && args.Contains("00:02:00"), "end-time flag");
    AssertTrue(args.Contains("--playlist-items") && args.Contains("1,3-5"), "playlist-items flag");
    AssertTrue(args.Contains("--sponsorblock-remove") && args.Contains("sponsor,intro"), "sponsorblock flag");
});

RunTest("UserSettings saves and reloads cleanly via source-generated JSON", () =>
{
    var tmpPath = Path.Combine(Path.GetTempPath(), $"ud_settings_test_{Guid.NewGuid():N}.json");
    try
    {
        var original = new UserSettings
        {
            QualityIndex = 2,
            CodecIndex = 1,
            ConcurrentFragments = 12,
            OutputDirectory = @"D:\Media",
            EmbedMetadata = false,
            EmbedSubs = true,
            CookiesBrowserIndex = 3,
            SponsorBlockEnabled = true,
        };
        original.Save(tmpPath);

        var loaded = UserSettings.Load(tmpPath);
        AssertEqual(2, loaded.QualityIndex);
        AssertEqual(1, loaded.CodecIndex);
        AssertEqual(12, loaded.ConcurrentFragments);
        AssertEqual(@"D:\Media", loaded.OutputDirectory);
        AssertEqual(false, loaded.EmbedMetadata);
        AssertEqual(true, loaded.EmbedSubs);
        AssertEqual(3, loaded.CookiesBrowserIndex);
        AssertEqual(true, loaded.SponsorBlockEnabled);
    }
    finally
    {
        if (File.Exists(tmpPath)) File.Delete(tmpPath);
    }
});

RunTest("DownloaderJsonContext deserializes MediaMetadataModel and DownloadProgressEvent", () =>
{
    var metaJson = """{"url":"https://youtu.be/abc","platform":"youtube","title":"Demo Video","uploader":"Tester","duration":125,"view_count":1500000}""";
    var meta = JsonSerializer.Deserialize(metaJson, DownloaderJsonContext.Default.MediaMetadataModel);
    AssertTrue(meta != null, "meta deserialized");
    AssertEqual("Demo Video", meta!.Title);
    AssertEqual("2:05", meta.DurationFormatted);

    var progJson = """{"event":"progress","status":"downloading","downloaded_bytes":5242880,"total_bytes":10485760,"percent":50.0,"speed":1048576,"eta":5}""";
    var prog = JsonSerializer.Deserialize(progJson, DownloaderJsonContext.Default.DownloadProgressEvent);
    AssertTrue(prog != null, "progress deserialized");
    AssertEqual(50.0, prog!.Percent);
});

RunTest("LogMessage.Classify assigns expected severity colors", () =>
{
    AssertEqual(LogSeverity.Error, LogMessage.Classify("[Error] Network timeout"));
    AssertEqual(LogSeverity.Warning, LogMessage.Classify("WARNING: Retrying request"));
    AssertEqual(LogSeverity.Success, LogMessage.Classify("[Complete] Download finished"));
    AssertEqual(LogSeverity.Info, LogMessage.Classify("Connecting to host..."));
});

RunTest("PlatformUtils.FormatBytes formats human-readable sizes", () =>
{
    AssertEqual("0 B", PlatformUtils.FormatBytes(0));
    AssertEqual("1.0 KB", PlatformUtils.FormatBytes(1024));
    AssertEqual("1.0 MB", PlatformUtils.FormatBytes(1024 * 1024));
});

RunTest("QueueItemModel updates status badge and progress clamping", () =>
{
    var item = new QueueItemModel { Url = "https://example.com/v" };
    AssertEqual("https://example.com/v", item.Title);
    item.Progress = 140.0;
    AssertEqual(100.0, item.Progress);
    item.Status = QueueItemStatus.Completed;
    AssertEqual("COMPLETED", item.StatusBadgeText);
    AssertEqual("#10B981", item.StatusColorHex);
});

Console.WriteLine($"\nResult: {passed} passed, {failed} failed.");
return failed == 0 ? 0 : 1;
