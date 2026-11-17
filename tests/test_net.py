"""Tests for URL parsing, normalization, and platform/content detection."""

import pytest

from universal_downloader.models import ContentType, Platform
from universal_downloader.utils.net import (
    detect_content_type,
    detect_platform,
    detect_target,
    get_domain,
    normalize_tiktok_url,
    normalize_url,
)


def test_normalize_url():
    assert normalize_url("youtube.com/watch?v=123") == "https://youtube.com/watch?v=123"
    assert normalize_url("www.instagram.com/reel/abc/") == "https://www.instagram.com/reel/abc/"
    assert normalize_url("https://X.com/user/status/123") == "https://x.com/user/status/123"

    with pytest.raises(ValueError, match="URL is empty"):
        normalize_url("")

    with pytest.raises(ValueError, match="Only HTTP and HTTPS"):
        normalize_url("file:///etc/passwd")


def test_get_domain():
    assert get_domain("https://www.youtube.com/watch?v=abc") == "www.youtube.com"
    assert get_domain("https://b23.tv/xyz") == "b23.tv"
    assert get_domain("invalid-url") == ""


def test_detect_platform():
    assert detect_platform("https://www.youtube.com/watch?v=test") == Platform.YOUTUBE
    assert detect_platform("https://youtu.be/test") == Platform.YOUTUBE
    assert detect_platform("https://www.instagram.com/p/test/") == Platform.INSTAGRAM
    assert detect_platform("https://x.com/user/status/123") == Platform.TWITTER
    assert detect_platform("https://www.tiktok.com/@user/video/123") == Platform.TIKTOK
    assert detect_platform("https://b23.tv/xyz") == Platform.BILIBILI
    assert detect_platform("https://bsky.app/profile/user.bsky.social") == Platform.BLUESKY
    assert detect_platform("https://artist.bandcamp.com/track/song") == Platform.BANDCAMP
    assert detect_platform("https://www.loom.com/share/1234") == Platform.LOOM
    assert detect_platform("https://example.com/video.mp4") == Platform.UNKNOWN


def test_detect_content_type():
    assert detect_content_type("https://youtube.com/watch?v=abc", Platform.YOUTUBE) == ContentType.VIDEO
    assert detect_content_type("https://youtube.com/playlist?list=PL123", Platform.YOUTUBE) == ContentType.PLAYLIST
    assert detect_content_type("https://youtube.com/@ChannelName", Platform.YOUTUBE) == ContentType.PROFILE
    assert detect_content_type("https://instagram.com/p/C123/", Platform.INSTAGRAM) == ContentType.POST
    assert detect_content_type("https://instagram.com/reel/C123/", Platform.INSTAGRAM) == ContentType.VIDEO
    assert detect_content_type("https://instagram.com/username", Platform.INSTAGRAM) == ContentType.PROFILE
    assert detect_content_type("https://www.facebook.com/example.user", Platform.FACEBOOK) == ContentType.PROFILE
    assert detect_content_type("https://www.facebook.com/profile.php?id=1000123", Platform.FACEBOOK) == ContentType.PROFILE
    assert detect_content_type("https://www.facebook.com/reel/123456789", Platform.FACEBOOK) == ContentType.VIDEO
    assert detect_content_type("https://www.facebook.com/watch/?v=123456", Platform.FACEBOOK) == ContentType.VIDEO
    assert detect_content_type("https://soundcloud.com/artist/track", Platform.SOUNDCLOUD) == ContentType.AUDIO


def test_normalize_tiktok_url():
    url_with_tracking = "https://www.tiktok.com/@user/video/7123456789012345678?_r=1&_t=8W1234"
    cleaned = normalize_tiktok_url(url_with_tracking)
    assert cleaned == "https://www.tiktok.com/@user/video/7123456789012345678"


def test_detect_target():
    target = detect_target("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert target.platform == Platform.YOUTUBE
    assert target.content_type == ContentType.VIDEO
    assert target.is_profile_candidate is False
