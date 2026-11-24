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
    chrome.contextMenus.create({
      id: "umd-open-in-app",
      title: "Open in Universal Downloader App",
      contexts: ["page", "link", "video", "audio"],
    });
  });
}

chrome.runtime.onInstalled.addListener(registerContextMenus);
chrome.runtime.onStartup.addListener(registerContextMenus);

function getCookiesForUrl(url, callback) {
  if (!chrome.cookies) {
    callback([]);
    return;
  }
  try {
    chrome.cookies.getAll({ url: url }, (cookies) => {
      if (chrome.runtime.lastError || !cookies) {
        callback([]);
      } else {
        const mapped = cookies.map((c) => ({
          domain: c.domain,
          path: c.path,
          secure: c.secure,
          expirationDate: c.expirationDate,
          name: c.name,
          value: c.value,
        }));
        callback(mapped);
      }
    });
  } catch (_e) {
    callback([]);
  }
}

function dispatchDownload(targetUrl, audioOnly, tabId) {
  if (!targetUrl) return;
  getCookiesForUrl(targetUrl, (cookies) => {
    const payload = {
      action: "download",
      url: targetUrl,
      audio_only: Boolean(audioOnly),
      quality: audioOnly ? "audio" : "best",
      cookies: cookies && cookies.length > 0 ? cookies : undefined,
    };

    try {
      chrome.runtime.sendNativeMessage(NATIVE_HOST, payload, (response) => {
        if (chrome.runtime.lastError || !response || !response.ok) {
          // Fallback to udloader:// URI protocol handler
          const suffix = audioOnly ? "#mp3" : "#mp4";
          const protoUrl = "udloader://" + encodeURI(targetUrl + suffix);
          if (tabId) {
            chrome.tabs.update(tabId, { url: protoUrl });
          } else {
            chrome.tabs.create({ url: protoUrl });
          }
        }
      });
    } catch (_err) {
      const suffix = audioOnly ? "#mp3" : "#mp4";
      const protoUrl = "udloader://" + encodeURI(targetUrl + suffix);
      chrome.tabs.create({ url: protoUrl });
    }
  });
}

function dispatchOpenInApp(targetUrl, tabId) {
  if (!targetUrl) return;
  getCookiesForUrl(targetUrl, (cookies) => {
    const payload = {
      action: "open_in_gui",
      url: targetUrl,
      cookies: cookies && cookies.length > 0 ? cookies : undefined,
    };

    try {
      chrome.runtime.sendNativeMessage(NATIVE_HOST, payload, (response) => {
        if (chrome.runtime.lastError || !response || !response.ok || response.delivered === "fallback_needed") {
          const protoUrl = "udloader://" + encodeURI(targetUrl);
          if (tabId) {
            chrome.tabs.update(tabId, { url: protoUrl });
          } else {
            chrome.tabs.create({ url: protoUrl });
          }
        }
      });
    } catch (_err) {
      const protoUrl = "udloader://" + encodeURI(targetUrl);
      chrome.tabs.create({ url: protoUrl });
    }
  });
}

chrome.contextMenus.onClicked.addListener((info, tab) => {
  const candidateUrl = info.srcUrl || info.linkUrl || info.pageUrl || (tab && tab.url) || "";
  if (!candidateUrl) return;

  if (info.menuItemId === "umd-download-mp3") {
    dispatchDownload(candidateUrl, true, tab ? tab.id : undefined);
  } else if (info.menuItemId === "umd-download-video") {
    dispatchDownload(candidateUrl, false, tab ? tab.id : undefined);
  } else if (info.menuItemId === "umd-open-in-app") {
    dispatchOpenInApp(candidateUrl, tab ? tab.id : undefined);
  }
});

chrome.runtime.onMessage.addListener((req, sender, sendResponse) => {
  if (req && req.action === "open_in_app" && req.url) {
    dispatchOpenInApp(req.url, sender && sender.tab ? sender.tab.id : undefined);
    sendResponse({ ok: true });
    return true;
  }
});
