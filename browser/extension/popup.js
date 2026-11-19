"use strict";

const NATIVE_HOST = "com.universaldownloader.coapp";

const urlInput = document.getElementById("urlInput");
const hostBadge = document.getElementById("hostBadge");
const statusText = document.getElementById("statusText");
const streamList = document.getElementById("streamList");

function setStatus(msg) {
  statusText.textContent = msg;
}

function checkNativeHost() {
  try {
    chrome.runtime.sendNativeMessage(NATIVE_HOST, { action: "ping" }, (resp) => {
      if (chrome.runtime.lastError || !resp || !resp.ok) {
        hostBadge.textContent = "Protocol Mode";
      } else {
        hostBadge.textContent = "CoApp v" + (resp.version || "Ready");
      }
    });
  } catch (_e) {
    hostBadge.textContent = "Protocol Mode";
  }
}

function triggerDownload(targetUrl, audioOnly) {
  const url = (targetUrl || urlInput.value || "").trim();
  if (!url) {
    setStatus("Please enter or select a media URL.");
    return;
  }
  setStatus(audioOnly ? "Sending MP3 request..." : "Sending Video request...");

  try {
    chrome.runtime.sendNativeMessage(
      NATIVE_HOST,
      {
        action: "download",
        url: url,
        audio_only: Boolean(audioOnly),
        quality: audioOnly ? "audio" : "best",
      },
      (resp) => {
        if (chrome.runtime.lastError || !resp || !resp.ok) {
          const suffix = audioOnly ? "#mp3" : "#mp4";
          window.open("downloader://" + encodeURI(url + suffix), "_blank");
          setStatus("Launched via downloader:// protocol.");
        } else {
          setStatus("Completed: " + (resp.title || url));
        }
      }
    );
  } catch (_err) {
    const suffix = audioOnly ? "#mp3" : "#mp4";
    window.open("downloader://" + encodeURI(url + suffix), "_blank");
    setStatus("Launched via downloader:// protocol.");
  }
}

function sniffActiveTab() {
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    const tab = tabs && tabs[0];
    if (!tab || !tab.id) {
      setStatus("No active tab available.");
      return;
    }
    chrome.scripting.executeScript(
      {
        target: { tabId: tab.id },
        func: () => {
          const found = new Set();
          document.querySelectorAll("video[src], audio[src], source[src]").forEach((el) => {
            const s = el.src || el.getAttribute("src");
            if (s && /^https?:\/\//i.test(s)) found.add(s);
          });
          document
            .querySelectorAll('meta[property^="og:video"], meta[property^="og:audio"], meta[name="twitter:player:stream"]')
            .forEach((el) => {
              const c = el.getAttribute("content");
              if (c && /^https?:\/\//i.test(c)) found.add(c);
            });
          const html = document.documentElement.innerHTML.replace(/\\\//g, "/");
          const re = /https?:\/\/[^\s"'<>\\)]+?\.(?:m3u8|mpd|mp4|webm|mp3|m4a|flac)(?:\?[^\s"'<>\\)]*)?/gi;
          let m;
          while ((m = re.exec(html)) !== null) {
            found.add(m[0]);
          }
          return Array.from(found);
        },
      },
      (results) => {
        streamList.innerHTML = "";
        const urls = (results && results[0] && results[0].result) || [];
        if (!urls.length) {
          setStatus("No embedded media streams detected on this tab.");
          return;
        }
        setStatus("Discovered " + urls.length + " stream(s) on active tab.");
        urls.slice(0, 12).forEach((u) => {
          const row = document.createElement("div");
          row.className = "stream-item";
          const span = document.createElement("span");
          span.className = "stream-url";
          span.textContent = u;
          const btn = document.createElement("button");
          btn.className = "btn-video";
          btn.style.flex = "0 0 auto";
          btn.style.padding = "4px 8px";
          btn.textContent = "Load";
          btn.addEventListener("click", () => {
            urlInput.value = u;
            setStatus("Loaded sniffed stream URL.");
          });
          row.appendChild(span);
          row.appendChild(btn);
          streamList.appendChild(row);
        });
      }
    );
  });
}

document.addEventListener("DOMContentLoaded", () => {
  checkNativeHost();
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    const tab = tabs && tabs[0];
    if (tab && tab.url && /^https?:\/\//i.test(tab.url)) {
      urlInput.value = tab.url;
    }
  });
  document.getElementById("downloadVideoBtn").addEventListener("click", () => triggerDownload(urlInput.value, false));
  document.getElementById("downloadMp3Btn").addEventListener("click", () => triggerDownload(urlInput.value, true));
  document.getElementById("sniffTabBtn").addEventListener("click", sniffActiveTab);
});
