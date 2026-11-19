"use strict";

const NATIVE_HOST = "com.universaldownloader.coapp";

function registerContextMenus() {
  if (!chrome.contextMenus) return;
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: "umd-download-video",
      title: "Download Video (MP4) with Universal Downloader",
      contexts: ["page", "link", "video", "audio"],
    });
    chrome.contextMenus.create({
      id: "umd-download-mp3",
      title: "Extract Audio (MP3) with Universal Downloader",
      contexts: ["page", "link", "video", "audio"],
    });
  });
}

chrome.runtime.onInstalled.addListener(registerContextMenus);
chrome.runtime.onStartup.addListener(registerContextMenus);

function dispatchDownload(targetUrl, audioOnly, tabId) {
  if (!targetUrl) return;
  const payload = {
    action: "download",
    url: targetUrl,
    audio_only: Boolean(audioOnly),
    quality: audioOnly ? "audio" : "best",
  };

  try {
    chrome.runtime.sendNativeMessage(NATIVE_HOST, payload, (response) => {
      if (chrome.runtime.lastError || !response || !response.ok) {
        // Fallback to downloader:// URI protocol handler
        const suffix = audioOnly ? "#mp3" : "#mp4";
        const protoUrl = "downloader://" + encodeURI(targetUrl + suffix);
        if (tabId) {
          chrome.tabs.update(tabId, { url: protoUrl });
        } else {
          chrome.tabs.create({ url: protoUrl });
        }
      }
    });
  } catch (_err) {
    const suffix = audioOnly ? "#mp3" : "#mp4";
    const protoUrl = "downloader://" + encodeURI(targetUrl + suffix);
    chrome.tabs.create({ url: protoUrl });
  }
}

chrome.contextMenus.onClicked.addListener((info, tab) => {
  const candidateUrl = info.srcUrl || info.linkUrl || info.pageUrl || (tab && tab.url) || "";
  if (!candidateUrl) return;

  if (info.menuItemId === "umd-download-mp3") {
    dispatchDownload(candidateUrl, true, tab ? tab.id : undefined);
  } else if (info.menuItemId === "umd-download-video") {
    dispatchDownload(candidateUrl, false, tab ? tab.id : undefined);
  }
});
