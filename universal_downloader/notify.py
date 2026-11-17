"""Desktop notifications and audio alert cues for download completions across Windows, Linux, and macOS."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from typing import Optional

LOGGER = logging.getLogger("universal_downloader")


def play_alert_sound() -> None:
    """Produce an audible completion cue across platforms."""
    if sys.platform.startswith("win"):
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
            return
        except Exception:
            pass
    elif sys.platform == "darwin":
        try:
            subprocess.Popen(["afplay", "/System/Library/Sounds/Glass.aiff"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except Exception:
            pass
    elif sys.platform.startswith("linux"):
        for player, sound_file in [
            ("paplay", "/usr/share/sounds/freedesktop/stereo/complete.oga"),
            ("aplay", "/usr/share/sounds/alsa/Front_Center.wav"),
        ]:
            if shutil.which(player) and os.path.isfile(sound_file):
                try:
                    subprocess.Popen([player, sound_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return
                except Exception:
                    pass

    # Universal terminal bell fallback
    try:
        sys.stdout.write("\a")
        sys.stdout.flush()
    except Exception:
        pass


def send_notification(
    title: str,
    message: str,
    sound: bool = True,
) -> bool:
    """Send desktop notification and audio cue across platforms."""
    if sound:
        play_alert_sound()

    # 1. Windows Toast Notification via PowerShell
    if sys.platform.startswith("win"):
        try:
            clean_title = title.replace("'", "''").replace('"', '')
            clean_msg = message.replace("'", "''").replace('"', '')
            ps_script = (
                f"[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null; "
                f"$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
                f"$texts = $xml.GetElementsByTagName('text'); "
                f"$null = $texts[0].AppendChild($xml.CreateTextNode('{clean_title}')); "
                f"$null = $texts[1].AppendChild($xml.CreateTextNode('{clean_msg}')); "
                f"$toast = [Windows.UI.Notifications.ToastNotification]::new($xml); "
                f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Universal Downloader').Show($toast);"
            )
            subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True
        except Exception as exc:
            LOGGER.debug("Could not display Windows toast: %s", exc)

    # 2. Linux Notification via notify-send (FreeDesktop standard)
    elif sys.platform.startswith("linux"):
        if shutil.which("notify-send"):
            try:
                subprocess.Popen(
                    ["notify-send", "--app-name=Universal Downloader", title, message],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return True
            except Exception as exc:
                LOGGER.debug("Could not display Linux notification via notify-send: %s", exc)

    # 3. macOS Notification via AppleScript
    elif sys.platform == "darwin":
        try:
            clean_title = title.replace('"', '\\"')
            clean_msg = message.replace('"', '\\"')
            osa_script = f'display notification "{clean_msg}" with title "{clean_title}"'
            subprocess.Popen(
                ["osascript", "-e", osa_script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception as exc:
            LOGGER.debug("Could not display macOS notification: %s", exc)

    return False
