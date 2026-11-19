namespace UniversalDownloader.Core.Models;

/// <summary>
/// Configuration options to customize media download.
/// </summary>
public class DownloadOptions
{
    public string Quality { get; set; } = "best";
    public bool AudioOnly { get; set; }
    public string AudioFormat { get; set; } = "mp3";
    public string AudioQuality { get; set; } = "192k";

    public bool EmbedMetadata { get; set; } = true;
    public bool EmbedThumbnail { get; set; } = true;
    public bool WriteThumbnail { get; set; }

    public bool WriteSubs { get; set; }
    public bool EmbedSubs { get; set; }
    public string? SubLangs { get; set; }
    public bool AutoSubs { get; set; }

    public string? OutputDirectory { get; set; }
    public string? OutputTemplate { get; set; }
    public string? Organize { get; set; }
    public bool CleanFilenames { get; set; }

    public string? DownloadSections { get; set; }
    public string? StartTime { get; set; }
    public string? EndTime { get; set; }
    public string? RecordDuration { get; set; }
    public bool LiveFromStart { get; set; }
    public string? PlaylistItems { get; set; }
    public string? SponsorBlockRemove { get; set; }

    public string? PreferCodec { get; set; }
    public int ConcurrentFragments { get; set; } = 4;
    public int Concurrency { get; set; } = 1;

    public string? LimitRate { get; set; }
    public string? MinFilesize { get; set; }
    public string? MaxFilesize { get; set; }

    public string? Proxy { get; set; }
    public bool GeoBypass { get; set; }

    public string? CookiesFile { get; set; }
    public string? CookiesFromBrowser { get; set; }

    public bool NoHistory { get; set; }
    public bool Notify { get; set; }

    /// <summary>
    /// Builds CLI argument list corresponding to these options.
    /// </summary>
    public List<string> BuildCliArguments()
    {
        var args = new List<string>();

        if (!string.IsNullOrWhiteSpace(Quality) && Quality != "best")
        {
            args.Add("--quality");
            args.Add(Quality);
        }

        if (AudioOnly)
        {
            args.Add("--audio-only");
            if (!string.IsNullOrWhiteSpace(AudioFormat))
            {
                args.Add("--audio-format");
                args.Add(AudioFormat);
            }
            if (!string.IsNullOrWhiteSpace(AudioQuality))
            {
                args.Add("--audio-quality");
                args.Add(AudioQuality);
            }
        }

        if (EmbedMetadata) args.Add("--embed-metadata");
        if (EmbedThumbnail) args.Add("--embed-thumbnail");
        if (WriteThumbnail) args.Add("--write-thumbnail");

        if (WriteSubs) args.Add("--write-subs");
        if (EmbedSubs) args.Add("--embed-subs");
        if (!string.IsNullOrWhiteSpace(SubLangs))
        {
            args.Add("--sub-langs");
            args.Add(SubLangs);
        }
        if (AutoSubs) args.Add("--auto-subs");

        if (!string.IsNullOrWhiteSpace(OutputDirectory))
        {
            args.Add("--output");
            args.Add(OutputDirectory.Contains(' ') ? $"\"{OutputDirectory}\"" : OutputDirectory);
        }

        if (!string.IsNullOrWhiteSpace(OutputTemplate))
        {
            args.Add("--output-template");
            args.Add(OutputTemplate);
        }

        if (!string.IsNullOrWhiteSpace(Organize))
        {
            args.Add("--organize");
            args.Add(Organize);
        }

        if (CleanFilenames) args.Add("--clean-filenames");

        if (!string.IsNullOrWhiteSpace(DownloadSections))
        {
            args.Add("--download-sections");
            args.Add(DownloadSections);
        }

        if (!string.IsNullOrWhiteSpace(StartTime))
        {
            args.Add("--start-time");
            args.Add(StartTime);
        }

        if (!string.IsNullOrWhiteSpace(EndTime))
        {
            args.Add("--end-time");
            args.Add(EndTime);
        }

        if (!string.IsNullOrWhiteSpace(RecordDuration))
        {
            args.Add("--record-duration");
            args.Add(RecordDuration);
        }

        if (LiveFromStart) args.Add("--live-from-start");

        if (!string.IsNullOrWhiteSpace(PlaylistItems))
        {
            args.Add("--playlist-items");
            args.Add(PlaylistItems);
        }

        if (!string.IsNullOrWhiteSpace(SponsorBlockRemove))
        {
            args.Add("--sponsorblock-remove");
            args.Add(SponsorBlockRemove);
        }

        if (!string.IsNullOrWhiteSpace(PreferCodec))
        {
            args.Add("--prefer-codec");
            args.Add(PreferCodec);
        }

        if (ConcurrentFragments > 1)
        {
            args.Add("--concurrent-fragments");
            args.Add(ConcurrentFragments.ToString());
        }

        if (!string.IsNullOrWhiteSpace(LimitRate))
        {
            args.Add("--limit-rate");
            args.Add(LimitRate);
        }

        if (!string.IsNullOrWhiteSpace(Proxy))
        {
            args.Add("--proxy");
            args.Add(Proxy);
        }

        if (GeoBypass) args.Add("--geo-bypass");
        if (NoHistory) args.Add("--no-history");
        if (Notify) args.Add("--notify");

        if (!string.IsNullOrWhiteSpace(CookiesFile))
        {
            args.Add("--cookies");
            args.Add(CookiesFile.Contains(' ') ? $"\"{CookiesFile}\"" : CookiesFile);
        }

        if (!string.IsNullOrWhiteSpace(CookiesFromBrowser))
        {
            args.Add("--cookies-from-browser");
            args.Add(CookiesFromBrowser);
        }

        return args;
    }
}
