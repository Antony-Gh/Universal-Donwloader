using System.Text.Json.Serialization;
using UniversalDownloader.Core.Models;

namespace UniversalDownloader.Core;

/// <summary>
/// Compile-time source-generated System.Text.Json context for zero-reflection, AOT/trim-safe IPC & settings serialization.
/// </summary>
[JsonSourceGenerationOptions(WriteIndented = true, PropertyNameCaseInsensitive = true)]
[JsonSerializable(typeof(DownloadProgressEvent))]
[JsonSerializable(typeof(DownloadCompleteEvent))]
[JsonSerializable(typeof(DownloadErrorEvent))]
[JsonSerializable(typeof(MediaMetadataModel))]
[JsonSerializable(typeof(PlaylistEntryModel))]
[JsonSerializable(typeof(List<PlaylistEntryModel>))]
[JsonSerializable(typeof(FormatInfoModel))]
[JsonSerializable(typeof(List<FormatInfoModel>))]
[JsonSerializable(typeof(HistoryRecordModel))]
[JsonSerializable(typeof(List<HistoryRecordModel>))]
[JsonSerializable(typeof(UserSettings))]
public partial class DownloaderJsonContext : JsonSerializerContext
{
}
