// ==UserScript==
// @name         Universal Media Downloader — 1-Click Companion
// @namespace    https://github.com/Antony-Gh/Universal-Donwloader
// @version      1.0.0
// @description  Adds a 1-click Video / MP3 download button on YouTube, TikTok, Instagram, X/Twitter, and Facebook powered by Universal Media Downloader.
// @author       Antony-Gh
// @license      MIT
// @match        *://*.youtube.com/*
// @match        *://*.youtu.be/*
// @match        *://*.tiktok.com/*
// @match        *://*.instagram.com/*
// @match        *://*.twitter.com/*
// @match        *://*.x.com/*
// @match        *://*.facebook.com/*
// @grant        none
// ==/UserScript==

(function () {
    'use strict';

    if (document.getElementById('umd-companion-bar')) return;

    const bar = document.createElement('div');
    bar.id = 'umd-companion-bar';
    bar.style.cssText = [
        'position: fixed',
        'right: 18px',
        'bottom: 18px',
        'z-index: 2147483647',
        'display: flex',
        'gap: 6px',
        'padding: 6px 8px',
        'border-radius: 999px',
        'background: rgba(18, 22, 32, 0.92)',
        'backdrop-filter: blur(8px)',
        'box-shadow: 0 6px 22px rgba(0, 0, 0, 0.35)',
        'border: 1px solid rgba(255, 255, 255, 0.14)',
        'font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif',
        'font-size: 12px',
    ].join(';');

    function makeButton(label, bg, suffix) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.textContent = label;
        btn.style.cssText = [
            'border: none',
            'border-radius: 999px',
            'padding: 6px 12px',
            'cursor: pointer',
            'color: #ffffff',
            'font-weight: 600',
            'font-size: 12px',
            `background: ${bg}`,
            'transition: opacity 0.15s ease',
        ].join(';');
        btn.addEventListener('mouseenter', () => { btn.style.opacity = '0.88'; });
        btn.addEventListener('mouseleave', () => { btn.style.opacity = '1'; });
        btn.addEventListener('click', () => {
            const targetUrl = window.location.href + (suffix || '');
            window.location.href = 'downloader://' + encodeURI(targetUrl);
        });
        return btn;
    }

    bar.appendChild(makeButton('⬇ Video', '#2563eb', '#mp4'));
    bar.appendChild(makeButton('🎵 MP3', '#059669', '#mp3'));
    document.body.appendChild(bar);
})();
