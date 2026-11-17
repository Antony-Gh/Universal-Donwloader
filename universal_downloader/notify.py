"""Desktop notifications and audio alert cues for download completions."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from typing import Optional

LOGGER = logging.getLogger("universal_downloader")


def send_notification(
    title: str,
    message: str,
    sound: bool = True,
) -> bool:
    """Send desktop notification and audio cue across platforms."""
    # Audio cue on Windows
    if sound and sys.platform.startswith("win"):
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            pass

    # Windows Toast Notification via PowerShell
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

    return False
